from uuid import UUID

from entitysdk import Client

from app.config.settings import settings
from app.core.job_stream import JobStream
from app.core.single_neuron.validation import Validation
from app.domains.job import JobStatus
from app.external.entitycore.service import ProjectContext
from app.infrastructure.rq import get_job_stream_key


def run(
    model_id: UUID,
    *,
    access_token: str,
    execution_id: UUID,
    project_context: ProjectContext,
):
    stream_key = get_job_stream_key()
    job_stream = JobStream(stream_key)

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    validation = Validation(model_id, client=client, execution_id=execution_id)

    job_stream.send_status(JobStatus.running, "validation_init")
    validation.init()

    job_stream.send_status(JobStatus.running, "validation_exec")
    validation.run()

    job_stream.send_status(JobStatus.running, "results_upload")
    validation.output.upload()
