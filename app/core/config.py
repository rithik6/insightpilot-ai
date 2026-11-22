from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INSIGHTPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Environment = "development"
    log_level: LogLevel = "INFO"
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8000, ge=1, le=65535)
    session_lifetime_days: int = Field(default=90, ge=1, le=365)
    allowed_origins: list[str] = Field(default_factory=list)
    postgres_host: str | None = None
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_database: str = "insightpilot"
    postgres_user: str = "insightpilot"
    postgres_password: SecretStr | None = None
    redis_url: SecretStr | None = None

    @property
    def secure_session_cookie(self) -> bool:
        return self.environment in {"staging", "production"}

    @property
    def browser_origins(self) -> list[str]:
        if self.allowed_origins or self.secure_session_cookie:
            return self.allowed_origins
        return [
            f"http://{host}:{self.bind_port}" for host in ("localhost", "127.0.0.1")
        ]

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or "*" in origin
                or any(character.isspace() for character in origin)
                or origin != f"{parsed.scheme}://{parsed.netloc}"
                or parsed.port == 0
            ):
                raise ValueError("Allowed origins must be exact HTTP or HTTPS origins.")
        return origins
