from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ENV_FILE = PROJECT_ROOT / ".env"

# Load project-local .env so each project can keep isolated config.
load_dotenv(dotenv_path=PROJECT_ENV_FILE, override=False)


def _resolve_data_file() -> Path:
    env_value = os.getenv("DATA_FILE")
    if env_value:
        candidate = Path(env_value)
        if candidate.is_absolute():
            return candidate
        return (PROJECT_ROOT / candidate).resolve()
    return PROJECT_ROOT / "propupkeep/data/activity.jsonl"


class Settings(BaseModel):
    app_name: str = "PropUpkeep MVP"
    app_env: str = Field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = Field(
        default_factory=lambda: os.getenv("MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    )
    openai_chat_url: str = Field(
        default_factory=lambda: os.getenv(
            "OPENAI_CHAT_URL", "https://api.openai.com/v1/chat/completions"
        )
    )
    request_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("OPENAI_TIMEOUT_SECONDS", "45"))
    )

    max_upload_mb: int = Field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "5")))
    max_input_chars: int = Field(default_factory=lambda: int(os.getenv("MAX_INPUT_CHARS", "3000")))
    data_file: Path = Field(default_factory=_resolve_data_file)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
