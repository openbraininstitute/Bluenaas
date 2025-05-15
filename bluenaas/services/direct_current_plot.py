import signal
import multiprocessing as mp
from loguru import logger
from http import HTTPStatus as status
from threading import Event
from queue import Empty as QueueEmptyException
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
    StimulationPlotGenerationError,
)
from bluenaas.core.model import model_factory
from bluenaas.core.simulation_factory_plot import StimulusFactoryPlot
from bluenaas.domains.simulation import StimulationPlotConfig
from bluenaas.utils.const import QUEUE_STOP_EVENT
from bluenaas.external.entitycore.service import ProjectContext


def _build_direct_current_plot_data(
    model_id: str,
    config: StimulationPlotConfig,
    token: str,
    queue: mp.Queue,
    stop_event: Event,
    entitycore: bool = False,
    project_context: ProjectContext | None = None,
):
    def stop_process(signum: int, frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_process)
    signal.signal(signal.SIGINT, stop_process)

    try:
        model = model_factory(
            model_id=model_id,
            hyamp=None,
            bearer_token=token,
            entitycore=entitycore,
            project_contect=project_context,
        )
        stimulus_factory_plot = StimulusFactoryPlot(
            config,
            model.threshold_current,
        )
        result_data = stimulus_factory_plot.apply_stim()
        queue.put(result_data)
        queue.put(QUEUE_STOP_EVENT)

    except Exception as ex:
        queue.put(QUEUE_STOP_EVENT)
        logger.exception(f"Stimulation direct current plot builder error: {ex}")
        raise StimulationPlotGenerationError from ex
    finally:
        logger.debug("Stimulation direct current plot ended")


def get_direct_current_plot_data(
    model_id: str,
    config: StimulationPlotConfig,
    token: str,
    req_id: str,
    entitycore: bool = False,
    project_context: ProjectContext | None = None,
):
    try:
        ctx = mp.get_context("spawn")

        plot_queue = ctx.Queue()
        stop_event = ctx.Event()

        process = ctx.Process(
            target=_build_direct_current_plot_data,
            args=(
                model_id,
                config,
                token,
                plot_queue,
                stop_event,
                entitycore,
                project_context,
            ),
            name=f"direct_current_plot_processor:{req_id}",
        )
        process.daemon = True
        process.start()

        result: list = []
        try:
            while True:
                try:
                    q_result = plot_queue.get(timeout=1)
                except QueueEmptyException:
                    if process.is_alive():
                        continue
                    if not plot_queue.empty():
                        continue
                    else:
                        raise Exception("Child process died unexpectedly")
                if isinstance(q_result, list):
                    result = q_result

                if q_result == QUEUE_STOP_EVENT or stop_event.is_set():
                    break
        finally:
            plot_queue.close()
            plot_queue.join_thread()
            process.join()
        return result
    except Exception as ex:
        logger.exception(f"retrieving stimulus direct current data failed {ex}")
        raise BlueNaasError(
            http_status_code=status.INTERNAL_SERVER_ERROR,
            error_code=BlueNaasErrorCode.INTERNAL_SERVER_ERROR,
            message="retrieving stimulus direct current data failed",
            details=ex.__str__(),
        ) from ex
