import json
import os
import subprocess

from loguru import logger

from app.infrastructure.redis import close_stream, stream
from app.infrastructure.rq import get_current_stream_key


def run_circuit_simulation():
    stream_key = get_current_stream_key()

    num_cores = 4
    num_cells = 10

    cwd = os.getcwd()

    logger.info(f"cwd: {cwd}")

    config = f"{cwd}/circuit_model/simulation_config.json"
    node = "S1nonbarrel_neurons"
    start_gid = 0

    stream(stream_key, json.dumps({"status": "compiling"}))

    compile_cmd = f"nrnivmodl {cwd}/circuit_model/mod"
    subprocess.run(compile_cmd.split(" "), cwd=f"{cwd}/circuit_model")

    stream(stream_key, json.dumps({"status": "running"}))
    run_cmd = f"mpiexec -n {num_cores} python {cwd}/app/services/worker/circuit/mpi_simulation.py --config {config} --node {node} --start_gid {start_gid} --num_cells {num_cells}"

    subprocess.run(run_cmd, cwd=f"{cwd}/circuit_model", shell=True)
    stream(stream_key, json.dumps({"status": "done"}))

    close_stream(stream_key)
