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
import sys
import time

from awscrt import mqtt
from awsiot import mqtt_connection_builder

USAGE = (
    "Usage: python3 ../scripts/mqtt_connect.py "
    "<endpoint> <clientId> <certFile> <keyFile> <caFile> <topic>"
)


def main():
    if len(sys.argv) < 7:
        print(USAGE)
        sys.exit(2)

    endpoint, client_id, cert, key, ca, topic = sys.argv[1:7]

    def on_interrupted(connection, error, **kwargs):
        print(f"WARNING  Connection interrupted: {error} (the SDK will retry automatically)")

    def on_resumed(connection, return_code, session_present, **kwargs):
        print(f"OK  Connection resumed (return_code={return_code}, session_present={session_present})")

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
            print(f"Connecting as {client_id} (attempt {attempt}) ...")
            conn.connect().result()
            print("Connected.")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  first connect dropped while provisioning finishes ({exc}); retrying in 3s ...")
            time.sleep(3)
    else:
        print("Could not connect after several attempts - check the certificate/policy and retry.")
        sys.exit(1)

    print(f"Now publishing on a loop to {topic}; each message should land on the topic.")
    for i in range(10):
        payload = {"msg": f"hello from {client_id}", "seq": i}
        try:
            conn.publish(
                topic=topic,
                payload=json.dumps(payload),
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )
            print(f"  PUBLISH -> {topic}: {json.dumps(payload)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  publish seq={i} failed (likely mid-reconnect): {exc}")
        time.sleep(3)

    conn.disconnect().result()
    print("Disconnected cleanly.")


if __name__ == "__main__":
    main()
