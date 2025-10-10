import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.http_stream import x_ndjson_http_stream


class TestXNdjsonHttpStream(unittest.TestCase):
    def test_stream_basic_items(self):
        """Test streaming basic JSON items."""

        async def create_iterator():
            yield {"id": 1, "value": "a"}
            yield {"id": 2, "value": "b"}
            yield {"id": 3, "value": "c"}

        async def test():
            request = MagicMock()
            request.is_disconnected = AsyncMock(return_value=False)

            results = []
            async for item in x_ndjson_http_stream(request, create_iterator(), ping_interval=10.0):
                results.append(item)

            self.assertEqual(len(results), 3)
            self.assertEqual(results[0], '{"id": 1, "value": "a"}\n')
            self.assertEqual(results[1], '{"id": 2, "value": "b"}\n')
            self.assertEqual(results[2], '{"id": 3, "value": "c"}\n')

        asyncio.run(test())

    def test_stream_stops_on_disconnect(self):
        """Test streaming stops when client disconnects."""

        async def create_iterator():
            yield {"id": 1}
            yield {"id": 2}
            yield {"id": 3}

        async def test():
            request = MagicMock()
            disconnect_after = 2
            call_count = [0]

            async def is_disconnected_fn():
                call_count[0] += 1
                return call_count[0] > disconnect_after

            request.is_disconnected = is_disconnected_fn

            results = []
            async for item in x_ndjson_http_stream(request, create_iterator(), ping_interval=10.0):
                results.append(item)

            # Should stop after disconnect
            self.assertLessEqual(len(results), disconnect_after)

        asyncio.run(test())

    def test_stream_sends_ping_on_timeout(self):
        """Test that ping messages are sent when no data arrives within timeout."""

        async def slow_iterator():
            await asyncio.sleep(0.2)
            yield {"id": 1}

        async def test():
            request = MagicMock()
            request.is_disconnected = AsyncMock(return_value=False)

            results = []
            async for item in x_ndjson_http_stream(request, slow_iterator(), ping_interval=0.05):
                results.append(item)
                if len(results) >= 3:  # Get a few pings then stop
                    break

            # Should have received ping messages before the actual data
            ping_count = sum(
                1 for r in results if json.loads(r.strip()).get("message_type") == "ping"
            )
            self.assertGreater(ping_count, 0)

        asyncio.run(test())

    def test_stream_empty_iterator(self):
        """Test streaming with empty iterator."""

        async def empty_iterator():
            return
            yield  # Make it a generator

        async def test():
            request = MagicMock()
            request.is_disconnected = AsyncMock(return_value=False)

            results = []
            async for item in x_ndjson_http_stream(request, empty_iterator(), ping_interval=10.0):
                results.append(item)

            self.assertEqual(results, [])

        asyncio.run(test())

    def test_stream_with_multiple_items(self):
        """Test stream with multiple data items."""

        async def multi_iterator():
            yield {"id": 1, "data": "first"}
            yield {"id": 2, "data": "second"}
            yield {"id": 3, "data": "third"}

        async def test():
            request = MagicMock()
            request.is_disconnected = AsyncMock(return_value=False)

            results = []
            async for item in x_ndjson_http_stream(request, multi_iterator(), ping_interval=10.0):
                results.append(item)

            self.assertEqual(len(results), 3)
            parsed_results = [json.loads(r.strip()) for r in results]

            self.assertEqual(parsed_results[0].get("data"), "first")
            self.assertEqual(parsed_results[1].get("data"), "second")
            self.assertEqual(parsed_results[2].get("data"), "third")

        asyncio.run(test())

    def test_stream_checks_disconnect_after_timeout(self):
        """Test that disconnect is checked after timeout, not just after receiving data."""

        async def slow_iterator():
            await asyncio.sleep(1.0)
            yield {"id": 1}

        async def test():
            request = MagicMock()
            disconnect_after_ms = 100
            start_time = [asyncio.get_event_loop().time()]

            async def is_disconnected_fn():
                elapsed = (asyncio.get_event_loop().time() - start_time[0]) * 1000
                return elapsed > disconnect_after_ms

            request.is_disconnected = is_disconnected_fn

            results = []
            async for item in x_ndjson_http_stream(request, slow_iterator(), ping_interval=0.05):
                results.append(item)

            # Should have stopped due to disconnect, possibly with some pings
            # but should not have waited for the full 1 second
            self.assertGreater(len(results), 0)  # At least some pings
            # Verify we got pings, not the actual data
            last_item = json.loads(results[-1].strip())
            self.assertEqual(last_item.get("message_type"), "ping")

        asyncio.run(test())

    def test_stream_ndjson_format(self):
        """Test that output is properly formatted as NDJSON."""

        async def create_iterator():
            yield {"key": "value1"}
            yield {"key": "value2"}

        async def test():
            request = MagicMock()
            request.is_disconnected = AsyncMock(return_value=False)

            results = []
            async for item in x_ndjson_http_stream(request, create_iterator(), ping_interval=10.0):
                results.append(item)

            # Each line should end with newline
            for result in results:
                self.assertTrue(result.endswith("\n"))

            # Each line should be valid JSON
            for result in results:
                json.loads(result.strip())  # Should not raise

        asyncio.run(test())


if __name__ == "__main__":
    unittest.main()
