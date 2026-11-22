from sqlalchemy.engine import URL

from app.core.config import Settings


def database_url(settings: Settings) -> URL:
    if not settings.postgres_host or not settings.postgres_password:
        raise ValueError(
            "Configure INSIGHTPILOT_POSTGRES_HOST and INSIGHTPILOT_POSTGRES_PASSWORD."
        )

    return URL.create(
        "postgresql+psycopg",
        username=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_database,
    )
