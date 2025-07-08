from uuid import UUID

from entitysdk.common import ProjectContext

from app.core.model import model_factory
from app.core.simulation_factory_plot import StimulusFactoryPlot
from app.domains.simulation import (
    SimulationStimulusConfig,
    StimulationItemResponse,
    StimulationPlotConfig,
)


def get_stimulation_plot_data(
    model_id: UUID,
    stimulus: SimulationStimulusConfig,
    *,
    project_context: ProjectContext,
    access_token: str,
) -> list[StimulationItemResponse]:
    model = model_factory(
        model_id, hyamp=None, access_token=access_token, project_context=project_context
    )
    stimulus_config = StimulationPlotConfig(
        stimulus_protocol=stimulus.stimulus_protocol,
        amplitudes=stimulus.amplitudes
        if isinstance(stimulus.amplitudes, list)
        else [stimulus.amplitudes],
    )
    stimulus_factory_plot = StimulusFactoryPlot(
        stimulus_config,
        model.threshold_current,
    )
    plot_data = stimulus_factory_plot.apply_stim()
    for trace in plot_data:
        StimulationItemResponse.model_validate(trace)
    return plot_data
