from enum import StrEnum, auto
from pydantic import BaseModel

from entitysdk.models import (
    IonChannelModelingConfig,
    IonChannelModelingExecution,
    IonChannelModel,
    IonChannelModelingCampaign,
)


class StreamDataType(StrEnum):
    build_input = auto()
    build_output = auto()


class BuildInputStreamData(BaseModel):
    campaign: IonChannelModelingCampaign
    config: IonChannelModelingConfig
    execution: IonChannelModelingExecution


class BuildOutputStreamData(BaseModel):
    model: IonChannelModel
