# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Device-side certificate rotation agent — the device half of Module 6.

Device-plane agent for Module 6, "Certificate Rotation" (design section 2.12).
It runs the device half of a backend-driven rotation: take the job execution,
generate a new key pair and certificate signing request **locally**, ask the
handler to sign it, install the result, reconnect with it, and prove an
authorized publish before reporting success.

Why the device does not decide to rotate
----------------------------------------
Rotation is **backend-initiated**. The device cannot know your age threshold,
your fleet renewal schedule, or that a certificate authority was compromised
this morning — so the backend drives a campaign with AWS IoT Jobs and this agent
executes its half. That is the inverse of the provisioning modules, where the
device often starts the flow.

The rotation invariant this agent respects
-----------------------------------------
**Report success only after the new certificate has done real work.** The agent
connects with the new certificate and completes an *authorized publish* before
reporting ``SUCCEEDED``. If either step fails, it falls back to the current
certificate — which was never retired — and reports ``FAILED``, leaving the
device online for a retry.

Two different failures, and why both matter
-------------------------------------------
A replacement certificate can fail in two distinct places, and the agent
handles both:

1. **It cannot connect.** AWS IoT Core authorizes ``iot:Connect`` on every
   CONNECT, and permissions come only from policies attached to the certificate
   itself. So a certificate the handler forgot to attach a policy to is refused
   at connect time — it never reaches a publish.
2. **It connects but cannot publish.** This one is subtler, because the handler
   copies the *same* policy documents onto the new certificate. A policy scoped
   by **thing** variables (``iot:Connection.Thing.ThingName``) means the same
   thing for both certificates. A policy scoped by **certificate** variables
   (``iot:Certificate.SerialNumber``, ``iot:Certificate.Subject.*``) does not —
   and rotation is the only operation that changes the certificate under a fixed
   thing. Note that the certificate signing request built below sets only
   ``CN``, so any subject attribute a policy relies on would be absent.

The proof publish is what catches case 2, which is why the agent does real work
rather than settling for a successful connection.

Simulating a device that never installs the certificate
---------------------------------------------------------
With ``--pause``, the moment the signed certificate arrives this agent offers a
choice instead of installing it right away: continue as normal, or simulate a
device that received the certificate but lost it before writing it to disk — a
crash, a reboot, a dropped connection between the two. Choosing the second
option is not narration over an unchanged flow. This agent discards the
certificate it just received, disconnects, reconnects on the certificate it
still holds, and asks the backend again with the **same** certificate signing
request it already generated. Because the request carries the same public key
the handler already signed for this rotation, the backend re-delivers the
certificate it already issued rather than signing a second one — the same
recovery this repository's certificate-rotation content calls out as
`redelivering` on the backend side. The offer appears once per rotation; after
either choice, the agent moves on to installing the certificate it holds.

The private key generated here never leaves the device. Only the certificate
signing request is transmitted, which is why a message the device misses costs
a recoverable certificate rather than an unrecoverable key.

Simulating a device that restarts before the reply arrives
------------------------------------------------------------
``--break-after-csr`` exits right after the certificate signing request is
sent, before waiting for the signed reply — a deterministic stand-in for a
device that crashes or reboots in that exact gap, generates a **new** key pair
on restart, and asks again. Timing that moment with Ctrl-C against a live
network round-trip is not reliably reproducible; this flag makes the same
state reachable on purpose, every time. The execution stays exactly where it
was left (``IN_PROGRESS``, ``phase=INITIATED``); run the same command again
**without** the flag to pick it back up. Because a fresh process calls
``generate_keypair()`` on startup with no memory of the request it sent
moments ago, that second run's request carries a **different** public key
than the one the handler already signed for this rotation — which is what
leads the handler to sign a second certificate (``resigning``) rather than
re-deliver the first one, unlike the same-key case above.

Why MQTT 5
----------
This agent speaks **MQTT 5**, which reports a **reason code** on every
acknowledgement. That is what lets the fallback below be deliberate instead of
blind: ``NOT_AUTHORIZED`` (0x87) on the CONNACK means the replacement
certificate will *never* work, so the agent stops retrying immediately and rolls
back; anything else (``QUOTA_EXCEEDED``, a dropped socket) is transient and is
retried with backoff first. Under MQTT 3.1.1 that distinction is unavailable for
a publish at all — its PUBACK packet has no reason-code field, so a refused
publish is indistinguishable from a lost one and every failure has to be treated
the same way. See `MQTT reason codes
<https://docs.aws.amazon.com/iot/latest/developerguide/mqtt.html>`_.

Phases written to the job execution
-----------------------------------
The job execution ``status`` field is a fixed enumeration, so this agent's own
phase markers live in ``statusDetails`` alongside it. This agent is the ONLY
writer of that map — the handler never touches job status at all, on this or
any other path::

    IN_PROGRESS  phase=INITIATED       job taken, about to generate a key pair
    SUCCEEDED    phase=INSTALLED       new certificate installed and proven
    FAILED       phase=CUTOVER_FAILED  new certificate unusable, rolled back

A ``CUTOVER_FAILED`` execution also carries a ``reason`` in ``statusDetails``, so
an operator reading ``describe-job-execution`` can tell the two failures apart —
a refused connect points at the certificate's policy attachment, a refused
publish points at the policy's *scope*. Between ``INITIATED`` and either
terminal phase, the execution's ``statusDetails`` says nothing new — that gap is
not a blind spot in this agent, it is the two-store split working as intended.
The handler's own progress (a certificate signed and attached, ready to be
picked up again) lives in its rotation shadow instead, which this agent has no
permission to read. See "What is deliberately NOT in statusDetails" below.

