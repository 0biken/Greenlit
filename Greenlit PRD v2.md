# Greenlit PRD v2

Oct 4, 2026 · @Seyi Ezekiel

## Overview

Greenlit is the QA record that links requirements, tests, evidence and defects, and shows what is still open before a release ships. This PRD defines version 1 (the MVP) in enough detail to build. It replaces the strategy PRD and folds in the audit, the SWOT and the accountability-layer decisions.

| Item | Detail |
| --- | --- |
| Product | Greenlit |
| Founder | Obioma Ezeocha |
| Document state | Draft for review |
| Replaces | PRD v1 (strategy memo) |
| Companion documents | Brand guidelines v2.0 (done; not in this folder, only the logo pack is); Data Model and Traceability Spec, AI Behaviour Spec, Security and Tenancy Design, Technical Architecture, UX Flows and Wireframes (drafts written) |

Sections 5 to 7 are what engineering builds. Requirement IDs such as FR-INB-02 are stable, so tickets and tests can reference them. Figures marked *proposed* are targets to confirm, not measured facts.

## Problem

QA teams lose track of what was tested, fixed and verified, because the work is spread across spreadsheets, Word files, Jira, Figma, screenshots and chat. Two things go wrong.

**The record drifts.** Test plans fall out of date when the product changes, evidence sits in folders and WhatsApp threads, and a final report takes hours to assemble by hand. Nobody can quickly answer which tests cover a requirement, or what changed between plan versions.

**Work falls through silently.** Issue trackers record tickets but do not check that QA closed the loop.

| What happens | Result |
| --- | --- |
| Bug found, never filed | Lost in a screenshot folder |
| Bug fixed, never retested | Nobody confirms the fix works |
| Ticket closed after a failed retest | A known bug ships |
| Test case exists, never run | Coverage figures are wrong |
| Run recorded with no evidence | The result cannot be checked later |
| Requirement changed, tests not updated | Tests check old behaviour |

This hurts most for QA engineers and agencies testing several client products at once, who must answer to each client for what shipped.

These problems come from the founder's own experience and have not yet been tested with other teams. Validation interviews (section 10, phase 0) must confirm them before the build starts.

## Goals, non-goals and success metrics

Version 1 succeeds if a QA team can run one real release through Greenlit, from PRD to sign-off, and can see nothing left untested, unretested or unclosed.

**Goals for v1**

1. Turn a PRD into a reviewed, versioned test plan in one sitting.
2. Keep every defect's QA verification separate from its tracker status, and flag where the two disagree.
3. Put every open item (unretested fix, stale test, uncovered requirement, run without evidence) in one QA Inbox.
4. Produce a release report that a client can read, with a named sign-off.

**Non-goals for v1**

- Running tests. Testing happens in the team's own tools or by hand.
- Replacing Jira or any issue tracker.
- Sprint planning or developer task management.
- Integrations beyond file and screenshot upload (Jira, Figma and GitHub come in phase 2).

**Metrics**

| Type | Metric | Definition | Target (proposed) |
| --- | --- | --- | --- |
| North Star | Verified coverage | Share of in-scope requirements whose linked tests passed and whose defects are verified with evidence | Tracked per release; no target until baseline |
| Supporting | Retest lag | Median time from Fixed to Verified | Under 2 working days |
| Supporting | Escaped closures | Defects closed in the tracker without QA verification | 0 per release |
| Supporting | Time to first plan | PRD upload to an approved test plan | Under 1 hour |
| Supporting | AI draft acceptance | Share of AI-drafted test cases kept after review | Baseline in beta |
| Supporting | Weekly active QA users | Users who record a run, retest or sign-off in a week | Baseline in beta |
| Guardrail | Reminder action rate | Reminders acted on within 72 hours | At least 40% |
| Guardrail | Reopen rate | Verified defects later reopened | Under 5% |

## Users

The first customers are QA agencies and freelance QA engineers testing three or more client products at once. Greenlit's own founding team is customer zero: the first real release goes through Greenlit before any outside team uses it.

| Persona | Role in Greenlit | Main job to be done |
| --- | --- | --- |
| QA engineer | Daily user: writes cases, records runs, attaches evidence, retests fixes | "Show me what I still need to test or retest today." |
| QA lead | Approves plans, owns release readiness, signs off | "Tell me if this release is safe to ship, with proof I can show the client." |
| Agency lead | Sees all client projects, sends reports | "Show each client what was tested without hours of report writing." |
| Developer | Reads tests and defects linked to their work, marks fixes ready | "Tell me exactly what failed and how to reproduce it." |
| Client stakeholder | Reads reports and readiness, may co-sign | "Can I trust this release, and who signed it off?" |

