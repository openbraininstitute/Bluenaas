from app.config.settings import settings
from app.constants import STOP_MESSAGE
from redis import ConnectionPool, Redis

MAX_REDIS_CONNECTIONS = 20

connection_pool = ConnectionPool.from_url(
    settings.REDIS_URL, max_connections=MAX_REDIS_CONNECTIONS
)
redis_client = Redis(connection_pool=connection_pool, decode_responses=True)


class Stream:
    stream_key: str

    def __init__(self, stream_key: str):
        self.stream_key = stream_key

    def _send(self, data: str):
        redis_client.xadd(self.stream_key, {"data": data})
        redis_client.expire(self.stream_key, settings.MAX_JOB_DURATION, nx=True)

    def _receive(self):
        pass

    def close(self):
        redis_client.xadd(self.stream_key, {"data": STOP_MESSAGE})
        redis_client.expire(self.stream_key, settings.MAX_JOB_DURATION, nx=True)

    def send(self, data: str):
        self._send(data)

    def send_one(self, data: str):
        self._send(data)
        self.close()


def stream(stream_key: str, data: str) -> None:
    redis_client.xadd(stream_key, {"data": data})

    redis_client.expire(stream_key, settings.MAX_JOB_DURATION, nx=True)


def close_stream(stream_key: str) -> None:
    redis_client.xadd(stream_key, {"data": STOP_MESSAGE})


def stream_one(stream_key: str, data: str) -> None:
    stream(stream_key, data)
    close_stream(stream_key)
