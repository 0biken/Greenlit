# Greenlit Security and Tenancy Design

Oct 4, 2026 ·&#32;

## Overview

Greenlit holds unreleased product plans and bug evidence for several client companies at once, so one leak between clients could end the business. This design sets the minimum security bar for the private beta and the order in which stronger controls arrive.

**What we protect, in order of harm if exposed**

1. Client separation: one organisation's data reaching another.
2. Evidence and documents: screenshots, recordings and PRDs, which can show unreleased features and personal data.
3. The integrity of the record: sign-offs, retests and results being changed or faked.
4. Accounts: a stolen login giving access to every project the user belongs to.

**Who we protect it from**

| Threat | Example |
| --- | --- |
| A user of another organisation | Guesses a URL or ID to read another client's defect |
| A member with the wrong role | A developer marks their own fix Verified |
| An outside attacker | Credential stuffing, a malicious upload, an injected script |
| A hostile document | A PRD with hidden instructions for the AI (see the AI behaviour spec) |
| Our own mistakes | A missing filter in a new endpoint, a public storage bucket, a leaked key |

**The bar for beta**: every item marked *Beta* in this document is done and tested. Items marked *Later* have an owner and a target phase.

## Trust boundaries

Data crosses three boundaries: from browsers into Greenlit, between Greenlit's own parts, and out to vendors. Each crossing has a named check.

*Text version; the original diagram was lost when this document was exported. Reconstructed from the rest of the specs, so check it against the source diagram.*

| Zone | Components | Check at the crossing |
| --- | --- | --- |
| Outside (untrusted) | Users' browsers | Session, membership and role checks in the API; signed links for files |
| Greenlit | App and API, workers, PostgreSQL, file storage | Row-level security on every query; jobs set one `org_id`; only `files/` touches storage |
| Vendors | AI provider, email service, error monitoring, malware scanning | Only the data each needs (section 10); one organisation per AI request; document text scrubbed from error traces |

The app and API is the only way in for users; the database and file storage never accept direct requests from a browser, except downloads through a signed link the API has just issued.

## Authentication

Users sign in with email and password or with Google, and every session can be revoked. SSO for enterprise customers comes later.

| Control | Rule | When |
| --- | --- | --- |
| Sign-in methods | Email and password with verified email; Google sign-in | Beta |
| Passwords | At least 12 characters, checked against a known-breached list, hashed with Argon2id or bcrypt | Beta |
| Brute force | 5 failed attempts in 15 minutes slows that account and IP; alerts the user by email | Beta |
| Sessions | Secure, HttpOnly, SameSite cookies; 12-hour idle timeout, 30-day maximum (proposed) | Beta |
| Sign out everywhere | User can end all sessions; changing a password does this automatically | Beta |
| Account recovery | One-time email link valid for 30 minutes; never reveals whether an email is registered | Beta |
| Two-step verification | Authenticator app (TOTP); required for owners and admins | Beta for owners, optional for others |
| Organisation policy | An owner can require two-step verification for all members | Later, phase 2 |
| SSO (SAML, OIDC) | Enterprise plan | Later, phase 3 |

Use a maintained authentication library or service rather than writing sign-in code from scratch.

## Authorisation

Every request passes three checks in a fixed order, on the server, before any data is read. The interface hiding a button is never the control.

1. **Who are you?** A valid session.
2. **Which organisation?** The user has an active `membership` in the organisation named by the request. This sets the database's organisation scope (section 5).
3. **May you do this, here?** The user's role allows the action (role matrix in PRD v2, section 9), and the user can see the project (`project_member`, or owner or admin).

**Rules**

- Permissions live in one shared policy module that every endpoint calls. No endpoint writes its own role logic.
- A request for a record the user cannot see returns "not found", not "forbidden", so IDs from other organisations reveal nothing.
- Separation of duties: the person who set a defect to Fixed cannot be the only one to mark it Verified, unless they are a QA lead (proposed; confirm in phase 0).
- Sign-off and Won't fix approvals check the role again at the moment of the action, not only when the page loaded.
- Share links for reports are read-only, show only the signed version, can be revoked, and expire after 30 days by default (proposed).

