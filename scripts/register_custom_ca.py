#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Register a custom Certificate Authority (CA) with AWS IoT Core (JITP config).

This is the control-plane wrapper for Module 2, "Just-in-Time Provisioning:
JITP & JITR" — section 2.4.1. It automates the exact ``aws iot`` flow the
workshop content shows CLI-first:

    aws iot get-registration-code
    aws iot register-ca-certificate \\
      --ca-certificate file://rootCA.pem \\
      --verification-certificate file://verification.pem \\
      --set-as-active --allow-auto-registration \\
      --registration-config file://jitp-registration-config.json

Every AWS control-plane call goes through the shared ``safe_api_call`` construct
(``iot_helpers/utils/api_helpers.py``) so error handling, "already exists"
tolerance, and gentle rate limiting are consistent with the rest of the sample.

What the script does:

1. Confirms OpenSSL is available (shared environment tool from Setup).
2. Creates a self-signed root CA with OpenSSL if one is not already present
   (WORKSHOP ONLY — never use a self-signed CA in production; see the anti-pattern
   callout in the module content).
3. Calls ``get-registration-code`` to obtain the code that proves you control
   the CA private key.
4. Creates a verification certificate whose common name (CN) equals that
   registration code.
5. Registers the CA with ``register-ca-certificate``, attaching a JITP
   ``registrationConfig`` (the provisioning template body + the registration
   role ARN) and enabling auto-registration.

