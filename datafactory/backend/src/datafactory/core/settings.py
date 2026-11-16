"""Process configuration and the environment isolation guard.

Development and production share the RAGFlow storage on the production host, so
DataFactory's own resources must be named apart. When ``DF_ENV`` is ``dev`` the
database name, object bucket and Redis prefix must all contain ``dev``; the
process refuses to start otherwise. There is no switch that skips the check.
"""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything the process needs, read from the environment."""

    model_config = SettingsConfigDict(env_prefix="DF_", extra="ignore")

    env: Literal["dev", "prod"] = "dev"
    host: str = "localhost"

    database_url: str = "mysql+asyncmy://datafactory:datafactory@127.0.0.1:3306/datafactory_dev_localhost"
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_prefix: str = "df:dev:localhost:"

    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "datafactory-dev-localhost"
    minio_secure: bool = False

    gateway_base_url: str = "http://127.0.0.1:9380/api/v1"
    gateway_service_key: str = ""
    gateway_version: str = "1"
    gateway_timeout_s: float = 60.0

    api_prefix: str = "/api/factory/v1"
    session_secret: str = Field(default="", repr=False)

    @model_validator(mode="after")
    def _guard_dev_isolation(self) -> "Settings":
        if self.env != "dev":
            return self
        # SQLite is local to the process and cannot be the shared production
        # database, so the name check applies to server URLs only.
        database = (
            "dev_local_sqlite"
            if self.database_url.startswith("sqlite")
            else self.database_url.rsplit("/", 1)[-1].split("?", 1)[0]
        )
        offenders = [
            name
            for name, value in (
                ("database", database),
                ("bucket", self.minio_bucket),
                ("redis prefix", self.redis_prefix),
            )
            if "dev" not in value
        ]
        if offenders:
            joined = ", ".join(offenders)
            raise ValueError(f"DF_ENV=dev but these names do not contain 'dev': {joined}. Refusing to start.")
        return self

    def redis_key(self, *parts: str) -> str:
        """A Redis key under this environment's prefix."""
        return self.redis_prefix + ":".join(parts)


class GatewaySettings(BaseSettings):
    """The subset of configuration the gateway client is allowed to see.

    Kept separate so the gateway package never imports the store or the app.
    """

    model_config = SettingsConfigDict(env_prefix="DF_", extra="ignore")

    gateway_base_url: str = "http://127.0.0.1:9380/api/v1"
    gateway_service_key: str = ""
    gateway_version: str = "1"
    gateway_timeout_s: float = Field(default=60.0)


def load_settings() -> Settings:
    """Read configuration and refuse a development process aimed at production resources."""
    return Settings()
