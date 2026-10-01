#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Manage Just-in-Time Provisioning (JITP) and Just-in-Time Registration (JITR).

Control-plane wrapper for Module 2, "Just-in-Time Provisioning: JITP & JITR".
It complements ``register_custom_ca.py`` by covering the two remaining moving
parts the module content shows CLI-first:

- The **JITR variant** (section 2.4.3): a device-registration event on the
  reserved topic ``$aws/events/certificates/registered/+`` is routed by an AWS
  IoT topic rule to the JITR AWS Lambda handler. This script creates that rule
  with ``create-topic-rule`` and (optionally) deploys the handler code over the
  pre-created skeleton with ``aws lambda update-function-code``.
- **Observe** the result of either flow with ``list-certificates-by-ca`` and
  ``describe-thing``.

Every AWS control-plane call goes through the shared ``safe_api_call`` construct
so behavior is consistent with the rest of the sample.

Subcommands
-----------
    register-ca        Register the custom CA with JITP config (delegates to
                       register_custom_ca.py; wraps register-ca-certificate).
    deploy-jitr-rule   Create the topic rule that routes the registration event
                       to the JITR handler (wraps create-topic-rule).
    deploy-jitr-code   Package lambdas/jitr_registration_handler.py and deploy it
                       over the pre-created skeleton (wraps update-function-code).
    observe            List certificates registered under the CA and describe a
                       provisioned thing.

Examples
--------
    python scripts/manage_jit_provisioning.py register-ca \\
        --role-arn arn:aws:iam::<account-id>:role/<stack>-jitp-registration-role

    python scripts/manage_jit_provisioning.py deploy-jitr-rule \\
        --rule-name JITRRegistrationRule \\
        --function-arn arn:aws:lambda:us-east-1:<account-id>:function:<stack>-jitr-registration-handler

    python scripts/manage_jit_provisioning.py observe \\
        --ca-cert-id <caCertificateId> --thing-name Vehicle-VIN-500
