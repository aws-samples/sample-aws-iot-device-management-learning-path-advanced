# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Rotation enroller — the piece that closes the age-based rotation loop.

Section 1 ("Foundations & Decision Framework") describes a loop: issue a
long-lived certificate, let AWS IoT Device Defender flag it once it crosses an
age threshold, enrol the flagged device in a rotation queue, and let a
continuous AWS IoT Jobs campaign replace its certificate. Section 6 builds the
rotation half of that loop hands-on. **This file is the other half** — the step
that turns an audit finding into an enrolment.

Not deployed by the workshop, and deliberately so
-------------------------------------------------
``DEVICE_CERTIFICATE_AGE_CHECK`` runs as part of a **scheduled audit**, and the
most frequent schedule is **daily**. There is no way to observe this trigger
firing inside a workshop session, so wiring it up hands-on would mean building
something and then taking its behaviour on faith. It ships as a reference
implementation you can read, lift, and deploy in your own account instead.

How it is triggered
-------------------
**Amazon SNS.** Device Defender publishes audit notifications to an Amazon SNS
topic — that is its *only* notification target
(``UpdateAccountAuditConfiguration``'s
``auditNotificationTargetConfigurations`` accepts the single key ``SNS``). Point
that topic at this function:

    aws iot update-account-audit-configuration \\
        --audit-notification-target-configurations \\
          'SNS={targetArn=arn:aws:sns:REGION:ACCOUNT:TOPIC,roleArn=ROLE,enabled=true}'

It also runs **unattended on a schedule** with no event payload at all (an
Amazon EventBridge Scheduler schedule, or an Amazon EventBridge rule): with
nothing to read a task id from, it finds the most recent completed scheduled
audit itself. Use whichever fits your operations — the SNS path reacts sooner,
the scheduled path has fewer moving parts.

Note the distinction, because the two are readily confused: **Amazon EventBridge
Scheduler** is what the rotation handler uses to defer a certificate *deletion*.
It is not a route for audit notifications.

What it does
------------
1. Resolve the audit task to read findings from.
2. List the task's ``DEVICE_CERTIFICATE_AGE_CHECK`` findings, skipping ones
   already suppressed — that is what keeps each run cheap rather than
   re-processing the whole fleet daily.
3. Map each flagged certificate to the thing or things it is attached to.
4. **Reconcile** each thing against the rotation queue (see
   :func:`enqueue_rotation`): leave it alone if a rotation is already pending,
   otherwise make sure a fresh one is enqueued — including the stranded case,
   where the thing is a member but no execution exists.
5. Suppress that certificate's finding for a window, so the next few audits do
   not re-process a rotation already under way. The suppression is given an
   **expiration, never indefinite**, which is what makes step 4 run again later.

Why the suppression expires — and why that is not the safety net
---------------------------------------------------------------
An expiring suppression is what gives this loop its periodic tick: when it lapses,
the finding returns, step 4 reconciles, and a rotation that never completed is
re-enqueued without anyone being paged. That is the whole reason the loop is
self-healing rather than dependent on an operator noticing.

Note what the suppression is *not*: it is a reporting filter, so nothing about
correctness may depend on it. Step 4 reconciles current state on every run, so if
suppression were unavailable the loop would simply tick daily instead of weekly —
same logic, shorter period. Keep it that way.

The suppression is keyed on ``deviceCertificateId``, and a successful rotation ends
with that certificate deleted, so the finding can never recur for it. There is
nothing to un-suppress and nothing to clean up.

What this loop does *not* do: escalate
--------------------------------------
Reconciliation retries indefinitely and quietly, which is right for a transient
fault and wrong for a permanent one. Two readings of the same
``ListJobExecutionsForThing`` response tell you which you have, and they belong to
different owners:

* an execution stuck ``QUEUED`` well past your fleet's expected check-in interval
  (compare ``queuedAt``) means the **device** is unreachable — a connectivity
  problem, and a fleet-level metric rather than a per-device alarm;
* a run of terminal ``FAILED`` / ``TIMED_OUT`` executions for one thing means the
  **rotation** is broken for it — a policy, handler, or firmware problem.

