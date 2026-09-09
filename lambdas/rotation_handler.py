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
3. The certificate signing request asks for the identity it is entitled to.

Caller identity comes from the **rule SQL** (``principal()`` and the topic
segment), never from the message payload — the payload is attacker-controlled.

Two IAM prefixes, not one
-------------------------
AWS IoT Jobs splits across two IAM prefixes and this function needs both:
reads of the job and its execution are **control plane** (``iot:DescribeJob``,
``iot:DescribeJobExecution``); writing the execution status is **data plane**
(``iotjobsdata:UpdateJobExecution``). Using ``iot:`` for the write does not
authorize the call.

Deployment
----------
This function is deployed into the pre-created base-infrastructure function
name with bundled dependencies, because the certificate signing request parser
(``cryptography``) is not in the AWS Lambda runtime::

    rm -rf build && mkdir build
    python3 -m pip install --quiet --target ./build \\
        --platform manylinux2014_x86_64 --implementation cp \\
        --python-version 3.12 --only-binary=:all: cryptography
    cp lambdas/rotation_handler.py build/rotation_handler.py
    cd build && zip -qr ../rotation_handler.zip . && cd ..

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

iot = boto3.client("iot")
scheduler = boto3.client("scheduler")

_data = None
_jobs = None


def data_client():
    """Client for publishing to devices (endpoint resolved once per container)."""
    global _data
    if _data is None:
        endpoint = iot.describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]
        _data = boto3.client("iot-data", endpoint_url=f"https://{endpoint}")
    return _data


def jobs_client():
    """Client for the Jobs DATA plane.

    ``UpdateJobExecution`` exists only on the data plane, which is a separate
    endpoint from the control plane ``iot`` client above.
    """
    global _jobs
    if _jobs is None:
        endpoint = iot.describe_endpoint(endpointType="iot:Jobs")["endpointAddress"]
        _jobs = boto3.client("iot-jobs-data", endpoint_url=f"https://{endpoint}")
    return _jobs


def handler(event, context):
    """Route to the signing path or the retirement path based on event shape."""
    print(json.dumps({"received": event}))
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
    job_id = event["jobId"]
    csr = event["csr"]

    # Check 1 — the caller must be a certificate attached to THIS thing, and ACTIVE.
    principals = iot.list_thing_principals(thingName=thing)["principals"]
    caller_arn = next((p for p in principals if p.endswith(f"/{caller_cert_id}")), None)
    if caller_arn is None:
        return deny(thing, job_id, "requesting certificate is not attached to this thing")

    status = iot.describe_certificate(certificateId=caller_cert_id)[
        "certificateDescription"
    ]["status"]
    if status != "ACTIVE":
        return deny(thing, job_id, f"requesting certificate is {status}, not ACTIVE")

    # Check 2 — a rotation must actually be in progress for this thing.
    execution = iot.describe_job_execution(jobId=job_id, thingName=thing)["execution"]
    if execution["status"] != "IN_PROGRESS":
        return deny(
            thing, job_id, f"no rotation in progress (status {execution['status']})"
        )

    details = execution.get("statusDetails", {}) or {}

    # Idempotency — if a certificate was already signed for this execution,
    # re-deliver it instead of minting a second one.
    existing = details.get("newCertificateId")
    if existing:
        deliver(thing, existing)
        return {"redelivered": existing}

    # Check 3 — the certificate signing request must ask for this thing's identity.
    try:
        subject = csr_subject(csr)
    except ImportError:
        # Fail closed: a handler that cannot read the subject cannot confirm the
        # request is for the identity it is entitled to, so it must not sign.
        return deny(thing, job_id, "handler cannot parse the certificate signing request")
    if f"CN={thing}" not in subject:
        return deny(
            thing,
            job_id,
            "certificate signing request subject does not match the thing name",
        )

    # Sign it. The new certificate is ACTIVE but not yet attached to anything.
    created = iot.create_certificate_from_csr(
        certificateSigningRequest=csr, setAsActive=True
    )
    new_id = created["certificateId"]
    new_arn = created["certificateArn"]

    # Record the id BEFORE delivery. If delivery fails, the id is still here, so
    # the device can ask again and we re-deliver rather than sign again.
    update_execution(
        thing, job_id, "IN_PROGRESS", {"phase": "CERT_READY", "newCertificateId": new_id}
    )

    # Attach the new certificate so it is usable the moment the device tries it.
    # Both certificates are attached at this point — that is the overlap window.
    iot.attach_thing_principal(thingName=thing, principal=new_arn)
    for policy in iot.list_attached_policies(target=caller_arn)["policies"]:
        iot.attach_policy(policyName=policy["policyName"], target=new_arn)

    deliver(thing, new_id)
    return {"issued": new_id}


