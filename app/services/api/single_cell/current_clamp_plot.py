from fastapi import Request
from fastapi.responses import StreamingResponse
from rq import Queue

from app.domains.simulation import StimulationPlotConfig
from app.external.entitycore.service import ProjectContext
from app.job import JobFn
from app.utils.rq_job import dispatch
from app.utils.api.streaming import x_ndjson_http_stream


async def get_current_clamp_plot_data_stream(
    request: Request,
    queue: Queue,
    model_id: str,
    config: StimulationPlotConfig,
    token: str,
    entitycore: bool = False,
    project_context: ProjectContext | None = None,
):
    # TODO: Switch to normal HTTP response, there is no benefit in streaming here.
    _job, stream = await dispatch(
        queue,
        JobFn.GET_CURRENT_CLAMP_PLOT_DATA,
        job_args=(
            model_id,
            config,
            token,
            entitycore,
            project_context,
        ),
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")
