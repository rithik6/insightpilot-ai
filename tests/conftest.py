from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(environment="test", postgres_host=None, redis_url=None)
    with TestClient(create_app(settings)) as client:
        yield client
