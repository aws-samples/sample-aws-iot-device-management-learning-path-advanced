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
  account resources stay safe. This includes things, certificates, provisioning
  templates, custom CAs, topic rules, thing groups, thing types, and device/claim
  policies — everything the sections create except the base-stack Lambdas below.
- **Non-destructive by default.** With no flags the script performs a DRY RUN:
  it lists what it *would* remove and deletes nothing. Pass ``--execute`` to
  actually delete.
- **Explicit confirmation before destructive deletes.** Before deleting any
  Certificate Authority (CA), provisioning template, certificate, or thing, the
  script asks the learner to confirm. If the learner declines, the affected
  resource is RETAINED and the script moves on.
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
import time

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
from loader import load_messages  # noqa: E402
from confirmation import is_affirmative  # noqa: E402

init()

# --- i18n message catalog + resolver -------------------------------------
# Populated once at entry (see main()) via load_messages(). The wrapper below is
# the shared nested-capable convention documented in i18n/README.md: dotted keys
# walk the nested catalog, a missing key falls back to the key itself, and
# positional {} placeholders are filled via str.format(*args). Defined per-script
# on purpose (NOT centralized in loader.py). The localized yes/no PARSING stays in
# confirmation.is_affirmative(); only the prompt TEXT lives in the catalog.
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


# ---------------------------------------------------------------------------
# Known workshop resource names created by THIS topic (used alongside
# matches_workshop_pattern for scoping). Keeping these explicit means the
# cleanup can only ever select resources the sections above actually created.
# ---------------------------------------------------------------------------

# Provisioning templates created via create-provisioning-template (Sections 3, 4).
WORKSHOP_PROVISIONING_TEMPLATES = ["FleetClaimTemplate", "TrustedUserTemplate"]

# Device / claim policies created by the scripts and provisioning templates.
WORKSHOP_POLICY_NAMES = [
    "FleetClaimPolicy",  # Section 3 — scoped claim (bootstrap) policy
    "FleetProvisionedDevicePolicy",  # Section 3 — template-created device policy
    "SmartHomeDevicePolicy",  # Section 4 — trusted-user device policy
    "JITPDevicePolicy",  # Section 2 — JITP device policy
    "JITRDevicePolicy",  # Section 2 — JITR device policy
    "MARLobbyDevicePolicy",  # Section 5 — MAR lobby (Region 1) device policy
    "MARLobbyRestrictedPolicy",  # Section 5 — MAR challenge's restricted lobby policy
    "RotationDevicePolicy",  # Section 6 — account-level rotation device policy
]

# Device policy created in the SECOND Region for the MAR move (Section 5).
WORKSHOP_MAR_POLICY_NAMES = ["MARProductionDevicePolicy"]

# Just-in-Time Registration topic rule (Section 2).
WORKSHOP_TOPIC_RULES = ["JITRRegistrationRule"]

# Static thing groups the provisioning templates and JITP registration config
# reference (Section 2's JITP-Onboarded, Section 3's v2 template).
WORKSHOP_THING_GROUPS = ["fleet-connected-vehicles", "JITP-Onboarded"]

# Thing types created by the fleet-provisioning sections (Sections 3 and 4).
# ConnectedVehicle is created by Section 2's optional JITP challenge
# ("Requirement 4 assumes the ConnectedVehicle thing type exists").
WORKSHOP_THING_TYPES = ["SedanVehicle", "SUVVehicle", "SmartHomeSensor", "ConnectedVehicle"]

