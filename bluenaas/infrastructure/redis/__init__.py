from redis import Redis, ConnectionPool
from bluenaas.config.settings import settings
from bluenaas.constants import MAX_TASK_DURATION, STOP_MESSAGE

MAX_REDIS_CONNECTIONS = 20

connection_pool = ConnectionPool.from_url(
    settings.REDIS_URL, max_connections=MAX_REDIS_CONNECTIONS
)
redis_client = Redis(connection_pool=connection_pool, decode_responses=True)


def stream(stream_key: str, data: str) -> None:
    redis_client.xadd(stream_key, {"data": data})

    redis_client.expire(stream_key, MAX_TASK_DURATION, nx=True)


def stream_stop_message(stream_key: str) -> None:
    redis_client.xadd(stream_key, {"data": STOP_MESSAGE})


def stream_one(stream_key: str, data: str) -> None:
    stream(stream_key, data)
    stream_stop_message(stream_key)
