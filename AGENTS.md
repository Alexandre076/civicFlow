# Codex instructions

- Inspect the current tree, Git status, relevant code/configuration, and assigned
  GitHub issue (technical decisions, checklist, and acceptance criteria) before
  editing. Preserve existing user changes.
- Keep work limited to the assigned issue. Respect `frontend/` and `backend/`
  ownership and existing conventions; avoid unrelated refactors or dependencies.
- Read [README.md](README.md), the relevant application guide, and
  [docs/architecture.md](docs/architecture.md). Distinguish working scaffolding
  from planned chat, LangGraph agents, MCP mocks, and future persistence.
- Follow [CONTRIBUTING.md](CONTRIBUTING.md) for the issue-to-PR workflow.

## Validation

Use Python 3.12 with uv. From `backend/`:

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Use Node.js 22 with npm. From `frontend/`:

```bash
npm ci
npm run lint
npm run typecheck
npm run test
npm run build
```

`ruff format --check` verifies formatting without modifying files. Apply
formatting locally only when intentionally requested. Preserve reproducible
installs using `backend/uv.lock` and `frontend/package-lock.json`; update
lockfiles only for intentional dependency changes in scope. Tests must not
require credentials, real external AI/API calls, or running external services.

Run checks appropriate to the change; for documentation, verify commands
against manifests/configuration, relative links and paths, and run
`git diff --check` from the root. Before handoff, inspect the final diff and
honestly report commands run, outcomes, and checks not run or blocked.

## Permissions

Do not commit, push, merge, or change unrelated GitHub resources without
explicit authorization. Documentation describes intended branch rules and
checks; it does not configure GitHub settings.