**Tests**: a permission test table lists every endpoint × every role with the expected outcome. It runs on every build, and adding an endpoint without a row fails the build.

## Tenant isolation

Isolation is enforced in three places at once (database, file storage and AI requests), so one missed check in application code cannot leak data. The data model spec, section 8, defines the schema rules; this section adds enforcement and proof.

| Layer | Control | When |
| --- | --- | --- |
| Database | Row-level security on every tenant table, keyed on `org_id`; the application connects as a role that cannot bypass it | Beta |
| Database | Admin and migration roles that can bypass row-level security are never used by the running app | Beta |
| Files | Paths start with `org_id`; no public buckets; downloads only through signed links checked against the requester's organisation | Beta |
| Background jobs | Each job carries one `org_id` and sets the scope before touching data | Beta |
| AI requests | Built from one organisation's records; no shared caches or indexes | Beta |
| Search | Index entries carry `org_id`; queries filter on it in the index itself | Beta |
| Logs | Application logs record IDs, not document text or file contents | Beta |
| Dedicated database per customer | Enterprise option | Later, on demand |

**Proof**

- **Isolation suite.** Creates organisations A and B with full sample data, then calls every endpoint, file route and search as a user of A with B's IDs. Every call must return not found. Runs on every deploy (Beta).
- **Review rule.** Any change touching queries, storage paths or jobs needs a second reviewer to confirm scoping (Beta).
- **External test.** An independent penetration test focused on cross-tenant access before general launch (Later, end of phase 2).

## Data protection

All data is encrypted in transit and at rest, secrets never live in code, and backups are restored as a test every month.

| Area | Control | When |
| --- | --- | --- |
| In transit | HTTPS only (TLS 1.2 or later), HSTS on all domains | Beta |
| At rest | Database and file storage encrypted by the hosting provider | Beta |
| Secrets | API keys and credentials in a secrets manager, rotated at least yearly and when anyone with access leaves | Beta |
| Integration tokens | Jira and GitHub tokens (phase 2) encrypted at the field level, scoped to the minimum permissions | Later, phase 2 |
| File downloads | Signed links valid for 15 minutes (proposed); files never served from a public URL | Beta |
| Backups | Daily database backups kept 30 days; file storage versioned | Beta |
| Restore test | Monthly restore into a separate environment, timed against the 8-hour target | Beta |
| Data location | One hosting region chosen for latency to Nigeria and Europe; recorded in the vendor list | Beta |
| Deletion | Deleted organisations are purged from the database and files after 30 days, and from backups as they expire | Beta |

## Privacy and personal data

Greenlit processes personal data mainly on behalf of its customers, so customers are the controllers and Greenlit is their processor. The legal points here are a plan to confirm with a lawyer, not legal advice.

| Data | Whose | Role of Greenlit | Kept for |
| --- | --- | --- | --- |
| Account details (name, email) | Users | Controller | While the account exists, then 30 days |
| Product documents and test records | Customer organisations | Processor | While the organisation exists, then 30 days |
| Personal data inside evidence (names, emails in screenshots) | The customer's end users | Processor | Same as the evidence |
| Usage and AI metering logs | Users and organisations | Controller | 12 months (proposed) |

**Commitments**

- A data processing agreement offered to every customer, listing sub-processors (section 10).
- Customers can export and delete their organisation's data without contacting support.
- Users can download or delete their own account data.
- At upload, users are asked to use test data, not real customer data, in screenshots and recordings.
- Laws to check with counsel before launch: the Nigeria Data Protection Act 2023 and, for European clients, the GDPR, including the rules on transferring data across borders.

## Application security

Greenlit accepts many uploaded files and renders user-written text, so uploads and rendering are the main attack surface. The controls follow the OWASP Top 10 categories.

