# Frontend

React + TypeScript application shell for CivicFlow's future citizen chat
experience. Built with Vite, native CSS, and CSS Modules. Chat, authentication,
and backend requests are not implemented yet.

## Setup

Use Node.js 22 and npm. With [nvm](https://github.com/nvm-sh/nvm) installed,
run from the repository root:

```bash
cd frontend
nvm install
nvm use
npm ci
```

`.nvmrc` selects Node.js 22; `package-lock.json` locks resolved dependencies.
Use `npm install` when intentionally updating dependencies and include the
resulting lockfile changes in review.

## Development

From `frontend/`:

```bash
npm run dev
```

Open the local URL printed by Vite (normally `http://localhost:5173`).
For GitHub Codespaces, run:

```bash
npm run dev -- --host 0.0.0.0
```

In the Codespaces **Ports** tab, forward port **5173** if it is not forwarded
automatically, then use **Open in Browser** on that port. If Vite selects a
different port because 5173 is busy, forward the port it prints. The backend
does not need to run for this shell.

## Environment configuration

Optionally copy the public configuration template:

```bash
cp .env.example .env
```

`VITE_API_BASE_URL` defaults to `http://localhost:8000`. All environment access
is centralized in `src/config/env.ts`. The shell consumes this configuration
as a root data attribute for future integration; it makes no API requests.
Vite embeds values at build time; restart the dev server after changing `.env`
and rebuild to change a production bundle.

**All `VITE_*` values are exposed to the browser and must never contain secrets.**
Local `.env` files, `node_modules/`, `dist/`, and coverage output are ignored by
the shared repository `.gitignore`.

### Development proxy and Docker

The Vite server forwards relative `/api` requests to `http://localhost:8000`
by default and strips the `/api` prefix: `/api/health` reaches `/health`.
Future API routes must match this convention or change the rewrite. Set
`VITE_API_BASE_URL=/api` in your optional local `.env` to use the proxy when
integrating browser requests. The existing shell still makes no API calls.
To override the server-only target outside Docker, run:

```bash
API_PROXY_TARGET=http://localhost:9000 npm run dev
```

Compose sets `API_PROXY_TARGET=http://backend:8000` and the public API base to
`/api`; never use the Docker hostname as a browser-facing URL. The target is
read from the server process environment, not a `VITE_*` browser setting.
See the [root Compose quickstart](../README.md#development-with-docker-compose)
for live reload, dependency volume refresh, and Codespaces ports.

## Scripts and checks

Run from `frontend/`:

```bash
npm run typecheck
npm run test
npm run lint
npm run build
```

- `typecheck`: strict TypeScript checks for source, tests, and Vite configuration.
- `test`: Vitest smoke test using React Testing Library, jest-dom, and jsdom;
  runs once without a backend or external services.
- `lint`: basic ESLint, TypeScript, and React rules.
- `build`: typecheck and create the production bundle in `dist/`.
- `preview`: serve the production build locally after `npm run build`.

## Layout

`src/App.tsx` contains the shell, `src/App.module.css` its local styles, and
`src/index.css` global defaults. `src/config/env.ts` owns browser configuration.
Shared test setup lives in `src/test/setup.ts`, with tests in `tests/`.

See the [architecture outline](../docs/architecture.md) for application boundaries.
