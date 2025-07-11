import asyncio
from typing import Callable, TypeVar

T = TypeVar("T")


async def run_async(fn: Callable[..., T], *args) -> T:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)