Developers and client stakeholders are light users in v1. Every screen is designed for the QA engineer and QA lead first.

## MVP scope

Version 1 has nine modules, and none of them needs a third-party integration. Everything enters Greenlit by upload or by hand.

| Module | In v1 | Code |
| --- | --- | --- |
| Organisations, projects and roles | Yes | ORG |
| PRD to test plan (AI draft) | Yes | PLAN |
| Screenshots to test ideas (AI draft) | Yes | SHOT |
| Import past QA reports (Word, PDF) | Yes | IMP |
| Test cases with versioning and approval | Yes | TC |
| Manual test runs with evidence | Yes | RUN |
| Defects with a separate QA verification status | Yes | DEF |
| QA Inbox, reminders and daily digest | Yes | INB |
| Release report with recorded sign-off | Yes | RPT |

**Deferred**

- Phase 2: Jira sync (read-only first, then two-way), Figma import, CSV and JSON result import, weighted QA debt score.
- Phase 3: GitHub change impact, Playwright and Cypress adapters, MCP connector, SSO, SOC 2.

**Never**

A test runner, browser automation, a code editor, CI/CD, an issue tracker, or a Figma replacement. Greenlit connects to these tools and does not replace them.

## Core concepts

Every item in Greenlit belongs to one project in one organisation and has a permanent ID. Each defect has two separate statuses: the tracker owns the ticket status, and Greenlit owns QA verification.

| Object | ID prefix | What it is |
| --- | --- | --- |
| Requirement | REQ- | One testable statement taken from a PRD or typed in |
| Test plan | TP- | A versioned set of test cases for a release or feature |
| Test case | TC- | Steps, expected result, priority, linked requirements |
| Test run | RUN- | One execution of a set of cases, against a build and environment |
| Evidence | EV- | A file (screenshot, video, log, PDF) attached to a case result, run or defect |
| Defect | BUG- | A problem found in a run, with steps to reproduce and evidence |
| Report | RPT- | A generated release report, with its sign-off |

**Two statuses per defect**

| Field | Owned by | Values |
| --- | --- | --- |
| Tracker status | The issue tracker, or Greenlit when no tracker is connected | Open, In progress, Fixed, Closed |
| QA verification | Greenlit only | Not retested, Retest failed, Verified, Won't fix, Deferred |

When the two disagree, Greenlit raises a flag but never overwrites the tracker. Fixed but not retested shows as **Needs retest**. Closed after a failed retest shows as **Closed, retest failed** (critical).

**Defect lifecycle**

*Text version; the original diagram was lost when this document was exported. Reconstructed from the rest of the specs, so check it against the source diagram.*

Main path: **Open → In progress → Fixed (shown as Needs retest) → Verified (retest passed, with evidence) → Closed**.

Side paths:

1. **Retest failed.** A failed retest, with evidence, sets QA verification to Retest failed and sends the defect back to Open (shown as Reopened). Setting it to Fixed again returns it to Needs retest.
2. **Closed after a failed retest.** The tracker closes a defect whose latest retest failed. Greenlit shows **Closed, retest failed** (critical).
3. **Won't fix or Deferred.** A QA lead approves with a written reason. The defect leaves the open lists and stays on the record.

A fix moves to Needs retest automatically. Only a QA retest with evidence reaches Verified, and a tracker that closes a defect after a failed retest triggers the critical flag.

**Other terms**

- **QA Inbox**: one list per person of everything open that needs them, grouped by kind and sorted by age.
- **Release readiness**: Greenlit's assessment of a release, either Ready or Not ready yet, with the blockers listed. It is advice, not approval.
- **Sign-off**: a named QA lead's approval of a release, recorded with a date and, if blockers remain, a written reason.
- **Draft**: anything AI produced that nobody has approved yet.

## Functional requirements

Each requirement has an ID, the behaviour, and the check that proves it is done. Roles are defined in section 9. Where a requirement names the QA lead as the approver or signer, it means every role the matrix in section 9 allows for that action (owner, admin or QA lead).

**ORG: Organisations, projects and roles**

