from pydantic import BaseModel


class SynaptomeFormulaResponse(BaseModel):
    valid: bool
    type: str | None = None
    message: str | None = None
