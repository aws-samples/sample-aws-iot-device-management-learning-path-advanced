#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Device-plane MQTT connection construct (the shared "device simulator").

This module is the DEVICE PLANE of the two-plane advanced provisioning sample.
It is a focused, reusable helper that opens an X.509 mutual-TLS **MQTT 5**
connection to AWS IoT Core, so it can be reused by the Module 3-6 connect steps:

- Module 3: Just-in-Time Provisioning (JITP) first connect.
- Module 4: fleet-provisioning MQTT exchange with the claim certificate.
- Module 5: trusted-user provisioning exchange.
- Module 6: reconnect the SAME certificate to the Region 2 endpoint after
  Multi-Account Registration (MAR) — only the ``endpoint`` argument changes.

Why MQTT 5
----------
This workshop standardises on **MQTT 5** for every device-plane connection.
New devices should be built on MQTT 5 because it reports a **reason code on
every acknowledgement** — CONNACK, PUBACK, SUBACK and DISCONNECT — so a device
can tell *why* an operation failed instead of inferring it. In particular
``NOT_AUTHORIZED`` (0x87) distinguishes an authorization failure, which retrying
cannot fix, from a transient condition such as ``QUOTA_EXCEEDED`` (0x97), which
retrying can. Under MQTT 3.1.1 that distinction is unavailable for a publish at
all: the MQTT 3.1.1 PUBACK packet carries only a packet identifier and has no
reason-code field, so a refused publish is indistinguishable from a lost one.
See `MQTT reason codes
<https://docs.aws.amazon.com/iot/latest/developerguide/mqtt.html>`_.

Note that adopting MQTT 5 is not the same as enabling every MQTT 5 feature.
AWS IoT Core's reserved provisioning topics reject a PUBLISH that carries a
Response Topic property, which is why Module 4's raw ``mosquitto_rr`` step
deliberately pins ``-V mqttv311``. This helper never sets MQTT 5 properties on
reserved topics.

Reason codes surfaced by this helper
------------------------------------
:meth:`DeviceConnection.connect` raises with the CONNACK reason code when the
broker refuses the connection, and records it on ``self.connect_reason_code``.
:meth:`DeviceConnection.publish` returns the PUBACK reason code for a QoS 1
publish and raises when the broker refuses it. :meth:`DeviceConnection.subscribe`
raises when the SUBACK reports anything other than a granted QoS.

