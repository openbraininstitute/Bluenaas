from pathlib import Path
from typing import Dict

from entitysdk import Client
from entitysdk.models import MEModelCalibrationResult, ValidationResult
from entitysdk.models.core import Identifiable
from loguru import logger

from app.infrastructure.storage import (
    UUID,
    get_single_neuron_validation_output_location,
)


class ValidationOutput:
    model_id: UUID
    client: Client
    execution_id: UUID
    calibration_result: MEModelCalibrationResult | None = None
    validation_result: Dict | None = None
    path: Path

    def __init__(self, model_id: UUID, *, execution_id: UUID, client: Client):
        self.model_id = model_id
        self.execution_id = execution_id
        self.client = client

        self.path = get_single_neuron_validation_output_location(execution_id)

    def set_calibration_result(
        self, *, holding_current: float, rin: float, threshold_current: float
    ):
        self.calibrationResult = MEModelCalibrationResult(
            calibrated_entity_id=self.model_id,
            holding_current=holding_current,
            rin=rin,
            threshold_current=threshold_current,
        )

    def set_validation_result(self, validation_dict: Dict):
        self.validation_result = validation_dict

    def _upload_file(
        self,
        *,
        path: Path,
        content_type: str,
        asset_label: str,
        entity_id: UUID,
        client: Client,
        raise_on_missing=True,
    ) -> None:
        """Upload a single file if it exists"""
        if not path.exists():
            msg = f"{path.name} can not be found"

            if raise_on_missing:
                raise FileNotFoundError(msg)
            else:
                logger.warning(msg)
                return

        with open(path, "rb") as f:
            client.upload_content(
                entity_id=entity_id,
                entity_type=ValidationResult,
                file_name=path.name,
                file_content=f,
                file_content_type=content_type,
                asset_label=asset_label,
            )

    def _uploadCalibrationResult(self):
        assert self.calibration_result
        # Do not register MEModelCalibrationResult if it already exists
        # Once we are able to delete the CalibrationResult, we should move to the following logic:
        # if no MEModelCalibrationResult exists, register a new one
        # if one exists with exactly the same values, do nothing
        # if one exists with different values, delete the old one and register a new one
        iterator = self.client.search_entity(
            entity_type=MEModelCalibrationResult,
            query={
                "calibrated_entity_id": self.calibration_result.calibrated_entity_id
            },
        )
        cal = iterator.first()
        if cal is not None:
            model_id = self.calibration_result.calibrated_entity_id
            logger.warning(
                f"MEModel {model_id} has already calibration result. Skipping registration"
            )
            return

        self.client.register_entity(
            entity=self.calibration_result,
        )

    def _uploadValidationResult(self) -> Identifiable:
        validation_result = self.client.register_entity(
            ValidationResult(
                name=val_dict["name"],
                passed=val_dict["passed"],
                validated_entity_id=self.model_id,
            )
        )
        assert validation_result.id
        logger.info(f"Registered validaton result {validation_result.id}")

        for pdf_file in self.path.glob("*.pdf"):
            self._upload_file(
                client=self.client,
                path=pdf_file,
                content_type="application/pdf",
                asset_label="validation_result_figure",
                entity_id=validation_result.id,
            )

        return validation_result

    def upload(self):
        self._uploadCalibrationResult()
        self._uploadValidationResult()
