# Greenlit v1 Build Tasks

The working task list for building Greenlit v1 (the MVP). Every task points back to the spec that defines it, so this file says *what to build and in what order*, and the specs say *exactly how it must behave*. When the two disagree, the specs win; fix this file.

**Specs**

| Short name | File |
| --- | --- |
| PRD | [Greenlit PRD v2.md](Greenlit%20PRD%20v2.md) |
| ARCH | [Greenlit Technical Architecture.md](Greenlit%20Technical%20Architecture.md) |
| DATA | [Greenlit Data Model and Traceability Spec.md](Greenlit%20Data%20Model%20and%20Traceability%20Spec.md) |
| AI | [Greenlit AI Behaviour Spec.md](Greenlit%20AI%20Behaviour%20Spec.md) |
| SEC | [Greenlit Security and Tenancy Design.md](Greenlit%20Security%20and%20Tenancy%20Design.md) |
| UX | [Greenlit UX Flows and Wireframes.md](Greenlit%20UX%20Flows%20and%20Wireframes.md) |

`DATA §7` means section 7 of the data model spec (sections are counted in heading order, Overview = 1).

**How to use this file**

- `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what).
- A task is done only when every "Done when" line is true **and** covered by an automated test where one is named.
- Every endpoint added must get a row in the permission table (M1-11) and be covered by the isolation suite (M1-15) in the same pull request.
- Every new tenant table must get `org_id`, row-level security and soft delete (M1-01, M1-03) in the same migration.
- Weeks follow the phase 1 build order in ARCH §9 (weeks 5 to 14).

---

## 0. Before writing code

### Decisions (ARCH §10)

- [ ] **D-00** Name the lead engineer; confirm Python (Django) back end vs TypeScript throughout. *Blocks everything below.*
- [ ] **D-001** Modular monolith, not microservices: write decision record.
- [ ] **D-002** Django + Django REST Framework: write decision record.
- [ ] **D-003** React + TypeScript single-page app (Vite): write decision record.
- [ ] **D-004** PostgreSQL 16+ with row-level security: write decision record.
- [ ] **D-005** Case identity + immutable case revisions: write decision record.
- [ ] **D-006** Celery + Redis: write decision record.
- [ ] **D-007** Hosting platform and region. Run a latency test from Lagos and London against 2 or 3 candidate regions; check cross-border transfer rules (SEC §7). *Blocks M0-07.*
- [ ] **D-008** AI provider. Score candidates on the AI test set; terms must exclude training on customer data and limit retention (PRD AI-05, SEC §10). *Blocks M2-04 going live; build against a stub until then.*
- [ ] **D-009** Email provider (bounce handling; no document contents in emails). *Blocks M6-07.*
- [ ] **D-010** Polling or server-sent events for job progress. *Affects M1-17, M8-01.*

### Spec gaps to close (found while planning)

These things are referenced by behaviour in the specs but have no table or field in DATA §3. Add them to the data model spec (marked *proposed*) before building the task that needs them.

- [ ] **G-01** `notification` table: user\_id, kind, target\_type, target\_id, level (48h, 96h, critical), sent\_at, read\_at. Needed for idempotent reminders (ARCH §5, M6-05).
- [ ] **G-02** `share_link` table: report\_id, token\_hash, expires\_at, revoked\_at. Needed for FR-RPT-04 and SEC §4 (M8-08).
- [ ] **G-03** `user.time_zone`: needed for the 07:00 digest (M6-07).
- [ ] **G-04** `job` table: kind, state, progress (json), error, attempts, org\_id. Needed for progress polling and the failed-job list (ARCH §5, §6; M1-17).
- [ ] **G-05** `ai_call` metering table: feature, model, tokens in and out, cost\_usd, duration\_ms, input\_hash (AI §8; M2-04). Plus `ai_dropped_item` for dropped and rejected drafts kept for quality review (AI §2).
- [ ] **G-06** Reject reason on drafts (wrong, duplicate, too vague, not testable) and an accepted-in-under-2-seconds flag (AI §6, §9).
- [ ] **G-07** Requirement revision history. AI §5 says the old passage stays linked to the old revision, but `requirement` keeps only an int `revision`. Decide: a `requirement_revision` table, or before/after text in `audit_event`.
- [x] **G-08** (closed: `project.settings`, see the data model spec and apps/core/project_settings.py) Project settings: stale window (30 days), retest escalation (48h, 96h), aging limits per severity, fixer-cannot-verify on/off. Store as a `project.settings` json or a table.
- [ ] **G-09** Merge semantics for FR-IMP-02 "merge with an existing defect": which fields win, where the evidence goes, what the audit log records.

### Phase 0: validate (weeks 1 to 4; PRD §10)

Not engineering work, but the build gate depends on it.

- [ ] **P0-01** Interview QA teams; confirm the problems in PRD §2 and answer the PRD §11 open questions (retest window, who retests at agencies, Jira needs, pricing).
- [ ] **P0-02** Build the AI test set: 10 PRDs with expert requirement lists and test plans, 5 screenshot sets, 5 old QA reports, with permission or anonymised (AI §7).
- [ ] **P0-03** Clickable mock-ups of the QA Inbox, draft review and release sign-off; test with 5 QA engineers and leads (UX §11).
- [x] **P0-04** (Greenlit_Brand_Guidelines_2.html and Greenlit_Logo_Pack/ in the repo; tokens copied into web/src/design/tokens.css) Get the brand guidelines v2.0 file into the repo (colour tokens, type, status marks, voice). *Blocks M1-18 styling.*
- [ ] **P0-05** Gate: other teams confirm the problem. Re-plan the weeks below if needed.

---

## M0. Repository and tooling (week 5)

- [x] **M0-01** (README, .editorconfig, CLAUDE.md, ARCH §4 layout in place; git repo initialised, nothing committed yet) Create the repository with the layout in ARCH §4: `web/`, `api/` (core, requirements, plans, runs, defects, inbox, reports, ai, files), `tests/` (isolation, permissions, ai\_eval), `docs/decisions/`. Add README, `.gitignore`, `.editorconfig`, CLAUDE.md.
  - Done when: `git clone` plus one documented command starts the stack locally.
- [x] **M0-02** (docker-compose.yml written but not run: Docker is optional, see docs/local-setup-no-docker.md; MinIO, ClamAV and Redis are not in use locally yet) Docker Compose for local: PostgreSQL 16, Redis, S3-compatible storage (MinIO), a local mail catcher, ClamAV.
- [x] **M0-03** (settings, apps, URLs, health and flags endpoints, OpenAPI at /api/schema/; verified against local Postgres 16 with the restricted app role) Django project: settings for local, staging and production; secrets from the environment only (SEC §6); one Django app per module; DRF; OpenAPI schema generated from code (drf-spectacular).
- [x] **M0-04** (Vite app installed, oxlint, typecheck and build pass; `pnpm gen:api` writes api/openapi.yaml and web/src/api/schema.d.ts; `pnpm check:api` fails when stale) Vite + React + TypeScript app in `web/` with `src/features/` and `src/design/`. API types generated from the OpenAPI schema; CI fails if they are out of date (ARCH §4).
- [x] **M0-05** (Celery configured with a ping task; local settings run jobs inline, so a real worker and beat schedule are untested until Redis is available) Celery + Redis + beat scheduler wired up; a hello-world job runs locally.
- [~] **M0-06** (.github/workflows/ci.yml covers lint, format, mypy, migration checks, tests, dependency and secret scans; every step except the Postgres service setup and gitleaks was run locally; the workflow has not run on GitHub because there is no remote) Pull request pipeline (ARCH §7): lint and type checks (ruff, mypy, eslint, tsc); unit and API tests; dependency scan; secret scan; migration check (applies cleanly; no row-level security policy dropped).
- [!] **M0-07** (blocked by D-007 hosting; the isolation suite stage also waits for M1-15) Merge pipeline: deploy to staging, run the isolation suite, promote to production with migrations first. Rollback = redeploy the previous build. *Needs D-007.*
- [x] **M0-08** (Sentry scrubbing in config/observability.py is tested; it only starts when SENTRY_DSN is set; the logs-carry-IDs-only rule is a convention with no automatic check yet) Error tracking (Sentry or similar) with personal data and document text scrubbed; logs record IDs only, never document text (SEC §5).
- [x] **M0-09** (apps/core/flags.py: flags per PRD module code, all on locally, off by default elsewhere, `flag_required('plan')` answers 404 when off, /api/flags/ for the app) Feature flags per module, so each module ships to staging behind a flag (ARCH §9).

## M1. Foundations: tenancy, sign-in, permissions, audit, IDs, files (weeks 5 to 6)

*Hard to add later. Nothing in M2 onwards starts until M1-01 to M1-15 are done.*

**Data layer**

- [x] **M1-01** (base model and soft-deleting manager in apps/core/models.py) Base model: `id` (uuid), `org_id`, `created_at`, `created_by`, `updated_at`, `deleted_at`. Default manager hides soft-deleted rows (DATA §1).
- [x] **M1-02** (organisation, membership, project, project_member, user; project key uniqueness is not yet limited to non-deleted rows) Account tables: `organisation`, `user` (global, no org\_id), `membership` (role enum: owner, admin, qa\_lead, qa\_engineer, developer, viewer; status), `project` (name, client\_name, key 2 to 6 letters, unique per organisation), `project_member` (DATA §3).
- [x] **M1-03** (policies in apps/core/rls.py; tests in apps/core/tests/test_rls.py, 12 passing) Row-level security on every tenant table, keyed on `current_setting('app.org_id')`. The app connects as a role without BYPASSRLS; a missing setting raises an error instead of returning rows. A migration helper adds the policy; a CI test fails if any tenant table lacks enabled and forced RLS (DATA §8, SEC §5).
  - Done when: a raw query with no org set fails, and a query with org A set never returns org B rows (test).
- [x] **M1-04** (apps/core/middleware.py: `X-Org` header names the organisation by slug; one transaction per request holds the scope and restores it on exit; a non-member and a nonexistent organisation get identical 404s; `/api/me/` and `/api/org/` use it; 9 tests as the app role) Tenancy middleware: resolve the organisation from the request, check an active `membership`, `SET LOCAL app.org_id` inside the request transaction. One code path only (ARCH §4 rule: `core` owns tenancy).
- [x] **M1-05** (database trigger per tenant-to-tenant foreign key via `same_org_refs`; tests/isolation/test_foreign_keys.py finds every such key from the models and fails the build if a trigger is missing; proven by dropping one) Cross-organisation foreign keys impossible: composite keys `(org_id, id)` or triggers on every tenant-to-tenant reference (DATA §8 rule 4).
- [x] **M1-06** (`visible_projects()` in apps/core/policy.py; every project lookup must go through it; tested for engineer vs admin) Project scope: access needs a `project_member` row unless the user is an owner or admin (DATA §8 rule 3).

**Sign-in (SEC §3)**

- [x] **M1-07** (allauth headless API for the single-page app; see docs/sign-in.md. 71 tests in tests/security as the restricted app role, and 13 deliberate breaks of it were all caught. Two things are NOT done and need you: Google sign-in is built and tested only with a stand-in, because the Google OAuth client ID and secret have to be created by you; and TOTP key rotation is supported but no key is set, so FIELD_ENCRYPTION_KEYS must be provided before any deployment. Found on the way: the planned 30-minute reset-link setting did nothing in this allauth version, so links would have lasted 3 days; it is now Django's PASSWORD_RESET_TIMEOUT and is tested) django-allauth: email and password with verified email; Google sign-in.
  - Passwords at least 12 characters, checked against a breached-password list, hashed with Argon2id.
  - 5 failed attempts in 15 minutes slows that account and IP and emails the user.
  - Cookies Secure, HttpOnly, SameSite; 12-hour idle timeout; 30-day maximum.
  - Sign out everywhere; a password change ends all sessions.
  - Recovery link valid 30 minutes; responses never reveal whether an email is registered.
  - Authenticator-app two-step verification, required for owners and admins.
- [x] **M1-08** (POST /api/orgs/ (creator becomes owner), POST /api/invites/ (email with a 7-day link; only a hash of the token is stored), POST /api/invites/accept/; every accept failure gives the same answer; admins cannot invite owners; switching organisation is the `X-Org` header, the switcher UI is M1-18. Accepting requires a verified email, added with sign-in (M1-07)) Create organisation; invite by email with a chosen role; accept joins with that role; switch organisation (FR-ORG-01, FR-ORG-02).
  - Done when: after switching, only that organisation's projects, files and search results appear (isolation test).
- [x] **M1-09** (POST/GET /api/projects/, GET /api/projects/<key>/; keys are unique per organisation, uppercased; members must be active org members; unseen projects are 404; audited. Member add/remove on an existing project is M1-19) Admins create projects with name, optional client name, key and members (FR-ORG-03).

**Permissions (SEC §4, PRD §9)**

- [x] **M1-10** (apps/core/policy.py: Action enum and MATRIX mirror PRD §9; `requires(Action.X)` gives 404 with no organisation or membership and 403 for a role the matrix denies) One policy module that every endpoint calls. Check order: session → membership → role and project access. Records the user cannot see return 404, never 403. Sign-off, Won't fix and Deferred re-check the role at the moment of the action.
- [x] **M1-11** (tests/permissions/test_endpoint_role_table.py: every /api/ route must declare requires/AuthenticatedOnly/Public or the build fails; each role is called against each requires-endpoint; policy matrix also checked against a hand-copied PRD table. Endpoints with bodies or URL parameters must add samples) Permission test table: every endpoint × every role with the expected outcome, generated from the PRD §9 matrix. The build fails if an endpoint has no row.

**Audit and IDs**

- [x] **M1-12** (apps/core/audit.py `record()`; core_auditevent is append-only: app role has SELECT/INSERT only and a trigger refuses UPDATE/DELETE for every role; changed fields only; org taken from the scope. Not yet written to by any feature, and AI-action entries (model name, source IDs) wait for M2-04) `audit_event` (actor\_id, action, target\_type, target\_id, before, after, at). Append-only in the database: the app role has no UPDATE or DELETE. Helper writes only changed fields. AI actions record the model name and source record IDs, not prompts (FR-ORG-04, DATA §10).
- [x] **M1-13** (apps/core/numbering.py: `next_number()` locks a per-project counter row; `format_display_id`/`parse_display_id` accept any case; 50-thread concurrency test gives 1..50. URL routing by display ID and API lookup by either form come with the first module that has records) `project_counter` (project\_id, kind, next\_no), incremented in the same transaction as the insert; numbers never reused. Display formats REQ-n, TP-n, TC-nnnn, RUN-n, EV-nnnn, BUG-n, RPT-n; `KEY-BUG-1042` outside the project; URLs use display IDs (`/hube/bugs/1042`); APIs accept uuid or display ID (DATA §4).
  - Done when: 50 concurrent inserts produce 50 unique, gap-free numbers (test).

**Files (SEC §8, §6; ARCH §4 rule: only `files/` touches storage)**

- [x] **M1-14** (apps/files, docs/files.md: content identified by bytes per PRD §9 kind, HTML and SVG refused whatever they are called; size limits, 10 GB org quota; keys `{org}/{project}/{uuid}`; scan job hashes and scans before release, rejected and infected bytes deleted; 15-minute signed links, downloads as sandboxed attachments; S3 (SigV4, size-limited presigned POST) or local storage; ClamAV or stub scanner, production refuses stub and local. 50 tests; 10 deliberate breaks caught after fixing one test that passed for the wrong reason. Found on the way: the scan deleted files while still open, which Windows refuses, leaving rejected files stuck in scanning; and S3 links defaulted to SigV2. NOT proven: S3/MinIO and ClamAV themselves, which need Docker or staging) File service:
  - Signed upload URL scoped to `/{org_id}/{project_id}/`; upload-complete callback.
  - Allow-list checked by content per upload kind (PRD §9 "File types"); HTML and SVG refused.
  - Size limits: 20 MB for PRDs, 200 MB per evidence file; 10 GB per organisation on the starter plan.
  - Malware scan before the file is available; sha256 recorded.
  - Signed download links valid 15 minutes, checked against the requester's organisation; documents and text served as downloads from a separate domain.
  - Error message names the accepted types for that upload (UX §9).

**Proof**

- [x] **M1-15** (tests/isolation/test_cross_tenant.py: two seeded organisations; checks every tenant table in the database, every API endpoint and method discovered from the URL config, and a leak scan of every GET response for the other tenant's data; a tenant table without seed data fails the suite. Proven able to fail: breaking the table policies, or the policies and the middleware together, turns it red. File routes and search are not covered yet because they do not exist) Isolation suite (`tests/isolation/`): seed organisations A and B with full sample data; as a user of A, call every endpoint, file route and search with B's IDs; every call returns 404. Endpoints are discovered from the URL config so a new endpoint is covered automatically. Runs on every deploy (SEC §5, DATA §8 rule 7).

**Platform**

- [x] **M1-16** (CSP via Django's built-in middleware, nosniff, frame denial, Permissions-Policy; CSRF token endpoint `/api/csrf/` and a test that every non-GET endpoint refuses a request without it; throttles per IP, user and organisation on every API view, `upload` and `ai_job` scopes ready; Redis cache for counters, in-memory locally; see docs/security-headers.md. Proven able to fail by breaking each protection. The single-page app's own CSP is set by its host, still open with D-007) Security headers (HSTS, strict CSP, nosniff, frame-ancestors none), CSRF tokens on state-changing requests, rate limits per user, organisation and IP on sign-in, uploads, AI jobs and the API (SEC §8).
- [x] **M1-17** (apps/core/jobs.py, docs/jobs.md: `job_handler`/`enqueue`, runs in its organisation's scope, retries 10 s doubling to 10 min, then `dead`; errors keep only the class name unless the handler raises `JobFailure` with a message written for people; a job delivered twice runs once; a running job silent for 30 min is taken over; progress commits as it goes and is readable from another connection mid-run; `for_each_org` fans out from `org_registry`; `GET /api/jobs/`, `GET /api/jobs/{id}/`, `POST /api/jobs/{id}/rerun/` (owners and admins). 20 tests; 9 deliberate breaks caught, one of them only after fixing a test that was checking itself. A real Redis-backed worker and beat schedule have not run, since there is no Redis here) Job framework: base task that requires one `org_id` and sets the scope before touching data; safe to run twice; retries with growing delays; failed jobs land in an admin list that can re-run them; progress written to the `job` table for the browser (G-04, D-010, ARCH §6).
- [x] **M1-18** Front-end shell: sign-in screens; organisation switcher; top bar Inbox, Projects, Settings; routes by display ID; brand tokens on `:root`; Radix primitives; status chip component (mark plus word, never colour alone); visible focus ring; `?` shortcut overlay (UX §1, §10). *Styling needs P0-04.*
- [~] **M1-19** (API done: change role, remove member, list and revoke invitations, edit project and its settings, add and remove project members; owners only for owner changes, never zero owners, everything audited, a stranger's or other tenant's ID is 404; project settings validated with spec defaults in apps/core/project_settings.py (G-08 closed). 29 tests plus permission-table and isolation coverage; 9 deliberate breaks caught. Screens come with M1-18) Settings: members (invite, change role, remove, all audited), projects, project settings (G-08).
- [x] **M1-20** Seed command: two organisations with projects, members of every role, and sample records for each module as it lands (used locally, on staging and by M1-15).

## M2. Source documents, requirements and the AI core (weeks 7 to 8)

- [ ] **M2-01** `source_document` (project\_id, kind: prd, screenshot\_set, qa\_report; file\_ref; page\_count). PRD upload or pasted text on the project's Sources screen (FR-PLAN-01; UX §2 screen 5).
- [ ] **M2-02** `scan_and_parse` job: malware scan; text and images extracted with page and character positions (pdfplumber, python-docx, Markdown, plain text); OCR only as fallback; extraction stored. Queues the matching AI job when done (ARCH §5, §6).
- [ ] **M2-03** `requirement` (display\_no, title, text, priority, revision, source\_document\_id, source\_locator, review\_state, origin). A text change raises `revision` and keeps the old provenance (G-07).
- [ ] **M2-04** AI client in `api/ai/`, the only code that calls the provider (ARCH §4):
  - Per-feature JSON schema; document text in a clearly delimited data section; the model gets no tools (AI §6).
  - Requests built from one organisation's records only; no shared caches or indexes (AI-04).
  - Retry once on bad output, 3 times with back-off on provider errors.
  - Metering of every call (G-05); hard cap at 100% of the allowance blocks new AI jobs only; 80% notice to owners and admins (AI §8, AI-06).
  - Re-running on unchanged input returns the stored result.
  - Works against a stub provider until D-008.
- [ ] **M2-05** Output checks (AI §4, §5): schema; every referenced ID exists in this project; 5-to-30-word quote found word for word in the stored text, then its position stored; image regions inside the image; possible duplicates marked; title 120 characters and 20 steps (over-length items dropped and counted, never cut). Dropped items logged.
  - Done when: a fixture reply with an invented quote, a foreign ID and an over-length title produces zero drafts and three logged drops.
- [ ] **M2-06** F1 `draft_requirements` (AI §3 F1): split compound statements, keep the PRD's wording, flag vague statements, never invent. Progress by section; drafts appear as each section finishes (FR-PLAN-02).
  - Done when: first drafts appear within 30 seconds for a 20-page PRD (PRD §9).
- [ ] **M2-07** Draft review screen, shared by F1 to F4 (UX §7, AI §6):
  - Source on the left with the passage or region highlighted; draft cards on the right with the blue-pencil mark and the word Draft.
  - Accept, edit, reject; shortcuts `A`, `R`, `Enter`, `J`, `K`.
  - Accept-all limited to 20 at a time; accepts under 2 seconds counted and shown to the QA lead.
  - Optional reject reason; assumptions shown on the card; the gaps list shown and copyable.
  - Every accept and reject writes the record and an audit event (FR-PLAN-04, AI-01, AI-02).
- [ ] **M2-08** Requirements screen: list, filter, manual create and edit (origin = human). Editing text raises `revision`, which makes linked cases Stale (FR-TC-05).
- [ ] **M2-09** AI failure states with the exact messages in AI §9 (unavailable, partly dropped, gaps, allowance used up), written in the brand voice.
- [ ] **M2-10** `tests/ai_eval/` runner: scores from AI §7 (recall, precision, coverage, keep rate, citation accuracy, report accuracy, injection pack). CI blocks a merge touching `api/ai/` if a score drops (ARCH §7).
- [ ] **M2-11** Prompt-injection pack: at least 30 hostile documents (hidden instructions, instructions in image text, fake system messages, requests for other data). Every one must produce schema-valid output, no injected content and no record changes (AI §6, AI-03).

## M3. Test plans, cases and versioning (weeks 7 to 8)

- [ ] **M3-01** Tables `test_plan`, `plan_version`, `test_case`, `case_revision`, `plan_version_case`, `case_requirement` (with `req_revision_seen`). Database constraints: one draft per plan (partial unique index); a trigger refuses updates to published versions and to revisions used by them (DATA §3, §5, §6; FR-TC-02).
- [ ] **M3-02** Case editing in a draft: title, preconditions, numbered steps, expected result, priority and linked requirements are validated on save. An edit creates revision n+1 and swaps the draft's pointer; adding creates a case and its first revision; removing drops the pointer only (FR-TC-01; DATA §6 steps 1 to 3).
- [ ] **M3-03** Approve a draft: requires the approve-plan role; next minor number by default, major bump optional; previous version becomes superseded; `current_version_id` moves; approver and date recorded; audited (FR-PLAN-05; DATA §4 rule 4).
- [ ] **M3-04** Editing a published plan opens a draft that copies the current pointers, no content (DATA §6 step 1).
- [ ] **M3-05** Discard a draft: deletes the draft version and revisions only it used (DATA §6 step 5).
- [ ] **M3-06** Diff any two versions by `test_case_id`: added, removed, changed (field by field), unchanged hidden by default; steps compared as an ordered list so reordering shows as moved (FR-TC-03).
- [ ] **M3-07** Roll back: a new version with the old version's pointers, published as the next number; history kept (FR-TC-04).
- [ ] **M3-08** F2 `draft_cases` (AI §3 F2): input is accepted requirements plus existing cases; a positive and a negative case per requirement where it makes sense; one action per step; checkable expected results; placeholders like `[valid card number]`; case type; gaps list. Accepted drafts go into the plan's draft version (FR-PLAN-03).
- [ ] **M3-09** Uncovered requirements (accepted requirements with no accepted case in the current version) listed on the plan (FR-PLAN-06; DATA §9).
- [ ] **M3-10** Plan screens: plan list, version history, editor, diff view, submit and approve actions (UX §2 screen 8; UX Flow 1).

## M4. Releases, runs and evidence (weeks 9 to 10)

- [ ] **M4-01** `release` (name, target\_date, state: open, signed\_off, cancelled): create, list, cancel (DATA §3).
- [ ] **M4-02** Create a run from a plan version with build, environment and release; the run is fixed to that version for life (FR-RUN-01).
- [ ] **M4-03** `case_result` per case per run pointing at the exact case revision; Passed, Failed, Blocked, Not run; saves immediately, even when the run is unfinished; latest write wins; old and new outcomes audited (FR-RUN-02).
- [ ] **M4-04** Run screen: `P`, `F`, `B`, `N`, `E`, arrow keys; live region announces saved results; results saved locally first when offline, with "Saving…" and "Saved"; failed saves stay marked and retry (UX §9, §10).
- [ ] **M4-05** Evidence: drag and drop or paste; `evidence` plus `evidence_link` (one file can support several results, defects or retests); records uploader, time, run, case and environment; EV-nnnn; test-data notice at upload (FR-RUN-03; SEC §7).
- [ ] **M4-06** A run cannot be completed while failed results have no evidence; the run lists which ones (FR-RUN-05).
- [ ] **M4-07** Create a defect from a failed result, pre-filled with steps and evidence and linked back via `found_in_result_id` (FR-RUN-04). *Needs M5-01.*

## M5. Defects and retests (weeks 9 to 10)

- [ ] **M5-01** `defect` (display\_no, title, steps, expected, actual, severity, tracker\_status, qa\_status, owner\_id, fixed\_at, found\_in\_result\_id, review\_state, origin) and `retest` (outcome, tested\_by, tested\_at, build, environment; one row per retest, never overwritten) (DATA §3).
- [ ] **M5-02** Create a defect by hand with title, steps, expected, actual, severity (Critical, High, Medium, Low) and evidence (FR-DEF-01).
- [ ] **M5-03** One status service that applies every rule in DATA §7 "Transitions Greenlit applies", and the only code that changes `tracker_status` or `qa_status`. Every change audited.
  - Done when: a table-driven test covers every row of the DATA §7 status table and all four transition rules.
- [ ] **M5-04** Set Fixed (developer, QA engineer, QA lead, admin, owner): records `fixed_at`, moves to Needs retest, resets Retest failed to Not retested (FR-DEF-02).
- [ ] **M5-05** Record a retest, passed or failed, with evidence required for both. A pass gives Verified; a fail gives Retest failed and sets tracker status to Open (v1) (FR-DEF-03).
- [ ] **M5-06** Won't fix and Deferred: written reason plus approval by a QA lead, admin or owner; reason and approver logged (FR-DEF-04).
- [ ] **M5-07** Closing a defect whose latest retest failed raises the critical flag: shown in the Inbox and on readiness, and notified immediately (FR-DEF-05; M6-06).
- [ ] **M5-08** Fixer-cannot-verify rule behind a project setting, default per the SEC §11 open question (SEC §4).
- [ ] **M5-09** Defect list and detail screens; "shown as" labels from DATA §7; phone layout with camera capture for retest evidence (UX Flow 2; UX §10).
  - Done when: on a 375 px screen, a retest with a photo can be recorded in under a minute.

## M6. Derived states, QA Inbox, reminders and digest (week 11)

- [ ] **M6-01** Derived states as database views, scoped by organisation: needs retest, closed with failed retest, aging (critical 2 days, high 7, medium 14, low 30), stale, uncovered, missing evidence, unfiled failure. Thresholds come from project settings (DATA §9; G-08).
  - Done when: each state has a fixture test that turns it on and off.
- [ ] **M6-02** Stale: no passed or failed result in 30 days, or a linked requirement's `revision` is above `req_revision_seen`; nightly `stale_check` job (FR-TC-05; ARCH §6).
- [ ] **M6-03** Inbox API: one list per user across their projects; groups from FR-INB-01 with counts; each item shows its age and its single next action (Retest, Run, Add case, Open); critical band first; snoozed items left out (FR-INB-01; UX §6).
- [ ] **M6-04** Snooze with a reason and an end date; logged; expires automatically; Snoozed filter; still counts towards readiness (FR-INB-04; DATA §9).
- [ ] **M6-05** `reminders` job every 15 minutes per organisation: Needs retest past 48 hours goes to the top of the owner's Inbox; past 96 hours it also appears for the QA lead; each level notified once (FR-INB-02; G-01).
- [ ] **M6-06** Critical items (closed with failed retest) skip the digest and notify the owner and QA lead within one job cycle (FR-INB-03; ARCH §5).
- [ ] **M6-07** `digest` job at 07:00 in each user's time zone: one email per user with open items, none for users with nothing open; titles and links only, never document contents (FR-INB-03; SEC §10; G-03; D-009).
- [ ] **M6-08** (screen built in web/src/features/inbox against the mock API in web/src/mocks; switch to the real endpoint when M6-03 lands) Inbox screen, desktop and phone (sidebar becomes filter chips); keyboard navigation; empty, loading and error states from UX §9; status chips read as "Status: Needs retest, 4 days" (UX §6, §10).
- [ ] **M6-09** Metrics instrumentation: reminder action rate within 72 hours, retest lag, escaped closures (PRD §3).

## M7. Screenshots and report import (week 11)

- [ ] **M7-01** Upload up to 30 screenshots per batch; shown in order; renamable; test-data notice (FR-SHOT-01; SEC §7).
- [ ] **M7-02** F3 `draft_screen_ideas`: per screen, the elements seen and test ideas tied to a region box (0 to 1); validation, empty, error, loading and long-content ideas; behaviour that cannot be seen marked as an assumption (FR-SHOT-02; AI §3 F3).
- [ ] **M7-03** Convert an idea to a draft case in one click; it then follows normal draft review (FR-SHOT-03).
- [ ] **M7-04** Upload a past QA report (PDF, DOCX); embedded images extracted and kept as evidence (FR-IMP-01).
- [ ] **M7-05** F4 `import_report`: draft defects keeping the reporter's wording; severity left empty unless stated; only adjacent images attached; possible duplicates suggested, never merged automatically. Each proposal can be accepted, edited, merged or rejected (FR-IMP-02; AI §3 F4; G-09).

## M8. Release readiness, report and sign-off (weeks 12 to 13)

- [ ] **M8-01** Readiness per release: Not ready yet if any needs retest, open critical, closed with failed retest, uncovered critical requirement or unfiled failure exists; blockers listed by type with counts, each linking to its record; the panel updates without a reload; "Checking…" while loading and "Couldn't check" blocks sign-off (FR-RPT-01; DATA §9; UX Flow 3).
- [ ] **M8-02** Verified coverage per release, as defined in DATA §9 (the North Star).
- [ ] **M8-03** Facts builder: the one function that computes run results, defect states, blockers and coverage for a release. F5, the report, and readiness all read from it.
- [ ] **M8-04** F5 `draft_release_report`: input is facts only; summary, results by area, open defects, risks, readiness statement; every claim cites record IDs. Checks: every number matches the facts, and the readiness line matches the computed value; never recommends shipping when Not ready yet (FR-RPT-02; AI §3 F5).
  - Done when: report accuracy is 100% on the test set.
- [ ] **M8-05** Report editor with each claim linked to its run or defect, beside the facts used (UX Flow 3 step 3).
- [ ] **M8-06** Sign-off (owner, admin or QA lead; role re-checked at the action):
  - The only green button in the product.
  - If Not ready yet, a dialog lists the blockers and the button stays disabled until a reason is typed.
  - On sign-off: report frozen (state signed, `snapshot_at`); `sign_off` row with `readiness_at_signing` and override reason; release set to signed\_off; audited.
  - (FR-RPT-03; DATA §3; UX §8)
- [ ] **M8-07** PDF export of the signed version (FR-RPT-04).
- [ ] **M8-08** Read-only share link showing only the signed version; revocable; expires after 30 days by default; downloads through it audited (FR-RPT-04; SEC §4; G-02).
- [ ] **M8-09** (screen built in web/src/features/releases against the mock API in web/src/mocks; PDF and share link are stubs until M8-07/M8-08) Release screen: blockers on the left, report and sign-off on the right; after sign-off, who signed, when and readiness at that moment (UX §8).

## M9. Cross-cutting work (runs alongside, finished by week 14)

- [ ] **M9-01** Search: PostgreSQL full-text search over display IDs and titles, scoped by organisation, covered by the isolation suite (ARCH §3; SEC §5).
- [ ] **M9-02** Empty, loading and error states for every screen in UX §9.
- [ ] **M9-03** Accessibility, WCAG 2.2 AA: automated checks (axe) in CI; a manual keyboard and screen-reader pass on the Inbox, draft review, run and sign-off screens; reduced motion respected; touch targets at least 44 × 44 px (PRD §9; UX §10).
- [ ] **M9-04** Performance: 95% of page loads under 2.5 seconds, measured from Lagos and London (PRD §9).
- [ ] **M9-05** Monitoring and alerts from ARCH §8: uptime, errors, speed, jobs (reminders not run for 1 hour, any failed digest), AI failure rate and cost, security (row-level security errors, cross-organisation lookups, sign-in spikes), backups.
- [ ] **M9-06** Backups: daily, kept 30 days; file storage versioned; monthly restore test timed against the 8-hour target; written runbook (SEC §6).
- [ ] **M9-07** Deletion and recovery: deleted items recoverable for 30 days with a restore action; nightly `purge` job hard-deletes after that (PRD §9; ARCH §6).
- [ ] **M9-08** Exports: full organisation export as JSON plus files (including the audit log); users can download or delete their own account data (SEC §7).
- [ ] **M9-09** `usage_rollup` hourly; AI usage page in Settings for owners and admins (AI §8).
- [ ] **M9-10** Compliance paperwork for beta: data processing agreement, sub-processor list, security page, incident response runbook (SEC §9, §10).

## M10. Beta gate (week 14)

All must be true before the private beta (PRD §10).

- [ ] **M10-01** One real release (customer zero) run through Greenlit from PRD to sign-off, with nothing left untested, unretested or unclosed.
- [ ] **M10-02** AI scores at beta targets on the test set: requirement recall ≥ 85%, precision ≥ 80%, case coverage ≥ 70%, keep rate ≥ 75%, citation accuracy ≥ 98%, report accuracy 100%, injection pack 100% (AI §7).
- [ ] **M10-03** Isolation suite and permission table green on staging, with every endpoint covered.
- [ ] **M10-04** Every *Beta* item in SEC checked off.
- [ ] **M10-05** Accessibility pass (M9-03) and performance target (M9-04) met.
- [ ] **M10-06** Restore test done within the last month.

---

## Later (not v1)

- **Phase 2:** Jira sync (read-only first, then two-way, with the conflict rules in DATA §7 and "Reopen in tracker"); Figma import; CSV and JSON result import; weighted QA debt score; organisation-wide two-step policy; field-level encryption for integration tokens; automatic blurring of personal data in screenshots; external penetration test.
- **Phase 3:** GitHub change impact; Playwright and Cypress adapters; MCP connector; SSO (SAML, OIDC); SOC 2; dedicated database option; a search engine if PostgreSQL search is outgrown.

---

## Traceability index

| Spec ID | Tasks |
| --- | --- |
| FR-ORG-01 | M1-08 |
| FR-ORG-02 | M1-08, M9-01 |
| FR-ORG-03 | M1-09 |
| FR-ORG-04 | M1-12 |
| FR-PLAN-01 | M1-14, M2-01 |
| FR-PLAN-02 | M2-05, M2-06 |
| FR-PLAN-03 | M3-08 |
| FR-PLAN-04 | M2-07 |
| FR-PLAN-05 | M3-03 |
| FR-PLAN-06 | M3-09 |
| FR-SHOT-01 | M7-01 |
| FR-SHOT-02 | M7-02 |
| FR-SHOT-03 | M7-03 |
| FR-IMP-01 | M7-04 |
| FR-IMP-02 | M7-05 |
| FR-TC-01 | M3-02 |
| FR-TC-02 | M3-01, M3-04 |
| FR-TC-03 | M3-06 |
| FR-TC-04 | M3-07 |
| FR-TC-05 | M2-08, M6-02 |
| FR-RUN-01 | M4-02 |
| FR-RUN-02 | M4-03, M4-04 |
| FR-RUN-03 | M4-05 |
| FR-RUN-04 | M4-07 |
| FR-RUN-05 | M4-06 |
| FR-DEF-01 | M5-02 |
| FR-DEF-02 | M5-03, M5-04 |
| FR-DEF-03 | M5-03, M5-05 |
| FR-DEF-04 | M5-06 |
| FR-DEF-05 | M5-07, M6-06 |
| FR-INB-01 | M6-01, M6-03, M6-08 |
| FR-INB-02 | M6-05 |
| FR-INB-03 | M6-06, M6-07 |
| FR-INB-04 | M6-04 |
| FR-RPT-01 | M8-01 |
| FR-RPT-02 | M8-03, M8-04 |
| FR-RPT-03 | M8-06 |
| FR-RPT-04 | M8-07, M8-08 |
| AI-01 | M2-07 |
| AI-02 | M2-05, M2-07 |
| AI-03 | M2-04, M2-11 |
| AI-04 | M1-15, M2-04 |
| AI-05 | D-008 |
| AI-06 | M2-04, M9-09 |
