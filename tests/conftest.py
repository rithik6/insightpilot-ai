import os
import subprocess
from collections.abc import Iterator
from secrets import token_urlsafe
from time import monotonic, sleep
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.config import database_url
from app.main import create_app


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--postgres",
        action="store_true",
        help="Run tests on disposable PostgreSQL in Docker",
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(environment="test", postgres_host=None, redis_url=None)
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture(scope="session")
def postgres_server_url(pytestconfig: pytest.Config) -> Iterator[URL]:
    if not pytestconfig.getoption("--postgres"):
        pytest.skip("Use --postgres to run the PostgreSQL integration tests.")

    password = token_urlsafe(32)
    image = subprocess.check_output(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "config",
            "--images",
            "postgres",
        ],
        env={**os.environ, "INSIGHTPILOT_POSTGRES_PASSWORD": password},
        text=True,
    ).strip()
    container = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "--detach",
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_PASSWORD",
            image,
        ],
        env={**os.environ, "POSTGRES_PASSWORD": password},
        text=True,
    ).strip()
    try:
        bind = subprocess.check_output(
            ["docker", "port", container, "5432/tcp"], text=True
        ).strip()
        host, port = bind.rsplit(":", 1)
        assert host == "127.0.0.1"
        url = database_url(
            Settings(
                environment="test",
                postgres_host=host,
                postgres_port=int(port),
                postgres_user="postgres",
                postgres_database="postgres",
                postgres_password=SecretStr(password),
                _env_file=None,
            )
        )
        deadline = monotonic() + 30
        while True:
            try:
                with psycopg.connect(
                    host=host,
                    port=port,
                    user="postgres",
                    dbname="postgres",
                    password=password,
                    connect_timeout=2,
                ):
                    break
            except psycopg.OperationalError:
                if monotonic() >= deadline:
                    pytest.fail(
                        "The disposable PostgreSQL container did not become ready."
                    )
                sleep(0.2)
        yield url
    finally:
        subprocess.run(
            ["docker", "stop", container], check=True, stdout=subprocess.DEVNULL
        )


@pytest.fixture
def postgres_url(postgres_server_url: URL) -> Iterator[URL]:
    name = f"test_{uuid4().hex}"
    engine = create_engine(
        postgres_server_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        try:
            yield postgres_server_url.set(database=name)
        finally:
            with engine.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
    finally:
        engine.dispose()


@pytest.fixture
def migrated_postgres_url(postgres_url: URL) -> URL:
    command.upgrade(
        Config("alembic.ini", attributes={"database_url": postgres_url}), "head"
    )
    return postgres_url


@pytest.fixture
def postgres_engine(migrated_postgres_url: URL) -> Iterator[Engine]:
    engine = create_engine(
        migrated_postgres_url, poolclass=NullPool, hide_parameters=True
    )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def database_settings(migrated_postgres_url: URL) -> Settings:
    url = migrated_postgres_url
    assert url.username and url.password and url.host and url.port and url.database
    return Settings(
        environment="test",
        allowed_origins=["http://testserver", "https://testserver"],
        postgres_host=url.host,
        postgres_port=url.port,
        postgres_user=url.username,
        postgres_password=SecretStr(url.password),
        postgres_database=url.database,
        _env_file=None,
    )
