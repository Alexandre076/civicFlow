"""BFF routes and reusable session/CSRF dependencies backed by PostgreSQL."""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from civicflow.models import BrowserSession, Identity, LoginTransaction, User
from civicflow.oidc import ISSUER, InvalidToken, ProviderUnavailable

router = APIRouter(prefix="/v1/auth")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def secret():
    return secrets.token_urlsafe(32)


class AuthError(Exception):
    def __init__(self, code, status, clear_session=False, clear_login=False):
        self.code, self.status = code, status
        self.clear_session, self.clear_login = clear_session, clear_login


def cookie(response, settings, name, value, max_age):
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def auth_error(request, exc):
    response = JSONResponse({"error": {"code": exc.code}}, status_code=exc.status)
    if exc.clear_session:
        cookie(
            response,
            request.app.state.settings,
            request.app.state.settings.session_cookie,
            "",
            0,
        )
    if exc.clear_login:
        cookie(
            response,
            request.app.state.settings,
            request.app.state.settings.transaction_cookie,
            "",
            0,
        )
    return response


def database(request: Request):
    with Session(request.app.state.engine, expire_on_commit=False) as db:
        yield db


@dataclass
class Authenticated:
    user: User
    session: BrowserSession


def require_session(request: Request, db: Session = Depends(database)):
    settings = request.app.state.settings
    raw = request.cookies.get(settings.session_cookie)
    if not raw:
        raise AuthError("AUTH_REQUIRED", 401, clear_session=True)
    # Row locking serializes activity/logout across workers. Future writes must
    # hold/recheck this session fence in the same transaction as their commit.
    session = db.scalar(
        select(BrowserSession)
        .where(BrowserSession.secret_hash == digest(raw))
        .with_for_update()
    )
    if session is None:
        raise AuthError("AUTH_REQUIRED", 401, clear_session=True)
    now = int(time.time())
    if (
        session.revoked
        or min(session.idle_expires_at, session.absolute_expires_at) <= now
    ):
        raise AuthError("SESSION_EXPIRED", 401, clear_session=True)
    session.last_used_at = now
    session.idle_expires_at = min(
        now + settings.session_idle_ttl, session.absolute_expires_at
    )
    user = db.get(User, session.user_id)
    return Authenticated(user, session)


def referer_origin(request: Request) -> str:
    try:
        ref = urlsplit(request.headers.get("referer", ""))
        if (
            ref.scheme not in {"http", "https"}
            or not ref.hostname
            or ref.username is not None
        ):
            return ""
        return f"{ref.scheme}://{ref.netloc}"
    except ValueError:
        return ""


def require_mutation(request: Request, auth: Authenticated = Depends(require_session)):
    settings = request.app.state.settings
    origin = request.headers.get("origin")
    if origin is None:
        origin = referer_origin(request)
    elif settings.trusted_proxy_origin and origin == settings.trusted_proxy_origin:
        # Codespaces rewrites same-origin requests to loopback. Require independent
        # browser Referer evidence; never infer the public origin from proxy headers.
        origin = referer_origin(request)
    if origin != settings.public_origin:
        raise AuthError("ORIGIN_FORBIDDEN", 403)
    token = request.headers.get("x-csrf-token", "")
    if not secrets.compare_digest(token.encode(), auth.session.csrf_token.encode()):
        raise AuthError("CSRF_INVALID", 403)
    return auth


def user_dto(user):
    return {
        "id": user.id,
        "display_name": user.display_name,
        "email": user.email,
        "preferred_locale": user.preferred_locale,
    }


@router.get("/google/login")
def login(request: Request, db: Session = Depends(database)):
    settings = request.app.state.settings
    if not settings.google_client_id or not settings.google_client_secret:
        raise AuthError("SERVICE_UNAVAILABLE", 503)
    path = request.query_params.get("return_to", "/")
    locale = request.query_params.get("locale", "pt-BR")
    if path not in settings.allowed_return_paths or locale not in {"pt-BR", "en"}:
        raise AuthError("VALIDATION_ERROR", 422)
    binding, state, nonce, verifier = secret(), secret(), secret(), secret()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    try:
        url = request.app.state.oidc.authorization_url(state, nonce, challenge)
    except ProviderUnavailable:
        raise AuthError("SERVICE_UNAVAILABLE", 503) from None
    old = request.cookies.get(settings.transaction_cookie)
    if old:
        db.execute(
            delete(LoginTransaction).where(LoginTransaction.binding_hash == digest(old))
        )
    db.execute(
        delete(LoginTransaction).where(LoginTransaction.expires_at <= int(time.time()))
    )
    db.add(
        LoginTransaction(
            binding_hash=digest(binding),
            state_hash=digest(state),
            nonce=nonce,
            verifier=verifier,
            expires_at=int(time.time()) + settings.login_ttl,
            return_to=path,
            locale=locale,
        )
    )
    db.commit()
    response = RedirectResponse(url, status_code=302)
    cookie(response, settings, settings.transaction_cookie, binding, settings.login_ttl)
    return response


