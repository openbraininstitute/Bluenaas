import math


def get_simulations_by_recoding_name(simulations: list) -> dict[str, list]:
    record_location_to_simulation_result: dict[str, list] = {}

    # Iterate over simulation result for each current/frequency
    for trace in simulations:
        # For a given current/frequency, gather data for different recording locations
        for recording_name in trace:
            if recording_name not in record_location_to_simulation_result:
                record_location_to_simulation_result[recording_name] = []

            record_location_to_simulation_result[recording_name].append(
                {
                    "label": trace[recording_name]["label"],
                    "amplitude": trace[recording_name]["amplitude"],
                    "frequency": trace[recording_name]["frequency"],
                    "recording": trace[recording_name]["recording_name"],
                    "varying_key": trace[recording_name]["varying_key"],
                    "type": "scatter",
                    "t": trace[recording_name]["time"],
                    "v": trace[recording_name]["voltage"],
                }
            )

    return record_location_to_simulation_result


def get_num_mpi_procs(num_cells: int) -> int:
    # Clamp between 1 and 4
    return min(max(math.floor(num_cells / 2), 1), 4)
