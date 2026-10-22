# Google authentication development

Issue #20 implements Google OIDC login, BFF cookies, session bootstrap and logout.
Chat/history, agents, MCP, preference editing and municipal protocols remain planned.

## Local setup

1. Copy `backend/.env.example` to ignored `backend/.env`. Set the Google client
   ID/secret there. Keep all credentials out of frontend `VITE_*` settings.
2. In Google Cloud Console, configure the OAuth consent screen and test users as
   needed, then create an OAuth client of type **Web application**. Register the
   exact authorized redirect URI `http://localhost:5173/api/v1/auth/google/callback`.
   This is a backend code flow; no browser Google SDK or implicit flow is used.
3. Run `docker compose up --build`. PostgreSQL starts first; the backend applies
   `uv run alembic upgrade head` before starting Uvicorn. Compose supplies the
   database URL using hostname `db`, overriding the standalone `.env` setting.
4. Open `http://localhost:5173`, select a language and use **Sign in with Google**.
   The `.env.example` explicitly selects loopback HTTP development cookies.
   Without credentials the shell and `/health` still work; login returns sanitized
   503. Restart the backend after changing configuration.

The login response redirects to Google; success returns to `/` with a 303.
Provider denial/invalid callbacks return a no-store JSON error page without
provider details. Navigate back to the application and retry login. Code/state
are removed by the success redirect; failure responses use no-referrer and
no-store. Do not configure access logs that include callback query strings.
Uvicorn access logging is disabled in Compose and the documented run command.
Production ingress/logging configuration remains deployment work.

For Codespaces, forward frontend 5173 and backend 8000 privately. Use the private
HTTPS frontend URL as `CIVICFLOW_PUBLIC_ORIGIN`, append
`/api/v1/auth/google/callback` for `CIVICFLOW_CALLBACK_URL`, register that exact
URI with Google, and set `CIVICFLOW_SECURE_COOKIES=true`. Always enter through
that frontend URL, rather than the backend port. Check both the Google test-user
and Codespaces access requirements in the browser. Never derive either URL from
Host/forwarded headers. Non-loopback insecure-cookie configuration is rejected.

Codespaces rewrites the browser's same-origin `Origin` header to
`http://localhost:5173`. For this development proxy, add this explicit setting to
`backend/.env` and restart the backend:

```dotenv
CIVICFLOW_TRUSTED_PROXY_ORIGIN=http://localhost:5173
```

This exception is disabled by default and requires a configured HTTPS public
origin. It accepts only the exact configured loopback origin, and only when the
request's `Referer` origin matches `CIVICFLOW_PUBLIC_ORIGIN`. Missing, malformed
or external Referer evidence is rejected. The session-bound CSRF token remains
mandatory. Other mismatching Origin values remain rejected even with a matching
Referer; Host and forwarded headers never grant trust. Keep the forwarded ports
private. This is a development proxy exception, not a production origin allowlist.


## Server configuration

All names below have the `CIVICFLOW_` prefix and are server-only. Environment
variables override the optional backend `.env`.

| Name suffix | Default / purpose |
| --- | --- |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Empty; login disabled until configured |
| `DATABASE_URL` | `postgresql+psycopg://civicflow:civicflow@localhost:5432/civicflow`; Compose overrides host to `db` |
| `PUBLIC_ORIGIN` | `http://localhost:5173`; exact trusted browser origin |
| `CALLBACK_URL` | `http://localhost:5173/api/v1/auth/google/callback`; exact registered URI on public origin |
| `TRUSTED_PROXY_ORIGIN` | Unset; optional exact loopback origin with port for Codespaces; requires matching public Referer and HTTPS public origin |
| `ALLOWED_RETURN_PATHS` | JSON array `["/"]`; literal relative UI paths, no escapes/query/fragment |
| `SECURE_COOKIES` | `true`; set false explicitly only on loopback HTTP |
| `LOGIN_TTL` | 600 seconds, single-use login transaction |
| `SESSION_IDLE_TTL` | 86400 seconds (24 hours) |
| `SESSION_ABSOLUTE_TTL` | 604800 seconds (7 days) |
| `CLOCK_SKEW` | 60 seconds; accepted range 0–120 |

Durations must be positive, at most one year. Activity extends idle expiry up to
absolute expiry. Every login rotates the browser session and synchronizer token;
other devices remain signed in. No background refresh or refresh tokens exist.
HTTPS uses `__Host-civicflow_session` and `__Host-civicflow_login`; explicit local
HTTP uses `civicflow_session_dev` and `civicflow_login_dev`. Cookies have Path=/,
HttpOnly, SameSite=Lax, no Domain, and finite Max-Age. Secure is set in HTTPS mode.
Logout clears the same cookie attributes and revokes the database session.

