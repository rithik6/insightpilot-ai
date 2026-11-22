from datetime import UTC, datetime, timedelta
from socket import socket

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

from app.api.dependencies import DatabaseSession
from app.core.config import Settings
from app.db.models import AnonymousSession
from app.db.repositories.sessions import add_session
from app.db.session import open_database_engine
from app.main import create_app

ORIGIN = {"Origin": "http://testserver"}


def test_failed_write_rolls_back_and_releases_connection(
    database_settings: Settings, postgres_engine: Engine
) -> None:
    app = create_app(database_settings)

    @app.post("/test-failed-write")
    def fail_after_one_insert(database: DatabaseSession) -> None:
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(days=1)
        with database.begin():
            add_session(database, b"x" * 32, created_at, expires_at)
            database.flush()
            add_session(database, b"x" * 32, created_at, expires_at)

    with TestClient(app) as browser:
        engine = app.state.database_sessions.kw["bind"]
        assert isinstance(engine.pool, QueuePool)
        result = browser.post("/test-failed-write")
        assert result.status_code == 503
        assert result.json() == {"detail": "Data storage unavailable."}
        assert engine.pool.checkedout() == 0

        with postgres_engine.connect() as connection:
            assert connection.execute(select(AnonymousSession.id)).first() is None

        assert browser.post("/api/v1/session", headers=ORIGIN).status_code == 201
        assert engine.pool.checkedout() == 0


def test_read_returns_connection_and_shutdown_disposes_pool(
    database_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = open_database_engine(database_settings)
    pool = engine.pool
    assert isinstance(pool, QueuePool)
    monkeypatch.setattr("app.main.open_database_engine", lambda _: engine)

    with TestClient(create_app(database_settings)) as browser:
        assert browser.post("/api/v1/session", headers=ORIGIN).status_code == 201
        result = browser.get("/api/v1/history")
        assert result.json() == {"conversations": [], "reports": []}
        assert pool.checkedout() == 0
        with engine.connect() as connection:
            assert connection.get_isolation_level() == "READ COMMITTED"
        assert pool.checkedin() == 1

    assert engine.pool is not pool
    assert pool.checkedin() == 0


def test_connection_failure_has_a_safe_response() -> None:
    with socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        settings = Settings(
            environment="test",
            allowed_origins=[ORIGIN["Origin"]],
            postgres_host="127.0.0.1",
            postgres_port=reserved.getsockname()[1],
            postgres_password=SecretStr("test-unavailable-password"),
            _env_file=None,
        )
        with TestClient(create_app(settings)) as browser:
            result = browser.post("/api/v1/session", headers=ORIGIN)

    assert result.status_code == 503
    assert result.json() == {"detail": "Data storage unavailable."}
    assert "set-cookie" not in result.headers
