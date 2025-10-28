import msgpack

from typing import Any, cast
from redis import ConnectionPool, Redis

from app.config.settings import settings
from app.constants import STOP_MESSAGE

MAX_REDIS_CONNECTIONS = 20

connection_pool = ConnectionPool.from_url(settings.REDIS_URL, max_connections=MAX_REDIS_CONNECTIONS)
redis_client = Redis(connection_pool=connection_pool)


class Stream:
    stream_key: str
    ttl: int

    def __init__(self, stream_key: str, *, ttl: int | None = None):
        self.stream_key = stream_key
        self.ttl = ttl or settings.DEFAULT_REDIS_STREAM_TTL

    def set_ttl(self):
        redis_client.expire(self.stream_key, self.ttl)

    def _send(self, data: bytes):
        redis_client.xadd(self.stream_key, {"data": data})
        self.set_ttl()

    def _receive(self):
        pass

    def close(self):
        redis_client.xadd(self.stream_key, {"data": STOP_MESSAGE})
        self.set_ttl()

    def send(self, data: dict[str, Any]):
        binary_data = cast(bytes, msgpack.packb(data))
        self._send(binary_data)
