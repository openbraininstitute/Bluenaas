from multiprocessing.process import BaseProcess
from multiprocessing.queues import Queue as QueueType
from typing import Any, Callable, Generator
from fastapi.responses import StreamingResponse
from loguru import logger


class StreamingResponseWithCleanup(StreamingResponse):
    def __init__(self, *args, finalizer, **kwargs):
        super().__init__(*args, **kwargs)
        self.finalizer = finalizer

    async def __call__(self, *args, **kwargs):
        try:
            await super(StreamingResponseWithCleanup, self).__call__(*args, **kwargs)
        except Exception as error:
            logger.exception(f"Streaming Exceptions {error}")
            raise
        finally:
            self.finalizer()


async def free_resources_after_streaming(
    fn: Callable[..., Generator[Any, Any, None]],
    queue: QueueType,
    process: BaseProcess,
):
    try:
        for element in fn():
            yield element
    finally:
        logger.debug("Killing process and sub processes")
        queue.close()
        queue.join_thread()
        process.join()
        logger.debug("Cleaned up resources")
