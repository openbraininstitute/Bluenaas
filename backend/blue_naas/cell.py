'''Cell module.'''
# pylint: disable=import-outside-toplevel
import os
import re

from blue_naas.settings import L
from blue_naas.util import (compile_mechanisms, get_sec_name, get_sections, locate_model,
                            set_sec_dendrogram)

TIME = 'time'


class BaseCell():
    '''Neuron model.'''

    def __init__(self, model_id):
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
        self._injection_location = None

    def _topology_children(self, sec, topology):
        children = topology['children']
        level = topology['level']
        for child_sec in sec.children():
            child_topology = {'id': get_sec_name(self._template_name, child_sec),
                              'children': [],
                              'level': level + 1}
            children.append(child_topology)
            self._topology_children(child_sec, child_topology)
        return topology

    def _load_by_model_id(self, model_id, threshold_current, holding_current):
        # pylint: disable=too-many-statements
        os.chdir('/opt/blue-naas')

        model_path = locate_model(model_id)
        compile_mechanisms(model_path)

        # make sure x86_64 is in current dir before importing neuron
        os.chdir(model_path)

        # importing here to avoid segmentation fault
        from bluecellulab import Cell
        from bluecellulab.circuit.circuit_access import EmodelProperties
        from bluecellulab.importer import neuron

        # load the model
        sbo_template = model_path / 'cell.hoc'
        morph_path = model_path / "morphology"
        morph_file_name = os.listdir(morph_path)[0]
        morph_file = morph_path / morph_file_name
        L.debug('morph_file: %s', morph_file)

        if sbo_template.exists():
            try:
                emodel_properties = EmodelProperties(threshold_current,
                                                     holding_current,
                                                     AIS_scaler=1)
                self._cell = Cell(sbo_template,
                                  morph_file,
                                  template_format="v6",
                                  emodel_properties=emodel_properties)
            except Exception as ex:
                L.error("Error creating Cell object: %s", ex)
                raise Exception(ex) from ex

            self._all_sec_array, self._all_sec_map = get_sections(self._cell)
            self._nrn = neuron
            self._template_name = self._cell.hocname
            self._injection_location = self._cell.soma
            set_sec_dendrogram(self._template_name, self._cell.soma, self._dendrogram)
        else:
            raise Exception("HOC file not found! Expecting '/checkpoints/cell.hoc' for "
                            "BSP model format or `/template.hoc`!")

    def get_init_params(self):
        '''Get initial parameters.'''
        return getattr(self, '_init_params', None)

    @property
    def model_id(self):
        '''Get model id.'''
        return self._model_id

    def get_cell_morph(self):
        '''Get neuron morphology.'''
        return self._all_sec_map

    def get_dendrogram(self):
        '''Get dendrogram.'''
        return self._dendrogram

    def get_synapses(self):
        '''Get synapses.'''
        return self._synapses

    def get_topology(self):
        '''Get topology.'''
        topology_root = {'id': get_sec_name(self._template_name, self._cell.soma),
                         'children': [],
                         'level': 0}
        return [self._topology_children(self._cell.soma, topology_root)]

    def get_sec_info(self, sec_name):
        '''Get section info from NEURON.'''
        L.debug(sec_name)
        self._nrn.h.psection(sec=self._all_sec_array[self._all_sec_map[sec_name]['index']])
        # TODO: rework this
        return {'txt': ''}

    def get_injection_location(self):
        '''Get injection location, return the name of the section where injection is attached.'''
        return get_sec_name(self._template_name, self._injection_location)

    def set_injection_location(self, sec_name):
        '''Move injection_location to the middle of the section.'''
        self._injection_location = self._get_section_from_name(sec_name)

    def _get_section_from_name(self, name):
        (section_name, section_id) = re.findall(r'(\w+)\[(\d)\]', name)[0]
        if section_name.startswith('soma'):
            return self._cell.soma
        elif section_name.startswith('apic'):
            return self._cell.apical[int(section_id)]
        elif section_name.startswith('dend'):
            return self._cell.basal[int(section_id)]
        elif section_name.startswith('axon'):
            return self._cell.axonal[int(section_id)]
        else:
            raise Exception('section name not found')

    def _get_simulation_results(self, responses):
        recordings = []
        for stimulus, recording in responses.items():
            recordings.append({
                't': list(recording.time),
                'v': list(recording.voltage),
                'name': stimulus,
            })

        return recordings

    def _get_stimulus_name(self, protocol_name):
        from bluecellulab.analysis.inject_sequence import StimulusName
        protocol_mapping = {
            'ap_waveform': StimulusName.AP_WAVEFORM,
            'idrest': StimulusName.IDREST,
            'iv': StimulusName.IV,
            'fire_pattern': StimulusName.FIRE_PATTERN,
        }

        if protocol_name not in protocol_mapping:
            raise Exception('Protocol does not have StimulusName assigned')

        return protocol_mapping[protocol_name]

    def start_simulation(self, params):
        '''Initialize the simulation and recordings.'''
        from bluecellulab.analysis.inject_sequence import apply_multiple_step_stimuli

        try:
            L.debug('params %s', params)

            stimulus_name = self._get_stimulus_name(params['stimulus']['stimulusProtocol'])

            amplitudes = params['stimulus']['amplitudes']
            responses = apply_multiple_step_stimuli(
                self._cell,
                stimulus_name,
                amplitudes,
                section_name=params['injectTo']
            )

            recordings = self._get_simulation_results(responses)
            return recordings

        except Exception as e:  # pylint: disable=broad-except
            L.error('Start-Simulation error: %s', e)
            raise Exception(f'Start-Simulation error: {e}') from e

    def stop_simulation(self):
        '''Stop simulation.'''
        L.debug('stop simulation')
        self._nrn.h.stoprun = 1


class HocCell(BaseCell):
    '''Cell model with hoc.'''

    def __init__(self, model_id, threshold_current=0, holding_current=0):
        super().__init__(model_id)

        self._load_by_model_id(model_id, threshold_current, holding_current)
