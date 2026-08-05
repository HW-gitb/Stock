"""Offline validation and calculation for the Knife 5 ETF total-return sidecar.

The module accepts a source-bound sidecar and an already validated local price
observation.  It never fetches data, selects a provider, writes an account, or
changes the diagnostic/ship-gate boundary.  A complete sidecar upgrades one
ETF-week to ``total_return_evaluable``; an incomplete sidecar keeps the local
price return and records the degradation reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from engine.us_short_market_diagnostic import BENCHMARKS, construct_simple_return
from engine.us_short_model_paper_portfolio import canonical_json_bytes


ROOT = Path(__file__).resolve().parent.parent
SIDECAR_SCHEMA_PATH = ROOT / "schemas" / "us_short_market_diagnostic_etf_total_return_sidecar.schema.json"
_SIDECAR_SCHEMA = json.loads(SIDECAR_SCHEMA_PATH.read_text(encoding="utf-8"))
Draft7Validator.check_schema(_SIDECAR_SCHEMA)
_SIDECAR_VALIDATOR = Draft7Validator(_SIDECAR_SCHEMA)
_MONEY_QUANTUM = Decimal("0.000001")
_TOTAL_RETURN_COVERAGE = (
    "pagination_complete",
    "dividend_complete",
    "split_complete",
    "adjusted_unadjusted_reconciled",
)
_SOURCE_DIGEST_FIELDS = (
    "adjusted_price_sha256",
    "unadjusted_price_sha256",
    "dividend_sha256",
    "split_sha256",
    "raw_capture_sha256",
)


class TotalReturnSidecarError(ValueError):
    """Raised when a Knife 5 sidecar is malformed or cannot be reconciled safely."""


def _fail(message: str) -> None:
    raise TotalReturnSidecarError(message)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{field} must be an object")
    return value


def _date8(value: object, field: str, *, allow_none: bool = False) -> date | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or len(value) != 8 or not value.isascii() or not value.isdigit():
        _fail(f"{field} must be an ASCII YYYYMMDD date")
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError as exc:
        raise TotalReturnSidecarError(f"{field} is not a real calendar date") from exc


def _money(value: object, field: str, *, allow_none: bool = False, positive: bool = False) -> Decimal | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        _fail(f"{field} must be a six-decimal money string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise TotalReturnSidecarError(f"{field} must be a six-decimal money string") from exc
    if not parsed.is_finite() or parsed < 0 or (positive and parsed <= 0):
        _fail(f"{field} must be {'positive ' if positive else ''}finite money")
    if parsed.quantize(_MONEY_QUANTUM) != parsed:
        _fail(f"{field} must have exactly six decimal places")
    return parsed


def _sha(value: object, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        _fail(f"{field} must be a lowercase sha256")
    return value


def _observed_at(value: object, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        _fail(f"{field} must be an ISO timestamp or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TotalReturnSidecarError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(f"{field} must include a timezone")


def _schema_validate(sidecar: Mapping[str, Any]) -> None:
    errors = sorted(_SIDECAR_VALIDATOR.iter_errors(sidecar), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        _fail(f"total-return sidecar schema violation at {path}: {error.message}")


def _validate_event_dates(
    events: list[Mapping[str, Any]],
    *,
    prior_date: date | None,
    price_date: date | None,
    field: str,
) -> None:
    previous: date | None = None
    for index, event in enumerate(events):
        event_date = _date8(event["ex_date"], f"{field}[{index}].ex_date")
        assert event_date is not None
        if previous is not None and event_date < previous:
            _fail(f"{field} must be ordered by ex_date")
        if prior_date is not None and price_date is not None and not prior_date < event_date <= price_date:
            _fail(f"{field}[{index}].ex_date is outside its price interval")
        previous = event_date


def _validate_benchmark_sidecar(observation: Mapping[str, Any], field: str) -> set[str]:
    prior_date = _date8(observation["prior_price_date"], f"{field}.prior_price_date", allow_none=True)
    price_date = _date8(observation["price_date"], f"{field}.price_date", allow_none=True)
    if (prior_date is None) != (price_date is None):
        _fail(f"{field}.prior_price_date and price_date must be both present or both null")
    if prior_date is not None and price_date is not None and prior_date >= price_date:
        _fail(f"{field} price interval must be strictly increasing")

    dividend_events = [_mapping(event, f"{field}.dividend_events[{index}]") for index, event in enumerate(observation["dividend_events"])]
    for index, event in enumerate(dividend_events):
        cash = _money(event["cash_amount"], f"{field}.dividend_events[{index}].cash_amount", positive=True)
        adjusted = _money(
            event["split_adjusted_cash_amount"],
            f"{field}.dividend_events[{index}].split_adjusted_cash_amount",
            positive=True,
        )
        try:
            factor = Decimal(str(event["split_adjustment_factor"]))
        except (InvalidOperation, ValueError) as exc:
            raise TotalReturnSidecarError(
                f"{field}.dividend_events[{index}].split_adjustment_factor must be finite"
            ) from exc
        if not factor.is_finite() or factor <= 0:
            _fail(f"{field}.dividend_events[{index}].split_adjustment_factor must be positive")
        assert cash is not None and adjusted is not None
        if (cash * factor).quantize(_MONEY_QUANTUM) != adjusted:
            _fail(f"{field}.dividend_events[{index}] split-adjusted cash does not match its factor")
        _sha(event["source_sha256"], f"{field}.dividend_events[{index}].source_sha256")
    _validate_event_dates(dividend_events, prior_date=prior_date, price_date=price_date, field=f"{field}.dividend_events")

    split_events = [_mapping(event, f"{field}.split_events[{index}]") for index, event in enumerate(observation["split_events"])]
    for index, event in enumerate(split_events):
        split_from = float(event["split_from"])
        split_to = float(event["split_to"])
        if split_from <= 0 or split_to <= 0 or split_from == split_to:
            _fail(f"{field}.split_events[{index}] must contain a changing positive ratio")
        _sha(event["source_sha256"], f"{field}.split_events[{index}].source_sha256")
    _validate_event_dates(split_events, prior_date=prior_date, price_date=price_date, field=f"{field}.split_events")

    coverage = _mapping(observation["coverage"], f"{field}.coverage")
    source_binding = _mapping(observation["source_binding"], f"{field}.source_binding")
    for name in _SOURCE_DIGEST_FIELDS:
        _sha(source_binding[name], f"{field}.source_binding.{name}", allow_none=True)
    _date8(source_binding["source_date"], f"{field}.source_binding.source_date", allow_none=True)
    _observed_at(source_binding["observed_at"], f"{field}.source_binding.observed_at")
    reasons = observation["data_quality_reasons"]
    coverage_requirements = {
        "pagination_complete": "raw_capture_sha256",
        "dividend_complete": "dividend_sha256",
        "split_complete": "split_sha256",
        "adjusted_unadjusted_reconciled": "adjusted_price_sha256",
    }
    for coverage_name, digest_name in coverage_requirements.items():
        if coverage[coverage_name] and source_binding[digest_name] is None:
            _fail(f"{field} {coverage_name} requires source_binding.{digest_name}")
    if coverage["adjusted_unadjusted_reconciled"] and source_binding["unadjusted_price_sha256"] is None:
        _fail(f"{field} adjusted_unadjusted_reconciled requires unadjusted_price_sha256")
    if all(coverage[name] for name in _TOTAL_RETURN_COVERAGE):
        if prior_date is None or price_date is None:
            _fail(f"{field} complete coverage requires a price interval")
        if any(source_binding[name] is None for name in _SOURCE_DIGEST_FIELDS):
            _fail(f"{field} complete coverage requires all source digests")
        if source_binding["source_date"] is None or source_binding["observed_at"] is None:
            _fail(f"{field} complete coverage requires source_date and observed_at")
        if reasons:
            _fail(f"{field} complete coverage cannot carry degradation reasons")
    elif not reasons:
        _fail(f"{field} incomplete coverage requires a data quality reason")

    digests = {
        digest
        for name in _SOURCE_DIGEST_FIELDS
        if (digest := source_binding[name]) is not None
    }
    digests.update(event["source_sha256"] for event in [*dividend_events, *split_events])
    return digests


def validate_etf_total_return_sidecar(sidecar: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a four-ETF sidecar and return a shallow copy without mutating it."""

    sidecar = _mapping(sidecar, "total_return_sidecar")
    _schema_validate(sidecar)
    if sidecar["benchmark_symbols"] != list(BENCHMARKS):
        _fail("total_return_sidecar.benchmark_symbols must be exactly VTI/IWB/SPY/QQQ")
    source_refs = set(sidecar["source_refs"])
    previous_index: int | None = None
    previous_valuation: date | None = None
    observed_digests: set[str] = set()
    for index, raw_week in enumerate(sidecar["weeks"]):
        week = _mapping(raw_week, f"total_return_sidecar.weeks[{index}]")
        week_index = week["calendar_week_index"]
        if previous_index is not None and week_index != previous_index + 1:
            _fail("total_return_sidecar weeks must be consecutive and ordered")
        valuation = _date8(week["valuation_date"], f"weeks[{index}].valuation_date")
        assert valuation is not None
        if previous_valuation is not None and valuation <= previous_valuation:
            _fail("total_return_sidecar valuation dates must be strictly increasing")
        for symbol in BENCHMARKS:
            observed_digests.update(
                _validate_benchmark_sidecar(
                    _mapping(week["benchmarks"][symbol], f"weeks[{index}].benchmarks.{symbol}"),
                    f"weeks[{index}].benchmarks.{symbol}",
                )
            )
        previous_index = week_index
        previous_valuation = valuation
    if not observed_digests.issubset(source_refs):
        _fail("total_return_sidecar.source_refs must bind every source digest used by its weeks")
    return dict(sidecar)


