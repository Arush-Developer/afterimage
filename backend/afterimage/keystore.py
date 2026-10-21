"""API keys entered in the Settings page.

A key typed into the UI is sent once to this backend and placed in the backend process
environment (where the provider adapters already look for it). It is never returned by
any endpoint: the API only reports *whether* a key is present and where it came from.

If the user ticks "remember", the key is also written to `<data_dir>/provider_keys.json`
with owner-only permissions (0600). That file is plain text on the local disk and lives
under `backend/data/`, which is gitignored. A key set in the shell before the backend
starts always takes precedence at startup; a key saved later from the UI replaces it for
the running process only.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}
KeySource = Literal["environment", "saved", "session"]
FILE_NAME = "provider_keys.json"


class KeyStoreError(ValueError):
    pass


def validate_key(value: str) -> str:
    """Basic shape check only. Whether the key works is verified by the provider Check."""
    key = value.strip()
    if not 20 <= len(key) <= 512:
        raise KeyStoreError("that does not look like an API key (expected 20-512 characters)")
    if not all(33 <= ord(ch) <= 126 for ch in key):
        raise KeyStoreError("an API key cannot contain spaces, line breaks or non-ASCII characters")
    return key


class KeyStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / FILE_NAME
        self._lock = threading.Lock()
        self._sources: dict[str, KeySource] = {}
        for provider, env_name in KEY_ENV.items():
            if os.environ.get(env_name):
                self._sources[provider] = "environment"
        for provider, key in self._read().items():
            if provider not in self._sources:  # the shell environment wins at startup
                os.environ[KEY_ENV[provider]] = key
                self._sources[provider] = "saved"

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {p: v for p, v in data.items() if p in KEY_ENV and isinstance(v, str) and v}

    def _write(self, data: dict[str, str]) -> None:
        if not data:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.path)
        os.chmod(self.path, 0o600)

    def status(self) -> dict[str, dict[str, object]]:
        with self._lock:
            return {p: {"present": bool(os.environ.get(env)),
                        "source": self._sources.get(p) if os.environ.get(env) else None}
                    for p, env in KEY_ENV.items()}

    def set(self, provider: str, value: str, *, remember: bool) -> None:
        if provider not in KEY_ENV:
            raise KeyStoreError(f"{provider} does not use an API key")
        key = validate_key(value)
        with self._lock:
            os.environ[KEY_ENV[provider]] = key
            saved = self._read()
            if remember:
                saved[provider] = key
            else:
                saved.pop(provider, None)
            self._write(saved)
            self._sources[provider] = "saved" if remember else "session"

    def remove(self, provider: str) -> None:
        if provider not in KEY_ENV:
            raise KeyStoreError(f"{provider} does not use an API key")
        with self._lock:
            saved = self._read()
            saved.pop(provider, None)
            self._write(saved)
            if self._sources.get(provider) == "environment":
                raise KeyStoreError("this key was set in the terminal that started the backend; "
                                    "unset it there and restart the backend to remove it")
            os.environ.pop(KEY_ENV[provider], None)
            self._sources.pop(provider, None)
