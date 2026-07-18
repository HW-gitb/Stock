"""No-secret exception summaries for A-short non-blocking sidecars."""
from __future__ import annotations

import os
import re


_URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(
    r"(?ix)(\b(?:tushare[_-]?token|token|api[_-]?key|authorization|password|secret)\b[\"']?\s*[:=]\s*)"
    r"(?:bearer\s+)?(?:[\"']?[^\s,;\"'}\]]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/=]+")
_ENV_SECRET_NAMES = ("TUSHARE_TOKEN", "FMP_API_KEY", "MASSIVE_API_KEY")


def safe_exception_summary(exc: BaseException, *, limit: int = 240) -> str:
    """Return a short diagnostic while excluding URLs and common secret values."""
    try:
        raw = str(exc)
    except Exception:  # noqa: BLE001 (diagnostics helper must never raise from a fail-safe path)
        raw = ""
    message = " ".join(raw.split())
    for name in _ENV_SECRET_NAMES:
        value = os.environ.get(name)
        if value:
            message = message.replace(value, "[REDACTED]")
    message = _URL_RE.sub("[REDACTED_URL]", message)
    message = _SECRET_VALUE_RE.sub(r"\1[REDACTED]", message)
    message = _BEARER_RE.sub("Bearer [REDACTED]", message)
    message = message[:limit]
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__
