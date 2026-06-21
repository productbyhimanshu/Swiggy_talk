"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root: phases/phase_00/config.py → ../../
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    # Emergent universal LLM key — OpenAI-compatible proxy; preferred over
    # the direct Gemini key when set (no 20 req/day free-tier limit)
    emergent_llm_key: str = Field(default="", alias="EMERGENT_LLM_KEY")

    swiggy_oauth_client_id: str = Field(default="", alias="SWIGGY_OAUTH_CLIENT_ID")
    swiggy_oauth_client_secret: str = Field(
        default="", alias="SWIGGY_OAUTH_CLIENT_SECRET"
    )
    swiggy_access_token: str = Field(default="", alias="SWIGGY_ACCESS_TOKEN")
    swiggy_token_expiry: float = Field(default=0.0, alias="SWIGGY_TOKEN_EXPIRY")
    swiggy_oauth_redirect_uri: str = Field(
        default="http://localhost:8000/auth/callback",
        alias="SWIGGY_OAUTH_REDIRECT_URI",
    )
    swiggy_oauth_base_url: str = Field(
        default="https://mcp.swiggy.com", alias="SWIGGY_OAUTH_BASE_URL"
    )
    swiggy_food_url: str = Field(
        default="https://mcp.swiggy.com/food", alias="SWIGGY_FOOD_URL"
    )

    frontend_url: str = Field(default="http://localhost:5173", alias="FRONTEND_URL")
    log_level: str = Field(default="debug", alias="LOG_LEVEL")
    log_dir: str = Field(default="logs", alias="LOG_DIR")
    log_file_name: str = Field(default="swiggy-talk.log", alias="LOG_FILE_NAME")
    log_errors_file_name: str = Field(
        default="errors.log", alias="LOG_ERRORS_FILE_NAME"
    )
    log_max_bytes: int = Field(default=10_485_760, alias="LOG_MAX_BYTES")
    log_backup_count: int = Field(default=5, alias="LOG_BACKUP_COUNT")
    session_timeout_minutes: int = Field(default=30, alias="SESSION_TIMEOUT_MINUTES")

    # ORDER_ENABLED is the only switch that unlocks real COD placement.
    # It defaults to False and is force-reset to False by phases/conftest.py
    # on every pytest run — so eval suites and unit tests can never trigger
    # a real order even if the .env on disk has it true.
    order_enabled: bool = Field(default=False, alias="ORDER_ENABLED")
    # Kept for backwards-compatibility with older .env / test fixtures.
    # No longer consulted by the order gate; safe to remove from .env.
    eval_suite_passed: bool = Field(default=False, alias="EVAL_SUITE_PASSED")

    @property
    def orders_allowed(self) -> bool:
        return self.order_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()
