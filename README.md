# Greenlit

The QA record that links requirements, tests, evidence and defects, and shows what is still open before a release ships.

This repository holds the product specs, the build plan and the code.

| Where | What |
| --- | --- |
| `Greenlit *.md` | Specs: PRD, architecture, data model, AI behaviour, security, UX |
| [TASKS.md](TASKS.md) | The build plan, with a task for every requirement |
| `api/` | Django API, background jobs and tests |
| `web/` | React and TypeScript app |
| `docs/` | Decision records and setup guides |
| `Greenlit_Logo_Pack/` | Brand assets |

## Run it locally

Docker is optional. See [docs/local-setup-no-docker.md](docs/local-setup-no-docker.md), or use `docker compose up -d` for the full set of services.

```bash
cd api && DATABASE_URL=<owner url> ./.venv/Scripts/python manage.py migrate && ./.venv/Scripts/python manage.py runserver
cd web && pnpm install && pnpm dev
```

## Checks (the same ones CI runs)

```bash
cd api && ruff check . && ruff format --check . && mypy apps config
cd api && DATABASE_URL=<owner url> pytest
cd web && pnpm lint && pnpm typecheck && pnpm build && pnpm check:api
```
