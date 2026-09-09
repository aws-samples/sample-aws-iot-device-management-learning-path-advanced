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
completes an *authorized publish* with the new certificate before reporting
``SUCCEEDED``, because a successful connection alone is not evidence: a
connection can succeed while the policy attachment is missing, and you would
not discover it until the device tried to publish — after the old certificate
had already been retired. If the publish fails, the agent falls back to the
current certificate (never retired) and reports ``FAILED``, leaving the device
online for a retry.

The private key generated here never leaves the device. Only the certificate
signing request is transmitted, which is why a message the device misses costs
a recoverable certificate rather than an unrecoverable key.

Phases written to the job execution
-----------------------------------
The job execution ``status`` field is a fixed enumeration, so the section's own
phase markers live in ``statusDetails`` alongside it::

    IN_PROGRESS  phase=INITIATED       job taken, about to generate a key pair
    IN_PROGRESS  phase=CERT_READY      (written by the handler) certificate signed
    SUCCEEDED    phase=INSTALLED       new certificate installed and proven
    FAILED       phase=CUTOVER_FAILED  new certificate unusable, rolled back

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
import time
from concurrent.futures import Future

# --- Repository path wiring (import shared constructs) --------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "i18n"))

from awscrt import mqtt  # noqa: E402
from awsiot import mqtt_connection_builder  # noqa: E402

