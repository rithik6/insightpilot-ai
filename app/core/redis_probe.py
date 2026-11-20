from pydantic import SecretStr
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry


def open_redis_probe(url: SecretStr) -> Redis:
    return Redis.from_url(
        url.get_secret_value(),
        socket_connect_timeout=2,
        socket_timeout=2,
        retry=Retry(NoBackoff(), 0),
    )
