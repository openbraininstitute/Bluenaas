from enum import StrEnum, auto
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, Field, TypeAdapter

from app.utils.datetime import iso_now


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


class JobMessageBase(BaseModel):
    timestamp: str = Field(default_factory=lambda: iso_now())


class JobStatusMessage(JobMessageBase):
    message_type: Literal[JobMessageType.status] = Field(
        default=JobMessageType.status, alias="type"
    )
    status: JobStatus
    extra: str | None = None


class JobDataMessage(JobMessageBase):
    message_type: Literal[JobMessageType.data] = Field(default=JobMessageType.data, alias="type")
    data_type: str | None
    data: Any


JobMessage = Annotated[Union[JobStatusMessage, JobDataMessage], Field(discriminator="message_type")]

JobMessageAdapter = TypeAdapter(JobMessage)
