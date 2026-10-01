#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Multi-Account Registration (MAR) — two-region move wrapper (control + device plane).

Control-plane + device-plane wrapper for Module 5, "Multi-Account Registration"
(design section 2.8). It automates the exact CLI-first flow the module content
shows by hand, so learners see the raw ``aws iot`` commands first and then run
the same move end to end.

What MAR is (and is NOT)
------------------------
MAR is not a way to *first* provision a device — it is the cross-account /
cross-region **move overlay**. A device already holds a registered certificate;
MAR makes a **second** account or Region recognize that **same** certificate
**without re-issuing it**, and the device is then reconnected to the
destination's endpoint. The lobby-to-production "move" is fundamentally an
**endpoint change with same-certificate reuse** — no new certificate is minted.

This is a different mechanism from the fleet-provisioning
``certificateOwnershipToken`` used in Modules 3 and 4: that token proves
ownership of a certificate AWS IoT Core *just issued* over an MQTT provisioning
exchange, and it never crosses an account boundary. MAR operates entirely over
the control-plane AWS CLI.

Two-region simulation
---------------------
A Workshop Studio account allows several accessible Regions but only one
deployable Region, so the account-to-account move is simulated with **two
Regions in one account**: Region 1 (the Region where the workshop runs) is the
"lobby", and a second Region (referenced with ``--region``) is the "production"
stand-in. In a true two-account deployment the same ``register-certificate-without-ca``
call runs in the second *account* instead of a second Region — the device-side
endpoint change is identical.

Two planes, one script
----------------------
- **Control plane** (``boto3`` / ``aws iot ...``, via the shared
  ``safe_api_call`` construct): ``register-certificate-without-ca`` (or
  ``register-ca-certificate --certificate-mode SNI_ONLY``) in the destination
  Region, plus ``describe-endpoint`` to obtain the destination endpoint.
- **Device plane** (MQTT, via the shared ``DeviceConnection`` construct in
  ``iot_helpers/utils/device_simulator.py`` — the same reused AWS IoT Core
  Learning SDK connection builder used by every other section): reconnect the
  **same** certificate to the destination endpoint. Only the ``endpoint``
  argument changes between the lobby connect and the production connect.

Subcommands
-----------
    register-without-ca  Register an existing device certificate in the
                         destination Region without a CA, optionally creating
                         and attaching a device policy and a thing
                         (wraps register-certificate-without-ca).
    register-ca-sni      Register a Certificate Authority in the destination
                         Region in SNI_ONLY (multi-account) mode, so every
                         device certificate it signed is trusted there
                         (wraps register-ca-certificate --certificate-mode SNI_ONLY).
    endpoint             describe-endpoint --endpoint-type iot:Data-ATS for a
                         Region (the destination endpoint the device moves to).
    move                 Reconnect the SAME certificate to the destination
                         Region's endpoint over the shared DeviceConnection —
                         the "move" is an endpoint change, not a re-mint.

Examples
--------
    python scripts/manage_multi_account_registration.py register-without-ca \\
        --region us-west-2 --certificate-pem device.pem \\
        --policy-name MARProductionDevicePolicy \\
        --policy-document mar-device-policy.json \\
        --thing-name Vehicle-VIN-MAR-001

    python scripts/manage_multi_account_registration.py register-ca-sni \\
        --region us-west-2 --ca-certificate rootCA.pem

    python scripts/manage_multi_account_registration.py endpoint --region us-west-2

    python scripts/manage_multi_account_registration.py move \\
        --region us-west-2 --thing-name Vehicle-VIN-MAR-001 \\
        --cert device.pem --key device.private.key
