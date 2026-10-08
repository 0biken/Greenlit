# Greenlit Data Model and Traceability Spec

Oct 4, 2026 · @Seyi Ezekiel

## Overview

This spec fixes the objects Greenlit stores, how they link, and which system owns each field. Traceability is Greenlit's core, so these rules must hold before any feature is built on top of them.

It implements PRD v2 sections 6, 7 and 9. Where the two disagree, the PRD states what the product does and this spec states how the data holds it.

**Conventions**

- Field types are database-neutral: `uuid`, `text`, `int`, `enum`, `timestamp` (UTC), `json`, `ref` (foreign key).
- Every table has `id` (uuid), `org_id`, `created_at`, `created_by`, `updated_at`. These are not repeated in the field tables.
- Records are never hard-deleted in normal use; they get `deleted_at` and are hidden.
- A field marked *proposed* is a suggestion for the engineer to confirm.

## Entity map

The spine runs from requirement to case revision to result to defect. Account, link and system tables are left out of the picture and listed in section 3.

*Text version; the original diagram was lost when this document was exported. Reconstructed from the rest of the specs, so check it against the source diagram.*

```
source_document ─▶ requirement ◀─(case_requirement)─▶ case_revision ─▶ test_case
                                                          ▲
test_plan ─▶ plan_version ─(plan_version_case)────────────┘
                  ▲
release ─▶ test_run ─▶ case_result ─▶ case_revision
   │                       ▲
   ├─▶ defect ─(found_in_result_id)
   │      └─▶ retest
   └─▶ report ◀── sign_off ──▶ release

evidence ◀─(evidence_link)─▶ case_result | test_run | defect | retest
```

Each case result also points at the exact case revision it tested, which is how a past run stays accurate after the plan changes.

## Entities and fields

There are 30 tables: 28 listed here in seven groups, the requirement-to-case link in section 5 and the ID counter in section 4. Test cases are split into a stable identity (`test_case`) and immutable content snapshots (`case_revision`), which lets versioning and run history work without copying whole plans.

**Account**

| Table | Key fields | Rules |
| --- | --- | --- |
| organisation | name, slug, plan\_tier, ai\_allowance | Root of every tenant; `org_id` on its own row equals `id` |
| user | email, name, auth\_provider | Global; not scoped to one organisation |
| membership | user\_id, role (enum: owner, admin, qa\_lead, qa\_engineer, developer, viewer), status | One row per user per organisation |
| project | name, client\_name, key (text, 2 to 6 letters), settings (json) | `key` is unique in the organisation; `settings` holds the per-project thresholds in section 9 and is validated against fixed defaults |
| project\_member | project\_id, user\_id | Who sees a project; owners and admins see all |
| invitation | email, role, token\_hash, expires\_at, accepted\_at, revoked\_at, invited\_by | Only a hash of the emailed token is stored; a new invitation to the same address revokes the earlier one; the holder of a token can read that one row before joining (section 8) |

**Requirements**

| Table | Key fields | Rules |
| --- | --- | --- |
| source\_document | project\_id, kind (enum: prd, screenshot\_set, qa\_report), file\_ref, page\_count | The uploaded file, kept as evidence of origin |
| requirement | project\_id, display\_no, title, text, priority, revision (int), source\_document\_id, source\_locator (json), review\_state, origin | `revision` goes up when `text` changes; `source_locator` holds page and passage, or image region |

**Plans**

| Table | Key fields | Rules |
| --- | --- | --- |
| test\_plan | project\_id, display\_no, title, scope, current\_version\_id | One plan per release or feature area |
| plan\_version | plan\_id, number (e.g. 1.0, 1.1), state (enum: draft, published, superseded), approved\_by, approved\_at | Only one draft per plan at a time; published rows never change |
| test\_case | project\_id, display\_no, retired\_at | Identity only; content lives in revisions |
| case\_revision | test\_case\_id, rev\_no, title, preconditions, steps (json list), expected, priority, review\_state, origin | Immutable once its plan version is published |
| plan\_version\_case | plan\_version\_id, case\_revision\_id, position | Which revisions make up a version |

