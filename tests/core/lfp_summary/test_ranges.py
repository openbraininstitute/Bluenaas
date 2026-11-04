import io
import logging
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import httpx

from app.core.lfp_summary import ranges
from app.core.lfp_summary.ranges import HttpRanges, RangeFile, RangeReadError, url_expires_at

CONTENT = bytes(range(256)) * 40


class TestRangeFile(unittest.TestCase):
    def setUp(self):
        self.reads: list[tuple[int, int]] = []
        patcher = patch.object(ranges, "FILE_BLOCK_BYTES", 1000)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, offset: int, length: int) -> bytes:
        self.reads.append((offset, length))
        return CONTENT[offset : offset + length]

    def test_reads_across_blocks(self):
        f = RangeFile(self.read, len(CONTENT))

        f.seek(990)

        self.assertEqual(f.read(30), CONTENT[990:1020])
        self.assertEqual(f.tell(), 1020)
        self.assertEqual(self.reads, [(0, 1000), (1000, 1000)])

    def test_blocks_are_kept(self):
        f = RangeFile(self.read, len(CONTENT))

        f.read(10)
        f.seek(500)
        f.read(10)

        self.assertEqual(self.reads, [(0, 1000)])

    def test_the_end_of_the_file(self):
        f = RangeFile(self.read, len(CONTENT))

        f.seek(-5, io.SEEK_END)

        self.assertEqual(f.read(100), CONTENT[-5:])
        self.assertEqual(f.read(100), b"")
        self.assertEqual(self.reads, [(10000, 240)])


class TestHttpRanges(unittest.TestCase):
    def ranges_answered_by(self, *responses: httpx.Response) -> HttpRanges:
        answers = iter(responses)
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return next(answers)

        http = HttpRanges("https://bucket/report.h5", connections=2)
        http.client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(http.client.close)
        return http

    def test_a_range_read(self):
        http = self.ranges_answered_by(httpx.Response(206, content=b"abcd"))

        self.assertEqual(http.read(10, 4), b"abcd")
        self.assertEqual(self.requests[0].headers["range"], "bytes=10-13")

    def test_a_whole_file_is_refused(self):
        http = self.ranges_answered_by(httpx.Response(200, content=b"abcd"))

        with self.assertRaises(RangeReadError):
            http.read(0, 4)

    def test_a_whole_file_is_not_read_into_memory(self):
        class Unread(httpx.SyncByteStream):
            def __iter__(self):
                raise AssertionError("The body was read")

        http = self.ranges_answered_by(httpx.Response(200, stream=Unread()))

        with self.assertRaises(RangeReadError):
            http.read(0, 4)

    def test_a_short_read_is_refused(self):
        http = self.ranges_answered_by(httpx.Response(206, content=b"ab"))

        with self.assertRaises(RangeReadError):
            http.read(0, 4)

    @patch.object(ranges.time, "sleep")
    def test_server_errors_are_tried_again(self, _sleep):
        http = self.ranges_answered_by(httpx.Response(503), httpx.Response(206, content=b"abcd"))

        self.assertEqual(http.read(0, 4), b"abcd")
        self.assertEqual(len(self.requests), 2)

    @patch.object(ranges.time, "sleep")
    def test_client_errors_are_not(self, _sleep):
        http = self.ranges_answered_by(httpx.Response(403))

        with self.assertRaises(RangeReadError) as caught:
            http.read(0, 4)
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn("bucket", str(caught.exception))

    def test_httpx_logs_no_request_and_so_no_url(self):
        self.assertFalse(logging.getLogger("httpx").isEnabledFor(logging.INFO))


class TestUrlExpiresAt(unittest.TestCase):
    def test_signature_version_4(self):
        url = "https://b.s3/r.h5?X-Amz-Date=20261030T120000Z&X-Amz-Expires=21600&X-Amz-Signature=s"

        self.assertEqual(url_expires_at(url), datetime(2026, 10, 30, 18, tzinfo=UTC).timestamp())

    def test_signature_version_2(self):
        self.assertEqual(url_expires_at("https://b.s3/r.h5?Expires=1790000000&Signature=s"), 1.79e9)

    def test_other_urls(self):
        for url in [
            "https://bucket/report.h5",
            "https://b.s3/r.h5?X-Amz-Date=yesterday&X-Amz-Expires=1",
        ]:
            with self.subTest(url=url):
                self.assertIsNone(url_expires_at(url))
