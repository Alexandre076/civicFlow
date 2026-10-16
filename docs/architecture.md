# Intended architecture

This document outlines application boundaries. The backend starts with Python
3.12, FastAPI, Pydantic v2, and uv; workflow and integration choices remain
future work.

## Frontend

`frontend/` contains a responsive React + TypeScript application shell using
Vite, native CSS, and CSS Modules, with Node.js 22 and npm. It will provide the
citizen-facing interface for engagement and municipal services. Backend
communication and citizen chat functionality are future work.

## Backend

`backend/` will contain APIs and the logic for municipal service orchestration,
agentic workflows, and urban intelligence. Integrations and data access will
belong to this application.

## Repository ownership

- Each application owns its dependency manifests, lockfiles, configuration,
  tests, and build tooling within its own directory.
- The repository root holds project documentation and shared repository and
  editor conventions.
- `docs/` holds documentation that spans application boundaries.
- Local secrets and generated artifacts stay out of version control. Future
  environment templates should use `.env.example` files with placeholder values
  in the relevant application directory.

The backend currently exposes only `GET /health` and generated API documentation.
Workflows, integrations, storage, and deployment configuration are future work.
