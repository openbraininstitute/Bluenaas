import asyncio
from datetime import datetime, timezone
from typing import Optional
from loguru import logger


from app.config.settings import settings
from app.infrastructure.rq import get_queue, JobQueue
from .base import MetricsReporter
from .cloudwatch import CloudWatchMetricsReporter
from .stdout import StdoutMetricsReporter


class MetricsService:
    def __init__(self):
        self.reporter: MetricsReporter = self._create_reporter()
        self._task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    def _create_reporter(self) -> MetricsReporter:
        if settings.METRICS_CLOUD_PROVIDER == "aws":
            return CloudWatchMetricsReporter()
        # Future: elif settings.CLOUD_PROVIDER == "azure":
        #     return AzureMetricsReporter()
        else:
            return StdoutMetricsReporter()

    async def start(self) -> None:
        """Start the background metrics reporting task"""
        if self._task and not self._task.done():
            logger.warning("Metrics service already running")
            return

        logger.info(f"Starting metrics service with {settings.METRICS_INTERVAL}s interval")
        self._task = asyncio.create_task(self._reporting_loop())

    async def stop(self) -> None:
        """Stop the background metrics reporting task"""
        if self._task:
            logger.info("Stopping metrics service")
            self._shutdown_event.set()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Metrics task didn't stop gracefully, cancelling")
                self._task.cancel()

    async def _reporting_loop(self) -> None:
        """Main reporting loop that runs in background"""
        while not self._shutdown_event.is_set():
            try:
                await self._collect_and_report_metrics()
                await asyncio.sleep(settings.METRICS_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in metrics reporting loop: {e}")
                await asyncio.sleep(settings.METRICS_INTERVAL)

    async def _collect_and_report_metrics(self) -> None:
        """Collect queue metrics and report them"""
        timestamp = datetime.now(timezone.utc)
        metrics = []

        for queue_name in JobQueue:
            queue = get_queue(queue_name)

            queue_length = len(queue)
            active_tasks = queue.started_job_registry.count

            metrics.extend(
                [
                    {
                        "name": "QueueLength",
                        "value": float(queue_length),
                        "timestamp": timestamp,
                        "dimensions": {"queue_name": queue_name.value},
                    },
                    {
                        "name": "ActiveTasks",
                        "value": float(active_tasks),
                        "timestamp": timestamp,
                        "dimensions": {"queue_name": queue_name.value},
                    },
                ]
            )

            logger.debug(f"Queue {queue_name.value}: {queue_length} jobs, {active_tasks} active")

        if metrics:
            await self.reporter.report_batch(metrics)


# Global instance
metrics_service = MetricsService()
