import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response


async def add_request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["x-request-id"] = request_id

    return response
