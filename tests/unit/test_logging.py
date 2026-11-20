import json
import logging
from uuid import uuid4

from app.core.logging import JsonLogFormatter, LogEvent


def test_json_formatter_drops_unapproved_third_party_data() -> None:
    private_value = "test-private-diagnostic-value"
    record = logging.LogRecord(
        f"rq.{private_value}",
        logging.ERROR,
        "worker.py",
        1,
        "Failed job: %s",
        (private_value,),
        (RuntimeError, RuntimeError(private_value), None),
    )
    record.__dict__.update(
        authorization=private_value,
        password=private_value,
        request_id=uuid4(),
        status_code=500,
        duration_ms=3.5,
    )

    serialized = JsonLogFormatter().format(record)
    payload = json.loads(serialized)

    assert private_value not in serialized
    assert set(payload) == {"timestamp", "level", "source", "event"}
    assert payload["level"] == "ERROR"
    assert payload["source"] == "rq"
    assert payload["event"] == "diagnostic"


def test_json_formatter_omits_invalid_request_metadata() -> None:
    record = logging.LogRecord(
        "app.main", logging.INFO, "main.py", 1, LogEvent.HTTP_REQUEST, (), None
    )
    record.__dict__.update(
        request_id="a" * 32,
        status_code=1000,
        duration_ms=float("nan"),
    )

    payload = json.loads(JsonLogFormatter().format(record))

    assert set(payload) == {"timestamp", "level", "source", "event"}
    assert payload["event"] == "http_request"
