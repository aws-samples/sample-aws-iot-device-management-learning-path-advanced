#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Per-topic cleanup for the Advanced Device Provisioning End-to-End topic.

This is the control-plane cleanup for the topic's closing section (Section 6).
It removes ONLY the AWS resources this provisioning topic created, matched by
their workshop naming pattern, and it leaves the shared setup environment fully
intact — the cloned sample repository, the installed Python dependencies
(``boto3`` and ``aws-iot-device-sdk-python-v2``), the selected language, and the
confirmed OpenSSL availability are never touched by this script (it only calls
``aws iot`` control-plane APIs). Future topics reuse that same environment, so
tearing it down here would break them.

Design (mirrors the Device Management basics ``cleanup_script.py`` pattern, but
scoped to this topic):

- **Pattern-scoped.** Every candidate is filtered with
  ``matches_workshop_pattern`` (``iot_helpers/utils/naming_conventions.py``) or an
  explicit, known workshop resource name. A resource that does not match the
  topic's pattern is never selected, so the shared environment and unrelated
  account resources stay safe.
- **Non-destructive by default.** With no flags the script performs a DRY RUN:
  it lists what it *would* remove and deletes nothing. Pass ``--execute`` to
  actually delete.
- **Explicit confirmation before destructive deletes.** Before deleting any
  Certificate Authority (CA), provisioning template, or certificate, the script
  asks the learner to confirm. If the learner declines, the affected resource is
  RETAINED and the script moves on.
- **Two Regions.** The main flow runs in the Region where the workshop runs
  (the AWS CLI default Region). Section 5 (Multi-Account Registration) also
  registered the same certificate in a second Region; pass ``--mar-region`` to
  clean that Region's moved certificate and thing without touching anything in
  the main Region.

The pre-provisioning hook and Just-in-Time Registration handler AWS Lambda
functions are created by the base AWS CloudFormation stack (learners only update
their code), so they are NOT deleted here — the script prints the base stack
name so it can be deleted deliberately (own-account) or torn down automatically
(AWS-led event).

Every control-plane call goes through the shared ``safe_api_call`` construct
(``iot_helpers/utils/api_helpers.py``) for consistent error handling and gentle
rate limiting.

Usage
-----
    python3 scripts/cleanup_script.py                          # dry run (default)
    python3 scripts/cleanup_script.py --execute                # delete (with confirmations)
    python3 scripts/cleanup_script.py --execute --mar-region us-west-2
    python3 scripts/cleanup_script.py --execute --debug
