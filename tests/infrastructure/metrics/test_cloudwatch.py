import unittest
import asyncio
from unittest.mock import patch, MagicMock
from datetime import datetime

from app.infrastructure.metrics.cloudwatch import CloudWatchMetricsReporter


class TestCloudWatchMetricsReporter(unittest.TestCase):
    def setUp(self):
        # Mock settings to avoid import issues
        with patch("app.infrastructure.metrics.cloudwatch.settings") as mock_settings:
            mock_settings.METRICS_AWS_REGION = None
            self.reporter = CloudWatchMetricsReporter()

    @patch("app.infrastructure.metrics.cloudwatch.boto3")
    @patch("app.infrastructure.metrics.cloudwatch.settings")
    def test_init_with_region(self, mock_settings, mock_boto3):
        """Test initialization with AWS region"""
        mock_settings.METRICS_AWS_REGION = "us-west-2"
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        reporter = CloudWatchMetricsReporter()

        mock_boto3.client.assert_called_once_with("cloudwatch", region_name="us-west-2")
        self.assertEqual(reporter.cloudwatch, mock_client)
        self.assertEqual(reporter.namespace, "BlueNaaS/RQ")

    @patch("app.infrastructure.metrics.cloudwatch.boto3")
    @patch("app.infrastructure.metrics.cloudwatch.settings")
    def test_init_without_region(self, mock_settings, mock_boto3):
        """Test initialization without AWS region"""
        mock_settings.METRICS_AWS_REGION = None
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        reporter = CloudWatchMetricsReporter()

        mock_boto3.client.assert_called_once_with("cloudwatch")
        self.assertEqual(reporter.cloudwatch, mock_client)

    @patch("app.infrastructure.metrics.cloudwatch.boto3")
    @patch("app.infrastructure.metrics.cloudwatch.settings")
    def test_init_custom_namespace(self, mock_settings, mock_boto3):
        """Test initialization with custom namespace"""
        mock_settings.METRICS_AWS_REGION = None
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        reporter = CloudWatchMetricsReporter(namespace="CustomNamespace")

        self.assertEqual(reporter.namespace, "CustomNamespace")

    @patch("app.infrastructure.metrics.cloudwatch.run_async")
    @patch("app.infrastructure.metrics.cloudwatch.logger")
    def test_report_metric_with_dimensions(self, mock_logger, mock_run_async):
        """Test reporting single metric with dimensions"""
        mock_run_async.return_value = None

        async def run_test():
            timestamp = datetime(2025, 1, 1, 12, 0, 0)
            dimensions = {"queue": "high", "worker": "w1"}
            await self.reporter.report_metric("test_metric", 42.5, timestamp, dimensions)

        asyncio.run(run_test())

        mock_run_async.assert_called_once()
        # Verify the lambda function would call put_metric_data correctly
        lambda_func = mock_run_async.call_args[0][0]

        # Mock the cloudwatch client call
        self.reporter.cloudwatch.put_metric_data = MagicMock()
        lambda_func()

        expected_metric_data = [
            {
                "MetricName": "test_metric",
                "Value": 42.5,
                "Timestamp": datetime(2025, 1, 1, 12, 0, 0),
                "Unit": "Count",
                "Dimensions": [
                    {"Name": "queue", "Value": "high"},
                    {"Name": "worker", "Value": "w1"},
                ],
            }
        ]

        self.reporter.cloudwatch.put_metric_data.assert_called_once_with(
            Namespace="BlueNaaS/RQ", MetricData=expected_metric_data
        )

        mock_logger.debug.assert_called_once_with("Sent metric test_metric=42.5 to CloudWatch")

    @patch("app.infrastructure.metrics.cloudwatch.run_async")
    @patch("app.infrastructure.metrics.cloudwatch.logger")
    def test_report_metric_without_dimensions(self, mock_logger, mock_run_async):
        """Test reporting single metric without dimensions"""
        mock_run_async.return_value = None

        async def run_test():
            timestamp = datetime(2025, 1, 1, 12, 0, 0)
            await self.reporter.report_metric("test_metric", 10.0, timestamp)

        asyncio.run(run_test())

        mock_run_async.assert_called_once()
        lambda_func = mock_run_async.call_args[0][0]

        self.reporter.cloudwatch.put_metric_data = MagicMock()
        lambda_func()

        expected_metric_data = [
            {
                "MetricName": "test_metric",
                "Value": 10.0,
                "Timestamp": datetime(2025, 1, 1, 12, 0, 0),
                "Unit": "Count",
            }
        ]

        self.reporter.cloudwatch.put_metric_data.assert_called_once_with(
            Namespace="BlueNaaS/RQ", MetricData=expected_metric_data
        )

    @patch("app.infrastructure.metrics.cloudwatch.run_async")
    def test_report_batch_empty(self, mock_run_async):
        """Test reporting empty batch"""

        async def run_test():
            await self.reporter.report_batch([])

        asyncio.run(run_test())
        mock_run_async.assert_not_called()

    @patch("app.infrastructure.metrics.cloudwatch.run_async")
    @patch("app.infrastructure.metrics.cloudwatch.logger")
    def test_report_batch_single_metric(self, mock_logger, mock_run_async):
        """Test reporting batch with single metric"""
        mock_run_async.return_value = None

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

        mock_run_async.assert_called_once()
        lambda_func = mock_run_async.call_args[0][0]

        self.reporter.cloudwatch.put_metric_data = MagicMock()
        lambda_func()

        expected_metric_data = [
            {
                "MetricName": "queue_length",
                "Value": 5.0,
                "Timestamp": datetime(2025, 1, 1, 12, 0, 0),
                "Unit": "Count",
                "Dimensions": [{"Name": "queue", "Value": "high"}],
            }
        ]

        self.reporter.cloudwatch.put_metric_data.assert_called_once_with(
            Namespace="BlueNaaS/RQ", MetricData=expected_metric_data
        )

        mock_logger.debug.assert_called_once_with("Sent 1 metrics to CloudWatch")

    @patch("app.infrastructure.metrics.cloudwatch.run_async")
    @patch("app.infrastructure.metrics.cloudwatch.logger")
    def test_report_batch_multiple_metrics_under_limit(self, mock_logger, mock_run_async):
        """Test reporting batch with multiple metrics under the 20 limit"""
        mock_run_async.return_value = None

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

        mock_run_async.assert_called_once()
        lambda_func = mock_run_async.call_args[0][0]

        self.reporter.cloudwatch.put_metric_data = MagicMock()
        lambda_func()

        # Should send all 3 metrics in one batch
        self.reporter.cloudwatch.put_metric_data.assert_called_once()
        call_args = self.reporter.cloudwatch.put_metric_data.call_args
        metric_data = call_args[1]["MetricData"]
        self.assertEqual(len(metric_data), 3)

        mock_logger.debug.assert_called_once_with("Sent 3 metrics to CloudWatch")

    @patch("app.infrastructure.metrics.cloudwatch.run_async")
    @patch("app.infrastructure.metrics.cloudwatch.logger")
    def test_report_batch_over_20_limit(self, mock_logger, mock_run_async):
        """Test reporting batch with more than 20 metrics (batching)"""
        mock_run_async.return_value = None

        async def run_test():
            timestamp = datetime(2025, 1, 1, 12, 0, 0)

            # Create 25 metrics to test batching
            metrics = []
            for i in range(25):
                metrics.append(
                    {
                        "name": f"metric_{i}",
                        "value": float(i),
                        "timestamp": timestamp,
                        "dimensions": {"batch": "test"},
                    }
                )

            await self.reporter.report_batch(metrics)

        asyncio.run(run_test())

        # Should be called twice (20 + 5)
        self.assertEqual(mock_run_async.call_count, 2)

        # Test both lambda functions
        self.reporter.cloudwatch.put_metric_data = MagicMock()

        # First batch (20 metrics)
        lambda_func_1 = mock_run_async.call_args_list[0][0][0]
        lambda_func_1()

        # Second batch (5 metrics)
        lambda_func_2 = mock_run_async.call_args_list[1][0][0]
        lambda_func_2()

        # Verify put_metric_data was called twice
        self.assertEqual(self.reporter.cloudwatch.put_metric_data.call_count, 2)

        # Verify first batch had 20 metrics
        first_call_data = self.reporter.cloudwatch.put_metric_data.call_args_list[0][1][
            "MetricData"
        ]
        self.assertEqual(len(first_call_data), 20)

        # Verify second batch had 5 metrics
        second_call_data = self.reporter.cloudwatch.put_metric_data.call_args_list[1][1][
            "MetricData"
        ]
        self.assertEqual(len(second_call_data), 5)

    @patch("app.infrastructure.metrics.cloudwatch.run_async")
    def test_report_batch_metric_without_dimensions(self, mock_run_async):
        """Test reporting batch metric without dimensions"""
        mock_run_async.return_value = None

        async def run_test():
            timestamp = datetime(2025, 1, 1, 12, 0, 0)
            metrics = [{"name": "simple_metric", "value": 1.0, "timestamp": timestamp}]
            await self.reporter.report_batch(metrics)

        asyncio.run(run_test())

        mock_run_async.assert_called_once()
        lambda_func = mock_run_async.call_args[0][0]

        self.reporter.cloudwatch.put_metric_data = MagicMock()
        lambda_func()

        expected_metric_data = [
            {
                "MetricName": "simple_metric",
                "Value": 1.0,
                "Timestamp": datetime(2025, 1, 1, 12, 0, 0),
                "Unit": "Count",
            }
        ]

        self.reporter.cloudwatch.put_metric_data.assert_called_once_with(
            Namespace="BlueNaaS/RQ", MetricData=expected_metric_data
        )

    @patch("app.infrastructure.metrics.cloudwatch.run_async")
    def test_report_batch_exactly_20_metrics(self, mock_run_async):
        """Test reporting exactly 20 metrics (boundary condition)"""
        mock_run_async.return_value = None

        async def run_test():
            timestamp = datetime(2025, 1, 1, 12, 0, 0)

            metrics = []
            for i in range(20):
                metrics.append({"name": f"metric_{i}", "value": float(i), "timestamp": timestamp})

            await self.reporter.report_batch(metrics)

        asyncio.run(run_test())

        # Should be called exactly once
        mock_run_async.assert_called_once()

        lambda_func = mock_run_async.call_args[0][0]
        self.reporter.cloudwatch.put_metric_data = MagicMock()
        lambda_func()

        # Should send all 20 metrics in one batch
        self.reporter.cloudwatch.put_metric_data.assert_called_once()
        call_args = self.reporter.cloudwatch.put_metric_data.call_args
        metric_data = call_args[1]["MetricData"]
        self.assertEqual(len(metric_data), 20)


if __name__ == "__main__":
    unittest.main()
