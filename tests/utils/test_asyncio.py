import asyncio
import time
import unittest

from app.utils.asyncio import interleave_async_iterators, run_async


class TestAsyncioUtils(unittest.TestCase):
    def test_run_async_basic(self):
        """Test run_async with a simple synchronous function."""

        def sync_fn(x: int, y: int) -> int:
            return x + y

        async def test():
            result = await run_async(sync_fn, 5, 3)
            self.assertEqual(result, 8)

        asyncio.run(test())

    def test_run_async_with_blocking_operation(self):
        """Test run_async with a function that would normally block."""

        def blocking_fn(duration: float) -> str:
            time.sleep(duration)
            return "completed"

        async def test():
            start_time = time.time()
            result = await run_async(blocking_fn, 0.1)
            elapsed = time.time() - start_time

            self.assertEqual(result, "completed")
            self.assertGreaterEqual(elapsed, 0.1)
            self.assertLess(elapsed, 0.2)  # Should not take much longer

        asyncio.run(test())

    def test_interleave_async_iterators_empty_list(self):
        """Test interleaving with empty list of iterators."""

        async def test():
            results = []
            async for item in interleave_async_iterators([]):
                results.append(item)
            self.assertEqual(results, [])

        asyncio.run(test())

    def test_interleave_async_iterators_single_iterator(self):
        """Test interleaving with a single iterator."""

        async def create_iterator():
            for i in range(3):
                yield i

        async def test():
            results = []
            async for item in interleave_async_iterators([create_iterator()]):
                results.append(item)
            self.assertEqual(results, [0, 1, 2])

        asyncio.run(test())

    def test_interleave_async_iterators_multiple_same_speed(self):
        """Test interleaving multiple iterators with same speed."""

        async def create_iterator(start: int, count: int):
            for i in range(start, start + count):
                yield i

        async def test():
            iterators = [
                create_iterator(0, 3),  # yields 0, 1, 2
                create_iterator(10, 3),  # yields 10, 11, 12
            ]

            results = []
            async for item in interleave_async_iterators(iterators):
                results.append(item)

            # Should get all items, though order may vary due to timing
            self.assertEqual(sorted(results), [0, 1, 2, 10, 11, 12])

        asyncio.run(test())

    def test_interleave_async_iterators_different_speeds(self):
        """Test interleaving iterators with different delays."""

        async def slow_iterator():
            for i in range(3):
                await asyncio.sleep(0.1)
                yield f"slow-{i}"

        async def fast_iterator():
            for i in range(5):
                await asyncio.sleep(0.02)
                yield f"fast-{i}"

        async def test():
            results = []
            async for item in interleave_async_iterators([slow_iterator(), fast_iterator()]):
                results.append(item)

            # Fast iterator should contribute most items first
            self.assertEqual(len(results), 8)
            self.assertIn("slow-0", results)
            self.assertIn("fast-4", results)

            # Fast items should appear before all slow items
            fast_items = [i for i, item in enumerate(results) if item.startswith("fast")]
            slow_items = [i for i, item in enumerate(results) if item.startswith("slow")]

            # At least some fast items should appear before slow items
            self.assertTrue(any(f < s for f in fast_items for s in slow_items))

        asyncio.run(test())

    def test_interleave_async_iterators_exhausted_iterator(self):
        """Test behavior when one iterator is exhausted before others."""

        async def short_iterator():
            yield "short-1"
            yield "short-2"

        async def long_iterator():
            for i in range(5):
                await asyncio.sleep(0.01)
                yield f"long-{i}"

        async def test():
            results = []
            async for item in interleave_async_iterators([short_iterator(), long_iterator()]):
                results.append(item)

            # Should get all items from both iterators
            short_items = [item for item in results if item.startswith("short")]
            long_items = [item for item in results if item.startswith("long")]

            self.assertEqual(len(short_items), 2)
            self.assertEqual(len(long_items), 5)
            self.assertEqual(len(results), 7)

        asyncio.run(test())

    def test_interleave_async_iterators_exception_handling(self):
        """Test that exceptions in one iterator don't affect others."""

        async def failing_iterator():
            yield "before-error"
            raise ValueError("Iterator failed")

        async def normal_iterator():
            yield "normal-1"
            yield "normal-2"

        async def test():
            results = []
            try:
                async for item in interleave_async_iterators(
                    [failing_iterator(), normal_iterator()]
                ):
                    results.append(item)
            except ValueError:
                pass  # Expected

            # Should have gotten at least some items before the exception
            self.assertIn("before-error", results)
            # Normal iterator should continue working
            self.assertTrue(any(item.startswith("normal") for item in results))

        asyncio.run(test())

    def test_interleave_preserves_ordering_within_iterator(self):
        """Test that items from each iterator maintain their relative order."""

        async def numbered_iterator(prefix: str, count: int):
            for i in range(count):
                await asyncio.sleep(0.01)  # Small delay to allow interleaving
                yield f"{prefix}-{i}"

        async def test():
            iterators = [
                numbered_iterator("A", 3),
                numbered_iterator("B", 3),
            ]

            results = []
            async for item in interleave_async_iterators(iterators):
                results.append(item)

            # Extract items by prefix and check ordering
            a_items = [item for item in results if item.startswith("A")]
            b_items = [item for item in results if item.startswith("B")]

            self.assertEqual(a_items, ["A-0", "A-1", "A-2"])
            self.assertEqual(b_items, ["B-0", "B-1", "B-2"])

        asyncio.run(test())


if __name__ == "__main__":
    unittest.main()
