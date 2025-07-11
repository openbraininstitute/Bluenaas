from uuid import UUID, uuid4

from entitysdk import Client
from loguru import logger

from app.core.single_neuron.single_neuron import SingleNeuron
from app.core.single_neuron.validation_output import ValidationOutput


class Validation:
    single_neuron: SingleNeuron
    output: ValidationOutput
    initialized: bool = False
    execution_id: UUID

    def __init__(
        self,
        model_id: UUID,
        client: Client,
        execution_id: UUID = uuid4(),
    ):
        self.execution_id = execution_id
        self.client = client

        self.single_neuron = SingleNeuron(model_id, client)

        # So that we can upload generated results, including logs even if the model init fails.
        self._init_output()

    def _init_single_neuron(self):
        self.single_neuron.init()

    def _init_output(self):
        assert self.single_neuron.metadata.id

        self.output = ValidationOutput(
            self.single_neuron.metadata.id,
            execution_id=self.execution_id,
            client=self.client,
        )

    def init(self):
        self._init_single_neuron()

    def run(self) -> ValidationOutput:
        # TODO: can we import that globally?
        from bluecellulab.validation.validation import run_validations

        logger.info("Running validations")
        result_dict = run_validations(
            self.single_neuron.cell,
            self.single_neuron.metadata.name,
            output_dir=str(self.output.path),
        )

        # TODO: Use pydantic class / validate
        calibration_dict = result_dict["memodel_properties"]
        logger.info("Setting calibration result")
        self.output.set_calibration_result(
            holding_current=calibration_dict["holding_current"],
            threshold_current=calibration_dict["rheobase"],
            rin=calibration_dict["rin"],
        )

        validation_dict = {
            k: v for k, v in result_dict.items() if k != "memodel_properties"
        }

        self.output.set_validation_result(validation_dict)

        return self.output