from language_selector import get_language  # noqa: E402
from loader import load_messages  # noqa: E402

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
        pause=False,
        in_progress_timeout=15,
    ):
        self.endpoint = endpoint
        self.thing = thing
        self.cert = cert
        self.key = key
        self.ca = ca
        self.telemetry_topic = telemetry_topic

        self.jobs_prefix = f"$aws/things/{thing}/jobs"
        self.request_topic = f"devices/{thing}/certificate/rotation/request"
        self.response_topic = f"devices/{thing}/certificate/rotation/response"

        self.job_started = Future()
        self.cert_arrived = Future()
        self.connection = None

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
        except (EOFError, KeyboardInterrupt):
            print()
            print(get_message("pause.disabled"))
            self.pause = False

    # --- MQTT plumbing ---------------------------------------------------
    def _on_message(self, topic, payload, **kwargs):
        try:
            body = json.loads(payload.decode())
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

    def connect(self, cert_path, key_path, which):
        label = get_message(f"connect.{which}_certificate")
        print(get_message("connect.attempt", self.thing, label))
        print(get_message("connect.detail", self.endpoint, self.thing, cert_path))
        connection = mqtt_connection_builder.mtls_from_path(
            endpoint=self.endpoint,
            cert_filepath=cert_path,
            pri_key_filepath=key_path,
            ca_filepath=self.ca,
            client_id=self.thing,
            clean_session=False,
            keep_alive_secs=30,
        )
        try:
            connection.connect().result()
        except Exception as error:  # noqa: BLE001 - surface any handshake failure
            raise RuntimeError(get_message("connect.failed", label, error)) from error
        print(get_message("connect.connected", label))
        self.connection = connection
        return connection

    def update_job(self, job_id, status, details):
        """Report status and phase back over the reserved job topic."""
        topic = f"{self.jobs_prefix}/{job_id}/update"
        payload = json.dumps({"status": status, "statusDetails": details})
        self.connection.publish(
            topic=topic, payload=payload, qos=mqtt.QoS.AT_LEAST_ONCE
        )
        print(get_message("job.phase", status, details.get("phase", "-")))
        self._wire("pub", topic)
        print(get_message("wire.payload", payload))
        if status in ("SUCCEEDED", "FAILED"):
            self._terminal = True
        time.sleep(1)

    # --- Flow ------------------------------------------------------------
    def take_job(self, timeout):
        """Subscribe to the reply topics, then claim the next job execution.

        Subscribing before publishing matters: the reply is delivered on the
        same connection that made the request, so a late subscriber misses it.
        """
        print(get_message("job.subscribing"))
        for topic in (f"{self.jobs_prefix}/start-next/accepted", self.response_topic):
            self.connection.subscribe(
                topic=topic, qos=mqtt.QoS.AT_LEAST_ONCE, callback=self._on_message
            )[0].result()
            self._wire("sub", topic)

        print(get_message("job.waiting", self.thing))
        claim_topic = f"{self.jobs_prefix}/start-next"
        self.connection.publish(
            topic=claim_topic,
            payload=json.dumps({}),
            qos=mqtt.QoS.AT_LEAST_ONCE,
        )
        self._wire("pub", claim_topic)
        print(get_message("wire.payload", "{}"))
        execution = self.job_started.result(timeout=timeout)
        print(get_message("job.taken", execution["jobId"]))
        self.job_id = execution["jobId"]
        return execution["jobId"]

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

    def request_certificate(self, job_id, csr_path, timeout):
        """Publish the certificate signing request and wait for the signed reply."""
        with open(csr_path, "r", encoding="utf-8") as handle:
            csr = handle.read()

        self.connection.publish(
            topic=self.request_topic,
            payload=json.dumps({"jobId": job_id, "csr": csr}),
            qos=mqtt.QoS.AT_LEAST_ONCE,
        )
        print(get_message("request.sent", self.request_topic))
        self._wire("pub", self.request_topic)
        print(get_message("wire.csr_payload", job_id, shorten(csr)))
        # Worth noticing in the trace: the request carries the certificate
        # signing request, never the private key.
        print(get_message("wire.key_not_sent"))

        try:
            answer = self.cert_arrived.result(timeout=timeout)
        except TimeoutError:
            raise RuntimeError(get_message("request.timeout", timeout)) from None

        print(get_message("request.received", answer["certificateId"]))
        new_cert = f"{self.thing}.new.cert.pem"
        print(get_message("cutover.installing", new_cert))
        with open(new_cert, "w", encoding="utf-8") as handle:
            handle.write(answer["certificatePem"])
        return new_cert, answer["certificateId"]

    def cutover(self, job_id, new_cert, new_key, certificate_id, rollback):
        """Reconnect with the new certificate and prove it is authorized."""
        self.connection.disconnect().result()
        print(get_message("cutover.reconnecting"))
        self.connect(new_cert, new_key, "new")

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
            self.connection.publish(
                topic=self.telemetry_topic,
                payload=telemetry,
                qos=mqtt.QoS.AT_LEAST_ONCE,
            ).result(timeout=15)
        except Exception as error:  # noqa: BLE001 - report any publish failure
            print(get_message("cutover.publish_failed", error))
            if not rollback:
                self.update_job(job_id, "FAILED", {"phase": "CUTOVER_FAILED"})
                print(get_message("result.failed"))
                return False
            # Fall back to the certificate that still works. It was never
            # retired, which is the whole point of the ordering.
            self.connection.disconnect().result()
            self.connect(self.cert, self.key, "old")
            self.update_job(job_id, "FAILED", {"phase": "CUTOVER_FAILED"})
            print(get_message("cutover.rolled_back"))
            print(get_message("result.failed"))
            return False

        print(get_message("cutover.proved"))
        self.update_job(
            job_id,
            "SUCCEEDED",
            {"phase": "INSTALLED", "newCertificateId": certificate_id},
        )
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
            self.connection.disconnect().result()
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
        self.connection.disconnect().result()
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
        "--pause",
        action="store_true",
        help=(
            "Pause at each observable step so you can inspect the job execution, "
            "the certificate overlap and the deferred retirement before continuing"
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
        pause=args.pause,
        in_progress_timeout=args.in_progress_timeout,
    )
    ok = agent.run(
        job_timeout=args.job_timeout,
        cert_timeout=args.cert_timeout,
        rollback=not args.no_rollback,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
