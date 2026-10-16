# civicFlow
An open-source, agentic AI platform for citizen engagement, municipal service orchestration, and urban intelligence.

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