**Execution**

| Table | Key fields | Rules |
| --- | --- | --- |
| release | project\_id, name (e.g. 2.4.1), target\_date, state (enum: open, signed\_off, cancelled) | Groups runs, defects and the report |
| test\_run | project\_id, display\_no, release\_id, plan\_version\_id, build, environment, state (enum: in\_progress, complete) | Fixed to one plan version for life |
| case\_result | run\_id, case\_revision\_id, outcome (enum: passed, failed, blocked, not\_run), note, recorded\_by, recorded\_at | One row per case per run; latest write wins, history in audit log |
| evidence | project\_id, display\_no, file\_ref, mime, size\_bytes, sha256, environment, captured\_at | File metadata; files live in object storage |
| evidence\_link | evidence\_id, target\_type, target\_id | One file can support several results, defects or retests |

**Defects**

| Table | Key fields | Rules |
| --- | --- | --- |
| defect | project\_id, display\_no, title, steps, expected, actual, severity (enum: critical, high, medium, low), tracker\_status, qa\_status, owner\_id, fixed\_at, found\_in\_result\_id, review\_state, origin | Two statuses kept apart (see section 7) |
| retest | defect\_id, outcome (enum: passed, failed), tested\_by, tested\_at, build, environment | Evidence required for both outcomes; each retest is a row, never overwritten |

**Reporting**

| Table | Key fields | Rules |
| --- | --- | --- |
| report | release\_id, display\_no, body (json), state (enum: draft, signed), snapshot\_at | Signed reports are frozen copies, never recomputed |
| sign\_off | release\_id, report\_id, signed\_by, signed\_at, readiness\_at\_signing (enum: ready, not\_ready), override\_reason | Reason is required when readiness was not\_ready |

**System**

| Table | Key fields | Rules |
| --- | --- | --- |
| snooze | user\_id, target\_type, target\_id, until, reason | Hides one Inbox item for one user until a date |
| audit\_event | actor\_id, action, target\_type, target\_id, before (json), after (json), at | Append-only (section 10) |
| external\_ref | target\_type, target\_id, provider (enum: jira, github, figma), external\_key, external\_url, last\_synced\_at | Unused in v1; ready for phase 2 sync |
| stored\_file | project\_id, kind (enum: prd, screenshot, qa\_report, evidence), original\_name, storage\_key, declared\_mime, detected\_mime, size\_bytes, sha256, state (enum: pending, scanning, available, rejected, infected), uploaded\_by | One row per uploaded file; the key is `{org_id}/{project_id}/{uuid}`; `source_document.file_ref` and `evidence.file_ref` point here; a file is not served until `available` |
| job | kind, args (json), state (enum: queued, running, succeeded, failed, dead), progress (json), error, attempts, created\_by, started\_at, finished\_at | Background work for one organisation; `args` hold IDs only, never document text; `error` holds an error class and IDs, never content |
| org\_registry | org\_id | Not tenant data: only organisation IDs, so schedulers can run a job once per organisation without a scope. Kept in step with `organisation` by a trigger |

Objects AI can draft (requirement, case\_revision, defect) carry `origin` (enum: human, ai) and `review_state` (enum: draft, accepted, rejected). Only accepted rows count anywhere in coverage, readiness or reports.

## IDs

Every record has two IDs: an internal `uuid` that never appears in the interface, and a short display ID that people type, say and search for.

| Object | Display format | Example | Counter scope |
| --- | --- | --- | --- |
| Requirement | REQ-n | REQ-102 | Per project |
| Test plan | TP-n | TP-3 | Per project |
| Test case | TC-nnnn | TC-0042 | Per project |
| Test run | RUN-n | RUN-019 | Per project |
| Evidence | EV-nnnn | EV-0310 | Per project |
| Defect | BUG-n | BUG-1042 | Per project |
| Report | RPT-n | RPT-008 | Per project |
| Plan version | major.minor | 1.4 | Per plan |

