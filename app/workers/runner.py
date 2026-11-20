from socket import gethostname

from redis import Redis
from redis.exceptions import RedisError
from rq import Worker

from app.core.config import Settings
from app.core.redis_probe import open_redis_probe


def is_worker_registered() -> bool:
    redis_url = Settings().redis_url
    if not redis_url:
        return False

    worker_name = gethostname()
    try:
        with open_redis_probe(redis_url) as connection:
            return any(
                worker.name == worker_name
                for worker in Worker.all(connection=connection)
            )
    except (RedisError, ValueError):
        return False


def main() -> None:
    redis_url = Settings().redis_url
    if not redis_url:
        raise SystemExit("Set INSIGHTPILOT_REDIS_URL before starting the worker.")

    with Redis.from_url(
        redis_url.get_secret_value(), socket_connect_timeout=2
    ) as connection:
        Worker(["default"], connection=connection, name=gethostname()).work()


if __name__ == "__main__":
    main()
