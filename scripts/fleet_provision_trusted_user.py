#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Fleet Provisioning by Trusted User — control plane + device plane wrapper.

Control-plane + device-plane wrapper for Module 4, "Fleet Provisioning by
Trusted User" (design section 2.7). It wraps the exact CLI-first flow the module
content shows by hand, so learners can see the raw ``aws iot`` commands and
reserved MQTT topics first and then run the same flow end to end.

How trusted-user differs from provisioning by claim (Module 3)
--------------------------------------------------------------
The device leaves the factory with **no certificate at all**. Instead, a
**trusted user** — a mobile app or field installer, authenticated with
**temporary credentials** and a **tightly scoped AWS Identity and Access
Management (IAM) identity** — calls ``CreateProvisioningClaim`` to mint a
**temporary provisioning claim certificate** (it expires in about five minutes
and never appears in your account's certificate list). The app hands that
temporary claim to the device, and from there the device runs the **exact same
reserved-topic MQTT exchange as Module 3**: ``CreateCertificateFromCsr`` (or
``CreateKeysAndCertificate``) to get a permanent certificate plus a
``certificateOwnershipToken``, then ``RegisterThing`` to register itself.
There is no shared claim certificate burned into a batch of devices; a
human/app vouches for the device instead.

Two planes, one script
----------------------
- **Control plane** (``boto3`` / ``aws iot ...``, via the shared
  ``safe_api_call`` construct): create the fleet provisioning template and call
  ``CreateProvisioningClaim`` to obtain the temporary claim certificate.
- **Device plane** (MQTT, via the shared ``DeviceConnection`` construct in
  ``iot_helpers/utils/device_simulator.py`` — the same reused AWS IoT Core
  Learning SDK connection builder used by every other section): connect with the
  temporary claim certificate, obtain a permanent certificate and its
  ``certificateOwnershipToken``, and drive ``RegisterThing``.

Subcommands
-----------
    create-template  Create the trusted-user fleet provisioning template
                     (wraps create-provisioning-template).
    create-claim     Call CreateProvisioningClaim as the trusted user and save
                     the temporary claim certificate + key to disk
                     (wraps create-provisioning-claim).
    provision        Run the device-plane MQTT exchange with the temporary
                     claim cert: CreateCertificateFromCsr (or
                     CreateKeysAndCertificate) -> RegisterThing, using the
                     certificateOwnershipToken.
    observe          describe-thing / list-thing-principals for a provisioned
                     device.

Examples
--------
    python scripts/fleet_provision_trusted_user.py create-template \\
        --template-name TrustedUserTemplate \\
        --provisioning-role-arn arn:aws:iam::<account-id>:role/<stack>-fleet-provisioning-role

    python scripts/fleet_provision_trusted_user.py create-claim \\
        --template-name TrustedUserTemplate \\
        --claim-cert-out claim.pem --claim-key-out claim.private.key

    python scripts/fleet_provision_trusted_user.py provision \\
        --template-name TrustedUserTemplate \\
        --claim-cert claim.pem --claim-key claim.private.key \\
        --serial-number SmartHome-Sensor-042 --device-type SmartHomeSensor \\
        --csr-file SmartHome-Sensor-042.csr
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


TEMPLATE_DIR = os.path.join(
    REPO_ROOT, "iot_helpers", "utils", "fleet_provisioning_templates"
)
DEFAULT_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, "trusted-user-template.json")

# Reserved MQTT topics for the fleet-provisioning device-plane exchange. The
# module content shows these raw first; this script publishes/subscribes on the
# exact same topics. They are identical to the by-claim flow (Module 3) — only
# the way the device obtains its claim certificate differs (a trusted user mints
# a temporary one server-side instead of a shared cert being burned in).
CREATE_KEYS_TOPIC = "$aws/certificates/create/json"
CREATE_KEYS_ACCEPTED = "$aws/certificates/create/json/accepted"
CREATE_KEYS_REJECTED = "$aws/certificates/create/json/rejected"

# Reserved MQTT topics for the CSR variant (CreateCertificateFromCsr): the device
# generates and keeps its own private key and sends only a CSR. Preferred from a
# security standpoint - the private key never travels over the wire - and the
# default path this script's provision() takes; CreateKeysAndCertificate above
# is the fallback for a device that cannot generate its own key pair.
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


