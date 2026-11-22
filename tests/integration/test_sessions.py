from hashlib import sha256
from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL

from app.core.config import Environment, Settings
from app.db.models import AnonymousSession
from app.main import create_app


def test_session_storage_unavailable(client: TestClient) -> None:
    response = client.post("/api/v1/session")

    assert response.status_code == 503
    assert response.json() == {"detail": "Session storage unavailable."}
    assert "set-cookie" not in response.headers


def test_browser_reuses_session_and_database_stores_digest(
    database_settings: Settings, migrated_postgres_url: URL
) -> None:
    with TestClient(create_app(database_settings)) as browser:
        first = browser.post("/api/v1/session")
        second = browser.post("/api/v1/session")

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json() == second.json()
    assert set(first.json()) == {"expires_at"}
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

    engine = create_engine(migrated_postgres_url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            digests = (
                connection.execute(select(AnonymousSession.token_hash)).scalars().all()
            )
        assert digests == [sha256(cookie.value.encode("ascii")).digest()]
    finally:
        engine.dispose()


def test_invalid_cookie_creates_a_separate_session(database_settings: Settings) -> None:
    app = create_app(database_settings)
    with TestClient(app) as browser:
        first = browser.post("/api/v1/session")
        second = browser.post(
            "/api/v1/session", headers={"Cookie": "insightpilot_session=invalid"}
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
        first = browser.post("/api/v1/session")
        second = browser.post("/api/v1/session")

    cookie = SimpleCookie(first.headers["set-cookie"])["__Host-insightpilot_session"]
    assert cookie["secure"] and cookie["httponly"]
    assert cookie["path"] == "/" and not cookie["domain"]
    assert cookie["samesite"] == "lax"
    assert second.status_code == 200
