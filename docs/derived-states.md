# Derived states, readiness and coverage

How the Inbox, the project dashboard and the release page get their numbers (DATA §9, TASKS M6-01, M6-03, M8-01 to M8-03). Nothing here is typed in by hand: every state is computed from stored rows each time a page loads, so it cannot drift from the records or be faked.

Tests: `api/apps/inbox/tests/`, `api/apps/reports/tests/`, `api/apps/defects/tests/`.

## Where each thing is computed

| Thing | Code | Used by |
| --- | --- | --- |
| The seven derived states | `apps/inbox/derived.py`, one function per state | Inbox, dashboard "open work", facts |
| Who sees an Inbox item, and snoozes | `apps/inbox/services.py` | `GET /api/inbox/` |
| Readiness, blockers, verified coverage | `apps/reports/facts.py::build_facts(release)` | Release page, dashboard, report, sign-off |
| The report text | `apps/reports/services.py::report_body(facts)` | Release page, sign-off |
| Defect statuses | `apps/defects/status.py` (the only writer) | Everything above |

`build_facts` is the one function that says what is true about a release. The readiness panel, the dashboard and the report all read from it, so they cannot disagree. When the AI-drafted report (F5) arrives it replaces how the report is worded, not what it is built from.

## The states

| State | Applies to | Condition | Inbox group | Who sees it |
| --- | --- | --- | --- | --- |
| Needs retest | Defect | Tracker status fixed or closed, QA status not retested | Fixed but not retested | Its owner at once. Leads, admins and owners after the second escalation time (96 hours by default) |
| Closed with a failed retest | Defect | Tracker status closed, QA status retest failed | Closed with a failed retest (critical, shown first) | Owner, leads, admins, owners |
| Aging | Defect | Open or in progress for longer than its severity allows (critical 2 days, high 7, medium 14, low 30) | Ageing defects | Owner, leads, admins, owners |
| Unfiled failure | Case result | Outcome failed and no defect points at it | Failures without a defect | Whoever recorded the result |
| Missing evidence | Case result | Outcome failed and no evidence linked | Missing evidence | Whoever recorded the result |
| Stale | Test case in a plan's current version | No passed or failed result in 30 days, or a linked requirement's text changed since the case was written | Stale tests | QA engineers, leads, admins, owners |
| Uncovered | Accepted requirement | No accepted case in any plan's current version links to it | Requirements without tests | Leads, admins, owners |

The thresholds are per project (`apps/core/project_settings.py`): `stale_after_days`, `retest_escalation_hours`, `aging_days`.

Only accepted records count. Drafts (including anything AI wrote that nobody has accepted) are ignored everywhere.

An item's ID in the API is `{type}.{uuid}`, for example `defect.7f3c…`. A failed result with neither a defect nor evidence appears in two groups under the same ID.

## Snoozing

A snooze hides one record from one person's Inbox until a date, with a reason (FR-INB-04). It is personal and it never affects readiness: a snoozed blocker still blocks. You can snooze any record in a project you can see; anything else is "not found". Removing a snooze soft-deletes the row, so the history stays, and every snooze is in the audit log.

## Readiness

A release is **Not ready yet** if any of these exist for it, otherwise **Ready**:

| Blocker | Condition |
| --- | --- |
| Closed with a failed retest | As above, for a defect of this release |
| Open critical defect | Severity critical, tracker status open or in progress, not verified, won't fix or deferred |
| Fixed but not retested | Needs retest, as above |
| Failure without a defect | A failed result in the release's latest runs with no defect filed |
| Critical requirement without tests | An uncovered requirement of critical priority |

A defect belongs to a release if its `release` is set to it, or it was found in one of the release's runs. "Latest runs" means the newest run of each plan in the release.

## Verified coverage

A requirement is verified for a release when every accepted case linked to it passed in the release's latest runs, and every defect found against those cases is Verified, Won't fix or Deferred.

Verified coverage = verified requirements ÷ accepted requirements in the project.

The other requirements are split for display: **failed** (a linked case failed, or a defect's retest failed), **on hold** (a case is blocked, or everything passed but a defect is still waiting for its retest) and **not run** (the rest, including requirements with no cases).

## Sign-off and the frozen report

- The draft report is computed each time the release is read. Nothing is stored, so a draft has no RPT number.
- Signing off recomputes the facts inside the transaction, checks the person's role again, and requires a written reason when the release is not ready. It then stores the report once, already signed, with an RPT number.
- The database refuses any later change to a signed report, and sign-offs are append-only. Readiness on the page stays live; the report and the sign-off record show what was true at signing.

## Performance note

These are ORM queries, not database views (M6-01 says views). They are simple and tested; if the Inbox becomes slow on large projects, the functions in `apps/inbox/derived.py` can be replaced by views without changing their callers.
