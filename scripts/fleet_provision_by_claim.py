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
from iot_helpers.utils.api_helpers import set_language as set_api_helpers_language  # noqa: E402
from iot_helpers.utils.device_simulator import (  # noqa: E402
    DeviceConnection,
    get_iot_endpoint,
)
from iot_helpers.utils.device_simulator import set_language as set_device_simulator_language  # noqa: E402
from language_selector import get_language, peek_language  # noqa: E402
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


TEMPLATE_DIR = os.path.join(REPO_ROOT, "iot_helpers", "utils", "fleet_provisioning_templates")
DEFAULT_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, "fleet-claim-template.json")
DEFAULT_CLAIM_POLICY_FILE = os.path.join(TEMPLATE_DIR, "claim-policy.json")

# Reserved MQTT topics for the fleet-provisioning device-plane exchange. The
# module content shows these raw first; this script publishes/subscribes on the
# exact same topics.
CREATE_KEYS_TOPIC = "$aws/certificates/create/json"
CREATE_KEYS_ACCEPTED = "$aws/certificates/create/json/accepted"
CREATE_KEYS_REJECTED = "$aws/certificates/create/json/rejected"

# Reserved MQTT topics for the CSR variant (CreateCertificateFromCsr): the device
# generates and keeps its own private key and sends only a CSR. This is also the
# path the OPTIONAL certificate-provider lab exercises — once a certificate
# provider is registered, AWS IoT Core routes each of these CSRs through your
# signing Lambda instead of signing with the Amazon CA.
CREATE_CSR_TOPIC = "$aws/certificates/create-from-csr/json"
CREATE_CSR_ACCEPTED = "$aws/certificates/create-from-csr/json/accepted"
CREATE_CSR_REJECTED = "$aws/certificates/create-from-csr/json/rejected"


def _provision_topics(template_name):
    """Return the RegisterThing publish/accepted/rejected topics for a template."""
    base = f"$aws/provisioning-templates/{template_name}/provision/json"
    return base, f"{base}/accepted", f"{base}/rejected"


# --- Verbose MQTT payload display (educational) --------------------------
# The module teaches the reserved-topic request/response, so by default this
# script prints the FULL payload it publishes and receives on each topic. Long
# secret fields (PEMs, private key, ownership token) are truncated so the shape
# stays readable and a full private key is not dumped to the terminal.
_TRUNCATE_KEYS = ("certificatePem", "privateKey", "publicKey", "keyPair")


def _fmt_payload(payload):
    """Pretty-print an MQTT payload, truncating long/secret fields for readability."""

    def _trunc(key, value):
        if isinstance(value, str) and key in _TRUNCATE_KEYS:
            first = value.strip().splitlines()[0] if value.strip() else ""
            return f"{first} …(truncated, {len(value)} chars total)"
        if isinstance(value, str) and key == "certificateOwnershipToken":
            return f"{value[:16]}… (truncated, {len(value)} chars total)"
        return value

    shown = {k: _trunc(k, v) for k, v in payload.items()} if isinstance(payload, dict) else payload
    return json.dumps(shown, indent=2)


def _indent(text, prefix="   "):
    """Indent every line of a block for a tidy 'topic → payload' display."""
    return "\n".join(prefix + line for line in text.splitlines())


# =========================================================================
# Control plane
# =========================================================================


def create_claim(policy_name, policy_file, claim_cert_out, claim_key_out, claim_pub_out, debug=False):
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
        get_message("operations.create_claim_certificate"),
        "claim-certificate",
        debug=debug,
        setAsActive=True,
    )
    if not created:
        print(get_message("errors.claim_create_failed"))
        sys.exit(1)

    claim_cert_id = created["certificateId"]
    claim_cert_arn = created["certificateArn"]
    with open(claim_cert_out, "w", encoding="utf-8") as handle:
        handle.write(created["certificatePem"])
    with open(claim_key_out, "w", encoding="utf-8") as handle:
        handle.write(created["keyPair"]["PrivateKey"])
    with open(claim_pub_out, "w", encoding="utf-8") as handle:
        handle.write(created["keyPair"]["PublicKey"])
    print(get_message("status.claim_cert_id", claim_cert_id))
    print(get_message("status.saved_claim_files", claim_cert_out, claim_key_out, claim_pub_out))

    # 2) Create the tightly scoped claim policy (connect + fleet-provisioning MQTT).
    with open(policy_file, "r", encoding="utf-8") as handle:
        policy_document = handle.read()
    safe_api_call(
        iot.create_policy,
        get_message("operations.create_claim_policy"),
        policy_name,
        debug=debug,
        policyName=policy_name,
        policyDocument=policy_document,
    )

    # 3) Attach the claim policy to the claim certificate.
    safe_api_call(
        iot.attach_policy,
        get_message("operations.attach_claim_policy_to_claim_certificate"),
        policy_name,
        debug=debug,
        policyName=policy_name,
        target=claim_cert_arn,
    )
    print(f"\n{get_message('status.claim_ready')}")
    print(get_message("status.claim_ready_detail"))
    return claim_cert_id


