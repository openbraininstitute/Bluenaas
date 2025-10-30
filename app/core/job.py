from pydantic import BaseModel
from typing import Any


class JobInfo(BaseModel):
    id: str
    status: str | None = None
    output: Any | None = None
    created_at: str | None = None
    enqueued_at: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    queue_position: int | None = None
    error: str | None = None
