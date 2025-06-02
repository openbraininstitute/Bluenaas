import json

from fastapi import Request
from fastapi.responses import StreamingResponse
from loguru import logger
from rq import Queue

from bluenaas.core.model import model_factory
from bluenaas.core.simulation_factory_plot import StimulusFactoryPlot
from bluenaas.domains.simulation import StimulationPlotConfig
from bluenaas.external.entitycore.service import ProjectContext
from bluenaas.infrastructure.redis import stream_one
from bluenaas.infrastructure.rq import get_current_stream_key
from bluenaas.utils.rq_job import dispatch
from bluenaas.utils.streaming import x_ndjson_http_stream


def get_current_clamp_plot_data_stream(
    request: Request,
    queue: Queue,
    model_id: str,
    config: StimulationPlotConfig,
    token: str,
    entitycore: bool = False,
    project_context: ProjectContext | None = None,
):
    # TODO: Switch to normal HTTP response, there is no benefit in streaming here.
    _job, stream = dispatch(
        queue,
        get_current_clamp_plot_data_task,
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


def get_current_clamp_plot_data_task(
    model_id: str,
    config: StimulationPlotConfig,
    token: str,
    entitycore: bool = False,
    project_context: ProjectContext | None = None,
):
    stream_key = get_current_stream_key()
    logger.info(f"Stream key: {stream_key}")

    try:
        model = model_factory(
            model_id=model_id,
            hyamp=None,
            bearer_token=token,
            entitycore=entitycore,
            project_context=project_context,
        )
        stimulus_factory_plot = StimulusFactoryPlot(
            config,
            model.threshold_current,
        )
        plot_data = stimulus_factory_plot.apply_stim()
        stream_one(stream_key, json.dumps(plot_data))

    except Exception as ex:
        logger.exception(f"Stimulation direct current plot builder error: {ex}")
        stream_one(stream_key, "error")
