# Greenlit Technical Architecture

Oct 4, 2026 ·&#32;

## Overview

Greenlit v1 is one web app with one API, one PostgreSQL database, a job queue and file storage, all on managed services. It is built as a single deployable application split into clear modules, not as microservices.

**Principles**

1. **Small team, boring technology.** Pick well-known tools with good documentation and many developers who know them. Novelty goes into the product, not the stack.
2. **Managed over self-run.** Pay for a managed database, queue and storage, so nobody is on call for servers.
3. **The database enforces the rules that matter.** Tenant isolation and immutability are enforced in PostgreSQL, not only in code (security design, section 5).
4. **Anything slow runs in the background.** File processing, AI drafting, reminders and digests never block a web request.
5. **One way to do each thing.** One permission module, one AI client, one file service.

Choices marked *proposed* need the lead engineer's sign-off. Each one is recorded as a decision record (section 10) when it is made.

## System diagram

The API answers requests quickly and hands anything slow to workers through the queue. Only workers call the AI provider and the email service.

*Text version; the original diagram was lost when this document was exported. Reconstructed from the rest of the specs, so check it against the source diagram.*

| Part | Talks to |
| --- | --- |
| Web app (React single-page app in the browser) | The API; file storage only through signed upload and download links the API issues |
| API (Django and Django REST Framework) | PostgreSQL, the job queue, file storage (to sign links) |
| Job queue (Redis) | Carries jobs from the API and the scheduler to the workers |
| Workers (Celery) | PostgreSQL, file storage, the AI provider, the email service |
| PostgreSQL | Read and written by the API and the workers only |
| File storage (S3-compatible, private) | Reached by browsers only through signed links |
| AI provider (outside) | Called only by workers, through `api/ai/` |
| Email service (outside) | Called only by workers: digests, alerts, invites, account emails |

## Technology choices

The proposed stack is a React and TypeScript front end, a Django API in Python, and PostgreSQL. Python is chosen for the back end because document parsing and AI tooling are strongest there, and Django brings sign-in, migrations and an admin screen for free.

| Layer | Proposed choice | Why | Alternative |
| --- | --- | --- | --- |
| Front end | React with TypeScript, built with Vite, as a single-page app | The app sits behind sign-in, so server rendering adds little; frontend skills are common | Next.js, if public marketing pages move into the same codebase |
| UI components | Accessible headless primitives (for example Radix UI) styled with the brand guide's tokens | Keyboard and screen-reader support out of the box; looks like Greenlit, not a template | A full component kit, at the cost of a generic look |
| API | Django with Django REST Framework | Mature auth, ORM, migrations, admin; large talent pool in Nigeria | Node.js with NestJS, to share TypeScript across front and back |
| Database | PostgreSQL 16 or later, managed | Row-level security, JSON fields, full-text search, strong constraints | None; this is fixed by the data model spec |
| Job queue | Celery with Redis | Standard with Django; retries and schedules built in | Dramatiq, or the hosting platform's own queue |
| File storage | S3-compatible object storage, private buckets | Signed links, versioning, cheap | Any S3-compatible provider |
| Sign-in | django-allauth (email, Google, authenticator-app 2FA) | Covers the security design's sign-in rules without custom code | A hosted auth service |
| Document parsing | Python libraries for PDF and DOCX text and images (for example pdfplumber, python-docx), with OCR only as fallback | Keeps page numbers and positions for provenance | A hosted document-parsing API |
| Search | PostgreSQL full-text search | Enough for v1 volumes; tenant filtering stays in one place | A search engine in phase 3 if needed |
| AI provider | Chosen by scores on the AI test set and by data terms; called through one internal client | Keeps the choice reversible | Two providers behind the same client, for fallback |
| Email | A transactional email service | Digest and alert delivery with bounce handling | Any reputable provider |
| Errors and tracing | Sentry or similar, with personal data scrubbing | Fast debugging for a small team | Platform-native logging only |
| Hosting | A managed platform with managed PostgreSQL and Redis, in one region chosen by a latency test from Lagos and London | No servers to run; scale up when needed | A major cloud (AWS, GCP) once there is ops capacity |

## Code structure

One repository holds the web app, the API and the job workers. Back-end code is split into Django apps that match the PRD's module codes, and modules talk to each other only through their service functions, never by reaching into another module's tables.

