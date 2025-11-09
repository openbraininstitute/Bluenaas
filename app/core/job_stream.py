from typing import Any
from app.domains.stream_message import DataMessage, StatusMessage
from app.infrastructure.redis import Stream
from app.domains.job import JobStatus


class JobStream(Stream):
    ctx: dict[str, Any] | None

    def __init__(
        self, stream_key: str, *, ctx: dict[str, Any] | None = None, ttl: int | None = None
    ):
        super().__init__(stream_key, ttl=ttl)
        self.ctx = ctx

    def set_ctx(self, ctx: dict[str, Any] | None):
        self.ctx = ctx

    def send_status(self, job_status: JobStatus, extra: str | None = None):
        status_message = StatusMessage(status=job_status, extra=extra, ctx=self.ctx)
        self.send(status_message.model_dump(mode="json"))

    def send_status_once(self, job_status: JobStatus, extra: str | None = None):
        self.send_status(job_status, extra)
        self.close()

    def send_data(self, data: Any, *, data_type: str | None = None):
        data_message = DataMessage(data=data, data_type=data_type, ctx=self.ctx)
        self.send(data_message.model_dump(mode="json"))

    def send_data_once(self, data: Any, *, data_type: str | None = None):
        self.send_data(data, data_type=data_type)
        self.close()
