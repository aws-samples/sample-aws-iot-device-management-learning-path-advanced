#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Minimal AWS IoT Device SDK for Python v2 MQTT client (shared across sections).

This is the tiny device-plane client the provisioning sections use whenever a
device connects with a certificate and publishes telemetry — the first connect
in JITP/JITR, the permanent-certificate reconnect in the fleet flows, and the
endpoint-switch reconnect in Multi-Account Registration.

It intentionally stays small and self-contained (direct ``awscrt`` / ``awsiot``,
no shared helper) so a learner can read the whole "how do I open a mutual-TLS
MQTT connection?" story in one file.

The very first connect right after provisioning is EXPECTED to be dropped: AWS
IoT Core registers the certificate and runs the provisioning template, then
closes that first connection. The SDK's automatic reconnect only starts AFTER a
first successful connect, so this client retries the initial connect itself —
you run it once and just watch it recover (no manual re-run, no traceback).

Usage:
    python3 ../scripts/mqtt_connect.py <endpoint> <clientId> \\
        <certFile> <keyFile> <caFile> <topic>
"""

import json
import os
import sys
import time

# --- Repository path wiring (import i18n framework) ----------------------
# mqtt_connect.py lives in scripts/, so REPO_ROOT is two dirnames up (the repo
# root, which contains i18n/ as a sibling of scripts/).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "i18n"))

from awscrt import mqtt  # noqa: E402
from awsiot import mqtt_connection_builder  # noqa: E402

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

    def on_interrupted(connection, error, **kwargs):
        print(get_message("callbacks.interrupted", error))

    def on_resumed(connection, return_code, session_present, **kwargs):
        print(get_message("callbacks.resumed", return_code, session_present))

    conn = mqtt_connection_builder.mtls_from_path(
        endpoint=endpoint,
        cert_filepath=cert,
        pri_key_filepath=key,
        ca_filepath=ca,
        client_id=client_id,
        clean_session=False,
        keep_alive_secs=30,
        on_connection_interrupted=on_interrupted,
        on_connection_resumed=on_resumed,
    )

    # Retry the initial connect until it succeeds (see module note above).
    for attempt in range(1, 21):
        try:
            print(get_message("connect.attempt", client_id, attempt))
            conn.connect().result()
            print(get_message("connect.connected"))
            break
        except Exception as exc:  # noqa: BLE001
            print(get_message("connect.first_drop_retry", exc))
            time.sleep(3)
    else:
        print(get_message("connect.failed"))
        sys.exit(1)

    print(get_message("publish.loop_start", topic))
    for i in range(10):
        payload = {"msg": f"hello from {client_id}", "seq": i}
        try:
            conn.publish(
                topic=topic,
                payload=json.dumps(payload),
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )
            print(get_message("publish.sent", topic, json.dumps(payload)))
        except Exception as exc:  # noqa: BLE001
            print(get_message("publish.failed", i, exc))
        time.sleep(3)

    conn.disconnect().result()
    print(get_message("disconnect.clean"))


if __name__ == "__main__":
    main()
