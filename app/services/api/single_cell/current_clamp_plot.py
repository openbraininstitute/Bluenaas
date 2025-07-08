from uuid import UUID

from fastapi import Request
from fastapi.responses import StreamingResponse
from rq import Queue

from app.domains.simulation import StimulationPlotConfig
from app.external.entitycore.service import ProjectContext
from app.job import JobFn
from app.utils.api.streaming import x_ndjson_http_stream
from app.utils.rq_job import dispatch


async def get_current_clamp_plot_data_stream(
    model_id: UUID,
    config: StimulationPlotConfig,
    *,
    request: Request,
    job_queue: Queue,
    access_token: str,
    project_context: ProjectContext,
) -> StreamingResponse:
    # TODO: Switch to normal HTTP response, there is no benefit in streaming here.
    _job, stream = await dispatch(
        job_queue,
        JobFn.GET_CURRENT_CLAMP_PLOT_DATA,
        job_args=(
            model_id,
            config,
        ),
        job_kwargs={"access_token": access_token, "project_context": project_context},
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")
