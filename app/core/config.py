from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INSIGHTPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Environment = "development"
    postgres_host: str | None = None
    postgres_database: str = "insightpilot"
    postgres_user: str = "insightpilot"
    postgres_password: SecretStr | None = None
    redis_url: SecretStr | None = None
