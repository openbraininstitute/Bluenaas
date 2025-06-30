from typing import Any
from app.infrastructure.redis import Stream
from app.domains.job import JobStatus, JobStatusMessage, JobDataMessage


class JobStream(Stream):
    def send_status(self, job_status: JobStatus, extra: str | None = None):
        status_message = JobStatusMessage(status=job_status, extra=extra)
        self.send(status_message.model_dump_json())

    def send_data(self, data: Any, data_type: str | None = None):
        data_message = JobDataMessage(data=data, data_type=data_type)
        self.send(data_message.model_dump_json())
