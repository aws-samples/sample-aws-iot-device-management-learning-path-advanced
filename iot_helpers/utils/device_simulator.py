#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Device-plane MQTT connection construct (the shared "device simulator").

This module is the DEVICE PLANE of the two-plane advanced provisioning sample.
It is a focused, reusable extraction of the connection-builder pattern from the
AWS IoT Core Learning SDK's interactive
``scripts/mqtt_client_explorer.py`` (repo:
``sample-aws-iot-core-learning-path-basics``). The large interactive explorer is
not copied wholesale; instead, its proven connection construct —
``awsiot.mqtt_connection_builder.mtls_from_path`` over ``awscrt.mqtt`` with
X.509 mutual TLS — is vendored here as a headless helper so it can be reused by
the Module 3–6 connect steps:

- Module 3: Just-in-Time Provisioning (JITP) first connect.
- Module 4: fleet-provisioning MQTT exchange with the claim certificate.
- Module 5: trusted-user provisioning exchange.
- Module 6: reconnect the SAME certificate to the Region 2 endpoint after
  Multi-Account Registration (MAR) — only the ``endpoint`` argument changes.

The ``mtls_from_path`` semantics are preserved EXACTLY as in the source
(``endpoint``, ``port=8883``, ``cert_filepath``, ``pri_key_filepath``,
``client_id``, ``clean_session=True``, ``keep_alive_secs=30``, and the
connection interrupted/resumed callbacks). Both the MQTT 3.1.1 and MQTT 5.0
builder paths from the source are retained.

