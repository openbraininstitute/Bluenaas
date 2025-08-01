"""
Usage:
    python run_bluecellulab_simulation.py --simulation_config <simulation_config> [--save-nwb]
"""

# TODO: To refactor and split into core logic and MPI entry python module

import argparse
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Union

import matplotlib
import numpy as np
from bluecellulab import CircuitSimulation
from bluecellulab.reports.manager import ReportManager
from loguru import logger
from neuron import h
from pynwb import NWBHDF5IO, H5DataIO, NWBFile
from pynwb.icephys import CurrentClampSeries, IntracellularElectrode

# Use non-interactive backend for matplotlib to avoid display issues
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def save_results_to_nwb(
    results: Dict[str, Any], execution_id: str, output_path: Union[str, Path]
):
    """Save simulation results to NWB format"""
    nwbfile = NWBFile(
        session_description="Small Microcircuit Simulation results",
        identifier=str(uuid.uuid4()),
        session_start_time=datetime.now(timezone.utc),
        experimenter="OBI User",
        lab="Virtual Lab",
        institution="OBI",
        experiment_description="Simulation results",
        session_id=execution_id,
        was_generated_by=["obi_small_scale_simulator_v1"],
    )

    # Add device and electrode
    device = nwbfile.create_device(
        name="SimulatedElectrode",
        description="Virtual electrode for simulation recording",
    )

    # Add voltage traces
    for cell_id, trace in results.items():
        electrode = IntracellularElectrode(
            name=f"electrode_{cell_id}",
            description=f"Simulated electrode for {cell_id}",
            device=device,
            location="soma",
            filtering="none",
        )
        nwbfile.add_icephys_electrode(electrode)

        # Compute time rate
        time_rate = 1 / (trace["time"][1] - trace["time"][0])

        voltage_data = (
            np.array(trace["voltage"], dtype=float) / 1000.0
        )  # Convert mV to V

        # Create current clamp series
        ics = CurrentClampSeries(
            name=cell_id,
            data=H5DataIO(data=voltage_data, compression="gzip"),
            electrode=electrode,
            rate=time_rate,
            gain=1.0,
            unit="volts",
            description=f"Voltage trace for {cell_id}",
        )
        nwbfile.add_acquisition(ics)

    # Save to file
    with NWBHDF5IO(str(output_path), "w") as io:
        io.write(nwbfile)

    logger.info(f"Saved results to {output_path}")


def plot_voltage_traces(
    results: Dict[str, Any], output_path: Union[str, Path], max_cols: int = 3
):
    """Plot voltage traces for all cells in a grid of subplots and save to file.

    Args:
        results: Dictionary containing simulation results for each cell
        output_path: Path where to save the plot (should include .png extension)
        max_cols: Maximum number of columns in the subplot grid
    """
    n_cells = len(results)
    if n_cells == 0:
        logger.warning("No voltage traces to plot")
        return

    # Calculate grid size
    n_cols = min(max_cols, n_cells)
    n_rows = (n_cells + n_cols - 1) // n_cols

    # Create figure with subplots
    fig, axes = plt.subplots(
        n_rows, n_cols, figsize=(15, 3 * n_rows), squeeze=False, constrained_layout=True
    )

    # Flatten axes for easier iteration
    axes = axes.ravel()

    # Plot each cell's voltage trace in its own subplot
    for idx, (cell_id, trace) in enumerate(results.items()):
        ax = axes[idx]
        time_ms = np.array(trace["time"])
        voltage_mv = np.array(trace["voltage"])

        ax.plot(time_ms, voltage_mv, linewidth=1)
        ax.set_title(f"Cell {cell_id}", fontsize=10)
        ax.grid(True, alpha=0.3)

        # Only label bottom row x-axes
        if idx >= (n_rows - 1) * n_cols:
            ax.set_xlabel("Time (ms)", fontsize=8)

        # Only label leftmost column y-axes
        if idx % n_cols == 0:
            ax.set_ylabel("mV", fontsize=8)

    # Turn off unused subplots
    for idx in range(n_cells, len(axes)):
        axes[idx].axis("off")

    # Add a main title
    fig.suptitle(f"Voltage Traces for {n_cells} Cells", fontsize=12)

    # Save the figure
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Saved voltage traces plot to {output_path}")


