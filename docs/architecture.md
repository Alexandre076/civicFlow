# Intended architecture

This document outlines application boundaries. The backend starts with Python
3.12, FastAPI, Pydantic v2, and uv; workflow and integration choices remain
future work.

## Frontend

`frontend/` will contain the citizen-facing user interface for engagement and
municipal services. It will communicate with backend APIs to access application
capabilities.

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
