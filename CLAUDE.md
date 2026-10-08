# Greenlit: notes for working in this repo

Spec-first project. [TASKS.md](TASKS.md) is the build checklist; the six `Greenlit *.md` specs win when they disagree with it. Find the task before building, follow its spec references, and tick it off when its "Done when" lines are true.

## Commands

- Backend (from `api/`, venv at `.venv`): `ruff check .`, `ruff format .`, `mypy apps config`, `pytest`.
- **Run migrations and tests with `DATABASE_URL` set to the owner role** (`postgres://greenlit_owner:greenlit_owner@localhost:5432/greenlit`). The default `.env` uses the restricted `greenlit_app` role, which cannot create tables or test databases.
- Local Postgres has no Windows service. Start it with `scripts/start-postgres.ps1` (PowerShell); never with `pg_ctl start` from a tool call, because the server dies when that shell is killed. Docker is optional (docs/local-setup-no-docker.md).
- Front end (from `web/`): `pnpm lint`, `pnpm typecheck`, `pnpm build`. After any API change run `pnpm gen:api` and commit `api/openapi.yaml` and `web/src/api/schema.d.ts`; CI fails if they are stale.
- Do not use `shell: true` or unquoted paths in scripts: the project path contains a space.

## Rules that must not be broken

- Every tenant table: inherit `TenantModel`, and in the same migration call `tenant_table_operations(...)` from `apps/core/rls.py`. A test fails the build if a table with `org_id` lacks forced row-level security. Pass `same_org_refs` for every foreign key to another tenant table.
- Never connect the running app as the owner or a superuser. Jobs and scripts use `org_scope(org_id)` from `apps/core/tenancy.py`.
- Every endpoint gets a row in the permission table and is covered by the isolation suite (TASKS M1-11, M1-15). Records the user cannot see return 404, never 403.
- AI calls go only through `apps/ai`. Files go only through `apps/files`. Logs and error reports carry IDs, never document text.
- Sign-in is allauth's headless API (docs/sign-in.md). Owners and admins must enrol in two-step verification before using an organisation (`ENFORCE_MFA_ROLES`); the test settings switch this off, and `tests/security/test_mfa.py` switches it on where it matters. Do not weaken it in `config/settings/base.py`; a test checks the default.
- Tests run under `config.settings.test` (no counters stored). Tests of limits or lockouts use the `real_cache` fixture.
- Every new `_allauth/` route must be reviewed and added to `EXPECTED_AUTH_ROUTES` in `tests/security/test_auth_surface.py`.
- Slow work goes through `apps/core/jobs.py` (docs/jobs.md): job args are IDs only, and messages people see come from `JobFailure`.
- New modules ship behind a flag from `apps/core/flags.py` (`flag_required("plan")`).
