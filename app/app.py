from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.core.exceptions import (
    AppError,
    AppErrorCode,
    AppErrorResponse,
)
from app.infrastructure.metrics import metrics_service
from app.middleware.request_id import add_request_id_middleware
from app.routes.admin import router as admin_router
from app.routes.circuit import router as circuit_router
from app.routes.ion_channel import router as ion_channel_router
from app.routes.mesh import router as mesh_router
from app.routes.single_neuron import router as single_neuron_router

sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
    environment=settings.DEPLOYMENT_ENV,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await metrics_service.start()
    yield
    # Shutdown
    await metrics_service.stop()


app = FastAPI(
    debug=True,
    title=settings.APP_NAME,
    openapi_url=f"{settings.BASE_PATH}/openapi.json",
    docs_url=f"{settings.BASE_PATH}/docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(add_request_id_middleware)


@app.exception_handler(AppError)
async def bluenaas_exception_handler(request: Request, exception: AppError) -> JSONResponse:
    """
    this is will handle (format, standardize) all exceptions raised by the app
    any BlueNaasError raised anywhere in the app, will be captured by this handler
    and format it.
    """
    logger.error(f"{request.method} {request.url} failed: {repr(exception)}")
    return JSONResponse(
        status_code=int(exception.http_status_code),
        content=AppErrorResponse(
            message=exception.message,
            error_code=AppErrorCode(
                exception.error_code
                if exception.error_code is not None
                else "UNKNOWN_BLUENAAS_ERROR"
            ),
            details=exception.details,
        ).model_dump(),
    )


base_router = APIRouter(prefix=settings.BASE_PATH)


@base_router.get("/")
def root() -> str:
    return "Server is running."


# TODO: add a proper health check logic, see https://pypi.org/project/fastapi-health/.
@base_router.get("/health")
def health() -> str:
    return "OK"


base_router.include_router(admin_router)
base_router.include_router(circuit_router)
base_router.include_router(mesh_router)
base_router.include_router(single_neuron_router)
base_router.include_router(ion_channel_router)

app.include_router(base_router)
