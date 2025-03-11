from typing import List, Literal, Optional, TypedDict
from pydantic import BaseModel, field_validator
import sympy as sp  # type: ignore
import pandas  # type: ignore
from enum import Enum

from bluenaas.domains.simulation import CurrentInjectionConfig, SynapseSimulationConfig


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
    neuron_segments_offset: List[float]
    neuron_section_id: int
    segment_distance_from_soma: list[float]


class SectionTarget(Enum):
    apical = "apic"
    basal = "basal"
    dendrite = "dend"
    soma = "soma"
    axom = "axon"

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))


class ExclusionRule(BaseModel):
    distance_soma_gte: float | None = None
    distance_soma_lte: float | None = None


class SynapseConfig(BaseModel):
    id: str
    name: str
    target: list[SectionTarget]  # Supports multiple target types
    type: int
    distribution: Literal["exponential", "linear", "formula"]
    formula: Optional[str | None] = None
    synapse_count: int | None = None
    seed: int
    exclusion_rules: list[ExclusionRule] | None = None

    @field_validator("synapse_count")
    @classmethod
    def validate_synapse_count(cls, value, info):
        target = info.data.get("target")

        # If the target is the soma, synapse_count is REQUIRED
        if target == SectionTarget.soma and value is None:
            raise ValueError("synapse_count must be provided if target is soma")

        # If synapse_count is given, validate its value
        if value is not None:
            if not isinstance(value, int):
                raise ValueError("synapse_count must be an integer")
            if value <= 0:
                raise ValueError("synapse_count must be greater than 0")
            if value > 1_000 and target == SectionTarget.soma:  # Limit soma synapses
                raise ValueError("synapse_count for soma cannot exceed 1,000")
            if value > 20_000:  # Global max limit
                raise ValueError("synapse_count cannot exceed 20,000 for a single set")

        return value

    @field_validator("formula", mode="before")
    @classmethod
    def validate_formula_depends_on_distribution(cls, value, info):
        if "distribution" in info.data and info.data.get("distribution") == "formula":
            if not value or not isinstance(value, str):
                raise ValueError(
                    'Formula must be a valid string when distribution is "formula".'
                )

            try:
                expr = sp.sympify(value)
                # Check if all free symbols are 'x' or 'X'
                allowed_symbols = {"x", "X"}
                free_symbols = {str(symbol) for symbol in expr.free_symbols}
                if not free_symbols.issubset(allowed_symbols):
                    raise ValueError("Formula can only contain the variable x or X.")

            except (sp.SympifyError, TypeError) as ex:
                raise ValueError(
                    f"Formula must be a valid mathematical expression. {ex}"
                )

        return value


# TODO: Remove
class SynapsePlacementBody(BaseModel):
    seed: int
    config: SynapseConfig


class SynapsesPlacementConfig(BaseModel):
    seed: int
    config: list[SynapseConfig]


class SynapsePosition(BaseModel):
    segment_id: int
    coordinates: list[float]
    position: float


class SectionSynapses(BaseModel):
    section_id: str
    synapses: list[SynapsePosition]


class SynapsePlacementResponse(BaseModel):
    synapses: list[SectionSynapses]


SynapseSeries = TypedDict(
    "SynapseSeries",
    {
        "id": int,
        "series": pandas.Series,
        "directCurrentConfig": CurrentInjectionConfig,
        "synapseSimulationConfig": SynapseSimulationConfig,
        "frequencies_to_apply": list[float],
    },
)