| ID | Requirement | Done when |
| --- | --- | --- |
| FR-ORG-01 | A user can create an organisation and invite members by email | An invitee who accepts joins with the role the inviter chose |
| FR-ORG-02 | A user can belong to several organisations and switch between them | Switching shows only that organisation's projects, files and search results |
| FR-ORG-03 | Admins create projects inside an organisation | A project has a name, client name (optional) and members |
| FR-ORG-04 | Every change to a plan, case, defect status or sign-off is logged | The audit log shows who, what, when, old and new value |

**PLAN: PRD to test plan**

| ID | Requirement | Done when |
| --- | --- | --- |
| FR-PLAN-01 | Upload a PRD (PDF, DOCX, Markdown) or paste text | Files up to 20 MB (proposed) are accepted; others get a clear error |
| FR-PLAN-02 | AI extracts requirements as REQ- items, each citing its source passage | Every draft requirement links to the page and passage it came from |
| FR-PLAN-03 | AI drafts test cases per requirement, including negative and edge cases | Each draft case is labelled Draft and linked to at least one requirement |
| FR-PLAN-04 | The QA engineer accepts, edits or rejects each draft | Nothing enters the approved plan without a person accepting it |
| FR-PLAN-05 | A QA lead approves the plan, which creates version 1.0 | Approval records the approver and date |
| FR-PLAN-06 | Requirements with no accepted test case are listed | The list appears on the plan and in the QA Inbox |

**SHOT: Screenshots to test ideas**

| ID | Requirement | Done when |
| --- | --- | --- |
| FR-SHOT-01 | Upload up to 30 screenshots (proposed) to a project | Images appear in order and can be renamed |
| FR-SHOT-02 | AI suggests test ideas per screen (fields, actions, validation, empty and error states) | Each idea points to the screenshot and region it came from |
| FR-SHOT-03 | Suggestions convert to draft test cases in one click | Converted cases follow FR-PLAN-04 review |

**IMP: Import past QA reports**

| ID | Requirement | Done when |
| --- | --- | --- |
| FR-IMP-01 | Upload past QA reports (DOCX, PDF) | Embedded images are extracted and kept as evidence |
| FR-IMP-02 | AI proposes defects (title, steps, expected, actual, evidence) from the report | Each proposal can be accepted, edited, merged with an existing defect, or rejected |

**TC: Test cases and versioning**

| ID | Requirement | Done when |
| --- | --- | --- |
| FR-TC-01 | Cases have title, preconditions, numbered steps, expected result, priority, linked requirements | Required fields are validated on save |
| FR-TC-02 | Editing an approved plan creates a draft version; approving it publishes a new version | Published versions cannot be edited, only superseded |
| FR-TC-03 | Compare any two versions | The diff lists added, removed and changed cases, down to changed steps and expected results |
| FR-TC-04 | Roll back to a previous version | Rollback publishes a new version equal to the old one; history is kept |
| FR-TC-05 | A test case is marked Stale when it has no passed or failed result for 30 days (configurable; Blocked and Not run do not count) or when a linked requirement changes | Stale cases show in the QA Inbox |

**RUN: Test runs and evidence**

| ID | Requirement | Done when |
| --- | --- | --- |
| FR-RUN-01 | Create a run from a plan version, with build number and environment | The run is tied to that exact version |
| FR-RUN-02 | Record each case as Passed, Failed, Blocked or Not run | Results save immediately, also when the run is unfinished |
| FR-RUN-03 | Attach evidence by drag and drop or paste | Each file records uploader, time, run, case and environment |
| FR-RUN-04 | A failed case can create a defect pre-filled with its steps and evidence | The new defect links back to the run and case |
| FR-RUN-05 | A run cannot be marked complete while failed cases have no evidence | The run shows which results are missing evidence |

**DEF: Defects and verification**

| ID | Requirement | Done when |
| --- | --- | --- |
| FR-DEF-01 | Create a defect with title, steps, expected, actual, severity, evidence | Severity is Critical, High, Medium or Low |
| FR-DEF-02 | Any role the matrix in section 9 allows (developer, QA engineer, QA lead, admin, owner) can set tracker status to Fixed | The defect moves to Needs retest and starts the retest clock; a defect in Retest failed has its QA verification reset to Not retested |
| FR-DEF-03 | QA records a retest as passed or failed, with evidence | Both outcomes require evidence. A pass sets QA verification to Verified. A fail sets it to Retest failed and, while Greenlit owns the tracker status (v1), sets tracker status back to Open. Once a tracker is synced (phase 2), Greenlit leaves the tracker status alone and offers an explicit Reopen in tracker action |
| FR-DEF-04 | Won't fix and Deferred need a reason and a QA lead | The reason and approver are logged |
| FR-DEF-05 | Closing a defect whose last retest failed raises a critical flag | The flag shows in the QA Inbox and on release readiness |

