import io
from http import HTTPStatus
from uuid import UUID

import sympy as sp
from entitysdk import Client, ProjectContext
from entitysdk.models import BrainRegion, MEModel, SingleNeuronSynaptome
from entitysdk.types import AssetLabel, ContentType
from fastapi.responses import JSONResponse
from loguru import logger
from obp_accounting_sdk.constants import ServiceSubtype
from rq import Queue

from app.config.settings import settings
from app.core.api import ApiResponse
from app.core.exceptions import AppError, AppErrorCode
from app.domains.morphology import SynapsePlacementBody
from app.domains.neuron_model import SingleNeuronSynaptomeCreateRequest
from app.infrastructure.accounting.session import async_accounting_session_factory
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.accounting import make_accounting_reservation_async
from app.utils.asyncio import run_async
from app.utils.rq_job import dispatch, get_job_data


async def create_synaptome_model(
    model: SingleNeuronSynaptomeCreateRequest,
    project_context: ProjectContext,
    auth: Auth,
):
    accounting_session = async_accounting_session_factory.oneshot_session(
        name=model.name,
        subtype=ServiceSubtype.SYNAPTOME_BUILD,
        proj_id=project_context.project_id,
        user_id=auth.decoded_token.sub,
        count=1,
    )

    await make_accounting_reservation_async(accounting_session)

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
    )

    await accounting_session.start()

    me_model = await run_async(
        lambda: client.get_entity(entity_id=model.memodel_id, entity_type=MEModel)
    )

    brain_region = await run_async(
        lambda: client.get_entity(
            entity_id=model.brain_region_id,
            entity_type=BrainRegion,  # type: ignore
        )
    )

    synaptome = await run_async(
        lambda: client.register_entity(
            SingleNeuronSynaptome(
                name=model.name,
                description=model.description,
                seed=model.seed,
                me_model=me_model,  # type: ignore
                brain_region=brain_region,
            )
        )
    )

    await run_async(
        lambda: client.upload_content(
            entity_id=synaptome.id,  # pyright: ignore[reportArgumentType]
            entity_type=SingleNeuronSynaptome,
            file_name="config.json",
            file_content=io.BytesIO(model.config.model_dump_json().encode("utf-8")),
            file_content_type=ContentType.application_json,
            asset_label=AssetLabel.single_neuron_synaptome_config,
        )
    )

    await accounting_session.finish()

    return ApiResponse[SingleNeuronSynaptome](
        message="Single neuron synaptome model created successfully",
        data=synaptome,  # type: ignore
    )


async def generate_synapses(
    model_id: UUID,
    params: SynapsePlacementBody,
    *,
    job_queue: Queue,
    access_token: str,
    project_context: ProjectContext,
) -> JSONResponse:
    _job, stream = await dispatch(
        job_queue,
        JobFn.GENERATE_SINGLE_NEURON_SYNAPTOME,
        job_args=(
            model_id,
            params,
        ),
        job_kwargs={"access_token": access_token, "project_context": project_context},
    )

    synaptome = await get_job_data(stream)

    return JSONResponse(synaptome)


def validate_synapse_generation_formula(formula: str):
    try:
        expr = sp.sympify(formula)
        allowed_symbols = {sp.Symbol("x"), sp.Symbol("X")}
        symbols = expr.free_symbols

        if symbols.issubset(allowed_symbols):
            return True
        else:
            return False

    except (sp.SympifyError, SyntaxError) as ex:
        logger.error(
            f"validating synapse generation formula failed [SympifyError, SyntaxError] {ex}"
        )
        return False

    except Exception as ex:
        logger.error(f"validating synapse generation formula failed {ex}")
        raise AppError(
            http_status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code=AppErrorCode.INTERNAL_SERVER_ERROR,
            message="validating synapse generation formula failed",
            details=ex.__str__(),
        ) from ex
