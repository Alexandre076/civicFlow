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

### Troubleshooting missing dependencies in Docker

If Vite reports `Failed to resolve import "react-i18next"` (or another
dependency listed in `package.json`) after updating the code, the existing
`frontend_node_modules` volume may still contain the previous installation.
Rebuilding with `docker compose up --build` preserves that volume, so refresh
its dependencies explicitly. From the repository root, run:

```bash
docker compose run --rm frontend npm ci
docker compose restart frontend
```

Reload the page at port **5173**. In Codespaces, use **Open in Browser** for
that port in the **Ports** tab. If the frontend has not been created yet, use
`docker compose up -d frontend` instead of `restart`.

To inspect startup failures, run from the repository root:

```bash
docker compose ps -a
docker compose logs --tail=100 frontend
```

Installing dependencies on the host does not update the container's separate
`node_modules` volume. Use the refresh commands whenever frontend dependencies
change; removing Compose volumes is unnecessary for this recovery.

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

## UI translations

The landing page supports Portuguese (Brazil) (`pt-BR`) and English (`en`).
Use the header's **Idioma / Language** native selector with mouse or keyboard;
changes apply immediately and update the document's `lang`. Only a manual
choice is stored, under `civicflow.locale` in localStorage. Storage failures
leave the page usable, but the selection may not survive another visit.

`src/i18n/config.ts` initializes i18next/react-i18next once through `main.tsx`.
Initial locale precedence is a valid saved canonical locale, the first supported
entry in `navigator.languages`, then `navigator.language`, then `pt-BR`.
Browser tags are matched case-insensitively: `pt` and `pt-*` map to `pt-BR`;
`en` and `en-*` map to `en`. Unsupported browser tags and stale saved values
are ignored. Automatic browser/default choices are not saved.

Catalogues live in `src/i18n/locales/pt-BR.json` and `en.json`. Use semantic
keys such as `home.welcome.title` with `useTranslation().t(...)`, and add the
same keys to every catalogue. Keep branding and language names consistent.
To add a future language, add its JSON catalogue, register its resource and
canonical code in `config.ts`, extend browser-tag mapping and the translated
`common.languages` options, and extend the locale/parity tests. Components
render the supported locale list and need no restructuring.

Missing English keys fall back to Portuguese. A key missing from every
catalogue returns its key without crashing; tests enforce catalogue parity to
catch omissions before release. To check fallback manually, temporarily remove
an English entry, select English and confirm its Portuguese text appears,
then restore the entry. `npm run test` covers fallback with a temporary test
resource, preference resolution, persistence, switching, accessible names and
keyboard focus. Native select arrow-key behavior should also be checked in a
browser because jsdom does not implement it. Technical missing-key diagnostics
are not shown to citizens.

This preference controls UI text only. It does not detect message language or
translate messages. No authentication or preferences endpoint is called.
Future authentication integration must apply the server's `preferred_locale`
for existing users and save authenticated selections through the profile API;
see the [locale contract](../docs/api-contracts.md#ui-locale-and-assistant-language).
That integration belongs to #20/#23.
