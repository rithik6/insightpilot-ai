import json
import logging
import sys
from datetime import UTC, datetime
from enum import StrEnum
from math import inf
from uuid import UUID

from pydantic import ValidationError

from app.core.config import LogLevel, Settings


class LogEvent(StrEnum):
    HTTP_REQUEST = "http_request"
    HTTP_REQUEST_FAILED = "http_request_failed"
    API_STARTING = "api_starting"
    API_FAILED = "api_failed"
    WORKER_STARTING = "worker_starting"
    WORKER_STOPPED = "worker_stopped"
    WORKER_FAILED = "worker_failed"
    CONFIGURATION_INVALID = "configuration_invalid"
    DIAGNOSTIC = "diagnostic"


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = record.msg if isinstance(record.msg, LogEvent) else LogEvent.DIAGNOSTIC
        source = record.name.partition(".")[0]
        payload: dict[str, str | int | float] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "source": source if source in {"app", "uvicorn", "rq"} else "external",
            "event": event,
        }

        # Serialize approved metadata only. Messages, arguments and tracebacks can contain secrets.
        if event in {LogEvent.HTTP_REQUEST, LogEvent.HTTP_REQUEST_FAILED}:
            request_id = getattr(record, "request_id", None)
            if isinstance(request_id, UUID) and request_id.version == 4:
                payload["request_id"] = request_id.hex
            status_code = getattr(record, "status_code", None)
            if isinstance(status_code, int) and 100 <= status_code <= 599:
                payload["status_code"] = status_code
            duration_ms = getattr(record, "duration_ms", None)
            if isinstance(duration_ms, float) and 0 <= duration_ms < inf:
                payload["duration_ms"] = duration_ms

        return json.dumps(payload, separators=(",", ":"))


def configure_logging(level: LogLevel) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(JsonLogFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


def load_runtime_settings() -> Settings:
    try:
        settings = Settings()
    except ValidationError:
        configure_logging("ERROR")
        logging.getLogger(__name__).error(LogEvent.CONFIGURATION_INVALID)
        raise SystemExit(1) from None

    configure_logging(settings.log_level)
    return settings
