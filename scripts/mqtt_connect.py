#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Minimal AWS IoT Device SDK for Python v2 MQTT 5 client (shared across sections).

This is the tiny device-plane client the provisioning sections use whenever a
device connects with a certificate and publishes telemetry — the first connect
in JITP/JITR, the permanent-certificate reconnect in the fleet flows, and the
endpoint-switch reconnect in Multi-Account Registration.

It intentionally stays small and self-contained (direct ``awscrt`` / ``awsiot``,
no shared helper) so a learner can read the whole "how do I open a mutual-TLS
MQTT connection?" story in one file.

Why MQTT 5
----------
This workshop standardises on **MQTT 5**. Every acknowledgement carries a
**reason code**, so the client can print *why* the broker refused an operation
instead of leaving you to infer it from a timeout. That is exactly what makes
the first-connect behaviour below legible rather than mysterious.

The very first connect right after provisioning is EXPECTED to fail: AWS IoT
Core registers the certificate and runs the provisioning template, then closes
that first connection. With MQTT 5 you can watch the CONNACK reason code change
from ``NOT_AUTHORIZED`` to accepted as registration completes.

**The same reason code can call for opposite responses.** Here,
``NOT_AUTHORIZED`` on the first attempt is expected and the right answer is to
keep retrying, because the certificate is still being activated. In the Module 6
rotation agent the same code means the replacement certificate is unusable and
the right answer is to stop immediately and fall back. A reason code tells you
what happened; only the surrounding flow tells you what to do about it.

Usage:
    python3 ../scripts/mqtt_connect.py <endpoint> <clientId> \\
        <certFile> <keyFile> <caFile> <topic>
