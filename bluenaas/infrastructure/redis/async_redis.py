import time
from redis.asyncio import Redis
from bluenaas.config.settings import settings
from bluenaas.constants import STOP_MESSAGE, MAX_TASK_DURATION
from bluenaas.core.exceptions import BlueNaasError, BlueNaasErrorCode

redis_client = Redis.from_url(url=settings.REDIS_URL, decode_responses=True)


async def redis_stream_reader(stream_key: str, timeout: int = MAX_TASK_DURATION):
    """
    Asynchronously read messages from a Redis stream with timeout handling.

    This function is a generator that continuously reads messages from a specified Redis stream.
    It supports a configurable timeout to prevent indefinite blocking and allows processing
    stream messages one at a time.

    Args:
        stream_key (str): The key of the Redis stream to read from.
        timeout (int, optional): Maximum duration in seconds to read from the stream.
                                Defaults to MAX_TASK_DURATION.

    Yields:
        The data payload of each message in the stream.

    Raises:
        BlueNaasError: If the stream reading exceeds the specified timeout.

    Notes:
        - Stops reading when a STOP_MESSAGE is encountered.
        - Uses non-blocking reads with a 1-second block interval.
        - Tracks and updates the last read message ID to support resumable reading.
    """
    last_id = "0"
    start_time = time.time()

    while True:
        # Check if timeout has been reached
        if time.time() - start_time > timeout:
            raise BlueNaasError(
                message=f"Redis stream reader timeout after {timeout} seconds",
                error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
                details=f"Stream key: {stream_key}",
            )

        # Read messages from Redis stream
        response = await redis_client.xread(
            streams={stream_key: last_id},
            count=1,
            block=1000,  # ms
        )
        if not response:
            continue

        for stream_key, messages in response:
            for message_id, fields in messages:
                last_id = message_id
                data = fields.get("data")

                if data == STOP_MESSAGE:
                    return

                yield data
