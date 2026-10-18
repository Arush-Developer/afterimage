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
    )
