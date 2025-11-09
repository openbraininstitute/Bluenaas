from datetime import UTC, datetime
from typing import Any

from entitysdk import Client, ProjectContext
from entitysdk.models import IonChannelModel, IonChannelModelingConfig, IonChannelModelingExecution
from entitysdk.types import IonChannelModelingExecutionStatus
from loguru import logger

from app.config.settings import settings
from app.core.ion_channel.build import Build
from app.domains.ion_channel.ion_channel import (
    BuildInputStreamData,
    BuildOutputStreamData,
    StreamDataType,
)
from app.domains.job import JobStatus
from app.utils.rq_job import get_current_job_stream


def run_ion_channel_build(
    config: Any,
    *,
    access_token: str,
    project_context: ProjectContext,
) -> None:
    job_stream = get_current_job_stream()

    client = Client(
        api_url=str(settings.ENTITYCORE_URI),
        project_context=project_context,
        token_manager=access_token,
    )

    build = Build(config, client=client)

    job_stream.send_status(JobStatus.running, "Initializing ion channel build")
    campaign = build.init()

    logger.debug(f"Created ion channel build campaign {campaign}")

    config = client.search_entity(
        entity_type=IonChannelModelingConfig,
        query={"ion_channel_modeling_campaign_id": campaign.id},
    ).first()

    logger.debug(f"Created ion channel build config {config}")

    execution = client.register_entity(
        IonChannelModelingExecution(
            used=[config],
            start_time=datetime.now(UTC),
            status=IonChannelModelingExecutionStatus.pending,
        )
    )
    assert execution.id

    logger.debug(f"Created ion channel build execution {execution}")

    job_stream.send_data(
        BuildInputStreamData(
            config=config,
            campaign=campaign,
            execution=execution,
        ),
        data_type=StreamDataType.build_input,
    )

    job_stream.send_status(JobStatus.running, "Running ion channel build")

    try:
        model_ids = build.run()
    except Exception as e:
        logger.error(f"Ion channel build failed: {e}")
        client.update_entity(
            entity_id=execution.id,
            entity_type=IonChannelModelingExecution,
            attrs_or_entity={
                "end_time": datetime.now(UTC),
                "status": IonChannelModelingExecutionStatus.error,
            },
        )
        raise
    finally:
        build.cleanup()

    model_id = model_ids[0]
    assert model_id

    ion_channel_model = client.get_entity(model_id, entity_type=IonChannelModel)

    client.update_entity(
        entity_id=execution.id,
        entity_type=IonChannelModelingExecution,
        attrs_or_entity={
            "end_time": datetime.now(UTC),
            "status": IonChannelModelingExecutionStatus.done,
            "generated": [ion_channel_model],
        },
    )

    job_stream.send_data(
        BuildOutputStreamData(model=ion_channel_model), data_type=StreamDataType.build_output
    )
