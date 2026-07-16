#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Fleet Provisioning by Claim — control plane + device plane wrapper.

Control-plane + device-plane wrapper for Module 3, "Fleet Provisioning by
Claim" (design sections 2.5.1–2.5.4). It wraps the exact CLI-first flow the
module content shows by hand, so learners can see the raw ``aws iot`` commands
and reserved MQTT topics first and then run the same flow end to end.

Two planes, one script:

- **Control plane** (``boto3`` / ``aws iot ...``, via the shared
  ``safe_api_call`` construct): create the shared **claim (bootstrap)
  certificate** and its tightly scoped policy, create/version the fleet
  provisioning template, and observe the provisioned thing.
- **Device plane** (MQTT, via the shared ``DeviceConnection`` construct in
  ``iot_helpers/utils/device_simulator.py`` — the same reused AWS IoT Core
  Learning SDK connection builder used by every other section): run the
  fleet-provisioning MQTT exchange with the **claim certificate**, obtain a
  permanent certificate and its ``certificateOwnershipToken``, and drive
  ``RegisterThing``.

Subcommands
-----------
    create-claim     Create the claim certificate + scoped claim policy
                     (wraps create-keys-and-certificate + create-policy).
    create-template  Create the fleet provisioning template with a
                     pre-provisioning hook (wraps create-provisioning-template
                     --pre-provisioning-hook).
    provision        Run the device-plane MQTT exchange with the claim cert:
                     CreateKeysAndCertificate (or CreateCertificateFromCsr) ->
                     RegisterThing, using the certificateOwnershipToken.
    versions         List / set-default / delete provisioning template versions
                     (wraps list-/create-/delete-provisioning-template-version).
    observe          describe-thing / list-thing-principals for a provisioned
                     device.

Examples
--------
    python scripts/fleet_provision_by_claim.py create-claim \\
        --policy-name FleetClaimPolicy

    python scripts/fleet_provision_by_claim.py create-template \\
        --template-name FleetClaimTemplate \\
        --provisioning-role-arn arn:aws:iam::<account-id>:role/<stack>-fleet-provisioning-role \\
        --hook-arn arn:aws:lambda:<region>:<account-id>:function:<stack>-pre-provisioning-hook

    python scripts/fleet_provision_by_claim.py provision \\
        --template-name FleetClaimTemplate \\
        --claim-cert claim.pem --claim-key claim.private.key \\
        --serial-number Vehicle-VIN-777 --model-type SUVVehicle

    python scripts/fleet_provision_by_claim.py versions --template-name FleetClaimTemplate --list