def load_template_body(template_file):
    """Load a provisioning template JSON file and return it as a compact string."""
    with open(template_file, "r", encoding="utf-8") as handle:
        template = json.load(handle)
    # create-provisioning-template expects templateBody as a JSON *string*.
    return json.dumps(template, separators=(",", ":"))


def create_template(template_name, provisioning_role_arn, template_file, hook_arn=None, debug=False):
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
        get_message("operations.create_fleet_provisioning_template"),
        template_name,
        debug=debug,
        **kwargs,
    )
    if response:
        print(get_message("status.template_created", template_name))
        if hook_arn:
            print(get_message("status.hook_attached", hook_arn))
    return response


def manage_versions(
    template_name, list_versions=False, new_version_file=None, set_default=False, delete_version_id=None, debug=False
):
    """List, create-as-default, or delete provisioning template versions."""
    iot = boto3.client("iot")

    if list_versions:
        response = safe_api_call(
            iot.list_provisioning_template_versions,
            get_message("operations.list_provisioning_template_versions"),
            template_name,
            debug=debug,
            templateName=template_name,
        )
        if response:
            for version in response.get("versions", []):
                default = get_message("status.version_default_marker") if version.get("isDefaultVersion") else ""
                print(get_message("status.version_line", version.get("versionId"), default))

    if new_version_file:
        response = safe_api_call(
            iot.create_provisioning_template_version,
            get_message("operations.create_provisioning_template_version"),
            template_name,
            debug=debug,
            templateName=template_name,
            templateBody=load_template_body(new_version_file),
            setAsDefault=set_default,
        )
        if response:
            suffix = get_message("status.version_set_default_suffix") if set_default else ""
            print(get_message("status.version_created", response.get("versionId"), suffix))

    if delete_version_id is not None:
        safe_api_call(
            iot.delete_provisioning_template_version,
            get_message("operations.delete_provisioning_template_version"),
            get_message("operation_resources.template_version", template_name, delete_version_id),
            debug=debug,
            templateName=template_name,
            versionId=int(delete_version_id),
        )
        print(get_message("status.version_deleted", delete_version_id))


def observe(thing_name, debug=False):
    """Observe a provisioned device via describe-thing / list-thing-principals."""
    iot = boto3.client("iot")

    thing = safe_api_call(
        iot.describe_thing,
        get_message("operations.describe_thing"),
        thing_name,
        debug=debug,
        thingName=thing_name,
    )
    if thing:
        print(
            get_message("status.thing_info", thing_name, thing.get("thingTypeName"), json.dumps(thing.get("attributes", {})))
        )

    principals = safe_api_call(
        iot.list_thing_principals,
        get_message("operations.list_thing_principals"),
        thing_name,
        debug=debug,
        thingName=thing_name,
    )
    if principals:
        for principal in principals.get("principals", []):
            print(get_message("status.principal_line", principal))


# =========================================================================
# Device plane (over the reused DeviceConnection / mqtt5_client_builder)
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
                        get_message("errors.provisioning_rejected", rejected_topic, json.dumps(message["payload"]))
                    )
        time.sleep(0.25)  # nosemgrep: arbitrary-sleep
    raise TimeoutError(get_message("errors.reply_timeout", accepted_topic))


def _create_keys_and_certificate(device, out_prefix):
    """CreateKeysAndCertificate path: AWS IoT Core mints the key pair + certificate.

    Returns ``(ownership_token, cert_out)``. Saves both the permanent certificate
    and the private key AWS IoT Core generated and returned over MQTT.
    """
    print(get_message("mqtt.subscribe", CREATE_KEYS_ACCEPTED))
    print(get_message("mqtt.subscribe", CREATE_KEYS_REJECTED))
    device.subscribe(CREATE_KEYS_ACCEPTED, qos=1)
    device.subscribe(CREATE_KEYS_REJECTED, qos=1)
    print(f"\n{get_message('mqtt.publish', CREATE_KEYS_TOPIC)}")
    print(get_message("mqtt.publish_empty_payload"))
    device.publish(CREATE_KEYS_TOPIC, {}, qos=1)
    created = _wait_for(device, CREATE_KEYS_ACCEPTED, CREATE_KEYS_REJECTED)
    print(get_message("mqtt.received", CREATE_KEYS_ACCEPTED))
    print(_indent(_fmt_payload(created)))

    print(f"\n{get_message('status.extracted_cert', created.get('certificateId', '')[:12])}")
    cert_out = f"{out_prefix}.cert.pem"
    key_out = f"{out_prefix}.private.key"
    with open(cert_out, "w", encoding="utf-8") as handle:
        handle.write(created["certificatePem"])
    with open(key_out, "w", encoding="utf-8") as handle:
        handle.write(created["privateKey"])
    print(get_message("status.saved_cert_key", cert_out, key_out))
    return created["certificateOwnershipToken"], cert_out


