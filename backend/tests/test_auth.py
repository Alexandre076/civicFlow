import base64
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from authlib.jose import JsonWebKey, jwt
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from civicflow.auth import (
    Authenticated,
    AuthError,
    database,
    digest,
    require_mutation,
    require_session,
)
from civicflow.config import Settings
from civicflow.main import create_app
from civicflow.models import BrowserSession, Identity, LoginTransaction, User
from civicflow.oidc import ISSUER, GoogleOIDC, InvalidToken, ProviderUnavailable


@pytest.fixture
def keys():
    return JsonWebKey.generate_key(
        "RSA", 2048, is_private=True, options={"kid": "test"}
    )


@pytest.fixture
def flow(auth_database, keys):
    settings = Settings(
        _env_file=None,
        database_url=auth_database,
        public_origin="https://civicflow.test",
        callback_url="https://civicflow.test/api/v1/auth/google/callback",
        google_client_id="client",
        google_client_secret="test-secret",
    )
    app = create_app(settings)
    pending = {}
    profile = {"sub": "subject", "email": "one@example.com", "name": "Citizen"}

    def provider(request):
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "/authorize",
                    "token_endpoint": "https://oauth2.googleapis.com/token",
                    "jwks_uri": "https://www.googleapis.com/keys",
                },
            )
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [keys.as_dict(is_private=False)]})
        body = parse_qs(request.content.decode())
        assert body["redirect_uri"] == [settings.callback_url]
        assert body["client_secret"] == ["test-secret"]
        assert body["code_verifier"] == [pending["verifier"]]
        now = int(time.time())
        token = jwt.encode(
            {"alg": "RS256", "kid": "test"},
            {
                "iss": ISSUER,
                "aud": "client",
                "iat": now,
                "exp": now + 600,
                "nonce": pending["nonce"],
                **profile,
            },
            keys,
        ).decode()
        return httpx.Response(
            200,
            json={
                "id_token": token,
                "access_token": "discard-me",
                "token_type": "Bearer",
            },
        )

    app.state.oidc = GoogleOIDC(settings, transport=httpx.MockTransport(provider))
    with TestClient(
        app, base_url=settings.public_origin, follow_redirects=False
    ) as client:

        def start(locale="en"):
            response = client.get("/v1/auth/google/login", params={"locale": locale})
            assert response.status_code == 302
            query = parse_qs(urlsplit(response.headers["location"]).query)
            with Session(app.state.engine) as db:
                tx = db.get(
                    LoginTransaction,
                    digest(client.cookies.get(settings.transaction_cookie)),
                )
                pending.update(nonce=query["nonce"][0], verifier=tx.verifier)
            expected = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(pending["verifier"].encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            assert query["code_challenge"] == [expected]
            assert query["code_challenge_method"] == ["S256"]
            assert query["scope"] == ["openid profile email"]
            return {"code": "fake-code", "state": query["state"][0]}

        yield client, app, start, profile
    app.state.engine.dispose()


def test_login_rotation_locale_and_logout(flow):
    client, app, start, profile = flow
    assert client.get("/v1/auth/me").status_code == 401
    callback = start()
    response = client.get("/v1/auth/google/callback", params=callback)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    cookie = response.headers.get_list("set-cookie")[0]
    assert all(
        value in cookie
        for value in [
            "__Host-civicflow_session",
            "HttpOnly",
            "Secure",
            "SameSite=lax",
            "Path=/",
        ]
    )
    assert "Domain=" not in cookie
    me = client.get("/v1/auth/me")
    assert me.json()["preferred_locale"] == "en"
    user_id = me.json()["id"]
    old_session = client.cookies.get(app.state.settings.session_cookie)
    profile["email"] = "changed@example.com"
    client.get("/v1/auth/google/callback", params=start("pt-BR"))
    me = client.get("/v1/auth/me")
    assert me.json()["id"] == user_id
    assert me.json()["email"] == "changed@example.com"
    assert me.json()["preferred_locale"] == "en"
    with Session(app.state.engine) as db:
        assert db.get(BrowserSession, digest(old_session)).revoked
        assert db.scalar(select(func.count()).select_from(User)) == 1
    token = me.headers["x-csrf-token"]
    headers = {"Origin": "https://civicflow.test", "X-CSRF-Token": token}
    raw = client.cookies.get(app.state.settings.session_cookie)
    assert client.post("/v1/auth/logout", headers=headers).status_code == 204
    with TestClient(
        create_app(app.state.settings), base_url="https://civicflow.test"
    ) as other:
        other.cookies.set(app.state.settings.session_cookie, raw)
        assert other.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    "headers,code",
    [
        ({}, "ORIGIN_FORBIDDEN"),
        ({"Origin": "https://evil.test"}, "ORIGIN_FORBIDDEN"),
        ({"Origin": "https://civicflow.test"}, "CSRF_INVALID"),
        ({"Origin": "https://civicflow.test", "X-CSRF-Token": "wrong"}, "CSRF_INVALID"),
    ],
)
def test_mutation_protection(flow, headers, code):
    client, _, start, _ = flow
    client.get("/v1/auth/google/callback", params=start())
    response = client.post("/v1/auth/logout", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == code
    assert client.get("/v1/auth/me").status_code == 200


def test_referer_fallback(flow):
    client, _, start, _ = flow
    client.get("/v1/auth/google/callback", params=start())
    token = client.get("/v1/auth/me").headers["x-csrf-token"]
    assert (
        client.post(
            "/v1/auth/logout",
            headers={"Referer": "https://civicflow.test/", "X-CSRF-Token": token},
        ).status_code
        == 204
    )


@pytest.mark.parametrize("failure", ["state", "binding", "expired", "denied", "replay"])
def test_callback_rejection(flow, failure):
    client, app, start, _ = flow
    callback = start()
    if failure == "state":
        callback["state"] = "wrong"
    if failure == "binding":
        client.cookies.clear()
    if failure == "expired":
        with Session(app.state.engine) as db:
            tx = db.scalar(select(LoginTransaction))
            tx.expires_at = 0
            db.commit()
    if failure == "denied":
        callback["error"] = "access_denied"
    if failure == "replay":
        assert (
            client.get("/v1/auth/google/callback", params=callback).status_code == 303
        )
    response = client.get("/v1/auth/google/callback", params=callback)
    assert response.status_code == 400
    assert response.json() == {"error": {"code": "OIDC_CALLBACK_INVALID"}}
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(BrowserSession)) == (
            1 if failure == "replay" else 0
        )


