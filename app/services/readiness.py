import psycopg
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.redis_probe import open_redis_probe


def dependencies_ready(settings: Settings) -> bool:
    if (
        not settings.postgres_host
        or not settings.postgres_password
        or not settings.redis_url
    ):
        return False

    try:
        with psycopg.connect(
            host=settings.postgres_host,
            dbname=settings.postgres_database,
            user=settings.postgres_user,
            password=settings.postgres_password.get_secret_value(),
            connect_timeout=2,
            options="-c statement_timeout=2000",
            autocommit=True,
        ) as connection:
            connection.execute("SELECT 1")

        with open_redis_probe(settings.redis_url) as redis:
            return redis.ping() is True
    except (psycopg.Error, RedisError, ValueError):
        return False
