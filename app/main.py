import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from app.api.routes.health import router as health_router
from app.core.config import Settings
from app.core.logging import LogEvent

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    app = FastAPI(
        title="InsightPilot AI",
        openapi_url="/openapi.json" if settings.environment == "development" else None,
    )
    app.state.settings = settings
    app.include_router(health_router, prefix="/api/v1")

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
