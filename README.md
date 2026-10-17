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
