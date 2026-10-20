# Contributing

Epics group related planning work; individual issues define focused units of
implementation. Prefer one issue per PR where practical. Start with the
[README](README.md) for setup and current capabilities. Codex sessions must
also follow [AGENTS.md](AGENTS.md).

## Issue to pull request

1. Select an issue and read its parent epic and relevant dependencies. Clarify
   scope, technical decisions, and acceptance criteria before implementing.
   Inspect the current repository; planned features may not exist yet.
2. With a clean working tree, create `feature/issue-N-short-description` from
   updated `main`. For example, for Issue #11:

   ```bash
   git switch main
   git pull --ff-only origin main
   git switch -c feature/issue-11-document-architecture
   ```

   Preserve existing local work before switching branches. These commands
   assume an existing clone with the `origin` remote and a local `main` branch.
3. Implement the issue with Codex, following application boundaries and existing
   conventions. Keep the diff focused and label planned capabilities clearly.
4. Run relevant local checks from the [quality guide](README.md#quality-checks-and-ci)
   and review the diff. Report results and checks not run. Verify links, paths,
   and commands for documentation changes, including `git diff --check`.
5. Once authorized, commit and push the branch, then open a focused PR targeting
   `main`. Explain the problem, resulting change, validation, and limitations.
   Include `Closes #N` when merging should close the issue. Codex must wait for
   explicit authorization before committing or pushing.
6. Review the PR and confirm both GitHub Actions checks, `backend` and
   `frontend`, pass. Resolve feedback and rerun affected local checks.
7. After approval and with explicit authorization for any Codex merge, use
   **Squash and Merge**. Confirm the issue closes; close it manually if needed
   once its acceptance criteria are met and closure is authorized.

## Branch rules and CI

The checked-in workflow runs on PRs targeting `main` and pushes to `main`.
Branch rules can require review and successful `backend`/`frontend` checks
before merging. A maintainer must configure those rules in GitHub after
validating hosted runs; this documentation neither enables them nor confirms
their current configuration. Do not bypass required review or checks.

Application-specific setup and commands live in the
[backend](backend/README.md) and [frontend](frontend/README.md) guides.