Runs on top of the ``aws-iot-device-sdk-python-v2`` package (declared in
``requirements.txt``), which provides the ``awscrt`` / ``awsiot`` modules.
"""

import json
import threading
import uuid
from concurrent.futures import Future
from datetime import datetime

import boto3
from awscrt import mqtt5
from awsiot import mqtt5_client_builder

# How long to wait for a CONNACK / SUBACK / PUBACK before giving up. The MQTT 5
# client signals connection outcome through lifecycle callbacks rather than a
# future, so the connect path below bridges those callbacks onto a Future and
# waits on it with this timeout.
DEFAULT_OPERATION_TIMEOUT_SEC = 30

# Reason codes that mean "this will never succeed, do not retry". Everything
# else (a quota, a rate limit, a dropped socket) is transient and worth a retry.
TERMINAL_CONNECT_REASON_CODES = frozenset(
    {
        mqtt5.ConnectReasonCode.NOT_AUTHORIZED,
        mqtt5.ConnectReasonCode.BAD_USERNAME_OR_PASSWORD,
        mqtt5.ConnectReasonCode.CLIENT_IDENTIFIER_NOT_VALID,
        mqtt5.ConnectReasonCode.BANNED,
    }
)


class ConnectFailed(RuntimeError):
    """Raised when the broker refuses the connection or it cannot be opened.

    ``reason_code`` is the CONNACK reason code when the broker answered, and
    ``None`` when the failure happened below MQTT (DNS, TLS, socket). Callers
    use :attr:`is_terminal` to decide whether retrying could ever help.
    """

    def __init__(self, message, reason_code=None, cause=None):
        super().__init__(message)
        self.reason_code = reason_code
        self.cause = cause

    @property
    def is_terminal(self):
        """True when retrying cannot change the outcome (an authorization failure)."""
        return self.reason_code in TERMINAL_CONNECT_REASON_CODES


class PublishRefused(RuntimeError):
    """Raised when a QoS 1 publish is acknowledged with a failure reason code."""

    def __init__(self, message, reason_code=None):
        super().__init__(message)
        self.reason_code = reason_code


def reason_code_name(reason_code):
    """Render a reason code as ``NAME (0xHH)``, or ``-`` when there is none.

    A network-level failure has no reason code at all, which is itself the
    useful signal: the broker never answered.
    """
    if reason_code is None:
        return "-"
    name = getattr(reason_code, "name", str(reason_code))
    try:
        return f"{name} (0x{int(reason_code):02X})"
    except (TypeError, ValueError):
        return name


def get_iot_endpoint(debug=False):
    """Return the account's ``iot:Data-ATS`` MQTT endpoint.

    Module 6 (MAR) obtains the Region 2 endpoint by calling this with a
    region-scoped boto3 client / session.
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
    """A simulated device's MQTT 5 connection to AWS IoT Core.

    Thin, reusable wrapper around ``awsiot.mqtt5_client_builder``. Build a
    connection with :meth:`connect` and drive it with :meth:`subscribe`,
    :meth:`publish`, and :meth:`disconnect`. The underlying
    :class:`awscrt.mqtt5.Client` is exposed as ``self.connection`` for callers
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
        self.client_id = None
        # Outcome of the most recent connect attempt, for callers that want to
        # report or branch on it without catching the exception.
        self.connect_reason_code = None
        self.rejoined_session = False
        # Lifecycle plumbing: the MQTT 5 client reports connection outcome
        # through callbacks, so they are bridged onto these.
        self._connect_result = None
        self._stopped = threading.Event()

    # -- Lifecycle callbacks ------------------------------------------------
    # MQTT 5 replaces MQTT 3.1.1's interrupted/resumed callback pair with a
    # lifecycle event stream. The two handlers below preserve the same
    # learner-visible narration.

    def _on_lifecycle_connection_success(self, data):
        """Lifecycle: CONNACK accepted. Carries the negotiated session state."""
        connack = data.connack_packet
        settings = data.negotiated_settings
        self.connected = True
        self.connect_reason_code = getattr(connack, "reason_code", None)
        self.rejoined_session = bool(getattr(settings, "rejoined_session", False))

        if self._connect_result is not None and not self._connect_result.done():
            self._connect_result.set_result(data)
            return

        # A success after the first one is a reconnect, which is the MQTT 3.1.1
        # "connection resumed" moment. If the session was not rejoined, the
        # broker has no record of our subscriptions and they must be replaced.
        print(
            f"\n🔄 MQTT connection resumed "
            f"(reason_code={reason_code_name(self.connect_reason_code)}, "
            f"rejoined_session={self.rejoined_session})"
        )
        if not self.rejoined_session and self.subscriptions:
            for topic, info in list(self.subscriptions.items()):
                try:
                    self._subscribe_once(topic, info["qos"])
                except Exception as error:  # noqa: BLE001 - keep the others
                    print(f"❌ Failed to re-subscribe to {topic}: {error}")
                    self.subscriptions.pop(topic, None)

    def _on_lifecycle_connection_failure(self, data):
        """Lifecycle: the connection attempt failed. Capture WHY, once."""
        connack = data.connack_packet
        reason_code = getattr(connack, "reason_code", None)
        self.connected = False
        self.connect_reason_code = reason_code

        if self._connect_result is not None and not self._connect_result.done():
            self._connect_result.set_exception(
                ConnectFailed(
                    f"connection refused: reason_code={reason_code_name(reason_code)}"
                    f" exception={data.exception}",
                    reason_code=reason_code,
                    cause=data.exception,
                )
            )

    def _on_lifecycle_disconnection(self, data):
        """Lifecycle: an established connection dropped."""
        self.connected = False
        packet = data.disconnect_packet
        reason_code = getattr(packet, "reason_code", None)
        print(
            f"\n⚠️  MQTT connection interrupted "
            f"(reason_code={reason_code_name(reason_code)}, exception={data.exception})"
        )

    def _on_lifecycle_stopped(self, data):  # noqa: ARG002 - dataclass is unused
        """Lifecycle: the client has fully stopped. Unblocks :meth:`disconnect`."""
        self.connected = False
        self._stopped.set()

    # -- Inbound messages --------------------------------------------------

    def on_message_received(self, data):
        """Record every inbound publish so callers can poll ``received_messages``.

        MQTT 5 delivers **all** inbound publishes to one callback rather than a
        per-subscription callback, so this records the topic alongside the
        payload and callers filter by topic themselves — which is what the
        provisioning scripts already did.
        """
        try:
            packet = data.publish_packet
            payload = packet.payload
            if isinstance(payload, (bytes, bytearray)):
                text = bytes(payload).decode("utf-8", errors="replace")
            else:
                text = str(payload)
            try:
                payload_data = json.loads(text)
            except json.JSONDecodeError:
                payload_data = text

            message_info = {
                "topic": packet.topic,
                "qos": int(getattr(packet, "qos", 0)),
                "retain": bool(getattr(packet, "retain", False)),
                "payload": payload_data,
                "timestamp": datetime.now().isoformat(),
            }
            with self.message_lock:
                self.received_messages.append(message_info)
        except Exception as error:  # noqa: BLE001 - never kill the callback thread
            print(f"❌ Error processing received message: {error}")

    # -- Connect / subscribe / publish / disconnect ------------------------

    def connect(
        self,
        endpoint,
        cert_filepath,
        pri_key_filepath,
        client_id=None,
        thing_name=None,
        ca_filepath=None,
        port=8883,
        clean_session=True,
        keep_alive_secs=30,
        session_expiry_interval_sec=3600,
        timeout=DEFAULT_OPERATION_TIMEOUT_SEC,
        debug=False,
    ):
        """Open an mTLS MQTT 5 connection to AWS IoT Core.

        X.509 mutual TLS on port 8883. ``clean_session`` is mapped onto MQTT 5
        session semantics: ``True`` starts a clean session every time, ``False``
        asks the broker to keep session state (and so keep subscriptions across
        a transient reconnect) for ``session_expiry_interval_sec``.

        Raises :class:`ConnectFailed` when the broker refuses the connection.
        The CONNACK reason code is on the exception and on
        ``self.connect_reason_code``; use ``ConnectFailed.is_terminal`` to tell
        an authorization failure from a transient one.
        """
        self.endpoint = endpoint
        self.thing_name = thing_name

        # Auto-generate a client ID if one is not supplied. Note that thing
        # policy variables such as ${iot:Connection.Thing.ThingName} require
        # the client ID to equal the thing name, so pass client_id explicitly
        # whenever such a policy is in play.
        if not client_id:
            base = thing_name or "device"
            client_id = f"{base}-{uuid.uuid4().hex[:8]}"
        self.client_id = client_id

        if clean_session:
            session_behavior = mqtt5.ClientSessionBehaviorType.CLEAN
            expiry = None
        else:
            session_behavior = mqtt5.ClientSessionBehaviorType.REJOIN_POST_SUCCESS
            expiry = session_expiry_interval_sec

        if debug:
            print("🔧 MQTT connection setup")
            print(f"   Client ID: {client_id}")
            print(f"   Endpoint: {endpoint}")
            print(f"   Port: {port}")
            print(f"   Certificate: {cert_filepath}")
            print(f"   Private key: {pri_key_filepath}")
            print("   Protocol: MQTT 5 over TLS")
            print(f"   Session: {session_behavior.name}")

        self._connect_result = Future()
        self._stopped.clear()
        self.connect_reason_code = None

        builder_kwargs = {
            "endpoint": endpoint,
            "port": port,
            "cert_filepath": cert_filepath,
            "pri_key_filepath": pri_key_filepath,
            "client_id": client_id,
            "keep_alive_interval_sec": keep_alive_secs,
            "session_behavior": session_behavior,
            "ack_timeout_sec": timeout,
            "on_publish_received": self.on_message_received,
            "on_lifecycle_connection_success": self._on_lifecycle_connection_success,
            "on_lifecycle_connection_failure": self._on_lifecycle_connection_failure,
            "on_lifecycle_disconnection": self._on_lifecycle_disconnection,
            "on_lifecycle_stopped": self._on_lifecycle_stopped,
        }
        if ca_filepath:
            builder_kwargs["ca_filepath"] = ca_filepath
        if expiry is not None:
            builder_kwargs["session_expiry_interval_sec"] = expiry

        self.connection = mqtt5_client_builder.mtls_from_path(**builder_kwargs)

        # start() returns immediately; the outcome arrives on a lifecycle
        # callback, which the handlers above bridge onto _connect_result.
        self.connection.start()
        try:
            self._connect_result.result(timeout=timeout)
        except ConnectFailed:
            # The MQTT 5 client retries in the background, so stop it rather
            # than leaving it spinning against a connection that was refused.
            self._stop_client()
            raise
        except TimeoutError as error:
            self._stop_client()
            raise ConnectFailed(
                f"no CONNACK within {timeout}s", cause=error
            ) from error
        finally:
            self._connect_result = None

        self.connected = True
        if debug:
            print("✅ MQTT connection established")
            print(f"   CONNACK: {reason_code_name(self.connect_reason_code)}")

        return self.connection

    def _subscribe_once(self, topic, qos):
        """Send one SUBSCRIBE and fail if the SUBACK does not grant it."""
        mqtt_qos = mqtt5.QoS.AT_MOST_ONCE if qos == 0 else mqtt5.QoS.AT_LEAST_ONCE
        suback = self.connection.subscribe(
            subscribe_packet=mqtt5.SubscribePacket(
                subscriptions=[
                    mqtt5.Subscription(topic_filter=topic, qos=mqtt_qos)
                ]
            )
        ).result(timeout=DEFAULT_OPERATION_TIMEOUT_SEC)

        granted = {
            mqtt5.SubackReasonCode.GRANTED_QOS_0,
            mqtt5.SubackReasonCode.GRANTED_QOS_1,
            mqtt5.SubackReasonCode.GRANTED_QOS_2,
        }
        for code in suback.reason_codes:
            if code not in granted:
                raise RuntimeError(
                    f"subscription to {topic} refused: {reason_code_name(code)}"
                )
        return suback

    def subscribe(self, topic, qos=0):
        """Subscribe to an MQTT topic and track the subscription.

        Raises when the SUBACK reports a failure reason code — under MQTT 3.1.1
        a refused subscription looked identical to a granted one.
        """
        if not self.connected or not self.connection:
            raise RuntimeError("Not connected to AWS IoT Core")

        self._subscribe_once(topic, qos)
        self.subscriptions[topic] = {
            "qos": qos,
            "subscribed_at": datetime.now().isoformat(),
        }
        return True

    def publish(self, topic, message, qos=0):
        """Publish a message (dict is serialized to JSON) to an MQTT topic.

        For QoS 1 the PUBACK reason code is checked and returned, so a refused
        publish raises :class:`PublishRefused` instead of silently succeeding.
        """
        if not self.connected or not self.connection:
            raise RuntimeError("Not connected to AWS IoT Core")

        payload = json.dumps(message) if isinstance(message, dict) else str(message)
        mqtt_qos = mqtt5.QoS.AT_MOST_ONCE if qos == 0 else mqtt5.QoS.AT_LEAST_ONCE
        completion = self.connection.publish(
            publish_packet=mqtt5.PublishPacket(
                topic=topic, payload=payload, qos=mqtt_qos
            )
        ).result(timeout=DEFAULT_OPERATION_TIMEOUT_SEC)

        # QoS 0 is fire-and-forget, so there is no PUBACK to inspect.
        puback = getattr(completion, "puback", None)
        if puback is None:
            return None
        if puback.reason_code != mqtt5.PubackReasonCode.SUCCESS:
            raise PublishRefused(
                f"publish to {topic} refused: {reason_code_name(puback.reason_code)}"
                f" {puback.reason_string or ''}".rstrip(),
                reason_code=puback.reason_code,
            )
        return puback.reason_code

    def _stop_client(self):
        """Stop the client and wait briefly for the stopped lifecycle event."""
        if not self.connection:
            return
        try:
            self.connection.stop()
            self._stopped.wait(timeout=DEFAULT_OPERATION_TIMEOUT_SEC)
        except Exception:  # noqa: BLE001 - teardown is best effort
            pass
        self.connection = None
        self.connected = False

    def disconnect(self):
        """Disconnect the MQTT connection and reset connection state."""
        self._stop_client()
        self.subscriptions = {}