def load_template_body(template_file):
    """Load a provisioning template JSON file and return it as a compact string."""
    with open(template_file, "r", encoding="utf-8") as handle:
        template = json.load(handle)
    # create-provisioning-template expects templateBody as a JSON *string*.
    return json.dumps(template, separators=(",", ":"))


# =========================================================================
# Control plane
# =========================================================================


def create_template(template_name, provisioning_role_arn, template_file, debug=False):
    """Create the trusted-user fleet provisioning template.

    Wraps ``create-provisioning-template``. Unlike the by-claim template in
    Module 3, the trusted-user template needs no pre-provisioning hook: the
    ``CreateProvisioningClaim`` call is already gated by the trusted user's
    tightly scoped IAM identity, so authorization happens before the device ever
    connects. The template body is read from a JSON file so the learner can
    inspect exactly what is created.
    """
    iot = boto3.client("iot")

    response = safe_api_call(
        iot.create_provisioning_template,
        "Create trusted-user provisioning template",
        template_name,
        debug=debug,
        templateName=template_name,
        templateBody=load_template_body(template_file),
        provisioningRoleArn=provisioning_role_arn,
        enabled=True,
    )
    if response:
        print(get_message("status.template_created", template_name))
        print(get_message("status.template_no_hook"))
    return response


def create_claim(template_name, claim_cert_out, claim_key_out, claim_pub_out=None,
                 debug=False):
    """Call CreateProvisioningClaim as the trusted user; save the temporary claim.

    Wraps ``create-provisioning-claim``. This is the control-plane action the
    trusted user (mobile app / installer) performs with its temporary,
    scoped credentials. The returned certificate is TEMPORARY — it expires in
    about five minutes, never appears in the account's certificate list, and is
    only good enough to drive the fleet-provisioning MQTT exchange that follows.
    """
    iot = boto3.client("iot")

    claim = safe_api_call(
        iot.create_provisioning_claim,
        "Create provisioning claim (trusted user)",
        template_name,
        debug=debug,
        templateName=template_name,
    )
    if not claim:
        print(get_message("errors.claim_create_failed"))
        sys.exit(1)

    with open(claim_cert_out, "w", encoding="utf-8") as handle:
        handle.write(claim["certificatePem"])
    with open(claim_key_out, "w", encoding="utf-8") as handle:
        handle.write(claim["keyPair"]["PrivateKey"])
    if claim_pub_out:
        with open(claim_pub_out, "w", encoding="utf-8") as handle:
            handle.write(claim["keyPair"]["PublicKey"])

    print(get_message("status.claim_minted", template_name))
    print(get_message("status.saved_claim_files", claim_cert_out, claim_key_out))
    print(get_message("status.claim_expires", claim.get("expiration")))
    print(get_message("status.claim_note"))
    return claim


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
        print(get_message("status.thing_info", thing_name, thing.get("thingTypeName"),
                          json.dumps(thing.get("attributes", {}))))

    principals = safe_api_call(
        iot.list_thing_principals,
        "List thing principals",
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
                        f"Fleet provisioning rejected on {rejected_topic}: "
                        f"{json.dumps(message['payload'])}"
                    )
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for a reply on {accepted_topic}")


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
    matches the CSR.
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


