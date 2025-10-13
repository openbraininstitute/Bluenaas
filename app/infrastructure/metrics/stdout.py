import json
from datetime import datetime
from typing import Dict, Any
from loguru import logger

from .base import MetricsReporter


class StdoutMetricsReporter(MetricsReporter):
    async def report_metric(
        self,
        metric_name: str,
        value: float,
        timestamp: datetime,
        dimensions: Dict[str, str] | None = None,
    ) -> None:
        metric_data = {
            "metric_name": metric_name,
            "value": value,
            "timestamp": timestamp.isoformat(),
            "dimensions": dimensions or {},
        }
        logger.info(f"METRIC: {json.dumps(metric_data)}")

    async def report_batch(self, metrics: list[Dict[str, Any]]) -> None:
        for metric in metrics:
            await self.report_metric(
                metric["name"], metric["value"], metric["timestamp"], metric.get("dimensions")
            )