@pytest.mark.parametrize(
    "path",
    ["https://evil.test", "//evil.test", "/%2f/evil.test", "/\\evil.test", "/other"],
)
def test_open_redirects(flow, path):
    client, _, _, _ = flow
    assert (
        client.get("/v1/auth/google/login", params={"return_to": path}).status_code
        == 422
    )


@pytest.mark.parametrize("field", ["idle_expires_at", "absolute_expires_at", "revoked"])
def test_session_expiry(flow, field):
    client, app, start, _ = flow
    client.get("/v1/auth/google/callback", params=start())
    with Session(app.state.engine) as db:
        session = db.scalar(select(BrowserSession))
        assert session.secret_hash != client.cookies.get(
            app.state.settings.session_cookie
        )
        setattr(session, field, True if field == "revoked" else 0)
        db.commit()
    response = client.get("/v1/auth/me")
    assert response.status_code == 401
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://evil.test"},
        {"aud": "wrong"},
        {"azp": "wrong"},
        {"exp": 0},
        {"iat": 9999999999},
        {"nonce": "wrong"},
        {"sub": ""},
        {"aud": ["client", "other"]},
    ],
)
def test_bad_tokens(keys, change):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": "client",
        "iat": now,
        "exp": now + 600,
        "nonce": "nonce",
        "sub": "subject",
        **change,
    }
    token = jwt.encode({"alg": "RS256"}, claims, keys)
    with pytest.raises(InvalidToken):
        GoogleOIDC(Settings(google_client_id="client")).validate(
            {"id_token": token}, {"keys": [keys.as_dict(is_private=False)]}, "nonce"
        )


def test_bad_signature(keys):
    now = int(time.time())
    token = jwt.encode(
        {"alg": "RS256"},
        {
            "iss": ISSUER,
            "aud": "client",
            "iat": now,
            "exp": now + 600,
            "nonce": "nonce",
            "sub": "subject",
        },
        keys,
    )
    other = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    with pytest.raises(InvalidToken):
        GoogleOIDC(Settings(google_client_id="client")).validate(
            {"id_token": token}, {"keys": [other.as_dict(is_private=False)]}, "nonce"
        )


def test_concurrent_identity_creation(flow):
    from civicflow.auth import resolve_user

    _, app, _, _ = flow

    def create(_):
        with Session(app.state.engine) as db:
            user = resolve_user(db, {"sub": "same-subject"}, "en")
            db.commit()
            return user.id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(create, range(4)))
    assert len(set(ids)) == 1
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(Identity)) == 1


def test_provider_unavailable(flow):
    client, app, start, _ = flow
    callback = start()

    def unavailable(request):
        raise httpx.ConnectError("private provider detail")

    app.state.oidc.transport = httpx.MockTransport(unavailable)
    response = client.get("/v1/auth/google/callback", params=callback)
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "SERVICE_UNAVAILABLE"}}
    assert client.get("/v1/auth/me").status_code == 401