def provision(template_name, claim_cert, claim_key, serial_number, device_type,
              endpoint=None, out_prefix=None, csr_file=None, debug=False):
    """Run the fleet-provisioning MQTT exchange with the temporary claim certificate.

    CreateCertificateFromCsr (when ``csr_file`` is supplied) or
    CreateKeysAndCertificate (the fallback, when it is omitted) -> capture
    certificateOwnershipToken -> RegisterThing. This is the identical
    device-plane exchange as ``fleet_provision_by_claim.py``; only the origin of
    the claim certificate differs (a trusted user minted a temporary one via
    CreateProvisioningClaim). Uses the shared ``DeviceConnection`` construct.
    """
    endpoint = endpoint or get_iot_endpoint(debug=debug)
    out_prefix = out_prefix or serial_number

    device = DeviceConnection()
    print(get_message("status.connecting_claim", endpoint))
    device.connect(
        endpoint=endpoint,
        cert_filepath=claim_cert,
        pri_key_filepath=claim_key,
        client_id=f"trusted-user-{serial_number}",
        debug=debug,
    )

    # 1) Obtain a permanent certificate + certificateOwnershipToken. The CSR path
    #    keeps the private key on the device; the keys path has AWS IoT Core mint
    #    both. Both return the same certificateOwnershipToken for step 2.
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
            "DeviceType": device_type,
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
    print(get_message("status.provisioned_device_config",
                      json.dumps(registered.get("deviceConfiguration", {}))))
    print(get_message("status.provisioned_reconnect", cert_out))

    device.disconnect()
    return registered


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fleet Provisioning by Trusted User: template, CreateProvisioningClaim, MQTT provision."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    template = subparsers.add_parser("create-template", help="Create trusted-user provisioning template.")
    template.add_argument("--template-name", default="TrustedUserTemplate", help="Template name.")
    template.add_argument("--provisioning-role-arn", required=True, help="Fleet provisioning role ARN.")
    template.add_argument("--template-file", default=DEFAULT_TEMPLATE_FILE, help="Template JSON path.")
    template.add_argument("--debug", action="store_true", help="Verbose output.")

    claim = subparsers.add_parser("create-claim", help="CreateProvisioningClaim as the trusted user.")
    claim.add_argument("--template-name", default="TrustedUserTemplate", help="Template name.")
    claim.add_argument("--claim-cert-out", default="claim.pem", help="Temporary claim cert output path.")
    claim.add_argument("--claim-key-out", default="claim.private.key", help="Temporary claim key output.")
    claim.add_argument("--claim-pub-out", default=None, help="Temporary claim public key output (optional).")
    claim.add_argument("--debug", action="store_true", help="Verbose output.")

    prov = subparsers.add_parser("provision", help="Run the trusted-user MQTT provisioning exchange.")
    prov.add_argument("--template-name", default="TrustedUserTemplate", help="Template name.")
    prov.add_argument("--claim-cert", default="claim.pem", help="Temporary claim certificate path.")
    prov.add_argument("--claim-key", default="claim.private.key", help="Temporary claim private key path.")
    prov.add_argument("--serial-number", required=True, help="Device SerialNumber (thing name).")
    prov.add_argument("--device-type", default="SmartHomeSensor", help="Device DeviceType parameter.")
    prov.add_argument("--endpoint", default=None, help="iot:Data-ATS endpoint (auto-discovered if omitted).")
    prov.add_argument("--out-prefix", default=None, help="Output prefix for the permanent cert/key.")
    prov.add_argument("--csr-file", default=None,
                     help="CSR PEM to use CreateCertificateFromCsr (device keeps its own key). "
                          "Omit to use CreateKeysAndCertificate.")
    prov.add_argument("--debug", action="store_true", help="Verbose output.")

    observe_parser = subparsers.add_parser("observe", help="describe-thing / list-thing-principals.")
    observe_parser.add_argument("--thing-name", required=True, help="Provisioned thing name.")
    observe_parser.add_argument("--debug", action="store_true", help="Verbose output.")

    return parser.parse_args()


def main():
    args = parse_arguments()

    # Load the localized message catalog once, before any user-facing print.
    # (Placed after argument parsing so --help stays free of the language menu.)
    global messages
    messages = load_messages("fleet_provision_trusted_user", get_language())

    if args.command == "create-template":
        create_template(
            template_name=args.template_name,
            provisioning_role_arn=args.provisioning_role_arn,
            template_file=args.template_file,
            debug=args.debug,
        )
    elif args.command == "create-claim":
        create_claim(
            template_name=args.template_name,
            claim_cert_out=args.claim_cert_out,
            claim_key_out=args.claim_key_out,
            claim_pub_out=args.claim_pub_out,
            debug=args.debug,
        )
    elif args.command == "provision":
        provision(
            template_name=args.template_name,
            claim_cert=args.claim_cert,
            claim_key=args.claim_key,
            serial_number=args.serial_number,
            device_type=args.device_type,
            endpoint=args.endpoint,
            out_prefix=args.out_prefix,
            csr_file=args.csr_file,
            debug=args.debug,
        )
    elif args.command == "observe":
        observe(thing_name=args.thing_name, debug=args.debug)


if __name__ == "__main__":
    main()