**Rules**

1. Display numbers come from a per-project counter table (`project_counter`: project\_id, kind, next\_no), incremented in the same transaction as the insert, so numbers never repeat.
2. Numbers are never reused, even after deletion. A gap in the sequence is normal.
3. Where a display ID can appear outside its project (reports, email, links), it is shown with the project key: `HUBE-BUG-1042`.
4. Plan versions: approving a draft makes the next minor number (1.3 to 1.4). A QA lead can choose a major bump (1.4 to 2.0) for a release-level rewrite.
5. URLs use the display ID (`/hube/bugs/1042`); APIs accept either form.

## Traceability links

One link table carries the many-to-many relationship between requirements and test cases. Every other link in the trace chain is a plain foreign key, so any record can be traced back to its requirement in a fixed number of joins.

**The link table**

| Table | Fields | Rules |
| --- | --- | --- |
| case\_requirement | case\_revision\_id, requirement\_id, req\_revision\_seen | Written when a case revision is saved; `req_revision_seen` records which requirement text the case was written against |

**How everything connects**

| From | To | Cardinality | Held by |
| --- | --- | --- | --- |
| Requirement | Case revision | many to many | case\_requirement |
| Case revision | Test case | many to one | case\_revision.test\_case\_id |
| Plan version | Case revision | many to many | plan\_version\_case |
| Test run | Plan version | many to one | test\_run.plan\_version\_id |
| Case result | Test run, case revision | many to one each | case\_result |
| Defect | Case result where it was found | many to one, optional | defect.found\_in\_result\_id |
| Retest | Defect | many to one | retest.defect\_id |
| Evidence | Result, defect, retest, run | many to many | evidence\_link |
| Release | Runs, defects, report | one to many | release\_id on each |
| Sign-off | Release, report | many to one each | sign\_off |

**Questions the links must answer in one query**

