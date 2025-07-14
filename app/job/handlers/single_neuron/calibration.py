from uuid import UUID

from entitysdk import Client

from app.config.settings import settings
from app.core.job_stream import JobStream
from app.core.single_neuron.calibration import Calibration
from app.domains.job import JobStatus
from app.external.entitycore.service import ProjectContext
from app.infrastructure.rq import get_job_stream_key


def run(
    model_id: UUID,
    *,
    access_token: str,
    project_context: ProjectContext,
):
    stream_key = get_job_stream_key()
    job_stream = JobStream(stream_key)

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    calibration = Calibration(model_id, client=client)

    job_stream.send_status(JobStatus.running, "calibration_init")
    calibration.init()

    job_stream.send_status(JobStatus.running, "calibration_exec")
    calibration.run()

    job_stream.send_status(JobStatus.running, "results_upload")
    calibration.output.upload()
