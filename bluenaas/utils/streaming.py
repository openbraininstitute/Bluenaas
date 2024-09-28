import asyncio
from multiprocessing.process import BaseProcess
from multiprocessing.queues import Queue as QueueType
from multiprocessing.synchronize import Event
from typing import Any, Callable, Generator
from fastapi.responses import StreamingResponse
from loguru import logger

class StreamingResponseWithCleanup(StreamingResponse):
    """ Extends `StreamingResponse` from fastapi and calls the "finalizer" when the request either completes or client disconnects it abruptly.
    This is used to (for example) cleanup the processes and subprocesses that are started when a request to run simulation is received.
    """
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
            await self.finalizer()

async def cleanup(stop_event: Event, process: BaseProcess):
    logger.debug(f"Cleaning up process {process.pid}")
    stop_event.set() # Send stop event to children

    # Wait for the process (and its subprocesses) to terminate. This takes around 1 second.
    counter = 0
    while process.is_alive() and counter < 50:
        await asyncio.sleep(0.1)
        counter=counter + 1

    if process.is_alive():
        logger.debug("Process did not die by itself. Terminating.")
        process.terminate()
    
    # Not sure why simply calling `process.join()` without the sleep above does not terminate the process (and subprocesses) in cases when multiple requests arrive simultaneuously, causing a race condition. 
    process.join() # Joining is blocking call. It helps cleanup child processes so that they don't become zombies


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
