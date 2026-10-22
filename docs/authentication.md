# Authentication contract — v1 (planned)

Design only for [Epic #2](https://github.com/Alexandre076/civicFlow/issues/2). Login,
PostgreSQL sessions and the minimal React account flow are now implemented in #20; see
[implementation/setup decisions](auth-development.md). Route prefixes, User DTO and
errors are defined in [API contracts](api-contracts.md); stream revocation behavior is
in [streaming](streaming.md). Google is the only MVP identity provider.

## Google OIDC and the BFF

1. Browser navigates to `GET /api/v1/auth/google/login`. FastAPI generates a
   cryptographically random, single-use `state`, `nonce`, and PKCE verifier;
   uses the S256 challenge; stores an expiring login transaction server-side,
   bound to a separate opaque HttpOnly browser transaction cookie. This also
   works before an application session exists. Validate `return_to` against
   an allowlist of relative UI paths (default `/`); reject external URLs,
   protocol-relative URLs and encoded bypasses. Validate optional `locale`.
2. Redirect to Google's discovered authorization endpoint with code flow,
   exact registered redirect URI, client ID, `openid profile email`, state,
   nonce and PKCE challenge. No offline access or extra Google API scopes are
   needed. Provider consent/access-denied returns a sanitized login failure.
3. On the GET callback, validate the browser binding, state and transaction
   expiry, consuming the transaction once. Exchange the code server-side over
   HTTPS with the original verifier and redirect URI, plus client authentication
   required for the registered confidential client. Never expose the verifier
   or provider tokens to React.
4. Validate the ID token with a maintained OIDC library and Google's configured
   discovery/JWKS: signature and allowed algorithm, issuer, client-ID audience,
   authorized party when applicable, expiry/issued-at with bounded clock skew,
   nonce and required nonempty subject. Discovery issuer is pinned to Google,
   never supplied by the browser. Normalize Google's documented issuer variants
   to canonical `https://accounts.google.com` only after validation.
5. Resolve the identity by unique `(canonical_issuer, sub)`, creating a user
   and linked identity transactionally if absent. Email/name are display
   attributes, possibly absent or changed. Never auto-link identities using
   email, even a verified email. Cross-provider/account merging is out of scope.
6. Rotate any prior browser application session, create a new server session,
   set its cookie, clear the login transaction/cookie, and 303 redirect to the
   validated UI path. Callback pages/responses use no-store and a no-referrer
   policy; promptly remove code/state from the address bar by redirecting.

Invalid or replayed callbacks create no session and return a sanitized 400
`OIDC_CALLBACK_INVALID`; unavailable provider services use 503
`SERVICE_UNAVAILABLE`. No raw provider errors or codes enter URLs/logs.
A login failure must not bind a different user to an existing session.
Tests use fake issuer/token exchange and controlled keys, without Google calls.

## Sessions and cookies

The browser receives only a high-entropy opaque session secret. Store a secure
hash of it server-side with user ID, creation/last-use timestamps, idle and
absolute expiry and revocation state. Session storage must support revocation
across workers; PostgreSQL is the default project persistence boundary, with
exact session store/library open in #20. Avoid JWT or provider tokens as browser
session cookies. Discard provider access/ID tokens after validation unless an
explicit server-only need is approved; refresh tokens are unnecessary here.

HTTPS cookie contract:

```http
Set-Cookie: __Host-civicflow_session=<opaque>; Path=/; HttpOnly; Secure; SameSite=Lax
```

No Domain attribute. Lax supports the top-level Google GET callback while
reducing cross-site cookie use; it does not replace CSRF checks. The separate
login transaction cookie uses the same protections and a short finite lifetime.
Set session Max-Age no later than the server's absolute expiry so browser
restarts can retain a valid login. Enforce idle and absolute expiry server-side;
activity may extend idle expiry but never absolute expiry. Exact session and
login transaction durations, clock skew, rotation and reauthentication policy
are open decisions for #20 and must be finite, documented and tested.

Each authenticated request checks expiry/revocation and resolves one user.
Expired/revoked sessions return 401, clear the cookie and never authorize an
operation from stale browser state. Session secrets/CSRF tokens are rotated
on login, not accepted from query parameters or request bodies. Shared-device
logout clears client user/history caches; a new user cannot see the prior cache.

`POST /auth/logout` requires a valid session and CSRF, revokes it server-side,
terminates its active streams, expires the cookie with identical name/path/
security attributes and returns 204. It logs out this device/session, not other
sessions or the Google account, and does not delete history. Already invalid
sessions return 401 and clear the cookie; clients can still clear local state.
A concurrent operation committed before revocation remains persisted; no new
stream writes are allowed after the revocation fence.

## CSRF and browser requests

Use a synchronizer token bound to the session. Authenticated `GET /auth/me`
returns the User JSON and `X-CSRF-Token` header with `Cache-Control: no-store`.
React keeps this token in memory and sends `X-CSRF-Token` on POST/PATCH/DELETE,
including streaming sends and logout. It is a CSRF token, not a Google token
or a replacement for the HttpOnly session. Reload fetches it again; do not put
it in URLs/localStorage. Validate with a constant-time comparison.

For every mutation also verify Origin against the configured public UI origin;
if absent, require a matching Referer origin; reject absent/bad evidence with
403 `ORIGIN_FORBIDDEN`. Reject missing/incorrect CSRF with 403 `CSRF_INVALID`.
Require JSON content type for JSON mutations, disallow state-changing GETs
except the protected OIDC callback, and avoid wildcard credentialed CORS.
Login/callback use their one-time state/browser-binding flow instead of the
application CSRF header. Logout is never GET. Fetch uses same-origin credentials;
a future approved cross-origin deployment needs an exact origin allowlist and
explicit credentials, with a new review of cookie and CSRF behavior.

An explicit development-only `TRUSTED_PROXY_ORIGIN` can accommodate Codespaces
rewriting same-origin Origin to loopback. In that case a matching public Referer
is additionally required; missing/bad Referer still returns `ORIGIN_FORBIDDEN`.
This setting is disabled by default, requires public HTTPS, and does not trust
Host/forwarded headers or other mismatching origins. See
[Codespaces setup](auth-development.md#local-setup).

## Local development and authorization

Prefer the existing Vite `/api` proxy so browser requests stay on one origin.
Future FastAPI routes retain `/v1` after the `/api` rewrite. Register the exact
external callback URL used by the browser with Google. Trusted proxy/public
origin configuration must generate that URL, never trust arbitrary Host or
forwarded headers. Codespaces uses its private HTTPS forwarded frontend URL,
not `backend:8000`. Configure callback allowlists/secrets server-side; never
embed them in `VITE_*` variables or commit them. Production ingress and Google
client registrations are follow-up setup, not configured by this document.

For explicit loopback HTTP development only, allow a separate cookie named
`civicflow_session_dev` with HttpOnly, Path=/, SameSite=Lax and Secure disabled;
`__Host-` cannot be used without Secure. Apply equivalent development treatment
to the transaction cookie. Never allow this override for non-loopback deployment
origins; use HTTPS for forwarded Codespaces. CSRF/origin checks remain enabled.
The current shell's standalone API URL is scaffolding, not a deployed auth setup.

All authenticated endpoints derive user identity from the session. Every
conversation/message operation, including pagination, deletion and idempotency
replay, checks ownership server-side and uses the non-disclosing 404 contract.
A valid login does not grant access to another user's IDs. Preference changes
only modify the current user's UI locale, not stored text or ownership.
Do not log cookies, provider tokens, authorization codes, state, nonce, verifier,
CSRF values or citizen report content. Operational logs use sanitized codes and
request IDs with restricted access and a retention policy still to be selected.

## Reference material

The project choices above apply the [Google OIDC
documentation](https://developers.google.com/identity/openid-connect/openid-connect),
[OAuth PKCE specification](https://www.rfc-editor.org/rfc/rfc7636) and [OWASP CSRF
guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
Implementation uses Authlib, SQLAlchemy and Alembic; see [setup and
tests](auth-development.md).