Runs on top of the ``aws-iot-device-sdk-python-v2`` package (declared in
``requirements.txt``), which provides the ``awscrt`` / ``awsiot`` modules.
"""

import json
import threading
import uuid
from datetime import datetime

import boto3
from awscrt import mqtt
from awsiot import mqtt_connection_builder

try:
    from awsiot import mqtt5_connection_builder

    MQTT5_AVAILABLE = True
except ImportError:
    MQTT5_AVAILABLE = False


def get_iot_endpoint(debug=False):
    """Return the account's ``iot:Data-ATS`` MQTT endpoint.

    Preserves the endpoint-discovery call used by the source
    ``mqtt_client_explorer.py`` (``describe_endpoint`` with
    ``endpointType="iot:Data-ATS"``). Module 6 (MAR) obtains the Region 2
    endpoint by calling this with a region-scoped boto3 client / session.
    """
    iot = boto3.client("iot")
    if debug:
        print("🔄 describe_endpoint(endpointType='iot:Data-ATS')")
    response = iot.describe_endpoint(endpointType="iot:Data-ATS")
    endpoint = response["endpointAddress"]
    if debug:
        print(f"📤 endpoint: {endpoint}")
    return endpoint


class DeviceConnection:
    """A simulated device's MQTT connection to AWS IoT Core.

    Thin, reusable wrapper around the AWS IoT Core Learning SDK connection
    construct. Build a connection with :meth:`connect` and drive it with
    :meth:`subscribe`, :meth:`publish`, and :meth:`disconnect`. The underlying
    ``awscrt`` connection object is exposed as ``self.connection`` for callers
    that need direct access.
    """

    def __init__(self):
        self.connection = None
        self.connected = False
        self.received_messages = []
        self.subscriptions = {}
        self.message_lock = threading.Lock()
        self.endpoint = None
        self.thing_name = None

    # -- Connection lifecycle callbacks (preserved from the source) ---------

    def on_connection_interrupted(self, connection, error, **kwargs):
        """Callback for connection interruption."""
        print(f"\n⚠️  MQTT connection interrupted: {error}")
        self.connected = False

    def on_connection_resumed(self, connection, return_code, session_present, **kwargs):
        """Callback for connection resumption, re-subscribing if needed."""
        print(f"\n🔄 MQTT connection resumed (return_code={return_code}, session_present={session_present})")
        self.connected = True

        # Re-subscribe to all topics if the session was not resumed.
        if not session_present and self.subscriptions:
            topics_to_resubscribe = list(self.subscriptions.items())
            for topic, info in topics_to_resubscribe:
                try:
                    qos = info["qos"] if isinstance(info, dict) else info
                    mqtt_qos = mqtt.QoS.AT_MOST_ONCE if qos == 0 else mqtt.QoS.AT_LEAST_ONCE
                    subscribe_future, _ = self.connection.subscribe(
                        topic=topic, qos=mqtt_qos, callback=self.on_message_received
                    )
                    subscribe_future.result()
                except Exception as e:
                    print(f"❌ Failed to re-subscribe to {topic}: {e}")
                    self.subscriptions.pop(topic, None)

    def on_message_received(self, topic, payload, dup, qos, retain, **kwargs):
        """Callback for received messages; records the message for callers."""
        try:
            try:
                payload_data = json.loads(payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload_data = payload.decode("utf-8", errors="replace")

            message_info = {
                "topic": topic,
                "qos": qos,
                "dup": dup,
                "retain": retain,
                "payload": payload_data,
                "timestamp": datetime.now().isoformat(),
            }
            with self.message_lock:
                self.received_messages.append(message_info)
        except Exception as e:
            print(f"❌ Error processing received message: {e}")

    # -- Connect / subscribe / publish / disconnect ------------------------

    def connect(
        self,
        endpoint,
        cert_filepath,
        pri_key_filepath,
        client_id=None,
        thing_name=None,
        mqtt_version="3.1.1",
        port=8883,
        clean_session=True,
        keep_alive_secs=30,
        debug=False,
    ):
        """Establish an mTLS MQTT connection to AWS IoT Core.

        Faithfully preserves the ``mqtt_connection_builder.mtls_from_path``
        connection construct from the source ``mqtt_client_explorer.py``:
        X.509 mutual TLS on port 8883, ``clean_session`` / ``keep_alive_secs``
        as in the source, with connection interrupted/resumed callbacks. When
        ``mqtt_version="5.0"`` and the MQTT 5 builder is available, the
        equivalent MQTT 5 builder path is used, mirroring the source's
        fallback to MQTT 3.1.1.
        """
        self.endpoint = endpoint
        self.thing_name = thing_name

        # Auto-generate a client ID if one is not supplied.
        if not client_id:
            base = thing_name or "device"
            client_id = f"{base}-{uuid.uuid4().hex[:8]}"

        if debug:
            print("🔧 MQTT connection setup")
            print(f"   Client ID: {client_id}")
            print(f"   Endpoint: {endpoint}")
            print(f"   Port: {port}")
            print(f"   Certificate: {cert_filepath}")
            print(f"   Private key: {pri_key_filepath}")
            print(f"   Protocol: MQTT {mqtt_version} over TLS")

        # Build MQTT connection using the appropriate SDK v2 builder,
        # preserving the exact mtls_from_path parameters from the source.
        if mqtt_version == "5.0" and MQTT5_AVAILABLE:
            try:
                self.connection = mqtt5_connection_builder.mtls_from_path(
                    endpoint=endpoint,
                    port=port,
                    cert_filepath=cert_filepath,
                    pri_key_filepath=pri_key_filepath,
                    client_id=client_id,
                    clean_session=clean_session,
                    keep_alive_secs=keep_alive_secs,
                    on_connection_interrupted=self.on_connection_interrupted,
                    on_connection_resumed=self.on_connection_resumed,
                )
            except Exception as mqtt5_error:
                print(f"⚠️  MQTT 5.0 connection failed: {mqtt5_error}")
                print("🔄 Falling back to MQTT 3.1.1")
                mqtt_version = "3.1.1"

        if mqtt_version == "3.1.1" or not MQTT5_AVAILABLE:
            self.connection = mqtt_connection_builder.mtls_from_path(
                endpoint=endpoint,
                port=port,
                cert_filepath=cert_filepath,
                pri_key_filepath=pri_key_filepath,
                client_id=client_id,
                clean_session=clean_session,
                keep_alive_secs=keep_alive_secs,
                on_connection_interrupted=self.on_connection_interrupted,
                on_connection_resumed=self.on_connection_resumed,
            )

        connect_future = self.connection.connect()
        connect_future.result()  # Wait for the connection to complete.
        self.connected = True

        if debug:
            print("✅ MQTT connection established")

        return self.connection

    def subscribe(self, topic, qos=0):
        """Subscribe to an MQTT topic and track the subscription."""
        if not self.connected or not self.connection:
            raise RuntimeError("Not connected to AWS IoT Core")

        mqtt_qos = mqtt.QoS.AT_MOST_ONCE if qos == 0 else mqtt.QoS.AT_LEAST_ONCE
        subscribe_future, packet_id = self.connection.subscribe(
            topic=topic, qos=mqtt_qos, callback=self.on_message_received
        )
        subscribe_future.result()
        self.subscriptions[topic] = {
            "qos": qos,
            "packet_id": packet_id,
            "subscribed_at": datetime.now().isoformat(),
        }
        return True

    def publish(self, topic, message, qos=0):
        """Publish a message (dict is serialized to JSON) to an MQTT topic."""
        if not self.connected or not self.connection:
            raise RuntimeError("Not connected to AWS IoT Core")

        payload = json.dumps(message) if isinstance(message, dict) else str(message)
        mqtt_qos = mqtt.QoS.AT_MOST_ONCE if qos == 0 else mqtt.QoS.AT_LEAST_ONCE
        publish_future, packet_id = self.connection.publish(topic=topic, payload=payload, qos=mqtt_qos)
        publish_future.result()
        return packet_id

    def disconnect(self):
        """Disconnect the MQTT connection and reset connection state."""
        if self.connection:
            try:
                disconnect_future = self.connection.disconnect()
                disconnect_future.result()
            except Exception:
                pass
        self.connection = None
        self.connected = False
        self.subscriptions = {}