def _merge_dicts(list_of_dicts):
    merged: Dict[Any, Any] = {}
    for d in list_of_dicts:
        merged.update(d)
    return merged


def _merge_spikes(list_of_pop_dicts):
    out: Dict[str, Dict[int, list]] = defaultdict(dict)
    for pop_dict in list_of_pop_dicts:
        for pop, gid_map in pop_dict.items():
            out[pop].update(gid_map)
    return out


def get_instantiate_gids_params(
    simulation_config_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Determine instantiate_gids parameters from simulation config.

    This function gives parameters for sim.instantiate_gids() based on the
    simulation config. See the package BlueCellulab/bluecellulab/circuit_simulation.py
    for more details.

    Args:
        simulation_config_data: Loaded simulation configuration
    Returns:
        Dictionary of parameters for instantiate_gids
    """
    params = {
        # Core parameters - these are the main ones we need to set
        "add_stimuli": False,
        "add_synapses": False,
        "add_minis": False,
        "add_replay": False,
        "add_projections": False,
        "interconnect_cells": True,
        # These will be handled automatically by add_stimuli=True
        "add_noise_stimuli": False,
        "add_hyperpolarizing_stimuli": False,
        "add_relativelinear_stimuli": False,
        "add_pulse_stimuli": False,
        "add_shotnoise_stimuli": False,
        "add_ornstein_uhlenbeck_stimuli": False,
        "add_sinusoidal_stimuli": False,
        "add_linear_stimuli": False,
    }

    # Check for any inputs in the config
    if "inputs" in simulation_config_data and simulation_config_data["inputs"]:
        params["add_stimuli"] = True

        # Log any unsupported input types
        supported_types = {
            "noise",
            "hyperpolarizing",
            "relativelinear",
            "pulse",
            "sinusoidal",
            "linear",
            "shotnoise",
            "ornstein_uhlenbeck",
        }

        for input_def in simulation_config_data["inputs"].values():
            module = input_def.get("module", "").lower()
            if module not in supported_types:
                logger.warning(
                    f"Input type '{module}' may not be fully supported by instantiate_gids"
                )

    # Check for synapses and minis in conditions
    if "conditions" in simulation_config_data:
        conditions = simulation_config_data["conditions"]
        if "mechanisms" in conditions and conditions["mechanisms"]:
            params["add_synapses"] = True
            # Check if any mechanism has minis enabled
            for mech in conditions["mechanisms"].values():
                if mech.get("minis_single_vesicle", False):
                    params["add_minis"] = True
                    break

    # # Check for spike replay in inputs
    # if 'inputs' in simulation_config_data:
    #     for input_def in simulation_config_data['inputs'].values():
    #         if input_def.get('module') == 'synapse_replay':
    #             params['add_replay'] = True
    #             break

    # Enable projections by default if synapses are enabled

    # ! This was disabling local synapses, to be addressed in BCL
    # params["add_projections"] = params["add_synapses"]

    return params


def run_bluecellulab(
    simulation_config: Union[str, Path],
    execution_id: str,
    libnrnmech_path: str,
    save_nwb: bool = False,
) -> None:
    """Run a simulation using BlueCelluLab backend.

    Args:
        simulation_config: Path to the simulation configuration file
        save_nwb: Whether to save results in NWB format.
    """

    # Get MPI info using NEURON's ParallelContext
    h.nrn_load_dll(libnrnmech_path)
    h.nrnmpi_init()
    pc = h.ParallelContext()
    rank = int(pc.id())
    size = int(pc.nhost())

    if rank == 0:
        logger.info("Initializing BlueCelluLab simulation")

    # Load configuration using json
    with open(simulation_config) as f:
        simulation_config_data = json.load(f)

    # Get simulation parameters from config
    t_stop = simulation_config_data["run"]["tstop"]
    dt = simulation_config_data["run"]["dt"]
    v_init = simulation_config_data["conditions"]["v_init"]

    # Get the directory of the simulation config
    sim_config_base_dir = Path(simulation_config).parent
    logger.info(f"sim_config_base_dir: {sim_config_base_dir}")

    # Get manifest path
    OUTPUT_DIR = simulation_config_data.get("manifest", {}).get("$OUTPUT_DIR", "./")
    logger.info(f"OUTPUT_DIR: {OUTPUT_DIR}")

    # Get the node_set
    node_set_name = simulation_config_data.get("node_set", "All")

    node_sets_file = sim_config_base_dir / simulation_config_data["node_sets_file"]
    logger.info(f"node_sets_file: {node_sets_file}")

    with open(node_sets_file) as f:
        node_set_data = json.load(f)

    # Get population and node IDs
    if node_set_name not in node_set_data:
        raise KeyError(f"Node set '{node_set_name}' not found in node sets file")

    population = node_set_data[node_set_name]["population"]
    all_node_ids = node_set_data[node_set_name]["node_id"]
    logger.info(f"Population: {population}")
    logger.info(f"All node IDs: {all_node_ids}")

    # Distribute nodes across ranks
    num_nodes = len(all_node_ids)
    nodes_per_rank = num_nodes // size
    remainder = num_nodes % size
    logger.info(
        f"Total nodes: {num_nodes}, Nodes per rank: {nodes_per_rank}, Remainder: {remainder}"
    )

    # Calculate start and end indices for this rank
    start_idx = rank * nodes_per_rank + min(rank, remainder)
    if rank < remainder:
        nodes_per_rank += 1
    end_idx = start_idx + nodes_per_rank
    logger.info(f"Rank {rank}: start_idx={start_idx}, end_idx={end_idx}")

    # Get node IDs for this rank
    rank_node_ids = all_node_ids[start_idx:end_idx]
    logger.info(f"Rank {rank} node IDs: {rank_node_ids}")
    # create cell_ids_for_this_rank
    cell_ids_for_this_rank = [(population, i) for i in rank_node_ids]
    logger.info(f"Rank {rank}: Handling {len(cell_ids_for_this_rank)} cells")

    if not cell_ids_for_this_rank:
        logger.warning(f"Rank {rank}: No cells to process")

    if rank == 0:
        logger.info(f"Running BlueCelluLab simulation with {size} MPI processes")
        logger.info(f"Total cells: {num_nodes}, Cells per rank: ~{num_nodes // size}")
        logger.info(f"Starting simulation: t_stop={t_stop}ms, dt={dt}ms")

    logger.info(
        f"Rank {rank}: Processing {len(rank_node_ids)} cells (IDs: {rank_node_ids[0]}...{rank_node_ids[-1] if rank_node_ids else 'None'})"
    )

    # Create simulation
    sim = CircuitSimulation(simulation_config)

    # Get instantiate_gids arguments from config
    instantiate_params = get_instantiate_gids_params(simulation_config_data)

    if rank == 0:
        logger.info("Instantiate arguments from config:")
        for param, value in instantiate_params.items():
            if value:  # Only log parameters that are True
                logger.info(f"  {param}: {value}")

    try:
        logger.info(f"Rank {rank}: Instantiating cells...")
        # Instantiate cells on this rank with arguments from config
        sim.instantiate_gids(cell_ids_for_this_rank, **instantiate_params)

        # Run simulation
        logger.info(f"Rank {rank}: Running simulation...")
        sim.run(t_stop, v_init, cvode=False)

        # Get time trace once for all cells
        time_ms = sim.get_time_trace()
        if time_ms is None:
            logger.error(
                f"Rank {rank}: Time trace is None, cannot proceed with saving."
            )
            return

        time_s = time_ms / 1000.0  # Convert ms to seconds

        # Get voltage traces and spikes for each cell on this rank
        results_traces: Dict[str, Any] = {}
        results_spikes: Dict[str, Dict[int, list]] = defaultdict(
            dict
        )  # pop → gid → spikes
        for cell_id in cell_ids_for_this_rank:
            gid_key = f"{cell_id[0]}_{cell_id[1]}"

            # voltage trace ----------------------------------------------------
            voltage = sim.get_voltage_trace(cell_id)
            if voltage is not None:
                results_traces[gid_key] = {
                    "time": time_s.tolist(),
                    "voltage": voltage.tolist(),
                    "unit": "mV",
                }

            # spikes -----------------------------------------------------------
            try:
                pop = cell_id[0]
                gid = cell_id[1]
                results_spikes[pop][gid] = []
                cell_obj = sim.cells[cell_id]
                spikes = cell_obj.get_recorded_spikes(
                    location=sim.spike_location, threshold=sim.spike_threshold
                )
                if spikes is not None and len(spikes):
                    results_spikes[pop][gid] = list(spikes)
            except Exception:
                pass  # silently skip cells without spike recordings

        # Gather all results to rank 0
        logger.info(f"Rank {rank}: Gathering results...")
        try:
            # gathered_results = pc.py_gather(results, 0)
            gathered_traces = pc.py_gather(results_traces, 0)
            gathered_spikes = pc.py_gather(results_spikes, 0)
        except Exception as e:
            logger.error(f"Rank {rank}: Error gathering results: {str(e)}")

        if rank == 0:
            # ---- SONATA reports --------------------------------------------
            all_traces = _merge_dicts(gathered_traces)
            all_spikes = _merge_spikes(gathered_spikes)

            report_mgr = ReportManager(sim.circuit_access.config, sim.dt)
            report_mgr.write_all(cells_or_traces=all_traces, spikes_by_pop=all_spikes)
            # ----------------------------------------------------------------

            if save_nwb:
                # Get output directory from config
                output_dir_str = simulation_config_data["output"]["output_dir"]
                output_dir = Path(output_dir_str).resolve()

                # Save NWB file directly in the output directory
                output_path = output_dir / "voltage_report.nwb"
                logger.info(f"Saving NWB voltage report to: {output_path}")
                save_results_to_nwb(all_traces, execution_id, output_path)

                # Save voltage traces plot
                plot_path = output_dir / "voltage_traces.png"
                plot_voltage_traces(all_traces, plot_path)
                logger.info(f"Successfully saved voltage traces plot to {plot_path}")

    except Exception as e:
        logger.error(f"Rank {rank} failed: {str(e)}", exc_info=True)
        raise
    finally:
        try:
            # Ensure proper cleanup
            logger.info(f"Rank {rank}: Cleaning up...")
            pc.barrier()
            h.quit()
            if rank == 0:
                logger.info("All ranks completed. Simulation finished.")
        except Exception as e:
            logger.error(f"Error during cleanup in rank {rank}: {str(e)}")


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run a BlueCelluLab simulation.")
    parser.add_argument(
        "--simulation_config",
        "--config",
        type=str,
        required=True,
        help="Path to the simulation configuration file",
    )
    parser.add_argument(
        "--execution_id",
        type=str,
        required=True,
        help="Execution ID for this simulation run",
    )
    parser.add_argument(
        "--libnrnmech_path",
        type=str,
        required=True,
        help="Path to the nrnmech library",
    )
    parser.add_argument(
        "--save-nwb", action="store_true", help="Save results in NWB format"
    )

    args = parser.parse_args()

    # Validate simulation config exists
    config_path = Path(args.simulation_config)
    if not config_path.exists():
        logger.error(f"Configuration file not found: {config_path}")
        return 1

    # Run the simulation
    run_bluecellulab(
        simulation_config=args.simulation_config,
        execution_id=args.execution_id,
        save_nwb=args.save_nwb,
        libnrnmech_path=args.libnrnmech_path,
    )
    return 0


if __name__ == "__main__":
    main()
