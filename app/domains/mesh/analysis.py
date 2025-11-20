from pydantic import BaseModel, Field


class AnalysisResult(BaseModel):
    approximate_volume: int = Field(description="Approximate volume of EM cell mesh")
