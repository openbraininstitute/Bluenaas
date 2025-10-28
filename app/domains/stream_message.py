from enum import StrEnum, auto
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

from app.domains.job import JobStatus
from app.utils.datetime import iso_now


class MessageBase(BaseModel):
    timestamp: str = Field(default_factory=lambda: iso_now())


class MessageType(StrEnum):
    """Message type."""

    status = auto()
    data = auto()
    keep_alive = auto()


class KeepAliveMessage(MessageBase):
    message_type: Literal[MessageType.keep_alive] = Field(
        default=MessageType.keep_alive, alias="type"
    )


class DataMessage(MessageBase):
    message_type: Literal[MessageType.data] = Field(default=MessageType.data, alias="type")
    ctx: dict[str, Any] | None = None
    data_type: str | None = None
    data: Any


class StatusMessage(MessageBase):
    message_type: Literal[MessageType.status] = Field(default=MessageType.status, alias="type")
    ctx: dict[str, Any] | None = None
    status: JobStatus
    extra: str | None = None


Message = Annotated[
    Union[StatusMessage, DataMessage, KeepAliveMessage], Field(discriminator="message_type")
]

MessageAdapter = TypeAdapter(Message)
