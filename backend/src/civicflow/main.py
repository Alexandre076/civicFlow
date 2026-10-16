"""ASGI entry point and application factory."""

from fastapi import FastAPI

from civicflow.api.routes.health import router as health_router
from civicflow.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(health_router)
    return app


app = create_app()
