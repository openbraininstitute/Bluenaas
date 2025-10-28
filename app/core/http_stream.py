import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import Request

from app.config.settings import settings
from app.domains.stream_message import KeepAliveMessage


def _create_x_ndjson_entry(data: dict) -> str:
    return f"{json.dumps(data)}\n"


async def x_ndjson_http_stream(
    request: Request,
    messages: AsyncIterator[dict[str, Any]],
    keep_alive_interval: float = settings.HTTP_STREAM_KEEP_ALIVE_INTERVAL,
):
    """
    Stream JSON data as newline-delimited JSON (NDJSON) over HTTP.

    Yields each JSON item as a separate line, handling client disconnection gracefully.
    Sends periodic keep_alive messages to prevent infrastructure timeouts (e.g., AWS ALB).

    Args:
        request (Request): The incoming HTTP request.
        messages (AsyncIterator[dict[str, Any]]): An asynchronous iterator of items to stream.
        keep_alive_interval (float): Interval in seconds between keep_alive messages when no data is sent.
            Defaults to 30.0 seconds to prevent ALB timeouts.

    Yields:
        str: Each JSON item followed by a newline character.

    Notes:
        - Stops streaming if the client disconnects.
        - Sends keep_alive messages if no data is received within keep_alive_interval seconds.
        - Suitable for streaming large or continuous datasets.
    """

    async def get_next_message() -> dict[str, Any]:
        return await anext(messages)

    while True:
        try:
            next_message_task = asyncio.create_task(get_next_message())

            try:
                message = await asyncio.wait_for(next_message_task, timeout=keep_alive_interval)
                output = _create_x_ndjson_entry(message)
            except asyncio.TimeoutError:
                output = _create_x_ndjson_entry(KeepAliveMessage().model_dump())

            if await request.is_disconnected():
                next_message_task.cancel()
                return

            yield output
        except StopAsyncIteration:
            break
