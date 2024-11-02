from typing import Optional
from datetime import datetime
from loguru import logger
from http import HTTPStatus

from bluenaas.external.nexus.nexus import Nexus
from bluenaas.domains.simulation import PaginatedResponse
from bluenaas.domains.neuron_model import (
    NexusSynaptomeType,
    SynaptomeModelResponse,
)
from bluenaas.services.neuron_model.nexus_model_conversions import (
    nexus_synaptome_model_to_bluenaas_synaptome_model,
)
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
)


def get_all_synaptome_models_for_project(
    token: str,
    org_id: str,
    project_id: str,
    offset: int,
    size: int,
    created_at_start: Optional[datetime],
    created_at_end: Optional[datetime],
) -> PaginatedResponse[SynaptomeModelResponse]:
    try:
        nexus_helper = Nexus(
            {"token": token, "model_self_url": ""}
        )  # TODO: Remove model_id as a required field for nexus helper

        nexus_model_response = nexus_helper.fetch_resources_of_type(
            org_label=org_id,
            project_label=project_id,
            res_types=[NexusSynaptomeType],
            offset=offset,
            size=size,
            created_at_start=created_at_start,
            created_at_end=created_at_end,
        )
        nexus_models = nexus_model_response["_results"]

        synaptome_models = []

        for nexus_model in nexus_models:
            verbose_model = nexus_helper.fetch_resource_by_self(nexus_model["_self"])
            file_url = verbose_model["distribution"]["contentUrl"]

            file_response = nexus_helper.fetch_file_by_url(file_url)
            distribution = file_response.json()

            synaptome_model = nexus_synaptome_model_to_bluenaas_synaptome_model(
                nexus_model=verbose_model, distribution=distribution
            )
            synaptome_models.append(synaptome_model)

        return PaginatedResponse[SynaptomeModelResponse](
            page_offset=offset,
            page_size=len(synaptome_models),
            total=nexus_model_response["_total"],
            results=synaptome_models,
        )
    except Exception as e:
        logger.exception(f"Error retrieving synaptome models from nexus {e}")
        raise BlueNaasError(
            message="Error retrieving synaptome models from nexus.",
            error_code=BlueNaasErrorCode.NEXUS_ERROR,
            http_status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
