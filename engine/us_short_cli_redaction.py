# -*- coding: utf-8 -*-
"""Small no-secret formatting helpers for US-short command-line boundaries."""
from __future__ import annotations


def safe_schema_location(path, *, allowed_roots) -> str:
    """Return only a schema-owned top-level container, never dynamic ticker/map keys."""
    parts = list(path)
    if not parts or not isinstance(parts[0], str) or parts[0] not in allowed_roots:
        return "$"
    return f"$.{parts[0]}"


def closed_world_counts(value, *, expected_keys) -> str:
    """Describe a top-level shape mismatch without echoing values or user-controlled keys."""
    if not isinstance(value, dict):
        return "expected_object"
    keys = set(value)
    return f"missing={len(expected_keys - keys)} extra={len(keys - expected_keys)}"
