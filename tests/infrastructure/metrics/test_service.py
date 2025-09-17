import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from app.infrastructure.metrics.service import MetricsService


class TestMetricsService(unittest.TestCase):
    def setUp(self):
        # Create a fresh instance for each test
        with patch("app.infrastructure.metrics.service.settings"):
            self.service = MetricsService()

    @patch("app.infrastructure.metrics.service.settings")
    def test_create_reporter_aws(self, mock_settings):
        """Test creating AWS CloudWatch reporter"""
        mock_settings.METRICS_CLOUD_PROVIDER = "aws"

        with patch(
            "app.infrastructure.metrics.service.CloudWatchMetricsReporter"
        ) as mock_cloudwatch:
            mock_reporter = MagicMock()
            mock_cloudwatch.return_value = mock_reporter

            service = MetricsService()

            mock_cloudwatch.assert_called_once()
            self.assertEqual(service.reporter, mock_reporter)

    @patch("app.infrastructure.metrics.service.settings")
    def test_create_reporter_default(self, mock_settings):
        """Test creating default stdout reporter"""
        mock_settings.METRICS_CLOUD_PROVIDER = "other"

        with patch("app.infrastructure.metrics.service.StdoutMetricsReporter") as mock_stdout:
            mock_reporter = MagicMock()
            mock_stdout.return_value = mock_reporter

            service = MetricsService()

            mock_stdout.assert_called_once()
            self.assertEqual(service.reporter, mock_reporter)

    @patch("app.infrastructure.metrics.service.settings")
    def test_create_reporter_none(self, mock_settings):
        """Test creating reporter when cloud provider is None"""
        mock_settings.METRICS_CLOUD_PROVIDER = None

        with patch("app.infrastructure.metrics.service.StdoutMetricsReporter") as mock_stdout:
            mock_reporter = MagicMock()
            mock_stdout.return_value = mock_reporter

            service = MetricsService()

            mock_stdout.assert_called_once()
            self.assertEqual(service.reporter, mock_reporter)

    @patch("app.infrastructure.metrics.service.settings")
    @patch("app.infrastructure.metrics.service.logger")
    def test_start_service(self, mock_logger, mock_settings):
        """Test starting the metrics service"""
        mock_settings.METRICS_INTERVAL = 30

        async def run_test():
            with patch.object(self.service, "_reporting_loop", new_callable=AsyncMock) as mock_loop:
                await self.service.start()

                self.assertIsNotNone(self.service._task)
                self.assertFalse(self.service._task.done())
                mock_logger.info.assert_called_once_with(
                    "Starting metrics service with 30s interval"
                )
                # Verify the reporting loop was mocked
                self.assertTrue(mock_loop.called)

                # Clean up the task
                self.service._task.cancel()
                try:
                    await self.service._task
                except asyncio.CancelledError:
                    pass

        asyncio.run(run_test())

    @patch("app.infrastructure.metrics.service.settings")
    @patch("app.infrastructure.metrics.service.logger")
    def test_start_service_already_running(self, mock_logger, mock_settings):
        """Test starting service when already running"""

        async def run_test():
            mock_settings.METRICS_INTERVAL = 30

            # Create a mock task that's not done
            mock_task = MagicMock()
            mock_task.done.return_value = False
            self.service._task = mock_task

            await self.service.start()

            mock_logger.warning.assert_called_once_with("Metrics service already running")
            self.assertEqual(self.service._task, mock_task)  # Task unchanged

        asyncio.run(run_test())

    @patch("app.infrastructure.metrics.service.logger")
    def test_stop_service(self, mock_logger):
        """Test stopping the metrics service"""

        async def run_test():
            # Create a mock task that completes quickly
            async def mock_task_coroutine():
                return "done"

            mock_task = asyncio.create_task(mock_task_coroutine())
            self.service._task = mock_task

            await self.service.stop()

            self.assertTrue(self.service._shutdown_event.is_set())
            mock_logger.info.assert_called_once_with("Stopping metrics service")

            # Verify the task was awaited with timeout
            # The asyncio.wait_for would have been called, but since we mocked the task
            # we can't easily test that. We can at least verify shutdown_event was set.

        asyncio.run(run_test())

    @patch("app.infrastructure.metrics.service.logger")
    def test_stop_service_timeout(self, mock_logger):
        """Test stopping service with timeout"""

        async def run_test():
            # Create a mock task that doesn't complete quickly
            async def slow_task():
                await asyncio.sleep(10)  # Longer than 5s timeout

            self.service._task = asyncio.create_task(slow_task())

            await self.service.stop()

            # Task should be cancelled due to timeout
            self.assertTrue(self.service._task.cancelled())
            mock_logger.warning.assert_called_once_with(
                "Metrics task didn't stop gracefully, cancelling"
            )

        asyncio.run(run_test())

    @patch("app.infrastructure.metrics.service.logger")
    def test_stop_service_no_task(self, mock_logger):
        """Test stopping service when no task exists"""

        async def run_test():
            self.service._task = None

            await self.service.stop()

            # Should not log anything or raise errors
            mock_logger.info.assert_not_called()
            mock_logger.warning.assert_not_called()

        asyncio.run(run_test())

    @patch("app.infrastructure.metrics.service.settings")
    @patch("app.infrastructure.metrics.service.logger")
    def test_reporting_loop_normal_operation(self, mock_logger, mock_settings):
        """Test normal operation of reporting loop"""

        async def run_test():
            mock_settings.METRICS_INTERVAL = 0.1  # Short interval for testing

            # Mock the collect and report method
            collect_calls = []

            async def mock_collect():
                collect_calls.append(datetime.now())
                if len(collect_calls) >= 2:  # Stop after 2 calls
                    self.service._shutdown_event.set()

            with patch.object(
                self.service, "_collect_and_report_metrics", side_effect=mock_collect
            ):
                await self.service._reporting_loop()

            # Should have called collect at least twice
            self.assertGreaterEqual(len(collect_calls), 2)
            self.assertTrue(self.service._shutdown_event.is_set())

        asyncio.run(run_test())

    @patch("app.infrastructure.metrics.service.settings")
    @patch("app.infrastructure.metrics.service.logger")
    def test_reporting_loop_exception_handling(self, mock_logger, mock_settings):
        """Test reporting loop handles exceptions"""

        async def run_test():
            mock_settings.METRICS_INTERVAL = 0.1

            call_count = 0

            async def mock_collect_with_error():
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ValueError("Test error")
                elif call_count >= 2:
                    self.service._shutdown_event.set()

            with patch.object(
                self.service, "_collect_and_report_metrics", side_effect=mock_collect_with_error
            ):
                await self.service._reporting_loop()

            # Should have logged the error and continued
            mock_logger.error.assert_called_once_with("Error in metrics reporting loop: Test error")
            self.assertEqual(call_count, 2)

        asyncio.run(run_test())

    @patch("app.infrastructure.metrics.service.settings")
    def test_reporting_loop_cancellation(self, mock_settings):
        """Test reporting loop handles cancellation"""

        async def run_test():
            mock_settings.METRICS_INTERVAL = 0.1

            async def mock_collect():
                # Don't set shutdown event, let it be cancelled
                # Add a small sleep to ensure the loop is running
                await asyncio.sleep(0.01)

            with patch.object(
                self.service, "_collect_and_report_metrics", side_effect=mock_collect
            ):
                task = asyncio.create_task(self.service._reporting_loop())
                await asyncio.sleep(0.05)  # Let it start and run a bit
                task.cancel()

                # The reporting loop catches CancelledError and breaks gracefully
                # So it should complete normally, not raise CancelledError
                await task
                self.assertTrue(task.done())

        asyncio.run(run_test())

    @patch("app.infrastructure.metrics.service.get_queue")
    @patch("app.infrastructure.metrics.service.JobQueue")
    def test_collect_and_report_metrics(self, mock_job_queue, mock_get_queue):
        """Test collecting and reporting metrics"""

        async def run_test():
            # Mock JobQueue enum
            from enum import Enum

            class MockJobQueue(Enum):
                HIGH = "high"
                MEDIUM = "medium"

            mock_job_queue.__iter__ = lambda x: iter([MockJobQueue.HIGH, MockJobQueue.MEDIUM])

            # Mock queue objects
            mock_high_queue = MagicMock()
            mock_high_queue.__len__ = MagicMock(return_value=5)
            mock_high_queue.started_job_registry.count = 2

            mock_medium_queue = MagicMock()
            mock_medium_queue.__len__ = MagicMock(return_value=1)
            mock_medium_queue.started_job_registry.count = 0

            def mock_get_queue_side_effect(queue_name):
                if queue_name == MockJobQueue.HIGH:
                    return mock_high_queue
                elif queue_name == MockJobQueue.MEDIUM:
                    return mock_medium_queue
                return MagicMock()

            mock_get_queue.side_effect = mock_get_queue_side_effect

            # Mock reporter
            mock_reporter = AsyncMock()
            self.service.reporter = mock_reporter

            await self.service._collect_and_report_metrics()

            # Verify report_batch was called
            mock_reporter.report_batch.assert_called_once()

            # Verify the metrics data structure
            call_args = mock_reporter.report_batch.call_args[0][0]
            self.assertEqual(len(call_args), 4)  # 2 metrics per queue * 2 queues

            # Check that we have queue_length and active_tasks for each queue
            metric_names = [metric["name"] for metric in call_args]
            self.assertEqual(metric_names.count("QueueLength"), 2)
            self.assertEqual(metric_names.count("ActiveTasks"), 2)

            # Check dimensions
            high_queue_metrics = [m for m in call_args if m["dimensions"]["QueueName"] == "high"]
            medium_queue_metrics = [
                m for m in call_args if m["dimensions"]["QueueName"] == "medium"
            ]

            self.assertEqual(len(high_queue_metrics), 2)
            self.assertEqual(len(medium_queue_metrics), 2)

            # Check values
            high_queue_length = next(m for m in high_queue_metrics if m["name"] == "QueueLength")
            self.assertEqual(high_queue_length["value"], 5.0)

            high_active_tasks = next(m for m in high_queue_metrics if m["name"] == "ActiveTasks")
            self.assertEqual(high_active_tasks["value"], 2.0)

        asyncio.run(run_test())

    @patch("app.infrastructure.metrics.service.get_queue")
    @patch("app.infrastructure.metrics.service.JobQueue")
    @patch("app.infrastructure.metrics.service.logger")
    def test_collect_and_report_no_metrics(self, mock_logger, mock_job_queue, mock_get_queue):
        """Test collect and report when no queues exist"""

        async def run_test():
            # Empty job queue enum
            mock_job_queue.__iter__ = lambda x: iter([])

            mock_reporter = AsyncMock()
            self.service.reporter = mock_reporter

            await self.service._collect_and_report_metrics()

            # report_batch should not be called with empty metrics
            mock_reporter.report_batch.assert_not_called()

        asyncio.run(run_test())

    def test_global_instance_creation(self):
        """Test that global metrics_service instance is created"""
        from app.infrastructure.metrics.service import metrics_service

        self.assertIsInstance(metrics_service, MetricsService)
        self.assertIsNotNone(metrics_service.reporter)
        self.assertIsNotNone(metrics_service._shutdown_event)
        self.assertIsNone(metrics_service._task)


if __name__ == "__main__":
    unittest.main()