| Risk | Control | When |
| --- | --- | --- |
| Malicious uploads | Allow-list of file types checked by content, not extension; size limits; malware scan before the file is available | Beta |
| Files that run code | Only allow-listed file types are accepted (PRD v2, section 9); HTML and SVG are refused in v1. Documents and text files are served as downloads from a separate domain, never rendered inside the app | Beta |
| Cross-site scripting | User text rendered as plain text or sanitised Markdown; a strict Content Security Policy | Beta |
| Injection | Parameterised queries only; no string-built SQL | Beta |
| Request forgery | SameSite cookies plus CSRF tokens on state-changing requests | Beta |
| Server-side request forgery | Greenlit never fetches a URL a user supplies in v1; phase 2 integrations call only fixed provider hosts | Beta |
| Abuse and scraping | Rate limits per user, per organisation and per IP on sign-in, uploads, AI jobs and the API | Beta |
| Vulnerable dependencies | Automated dependency scanning on every build; critical fixes within 7 days | Beta |
| Secrets in code | Secret scanning on every commit | Beta |
| Security headers | HSTS, CSP, X-Content-Type-Options, frame-ancestors none | Beta |
| Code review | Every change reviewed by a second person; security-sensitive areas flagged for extra review | Beta |

## Monitoring and incident response

Security events are logged and alerted on, and there is a written plan for the first 72 hours of an incident. A small team needs the plan more than a large one, because there is no one else to call.

**Alerts (Beta)**

- Spikes in failed sign-ins, or sign-ins from new countries for owners and admins.
- Any "not found" response caused by a cross-organisation ID (possible probing).
- Rate-limit hits, unusual export or download volume from one user.
- Errors from the row-level security layer, which should never happen in normal use.

**Incident steps**

1. **Contain**: revoke affected sessions and keys, disable the affected feature if needed.
2. **Assess**: which organisations and what data, using the audit log and access logs.
3. **Notify**: affected customers without undue delay, and regulators where the law requires it (for example, the NDPA and GDPR set 72-hour reporting windows for some breaches; confirm with counsel).
4. **Fix and review**: repair the cause, add a test that would have caught it, and write a short public or customer-facing summary.

| Role | Who |
| --- | --- |
| Incident lead | Obioma Ezeocha (founder) until a security owner is hired |
| Technical lead | Lead engineer (to be named) |
| Customer contact | Founder |

## Vendors and compliance roadmap

Every outside service that touches customer data is a sub-processor and is listed for customers. Formal certification waits until customers ask for it, but the controls it needs are built in from the start.

**Sub-processors (to be chosen in the architecture doc)**

| Service | Data it sees | Requirement |
| --- | --- | --- |
| Cloud hosting and database | All data | Encryption at rest, region choice, published security report |
| File storage | Evidence and documents | Private by default, versioning, signed links |
| AI model provider | Content sent for drafting | No training on customer data, short retention, business terms signed |
| Email delivery | Names, emails, item titles in digests | No document contents in emails, only titles and links |
| Error monitoring | Error traces | Personal data and document text scrubbed before sending |
| Malware scanning | Uploaded files | Files not kept after scanning |

**Roadmap**

| Stage | What | Trigger |
| --- | --- | --- |
| Beta | Every Beta item in this document; data processing agreement; security page on the website | Before the first design partner |
| General launch | External penetration test; written security policies; access reviews every quarter | End of phase 2 |
| Enterprise | SOC 2 Type I, then Type II; SSO; dedicated database option | First enterprise deal that requires it |

## Open questions

- [ ] Which hosting region best serves Nigerian and European customers, and does it satisfy cross-border transfer rules?
- [ ] Should the fixer-cannot-verify rule apply in small teams where one person does both jobs?
- [ ] Is two-step verification for all members needed before beta for any design partner?
- [ ] Who reviews the data processing agreement and privacy policy, and by when?
- [ ] Budget and timing for the external penetration test.
- [ ] Who becomes the security owner once there is more than one engineer?