The JITP provisioning template body is read from
``iot_helpers/utils/fleet_provisioning_templates/jitp-template.json`` and passed
as the ``templateBody`` string, matching what the content shows.
"""

import argparse
import json
import os
import re
import subprocess  # nosec B404 -- used only for local, hardcoded openssl calls below
import sys

# --- Repository path wiring (import shared constructs) --------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "i18n"))

import boto3  # noqa: E402

from iot_helpers.utils.api_helpers import safe_api_call  # noqa: E402
from iot_helpers.utils.dependency_handler import check_openssl_available  # noqa: E402
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


TEMPLATE_DIR = os.path.join(REPO_ROOT, "iot_helpers", "utils", "fleet_provisioning_templates")
DEFAULT_TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, "jitp-template.json")

# File names kept identical to the CLI-first commands in the module content.
ROOT_CA_KEY = "rootCA.key"
ROOT_CA_PEM = "rootCA.pem"
VERIFICATION_KEY = "verification.key"
VERIFICATION_CSR = "verification.csr"
VERIFICATION_PEM = "verification.pem"


def run_openssl(args, debug=False):
    """Run an ``openssl`` command with list args (no shell) and surface errors."""
    cmd = ["openssl"] + args
    if debug:
        print(get_message("debug.openssl_cmd", " ".join(cmd)))
    # nosemgrep: dangerous-subprocess-use-audit -- list args, shell=False; --ca-common-name pre-validated against ^[a-zA-Z0-9 _.-]+$ in create_root_ca above
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=False
    )  # nosec B603 -- list args, no shell, fixed "openssl" executable
    if result.returncode != 0:
        print(get_message("errors.openssl_failed", " ".join(cmd)))
        print(result.stderr.strip())
        raise RuntimeError("OpenSSL command failed")
    return result


def create_root_ca(common_name, debug=False):
    """Create a self-signed root CA (workshop only) if it is not already present."""
    if os.path.exists(ROOT_CA_KEY) and os.path.exists(ROOT_CA_PEM):
        print(get_message("status.reusing_root_ca", ROOT_CA_PEM))
        return

    # Validate the CA common name before it is interpolated into a -subj value.
    # No shell is involved (list args, shell=False in run_openssl), so this is
    # not a command-injection guard — it stops an operator-supplied name with a
    # stray "/" (the openssl distinguished-name field separator) from silently
    # producing a self-signed cert with an unexpected subject.
    if not re.match(r"^[a-zA-Z0-9 _.-]+$", common_name):
        print(get_message("errors.ca_common_name_invalid_chars"))
        sys.exit(1)

    print(get_message("status.creating_root_ca"))
    run_openssl(["genrsa", "-out", ROOT_CA_KEY, "2048"], debug=debug)
    run_openssl(
        [
            "req",
            "-x509",
            "-new",
            "-nodes",
            "-key",
            ROOT_CA_KEY,
            "-sha256",
            "-days",
            "365",
            "-out",
            ROOT_CA_PEM,
            "-subj",
            f"/CN={common_name}",
        ],
        debug=debug,
    )
    print(get_message("status.root_ca_created", ROOT_CA_PEM))


def create_verification_certificate(registration_code, debug=False):
    """Create a verification certificate whose CN is the registration code."""
    print(get_message("status.creating_verification"))
    run_openssl(["genrsa", "-out", VERIFICATION_KEY, "2048"], debug=debug)
    run_openssl(
        [
            "req",
            "-new",
            "-key",
            VERIFICATION_KEY,
            "-out",
            VERIFICATION_CSR,
            "-subj",
            f"/CN={registration_code}",
        ],
        debug=debug,
    )
    run_openssl(
        [
            "x509",
            "-req",
            "-in",
            VERIFICATION_CSR,
            "-CA",
            ROOT_CA_PEM,
            "-CAkey",
            ROOT_CA_KEY,
            "-CAcreateserial",
            "-out",
            VERIFICATION_PEM,
            "-days",
            "365",
            "-sha256",
        ],
        debug=debug,
    )
    print(get_message("status.verification_created", VERIFICATION_PEM))


def load_template_body(template_file):
    """Load the JITP provisioning template JSON and return it as a compact string."""
    with open(template_file, "r", encoding="utf-8") as handle:
        template = json.load(handle)
    # register-ca-certificate expects templateBody as a JSON *string*.
    return json.dumps(template, separators=(",", ":"))


def register_custom_ca(role_arn, template_file, ca_common_name, debug=False):
    """Drive the full get-registration-code -> register-ca-certificate flow."""
    iot = boto3.client("iot")

    # Step 1 — confirm OpenSSL is available.
    available, detail = check_openssl_available()
    if not available:
        print(detail)
        sys.exit(1)
    print(get_message("status.openssl_available", detail))

    # Step 2 — create the root CA (workshop only) if needed.
    create_root_ca(ca_common_name, debug=debug)

    # Step 3 — get the registration code.
    reg = safe_api_call(
        iot.get_registration_code,
        "Get CA registration code",
        "registration-code",
        debug=debug,
    )
    if not reg:
        print(get_message("errors.no_registration_code"))
        sys.exit(1)
    registration_code = reg["registrationCode"]
    print(get_message("status.registration_code", registration_code))

    # Step 4 — create the verification certificate.
    create_verification_certificate(registration_code, debug=debug)

    # Step 5 — register the CA with the JITP registration config.
    with open(ROOT_CA_PEM, "r", encoding="utf-8") as handle:
        ca_certificate = handle.read()
    with open(VERIFICATION_PEM, "r", encoding="utf-8") as handle:
        verification_certificate = handle.read()

    template_body = load_template_body(template_file)

    response = safe_api_call(
        iot.register_ca_certificate,
        "Register custom CA (JITP)",
        "custom-ca",
        debug=debug,
        caCertificate=ca_certificate,
        verificationCertificate=verification_certificate,
        setAsActive=True,
        allowAutoRegistration=True,
        registrationConfig={
            "templateBody": template_body,
            "roleArn": role_arn,
        },
    )
    if not response:
        print(get_message("errors.registration_failed"))
        sys.exit(1)

    ca_certificate_id = response.get("certificateId")
    print(f"\n{get_message('status.registered_title')}")
    print(get_message("status.ca_certificate_id", ca_certificate_id))
    print(get_message("status.verify_hint", ca_certificate_id))
    return ca_certificate_id


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Register a custom Certificate Authority with AWS IoT Core and enable " "Just-in-Time Provisioning (JITP)."
        )
    )
    parser.add_argument(
        "--role-arn",
        required=True,
        help=("ARN of the JITP registration role (the base stack output " "'JitpRegistrationRoleArn')."),
    )
    parser.add_argument(
        "--template-file",
        default=DEFAULT_TEMPLATE_FILE,
        help="Path to the JITP provisioning template JSON (default: bundled jitp-template.json).",
    )
    parser.add_argument(
        "--ca-common-name",
        default="AnyCompany Device Root CA",
        help="Common name for the self-signed root CA (workshop only).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print API request/response detail and OpenSSL commands.",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()

    # Load the localized message catalog once, before any user-facing print.
    # (Placed after argument parsing so --help stays free of the language menu.)
    global messages
    messages = load_messages("register_custom_ca", get_language())

    register_custom_ca(
        role_arn=args.role_arn,
        template_file=args.template_file,
        ca_common_name=args.ca_common_name,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
