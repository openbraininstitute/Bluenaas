import time
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

from bluenaas.config.settings import settings
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
    BlueNaasErrorResponse,
)
from bluenaas.routes.morphology import router as morphology_router
from bluenaas.routes.simulation import router as simulation_router
from starlette.middleware.cors import CORSMiddleware

app = FastAPI(
    debug=True,
    title=settings.APP_NAME,
    openapi_url=f"{settings.BASE_PATH}/openapi.json",
    docs_url=f"{settings.BASE_PATH}/docs",
)

# TODO: reduce origins to only the allowed ones
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


requests = []


@app.exception_handler(BlueNaasError)
async def bluenaas_exception_handler(
    request: Request, exception: BlueNaasError
) -> JSONResponse:
    """
    this is will handle (format, standardize) all exceptions raised by the app
    any BlueNaasError raised anywhere in the app, will be captured by this handler
    and format it.
    """
    logger.error(f"{request.method} {request.url} failed: {repr(exception)}")

    return JSONResponse(
        status_code=int(exception.http_status_code),
        content=BlueNaasErrorResponse(
            message=exception.message,
            error_code=BlueNaasErrorCode(exception.error_code),
            details=exception.details,
        ).model_dump(),
    )


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    id = uuid4()
    response = await call_next(request)
    process_time = time.time() - start_time
    requests.append(
        {"id": id, "process_time": f"{process_time}s", "path": request.url.path},
    )
    return response


base_router = APIRouter(prefix=settings.BASE_PATH)


@base_router.get("/requests", description="for testing purposes")
def res_requests():
    return requests


base_router.include_router(morphology_router)
base_router.include_router(simulation_router)


app.include_router(base_router)