Escalate the second after N attempts instead of re-enqueuing forever. The job
execution history *is* the attempt counter, so this needs no datastore.

Approaching expiry is a different check, and it is the deadline
--------------------------------------------------------------
Age is hygiene; expiry is a wall. ``DEVICE_CERTIFICATE_EXPIRING_CHECK`` is a
separate check reporting ``CERTIFICATE_APPROACHING_EXPIRATION`` and
``CERTIFICATE_PAST_EXPIRATION``, and unlike the age check it supports the
``ADD_THINGS_TO_THING_GROUP`` and ``UPDATE_DEVICE_CERTIFICATE`` mitigation actions —
so an escalation track can be wired with no code at all. Suppressing the *age*
finding does not suppress the *expiring* finding, so the two tracks do not interfere.

Size ``CERT_EXPIRATION_THRESHOLD_IN_DAYS`` to exceed your worst-case device
dormancy. The gap between the age threshold and the expiry threshold is your entire
window of agency: before expiry the device can still connect, so it can still
rotate; after it, an offline device cannot come back at all and the only remaining
action is to reach the device physically. The default threshold is 30 days, which is
too short for any fleet whose devices sleep for longer than that.

The rotation handler closes the loop from the other end: on a proven cutover it
removes the thing from the group and retires the old certificate, which takes
that certificate out of the check's scope so its finding clears on its own. The
replacement certificate is a distinct resource with its own age clock.

IAM the execution role needs
----------------------------
``iot:ListAuditFindings``, ``iot:ListAuditTasks``, ``iot:DescribeAuditTask``,
``iot:ListPrincipalThings``, ``iot:ListJobExecutionsForThing``,
``iot:ListThingsInThingGroup``, ``iot:AddThingToThingGroup``,
``iot:RemoveThingFromThingGroup``, ``iot:CreateAuditSuppression``, plus Amazon
CloudWatch Logs write access. Scope both thing-group actions to the rotation thing
group.

Deployment
----------
Package and deploy as you would any AWS Lambda function; no third-party
dependencies, so a plain zip of this one file is enough::

    cp lambdas/rotation_enroller.py index.py && zip -q enroller.zip index.py

Entry point is ``index.handler`` if you package it as ``index.py``, matching the
convention the rotation handler uses.