What is deliberately NOT in statusDetails
-----------------------------------------
``phase`` is the only thing this agent writes there, and the id of the new
certificate is deliberately absent. Two reasons:

* ``statusDetails`` is **replaced wholesale** on every ``UpdateJobExecution``,
  not merged. Both the device and the handler write that map, so whatever one
  puts there the other erases. Keeping it to a single key both actors own means
  replacement can no longer lose anything.
* Which certificate survives a rotation is a **backend** decision. A device that
  reported it would be choosing which of its own credentials gets destroyed. The
  handler records it in a dedicated named shadow instead — one this device has no
  policy permitting it to read or write.

If you adapt this agent and find yourself needing to write a second key here,
read the current map back first and carry it forward. Do not assume a merge.

Examples
--------
    python scripts/rotate_certificate.py \\
        --endpoint "$IOT_ENDPOINT" --thing-name AnyCompany-Sensor-9001 \\
        --cert AnyCompany-Sensor-9001.old.cert.pem \\
        --key AnyCompany-Sensor-9001.old.private.key \\
        --ca AmazonRootCA1.pem

    # Keep using the old certificate if the cutover fails (default), or stop at
    # the failure to inspect state:
    python scripts/rotate_certificate.py ... --no-rollback

    # Guided walkthrough: pause at each observable step so you can inspect the
    # job execution, the certificate overlap and the deferred retirement in the
    # console or with the AWS CLI before the device continues:
    python scripts/rotate_certificate.py ... --pause

Reading the output
------------------
The agent narrates each step in prose and prints the MQTT traffic underneath it,
so the story and the wire are side by side::

    SUB      subscribed to a topic
    PUB  --> published by the device
    RECV <-- delivered to the device

The signed certificate is public and is printed truncated. The private key is
never printed, and never published: only the certificate signing request is
transmitted, which is why the wire trace is safe to read and to share.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import Future

# --- Repository path wiring (import shared constructs) --------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "i18n"))

from awscrt import mqtt5  # noqa: E402
from awsiot import mqtt5_client_builder  # noqa: E402

from language_selector import get_language  # noqa: E402
from loader import load_messages  # noqa: E402

# --- MQTT 5 reason-code handling -----------------------------------------
# CONNACK reason codes that mean "this will never succeed". Retrying an
# authorization failure only wastes the job execution's in-progress budget, so
# the agent stops and rolls back the moment it sees one. Everything else — a
# quota, a rate limit, a dropped socket — is transient and worth a retry.
# The one operation this agent implements. A device polling start-next receives
# whatever job is next for it — in a real account that could be a firmware update
# or a reboot — so the job document's operation is dispatched on rather than
# assumed. See take_job().
ROTATE_OPERATION = "rotateCertificate"

TERMINAL_CONNECT_REASON_CODES = frozenset(
    {
        mqtt5.ConnectReasonCode.NOT_AUTHORIZED,
        mqtt5.ConnectReasonCode.BAD_USERNAME_OR_PASSWORD,
        mqtt5.ConnectReasonCode.CLIENT_IDENTIFIER_NOT_VALID,
        mqtt5.ConnectReasonCode.BANNED,
    }
)


class ConnectFailed(RuntimeError):
    """The broker refused the connection, or it could not be opened at all.

    ``reason_code`` is the CONNACK reason code when the broker answered and
    ``None`` when the failure happened below MQTT (DNS, TLS, socket) — that
    absence is itself informative, because it means the broker never replied.
    """

    def __init__(self, message, reason_code=None, cause=None):
        super().__init__(message)
        self.reason_code = reason_code
        self.cause = cause

    @property
    def is_terminal(self):
        """True when retrying cannot change the outcome."""
        return self.reason_code in TERMINAL_CONNECT_REASON_CODES


class PublishRefused(RuntimeError):
    """A QoS 1 publish was acknowledged with a failure reason code."""

    def __init__(self, message, reason_code=None):
        super().__init__(message)
        self.reason_code = reason_code


class UnsupportedOperation(RuntimeError):
    """The job execution asked for an operation this agent does not implement."""


class BreakAfterCsr(Exception):
    """Requested exit right after the certificate signing request was sent.

    Raised by :meth:`RotationAgent.request_certificate` when ``--break-after-csr``
    is set, instead of waiting for the signed reply. This is a deterministic
    stand-in for a device that restarts between sending its request and
    receiving the answer — the same moment a Ctrl-C would have to land, but
    exactly, every time, without racing the network.
    """


def reason_code_name(reason_code):
    """Render an MQTT 5 reason code as ``NAME (0xHH)``, or ``-`` when absent."""
    if reason_code is None:
        return "-"
    name = getattr(reason_code, "name", str(reason_code))
    try:
        return f"{name} (0x{int(reason_code):02X})"
    except (TypeError, ValueError):
        return name

# --- i18n message catalog + resolver -------------------------------------
# Populated once at entry (see main()) via load_messages(). The wrapper below
# is the shared nested-capable convention documented in i18n/README.md: dotted
# keys walk the nested catalog, a missing key falls back to the key itself, and
# positional {} placeholders are filled via str.format(*args). It is defined
# per-script on purpose (NOT centralized in loader.py).
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