"""

import argparse
import json
import os
import sys
import time

# --- Repository path wiring (import shared constructs) --------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "i18n"))

import boto3  # noqa: E402

from iot_helpers.utils.api_helpers import safe_api_call  # noqa: E402
from iot_helpers.utils.device_simulator import (  # noqa: E402
    DeviceConnection,
    get_iot_endpoint,
)

TEMPLATE_DIR = os.path.join(
    REPO_ROOT, "iot_helpers", "utils", "fleet_provisioning_templates"
)
DEFAULT_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, "fleet-claim-template.json")
DEFAULT_CLAIM_POLICY_FILE = os.path.join(TEMPLATE_DIR, "claim-policy.json")

# Reserved MQTT topics for the fleet-provisioning device-plane exchange. The
# module content shows these raw first; this script publishes/subscribes on the
# exact same topics.
CREATE_KEYS_TOPIC = "$aws/certificates/create/json"
CREATE_KEYS_ACCEPTED = "$aws/certificates/create/json/accepted"
CREATE_KEYS_REJECTED = "$aws/certificates/create/json/rejected"


def _provision_topics(template_name):
    """Return the RegisterThing publish/accepted/rejected topics for a template."""
    base = f"$aws/provisioning-templates/{template_name}/provision/json"
    return base, f"{base}/accepted", f"{base}/rejected"


# =========================================================================
# Control plane
# =========================================================================


def create_claim(policy_name, policy_file, claim_cert_out, claim_key_out,
                 claim_pub_out, debug=False):
    """Create the claim certificate and attach the tightly scoped claim policy.

    Wraps ``create-keys-and-certificate`` + ``create-policy`` + ``attach-policy``.
    The claim certificate is a SHARED, per-batch bootstrap identity: it can do
    nothing but connect and drive the fleet-provisioning MQTT API (that scoping
    lives in ``claim-policy.json``).
    """
    iot = boto3.client("iot")

    # 1) Create the claim key pair + certificate (the shared bootstrap identity).
    created = safe_api_call(
        iot.create_keys_and_certificate,
        "Create claim certificate",
        "claim-certificate",
        debug=debug,
        setAsActive=True,
    )
    if not created:
        print("❌ Could not create the claim certificate")
        sys.exit(1)

    claim_cert_id = created["certificateId"]
    claim_cert_arn = created["certificateArn"]
    with open(claim_cert_out, "w", encoding="utf-8") as handle:
        handle.write(created["certificatePem"])
    with open(claim_key_out, "w", encoding="utf-8") as handle:
        handle.write(created["keyPair"]["PrivateKey"])
    with open(claim_pub_out, "w", encoding="utf-8") as handle:
        handle.write(created["keyPair"]["PublicKey"])
    print(f"ℹ️  Claim certificate id: {claim_cert_id}")
    print(f"   Saved {claim_cert_out} / {claim_key_out} / {claim_pub_out}")

    # 2) Create the tightly scoped claim policy (connect + fleet-provisioning MQTT).
    with open(policy_file, "r", encoding="utf-8") as handle:
        policy_document = handle.read()
    safe_api_call(
        iot.create_policy,
        "Create claim policy",
        policy_name,
        debug=debug,
        policyName=policy_name,
        policyDocument=policy_document,
    )

    # 3) Attach the claim policy to the claim certificate.
    safe_api_call(
        iot.attach_policy,
        "Attach claim policy to claim certificate",
        policy_name,
        debug=debug,
        policyName=policy_name,
        target=claim_cert_arn,
    )
    print("\n🎉 Claim certificate ready and scoped to fleet provisioning only")
    print("   CA/Lambda/template are separate — this claim cert can ONLY bootstrap.")
    return claim_cert_id


def load_template_body(template_file):
    """Load a provisioning template JSON file and return it as a compact string."""
    with open(template_file, "r", encoding="utf-8") as handle:
        template = json.load(handle)
    # create-provisioning-template expects templateBody as a JSON *string*.
    return json.dumps(template, separators=(",", ":"))


def create_template(template_name, provisioning_role_arn, template_file,
                    hook_arn=None, debug=False):
    """Create the fleet provisioning template, optionally with a pre-provisioning hook.

    Wraps ``create-provisioning-template`` (with ``--pre-provisioning-hook`` when
    ``hook_arn`` is supplied). The template body is read from a JSON file so the
    learner can inspect exactly what is created.
    """
    iot = boto3.client("iot")

    kwargs = {
        "templateName": template_name,
        "templateBody": load_template_body(template_file),
        "provisioningRoleArn": provisioning_role_arn,
        "enabled": True,
    }
    if hook_arn:
        # The pre-provisioning hook runs synchronously during RegisterThing and
        # returns allowProvisioning + parameterOverrides.
        kwargs["preProvisioningHook"] = {"targetArn": hook_arn}

    response = safe_api_call(
        iot.create_provisioning_template,
        "Create fleet provisioning template",
        template_name,
        debug=debug,
        **kwargs,
    )
    if response:
        print(f"✅ Provisioning template '{template_name}' created (enabled)")
        if hook_arn:
            print(f"   Pre-provisioning hook attached: {hook_arn}")
    return response


def manage_versions(template_name, list_versions=False, new_version_file=None,
                    set_default=False, delete_version_id=None, debug=False):
    """List, create-as-default, or delete provisioning template versions."""
    iot = boto3.client("iot")

    if list_versions:
        response = safe_api_call(
            iot.list_provisioning_template_versions,
            "List provisioning template versions",
            template_name,
            debug=debug,
            templateName=template_name,
        )
        if response:
            for version in response.get("versions", []):
                default = " (default)" if version.get("isDefaultVersion") else ""
                print(f"   - version {version.get('versionId')}{default}")

    if new_version_file:
        response = safe_api_call(
            iot.create_provisioning_template_version,
            "Create provisioning template version",
            template_name,
            debug=debug,
            templateName=template_name,
            templateBody=load_template_body(new_version_file),
            setAsDefault=set_default,
        )
        if response:
            print(f"✅ Created version {response.get('versionId')}"
                  f"{' and set as default' if set_default else ''}")

    if delete_version_id is not None:
        safe_api_call(
            iot.delete_provisioning_template_version,
            "Delete provisioning template version",
            f"{template_name} v{delete_version_id}",
            debug=debug,
            templateName=template_name,
            versionId=int(delete_version_id),
        )
        print(f"✅ Deleted version {delete_version_id} (rollback)")


def observe(thing_name, debug=False):
    """Observe a provisioned device via describe-thing / list-thing-principals."""
    iot = boto3.client("iot")

    thing = safe_api_call(
        iot.describe_thing,
        "Describe thing",
        thing_name,
        debug=debug,
        thingName=thing_name,
    )
    if thing:
        print(f"ℹ️  Thing '{thing_name}' type={thing.get('thingTypeName')} "
              f"attributes={json.dumps(thing.get('attributes', {}))}")

    principals = safe_api_call(
        iot.list_thing_principals,
        "List thing principals",
        thing_name,
        debug=debug,
        thingName=thing_name,
    )
    if principals:
        for principal in principals.get("principals", []):
            print(f"   - principal: {principal}")


# =========================================================================
# Device plane (over the reused DeviceConnection / mqtt_connection_builder)
# =========================================================================


def _wait_for(device, accepted_topic, rejected_topic, timeout=20):
    """Poll the DeviceConnection inbox for an accepted/rejected reserved-topic reply."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with device.message_lock:
            for message in list(device.received_messages):
                if message["topic"] == accepted_topic:
                    return message["payload"]
                if message["topic"] == rejected_topic:
                    raise RuntimeError(
                        f"Fleet provisioning rejected on {rejected_topic}: "
                        f"{json.dumps(message['payload'])}"
                    )
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for a reply on {accepted_topic}")


