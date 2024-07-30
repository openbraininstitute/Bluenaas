"""Model"""

import os
from loguru import logger as L
from sympy import symbols, parse_expr  # type: ignore
from bluenaas.core.cell import HocCell
from bluenaas.domains.morphology import (
    LocationData,
    SectionSynapses,
    SynapseConfig,
    SynapsePlacementBody,
    SynapsePlacementResponse,
    SynapsePosition,
)
from bluenaas.external.nexus.nexus import Nexus
from bluenaas.utils.util import (
    get_sections,
    locate_model,
    perpendicular_vector,
    point_between_vectors,
    set_vector_length,
)
from math import ceil
from random import seed, random, randint
import numpy as np

SUPPORTED_SYNAPSES_TYPES = ["apic", "basal", "dend"]

# TODO: The keys of dict should be same as SynapseConfig.distribution
distribution_type_to_formula = {"linear": "x", "exponential": "exp(x)"}


class Model:
    def __init__(self, *, model_id: str, token: str):
        self.model_id: str = model_id
        self.token: str = token
        self.CELL: HocCell = None
        self.THRESHOLD_CURRENT: int = 1
    
    def build_model(self):
        """Prepare model."""
        if self.model_id is None:
            raise Exception("Missing model _self url")

        nexus_helper = Nexus({"token": self.token, "model_self_url": self.model_id})
        [holding_current, threshold_current] = nexus_helper.get_currents()
        self.THRESHOLD_CURRENT = threshold_current

        model_uuid = nexus_helper.get_model_uuid()

        path_exists = os.path.exists("/opt/blue-naas")
        model_path = locate_model(model_uuid)

        if path_exists is True and model_path is not None:
            self.CELL = HocCell(model_uuid, threshold_current, holding_current)
            return True

        nexus_helper.download_model()
        L.debug(
            f"loading model {model_uuid}",
        )
        L.debug(f"threshold_current {threshold_current}")
        L.debug(f"holding_current {holding_current}")
        self.CELL = HocCell(model_uuid, threshold_current, holding_current)

    def _generate_synapse(self, section_info: LocationData, segment_count):
        target_segment = randint(0, segment_count - 1)
        # 2. Find a random position on that segment (using random_point_between_vectors from chatgpt)
        position = random()
        vStart = np.array(
            [
                section_info.xstart[target_segment],
                section_info.ystart[target_segment],
                section_info.zstart[target_segment],
            ]
        )
        vEnd = np.array(
            [
                section_info.xend[target_segment],
                section_info.yend[target_segment],
                section_info.zend[target_segment],
            ]
        )
        vNew = point_between_vectors(vStart, vEnd, position)

        # 3. Subtract total sengment vector from the V(start to new)
        new_vector = vEnd - vNew

        # 4. Find a vector perpendicular to above
        perp_vector = perpendicular_vector(new_vector)

        # 5. Create new (perpendicular) vector of length = segment radius
        adjusted_perp_vector = set_vector_length(
            perp_vector, section_info.diam[target_segment] / 2
        )

        # 6. Project above vector to segment (Not sure how. ChatGPT answer looks different from one we discussed yesterday)
        # target_vector = project_vector(vNew, length_vector)
        target_vector = np.add(vNew, adjusted_perp_vector)

        return SynapsePosition(
            segment_id=target_segment,
            coordinates=target_vector.tolist(),
            position=position,
        )

    def _calc_synapse_count(
        self, config: SynapseConfig, distance: float, sec_length: float
    ):
        x_symbol, X_symbol = symbols("x X")
        formula = (
            distribution_type_to_formula.get(config.distribution)
            if config.distribution in distribution_type_to_formula is not None
            else config.formula
        )
        expression = parse_expr(f"{formula} * {sec_length}")
        synapse_count = ceil(expression.subs({x_symbol: distance, X_symbol: distance}))
        return synapse_count

    def add_synapses(self, params: SynapsePlacementBody) -> SynapsePlacementResponse:
        _, section_map = get_sections(self.CELL._cell)
        config = params.config
        synapses: list[SectionSynapses] = []
        sections = section_map
        # select the target
        # {
        #     key: value
        #     for key, value in section_map.items()
        #     if key.startswith(params.config.target) and not key.startswith("soma")
        # }
        seed(params.config.seed, version=2)

        seed(params.seed, version=2)
        
        for section_key, section_value in sections.items():
            try:
                section_info = LocationData.model_validate(
                    section_value,
                )
            except Exception:
                continue

            section_target = [
                section_key
                for t in SUPPORTED_SYNAPSES_TYPES
                if section_key.startswith(t)
            ]
            if not len(section_target):
                continue

            synapse_count = self._calc_synapse_count(
                config, section_info.distance_from_soma, section_info.sec_length
            )

            
            segment_count = section_info.nseg

            synapse = SectionSynapses(
                section_id=section_key,
                synapses=[
                    self._generate_synapse(
                        section_info=section_info, segment_count=segment_count
                    )
                    for i in range(synapse_count)
                ],
            )
            synapses.append(synapse)

        return SynapsePlacementResponse(
            synapses=synapses,
        )


def model_factory(
    model_id: str,
    bearer_token: str,
):
    model = Model(
        model_id=model_id,
        token=bearer_token,
    )

    model.build_model()

    return model
