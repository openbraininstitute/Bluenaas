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

    # If the process is not yet dead, force terminate.
    if process.is_alive():
        logger.debug("Process did not die by itself. Terminating.")
        process.terminate()
    
    # Cleanup resources by joining.
    process.join() # Joining is blocking call. It helps cleanup child processes so that they don't become zombies
    logger.debug(f"Done Cleaning up process {process.pid}")

