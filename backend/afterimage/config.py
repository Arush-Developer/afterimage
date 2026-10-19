"""Application settings, loaded from environment variables and validated on startup.

Only non-secret settings exist. If an optional `.env` file is present in the backend
directory it is read first, but real environment variables always take precedence.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, Field, field_validator

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BACKEND_DIR / "data"
DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173"


class Settings(BaseModel):
    data_dir: Path
    cors_origins: list[str]
    max_read_bytes: int = Field(default=65536, ge=1024, le=1_048_576)
    cloud_sync: str = "disabled"
    # LLM agent settings (no secrets here: credentials stay in the SDK's own env vars)
    llm_provider: str = "anthropic"
    llm_model: str | None = None
    llm_effort: str = "medium"
    llm_timeout_s: float = Field(default=120.0, ge=5, le=600)
    llm_max_steps: int = Field(default=12, ge=1, le=40)
    llm_max_tokens: int = Field(default=16000, ge=256, le=64000)
    llm_max_trials: int = Field(default=5, ge=1, le=20)
    ollama_host: str = "http://127.0.0.1:11434"
    anthropic_base_url: str | None = None
    gemini_base_url: str | None = None
    gemini_min_interval_s: float = Field(default=0.0, ge=0, le=120)

    @field_validator("cors_origins")
    @classmethod
    def _validate_origins(cls, origins: list[str]) -> list[str]:
        if not origins:
            raise ValueError("at least one CORS origin is required")
        for origin in origins:
            if origin == "*" or "*" in origin:
                raise ValueError("wildcard CORS origins are not allowed")
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"CORS origin must start with http:// or https://: {origin!r}")
            if origin.endswith("/"):
                raise ValueError(f"CORS origin must not end with '/': {origin!r}")
        return origins

    @field_validator("cloud_sync")
    @classmethod
    def _validate_cloud(cls, value: str) -> str:
        if value != "disabled":
            raise ValueError("cloud sync is not implemented in this prototype; leave AFTERIMAGE_CLOUD_SYNC unset")
        return value

    @field_validator("llm_provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        if value not in ("anthropic", "gemini", "ollama", "simulated"):
            raise ValueError("AFTERIMAGE_LLM_PROVIDER must be anthropic, gemini, ollama or simulated")
        return value

    @field_validator("llm_effort")
    @classmethod
    def _validate_effort(cls, value: str) -> str:
        if value not in ("", "low", "medium", "high", "xhigh", "max"):
            raise ValueError("AFTERIMAGE_LLM_EFFORT must be empty or one of low, medium, high, xhigh, max")
        return value

    @field_validator("llm_model")
    @classmethod
    def _validate_model(cls, value: str | None) -> str | None:
        import re
        if value and not re.match(r"^[A-Za-z0-9._:/-]{1,100}$", value):
            raise ValueError("AFTERIMAGE_LLM_MODEL contains invalid characters")
        return value or None

    @field_validator("ollama_host", "anthropic_base_url", "gemini_base_url")
    @classmethod
    def _validate_url(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("URLs must start with http:// or https://")
        return value or None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "afterimage.db"

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def vault_dir(self) -> Path:
        return self.data_dir / "vault"

    @property
    def archives_dir(self) -> Path:
        return self.data_dir / "archives"


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build validated settings. Raises pydantic.ValidationError on bad configuration."""
    if env is None:
        merged = _read_dotenv(BACKEND_DIR / ".env")
        merged.update(os.environ)
        env = merged

    data_dir = Path(env.get("AFTERIMAGE_DATA_DIR", str(DEFAULT_DATA_DIR)))
    if not data_dir.is_absolute():
        data_dir = (BACKEND_DIR / data_dir).resolve()
    origins = [o.strip() for o in env.get("AFTERIMAGE_CORS_ORIGINS", DEFAULT_CORS).split(",") if o.strip()]
    return Settings(
        data_dir=data_dir,
        cors_origins=origins,
        max_read_bytes=int(env.get("AFTERIMAGE_MAX_READ_BYTES", "65536")),
        cloud_sync=env.get("AFTERIMAGE_CLOUD_SYNC", "disabled"),
        llm_provider=env.get("AFTERIMAGE_LLM_PROVIDER", "anthropic"),
        llm_model=env.get("AFTERIMAGE_LLM_MODEL") or None,
        llm_effort=env.get("AFTERIMAGE_LLM_EFFORT", "medium"),
        llm_timeout_s=float(env.get("AFTERIMAGE_LLM_TIMEOUT_S", "120")),
        llm_max_steps=int(env.get("AFTERIMAGE_LLM_MAX_STEPS", "12")),
        llm_max_tokens=int(env.get("AFTERIMAGE_LLM_MAX_TOKENS", "16000")),
        llm_max_trials=int(env.get("AFTERIMAGE_LLM_MAX_TRIALS", "5")),
        ollama_host=env.get("AFTERIMAGE_OLLAMA_HOST", "http://127.0.0.1:11434"),
        anthropic_base_url=env.get("AFTERIMAGE_ANTHROPIC_BASE_URL") or None,
        gemini_base_url=env.get("AFTERIMAGE_GEMINI_BASE_URL") or None,
        gemini_min_interval_s=float(env.get("AFTERIMAGE_GEMINI_MIN_INTERVAL_S", "0") or 0),
    )
