"""
Centralized configuration using Pydantic Settings.

Validates all environment variables at startup and provides
typed access throughout the application.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App
    env: str = Field("development", alias="ENV")
    port: int = Field(8000, alias="PORT")
    allowed_origins: str = Field(
        "http://localhost:3000,http://localhost:5173",
        alias="ALLOWED_ORIGINS",
    )

    # Authentication
    propai_api_keys: str = Field("", alias="PROPAI_API_KEYS")

    # Rate limiting
    rate_limit_requests: int = Field(30, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(60, alias="RATE_LIMIT_WINDOW")

    # Database
    database_url: str = Field(
        "postgresql+asyncpg://propai:propai@localhost:5432/propai",
        alias="DATABASE_URL",
    )

    # Redis
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")

    # AI / LLM
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")

    # File storage
    storage_backend: str = Field("local", alias="STORAGE_BACKEND")
    storage_local_path: str = Field("./uploads", alias="STORAGE_LOCAL_PATH")

    # Data APIs (all optional)
    census_api_key: str = Field("", alias="CENSUS_API_KEY")
    fred_api_key: str = Field("", alias="FRED_API_KEY")
    walkscore_api_key: str = Field("", alias="WALKSCORE_API_KEY")

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def api_keys_set(self) -> set[str]:
        return {k.strip() for k in self.propai_api_keys.split(",") if k.strip()}

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys_set)

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
