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
from iot_helpers.utils.device_simulator import DeviceConnection  # noqa: E402

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


def register_without_ca(certificate_pem, region, policy_name=None,
                        policy_document=None, thing_name=None, debug=False):
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
        "Register certificate without CA (MAR)",
        f"certificate in {region}",
        debug=debug,
        certificatePem=_read_pem(certificate_pem),
        status="ACTIVE",
    )
    if not response:
        print("❌ register-certificate-without-ca failed — is the certificate PEM valid?")
        sys.exit(1)

    # Capture the id straight from the registering call (not a broad list-certificates):
    # earlier sections leave certs ACTIVE and list order is not guaranteed.
    certificate_id = response.get("certificateId")
    certificate_arn = response.get("certificateArn")
    print("\n🪪 Certificate registered in the destination Region (no new cert minted)")
    print(f"   Region:         {region}")
    print(f"   certificateId:  {certificate_id}")
    print("   (This id is derived from the certificate — it matches the lobby id.)")

    # Rebuild the ARN if the API did not return it (older API shapes).
    if not certificate_arn and certificate_id:
        certificate_arn = f"arn:aws:iot:{region}:{_account_id()}:cert/{certificate_id}"

    if policy_name:
        if policy_document:
            safe_api_call(
                iot.create_policy,
                "Create destination device policy",
                policy_name,
                debug=debug,
                policyName=policy_name,
                policyDocument=_read_pem(policy_document),
            )
        safe_api_call(
            iot.attach_policy,
            "Attach device policy to moved certificate",
            policy_name,
            debug=debug,
            policyName=policy_name,
            target=certificate_arn,
        )

    if thing_name:
        safe_api_call(
            iot.create_thing,
            "Create thing in destination Region",
            thing_name,
            debug=debug,
            thingName=thing_name,
        )
        safe_api_call(
            iot.attach_thing_principal,
            "Attach moved certificate to thing",
            thing_name,
            debug=debug,
            thingName=thing_name,
            principal=certificate_arn,
        )

    print("\n✅ The same certificate is now recognized in the destination Region.")
    print("   Next: get that Region's iot:Data-ATS endpoint and reconnect the SAME "
          "certificate to it (the 'move' subcommand).")
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
        "Register CA in SNI_ONLY (multi-account) mode",
        f"CA in {region}",
        debug=debug,
        caCertificate=_read_pem(ca_certificate),
        certificateMode="SNI_ONLY",
        setAsActive=True,
    )
    if not response:
        print("❌ register-ca-certificate (SNI_ONLY) failed — is the CA PEM valid?")
        sys.exit(1)

    ca_certificate_id = response.get("certificateId")
    print("\n🏛️  CA registered in SNI_ONLY (multi-account) mode")
    print(f"   Region:            {region}")
    print(f"   CA certificate id: {ca_certificate_id}")
    print("   Every device certificate this CA signed is now trusted in this Region,")
    print("   validated by the SNI hostname the device presents. No per-cert "
          "registration needed.")
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
        "Describe iot:Data-ATS endpoint",
        region,
        debug=debug,
        endpointType="iot:Data-ATS",
    )
    if not response:
        print("❌ describe-endpoint failed")
        sys.exit(1)
    endpoint = response["endpointAddress"]
    print(f"🌐 iot:Data-ATS endpoint for {region}: {endpoint}")
    return endpoint


# =========================================================================
# Device plane (over the reused DeviceConnection / mqtt_connection_builder)
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
    print(f"🔌 Reconnecting '{thing_name}' with the SAME certificate to the "
          f"destination endpoint {endpoint} ...")
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
        print(f"   published seq={seq} to {TELEMETRY_TOPIC}")
        time.sleep(2)  # nosemgrep: arbitrary-sleep

    device.disconnect()
    print("\n🎉 Move complete — the same certificate is now connected to the "
          "destination Region.")
    print("   No new certificate was minted; only the endpoint changed.")


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Multi-Account Registration (MAR): register an existing certificate in a "
            "destination Region and reconnect the same certificate to that Region's endpoint."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    reg = subparsers.add_parser(
        "register-without-ca",
        help="Register an existing device certificate in the destination Region (no CA).",
    )
    reg.add_argument("--region", required=True, help="Destination (production stand-in) Region.")
    reg.add_argument("--certificate-pem", required=True, help="Path to the device certificate PEM.")
    reg.add_argument("--policy-name", default=None, help="Device policy to create/attach in the destination.")
    reg.add_argument("--policy-document", default=None, help="Policy JSON to create (if --policy-name is new).")
    reg.add_argument("--thing-name", default=None, help="Optional thing to create + attach in the destination.")
    reg.add_argument("--debug", action="store_true", help="Verbose output.")

    ca = subparsers.add_parser(
        "register-ca-sni",
        help="Register a CA in SNI_ONLY (multi-account) mode in the destination Region.",
    )
    ca.add_argument("--region", required=True, help="Destination (production stand-in) Region.")
    ca.add_argument("--ca-certificate", required=True, help="Path to the CA certificate PEM.")
    ca.add_argument("--debug", action="store_true", help="Verbose output.")

    ep = subparsers.add_parser("endpoint", help="describe-endpoint --endpoint-type iot:Data-ATS for a Region.")
    ep.add_argument("--region", required=True, help="Region to describe the data endpoint for.")
    ep.add_argument("--debug", action="store_true", help="Verbose output.")

    mv = subparsers.add_parser("move", help="Reconnect the same certificate to the destination endpoint.")
    mv.add_argument("--region", required=True, help="Destination (production stand-in) Region.")
    mv.add_argument("--thing-name", required=True, help="Device/thing name (used as the MQTT client id).")
    mv.add_argument("--cert", required=True, help="Path to the SAME device certificate PEM.")
    mv.add_argument("--key", required=True, help="Path to the SAME device private key.")
    mv.add_argument("--endpoint", default=None, help="Destination endpoint (auto-discovered if omitted).")
    mv.add_argument("--message-count", type=int, default=5, help="Telemetry messages to publish.")
    mv.add_argument("--debug", action="store_true", help="Verbose output.")

    return parser.parse_args()


def main():
    args = parse_arguments()

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