Note on localization: like the other ``lambdas/`` handlers in this repository,
this module's output is operator-facing Amazon CloudWatch Logs rather than
learner-facing terminal output, so it does not use the ``i18n/`` catalog (see
``i18n/README.md``).
"""

import datetime
import json
import os

import boto3

CHECK_NAME = "DEVICE_CERTIFICATE_AGE_CHECK"

ROTATION_GROUP = os.environ.get(
    "ROTATION_THING_GROUP", "ws-aws-iot-dm-adv-prov-rotation"
)
# How long to suppress a certificate's finding while its rotation is in flight.
# Give a rotation room to complete, but keep it FINITE: a stalled rotation should
# resurface as a finding rather than stay hidden.
SUPPRESSION_DAYS = int(os.environ.get("SUPPRESSION_WINDOW_DAYS", "7"))
# The continuous rotation campaign this enroller feeds. Needed to read a thing's
# execution state, which is what makes each run a reconciliation rather than a
# blind re-enqueue.
ROTATION_JOB_ID = os.environ.get("ROTATION_JOB_ID", "ws-cert-rotation-001")

# A job execution in either of these states means a rotation is already accounted
# for and must be left alone. Everything else is terminal.
NON_TERMINAL = ("QUEUED", "IN_PROGRESS")

iot = boto3.client("iot")


def handler(event, context):
    """Reconcile every age-flagged device against the rotation queue."""
    task_id = resolve_task_id(event)
    if task_id is None:
        print(json.dumps({"skipped": "no completed scheduled audit task found"}))
        return {"enrolled": 0, "reason": "no audit task"}

    enrolled, in_flight, skipped = [], [], []
    for certificate_arn, certificate_id in aged_certificates(task_id):
        things = things_for_certificate(certificate_arn)
        if not things:
            # A certificate with no thing attached cannot be rotated by a job —
            # a job targets things, not certificates. Worth surfacing rather
            # than silently dropping: it usually means an orphan to clean up.
            skipped.append({"certificateId": certificate_id, "why": "no thing attached"})
            continue

        for thing in things:
            if enqueue_rotation(thing):
                enrolled.append(thing)
            else:
                in_flight.append(thing)

        suppress_finding(certificate_id)

    result = {
        "taskId": task_id,
        "enrolled": enrolled,
        "already_in_flight": in_flight,
        "skipped": skipped,
    }
    print(json.dumps(result))
    return result


def enqueue_rotation(thing):
    """Ensure a rotation is pending for this thing. Returns True if one was created.

    This is a **reconciliation**, not a blind enqueue, and that is what makes the
    loop self-healing. Group membership alone does not mean a rotation is coming:
    a continuous job creates an execution when a thing **joins** the target group,
    never on a recurring sweep of the members already in it. So a thing left in the
    group with a terminal execution — the retirement handler failed before its
    ``RemoveThingFromThingGroup`` call, say — is stranded, and re-adding it changes
    nothing because ``AddThingToThingGroup`` on an existing member is a no-op.

    Leaving and rejoining the group is the documented recovery: removal moves a
    ``QUEUED`` execution to ``REMOVED``, and re-attaching the thing restarts the
    execution for the device.

    **Read the execution state before touching group membership.** Removing a thing
    mid-rotation would disrupt work that is progressing normally, so the check is a
    precondition rather than an optimisation:

    * a ``QUEUED`` execution means the work is already enqueued and the device will
      claim it whenever it next connects — a dormant device sits here harmlessly for
      as long as it takes, so leave it;
    * an ``IN_PROGRESS`` execution means a rotation is running right now — leave it,
      and note the documentation does not spell out what removal does to an
      ``IN_PROGRESS`` execution, which is a reason to be conservative rather than
      curious;
    * no non-terminal execution is the only state that needs reconciling, and by
      then there is nothing in flight to disturb. That is also what closes the race
      between the read and the write: a new execution cannot appear in between,
      because executions are created on *join* and the thing is already a member.
    """
    if pending_execution(thing):
        print(json.dumps({"rotation_already_pending": thing}))
        return False

    if thing in things_in_rotation_group():
        # Stranded: a member with no pending execution. Leave and rejoin so the
        # continuous job sees a genuine join and enqueues a fresh rotation.
        print(json.dumps({"rotation_stranded_requeued": thing}))
        iot.remove_thing_from_thing_group(
            thingGroupName=ROTATION_GROUP, thingName=thing
        )

    iot.add_thing_to_thing_group(thingGroupName=ROTATION_GROUP, thingName=thing)
    return True


def pending_execution(thing):
    """True when this thing already has a QUEUED or IN_PROGRESS rotation execution.

    Both filters are applied server-side, so this is a scoped read of one thing's
    executions on one job rather than a scan. ``ResourceNotFoundException`` means the
    thing has no executions at all, which is simply "nothing pending".
    """
    for status in NON_TERMINAL:
        try:
            summaries = iot.list_job_executions_for_thing(
                thingName=thing, jobId=ROTATION_JOB_ID, status=status
            ).get("executionSummaries", [])
        except iot.exceptions.ResourceNotFoundException:
            return False
        if summaries:
            return True
    return False


def things_in_rotation_group():
    """Current membership of the rotation queue, as a set."""
    members = set()
    for page in iot.get_paginator("list_things_in_thing_group").paginate(
        thingGroupName=ROTATION_GROUP
    ):
        members.update(page.get("things", []))
    return members


def resolve_task_id(event):
    """Find the audit task whose findings we should read.

    Two shapes are accepted, matching the two supported triggers: an Amazon SNS
    notification carrying the task id, or no usable payload at all (a scheduled
    invocation), in which case the most recent completed scheduled audit is used.
    """
    for record in (event or {}).get("Records", []):
        raw = record.get("Sns", {}).get("Message")
        if not raw:
            continue
        try:
            task_id = json.loads(raw).get("taskId")
        except (TypeError, ValueError):
            continue
        if task_id:
            return task_id

    # A direct invocation may pass the task id straight through.
    if isinstance(event, dict) and event.get("taskId"):
        return event["taskId"]

    return latest_completed_audit()


def latest_completed_audit():
    """Most recent completed scheduled audit task, or None if there is not one.

    ``ListAuditTasks`` requires a time range, so look back over a window wide
    enough to cover a daily schedule that skipped a day.

    Two details are deliberate, and both are the same lesson the rotation module
    teaches about reading an id back out of a list:

    * **The result is paginated**, so it is read through the paginator. Taking only
      the first page could miss the newest task entirely.
    * **The newest task is chosen by timestamp, not by position.** ``ListAuditTasks``
      makes no ordering guarantee, and its ``AuditTaskMetadata`` carries only
      ``taskId``/``taskStatus``/``taskType`` — there is no time field to sort on. So
      each candidate is resolved with ``DescribeAuditTask``, which does return
      ``taskStartTime``, and the maximum wins. Picking ``tasks[-1]`` would quietly
      process the wrong audit on any day with more than one completed run.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    candidates = []
    for page in iot.get_paginator("list_audit_tasks").paginate(
        startTime=now - datetime.timedelta(days=3),
        endTime=now,
        taskType="SCHEDULED_AUDIT_TASK",
        taskStatus="COMPLETED",
    ):
        candidates.extend(task["taskId"] for task in page.get("tasks", []))

    if not candidates:
        return None

    newest_id, newest_start = None, None
    for task_id in candidates:
        started = iot.describe_audit_task(taskId=task_id).get("taskStartTime")
        if started is None:
            continue
        if newest_start is None or started > newest_start:
            newest_id, newest_start = task_id, started
    return newest_id