```
greenlit/
  web/                 React + TypeScript app
    src/features/      one folder per module (plans, runs, defects, inbox...)
    src/design/        brand tokens, components, status marks
  api/
    core/              organisations, members, permissions, audit log, ID counters
    requirements/      PLAN: source documents, requirements
    plans/             TC: plans, versions, cases, revisions, diffs
    runs/              RUN: runs, results, evidence
    defects/           DEF: defects, retests, status rules
    inbox/             INB: derived states, reminders, digests
    reports/           RPT: releases, readiness, reports, sign-off
    ai/                one AI client, prompts, schemas, checks, metering
    files/             uploads, scanning, signed links, parsing
  tests/
    isolation/         cross-tenant suite (runs on every deploy)
    permissions/       endpoint x role table
    ai_eval/           quality test set runner
  docs/decisions/      decision records
```

**Rules**

- `core` owns tenancy: one middleware sets the organisation scope for every request and every job.
- Only `ai/` calls the model provider. Feature modules ask it for a draft and receive checked objects.
- Only `files/` touches storage. Other modules handle file IDs, never paths.
- The API is described with an OpenAPI schema generated from the code, and the front end's types are generated from it, so the two cannot drift.

## Key flows

Two flows carry most of the risk: turning an upload into AI drafts, and reminding people about unretested fixes. Both run in the background and report progress back to the app.

**Upload to AI draft (FR-PLAN-01 to 04)**

1. The browser asks the API for an upload link; the API checks role and project and returns a signed upload URL scoped to the organisation's folder.
2. The browser uploads the file straight to storage, then tells the API it is done.
3. The API records a `source_document` and queues a `scan_and_parse` job.
4. The worker scans the file for malware, extracts text and images with page positions, and stores the extraction.
5. The worker queues `draft_requirements`. The AI module builds a request from this one document, calls the provider, and checks the reply (schema, IDs, quotes found in the text).
6. Checked drafts are saved with `review_state` = draft; dropped items are logged. Each step updates a job record that the browser polls every few seconds, or receives through server-sent events (proposed).
7. The user reviews drafts; each accept or reject writes the record and an audit event.

**Retest reminder (FR-INB-02, 03)**

1. A developer sets BUG-1042 to Fixed. The defects module records `fixed_at` and writes an audit event.
2. The derived-state view now lists BUG-1042 as Needs retest for its owner.
3. Every 15 minutes the `reminders` job, run once per organisation, finds items past 48 hours and 96 hours that have not been notified at that level, and writes notifications.
4. At 07:00 in each user's time zone, the `digest` job sends one email per user with open items, skipping users with none.
5. Critical items (closed with a failed retest) skip the digest and notify the owner and QA lead within one job cycle.

## Background jobs and schedules

Every job carries one `org_id`, is safe to run twice, and retries on failure with growing delays. Jobs that fail for good land in a list an admin can inspect and re-run.

| Job | Trigger | Does | Retries |
| --- | --- | --- | --- |
| scan\_and\_parse | File upload completed | Malware scan, text and image extraction with positions | 3 |
| draft\_requirements | scan\_and\_parse finishes on a PRD, or PRD text is pasted (F1) | AI extraction of requirements, checks, saves drafts | 1 retry on bad output, 3 on provider errors |
| draft\_cases | User starts F2 | AI test case drafting for chosen requirements | Same as above |
| draft\_screen\_ideas | scan\_and\_parse finishes on a screenshot batch (F3) | AI test ideas per screenshot | Same as above |
| import\_report | scan\_and\_parse finishes on a past QA report (F4) | AI defect proposals from a past report | Same as above |
| draft\_release\_report | QA lead requests F5 | Builds facts, calls AI, checks numbers against facts | Same as above |
| reminders | Every 15 minutes (proposed), per organisation | Escalations at 48 and 96 hours, critical alerts | 3 |
| digest | Daily, 07:00 per user's time zone | One email per user with open items | 3 |
| stale\_check | Nightly | Marks test cases Stale (30 days, or changed requirement) | 3 |
| purge | Nightly | Hard-deletes data past its 30-day recovery window | 3 |
| usage\_rollup | Hourly | Totals AI credits and cost per organisation, triggers 80% and 100% notices | 3 |

## Environments, deployment and CI/CD

There are three environments, and code reaches production only through the pipeline after every required test passes. Nobody deploys from a laptop.

