# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Certificate-rotation handler — the backend half of Module 6 rotation.

Backend handler for Module 6, "Certificate Rotation" (design section 2.12). It
performs the cloud-side identity swap a device cannot perform for itself: it
signs the device's certificate signing request, attaches the resulting
certificate, and later retires the superseded one.

The rotation invariant this file enforces
-----------------------------------------
**Nothing is detached or deactivated until the device has reported SUCCEEDED.**
Both certificates are attached to the thing during an *overlap window*, so a
device whose new certificate turns out to be unusable falls back to a
credential that still works. Deactivation (reversible) happens at cutover;
deletion (irreversible) is deferred behind a one-time Amazon EventBridge
Scheduler timer.

Two entry points, both invoked by AWS IoT topic rules
-----------------------------------------------------
1. A certificate signing request arriving on
   ``devices/<thing>/certificate/rotation/request`` — verify, sign, record the
   new certificate id, attach, deliver.
2. A job-execution terminal event on
   ``$aws/events/jobExecution/<jobId>/succeeded`` — retire the superseded
   certificate (deactivate now, delete later).

Three checks before signing anything
------------------------------------
1. The requesting certificate is attached to the named thing **and** ``ACTIVE``.
2. An ``IN_PROGRESS`` rotation job execution exists for that thing (without
   this the topic is a certificate-minting service for any authenticated
   device).
3. The certificate signing request asks for the identity it is entitled to:
   the subject common name matches the thing name, **and** the public key is
   not a reuse of the one in the certificate being replaced. A rotation that
   reuses the old key pair is not a rotation. ``CreateCertificateFromCsr``
   validates neither for you.

Caller identity comes from the **rule SQL** (``principal()`` and the topic
segment), never from the message payload — the payload is attacker-controlled.

Two IAM prefixes, not one
-------------------------
AWS IoT Jobs splits across two IAM prefixes and this function needs both:
reading the job execution is **control plane** (``iot:DescribeJobExecution``);
writing the execution status is **data plane**
(``iotjobsdata:UpdateJobExecution``). Using ``iot:`` for the write does not
authorize the call. Each prefix has its own ``DescribeJobExecution``, so the two
are not interchangeable in either direction.

Deployment
----------
This function is deployed into the pre-created base-infrastructure function
name with bundled dependencies, because the certificate signing request parser
(``cryptography``) is not in the AWS Lambda runtime::

    rm -rf build && mkdir build
    python3 -m pip install --quiet --target ./build \\
        --platform manylinux2014_x86_64 --implementation cp \\
        --python-version 3.12 --only-binary=:all: cryptography
    cp lambdas/rotation_handler.py build/index.py
    cd build && zip -qr ../rotation_handler.zip . && cd ..

The copy target is ``index.py`` because the pre-created function's entry point
is ``index.handler``. Packaging it under any other filename deploys cleanly and
then fails at invoke with a module import error.

    aws lambda update-function-code \\
        --function-name ws-aws-iot-dm-adv-prov-rotation-handler \\
        --zip-file fileb://rotation_handler.zip

