import unittest
import asyncio
from datetime import datetime
from typing import Dict, Any

from app.infrastructure.metrics.base import MetricsReporter


class MockMetricsReporter(MetricsReporter):
    def __init__(self):
        self.report_metric_calls = []
        self.report_batch_calls = []

    async def report_metric(
        self,
        metric_name: str,
        value: float,
        timestamp: datetime,
        dimensions: Dict[str, str] | None = None,
    ) -> None:
        self.report_metric_calls.append(
            {
                "metric_name": metric_name,
                "value": value,
                "timestamp": timestamp,
                "dimensions": dimensions,
            }
        )

    async def report_batch(self, metrics: list[Dict[str, Any]]) -> None:
        self.report_batch_calls.append(metrics)


class TestMetricsReporter(unittest.TestCase):
    def setUp(self):
        self.reporter = MockMetricsReporter()

    def test_report_metric_interface(self):
        """Test that the reporter implements the required interface"""

        async def run_test():
            timestamp = datetime.now()
            dimensions = {"queue": "high"}

            await self.reporter.report_metric("test_metric", 42.5, timestamp, dimensions)

            self.assertEqual(len(self.reporter.report_metric_calls), 1)
            call = self.reporter.report_metric_calls[0]
            self.assertEqual(call["metric_name"], "test_metric")
            self.assertEqual(call["value"], 42.5)
            self.assertEqual(call["timestamp"], timestamp)
            self.assertEqual(call["dimensions"], dimensions)

        asyncio.run(run_test())

    def test_report_metric_without_dimensions(self):
        """Test reporting metric without dimensions"""

        async def run_test():
            timestamp = datetime.now()

            await self.reporter.report_metric("test_metric", 10.0, timestamp)

            self.assertEqual(len(self.reporter.report_metric_calls), 1)
            call = self.reporter.report_metric_calls[0]
            self.assertEqual(call["metric_name"], "test_metric")
            self.assertEqual(call["value"], 10.0)
            self.assertEqual(call["timestamp"], timestamp)
            self.assertIsNone(call["dimensions"])

        asyncio.run(run_test())

    def test_report_batch_interface(self):
        """Test that the reporter implements batch reporting"""

        async def run_test():
            metrics = [
                {
                    "name": "metric1",
                    "value": 1.0,
                    "timestamp": datetime.now(),
                    "dimensions": {"queue": "high"},
                },
                {
                    "name": "metric2",
                    "value": 2.0,
                    "timestamp": datetime.now(),
                    "dimensions": {"queue": "low"},
                },
            ]

            await self.reporter.report_batch(metrics)

            self.assertEqual(len(self.reporter.report_batch_calls), 1)
            self.assertEqual(self.reporter.report_batch_calls[0], metrics)

        asyncio.run(run_test())

    def test_report_empty_batch(self):
        """Test reporting empty batch"""

        async def run_test():
            await self.reporter.report_batch([])

            self.assertEqual(len(self.reporter.report_batch_calls), 1)
            self.assertEqual(self.reporter.report_batch_calls[0], [])

        asyncio.run(run_test())

    def test_abstract_methods_exist(self):
        """Test that abstract methods are defined"""
        self.assertTrue(hasattr(MetricsReporter, "report_metric"))
        self.assertTrue(hasattr(MetricsReporter, "report_batch"))

        # Test that direct instantiation raises TypeError
        with self.assertRaises(TypeError):
            MetricsReporter()


if __name__ == "__main__":
    unittest.main()
