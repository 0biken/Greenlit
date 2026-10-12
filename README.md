<p align="center">
  <img src="Greenlit_Logo_Pack/greenlit-logo.svg" alt="Greenlit Logo" width="360" />
</p>

<p align="center">
  <strong>The immutable QA record that links requirements, tests, evidence, and defects — making release readiness unambiguous.</strong>
</p>

<p align="center">
  <a href="#overview"><img src="https://img.shields.io/badge/Status-Milestone%201%20Ready-2ea44f?style=flat-square" alt="Status"></a>
  <a href="#technology-stack"><img src="https://img.shields.io/badge/Django-6.1-092E20?style=flat-square&logo=django&logoColor=white" alt="Django"></a>
  <a href="#technology-stack"><img src="https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React"></a>
  <a href="#technology-stack"><img src="https://img.shields.io/badge/TypeScript-5.x-3178C6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript"></a>
  <a href="#security--tenancy"><img src="https://img.shields.io/badge/PostgreSQL-16%20RLS-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL"></a>
  <a href="#quality-assurance--testing"><img src="https://img.shields.io/badge/Test%20Suite-450%2B%20Passing-brightgreen?style=flat-square" alt="Tests"></a>
</p>

---

## Table of Contents

- [Overview](#overview)
- [The Problem Greenlit Solves](#the-problem-greenlit-solves)
- [Core Architectural Principles](#core-architectural-principles)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [Repository Structure](#repository-structure)
- [Quick Start & Local Setup](#quick-start--local-setup)
  - [Option A: Full Services via Docker Compose](#option-a-full-services-via-docker-compose)
  - [Option B: Bare-Metal Local Development (No Docker)](#option-b-bare-metal-local-development-no-docker)
  - [Option C: Instant Frontend Preview (Mock Mode)](#option-c-instant-frontend-preview-mock-mode)
- [Seed Data & Demo Accounts](#seed-data--demo-accounts)
- [Quality Assurance & Verification](#quality-assurance--verification)
- [Specifications & Design Documents](#specifications--design-documents)
- [Roadmap & Milestones](#roadmap--milestones)
- [Security & Compliance Highlights](#security--compliance-highlights)

---

## Overview

**Greenlit** is a modern QA system of record built for software teams, product agencies, and QA leads who need indisputable proof of what was tested, verified, and shipped.

In traditional setups, QA work is scattered across Google Docs, Jira comments, Figma inspects, Slack threads, and unindexed screenshot folders. Test records drift out of sync with product changes, fixes are marked resolved without verification, and release sign-offs happen on trust rather than evidence.

Greenlit replaces that fragmentation with a single, verifiable chain of custody:

```text
Requirement ──► Test Plan ──► Run Execution ──► Defect ──► Fix Retest ──► Audited Sign-Off
     │              │               │               │             │               │
  (PRD/Spec)   (Versioned)    (Proof Files)   (Separated)   (Fixer Blind)    (Client Ready)
```

---

## The Problem Greenlit Solves

| What Breaks in Traditional QA | How Teams Suffer | How Greenlit Enforces It |
| :--- | :--- | :--- |
| **Silent Slip** | A ticket is marked "Fixed" in Jira, but QA never validates it on staging. Bug ships to production. | **Segregated Verification Gate:** Tracker status and QA verification status are strictly isolated. A developer cannot verify their own fix. |
| **Record Drift** | Requirements change mid-cycle; test plans never get updated. Coverage numbers are fictitious. | **Bidirectional Traceability:** Requirements maintain an immutable link to test cases and run histories. Stale tests are flagged automatically. |
| **Evidence Amnesia** | A bug is marked "Passed", but nobody recorded evidence. When a regression hits, nobody can reproduce the test conditions. | **Tamper-Evident Attachments:** Test runs require direct byte-inspected uploads, SHA-256 checksummed and scanned before release. |
| **Manual Release Reporting** | Assembling a release report for clients or stakeholders takes hours of manual screenshot collection. | **Instant Audited Release Reports:** Automated blocker accounting, verified coverage metrics, and cryptographic sign-off audit trails. |

---

## Core Architectural Principles

1. **Enforced at the Database, Not Just Code**  
   Every multi-tenant table enforces forced PostgreSQL **Row-Level Security (RLS)**. The web application runs under an unprivileged `greenlit_app` role without table ownership or RLS bypass privileges. Same-tenant foreign key constraints are enforced via triggers.
2. **Strict Segregation of Duties (Fixer-Cannot-Verify)**  
   The user who marks a defect fixed in an issue tracker cannot retest or verify the fix. Retests mandate reproducible evidence uploads and audit logs.
3. **Traceability by Construction**  
   Every defect, run, and retest traces directly back to a parent requirement and test plan revision. Display IDs (e.g. `HUBE-DEF-12`, `KOLA-REQ-04`) are sequentially scoped per project.
4. **Asynchronous Heavy Lifting**  
   File uploads use pre-signed S3 links directly from the browser; virus scanning (ClamAV), byte-sniffing validation, digest deliveries, and AI drafting execute strictly off the request path via Celery workers.
5. **Zero-Drift API & Front-End Types**  
   The front-end TypeScript types (`schema.d.ts`) are generated directly from the Django OpenAPI schema (`openapi.yaml`). CI checks ensure they never drift.

---

## Key Features

### 📥 1. The QA Inbox
A unified, keyboard-navigable triage cockpit (`j` / `k` navigation) that surfaces everything requiring attention:
- **Unretested Fixes:** Defects marked fixed waiting for QA verification.
- **Stale Tests:** Test cases unexecuted beyond the project aging threshold (default: 30 days).
- **Uncovered Requirements:** Requirements lacking an active test case.
- **Overdue Retest Escalations:** Critical blockers flagged with 48h and 96h escalation bands.
- **Snooze with Justification:** Temporary dismissal requires a mandatory reason and expiry timestamp.

### 📋 2. Versioned Test Planning & Requirements
- Direct intake of PRDs and product specifications.
- Test cases revisioned immutably: when requirements shift, test cases produce clear diff histories.
- Project-level configurations (`stale_after_days`, `retest_escalation_hours`, `aging_days` per severity).

### 🔍 3. Proof-Backed Run Execution
- Direct-to-storage signed uploads (S3 or local storage).
- Content-type verification by magic bytes (HTML/SVG rejected to prevent XSS).
- File quota accounting (20 MB document limit, 200 MB evidence limit, 10 GB org quota).
- Background ClamAV malware scanning with SHA-256 fingerprinting before files are released.

### 🛡️ 4. Defect Lifecycle & Segregated Verification
- Dual-state tracking: **Issue Tracker State** (Open, Fixed, Wontfix) vs **QA State** (Open, Retest In Progress, Verified, Failed).
- Audit trails recording every state transition with timestamp and user ID.
- Access policies that return standard `404 Not Found` (never `403`) for non-accessible resources to prevent tenant enumeration.

### 🚀 5. Release Dashboard & Client-Ready Sign-Off
- Live release readiness metric (% verified coverage).
- Blocker summary by severity (Critical, High, Medium, Low).
- Formal release sign-off mechanism with audit recording and stakeholder notes.

---

## System Architecture

```mermaid
flowchart TD
    subgraph Client["Client Tier"]
        Browser["React 19 SPA (Vite + TS)<br/>TanStack Query + Radix UI"]
    end

    subgraph Edge["Gateway & Auth"]
        AllAuth["Allauth Headless Auth<br/>Argon2id + TOTP 2FA"]
        CSRF["CSRF & Rate Limiter<br/>(Redis In-Memory)"]
    end

    subgraph Application["Django 6 Application Layer"]
        Policy["Central Policy Engine<br/>(apps/core/policy.py)"]
        Modules["Core Apps<br/>Requirements · Plans · Runs<br/>Defects · Inbox · Reports"]
        FileService["File Service<br/>(Pre-Signed Links)"]
    end

    subgraph Data["Persistence & Storage Tier"]
        PG[("PostgreSQL 16+<br/>Forced Row-Level Security<br/>Same-Org FK Triggers")]
        Redis[("Redis 7<br/>Rate Limits & Cache")]
        S3[("S3 / MinIO<br/>Object Storage")]
    end

    subgraph Workers["Asynchronous Workers"]
        Celery["Celery Task Workers"]
        ClamAV["ClamAV Antivirus Scanner"]
    end

    Browser -->|REST API with CSRF & X-Org| Edge
    Edge --> Application
    Application --> Policy
    Policy --> Modules
    Modules -->|Scoped Queries| PG
    FileService -->|Signed URL| Browser
    Browser -->|Direct Upload| S3
    Celery --> S3
    Celery --> ClamAV
    Celery --> PG
    Modules -->|Job Dispatch| Redis
    Redis --> Celery
```

---

## Technology Stack

| Layer | Technology | Rationale & Architectural Notes |
| :--- | :--- | :--- |
| **Front End** | React 19, TypeScript, Vite | Single-page application with type-safety and instantaneous HMR. |
| **UI Primitives** | Radix UI, Custom Design System | Fully accessible headless components styled with Greenlit tokens. |
| **Typography** | Newsreader & IBM Plex (Sans/Mono) | Editorial legibility paired with dense technical layout. |
| **State Management** | TanStack Query (React Query v5) | Robust server-state caching, background refetching, and optimistic mutations. |
| **Back End** | Django 6, Django REST Framework | Python 3.12+ backend with mature ORM, migrations, and clean modular app structure. |
| **Database** | PostgreSQL 16+ | Forced **Row-Level Security (RLS)**, same-tenant foreign key triggers, JSON fields. |
| **Task Queue** | Celery 5 + Redis 7 | Background file scanning, digest delivery, and asynchronous job execution. |
| **Authentication** | `django-allauth` (Headless API) | Verified email requirement, Argon2id hashing, TOTP 2FA, session rotation. |
| **File Storage** | AWS S3 / MinIO | Pre-signed upload links, sandboxed attachments, byte-level file inspections. |
| **Security Scanning** | ClamAV Antivirus | Pre-download malware scanning of all attachments. |
| **Tooling & Linting** | Ruff, Mypy, Oxlint, Vitest, Pytest | Sub-second Python linting, strict static typing, and high-speed test runners. |

---

## Repository Structure

```text
Greenlit/
├── api/                          # Django 6 Backend Application
│   ├── apps/
│   │   ├── core/                 # Tenancy, RLS policies, audit logs, jobs, memberships
│   │   ├── defects/              # Defect tracking, fixer-blind retests, status lifecycle
│   │   ├── files/                # Pre-signed S3 links, quota checks, ClamAV integration
│   │   ├── inbox/                # Unified QA triage inbox, snooze mechanisms, SLA bands
│   │   ├── plans/                # Test suites, test cases, versioned test plans
│   │   ├── reports/              # Project dashboards, release summaries, sign-offs
│   │   ├── requirements/         # Spec intake, requirement records, revisions
│   │   └── runs/                 # Test runs, execution records, evidence links
│   ├── config/                   # Django settings (base, local, test, production), URLs
│   ├── openapi.yaml              # Contract schema source of truth
│   └── manage.py
├── web/                          # React 19 + TypeScript Front End
│   ├── src/
│   │   ├── api/                  # Generated TypeScript client & OpenAPI definitions
│   │   ├── app/                  # Router, organisation gate, top bar, keyboard shortcut overlay
│   │   ├── design/               # Design tokens, Radix UI components, Mark, StatusChip
│   │   ├── features/             # Feature views (Inbox, Dashboard, Releases, Members)
│   │   └── mocks/                # MSW mock handlers for standalone frontend development
│   └── package.json
├── tests/                        # Comprehensive Backend Test Suites
│   ├── isolation/                # Cross-tenant leak detection & foreign-key trigger tests
│   ├── permissions/              # Endpoint-by-role security matrix validation
│   └── security/                 # MFA, allauth surface, hardening, rate-limit tests
├── docs/                         # Architecture decision records & runbooks
├── Greenlit_Logo_Pack/           # Official SVG & PNG branding assets
├── docker-compose.yml            # Local development orchestration (Postgres, Redis, MinIO, Mailpit, ClamAV)
├── TASKS.md                      # Milestone tracking and build checklist
└── README.md
```

---

## Quick Start & Local Setup

### Option A: Full Services via Docker Compose

Run all supporting infrastructure services with Docker:

```bash
# 1. Start Postgres, Redis, MinIO, Mailpit, and ClamAV
docker compose up -d

# 2. Setup the backend virtualenv and run migrations
cd api
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env

# Run migrations as the database owner
DATABASE_URL=postgres://greenlit_owner:greenlit_owner@localhost:5432/greenlit ./.venv/Scripts/python manage.py migrate

# Seed sample organisations, projects, and users
DATABASE_URL=postgres://greenlit_owner:greenlit_owner@localhost:5432/greenlit ./.venv/Scripts/python manage.py seed

# Start the Django development server
./.venv/Scripts/python manage.py runserver
```

In a second terminal, launch the front end:

```bash
cd web
pnpm install
pnpm dev
```

Visit **http://localhost:5173** in your browser.

---

### Option B: Bare-Metal Local Development (No Docker)

If you prefer running without Docker, follow [docs/local-setup-no-docker.md](docs/local-setup-no-docker.md):

1. **PostgreSQL 16+ Setup:**  
   Initialize a local database with two distinct roles:
   - `greenlit_owner`: Used solely for schema migrations and test execution (owns tables).
   - `greenlit_app`: Used by the running web server (`NOSUPERUSER NOBYPASSRLS`).

2. **Run Migrations & Seed:**
   ```bash
   cd api
   DATABASE_URL=postgres://greenlit_owner:greenlit_owner@localhost:5432/greenlit ./.venv/Scripts/python manage.py migrate
   DATABASE_URL=postgres://greenlit_owner:greenlit_owner@localhost:5432/greenlit ./.venv/Scripts/python manage.py seed
   ./.venv/Scripts/python manage.py runserver
   ```

3. **Start the Web App:**
   ```bash
   cd web && pnpm install && pnpm dev
   ```

---

### Option C: Instant Frontend Preview (Mock Mode)

You can preview and interact with the complete front-end user experience without spinning up Python, Postgres, or Redis. Greenlit includes a comprehensive **Mock Service Worker (MSW)** layer:

```bash
cd web
pnpm install
pnpm dev:mock
```

Open **http://localhost:5173** to test the QA Inbox, Project Dashboard, keyboard navigation, and release sign-off flows immediately.

---

## Seed Data & Demo Accounts

The `seed` management command bootstraps two separate tenant organisations (`Karma Groups` and `Globex Corporation`) with full role coverage:

| Email Address | Role | Organization | Password | Permissions & Intended Test Flow |
| :--- | :--- | :--- | :--- | :--- |
| `owner@karmagroups.example` | **Owner** | Karma Groups | `password1234` | Full tenant authority, billing, member deletion, MFA enforced |
| `admin@karmagroups.example` | **Admin** | Karma Groups | `password1234` | Organization settings, user invitations, MFA enforced |
| `lead@karmagroups.example` | **QA Lead** | Karma Groups | `password1234` | Test plan publishing, release sign-offs, retest assignments |
| `qa@karmagroups.example` | **QA Engineer** | Karma Groups | `password1234` | Test execution, defect filing, retest verification with evidence |
| `dev@karmagroups.example` | **Developer** | Karma Groups | `password1234` | Marking defects fixed (cannot verify own fixes) |
| `viewer@karmagroups.example` | **Viewer** | Karma Groups | `password1234` | Read-only dashboards and release report access |
| `scorpio@globex.example` | **Owner** | Globex Corp | `password1234` | Second isolated tenant for validating cross-tenant security |

**Pre-Seeded Projects in Karma Groups:**
- `HUBE`: Hube Checkout (`Hube Retail`)
- `KOLA`: Kola Banking App (`Kola Finance`)
- `MARA`: Mara Bookings (`Mara Travel`)

---

## Quality Assurance & Verification

Greenlit maintains a strict zero-tolerance policy for linting, typing, and test failures. All checks can be executed locally:

### Backend Checks
```bash
cd api

# 1. Lint and code style validation
./.venv/Scripts/ruff check .
./.venv/Scripts/ruff format --check .

# 2. Strict static typing
./.venv/Scripts/mypy apps config

# 3. Test suite execution (requires Postgres test database)
DATABASE_URL=postgres://greenlit_owner:greenlit_owner@localhost:5432/greenlit pytest
```

### Frontend Checks
```bash
cd web

# 1. High-speed Oxlint check
pnpm lint

# 2. TypeScript compilation check
pnpm typecheck

# 3. Production build test
pnpm build

# 4. Verify API schema synchronization
pnpm check:api
```

---

## Specifications & Design Documents

Greenlit is built strictly spec-first. Every implementation detail is anchored to comprehensive architectural specifications:

| Document | Purpose & Scope |
| :--- | :--- |
| 📄 [Greenlit PRD v2.md](Greenlit%20PRD%20v2.md) | Product requirements, problem statement, user personas, and acceptance criteria. |
| 🏗️ [Greenlit Technical Architecture.md](Greenlit%20Technical%20Architecture.md) | System components, module boundaries, database rules, and tech stack rationale. |
| 🗄️ [Greenlit Data Model and Traceability Spec.md](Greenlit%20Data%20Model%20and%20Traceability%20Spec.md) | Schema definitions, entity relations, immutability rules, and audit patterns. |
| 🔒 [Greenlit Security and Tenancy Design.md](Greenlit%20Security%20and%20Tenancy%20Design.md) | Forced RLS implementation, cross-tenant isolation, MFA rules, and cryptography. |
| 🤖 [Greenlit AI Behaviour Spec.md](Greenlit%20AI%20Behaviour%20Spec.md) | Guardrails, prompt engineering standards, metering, and provenance rules. |
| 🎨 [Greenlit UX Flows and Wireframes.md](Greenlit%20UX%20Flows%20and%20Wireframes.md) | UI wireframes, keyboard interaction specs, and component layouts. |
| ✅ [TASKS.md](TASKS.md) | Full engineering work breakdown, milestones M0 through M10, and decision records. |

---

## Roadmap & Milestones

- [x] **M0: Project Foundations & Infrastructure** (Specs, Docker, PostgreSQL RLS primitives, CI).
- [x] **M1: Multi-Tenant Core, Auth & Spine** (Allauth headless auth, TOTP 2FA, rate limits, file service, tenancy policy).
- [x] **M1.5: UI Shell & Front-End Cockpit** (QA Inbox, Project Dashboard, Release Sign-off screen, MSW mocks).
- [x] **M1.8: Real Endpoints Spine** (Full Django REST models, services, migrations, and viewsets for requirements, plans, runs, defects, and reports).
- [ ] **M2: Specification Intake & Test Plan Generation** (Document parsing, AI test plan drafts with human review).
- [ ] **M3: Defect & Execution Workflows** (Direct evidence uploads, Jira bi-directional synchronization).
- [ ] **M4: Automated Digest & Escalation Worker** (07:00 daily email digest, 48h/96h SLA escalations).

---

## Security & Compliance Highlights

- **Strict Row-Level Security:** Enforced by PostgreSQL policies (`ALTER TABLE ... FORCE ROW LEVEL SECURITY`). Even if an application query omits tenant filtering, the database prevents cross-tenant data access.
- **Zero Enumeration Surface:** Requests referencing unauthorized objects or cross-tenant IDs always respond with `404 Not Found` rather than `403 Forbidden`.
- **Argon2id & Rotatable Encryption:** Password hashing powered by Argon2id; two-factor authentication secrets encrypted at rest.
- **Hardened Security Headers:** Strict Content Security Policy (`default-src 'self'`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and strict `Permissions-Policy`.
- **Antivirus Pipeline:** ClamAV container inspects all uploads prior to download link generation.

---

<p align="center">
  Built with precision by Obioma Ezeocha & Sandy Star · Designed for bulletproof software releases.
</p>
