from enum import StrEnum, auto
from typing import Literal, Union
from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    """Job status."""

    created = auto()
    pending = auto()
    running = auto()
    done = auto()
    error = auto()


class JobMessageType(StrEnum):
    """Message type."""

    status = auto()
    data = auto()


class JobStatusMessage(BaseModel):
    message_type: Literal[JobMessageType.status] = Field(
        default=JobMessageType.status,
        alias="type",
    )
    status: JobStatus
    extra: str | None = None


class JobDataMessage(BaseModel):
    message_type: Literal[JobMessageType.data] = Field(
        default=JobMessageType.data, alias="type"
    )
    data_type: str | None
    data: str


JobMessage = Union[JobStatusMessage, JobDataMessage]
