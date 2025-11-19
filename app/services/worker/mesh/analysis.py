from uuid import UUID

from entitysdk import Client, ProjectContext
from loguru import logger

from app.config.settings import settings
from app.core.mesh.analysis import Analysis
from app.domains.job import JobStatus
from app.infrastructure.rq import get_job_stream_key
from app.utils.rq_job import JobStream


def run_mesh_analysis(
    em_cell_mesh_id: UUID,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    job_stream = JobStream(get_job_stream_key())

    logger.info(f"Starting analysis for mesh {em_cell_mesh_id}")

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    analysis = Analysis(em_cell_mesh_id, client=client)

    try:
        analysis.init()
        analysis_result = analysis.run()
        job_stream.send_data(analysis_result)
    except Exception as e:
        logger.exception(e)
        job_stream.send_status(JobStatus.error, str(e))
        raise
    finally:
        job_stream.close()

    logger.info(f"Analysis completed for mesh {em_cell_mesh_id}")
