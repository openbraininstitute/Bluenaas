import json
import os
import subprocess
from fastapi import Request
from fastapi.responses import StreamingResponse
from rq import Queue

from bluenaas.infrastructure.redis import stream, close_stream
from bluenaas.infrastructure.rq import get_current_stream_key
from bluenaas.utils.rq_job import dispatch
from bluenaas.utils.streaming import x_ndjson_http_stream


def run_circuit_simulation(
    request: Request,
    job_queue: Queue,
):
    _job, stream = dispatch(
        job_queue,
        run_circuit_simulation_task,
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")


def run_circuit_simulation_task():
    stream_key = get_current_stream_key()

    num_cores = 1
    num_cells = 10

    cwd = os.getcwd()

    config = f"{cwd}/circuit_model/simulation_config.json"
    nodes = "S1nonbarrel_neurons"
    start_gid = 0

    stream(stream_key, json.dumps({"status": "compiling"}))

    compile_cmd = f"nrnivmodl {cwd}/circuit_model/mod"
    subprocess.run(compile_cmd.split(" "), cwd=f"{cwd}/circuit_model")

    stream(stream_key, json.dumps({"status": "running"}))
    run_cmd = f"mpiexec -n {num_cores} python3 {cwd}/bluenaas/services/circuit/run-sim-mpi-entrypoint.py --config {config} --node {nodes} --start_gid {start_gid} --num_cells {num_cells}"
    # run_cmd = f"mpiexec -n {num_cores} python3 /app/bluenaas/services/circuit/test.py --config {config} --node {nodes} --start_gid {start_gid} --num_cells {num_cells}"

    subprocess.run(run_cmd, cwd=f"{cwd}/circuit_model", shell=True)

    stream(stream_key, json.dumps({"status": "done"}))

    close_stream(stream_key)