def sidecar_observation_sha256(observation: Mapping[str, Any]) -> str:
    """Return the stable digest stored in a weekly record for one sidecar observation."""

    try:
        payload = canonical_json_bytes(dict(observation))
    except Exception as exc:  # pragma: no cover - canonical_json_bytes owns its contract
        raise TotalReturnSidecarError("sidecar observation cannot be canonicalized") from exc
    return hashlib.sha256(payload).hexdigest()


def _price_money(value: object, field: str, *, allow_none: bool = False) -> Decimal | None:
    return _money(value, field, allow_none=allow_none)


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def build_total_return_benchmark_observation(
    *,
    sidecar_observation: Mapping[str, Any],
    price_observation: Mapping[str, Any],
    strategy_evaluable: bool,
    strategy_weekly_return: float | None,
) -> dict[str, Any]:
    """Build the existing weekly benchmark shape from one sidecar and one price observation."""

    sidecar = _mapping(sidecar_observation, "sidecar_observation")
    price = _mapping(price_observation, "price_observation")
    try:
        _validate_benchmark_sidecar(sidecar, "sidecar_observation")
    except (KeyError, TypeError, IndexError) as exc:
        raise TotalReturnSidecarError("sidecar_observation is not a valid ETF sidecar observation") from exc
    sidecar_digest = sidecar_observation_sha256(sidecar)
    prior_close = _price_money(price.get("prior_close"), "price_observation.prior_close", allow_none=True)
    close = _price_money(price.get("close"), "price_observation.close", allow_none=True)
    price_date = _date8(price.get("price_date"), "price_observation.price_date", allow_none=True)
    source_sha = _sha(price.get("source_sha256"), "price_observation.source_sha256", allow_none=True)
    sidecar_price_date = _date8(sidecar.get("price_date"), "sidecar_observation.price_date", allow_none=True)
    sidecar_prior_date = _date8(
        sidecar.get("prior_price_date"),
        "sidecar_observation.prior_price_date",
        allow_none=True,
    )
    reasons = list(sidecar["data_quality_reasons"])
    price_evaluable = prior_close is not None and close is not None
    date_bound = (
        sidecar_price_date == price_date
        and sidecar_prior_date is not None
        and price_date is not None
    )
    complete = all(sidecar["coverage"][name] for name in _TOTAL_RETURN_COVERAGE)
    if not price_evaluable:
        weekly_return = None
        return_quality = "unavailable"
        _append_reason(reasons, "price_missing" if close is None else "prior_price_missing")
    elif complete and date_bound:
        dividend_total = sum(
            (
                _money(
                    event["split_adjusted_cash_amount"],
                    "sidecar_observation.dividend_events.split_adjusted_cash_amount",
                    positive=True,
                )
                for event in sidecar["dividend_events"]
            ),
            Decimal("0.000000"),
        )
        assert prior_close is not None and close is not None
        weekly_return = float((close + dividend_total) / prior_close - Decimal("1"))
        return_quality = "total_return_evaluable"
        reasons = []
    else:
        assert prior_close is not None and close is not None
        weekly_return = construct_simple_return(float(prior_close), float(close), field="benchmark.close")
        return_quality = "price_return_diagnostic"
        _append_reason(reasons, "dividend_sidecar_not_reconciled")
        if complete and not date_bound:
            _append_reason(reasons, "sidecar_price_date_mismatch")

    benchmark_evaluable = price_evaluable
    joint_evaluable = bool(strategy_evaluable and benchmark_evaluable)
    raw_excess = (
        strategy_weekly_return - weekly_return
        if joint_evaluable and strategy_weekly_return is not None and weekly_return is not None
        else None
    )
    relative_wealth = (
        (1.0 + strategy_weekly_return) / (1.0 + weekly_return) - 1.0
        if joint_evaluable and strategy_weekly_return is not None and weekly_return is not None
        else None
    )
    return {
        "return_quality": return_quality,
        "benchmark_evaluable": benchmark_evaluable,
        "joint_evaluable": joint_evaluable,
        "weekly_return": weekly_return,
        "cumulative_return": None,
        "raw_excess": raw_excess,
        "relative_wealth": relative_wealth,
        "price_date": price["price_date"],
        "price_source": price.get("source_kind"),
        "price_packet_sha256": source_sha,
        "dividend_sidecar_sha256": sidecar_digest,
        "data_quality_reasons": reasons,
    }


def sidecar_week(sidecar: Mapping[str, Any], calendar_week_index: int) -> Mapping[str, Any]:
    """Return one validated sidecar week by calendar index."""

    validated = validate_etf_total_return_sidecar(sidecar)
    for week in validated["weeks"]:
        if week["calendar_week_index"] == calendar_week_index:
            return week
    _fail(f"total_return_sidecar has no calendar week {calendar_week_index}")


__all__ = [
    "TotalReturnSidecarError",
    "build_total_return_benchmark_observation",
    "sidecar_observation_sha256",
    "sidecar_week",
    "validate_etf_total_return_sidecar",
]
