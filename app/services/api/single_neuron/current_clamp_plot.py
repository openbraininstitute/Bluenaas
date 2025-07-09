from uuid import UUID

from fastapi.responses import JSONResponse
from rq import Queue

from app.domains.simulation import StimulationPlotConfig
from app.external.entitycore.service import ProjectContext
from app.job import JobFn
from app.utils.rq_job import dispatch, get_job_data


async def get_current_clamp_plot_data_response(
    model_id: UUID,
    config: StimulationPlotConfig,
    *,
    job_queue: Queue,
    access_token: str,
    project_context: ProjectContext,
) -> JSONResponse:
    _job, stream = await dispatch(
        job_queue,
        JobFn.GET_CURRENT_CLAMP_PLOT_DATA,
        job_args=(
            model_id,
            config,
        ),
        job_kwargs={"access_token": access_token, "project_context": project_context},
    )
    current_clamp_plot_data = await get_job_data(stream)

    return JSONResponse(current_clamp_plot_data)