Authlib's OAuth2Client exchanges codes with client authentication over HTTPS.
Authlib CodeIDToken validates the RSA signature and OIDC claims with RS256 as
the only allowed algorithm. Discovery is pinned to Google's HTTPS discovery URL
and issuer; JWKS comes only from that document, never from token header URLs.
The validated issuer variants normalize to `https://accounts.google.com` for
identity lookup. Required claims include audience/client ID, expiry, issued-at,
nonce and a nonempty subject; authorized party is checked including multi-audience
cases. State/browser binding use 256-bit random secrets, SHA-256 and constant-time
comparison. PKCE uses a fresh 256-bit verifier and S256. Provider tokens are
neither returned to React nor persisted. The lockfile pins reviewed library
versions; Authlib 1.x currently emits upstream JOSE/httpx migration warnings.

## Persistence conventions shared with #21

SQLAlchemy 2 declarative models live in `backend/src/civicflow/models.py`.
Alembic uses one linear revision chain in `backend/migrations/versions/`, starting
with `0001` for users, unique `(issuer, subject)` identities, sessions and login
transactions. #21 should import the same Base and append a revision with
`down_revision = "0001"`; do not recreate user/identity tables. IDs are opaque
random strings. Time columns store UTC Unix seconds. Identity resolution uses
a savepoint and the unique database constraint to handle concurrent first login
without orphan users. Email is never an identity key.

Standalone migrations from `backend/` with a configured database URL:

```bash
uv sync --locked
uv run alembic upgrade head
uv run alembic current
# After intentionally editing models for a later issue:
uv run alembic revision --autogenerate -m description
```

Review generated revisions. `alembic downgrade base` is destructive and is used
only against the isolated test database for roundtrip tests. Compose's
`postgres_data` volume retains account/session records across restarts.
`docker compose down -v` now deletes those records as well as dependencies.

Sessions persist only SHA-256 hashes of opaque browser secrets, plus a separate
session-bound synchronizer CSRF value. Transactions retain nonce/verifier only
until callback consumption or expiry cleanup during login. Revoked/expired
sessions authorize nothing; retention/periodic cleanup and production limits
remain release setup. Database access is privileged: do not expose tables or
log row values. Future authenticated mutation endpoints reuse `require_mutation`
and hold/recheck the session row lock in the same transaction as their writes;
streams must add their own recurring revocation fence in #24. No streams exist yet.

## Tests and frontend integration

The CI backend job starts PostgreSQL 17, sets `CIVICFLOW_TEST_DATABASE_URL` to a
throwaway database, applies migrations in fixtures, and uses httpx MockTransport
with controlled RSA keys. No Google credentials or live provider requests are
required. Locally use a **separate disposable** database; tests truncate all auth
tables and include a downgrade/upgrade roundtrip:

```bash
cd backend
CIVICFLOW_TEST_DATABASE_URL=postgresql+psycopg://civicflow:civicflow@localhost:5432/civicflow_test uv run pytest
```

For a reproducible local test database without host Python/PostgreSQL, run from
repository root (create the test database once):

```bash
docker compose up -d db
docker compose exec db createdb -U civicflow civicflow_test
docker compose run --rm -e CIVICFLOW_TEST_DATABASE_URL=postgresql+psycopg://civicflow:civicflow@db:5432/civicflow_test backend uv run pytest
```

If `civicflow_test` already exists, omit `createdb`. This uses the disposable test
database rather than Compose's account database.

Without that variable database tests explicitly skip; token/config/health tests
still run. Never point the variable at a database containing useful data.

React requests `/api/v1/auth/me` with same-origin credentials at startup. A 401
shows login; other failures offer retry. CSRF/user state stays in component
memory. Existing server locale takes precedence without writing localStorage;
first login passes the selected locale. Until #23 implements preference PATCH,
the authenticated language selector is disabled. That issue should enable it
only when it can save the server preference and apply changes on success.
Logout clears memory after 204/401; future user-scoped history caches must join
that cleanup. Responses render profile text as ordinary React text.

The browser flow with real Google and private Codespaces forwarding requires
manual verification with configured credentials. Automated tests cover fake
exchange, validation failures, replay, binding, redirects, expiry/revocation,
CSRF/Origin, identity uniqueness/concurrency and the localized React lifecycle.
