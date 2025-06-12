from redis import Redis, ConnectionPool
from app.config.settings import settings
from app.constants import MAX_JOB_DURATION, STOP_MESSAGE

MAX_REDIS_CONNECTIONS = 20

connection_pool = ConnectionPool.from_url(
    settings.REDIS_URL, max_connections=MAX_REDIS_CONNECTIONS
)
redis_client = Redis(connection_pool=connection_pool)


def stream(stream_key: str, data: str) -> None:
    redis_client.xadd(stream_key, {"data": data})

    redis_client.expire(stream_key, MAX_JOB_DURATION, nx=True)


def close_stream(stream_key: str) -> None:
    redis_client.xadd(stream_key, {"data": STOP_MESSAGE})


def stream_one(stream_key: str, data: str) -> None:
    stream(stream_key, data)
    close_stream(stream_key)
