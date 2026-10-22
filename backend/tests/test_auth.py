import base64
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from authlib.jose import JsonWebKey, jwt
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from civicflow.auth import digest
from civicflow.config import Settings
from civicflow.main import create_app
from civicflow.models import BrowserSession, Identity, LoginTransaction, User
from civicflow.oidc import ISSUER, GoogleOIDC, InvalidToken


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
                    "token_endpoint": ISSUER + "/token",
                    "jwks_uri": ISSUER + "/keys",
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
