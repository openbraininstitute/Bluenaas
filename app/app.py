import sentry_sdk
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from starlette.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.core.exceptions import (
    AppError,
    AppErrorCode,
    AppErrorResponse,
)
from app.middleware.request_id import add_request_id_middleware
from app.routes.circuit import router as circuit_router
from app.routes.single_neuron import router as single_neuron_router

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
# TODO: reduce origins to only the allowed ones
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


base_router.include_router(single_neuron_router)
base_router.include_router(circuit_router)

app.include_router(base_router)
app.include_router(entitycore_router)