# Section 6 (Certificate Rotation) resources. None of these match the generic
# WORKSHOP_TOPIC_RULES/WORKSHOP_THING_GROUPS patterns above (the rotation rules
# are snake_case, not *Rule; the rotation group is base infrastructure the
# script must empty, never delete), so they get their own constants and their
# own cleanup step rather than being folded into the generic ones.
WORKSHOP_ROTATION_JOB_ID = "ws-cert-rotation-001"
WORKSHOP_ROTATION_TOPIC_RULES = ["ws_rotation_request", "ws_rotation_terminal"]
# Base-infrastructure thing group (provisioning-base.yaml's RotationThingGroup).
# The script removes member things from it but never deletes the group itself.
WORKSHOP_ROTATION_THING_GROUP = "ws-aws-iot-dm-adv-prov-rotation"
# Deferred-deletion schedule name prefix (rotation_handler.py's _create_schedule:
# f"ws-aws-iot-dm-adv-prov-revoke-{certificate_id[:16]}"). Certificates are
# always deleted before this sweep runs (steps 2 and 3 of run() precede it), so
# every schedule this finds is already pointed at a certificate that no longer
# exists — there is no live cert-vs-schedule ordering hazard to preserve here,
# unlike Section 6's own per-device reset block, which runs mid-topic while
# other devices' certificates may still be live.
WORKSHOP_REVOKE_SCHEDULE_PREFIX = "ws-aws-iot-dm-adv-prov-revoke"
# Named shadow the rotation handler uses to track in-flight state per device
# (GetThingShadow/DeleteThingShadow calls in rotation_handler.py). Deleting a
# thing does NOT delete its shadows, so this must be removed explicitly before
# the thing itself, or the record is orphaned with nothing left to find it by.
WORKSHOP_ROTATION_SHADOW_NAME = "ws-rotation"

# Section 3's optional certificate-provider lab (fleet_provision_by_claim.py /
# 3-fleet-provisioning-claim's "sign with your own CA" exercise). Deleting this
# reverts CreateCertificateFromCsr to Amazon-signed for the account.
WORKSHOP_CERTIFICATE_PROVIDER_NAME = "ws-aws-iot-dm-adv-prov-cert-provider"

# Fixed name of the base CloudFormation stack deployed once per topic (see
# the topic overview's self-paced deploy step). Looked up by this exact name
# rather than an unscoped describe_stacks() enumeration — see the notice on
# print_base_stack_notice() below.
BASE_STACK_NAME = "ws-aws-iot-dm-adv-prov-base"

# Thing-name prefixes this topic uses. Vehicle-VIN-### matches the built-in
# "thing" pattern; the others are passed as custom prefixes. AnyCompany-Sensor-
# is Section 6 (Certificate Rotation) — normally cleaned by that section's own
# reset block, but included here too so the automated script catches it if a
# learner skips straight to this script instead.
WORKSHOP_THING_PREFIXES = [
    "Vehicle-VIN-",
    "SmartHome-Sensor-",
    "Vehicle-VIN-MAR-",
    "AnyCompany-Sensor-",
]

# Thing prefix used specifically for the moved device in the MAR (second) Region.
WORKSHOP_MAR_THING_PREFIXES = ["Vehicle-VIN-MAR-"]

# Section 6's own thing prefix — the only one that ever carries a ws-rotation
# named shadow (see WORKSHOP_ROTATION_SHADOW_NAME below), so _cleanup_things
# only attempts the shadow-delete pre-step for names matching this.
WORKSHOP_ROTATION_THING_PREFIXES = ["AnyCompany-Sensor-"]

# Exact common names of the self-signed workshop root CAs this topic creates
# (Section 2's JITP and JITR labs). Matched exactly rather than by loose
# substring ("AnyCompany" + "Root CA" alone) so a learner's own unrelated CA
# sharing those words is never swept up by this cleanup.
WORKSHOP_CA_COMMON_NAMES = ("AnyCompany JITP Root CA", "AnyCompany JITR Root CA")


