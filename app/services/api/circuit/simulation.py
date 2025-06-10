from app.job import JobFn
from app.utils.rq_job import dispatch
from app.utils.api.streaming import x_ndjson_http_stream


from fastapi import Request
from fastapi.responses import StreamingResponse
from rq import Queue


def run_circuit_simulation(
    request: Request,
    job_queue: Queue,
):
    _job, stream = dispatch(
        job_queue,
        JobFn.RUN_CIRCUIT_SIMULATION,
    )
    http_stream = x_ndjson_http_stream(request, stream)

    return StreamingResponse(http_stream, media_type="application/x-ndjson")
