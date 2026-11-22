from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_default_to_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INSIGHTPILOT_ENVIRONMENT", raising=False)

    assert Settings(_env_file=None).environment == "development"


def test_settings_load_dotenv_and_prefer_the_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("INSIGHTPILOT_ENVIRONMENT", raising=False)
    (tmp_path / ".env").write_text(
        "INSIGHTPILOT_ENVIRONMENT=staging\n", encoding="utf-8"
    )

    assert Settings().environment == "staging"

    monkeypatch.setenv("INSIGHTPILOT_ENVIRONMENT", "production")
    assert Settings().environment == "production"


def test_settings_reject_an_unknown_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSIGHTPILOT_ENVIRONMENT", "unknown")

    with pytest.raises(ValidationError, match="environment"):
        Settings(_env_file=None)


def test_settings_load_runtime_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSIGHTPILOT_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("INSIGHTPILOT_BIND_PORT", "18014")

    settings = Settings(environment="test", _env_file=None)

    assert settings.log_level == "WARNING"
    assert settings.bind_port == 18014


def test_settings_reject_an_unknown_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSIGHTPILOT_LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError, match="log_level"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "origin", ["*", "https://example.com/path", "https://user@example.com"]
)
def test_settings_reject_invalid_allowed_origins(origin: str) -> None:
    with pytest.raises(ValidationError, match="allowed_origins"):
        Settings(allowed_origins=[origin], _env_file=None)
