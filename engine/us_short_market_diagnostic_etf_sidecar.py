"""Pure builder for one source-bound Knife 5 ETF sidecar week.

Provider access belongs to the weekly gated runner.  This module only turns the
four already-captured Massive endpoint families for each ETF into the existing
total-return sidecar contract.  A family that is absent, incomplete, or cannot
be reconciled makes that ETF's week price-only; it never invents a dividend.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal, DecimalException, InvalidOperation
import hashlib
import json
import math
from typing import Any

from engine.us_short_market_diagnostic import BENCHMARKS, window_containing_week


FAMILIES = ("dividends", "splits", "daily_adjusted", "daily_unadjusted")
EVENT_FAMILIES = frozenset(("dividends", "splits"))
_MONEY_QUANTUM = Decimal("0.000001")
_FACTOR_QUANTUM = Decimal("0.000001")
_SHA256_LENGTH = 64


class EtfSidecarProducerError(ValueError):
    """Raised when a sidecar cannot be assembled without guessing."""


def _fail(message: str) -> None:
    raise EtfSidecarProducerError(message)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _digest(value: object, field: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(char not in "0123456789abcdef" for char in value)
    ):
        _fail(f"{field} must be a lowercase sha256 or null")
    return value


def _date(value: object, field: str, *, allow_none: bool = False) -> date | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        _fail(f"{field} must be YYYYMMDD or YYYY-MM-DD")
    normalized = value.replace("-", "") if len(value) == 10 else value
    if len(normalized) != 8 or not normalized.isascii() or not normalized.isdigit():
        _fail(f"{field} must be YYYYMMDD or YYYY-MM-DD")
    try:
        return date(int(normalized[:4]), int(normalized[4:6]), int(normalized[6:8]))
    except ValueError as exc:
        raise EtfSidecarProducerError(f"{field} is not a real date") from exc


def _date8(value: date) -> str:
    return value.strftime("%Y%m%d")


def _row_date(row: object, family: str, field: str) -> date | None:
    if not isinstance(row, Mapping):
        return None
    date_fields = {
        "dividends": ("ex_dividend_date",),
        "splits": ("execution_date",),
        "daily_adjusted": ("session_date", "date"),
        "daily_unadjusted": ("session_date", "date"),
    }[family]
    for name in date_fields:
        try:
            parsed = _date(row.get(name), f"{field}.{name}", allow_none=True)
        except EtfSidecarProducerError:
            parsed = None
        if parsed is not None:
            return parsed
    timestamp = row.get("t", row.get("timestamp"))
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return None
    try:
        number = float(timestamp)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    seconds = number / 1000 if abs(number) > 10_000_000_000 else number
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def _money(value: object, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _fail(f"{field} must be a finite money value")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EtfSidecarProducerError(f"{field} must be a finite money value") from exc
    if not parsed.is_finite() or parsed < 0 or (positive and parsed <= 0):
        _fail(f"{field} must be {'positive ' if positive else ''}finite money")
    try:
        quantized = parsed.quantize(_MONEY_QUANTUM)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise EtfSidecarProducerError(f"{field} is not representable at six decimals") from exc
    if quantized != parsed:
        _fail(f"{field} must have at most six decimal places")
    return quantized


def _positive_number(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _fail(f"{field} must be a positive finite number")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EtfSidecarProducerError(f"{field} must be a positive finite number") from exc
    if not parsed.is_finite() or parsed <= 0:
        _fail(f"{field} must be a positive finite number")
    return parsed


def _finite_float(value: Decimal, field: str) -> float:
    try:
        converted = float(value)
    except (OverflowError, ValueError) as exc:
        raise EtfSidecarProducerError(f"{field} is not representable as a finite number") from exc
    if not math.isfinite(converted) or converted <= 0:
        _fail(f"{field} is not representable as a finite positive number")
    return converted


def _money_text(value: Decimal) -> str:
    return f"{value:f}"


def _capture_rows(capture: Mapping[str, Any], field: str) -> list[Any]:
    rows = capture.get("rows")
    if not isinstance(rows, list):
        _fail(f"{field}.rows must be a list")
    return rows


def _family_complete(capture: Mapping[str, Any], family: str) -> bool:
    status = capture.get("status")
    success_pages = capture.get("http_success_pages")
    return (
        capture.get("pagination_complete") is True
        # A broad-market ETF's full dividend history cannot safely be inferred
        # from an empty/unreadable endpoint body.  Splits may legitimately be
        # absent, but a dividend family needs positive coverage evidence before
        # it can participate in a total-return upgrade.
        and (status == "covered" or (family != "dividends" and status == "empty"))
        and type(success_pages) is int
        and success_pages > 0
    )


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _family_failure_reasons(
    capture: Mapping[str, Any],
    family: str,
    reasons: list[str],
) -> None:
    if capture.get("pagination_complete") is not True:
        _append_reason(reasons, "pagination_incomplete")
    if not _family_complete(capture, family):
        label = {
            "dividends": "dividend",
            "splits": "split",
            "daily_adjusted": "adjusted_price",
            "daily_unadjusted": "unadjusted_price",
        }[family]
        _append_reason(reasons, f"{label}_endpoint_incomplete")
    if capture.get("status") == "unreadable_body":
        _append_reason(reasons, f"{label}_body_unreadable")
    if family == "dividends" and capture.get("status") in {"empty", "unreadable_body"}:
        _append_reason(reasons, "dividend_history_empty_or_unreadable")


def _dividend_events(
    capture: Mapping[str, Any],
    *,
    prior_date: date | None,
    price_date: date | None,
    source_digest: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    rows = _capture_rows(capture, "dividends")
    if prior_date is None or price_date is None:
        return [], False
    invalid = False
    events: list[dict[str, Any]] = []
    events_by_date: dict[date, tuple[Decimal, Decimal, Decimal]] = {}
    for index, row in enumerate(rows):
        event_date = _row_date(row, "dividends", f"dividends.rows[{index}]")
        if event_date is None:
            invalid = True
            continue
        if not prior_date < event_date <= price_date:
            continue
        if not isinstance(row, Mapping):
            invalid = True
            continue
        try:
            cash = _money(row.get("cash_amount"), f"dividends.rows[{index}].cash_amount", positive=True)
            adjusted_cash = _money(
                row.get("split_adjusted_cash_amount"),
                f"dividends.rows[{index}].split_adjusted_cash_amount",
                positive=True,
            )
            raw_factor = row.get("historical_adjustment_factor")
            if raw_factor is None:
                factor = (adjusted_cash / cash).quantize(_FACTOR_QUANTUM)
            else:
                factor = _positive_number(raw_factor, f"dividends.rows[{index}].historical_adjustment_factor")
            if (cash * factor).quantize(_MONEY_QUANTUM) != adjusted_cash:
                invalid = True
                continue
            factor_float = _finite_float(
                factor,
                f"dividends.rows[{index}].historical_adjustment_factor",
            )
        except (EtfSidecarProducerError, DecimalException, ValueError, OverflowError):
            invalid = True
            continue
        if source_digest is None:
            invalid = True
            continue
        event_key = (cash, adjusted_cash, factor)
        previous = events_by_date.get(event_date)
        if previous is not None:
            if previous != event_key:
                invalid = True
            continue
        events_by_date[event_date] = event_key
        events.append(
            {
                "ex_date": _date8(event_date),
                "cash_amount": _money_text(cash),
                "split_adjustment_factor": factor_float,
                "split_adjusted_cash_amount": _money_text(adjusted_cash),
                "source_sha256": source_digest,
            }
        )
    return sorted(events, key=lambda row: row["ex_date"]), not invalid


def _split_events(
    capture: Mapping[str, Any],
    *,
    prior_date: date | None,
    price_date: date | None,
    source_digest: str | None,
) -> tuple[list[dict[str, Any]], bool]:
    rows = _capture_rows(capture, "splits")
    if prior_date is None or price_date is None:
        return [], False
    invalid = False
    events: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        event_date = _row_date(row, "splits", f"splits.rows[{index}]")
        if event_date is None:
            invalid = True
            continue
        if not prior_date < event_date <= price_date:
            continue
        if not isinstance(row, Mapping):
            invalid = True
            continue
        try:
            split_from = _positive_number(row.get("split_from"), f"splits.rows[{index}].split_from")
            split_to = _positive_number(row.get("split_to"), f"splits.rows[{index}].split_to")
            split_from_float = _finite_float(split_from, f"splits.rows[{index}].split_from")
            split_to_float = _finite_float(split_to, f"splits.rows[{index}].split_to")
        except EtfSidecarProducerError:
            invalid = True
            continue
        if split_from == split_to or source_digest is None:
            invalid = True
            continue
        events.append(
            {
                "ex_date": _date8(event_date),
                "split_from": split_from_float,
                "split_to": split_to_float,
                "source_sha256": source_digest,
            }
        )
    return sorted(events, key=lambda row: row["ex_date"]), not invalid


def _daily_dates(capture: Mapping[str, Any], family: str) -> tuple[set[date], bool]:
    rows = _capture_rows(capture, family)
    seen: set[date] = set()
    valid = True
    for index, row in enumerate(rows):
        parsed = _row_date(row, family, f"{family}.rows[{index}]")
        if parsed is None or parsed in seen or not isinstance(row, Mapping):
            valid = False
            continue
        seen.add(parsed)
        try:
            _positive_number(row.get("c"), f"{family}.rows[{index}].c")
        except EtfSidecarProducerError:
            valid = False
    return seen, valid


def _daily_close_values(capture: Mapping[str, Any], family: str) -> dict[date, Decimal] | None:
    rows = _capture_rows(capture, family)
    values: dict[date, Decimal] = {}
    for index, row in enumerate(rows):
        parsed = _row_date(row, family, f"{family}.rows[{index}]")
        if parsed is None or not isinstance(row, Mapping) or parsed in values:
            return None
        try:
            values[parsed] = _positive_number(row.get("c"), f"{family}.rows[{index}].c")
        except EtfSidecarProducerError:
            return None
    return values


def _daily_prices_reconciled(
    adjusted_capture: Mapping[str, Any],
    unadjusted_capture: Mapping[str, Any],
    *,
    split_events: list[dict[str, Any]],
) -> bool:
    if split_events:
        return True
    adjusted = _daily_close_values(adjusted_capture, "daily_adjusted")
    unadjusted = _daily_close_values(unadjusted_capture, "daily_unadjusted")
    if adjusted is None or unadjusted is None or set(adjusted) != set(unadjusted):
        return False
    return all(
        abs(adjusted[session] - unadjusted[session]) <= _MONEY_QUANTUM
        for session in adjusted
    )


def _intervals(value: Mapping[str, Any]) -> tuple[date | None, date | None, bool]:
    if not isinstance(value, Mapping):
        _fail("price_intervals entries must be objects")
    if set(value) != {"prior_price_date", "price_date"}:
        _fail("price_intervals must contain prior_price_date and price_date for every symbol")
    prior = _date(value["prior_price_date"], "price_intervals.prior_price_date", allow_none=True)
    price = _date(value["price_date"], "price_intervals.price_date", allow_none=True)
    if (prior is None) != (price is None):
        # The local packet deliberately represents a half-missing price pair.
        # A sidecar cannot source-bind events to that span, so normalize only
        # the sidecar's own observation to unavailable rather than aborting the
        # other three ETFs.
        return None, None, True
    if prior is not None and price is not None and prior >= price:
        _fail("price_intervals must be strictly increasing")
    return prior, price, False


def build_etf_total_return_sidecar_week(
    *,
    captures: Mapping[str, Mapping[str, Mapping[str, Any]]],
    price_intervals: Mapping[str, Mapping[str, Any]],
    calendar_week_index: int,
    valuation_date: str,
    diagnostic_epoch: str,
    observed_at: str,
) -> dict[str, Any]:
    """Build one week from normalized endpoint captures.

    ``captures`` is deliberately exact: every ETF and every endpoint family
    must be represented.  The caller cannot silently omit a symbol or turn an
    absent family into a successful total-return observation.
    """

    if set(captures) != set(BENCHMARKS):
        _fail(f"captures must name exactly {', '.join(BENCHMARKS)}")
    if set(price_intervals) != set(BENCHMARKS):
        _fail(f"price_intervals must name exactly {', '.join(BENCHMARKS)}")
    if type(calendar_week_index) is not int or calendar_week_index < 1:
        _fail("calendar_week_index must be a positive integer")
    valuation = _date(valuation_date, "valuation_date")
    if not isinstance(diagnostic_epoch, str) or not diagnostic_epoch:
        _fail("diagnostic_epoch must be a non-empty string")
    if not isinstance(observed_at, str) or not observed_at:
        _fail("observed_at must be a non-empty ISO timestamp")

    source_refs: set[str] = set()
    benchmark_rows: dict[str, dict[str, Any]] = {}
    for symbol in BENCHMARKS:
        symbol_captures = captures[symbol]
        if set(symbol_captures) != set(FAMILIES):
            _fail(f"captures[{symbol}] must contain exactly {', '.join(FAMILIES)}")
        prior_date, price_date, price_interval_partial = _intervals(price_intervals[symbol])
        reasons: list[str] = []
        if price_interval_partial:
            _append_reason(reasons, "price_interval_partial")
        family_digests: dict[str, str | None] = {}
        for family in FAMILIES:
            capture = symbol_captures[family]
            if not isinstance(capture, Mapping):
                _fail(f"captures[{symbol}][{family}] must be an object")
            family_digests[family] = _digest(
                capture.get("source_sha256"), f"captures[{symbol}][{family}].source_sha256"
            )
            if family_digests[family] is not None:
                source_refs.add(family_digests[family])
            _family_failure_reasons(capture, family, reasons)
            error_types = capture.get("error_types")
            if isinstance(error_types, list):
                for error_type in error_types:
                    if isinstance(error_type, str) and error_type:
                        _append_reason(reasons, error_type)

        raw_capture_digest = _sha256({"symbol": symbol, "families": family_digests})
        source_refs.add(raw_capture_digest)
        if any(value is None for value in family_digests.values()):
            _append_reason(reasons, "source_binding_incomplete")

        if prior_date is None or price_date is None:
            _append_reason(reasons, "price_interval_unavailable")
        dividend_events, dividend_rows_valid = _dividend_events(
            symbol_captures["dividends"],
            prior_date=prior_date,
            price_date=price_date,
            source_digest=family_digests["dividends"],
        )
        split_events, split_rows_valid = _split_events(
            symbol_captures["splits"],
            prior_date=prior_date,
            price_date=price_date,
            source_digest=family_digests["splits"],
        )
        if not dividend_rows_valid:
            _append_reason(reasons, "dividend_event_reconciliation_failed")
        if not split_rows_valid:
            _append_reason(reasons, "split_event_reconciliation_failed")

        adjusted_dates, adjusted_valid = _daily_dates(
            symbol_captures["daily_adjusted"], "daily_adjusted"
        )
        unadjusted_dates, unadjusted_valid = _daily_dates(
            symbol_captures["daily_unadjusted"], "daily_unadjusted"
        )
        price_dates_present = (
            prior_date is not None
            and price_date is not None
            and prior_date in adjusted_dates
            and price_date in adjusted_dates
            and prior_date in unadjusted_dates
            and price_date in unadjusted_dates
        )
        adjusted_unadjusted_reconciled = (
            _family_complete(symbol_captures["daily_adjusted"], "daily_adjusted")
            and _family_complete(symbol_captures["daily_unadjusted"], "daily_unadjusted")
            and adjusted_valid
            and unadjusted_valid
            and adjusted_dates == unadjusted_dates
            and price_dates_present
            and _daily_prices_reconciled(
                symbol_captures["daily_adjusted"],
                symbol_captures["daily_unadjusted"],
                split_events=split_events,
            )
        )
        if not adjusted_unadjusted_reconciled:
            _append_reason(reasons, "adjusted_unadjusted_not_reconciled")

        pagination_complete = all(
            symbol_captures[family].get("pagination_complete") is True for family in FAMILIES
        )
        dividend_complete = (
            _family_complete(symbol_captures["dividends"], "dividends")
            and dividend_rows_valid
            and prior_date is not None
            and price_date is not None
        )
        split_complete = (
            _family_complete(symbol_captures["splits"], "splits")
            and split_rows_valid
            and prior_date is not None
            and price_date is not None
        )
        coverage = {
            "pagination_complete": pagination_complete,
            "dividend_complete": dividend_complete,
            "split_complete": split_complete,
            "adjusted_unadjusted_reconciled": adjusted_unadjusted_reconciled,
        }
        source_date = _date8(price_date) if price_date is not None else None
        benchmark_rows[symbol] = {
            "prior_price_date": _date8(prior_date) if prior_date is not None else None,
            "price_date": _date8(price_date) if price_date is not None else None,
            "dividend_events": dividend_events,
            "split_events": split_events,
            "coverage": coverage,
            "source_binding": {
                "adjusted_price_sha256": family_digests["daily_adjusted"],
                "unadjusted_price_sha256": family_digests["daily_unadjusted"],
                "dividend_sha256": family_digests["dividends"],
                "split_sha256": family_digests["splits"],
                "raw_capture_sha256": raw_capture_digest,
                "source_date": source_date,
                "observed_at": observed_at,
            },
            "data_quality_reasons": sorted(set(reasons)),
        }
        source_refs.update(event["source_sha256"] for event in [*dividend_events, *split_events])

    window = window_containing_week(calendar_week_index)
    return {
        "schema_name": "us_short_market_diagnostic_etf_total_return_sidecar",
        "schema_version": "1.0.0",
        "window_id": window["window_id"],
        "diagnostic_epoch": diagnostic_epoch,
        "price_basis": "split_adjusted_close",
        "benchmark_symbols": list(BENCHMARKS),
        "weeks": [
            {
                "calendar_week_index": calendar_week_index,
                "valuation_date": _date8(valuation),
                "benchmarks": benchmark_rows,
            }
        ],
        "source_refs": sorted(source_refs),
        "boundary": {
            "sidecar_only": True,
            "provider_selection_performed": False,
            "provider_call_performed_by_reconciler": False,
            "account_write_performed": False,
            "paper_gate_upgrade_performed": False,
            "ship_gate_or_production_authorized": False,
        },
    }


def sidecar_evaluable_symbols(sidecar: Mapping[str, Any]) -> list[str]:
    """Return only ETF weeks whose four coverage gates and reasons are clean."""

    weeks = sidecar.get("weeks") if isinstance(sidecar, Mapping) else None
    if not isinstance(weeks, list) or len(weeks) != 1 or not isinstance(weeks[0], Mapping):
        return []
    rows = weeks[0].get("benchmarks")
    if not isinstance(rows, Mapping):
        return []
    return [
        symbol
        for symbol in BENCHMARKS
        if isinstance(rows.get(symbol), Mapping)
        and isinstance(rows[symbol].get("coverage"), Mapping)
        and all(rows[symbol]["coverage"].get(name) is True for name in (
            "pagination_complete", "dividend_complete", "split_complete",
            "adjusted_unadjusted_reconciled",
        ))
        and rows[symbol].get("data_quality_reasons") == []
    ]


__all__ = [
    "EVENT_FAMILIES",
    "FAMILIES",
    "EtfSidecarProducerError",
    "build_etf_total_return_sidecar_week",
    "sidecar_evaluable_symbols",
]
