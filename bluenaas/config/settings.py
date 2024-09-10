from os import getenv
from typing import Literal, TypeGuard, get_args

from dotenv import load_dotenv
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

    KC_SERVER_URI: str = "http://localhost:9090/"
    KC_CLIENT_ID: str = "obpapp"
    KC_CLIENT_SECRET: str = "obp-secret"
    KC_REALM_NAME: str = "obp-realm"

    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 1.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 1.0


settings = Settings()
