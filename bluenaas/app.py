from typing import Awaitable, Callable
import uuid
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.gzip import GZipMiddleware
import sentry_sdk

from bluenaas.config.settings import settings
from bluenaas.core.exceptions import (
    BlueNaasError,
    BlueNaasErrorCode,
    BlueNaasErrorResponse,
)
from bluenaas.routes.morphology import router as morphology_router
from bluenaas.routes.entitycore.morphology import router as entitycore_morphology_router
from bluenaas.routes.simulation import router as simulation_router
from bluenaas.routes.graph_data import router as graph_router
from bluenaas.routes.synaptome import router as synaptome_router
from bluenaas.routes.validation import router as validation_router
from bluenaas.routes.neuron_model import router as neuron_model_router
from starlette.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware


sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
    environment=settings.DEPLOYMENT_ENV,
)


app = FastAPI(
    debug=True,
    title=settings.APP_NAME,
    openapi_url=f"{settings.BASE_PATH}/openapi.json",
    docs_url=f"{settings.BASE_PATH}/docs",
)

app.add_middleware(SentryAsgiMiddleware)
app.add_middleware(GZipMiddleware)
# TODO: reduce origins to only the allowed ones
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


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


base_router = APIRouter(prefix=settings.BASE_PATH)
entitycore_router = APIRouter(prefix=settings.BASE_PATH + "/entitycore")


@base_router.get("/")
def root() -> str:
    return "Server is running."


# TODO: add a proper health check logic, see https://pypi.org/project/fastapi-health/.
@base_router.get("/health")
def health() -> str:
    return "OK"


base_router.include_router(morphology_router)
base_router.include_router(simulation_router)
base_router.include_router(synaptome_router)
base_router.include_router(graph_router)
base_router.include_router(validation_router)
base_router.include_router(neuron_model_router)

entitycore_router.include_router(entitycore_morphology_router)

app.include_router(base_router)
app.include_router(entitycore_router)
