from typing import List
from uuid import UUID as UUID4

from pydantic import BaseModel, Field

from app.domains.circuit.circuit import CircuitOrigin


class RunBatchRequest(BaseModel):
    simulation_ids: List[UUID4]
    circuit_origin: CircuitOrigin = CircuitOrigin.CIRCUIT


class SimulationParams(BaseModel):
    num_cells: int = Field(description="The number of cells to simulate")
    tstop: float = Field(description="The simulation time in milliseconds")
