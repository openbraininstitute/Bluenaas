from entitysdk import Client
from entitysdk.models import MEModelCalibrationResult
from loguru import logger

from app.infrastructure.storage import (
    UUID,
)


class CalibrationOutput:
    model_id: UUID
    client: Client
    calibration_result: MEModelCalibrationResult | None = None

    def __init__(
        self,
        model_id: UUID,
        *,
        holding_current: float,
        threshold_current: float,
        rin: float,
        client: Client,
    ):
        self.model_id = model_id
        self.client = client

        self.calibration_result = MEModelCalibrationResult(
            calibrated_entity_id=self.model_id,
            holding_current=holding_current,
            rin=rin,
            threshold_current=threshold_current,
        )

    def upload(self):
        logger.debug("Uploading calibration results")

        assert self.calibration_result
        # Do not register MEModelCalibrationResult if it already exists
        # Once we are able to delete the CalibrationResult, we should move to the following logic:
        # if no MEModelCalibrationResult exists, register a new one
        # if one exists with exactly the same values, do nothing
        # if one exists with different values, delete the old one and register a new one
        iterator = self.client.search_entity(
            entity_type=MEModelCalibrationResult,
            query={"calibrated_entity_id": self.calibration_result.calibrated_entity_id},
        )
        if iterator.first() is not None:
            logger.warning(
                f"MEModel {self.model_id} already has calibration result. Skipping registration"
            )
            return

        self.client.register_entity(
            entity=self.calibration_result,
        )
