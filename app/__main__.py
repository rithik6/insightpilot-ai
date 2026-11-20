import logging

import uvicorn

from app.core.logging import LogEvent, load_runtime_settings
from app.main import create_app

logger = logging.getLogger("app.api")


def main() -> None:
    settings = load_runtime_settings()
    logger.info(LogEvent.API_STARTING)
    try:
        uvicorn.run(
            create_app(settings),
            host=settings.bind_host,
            port=settings.bind_port,
            log_config=None,
            access_log=False,
        )
    except Exception:  # noqa: BLE001
        logger.error(LogEvent.API_FAILED)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
