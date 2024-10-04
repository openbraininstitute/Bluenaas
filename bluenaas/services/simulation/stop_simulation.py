from fastapi.responses import JSONResponse
from bluenaas.utils.streaming import cleanup_worker
from http import HTTPStatus


async def stop_simulation(
    token: str,
    task_id: str,
):
    from celery.result import AsyncResult
    from bluenaas.infrastructure.celery import celery_app

    task_result = AsyncResult(
        task_id,
        app=celery_app,
    )

    if not task_result.ready():
        await cleanup_worker(
            task_id,
        )

    return JSONResponse(
        content={
            "task_id": task_id,
            "status": task_result.status.lower(),
            "message": f"Simulation running by {task_id} is terminated",
        },
        status_code=HTTPStatus.ACCEPTED,
        headers={
            "x-bnaas-task": task_id,
        },
    )
