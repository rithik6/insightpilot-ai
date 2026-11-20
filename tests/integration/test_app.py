import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import Environment, Settings
from app.main import create_app


def test_health_endpoint() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
    assert caplog.messages == ["Unhandled HTTP request error"]
    assert all(record.exc_info is None for record in caplog.records)
