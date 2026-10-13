from uuid import UUID

from pydantic import BaseModel


class IonChannelBuildRequest(BaseModel):
    config_id: UUID


class IonChannelBuildLaunch(BaseModel):
    job_id: UUID
    execution_id: UUID
