from uuid import UUID

from entitysdk.common import ProjectContext
from loguru import logger

from app.core.job_stream import JobStream
from app.core.model import model_factory
from app.core.simulation_factory_plot import StimulusFactoryPlot
from app.domains.simulation import StimulationPlotConfig
from app.infrastructure.rq import get_job_stream_key


def get_single_neuron_current_clamp_plot_data(
    model_id: UUID,
    config: StimulationPlotConfig,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    stream_key = get_job_stream_key()
    job_stream = JobStream(stream_key)

    try:
        # TODO: consider moving this logic to services/worker
        model = model_factory(
            model_id,
            hyamp=None,
            access_token=access_token,
            project_context=project_context,
        )
        stimulus_factory_plot = StimulusFactoryPlot(
            config,
            model.threshold_current,
        )
        plot_data = stimulus_factory_plot.apply_stim()

        job_stream.send_data(plot_data)
        job_stream.close()

    except Exception as ex:
        logger.exception(f"Stimulation direct current plot builder error: {ex}")
        raise
