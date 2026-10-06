# Local setup without Docker

Docker is optional (see TASKS.md, M0-02). You need only PostgreSQL 16 or later, because tenant isolation relies on its row-level security. The local settings run background jobs inline, store files in a folder, print email to the console and skip malware scanning.

## 1. PostgreSQL

Install PostgreSQL 16+ (for example `winget install PostgreSQL.PostgreSQL.16`). If the installer does not register a Windows service (it exited with code 4 on one machine), you can still run the binaries it unpacked against a data folder inside the project. This is development only: it listens on localhost and trusts local connections.

```bash
PGBIN="/c/Program Files/PostgreSQL/16/bin"
cd api && mkdir -p var
"$PGBIN/initdb.exe" -D var/pgdata -U postgres --auth=trust -E UTF8 --locale=C   # once
"$PGBIN/pg_ctl.exe" -D var/pgdata stop -m fast                                  # when done
```

Start the server from PowerShell with `scripts/start-postgres.ps1`. It launches Postgres through Windows' process-creation service, so the server is not a child of your terminal or editor. Started from a shell that later closes, or from a tool call that times out, Windows kills the server's child processes and Postgres shuts down (log: `terminated by exception 0xC0000142`). Data survives; the next start runs crash recovery.

`api/var/` is git-ignored. The server is up once `var/postgres.log` says it is ready to accept connections.

Then create the database and the two roles. Run this once as the `postgres` superuser:

```sql
CREATE ROLE greenlit_owner LOGIN PASSWORD 'greenlit_owner' CREATEDB;   -- migrations; owns the tables
CREATE DATABASE greenlit OWNER greenlit_owner;
CREATE ROLE greenlit_app LOGIN PASSWORD 'greenlit_app'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;                      -- the running app
\c greenlit
GRANT USAGE ON SCHEMA public TO greenlit_app;
GRANT greenlit_app TO greenlit_owner;   -- lets tests run SET ROLE greenlit_app
ALTER DEFAULT PRIVILEGES FOR ROLE greenlit_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO greenlit_app;
ALTER DEFAULT PRIVILEGES FOR ROLE greenlit_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO greenlit_app;
```

The app must never connect as `greenlit_owner` or as a superuser, or row-level security is bypassed (SEC §5). Local passwords are for development only.

## 2. Backend

```bash
cd api
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env
```

Run migrations as the owner role (the app role cannot create tables), then start the server as the app role. An environment variable overrides `.env`:

```bash
DATABASE_URL=postgres://greenlit_owner:greenlit_owner@localhost:5432/greenlit ./.venv/Scripts/python manage.py migrate
./.venv/Scripts/python manage.py runserver
```

Every new migration that adds a tenant table needs the owner role. Tests that create tables or policies do too.

## Tests

Tests create their own database, so run them as the owner role. They switch to `greenlit_app` where they need to prove isolation:

```bash
cd api
DATABASE_URL=postgres://greenlit_owner:greenlit_owner@localhost:5432/greenlit ./.venv/Scripts/python -m pytest
```

## 3. Front end

```bash
cd web
pnpm install
pnpm dev
```

## What is skipped, and when you need it

| Skipped | Needed for |
| --- | --- |
| Redis and a Celery worker | Testing schedules (reminders, digest). Jobs run inline until then. |
| MinIO or S3 | Testing signed upload and download links (M1-14). |
| ClamAV | Testing real malware scanning. |

CI and staging use the full set of services.
