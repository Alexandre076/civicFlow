# civicFlow
An open-source, agentic AI platform for citizen engagement, municipal service orchestration, and urban intelligence.

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
# Clean reset: deletes all Compose volumes and their installed dependencies
docker compose down -v
docker compose up --build
```

`down -v` permanently deletes data in this project's Compose volumes. Currently
these contain only reproducible dependencies; any files manually placed there
will also be lost. Host source files and local `.env` files remain intact.

The frontend dev proxy forwards relative `/api/*` requests to
`http://backend:8000` over the default Compose network, stripping `/api`
(`GET /api/health` reaches backend `GET /health`). This service hostname is
server-only; the browser receives `/api` as its API base URL. The current shell
makes no API calls and can start independently of backend health. Future
endpoints must follow this rewrite convention or update the proxy together
with the backend routes. Check DNS/connectivity and the proxy with:

```bash
docker compose exec frontend node -e "fetch('http://backend:8000/health').then(async r => console.log(r.status, await r.text()))"
curl http://localhost:5173/api/health
```

No configuration files or secrets are required. Optional ignored
`backend/.env` overrides backend settings through its source mount; restart the
backend after changing settings. Local `.env` files are excluded from image
builds. Public frontend settings and the server-only `API_PROXY_TARGET` are
described in the [frontend guide](frontend/README.md); backend settings are in
the [backend guide](backend/README.md). This Compose setup is for development.

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

See the [backend guide](backend/README.md) and
[frontend guide](frontend/README.md) for standalone setup and development.
Vitest runs once and exits. Tests require no running servers, database,
credentials, or external AI APIs. Docker Compose is optional for development
and is not used by CI.

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
docs/architecture.md  Intended architecture and application boundaries
.editorconfig         Shared editor conventions
.gitignore            Generated files and local-only configuration
```

The backend provides a minimal FastAPI application with a health endpoint.
See the [backend setup guide](backend/README.md) for Python 3.12 and uv install,
run, configuration, and test commands. The [frontend setup guide](frontend/README.md)
covers the React application shell, Node.js 22, npm scripts, and Codespaces access.

Each application will own its dependencies, configuration, tests, and build
tooling in its own directory. See the [architecture outline](docs/architecture.md)
for the intended responsibilities.
