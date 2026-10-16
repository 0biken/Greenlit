"""Sample records for the seed command: requirements, plans, runs, defects and evidence.

Everything goes through the services, so the same rules apply as in real use. Call inside the
organisation's scope. Each function does nothing if its release already exists, so the seed
stays safe to run again.

Ages (a fix waiting four days, a test not run for 42) need timestamps in the past. Those are
set directly on the rows after the services have created them. Seed only: nothing in the
product backdates anything.
"""

import hashlib
import struct
import uuid
import zlib
from datetime import timedelta

from django.utils import timezone

from apps.core.choices import Priority
from apps.core.models import Membership, Project
from apps.defects import status
from apps.defects.models import Defect
from apps.files.models import FileState, StoredFile
from apps.files.storage import get_storage
from apps.plans import services as plans
from apps.reports import services as reports
from apps.reports import sharing
from apps.requirements.services import create_requirement
from apps.runs import services as runs
from apps.runs.models import CaseResult, Release


def _png() -> bytes:
    """A valid 1x1 grey PNG, standing in for a screenshot."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    pixels = zlib.compress(bytes([0, 204]))
    signature = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    return signature + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


PNG = _png()


def _days_ago(days: float):
    return timezone.now() - timedelta(days=days)


def _screenshot(project: Project, name: str) -> StoredFile:
    """An available evidence file with its bytes in storage."""
    file_id = uuid.uuid4()
    key = f"{project.org_id}/{project.pk}/{file_id}"
    get_storage().put_bytes(key, PNG)
    return StoredFile.objects.create(
        id=file_id,
        org_id=project.org_id,
        project=project,
        kind="evidence",
        original_name=name,
        storage_key=key,
        declared_mime="image/png",
        detected_type="png",
        size_bytes=len(PNG),
        sha256=hashlib.sha256(PNG).hexdigest(),
        state=FileState.AVAILABLE,
        available_at=timezone.now(),
    )


def _plan(project, lead, title, cases):
    """`cases` is a list of (title, steps, expected, [requirements]). Returns the version."""
    plan = plans.create_plan(project, lead, title=title)
    for case_title, steps, expected, requirements in cases:
        plans.add_case(
            plans.draft_of(plan),
            lead,
            title=case_title,
            steps=steps,
            expected=expected,
            requirements=requirements,
        )
    return plans.approve(plans.draft_of(plan), lead)


def _run(release, version, tester, outcomes, build):
    run = runs.start_run(release, version, tester, build=build, environment="staging")
    results = list(CaseResult.objects.filter(run=run).order_by("created_at"))
    for result, outcome in zip(results, outcomes, strict=True):
        runs.record_result(result, tester, outcome)
    return results


def _fixed(defect, dev, days_ago: float) -> Defect:
    defect = status.set_tracker_status(defect, dev, "fixed")
    Defect.objects.filter(pk=defect.pk).update(
        fixed_at=_days_ago(days_ago), created_at=_days_ago(days_ago + 2)
    )
    defect.refresh_from_db()
    return defect


def seed_hube(project: Project, lead, tester, dev) -> bool:
    """Release 2.4.1, not ready yet: two fixes waiting for a retest, one closed with a failed
    retest, one failure nobody filed, one critical requirement without tests, one stale test."""
    if Release.objects.filter(project=project, name="2.4.1").exists():
        return False
    req = {
        title: create_requirement(project, lead, title=title, text=text, priority=priority)
        for title, text, priority in [
            ("Guest checkout", "A visitor can buy without creating an account.", Priority.HIGH),
            ("Card payment", "Customers can pay by debit or credit card.", Priority.CRITICAL),
            (
                "Discount codes",
                "A valid code reduces the cart total before payment.",
                Priority.MEDIUM,
            ),
            (
                "Emptying the cart",
                "Customers can remove every item from the cart.",
                Priority.MEDIUM,
            ),
            ("Order history", "Signed-in customers can see their past orders.", Priority.LOW),
            (
                "Saved addresses",
                "A saved delivery address is offered at checkout.",
                Priority.MEDIUM,
            ),
            (
                "Refunds go back to the original card",
                "A refund is paid to the card used.",
                Priority.CRITICAL,
            ),
        ]
    }
    checkout = _plan(
        project,
        lead,
        "Checkout",
        [
            (
                "Guest user completes checkout",
                ["Add an item", "Check out as a guest", "Pay"],
                "The order is confirmed.",
                [req["Guest checkout"]],
            ),
            (
                "Customer pays by card",
                ["Add an item", "Pay with [valid card number]"],
                "Payment succeeds within 10 seconds.",
                [req["Card payment"]],
            ),
            (
                "Declined card shows a clear message",
                ["Pay with [declined card number]"],
                "A message says the card was declined.",
                [req["Card payment"]],
            ),
            (
                "Saved address is offered at checkout",
                ["Sign in", "Go to checkout"],
                "The saved address is preselected.",
                [req["Saved addresses"]],
            ),
        ],
    )
    cart = _plan(
        project,
        lead,
        "Cart",
        [
            (
                "Discount code reduces the total",
                ["Add an item", "Enter [valid code]"],
                "The total drops by the discount.",
                [req["Discount codes"]],
            ),
            (
                "Cart can be emptied",
                ["Add two items", "Remove both"],
                "The cart is empty and the app stays open.",
                [req["Emptying the cart"]],
            ),
        ],
    )
    account = _plan(
        project,
        lead,
        "Account",
        [
            (
                "Order history lists past orders",
                ["Sign in", "Open Orders"],
                "Past orders are listed, newest first.",
                [req["Order history"]],
            ),
            (
                "Order history is empty for a new account",
                ["Sign up", "Open Orders"],
                "An empty state is shown.",
                [req["Order history"]],
            ),
        ],
    )

    release = runs.create_release(
        project, lead, name="2.4.1", target_date=timezone.now().date() + timedelta(days=3)
    )
    guest, pays, _declined, address = _run(
        release, checkout, tester, ["passed", "failed", "passed", "failed"], "2.4.1-rc2"
    )
    discount, empties = _run(release, cart, tester, ["failed", "failed"], "2.4.1-rc2")
    _run(release, account, tester, ["passed", "passed"], "2.4.1-rc2")

    # The guest checkout case last ran six weeks ago: stale.
    CaseResult.objects.filter(pk=guest.pk).update(recorded_at=_days_ago(42))
    # The saved-address failure was recorded yesterday; nobody has filed it or attached evidence.
    CaseResult.objects.filter(pk=address.pk).update(recorded_at=_days_ago(1))

    def filed(result, title, severity, actual):
        runs.attach_evidence(
            project, tester, [_screenshot(project, "failure.png").pk], [("case_result", result.pk)]
        )
        return status.create_defect(
            project,
            tester,
            title=title,
            steps="Follow the steps of the test case.",
            expected=result.case_revision.expected,
            actual=actual,
            severity=severity,
            owner=tester,
            release=release,
            found_in_result=result,
            evidence_file_ids=[_screenshot(project, "defect.png").pk],
        )

    _fixed(
        filed(
            pays,
            "Payment times out on card checkout",
            Priority.HIGH,
            "The spinner runs for 60 seconds, then an error.",
        ),
        dev,
        5,
    )
    _fixed(
        filed(empties, "App crashes when the cart is emptied", Priority.HIGH, "The app closes."),
        dev,
        2,
    )

    broken = _fixed(
        filed(
            discount,
            "Cart total ignores discount code",
            Priority.MEDIUM,
            "The total does not change.",
        ),
        dev,
        3,
    )
    status.record_retest(
        broken,
        tester,
        outcome="failed",
        evidence_file_ids=[_screenshot(project, "retest.png").pk],
        build="2.4.1-rc3",
    )
    broken.refresh_from_db()
    broken = status.set_tracker_status(broken, dev, "closed")  # closed in the tracker anyway
    Defect.objects.filter(pk=broken.pk).update(closed_at=_days_ago(1))
    return True


def seed_kola(project: Project, lead, tester, dev) -> str | None:
    """Release 5.0.0, signed off while not ready (so there is a frozen report, a PDF and a
    share link to look at), and 5.1.0 with a run in progress. Returns the share link's token,
    which can only be shown now, or None if the records were already there."""
    if Release.objects.filter(project=project, name="5.0.0").exists():
        return None
    transfers = create_requirement(
        project,
        lead,
        title="Transfers between own accounts",
        text="A customer can move money between their accounts.",
        priority=Priority.HIGH,
    )
    receipts = create_requirement(
        project,
        lead,
        title="Transfer receipts",
        text="A receipt shows the amount in the account's currency.",
        priority=Priority.MEDIUM,
    )
    idle = create_requirement(
        project,
        lead,
        title="Session ends after 5 minutes idle",
        text="An idle session is signed out after 5 minutes.",
        priority=Priority.MEDIUM,
    )
    version = _plan(
        project,
        lead,
        "Transfers",
        [
            (
                "Transfer between own accounts",
                ["Sign in", "Transfer [amount]"],
                "Both balances update.",
                [transfers],
            ),
            (
                "Receipt shows the right currency",
                ["Make a transfer", "Open the receipt"],
                "The currency symbol matches the account.",
                [receipts],
            ),
        ],
    )
    release = runs.create_release(
        project, lead, name="5.0.0", target_date=timezone.now().date() + timedelta(days=12)
    )
    _, receipt = _run(release, version, tester, ["passed", "failed"], "5.0.0-beta1")
    runs.attach_evidence(
        project, tester, [_screenshot(project, "receipt.png").pk], [("case_result", receipt.pk)]
    )
    defect = status.create_defect(
        project,
        tester,
        title="Transfer receipt shows the wrong currency symbol",
        severity=Priority.MEDIUM,
        owner=tester,
        release=release,
        found_in_result=receipt,
    )
    _fixed(defect, dev, 1)
    reports.sign_off(
        release,
        Membership.objects.select_related("user").get(user=lead),
        "Kola accepted the open receipt defect in writing.",
    )
    _, token = sharing.create_link(release, lead)

    upcoming = runs.create_release(project, lead, name="5.1.0")
    in_progress = runs.start_run(
        upcoming, version, tester, build="5.1.0-beta1", environment="staging"
    )
    first = CaseResult.objects.filter(run=in_progress).order_by("created_at").first()
    runs.record_result(first, tester, "passed")
    _seed_plan_history(project, lead, tester)
    _seed_source(project, tester)
    # Cases for the one requirement nothing covers are drafted by AI and left for review, so the
    # case review screen has something to show (M3-08). The job runs when the seed commits.
    from apps.plans import drafting

    drafting.queue_case_drafting(version.plan, tester, [idle])
    return token


def _seed_plan_history(project: Project, lead, tester) -> None:
    """A plan with two published versions and an open draft, so the version history, the diff
    and roll back have something to show (M3-06, M3-07)."""
    plan = plans.create_plan(project, lead, title="Sign-in", scope="Signing in and out.")
    first = plans.add_case(
        plans.draft_of(plan),
        lead,
        title="Signs in with a password",
        steps=["Open the app", "Enter [valid email]", "Enter [valid password]", "Press Sign in"],
        expected="The accounts screen opens.",
    )
    plans.add_case(
        plans.draft_of(plan),
        lead,
        title="Wrong password is refused",
        steps=["Open the app", "Enter [valid email]", "Enter [wrong password]", "Press Sign in"],
        expected="An error says the details are wrong. Nothing says which one.",
    )
    plans.approve(plans.draft_of(plan), lead)

    draft = plans.open_draft(plan, tester)
    plans.edit_case(
        draft,
        first.test_case,
        tester,
        steps=["Open the app", "Press Sign in", "Enter [valid email]", "Enter [valid password]"],
        expected="The accounts screen opens within 2 seconds.",
    )
    plans.add_case(
        draft,
        tester,
        title="Signs out from the menu",
        steps=["Sign in", "Open the menu", "Press Sign out"],
        expected="The sign-in screen opens.",
    )
    plans.approve(draft, lead)

    draft = plans.open_draft(plan, tester)
    plans.add_case(
        draft,
        tester,
        title="Three wrong passwords lock the account",
        steps=["Enter [wrong password] three times"],
        expected="The account is locked for 15 minutes.",
        priority=Priority.HIGH,
    )
    plans.submit(draft, tester)


def seed_small(project: Project, lead) -> bool:
    """A minimal passing release, for the second organisation."""
    if Release.objects.filter(project=project, name="1.0").exists():
        return False
    requirement = create_requirement(
        project, lead, title="Launch checklist", text="The launch checklist is complete."
    )
    version = _plan(
        project,
        lead,
        "Launch",
        [("Checklist is complete", ["Open the checklist"], "Every item is ticked.", [requirement])],
    )
    release = runs.create_release(project, lead, name="1.0")
    _run(release, version, lead, ["passed"], "1.0.0")
    return True


SAMPLE_PRD = """# Scheduled transfers

A customer can schedule a transfer for a future date.
A scheduled transfer must be cancellable until midnight before it runs.
The scheduling screen should feel fast on older phones.

# Limits

A single transfer cannot be more than the account's daily limit.
A customer will see the remaining daily limit before confirming a transfer.
"""


def _seed_source(project: Project, tester) -> None:
    """A pasted PRD, so the Sources and draft review screens have something to show (M2-01,
    M2-06, M2-07). Its requirements are drafted by the job this queues, which runs when the
    seed's transaction commits (inline locally, on a worker elsewhere)."""
    from apps.sources import services as sources

    sources.create_from_text(project, tester, title="Scheduled transfers PRD", text=SAMPLE_PRD)
