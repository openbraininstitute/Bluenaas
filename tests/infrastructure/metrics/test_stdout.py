import unittest
import asyncio
import json
from datetime import datetime
from unittest.mock import patch

from app.infrastructure.metrics.stdout import StdoutMetricsReporter


class TestStdoutMetricsReporter(unittest.TestCase):
    def setUp(self):
        self.reporter = StdoutMetricsReporter()

    @patch("app.infrastructure.metrics.stdout.logger")
    def test_report_metric_with_dimensions(self, mock_logger):
        """Test reporting a single metric with dimensions"""

        async def run_test():
            timestamp = datetime(2025, 1, 1, 12, 0, 0)
            dimensions = {"queue": "high", "worker": "w1"}
            await self.reporter.report_metric("test_metric", 42.5, timestamp, dimensions)

        asyncio.run(run_test())

        mock_logger.info.assert_called_once()
        logged_message = mock_logger.info.call_args[0][0]
        self.assertTrue(logged_message.startswith("METRIC: "))

        json_part = logged_message[8:]
        metric_data = json.loads(json_part)

        expected = {
            "metric_name": "test_metric",
            "value": 42.5,
            "timestamp": "2025-01-01T12:00:00",
            "dimensions": {"queue": "high", "worker": "w1"},
        }
        self.assertEqual(metric_data, expected)

    @patch("app.infrastructure.metrics.stdout.logger")
    def test_report_metric_without_dimensions(self, mock_logger):
        """Test reporting a single metric without dimensions"""

        async def run_test():
            timestamp = datetime(2025, 1, 1, 12, 0, 0)
            await self.reporter.report_metric("test_metric", 10.0, timestamp)

        asyncio.run(run_test())

        mock_logger.info.assert_called_once()
        logged_message = mock_logger.info.call_args[0][0]
        json_part = logged_message[8:]
        metric_data = json.loads(json_part)

        expected = {
            "metric_name": "test_metric",
            "value": 10.0,
            "timestamp": "2025-01-01T12:00:00",
            "dimensions": {},
        }
        self.assertEqual(metric_data, expected)

    @patch("app.infrastructure.metrics.stdout.logger")
    def test_report_metric_with_none_dimensions(self, mock_logger):
        """Test reporting a single metric with None dimensions"""

        async def run_test():
            timestamp = datetime(2025, 1, 1, 12, 0, 0)
            await self.reporter.report_metric("test_metric", 5.0, timestamp, None)

        asyncio.run(run_test())

        mock_logger.info.assert_called_once()
        logged_message = mock_logger.info.call_args[0][0]
        json_part = logged_message[8:]
        metric_data = json.loads(json_part)

        expected = {
            "metric_name": "test_metric",
            "value": 5.0,
            "timestamp": "2025-01-01T12:00:00",
            "dimensions": {},
        }
        self.assertEqual(metric_data, expected)

    @patch("app.infrastructure.metrics.stdout.logger")
    def test_report_batch_empty(self, mock_logger):
        """Test reporting empty batch"""

        async def run_test():
            await self.reporter.report_batch([])

        asyncio.run(run_test())
        mock_logger.info.assert_not_called()

    @patch("app.infrastructure.metrics.stdout.logger")
    def test_report_batch_single_metric(self, mock_logger):
        """Test reporting batch with single metric"""

        async def run_test():
            timestamp = datetime(2025, 1, 1, 12, 0, 0)
            metrics = [
                {
                    "name": "queue_length",
                    "value": 5.0,
                    "timestamp": timestamp,
                    "dimensions": {"queue": "high"},
                }
            ]
            await self.reporter.report_batch(metrics)

        asyncio.run(run_test())

        mock_logger.info.assert_called_once()
        logged_message = mock_logger.info.call_args[0][0]
        json_part = logged_message[8:]
        metric_data = json.loads(json_part)

        expected = {
            "metric_name": "queue_length",
            "value": 5.0,
            "timestamp": "2025-01-01T12:00:00",
            "dimensions": {"queue": "high"},
        }
        self.assertEqual(metric_data, expected)

    @patch("app.infrastructure.metrics.stdout.logger")
    def test_report_batch_multiple_metrics(self, mock_logger):
        """Test reporting batch with multiple metrics"""

        async def run_test():
            timestamp = datetime(2025, 1, 1, 12, 0, 0)
            metrics = [
                {
                    "name": "queue_length",
                    "value": 5.0,
                    "timestamp": timestamp,
                    "dimensions": {"queue": "high"},
                },
                {
                    "name": "active_tasks",
                    "value": 2.0,
                    "timestamp": timestamp,
                    "dimensions": {"queue": "high"},
                },
                {
                    "name": "queue_length",
                    "value": 1.0,
                    "timestamp": timestamp,
                    "dimensions": {"queue": "low"},
                },
            ]
            await self.reporter.report_batch(metrics)

        asyncio.run(run_test())

        self.assertEqual(mock_logger.info.call_count, 3)

        # Verify each call
        calls = mock_logger.info.call_args_list
        for i, metric in enumerate(
            [
                {"name": "queue_length", "value": 5.0, "dimensions": {"queue": "high"}},
                {"name": "active_tasks", "value": 2.0, "dimensions": {"queue": "high"}},
                {"name": "queue_length", "value": 1.0, "dimensions": {"queue": "low"}},
            ]
        ):
            logged_message = calls[i][0][0]
            json_part = logged_message[8:]
            metric_data = json.loads(json_part)

            expected = {
                "metric_name": metric["name"],
                "value": metric["value"],
                "timestamp": "2025-01-01T12:00:00",
                "dimensions": metric["dimensions"],
            }
            self.assertEqual(metric_data, expected)

    @patch("app.infrastructure.metrics.stdout.logger")
    def test_report_batch_metric_without_dimensions(self, mock_logger):
        """Test reporting batch metric without dimensions key"""

        async def run_test():
            timestamp = datetime(2025, 1, 1, 12, 0, 0)
            metrics = [{"name": "simple_metric", "value": 1.0, "timestamp": timestamp}]
            await self.reporter.report_batch(metrics)

        asyncio.run(run_test())

        mock_logger.info.assert_called_once()
        logged_message = mock_logger.info.call_args[0][0]
        json_part = logged_message[8:]
        metric_data = json.loads(json_part)

        expected = {
            "metric_name": "simple_metric",
            "value": 1.0,
            "timestamp": "2025-01-01T12:00:00",
            "dimensions": {},
        }
        self.assertEqual(metric_data, expected)

    def test_json_serialization_edge_cases(self):
        """Test that timestamp serialization works correctly"""
        timestamp = datetime(2025, 1, 1, 12, 0, 0, 123456)
        expected_iso = timestamp.isoformat()

        test_data = {"timestamp": expected_iso}
        json_str = json.dumps(test_data)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["timestamp"], expected_iso)


if __name__ == "__main__":
    unittest.main()