Note on localization: this module is **not** localized. Like the other
``lambdas/`` handlers in this repository, its output is operator-facing
Amazon CloudWatch Logs rather than learner-facing terminal output, so it does
not use the ``i18n/`` catalog (see ``i18n/README.md``).
"""

import datetime
import json
import os

import boto3

ROTATION_GROUP = os.environ.get(
    "ROTATION_THING_GROUP", "ws-aws-iot-dm-adv-prov-rotation"
)
SCHEDULER_ROLE_ARN = os.environ.get("REVOKE_SCHEDULER_ROLE_ARN", "")
GRACE_MINUTES = int(os.environ.get("REVOKE_GRACE_MINUTES", "10"))

# The deferred-deletion timer invokes THIS function rather than calling
# iot:DeleteCertificate directly, so this marker is what tells the router which
# entry point a scheduled invocation belongs to. See _create_schedule.
REVOKE_OPERATION = "revokeCertificate"

# Backend-authored rotation state lives in a dedicated NAMED SHADOW, never in the
# job execution's statusDetails. Two reasons, and both are load-bearing:
#
#   1. statusDetails is REPLACED wholesale on every UpdateJobExecution, not
#      merged (verified empirically). The device writes that map too, so anything
#      the backend recorded there is erased by the device's next status report.
#   2. Which certificate survives a rotation is a BACKEND decision. Reading it
#      from a map the device writes would let a device choose which of its own
#      credentials gets destroyed — the same mistake check 1 exists to avoid.
#
# A named shadow fixes both. It is scoped per shadow name on BOTH planes
# (topic/$aws/things/<thing>/shadow/name/<name>/... for MQTT, and the
# thing/<thing>/<shadowName> resource ARN for the API), the device policy in this
# module grants no shadow permission at all, and AWS IoT policies are
# default-deny. It also MERGES on update, which is the opposite of statusDetails
# and the reason one record per thing can accumulate everything a sweeper needs.
ROTATION_SHADOW = os.environ.get("ROTATION_SHADOW_NAME", "ws-rotation")

iot = boto3.client("iot")
scheduler = boto3.client("scheduler")

_data = None
# This function's own ARN, captured from the Lambda context on first invocation
# so a schedule can be pointed back at it.
_self_arn = None


def data_client():
    """Client for publishing to devices (endpoint resolved once per container)."""
    global _data
    if _data is None:
        endpoint = iot.describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]
        _data = boto3.client("iot-data", endpoint_url=f"https://{endpoint}")
    return _data


# --- Paginated list helpers ----------------------------------------------
# Both of these AWS IoT list calls are paginated, and reading only the first
# page would be a silent CORRECTNESS bug here, not a cosmetic one:
#
#   * a truncated policy list copies only SOME of the old certificate's policies
#     onto the new one, producing a replacement that connects but is not
#     authorized to do the device's work;
#   * a truncated principal list leaves a superseded certificate attached and
#     ACTIVE after retirement — precisely what this flow exists to prevent, and
#     it would quietly falsify the claim that retirement removes *every*
#     certificate that is not the new one.
#
# Both operations have official boto3 paginators, so use them rather than
# hand-rolling a marker loop (their token names differ: nextToken for one,
# marker/nextMarker for the other).


def all_thing_principals(thing_name):
    """Every principal attached to a thing, across all pages."""
    principals = []
    for page in iot.get_paginator("list_thing_principals").paginate(
        thingName=thing_name
    ):
        principals.extend(page.get("principals", []))
    return principals


def all_attached_policies(target_arn):
    """Every policy attached to a target (certificate), across all pages."""
    policies = []
    for page in iot.get_paginator("list_attached_policies").paginate(
        target=target_arn
    ):
        policies.extend(page.get("policies", []))
    return policies


# --- The backend-only rotation record ------------------------------------
# Written and read by this function only. See ROTATION_SHADOW above for why it is
# a named shadow rather than the job execution's statusDetails.
#
# The ``state.reported`` wrapper is required: a bare ``{"certificateId": ...}``
# payload is rejected with "Missing required node: state". Writing ``reported``
# from the cloud inverts the usual convention (devices report, applications
# desire), and that is deliberate — this shadow has no device side at all, so
# there is no desired/reported delta to compute. AWS's own reserved ``$package``
# named shadow holds cloud-written data the same way.


def record_rotation(thing, fields):
    """Merge fields into the thing's rotation shadow.

    A shadow update MERGES into the existing document, so each call adds to the
    record instead of replacing it — which is exactly what statusDetails does not
    do, and the whole reason this state lives here.
    """
    data_client().update_thing_shadow(
        thingName=thing,
        shadowName=ROTATION_SHADOW,
        payload=json.dumps({"state": {"reported": fields}}),
    )


def read_rotation(thing):
    """Read the rotation record, or ``{}`` if this thing has none yet."""
    client = data_client()
    try:
        response = client.get_thing_shadow(
            thingName=thing, shadowName=ROTATION_SHADOW
        )
    except client.exceptions.ResourceNotFoundException:
        # No shadow yet: this thing has never been through a rotation.
        return {}
    document = json.loads(response["payload"].read())
    return document.get("state", {}).get("reported", {}) or {}


def _certificate_matches_key(certificate_id, csr_key):
    """Does an already-issued certificate carry the public key in this request?

    Guards the re-delivery path. A device that restarted has generated a NEW key
    pair, so handing it the certificate issued for the PREVIOUS key would give it
    a credential its private key cannot use. Returning ``False`` sends the caller
    down the signing path instead.

    A certificate that has since been deleted, or that cannot be parsed, is
    treated as "does not match": signing again is the safe answer, because the
    retirement loop sweeps whatever is superseded.
    """
    try:
        pem = iot.describe_certificate(certificateId=certificate_id)[
            "certificateDescription"
        ]["certificatePem"]
        return certificate_public_key(pem) == csr_key
    except iot.exceptions.ResourceNotFoundException:
        return False
    except (ImportError, ValueError, TypeError):
        return False


def handler(event, context):
    """Route to one of three entry points based on the event shape.

    Order matters. The revoke check comes first because it is the narrowest and
    most explicit: only Amazon EventBridge Scheduler sends ``operation`` =
    ``revokeCertificate``, and that payload is written by this same function in
    ``_create_schedule``. Everything that is not a recognised event shape falls
    through to the signing path, which is the only one that validates its caller.
    """
    print(json.dumps({"received": event}))

    # The Lambda needs its own ARN to point a schedule back at itself. Stash it
    # once per invocation rather than reconstructing it from Region and account.
    global _self_arn
    if _self_arn is None and context is not None:
        _self_arn = getattr(context, "invoked_function_arn", None)

    if event.get("operation") == REVOKE_OPERATION:
        return delete_superseded_certificate(event)
    if event.get("eventType") == "JOB_EXECUTION":
        return retire_old_certificate(event)
    return issue_new_certificate(event)


# ---------------------------------------------------------------------------
# Entry point 1 — sign a certificate signing request
# ---------------------------------------------------------------------------
def issue_new_certificate(event):
    """Verify the request, sign it, attach the result, and deliver it."""
    thing = event["thingName"]  # from topic(2) in the rule SQL
    caller_cert_id = event["callerCertificateId"]  # from principal() in the rule SQL
    csr = event["csr"]

    # A request with no jobId cannot be part of a sanctioned rotation, and there is
    # no execution to record a denial on — so refuse it here, before any lookup.
    job_id = event.get("jobId")
    if not job_id:
        return refuse(thing, "no jobId in the rotation request")

    # Check 1 — the caller must be a certificate attached to THIS thing, and ACTIVE.
    # Keep the whole description: check 3 needs its PEM to compare public keys, and
    # re-reading it would be a second API call for data already in hand.
    principals = all_thing_principals(thing)
    caller_arn = next((p for p in principals if p.endswith(f"/{caller_cert_id}")), None)
    if caller_arn is None:
        return deny(thing, job_id, "requesting certificate is not attached to this thing")

    caller_cert = iot.describe_certificate(certificateId=caller_cert_id)[
        "certificateDescription"
    ]
    if caller_cert["status"] != "ACTIVE":
        return deny(
            thing, job_id, f"requesting certificate is {caller_cert['status']}, not ACTIVE"
        )

    # Check 2 — a rotation must actually be in progress for this thing. An unknown
    # jobId is refused rather than denied, for the same reason as a missing one:
    # there is no execution to write the denial to.
    try:
        execution = iot.describe_job_execution(jobId=job_id, thingName=thing)["execution"]
    except iot.exceptions.ResourceNotFoundException:
        return refuse(thing, f"no job execution {job_id} for this thing")
    if execution["status"] != "IN_PROGRESS":
        return deny(
            thing, job_id, f"no rotation in progress (status {execution['status']})"
        )

    # Check 3 — the certificate signing request must ask for this thing's identity.
    # This is read BEFORE the idempotency guard below, because that guard needs the
    # request's public key to decide whether a re-delivery is even valid.
    try:
        subject, csr_key = csr_subject_and_key(csr)
        current_key = certificate_public_key(caller_cert["certificatePem"])
    except ImportError:
        # Fail closed: a handler that cannot read the request cannot confirm it is
        # for the identity it is entitled to, so it must not sign.
        return deny(thing, job_id, "handler cannot parse the certificate signing request")
    except (ValueError, TypeError) as error:
        # A malformed or non-PEM certificate signing request. Catch it explicitly:
        # letting it escape would leave the execution IN_PROGRESS until it timed
        # out, with the denial recorded nowhere. Fail closed, and say why.
        return deny(
            thing, job_id, f"malformed certificate signing request: {type(error).__name__}"
        )
    if f"CN={thing}" not in subject:
        return deny(
            thing,
            job_id,
            "certificate signing request subject does not match the thing name",
        )

    # Idempotency — if a certificate was already signed for THIS rotation AND FOR
    # THIS KEY, re-deliver it instead of minting a second one.
    #
    # Read from the rotation shadow, NOT from statusDetails. That is what makes
    # this guard reachable on the path it exists for. A device that reboots
    # mid-rotation re-claims the same IN_PROGRESS execution (start-next returns
    # IN_PROGRESS executions first) and writes its own phase marker, which
    # REPLACES statusDetails wholesale — so an id kept there would already be
    # gone by the time we looked.
    #
    # TWO conditions, and both are load-bearing:
    #
    #   * ``supersedes == caller_cert_id`` — the record belongs to THIS rotation.
    #     Not jobId: the campaign is one CONTINUOUS job, so its jobId is identical
    #     for every rotation of every device and cannot tell them apart. The caller
    #     certificate can, because a rotation starts from a different certificate
    #     than the last one did, by construction. Without this, the second rotation
    #     would re-deliver the FIRST rotation's certificate — the device would "cut
    #     over" to the certificate it already holds and report success, and rotation
    #     would silently become a permanent no-op.
    #
    #   * the recorded certificate must carry THIS request's public key. A device
    #     that restarts generates a FRESH key pair, so re-delivering the earlier
    #     certificate would hand it a credential bound to a private key it has
    #     already discarded — the certificate would install and then fail the TLS
    #     handshake. When the key differs we fall through and sign a new
    #     certificate, overwriting the record; the superseded one is swept by the
    #     retirement loop, which retires everything that is not the kept id.
    #
    # So this guard now fires for exactly the case it is correct for: the SAME
    # request arriving more than once (a QoS 1 redelivery, or the topic rule
    # invoking twice), where the key material is identical.
    record = read_rotation(thing)
    existing = record.get("certificateId")
    if existing and record.get("supersedes") == caller_cert_id:
        if _certificate_matches_key(existing, csr_key):
            print(json.dumps({"redelivering": existing, "thing": thing}))
            deliver(thing, existing)
            return {"redelivered": existing}
        print(
            json.dumps(
                {
                    "resigning": thing,
                    "reason": "request carries a different key than the recorded certificate",
                    "superseded": existing,
                }
            )
        )

    # Rotating onto the same key pair would issue a new certificate over an
    # unchanged private key — new expiry, same secret, none of the benefit.
    if csr_key == current_key:
        return deny(
            thing,
            job_id,
            "certificate signing request reuses the current public key",
        )

    # Sign it. The new certificate is ACTIVE but not yet attached to anything.
    created = iot.create_certificate_from_csr(
        certificateSigningRequest=csr, setAsActive=True
    )
    new_id = created["certificateId"]
    new_arn = created["certificateArn"]

    # Record the id BEFORE delivery. If delivery fails, the record is still here,
    # so the device can ask again and we re-deliver rather than sign again.
    #
    # Note what goes where, because the split IS the design. The certificate id
    # and the id it supersedes are BACKEND decisions, so they go in the shadow the
    # device cannot write. ``phase`` is the DEVICE's own progress marker, so it
    # stays in statusDetails where the device legitimately overwrites it — and
    # because phase is now the only key there, wholesale replacement can no longer
    # lose anything.
    record_rotation(
        thing,
        {
            "certificateId": new_id,
            "supersedes": caller_cert_id,
            "jobId": job_id,
            # Fences a stale duplicate of an EARLIER rotation's succeeded event,
            # which job events being at-least-once and unordered makes possible.
            "recordedAt": int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
        },
    )

    # Attach the new certificate so it is usable the moment the device tries it.
    # Both certificates are attached at this point — that is the overlap window.
    iot.attach_thing_principal(thingName=thing, principal=new_arn)
    for policy in all_attached_policies(caller_arn):
        iot.attach_policy(policyName=policy["policyName"], target=new_arn)

    # Only NOW mark the phase. A status marker should describe work that has
    # finished, not work that is about to start: writing CERT_READY before the
    # attachments would make the execution claim readiness while the certificate
    # was still unattached and unauthorized. The ordering inside this function is
    # therefore deliberate and not interchangeable —
    #
    #   record the id  →  attach thing + policies  →  mark CERT_READY  →  deliver
    #
    # The record goes first because it is what makes the flow resumable: a crash
    # after signing but before the record leaves an orphan nobody can identify.
    # CERT_READY goes last of the cloud-side steps because it is the only one that
    # is a *claim about the others*.
    update_execution(thing, job_id, "IN_PROGRESS", {"phase": "CERT_READY"})

    deliver(thing, new_id)
    return {"issued": new_id}


def csr_subject_and_key(csr_pem):
    """Read the subject and the public key out of a certificate signing request.

    Returns ``(subject_string, public_key_der)``. The key is serialized as DER
    ``SubjectPublicKeyInfo`` so it can be compared byte-for-byte against the key
    in an existing certificate — different key types serialize differently, so
    the comparison cannot produce a false match.

    Raises ``ImportError`` when the parser is missing from the deployment
    package, which the caller turns into a denial. Refusing to sign is the
    correct response to being unable to verify what you are signing.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    csr = x509.load_pem_x509_csr(csr_pem.encode())
    return (
        csr.subject.rfc4514_string(),
        csr.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo),
    )


