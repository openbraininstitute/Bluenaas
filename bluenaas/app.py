import time
from typing import Awaitable, Callable
from uuid import uuid4
import uuid
from fastapi import APIRouter, FastAPI, Request, Response
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
from bluenaas.routes.graph_data import router as graph_router
from bluenaas.routes.synaptome import router as synaptome_router
from starlette.middleware.cors import CORSMiddleware


app = FastAPI(
    debug=True,
    title=settings.APP_NAME,
    openapi_url=f"{settings.BASE_PATH}/openapi.json",
    docs_url=f"{settings.BASE_PATH}/docs",
)


@app.middleware("http")
async def add_request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


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
            error_code=BlueNaasErrorCode(
                exception.error_code
                if exception.error_code is not None
                else "UNKNOWN_BLUENAAS_ERROR"
            ),
            details=exception.details,
        ).model_dump(),
    )


@app.middleware("http")
async def add_process_time_header(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start_time = time.time()
    id = uuid4()
    response = await call_next(request)
    process_time = time.time() - start_time
    requests.append(
        {
            "id": id,
            "process_time": f"{process_time}s",
            "path": request.url.path,
        },
    )
    return response


base_router = APIRouter(prefix=settings.BASE_PATH)


@base_router.get("/requests", description="for testing purposes")
def res_requests() -> list[dict[str, object]]:
    return requests


@base_router.get("/")
def root() -> str:
    return "Server is running."


# TODO: add a proper health check logic, see https://pypi.org/project/fastapi-health/.
@base_router.get("/health")
def health() -> str:
    logger.info(f"total requests {len(requests)}")
    return "OK"


base_router.include_router(morphology_router)
base_router.include_router(simulation_router)
base_router.include_router(synaptome_router)
base_router.include_router(graph_router)


app.include_router(base_router)
