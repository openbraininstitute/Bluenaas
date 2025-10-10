import json
from typing import AsyncIterator

from fastapi import Request


async def x_ndjson_http_stream(request: Request, json_data: AsyncIterator[str]):
    """
    Stream JSON data as newline-delimited JSON (NDJSON) over HTTP.

    Yields each JSON item as a separate line, handling client disconnection gracefully.

    Args:
        request (Request): The incoming HTTP request.
        json_data (AsyncIterator[str]): An asynchronous iterator of JSON items to stream.

    Yields:
        str: Each JSON item followed by a newline character.

    Notes:
        - Stops streaming if the client disconnects.
        - Suitable for streaming large or continuous JSON datasets.
    """
    async for item in json_data:
        if await request.is_disconnected():
            return

        yield f"{json.dumps(item)}\n"
