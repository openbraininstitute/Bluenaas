SIZE = 3000  # elements per chunk


def chunky_simulation(stimulus_name, voltages, times):
    """Divide simulation result in chunks."""
    # Transform
    # 'cmd': '...', 'stimulus_name': 'IV', 'v': [-75,-74,0,10], 't': [1,2,3,4]
    # TO
    # [
    #    { {'name': 'IV', 'offset': 0, 'v': [-75,-74], 't': [1,2]} },
    #    { {'name': 'IV', 'offset': 1, 'v': [0,10], 't': [3,4]} },
    # ]

    chunks = []
    offset = 0
    for i in range(0, len(times), SIZE):
        chunk_data = {
            "name": stimulus_name.replace("StimulusName.", ""),
            "offset": offset,
            "v": list(voltages[i : i + SIZE]),
            "t": list(times[i : i + SIZE]),
        }
        chunks.append(chunk_data)
        offset += 1
    return chunks