def test_distinct_subjects_with_same_email_are_not_linked(flow):
    client, _, start, profile = flow
    client.get("/v1/auth/google/callback", params=start())
    first = client.get("/v1/auth/me").json()["id"]
    profile["sub"] = "different-subject"
    client.get("/v1/auth/google/callback", params=start())
    assert client.get("/v1/auth/me").json()["id"] != first


def test_migration_roundtrip(auth_database):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    engine = create_engine(auth_database)
    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "users",
        "external_identities",
        "sessions",
        "oidc_transactions",
    }
    engine.dispose()


def test_wrong_algorithm(keys):
    now = int(time.time())
    token = jwt.encode(
        {"alg": "HS256"},
        {
            "iss": ISSUER,
            "aud": "client",
            "iat": now,
            "exp": now + 600,
            "nonce": "nonce",
            "sub": "subject",
        },
        b"a" * 32,
    )
    with pytest.raises(InvalidToken):
        GoogleOIDC(Settings(google_client_id="client")).validate(
            {"id_token": token}, {"keys": [keys.as_dict(is_private=False)]}, "nonce"
        )


def test_development_cookie_attributes(auth_database):
    app = create_app(
        Settings(_env_file=None, database_url=auth_database, secure_cookies=False)
    )
    with TestClient(app, base_url="http://localhost:5173") as client:
        response = client.get("/v1/auth/me")
    cookie = response.headers["set-cookie"]
    assert "civicflow_session_dev=" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Secure" not in cookie and "Domain=" not in cookie
    app.state.engine.dispose()


def test_codespaces_proxy_requires_referer_and_csrf(flow):
    client, app, start, _ = flow
    app.state.settings.trusted_proxy_origin = "http://localhost:5173"
    client.get("/v1/auth/google/callback", params=start())
    csrf = client.get("/v1/auth/me").headers["x-csrf-token"]
    headers = {
        "Origin": "http://localhost:5173",
        "Referer": "https://civicflow.test/",
    }
    rejected = client.post("/v1/auth/logout", headers=headers)
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "CSRF_INVALID"
    headers["X-CSRF-Token"] = csrf
    assert client.post("/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    "origin,referer,enabled",
    [
        ("http://localhost:5173", "https://civicflow.test/", False),
        ("http://localhost:5173", None, True),
        ("http://localhost:5173", "https://evil.test/", True),
        ("http://localhost:5173", "https://civicflow.test.evil.test/", True),
        ("http://localhost:5173", "https://user@civicflow.test/", True),
        ("http://localhost:5173", "https://[broken", True),
        ("http://localhost:8000", "https://civicflow.test/", True),
        ("https://evil.test", "https://civicflow.test/", True),
        ("null", "https://civicflow.test/", True),
    ],
)
def test_proxy_origin_does_not_trust_other_origins(flow, origin, referer, enabled):
    client, app, start, _ = flow
    if enabled:
        app.state.settings.trusted_proxy_origin = "http://localhost:5173"
    client.get("/v1/auth/google/callback", params=start())
    csrf = client.get("/v1/auth/me").headers["x-csrf-token"]
    headers = {
        "Origin": origin,
        "X-CSRF-Token": csrf,
        "X-Forwarded-Host": "civicflow.test",
        "X-Forwarded-Proto": "https",
    }
    if referer is not None:
        headers["Referer"] = referer
    response = client.post("/v1/auth/logout", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_FORBIDDEN"
    assert client.get("/v1/auth/me").status_code == 200


@pytest.mark.parametrize("remaining", [30, 200000])
def test_read_only_dependency_persists_renewal_and_releases_lock(flow, remaining):
    client, app, start, _ = flow
    client.get("/v1/auth/google/callback", params=start())
    now = int(time.time())
    with Session(app.state.engine) as db:
        session = db.scalar(select(BrowserSession))
        session.last_used_at = now - 100
        session.idle_expires_at = now + 10
        session.absolute_expires_at = now + remaining
        db.commit()

    @app.get("/v1/read-only")
    def read_only(
        auth: Authenticated = Depends(require_session),
        db: Session = Depends(database, scope="function"),
    ):
        assert not db.in_transaction()
        # A separate connection can lock the row before this handler returns.
        with Session(app.state.engine) as other:
            renewed = other.scalar(select(BrowserSession).with_for_update(nowait=True))
            assert renewed.last_used_at >= now
            assert renewed.idle_expires_at == min(
                renewed.last_used_at + app.state.settings.session_idle_ttl,
                renewed.absolute_expires_at,
            )
            assert renewed.idle_expires_at > now + 10
        return {"id": auth.user.id}

    assert client.get("/v1/read-only").status_code == 200


@pytest.mark.parametrize("fail", [False, True])
def test_mutation_dependency_owns_transaction_and_fence(flow, fail):
    client, app, start, _ = flow
    client.get("/v1/auth/google/callback", params=start())
    token = client.get("/v1/auth/me").headers["x-csrf-token"]
    with Session(app.state.engine) as db:
        session = db.scalar(select(BrowserSession))
        session.last_used_at = 1
        db.commit()

    @app.post("/v1/mutate")
    def mutate(auth: Authenticated = Depends(require_mutation)):
        with Session(app.state.engine) as other:
            with pytest.raises(OperationalError):
                other.scalar(select(BrowserSession).with_for_update(nowait=True))
        auth.user.display_name = "Changed"
        if fail:
            raise AuthError("VALIDATION_ERROR", 422)
        auth.session.revoked = True
        return {"ok": True}

    response = client.post(
        "/v1/mutate",
        headers={"Origin": app.state.settings.public_origin, "X-CSRF-Token": token},
    )
    assert response.status_code == (422 if fail else 200)
    with Session(app.state.engine) as db:
        session = db.scalar(select(BrowserSession).with_for_update(nowait=True))
        assert session.revoked is (not fail)
        assert (session.last_used_at == 1) is fail
        assert db.get(User, session.user_id).display_name == (
            "Citizen" if fail else "Changed"
        )
    if not fail:
        assert client.get("/v1/auth/me").status_code == 401


def test_mutation_commit_failure_returns_error_and_rolls_back(flow):
    client, app, start, _ = flow
    client.get("/v1/auth/google/callback", params=start())
    token = client.get("/v1/auth/me").headers["x-csrf-token"]

    def fail_commit(db):
        raise SQLAlchemyError("test commit failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        response = client.post(
            "/v1/auth/logout",
            headers={"Origin": app.state.settings.public_origin, "X-CSRF-Token": token},
        )
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert response.status_code == 503
    with Session(app.state.engine) as db:
        assert not db.scalar(
            select(BrowserSession).with_for_update(nowait=True)
        ).revoked


GOOGLE_METADATA = {
    "issuer": ISSUER,
    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_endpoint": "https://oauth2.googleapis.com/token",
    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
}


@pytest.mark.parametrize("port", ["", ":443"])
def test_google_discovery_accepts_official_endpoints(port):
    metadata = {
        key: value.replace(".com/", ".com" + port + "/") if key != "issuer" else value
        for key, value in GOOGLE_METADATA.items()
    }
    oidc = GoogleOIDC(
        Settings(_env_file=None),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=metadata)
        ),
    )
    assert oidc.metadata() == metadata