**INB: QA Inbox and reminders**

| ID | Requirement | Done when |
| --- | --- | --- |
| FR-INB-01 | Each user has an inbox of their open items, grouped: needs retest, closed with failed retest, aging defects, stale tests, uncovered requirements, runs missing evidence, unfiled failures | Groups show counts and each item shows its age |
| FR-INB-02 | A defect left in Needs retest for 48 hours (configurable) is escalated to the owner | It appears at the top of the owner's inbox; after 96 hours it also appears in the QA lead's |
| FR-INB-03 | One daily email digest per user, sent only when they have open items | Critical items (closed with failed retest) are also notified immediately |
| FR-INB-04 | Items can be snoozed with a reason | Snoozes are logged and expire after the chosen date |

**RPT: Release report and sign-off**

| ID | Requirement | Done when |
| --- | --- | --- |
| FR-RPT-01 | Release readiness shows Ready or Not ready yet, with the blockers listed | Blockers: needs retest, critical open, closed with failed retest, uncovered critical requirements, unfiled failures (failed results with no defect filed) |
| FR-RPT-02 | AI drafts the release report: summary, results, open defects, risks | The draft cites the runs and defects it describes |
| FR-RPT-03 | A QA lead signs off a release | Sign-off while Not ready yet requires a written reason, which appears in the report |
| FR-RPT-04 | Export the report as PDF and share a read-only link | The link shows the signed version, not later edits |

## AI requirements

AI drafts and people approve. No AI output becomes part of the record until a named person accepts it, and every draft shows where it came from.

| Feature | Input | Output | Who approves |
| --- | --- | --- | --- |
| Requirement extraction | PRD file or text | REQ- drafts with source passages | QA engineer |
| Test case drafting | Approved requirements | TC- drafts, including negative and edge cases | QA engineer, then QA lead approves the plan |
| Screenshot test ideas | Screenshots | Test ideas per screen and region | QA engineer |
| Report import | Past QA reports | Defect drafts with extracted evidence | QA engineer |
| Release report | Runs, defects, readiness | Report draft with citations | QA lead signs off |

**Rules**

- **AI-01 Drafts are marked.** AI output carries the Draft status and the blue-pencil mark until accepted.
- **AI-02 Sources are shown.** Every draft links to the passage, page, screenshot region or record it came from. A draft with no source is not shown.
- **AI-03 Uploads are data, not instructions.** Text inside an uploaded file can never change what the AI does. This is tested against known prompt-injection examples before launch.
- **AI-04 Tenants never mix.** Retrieval and context for one organisation never include another organisation's data.
- **AI-05 No training on customer data.** The chosen model provider must contractually exclude customer data from training.
- **AI-06 Costs are capped.** Each organisation has a monthly AI usage allowance; usage and cost per generation are logged.

**Quality check before beta**

Build a test set of 10 real PRDs, each with a test plan written by an experienced QA engineer. Measure how many of the expert's cases the AI covers, and how many AI cases a reviewer keeps. Run the set again after every prompt or model change, and do not ship a change that lowers either score.

## Non-functional requirements

Greenlit holds client data for several companies at once, so tenant isolation and access control are part of v1, not later work.

**Roles and permissions**

| Action | Owner | Admin | QA lead | QA engineer | Developer | Viewer |
| --- | --- | --- | --- | --- | --- | --- |
| Manage members and billing | Yes | Members only | No | No | No | No |
| Create projects | Yes | Yes | No | No | No | No |
| Approve a test plan version | Yes | Yes | Yes | No | No | No |
| Write cases, record runs, attach evidence | Yes | Yes | Yes | Yes | No | No |
| Set a defect to Fixed | Yes | Yes | Yes | Yes | Yes | No |
| Mark a defect Verified | Yes | Yes | Yes | Yes | No | No |
| Approve Won't fix or Deferred | Yes | Yes | Yes | No | No | No |
| Sign off a release | Yes | Yes | Yes | No | No | No |
| View plans, runs, defects, reports | Yes | Yes | Yes | Yes | Yes | Yes |

**Other requirements**

