import boto3
from botocore.config import Config
from mypy_boto3_ecs import ECSClient
from mypy_boto3_cloudwatch import CloudWatchClient

from bluenaas.config.settings import settings

boto3_config = Config(
    region_name=settings.AWS_REGION,
    signature_version="v4",
    retries=dict(
        max_attempts=10,
        mode="standard",
    ),
)


def get_ecs_boto_client() -> ECSClient:
    """
    Returns boto3 client for the provided service name
    """
    try:
        return boto3.client(
            "ecs",
            config=boto3_config,
        )
    except Exception as ex:
        raise ex


def get_cloudwatch_boto_client() -> CloudWatchClient:
    """
    Returns boto3 client for the provided service name
    """
    try:
        return boto3.client(
            "cloudwatch",
            config=boto3_config,
        )
    except Exception as ex:
        raise ex
