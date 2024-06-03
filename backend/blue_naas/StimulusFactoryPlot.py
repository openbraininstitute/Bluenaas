'''Stimulus Factory Plot module.'''
import numpy as np


class StimulusFactoryPlot:
    '''Generates stimuli preview plot data.'''

    def __init__(self, params, threshold_current):
        from bluecellulab.stimulus.factory import \
            StimulusFactory  # pylint: disable=import-outside-toplevel
        self.dt = 0.1
        self.factory = StimulusFactory(dt=self.dt)

        stimulus_param = params['stimulus']
        self.protocol_name = stimulus_param['stimulusProtocol']
        self.threshold_current = threshold_current
        self.amplitudes = stimulus_param['amplitudes']

        if not isinstance(self.amplitudes, list):
            raise ValueError("Amplitudes must be a list")

    @property
    def stim_fn(self):
        '''Exposes the stimulus function to call based on stimulus chosen.'''
        protocol_mapping = {
            'iv': self.factory.iv,
            'fire_pattern': self.factory.fire_pattern,
            'ap_waveform': self.factory.ap_waveform,
            'idrest': self.factory.idrest,
        }
        return protocol_mapping[self.protocol_name]

    def _get_stim_name(self, amplitude):
        return f'{self.protocol_name.upper()}_{amplitude}'

    def _get_time_by_index(self, times):
        def get_time_for(index):
            return int(times[index])
        return get_time_for

    def _get_plot_data(self, response):
        # get the x and y axis to plot the breaking points
        # even though we have 4 points (initial, up, down, final), to make the plot looks square _∏_
        # we need to add 2 more points just before up and right after down breaking points

        unique_elements = np.unique(response.current)
        if unique_elements.size != 2:
            raise Exception('current has not _∏_ shape')

        down_value = unique_elements[0]
        up_value = unique_elements[1]
        down_indices = np.where(response.current == down_value)[0]
        up_indices = np.where(response.current == up_value)[0]

        get_time_for = self._get_time_by_index(response.time)
        return {
            'x': [
                get_time_for(down_indices[0]),
                get_time_for(up_indices[0] - 1),
                get_time_for(up_indices[0]),
                get_time_for(up_indices[-1]),
                get_time_for(up_indices[-1] + 1),
                get_time_for(down_indices[-1])
            ],
            'y': [down_value, down_value, up_value, up_value, down_value, down_value]
        }

    def apply_stim(self):
        '''Generate plot data based on  stimuli parameters.'''
        final_data = []
        for amplitude in self.amplitudes:
            label = self._get_stim_name(amplitude)
            response = self.stim_fn(
                self.threshold_current,
                threshold_percentage=amplitude
            )
            plot_data = self._get_plot_data(response)
            plot_data.update({'name': label})
            final_data.append(plot_data)

        return final_data
