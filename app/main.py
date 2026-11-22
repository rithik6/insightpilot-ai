import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker
from starlette.middleware.base import RequestResponseEndpoint

from app.api.routes.health import router as health_router
from app.api.routes.sessions import router as sessions_router
from app.core.config import Settings
from app.core.logging import LogEvent
from app.db.session import open_database_engine

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = (
            open_database_engine(settings)
            if settings.postgres_host and settings.postgres_password
            else None
        )
        if engine is not None:
            application.state.database_sessions = sessionmaker(engine)
        try:
            yield
        finally:
            application.state.database_sessions = None
            if engine is not None:
                engine.dispose()

    app = FastAPI(
        title="InsightPilot AI",
        openapi_url="/openapi.json" if settings.environment == "development" else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database_sessions = None
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")

    @app.middleware("http")
    async def log_http_request(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = uuid4()
        started_at = perf_counter()
        event = LogEvent.HTTP_REQUEST
        level = logging.INFO
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            event = LogEvent.HTTP_REQUEST_FAILED
            level = logging.ERROR
            response = JSONResponse(
                status_code=500, content={"detail": "Internal server error."}
            )

        response.headers["X-Request-ID"] = request_id.hex
        logger.log(
            level,
            event,
            extra={
                "request_id": request_id,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            },
        )
        return response

    return app