def csr_subject(csr_pem):
    """Read the subject out of the certificate signing request.

    Raises ``ImportError`` when the parser is missing from the deployment
    package, which the caller turns into a denial. Refusing to sign is the
    correct response to being unable to verify what you are signing.
    """
    from cryptography import x509

    return x509.load_pem_x509_csr(csr_pem.encode()).subject.rfc4514_string()


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
    """Detach and deactivate every superseded certificate, then defer deletion."""
    thing = event["thingArn"].split("/")[-1]
    details = event.get("statusDetails", {}) or {}
    new_id = details.get("newCertificateId")
    if not new_id:
        return {"skipped": "no newCertificateId recorded"}

    # Every other certificate attached to this thing is now superseded.
    for arn in iot.list_thing_principals(thingName=thing)["principals"]:
        old_id = arn.split("/")[-1]
        if old_id == new_id:
            continue

        for policy in iot.list_attached_policies(target=arn)["policies"]:
            iot.detach_policy(policyName=policy["policyName"], target=arn)
        iot.detach_thing_principal(thingName=thing, principal=arn)

        # Reversible step first: INACTIVE can be undone, deletion cannot.
        iot.update_certificate(certificateId=old_id, newStatus="INACTIVE")
        schedule_deletion(old_id)

    # Leave the rotation queue so the continuous job does not pick this thing up
    # again on its next pass.
    iot.remove_thing_from_thing_group(thingGroupName=ROTATION_GROUP, thingName=thing)
    return {"retired_for": thing, "kept": new_id}


def schedule_deletion(certificate_id):
    """Create a one-time timer that deletes the certificate after the grace
    period, and deletes itself afterwards.

    At demonstration scale a schedule per certificate is clear to inspect. At
    fleet scale prefer a sweeper (a table of deactivation times plus one
    scheduled task) to stay well clear of the Amazon EventBridge Scheduler
    quotas — see the Module 1 reference design.
    """
    when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=GRACE_MINUTES
    )
    scheduler.create_schedule(
        Name=f"ws-aws-iot-dm-adv-prov-revoke-{certificate_id[:16]}",
        ScheduleExpression=f"at({when.strftime('%Y-%m-%dT%H:%M:%S')})",
        FlexibleTimeWindow={"Mode": "OFF"},
        ActionAfterCompletion="DELETE",
        Target={
            "Arn": "arn:aws:scheduler:::aws-sdk:iot:deleteCertificate",
            "RoleArn": SCHEDULER_ROLE_ARN,
            "Input": json.dumps(
                {"CertificateId": certificate_id, "ForceDelete": True}
            ),
        },
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def update_execution(thing, job_id, status, details):
    """Write the rotation phase into the job execution (data plane)."""
    jobs_client().update_job_execution(
        thingName=thing,
        jobId=job_id,
        status=status,
        statusDetails={k: str(v) for k, v in details.items()},
    )


def deny(thing, job_id, reason):
    """Refuse to sign, and record why on the job execution."""
    print(json.dumps({"denied": reason, "thing": thing}))
    update_execution(
        thing, job_id, "FAILED", {"phase": "DENIED", "reason": reason[:1024]}
    )
    return {"denied": reason}
