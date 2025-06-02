"""Model"""

import json
from enum import Enum
from math import floor, modf
from random import randint, random, seed
from typing import List, NamedTuple
from uuid import UUID

import numpy as np
import pandas  # type: ignore
import requests
from filelock import FileLock
from loguru import logger
from sympy import parse_expr, symbols  # type: ignore

from bluenaas.core.cell import HocCell
from bluenaas.core.exceptions import (
    SimulationError,
    SingleNeuronSynaptomeConfigurationError,
    SynapseGenerationError,
)
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
from bluenaas.external.entitycore.schemas import AssetLabel, EntityRoute
from bluenaas.external.entitycore.service import (
    EntityCore,
    ProjectContext,
    download_asset,
    fetch_one,
)
from bluenaas.external.nexus.nexus import Nexus
from bluenaas.utils.util import (
    get_model_path,
    get_sections,
    get_segments_satisfying_all_exclusion_rules,
    perpendicular_vector,
    point_between_vectors,
    set_vector_length,
)

SUPPORTED_SYNAPSES_TYPES = ["apic", "basal", "dend"]

SynapseType = Enum("SynapseType", "GABAAB AMPANMDA GLUSYNAPSE")
defaultIdBaseUrl = "https://bbp.epfl.ch/data/bbp/mmb-point-neuron-framework-model"
MAXIMUM_ALLOWED_SYNAPSES = 20_000


class Model:
    def __init__(
        self,
        *,
        model_id: str,
        hyamp: float | None,
        token: str,
        entitycore: bool = False,
        project_context: ProjectContext | None = None,
    ):
        self.model_id = model_id
        self.token: str = token
        self.CELL: HocCell | None = None
        self.threshold_current: float = 1
        self.holding_current: float | None = hyamp
        self.resource: NexusBaseResource | None = None
        self.entitycore = entitycore
        self.project_context = project_context

    def build_model(self):
        """Prepare model."""
        if self.model_id is None:
            raise Exception("Missing model _self url")

        helper = None

        if not self.entitycore:
            helper = Nexus({"token": self.token, "model_self_url": self.model_id})

        elif self.entitycore and self.project_context:
            helper = EntityCore(
                token=self.token,
                model_id=self.model_id,
                project_context=self.project_context,
            )

        if not helper:
            raise ValueError("Missing project context")

        [holding_current, threshold_current] = helper.get_currents()
        self.threshold_current = threshold_current

        model_uuid = helper.get_model_uuid()

        model_path = get_model_path(model_uuid)
        done_file = model_path / "done"

        if not done_file.exists():
            lock = FileLock(model_path / "dir.lock")
            with lock.acquire(timeout=2 * 60):
                helper.download_model()
                self.CELL = HocCell(
                    model_uuid=model_uuid,
                    threshold_current=threshold_current,
                    holding_current=self.holding_current
                    if self.holding_current is not None
                    else holding_current,
                )
                done_file.touch()
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
        if config.target == SectionTarget.soma:
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
        if not self.CELL:
            raise SimulationError("Model not built yet. Please build the model first.")

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
                    for i in range(synapse_count or 0)
                ],
            )
            synapses.append(synapse)

        return SynapsePlacementResponse(
            synapses=synapses,
        )

    def _get_synapse_series_for_section(
        self,
        section_info: LocationData,
        seg_indices_to_include: List[int],
        placement_config: SynapseConfig,
        simulation_config: SynapseSimulationConfig,
    ):
        from bluecellulab.circuit.synapse_properties import (
            SynapseProperty,  # type: ignore
        )

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
        if not self.CELL:
            raise SimulationError("Model not built yet. Please build the model first.")

        synapse_series: list[SynapseSeries] = []
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

            for _ in range(synapse_count or 0):
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
                        "directCurrentConfig": None,
                    }
                )

        return synapse_series


def model_factory(
    model_id: str,
    hyamp: float | None,
    bearer_token: str,
    entitycore: bool = False,
    project_context: ProjectContext | None = None,
):
    model = Model(
        model_id=model_id,
        hyamp=hyamp,
        token=bearer_token,
        entitycore=entitycore,
        project_context=project_context,
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


file_name = "single_neuron_synaptome_config"


def fetch_synaptome_entitycore_model_details(
    model_id: UUID, project_context: ProjectContext, bearer_token: str
):
    """For a given synaptome model, returns the following:
    1. The base me-model or e-model
    2. The configuration for all synapse groups added to the given synaptome model
    """
    from bluenaas.external.entitycore.schemas import SingleNeuronSynaptomeRead

    try:
        single_neuron_synaptome = fetch_one(
            id=model_id,
            project_context=project_context,
            response_class=SingleNeuronSynaptomeRead,
            route=EntityRoute.single_neuron_synaptome,
            token=bearer_token,
        )

        if not single_neuron_synaptome.assets:
            raise SimulationError(
                f"No synaptome configuration file found for {model_id}"
            )

        asset = next(
            (
                item
                for item in single_neuron_synaptome.assets
                if item.label == AssetLabel.single_neuron_synaptome_config
                or any(
                    item.path.startswith(prefix)
                    for prefix in ["single_neuron_synaptome_config", "synaptome_config"]
                    if item.path
                )
            ),
            None,
        )

        if asset:
            config = download_asset(
                entity_id=model_id,
                entity_route=EntityRoute.single_neuron_synaptome,
                id=asset.id,
                project_context=project_context,
                token=bearer_token,
            )
            synapses_file = json.loads(config)
            synapse_placement_config = [
                SynapseConfig.model_validate(synapse)
                for synapse in synapses_file["synapses"]
            ]

            return SynaptomeDetails(
                base_model_self=str(single_neuron_synaptome.me_model.id),
                synaptome_placement_config=SynapsesPlacementConfig(
                    seed=single_neuron_synaptome.seed,
                    config=synapse_placement_config,
                ),
            )
        raise FileNotFoundError
    except FileNotFoundError as ex:
        raise SingleNeuronSynaptomeConfigurationError(
            "Synapse distribution configuration file not found"
        ) from ex
    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.error(
            f"There was an error while loading single neuron synaptome model {e}"
        )

        raise Exception(e)
