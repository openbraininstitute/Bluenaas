"""
Usage:
    python run_bluecellulab_simulation.py --simulation_config <simulation_config> [--save-nwb]
"""

# TODO: To refactor and split into core logic and MPI entry python module

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Union

import matplotlib
import numpy as np
from bluecellulab import CircuitSimulation
from loguru import logger
from neuron import h
from pynwb import NWBHDF5IO, NWBFile
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

        # Convert time from ms to seconds for NWB
        time_data = np.array(trace["time"], dtype=float) / 1000.0
        voltage_data = (
            np.array(trace["voltage"], dtype=float) / 1000.0
        )  # Convert mV to V

        # Create current clamp series
        ics = CurrentClampSeries(
            name=cell_id,
            data=voltage_data,
            electrode=electrode,
            timestamps=time_data,
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

    # Get the directory of the simulation config
    sim_config_base_dir = Path(simulation_config).parent
    print("sim_config_base_dir", sim_config_base_dir)
    # Get manifest path
    OUTPUT_DIR = simulation_config_data.get("manifest", {}).get("$OUTPUT_DIR", "./")
    print("OUTPUT_DIR", OUTPUT_DIR)
    # Get the node_set
    node_set_name = simulation_config_data.get("node_set", "All")

    # # Get the circuit config
    # circuit_config_file = simulation_config_data["network"]

    # Load node sets
    # with open(sim_config_base_dir / manifest_sim / circuit_config_file) as f:
    #     circuit_config_data = json.load(f)

    node_sets_file = sim_config_base_dir / simulation_config_data["node_sets_file"]
    print("node_sets_file", node_sets_file)

    with open(node_sets_file) as f:
        node_set_data = json.load(f)

    # Get population and node IDs
    population = node_set_data[node_set_name]["population"]
    all_node_ids = node_set_data[node_set_name]["node_id"]
    print("population", population)
    print("all_node_ids", all_node_ids)

    # Distribute nodes across ranks
    num_nodes = len(all_node_ids)
    nodes_per_rank = num_nodes // size
    remainder = num_nodes % size
    print("num_nodes", num_nodes)
    print("nodes_per_rank", nodes_per_rank)
    print("remainder", remainder)

    # Calculate start and end indices for this rank
    start_idx = rank * nodes_per_rank + min(rank, remainder)
    if rank < remainder:
        nodes_per_rank += 1
    end_idx = start_idx + nodes_per_rank
    print("start_idx", start_idx)
    print("end_idx", end_idx)
    # Get node IDs for this rank
    rank_node_ids = all_node_ids[start_idx:end_idx]
    print("rank_node_ids", rank_node_ids)
    # create cell_ids_for_this_rank
    cell_ids_for_this_rank = [(population, i) for i in rank_node_ids]
    logger.info(
        f"Rank {rank}: Handling {len(cell_ids_for_this_rank)} cells: {cell_ids_for_this_rank}"
    )

    if rank == 0:
        logger.info(f"Running BlueCelluLab simulation with {size} MPI processes")
        logger.info(f"Total cells: {num_nodes}, Cells per rank: ~{num_nodes // size}")
        logger.info(f"Starting simulation: t_stop={t_stop}ms, dt={dt}ms")

    logger.info(
        f"Rank {rank}: Processing {len(rank_node_ids)} cells (IDs: {rank_node_ids[0]}...{rank_node_ids[-1] if rank_node_ids else 'None'})"
    )

    # Create simulation
    sim = CircuitSimulation(simulation_config)

    try:
        # Instantiate cells on this rank
        # https://github.com/openbraininstitute/BlueCelluLab/blob/24e49003859571d3c01b943b4e3113a374ea1b80/bluecellulab/circuit_simulation.py#L128
        sim.instantiate_gids(
            cell_ids_for_this_rank,
            add_stimuli=True,
            add_synapses=True,
            add_minis=True,  # False
            add_replay=False,
            add_projections=True,
        )

        # Run simulation
        sim.run(t_stop, dt, cvode=False)

        # Get time trace once for all cells
        time_ms = sim.get_time_trace()
        if time_ms is None:
            logger.error(
                f"Rank {rank}: Time trace is None, cannot proceed with saving."
            )
            return

        time_s = time_ms / 1000.0  # Convert ms to seconds

        # Get voltage traces for each cell on this rank
        results = {}
        for cell_id in cell_ids_for_this_rank:
            voltage = sim.get_voltage_trace(cell_id)
            if voltage is not None:
                # change the cell_id to be Population_ID format
                cell_id_key = f"{cell_id[0]}_{cell_id[1]}"
                results[cell_id_key] = {
                    "time": time_s.tolist(),  # Convert numpy array to list for serialization
                    "voltage": voltage.tolist(),
                    "unit": "mV",
                }
            else:
                logger.warning(f"Rank {rank}: No voltage trace for cell {cell_id}")

        logger.info(f"Rank {rank}: Collected {len(results)} voltage traces")

        # Debug: Print first few keys from each rank
        if results:
            sample_keys = list(results.keys())[:3]
            logger.info(f"Rank {rank}: Sample cell IDs: {sample_keys}")
        else:
            logger.warning(f"Rank {rank}: No results to gather!")

        # Gather all results to rank 0
        gathered_results = pc.py_gather(results, 0)

        if rank == 0 and save_nwb:
            logger.info(
                f"Rank 0: Received gathered results from {len(gathered_results) if gathered_results else 0} ranks"
            )

            # Debug: Check what we got from each rank
            if gathered_results:
                for i, rank_results in enumerate(gathered_results):
                    if rank_results:
                        logger.info(
                            f"Rank 0: Results from rank {i}: {len(rank_results)} cells"
                        )
                    else:
                        logger.warning(f"Rank 0: No results from rank {i}")

            # Merge results from all ranks
            all_results = {}
            for rank_results in gathered_results:
                if rank_results:
                    all_results.update(rank_results)

            logger.info(f"Rank 0: Total merged results: {len(all_results)} cells")

            # Get output directory from config, handling all cases
            base_dir = Path(simulation_config).parent
            output_dir = None

            # if output_dir is explicitly specified in config
            if (
                "output" in simulation_config_data
                and "output_dir" in simulation_config_data["output"]
            ):
                output_dir_str = simulation_config_data["output"]["output_dir"]
                # Handle $OUTPUT_DIR variable if present
                if output_dir_str.startswith("$OUTPUT_DIR"):
                    if (
                        "manifest" in simulation_config_data
                        and "$OUTPUT_DIR" in simulation_config_data["manifest"]
                    ):
                        output_dir = Path(
                            simulation_config_data["manifest"]["$OUTPUT_DIR"]
                        ) / output_dir_str.replace("$OUTPUT_DIR/", "")
                else:
                    output_dir = Path(output_dir_str)

                # Make path absolute if it's relative
                if not output_dir.is_absolute():
                    output_dir = base_dir / output_dir

            # if output_dir not specified or invalid
            if output_dir is None:
                output_dir = base_dir / "output"

            # TODO: probably not needed
            # Ensure output directory exists
            output_dir.mkdir(parents=True, exist_ok=True)

            # Save NWB file directly in the output directory
            output_path = (output_dir / "voltage_report.nwb").resolve()
            logger.info(f"Saving simulation results to: {output_path}")
            save_results_to_nwb(all_results, execution_id, output_path)

            logger.info(f"Successfully saved results to {output_path}")

            # Save voltage traces plot
            plot_path = (output_dir / "voltage_report.png").resolve()
            plot_voltage_traces(all_results, plot_path)
            logger.info(f"Successfully saved voltage traces plot to {plot_path}")

    except Exception as e:
        logger.error(f"Rank {rank} failed: {str(e)}")
        raise
    finally:
        # Ensure proper cleanup
        pc.barrier()
        if rank == 0:
            logger.info("Simulation completed")


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
