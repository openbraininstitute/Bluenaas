from typing import List
from uuid import UUID as UUID4

from pydantic import BaseModel, Field


class RunBatchRequest(BaseModel):
    simulation_ids: List[UUID4]


class SimulationParams(BaseModel):
    num_cells: int = Field(description="The number of cells to simulate")
    tstop: float = Field(description="The simulation time in milliseconds")