# --- Verbose wire-trace helpers ------------------------------------------
# The agent narrates what it is doing in prose, and prints the MQTT traffic
# that carries it directly underneath. Only the labels are localized: topic
# names, payloads and identifiers are protocol data and print verbatim.
def shorten(value, keep=56):
    """Collapse a long value (PEM, certificate signing request, JSON) to one readable line."""
    flat = " ".join(str(value).split())
    if len(flat) <= keep:
        return flat
    return get_message("wire.truncated", flat[:keep], len(flat))


def region_from_endpoint(endpoint):
    """Best-effort Region from an iot:Data-ATS endpoint, for console links."""
    parts = str(endpoint).split(".")
    if len(parts) >= 4 and parts[1] == "iot":
        return parts[2]
    return None


def console_url(fragment, region):
    """Build an AWS IoT console link, Region-qualified when the Region is known."""
    base = "https://console.aws.amazon.com/iot/home"
    if region:
        return f"{base}?region={region}#/{fragment}"
    return f"{base}#/{fragment}"


class RotationAgent:
    """Runs one device-side rotation against an AWS IoT Jobs execution."""

    def __init__(
        self,
        endpoint,
        thing,
        cert,
        key,
        ca,
        telemetry_topic,
        request_rule="ws_rotation_request",
        pause=False,
        in_progress_timeout=15,
        connect_retries=3,
        connect_backoff=2.0,
        break_after_csr=False,
    ):
        self.endpoint = endpoint
        self.thing = thing
        self.cert = cert
        self.key = key
        self.ca = ca
        self.telemetry_topic = telemetry_topic
        self.request_rule = request_rule
        # Deterministic stand-in for "the device restarted before the reply
        # arrived": exit immediately after the certificate signing request is
        # sent, before waiting on the response. See request_certificate().
        self.break_after_csr = break_after_csr

        self.jobs_prefix = f"$aws/things/{thing}/jobs"
        # The certificate signing request goes out over BASIC INGEST — the
        # `$aws/rules/<ruleName>/` prefix hands the message straight to the rules
        # engine, skipping the publish/subscribe message broker and its messaging
        # charge. Nothing but the rule needs to see this message, so paying to
        # distribute it would buy nothing.
        #
        # Two consequences worth knowing. The rules engine strips that prefix
        # before the rule sees the topic, so the rule's `FROM` clause and its
        # `topic(2)` are unchanged — the thing name is still the second segment.
        # And a Basic Ingest topic is PUBLISH-ONLY and never reaches the broker,
        # so no other client (including the console MQTT test client) can observe
        # it. That is why the RESPONSE below stays an ordinary topic: the device
        # has to be able to subscribe to it.
        self.request_topic = (
            f"$aws/rules/{request_rule}/devices/{thing}/certificate/rotation/request"
        )
        self.response_topic = f"devices/{thing}/certificate/rotation/response"

        self.job_started = Future()
        self.cert_arrived = Future()
        self.connection = None

        # How hard to try before giving up on the replacement certificate. A
        # terminal reason code short-circuits this entirely (see connect()).
        self.connect_retries = max(1, connect_retries)
        self.connect_backoff = max(0.0, connect_backoff)

        # MQTT 5 lifecycle plumbing: connection outcome arrives on a callback
        # rather than a future, so the callbacks below bridge onto these.
        self._connect_result = None
        self._stopped = threading.Event()

        # Guided walkthrough state. Pausing is only useful on a terminal, so a
        # piped or redirected run degrades to a straight-through execution
        # instead of raising EOFError on the first prompt.
        self.pause = pause and sys.stdin.isatty()
        if pause and not self.pause:
            print(get_message("pause.not_a_terminal"))
        self.region = region_from_endpoint(endpoint)
        self.in_progress_timeout = in_progress_timeout
        self._in_progress_at = None
        self._terminal = False
        self.job_id = None
        self.execution_number = None

    # --- Verbose output --------------------------------------------------
    def _wire(self, kind, topic):
        """Print one MQTT wire event: direction marker plus topic."""
        print(get_message(f"wire.{kind}", topic))

    def _remaining_minutes(self):
        """Minutes left before AWS IoT Core marks the execution TIMED_OUT.

        Returns None once the execution has reached a terminal status, because
        a timeout can no longer apply and warning about one would mislead.
        """
        if self._in_progress_at is None or self._terminal:
            return None
        elapsed = (time.time() - self._in_progress_at) / 60
        return max(0, round(self.in_progress_timeout - elapsed, 1))

    def _pause_here(self, *lines):
        """Show what to go and observe, then wait for Enter (only with --pause)."""
        if not self.pause:
            return
        print()
        print(get_message("pause.rule"))
        for line in lines:
            print(line)
        remaining = self._remaining_minutes()
        if remaining is not None:
            print()
            print(get_message("pause.budget", remaining, self.in_progress_timeout))
        print(get_message("pause.rule"))
        try:
            input(get_message("pause.prompt"))
        except EOFError:
            # Stdin closed out from under an interactive run (e.g. the terminal
            # was redirected mid-flow). Degrade like a piped run: keep going,
            # just without further pauses.
            print()
            print(get_message("pause.disabled"))
            self.pause = False
        except KeyboardInterrupt:
            # A human pressed Ctrl-C on purpose. Unlike EOF, this means "stop",
            # so let it propagate instead of treating it as "continue without
            # pausing" - main() turns it into a clean exit.
            print()
            print(get_message("pause.aborted"))
            raise

    # --- MQTT plumbing ---------------------------------------------------
    def _on_message(self, data):
        """Handle every inbound publish.

        MQTT 5 delivers all inbound publishes to a single callback rather than
        one per subscription, so this dispatches on the topic itself.
        """
        packet = data.publish_packet
        topic = packet.topic
        payload = packet.payload
        try:
            if isinstance(payload, (bytes, bytearray)):
                payload = bytes(payload).decode()
            body = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return
        if topic.endswith("/start-next/accepted"):
            execution = body.get("execution")
            if execution and not self.job_started.done():
                self._wire("recv", topic)
                print(
                    get_message(
                        "wire.job_meta",
                        execution.get("jobId", "-"),
                        execution.get("executionNumber", "-"),
                        execution.get("status", "-"),
                    )
                )
                print(
                    get_message(
                        "wire.job_document",
                        json.dumps(execution.get("jobDocument", {}), sort_keys=True),
                    )
                )
                self.job_started.set_result(execution)
        elif topic == self.response_topic and not self.cert_arrived.done():
            self._wire("recv", topic)
            # The signed certificate is public, so it is safe to show — but it
            # is long, so print an identifiable head and its true length.
            print(
                get_message(
                    "wire.cert_detail",
                    body.get("certificateId", "-"),
                    shorten(body.get("certificatePem", "")),
                )
            )
            self.cert_arrived.set_result(body)

    def _stop_client(self):
        """Stop the current MQTT 5 client and wait for it to finish stopping."""
        if not self.connection:
            return
        try:
            self.connection.stop()
            self._stopped.wait(timeout=15)
        except Exception:  # noqa: BLE001 - teardown is best effort
            pass
        self.connection = None

    def _connect_once(self, cert_path, key_path):
        """Open one MQTT 5 connection. Raise ConnectFailed with the reason code.

        A fresh client per attempt on purpose: the MQTT 5 client reconnects on
        its own schedule, and this agent needs to make the retry decision itself
        based on the CONNACK reason code.
        """
        result = Future()
        self._connect_result = result
        self._stopped.clear()

        def on_success(data):
            if not result.done():
                result.set_result(data)

        def on_failure(data):
            reason_code = getattr(data.connack_packet, "reason_code", None)
            if not result.done():
                result.set_exception(
                    ConnectFailed(
                        reason_code_name(reason_code),
                        reason_code=reason_code,
                        cause=data.exception,
                    )
                )

        def on_stopped(data):  # noqa: ARG001 - dataclass is unused
            self._stopped.set()

        client = mqtt5_client_builder.mtls_from_path(
            endpoint=self.endpoint,
            cert_filepath=cert_path,
            pri_key_filepath=key_path,
            ca_filepath=self.ca,
            client_id=self.thing,
            # clean_session=False under MQTT 3.1.1 becomes "rejoin the session
            # once this client has connected successfully at least once", so a
            # transient drop mid-rotation keeps the jobs subscriptions.
            session_behavior=mqtt5.ClientSessionBehaviorType.REJOIN_POST_SUCCESS,
            session_expiry_interval_sec=3600,
            keep_alive_interval_sec=30,
            # This agent owns the retry decision, so keep the client's own
            # reconnect from racing it.
            min_reconnect_delay_ms=30000,
            max_reconnect_delay_ms=30000,
            # Without this the client defaults to FULL jitter - even with
            # min == max, that still draws uniformly in [0, 30000ms] on every
            # retry, undermining the fixed 30s cadence above. NONE makes the
            # client's own retry (which this agent does not rely on; see the
            # comment above) actually wait the full interval.
            retry_jitter_mode=mqtt5.ExponentialBackoffJitterMode.NONE,
            on_publish_received=self._on_message,
            on_lifecycle_connection_success=on_success,
            on_lifecycle_connection_failure=on_failure,
            on_lifecycle_stopped=on_stopped,
        )
        self.connection = client
        client.start()
        try:
            data = result.result(timeout=30)
        except ConnectFailed:
            self._stop_client()
            raise
        except TimeoutError as error:
            self._stop_client()
            raise ConnectFailed("no CONNACK within 30s", cause=error) from error
        finally:
            self._connect_result = None
        return data

    def connect(self, cert_path, key_path, which):
        """Connect, retrying transient failures but never an authorization one.

        This is where the MQTT 5 reason code does real work. ``NOT_AUTHORIZED``
        means the certificate cannot be used at all, so retrying would only burn
        the job execution's in-progress budget before the inevitable rollback.
        Any other failure gets ``--connect-retries`` attempts with backoff.
        """
        label = get_message(f"connect.{which}_certificate")
        last_error = None

        for attempt in range(1, self.connect_retries + 1):
            print(get_message("connect.attempt", self.thing, label))
            print(get_message("connect.detail", self.endpoint, self.thing, cert_path))
            try:
                data = self._connect_once(cert_path, key_path)
            except ConnectFailed as error:
                last_error = error
                if error.is_terminal:
                    # No retry: the broker has told us this will never work.
                    print(
                        get_message(
                            "connect.refused_terminal",
                            label,
                            reason_code_name(error.reason_code),
                        )
                    )
                    raise
                if attempt < self.connect_retries:
                    delay = round(self.connect_backoff * (2 ** (attempt - 1)), 1)
                    print(
                        get_message(
                            "connect.refused_retry",
                            label,
                            reason_code_name(error.reason_code),
                            attempt,
                            self.connect_retries,
                            delay,
                        )
                    )
                    time.sleep(delay)
                    continue
                print(
                    get_message(
                        "connect.refused_exhausted", label, self.connect_retries
                    )
                )
                raise
            else:
                connack = getattr(data, "connack_packet", None)
                print(get_message("connect.connected", label))
                print(
                    get_message(
                        "connect.connack",
                        reason_code_name(getattr(connack, "reason_code", None)),
                    )
                )
                return self.connection

        raise last_error  # pragma: no cover - the loop always returns or raises

    def update_job(self, job_id, status, details):
        """Report status and phase back over the reserved job topic.

        The publish is awaited and its PUBACK checked, so a status write that the
        broker refuses is reported rather than silently lost. A failure here is
        logged and not raised: by the time this runs the outcome is already
        decided, and losing the report must not mask it.
        """
        topic = f"{self.jobs_prefix}/{job_id}/update"
        payload = json.dumps({"status": status, "statusDetails": details})
        print(get_message("job.phase", status, details.get("phase", "-")))
        self._wire("pub", topic)
        print(get_message("wire.payload", payload))
        try:
            self._publish(topic, payload, timeout=15)
        except (PublishRefused, Exception) as error:  # noqa: BLE001
            print(get_message("job.update_failed", status, error))
        if status in ("SUCCEEDED", "FAILED", "REJECTED"):
            self._terminal = True
        time.sleep(1)

    def _publish(self, topic, payload, timeout=15):
        """Publish at QoS 1 and check the PUBACK reason code.

        Under MQTT 3.1.1 this check was impossible: its PUBACK carries only a
        packet identifier, so a refused publish was indistinguishable from a
        lost one and showed up only as a timeout.
        """
        completion = self.connection.publish(
            publish_packet=mqtt5.PublishPacket(
                topic=topic, payload=payload, qos=mqtt5.QoS.AT_LEAST_ONCE
            )
        ).result(timeout=timeout)
        puback = getattr(completion, "puback", None)
        if puback is not None and puback.reason_code != mqtt5.PubackReasonCode.SUCCESS:
            raise PublishRefused(
                reason_code_name(puback.reason_code), reason_code=puback.reason_code
            )
        return puback

    # --- Flow ------------------------------------------------------------
    def _subscribe_reply_topics(self):
        """Subscribe to the two topics this agent expects a reply on.

        Shared by the first claim in :meth:`take_job` and by the simulated
        reconnect in :meth:`request_certificate` — a fresh MQTT 5 connection
        carries no subscriptions of its own, so anything that reconnects mid
        rotation must redo this before it can see either reply.
        """
        granted = {
            mqtt5.SubackReasonCode.GRANTED_QOS_0,
            mqtt5.SubackReasonCode.GRANTED_QOS_1,
            mqtt5.SubackReasonCode.GRANTED_QOS_2,
        }
        for topic in (f"{self.jobs_prefix}/start-next/accepted", self.response_topic):
            suback = self.connection.subscribe(
                subscribe_packet=mqtt5.SubscribePacket(
                    subscriptions=[
                        mqtt5.Subscription(
                            topic_filter=topic, qos=mqtt5.QoS.AT_LEAST_ONCE
                        )
                    ]
                )
            ).result(timeout=30)
            # MQTT 5 reports a per-subscription reason code, so a refused
            # subscription fails here instead of looking like silence later.
            for code in suback.reason_codes:
                if code not in granted:
                    raise RuntimeError(
                        get_message(
                            "job.subscribe_refused", topic, reason_code_name(code)
                        )
                    )
            self._wire("sub", topic)

    def take_job(self, timeout):
        """Subscribe to the reply topics, claim the next execution, check its operation.

        Subscribing before publishing matters: the reply is delivered on the
        same connection that made the request, so a late subscriber misses it.

        ``start-next`` hands back whatever job is next for this thing, not
        necessarily a rotation, so the job document's ``operation`` is checked
        before anything else happens. A device that skipped this check would
        generate a key pair in response to a firmware-update job. AWS IoT Jobs
        defines ``REJECTED`` as the status for "an invalid or incompatible
        request", so that is what an unrecognised operation reports — and unlike
        ``FAILED`` it is not retryable, which is correct: retrying will not make
        this agent understand the operation.
        """
        print(get_message("job.subscribing"))
        self._subscribe_reply_topics()

        print(get_message("job.waiting", self.thing))
        claim_topic = f"{self.jobs_prefix}/start-next"
        self._publish(claim_topic, json.dumps({}), timeout=30)
        self._wire("pub", claim_topic)
        print(get_message("wire.payload", "{}"))
        execution = self.job_started.result(timeout=timeout)
        job_id = execution["jobId"]
        # Pin the exact execution the request is about. On a CONTINUOUS job the
        # same (jobId, thing) pair accumulates a new execution every time this
        # thing re-enrolls, so the handler cannot safely ask for "the" execution
        # by jobId and thing alone once a prior SUCCEEDED execution exists for
        # the same pair — it needs to know exactly which one this request means.
        self.execution_number = execution.get("executionNumber")
        print(get_message("job.taken", job_id))

        operation = (execution.get("jobDocument") or {}).get("operation")
        if operation != ROTATE_OPERATION:
            shown = operation or "(none)"
            print(get_message("job.wrong_operation", shown, ROTATE_OPERATION))
            self.update_job(
                job_id,
                "REJECTED",
                {"phase": "REJECTED", "reason": f"unsupported operation: {shown}"},
            )
            raise UnsupportedOperation(shown)

        self.job_id = job_id
        return job_id

    def generate_keypair(self):
        """Create a new private key and certificate signing request locally."""
        if shutil.which("openssl") is None:
            raise RuntimeError(get_message("keypair.openssl_missing"))

        new_key = f"{self.thing}.new.private.key"
        new_csr = f"{self.thing}.new.csr"
        print(get_message("keypair.generating"))
        try:
            subprocess.run(
                ["openssl", "genrsa", "-out", new_key, "2048"],
                check=True,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    "openssl", "req", "-new",
                    "-key", new_key,
                    "-out", new_csr,
                    "-subj", f"/CN={self.thing}",
                ],
                check=True,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(get_message("keypair.failed", error)) from error

        print(get_message("keypair.generated", new_key))
        print(get_message("keypair.detail", 2048, self.thing, new_csr))
        return new_key, new_csr

    def _send_signing_request(self, job_id, csr):
        """Publish the certificate signing request on the rotation-request topic.

        Includes ``executionNumber`` alongside ``jobId``. On a CONTINUOUS job the
        two together are what the handler needs to look up the exact execution
        this request is about — jobId alone is not enough once this thing has
        rotated more than once, because every rotation of every device shares
        the same jobId.
        """
        self._publish(
            self.request_topic,
            json.dumps(
                {"jobId": job_id, "executionNumber": self.execution_number, "csr": csr}
            ),
            timeout=30,
        )
        print(get_message("request.sent", self.request_topic))
        self._wire("pub", self.request_topic)
        print(get_message("wire.csr_payload", job_id, shorten(csr)))
        # Worth noticing in the trace: the request carries the certificate
        # signing request, never the private key.
        print(get_message("wire.key_not_sent"))

    def _await_certificate(self, timeout):
        """Block on the response topic for the signed certificate."""
        try:
            return self.cert_arrived.result(timeout=timeout)
        except TimeoutError:
            raise RuntimeError(get_message("request.timeout", timeout)) from None

    def _offer_disconnect_simulation(self, job_id, csr):
        """Offer to simulate a device that lost the certificate before installing it.

        Only reachable with ``--pause``. Returns ``True`` when the learner chose
        to simulate the disconnect — a fresh certificate is now on its way and
        the caller must wait for it again — or ``False`` to install the one
        already in hand.

        Choosing the simulation is not narration layered over an unchanged flow.
        This disconnects for real, reconnects on the certificate the device
        still holds (the new one was never installed), re-discovers the SAME
        job execution, and re-asks with the SAME certificate signing request —
        no new key pair, so the request carries the same public key the handler
        already signed for this rotation. That is what leads the handler to
        re-deliver the certificate it already issued instead of signing a
        second one.
        """
        print()
        print(get_message("pause.rule"))
        print(get_message("disconnect_choice.menu"))
        print(get_message("pause.rule"))
        try:
            choice = input(get_message("disconnect_choice.prompt"))
        except EOFError:
            print()
            print(get_message("pause.disabled"))
            self.pause = False
            return False
        except KeyboardInterrupt:
            print()
            print(get_message("pause.aborted"))
            raise

        if choice.strip() != "2":
            return False

        print(get_message("disconnect_choice.disconnecting"))
        self._stop_client()
        time.sleep(2)
        self.connect(self.cert, self.key, "old")
        print(get_message("disconnect_choice.reconnected"))

        print(get_message("job.subscribing"))
        self._subscribe_reply_topics()

        print(get_message("job.waiting", self.thing))
        # A fresh Future for each: the previous ones are already done() and
        # cannot be resolved a second time.
        self.job_started = Future()
        claim_topic = f"{self.jobs_prefix}/start-next"
        self._publish(claim_topic, json.dumps({}), timeout=30)
        self._wire("pub", claim_topic)
        print(get_message("wire.payload", "{}"))
        execution = self.job_started.result(timeout=30)
        # Refresh the pinned execution number from what start-next actually
        # returned, rather than assuming it is unchanged - re-claiming the same
        # IN_PROGRESS execution is the expected outcome, but the request below
        # should reflect what the device was just told, not what it assumed.
        self.execution_number = execution.get("executionNumber")
        print(
            get_message(
                "disconnect_choice.rediscovered",
                execution.get("status", "-"),
                json.dumps(execution.get("statusDetails", {}), sort_keys=True),
            )
        )

        self.cert_arrived = Future()
        print(get_message("disconnect_choice.reasking"))
        self._send_signing_request(job_id, csr)
        return True

    def request_certificate(self, job_id, csr_path, timeout):
        """Publish the certificate signing request and wait for the signed reply.

        With ``--pause``, the moment the certificate arrives this offers a
        choice instead of installing it right away — see
        :meth:`_offer_disconnect_simulation` and the module docstring.

        With ``--break-after-csr``, this raises :class:`BreakAfterCsr` right
        after the request is sent, before waiting for anything back — a
        deterministic stand-in for a device that restarts in that exact gap,
        in place of timing a Ctrl-C against the network.
        """
        with open(csr_path, "r", encoding="utf-8") as handle:
            csr = handle.read()

        self._send_signing_request(job_id, csr)

        if self.break_after_csr:
            raise BreakAfterCsr(job_id)

        answer = self._await_certificate(timeout)
        print(get_message("request.received", answer["certificateId"]))

        if self.pause and self._offer_disconnect_simulation(job_id, csr):
            answer = self._await_certificate(timeout)
            print(get_message("request.received", answer["certificateId"]))

        new_cert = f"{self.thing}.new.cert.pem"
        print(get_message("cutover.installing", new_cert))
        with open(new_cert, "w", encoding="utf-8") as handle:
            handle.write(answer["certificatePem"])
        return new_cert, answer["certificateId"]

    def _abandon_cutover(self, job_id, reason, rollback):
        """Give up on the new certificate and leave the device online.

        The old certificate was never retired — that is the whole point of the
        ordering — so falling back to it is always available. ``reason`` is
        recorded on the job execution so an operator can tell a refused connect
        from a refused publish without reading the device's logs.
        """
        if rollback:
            # Reconnect on the credential that still works BEFORE reporting, so
            # the status write travels over a connection that can carry it.
            self._stop_client()
            self.connect(self.cert, self.key, "old")
            self.update_job(
                job_id, "FAILED", {"phase": "CUTOVER_FAILED", "reason": reason}
            )
            print(get_message("cutover.rolled_back"))
        else:
            self.update_job(
                job_id, "FAILED", {"phase": "CUTOVER_FAILED", "reason": reason}
            )
        print(get_message("result.failed"))
        return False

    def cutover(self, job_id, new_cert, new_key, certificate_id, rollback):
        """Reconnect with the new certificate and prove it is authorized.

        Two failures are handled, and they mean different things:

        * the new certificate cannot **connect** — no policy is attached to it,
          so ``iot:Connect`` is denied;
        * the new certificate connects but cannot **publish** — a policy is
          attached, but it does not authorize the work this device does.

        Either way the device returns to the certificate it started with and
        reports ``FAILED``. Nothing is retired, so a failed rotation is a retry
        rather than a field visit.
        """
        self._stop_client()
        print(get_message("cutover.reconnecting"))

        # Failure 1: the replacement certificate cannot even connect.
        try:
            self.connect(new_cert, new_key, "new")
        except ConnectFailed as error:
            print(get_message("cutover.connect_failed", reason_code_name(error.reason_code)))
            return self._abandon_cutover(
                job_id,
                f"new certificate could not connect: {reason_code_name(error.reason_code)}",
                rollback,
            )

        # Failure 2: it connects, but it is not authorized to do real work. This
        # is why the proof is a publish and not merely a connection.
        print(get_message("cutover.proving", self.telemetry_topic))
        telemetry = json.dumps(
            {
                "thing": self.thing,
                "rotated": True,
                "certificateId": certificate_id,
            }
        )
        self._wire("pub", self.telemetry_topic)
        print(get_message("wire.payload", telemetry))
        try:
            self._publish(self.telemetry_topic, telemetry, timeout=15)
        except PublishRefused as error:
            print(get_message("cutover.publish_refused", reason_code_name(error.reason_code)))
            return self._abandon_cutover(
                job_id,
                f"new certificate could not publish: {reason_code_name(error.reason_code)}",
                rollback,
            )
        except Exception as error:  # noqa: BLE001 - report any publish failure
            print(get_message("cutover.publish_failed", error))
            return self._abandon_cutover(
                job_id, f"new certificate could not publish: {error}", rollback
            )

        print(get_message("cutover.proved"))
        # Report the phase and nothing else. The device does NOT tell the backend
        # which certificate to keep — that is a backend decision, recorded in the
        # rotation shadow the device cannot write. See the module docstring.
        self.update_job(job_id, "SUCCEEDED", {"phase": "INSTALLED"})
        print(get_message("result.succeeded"))
        print(get_message("result.summary", self.thing, certificate_id))
        return True

    def run(self, job_timeout, cert_timeout, rollback):
        """Execute the whole device-side rotation."""
        self.connect(self.cert, self.key, "old")
        try:
            job_id = self.take_job(job_timeout)
        except TimeoutError:
            print(get_message("job.none"))
            self._stop_client()
            return False
        except UnsupportedOperation:
            # Already reported REJECTED on the execution. Nothing was generated and
            # nothing was changed, so there is nothing to roll back.
            self._stop_client()
            return False

        self._in_progress_at = time.time()
        self.update_job(job_id, "IN_PROGRESS", {"phase": "INITIATED"})

        # Observation 1: the execution has moved QUEUED -> IN_PROGRESS.
        self._pause_here(
            get_message("pause.job_taken.what"),
            get_message(
                "pause.job_taken.console", console_url("jobhub", self.region)
            ),
            get_message("pause.job_taken.cli", job_id, self.thing),
        )

        new_key, new_csr = self.generate_keypair()
        new_cert, certificate_id = self.request_certificate(
            job_id, new_csr, cert_timeout
        )

        # Observation 2: the overlap window. The handler has attached the new
        # certificate while the current one is still attached and active, so
        # the thing has TWO principals right now. This is the whole reason the
        # rotation is safe, and it is only visible here.
        self._pause_here(
            get_message("pause.overlap.what"),
            get_message(
                "pause.overlap.console", console_url("thinghub", self.region)
            ),
            get_message("pause.overlap.cli", self.thing),
            get_message("pause.overlap.expect", certificate_id[-12:]),
        )

        ok = self.cutover(job_id, new_cert, new_key, certificate_id, rollback)

        # Observation 3: retirement is deferred, not immediate.
        if ok:
            self._pause_here(
                get_message("pause.retired.what"),
                get_message(
                    "pause.retired.console", console_url("certificatehub", self.region)
                ),
                get_message("pause.retired.cli"),
                get_message("pause.retired.scheduler"),
            )
        self._stop_client()
        return ok


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Run the device half of a backend-driven certificate rotation."
    )
    parser.add_argument("--endpoint", required=True, help="iot:Data-ATS endpoint")
    parser.add_argument("--thing-name", required=True, help="Thing being rotated")
    parser.add_argument("--cert", required=True, help="Current certificate PEM")
    parser.add_argument("--key", required=True, help="Current private key")
    parser.add_argument("--ca", required=True, help="Amazon root CA file")
    parser.add_argument(
        "--telemetry-topic",
        default="anycompany/telemetry",
        help="Topic used to prove the new certificate is authorized",
    )
    parser.add_argument(
        "--request-rule",
        default="ws_rotation_request",
        help=(
            "Name of the topic rule that receives the certificate signing request. "
            "The request is published over Basic Ingest "
            "($aws/rules/<rule>/devices/<thing>/certificate/rotation/request) so it "
            "reaches the rules engine without a messaging charge. Must match the "
            "rule you created, or the publish is dropped and RuleNotFound is emitted"
        ),
    )
    parser.add_argument(
        "--job-timeout",
        type=int,
        default=30,
        help="Seconds to wait for a pending job execution",
    )
    parser.add_argument(
        "--cert-timeout",
        type=int,
        default=60,
        help="Seconds to wait for the signed certificate",
    )
    parser.add_argument(
        "--no-rollback",
        action="store_true",
        help="Do not fall back to the current certificate when the cutover fails",
    )
    parser.add_argument(
        "--connect-retries",
        type=int,
        default=3,
        help=(
            "Attempts to connect with the new certificate before giving up. An "
            "authorization failure (CONNACK NOT_AUTHORIZED) is never retried, "
            "because retrying cannot change it"
        ),
    )
    parser.add_argument(
        "--connect-backoff",
        type=float,
        default=2.0,
        help="Base seconds between connect attempts; doubles after each attempt",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help=(
            "Pause at each observable step so you can inspect the job execution, "
            "the certificate overlap and the deferred retirement before continuing"
        ),
    )
    parser.add_argument(
        "--break-after-csr",
        action="store_true",
        help=(
            "Exit immediately after sending the certificate signing request, "
            "before waiting for the signed reply — a deterministic stand-in for "
            "a device that restarts in that gap. Re-run WITHOUT this flag "
            "afterwards: a fresh process generates a new key pair and asks "
            "again, which is what makes the handler sign a second certificate "
            "(`resigning`) instead of re-delivering the first one"
        ),
    )
    parser.add_argument(
        "--in-progress-timeout",
        type=int,
        default=15,
        help=(
            "Minutes the job allows an execution to stay IN_PROGRESS; used to warn "
            "how long you may pause before the execution is marked TIMED_OUT"
        ),
    )
    return parser.parse_args()


