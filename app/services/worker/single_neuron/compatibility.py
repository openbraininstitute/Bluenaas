from uuid import UUID

from entitysdk import Client, ProjectContext

from app.config.settings import settings
from app.core.job_stream import JobStream
from app.core.single_neuron.compatibility import CompatibilityChecker
from app.domains.job import JobStatus
from app.infrastructure.rq import get_job_stream_key
from app.logging import worker_subprocess


@worker_subprocess
def run_compatibility_check(
    morphology_id: UUID,
    emodel_id: UUID,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    stream_key = get_job_stream_key()
    job_stream = JobStream(stream_key)

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    checker = CompatibilityChecker(morphology_id, emodel_id, client=client)

    job_stream.send_status(JobStatus.running, "checking_compatibility")
    result = checker.run()

    job_stream.send_data_once(result.model_dump(mode="json"))
