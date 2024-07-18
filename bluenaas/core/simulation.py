"""Simulation."""

from loguru import logger as L

from bluenaas.core.cell import HocCell
from bluenaas.core.model import Model
from bluenaas.core.simulation_factory_plot import StimulusFactoryPlot
from bluenaas.domains.simulation import SimulationConfigBody


class Simulation:
    def __init__(self, *, cell: HocCell):
        self.CELL = cell
        self.THRESHOLD_CURRENT = 1

    def get_sec_info(self, values):
        """Get section info."""
        return self.CELL.get_sec_info(values)

    def set_injection_location(self, values):
        """Set injection location."""
        self.CELL.set_injection_location(values)
        return self.CELL.get_injection_location()

    def stop_simulation(self):
        """Stop simulation."""
        self.CELL.stop_simulation()
        return True

    def start_simulation(self, values: SimulationConfigBody):
        """Start simulation."""
        L.info("Starting simulation...")
        result = self.CELL.start_simulation(values)
        L.info("Simulation ended!")
        return result

    def get_ui_data(self):
        """Get UI data."""
        results = {"morphology": self.CELL.get_cell_morph()}
        return results

    def get_stimuli_plot_data(self, values):
        """Get stimuli plot data."""
        # As the model need to be initialized first, the THRESHOLD_CURRENT is set already
        stimulus_factory_plot = StimulusFactoryPlot(values, self.THRESHOLD_CURRENT)
        result_data = stimulus_factory_plot.apply_stim()
        return result_data


class Treat:
    def __init__(self, *, model_id: str, config: any, token: str) -> None:
        self.token: str = token
        self.model_id: str = model_id
        self.config: SimulationConfigBody = config
        self.simulation_result: any = None

    def run(self):
        model = Model(model_id=self.model_id, token=self.token)
        model.build_model()
        simulation = Simulation(cell=model.CELL)
        simulation.set_injection_location(self.config.injectTo)
        result = simulation.start_simulation(self.config)
        return result