"""

import argparse
import os
import sys

# --- Repository path wiring (import shared constructs) --------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.path.append(os.path.join(REPO_ROOT, "i18n"))

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from colorama import Fore, Style, init  # noqa: E402

from iot_helpers.utils.api_helpers import safe_api_call  # noqa: E402
from iot_helpers.utils.naming_conventions import matches_workshop_pattern  # noqa: E402

# i18n: reuse the shared language selector + localized yes/no confirmation so a
# German 'j' or French 'o' works like the rest of the sample scripts.
from language_selector import get_language  # noqa: E402
from confirmation import is_affirmative  # noqa: E402

init()

# ---------------------------------------------------------------------------
# Known workshop resource names created by THIS topic (used alongside
# matches_workshop_pattern for scoping). Keeping these explicit means the
# cleanup can only ever select resources the sections above actually created.
# ---------------------------------------------------------------------------

# Provisioning templates created via create-provisioning-template (Sections 3, 4).
WORKSHOP_PROVISIONING_TEMPLATES = ["FleetClaimTemplate", "TrustedUserTemplate"]

# Device / claim policies created by the scripts and provisioning templates.
WORKSHOP_POLICY_NAMES = [
    "FleetClaimPolicy",             # Section 3 — scoped claim (bootstrap) policy
    "FleetProvisionedDevicePolicy",  # Section 3 — template-created device policy
    "SmartHomeDevicePolicy",         # Section 4 — trusted-user device policy
    "JITPDevicePolicy",              # Section 2 — JITP device policy
    "JITRDevicePolicy",              # Section 2 — JITR device policy
]

# Device policy created in the SECOND Region for the MAR move (Section 5).
WORKSHOP_MAR_POLICY_NAMES = ["MARProductionDevicePolicy"]

# Just-in-Time Registration topic rule (Section 2).
WORKSHOP_TOPIC_RULES = ["JITRRegistrationRule"]

# Static thing groups the provisioning templates reference (Section 3 v2 template).
WORKSHOP_THING_GROUPS = ["fleet-connected-vehicles"]

# Thing-name prefixes this topic uses. Vehicle-VIN-### matches the built-in
# "thing" pattern; the others are passed as custom prefixes.
WORKSHOP_THING_PREFIXES = ["Vehicle-VIN-", "SmartHome-Sensor-", "Vehicle-VIN-MAR-"]

# Thing prefix used specifically for the moved device in the MAR (second) Region.
WORKSHOP_MAR_THING_PREFIXES = ["Vehicle-VIN-MAR-"]

# Substring markers identifying the self-signed workshop root CAs by subject
# common name (for example "AnyCompany JITP Root CA", "AnyCompany JITR Root CA").
# A CA whose subject does not contain BOTH markers is never selected.
WORKSHOP_CA_CN_MARKERS = ("AnyCompany", "Root CA")


class AdvancedProvisioningCleanup:
    """Pattern-scoped, confirmation-gated cleanup for the provisioning topic."""

    def __init__(self, execute=False, mar_region=None, language="en", debug=False):
        # Non-destructive by default: dry_run is the inverse of --execute.
        self.dry_run = not execute
        self.mar_region = mar_region
        self.language = language
        self.debug = debug

        self.region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        self.iot = boto3.client("iot", region_name=self.region)
        self.iot_mar = (
            boto3.client("iot", region_name=mar_region) if mar_region else None
        )

        # Populated during CA discovery; reused for certificate discovery.
        self.workshop_ca_ids = []

    # -- helpers -----------------------------------------------------------

    def _info(self, text):
        print(f"{Fore.CYAN}{text}{Style.RESET_ALL}")

    def _plan(self, text):
        # A resource the cleanup would act on (shown in both dry-run and execute).
        prefix = "DRY RUN — would remove" if self.dry_run else "Removing"
        print(f"{Fore.YELLOW}  • {prefix}: {text}{Style.RESET_ALL}")

    def _confirm_destructive(self, category, count):
        """Ask for explicit confirmation before a destructive category.

        Returns True to proceed, False to RETAIN (skip) the category. In dry-run
        mode nothing is deleted, so no confirmation is needed.
        """
        if self.dry_run or count == 0:
            return not self.dry_run and count > 0
        print(
            f"\n{Fore.RED}⚠️  About to delete {count} {category}. "
            f"This is destructive and not reversible.{Style.RESET_ALL}"
        )
        answer = input(
            f"{Fore.YELLOW}Delete these {category}? [y/N]: {Style.RESET_ALL}"
        )
        if is_affirmative(answer, self.language):
            return True
        print(f"{Fore.GREEN}Keeping {category} — retained at your request.{Style.RESET_ALL}")
        return False

    def _is_workshop_thing(self, thing_name):
        """True if the thing name matches any workshop prefix/pattern."""
        if matches_workshop_pattern(thing_name, "thing"):
            return True
        return any(
            matches_workshop_pattern(thing_name, "thing", prefix=prefix)
            for prefix in WORKSHOP_THING_PREFIXES
        )

    def _list_things(self, iot_client, prefixes):
        """Return workshop thing names in an account/Region for the given prefixes."""
        names = []
        paginator = iot_client.get_paginator("list_things")
        for page in paginator.paginate():
            for thing in page.get("things", []):
                name = thing.get("thingName", "")
                if any(name.startswith(prefix) for prefix in prefixes):
                    names.append(name)
        return names

    # -- certificate + thing teardown -------------------------------------

    def _delete_certificate(self, iot_client, certificate_id):
        """Detach policies + thing principals, deactivate, then force-delete a cert."""
        cert_arn = None
        described = safe_api_call(
            iot_client.describe_certificate,
            "Describe certificate",
            certificate_id,
            debug=self.debug,
            certificateId=certificate_id,
        )
        if described:
            cert_arn = described["certificateDescription"]["certificateArn"]

        if cert_arn:
            attached = safe_api_call(
                iot_client.list_attached_policies,
                "List attached policies",
                certificate_id,
                debug=self.debug,
                target=cert_arn,
            )
            for policy in (attached or {}).get("policies", []):
                safe_api_call(
                    iot_client.detach_policy,
                    "Detach policy",
                    policy["policyName"],
                    debug=self.debug,
                    policyName=policy["policyName"],
                    target=cert_arn,
                )
            principal_things = safe_api_call(
                iot_client.list_principal_things,
                "List principal things",
                certificate_id,
                debug=self.debug,
                principal=cert_arn,
            )
            for thing_name in (principal_things or {}).get("things", []):
                safe_api_call(
                    iot_client.detach_thing_principal,
                    "Detach thing principal",
                    thing_name,
                    debug=self.debug,
                    thingName=thing_name,
                    principal=cert_arn,
                )

        safe_api_call(
            iot_client.update_certificate,
            "Deactivate certificate",
            certificate_id,
            debug=self.debug,
            certificateId=certificate_id,
            newStatus="INACTIVE",
        )
        safe_api_call(
            iot_client.delete_certificate,
            "Delete certificate",
            certificate_id,
            debug=self.debug,
            certificateId=certificate_id,
            forceDelete=True,
        )

    def _discover_certificate_ids(self, iot_client, thing_names, policy_names):
        """Collect workshop certificate ids from scoped lookups (never a broad list).

        Sources, all scoped so they cannot return an unrelated certificate:
        - certificates signed by each workshop CA (list-certificates-by-ca);
        - certificates attached to each workshop thing (list-thing-principals);
        - certificates carrying a workshop policy (list-targets-for-policy).
        """
        cert_ids = set()

        for ca_id in self.workshop_ca_ids:
            signed = safe_api_call(
                iot_client.list_certificates_by_ca,
                "List certificates by CA",
                ca_id,
                debug=self.debug,
                caCertificateId=ca_id,
            )
            for cert in (signed or {}).get("certificates", []):
                cert_ids.add(cert["certificateId"])

        for thing_name in thing_names:
            principals = safe_api_call(
                iot_client.list_thing_principals,
                "List thing principals",
                thing_name,
                debug=self.debug,
                thingName=thing_name,
            )
            for arn in (principals or {}).get("principals", []):
                if ":cert/" in arn:
                    cert_ids.add(arn.split("/")[-1])

        for policy_name in policy_names:
            targets = safe_api_call(
                iot_client.list_targets_for_policy,
                "List targets for policy",
                policy_name,
                debug=self.debug,
                policyName=policy_name,
            )
            for arn in (targets or {}).get("targets", []):
                if ":cert/" in arn:
                    cert_ids.add(arn.split("/")[-1])

        return sorted(cert_ids)

    # -- CA discovery ------------------------------------------------------

    def _ca_common_name(self, certificate_pem):
        """Return the CA certificate's subject common name, or '' if unreadable.

        Uses ``cryptography`` (a declared dependency) lazily so importing this
        module never hard-requires it. On any parse error we return '' so an
        unrecognized CA is simply skipped, never deleted.
        """
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID

            cert = x509.load_pem_x509_certificate(certificate_pem.encode("utf-8"))
            attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            return attrs[0].value if attrs else ""
        except Exception:  # noqa: BLE001 - unreadable/unknown CA is skipped
            return ""

    def discover_workshop_cas(self):
        """Find workshop custom CAs by subject common-name markers (scoped)."""
        self._info("\n🔎 Discovering custom Certificate Authorities created by this topic...")
        found = []
        listed = safe_api_call(
            self.iot.list_ca_certificates,
            "List CA certificates",
            "ca-certificates",
            debug=self.debug,
        )
        for ca in (listed or {}).get("certificates", []):
            ca_id = ca.get("certificateId")
            described = safe_api_call(
                self.iot.describe_ca_certificate,
                "Describe CA certificate",
                ca_id,
                debug=self.debug,
                certificateId=ca_id,
            )
            if not described:
                continue
            pem = described["certificateDescription"].get("certificatePem", "")
            common_name = self._ca_common_name(pem)
            if common_name and all(marker in common_name for marker in WORKSHOP_CA_CN_MARKERS):
                found.append((ca_id, common_name))
        self.workshop_ca_ids = [ca_id for ca_id, _ in found]
        if found:
            for ca_id, common_name in found:
                self._plan(f"Certificate Authority '{common_name}' ({ca_id})")
        else:
            self._info("  (none found)")
        return found

    def delete_workshop_cas(self, cas):
        """Deregister (INACTIVE) then delete workshop CAs, with confirmation."""
        if not self._confirm_destructive("Certificate Authorities", len(cas)):
            return
        for ca_id, common_name in cas:
            safe_api_call(
                self.iot.update_ca_certificate,
                "Deactivate CA certificate",
                common_name,
                debug=self.debug,
                certificateId=ca_id,
                newStatus="INACTIVE",
            )
            safe_api_call(
                self.iot.delete_ca_certificate,
                "Delete CA certificate",
                common_name,
                debug=self.debug,
                certificateId=ca_id,
            )

    # -- top-level orchestration ------------------------------------------

    def _cleanup_certificates(self, iot_client, thing_names, policy_names, region_label):
        """Discover + delete workshop certificates in a Region, with confirmation."""
        self._info(f"\n🔎 Discovering certificates created by this topic ({region_label})...")
        cert_ids = self._discover_certificate_ids(iot_client, thing_names, policy_names)
        for cert_id in cert_ids:
            self._plan(f"certificate {cert_id}")
        if self._confirm_destructive(f"certificates ({region_label})", len(cert_ids)):
            for cert_id in cert_ids:
                self._delete_certificate(iot_client, cert_id)
        return cert_ids

    def _cleanup_things(self, iot_client, thing_names, region_label):
        """Delete workshop things (their certificates are already detached)."""
        self._info(f"\n🔎 Discovering things created by this topic ({region_label})...")
        for thing_name in thing_names:
            self._plan(f"thing {thing_name}")
            if not self.dry_run:
                safe_api_call(
                    iot_client.delete_thing,
                    "Delete thing",
                    thing_name,
                    debug=self.debug,
                    thingName=thing_name,
                )

    def _cleanup_templates(self):
        """Delete the topic's provisioning templates, with confirmation."""
        self._info("\n🔎 Provisioning templates created by this topic...")
        existing = []
        for name in WORKSHOP_PROVISIONING_TEMPLATES:
            described = safe_api_call(
                self.iot.describe_provisioning_template,
                "Describe provisioning template",
                name,
                debug=self.debug,
                templateName=name,
            )
            if described:
                existing.append(name)
                self._plan(f"provisioning template {name}")
        if self._confirm_destructive("provisioning templates", len(existing)):
            for name in existing:
                safe_api_call(
                    self.iot.delete_provisioning_template,
                    "Delete provisioning template",
                    name,
                    debug=self.debug,
                    templateName=name,
                )

    def _cleanup_topic_rules(self):
        """Delete the topic's Just-in-Time Registration topic rule(s)."""
        self._info("\n🔎 Topic rules created by this topic...")
        for rule_name in WORKSHOP_TOPIC_RULES:
            if not matches_workshop_pattern(rule_name, "iot_rule"):
                continue
            self._plan(f"topic rule {rule_name}")
            if not self.dry_run:
                safe_api_call(
                    self.iot.delete_topic_rule,
                    "Delete topic rule",
                    rule_name,
                    debug=self.debug,
                    ruleName=rule_name,
                )

    def _cleanup_thing_groups(self):
        """Delete the topic's workshop thing groups (pattern-scoped)."""
        self._info("\n🔎 Thing groups created by this topic...")
        for group_name in WORKSHOP_THING_GROUPS:
            described = safe_api_call(
                self.iot.describe_thing_group,
                "Describe thing group",
                group_name,
                debug=self.debug,
                thingGroupName=group_name,
            )
            if not described:
                continue
            self._plan(f"thing group {group_name}")
            if not self.dry_run:
                safe_api_call(
                    self.iot.delete_thing_group,
                    "Delete thing group",
                    group_name,
                    debug=self.debug,
                    thingGroupName=group_name,
                )

    def _cleanup_policies(self, iot_client, policy_names, region_label):
        """Delete the topic's device/claim policies (after certs are detached)."""
        self._info(f"\n🔎 Device / claim policies created by this topic ({region_label})...")
        for policy_name in policy_names:
            described = safe_api_call(
                iot_client.get_policy,
                "Get policy",
                policy_name,
                debug=self.debug,
                policyName=policy_name,
            )
            if not described:
                continue
            self._plan(f"policy {policy_name}")
            if self.dry_run:
                continue
            # Delete non-default policy versions before the policy itself.
            versions = safe_api_call(
                iot_client.list_policy_versions,
                "List policy versions",
                policy_name,
                debug=self.debug,
                policyName=policy_name,
            )
            for version in (versions or {}).get("policyVersions", []):
                if not version.get("isDefaultVersion"):
                    safe_api_call(
                        iot_client.delete_policy_version,
                        "Delete policy version",
                        policy_name,
                        debug=self.debug,
                        policyName=policy_name,
                        policyVersionId=version["versionId"],
                    )
            safe_api_call(
                iot_client.delete_policy,
                "Delete policy",
                policy_name,
                debug=self.debug,
                policyName=policy_name,
            )

    # -- base CloudFormation stack notice ---------------------------------

    def print_base_stack_notice(self):
        """Explain that stack-managed Lambdas/roles are NOT deleted here.

        The Just-in-Time Registration handler and pre-provisioning hook AWS
        Lambda functions (and their IAM roles + log groups) belong to the base
        CloudFormation stack; learners only updated their code. Deleting them
        out-of-band would leave the stack in drift, so we surface the stack name
        and let CloudFormation own them.
        """
        self._info("\n🧱 Base infrastructure (AWS Lambda functions, IAM roles) — NOT deleted here")
        try:
            cfn = boto3.client("cloudformation", region_name=self.region)
            stacks = cfn.describe_stacks()
            candidates = [
                stack["StackName"]
                for stack in stacks.get("Stacks", [])
                if "provisioning" in stack["StackName"].lower()
            ]
        except ClientError:
            candidates = []
        if candidates:
            for name in candidates:
                print(
                    f"{Fore.CYAN}  • The pre-provisioning hook + JITR handler Lambdas belong to "
                    f"CloudFormation stack '{name}'.{Style.RESET_ALL}"
                )
            print(
                f"{Fore.CYAN}    AWS-led event: removed automatically at event end. "
                f"Own account: delete that stack when finished with the topic.{Style.RESET_ALL}"
            )
        else:
            print(
                f"{Fore.CYAN}  • The JITR handler and pre-provisioning hook Lambdas are stack-managed. "
                f"Delete the base CloudFormation stack to remove them (own account), or let the "
                f"AWS-led event tear it down.{Style.RESET_ALL}"
            )

    # -- MAR (second Region) ----------------------------------------------

    def cleanup_mar_region(self):
        """Clean the moved certificate + thing in the second (MAR) Region."""
        if not self.iot_mar:
            return
        label = f"MAR Region {self.mar_region}"
        self._info(f"\n=== Cleaning up the second Region ({self.mar_region}) — Section 5 (MAR) ===")
        thing_names = self._list_things(self.iot_mar, WORKSHOP_MAR_THING_PREFIXES)
        # In the destination Region there is no workshop CA, so cert discovery
        # relies on thing principals and the MAR device policy only.
        saved_ca_ids = self.workshop_ca_ids
        self.workshop_ca_ids = []
        try:
            self._cleanup_certificates(
                self.iot_mar, thing_names, WORKSHOP_MAR_POLICY_NAMES, label
            )
        finally:
            self.workshop_ca_ids = saved_ca_ids
        self._cleanup_things(self.iot_mar, thing_names, label)
        self._cleanup_policies(self.iot_mar, WORKSHOP_MAR_POLICY_NAMES, label)

    # -- entry point -------------------------------------------------------

    def run(self):
        mode = "DRY RUN (nothing will be deleted)" if self.dry_run else "EXECUTE"
        print(f"{Fore.CYAN}{'=' * 68}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Advanced Device Provisioning — per-topic cleanup [{mode}]{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 68}{Style.RESET_ALL}")
        self._info(f"Region (workshop): {self.region}")
        if self.mar_region:
            self._info(f"Region (MAR / Section 5): {self.mar_region}")
        print(
            f"{Fore.GREEN}This cleanup is scoped to the provisioning topic only. The shared setup "
            f"(repo, dependencies, language, OpenSSL) is never touched.{Style.RESET_ALL}"
        )
        if self.dry_run:
            print(
                f"{Fore.YELLOW}Dry run: reviewing what would be removed. Re-run with --execute "
                f"to delete (you will be asked to confirm destructive deletes).{Style.RESET_ALL}"
            )

        label = f"Region {self.region}"

        # 1) Discover workshop CAs first — needed to find JITP/JITR device certs.
        cas = self.discover_workshop_cas()

        # 2) Certificates (destructive → confirm). Detaches policies + principals.
        thing_names = self._list_things(self.iot, WORKSHOP_THING_PREFIXES)
        self._cleanup_certificates(
            self.iot, thing_names, WORKSHOP_POLICY_NAMES, label
        )

        # 3) Things (their certs are now detached/deleted).
        self._cleanup_things(self.iot, thing_names, label)

        # 4) Provisioning templates (destructive → confirm).
        self._cleanup_templates()

        # 5) Custom CAs (destructive → confirm): deregister, then delete.
        self.delete_workshop_cas(cas)

        # 6) Topic rules, thing groups, policies (non-CA/template/cert cleanup).
        self._cleanup_topic_rules()
        self._cleanup_thing_groups()
        self._cleanup_policies(self.iot, WORKSHOP_POLICY_NAMES, label)

        # 7) Second Region (MAR) cleanup, if requested.
        self.cleanup_mar_region()

        # 8) Explain the stack-managed Lambdas we deliberately leave alone.
        self.print_base_stack_notice()

        print(f"\n{Fore.GREEN}{'=' * 68}{Style.RESET_ALL}")
        if self.dry_run:
            print(f"{Fore.GREEN}Dry run complete. No resources were changed.{Style.RESET_ALL}")
        else:
            print(f"{Fore.GREEN}Cleanup complete. Retained anything you declined to delete.{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{'=' * 68}{Style.RESET_ALL}")


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Per-topic cleanup for the Advanced Device Provisioning End-to-End topic. "
            "Pattern-scoped and non-destructive by default (dry run); pass --execute to delete."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete resources (default is a dry run that deletes nothing).",
    )
    parser.add_argument(
        "--mar-region",
        default=None,
        help=(
            "The second Region used in Section 5 (Multi-Account Registration), e.g. us-west-2. "
            "Cleans the moved certificate and thing there without touching the main Region."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print API request/response detail for each control-plane call.",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    language = get_language()
    cleanup = AdvancedProvisioningCleanup(
        execute=args.execute,
        mar_region=args.mar_region,
        language=language,
        debug=args.debug,
    )
    cleanup.run()


if __name__ == "__main__":
    main()
