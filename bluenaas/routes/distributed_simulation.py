"""
Synapse Placement Generation:
Exposes an endpoint (`/distributed`) to generate synapse placements based on user-provided parameters
"""

import json
from typing import cast
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
from http import HTTPStatus as status

from loguru import logger
from pydantic import UUID4
from bluenaas.domains.simulation import SingleNeuronSimulationConfig
from bluenaas.infrastructure.celery import celery_app
from bluenaas.infrastructure.kc.auth import verify_jwt


router = APIRouter(prefix="/distributed")


def select_best_worker(cpus, amplitudes):
    # Create a list of tuples containing (worker_name, available_cpus)
    available_workers = [
        (worker_name, stats["total_cpus"] - stats["cpus_in_use"])
        for worker_info in cpus
        for worker_name, stats in worker_info.items()
    ]

    # Filter workers that can handle the required amplitudes
    suitable_workers = [
        (worker_name, available_cpus)
        for worker_name, available_cpus in available_workers
        if available_cpus >= amplitudes
    ]

    # Return the worker with the maximum available CPUs or None if no suitable worker exists
    return max(suitable_workers, key=lambda x: x[1], default=None)


@router.post(
    "/simulation",
)
def distributed_simulation(
    request: Request,
    model_id: str,
    config: SingleNeuronSimulationConfig,
    token: str = Depends(verify_jwt),
):
    from bluenaas.infrastructure.celery import create_simulation, celery_app
    from celery import states

    req_id = request.state.request_id
    result_cpu = celery_app.control.broadcast("cpu_usage_stats", reply=True, timeout=2)
    # TODO: there is no way to specify which worker is best in the current API
    worker = select_best_worker(
        result_cpu, len(config.currentInjection.stimulus.amplitudes)
    )

    task = create_simulation.apply_async(
        kwargs={
            "model_id": model_id,
            "req_id": req_id,
            "config": config.model_dump_json(),
            "token": token,
        }
    )

    def streamify():
        yield f"{json.dumps(
            {
                "event": "info",
                "state": task.state,
                "task_id": task.id,
            }
        )}\n"

        while not task.ready():
            logger.info(f"data--> {task.state}")
            yield f"{json.dumps(
                    {
                        "event": "info" if task.state in {states.PENDING, states.SUCCESS} else "data",
                        "state": task.state,
                        "data": task.info,
                    }
                )}\n"

        logger.info(f"Simulation {req_id} completed")

    return StreamingResponse(
        streamify(),
        media_type="application/octet-stream",
        headers={
            "x-bnaas-task": task.id,
        },
    )


@router.get("/simulation")
def get_simualation(
    request: Request,
    simulation_id: str = Query(title="simulation id"),
):
    from celery.result import AsyncResult, states

    factory = AsyncResult(simulation_id, app=celery_app)
    if factory.ready():
        re = factory.result
        logger.info(f"data {re}")
        logger.info(f"data {type(re)}")

        return JSONResponse(
            content=jsonable_encoder({"b": str(re)}),
            status_code=status.OK,
        )
    else:

        def streamify():
            yield f"{json.dumps(
                {
                    "event": "info",
                    "state": factory.state,
                    "task_id": factory.task_id
                }
            )}\n"

            while not factory.ready():
                logger.info(f"data--> {factory.state}")
                yield f"{json.dumps(
                        {
                            "event": "info" if factory.state in {states.PENDING, states.SUCCESS} else "data",
                            "state": factory.state,
                            "data": factory.info,
                        }
                    )}\n"

            return StreamingResponse(
                streamify(),
                media_type="application/octet-stream",
                headers={
                    "x-bnaas-task": factory.task_id,
                },
            )
