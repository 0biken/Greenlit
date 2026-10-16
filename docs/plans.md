# Requirements, test plans and cases

How requirements and plans are written, changed and compared (FR-PLAN-05, FR-PLAN-06, FR-TC-01 to FR-TC-05; DATA "Versioning"; TASKS M2-08, M3-02 to M3-10). Code: `api/apps/requirements/`, `api/apps/plans/`. Tests: `api/apps/requirements/tests/`, `api/apps/plans/tests/`.

## Requirements

| Call | Who |
| --- | --- |
| `GET /api/projects/{key}/requirements/` (`q`, `priority`, `coverage`) | Anyone on the project |
| `POST /api/projects/{key}/requirements/` | Owners, admins, QA leads, QA engineers |
| `GET /api/projects/{key}/requirements/{id}/` | Anyone on the project |
| `PATCH /api/projects/{key}/requirements/{id}/` | Owners, admins, QA leads, QA engineers |

- `{id}` is the number, `REQ-n` or the uuid.
- A requirement is **covered** when an accepted case in some plan's current version links to it.
- **Changing the text raises `revision`.** Every case linked at the old revision is then Stale, until someone saves that case in a draft (see below). Changing the title or priority does not.
- **Old text is kept** in `requirement_revision`, one row per revision (spec gap G-07). The audit log records that the text changed and the revision numbers, never the text.
- Requirements made before this table existed have no rows for their earlier revisions; their current text is recorded the first time it changes.

## Plans and versions

A plan has at most one **draft** and any number of published versions, of which the newest is **current** and the rest **superseded**. Published versions and the case revisions they use never change: the database refuses it (`plans` migration 0003).

| Call (under `/api/projects/{key}/plans/`) | Who | Does |
| --- | --- | --- |
| `GET`, `POST` (list, create) | Anyone / testers | A new plan starts as an empty draft |
| `GET {id}/` | Anyone | Versions, the draft, and requirements with no test cases (FR-PLAN-06) |
| `GET {id}/versions/{number}/` | Anyone | The cases of one version in order. `draft` names the draft |
| `POST {id}/draft/` | Testers | Opens a draft that points at the current version's revisions. If a draft is already open, answers with it |
| `DELETE {id}/draft/` | Testers | Discards the draft and the revisions and new cases only it used |
| `POST {id}/draft/cases/` | Testers | Adds a case |
| `PATCH`, `DELETE {id}/draft/cases/{case}/` | Testers | Edits or moves (`position`) a case, or takes it out of the draft |
| `POST {id}/draft/submit/` | Testers | Hands the draft to a lead |
| `POST {id}/draft/approve/` | Owners, admins, QA leads | Publishes it as the next minor number, or `{"major": true}` for the next major |
| `GET {id}/diff/?from=&to=` | Anyone | What changed between two versions |
| `POST {id}/versions/{number}/roll-back/` | Owners, admins, QA leads | Publishes a new version with that version's cases |

"Testers" are owners, admins, QA leads and QA engineers.

## What an edit does

- A case's content is a **revision**. A revision that a published version or a run uses is never touched: editing that case in a draft makes revision n+1 and points the draft at it.
- A revision made in the current draft, which nothing else uses, is changed in place, so ten saves do not make ten revisions.
- **Saving a case records that it was written against each linked requirement's current text.** That is how Stale is cleared: open the draft, check the case against the new text, save, and have the draft approved.
- Removing a case from a draft drops the pointer only. The case and its history remain.
- Any change to a draft withdraws its submission.

## Diff

Two versions are matched case by case. A case in both that points at different revisions is compared field by field; its steps are compared as an ordered list, and a step that only changed place is reported as **moved**. Unchanged cases are counted and listed only with `unchanged=1`. Without `from` and `to`, the draft is compared with the current version, or the current version with the one before.

## Roll back

Rolling back to 1.2 publishes a new version (say 1.5) with 1.2's cases. Nothing is rewritten. It is refused while the plan has a draft: approve or discard the draft first.

## Cases

`GET /api/projects/{key}/cases/{id}/` shows what a tester would run today (the published revision), the plans the case is in, its revisions and its last ten results. Cases are edited inside a plan's draft, not on their own page.

## Cases drafted by AI

A tester can have cases drafted for accepted requirements (FR-PLAN-03; AI §3 F2; TASKS M3-08). Code: `api/apps/plans/drafting.py`, `web/src/features/plans/CaseDrafts.tsx`.

| Call (under `/api/projects/{key}/plans/{id}/`) | Who | Does |
| --- | --- | --- |
| `GET case-drafts/` | Anyone | The drafted cases with the requirements each covers, the gaps list, how many were left out, job progress |
| `POST case-drafts/` | Testers | `{requirements?: [numbers]}`. Without it, drafts for every accepted requirement no accepted case covers (up to 50) |
| `PATCH case-drafts/{case}/` | Testers | Edit a draft; it stays a draft |
| `POST case-drafts/{case}/review/` | Testers | `{decision: accepted or rejected, reason?, viewed_ms?}` |
| `POST case-drafts/accept/` | Testers | Accept up to 20 at once |

- **A drafted case is in no plan version.** It is a real case with one revision in `review_state = draft`, and nothing points at it. Runs, coverage, stale checks and readiness all read a version's cases, so a draft counts nowhere and its case page answers "not found".
- **Accepting adds it to the plan's draft**, last in the order, opening a draft if the plan has none. From there it is submitted and approved like any other change.
- **Rejecting** keeps the case and its number for quality review. Its requirement can be drafted for again.
- Drafting again skips a requirement that still has an undecided draft on this plan.
- The review screen at `/{project}/plans/{n}/drafts` uses the same keys as requirement review (`A`, `R`, `Enter`, `J`, `K`), with the requirement the case covers shown beside it.

## Limits today

- The plan page starts drafting for every uncovered requirement at once; choosing requirements one by one is in the API but has no screen yet.

- Approval is recorded on the plan page; there is no notification to leads when a draft is submitted.
- Two people editing the same draft at once overwrite each other case by case: the last save wins.
- A case belongs to the plan it was added to. There is no screen to add an existing case to a second plan.
