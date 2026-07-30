"""Shared fail-closed semantics for nullable A-short risk booleans."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _is_missing(value: object) -> bool:
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return isinstance(missing, (bool, np.bool_)) and bool(missing)


def fail_closed_risk_bool(value: object) -> bool:
    """Treat an unknown or malformed risk fact as dangerous."""
    if _is_missing(value):
        return True
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    if isinstance(value, (int, float, np.integer, np.floating)) and value in {0, 1}:
        return bool(value)
    return True


def require_known_risk_bool(value: object, label: str, error_type=ValueError) -> bool:
    """Return a real boolean or reject evidence that erased its unknown state."""
    if _is_missing(value) or not isinstance(value, (bool, np.bool_)):
        raise error_type(f"{label} must be an explicit boolean")
    return bool(value)