def provision(template_name, claim_cert, claim_key, serial_number, model_type,
              endpoint=None, out_prefix=None, debug=False):
    """Run the fleet-provisioning MQTT exchange with the claim certificate.

    CreateKeysAndCertificate -> capture certificateOwnershipToken -> RegisterThing.
    Uses the shared ``DeviceConnection`` construct (same MQTT connection builder
    reused across sections). Saves the permanent certificate + private key.
    """
    endpoint = endpoint or get_iot_endpoint(debug=debug)
    out_prefix = out_prefix or serial_number

    device = DeviceConnection()
    print(f"🔌 Connecting with the CLAIM certificate to {endpoint} ...")
    device.connect(
        endpoint=endpoint,
        cert_filepath=claim_cert,
        pri_key_filepath=claim_key,
        client_id=f"claim-{serial_number}",
        debug=debug,
    )

    # 1) CreateKeysAndCertificate — AWS IoT Core mints the key pair + certificate.
    device.subscribe(CREATE_KEYS_ACCEPTED, qos=1)
    device.subscribe(CREATE_KEYS_REJECTED, qos=1)
    print(f"📨 Publishing {CREATE_KEYS_TOPIC} (empty payload) ...")
    device.publish(CREATE_KEYS_TOPIC, {}, qos=1)
    created = _wait_for(device, CREATE_KEYS_ACCEPTED, CREATE_KEYS_REJECTED)

    ownership_token = created["certificateOwnershipToken"]
    permanent_cert = created["certificatePem"]
    permanent_key = created["privateKey"]
    print(f"🔑 Received permanent certificate {created.get('certificateId', '')[:12]}... "
          f"and a certificateOwnershipToken")

    cert_out = f"{out_prefix}.cert.pem"
    key_out = f"{out_prefix}.private.key"
    with open(cert_out, "w", encoding="utf-8") as handle:
        handle.write(permanent_cert)
    with open(key_out, "w", encoding="utf-8") as handle:
        handle.write(permanent_key)
    print(f"   Saved {cert_out} / {key_out}")

    # 2) RegisterThing — prove ownership with the token; pass template parameters.
    provision_topic, provision_accepted, provision_rejected = _provision_topics(template_name)
    device.subscribe(provision_accepted, qos=1)
    device.subscribe(provision_rejected, qos=1)
    register_payload = {
        "certificateOwnershipToken": ownership_token,
        "parameters": {
            "SerialNumber": serial_number,
            "ModelType": model_type,
        },
    }
    print(f"📨 Publishing {provision_topic} with the ownership token + parameters ...")
    device.publish(provision_topic, register_payload, qos=1)
    registered = _wait_for(device, provision_accepted, provision_rejected)

    print("\n🎉 Device provisioned by claim")
    print(f"   thingName: {registered.get('thingName')}")
    print(f"   deviceConfiguration: {json.dumps(registered.get('deviceConfiguration', {}))}")
    print("   Now reconnect with the PERMANENT certificate "
          f"({cert_out}) to publish telemetry — the claim cert's job is done.")

    device.disconnect()
    return registered


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fleet Provisioning by Claim: claim cert, template, versioning, MQTT provision."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    claim = subparsers.add_parser("create-claim", help="Create claim cert + scoped policy.")
    claim.add_argument("--policy-name", default="FleetClaimPolicy", help="Claim policy name.")
    claim.add_argument("--policy-file", default=DEFAULT_CLAIM_POLICY_FILE, help="Claim policy JSON.")
    claim.add_argument("--claim-cert-out", default="claim.pem", help="Claim cert output path.")
    claim.add_argument("--claim-key-out", default="claim.private.key", help="Claim key output.")
    claim.add_argument("--claim-pub-out", default="claim.public.key", help="Claim public key output.")
    claim.add_argument("--debug", action="store_true", help="Verbose output.")

    template = subparsers.add_parser("create-template", help="Create fleet provisioning template.")
    template.add_argument("--template-name", default="FleetClaimTemplate", help="Template name.")
    template.add_argument("--provisioning-role-arn", required=True, help="Fleet provisioning role ARN.")
    template.add_argument("--template-file", default=DEFAULT_TEMPLATE_FILE, help="Template JSON path.")
    template.add_argument("--hook-arn", default=None, help="Pre-provisioning hook Lambda ARN.")
    template.add_argument("--debug", action="store_true", help="Verbose output.")

    prov = subparsers.add_parser("provision", help="Run the claim-based MQTT provisioning exchange.")
    prov.add_argument("--template-name", default="FleetClaimTemplate", help="Template name.")
    prov.add_argument("--claim-cert", default="claim.pem", help="Claim certificate path.")
    prov.add_argument("--claim-key", default="claim.private.key", help="Claim private key path.")
    prov.add_argument("--serial-number", required=True, help="Device SerialNumber (thing name).")
    prov.add_argument("--model-type", default="SedanVehicle", help="Device ModelType parameter.")
    prov.add_argument("--endpoint", default=None, help="iot:Data-ATS endpoint (auto-discovered if omitted).")
    prov.add_argument("--out-prefix", default=None, help="Output prefix for the permanent cert/key.")
    prov.add_argument("--debug", action="store_true", help="Verbose output.")

    versions = subparsers.add_parser("versions", help="Manage provisioning template versions.")
    versions.add_argument("--template-name", default="FleetClaimTemplate", help="Template name.")
    versions.add_argument("--list", action="store_true", help="List versions.")
    versions.add_argument("--new-version-file", default=None, help="New template body JSON to add.")
    versions.add_argument("--set-default", action="store_true", help="Set the new version as default.")
    versions.add_argument("--delete-version-id", default=None, help="Version id to delete (rollback).")
    versions.add_argument("--debug", action="store_true", help="Verbose output.")

    observe_parser = subparsers.add_parser("observe", help="describe-thing / list-thing-principals.")
    observe_parser.add_argument("--thing-name", required=True, help="Provisioned thing name.")
    observe_parser.add_argument("--debug", action="store_true", help="Verbose output.")

    return parser.parse_args()


