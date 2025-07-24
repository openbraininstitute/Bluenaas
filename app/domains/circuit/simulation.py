from pydantic import BaseModel, Field


class SimulationParams(BaseModel):
    num_cells: int = Field(description="The number of cells to simulate")
    tstop: float = Field(description="The simulation time in milliseconds")