def certificate_public_key(certificate_pem):
    """Return an existing certificate's public key as DER ``SubjectPublicKeyInfo``.

    Same encoding as :func:`csr_subject_and_key` returns, so the two are directly
    comparable. Raises ``ImportError`` alongside its caller for the same reason.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return (
        x509.load_pem_x509_certificate(certificate_pem.encode())
        .public_key()
        .public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    )


def deliver(thing, certificate_id):
    """Publish the certificate to the requesting device's own topic.

    The PEM is read back from the registry rather than cached here: a
    certificate is public data, and ``DescribeCertificate`` is the recovery path
    when a device misses the message.
    """
    pem = iot.describe_certificate(certificateId=certificate_id)[
        "certificateDescription"
    ]["certificatePem"]
    data_client().publish(
        topic=f"devices/{thing}/certificate/rotation/response",
        qos=1,
        payload=json.dumps({"certificateId": certificate_id, "certificatePem": pem}),
    )


# ---------------------------------------------------------------------------
# Entry point 2 — retire the superseded certificate after a proven cutover
# ---------------------------------------------------------------------------
def retire_old_certificate(event):
    """Detach and deactivate every superseded certificate, then defer deletion.

    Safe to run more than once for the same rotation, which matters because job
    events are delivered **at least once**. Detaches and the ``INACTIVE`` update
    are naturally idempotent; :func:`schedule_deletion` carries the one guard
    that is not automatic.
    """
    thing = event["thingArn"].split("/")[-1]

    # Which certificate to KEEP comes from the backend-only rotation shadow —
    # never from the event's statusDetails, whose last writer is the DEVICE. This
    # is the same rule as check 1 in the signing path, applied to the one decision
    # in this flow that destroys something: the input to it does not come from the
    # party it is being applied to.
    record = read_rotation(thing)
    new_id = record.get("certificateId")
    if not new_id:
        # Log it. Without this marker the outcome is invisible: a topic rule invokes
        # this function ASYNCHRONOUSLY, so the return value below is discarded, never
        # written to Amazon CloudWatch Logs. And this is the one path that leaves the
        # thing in the rotation queue with a terminal execution, where nothing will
        # re-trigger it — so it has to be findable.
        print(json.dumps({"retire_skipped": thing, "reason": "no rotation record"}))
        return {"skipped": "no rotation record"}

    # Fence a stale event. Job events are delivered at least once AND out of
    # order, so a duplicate of an earlier rotation's succeeded event can arrive
    # after a later rotation has already recorded its own certificate. Acting on
    # it would retire the certificate the device is using mid-cutover. jobId
    # cannot detect this (one continuous job, one jobId), and the event carries no
    # executionNumber — so compare times.
    event_at = event.get("timestamp")
    recorded_at = record.get("recordedAt")
    if event_at and recorded_at and int(event_at) < int(recorded_at):
        print(
            json.dumps(
                {
                    "retire_skipped": thing,
                    "reason": "event predates the rotation record",
                    "event_at": int(event_at),
                    "recorded_at": int(recorded_at),
                }
            )
        )
        return {"skipped": "event predates the rotation record"}

    # Fail closed if the certificate to keep is not actually attached to this
    # thing. This guard is doing more work than it looks: without it NOTHING
    # matches the skip inside the loop, so the loop retires EVERY principal —
    # including the working one — and locks the device out. A record naming a
    # certificate that the reset block or the revoke timer already deleted is
    # exactly how you would get there.
    principals = all_thing_principals(thing)
    if not any(arn.endswith(f"/{new_id}") for arn in principals):
        print(
            json.dumps(
                {
                    "retire_refused": thing,
                    "reason": "certificate to keep is not attached to this thing",
                    "certificateId": new_id,
                }
            )
        )
        return {"refused": "certificate to keep is not attached"}

    # Every other certificate attached to this thing is now superseded. The list
    # is paginated deliberately: missing one here would leave a superseded
    # certificate ACTIVE and attached.
    retired = []
    grace_expires = None
    for arn in principals:
        old_id = arn.split("/")[-1]
        if old_id == new_id:
            continue

        for policy in all_attached_policies(arn):
            iot.detach_policy(policyName=policy["policyName"], target=arn)
        iot.detach_thing_principal(thingName=thing, principal=arn)

        # Reversible step first: INACTIVE can be undone, deletion cannot.
        iot.update_certificate(certificateId=old_id, newStatus="INACTIVE")
        grace_expires = schedule_deletion(old_id, thing)
        retired.append(old_id)

    # Extend the record with what was retired and when the grace period ends.
    # This is a merge, not a replacement, so it ADDS to what the signing path
    # wrote — which is what makes one shadow per thing a usable retirement log,
    # and what turns the "prefer a sweeper at fleet scale" advice in Step 6 from
    # a suggestion into something you can actually query.
    if retired:
        record_rotation(
            thing,
            {
                "retiredCertificateIds": retired,
                "deactivatedAt": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
                "graceExpiresAt": grace_expires.isoformat(),
            },
        )

    # Leave the rotation queue so the continuous job does not pick this thing up
    # again on its next pass.
    iot.remove_thing_from_thing_group(thingGroupName=ROTATION_GROUP, thingName=thing)
    return {"retired_for": thing, "kept": new_id, "retired": retired}


# ---------------------------------------------------------------------------
# Entry point 3 — the deferred deletion, invoked by the timer
# ---------------------------------------------------------------------------
def delete_superseded_certificate(event):
    """Delete a superseded certificate — but only if it is still safe to.

    This runs when the grace period expires. It is the only irreversible step in
    the rotation, so it re-reads current state instead of trusting the decision
    that was made when the timer was created.

    Three outcomes:

    * **Gone already** — nothing to do. A repeated timer, or a cleanup script that
      got there first. Success.
    * **Rescued** — the certificate is ``ACTIVE`` again, or has been re-attached to
      a thing or a policy. Somebody intervened deliberately (the break-glass
      rollback does exactly this), so **abandon**. Do not delete, and do not
      reschedule: this is not a transient failure that a retry would clear, it is
      a decision that has been overtaken.
    * **Still retired** — ``INACTIVE``, no thing, no policy. Delete it.

    Anything genuinely transient (throttling, a service error) is allowed to raise
    so the invocation fails and Amazon EventBridge Scheduler's retry applies.
    """
    certificate_id = event.get("certificateId")
    if not certificate_id:
        print(json.dumps({"revoke_refused": "no certificateId in the revoke event"}))
        return {"refused": "no certificateId"}
    # The thing name travels in the timer's payload. That is deliberate: checking
    # re-attachment the other way round (ListPrincipalThings) is an action this
    # role does not need for anything else, and the name is already in hand when
    # the schedule is created.
    thing = event.get("thingName")

    try:
        description = iot.describe_certificate(certificateId=certificate_id)[
            "certificateDescription"
        ]
    except iot.exceptions.ResourceNotFoundException:
        print(json.dumps({"revoke_already_deleted": certificate_id}))
        return {"already_deleted": certificate_id}

    status = description["status"]
    certificate_arn = description["certificateArn"]

    # Re-read the attachments. A rollback re-activates the certificate AND
    # re-attaches the thing and the policy, so any one of the three is evidence
    # that this certificate is back in service.
    reattached = False
    if thing:
        try:
            reattached = certificate_arn in all_thing_principals(thing)
        except iot.exceptions.ResourceNotFoundException:
            # The thing itself is gone, so nothing is attached to this certificate
            # through it. Deleting remains safe.
            reattached = False
    policies = all_attached_policies(certificate_arn)

    if status != "INACTIVE" or reattached or policies:
        # Stop, and say so loudly. Deleting here would destroy a credential that
        # somebody deliberately put back into service.
        print(
            json.dumps(
                {
                    "revoke_abandoned": certificate_id,
                    "reason": "certificate is back in service - not deleting",
                    "status": status,
                    "thing": thing,
                    "reattached_to_thing": reattached,
                    "policies": [p["policyName"] for p in policies],
                }
            )
        )
        return {"abandoned": certificate_id, "status": status}

    iot.delete_certificate(certificateId=certificate_id, forceDelete=True)
    print(json.dumps({"revoked": certificate_id, "thing": thing}))
    return {"deleted": certificate_id}


def schedule_deletion(certificate_id, thing):
    """Create a one-time timer that revokes the certificate after the grace
    period, and deletes itself afterwards.

    Idempotent by design. Job events are delivered **at least once**, so this
    whole retirement path can run twice for one rotation. Every other call in it
    tolerates that — detaching an already-detached principal, or setting an
    already-``INACTIVE`` certificate ``INACTIVE``, is a no-op — but
    ``CreateSchedule`` raises ``ConflictException`` on a name that already
    exists. Left unhandled that exception fails the invocation *before*
    ``RemoveThingFromThingGroup`` runs, so the thing stays in the rotation queue
    and the continuous job enqueues it again: a loop. Treating an existing
    schedule as success is what breaks the loop.

    At demonstration scale a schedule per certificate is clear to inspect. At
    fleet scale prefer a sweeper (a table of deactivation times plus one
    scheduled task) to stay well clear of the Amazon EventBridge Scheduler
    quotas — see the Module 1 reference design.

    Returns the moment the timer will fire, so the caller can record it without
    recomputing the grace period and risking two slightly different answers.
    """
    when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=GRACE_MINUTES
    )
    try:
        _create_schedule(certificate_id, thing, when)
    except scheduler.exceptions.ConflictException:
        # Already scheduled by an earlier delivery of the same event.
        print(json.dumps({"deletion_already_scheduled": certificate_id}))
    return when


def _create_schedule(certificate_id, thing, when):
    """Create the one-time deletion schedule, targeting THIS function.

    The timer invokes this Lambda rather than calling ``iot:DeleteCertificate``
    directly as an Amazon EventBridge Scheduler universal target. That indirection
    is the point: it puts a decision point in front of the only irreversible step
    in the whole rotation.

    A universal target would fire a delete built ten minutes earlier and could not
    reconsider it. A function re-reads the certificate's current state first, so it
    can tell the difference between "the grace period elapsed, delete it" and
    "someone re-activated this certificate on purpose — leave it alone". It also
    gets a log group for free, which matters because a failed deletion is
    otherwise completely silent: this schedule has no dead-letter queue, and
    ``ActionAfterCompletion=DELETE`` removes it afterwards either way.
    """
    if not _self_arn:
        raise RuntimeError(
            "cannot schedule deletion: this function's ARN is unknown "
            "(no Lambda context captured)"
        )
    scheduler.create_schedule(
        Name=f"ws-aws-iot-dm-adv-prov-revoke-{certificate_id[:16]}",
        ScheduleExpression=f"at({when.strftime('%Y-%m-%dT%H:%M:%S')})",
        FlexibleTimeWindow={"Mode": "OFF"},
        ActionAfterCompletion="DELETE",
        Target={
            "Arn": _self_arn,
            "RoleArn": SCHEDULER_ROLE_ARN,
            # Routed by handler() on this marker. Keeping the payload explicit
            # means a scheduled invocation can never be mistaken for a signing
            # request, which is the one path that trusts its input.
            "Input": json.dumps(
                {
                    "operation": REVOKE_OPERATION,
                    "certificateId": certificate_id,
                    "thingName": thing,
                }
            ),
        },
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def update_execution(thing, job_id, status, details):
    """Write the rotation phase into the job execution.

    This publishes to the reserved Jobs MQTT topic
    (``$aws/things/<thing>/jobs/<jobId>/update``) rather than calling the Jobs
    data-plane ``UpdateJobExecution`` HTTPS API directly. Functionally the two
    are the same operation - the message broker turns this publish into an
    UpdateJobExecution call server-side - but the IAM story is different, and
    that difference is the reason to prefer this form for a backend Lambda:

    - The HTTPS API is authorized by ``iotjobsdata:UpdateJobExecution``, a
      third IAM prefix on top of the ``iot:`` control plane and the AWS IoT
      Core policy world devices normally live in. Some accounts restrict or
      omit this prefix entirely (for example, a locked-down sandbox account's
      service control policy), which surfaces as a bare
      ``ForbiddenException`` with no further detail - nothing to fix in the
      IAM policy itself, because the policy can be perfectly correct and
      still be overridden by something the policy cannot see.
    - The MQTT publish is authorized by plain ``iot:Publish`` on the topic,
      the same action and mechanism ``deliver()`` below already uses to hand
      the signed certificate back to the device. One IAM action to reason
      about instead of two.

    The trade-off: this call is fire-and-forget. The synchronous HTTPS API
    raises ``InvalidStateTransitionException`` immediately if the execution
    cannot accept the update; a publish never raises for that - the broker
    instead publishes to the topic's ``.../rejected`` sibling, which nothing
    here subscribes to. ``deny()``'s best-effort recording of a denial is
    written the same way either way: log first, then attempt this update, and
    do not let a rejected transition (silently dropped here, previously an
    exception) block the log line that already ran.
    """
    data_client().publish(
        topic=f"$aws/things/{thing}/jobs/{job_id}/update",
        qos=1,
        payload=json.dumps(
            {
                "status": status,
                "statusDetails": {k: str(v) for k, v in details.items()},
            }
        ),
    )


def deny(thing, job_id, reason):
    """Refuse to sign, and record why on the job execution.

    Recording the reason is best-effort. ``update_execution`` publishes over
    MQTT rather than calling the Jobs data-plane API directly (see its
    docstring), which is fire-and-forget: a rejected state transition - for
    example an execution that already reached a terminal state such as
    ``TIMED_OUT`` because the in-progress timer expired while this handler was
    working - is not reported back as an exception. The publish itself can
    still fail (an endpoint lookup error, a network error, or an IAM denial on
    the topic), and that is what the catch below is for. Either way the denial
    still holds: nothing is signed. It is simply visible in Amazon CloudWatch
    Logs rather than on the execution when the write does not land.
    """
    # Log the denial FIRST and unconditionally. Everything after this point can
    # fail, and the one thing that must survive is the record that we refused.
    print(json.dumps({"denied": reason, "thing": thing}))

    # Recording it on the execution is best effort, and the catch is deliberately
    # broad. update_execution() resolves the device data endpoint on first use
    # with a control-plane DescribeEndpoint call, and the publish itself can be
    # denied or fail transiently - a narrow catch would let any of that raise
    # straight out of deny() and lose even the log line above.
    try:
        update_execution(
            thing, job_id, "FAILED", {"phase": "DENIED", "reason": reason[:1024]}
        )
    except Exception as error:  # noqa: BLE001 - never let reporting mask the denial
        record = {
            "denial_not_recorded_on_execution": job_id,
            "thing": thing,
            "reason": reason,
            "record_error": f"{type(error).__name__}: {error}",
        }
        print(json.dumps(record))
    return {"denied": reason}


def refuse(thing, reason):
    """Refuse a request that has no job execution to record a denial against.

    Used when the request carries no ``jobId``, or one that does not resolve to an
    execution for this thing. Fails closed and logs, with nothing to update.
    """
    print(json.dumps({"refused": reason, "thing": thing}))
    return {"refused": reason}
