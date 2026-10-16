from os import getenv
from pathlib import Path
from typing import Literal, Self, TypeGuard, get_args

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_core import Url
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv("")

_ENVS = Literal["development", "testing", "staging", "production"]

_CLOUD_PROVIDER = Literal["aws", "azure"] | None


def _is_valid_env(env: str | None) -> TypeGuard[_ENVS]:
    return env in get_args(_ENVS)


_ENV = getenv("DEPLOYMENT_ENV")
_DEPLOYMENT_ENV = _ENV if _is_valid_env(_ENV) else "development"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # `.env.local` takes priority over `.env`
        env_file=(".env", f".env.{_DEPLOYMENT_ENV}", ".env.local")
    )

    APP_NAME: str = "BlueNaas Service"
    APP_DEBUG: bool = False
    DEPLOYMENT_ENV: _ENVS = _DEPLOYMENT_ENV
    BASE_PATH: str = ""
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    CORS_ORIGIN_REGEX: str | None = None
    ENTITYCORE_URI: Url = Url("https://staging.cell-a.openbraininstitute.org/api/entitycore")

    KC_SERVER_URI: str = "http://localhost:9090/"
    KC_CLIENT_ID: str = "obpapp"
    KC_CLIENT_SECRET: str = "obp-secret"
    KC_REALM_NAME: str = "obp-realm"

    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 1.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 1.0

    ACCOUNTING_BASE_URL: Url | None = Url("http://localhost:8100")
    ACCOUNTING_DISABLED: str | None = None

    REDIS_URL: str = "redis://localhost:6379/0"

    STORAGE_PATH: Path = Path("/app/storage")

    # Cache cleanup. A cleanup starts a new epoch of the cache, so that new jobs never see the old
    # one, and deletes the old epoch once no job that could be using it is left.
    # Pause between starting a new epoch and listing the jobs that might still use the old one.
    CACHE_EPOCH_SETTLE_SECONDS: int = 60
    # Upper bound on how long an old epoch is kept: the longest job timeout (one hour) plus the
    # grace period RQ gives before it kills the job, with a margin.
    CACHE_RETIRED_MAX_AGE: int = 70 * 60
    # How often a cleanup that is waiting for jobs to finish checks again
    CACHE_RECLAIM_POLL_SECONDS: int = 5 * 60
    # Threads deleting a retired epoch. Every delete is a network round trip on EFS
    CACHE_CLEANUP_WORKERS: int = 8

    MAX_JOB_DURATION: int = 20 * 60  # 20 minutes
    DEFAULT_REDIS_STREAM_TTL: int = 60  # 1 minute

    HTTP_STREAM_KEEP_ALIVE_INTERVAL: int = 30  # 30 seconds

    METRICS_CLOUD_PROVIDER: _CLOUD_PROVIDER = None
    METRICS_INTERVAL: int = 60  # 1 minute
    METRICS_AWS_REGION: str | None = None

    LOG_LEVEL: str = "INFO"
    LOG_LEVEL_LIBS: str = "WARNING"
    LOG_SHOW_CID: bool = True
    LOG_SHOW_SOURCE: bool = True

    @model_validator(mode="after")
    def validate_accounting_config(self) -> Self:
        if not self.ACCOUNTING_DISABLED and not self.ACCOUNTING_BASE_URL:
            raise ValueError(
                "ACCOUNTING_BASE_URL must be set if not explicitly disabled with ACCOUNTING_DISABLED"
            )
        return self


settings = Settings()