"""

import argparse
import io
import json
import os
import shutil
import subprocess  # nosec B404 -- used only for a local, hardcoded pip install call below
import sys
import tempfile
import zipfile

# --- Repository path wiring (import shared constructs) --------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "i18n"))

import boto3  # noqa: E402

from iot_helpers.utils.api_helpers import safe_api_call  # noqa: E402
from iot_helpers.utils.api_helpers import set_language as set_api_helpers_language  # noqa: E402
from language_selector import get_language, peek_language  # noqa: E402
from loader import load_messages  # noqa: E402

# --- i18n message catalog + resolver -------------------------------------
# Populated once at entry (see main()) via load_messages(). The wrapper below
# is the shared nested-capable convention documented in i18n/README.md: dotted
# keys walk the nested catalog, a missing key falls back to the key itself, and
# positional {} placeholders are filled via str.format(*args). It is defined
# per-script on purpose (NOT centralized in loader.py).
messages = {}
# Runtime language resolved once in main(); reused so register-ca never prompts twice.
language = None


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


# The reserved topic AWS IoT Core publishes to when a device whose CA is
# registered connects for the first time. The '+' wildcard matches any CA id.
JITR_EVENT_TOPIC = "$aws/events/certificates/registered/+"

LAMBDA_SOURCE = os.path.join(REPO_ROOT, "lambdas", "jitr_registration_handler.py")


def deploy_jitr_rule(rule_name, function_arn, debug=False):
    """Create the AWS IoT topic rule that routes the registration event to Lambda."""
    iot = boto3.client("iot")

    # SELECT * FROM the reserved registration-event topic; single Lambda action.
    # This is an AWS IoT Rules Engine SQL statement (evaluated by AWS IoT, not a
    # database), and JITR_EVENT_TOPIC is a fixed constant, not external input.
    topic_rule_payload = {
        "sql": f'SELECT * FROM "{JITR_EVENT_TOPIC}"',  # nosec B608
        "description": "Route JITR device-registration events to the JITR handler.",
        "actions": [{"lambda": {"functionArn": function_arn}}],
        "ruleDisabled": False,
    }

    response = safe_api_call(
        iot.create_topic_rule,
        get_message("operations.create_jitr_topic_rule"),
        rule_name,
        debug=debug,
        ruleName=rule_name,
        topicRulePayload=topic_rule_payload,
    )
    if response is None:
        # create_topic_rule returns no body on success; safe_api_call returns the
        # (empty) response dict. None means an error other than "already exists".
        print(get_message("warnings.topic_rule_not_created"))
        return
    print(get_message("status.topic_rule_created", rule_name, JITR_EVENT_TOPIC))


# The base stack's JitrRegistrationHandlerFunction runs python3.12 with no
# Architectures override, which defaults to x86_64 — request that exact wheel
# rather than whatever platform this script happens to run on, the same way
# the module content's own deploy commands and rotation_handler.py's deploy
# docstring do for the identical cryptography dependency.
CRYPTOGRAPHY_PIP_ARGS = [
    "--platform",
    "manylinux2014_x86_64",
    "--implementation",
    "cp",
    "--python-version",
    "3.12",
    "--only-binary=:all:",
    "cryptography",
]


def deploy_jitr_code(function_name, debug=False):
    """Package the JITR handler as index.py, with cryptography bundled, and deploy it.

    jitr_registration_handler.py's ``_parse_subject`` lazily imports
    ``cryptography`` to parse the certificate CN — a compiled dependency the
    base Lambda runtime does not include. Packaging only ``index.py`` (as this
    function used to) leaves that import failing at runtime; the handler's own
    broad ``except Exception`` catches it silently and falls back to naming the
    thing ``jitr-device-<cert-id-prefix>`` instead of its real CN. Install the
    dependency into the same package the source is zipped from, matching the
    module content's own manual deploy commands and rotation_handler.py's
    documented deploy step for the identical dependency.
    """
    if not os.path.exists(LAMBDA_SOURCE):
        print(get_message("errors.handler_source_not_found", LAMBDA_SOURCE))
        sys.exit(1)

    with tempfile.TemporaryDirectory() as build_dir:
        # sys.executable -m pip: fixed executable, list args, no shell (pip ships with Python).
        result = subprocess.run(  # nosec B603 B607 -- list args, no shell, fixed executable
            [sys.executable, "-m", "pip", "install", "--quiet", "--target", build_dir] + CRYPTOGRAPHY_PIP_ARGS,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(get_message("errors.dependency_install_failed", result.stderr.strip()))
            sys.exit(1)

        # The base stack created the function with handler 'index.handler', so
        # the source must be packaged as index.py inside the zip, alongside
        # the cryptography wheel just installed into the same directory.
        shutil.copyfile(LAMBDA_SOURCE, os.path.join(build_dir, "index.py"))

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for root, _dirs, files in os.walk(build_dir):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    archive.write(file_path, os.path.relpath(file_path, build_dir))
        zip_bytes = buffer.getvalue()

    lambda_client = boto3.client("lambda")
    response = safe_api_call(
        lambda_client.update_function_code,
        get_message("operations.deploy_jitr_handler_code"),
        function_name,
        debug=debug,
        FunctionName=function_name,
        ZipFile=zip_bytes,
    )
    if response:
        print(get_message("status.handler_code_deployed", function_name))


def observe(ca_cert_id, thing_name=None, debug=False):
    """Observe registration results via list-certificates-by-ca / describe-thing."""
    iot = boto3.client("iot")

    certs = safe_api_call(
        iot.list_certificates_by_ca,
        get_message("operations.list_certificates_by_ca"),
        ca_cert_id,
        debug=debug,
        caCertificateId=ca_cert_id,
    )
    if certs:
        certificates = certs.get("certificates", [])
        print(get_message("status.certs_registered_header", len(certificates), ca_cert_id))
        for cert in certificates:
            print(get_message("status.cert_line", cert.get("certificateId"), cert.get("status")))

    if thing_name:
        thing = safe_api_call(
            iot.describe_thing,
            get_message("operations.describe_thing"),
            thing_name,
            debug=debug,
            thingName=thing_name,
        )
        if thing:
            print(get_message("status.thing_attributes", thing_name, json.dumps(thing.get("attributes", {}))))


def register_ca(args):
    """Delegate CA registration to the dedicated register_custom_ca module.

    register_custom_ca.py keeps its own module-level ``messages`` catalog,
    separate from this script's — calling register_custom_ca() directly (as
    opposed to going through that module's own main()) never populates it,
    so every get_message() call inside register_custom_ca() would otherwise
    resolve to the raw dotted key instead of localized text. Load it here,
    into that module's own global, before delegating.
    """
    import register_custom_ca as register_custom_ca_module

    register_custom_ca_module.messages = load_messages("register_custom_ca", language)
    register_custom_ca_module.register_custom_ca(
        role_arn=args.role_arn,
        template_file=args.template_file or register_custom_ca_module.DEFAULT_TEMPLATE_FILE,
        ca_common_name=args.ca_common_name,
        debug=args.debug,
        language=language,
    )


def parse_arguments():
    """Parse command-line arguments."""

    # Help text comes from the "cli" category of this script's catalog. It is
    # loaded with peek_language() -- which never prompts -- because the parser is
    # built before the runtime language is chosen, so --help never shows the
    # interactive language menu. The runtime ``messages`` catalog is still
    # loaded in main() exactly as before.
    help_messages = load_messages("manage_jit_provisioning", peek_language())

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

    ca_parser = subparsers.add_parser("register-ca", help=cli("register_ca.help"))
    ca_parser.add_argument("--role-arn", required=True, help=cli("register_ca.role_arn"))
    ca_parser.add_argument("--template-file", default=None, help=cli("register_ca.template_file"))
    ca_parser.add_argument("--ca-common-name", default="AnyCompany Device Root CA", help=cli("register_ca.ca_common_name"))
    ca_parser.add_argument("--debug", action="store_true", help=cli("register_ca.debug"))

    rule_parser = subparsers.add_parser("deploy-jitr-rule", help=cli("deploy_jitr_rule.help"))
    rule_parser.add_argument("--rule-name", default="JITRRegistrationRule", help=cli("deploy_jitr_rule.rule_name"))
    rule_parser.add_argument("--function-arn", required=True, help=cli("deploy_jitr_rule.function_arn"))
    rule_parser.add_argument("--debug", action="store_true", help=cli("deploy_jitr_rule.debug"))

    code_parser = subparsers.add_parser("deploy-jitr-code", help=cli("deploy_jitr_code.help"))
    code_parser.add_argument("--function-name", required=True, help=cli("deploy_jitr_code.function_name"))
    code_parser.add_argument("--debug", action="store_true", help=cli("deploy_jitr_code.debug"))

    observe_parser = subparsers.add_parser("observe", help=cli("observe.help"))
    observe_parser.add_argument("--ca-cert-id", required=True, help=cli("observe.ca_cert_id"))
    observe_parser.add_argument("--thing-name", default=None, help=cli("observe.thing_name"))
    observe_parser.add_argument("--debug", action="store_true", help=cli("observe.debug"))

    return parser.parse_args()


def main():
    args = parse_arguments()

    # Load the localized message catalog once, before any user-facing print.
    # (Placed after argument parsing so --help stays free of the language menu.)
    global messages, language
    language = get_language()
    messages = load_messages("manage_jit_provisioning", language)
    # Apply the same runtime language to the shared helpers' own catalogs.
    set_api_helpers_language(language)

    if args.command == "register-ca":
        register_ca(args)
    elif args.command == "deploy-jitr-rule":
        deploy_jitr_rule(args.rule_name, args.function_arn, debug=args.debug)
    elif args.command == "deploy-jitr-code":
        deploy_jitr_code(args.function_name, debug=args.debug)
    elif args.command == "observe":
        observe(args.ca_cert_id, thing_name=args.thing_name, debug=args.debug)


if __name__ == "__main__":
    main()
