import json
from loguru import logger

from bluenaas.infrastructure.celery import celery_app
from bluenaas.core.exceptions import MorphologyGenerationError
from bluenaas.domains.simulation import StimulationPlotConfig


@celery_app.task(
    bind=True,
    serializer="json",
)
def build_stimulation_graph(
    self,
    model_self: str,
    token: str,
    config: str,  # JSON string representing object of type StimulationPlotConfig
):
    try:
        from bluenaas.core.model import model_factory
        from bluenaas.core.simulation_factory_plot import StimulusFactoryPlot

        stimulus_plot_config = StimulationPlotConfig(**json.loads(config))

        logger.debug(f"Started stimulation graph building for model {model_self}")

        model = model_factory(
            model_self=model_self,
            hyamp=None,
            bearer_token=token,
        )
        stimulus_factory_plot = StimulusFactoryPlot(
            stimulus_plot_config,
            model.threshold_current,
        )
        result_data = stimulus_factory_plot.apply_stim()

        logger.debug(f"Completed stimulation graph building for model {model_self}")
        return json.dumps(result_data)
    except Exception as e:
        logger.exception(
            f"Exception in celery worker during stimulation graph building {e}"
        )
        raise MorphologyGenerationError(
            message=f"Exception in celery worker during stimulation graph building {e}"
        )