| Area | Requirement | Target (proposed) |
| --- | --- | --- |
| Tenancy | Every record carries an organisation ID; every query is filtered by it at the data layer | Automated tests prove one tenant cannot read another's data |
| Sign-in | Email and password with verification, plus Google sign-in | SSO deferred to phase 3 |
| Encryption | In transit and at rest, including evidence files | TLS 1.2 or later |
| Evidence storage | Files in object storage, private by default, served by expiring links | 200 MB per file, 10 GB per organisation on the starter plan |
| File types | Allow-list checked by file content, per upload kind. PRD: PDF, DOCX, Markdown, plain text, or pasted text. Screenshots: PNG, JPEG, WebP. Past QA reports: PDF, DOCX. Evidence: PNG, JPEG, WebP, GIF, MP4, WebM, MOV, PDF, plain-text logs, JSON. HTML and SVG are refused in v1 | Anything else gets an error naming the types accepted for that upload |
| Retention | Deleted items recoverable for 30 days; full organisation export on request | Export as JSON plus files |
| Performance | Pages load quickly on an average connection in Nigeria and Europe | 95% of page loads under 2.5 seconds |
| AI response | Drafting shows progress and streams results | First draft cases within 30 seconds for a 20-page PRD |
| Availability | Service is up during beta and v1 | 99.5% monthly |
| Backups | Daily database backups, tested monthly | Restore within 8 hours, lose at most 24 hours of data |
| Accessibility | Usable by keyboard and screen reader; status never shown by colour alone | WCAG 2.2 AA |
| Browsers | Current Chrome, Edge, Safari, Firefox; usable on a phone for the QA Inbox | Last two versions |

## Release plan

The build does not start until phase 0 shows that other QA teams share the problem. Each later phase opens only when the gate before it is met.

*Text version; the original diagram was lost when this document was exported. Reconstructed from the rest of the specs, so check it against the source diagram.*

| Phase | What happens | Gate to the next phase |
| --- | --- | --- |
| 0. Validate (weeks 1 to 4) | Interviews with QA teams; build the AI test set (10 PRDs with expert answer keys, 5 screenshot sets, 5 old reports); clickable mock-ups of the three wireframed screens tested with 5 QA engineers and leads | Other QA teams confirm the problem |
| 1. Build v1 (weeks 5 to 14) | Foundations first (tenancy, permissions, isolation suite), then the nine modules behind feature flags; Greenlit's own team is customer zero | One real release run through Greenlit end to end, and AI quality scores at their beta targets |
| 2. Private beta and first integrations | Design partners on v1; Jira sync (read-only first), Figma import, CSV and JSON result import, weighted QA debt score; external penetration test at the end | General launch checklist in the security design met |
| 3. Scale | GitHub change impact, Playwright and Cypress adapters, MCP connector, SSO, SOC 2 | n/a |

The week ranges assume one full-time engineer plus the founder and should be re-planned after phase 0. If a gate is missed, the phase is extended or the plan is changed, rather than moving on anyway.

## Risks and open questions

The biggest risk is building before the problem is confirmed by other QA teams. Phase 0 exists to retire that risk first.

| Risk | What it would cause | Mitigation |
| --- | --- | --- |
| The pain is weaker than assumed | Nobody switches from spreadsheets | Phase 0 interviews; a gate before the build |
| AI drafts are shallow or wrong | False confidence in coverage | Review before approval (AI-01 to AI-02); the quality test set |
| Reminders become noise | Users mute them and the Inbox is ignored | Digest first, owner-only alerts, snooze with reason, reminder action rate guardrail |
| Data leaks between clients | Loss of trust, possibly the business | Tenant filter at the data layer, isolation tests, no shared AI context |
| Without Jira sync, teams type defects twice | Low adoption in v1 | Keep defect entry fast; bring read-only Jira sync early in phase 2 |
| Incumbents add AI test generation | The AI feature alone stops being different | Lead with accountability and traceability, which incumbents lack |
| AI costs grow faster than revenue | Losses per customer | Usage caps, cost logged per generation, pricing with AI credits |

**Open questions**

- [ ] Would teams pay for the QA Inbox without AI test generation? If yes, it becomes the lead feature.
- [ ] At agencies, who retests fixes: the agency's QA or the client's?
- [ ] What retest window do teams actually work to (48 hours is a guess)?
- [ ] Do teams need two-way Jira sync on day one, or is read-only enough?
- [ ] Which AI model provider, and do its terms exclude customer data from training?
- [ ] Pricing: per seat, per project, or per client organisation for agencies?
- [ ] Is "Greenlit" available as a domain and trademark in Nigeria and key markets?
