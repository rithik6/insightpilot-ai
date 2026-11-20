import json
import logging
from unittest.mock import MagicMock
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import Environment, Settings
from app.core.logging import JsonLogFormatter
from app.main import create_app
from app.services import readiness


def test_health_endpoint() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_ids_are_generated_and_match_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    supplied_id = "a" * 32
    private_value = "test-private-request-value"
    headers = {"X-Request-ID": supplied_id, "Authorization": private_value}
    with (
        caplog.at_level(logging.INFO, logger="app.main"),
        TestClient(create_app(Settings(environment="test"))) as client,
    ):
        success = client.get(f"/api/v1/health?value={private_value}", headers=headers)
        missing = client.get(f"/{private_value}", headers=headers)

    request_ids = [success.headers["X-Request-ID"], missing.headers["X-Request-ID"]]
    assert len({supplied_id, *request_ids}) == 3
    assert all(UUID(request_id).version == 4 for request_id in request_ids)

    formatter = JsonLogFormatter()
    formatted = [formatter.format(record) for record in caplog.records]
    assert len(formatted) == 2
    for line, response in zip(formatted, [success, missing], strict=True):
        assert private_value not in line
        payload = json.loads(line)
        assert payload["event"] == "http_request"
        assert payload["request_id"] == response.headers["X-Request-ID"]
        assert payload["status_code"] == response.status_code
        assert payload["duration_ms"] >= 0


def test_readiness_requires_service_configuration() -> None:
    settings = Settings(environment="test", postgres_host=None, redis_url=None)

    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health").status_code == 200
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Dependencies unavailable."}


@pytest.mark.parametrize("unavailable", [None, "postgres", "redis"])
def test_readiness_checks_both_services(
    monkeypatch: pytest.MonkeyPatch, unavailable: str | None
) -> None:
    settings = Settings(
        environment="test",
        postgres_host="postgres",
        postgres_password=SecretStr("test-password"),
        redis_url=SecretStr("redis://redis:6379/0"),
    )
    connect_postgres = MagicMock()
    connect_redis = MagicMock()
    redis = connect_redis.return_value.__enter__.return_value
    redis.ping.return_value = True
    if unavailable == "postgres":
        connect_postgres.side_effect = psycopg.OperationalError(
            "private database detail"
        )
    if unavailable == "redis":
        redis.ping.side_effect = RedisConnectionError("private redis detail")
    monkeypatch.setattr(readiness.psycopg, "connect", connect_postgres)
    monkeypatch.setattr(readiness, "open_redis_probe", connect_redis)

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/ready")

    if unavailable is None:
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
        postgres = connect_postgres.return_value.__enter__.return_value
        postgres.execute.assert_called_once_with("SELECT 1")
        redis.ping.assert_called_once_with()
    else:
        assert response.status_code == 503
        assert response.json() == {"detail": "Dependencies unavailable."}


def test_openapi_is_available_in_development() -> None:
    with TestClient(create_app(Settings(environment="development"))) as client:
        assert client.get("/docs").status_code == 200
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]


@pytest.mark.parametrize("environment", ["test", "staging", "production"])
def test_openapi_is_disabled_outside_development(environment: Environment) -> None:
    with TestClient(create_app(Settings(environment=environment))) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_unexpected_error_returns_safe_response_and_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(Settings(environment="test"))
    private_detail = "private exception detail from test"

    @app.get("/test-error")
    async def fail() -> None:
        raise RuntimeError(private_detail)

    with caplog.at_level(logging.ERROR, logger="app.main"), TestClient(app) as client:
        response = client.get("/test-error")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    assert len(caplog.records) == 1
    record = caplog.records[0]
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["event"] == "http_request_failed"
    assert payload["level"] == "ERROR"
    assert payload["status_code"] == 500
    assert payload["request_id"] == response.headers["X-Request-ID"]
    assert private_detail not in str(payload)
    assert record.exc_info is None
