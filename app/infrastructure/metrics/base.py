from abc import ABC, abstractmethod
from typing import Dict, Any
from datetime import datetime


class MetricsReporter(ABC):
    @abstractmethod
    async def report_metric(
        self,
        metric_name: str,
        value: float,
        timestamp: datetime,
        dimensions: Dict[str, str] | None = None,
    ) -> None:
        """Report a single metric value"""
        pass

    @abstractmethod
    async def report_batch(self, metrics: list[Dict[str, Any]]) -> None:
        """Report multiple metrics in a batch"""
        pass
