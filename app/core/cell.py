"""Cell module."""

# pylint: disable=import-outside-toplevel
import os
import re
from uuid import UUID
from loguru import logger
from app.constants import SINGLE_NEURON_HOC_DIR, SINGLE_NEURON_MORPHOLOGY_DIR
from app.infrastructure.storage import get_single_neuron_location
from app.utils.util import (
    compile_mechanisms,
    get_sec_name,
    get_sections,
    set_sec_dendrogram,
)


class BaseCell:
    """Neuron model."""

    def __init__(self, model_id: UUID):
        self._model_id = model_id
        self._template_name = None
        self._all_sec_array = []
        self._all_sec_map = {}
        self._dendrogram = {}
        self._synapses = {}
        self._nrn = None
        self._init_params = {}
        self.template = None
        self.delta_t = None
        self._recording_position = 0.5  # 0.5 middle of the section
        self._cell = None

    def _topology_children(self, sec, topology):
        children = topology["children"]
        level = topology["level"]
        for child_sec in sec.children():
            child_topology = {
                "id": get_sec_name(self._template_name, child_sec),
                "children": [],
                "level": level + 1,
            }
            children.append(child_topology)
            self._topology_children(child_sec, child_topology)
        return topology

    def _load_by_model_uuid(self, model_uuid, threshold_current, holding_current):
        # pylint: disable=too-many-statements
        model_path = get_single_neuron_location(model_uuid)

        compile_mechanisms(model_path)

        # make sure x86_64 is in current dir before importing neuron
        os.chdir(model_path)

        # importing here to avoid segmentation fault
        from bluecellulab import Cell
        from bluecellulab.circuit.circuit_access import EmodelProperties
        from bluecellulab.importer import neuron

        # load the model
        hoc_dir_path = model_path / SINGLE_NEURON_HOC_DIR
        hoc_path = next(hoc_dir_path.iterdir())
        logger.debug(f"hoc_file: {hoc_path}")

        morphology_dir_path = model_path / SINGLE_NEURON_MORPHOLOGY_DIR
        morphology_path = next(morphology_dir_path.iterdir())
        logger.debug(f"morph_file: {morphology_path}")

        try:
            emodel_properties = EmodelProperties(
                threshold_current,
                holding_current,
                AIS_scaler=1,
            )
            logger.debug(f"emodel_properties {emodel_properties}")
            self._cell = Cell(
                hoc_path,
                morphology_path,
                template_format="v6",
                emodel_properties=emodel_properties,
            )
        except Exception as ex:
            logger.error(f"Error creating Cell object: {ex}")
            raise Exception(ex) from ex

        neuron.h.define_shape()

        self._all_sec_array, self._all_sec_map = get_sections(self._cell)
        self._nrn = neuron
        self._template_name = self._cell.hocname
        set_sec_dendrogram(self._template_name, self._cell.soma, self._dendrogram)

    def get_init_params(self):
        """Get initial parameters."""
        return getattr(self, "_init_params", None)

    def get_cell_morph(self):
        """Get neuron morphology."""
        return self._all_sec_map

    def get_dendrogram(self):
        """Get dendrogram."""
        return self._dendrogram

    def get_synapses(self):
        """Get synapses."""
        return self._synapses

    def get_topology(self):
        """Get topology."""
        if not self._cell:
            raise ValueError("Model not loaded")
        topology_root = {
            "id": get_sec_name(self._template_name, self._cell.soma),
            "children": [],
            "level": 0,
        }
        return [self._topology_children(self._cell.soma, topology_root)]

    def get_sec_info(self, sec_name):
        """Get section info from NEURON."""
        if not self._nrn:
            raise ValueError("Model not loadedF")
        logger.debug(sec_name)
        self._nrn.h.psection(sec=self._all_sec_array[self._all_sec_map[sec_name]["index"]])
        # TODO: rework this
        return {"txt": ""}

    def _get_section_from_name(self, name):
        if not self._cell:
            raise ValueError("Model not loaded")
        (section_name, section_id) = re.findall(r"(\w+)\[(\d)\]", name)[0]
        if section_name.startswith("soma"):
            return self._cell.soma
        elif section_name.startswith("apic"):
            return self._cell.apical[int(section_id)]
        elif section_name.startswith("dend"):
            return self._cell.basal[int(section_id)]
        elif section_name.startswith("axon"):
            return self._cell.axonal[int(section_id)]
        else:
            raise Exception("section name not found")

    def _get_simulation_results(self, responses):
        recordings = []
        for stimulus, recording in responses.items():
            recordings.append(
                {
                    "t": list(recording.time),
                    "v": list(recording.voltage),
                    "name": stimulus,
                }
            )

        return recordings

    def _get_stimulus_name(self, protocol_name):
        from bluecellulab.analysis.inject_sequence import StimulusName

        protocol_mapping = {
            "ap_waveform": StimulusName.AP_WAVEFORM,
            "idrest": StimulusName.IDREST,
            "iv": StimulusName.IV,
            "fire_pattern": StimulusName.FIRE_PATTERN,
        }

        if protocol_name not in protocol_mapping:
            raise Exception("Protocol does not have StimulusName assigned")

        return protocol_mapping[protocol_name]

    def start_simulation(
        self,
        expanded_configs: list,  # List of ExpandedSimulationConfig
        realtime: bool = False,
        job_stream=None,
    ):
        """Unified simulation method that handles all simulation types."""
        from app.core.stimulation import apply_simulation

        try:
            apply_simulation(
                realtime=realtime,
                cell=self._cell,
                expanded_configs=expanded_configs,
                job_stream=job_stream,
            )
        except Exception as e:
            logger.exception(f"Apply Unified Simulation error: {e}")
            raise Exception(f"Apply Unified Simulation error: {e}") from e


class HocCell(BaseCell):
    """Cell model with hoc."""

    def __init__(
        self,
        model_id: UUID,
        *,
        threshold_current: float = 0,
        holding_current: float = 0,
    ):
        super().__init__(model_id)

        logger.info(f"hoccell init: {model_id, threshold_current, holding_current}")
        self._load_by_model_uuid(model_id, threshold_current, holding_current)
