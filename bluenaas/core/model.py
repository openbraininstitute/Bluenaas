"""Model"""

from enum import Enum
import os
from typing import NamedTuple
from loguru import logger as L
import pandas  # type: ignore
import requests
from sympy import symbols, parse_expr  # type: ignore
import json
from bluenaas.core.cell import HocCell
from bluenaas.domains.morphology import (
    LocationData,
    SectionSynapses,
    SectionTarget,
    SynapseConfig,
    SynapsePlacementBody,
    SynapsePlacementResponse,
    SynapsePosition,
    SynapseSeries,
    SynapsesPlacementConfig,
)
from bluenaas.domains.simulation import SynapseSimulationConfig
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

SynapseType = Enum("SynapseType", "GABAAB AMPANMDA GLUSYNAPSE")


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

    def _should_place_synapse_on_section(
        self, section_name: str, config: SynapseConfig
    ) -> bool:
        if config.target is not None:
            return section_name.startswith(config.target.value)

        supported_sections = SectionTarget.list()
        target = list(filter(lambda s: section_name.startswith(s), supported_sections))
        return len(target) > 0

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

        # seed(params.seed, version=2)

        for section_key, section_value in sections.items():
            try:
                section_info = LocationData.model_validate(
                    section_value,
                )
            except Exception:
                continue

            if not self._should_place_synapse_on_section(section_key, params.config):
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

    def _get_synapse_series_for_section(
        self,
        section_info: LocationData,
        segment_count: int,
        placement_config: SynapseConfig,
        simulation_config: SynapseSimulationConfig,
    ):
        from bluecellulab.circuit.synapse_properties import SynapseProperty  # type: ignore

        target_segment = randint(0, segment_count - 1)
        position = random()
        # 1. get the seg_x for target segment
        start = section_info.neuron_segments_offset[target_segment]
        # 2. get the seg_x for target segment +1
        end = section_info.neuron_segments_offset[target_segment + 1]
        diff = end - start
        offset = position * diff
        # 3. if the offset is bind to the section id not segment id then
        # offset = (position * diff) + start

        syn_description = pandas.Series(
            {
                SynapseProperty.PRE_GID: 1,
                SynapseProperty.AXONAL_DELAY: 1.0,
                SynapseProperty.G_SYNX: 0.566172,
                SynapseProperty.TYPE: placement_config.type,
                SynapseProperty.U_SYN: 0.505514,
                SynapseProperty.D_SYN: 684.279663,
                SynapseProperty.F_SYN: 1.937531,
                SynapseProperty.DTC: 2.983491,
                # SynapseProperty.NRRP: 2,
                # "source_population_name": "hippocampus_projections",
                # "source_popid": 2126,
                # "target_popid": 378,
                # SynapseProperty.AFFERENT_SECTION_POS: 0.365956,
                SynapseProperty.POST_SECTION_ID: section_info.neuron_section_id,
                SynapseProperty.POST_SEGMENT_ID: target_segment,
                SynapseProperty.POST_SEGMENT_OFFSET: offset,
            }
        )
        return syn_description

    def get_synapse_series(
        self,
        global_seed: int,
        placement_config: SynapseConfig,
        simulation_config: SynapseSimulationConfig,
        offset: int,
    ) -> list[SynapseSeries]:
        synapse_series: list[SynapseSeries] = []
        _, section_map = get_sections(self.CELL._cell)
        sections = section_map

        seed(placement_config.seed, version=2)
        # seed(global_seed, version=2)

        for section_key, section_value in sections.items():
            try:
                section_info = LocationData.model_validate(
                    section_value,
                )

            except Exception:
                continue

            if not self._should_place_synapse_on_section(section_key, placement_config):
                continue

            synapse_count = self._calc_synapse_count(
                placement_config,
                section_info.distance_from_soma,
                section_info.sec_length,
            )

            segment_count = section_info.nseg
            for i in range(synapse_count):
                synapse_id = int(f"{len(synapse_series)}{offset}")
                synapse_series.append(
                    {
                        "id": synapse_id,
                        "series": self._get_synapse_series_for_section(
                            section_info=section_info,
                            segment_count=segment_count,
                            placement_config=placement_config,
                            simulation_config=simulation_config,
                        ),
                    }
                )

        return synapse_series


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


class Synaptome_Details(NamedTuple):
    base_model_self: str
    synaptome_placement_config: SynapsesPlacementConfig


def fetch_synaptome_model_details(synaptome_self: str, bearer_token: str):
    """For a given synamptome model, returns the following:
    1. The base me-model or e-model
    2. The configuration for all synapse groups added to the given synaptome model
    """
    try:
        resource_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": bearer_token,
        }
        file_headers = {
            "Authorization": bearer_token,
        }

        synaptome_resource_req = requests.get(
            synaptome_self, headers=resource_headers, verify=False
        )
        synaptome_resource_req.raise_for_status()
        synaptome_model_resource = synaptome_resource_req.json()

        distributions = synaptome_model_resource.get("distribution")
        distribution = (
            distributions[0] if isinstance(distributions, list) else distributions
        )

        distribution_req = requests.get(
            distribution["contentUrl"], headers=file_headers
        )
        distribution_req.raise_for_status()
        synapses_file = json.loads(
            distribution_req.text
        )  # TODO: Add type for distribution file content
        synapse_placement_config = [
            SynapseConfig.model_validate(synapse)
            for synapse in synapses_file["synapses"]
        ]

        return Synaptome_Details(
            base_model_self=synapses_file["meModelSelf"],
            synaptome_placement_config=SynapsesPlacementConfig(
                seed=synaptome_model_resource["seed"], config=synapse_placement_config
            ),
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        L.error(f"There was an error while loading synaptome model {e}")

        raise Exception(e)
