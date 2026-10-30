"""Reading a file by byte ranges: over HTTP, and as a file object h5py opens."""

import io
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

import httpx

# httpx logs every request's URL at INFO, and a presigned URL's signature with it
logging.getLogger("httpx").setLevel(logging.WARNING)

# Reads `length` bytes at `offset`
ReadRange = Callable[[int, int], bytes]

# h5py reads a file's metadata in many small pieces: they are served from blocks of this size
FILE_BLOCK_BYTES = 1 << 20
FILE_CACHED_BLOCKS = 64

ATTEMPTS = 3


class RangeReadError(Exception):
    pass


def url_expires_at(url: str) -> float | None:
    """When a presigned S3 URL expires, in seconds since the epoch. None for another URL."""
    query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    try:
        if "X-Amz-Date" in query and "X-Amz-Expires" in query:
            signed = datetime.strptime(query["X-Amz-Date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            return signed.timestamp() + int(query["X-Amz-Expires"])
        if "Expires" in query:
            return float(query["Expires"])
    except ValueError:
        pass
    return None


class HttpRanges:
    """Range reads of one URL, from any number of threads at once."""

    def __init__(self, url: str, *, connections: int):
        self.url = url
        self.client = httpx.Client(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=connections),
        )

    def __enter__(self) -> "HttpRanges":
        return self

    def __exit__(self, *_) -> None:
        self.client.close()

    def read(self, offset: int, length: int) -> bytes:
        headers = {"Range": f"bytes={offset}-{offset + length - 1}"}
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = self.client.get(self.url, headers=headers)
                if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR and attempt < ATTEMPTS:
                    time.sleep(attempt)
                    continue
            except httpx.TransportError:
                if attempt == ATTEMPTS:
                    raise
                time.sleep(attempt)
                continue
            # Not raised by httpx, whose message holds the URL and so its signature
            if response.status_code != HTTPStatus.PARTIAL_CONTENT:
                raise RangeReadError(f"A range read was answered with {response.status_code}")
            if len(response.content) != length:
                raise RangeReadError(
                    f"{len(response.content)} bytes read at {offset}, {length} asked for"
                )
            return response.content
        raise AssertionError("unreachable")


class RangeFile(io.RawIOBase):
    """A read-only file of `size` bytes read by `read`, in cached blocks."""

    def __init__(self, read: ReadRange, size: int):
        super().__init__()
        self._read = read
        self._size = size
        self._position = 0
        self._blocks: OrderedDict[int, bytes] = OrderedDict()
        self._lock = threading.Lock()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._position, io.SEEK_END: self._size}[whence]
        self._position = max(0, base + offset)
        return self._position

    def _block(self, index: int) -> bytes:
        if (block := self._blocks.get(index)) is not None:
            self._blocks.move_to_end(index)
            return block
        start = index * FILE_BLOCK_BYTES
        block = self._read(start, min(FILE_BLOCK_BYTES, self._size - start))
        self._blocks[index] = block
        if len(self._blocks) > FILE_CACHED_BLOCKS:
            self._blocks.popitem(last=False)
        return block

    def readinto(self, buffer) -> int:
        with self._lock:
            view = memoryview(buffer).cast("B")
            end = min(self._size, self._position + len(view))
            done = 0
            while self._position < end:
                index, start = divmod(self._position, FILE_BLOCK_BYTES)
                block = self._block(index)
                n = min(len(block) - start, end - self._position)
                view[done : done + n] = block[start : start + n]
                done += n
                self._position += n
            return done
