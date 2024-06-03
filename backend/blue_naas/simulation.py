'''Simulation.'''
from .cell import HocCell
from .Nexus import Nexus
from .settings import L
from .StimulusFactoryPlot import StimulusFactoryPlot

CELL = None
TOKEN = None
THRESHOLD_CURRENT = 1


def set_token(token):
    '''Set token to fetch model in the future.'''
    global TOKEN  # pylint: disable=global-statement
    L.info('Setting token...')
    TOKEN = token


def set_model(values):
    '''Set model.'''
    model_id = values.get('model_id', 'sbo-model')

    if model_id is None:
        raise Exception('Missing model id')

    nexus_helper = Nexus({
        'token': TOKEN,
        'emodel_id': model_id
    })
    nexus_helper.download_model()
    [holding_current, threshold_current] = nexus_helper.get_currents()

    global THRESHOLD_CURRENT  # pylint: disable=global-statement
    THRESHOLD_CURRENT = threshold_current

    global CELL  # pylint: disable=global-statement
    if CELL is None:
        L.debug('loading model %s', model_id)
        L.debug('threshold_current %s', threshold_current)
        L.debug('holding_current %s', holding_current)
        CELL = HocCell(model_id, threshold_current, holding_current)

    elif CELL.model_id != model_id:
        L.debug('Trying to load different model, '
                'current: %s, new: %s, discarding the pod', CELL.model_id, model_id)
        raise Exception('Different model')
    return True


def get_sec_info(values):
    '''Get section info.'''
    return CELL.get_sec_info(values)


def set_injection_location(values):
    '''Set injection location.'''
    CELL.set_injection_location(values)
    return CELL.get_injection_location()


def stop_simulation(_):
    '''Stop simulation.'''
    CELL.stop_simulation()
    return True


def start_simulation(values):
    '''Start simulation.'''
    L.info('Starting simulation...')
    result = CELL.start_simulation(values)
    L.info('Simulation ended!')
    return result


def get_ui_data(_):
    '''Get UI data.'''
    results = {'morphology': CELL.get_cell_morph()}
    return results


def get_stimuli_plot_data(values):
    '''Get stimuli plot data.'''
    # as the model need to be initialized first, the THRESHOLD_CURRENT is set already
    stimulus_factory_plot = StimulusFactoryPlot(values, THRESHOLD_CURRENT)
    result_data = stimulus_factory_plot.apply_stim()
    return result_data
