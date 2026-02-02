import datetime

from http import HTTPStatus
from uuid import UUID

from entitysdk import Client, ProjectContext
from entitysdk._server_schemas import ValidationStatus
from entitysdk.models import (
    BrainRegion,
    CellMorphology,
    EModel,
    MEModel,
    Species,
    Strain,
    MTypeClassification,
    ETypeClassification,
    Person,
    Role,
    Contribution
)
from loguru import logger
from obp_accounting_sdk.constants import ServiceSubtype
from obp_accounting_sdk.errors import BaseAccountingError, InsufficientFundsError
from rq import Queue

from app.config.settings import settings
from app.core.api import ApiResponse
from app.core.exceptions import AppError, AppErrorCode
from app.domains.neuron_model import MEModelCreateRequest
from app.infrastructure.accounting.session import async_accounting_session_factory
from app.infrastructure.kc.auth import Auth
from app.job import JobFn
from app.utils.asyncio import run_async
from app.utils.rq_job import dispatch


async def create_single_neuron_model(
    model: MEModelCreateRequest,
    project_context: ProjectContext,
    auth: Auth,
    job_queue: Queue,
):
    accounting_session = async_accounting_session_factory.oneshot_session(
        name=model.name,
        subtype=ServiceSubtype.SINGLE_CELL_BUILD,
        proj_id=project_context.project_id,
        user_id=auth.decoded_token.sub,
        count=1,
    )

    try:
        await accounting_session.make_reservation()
        logger.info("Accounting reservation success")
    except InsufficientFundsError as ex:
        logger.warning(f"Insufficient funds: {ex}")
        raise AppError(
            http_status_code=HTTPStatus.FORBIDDEN,
            error_code=AppErrorCode.ACCOUNTING_INSUFFICIENT_FUNDS_ERROR,
            message="The project does not have enough funds to run the simulation",
            details=ex.__str__(),
        ) from ex
    except BaseAccountingError as ex:
        logger.warning(f"Accounting service error: {ex}")
        raise AppError(
            http_status_code=HTTPStatus.BAD_GATEWAY,
            error_code=AppErrorCode.ACCOUNTING_GENERIC_ERROR,
            message="Accounting service error",
            details=ex.__str__(),
        ) from ex

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=auth.access_token,
    )

    await accounting_session.start()

    morphology = await run_async(
        lambda: client.get_entity(entity_id=model.morphology_id, entity_type=CellMorphology)
    )

    emodel = await run_async(
        lambda: client.get_entity(entity_id=model.emodel_id, entity_type=EModel)
    )
    species = await run_async(
        lambda: client.get_entity(entity_id=model.species_id, entity_type=Species)  # type: ignore
    )
    strain = (
        await run_async(
            lambda: client.get_entity(entity_id=model.strain_id, entity_type=Strain)  # type: ignore
        )
        if model.strain_id
        else None
    )

    brain_region = await run_async(
        lambda: client.get_entity(
            entity_id=model.brain_region_id,
            entity_type=BrainRegion,  # type: ignore
        )
    )

    initial_memodel = await run_async(
        lambda: client.register_entity(
            MEModel(
                brain_region=brain_region,
                description=model.description,
                emodel=emodel,
                morphology=morphology,
                name=model.name,
                species=species,
                strain=strain,
                validation_status=ValidationStatus.created,
            )
        )
    )

    agent = client.get_entity(entity_id=initial_memodel.created_by.id, entity_type=Person)
    role = client.search_entity(entity_type=Role, limit=1, query={"name": "creator role"}).one()
    contribution = Contribution(
        agent=agent,
        role=role,
        entity=initial_memodel,
    )
    contribution = client.register_entity(contribution)

    for etype in emodel.etypes or []:
        await run_async(
            lambda: client.register_entity(
                ETypeClassification(
                    etype_class_id=etype.id,  # type: ignore
                    entity_id=initial_memodel.id,  # type: ignore
                    authorized_public=True,
                )
            )
        )

    for mtype in morphology.mtypes or []:
        await run_async(
            lambda: client.register_entity(
                MTypeClassification(
                    mtype_class_id=mtype.id,  # type: ignore
                    entity_id=initial_memodel.id,  # type: ignore
                    authorized_public=True,
                )
            )
        )

    memodel = await run_async(
        lambda: client.get_entity(
            entity_id=initial_memodel.id,  # type: ignore
            entity_type=MEModel,
        )
    )

    await accounting_session.finish()

    calibration_job, _calibration_stream = await dispatch(
        job_queue,
        JobFn.RUN_SINGLE_NEURON_CALIBRATION,
        job_args=(memodel.id,),
        job_kwargs={
            "project_context": project_context,
            "access_token": auth.access_token,
        },
    )

    validation_job, _validation_stream = await dispatch(
        job_queue,
        JobFn.RUN_SINGLE_NEURON_VALIDATION,
        depends_on=[calibration_job],
        job_args=(memodel.id,),
        job_kwargs={
            "project_context": project_context,
            "access_token": auth.access_token,
        },
    )

    return ApiResponse[MEModel](message="Single neuron model created successfully", data=memodel)
