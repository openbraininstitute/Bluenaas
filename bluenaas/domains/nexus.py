from datetime import datetime
from typing import Annotated, Any, List
from pydantic import BaseModel, Field


class NexusBaseResource(BaseModel):
    context: Annotated[str | List[Any], Field(alias="@context")] = []
    id: Annotated[str, Field(alias="@id")]
    type: Annotated[str | List[str] | None, Field(alias="@type")] = None
    createdAt: Annotated[datetime, Field(alias="_createdAt")]
    createdBy: Annotated[str, Field(alias="_createdBy")]
    deprecated: Annotated[bool, Field(alias="_deprecated")]
    self: Annotated[str, Field(alias="_self")]
    rev: Annotated[int, Field(alias="_rev")]