def main():
    args = parse_arguments()

    # Load the localized message catalog once, before any user-facing print.
    # (Placed after argument parsing so --help stays free of the language menu.)
    global messages
    messages = load_messages("rotate_certificate", get_language())

    agent = RotationAgent(
        endpoint=args.endpoint,
        thing=args.thing_name,
        cert=args.cert,
        key=args.key,
        ca=args.ca,
        telemetry_topic=args.telemetry_topic,
        request_rule=args.request_rule,
        pause=args.pause,
        in_progress_timeout=args.in_progress_timeout,
        connect_retries=args.connect_retries,
        connect_backoff=args.connect_backoff,
        break_after_csr=args.break_after_csr,
    )
    try:
        ok = agent.run(
            job_timeout=args.job_timeout,
            cert_timeout=args.cert_timeout,
            rollback=not args.no_rollback,
        )
    except ConnectFailed as error:
        # The device could not connect with the certificate it already holds, so
        # there is no rotation to attempt and nothing to roll back to.
        print(get_message("connect.failed", get_message("connect.old_certificate"), error))
        agent._stop_client()
        sys.exit(1)
    except BreakAfterCsr as error:
        # Requested via --break-after-csr: the request is already on its way,
        # so exit cleanly without waiting for a reply or rolling anything back.
        # The execution stays exactly where it is (IN_PROGRESS); re-running
        # WITHOUT this flag generates a fresh key pair and asks again.
        job_id = error.args[0]
        print()
        print(get_message("break_after_csr.exit", job_id))
        agent._stop_client()
        sys.exit(0)
    except KeyboardInterrupt:
        # Ctrl-C during a --pause stop. The job execution stays wherever it was
        # left (IN_PROGRESS, most likely) - re-running the script claims the
        # same execution again rather than starting a new one.
        print()
        print(get_message("pause.exit"))
        agent._stop_client()
        sys.exit(130)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
