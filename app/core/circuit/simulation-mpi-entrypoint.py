"""
Usage:
    python run_bluecellulab_simulation.py --simulation_config <simulation_config>
"""

# TODO: To refactor and split into core logic and MPI entry python module

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Union

from bluecellulab import CircuitSimulation
from bluecellulab.reports.manager import ReportManager
from loguru import logger
from neuron import h

from bluecellulab.reports.utils import (
    collect_local_payload,
    collect_local_spikes,
    gather_payload_to_rank0,
    payload_to_cells,
    gather_recording_sites,
    prepare_recordings_for_reports,
)


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
            "seclamp",
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

    # Check for spike replay in inputs
    if "inputs" in simulation_config_data:
        for input_def in simulation_config_data["inputs"].values():
            if input_def.get("module") == "synapse_replay":
                params["add_replay"] = True
                params["add_synapses"] = True
                break

    params["add_projections"] = params["add_synapses"] or params["add_replay"]
    return params


def run_bluecellulab(
    simulation_config: Union[str, Path],
    libnrnmech_path: str,
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
        f"Rank {rank}: Processing {len(rank_node_ids)} cells "
        f"(IDs: {rank_node_ids[0] if rank_node_ids else 'None'}..."
        f"{rank_node_ids[-1] if rank_node_ids else 'None'})"
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
        logger.info(f"Rank {rank}: Setting up recordings...")
        recording_index, local_sites_index = prepare_recordings_for_reports(
            sim.cells,
            sim.circuit_access.config,
        )

        logger.info(f"Rank {rank}: Running simulation...")
        sim.run(t_stop, v_init, cvode=False)

        gathered_sites = pc.py_gather(local_sites_index, 0)

        local_payload = collect_local_payload(
            sim.cells,
            cell_ids_for_this_rank,
            recording_index,
        )
        local_spikes = collect_local_spikes(sim, cell_ids_for_this_rank)

        all_payload, all_spikes = gather_payload_to_rank0(pc, local_payload, local_spikes)
        if rank == 0:
            all_sites_index = gather_recording_sites(gathered_sites)
            cells_for_writer = payload_to_cells(all_payload, all_sites_index)

            report_mgr = ReportManager(sim.circuit_access.config, sim.dt)
            report_mgr.write_all(cells=cells_for_writer, spikes_by_pop=all_spikes)

    except Exception as e:
        logger.error(f"Rank {rank} failed: {str(e)}", exc_info=True)
        raise

    try:
        # Ensure proper cleanup for successful runs
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
        "--libnrnmech_path",
        type=str,
        required=True,
        help="Path to the nrnmech library",
    )
    parser.add_argument("--cid", type=str, default=None, help="Correlation ID for log tracing")

    args = parser.parse_args()

    # Validate simulation config exists
    config_path = Path(args.simulation_config)
    if not config_path.exists():
        raise RuntimeError(f"Simulation config file not found: {config_path}")

    from app.logging import setup_logging

    setup_logging()
    if args.cid:
        logger.configure(extra={"cid": args.cid})

    # Run the simulation
    run_bluecellulab(
        simulation_config=args.simulation_config,
        libnrnmech_path=args.libnrnmech_path,
    )


if __name__ == "__main__":
    main()
