'''Handler.'''
from .simulation import (get_sec_info, get_ui_data, set_injection_location, set_model, set_token,
                         start_simulation, stop_simulation)

function_mapping = {
    'set_model': set_model,
    'start_simulation': start_simulation,
    'get_sec_info': get_sec_info,
    'set_injection_location': set_injection_location,
    'stop_simulation': stop_simulation,
    'get_ui_data': get_ui_data,
}

SIZE = 3000  # elements per chunk


def message_handler(msg):
    '''Handle message.'''
    if 'token' in msg:
        set_token(msg['token'])
        return {'message': 'Token set'}

    if 'cmd' not in msg:
        return {'message': 'Service up'}

    command_name = msg['cmd']
    data = msg['data']

    if command_name not in function_mapping:
        raise Exception('Unknown command: ' + command_name)

    result = function_mapping[command_name](data)

    if result is None:
        raise Exception('Empty result')

    return {
        'cmd': f"{command_name}_done",
        'data': result
    }


def divide_sim_chunks(cmd, stimulus_name, voltages, times):
    '''Divide simulation result in chunks.'''
    # Transform
    # 'cmd': '...', 'stimulus_name': 'IV', 'v': [-75,-74,0,10], 't': [1,2,3,4]
    # TO
    # [
    #    { 'cmd': '...', 'data': {'name': 'IV', 'offset': 0, 'v': [-75,-74], 't': [1,2]} },
    #    { 'cmd': '...', 'data': {'name': 'IV', 'offset': 1, 'v': [0,10], 't': [3,4]} },
    # ]

    chunks = []
    offset = 0
    for i in range(0, len(times), SIZE):
        chunk_data = {
            'name': stimulus_name,
            'offset': offset,
            'v': list(voltages[i:i + SIZE]),
            't': list(times[i:i + SIZE]),
        }
        chunks.append({'cmd': cmd, 'data': chunk_data})
        offset += 1
    return chunks
