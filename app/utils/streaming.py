import asyncio
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event

from loguru import logger


async def cleanup(stop_event: Event, process: BaseProcess):
    logger.debug(f"Cleaning up process {process.pid}")
    stop_event.set()  # Send stop event to children

    # Wait for the process (and its subprocesses) to terminate. This takes around 1 second.
    counter = 0
    while process.is_alive() and counter < 50:
        await asyncio.sleep(0.1)
        counter = counter + 1

    # If the process is not yet dead, force terminate.
    if process.is_alive():
        logger.debug("Process did not die by itself. Terminating.")
        process.terminate()

    # Cleanup resources by joining.
    process.join()  # Joining is blocking call. It helps cleanup child processes so that they don't become zombies
    logger.debug(f"Done Cleaning up process {process.pid}")


def cleanup_without_wait(stop_event: Event, process: BaseProcess):
    logger.debug(f"Cleaning up process {process.pid}")
    stop_event.set()  # Send stop event to children

    process.join()  # Joining is blocking call. It helps cleanup child processes so that they don't become zombies
    logger.debug(f"Done Cleaning up process {process.pid}")


def compose_key(op_key: str) -> str:
    return f"stream:{op_key}"
