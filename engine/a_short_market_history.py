"""Coverage-reconciled historical series for A-short market-level statistics.

Queue row 22a.  Row 12 proved that summing whatever rows a provider happens to
return is a real-money defect: one session standing in for five flipped a
position gate in both directions.  A multi-year window is far likelier to be
missing a day than a five-session one, so every historical consumer -- the
margin percentile (row 19) and the northbound lookback (row 22b) -- reduces its
rows through this one reconciliation instead of trusting the response.

Pure and offline: this module issues no request, reads no environment, and
writes nothing.  Callers fetch; this decides whether what came back is usable.
"""

from __future__ import annotations

import math
import numbers
import re
from typing import Any, Iterable, Mapping, Sequence

_DATE8 = re.compile(r"^[0-9]{8}$")


def _is_finite_number(value: Any) -> bool:
    """Accept any real number, including numpy scalars.

    ``isinstance(value, (int, float))`` looks equivalent but is not: provider
    frames hand back ``numpy.int64`` and ``numpy.float32``, neither of which
    subclasses a Python builtin, so that form would silently reject a perfectly
    good window as "coverage incomplete" -- with no hint that the real cause was
    a dtype.  ``engine/a_short_northbound.py::_finite_number`` was moved to
    ``numbers.Real`` for exactly this reason; this module must not diverge.
    """
    return (
        not isinstance(value, bool)
        and isinstance(value, numbers.Real)
        and math.isfinite(float(value))
    )


def canonical_dates(dates: Iterable[Any]) -> tuple[str, ...]:
    """Normalise a requested window to unique 8-digit dates, newest first."""
    seen: set[str] = set()
    for value in dates or ():
        text = str(value).strip()
        if text.endswith(".0"):
            text = text[:-2]
        if not _DATE8.match(text):
            raise ValueError(f"requested window contains a non-date entry: {value!r}")
        seen.add(text)
    return tuple(sorted(seen, reverse=True))


def reconcile_dated_series(
    rows: Sequence[Mapping[str, Any]] | None,
    *,
    requested_dates: Iterable[Any],
    date_key: str = "trade_date",
    value_key: str,
) -> dict[str, Any]:
    """Return a dated series only when the response covers the window exactly.

    ``rows`` must be a list or tuple of mappings -- a DataFrame or a generator
    fails closed rather than being half-read, so callers convert explicitly
    (``frame.to_dict("records")``).

    Exact means all three of: the row count equals the requested count, the row
    count survives de-duplication, and the observed date set equals the
    requested set.  Anything else -- a short response, a duplicate session, an
    out-of-window row, an extra row, a non-finite value -- yields
    ``coverage_complete=False`` with no series.  There is deliberately no
    interpolation and no forward-fill: a gap must stay visible as a gap.
    """
    requested = canonical_dates(requested_dates)
    result: dict[str, Any] = {
        "series": None,
        "requested_count": len(requested),
        "observed_count": 0,
        "coverage_complete": False,
    }
    if not requested:
        return result
    if rows is None or isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        return result

    requested_set = set(requested)
    observed: dict[str, Any] = {}
    raw_dates: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            return result
        raw = str(row.get(date_key, "")).strip()
        if raw.endswith(".0"):
            raw = raw[:-2]
        raw_dates.append(raw)
        if _DATE8.match(raw) and raw in requested_set:
            observed[raw] = row.get(value_key)
    result["observed_count"] = len(observed)

    if len(raw_dates) != len(requested):
        return result
    if len(set(raw_dates)) != len(requested):
        return result
    if set(raw_dates) != requested_set:
        return result
    if any(not _is_finite_number(observed.get(date)) for date in requested):
        return result

    result["series"] = tuple((date, float(observed[date])) for date in requested)
    result["coverage_complete"] = True
    return result


def percentile_rank(series_values: Iterable[Any], current: Any) -> float | None:
    """Fraction of the window at or below ``current``, or None if unusable.

    Used by the margin-overheat percentile.  Returns None rather than a
    fabricated rank when the window or the current value is not fully finite,
    so a caller can only ever fail closed.
    """
    if not _is_finite_number(current):
        return None
    values = list(series_values or ())
    if not values or any(not _is_finite_number(value) for value in values):
        return None
    at_or_below = sum(1 for value in values if float(value) <= float(current))
    return at_or_below / len(values)
