# Greenlit: from here to Beta, then Launch

Handover list for the next developer. It covers only what is left; [TASKS.md](TASKS.md) stays the master checklist and the six `Greenlit *.md` specs win on any conflict. Read [CLAUDE.md](CLAUDE.md) first (commands, and the rules that must not be broken). Task IDs below are TASKS.md IDs; tick them off there as well as here.

Status as of 2026-10-16: milestones M0 to M6 (except M6-09) are built. Left: screenshot and report import (M7), release reports (M8-04, M8-05), hardening (M9), and the gates.

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

Release plan (PRD, "Release plan"): Phase 1 build v1 → **Beta gate** (M10) → Phase 2 private beta with design partners → **General launch** (end of phase 2).

---

## Stage A. Unblock first (decisions, nothing else moves without these)

Do these in week 1. Each is a short decision record in `docs/decisions/` (or the repo's existing place for them).

- [ ] **A1 · D-00** Name the lead engineer and the security owner (SEC open questions); confirm the Django back end.
- [ ] **A2 · D-001 to D-006, D-010** Write the seven decision records for choices already made in code (monolith, Django/DRF, React/Vite, Postgres RLS, case revisions, Celery/Redis, polling vs SSE). Record what the code actually does.
- [ ] **A3 · D-007** Hosting platform and region. Latency test from Lagos and London against 2 or 3 regions; check cross-border transfer rules (SEC §7). Blocks staging and production. Record the region in the vendor list.
- [ ] **A4 · D-008** AI provider. Needs A8 (test set) to score candidates. Terms must exclude training on customer data and limit retention. Until signed, the app stays on the stub or Gemini dev provider and AI is off for design partners.
- [ ] **A5 · D-009** Email provider with bounce handling; no document contents in emails (titles and links only).
- [ ] **A6 · G-09** Decide merge semantics for "merge with an existing defect" (which fields win, where evidence goes, what the audit log records). Add to the data model spec. Blocks M7-05.
- [ ] **A7 · P0-01** Interview QA teams; answer the PRD §11 open questions (retest window, who retests at agencies, Jira needs, pricing).
- [ ] **A8 · P0-02** Build the AI test set: 10 PRDs with expert requirement lists and test plans, 5 screenshot sets, 5 old QA reports (permission or anonymised). Blocks M2-10, M10-02 and A4.
- [ ] **A9 · P0-03 / P0-05** Clickable mock-ups tested with 5 QA engineers; gate: other teams confirm the problem. If the gate fails, stop and re-plan; do not push on.

## Stage B. Finish the build (code)

Order matters: B1 before B6 (the eval needs the test set); B2 before B3.

### B1. AI quality harness
- [ ] **M2-10** `tests/ai_eval/` runner scoring recall, precision, coverage, keep rate, citation accuracy, report accuracy, injection pack. CI blocks a merge touching `api/ai/` if a score drops.
- [ ] **M2-11** Prompt-injection pack: at least 30 hostile documents; every one gives schema-valid output, no injected content, no record changes.

### B2. Screenshots and import (M7)
- [ ] **M7-01** Screenshot batch upload (up to 30, ordered, renamable, test-data notice).
- [ ] **M7-02** F3 `draft_screen_ideas`.
- [ ] **M7-03** Convert an idea to a draft case in one click.
- [ ] **M7-04** Past QA report upload (PDF, DOCX); embedded images kept as evidence.
- [ ] **M7-05** F4 `import_report` (needs A6).

### B3. Release report (M8)
- [ ] **M8-04** F5 `draft_release_report`: facts-only input, every claim cites record IDs, numbers and readiness line verified, never recommends shipping when Not ready yet.
- [ ] **M8-05** Report editor with each claim linked to its run or defect.

### B4. Metrics
- [ ] **M6-09** Reminder action rate within 72 hours, retest lag, escaped closures.

### B5. Hardening (M9)
- [ ] **M9-01** Search (Postgres full-text, org-scoped, in the isolation suite).
- [ ] **M9-02** Empty, loading and error states for every screen in UX §9.
- [ ] **M9-03** WCAG 2.2 AA: axe in CI, manual keyboard and screen-reader pass on Inbox, draft review, run and sign-off; reduced motion; 44 px targets.
- [ ] **M9-04** Performance: 95% of page loads under 2.5 s from Lagos and London (needs A3 staging).
- [ ] **M9-05** Monitoring and alerts (uptime, errors, speed, jobs, AI failure rate and cost, security, backups).
- [ ] **M9-06** Backups: daily, 30 days, versioned files; monthly timed restore test against the 8-hour target; written runbook.
- [ ] **M9-07** Deletion and 30-day recovery with a nightly `purge` job.
- [ ] **M9-08** Organisation export (JSON plus files, including audit log); user account-data download and delete.
- [ ] **M9-09** Hourly `usage_rollup`; AI usage page in Settings.

### B6. Every build task, every time
- [ ] Each new endpoint has a permission-table row and is in the isolation suite; each new tenant table has RLS in its migration; each new module is behind a flag. `pnpm gen:api` run and committed.

## Stage C. Production readiness

- [ ] **C1** Stand up staging and production in the A3 region (TASKS M0-07). Secrets in a secrets manager; app connects as the restricted role only; TLS 1.2+, HSTS, CSP, frame-ancestors none.
- [ ] **C2** Run SEC §"Beta" items one by one and tick the SEC checklist: Argon2id passwords and breached-password check, brute-force slowdown, session timeouts, sign out everywhere, 30-minute recovery links, TOTP required for owners and admins, signed 15-minute file links from a separate domain, malware scan, file-type allow-list by content, rate limits, dependency scanning and secret scanning in CI, second-reviewer rule. (= **M10-04**.)
- [ ] **C3** Error monitoring with personal data and document text scrubbed before sending.
- [ ] **C4** Email domain set up (SPF, DKIM, DMARC) and bounce handling working (A5).
- [ ] **C5** Availability target 99.5% monthly: uptime check and on-call/alert route named.
- [ ] **C6 · M9-10** Compliance paperwork: data processing agreement and privacy policy (name the reviewer and a date; open SEC question), sub-processor list matching SEC §9 vendor table, public security page, incident response runbook.

## Stage D. Beta gate (M10): all must be true before the first design partner

- [ ] **M10-01** Customer-zero release run PRD to sign-off with nothing left untested, unretested or unclosed.
- [ ] **M10-02** AI scores at beta targets: recall ≥ 85%, precision ≥ 80%, case coverage ≥ 70%, keep rate ≥ 75%, citation accuracy ≥ 98%, report accuracy 100%, injection pack 100%.
- [ ] **M10-03** Isolation suite and permission table green on staging, every endpoint covered.
- [ ] **M10-04** Every Beta item in SEC checked (C2).
- [ ] **M10-05** Accessibility (M9-03) and performance (M9-04) met.
- [ ] **M10-06** Restore test done within the last month.

## Stage E. Private beta (Phase 2)

- [ ] **E1** Pick 3 to 5 design partners (include one agency and one in-house team, ideally one in Nigeria and one in Europe). Sign the data processing agreement before data goes in.
- [ ] **E2** Onboarding: invite flow, sample project, a one-page "your first release" guide, a feedback channel and a weekly check-in.
- [ ] **E3** Decide two-step verification for all members if any partner needs it (SEC open question).
- [ ] **E4** Set usage caps and cost alerts for AI per organisation (risk: AI cost outgrows revenue).
- [ ] **E5** Track the PRD success metrics through the beta: reminder action rate, retest lag, escaped closures, AI draft keep rate, weekly active QA users. Review weekly; tune reminders if they turn to noise.
- [ ] **E6** Triage bugs by severity; no data-isolation bug is ever deferred.
- [ ] **E7** Phase 2 features, in this order, each behind its flag: Jira sync (read-only first), CSV/JSON result import, Figma import, weighted QA debt score.
- [ ] **E8** Fix the PRD §11 pricing question with partner input; build the plan limits (10 GB per organisation on starter) and AI credits.
- [ ] **E9** Monthly restore test continues; keep the last-month evidence.

## Stage F. General launch (end of phase 2; SEC "General launch")

- [ ] **F1** External penetration test: set the budget and date (open SEC question); fix all critical and high findings; retest.
- [ ] **F2** Written security policies; first quarterly access review done and scheduled.
- [ ] **F3** Re-check availability (99.5%) and performance (2.5 s) over the beta period with real numbers.
- [ ] **F4** Billing and sign-up: public pricing page, self-serve organisation creation, terms of service and privacy policy published.
- [ ] **F5** Public website and security page; support inbox and status page.
- [ ] **F6** Launch checklist sign-off by the security owner and lead engineer; flip flags on for general availability; announce.
- [ ] **F7** Post-launch: 30-day review of metrics, incidents and costs; then plan Phase 3 (GitHub change impact, Playwright/Cypress adapters, MCP connector, SSO, SOC 2).

---

## Suggested order and rough timing (one full-time engineer)

| Weeks | Work |
| --- | --- |
| 1 | Stage A (decisions); start A7 to A9 in parallel with the founder |
| 2 to 4 | B1, B2, B3, B4 |
| 5 to 7 | B5, C1 to C5 |
| 8 | C6, Stage D, fix what the gate finds |
| 9 onward | Stage E private beta; E7 features as capacity allows |
| End of beta | Stage F |

Re-plan after A9. If a gate is missed, extend the phase rather than moving on (PRD).
