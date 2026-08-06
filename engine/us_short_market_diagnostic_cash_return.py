"""Knife 9: turn a captured FRED DGS3MO vintage into one week's PIT cash return.

The v1.1 attribution has a cash leg — the ``(1 - g*)`` half of the
exposure-matched benchmark — and nothing in the repo ever produced one, so the
weekly task passed ``None`` and every activated week would have reported
``unavailable``. This is that producer's offline half.

Why the series is read with a real-time pin
-------------------------------------------
FRED serves DGS3MO as a *revisable* view. A probe on 2026-08-06 showed the
revision is not in the numbers but in the ROWS: asked on 2026-06-22 the series
had no 2026-06-19 row at all, and asked today it has one carrying ``"."`` — the
Juneteenth holiday placeholder was added after the fact. A week's cash return
divides by the days it believes were in the week, so an unpinned read silently
recomputes history with information the decision could not have had. Every read
here is therefore pinned, and the observation this module picks must have been
PUBLISHED on or before the decision date, not merely dated before it.

That second rule is stricter than the consumer's gate, which only asks that
``available_at`` not be after the decision date. It has to be: the consumer can
only judge the timestamp it is handed, and choosing which observation to hand it
is exactly this module's job.

``"."`` is not zero. A holiday, or a value the Fed has not published yet, steps
back to the previous observation inside the window; when the whole window is
empty the week is ``unavailable`` and says why.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import re
from typing import Any

CAPTURE_SCHEMA_NAME = "us_short_market_diagnostic_cash_capture"
CAPTURE_SCHEMA_VERSION = "1.0.0"
SERIES_ID = "DGS3MO"
INSTRUMENT = "pit_3m_tbill"
VENDOR = "fred"

FETCH_OK = "ok"
FETCH_FAILED = "failed"

# The canonical week the attribution report compounds a cash return for, and the
# day count the consumer annualises it back over. Divergence here would be
# invisible: the number would simply be wrong by a constant.
_WEEK_DAYS = 7
_DAYS_PER_YEAR = 365
# How far back to look for a published rate before giving up on the week. A
# T-bill rate three weeks stale is not this week's rate, and the consumer's
# effective-period bound refuses a span beyond 21 days anyway.
_MAX_LOOKBACK_DAYS = 21

MISSING_VALUE = "."

_DATE8 = re.compile(r"^[0-9]{8}$")
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RATE = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")

REASON_NO_PUBLISHED_RATE = "pit_3m_tbill_not_published_by_decision_date"
REASON_FETCH_FAILED = "pit_3m_tbill_fetch_failed"


class CashReturnError(Exception):
    """A capture that cannot be trusted, or a request that cannot be answered."""


def _fail(message: str) -> None:
    raise CashReturnError(message)


def _date8(value: object, field: str) -> date:
    if not isinstance(value, str) or _DATE8.fullmatch(value) is None:
        _fail(f"{field} must be YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").date()  # type: ignore[arg-type]
    except ValueError as exc:
        raise CashReturnError(f"{field} is not a real date") from exc


def _iso_date(value: object, field: str) -> date:
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        _fail(f"{field} must be YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()  # type: ignore[arg-type]
    except ValueError as exc:
        raise CashReturnError(f"{field} is not a real date") from exc


def validate_cash_capture(capture: object, *, as_of_date: str | None = None) -> dict[str, Any]:
    """Validate one landed FRED capture and return it unchanged."""

    if not isinstance(capture, Mapping):
        _fail("cash capture must be an object")
    if capture.get("schema_name") != CAPTURE_SCHEMA_NAME:
        _fail(f"cash capture schema_name is not {CAPTURE_SCHEMA_NAME}")
    if capture.get("schema_version") != CAPTURE_SCHEMA_VERSION:
        _fail(f"cash capture schema_version is not {CAPTURE_SCHEMA_VERSION}")
    if capture.get("series_id") != SERIES_ID:
        _fail(f"cash capture must be {SERIES_ID}, got {capture.get('series_id')!r}")
    if not isinstance(capture.get("vendor"), str) or not capture["vendor"]:
        _fail("cash capture must name its vendor")
    status = capture.get("fetch_status")
    if status not in {FETCH_OK, FETCH_FAILED}:
        _fail(f"cash capture fetch_status must be {FETCH_OK!r} or {FETCH_FAILED!r}")
    observed = capture.get("observed_at")
    if not isinstance(observed, str) or not observed.endswith("Z"):
        _fail("cash capture observed_at must be a UTC timestamp ending in Z")
    # The pin is the whole point of the capture: an unpinned read is a different
    # measurement, so a capture that cannot name its vintage cannot be used.
    pin = capture.get("vintage_realtime_date")
    if status == FETCH_OK and pin is None:
        _fail("an ok cash capture must record the real-time date it was pinned to")
    if pin is not None:
        _iso_date(pin, "cash capture vintage_realtime_date")
    observations = capture.get("observations")
    if not isinstance(observations, list):
        _fail("cash capture observations must be a list")
    if status == FETCH_FAILED and observations:
        _fail("cash capture claims the fetch failed but carries observations")
    as_of = _date8(as_of_date, "as_of_date") if as_of_date is not None else None
    if as_of is not None and pin is not None and _iso_date(pin, "pin") > as_of:
        _fail("cash capture is pinned to a real-time date after as_of_date")
    seen: set[str] = set()
    previous: date | None = None
    for index, raw in enumerate(observations):
        field = f"cash capture observations[{index}]"
        if not isinstance(raw, Mapping):
            _fail(f"{field} must be an object")
        day = _date8(raw.get("date"), f"{field}.date")
        if raw["date"] in seen:
            _fail(f"{field}.date is repeated")
        seen.add(raw["date"])
        if previous is not None and day <= previous:
            _fail(f"{field}.date must be strictly increasing")
        previous = day
        if as_of is not None and day > as_of:
            _fail(f"{field}.date is after as_of_date")
        value = raw.get("value")
        if not isinstance(value, str) or (value != MISSING_VALUE and _RATE.fullmatch(value) is None):
            _fail(f"{field}.value must be a decimal string or {MISSING_VALUE!r}")
        published = raw.get("first_published")
        if value == MISSING_VALUE:
            if published is not None:
                _fail(f"{field} has no rate, so it cannot have been published")
        else:
            if published is None:
                _fail(f"{field} carries a rate with no publication date")
            published_day = _iso_date(published, f"{field}.first_published")
            if published_day < day:
                _fail(f"{field} claims it was published before the day it measures")
            if as_of is not None and published_day > as_of:
                _fail(f"{field}.first_published is after as_of_date")
    return dict(capture)


def _weekly_return(rate_percent: str, field: str) -> float:
    """Percent per annum, bond-equivalent, into one canonical week.

    DGS3MO is a constant-maturity yield, so this is a plain linear conversion.
    The discount-basis sibling (DTB3) would need a different one, which is why
    the series id is pinned rather than passed in.
    """

    try:
        rate = Decimal(rate_percent)
    except InvalidOperation as exc:
        raise CashReturnError(f"{field} is not a decimal rate") from exc
    if not rate.is_finite():
        _fail(f"{field} is not a finite rate")
    return float(rate / Decimal(100) * Decimal(_WEEK_DAYS) / Decimal(_DAYS_PER_YEAR))


def _unavailable(reasons: list[str]) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "instrument": INSTRUMENT,
        "weekly_return": None,
        "effective_start_date": None,
        "effective_end_date": None,
        "as_of_date": None,
        "available_at": None,
        "source_sha256": None,
        "source_refs": [],
        "data_quality_reasons": reasons,
    }


def build_cash_observation(
    *,
    capture: Mapping[str, Any],
    capture_sha256: str,
    valuation_date: str,
    decision_date: str,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Pick this week's rate out of a captured vintage and shape the observation."""

    if not isinstance(capture_sha256, str) or _SHA256.fullmatch(capture_sha256) is None:
        _fail("capture_sha256 must be a lowercase sha256")
    valuation = _date8(valuation_date, "valuation_date")
    decision = _date8(decision_date, "decision_date")
    if valuation > decision:
        _fail("valuation_date cannot be after decision_date")
    validated = validate_cash_capture(capture, as_of_date=as_of_date)
    if validated["fetch_status"] == FETCH_FAILED:
        return _unavailable([REASON_FETCH_FAILED])

    earliest = valuation - timedelta(days=_MAX_LOOKBACK_DAYS)
    chosen: Mapping[str, Any] | None = None
    for raw in reversed(validated["observations"]):
        day = _date8(raw["date"], "observation.date")
        if day > valuation or day < earliest:
            continue
        if raw["value"] == MISSING_VALUE:
            # A holiday, or a day the Fed has not published. Step back; never zero.
            continue
        if _iso_date(raw["first_published"], "observation.first_published") > decision:
            # Dated before the decision but not yet PUBLISHED when it was made.
            # Using it would be look-ahead wearing a plausible date.
            continue
        chosen = raw
        break
    if chosen is None:
        return _unavailable([REASON_NO_PUBLISHED_RATE])

    weekly_return = _weekly_return(chosen["value"], "observation.value")
    return {
        "status": "evaluable",
        "instrument": INSTRUMENT,
        "weekly_return": weekly_return,
        # The consumer's two containment checks together force the end of the
        # effective period to be the valuation date exactly, so this is not a
        # choice; the start is one canonical week before it, which is the interval
        # the return was converted for.
        "effective_start_date": (valuation - timedelta(days=_WEEK_DAYS)).strftime("%Y%m%d"),
        "effective_end_date": valuation.strftime("%Y%m%d"),
        "as_of_date": chosen["date"],
        # End of the publication day rather than its start: the vendor gives a
        # date, not a time, and claiming midnight would assert the rate was in
        # hand earlier than it can be shown to have been.
        "available_at": f"{chosen['first_published']}T23:59:59Z",
        "source_sha256": capture_sha256,
        "source_refs": [capture_sha256],
        "data_quality_reasons": [],
    }