"""

import json
import os
import sys
import threading
import time
from concurrent.futures import Future

# --- Repository path wiring (import i18n framework) ----------------------
# mqtt_connect.py lives in scripts/, so REPO_ROOT is two dirnames up (the repo
# root, which contains i18n/ as a sibling of scripts/).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "i18n"))

from awscrt import mqtt5  # noqa: E402
from awsiot import mqtt5_client_builder  # noqa: E402

from language_selector import get_language  # noqa: E402
from loader import load_messages  # noqa: E402

# --- i18n message catalog + resolver -------------------------------------
# Populated once at entry (see main()) via load_messages(). Loading is done
# INSIDE main(), never at import time: this module is also run standalone as a
# subprocess by every provisioning section, and get_language() may pop the
# interactive language menu when AWS_IOT_LANG is unset. Deferring the load keeps
# a bare ``import mqtt_connect`` side-effect-free (no menu, no catalog read). The
# wrapper below is the shared nested-capable convention documented in
# i18n/README.md: dotted keys walk the nested catalog, a missing key falls back
# to the key itself, and positional {} placeholders are filled via
# str.format(*args). It is defined per-script on purpose (NOT centralized in
# loader.py).
messages = {}


def get_message(key, *args):
    """Resolve a localized message (nested dotted keys) with positional formatting."""
    if "." in key:
        msg = messages
        for part in key.split("."):
            if isinstance(msg, dict) and part in msg:
                msg = msg[part]
            else:
                msg = key  # fall back to the raw key
                break
    else:
        msg = messages.get(key, key)
    if args and isinstance(msg, str):
        return msg.format(*args)
    return msg


def reason_code_name(reason_code):
    """Render an MQTT 5 reason code as ``NAME (0xHH)``, or ``-`` when absent.

    A failure below MQTT — DNS, TLS, a dropped socket — has no reason code at
    all, and that absence is itself the signal: the broker never answered.
    """
    if reason_code is None:
        return "-"
    name = getattr(reason_code, "name", str(reason_code))
    try:
        return f"{name} (0x{int(reason_code):02X})"
    except (TypeError, ValueError):
        return name


# How long to keep waiting for that first successful connect. The MQTT 5 client
# retries on its own, so this is a total budget rather than an attempt count.
FIRST_CONNECT_BUDGET_SEC = 90


def main():
    # Load the localized message catalog once, before any user-facing print.
    # (Done here, not at import time, so importing this module never triggers
    # the language selector — see the module note above.)
    global messages
    messages = load_messages("mqtt_connect", get_language())

    if len(sys.argv) < 7:
        print(get_message("usage"))
        sys.exit(2)

    endpoint, client_id, cert, key, ca, topic = sys.argv[1:7]

    connected = Future()
    stopped = threading.Event()

    def on_connection_success(data):
        """Lifecycle: CONNACK accepted."""
        connack = data.connack_packet
        rejoined = bool(getattr(data.negotiated_settings, "rejoined_session", False))
        if not connected.done():
            connected.set_result(data)
            print(get_message("connect.connected"))
            return
        # Any later success is a reconnect — the MQTT 3.1.1 "resumed" moment.
        print(
            get_message(
                "callbacks.resumed",
                reason_code_name(getattr(connack, "reason_code", None)),
                rejoined,
            )
        )

    def on_connection_failure(data):
        """Lifecycle: the attempt was refused. Print WHY and let the client retry.

        This is where MQTT 5 earns its place in a provisioning workshop: the
        first attempt after Just-in-Time Provisioning is normally refused with
        NOT_AUTHORIZED while AWS IoT Core activates the certificate, and here you
        can read that reason code instead of guessing at a timeout. Deliberately
        NOT fail-fast: retrying is the correct response in this flow.
        """
        reason_code = getattr(data.connack_packet, "reason_code", None)
        print(
            get_message(
                "connect.refused_retry",
                reason_code_name(reason_code),
                data.exception,
            )
        )

    def on_disconnection(data):
        """Lifecycle: an established connection dropped."""
        reason_code = getattr(data.disconnect_packet, "reason_code", None)
        print(get_message("callbacks.interrupted", reason_code_name(reason_code), data.exception))

    def on_stopped(data):  # noqa: ARG001 - dataclass is unused
        stopped.set()

    client = mqtt5_client_builder.mtls_from_path(
        endpoint=endpoint,
        cert_filepath=cert,
        pri_key_filepath=key,
        ca_filepath=ca,
        client_id=client_id,
        # clean_session=False under MQTT 3.1.1 becomes "rejoin the session once
        # this client has connected successfully at least once", plus a window
        # for the broker to keep that session.
        session_behavior=mqtt5.ClientSessionBehaviorType.REJOIN_POST_SUCCESS,
        session_expiry_interval_sec=3600,
        keep_alive_interval_sec=30,
        # Keep the reconnect cadence visible in a workshop. The default upper
        # bound is minutes, which would look like a hang.
        min_reconnect_delay_ms=1000,
        max_reconnect_delay_ms=5000,
        # Without this, the client defaults to FULL jitter: the delay is drawn
        # randomly between 0 and the current backoff value, so the very first
        # retry can land near 0ms and look like it isn't backing off at all.
        # NONE gives a deterministic doubling sequence (1s, 2s, 4s, 5s capped,
        # ...) that is actually visible instead of racing straight through.
        retry_jitter_mode=mqtt5.ExponentialBackoffJitterMode.NONE,
        on_lifecycle_connection_success=on_connection_success,
        on_lifecycle_connection_failure=on_connection_failure,
        on_lifecycle_disconnection=on_disconnection,
        on_lifecycle_stopped=on_stopped,
    )

    # start() returns immediately and the MQTT 5 client retries on its own, so
    # there is no manual retry loop here: just wait for the first CONNACK.
    print(get_message("connect.waiting", client_id))
    client.start()
    try:
        connected.result(timeout=FIRST_CONNECT_BUDGET_SEC)
    except TimeoutError:
        print(get_message("connect.failed"))
        client.stop()
        stopped.wait(timeout=10)
        sys.exit(1)

    print(get_message("publish.loop_start", topic))
    for i in range(10):
        payload = {"msg": f"hello from {client_id}", "seq": i}
        try:
            completion = client.publish(
                publish_packet=mqtt5.PublishPacket(
                    topic=topic,
                    payload=json.dumps(payload),
                    qos=mqtt5.QoS.AT_LEAST_ONCE,
                )
            ).result(timeout=15)
            puback = getattr(completion, "puback", None)
            if puback is not None and puback.reason_code != mqtt5.PubackReasonCode.SUCCESS:
                # Under MQTT 3.1.1 this was invisible: its PUBACK carries only a
                # packet identifier, so a refused publish looked like a lost one.
                print(
                    get_message(
                        "publish.refused",
                        topic,
                        reason_code_name(puback.reason_code),
                    )
                )
            else:
                print(get_message("publish.sent", topic, json.dumps(payload)))
        except Exception as exc:  # noqa: BLE001
            print(get_message("publish.failed", i, exc))
        time.sleep(3)  # nosemgrep: arbitrary-sleep

    client.stop()
    stopped.wait(timeout=10)
    print(get_message("disconnect.clean"))


if __name__ == "__main__":
    main()
