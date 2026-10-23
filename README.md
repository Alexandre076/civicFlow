# civicFlow
An open-source, AI-assisted municipal incident and service-request platform for citizens.

## Current state and target MVP

Today, CivicFlow provides a bilingual React + TypeScript shell with Google OIDC
login/logout, FastAPI BFF authentication and a health endpoint, PostgreSQL
user/identity/session and conversation storage, Docker Compose development, and
CI checks. Conversation HTTP APIs, interactive chat, agent orchestration and MCP
tools remain planned. See [conversation storage](docs/conversation-storage.md) and
[authentication setup](docs/auth-development.md) for implementation and configuration.

The target MVP is a text-based citizen conversation: describe an incident or service
request, supply missing details, and receive a municipal protocol reference or look up
its status through mock tools. The planned FastAPI + Pydantic backend uses LangGraph
Intake and Routing Agents with MCP tools for mock protocol creation and lookup. There
are no live government-system integrations. Authentication persistence uses PostgreSQL;
Epic #2 provides conversation storage while its HTTP API and streaming remain planned.
Municipal incident/protocol storage belongs to Epic #4. The planned [API contracts](docs/api-contracts.md),
[authentication](docs/authentication.md), and [streaming](docs/streaming.md) contracts
guide Epic #2 implementation.

See the [architecture reference](docs/architecture.md) for component boundaries
and the intended request flow.

## Development with Docker Compose

Install Docker with Compose, then run from the repository root (no host Node.js,
Python or dependency installation required):

```bash
docker compose config --quiet
docker compose up --build
```

Open <http://localhost:5173> for the existing CivicFlow shell and
<http://localhost:8000/health> for `{"status":"ok"}`. Both development servers
listen on `0.0.0.0` inside their containers. In GitHub Codespaces, forward
**5173** and **8000** in the **Ports** tab and use **Open in Browser** on each.
Keep forwarded ports private. Port forwarding itself must be checked in your
Codespace browser.

The frontend uses Node.js 22 and `npm ci`; the backend uses Python 3.12 and
`uv sync --locked`. Source bind mounts enable Vite HMR for `.tsx` changes and
Uvicorn reload for `.py` changes without rebuilding. Named volumes protect
container `node_modules` and `.venv` from host dependencies. Containers run as
non-root users; source edits are made on the host.

```bash
# Background startup and logs
docker compose up --build -d
docker compose logs -f
# Service state, including backend health
docker compose ps
docker inspect --format '{{json .State.Health}}' "$(docker compose ps -q backend)"
# Stop and remove containers/network; dependency volumes remain
docker compose down
# Rebuild after Dockerfile or dependency lockfile changes
docker compose build
# Refresh installed dependencies after lockfile changes, then restart
docker compose run --rm frontend npm ci
docker compose run --rm backend uv sync --locked
docker compose up -d
# Restart running development servers after refreshing dependencies
docker compose restart frontend backend
# Clean reset: deletes all Compose volumes and their installed dependencies
docker compose down -v
docker compose up --build
```

`down -v` permanently deletes data in this project's Compose volumes. These now include
PostgreSQL account/session data and reproducible dependencies; all of that data will be
lost. Host source files and local `.env` files remain intact.

Rebuilding images preserves existing dependency volumes. If Vite reports
`Failed to resolve import` after a dependency change, follow the
[frontend troubleshooting guide](frontend/README.md#troubleshooting-missing-dependencies-in-docker)
to refresh the frontend volume and restart its server.

The frontend dev proxy forwards relative `/api/*` requests to `http://backend:8000` over
the default Compose network, stripping `/api` (`GET /api/health` reaches backend `GET
/health`). This service hostname is server-only; the browser receives `/api` as its API
base URL. Authentication calls use the same-origin proxy; the shell can still render
when the backend is unavailable. Future endpoints must follow this rewrite convention or
update the proxy together with the backend routes. Check DNS/connectivity and the proxy
with:

```bash
docker compose exec frontend node -e "fetch('http://backend:8000/health').then(async r => console.log(r.status, await r.text()))"
curl http://localhost:5173/api/health
```

The shell and health endpoint need no Google credentials. Login requires the server-only
configuration in [authentication setup](docs/auth-development.md). Optional ignored
`backend/.env` overrides backend settings through its source mount; restart the backend
after changing settings. Local `.env` files are excluded from image builds. Public
frontend settings and the server-only `API_PROXY_TARGET` are described in the [frontend
guide](frontend/README.md); backend settings are in the [backend
guide](backend/README.md). This Compose setup is for development.

## Quality checks and CI

Use Python 3.12 with uv and Node.js 22 with npm. Run the same checks as CI
from the repository root:

```bash
cd backend
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd ../frontend
npm ci
npm run lint
npm run typecheck
npm run test
npm run build
```

See the [backend guide](backend/README.md) and [frontend guide](frontend/README.md) for
standalone setup and development. Vitest runs once and exits. Authentication integration
tests require an isolated PostgreSQL database via `CIVICFLOW_TEST_DATABASE_URL`; CI
supplies one. No Google credentials or external AI APIs are required. See [test
setup](docs/auth-development.md#tests-and-frontend-integration). Docker Compose is
optional for development and is not used by CI.

The single workflow in [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
runs on pull requests targeting `main` and pushes to `main`. Its independent
Ubuntu jobs appear as `backend` and `frontend`; a failure in either job does
not prevent the other job from running. They use the committed lockfiles and
cache uv/npm downloads based on their respective lockfiles. Workflow
permissions are limited to `contents: read`; checks do not fix or commit source.
The production build writes only generated output under `frontend/dist/`.

For a failed check, open the failing job and step in GitHub Actions, then run
that command locally in the corresponding application directory. Ruff and
ESLint report file locations; fix the reported code. For formatting failures,
run `uv run ruff format .` from `backend/` and review the diff. TypeScript errors
come from `typecheck` (also included in `build`); pytest and Vitest report the
failed assertions. Re-run the affected checks after fixing the cause.

If installation fails, verify tool versions first. For a stale backend lockfile,
run `uv lock` after an intentional dependency change; for frontend dependency
changes, run `npm install` to update `package-lock.json`. Review and include
lockfile changes with dependency edits. For download/cache failures, retry the
job; caches are an optimization and locked installs remain required.

After validating successful GitHub-hosted runs, configure `main` branch
protection manually to require both `backend` and `frontend` status checks.

## Repository layout

```text
frontend/             React + TypeScript application shell
backend/              FastAPI backend and tests
docs/architecture.md  Current foundation and target MVP architecture
CONTRIBUTING.md       Issue-to-PR contribution workflow
AGENTS.md             Instructions for Codex sessions
.github/workflows/    Backend and frontend CI checks
compose.yaml          Local development services and dependency volumes
.editorconfig         Shared editor conventions
.gitignore            Generated files and local-only configuration
```

The backend provides FastAPI health and v1 BFF authentication endpoints. See the
[backend setup guide](backend/README.md) for Python 3.12 and uv install, run,
configuration, and test commands. The [frontend setup guide](frontend/README.md) covers
the React application shell, Node.js 22, npm scripts, and Codespaces access.

Each application owns its dependencies, configuration, tests, and build
tooling in its own directory. See the [architecture outline](docs/architecture.md)
for the intended responsibilities.

## Contributing

Follow the [issue-to-PR workflow](CONTRIBUTING.md) for scope, branches, validation,
review, and Squash and Merge. New Codex sessions should read
[AGENTS.md](AGENTS.md) and the assigned issue before making changes.
