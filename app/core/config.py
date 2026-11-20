from typing import Literal

from pydantic import Field, SecretStr
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
    postgres_host: str | None = None
    postgres_database: str = "insightpilot"
    postgres_user: str = "insightpilot"
    postgres_password: SecretStr | None = None
    redis_url: SecretStr | None = None
