from uuid import UUID, uuid4

from entitysdk import Client
from loguru import logger

from app.core.single_neuron.single_neuron import SingleNeuron
from app.core.single_neuron.validation_output import ValidationOutput


class Validation:
    model_id: UUID
    single_neuron: SingleNeuron
    output: ValidationOutput
    initialized: bool = False
    execution_id: UUID

    def __init__(
        self,
        model_id: UUID,
        client: Client,
        execution_id: UUID | None = None,
    ):
        self.model_id = model_id
        self.execution_id = execution_id or uuid4()
        self.client = client

        self.single_neuron = SingleNeuron(model_id, client)

    def init(self):
        self.single_neuron.init()

    def run(self) -> ValidationOutput:
        # TODO: can we import that globally?
        from bluecellulab.validation.validation import run_validations

        self.output = ValidationOutput(
            self.model_id,
            execution_id=self.execution_id,
            client=self.client,
        )

        logger.info("Running validations")
        result_dict = run_validations(
            self.single_neuron.cell,
            self.single_neuron.metadata.name,
            output_dir=str(self.output.path),
            n_processes=4,
        )

        validation_dict = {k: v for k, v in result_dict.items() if k != "memodel_properties"}

        self.output.set_validation_result(validation_dict)

        return self.output
