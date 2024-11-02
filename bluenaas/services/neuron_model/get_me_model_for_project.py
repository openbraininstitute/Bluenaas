from loguru import logger
from http import HTTPStatus
from bluenaas.external.nexus.nexus import Nexus
from bluenaas.domains.neuron_model import (
    MEModelResponse,
)
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
)
from bluenaas.services.neuron_model.nexus_model_conversions import (
    nexus_me_model_to_bluenaas_me_model,
)


def get_me_model_for_project(
    token: str, org_id: str, project_id: str, model_self: str
) -> MEModelResponse:
    nexus_helper = Nexus({"token": token, "model_self_url": ""})
    try:
        nexus_model = nexus_helper.fetch_resource_by_self(resource_self=model_self)
    except Exception as e:
        logger.error(f"Error when retrieving synaptome {model_self} from nexus {e}")
        raise BlueNaasError(
            message="Resource not found.",
            error_code=BlueNaasErrorCode.NEXUS_ERROR,
            details="Please ensure that the model self is url-encoded.",
            http_status_code=HTTPStatus.NOT_FOUND,
        )

    try:
        return nexus_me_model_to_bluenaas_me_model(nexus_model=nexus_model)
    except Exception as e:
        logger.exception(f"Cannot process incompatible nexus me model {e}")
        raise BlueNaasError(
            message="Resource cannot be processed.",
            error_code=BlueNaasErrorCode.NEXUS_ERROR,
            http_status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        )