def _create_certificate_from_csr(device, out_prefix, csr_file):
    """CreateCertificateFromCsr path: the device keeps its own key, sends a CSR.

    Returns ``(ownership_token, cert_out)``. Only the certificate is returned by
    AWS IoT Core (never a private key) — the device already holds the key that
    matches the CSR. This is the path the certificate-provider lab exercises: if a
    certificate provider is registered, the returned certificate is signed by your
    own CA instead of the Amazon CA.
    """
    with open(csr_file, "r", encoding="utf-8") as handle:
        csr_pem = handle.read()

    print(get_message("mqtt.subscribe", CREATE_CSR_ACCEPTED))
    print(get_message("mqtt.subscribe", CREATE_CSR_REJECTED))
    device.subscribe(CREATE_CSR_ACCEPTED, qos=1)
    device.subscribe(CREATE_CSR_REJECTED, qos=1)
    print(f"\n{get_message('mqtt.publish', CREATE_CSR_TOPIC)}")
    print(get_message("mqtt.publish_csr_payload", csr_file))
    device.publish(CREATE_CSR_TOPIC, {"certificateSigningRequest": csr_pem}, qos=1)
    created = _wait_for(device, CREATE_CSR_ACCEPTED, CREATE_CSR_REJECTED)
    print(get_message("mqtt.received", CREATE_CSR_ACCEPTED))
    print(_indent(_fmt_payload(created)))

    print(f"\n{get_message('status.extracted_cert', created.get('certificateId', '')[:12])}")
    print(get_message("status.extracted_cert_csr_note"))
    cert_out = f"{out_prefix}.cert.pem"
    with open(cert_out, "w", encoding="utf-8") as handle:
        handle.write(created["certificatePem"])
    print(get_message("status.saved_cert_csr", cert_out))
    return created["certificateOwnershipToken"], cert_out


def provision(
    template_name, claim_cert, claim_key, serial_number, model_type, endpoint=None, out_prefix=None, csr_file=None, debug=False
):
    """Run the fleet-provisioning MQTT exchange with the claim certificate.

    CreateKeysAndCertificate (default) or CreateCertificateFromCsr (when
    ``csr_file`` is supplied) -> capture certificateOwnershipToken ->
    RegisterThing. Uses the shared ``DeviceConnection`` construct (same MQTT
    connection builder reused across sections).
    """
    endpoint = endpoint or get_iot_endpoint(debug=debug)
    out_prefix = out_prefix or serial_number

    device = DeviceConnection()
    print(get_message("status.connecting_claim", endpoint))
    device.connect(
        endpoint=endpoint,
        cert_filepath=claim_cert,
        pri_key_filepath=claim_key,
        client_id=f"claim-{serial_number}",
        debug=debug,
    )

    # A rejected RegisterThing (Challenge 2's deliberate scenario: a serial
    # number/model the pre-provisioning hook does not recognize) raises
    # RuntimeError from _wait_for. Without this try/finally, that exception
    # skipped device.disconnect() below and surfaced as a raw traceback
    # instead of the clean, expected failure message the content walks
    # through.
    try:
        # 1) Obtain a permanent certificate + certificateOwnershipToken. The CSR
        #    path keeps the private key on the device; the keys path has AWS IoT
        #    Core mint both. Both return the same certificateOwnershipToken.
        if csr_file:
            ownership_token, cert_out = _create_certificate_from_csr(device, out_prefix, csr_file)
        else:
            ownership_token, cert_out = _create_keys_and_certificate(device, out_prefix)

        # 2) RegisterThing — prove ownership with the token; pass template parameters.
        provision_topic, provision_accepted, provision_rejected = _provision_topics(template_name)
        print(f"\n{get_message('mqtt.subscribe', provision_accepted)}")
        print(get_message("mqtt.subscribe", provision_rejected))
        device.subscribe(provision_accepted, qos=1)
        device.subscribe(provision_rejected, qos=1)
        register_payload = {
            "certificateOwnershipToken": ownership_token,
            "parameters": {
                "SerialNumber": serial_number,
                "ModelType": model_type,
            },
        }
        print(f"\n{get_message('mqtt.publish', provision_topic)}")
        print(_indent(_fmt_payload(register_payload)))
        device.publish(provision_topic, register_payload, qos=1)
        registered = _wait_for(device, provision_accepted, provision_rejected)
        print(get_message("mqtt.received", provision_accepted))
        print(_indent(_fmt_payload(registered)))

        print(f"\n{get_message('status.provisioned')}")
        print(get_message("status.provisioned_thing_name", registered.get("thingName")))
        print(get_message("status.provisioned_device_config", json.dumps(registered.get("deviceConfiguration", {}))))
        print(get_message("status.provisioned_reconnect", cert_out))

        return registered
    except (RuntimeError, TimeoutError) as error:
        print(get_message("errors.provisioning_failed", str(error)))
        sys.exit(1)
    finally:
        device.disconnect()


