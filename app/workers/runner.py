import logging
from socket import gethostname

from redis import Redis
from redis.exceptions import RedisError
from rq import Worker

from app.core.config import Settings
from app.core.logging import LogEvent, load_runtime_settings
from app.core.redis_probe import open_redis_probe

logger = logging.getLogger("app.workers")


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
    settings = load_runtime_settings()
    redis_url = settings.redis_url
    if not redis_url:
        logger.error(LogEvent.CONFIGURATION_INVALID)
        raise SystemExit(1)

    logger.info(LogEvent.WORKER_STARTING)
    try:
        with Redis.from_url(
            redis_url.get_secret_value(), socket_connect_timeout=2
        ) as connection:
            worker = Worker(
                ["default"],
                connection=connection,
                name=gethostname(),
                log_job_description=False,
            )
            worker.work(logging_level=settings.log_level)
    except Exception:  # noqa: BLE001
        logger.error(LogEvent.WORKER_FAILED)
        raise SystemExit(1) from None

    logger.info(LogEvent.WORKER_STOPPED)


if __name__ == "__main__":
    main()
