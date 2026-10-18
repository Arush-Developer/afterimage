"""Small shared helpers: IDs, timestamps, hashing and typed errors."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone

ID_PREFIXES = ("run", "evt", "dec", "inc", "rpl", "snp", "exp")
ID_PATTERN = r"^(run|evt|dec|inc|rpl|snp|exp)_[0-9a-f]{16}$"
_ID_RE = re.compile(ID_PATTERN)


def new_id(prefix: str) -> str:
    assert prefix in ID_PREFIXES
    return f"{prefix}_{secrets.token_hex(8)}"


def is_valid_id(value: str, prefix: str) -> bool:
    return bool(_ID_RE.match(value)) and value.startswith(prefix + "_")


def utc_now() -> str:
    """UTC ISO-8601 timestamp with microseconds, e.g. 2026-01-01T12:00:00.000000+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


class AfterimageError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(AfterimageError):
    status_code = 404
    code = "not_found"


class ConflictError(AfterimageError):
    status_code = 409
    code = "conflict"


class ValidationFailure(AfterimageError):
    status_code = 400
    code = "invalid_request"
