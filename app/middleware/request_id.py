from typing import Awaitable, Callable

from fastapi import Request, Response
from loguru import logger
from nanoid import generate as nanoid

from app.constants import CID_LENGTH

from app.context import cid_var


async def add_request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    cid = nanoid(alphabet="0123456789abcdefghijklmnopqrstuvwxyz", size=CID_LENGTH)
    token = cid_var.set(cid)
    request.state.cid = cid
    request.state.request_id = cid  # backward compat

    try:
        with logger.contextualize(cid=cid):
            response = await call_next(request)
        response.headers["x-request-id"] = cid
        return response
    finally:
        cid_var.reset(token)
