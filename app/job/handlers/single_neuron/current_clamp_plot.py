from uuid import UUID

from entitysdk.common import ProjectContext

from app.domains.simulation import StimulationPlotConfig
from app.services.worker.single_neuron.current_clamp_plot import (
    get_single_neuron_current_clamp_plot_data,
)


def get_current_clamp_plot_data(
    model_id: UUID,
    config: StimulationPlotConfig,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    get_single_neuron_current_clamp_plot_data(
        model_id,
        config,
        access_token=access_token,
        project_context=project_context,
    )