@pytest.mark.parametrize(
    "key", ["authorization_endpoint", "token_endpoint", "jwks_uri"]
)
@pytest.mark.parametrize(
    "destination",
    [
        "https://evil.test/path",
        "https://accounts.google.com.evil.test/path",
        "https://untrusted.googleapis.com/path",
        "https://accounts.google.com@evil.test/path",
        "https://@accounts.google.com/path",
        "https://user:password@accounts.google.com/path",
        "https://accounts.google.com:444/path",
        "https://accounts.google.com:bad/path",
        "https://accounts.google.com:/path",
        "https://accounts.google.com./path",
        "http://accounts.google.com/path",
        "//accounts.google.com/path",
        "https://[broken/path",
        "https://accounts.google.com/pa\nth",
        " https://accounts.google.com/path",
        "https://accounts.google.com/path?next=evil",
        "https://accounts.google.com/path#fragment",
        "https://accounts.google.com/pa\\th",
        "",
        None,
        42,
        {},
    ],
)
def test_google_discovery_rejects_untrusted_or_malformed_endpoints(key, destination):
    metadata = {**GOOGLE_METADATA, key: destination}
    oidc = GoogleOIDC(
        Settings(_env_file=None),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=metadata)
        ),
    )
    with pytest.raises(ProviderUnavailable):
        oidc.metadata()


@pytest.mark.parametrize(
    "key", ["authorization_endpoint", "token_endpoint", "jwks_uri"]
)
def test_google_discovery_rejects_wrong_endpoint_role(key):
    metadata = {**GOOGLE_METADATA, key: "https://openidconnect.googleapis.com/path"}
    oidc = GoogleOIDC(
        Settings(_env_file=None),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=metadata)
        ),
    )
    with pytest.raises(ProviderUnavailable):
        oidc.metadata()