def main():
    args = parse_arguments()

    if args.command == "create-claim":
        create_claim(
            policy_name=args.policy_name,
            policy_file=args.policy_file,
            claim_cert_out=args.claim_cert_out,
            claim_key_out=args.claim_key_out,
            claim_pub_out=args.claim_pub_out,
            debug=args.debug,
        )
    elif args.command == "create-template":
        create_template(
            template_name=args.template_name,
            provisioning_role_arn=args.provisioning_role_arn,
            template_file=args.template_file,
            hook_arn=args.hook_arn,
            debug=args.debug,
        )
    elif args.command == "provision":
        provision(
            template_name=args.template_name,
            claim_cert=args.claim_cert,
            claim_key=args.claim_key,
            serial_number=args.serial_number,
            model_type=args.model_type,
            endpoint=args.endpoint,
            out_prefix=args.out_prefix,
            debug=args.debug,
        )
    elif args.command == "versions":
        manage_versions(
            template_name=args.template_name,
            list_versions=args.list,
            new_version_file=args.new_version_file,
            set_default=args.set_default,
            delete_version_id=args.delete_version_id,
            debug=args.debug,
        )
    elif args.command == "observe":
        observe(thing_name=args.thing_name, debug=args.debug)


if __name__ == "__main__":
    main()