"""

import argparse
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
from iot_helpers.utils.device_simulator import DeviceConnection  # noqa: E402
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


# Telemetry topic the moved device publishes on (matches the module content).
TELEMETRY_TOPIC = "anycompany/telemetry"


def _iot_client(region=None):
    """Return an AWS IoT control-plane client, Region-scoped when a Region is given.

    MAR is inherently multi-Region: the destination steps run against the
    "production" stand-in Region, so those calls use a Region-scoped client
    (``boto3.client("iot", region_name=region)``). When ``region`` is omitted,
    the default-Region client is used (the "lobby" / the Region where the
    workshop runs).
    """
    if region:
        return boto3.client("iot", region_name=region)
    return boto3.client("iot")


def _read_pem(path):
    """Read a PEM file (certificate or CA) and return its text."""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _account_id():
    """Return the current account id (for building destination certificate ARNs)."""
    return boto3.client("sts").get_caller_identity()["Account"]


# =========================================================================
# Control plane
# =========================================================================


def register_without_ca(certificate_pem, region, policy_name=None, policy_document=None, thing_name=None, debug=False):
    """Register an existing device certificate in the destination Region (MAR core).

    Wraps ``register-certificate-without-ca``. This is the heart of MAR: it
    re-registers the SAME certificate PEM in a second Region (or, in production,
    a second account) and marks it ACTIVE — no new certificate is minted, and
    the certificate's issuing CA does not need to be registered there. The
    returned ``certificateId`` is derived from the certificate itself, so it is
    IDENTICAL to the id the certificate has in the lobby Region — the strongest
    signal that this is a move, not a re-mint.

    Optionally creates + attaches a device policy and a thing in the destination
    Region (certificates, policies, and things are all per-Region).
    """
    iot = _iot_client(region)

    response = safe_api_call(
        iot.register_certificate_without_ca,
        get_message("operations.register_certificate_without_ca_mar"),
        get_message("operation_resources.certificate_in_region", region),
        debug=debug,
        certificatePem=_read_pem(certificate_pem),
        status="ACTIVE",
    )
    if not response:
        print(get_message("errors.register_without_ca_failed"))
        sys.exit(1)

    # Capture the id straight from the registering call (not a broad list-certificates):
    # earlier sections leave certs ACTIVE and list order is not guaranteed.
    certificate_id = response.get("certificateId")
    certificate_arn = response.get("certificateArn")
    print(f"\n{get_message('status.cert_registered_header')}")
    print(get_message("status.cert_registered_region", region))
    print(get_message("status.cert_registered_id", certificate_id))
    print(get_message("status.cert_id_derived_note"))

    # Rebuild the ARN if the API did not return it (older API shapes).
    if not certificate_arn and certificate_id:
        certificate_arn = f"arn:aws:iot:{region}:{_account_id()}:cert/{certificate_id}"

    if policy_name:
        if policy_document:
            safe_api_call(
                iot.create_policy,
                get_message("operations.create_destination_device_policy"),
                policy_name,
                debug=debug,
                policyName=policy_name,
                policyDocument=_read_pem(policy_document),
            )
        safe_api_call(
            iot.attach_policy,
            get_message("operations.attach_device_policy_to_moved_certificate"),
            policy_name,
            debug=debug,
            policyName=policy_name,
            target=certificate_arn,
        )

    if thing_name:
        safe_api_call(
            iot.create_thing,
            get_message("operations.create_thing_in_destination_region"),
            thing_name,
            debug=debug,
            thingName=thing_name,
        )
        safe_api_call(
            iot.attach_thing_principal,
            get_message("operations.attach_moved_certificate_to_thing"),
            thing_name,
            debug=debug,
            thingName=thing_name,
            principal=certificate_arn,
        )

    print(f"\n{get_message('status.same_cert_recognized')}")
    print(get_message("status.next_get_endpoint"))
    return certificate_id


def register_ca_sni(ca_certificate, region, debug=False):
    """Register a Certificate Authority in SNI_ONLY (multi-account) mode.

    Wraps ``register-ca-certificate --certificate-mode SNI_ONLY``. This is the
    fleet-scale alternative to ``register-certificate-without-ca``: instead of
    moving one certificate at a time, register the CA in SNI_ONLY mode in the
    destination so that EVERY device certificate that CA signed is trusted
    there, validated by the Server Name Indication (SNI) hostname the device
    presents during the TLS handshake. SNI_ONLY is the multi-account mode (a CA
    can be registered this way in many accounts/Regions at once) and does NOT
    support Just-in-Time auto-registration — unlike DEFAULT mode.
    """
    iot = _iot_client(region)

    response = safe_api_call(
        iot.register_ca_certificate,
        get_message("operations.register_ca_in_sni_only_multi_account_mode"),
        get_message("operation_resources.ca_in_region", region),
        debug=debug,
        caCertificate=_read_pem(ca_certificate),
        certificateMode="SNI_ONLY",
        setAsActive=True,
    )
    if not response:
        print(get_message("errors.register_ca_sni_failed"))
        sys.exit(1)

    ca_certificate_id = response.get("certificateId")
    print(f"\n{get_message('status.ca_registered_header')}")
    print(get_message("status.ca_registered_region", region))
    print(get_message("status.ca_registered_id", ca_certificate_id))
    print(get_message("status.ca_trusted_note"))
    print(get_message("status.ca_sni_validated_note"))
    return ca_certificate_id


def get_endpoint(region, debug=False):
    """Return (and print) the ``iot:Data-ATS`` endpoint for a Region.

    Wraps ``describe-endpoint --endpoint-type iot:Data-ATS``. Each Region (and,
    in production, each account) has its OWN data endpoint — this is the value
    that changes during the move. The device keeps its certificate and simply
    points at this new endpoint.
    """
    iot = _iot_client(region)
    response = safe_api_call(
        iot.describe_endpoint,
        get_message("operations.describe_iot_data_ats_endpoint"),
        region,
        debug=debug,
        endpointType="iot:Data-ATS",
    )
    if not response:
        print(get_message("errors.describe_endpoint_failed"))
        sys.exit(1)
    endpoint = response["endpointAddress"]
    print(get_message("status.endpoint_for_region", region, endpoint))
    return endpoint


# =========================================================================
# Device plane (over the reused DeviceConnection / mqtt5_client_builder)
# =========================================================================


def move(region, cert, key, thing_name, endpoint=None, message_count=5, debug=False):
    """Reconnect the SAME certificate to the destination Region's endpoint.

    This is the "move": the certificate and key do not change — only the
    endpoint the device connects to. It reuses the shared ``DeviceConnection``
    construct (the same AWS IoT Core Learning SDK connection builder used by
    every other section), so the ONLY difference from the lobby connect is the
    ``endpoint`` argument (lobby Region -> destination Region).
    """
    if not endpoint:
        endpoint = get_endpoint(region, debug=debug)

    device = DeviceConnection()
    print(get_message("status.reconnecting_move", thing_name, endpoint))
    device.connect(
        endpoint=endpoint,
        cert_filepath=cert,
        pri_key_filepath=key,
        client_id=thing_name,
        thing_name=thing_name,
        debug=debug,
    )

    for seq in range(message_count):
        device.publish(
            TELEMETRY_TOPIC,
            {"msg": f"hello from {thing_name} (moved)", "seq": seq},
            qos=1,
        )
        print(get_message("status.published_seq", seq, TELEMETRY_TOPIC))
        time.sleep(2)  # nosemgrep: arbitrary-sleep

    device.disconnect()
    print(f"\n{get_message('status.move_complete')}")
    print(get_message("status.move_complete_note"))


def parse_arguments():
    """Parse command-line arguments."""

    # Help text comes from the "cli" category of this script's catalog. It is
    # loaded with peek_language() -- which never prompts -- because the parser is
    # built before the runtime language is chosen, so --help never shows the
    # interactive language menu. The runtime ``messages`` catalog is still
    # loaded in main() exactly as before.
    help_messages = load_messages("manage_multi_account_registration", peek_language())

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

    reg = subparsers.add_parser(
        "register-without-ca",
        help=cli("register_without_ca.help"),
    )
    reg.add_argument("--region", required=True, help=cli("register_without_ca.region"))
    reg.add_argument("--certificate-pem", required=True, help=cli("register_without_ca.certificate_pem"))
    reg.add_argument("--policy-name", default=None, help=cli("register_without_ca.policy_name"))
    reg.add_argument("--policy-document", default=None, help=cli("register_without_ca.policy_document"))
    reg.add_argument("--thing-name", default=None, help=cli("register_without_ca.thing_name"))
    reg.add_argument("--debug", action="store_true", help=cli("register_without_ca.debug"))

    ca = subparsers.add_parser(
        "register-ca-sni",
        help=cli("register_ca_sni.help"),
    )
    ca.add_argument("--region", required=True, help=cli("register_ca_sni.region"))
    ca.add_argument("--ca-certificate", required=True, help=cli("register_ca_sni.ca_certificate"))
    ca.add_argument("--debug", action="store_true", help=cli("register_ca_sni.debug"))

    ep = subparsers.add_parser("endpoint", help=cli("endpoint.help"))
    ep.add_argument("--region", required=True, help=cli("endpoint.region"))
    ep.add_argument("--debug", action="store_true", help=cli("endpoint.debug"))

    mv = subparsers.add_parser("move", help=cli("move.help"))
    mv.add_argument("--region", required=True, help=cli("move.region"))
    mv.add_argument("--thing-name", required=True, help=cli("move.thing_name"))
    mv.add_argument("--cert", required=True, help=cli("move.cert"))
    mv.add_argument("--key", required=True, help=cli("move.key"))
    mv.add_argument("--endpoint", default=None, help=cli("move.endpoint"))
    mv.add_argument("--message-count", type=int, default=5, help=cli("move.message_count"))
    mv.add_argument("--debug", action="store_true", help=cli("move.debug"))

    return parser.parse_args()


def main():
    args = parse_arguments()

    # Load the localized message catalog once, before any user-facing print.
    # (Placed after argument parsing so --help stays free of the language menu.)
    global messages
    language = get_language()
    messages = load_messages("manage_multi_account_registration", language)
    # Apply the same runtime language to the shared helpers' own catalogs.
    set_api_helpers_language(language)
    set_device_simulator_language(language)

    if args.command == "register-without-ca":
        register_without_ca(
            certificate_pem=args.certificate_pem,
            region=args.region,
            policy_name=args.policy_name,
            policy_document=args.policy_document,
            thing_name=args.thing_name,
            debug=args.debug,
        )
    elif args.command == "register-ca-sni":
        register_ca_sni(
            ca_certificate=args.ca_certificate,
            region=args.region,
            debug=args.debug,
        )
    elif args.command == "endpoint":
        get_endpoint(region=args.region, debug=args.debug)
    elif args.command == "move":
        move(
            region=args.region,
            cert=args.cert,
            key=args.key,
            thing_name=args.thing_name,
            endpoint=args.endpoint,
            message_count=args.message_count,
            debug=args.debug,
        )


if __name__ == "__main__":
    main()
