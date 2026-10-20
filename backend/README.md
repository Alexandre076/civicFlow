# Backend

Minimal CivicFlow API built with FastAPI and Pydantic v2. It currently exposes
only a health endpoint; workflows, integrations, and storage are future work.

## Local setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run
from the repository root:

```bash
cd backend
uv python install 3.12
uv sync --locked
```

Python is restricted to 3.12 (`>=3.12,<3.13`), with `.python-version` selecting
that version. `uv sync --locked` creates `.venv`, installs the application and
development dependencies, and uses the resolved versions in `uv.lock`. No manual
virtual environment activation is required.

## Configuration

Defaults work without credentials or a configuration file. To customize them,
run from `backend/`:

```bash
cp .env.example .env
```

`CIVICFLOW_APP_NAME` sets the title shown in API documentation (default:
`CivicFlow API`). Environment variables override `.env` values. The `.env` file
is read from the current working directory and is ignored by Git.

## Run

From `backend/`:

```bash
uv run uvicorn civicflow.main:app --reload
```

The development server listens at `http://127.0.0.1:8000` by default:

- `GET /health` returns HTTP 200 with `{"status":"ok"}`.
- `/docs` provides interactive API documentation.
- `/openapi.json` provides the generated OpenAPI schema.

## Quality checks

From `backend/`:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Ruff checks Python errors and import ordering and verifies formatting without
rewriting source. To apply formatting locally, run `uv run ruff format .` and
review the changes. CI uses the same checks; see the
[root quality guide](../README.md#quality-checks-and-ci) for troubleshooting.

Tests use FastAPI's TestClient and require no running server, external APIs,
databases, or credentials. To verify the lockfile without updating it, use
`uv sync --locked`.

## Layout

Application code lives in `src/civicflow/`: `main.py` creates the app,
`config.py` defines settings, and `api/routes/` contains endpoints. Tests live
in `tests/`.

See the [architecture outline](../docs/architecture.md) for application boundaries.

## Docker development

The [root Compose quickstart](../README.md#development-with-docker-compose)
runs Uvicorn with `--host 0.0.0.0 --port 8000 --reload`, source mounts and an
isolated `.venv` volume. Safe default settings need no `.env`; an optional local
`backend/.env` is read through the mount and is excluded from image builds.
Restart the service after changing configuration. `docker compose ps` shows
health status; the health check uses Python's standard library against
`GET /health`. No database or other infrastructure is required.