def aged_certificates(task_id):
    """Yield ``(certificateArn, certificateId)`` for each newly aged certificate.

    ``listSuppressedFindings=False`` is what makes this delta-based: a
    certificate whose rotation is already in flight carries a suppression, so it
    is not yielded again on the next run.
    """
    paginator = iot.get_paginator("list_audit_findings")
    for page in paginator.paginate(
        taskId=task_id, checkName=CHECK_NAME, listSuppressedFindings=False
    ):
        for finding in page["findings"]:
            identifier = finding.get("nonCompliantResource", {}).get(
                "resourceIdentifier", {}
            )
            certificate_id = identifier.get("deviceCertificateId")
            certificate_arn = identifier.get("deviceCertificateArn")
            if certificate_id and certificate_arn:
                yield certificate_arn, certificate_id


def things_for_certificate(certificate_arn):
    """Things the flagged certificate is attached to.

    Usually exactly one. A certificate attached to several things would enrol
    all of them, which is the correct behaviour — each thing needs its own
    rotation.
    """
    paginator = iot.get_paginator("list_principal_things")
    things = []
    for page in paginator.paginate(principal=certificate_arn):
        things.extend(page["things"])
    return things


def suppress_finding(certificate_id):
    """Hide this certificate's finding while its rotation is in flight.

    Deliberately **not** ``suppressIndefinitely``. An expiring suppression means
    a rotation that stalls comes back as a finding instead of disappearing, so
    the loop degrades into an alert rather than into silence.
    """
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        days=SUPPRESSION_DAYS
    )
    try:
        iot.create_audit_suppression(
            checkName=CHECK_NAME,
            resourceIdentifier={"deviceCertificateId": certificate_id},
            expirationDate=expires,
            description=(
                "Rotation enqueued by rotation_enroller; suppressed while the "
                "rotation job execution is in flight."
            ),
            clientRequestToken=f"rotation-{certificate_id[:32]}",
        )
    except iot.exceptions.ResourceAlreadyExistsException:
        # Already suppressed by an earlier run — nothing to do.
        print(json.dumps({"suppression_already_exists": certificate_id}))
