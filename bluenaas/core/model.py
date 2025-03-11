"""Model"""

from enum import Enum
from typing import List, NamedTuple
from bluenaas.core.exceptions import SimulationError, SynapseGenerationError
from filelock import FileLock
from loguru import logger
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
from bluenaas.domains.nexus import NexusBaseResource
from bluenaas.domains.simulation import SynapseSimulationConfig
from bluenaas.external.nexus.nexus import Nexus
from bluenaas.utils.util import (
    get_sections,
    get_segments_satisfying_all_exclusion_rules,
    get_model_path,
    perpendicular_vector,
    point_between_vectors,
    set_vector_length,
)
from math import floor, modf
from random import seed, random, randint
import numpy as np

SUPPORTED_SYNAPSES_TYPES = ["apic", "basal", "dend"]

SynapseType = Enum("SynapseType", "GABAAB AMPANMDA GLUSYNAPSE")
defaultIdBaseUrl = "https://bbp.epfl.ch/data/bbp/mmb-point-neuron-framework-model"
MAXIMUM_ALLOWED_SYNAPSES = 20_000


class Model:
    def __init__(self, *, model_id: str, hyamp: float | None, token: str):
        self.model_id: str = model_id
        self.token: str = token
        self.CELL: HocCell = None
        self.threshold_current: int = 1
        self.holding_current: float | None = hyamp
        self.resource: NexusBaseResource = None

    def build_model(self):
        """Prepare model."""
        if self.model_id is None:
            raise Exception("Missing model _self url")

        nexus_helper = Nexus({"token": self.token, "model_self_url": self.model_id})
        [holding_current, threshold_current] = nexus_helper.get_currents()
        self.threshold_current = threshold_current

        model_uuid = nexus_helper.get_model_uuid()

        model_path = get_model_path(model_uuid)
        lock = FileLock(f"{model_path/'dir.lock'}")

        with lock.acquire(timeout=2 * 60):
            done_file = model_path / "done"
            if not done_file.exists():
                nexus_helper.download_model()
                done_file.touch()
                self.CELL = HocCell(
                    model_uuid=model_uuid,
                    threshold_current=threshold_current,
                    holding_current=self.holding_current
                    if self.holding_current is not None
                    else holding_current,
                )
            else:
                self.CELL = HocCell(
                    model_uuid=model_uuid,
                    threshold_current=threshold_current,
                    holding_current=self.holding_current
                    if self.holding_current is not None
                    else holding_current,
                )

    def _generate_synapse(
        self, section_info: LocationData, seg_indices_to_include: list[int]
    ):
        random_index = randint(0, len(seg_indices_to_include) - 1)

        target_segment = seg_indices_to_include[random_index]

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
    ) -> int | None:
        x_symbol, X_symbol = symbols("x X")
        expression = parse_expr(f"{config.formula} * {sec_length}")
        formula_value = expression.subs({x_symbol: distance, X_symbol: distance})
        fractional_part, integer_part = modf(formula_value)

        if fractional_part < random():
            return floor(formula_value)

        return floor(formula_value) + 1

    def _should_place_synapse_on_section_based_on_target(self, section_name: str, config: SynapseConfig) -> bool:
        """Checks if a section matches any of the selected target types."""
        supported_sections = SectionTarget.list()

        if isinstance(config.target, list):
            valid_targets = [target for target in config.target if target.value in supported_sections]
            return any(section_name.startswith(target.value) for target in valid_targets)

        return section_name.startswith(config.target.value) and config.target.value in supported_sections

    def _get_valid_sections(self, config: SynapseConfig) -> list[tuple]:
        """Returns a list of sections that pass validation and exclusion rules."""
        valid_sections = []
        _, section_map = get_sections(self.CELL._cell)

        for section_key, section_value in section_map.items():
            try:
                section_info = LocationData.model_validate(section_value)
            except Exception:
                continue  # Skip invalid sections

            if not self._should_place_synapse_on_section_based_on_target(section_key, config):
                continue  # Skip sections that do not match the target

            segment_indices = get_segments_satisfying_all_exclusion_rules(
                config.exclusion_rules,
                section_info.segment_distance_from_soma,
                section_info,
            )

            if not segment_indices:
                continue  # Skip sections that do not pass exclusion rules

            valid_sections.append((section_key, section_info, segment_indices))

        return valid_sections


    def _distribute_total_synapses(self, total_synapses: int, valid_sections: list[tuple]) -> dict:
        """Assigns `total_synapses` randomly across `valid_sections` while ensuring correct placement."""
        num_valid_sections = len(valid_sections)
        if num_valid_sections == 0 or total_synapses <= 0:
            return {}

        section_keys = [section_key for section_key, _, _ in valid_sections]  # Extract section keys
        synapse_counts = {section_key: 0 for section_key in section_keys}  # Initialize counts

        # Assign each synapse randomly while ensuring total matches
        for _ in range(total_synapses):
            random_section = random.choice(section_keys)  # Pick a section randomly
            synapse_counts[random_section] += 1  # Assign a synapse to that section

        return synapse_counts  # {section_key: assigned_synapse_count}

    def add_synapses(self, params: SynapsePlacementBody) -> SynapsePlacementResponse:
        """Assigns synapses randomly across sections if total_synapses is set."""

        seed(params.config.seed, version=2)

        # Get valid sections
        valid_sections = self._get_valid_sections(params.config)

        if not valid_sections:
            return SynapsePlacementResponse(synapses=[])

        # Compute synapse counts based on total_synapses or density
        total_synapses = params.config.synapse_count
        synapse_distribution = None

        if total_synapses and total_synapses > 0:
            # Distribute synapses randomly across ALL selected target sections
            synapse_distribution = self._distribute_total_synapses(total_synapses, valid_sections)
        else:
            synapse_distribution = None  # Formula-based synapse calculation will be used

        # Assign synapses per section
        synapses = []
        for section_key, section_info, segment_indices in valid_sections:
            if synapse_distribution is None:
                # Use formula-based synapse density
                synapse_count_per_section = self._calc_synapse_count(
                    params.config, section_info.distance_from_soma, section_info.sec_length
                )
            else:
                # Lookup precomputed synapse count (default to 0 if not assigned)
                synapse_count_per_section = synapse_distribution.get(section_key, 0)

            # Ensure we do not exceed the max allowed synapses
            if len(synapses) + synapse_count_per_section > MAXIMUM_ALLOWED_SYNAPSES:
                raise SynapseGenerationError(
                    f"Cannot generate more than {MAXIMUM_ALLOWED_SYNAPSES} synapses per synapse set. Please revise your formula."
                )

            # Generate synapse objects
            synapse = SectionSynapses(
                section_id=section_key,
                synapses=[
                    self._generate_synapse(
                        section_info=section_info,
                        seg_indices_to_include=segment_indices,
                    )
                    for _ in range(synapse_count_per_section)
                ],
            )
            synapses.append(synapse)

        return SynapsePlacementResponse(synapses=synapses)

    def _get_synapse_series_for_section(
        self,
        section_info: LocationData,
        seg_indices_to_include: List[int],
        placement_config: SynapseConfig,
        simulation_config: SynapseSimulationConfig,
    ):
        from bluecellulab.circuit.synapse_properties import SynapseProperty  # type: ignore

        random_index = randint(0, len(seg_indices_to_include) - 1)
        target_segment = seg_indices_to_include[random_index]

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
                SynapseProperty.G_SYNX: simulation_config.weight_scalar,
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
        synapse_placement_config: SynapseConfig,
        synapse_simulation_config: SynapseSimulationConfig,
        offset: int,
        frequencies_to_apply: list[float],
    ) -> list[SynapseSeries]:

        seed(synapse_placement_config.seed, version=2)

        # Get valid sections
        valid_sections = self._get_valid_sections(synapse_placement_config)

        if not valid_sections:
            return []

        # Compute synapse counts based on total_synapses or formula
        total_synapses = synapse_placement_config.synapse_count
        synapse_distribution = None

        if total_synapses and total_synapses > 0:
            # Distribute synapses randomly across ALL selected target sections
            synapse_distribution = self._distribute_total_synapses(total_synapses, valid_sections)
        else:
            synapse_distribution = None  # Formula-based synapse calculation will be used

        # Assign synapses per section
        synapse_series = []
        for section_key, section_info, segment_indices in valid_sections:
            if synapse_distribution is None:
                # Use formula-based synapse density
                synapse_count = self._calc_synapse_count(
                    synapse_placement_config,
                    section_info.distance_from_soma,
                    section_info.sec_length,
                )
            else:
                # Lookup precomputed synapse count using `section_key`
                synapse_count = synapse_distribution.get(section_key, 0)

            # Ensure we do not exceed the max allowed synapses
            if len(synapse_series) + synapse_count > MAXIMUM_ALLOWED_SYNAPSES:
                raise SimulationError(
                    f"Simulation cannot have more than {MAXIMUM_ALLOWED_SYNAPSES} synapses per synapse set."
                )

            # Generate synapse series entries
            for _ in range(synapse_count):
                synapse_id = int(f"{len(synapse_series)}{offset}")
                synapse_series.append(
                    {
                        "id": synapse_id,
                        "series": self._get_synapse_series_for_section(
                            section_info=section_info,
                            seg_indices_to_include=segment_indices,
                            placement_config=synapse_placement_config,
                            simulation_config=synapse_simulation_config,
                        ),
                        "synapseSimulationConfig": synapse_simulation_config,
                        "frequencies_to_apply": frequencies_to_apply,
                    }
                )

        return synapse_series


def model_factory(
    model_id: str,
    hyamp: float | None,
    bearer_token: str,
):
    model = Model(
        model_id=model_id,
        hyamp=hyamp,
        token=bearer_token,
    )

    model.build_model()

    return model


class SynaptomeDetails(NamedTuple):
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

        return SynaptomeDetails(
            base_model_self=synapses_file["meModelSelf"],
            synaptome_placement_config=SynapsesPlacementConfig(
                seed=synaptome_model_resource["seed"], config=synapse_placement_config
            ),
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.error(f"There was an error while loading synaptome model {e}")

        raise Exception(e)