class AdvancedProvisioningCleanup:
    """Pattern-scoped, confirmation-gated cleanup for the provisioning topic."""

    def __init__(self, execute=False, region=None, mar_region=None, language="en", debug=False):
        # Non-destructive by default: dry_run is the inverse of --execute.
        self.dry_run = not execute
        self.mar_region = mar_region
        self.language = language
        self.debug = debug

        # Resolve the Region the same way every other script in this sample
        # repo does: an explicit --region wins, otherwise fall back to boto3's
        # own default resolution chain (AWS_DEFAULT_REGION / AWS_REGION, then
        # the active profile's "region" in ~/.aws/config, then IMDS) rather
        # than a hardcoded literal. A learner who set their Region only via
        # 'aws configure' (which writes ~/.aws/config, not an env var) would
        # otherwise have every hands-on 'aws iot ...' command target their
        # real Region while this script silently pointed at us-east-1 instead
        # — the dry run would then report "nothing found" for the wrong
        # reason, and --execute could act on unrelated resources there.
        self.region = region or boto3.session.Session().region_name
        if not self.region:
            raise SystemExit(
                "No AWS Region resolved. Pass --region, or set it via 'aws configure' "
                "or the AWS_DEFAULT_REGION environment variable."
            )
        self.iot = boto3.client("iot", region_name=self.region)
        self.iot_mar = boto3.client("iot", region_name=mar_region) if mar_region else None

        # Populated during CA discovery; reused for certificate discovery.
        self.workshop_ca_ids = []

        # Lazily resolved per-Region iot-data clients (Section 6's rotation
        # shadow lives on the data plane, not the control plane). Cached by
        # Region name so the endpoint lookup only happens once per Region.
        self._iot_data_clients = {}

    # -- helpers -----------------------------------------------------------

    def _info(self, text):
        print(f"{Fore.CYAN}{text}{Style.RESET_ALL}")

    def _plan(self, text):
        # A resource the cleanup would act on (shown in both dry-run and execute).
        prefix = get_message("plan.prefix_dry_run") if self.dry_run else get_message("plan.prefix_execute")
        print(f"{Fore.YELLOW}  • {prefix}: {text}{Style.RESET_ALL}")

    def _confirm_destructive(self, category, count):
        """Ask for explicit confirmation before a destructive category.

        Returns True to proceed, False to RETAIN (skip) the category. In dry-run
        mode nothing is deleted, so no confirmation is needed.
        """
        if self.dry_run or count == 0:
            return not self.dry_run and count > 0
        print(f"\n{Fore.RED}{get_message('prompts.confirm_warning', count, category)}{Style.RESET_ALL}")
        answer = input(f"{Fore.YELLOW}{get_message('prompts.confirm_question', category)}{Style.RESET_ALL}")
        if is_affirmative(answer, self.language):
            return True
        print(f"{Fore.GREEN}{get_message('prompts.retained', category)}{Style.RESET_ALL}")
        return False

    def _is_workshop_thing(self, thing_name):
        """True if the thing name matches any workshop prefix/pattern."""
        if matches_workshop_pattern(thing_name, "thing"):
            return True
        return any(matches_workshop_pattern(thing_name, "thing", prefix=prefix) for prefix in WORKSHOP_THING_PREFIXES)

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

    def _iot_data_client(self, iot_client, region_name):
        """Return a cached iot-data client for the Region iot_client talks to.

        Resolved the same way rotation_handler.py and device_simulator.py
        already do (describe_endpoint(endpointType="iot:Data-ATS") -> a
        boto3 "iot-data" client against that endpoint), since DeleteThingShadow
        lives on the data plane, not the control plane.
        """
        if region_name not in self._iot_data_clients:
            described = safe_api_call(
                iot_client.describe_endpoint,
                "Describe endpoint",
                f"IoT data endpoint ({region_name})",
                debug=self.debug,
                endpointType="iot:Data-ATS",
            )
            if not described:
                return None
            endpoint = described["endpointAddress"]
            self._iot_data_clients[region_name] = boto3.client(
                "iot-data", region_name=region_name, endpoint_url=f"https://{endpoint}"
            )
        return self._iot_data_clients[region_name]

    def _delete_rotation_shadow(self, iot_client, region_name, thing_name):
        """Delete the ws-rotation named shadow before its thing is deleted.

        Deleting a thing does not delete its shadows (see the callout in
        Section 6's own reset block), so a thing this script deletes without
        this step first would leave its rotation record orphaned — attached
        to a thing that no longer exists, and invisible until someone goes
        looking for it. Only ever attempted for things this script is about
        to delete itself, and errors (including "no such shadow") are
        swallowed by safe_api_call, so a device that never rotated is unaffected.
        """
        data_client = self._iot_data_client(iot_client, region_name)
        if not data_client:
            return
        safe_api_call(
            data_client.delete_thing_shadow,
            "Delete rotation shadow",
            thing_name,
            debug=self.debug,
            thingName=thing_name,
            shadowName=WORKSHOP_ROTATION_SHADOW_NAME,
        )

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
        """Find workshop custom CAs by exact subject common name (scoped)."""
        self._info(f"\n{get_message('status.discovering_cas')}")
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
            if common_name in WORKSHOP_CA_COMMON_NAMES:
                found.append((ca_id, common_name))
        self.workshop_ca_ids = [ca_id for ca_id, _ in found]
        if found:
            for ca_id, common_name in found:
                self._plan(get_message("plan.ca", common_name, ca_id))
        else:
            self._info(get_message("status.none_found"))
        return found

    def delete_workshop_cas(self, cas):
        """Deregister (INACTIVE) then delete workshop CAs, with confirmation."""
        if not self._confirm_destructive(get_message("categories.certificate_authorities"), len(cas)):
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
        self._info(f"\n{get_message('status.discovering_certificates', region_label)}")
        cert_ids = self._discover_certificate_ids(iot_client, thing_names, policy_names)
        for cert_id in cert_ids:
            self._plan(get_message("plan.certificate", cert_id))
        if self._confirm_destructive(get_message("categories.certificates_region", region_label), len(cert_ids)):
            for cert_id in cert_ids:
                self._delete_certificate(iot_client, cert_id)
        return cert_ids

    def _cleanup_things(self, iot_client, thing_names, region_label, region_name=None):
        """Delete workshop things (their certificates are already detached), with confirmation.

        Things are matched by name PREFIX (``WORKSHOP_THING_PREFIXES``,
        ``_list_things``), not an exact or account-scoped pattern — a prefix
        like ``Vehicle-VIN-`` can also match a different sample repo's things
        in the same account (the Device Management Basics workshop uses the
        identical prefix for its own devices). Every other destructive
        category in this script (CAs, templates, certificates) confirms before
        deleting; things did not, so a learner running this script against an
        account that also has another workshop's matching things would delete
        them with no warning. Confirm here for the same reason.
        """
        self._info(f"\n{get_message('status.discovering_things', region_label)}")
        for thing_name in thing_names:
            self._plan(get_message("plan.thing", thing_name))
        if not self._confirm_destructive(get_message("categories.things_region", region_label), len(thing_names)):
            return
        for thing_name in thing_names:
            # Section 6's rotation devices carry a ws-rotation named shadow that
            # delete_thing never removes on its own — delete it first so the
            # record does not outlive the thing (see _delete_rotation_shadow).
            # Scoped to that section's own thing prefix so every other device
            # this loop deletes (which never had a rotation shadow) does not
            # generate a spurious "shadow not found" error on every run.
            if any(thing_name.startswith(prefix) for prefix in WORKSHOP_ROTATION_THING_PREFIXES):
                self._delete_rotation_shadow(iot_client, region_name or self.region, thing_name)
            safe_api_call(
                iot_client.delete_thing,
                "Delete thing",
                thing_name,
                debug=self.debug,
                thingName=thing_name,
            )

    def _cleanup_templates(self):
        """Delete the topic's provisioning templates, with confirmation."""
        self._info(f"\n{get_message('status.discovering_templates')}")
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
                self._plan(get_message("plan.provisioning_template", name))
        if self._confirm_destructive(get_message("categories.provisioning_templates"), len(existing)):
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
        self._info(f"\n{get_message('status.discovering_topic_rules')}")
        for rule_name in WORKSHOP_TOPIC_RULES:
            if not matches_workshop_pattern(rule_name, "iot_rule"):
                continue
            self._plan(get_message("plan.topic_rule", rule_name))
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
        self._info(f"\n{get_message('status.discovering_thing_groups')}")
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
            self._plan(get_message("plan.thing_group", group_name))
            if not self.dry_run:
                safe_api_call(
                    self.iot.delete_thing_group,
                    "Delete thing group",
                    group_name,
                    debug=self.debug,
                    thingGroupName=group_name,
                )

    def _cleanup_thing_types(self):
        """Deprecate + delete the topic's workshop thing types (pattern-scoped).

        A thing type cannot be deleted while any thing still uses it, and AWS
        IoT enforces a 5-minute wait after deprecation before deletion is
        allowed (see the "Delete a thing type" developer guide topic). Because
        this topic's things are removed earlier in ``run()`` (step 3, before
        this step), only a thing outside the discovered set — for example one
        you created by hand with the same thing type — could still block it;
        the delete call is left to fail safely (and print why) in that case.
        """
        self._info(f"\n{get_message('status.discovering_thing_types')}")
        existing = []
        for type_name in WORKSHOP_THING_TYPES:
            described = safe_api_call(
                self.iot.describe_thing_type,
                "Describe thing type",
                type_name,
                debug=self.debug,
                thingTypeName=type_name,
            )
            if described:
                existing.append(type_name)
                self._plan(get_message("plan.thing_type", type_name))

        if not existing or self.dry_run:
            return

        for type_name in existing:
            safe_api_call(
                self.iot.deprecate_thing_type,
                "Deprecate thing type",
                type_name,
                debug=self.debug,
                thingTypeName=type_name,
            )

        self._info(get_message("status.waiting_thing_types"))
        time.sleep(300)  # AWS-required wait after deprecation before delete  # nosemgrep: arbitrary-sleep

        for type_name in existing:
            safe_api_call(
                self.iot.delete_thing_type,
                "Delete thing type",
                type_name,
                debug=self.debug,
                thingTypeName=type_name,
            )

    def _cleanup_policies(self, iot_client, policy_names, region_label):
        """Delete the topic's device/claim policies (after certs are detached)."""
        self._info(f"\n{get_message('status.discovering_policies', region_label)}")
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
            self._plan(get_message("plan.policy", policy_name))
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

    # -- Section 6 (Certificate Rotation) resources ------------------------

    def _cleanup_rotation_job(self):
        """Cancel + delete the rotation campaign, if it exists."""
        described = safe_api_call(
            self.iot.describe_job,
            "Describe job",
            WORKSHOP_ROTATION_JOB_ID,
            debug=self.debug,
            jobId=WORKSHOP_ROTATION_JOB_ID,
        )
        if not described:
            return
        self._plan(get_message("plan.rotation_job", WORKSHOP_ROTATION_JOB_ID))
        if self.dry_run:
            return
        # A CONTINUOUS job runs until cancelled — delete_job on its own is
        # refused while it is still IN_PROGRESS, so cancel first (force=True
        # covers a job that already has in-flight executions, same as the
        # topic content's own reset instructions).
        safe_api_call(
            self.iot.cancel_job,
            "Cancel job",
            WORKSHOP_ROTATION_JOB_ID,
            debug=self.debug,
            jobId=WORKSHOP_ROTATION_JOB_ID,
            force=True,
        )
        safe_api_call(
            self.iot.delete_job,
            "Delete job",
            WORKSHOP_ROTATION_JOB_ID,
            debug=self.debug,
            jobId=WORKSHOP_ROTATION_JOB_ID,
            force=True,
        )

    def _cleanup_rotation_topic_rules(self):
        """Delete the rotation request/terminal topic rules, if they exist."""
        for rule_name in WORKSHOP_ROTATION_TOPIC_RULES:
            described = safe_api_call(
                self.iot.get_topic_rule,
                "Get topic rule",
                rule_name,
                debug=self.debug,
                ruleName=rule_name,
            )
            if not described:
                continue
            self._plan(get_message("plan.topic_rule", rule_name))
            if not self.dry_run:
                safe_api_call(
                    self.iot.delete_topic_rule,
                    "Delete topic rule",
                    rule_name,
                    debug=self.debug,
                    ruleName=rule_name,
                )

    def _empty_rotation_thing_group(self):
        """Remove every member thing from the rotation work-queue group.

        The group itself (``WORKSHOP_ROTATION_THING_GROUP``) is base
        infrastructure created by the topic's CloudFormation stack — it is
        never deleted here, only emptied, so a thing left enrolled from an
        interrupted run does not sit in the queue indefinitely.
        """
        described = safe_api_call(
            self.iot.describe_thing_group,
            "Describe thing group",
            WORKSHOP_ROTATION_THING_GROUP,
            debug=self.debug,
            thingGroupName=WORKSHOP_ROTATION_THING_GROUP,
        )
        if not described:
            return
        member_things = []
        paginator = self.iot.get_paginator("list_things_in_thing_group")
        for page in paginator.paginate(thingGroupName=WORKSHOP_ROTATION_THING_GROUP):
            member_things.extend(page.get("things", []))
        for thing_name in member_things:
            self._plan(get_message("plan.rotation_thing_group_member", thing_name))
        if self.dry_run:
            return
        for thing_name in member_things:
            safe_api_call(
                self.iot.remove_thing_from_thing_group,
                "Remove thing from rotation group",
                thing_name,
                debug=self.debug,
                thingGroupName=WORKSHOP_ROTATION_THING_GROUP,
                thingName=thing_name,
            )

    def _cleanup_rotation_schedules(self):
        """Delete every pending deferred-deletion timer this topic created.

        By the time this runs, every workshop certificate (including any a
        pending schedule still targets) has already been deleted in steps 2
        and 3 of run() — so unlike Section 6's own per-device reset block
        (which scopes to just-detached certificate ids because other devices'
        rotations may still be in flight), a full sweep by name prefix is safe
        here: nothing this finds can still be a live, wanted timer.
        """
        scheduler_client = boto3.client("scheduler", region_name=self.region)
        listed = safe_api_call(
            scheduler_client.list_schedules,
            "List schedules",
            WORKSHOP_REVOKE_SCHEDULE_PREFIX,
            debug=self.debug,
            NamePrefix=WORKSHOP_REVOKE_SCHEDULE_PREFIX,
        )
        schedule_names = [s["Name"] for s in (listed or {}).get("Schedules", [])]
        for name in schedule_names:
            self._plan(get_message("plan.schedule", name))
        if self.dry_run:
            return
        for name in schedule_names:
            safe_api_call(
                scheduler_client.delete_schedule,
                "Delete schedule",
                name,
                debug=self.debug,
                Name=name,
            )

    def cleanup_rotation_resources(self):
        """Remove Section 6's rotation campaign, rules, queue membership, and timers.

        None of these match the generic topic-rule/thing-group patterns this
        script already scopes to (the rotation rules are snake_case, and the
        rotation thing group is base infrastructure that must be emptied, not
        deleted) — see the constants above for why each gets its own lookup.
        """
        self._info(f"\n{get_message('status.discovering_rotation_resources')}")
        self._cleanup_rotation_job()
        self._cleanup_rotation_topic_rules()
        self._empty_rotation_thing_group()
        self._cleanup_rotation_schedules()

    # -- Section 3 optional certificate-provider lab -----------------------

    def cleanup_certificate_provider(self):
        """Delete the Section 3 optional lab's certificate provider, if created.

        Deleting it reverts CreateCertificateFromCsr to Amazon-signed for the
        account — the provider is not part of the base CloudFormation stack,
        so deleting that stack does not remove it.
        """
        self._info(f"\n{get_message('status.discovering_certificate_provider')}")
        described = safe_api_call(
            self.iot.describe_certificate_provider,
            "Describe certificate provider",
            WORKSHOP_CERTIFICATE_PROVIDER_NAME,
            debug=self.debug,
            certificateProviderName=WORKSHOP_CERTIFICATE_PROVIDER_NAME,
        )
        if not described:
            self._info(get_message("status.none_found"))
            return
        self._plan(get_message("plan.certificate_provider", WORKSHOP_CERTIFICATE_PROVIDER_NAME))
        if not self.dry_run:
            safe_api_call(
                self.iot.delete_certificate_provider,
                "Delete certificate provider",
                WORKSHOP_CERTIFICATE_PROVIDER_NAME,
                debug=self.debug,
                certificateProviderName=WORKSHOP_CERTIFICATE_PROVIDER_NAME,
            )

    # -- account-wide settings this topic changed --------------------------

    def revert_event_configurations(self):
        """Turn the JOB/JOB_EXECUTION account-wide event setting back off.

        Section 6 Step 3 enables these with update-event-configurations so
        the rotation handler's topic rule can react to job-execution events;
        nothing in the topic ever reverts it. This is account-wide (not
        pattern-scoped to a resource name), so — like the SetV2LoggingOptions
        revert this script's sibling instructions already document — it is
        a plain revert-to-default with no destructive-delete confirmation
        gate: unlike a resource deletion, disabling it is trivially
        reversible by re-running Section 6 Step 3 if you run the section again.
        """
        described = safe_api_call(
            self.iot.describe_event_configurations,
            "Describe event configurations",
            "JOB / JOB_EXECUTION",
            debug=self.debug,
        )
        configs = (described or {}).get("eventConfigurations", {})
        job_enabled = configs.get("JOB", {}).get("Enabled", False)
        job_execution_enabled = configs.get("JOB_EXECUTION", {}).get("Enabled", False)
        if not job_enabled and not job_execution_enabled:
            return
        self._info(f"\n{get_message('status.reverting_event_configurations')}")
        self._plan(get_message("plan.event_configurations"))
        if self.dry_run:
            return
        safe_api_call(
            self.iot.update_event_configurations,
            "Revert event configurations",
            "JOB / JOB_EXECUTION",
            debug=self.debug,
            eventConfigurations={
                "JOB": {"Enabled": False},
                "JOB_EXECUTION": {"Enabled": False},
            },
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
        self._info(f"\n{get_message('notice.header')}")
        try:
            cfn = boto3.client("cloudformation", region_name=self.region)
            # Look up the one, fixed-named base stack directly rather than
            # calling describe_stacks() with no StackName to enumerate every
            # stack in the account: that unscoped form needs Resource: "*" in
            # IAM (CloudFormation cannot apply a single-stack-scoped policy to
            # a call with nothing to scope it against), while every other
            # lookup in this workshop resolves a resource by its exact, known
            # name instead of a broad list (see the naming-convention note on
            # thing/certificate discovery elsewhere in this script). This
            # stack's name is fixed and documented in the topic overview, so
            # there is nothing to search for.
            stacks = cfn.describe_stacks(StackName=BASE_STACK_NAME)
            candidates = [stack["StackName"] for stack in stacks.get("Stacks", [])]
        except ClientError:
            candidates = []
        if candidates:
            for name in candidates:
                print(f"{Fore.CYAN}{get_message('notice.stack_named', name)}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}{get_message('notice.stack_named_detail')}{Style.RESET_ALL}")
        else:
            print(f"{Fore.CYAN}{get_message('notice.stack_unknown')}{Style.RESET_ALL}")

    # -- MAR (second Region) ----------------------------------------------

    def cleanup_mar_region(self):
        """Clean the moved certificate + thing in the second (MAR) Region."""
        if not self.iot_mar:
            return
        label = get_message("labels.mar_region", self.mar_region)
        self._info(f"\n{get_message('status.cleaning_mar_region', self.mar_region)}")
        thing_names = self._list_things(self.iot_mar, WORKSHOP_MAR_THING_PREFIXES)
        # In the destination Region there is no workshop CA, so cert discovery
        # relies on thing principals and the MAR device policy only.
        saved_ca_ids = self.workshop_ca_ids
        self.workshop_ca_ids = []
        try:
            self._cleanup_certificates(self.iot_mar, thing_names, WORKSHOP_MAR_POLICY_NAMES, label)
        finally:
            self.workshop_ca_ids = saved_ca_ids
        self._cleanup_things(self.iot_mar, thing_names, label, region_name=self.mar_region)
        self._cleanup_policies(self.iot_mar, WORKSHOP_MAR_POLICY_NAMES, label)

    # -- entry point -------------------------------------------------------

    def run(self):
        mode = get_message("header.mode_dry_run") if self.dry_run else get_message("header.mode_execute")
        print(f"{Fore.CYAN}{'=' * 68}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{get_message('header.title', mode)}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'=' * 68}{Style.RESET_ALL}")
        self._info(get_message("status.region_workshop", self.region))
        if self.mar_region:
            self._info(get_message("status.region_mar", self.mar_region))
        print(f"{Fore.GREEN}{get_message('status.scope_note')}{Style.RESET_ALL}")
        if self.dry_run:
            print(f"{Fore.YELLOW}{get_message('status.dry_run_hint')}{Style.RESET_ALL}")

        label = get_message("labels.region", self.region)

        # 1) Discover workshop CAs first — needed to find JITP/JITR device certs.
        cas = self.discover_workshop_cas()

        # 2) Certificates (destructive → confirm). Detaches policies + principals.
        thing_names = self._list_things(self.iot, WORKSHOP_THING_PREFIXES)
        self._cleanup_certificates(self.iot, thing_names, WORKSHOP_POLICY_NAMES, label)

        # 3) Things (their certs are now detached/deleted).
        self._cleanup_things(self.iot, thing_names, label, region_name=self.region)

        # 4) Provisioning templates (destructive → confirm).
        self._cleanup_templates()

        # 5) Custom CAs (destructive → confirm): deregister, then delete.
        self.delete_workshop_cas(cas)

        # 6) Topic rules, thing groups, policies (non-CA/template/cert cleanup).
        self._cleanup_topic_rules()
        self._cleanup_thing_groups()
        self._cleanup_policies(self.iot, WORKSHOP_POLICY_NAMES, label)

        # 6b) Thing types — deprecate + delete last among the main-Region cleanup,
        # since deprecation requires a 5-minute wait and every thing that used
        # to reference one was already deleted in step 3.
        self._cleanup_thing_types()

        # 6c) Section 6 (Certificate Rotation) resources — job, topic rules,
        # rotation-queue membership, and deferred-deletion timers. Runs after
        # certificates/things (steps 2-3) so the schedule sweep below never
        # races a certificate this run just deleted.
        self.cleanup_rotation_resources()

        # 6d) Section 3's optional certificate-provider lab, if used.
        self.cleanup_certificate_provider()

        # 6e) Account-wide settings this topic changed and never reverted.
        self.revert_event_configurations()

        # 7) Second Region (MAR) cleanup, if requested.
        self.cleanup_mar_region()

        # 8) Explain the stack-managed Lambdas we deliberately leave alone.
        self.print_base_stack_notice()

        print(f"\n{Fore.GREEN}{'=' * 68}{Style.RESET_ALL}")
        if self.dry_run:
            print(f"{Fore.GREEN}{get_message('status.dry_run_complete')}{Style.RESET_ALL}")
        else:
            print(f"{Fore.GREEN}{get_message('status.execute_complete')}{Style.RESET_ALL}")
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
        "--region",
        default=None,
        help=(
            "The Region where you ran this topic's hands-on sections. Defaults to "
            "boto3's normal Region resolution (AWS_DEFAULT_REGION, then your AWS "
            "CLI profile's configured Region) if omitted."
        ),
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

    # Load the localized message catalog once, before any user-facing print.
    # (Placed after argument parsing so --help stays free of the language menu.)
    global messages
    messages = load_messages("cleanup_script", language)

    cleanup = AdvancedProvisioningCleanup(
        execute=args.execute,
        region=args.region,
        mar_region=args.mar_region,
        language=language,
        debug=args.debug,
    )
    cleanup.run()


if __name__ == "__main__":
    main()