def parse_arguments():
    """Parse command-line arguments."""

    # Help text comes from the "cli" category of this script's catalog. It is
    # loaded with peek_language() -- which never prompts -- because the parser is
    # built before the runtime language is chosen, so --help never shows the
    # interactive language menu. The runtime ``messages`` catalog is still
    # loaded in main() exactly as before.
    help_messages = load_messages("fleet_provision_by_claim", peek_language())

    def cli(key):
        """Resolve a nested ``cli.*`` help string; fall back to the raw key."""
        msg = help_messages.get("cli", {})
        for part in key.split("."):
            if isinstance(msg, dict) and part in msg:
                msg = msg[part]
            else:
                return "cli." + key
        return msg

    parser = argparse.ArgumentParser(description=cli("description"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    claim = subparsers.add_parser("create-claim", help=cli("create_claim.help"))
    claim.add_argument("--policy-name", default="FleetClaimPolicy", help=cli("create_claim.policy_name"))
    claim.add_argument("--policy-file", default=DEFAULT_CLAIM_POLICY_FILE, help=cli("create_claim.policy_file"))
    claim.add_argument("--claim-cert-out", default="claim.pem", help=cli("create_claim.claim_cert_out"))
    claim.add_argument("--claim-key-out", default="claim.private.key", help=cli("create_claim.claim_key_out"))
    claim.add_argument("--claim-pub-out", default="claim.public.key", help=cli("create_claim.claim_pub_out"))
    claim.add_argument("--debug", action="store_true", help=cli("create_claim.debug"))

    template = subparsers.add_parser("create-template", help=cli("create_template.help"))
    template.add_argument("--template-name", default="FleetClaimTemplate", help=cli("create_template.template_name"))
    template.add_argument("--provisioning-role-arn", required=True, help=cli("create_template.provisioning_role_arn"))
    template.add_argument("--template-file", default=DEFAULT_TEMPLATE_FILE, help=cli("create_template.template_file"))
    template.add_argument("--hook-arn", default=None, help=cli("create_template.hook_arn"))
    template.add_argument("--debug", action="store_true", help=cli("create_template.debug"))

    prov = subparsers.add_parser("provision", help=cli("provision.help"))
    prov.add_argument("--template-name", default="FleetClaimTemplate", help=cli("provision.template_name"))
    prov.add_argument("--claim-cert", default="claim.pem", help=cli("provision.claim_cert"))
    prov.add_argument("--claim-key", default="claim.private.key", help=cli("provision.claim_key"))
    prov.add_argument("--serial-number", required=True, help=cli("provision.serial_number"))
    prov.add_argument("--model-type", default="SedanVehicle", help=cli("provision.model_type"))
    prov.add_argument("--endpoint", default=None, help=cli("provision.endpoint"))
    prov.add_argument("--out-prefix", default=None, help=cli("provision.out_prefix"))
    prov.add_argument(
        "--csr-file",
        default=None,
        help=cli("provision.csr_file"),
    )
    prov.add_argument("--debug", action="store_true", help=cli("provision.debug"))

    versions = subparsers.add_parser("versions", help=cli("versions.help"))
    versions.add_argument("--template-name", default="FleetClaimTemplate", help=cli("versions.template_name"))
    versions.add_argument("--list", action="store_true", help=cli("versions.list"))
    versions.add_argument("--new-version-file", default=None, help=cli("versions.new_version_file"))
    versions.add_argument("--set-default", action="store_true", help=cli("versions.set_default"))
    versions.add_argument("--delete-version-id", default=None, help=cli("versions.delete_version_id"))
    versions.add_argument("--debug", action="store_true", help=cli("versions.debug"))

    observe_parser = subparsers.add_parser("observe", help=cli("observe.help"))
    observe_parser.add_argument("--thing-name", required=True, help=cli("observe.thing_name"))
    observe_parser.add_argument("--debug", action="store_true", help=cli("observe.debug"))

    return parser.parse_args()


def main():
    args = parse_arguments()

    # Load the localized message catalog once, before any user-facing print.
    # (Placed after argument parsing so --help stays free of the language menu.)
    global messages
    language = get_language()
    messages = load_messages("fleet_provision_by_claim", language)
    # Apply the same runtime language to the shared helpers' own catalogs.
    set_api_helpers_language(language)
    set_device_simulator_language(language)

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
            csr_file=args.csr_file,
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
