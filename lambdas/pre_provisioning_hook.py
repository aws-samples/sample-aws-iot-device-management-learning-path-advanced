#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Fleet-provisioning pre-provisioning hook — AWS Lambda function.

This is the pre-provisioning hook for Module 3, "Fleet Provisioning by Claim"
(design section 2.6). A fleet provisioning template can name a
``preProvisioningHook``; when it does, AWS IoT Core invokes THIS function
**synchronously** during ``RegisterThing`` — after the device presents its
``certificateOwnershipToken`` and before any resource is created — and lets the
function decide, per device, whether provisioning may proceed.

The hook is the fleet-provisioning equivalent of the Just-in-Time Registration
(JITR) handler's "your code decides" moment, but it runs at a different point:

- The JITR handler (Module 2) runs *after* the certificate is already
  registered, and it activates/attaches resources itself.
- This pre-provisioning hook runs *before* the template's resources are created,
  and it only returns an allow/deny decision plus optional parameter overrides —
  AWS IoT Core (not this function) then creates the thing/certificate/policy
  from the template.

Input event shape delivered by AWS IoT Core fleet provisioning:

    {
      "claimCertificateId": "<id of the claim/bootstrap cert used to connect>",
      "certificateId": "<id of the just-issued permanent cert>",
      "templateArn": "arn:aws:iot:<region>:<account>:provisioningtemplate/FleetClaimTemplate",
      "parameters": {
        "SerialNumber": "Vehicle-VIN-777",
        "ModelType": "SUVVehicle"
      }
    }

Return contract (design section 2.6):

    {
      "allowProvisioning": true | false,
      "parameterOverrides": { "<templateParam>": "<value>", ... }
    }

Rules taught in the module content:

- ``allowProvisioning: false`` (or ANY unhandled exception in this function)
  **blocks** the device — no thing, certificate, or policy is created.
- ``parameterOverrides`` values are injected into the provisioning template, so
  a template parameter (for example ``provisionedBy``) is populated by the hook
  rather than trusted from the device-supplied parameters.
- The hook must return within the fleet-provisioning timeout; keep external
  lookups fast and fail closed.

This function is pre-created as a skeleton by ``provisioning-base.yaml`` under
the name ``<stack-name>-pre-provisioning-hook`` with the handler set to
``index.handler`` (the skeleton denies provisioning, fail-closed, until this
code is deployed). Deploy this code over the skeleton with, for example:

    zip function.zip index.py           # (rename this file to index.py in the zip)
    aws lambda update-function-code \
      --function-name <stack-name>-pre-provisioning-hook \
      --zip-file fileb://function.zip

The execution role pre-created by the base stack grants Amazon CloudWatch Logs
write access and read-only AWS IoT describe access for the advanced hook's
validation lookups; the hook does not mutate the registry.
"""

import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# --- Simple hook: allow-list a serial-number prefix -----------------------
# The simplest useful hook accepts a device only when its SerialNumber starts
# with a known factory prefix. AnyCompany burns "Vehicle-VIN-" into its vehicle
# batches and "SmartHome-" into its consumer sensor batches, so anything else is
# almost certainly a mistake or a rogue device using a leaked claim certificate.
ALLOWED_PREFIXES = ("Vehicle-VIN-", "SmartHome-")

# --- Advanced hook: simulated external inventory + per-model quota ---------
# A production hook usually calls an external system (a manufacturing database,
# Amazon DynamoDB, an inventory API) to confirm the serial was really built and
# to look up how the device should be configured. We SIMULATE that lookup with
# an in-memory table so the hook is self-contained in the workshop; swap
# ``_lookup_inventory`` for a real call in production.
_SIMULATED_INVENTORY = {
    "Vehicle-VIN-777": {"modelType": "SUVVehicle", "region": "us"},
    "Vehicle-VIN-500": {"modelType": "SedanVehicle", "region": "us"},
    "SmartHome-Sensor-001": {"modelType": "SedanVehicle", "region": "eu"},
}

# Advanced hook: cap how many devices of a given model may provision. In a real
# hook this counter lives in an external store; here an environment variable
# stands in so the behaviour can be demonstrated without extra infrastructure.
PER_MODEL_QUOTA = int(os.environ.get("PER_MODEL_QUOTA", "0"))  # 0 == unlimited


def _serial_prefix_allowed(serial: str) -> bool:
    """Simple hook: return True when the serial matches a known factory prefix."""
    return serial.startswith(ALLOWED_PREFIXES)


def _lookup_inventory(serial: str):
    """Advanced hook: simulated external inventory lookup.

    Returns the inventory record for a serial, or ``None`` when the serial is
    unknown. Replace the in-memory table with a real call (Amazon DynamoDB, an
    inventory service, ...) in production; keep it fast so the hook returns
    within the fleet-provisioning timeout.
    """
    return _SIMULATED_INVENTORY.get(serial)


def _deny(reason: str) -> dict:
    """Return a fail-closed deny decision and log why."""
    logger.warning("Pre-provisioning hook DENIED provisioning: %s", reason)
    return {"allowProvisioning": False}


def handler(event, context):
    """Entry point invoked synchronously by AWS IoT Core during RegisterThing."""
    parameters = event.get("parameters", {}) or {}
    serial = parameters.get("SerialNumber", "")

    # Log only what a learner needs to debug a hook decision. The full event also
    # carries claimCertificateId, certificateId, and templateArn — certificate and
    # template identifiers that do not belong in Amazon CloudWatch Logs unfiltered.
    logger.info(
        "Pre-provisioning hook invoked: SerialNumber=%s templateArn=%s",
        serial,
        event.get("templateArn", ""),
    )

    # 1) Simple hook: allow-list the serial prefix (fail closed on anything else).
    if not _serial_prefix_allowed(serial):
        return _deny(f"SerialNumber '{serial}' does not match an allowed prefix")

    # 2) Advanced hook: confirm the serial exists in the (simulated) inventory.
    record = _lookup_inventory(serial)
    if record is None:
        # Unknown-but-well-formed serial. The workshop keeps this permissive so
        # the happy path still provisions devices that are not pre-seeded in the
        # simulated table; flip this to ``_deny(...)`` to require an inventory
        # match (the stricter production posture).
        logger.info("Serial '%s' not in simulated inventory; allowing on prefix match", serial)
        resolved_model = parameters.get("ModelType", "SedanVehicle")
    else:
        # 3) Advanced hook: parameter override. Trust the INVENTORY's model type,
        #    not the value the device supplied, and enforce an optional quota.
        resolved_model = record.get("modelType", parameters.get("ModelType", "SedanVehicle"))

    if PER_MODEL_QUOTA and _would_exceed_quota(resolved_model):
        return _deny(f"per-model quota reached for ModelType '{resolved_model}'")

    # Allow provisioning, injecting server-controlled parameter overrides. These
    # values are merged into the provisioning template, so the template's
    # ``provisionedBy`` attribute is stamped by the hook (not by the device) and
    # the model type is the one the hook resolved.
    overrides = {
        "ModelType": resolved_model,
        "provisionedBy": "pre-provisioning-hook",
    }
    logger.info(
        "Pre-provisioning hook ALLOWED serial '%s' with overrides %s",
        serial,
        json.dumps(overrides),
    )
    return {
        "allowProvisioning": True,
        "parameterOverrides": overrides,
    }


def _would_exceed_quota(model_type: str) -> bool:
    """Advanced hook: simulated per-model quota check.

    Placeholder for a real counter kept in an external store. Returns ``False``
    (never exceeded) in the workshop unless you wire in a real count; the
    structure shows where a quota decision belongs in the hook.
    """
    return False
