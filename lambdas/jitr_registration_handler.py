#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Just-in-Time Registration (JITR) handler — AWS Lambda function.

This is the JITR variant of Just-in-Time Provisioning (Module 2, "Just-in-Time
Provisioning: JITP & JITR"). Where JITP registers a device automatically from a
provisioning template embedded in the Certificate Authority (CA) registration
config, **JITR moves the registration decision into your own code** so you can
run allow-list checks, look devices up in an external system, or shape the thing
however you like before activating it.

Event flow (design section 2.4.3):

1. A device whose CA is registered (with auto-registration NOT doing the whole
   job) connects for the first time. AWS IoT Core registers the certificate in
   ``PENDING_ACTIVATION`` and publishes a registration event to the reserved
   topic ``$aws/events/certificates/registered/<caCertificateId>``.
2. An AWS IoT topic rule (``JITRRegistrationRule``) selecting from
   ``$aws/events/certificates/registered/+`` invokes this AWS Lambda function
   with the event payload.
3. This handler:
   a. Ensures the device policy exists, creates the thing, and attaches the
      certificate as its principal.
   b. Attaches the device policy to the certificate.
   c. Activates the certificate (``update_certificate`` -> ``ACTIVE``) LAST,
      once the thing and policy are fully wired up - so a failure partway
      through step (a) or (b) never leaves an ACTIVE certificate with no
      policy or thing attached; the certificate simply stays
      ``PENDING_ACTIVATION`` and the device cannot connect (fail-closed).

The reserved-topic event payload delivered by AWS IoT Core looks like:

    {
      "certificateId": "<id>",
      "caCertificateId": "<ca-id>",
      "timestamp": 1600000000000,
      "certificateStatus": "PENDING_ACTIVATION",
      "awsAccountId": "<account-id>",
      "certificateRegistrationTimestamp": "1600000000000"
    }

This handler names the created thing from the device CERTIFICATE's subject
common name (CN) - the same source JITP's provisioning template uses via its
built-in ``AWS::IoT::Certificate::CommonName`` template variable - rather than
from the connecting MQTT client id. The client id is not a good naming source
for this: it is presented by whoever holds the private key at connect time,
with no independent verification, so naming (and therefore policy-scoping) a
thing from it would let any client claim any name that a policy has not
already locked down - which is exactly the restriction you are trying to
build. The certificate's CN, by contrast, is baked into a certificate the CA
signed, so it cannot be changed by the connecting client after the fact.

Parsing the CN requires the ``cryptography`` library (see the deploy step
below); this handler imports it lazily and falls back to a deterministic
``jitr-device-<cert-id-prefix>`` name only if the PEM cannot be parsed.

This function is pre-created as a skeleton by ``provisioning-base.yaml`` under
the name ``<stack-name>-jitr-registration-handler`` with the handler set to
``index.handler``. Deploy this code over the skeleton with, for example:

    zip function.zip index.py           # (rename this file to index.py in the zip)
    aws lambda update-function-code \
      --function-name <stack-name>-jitr-registration-handler \
      --zip-file fileb://function.zip

The execution role pre-created by the base stack already grants the scoped
``iot:DescribeCertificate``, ``iot:UpdateCertificate``, ``iot:GetPolicy``,
``iot:CreatePolicy``, ``iot:AttachPolicy``, ``iot:CreateThing``, and
``iot:AttachThingPrincipal`` permissions this handler needs.
"""

import json
import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Lazily-created, reused AWS IoT client. Created on first use (not at import
# time) so the module imports cleanly in any environment; inside the AWS Lambda
# runtime the region is always present and the client is reused across
# invocations.
_iot_client = None


def _iot():
    """Return a cached boto3 AWS IoT client, creating it on first use."""
    global _iot_client
    if _iot_client is None:
        _iot_client = boto3.client("iot")
    return _iot_client


# Device policy attached to every JITR-registered certificate. Kept distinct
# from the JITP path's ``JITPDevicePolicy`` so the two flows can be told apart
# in the console. Created on first use if it does not already exist.
JITR_DEVICE_POLICY_NAME = "JITRDevicePolicy"

# Minimal least-privilege device policy, matching the JITRDevicePolicy shown
# in 2-jit-provisioning's Step 2 exactly (same topic, same actions) so a
# standalone run of this handler (no Step 2 policy created by hand first)
# behaves identically to the documented flow instead of silently refusing the
# device's own publish. If the learner already created ``JITRDevicePolicy``
# by hand, ``_ensure_device_policy`` finds it and does not overwrite it.
#
# ``${iot:Connection.Thing.ThingName}`` resolves at connection time to the
# thing the connecting certificate is attached to - a real registry lookup -
# unlike ``${iot:ClientId}``, which just echoes back whatever client id the
# caller presented (attacker-controlled, unverified) and so grants nothing
# beyond "any client can connect as itself." This handler names the thing
# from the certificate's CN (see ``_common_name_from_certificate``), which the
# connecting device cannot forge after the fact, so this variable enforces
# "connect only as the thing your certificate is actually registered to."
JITR_DEVICE_POLICY_DOCUMENT = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "iot:Connect",
            "Resource": "arn:aws:iot:*:*:client/${iot:Connection.Thing.ThingName}",
        },
        {
            "Effect": "Allow",
            "Action": ["iot:Publish", "iot:Receive"],
            "Resource": "arn:aws:iot:*:*:topic/anycompany/telemetry",
        },
        {
            "Effect": "Allow",
            "Action": "iot:Subscribe",
            "Resource": "arn:aws:iot:*:*:topicfilter/anycompany/telemetry",
        },
    ],
}

# Optional allow-list guardrail. Leave empty to accept any country; populate it
# (e.g. {"US", "DE"}) to reject devices whose certificate country code is not on
# the list, deactivating any device that fails the check (fail-closed).
ALLOWED_COUNTRY_CODES: set = set()


def _ensure_device_policy() -> None:
    """Create the JITR device policy if it does not already exist (idempotent)."""
    try:
        _iot().get_policy(policyName=JITR_DEVICE_POLICY_NAME)
        logger.info("Device policy %s already exists", JITR_DEVICE_POLICY_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] == "ResourceNotFoundException":
            _iot().create_policy(
                policyName=JITR_DEVICE_POLICY_NAME,
                policyDocument=json.dumps(JITR_DEVICE_POLICY_DOCUMENT),
            )
            logger.info("Created device policy %s", JITR_DEVICE_POLICY_NAME)
        else:
            raise


def _describe_certificate(certificate_id: str) -> dict:
    """Return the certificate description, including its subject/common name."""
    return _iot().describe_certificate(certificateId=certificate_id)["certificateDescription"]


def _parse_subject(cert_description: dict) -> dict:
    """Parse the device certificate subject (CN, country) from its PEM.

    The registration event and ``describe_certificate`` do NOT include a parsed
    subject, but ``describe_certificate`` does return the certificate PEM
    (``certificatePem``). We parse the subject from that PEM. The parse uses the
    ``cryptography`` library, imported lazily so this module still imports
    cleanly in environments where it is not installed; on any parse failure we
    return an empty subject and callers decide how to handle "unknown".
    """
    subject = {}
    pem = cert_description.get("certificatePem")
    if not pem:
        return subject
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID

        cert = x509.load_pem_x509_certificate(pem.encode("utf-8"))
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        country = cert.subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)
        if cn:
            subject["common_name"] = cn[0].value
        if country:
            subject["country"] = country[0].value
    except Exception as error:  # noqa: BLE001 - parsing is best-effort
        logger.warning("Could not parse certificate subject: %s", error)
    return subject


def _common_name_from_certificate(cert_description: dict) -> str:
    """Return a thing name from the certificate common name (CN), or a fallback.

    Prefer the certificate's CN (matching how the JITP template names the thing);
    fall back to a deterministic name derived from the certificate id when the CN
    cannot be parsed.
    """
    subject = _parse_subject(cert_description)
    common_name = subject.get("common_name")
    if common_name:
        return common_name
    cert_id = cert_description["certificateId"]
    return f"jitr-device-{cert_id[:12]}"


def _country_allowed(cert_description: dict) -> bool:
    """Apply the optional country-code allow-list guardrail.

    The country is parsed from the device certificate subject (see
    :func:`_parse_subject`). When an allow-list is configured and the country
    cannot be determined, the device is denied (fail-closed).
    """
    if not ALLOWED_COUNTRY_CODES:
        return True
    country = _parse_subject(cert_description).get("country")
    return country in ALLOWED_COUNTRY_CODES


def handler(event, context):
    """Entry point invoked by the AWS IoT topic rule for the registration event."""
    logger.info("JITR registration event: %s", json.dumps(event, default=str))

    certificate_id = event.get("certificateId")
    if not certificate_id:
        logger.error("Event did not contain a certificateId; nothing to register")
        return {"status": "ignored", "reason": "missing certificateId"}

    account_id = event.get("awsAccountId") or (context and getattr(context, "invoked_function_arn", "").split(":")[4])
    region = _iot().meta.region_name
    certificate_arn = event.get("certificateArn") or (
        f"arn:aws:iot:{region}:{account_id}:cert/{certificate_id}" if account_id else None
    )

    try:
        cert_description = _describe_certificate(certificate_id)

        # Guardrail: optionally reject certificates outside the allow-list.
        if not _country_allowed(cert_description):
            logger.warning(
                "Certificate %s rejected by country allow-list; deactivating",
                certificate_id,
            )
            _iot().update_certificate(certificateId=certificate_id, newStatus="INACTIVE")
            return {"status": "rejected", "certificateId": certificate_id}

        certificate_arn = certificate_arn or cert_description["certificateArn"]

        # Do everything the device NEEDS before it can use the certificate first,
        # and activate the certificate LAST. If any step below raises, the
        # certificate is still PENDING_ACTIVATION - the device cannot connect
        # with it - rather than ACTIVE with a missing policy or thing. That
        # ordering is what makes this handler fail-closed: a partial failure
        # denies the device instead of silently under-provisioning it.

        # 1) Ensure the device policy exists (does not attach it yet).
        _ensure_device_policy()

        # 2) Create the thing, named from the certificate's CN so the name is
        #    tied to what the CA signed (see _common_name_from_certificate),
        #    and attach the certificate as its principal.
        thing_name = _common_name_from_certificate(cert_description)
        try:
            _iot().create_thing(thingName=thing_name)
            logger.info("Created thing %s", thing_name)
        except ClientError as error:
            if error.response["Error"]["Code"] != "ResourceAlreadyExistsException":
                raise
            logger.info("Thing %s already exists, continuing", thing_name)

        _iot().attach_thing_principal(thingName=thing_name, principal=certificate_arn)
        logger.info("Attached certificate %s to thing %s", certificate_id, thing_name)

        # 3) Attach the device policy to the certificate.
        _iot().attach_policy(policyName=JITR_DEVICE_POLICY_NAME, target=certificate_arn)
        logger.info("Attached policy %s to %s", JITR_DEVICE_POLICY_NAME, certificate_arn)

        # 4) Only now activate the certificate, so the device can complete its
        #    connection - the policy and thing are already fully wired up.
        _iot().update_certificate(certificateId=certificate_id, newStatus="ACTIVE")
        logger.info("Activated certificate %s", certificate_id)

        return {
            "status": "registered",
            "certificateId": certificate_id,
            "thingName": thing_name,
        }

    except ClientError as error:
        # Re-raised below, so this is a warning (not handled here) rather than an
        # error: the caller (AWS Lambda) is what ultimately handles/reports it.
        # Logged so the failure is visible in Amazon CloudWatch Logs and the
        # certificate stays PENDING_ACTIVATION rather than being wrongly trusted.
        logger.warning("JITR registration failed for %s: %s", certificate_id, error)
        raise
