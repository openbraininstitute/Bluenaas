from pathlib import Path
from typing import Dict

from entitysdk import Client
from entitysdk.types import ContentType, AssetLabel
from entitysdk.models import ValidationResult
from loguru import logger

from app.infrastructure.storage import (
    UUID,
    get_single_neuron_validation_output_location,
)


class ValidationOutput:
    def __init__(self, model_id: UUID, *, execution_id: UUID, client: Client):
        self.model_id: UUID = model_id
        self.execution_id: UUID = execution_id
        self.client: Client = client
        self.validation_result: Dict | None = None
        self.path: Path = get_single_neuron_validation_output_location(execution_id)

    def set_validation_result(self, validation_dict: Dict):
        self.validation_result = validation_dict

    def _upload_validation_result_entry(self, val_dict: Dict) -> None:
        # Do not register ValidationResult if it already exists
        # Once we are able to delete the ValidationResult, we should move to the following logic:
        # delete the ValidationResult if it already exists
        # register the new one
        iterator = self.client.search_entity(
            entity_type=ValidationResult,
            query={"name": val_dict["name"], "validated_entity_id": self.model_id},
        )
        if iterator.first() is not None:
            logger.warning(
                f"MEModel {self.model_id} has already validation result for {val_dict['name']}. Skipping registration"
            )
            return

        validation_result_entity = ValidationResult(
            name=val_dict["name"],
            passed=val_dict["passed"],
            validated_entity_id=self.model_id,
        )
        registered = self.client.register_entity(
            entity=validation_result_entity,
        )

        assert registered.id

        for fig_path in val_dict["figures"]:
            if fig_path.suffix not in [".pdf", ".png"]:
                logger.warning(f"Unsupported figure format: {str(fig_path)}")
                continue

            self.client.upload_file(
                entity_id=registered.id,
                entity_type=ValidationResult,
                file_path=fig_path,
                file_content_type=ContentType.application_pdf
                if fig_path.suffix == ".pdf"
                else ContentType.image_png,
                asset_label=AssetLabel.validation_result_figure,
            )

        if val_dict["validation_details"]:
            # write down validation details to a file
            val_details_fname = f"{val_dict['name'].replace(' ', '')}_validation_details.txt"
            val_details_path = self.path / val_details_fname

            with open(val_details_path, "w") as f:
                f.write(val_dict["validation_details"])

            # register validation details as asset
            self.client.upload_file(
                entity_id=registered.id,
                entity_type=ValidationResult,
                file_path=val_details_path,
                file_content_type=ContentType.text_plain,
                asset_label=AssetLabel.validation_result_details,
            )

    def _upload_validation_result(self) -> None:
        logger.debug("Uploading validation result(s)")

        assert self.validation_result

        for validation_result_entry in self.validation_result.values():
            self._upload_validation_result_entry(validation_result_entry)

    def upload(self):
        self._upload_validation_result()
