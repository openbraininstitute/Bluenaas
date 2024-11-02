from loguru import logger
from http import HTTPStatus
from typing import Optional
from datetime import datetime

from bluenaas.external.nexus.nexus import Nexus
from bluenaas.domains.neuron_model import MEModelResponse, NexusMEModelType
from bluenaas.domains.simulation import PaginatedResponse
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
)
from bluenaas.services.neuron_model.nexus_model_conversions import (
    nexus_me_model_to_bluenaas_me_model,
)


def get_all_me_models_for_project(
    token: str,
    org_id: str,
    project_id: str,
    offset: int,
    size: int,
    created_at_start: Optional[datetime],
    created_at_end: Optional[datetime],
) -> PaginatedResponse[MEModelResponse]:
    try:
        nexus_helper = Nexus({"token": token, "model_self_url": ""})

        nexus_model_response = nexus_helper.fetch_resources_of_type(
            org_label=None,
            project_label=None,
            res_types=[NexusMEModelType],
            offset=offset,
            size=size,
            created_at_start=created_at_start,
            created_at_end=created_at_end,
        )

        nexus_models = nexus_model_response["_results"]
        logger.debug(f"REMOVE NEXUS {(len(nexus_models))}")
        me_models = []

        for nexus_model in nexus_models:
            verbose_model = nexus_helper.fetch_resource_by_self(
                resource_self=nexus_model["_self"]
            )
            try:
                me_models.append(
                    nexus_me_model_to_bluenaas_me_model(nexus_model=verbose_model)
                )
            except ValueError:
                logger.debug(
                    f"Nexus model {nexus_model["_self"]} could not be converted to me_model_response"
                )

        return PaginatedResponse[MEModelResponse](
            page_offset=offset,
            page_size=len(me_models),
            total=nexus_model_response["_total"],
            results=me_models,
        )
    except Exception as e:
        logger.exception(f"Error retrieving me models from nexus {e}")
        raise BlueNaasError(
            message="Error retrieving me models from nexus.",
            error_code=BlueNaasErrorCode.NEXUS_ERROR,
            http_status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
