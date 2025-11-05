from typing import Any

from entitysdk import Client, ProjectContext
from loguru import logger

from app.config.settings import settings
from app.core.ion_channel.build import Build
from app.domains.job import JobStatus
from app.utils.rq_job import get_current_job_stream


def run_ion_channel_build(
    config: Any,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    job_stream = get_current_job_stream()

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    build = Build(config, client=client)

    job_stream.send_status(JobStatus.running, "Initializing ion channel build")
    build.init()

    logger.debug(f"Running ion channel build with config: {config}")
    job_stream.send_status(JobStatus.running, "Running ion channel build")

    try:
        build.run()
    except Exception as e:
        logger.error(f"Ion channel build failed: {e}")
        raise
    finally:
        build.cleanup()
