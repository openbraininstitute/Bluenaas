import asyncio
from typing import AsyncIterator, Callable, List, TypeVar

T = TypeVar("T")


async def run_async(fn: Callable[..., T], *args) -> T:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


async def interleave_async_iterators(iterators: List[AsyncIterator[T]]) -> AsyncIterator[T]:
    """
    Interleave results from multiple async iterators, yielding items as soon as they're available.

    Args:
        iterators: List of async iterators to interleave

    Yields:
        Items from any of the input iterators as they become available
    """
    if not iterators:
        return

    # Create tasks for getting the next item from each iterator
    tasks = {}
    for i, iterator in enumerate(iterators):
        task = asyncio.create_task(_get_next_item(iterator))
        tasks[task] = i

    # Process items as they become available
    while tasks:
        # Wait for the first task to complete
        done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            iterator_index = tasks.pop(task)
            try:
                item = await task
                yield item
                # Schedule the next item from this iterator
                new_task = asyncio.create_task(_get_next_item(iterators[iterator_index]))
                tasks[new_task] = iterator_index
            except StopAsyncIteration:
                # This iterator is exhausted, don't schedule a new task
                pass


async def _get_next_item(iterator: AsyncIterator[T]) -> T:
    """Helper function to get the next item from an async iterator."""
    return await iterator.__anext__()
