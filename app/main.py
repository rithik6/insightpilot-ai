import logging

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from app.api.routes.health import router as health_router
from app.core.config import Settings

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    app = FastAPI(
        title="InsightPilot AI",
        openapi_url="/openapi.json" if settings.environment == "development" else None,
    )
    app.include_router(health_router, prefix="/api/v1")

    @app.middleware("http")
    async def handle_unexpected_error(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            return await call_next(request)
        # This boundary catches unexpected request failures without logging their details.
        except Exception:  # noqa: BLE001
            logger.error("Unhandled HTTP request error")
            return JSONResponse(
                status_code=500, content={"detail": "Internal server error."}
            )

    return app
