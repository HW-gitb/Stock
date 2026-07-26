"""Dependency-free JSON-schema format checks shared by the US-short discovery lane."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from jsonschema import FormatChecker


# The fraction is bounded: `fromisoformat` truncates beyond microseconds, and an
# unbounded fraction would be copied verbatim into a persisted artifact.
_RFC3339_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})")


FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("date-time")
def is_rfc3339_date_time(value: Any) -> bool:
    """Require a real RFC 3339 instant, not merely something `fromisoformat` can parse.

    `fromisoformat` accepts a space/tab/NUL/any single character as the date-time separator,
    `+0000` offsets, comma decimals and `+00:00:30`; those strings are copied VERBATIM into the
    persisted validation artifact, so the shape gate has to mean what its name says (K3-R48).
    The accepted set is exactly what this lane's parsers accept: `T`, an optional fractional
    second, and either `Z` or a `±HH:MM` offset.
    """
    if not isinstance(value, str):
        return True  # JSON Schema's separate type check supplies this rejection.
    if _RFC3339_RE.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except (ValueError, OverflowError):
        return False
    return parsed.tzinfo is not None
