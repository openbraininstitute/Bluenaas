from os import getenv
from pathlib import Path
from typing import Literal, Self, TypeGuard, get_args

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_core import Url
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv("")

_ENVS = Literal["development", "testing", "staging", "production"]


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
    CORS_ORIGINS: list[str] = []
    NEXUS_ROOT_URI: Url = Url("https://openbluebrain.com/api/nexus/v1")
    ENTITYCORE_URI: Url = Url("https://staging.openbraininstitute.org/api/entitycore")

    KC_SERVER_URI: str = "http://localhost:9090/"
    KC_CLIENT_ID: str = "obpapp"
    KC_CLIENT_SECRET: str = "obp-secret"
    KC_REALM_NAME: str = "obp-realm"

    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 1.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 1.0

    ACCOUNTING_BASE_URL: Url | None = None
    ACCOUNTING_DISABLED: str | None = None

    REDIS_URL: str = "redis://localhost:6379/0"

    STORAGE_PATH: Path = Path("/app/storage")

    @model_validator(mode="after")
    def validate_accounting_config(self) -> Self:
        if not self.ACCOUNTING_DISABLED and not self.ACCOUNTING_BASE_URL:
            raise ValueError(
                "ACCOUNTING_BASE_URL must be set if not explicitly disabled with ACCOUNTING_DISABLED"
            )
        return self


settings = Settings()
