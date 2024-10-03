import json

from fastapi.responses import StreamingResponse
from loguru import logger


def retrieve_simulation(simulation_id: str):
    # check if the simulation still running
    # then use celery AsyncResult to get realtime data
    # else fetch it from nexus
    from celery.result import AsyncResult, states
    from bluenaas.infrastructure.celery import celery_app

    task = AsyncResult(simulation_id, app=celery_app)

    def streamify():
        yield f"{json.dumps(
                {
                    "event": "info",
                    "state": task.state,
                    "task_id": task.task_id
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

        return StreamingResponse(
            streamify(),
            media_type="application/octet-stream",
            headers={
                "x-bnaas-task": task.task_id,
            },
        )
