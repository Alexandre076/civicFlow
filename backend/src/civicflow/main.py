"""ASGI entry point and application factory."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from civicflow.api.routes.health import router as health_router
from civicflow.auth import AuthError, auth_error
from civicflow.auth import router as auth_router
from civicflow.config import Settings
from civicflow.oidc import GoogleOIDC


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    app = FastAPI(title=settings.app_name)
    app.state.settings = settings
    app.state.engine = create_engine(settings.database_url, hide_parameters=True)
    app.state.oidc = GoogleOIDC(settings)
    app.add_exception_handler(AuthError, auth_error)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse({"error": {"code": "SERVICE_UNAVAILABLE"}}, status_code=503)

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.include_router(auth_router)
    app.include_router(health_router)
    return app


app = create_app()