- Which accepted test cases cover REQ-102, and did they pass in the latest run of this release?
- Which test cases are affected now that REQ-102 has changed? (`req_revision_seen` lower than the requirement's current `revision`.)
- For BUG-1042: which requirement it threatens, which run found it, every retest, and the evidence for each.
- For release 2.4.1: every requirement, its tests, their results, open defects and the sign-off, as one report.

A defect's link to a requirement is derived through the case result where it was found. Defects logged outside a run (for example from an imported report) can be linked to requirements by hand in phase 2.

## Versioning

Published plan versions and their case revisions never change. Every edit happens in a draft version, and approving the draft publishes it as the next version.

**Lifecycle of a plan version**

1. Editing a published plan opens a draft version that starts as a copy of the current version's `plan_version_case` rows (pointers only, no content copied).
2. Editing a case inside the draft creates a new `case_revision` (rev\_no + 1) and swaps the draft's pointer to it. Unchanged cases keep pointing at their existing revision.
3. Adding a case creates a `test_case` and its first revision. Removing a case drops the pointer; the case and its history remain.
4. A QA lead approves the draft: it becomes `published`, gets its number, and the previous version becomes `superseded`. `test_plan.current_version_id` moves to it.
5. Discarding a draft deletes the draft version and any revisions that only it used.

**Diff between two versions**

Compare the two sets of `plan_version_case` rows by `test_case_id`:

| Case appears in | Shown as |
| --- | --- |
| New version only | Added |
| Old version only | Removed |
| Both, same revision | Unchanged (hidden by default) |
| Both, different revision | Changed, with a field-by-field diff of title, preconditions, steps, expected and priority |

Steps are compared as an ordered list, so a reordered step shows as moved rather than deleted and re-added.

**Rollback**

Rolling back to version 1.2 creates a new draft whose pointers equal 1.2's, then publishes it as the next number (for example 1.5). History is never rewritten.

**Why runs stay correct**

A test run points at one plan version, and each result points at the exact case revision that was tested. Later edits cannot change what a past run says was tested.

## Source of truth and sync

In v1 Greenlit owns every field, because nothing is synced. The table below fixes ownership now, so that adding Jira in phase 2 does not change the meaning of any field.

| Data | Owner in v1 | Owner once synced (phase 2) | Greenlit's behaviour |
| --- | --- | --- | --- |
| Requirement text | Greenlit | Jira story or PRD | Mirrors it; a change raises `revision` and marks linked cases Stale |
| Test cases and plans | Greenlit | Greenlit | Never written to other tools |
| Case results and runs | Greenlit | Greenlit, with raw automation output attached as evidence | Imports never overwrite a result a person recorded |
| Defect title, steps, severity | Greenlit | Tracker | Mirrors it; shows the tracker's version |
| Defect `tracker_status` | Greenlit | Tracker | Mirrors it; never written back except by an explicit user action |
| Defect `qa_status` | Greenlit | Greenlit | Never sent to the tracker as a status; may be posted as a comment |
| Evidence files | Greenlit | Greenlit | Links to tracker attachments are stored, files are copied only on request |
| Reports and sign-offs | Greenlit | Greenlit | Frozen at signing |

**The two defect statuses**

| tracker\_status | qa\_status | Shown as | Inbox group |
| --- | --- | --- | --- |
| open, in\_progress | not\_retested | Open | Aging defects (after the age threshold) |
| fixed | not\_retested | Needs retest | Needs retest |
| fixed or closed | verified | Verified | None |
| open | retest\_failed | Reopened | Aging defects |
| fixed | retest\_failed | Retest failed, tracker not reopened (phase 2 only; in v1 a failed retest sets `tracker_status` to open) | Aging defects, flagged |
| closed | retest\_failed | Closed, retest failed | Closed with failed retest (critical) |
| closed | not\_retested | Closed, unverified | Needs retest |
| any | wont\_fix or deferred | Won't fix / Deferred | None |

**Transitions Greenlit applies**

1. Setting `tracker_status` to fixed sets `fixed_at` and, if `qa_status` is retest\_failed, resets it to not\_retested.
2. A passed retest sets `qa_status` to verified. A failed retest sets it to retest\_failed and, in v1 only, sets `tracker_status` to open. Both need evidence.
3. Moving `tracker_status` from fixed or closed back to open or in\_progress resets `qa_status` to not\_retested. If `qa_status` was verified, the change is counted as a reopen (the reopen-rate guardrail).
4. wont\_fix and deferred need a reason and an approver with that right; both are written to the audit log.

**Conflict rules for phase 2 sync**

1. Each mirrored field stores the last value received and `last_synced_at`. Incoming changes replace mirrored fields only.
2. If a user edits a mirrored field in Greenlit, the edit is sent to the tracker. If the tracker changed the same field since the last sync, the tracker's value wins and the user is told.
3. A sync failure never changes `qa_status` and is shown on the record and in an admin log.
4. Mapping custom tracker workflows to the four `tracker_status` values is set once per project by an admin.

## Tenancy at the data layer

Every tenant-owned row carries `org_id`, and the database itself refuses to return rows from another organisation. Application code filtering alone is not enough.

1. **One database, shared tables, row-level isolation.** Every table except `user` has a non-null `org_id`. A row-level security policy (or the equivalent in the chosen database) limits every read and write to the organisation set for the current request.
2. **Request scope.** Each request sets the organisation once, after checking the user's `membership`. Queries without that setting fail rather than return everything.
3. **Project scope.** Inside an organisation, access to a project also requires a `project_member` row, unless the user is an owner or admin.
4. **Cross-references stay inside one organisation.** Every foreign key between tenant tables must point to a row with the same `org_id`; this is checked with composite keys or triggers.
5. **Files.** Evidence and source documents are stored under `/{org_id}/{project_id}/` and served only through short-lived signed links (proposed: 15 minutes).
6. **AI context.** Retrieval indexes and prompts are built per organisation. No embedding, cache or prompt ever holds data from two organisations.
7. **Proof.** An automated test suite creates two organisations and checks every API endpoint and file route for leakage between them. It runs on every deploy.

Search, exports and background jobs (reminders, digests, AI drafting) follow the same rules: each job runs inside one organisation's scope.

## Derived states

Inbox items, readiness and coverage are computed from stored rows, never typed in by hand. This keeps them impossible to fake and easy to recompute.

| State | Applies to | Condition | Who sees it |
| --- | --- | --- | --- |
| Needs retest | Defect | `tracker_status` = fixed or closed, and `qa_status` = not\_retested | Owner at once; QA lead after 96 hours (proposed) |
| Closed with failed retest | Defect | `tracker_status` = closed and latest retest failed | QA lead and owner, immediately; critical |
| Aging | Defect | Open longer than its severity limit: critical 2 days, high 7, medium 14, low 30 (proposed) | Owner, then QA lead |
| Stale | Test case | No passed or failed result in the last 30 days (project setting), or any linked requirement's `revision` is above `req_revision_seen` | QA engineers on the project |
| Uncovered | Requirement | Accepted, not deleted, and no accepted case in the plan's current version links to it | QA lead |
| Missing evidence | Case result | Outcome failed, and no evidence linked | The person who recorded it |
| Unfiled failure | Case result | Outcome failed, and no defect has `found_in_result_id` pointing to it | The person who recorded it |

**Release readiness**

A release is **Not ready yet** if any of these exist for it: a defect in Needs retest, an open critical defect, a defect closed with a failed retest, an uncovered requirement of critical priority, or an unfiled failure. Otherwise it is **Ready**. The blockers are listed by type with counts.

**Verified coverage (the North Star)**

A requirement counts as verified for a release when every accepted case linked to it has passed in the release's latest run, and every defect found against those cases is Verified, Won't fix or Deferred.

```latex
\text{Verified coverage} = \frac{\text{requirements verified for the release}}{\text{accepted, non-deleted requirements in the project}}
```

**How it is computed**

In v1 these states are database views or queries run when a page loads. A background job runs every 15 minutes (proposed) and after each relevant change to send reminders and build the daily digest. Snoozed items are left out of the person's Inbox until the snooze ends, but they still count towards readiness.

## Audit log and history

Every change that affects what Greenlit claims about quality is written to `audit_event`, which is append-only. No user, including owners, can edit or delete it through the product.

| Recorded | Examples |
| --- | --- |
| Approvals | Plan version approved; AI draft accepted or rejected |
| Status changes | Defect `tracker_status` or `qa_status` changed; retest recorded |
| Results | Case result recorded or changed, with old and new outcome |
| Sign-off | Release signed off, readiness at that moment, override reason |
| Access | Member invited, role changed, member removed |
| Data movement | Organisation export, file downloaded through a share link |

**Rules**

- `before` and `after` hold only the changed fields, not whole records.
- Events are kept for the life of the organisation, and exported with it (proposed).
- AI actions are logged with the model name and the IDs of the source records it read, not the full prompt.
- Ordinary edits to text fields (a typo in a step) are covered by case revisions and are not duplicated in the log.

## Open questions

- [ ] Release scope: should a release list its own requirements (a `release_requirement` table), instead of counting every requirement in the project?
- [ ] Can one test case belong to several plans, or does each plan own its cases? This spec assumes cases belong to the project and plans point to them.
- [x] Database choice: resolved. The architecture doc fixes PostgreSQL 16 or later with row-level security (decision record 004).
- [ ] Do the aging limits per severity and the 30-day stale window match how real teams work? Check in phase 0 interviews.
- [ ] How long are evidence files kept after a project is archived, and who pays for storage over the plan limit?
- [ ] Should a defect be linkable directly to a requirement in v1, for defects found outside a run?
