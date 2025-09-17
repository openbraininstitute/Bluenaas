import boto3
from datetime import datetime
from typing import Dict, Any
from loguru import logger


from app.config.settings import settings
from app.utils.asyncio import run_async
from .base import MetricsReporter


class CloudWatchMetricsReporter(MetricsReporter):
    def __init__(self, namespace: str = "SmallScaleSimulator/JobQueue"):
        client_config = {}
        if settings.METRICS_AWS_REGION:
            client_config["region_name"] = settings.METRICS_AWS_REGION

        self.cloudwatch = boto3.client("cloudwatch", **client_config)
        self.namespace = namespace

    async def report_metric(
        self,
        metric_name: str,
        value: float,
        timestamp: datetime,
        dimensions: Dict[str, str] | None = None,
    ) -> None:
        metric_data = {
            "MetricName": metric_name,
            "Value": value,
            "Timestamp": timestamp,
            "Unit": "Count",
        }

        if dimensions:
            metric_data["Dimensions"] = [{"Name": k, "Value": v} for k, v in dimensions.items()]

        await run_async(
            lambda: self.cloudwatch.put_metric_data(
                Namespace=self.namespace, MetricData=[metric_data]
            )
        )

        logger.debug(f"Sent metric {metric_name}={value} to CloudWatch")

    async def report_batch(self, metrics: list[Dict[str, Any]]) -> None:
        if not metrics:
            return

        metric_data = []
        for metric in metrics:
            data = {
                "MetricName": metric["name"],
                "Value": metric["value"],
                "Timestamp": metric["timestamp"],
                "Unit": "Count",
            }
            if metric.get("dimensions"):
                data["Dimensions"] = [
                    {"Name": k, "Value": v} for k, v in metric["dimensions"].items()
                ]
            metric_data.append(data)

        # CloudWatch allows max 20 metrics per put_metric_data call
        for i in range(0, len(metric_data), 20):
            batch = metric_data[i : i + 20]
            await run_async(
                lambda b=batch: self.cloudwatch.put_metric_data(
                    Namespace=self.namespace, MetricData=b
                )
            )

        logger.debug(f"Sent {len(metrics)} metrics to CloudWatch")
