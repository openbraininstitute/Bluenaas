'''Cell module.'''
import os
import re
import sys
from pathlib import Path

from blue_naas.settings import L
from blue_naas.util import (NeuronOutput, compile_mechanisms, get_sec_name, get_sections,
                            locate_model, set_sec_dendrogram)

# for the simulation time interval not more than voltage samples from all segments
MAX_SAMPLES = 300

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
        self._neuron_output = None
        self._nrn = None
        self._init_params = {}
        self.template = None
        self.delta_t = None
        self._recording_position = 0.5  # 0.5 middle of the section
        self._cell = None
        self._injection_location = None

    def _prepare_neuron_output_file(self):
        '''Redirect std output to fifo file.'''
        neuron_output_file_name = '/opt/blue-naas/tmp/neuron_output'

        Path(neuron_output_file_name).unlink(missing_ok=True)

        os.mkfifo(neuron_output_file_name)
        neuron_output_fd = os.open(neuron_output_file_name, os.O_RDONLY | os.O_NONBLOCK)
        self._neuron_output = NeuronOutput(neuron_output_fd)

        neuron_output_fd_w = os.open(neuron_output_file_name, os.O_WRONLY)
        # if you are running in docker with ipdb breakpoint -> comment the following 2 lines,
        # to be able to stop at the breakpoint
        os.dup2(neuron_output_fd_w, sys.stdout.fileno())
        os.dup2(neuron_output_fd_w, sys.stderr.fileno())

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

    def _load_by_model_id(self, model_id):
        # pylint: disable=too-many-statements
        os.chdir('/opt/blue-naas')  # in dev, if tornado reloads, cwd will not be root for nmc

        model_path = locate_model(model_id)
        compile_mechanisms(model_path)

        # make sure x86_64 is in current dir before importing neuron
        os.chdir(model_path)

        # importing here to avoid segmentation fault
        from bluecellulab import Cell  # pylint: disable=import-outside-toplevel
        from bluecellulab.circuit.circuit_access import \
            EmodelProperties  # pylint: disable=import-outside-toplevel
        from bluecellulab.importer import neuron  # pylint: disable=import-outside-toplevel

        # load the model
        sbo_template = model_path / 'cell.hoc'
        morph_path = model_path / "morphology"
        morph_file_name = os.listdir(morph_path)[0]
        morph_file = morph_path / morph_file_name
        L.debug('morph_file: %s', morph_file)

        self._prepare_neuron_output_file()

        if sbo_template.exists():
            try:
                with self._neuron_output:
                    emodel_properties = EmodelProperties(threshold_current=0,
                                                         holding_current=0,
                                                         AIS_scaler=1)
                    self._cell = Cell(sbo_template,
                                      morph_file,
                                      template_format="v6",
                                      emodel_properties=emodel_properties)
            except Exception as ex:
                raise Exception(self.get_neuron_output()) from ex

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

    def get_neuron_output(self):
        '''Get NEURON output.'''
        return str(self._neuron_output)

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
        with self._neuron_output:
            self._nrn.h.psection(sec=self._all_sec_array[self._all_sec_map[sec_name]['index']])
        return {'txt': self.get_neuron_output()}

    def get_injection_location(self):
        '''Get injection location, return the name of the section where injection is attached.'''
        return get_sec_name(self._template_name, self._injection_location)

    def set_injection_location(self, sec_name):
        '''Move injection_location to the middle of the section.'''
        self._injection_location = self._get_section_from_name(sec_name)

    def _send_voltage(self, send_message_fn):
        '''Send voltage trace message.'''
        voltages = [self._nrn.h.t]
        for sec in self._all_sec_array:
            for _, seg in enumerate(sec):
                voltages.append(seg.v)

        send_message_fn('sim_voltage', voltages)

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

    def _add_recordings(self, params):
        self._all_sec_array = []
        for recording_point in params['recordFrom']:
            section = self._get_section_from_name(recording_point)
            self._cell.add_voltage_recording(section, self._recording_position)
            self._all_sec_array.append(section)

    def _add_iclamp(self, params):
        from bluecellulab.cell.injector import \
            Hyperpolarizing  # pylint: disable=import-outside-toplevel

        hyperpolarizing = Hyperpolarizing("single-cell", delay=0, duration=params['tstop'])
        self._cell.hypamp = params['hypamp']
        self._cell.add_replay_hypamp(hyperpolarizing)
        self._cell.add_step(start_time=params['delay'],
                            stop_time=params['dur'] + params['delay'],
                            level=params['amp'],
                            section=self._injection_location)

    def _get_callback_step(self, send_message_fn):
        def send_voltage():
            voltages = [self._nrn.h.t]
            for section in self._all_sec_array:
                # get segments without 0 and 1
                for seg in list(section.allseg())[1:-1]:
                    voltages.append(seg.v)
            send_message_fn('sim_voltage', voltages)

        def callback():
            send_voltage()
            # schedule next step
            self._nrn.h.cvode.event(self._nrn.h.t + self.delta_t, callback)

        return callback

    def _run_simulation(self, sim, params):
        if params['dt'] is None:
            sim.run(params['tstop'], cvode=False, celsius=params['celsius'], v_init=params['vinit'])
        else:
            sim.run(params['tstop'], cvode=True, celsius=params['celsius'], v_init=params['vinit'],
                    dt=params['dt'])

    def _get_simulation_results(self, params):
        time = self._cell.get_time()
        headers = ['time']
        results = [time]
        for recording_point in params['recordFrom']:
            headers.append(recording_point)
            section = self._get_section_from_name(recording_point)
            voltage = self._cell.get_voltage_recording(section, self._recording_position)
            results.append(voltage)

        # TODO: improve this
        # [('time', 'soma[0]_0'), (0.0, -73.0), (0.1, -70.0), (0.2, -60.0), ...
        recordings = [tuple(headers)] + list(tuple(zip(*results)))
        return recordings

    def start_simulation(self, params, send_message_fn):
        '''Initialize the simulation and recordings.'''
        from bluecellulab import Simulation  # pylint: disable=import-outside-toplevel

        try:
            with self._neuron_output:
                L.debug('params %s', params)

                sim = Simulation()
                sim.add_cell(self._cell)

                self.delta_t = params['tstop'] / MAX_SAMPLES
                L.debug('delta_t: %s', self.delta_t)

                self._add_recordings(params)

                # TODO: add more stimulus protocols
                self._add_iclamp(params)

                callback_fn = self._get_callback_step(send_message_fn)
                # https://github.com/neuronsimulator/nrn/blob/master/docs/guide/finitialize_handler.rst
                simulation_initilizer_fn = self._nrn.h.FInitializeHandler
                # TODO: fix if the value is not assigned, the function is not called.
                _ = simulation_initilizer_fn(1, callback_fn)  # pylint: disable=unused-variable

                self._run_simulation(sim, params)
                recordings = self._get_simulation_results(params)
                send_message_fn('sim_done', recordings)

        except Exception:  # pylint: disable=broad-except
            send_message_fn('error', {'msg': 'Start-Simulation error',
                                      'raw': self.get_neuron_output()})

    def stop_simulation(self):
        '''Stop simulation.'''
        L.debug('stop simulation')
        self._nrn.h.stoprun = 1


class HocCell(BaseCell):
    '''Cell model with hoc.'''

    def __init__(self, model_id):
        super().__init__(model_id)

        self._load_by_model_id(model_id)

        L.debug('Loading model output: %s', self.get_neuron_output())
