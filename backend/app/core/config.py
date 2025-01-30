import os
from enum import Enum
from typing import List, Union, Optional
from pydantic import BaseSettings, AnyHttpUrl, EmailStr, validator
from multiprocessing import cpu_count


class AppConfig(BaseSettings.Config):
    """
    Config for settings classes that allows for
    combining Setings classes with different env_prefix settings.

    Taken from here:
    https://github.com/pydantic/pydantic/issues/1727#issuecomment-658881926
    """

    case_sensitive = True

    @classmethod
    def prepare_field(cls, field) -> None:
        if "env_names" in field.field_info.extra:
            return
        return super().prepare_field(field)


class AppEnvironment(str, Enum):
    """
    Enum for app environments.
    """

    LOCAL = "local"
    PREVIEW = "preview"
    PRODUCTION = "production"


is_pull_request: bool = os.environ.get("IS_PULL_REQUEST") == "true"
is_preview_env: bool = os.environ.get("IS_PREVIEW_ENV") == "true"


class PreviewPrefixedSettings(BaseSettings):
    """
    Settings class that uses a different env_prefix for PR Preview deployments.

    PR Preview deployments should source their secret environment variables with
    the `PREVIEW_` prefix, while regular deployments should source them from the
    environment variables with no prefix.

    Some environment variables (like `DATABASE_URL`) use Render.com's capability to
    automatically set environment variables to their preview value for PR Preview
    deployments, so they are not prefixed.
    """

    OPENAI_API_KEY: str
    AWS_KEY: str
    AWS_SECRET: str
    POLYGON_IO_API_KEY: str

    class Config(AppConfig):
        env_prefix = "PREVIEW_" if is_pull_request or is_preview_env else ""


class Settings(PreviewPrefixedSettings):
    """
    Application settings.
    """

    PROJECT_NAME: str = "llama_app"
    API_PREFIX: str = "/api"
    DATABASE_URL: str
    LOG_LEVEL: str = "DEBUG"
    IS_PULL_REQUEST: bool = False
    RENDER: bool = False
    CODESPACES: bool = False
    CODESPACE_NAME: Optional[str]
    S3_BUCKET_NAME: str
    S3_ASSET_BUCKET_NAME: str
    CDN_BASE_URL: str
    VECTOR_STORE_TABLE_NAME: str = "pg_vector_store"
    SENTRY_DSN: Optional[str]
    RENDER_GIT_COMMIT: Optional[str]
    LOADER_IO_VERIFICATION_STR: str = "loaderio-e51043c635e0f4656473d3570ae5d9ec"
    SEC_EDGAR_COMPANY_NAME: str = "YourOrgName"
    SEC_EDGAR_EMAIL: EmailStr = "you@example.com"

    # BACKEND_CORS_ORIGINS is a JSON-formatted list of origins
    # e.g: '["http://localhost", "http://localhost:4200", "http://localhost:3000", \
    # "http://localhost:8080", "http://local.dockertoolbox.tiangolo.com"]'
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    MODEL_NAME: str = "gpt-4o"  # Default to GPT-4o

    @property
    def VERBOSE(self) -> bool:
        """
        Used for setting verbose flag in LlamaIndex modules.
        """
        return self.LOG_LEVEL == "DEBUG" or self.IS_PULL_REQUEST or not self.RENDER

    @property
    def S3_ENDPOINT_URL(self) -> str:
        """
        Used for setting S3 endpoint URL in the s3fs module.
        When running locally, this should be set to the localstack endpoint.
        """
        if not self.RENDER:
            return "http://localhost:4566"
        return None


    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    @validator("DATABASE_URL", pre=True)
    def assemble_db_url(cls, v: str) -> str:
        """Preprocesses the database URL to make it compatible with asyncpg."""
        if not v or not v.startswith("postgres"):
            raise ValueError("Invalid database URL: " + str(v))
        return (
            v.replace("postgres://", "postgresql://")
            .replace("postgresql://", "postgresql+asyncpg://")
            .strip()
        )

    @validator("LOG_LEVEL", pre=True)
    def assemble_log_level(cls, v: str) -> str:
        """Preprocesses the log level to ensure its validity."""
        v = v.strip().upper()
        if v not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            raise ValueError("Invalid log level: " + str(v))
        return v

    @validator("IS_PULL_REQUEST", pre=True)
    def assemble_is_pull_request(cls, v: str) -> bool:
        """Preprocesses the IS_PULL_REQUEST flag.

        See Render.com docs for more info:
        https://render.com/docs/pull-request-previews#how-pull-request-previews-work
        """
        if isinstance(v, bool):
            return v
        return v.lower() == "true"

    @property
    def ENVIRONMENT(self) -> AppEnvironment:
        """Returns the app environment."""
        if self.RENDER:
            if self.IS_PULL_REQUEST:
                return AppEnvironment.PREVIEW
            else:
                return AppEnvironment.PRODUCTION
        else:
            return AppEnvironment.LOCAL

    @property
    def UVICORN_WORKER_COUNT(self) -> int:
        if self.ENVIRONMENT == AppEnvironment.LOCAL:
            return 1
        # The recommended number of workers is (2 x $num_cores) + 1:
        # Source: https://docs.gunicorn.org/en/stable/design.html#how-many-workers
        # But the Render.com servers don't have enough memory to support that many workers,
        # so we instead go by the number of server instances that can be run given the memory
        return 3

    @property
    def SENTRY_SAMPLE_RATE(self) -> float:
        # TODO: before full release, set this to 0.1 for production
        return 0.07 if self.ENVIRONMENT == AppEnvironment.PRODUCTION else 1.0

    @property 
    def CDN_BASE_URL(self) -> str:
        """
        Base URL for accessing S3 assets.
        Uses LocalStack endpoint in local development, AWS S3 in production/preview.
        """
        if not self.RENDER:
            return f"http://{self.S3_ASSET_BUCKET_NAME}.s3-website.localhost.localstack.cloud:4566"
        return f"https://{self.S3_ASSET_BUCKET_NAME}.s3.amazonaws.com"

    
settings = Settings()
os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
