from uuid import UUID

from entitysdk import Client

from app.core.single_neuron.calibration_output import CalibrationOutput
from app.core.single_neuron.single_neuron import SingleNeuron


class Calibration:
    model_id: UUID
    single_neuron: SingleNeuron
    output: CalibrationOutput

    def __init__(
        self,
        model_id: UUID,
        client: Client,
    ):
        self.model_id = model_id
        self.client = client

        self.single_neuron = SingleNeuron(model_id, client)

    def init(self):
        self.single_neuron.init()

    def run(self) -> CalibrationOutput | None:
        from bluecellulab.tools import compute_memodel_properties

        model_properties = compute_memodel_properties(self.single_neuron.cell)

        self.output = CalibrationOutput(
            self.model_id,
            holding_current=model_properties["holding_current"],
            threshold_current=model_properties["rheobase"],
            rin=model_properties["rin"],
            client=self.client,
        )

        return self.output