def resolve_user(db, claims, locale):
    # A savepoint rolls back the losing user insert if a concurrent first login
    # wins the unique issuer/subject constraint; PostgreSQL waits for that commit.
    identity = db.scalar(
        select(Identity).where(
            Identity.issuer == ISSUER, Identity.subject == claims["sub"]
        )
    )
    if identity is None:
        try:
            with db.begin_nested():
                user = User(id=secret(), preferred_locale=locale)
                db.add(user)
                db.flush()
                identity = Identity(
                    id=secret(), issuer=ISSUER, subject=claims["sub"], user_id=user.id
                )
                db.add(identity)
                db.flush()
        except IntegrityError:
            identity = db.scalar(
                select(Identity).where(
                    Identity.issuer == ISSUER, Identity.subject == claims["sub"]
                )
            )
            if identity is None:
                raise
    user = db.get(User, identity.user_id)
    user.display_name = (
        claims.get("name") if isinstance(claims.get("name"), str) else None
    )
    user.email = claims.get("email") if isinstance(claims.get("email"), str) else None
    if user.display_name:
        user.display_name = user.display_name[:512]
    if user.email:
        user.email = user.email[:512]
    return user


@router.get("/google/callback")
def callback(request: Request, db: Session = Depends(database)):
    settings = request.app.state.settings
    raw = request.cookies.get(settings.transaction_cookie, "")
    # DELETE RETURNING consumes once even across workers, before token exchange.
    transaction = db.scalar(
        delete(LoginTransaction)
        .where(LoginTransaction.binding_hash == digest(raw))
        .returning(LoginTransaction)
    )
    db.commit()
    query = request.query_params
    if (
        transaction is None
        or transaction.expires_at <= int(time.time())
        or not secrets.compare_digest(
            transaction.state_hash, digest(query.get("state", ""))
        )
        or "error" in query
        or not query.get("code")
        or any(len(query.getlist(key)) > 1 for key in ("code", "state", "error"))
    ):
        raise AuthError("OIDC_CALLBACK_INVALID", 400, clear_login=True)
    try:
        claims = request.app.state.oidc.exchange(
            query["code"], transaction.verifier, transaction.nonce
        )
    except InvalidToken:
        raise AuthError("OIDC_CALLBACK_INVALID", 400, clear_login=True) from None
    except ProviderUnavailable:
        raise AuthError("SERVICE_UNAVAILABLE", 503, clear_login=True) from None
    user = resolve_user(db, claims, transaction.locale)
    old = request.cookies.get(settings.session_cookie)
    if old:
        db.execute(
            update(BrowserSession)
            .where(BrowserSession.secret_hash == digest(old))
            .values(revoked=True)
        )
    raw_session, now = secret(), int(time.time())
    db.add(
        BrowserSession(
            secret_hash=digest(raw_session),
            user_id=user.id,
            csrf_token=secret(),
            created_at=now,
            last_used_at=now,
            idle_expires_at=now
            + min(settings.session_idle_ttl, settings.session_absolute_ttl),
            absolute_expires_at=now + settings.session_absolute_ttl,
            revoked=False,
        )
    )
    db.commit()
    response = RedirectResponse(transaction.return_to, status_code=303)
    cookie(
        response,
        settings,
        settings.session_cookie,
        raw_session,
        settings.session_absolute_ttl,
    )
    cookie(response, settings, settings.transaction_cookie, "", 0)
    return response


@router.get("/me")
def me(auth: Authenticated = Depends(require_session), db: Session = Depends(database)):
    result = user_dto(auth.user)
    token = auth.session.csrf_token
    db.commit()
    return JSONResponse(result, headers={"X-CSRF-Token": token})


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    auth: Authenticated = Depends(require_mutation),
    db: Session = Depends(database),
):
    auth.session.revoked = True
    db.commit()
    response = Response(status_code=204)
    settings = request.app.state.settings
    cookie(response, settings, settings.session_cookie, "", 0)
    return response
