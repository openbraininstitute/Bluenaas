from typing import List, Literal, Optional

from loguru import logger
from pydantic import BaseModel, field_validator
import sympy as sp



class LocationData(BaseModel):
    index: int
    nseg: int
    xstart: List[float]
    xend: List[float]
    xcenter: List[float]
    xdirection: List[float]
    ystart: List[float]
    yend: List[float]
    ycenter: List[float]
    ydirection: List[float]
    zstart: List[float]
    zend: List[float]
    zcenter: List[float]
    zdirection: List[float]
    segx: List[float]
    diam: List[float]
    length: List[float]
    distance: List[float]
    distance_from_soma: float
    sec_length: float


class SynapseConfig(BaseModel):
    id: str
    name: str
    target: str
    type: int
    distribution: Literal["exponential", "linear", "formula"]
    formula: Optional[str | None] = None  # Check that this is a valid string if `distribution` is "formula"

    @field_validator('formula', mode='before')
    @classmethod
    def validate_formula_depends_on_distribution(cls, value, info):
        logger.debug(f'if {info}')
        logger.debug(f'value {value}')
        if 'distribution' in info.data and info.data.get('distribution') == 'formula':
            if not value or not isinstance(value, str):
                raise ValueError('Formula must be a valid string when distribution is "formula".')
            
            try:
                expr = sp.sympify(value)
                # Check if all free symbols are 'x' or 'X'
                allowed_symbols = {'x', 'X'}
                free_symbols = {str(symbol) for symbol in expr.free_symbols}
                if not free_symbols.issubset(allowed_symbols):
                    raise ValueError('Formula can only contain the variable x or X.')
            
            except (sp.SympifyError, TypeError) as ex:
                raise ValueError(f'Formula must be a valid mathematical expression. {ex}')
            
        return value


class SynapsePlacementBody(BaseModel):
    seed: int
    config: SynapseConfig


class SynapsePosition(BaseModel):
    segment_id: int
    coordinates: list[float]
    position: float


class SectionSynapses(BaseModel):
    section_id: str
    synapses: list[SynapsePosition]


class SynapsePlacementResponse(BaseModel):
    synapses: list[SectionSynapses]
