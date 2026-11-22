from hashlib import sha256
from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.config import Environment, Settings
from app.db.models import AnonymousSession
from app.main import create_app

LOCAL_ORIGIN = {"Origin": "http://testserver"}


def test_session_storage_unavailable(client: TestClient) -> None:
    response = client.post(
        "/api/v1/session", headers={"Origin": "http://127.0.0.1:8000"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Data storage unavailable."}
    assert "set-cookie" not in response.headers


def test_browser_reuses_session_and_database_stores_digest(
    database_settings: Settings, postgres_engine: Engine
) -> None:
    with TestClient(create_app(database_settings)) as browser:
        first = browser.post("/api/v1/session", headers=LOCAL_ORIGIN)
        second = browser.post("/api/v1/session", headers=LOCAL_ORIGIN)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json() == second.json()
    assert set(first.json()) == {"expires_at", "csrf_token"}
    assert (
        first.headers["cache-control"] == second.headers["cache-control"] == "no-store"
    )
    assert "set-cookie" not in second.headers

    cookie = SimpleCookie(first.headers["set-cookie"])["insightpilot_session"]
    assert len(cookie.value) == 43
    assert cookie["path"] == "/"
    assert cookie["httponly"] and cookie["samesite"] == "lax"
    assert not cookie["secure"]
    assert cookie["max-age"] == str(database_settings.session_lifetime_days * 86400)

    with postgres_engine.connect() as connection:
        digests = (
            connection.execute(select(AnonymousSession.token_hash)).scalars().all()
        )
    assert digests == [sha256(cookie.value.encode("ascii")).digest()]


def test_invalid_cookie_creates_a_separate_session(database_settings: Settings) -> None:
    app = create_app(database_settings)
    with TestClient(app) as browser:
        first = browser.post("/api/v1/session", headers=LOCAL_ORIGIN)
        second = browser.post(
            "/api/v1/session",
            headers={**LOCAL_ORIGIN, "Cookie": "insightpilot_session=invalid"},
        )

    assert first.status_code == second.status_code == 201
    first_value = SimpleCookie(first.headers["set-cookie"])[
        "insightpilot_session"
    ].value
    second_value = SimpleCookie(second.headers["set-cookie"])[
        "insightpilot_session"
    ].value
    assert first_value != second_value


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_https_session_cookie_flags(
    database_settings: Settings, environment: Environment
) -> None:
    database_settings.environment = environment
    with TestClient(
        create_app(database_settings), base_url="https://testserver"
    ) as browser:
        first = browser.post(
            "/api/v1/session", headers={"Origin": "https://testserver"}
        )
        second = browser.post(
            "/api/v1/session", headers={"Origin": "https://testserver"}
        )

    cookie = SimpleCookie(first.headers["set-cookie"])["__Host-insightpilot_session"]
    assert cookie["secure"] and cookie["httponly"]
    assert cookie["path"] == "/" and not cookie["domain"]
    assert cookie["samesite"] == "lax"
    assert second.status_code == 200