| Environment | Purpose | Data |
| --- | --- | --- |
| Local | Development on each engineer's machine, with Docker Compose for PostgreSQL, Redis and S3-compatible storage | Seed data only |
| Staging | Every merged change, for review and the isolation suite | Generated sample data for two or more organisations; never real customer data |
| Production | Customers | Real data, backed up daily |

**Pipeline on every pull request**

1. Lint and type checks (front and back end).
2. Unit and API tests, including the endpoint × role permission table.
3. Dependency and secret scanning.
4. Database migrations checked: they must apply cleanly and must not drop row-level security policies.

**On merge to main**

1. Build and deploy to staging.
2. Run the cross-tenant isolation suite against staging.
3. Promote to production when the suite passes, with migrations run first. Rollback means redeploying the previous build; migrations are written to be backward-compatible for one release.

The AI quality test set runs on any change under `api/ai/` and blocks the merge if a score drops.

## Operations

A small team needs to know about problems before customers do, without staring at dashboards. Alerts go to the founder and lead engineer by email and chat.

| Area | What is tracked | Alert when |
| --- | --- | --- |
| Uptime | External check on the app and API every minute | Down for 3 minutes |
| Errors | Error rate and new error types | A new error type, or rate above normal |
| Speed | 95th-percentile page and API response times | Above 2.5 seconds for 15 minutes |
| Jobs | Queue length, failures, time since last reminder and digest run | Reminders not run for 1 hour; any failed digest |
| AI | Calls, failures, latency, cost per organisation per day | Provider failure rate above 10%, or daily cost twice the normal level |
| Security | Failed sign-ins, cross-organisation lookups, row-level security errors | Any row-level security error; sign-in spikes |
| Backups | Last successful backup and last restore test | Backup older than 26 hours; restore test missed |

**Cost**

A monthly review covers hosting, storage and AI spend per active organisation, against the AI cost target in the AI behaviour spec. Hosting is sized for the beta and scaled on measured load, not ahead of it.

## Build order

Foundations come first because tenancy, permissions and the isolation suite are hard to add later. Each module ships behind a feature flag to staging as soon as it works.

*Text version; the original diagram was lost when this document was exported. Reconstructed from the rest of the specs, so check it against the source diagram.*

| Weeks | Work |
| --- | --- |
| 5 to 6 | Foundations: repository, CI, environments, sign-in, organisations, members and projects, row-level security and the tenancy middleware, the permission module and its test table, audit log, ID counters, file service, the isolation suite |
| 7 to 8 | PLAN and TC: source documents, parsing, requirements, the AI client, F1 and F2, draft review, plans, versions, diff and rollback |
| 9 to 10 | RUN and DEF: runs, results, evidence, defects, retests and the status rules |
| 11 | INB, SHOT, IMP: derived states, QA Inbox, reminders, digest, snooze; F3 screenshot ideas; F4 report import |
| 12 to 13 | RPT: releases, readiness, F5 release report, sign-off, PDF export and share links |
| 14 | Hardening, accessibility pass, the injection pack, and one real release run end to end |

Week 14 runs one real release through Greenlit end to end, which is the gate into the private beta (PRD v2, section 10).

## Decision records and open questions

Each significant choice gets a one-page decision record in `docs/decisions/`: the context, the options, the decision, and what would make us revisit it. These are the first ten to write.

| No. | Decision | State |
| --- | --- | --- |
| 001 | Modular monolith, not microservices | Proposed |
| 002 | Django and Django REST Framework for the API | Proposed |
| 003 | React with TypeScript single-page app | Proposed |
| 004 | PostgreSQL with row-level security for tenant isolation | Proposed |
| 005 | Case identity and immutable case revisions for versioning | Proposed |
| 006 | Celery and Redis for background jobs | Proposed |
| 007 | Hosting platform and region (after the latency test) | Open |
| 008 | AI provider (after the test set and terms review) | Open |
| 009 | Email provider | Open |
| 010 | Polling or server-sent events for job progress | Open |

**Open questions**

- [ ] Who is the lead engineer, and do they agree with Python on the back end, or prefer TypeScript throughout?
- [ ] Hosting region: run the latency test from Lagos and London against two or three candidate regions.
- [ ] Is one full-time engineer plus the founder enough for the phase 1 plan, or should the scope or timeline change?
- [ ] Should the marketing site live in this repository or separately?
