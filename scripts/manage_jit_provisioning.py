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
import sys
import zipfile

# --- Repository path wiring (import shared constructs) --------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "i18n"))

import boto3  # noqa: E402

from iot_helpers.utils.api_helpers import safe_api_call  # noqa: E402
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
        "Create JITR topic rule",
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


def deploy_jitr_code(function_name, debug=False):
    """Package the JITR handler as index.py and deploy it over the skeleton."""
    if not os.path.exists(LAMBDA_SOURCE):
        print(get_message("errors.handler_source_not_found", LAMBDA_SOURCE))
        sys.exit(1)

    # The base stack created the function with handler 'index.handler', so the
    # source must be packaged as index.py inside the zip.
    with open(LAMBDA_SOURCE, "r", encoding="utf-8") as handle:
        source = handle.read()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.py", source)
    zip_bytes = buffer.getvalue()

    lambda_client = boto3.client("lambda")
    response = safe_api_call(
        lambda_client.update_function_code,
        "Deploy JITR handler code",
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
        "List certificates by CA",
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
            "Describe thing",
            thing_name,
            debug=debug,
            thingName=thing_name,
        )
        if thing:
            print(get_message("status.thing_attributes", thing_name, json.dumps(thing.get("attributes", {}))))


def register_ca(args):
    """Delegate CA registration to the dedicated register_custom_ca module."""
    from register_custom_ca import register_custom_ca, DEFAULT_TEMPLATE_FILE

    register_custom_ca(
        role_arn=args.role_arn,
        template_file=args.template_file or DEFAULT_TEMPLATE_FILE,
        ca_common_name=args.ca_common_name,
        debug=args.debug,
    )


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Manage Just-in-Time Provisioning (JITP) and JITR resources.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ca_parser = subparsers.add_parser("register-ca", help="Register the custom CA with JITP config.")
    ca_parser.add_argument("--role-arn", required=True, help="JITP registration role ARN.")
    ca_parser.add_argument("--template-file", default=None, help="JITP template JSON path.")
    ca_parser.add_argument("--ca-common-name", default="AnyCompany Device Root CA", help="Root CA common name.")
    ca_parser.add_argument("--debug", action="store_true", help="Verbose output.")

    rule_parser = subparsers.add_parser("deploy-jitr-rule", help="Create the JITR topic rule (create-topic-rule).")
    rule_parser.add_argument("--rule-name", default="JITRRegistrationRule", help="Topic rule name.")
    rule_parser.add_argument("--function-arn", required=True, help="JITR handler Lambda ARN.")
    rule_parser.add_argument("--debug", action="store_true", help="Verbose output.")

    code_parser = subparsers.add_parser("deploy-jitr-code", help="Deploy the JITR handler code (update-function-code).")
    code_parser.add_argument("--function-name", required=True, help="JITR handler function name.")
    code_parser.add_argument("--debug", action="store_true", help="Verbose output.")

    observe_parser = subparsers.add_parser(
        "observe", help="Observe registration results (list-certificates-by-ca / describe-thing)."
    )
    observe_parser.add_argument("--ca-cert-id", required=True, help="CA certificate id.")
    observe_parser.add_argument("--thing-name", default=None, help="Thing to describe.")
    observe_parser.add_argument("--debug", action="store_true", help="Verbose output.")

    return parser.parse_args()


def main():
    args = parse_arguments()

    # Load the localized message catalog once, before any user-facing print.
    # (Placed after argument parsing so --help stays free of the language menu.)
    global messages
    messages = load_messages("manage_jit_provisioning", get_language())

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
