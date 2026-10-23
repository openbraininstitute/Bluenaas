from uuid import UUID

from pydantic import BaseModel


class TaskConfigRunRequest(BaseModel):
    config_id: UUID


class TaskConfigRunLaunch(BaseModel):
    job_id: UUID
    execution_id: UUID
