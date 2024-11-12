"""Model"""

from enum import Enum
from typing import NamedTuple
from bluenaas.core.exceptions import SimulationError, SynapseGenerationError
from filelock import FileLock
from loguru import logger
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
    SynapseMetadata,
    SynapsesPlacementConfig,
)
from bluenaas.domains.nexus import NexusBaseResource
from bluenaas.domains.simulation import (
    SynaptomeSimulationConfig,
    CurrentInjectionConfig,
)
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
    def __init__(self, *, model_self: str, hyamp: float | None, token: str):
        self.model_self: str = model_self
        self.token: str = token
        self.CELL: HocCell = None
        self.threshold_current: int = 1
        self.holding_current: float | None = hyamp
        self.resource: NexusBaseResource = None
        self.model_uuid = None

    def build_model(self):
        """Prepare model."""
        if self.model_self is None:
            raise Exception("Missing model _self url")

        nexus_helper = Nexus({"token": self.token, "model_self_url": self.model_self})
        [holding_current, threshold_current] = nexus_helper.get_currents()
        self.threshold_current = threshold_current

        model_uuid = nexus_helper.get_model_uuid()
        self.model_uuid = model_uuid
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
    ) -> int:
        if config.target == SectionTarget.soma:
            assert config.soma_synapse_count is not None
            return config.soma_synapse_count

        x_symbol, X_symbol = symbols("x X")
        expression = parse_expr(f"{config.formula} * {sec_length}")
        formula_value = expression.subs({x_symbol: distance, X_symbol: distance})
        fractional_part, integer_part = modf(formula_value)

        if fractional_part < random():
            return floor(formula_value)

        return floor(formula_value) + 1

    def _should_place_synapse_on_section_based_on_target(
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
        seed(params.config.seed, version=2)

        for section_key, section_value in sections.items():
            try:
                section_info = LocationData.model_validate(
                    section_value,
                )
            except Exception:
                continue

            if not self._should_place_synapse_on_section_based_on_target(
                section_key, params.config
            ):
                continue

            segment_indices = get_segments_satisfying_all_exclusion_rules(
                params.config.exclusion_rules,
                section_info.segment_distance_from_soma,
                section_info,
            )

            if segment_indices is None:
                continue

            synapse_count = self._calc_synapse_count(
                config, section_info.distance_from_soma, section_info.sec_length
            )
            total_synapses = len(synapses) + (synapse_count or 0)
            if total_synapses > MAXIMUM_ALLOWED_SYNAPSES:
                raise SynapseGenerationError(
                    f"Cannot generate more than {MAXIMUM_ALLOWED_SYNAPSES} synapses per synapse set. Please revise your formula."
                )
            synapse = SectionSynapses(
                section_id=section_key,
                synapses=[
                    self._generate_synapse(
                        section_info=section_info,
                        seg_indices_to_include=segment_indices,
                    )
                    for i in range(synapse_count)
                ],
            )
            synapses.append(synapse)

        return SynapsePlacementResponse(
            synapses=synapses,
        )

    def get_synapse_series(
        self,
        synapse_placement_config: SynapseConfig,
        synapse_simulation_config: SynaptomeSimulationConfig,
        offset: int,
        frequencies_to_apply: list[float],
        current_injection_config: CurrentInjectionConfig,  # TODO: Remove this unused parameter.
    ) -> list[SynapseMetadata]:
        synapse_series: list[SynapseMetadata] = []
        _, section_map = get_sections(self.CELL._cell)
        sections = section_map

        seed(synapse_placement_config.seed, version=2)

        for section_key, section_value in sections.items():
            try:
                section_info = LocationData.model_validate(
                    section_value,
                )

            except Exception:
                continue

            if not self._should_place_synapse_on_section_based_on_target(
                section_key, synapse_placement_config
            ):
                continue

            segment_indices = get_segments_satisfying_all_exclusion_rules(
                synapse_placement_config.exclusion_rules,
                section_info.segment_distance_from_soma,
                section_info,
            )

            if segment_indices is None:
                continue

            synapse_count = self._calc_synapse_count(
                synapse_placement_config,
                section_info.distance_from_soma,
                section_info.sec_length,
            )

            total_synapses = len(synapse_series) + (synapse_count or 0)
            if total_synapses > MAXIMUM_ALLOWED_SYNAPSES:
                raise SimulationError(
                    f"Simulation cannot have more than {MAXIMUM_ALLOWED_SYNAPSES} synapses per synapse set."
                )

            for _ in range(synapse_count):
                synapse_id = int(f"{len(synapse_series)}{offset}")
                synapse_series.append(
                    SynapseMetadata(
                        id=synapse_id,
                        section_info=section_info,
                        segment_indices=segment_indices,
                        simulation_config=synapse_simulation_config,
                        frequencies_to_apply=frequencies_to_apply,
                        type=synapse_placement_config.type,
                    )
                )

        return synapse_series


def model_factory(
    model_self: str,
    hyamp: float | None,
    bearer_token: str,
):
    model = Model(
        model_self=model_self,
        hyamp=hyamp,
        token=bearer_token,
    )

    model.build_model()

    return model


class SynaptomeDetails(NamedTuple):
    base_model_self: str
    synaptome_placement_config: SynapsesPlacementConfig


def fetch_synaptome_model_details(synaptome_self: str, bearer_token: str):
    """For a given synaptome model, returns the following:
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
            synaptome_self,
            headers=resource_headers,
            verify=False,
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
