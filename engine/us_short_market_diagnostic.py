"""Pure calculations for the US-short 26-week market diagnostic.

This module deliberately has no filesystem, network, account-store, broker, or
selection imports.  Callers provide schema-shaped weekly records; this module
only validates the calculation inputs and returns diagnostic facts.

The calculation contract is intentionally conservative:

* the 26 calendar weeks remain the denominator, including ``no_count`` weeks;
* missing observations are never replaced with zero;
* direction labels require at least 20 joint observations for every benchmark;
* ``price_return_diagnostic`` is usable for arithmetic comparison but always
  keeps the result in ``data_degraded``;
* HAC t values are descriptive and are never an approval or switching gate.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any


BENCHMARKS = ("VTI", "IWB", "SPY", "QQQ")
BENCHMARK_ROLES = {
    "VTI": "ship_gate_economic_continuity",
    "IWB": "russell_1000_investable_proxy",
    "SPY": "broad_large_cap_sensitivity",
    "QQQ": "growth_technology_sensitivity",
}
WINDOW_WEEKS = 26
MIN_JOINT_EVALUABLE_WEEKS = 20
HAC_MAX_LAGS = 4
INITIAL_CAPITAL = Decimal("100000.000000")
STRATEGY_STATUSES = ("evaluable", "diagnostic_data_degraded", "not_evaluable")
BENCHMARK_RETURN_QUALITIES = (
    "total_return_evaluable",
    "price_return_diagnostic",
    "unavailable",
)
BENCHMARK_STATUSES = (
    "ahead_diagnostic",
    "behind_diagnostic",
    "flat_diagnostic",
    "mixed_across_benchmarks",
    "data_insufficient",
    "data_degraded",
    "unavailable",
)
OVERALL_STATUSES = (
    "ahead_diagnostic",
    "behind_diagnostic",
    "mixed_across_benchmarks",
    "data_insufficient",
    "data_degraded",
    "unavailable",
)
STATUS_PRIORITY = (
    "unavailable",
    "data_insufficient",
    "data_degraded",
    "mixed_across_benchmarks",
    "ahead_diagnostic",
    "behind_diagnostic",
)
BOUNDARY = {
    "diagnostic_only": True,
    "comparison_only": True,
    "counts_ship_gate": False,
    "changes_selection_or_action": False,
    "automatic_policy_switch": False,
    "broker_or_order_automation": False,
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MONEY = re.compile(r"^(0|[1-9][0-9]*)\.[0-9]{6}$")
_DATE8 = re.compile(r"^[0-9]{8}$")


class MarketDiagnosticError(ValueError):
    """Raised when a diagnostic input would make the result ambiguous."""


def _fail(message: str) -> None:
    raise MarketDiagnosticError(message)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{field} must be an object")
    return value


def _required(mapping: Mapping[str, Any], field: str, parent: str) -> Any:
    if field not in mapping:
        _fail(f"{parent}.{field} is required")
    return mapping[field]


def _finite(value: object, field: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _fail(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        _fail(f"{field} must be a finite number")
    return result


def _finite_nonnegative(value: object, field: str, *, allow_none: bool = False) -> float | None:
    result = _finite(value, field, allow_none=allow_none)
    if result is not None and result < 0:
        _fail(f"{field} must be non-negative")
    return result


def _money(value: object, field: str, *, allow_none: bool = False) -> Decimal | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or _MONEY.fullmatch(value) is None:
        _fail(f"{field} must be a non-negative six-decimal money string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - regex already rejects this
        raise MarketDiagnosticError(f"{field} is not valid money") from exc
    if not result.is_finite():
        _fail(f"{field} must be finite")
    return result


def _money_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.6f}"


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"{field} must be a lowercase sha256")
    return value


def _date8_value(value: object, field: str) -> date:
    if not isinstance(value, str) or _DATE8.fullmatch(value) is None:
        _fail(f"{field} must be an eight-digit date")
    try:
        return date(year=int(value[0:4]), month=int(value[4:6]), day=int(value[6:8]))
    except ValueError as exc:
        raise MarketDiagnosticError(f"{field} is not a real calendar date") from exc


def construct_simple_return(prior_value: object, current_value: object, *, field: str = "value") -> float:
    """Construct a simple return without allowing an implicit zero base."""

    prior = _finite(prior_value, f"{field}.prior")
    current = _finite(current_value, f"{field}.current")
    assert prior is not None and current is not None
    if prior <= 0 or current <= 0:
        _fail(f"{field} values must be positive")
    result = current / prior - 1.0
    if not math.isfinite(result) or result <= -1.0:
        _fail(f"{field} return is invalid")
    return result


def construct_weekly_return(
    prior_nav: str | None,
    nav: str,
    *,
    initial_capital: str = "100000.000000",
) -> float:
    """Construct a weekly NAV return from the prior settled NAV.

    ``prior_nav=None`` means the first observation uses the frozen normalized
    capital.  It is not a permission to fill a missing later observation.
    """

    prior = _money(initial_capital if prior_nav is None else prior_nav, "prior_nav")
    current = _money(nav, "nav")
    assert prior is not None and current is not None
    return construct_simple_return(float(prior), float(current), field="nav")


def _returns(values: Iterable[object], field: str) -> list[float]:
    result: list[float] = []
    for index, value in enumerate(values):
        number = _finite(value, f"{field}[{index}]")
        assert number is not None
        if number <= -1.0:
            _fail(f"{field}[{index}] must be greater than -1")
        result.append(number)
    return result


def _finite_values(values: Iterable[object], field: str) -> list[float]:
    result: list[float] = []
    for index, value in enumerate(values):
        number = _finite(value, f"{field}[{index}]")
        assert number is not None
        result.append(number)
    return result


def compound_wealth(values: Iterable[object]) -> float:
    """Return compounded wealth starting at 1; missing values must be rejected."""

    wealth = 1.0
    for value in _returns(values, "returns"):
        wealth *= 1.0 + value
        if not math.isfinite(wealth):
            _fail("compounded wealth is not finite")
    return wealth


def cumulative_return(values: Iterable[object]) -> float:
    """Return compounded cumulative return, without annualization."""

    return compound_wealth(values) - 1.0


def maximum_drawdown(values: Iterable[object]) -> float:
    """Return the worst peak-to-trough drawdown from compounded wealth levels."""

    wealth = 1.0
    peak = wealth
    worst = 0.0
    for value in _returns(values, "returns"):
        wealth *= 1.0 + value
        peak = max(peak, wealth)
        worst = min(worst, wealth / peak - 1.0)
    return worst


max_drawdown = maximum_drawdown


def weekly_excess(strategy_return: object, benchmark_return: object) -> float:
    """Return arithmetic strategy minus benchmark excess for one joint week."""

    strategy = _finite(strategy_return, "strategy_return")
    benchmark = _finite(benchmark_return, "benchmark_return")
    assert strategy is not None and benchmark is not None
    return strategy - benchmark


def information_ratio(values: Iterable[object]) -> float | None:
    """Return the non-annualized sample Information Ratio for weekly excesses."""

    excesses = _finite_values(values, "excess_returns")
    if len(excesses) < 2:
        return None
    mean = sum(excesses) / len(excesses)
    centered = [value - mean for value in excesses]
    variance = sum(value * value for value in centered) / (len(excesses) - 1)
    if variance <= 0:
        return 0.0 if mean == 0 else None
    return mean / math.sqrt(variance)


def newey_west_hac_t(values: Iterable[object], *, max_lags: int = HAC_MAX_LAGS) -> float | None:
    """Return a descriptive Newey-West t statistic for a mean weekly excess.

    The default lag is fixed at ``min(4, n - 1)``.  No p-value or automatic
    decision is produced by this diagnostic function.
    """

    if isinstance(max_lags, bool) or not isinstance(max_lags, int) or max_lags < 0:
        _fail("max_lags must be a non-negative integer")
    excesses = _finite_values(values, "excess_returns")
    if len(excesses) < 2:
        return None
    mean = sum(excesses) / len(excesses)
    centered = [value - mean for value in excesses]
    lag = min(max_lags, len(excesses) - 1)
    long_run_variance = sum(value * value for value in centered) / len(excesses)
    for offset in range(1, lag + 1):
        covariance = sum(
            centered[index] * centered[index - offset] for index in range(offset, len(excesses))
        ) / len(excesses)
        weight = 1.0 - offset / (lag + 1.0)
        long_run_variance += 2.0 * weight * covariance
    if long_run_variance <= 0:
        return None
    return mean / math.sqrt(long_run_variance / len(excesses))


def _week_index(row: Mapping[str, Any]) -> int:
    value = _required(row, "calendar_week_index", "weekly_record")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail("calendar_week_index must be a positive integer")
    return value


def _strategy_returns(rows: Sequence[Mapping[str, Any]]) -> list[float | None]:
    result: list[float | None] = []
    for row in rows:
        strategy = _mapping(row["strategy"], "strategy")
        if strategy["no_count"]:
            result.append(None)
            continue
        stored = strategy.get("weekly_return")
        derived = construct_weekly_return(strategy.get("prior_nav"), strategy["nav"])
        if stored is not None:
            observed = _finite(stored, "strategy.weekly_return")
            assert observed is not None
            if not math.isclose(observed, derived, rel_tol=0.0, abs_tol=1e-9):
                _fail("strategy.weekly_return disagrees with NAV construction")
        result.append(derived)
    return result


def _validate_strategy(strategy: Mapping[str, Any]) -> None:
    for field in (
        "paper_evaluable",
        "performance_status",
        "strategy_evaluable",
        "initial_capital",
        "nav",
        "prior_nav",
        "weekly_return",
        "cash",
        "market_value",
        "cumulative_cost_paid",
        "no_count",
    ):
        _required(strategy, field, "strategy")
    if not isinstance(strategy["paper_evaluable"], bool):
        _fail("strategy.paper_evaluable must be boolean")
    if strategy["performance_status"] not in STRATEGY_STATUSES:
        _fail("strategy.performance_status is unknown")
    if not isinstance(strategy["strategy_evaluable"], bool):
        _fail("strategy.strategy_evaluable must be boolean")
    if strategy["initial_capital"] != "100000.000000":
        _fail("strategy.initial_capital is not the frozen normalized capital")
    if not isinstance(strategy["no_count"], bool):
        _fail("strategy.no_count must be boolean")
    _money(strategy["nav"], "strategy.nav")
    _money(strategy["prior_nav"], "strategy.prior_nav", allow_none=True)
    _money(strategy["cash"], "strategy.cash", allow_none=True)
    _money(strategy["market_value"], "strategy.market_value", allow_none=True)
    _money(strategy["cumulative_cost_paid"], "strategy.cumulative_cost_paid", allow_none=True)
    if strategy["no_count"]:
        reason = strategy.get("no_count_reason")
        if not isinstance(reason, str) or not reason:
            _fail("no_count requires no_count_reason")
        if strategy["weekly_return"] is not None or strategy["strategy_evaluable"]:
            _fail("no_count cannot carry a return or be strategy_evaluable")
    elif strategy.get("no_count_reason") is not None:
        _fail("non-no_count week cannot carry no_count_reason")
    if not strategy["paper_evaluable"]:
        if strategy["strategy_evaluable"]:
            _fail("paper_evaluable=false cannot be strategy_evaluable")
        if strategy["performance_status"] == "evaluable":
            _fail("paper_evaluable=false cannot have evaluable status")
    if strategy["strategy_evaluable"] and not strategy["paper_evaluable"]:
        _fail("strategy_evaluable requires paper_evaluable")
    if strategy["strategy_evaluable"] and strategy["performance_status"] != "evaluable":
        _fail("strategy_evaluable requires evaluable performance_status")
    if strategy["weekly_return"] is not None:
        _finite(strategy["weekly_return"], "strategy.weekly_return")
    if strategy["cash"] is not None and strategy["market_value"] is not None:
        nav = _money(strategy["nav"], "strategy.nav")
        cash = _money(strategy["cash"], "strategy.cash")
        market_value = _money(strategy["market_value"], "strategy.market_value")
        assert nav is not None and cash is not None and market_value is not None
        if abs((cash + market_value) - nav) > Decimal("0.000001"):
            _fail("strategy cash plus market_value must equal nav")
    if "turnover" in strategy:
        _finite_nonnegative(strategy["turnover"], "strategy.turnover", allow_none=True)
    if "unfilled_order_count" in strategy:
        count = strategy["unfilled_order_count"]
        if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
            _fail("strategy.unfilled_order_count must be a non-negative integer or null")


def _validate_benchmark(benchmark: Mapping[str, Any], strategy: Mapping[str, Any], symbol: str) -> None:
    for field in (
        "return_quality",
        "benchmark_evaluable",
        "joint_evaluable",
        "weekly_return",
        "price_date",
        "price_source",
    ):
        _required(benchmark, field, f"benchmarks.{symbol}")
    quality = benchmark["return_quality"]
    if quality not in BENCHMARK_RETURN_QUALITIES:
        _fail(f"benchmarks.{symbol}.return_quality is unknown")
    if not isinstance(benchmark["benchmark_evaluable"], bool) or not isinstance(
        benchmark["joint_evaluable"], bool
    ):
        _fail(f"benchmarks.{symbol} evaluability flags must be boolean")
    if benchmark["price_date"] is not None:
        _date8_value(benchmark["price_date"], f"benchmarks.{symbol}.price_date")
    if benchmark["price_source"] is not None and (
        not isinstance(benchmark["price_source"], str) or not benchmark["price_source"]
    ):
        _fail(f"benchmarks.{symbol}.price_source must be a non-empty string or null")
    if benchmark["benchmark_evaluable"]:
        if quality == "unavailable" or benchmark["weekly_return"] is None:
            _fail(f"benchmarks.{symbol} evaluable return is missing")
        number = _finite(benchmark["weekly_return"], f"benchmarks.{symbol}.weekly_return")
        assert number is not None
        if number <= -1.0:
            _fail(f"benchmarks.{symbol}.weekly_return must be greater than -1")
    elif benchmark["weekly_return"] is not None:
        _fail(f"benchmarks.{symbol} unavailable return must be null")
    if benchmark["joint_evaluable"]:
        if not strategy["paper_evaluable"] or not strategy["strategy_evaluable"]:
            _fail(f"benchmarks.{symbol} joint_evaluable bypasses the paper gate")
        if not benchmark["benchmark_evaluable"]:
            _fail(f"benchmarks.{symbol} joint_evaluable requires benchmark_evaluable")


def _validate_rows(
    rows: Sequence[Mapping[str, Any]], *, as_of_date: str | None = None
) -> dict[str, Any]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence) or len(rows) != WINDOW_WEEKS:
        _fail("a diagnostic window must contain exactly 26 weekly records")
    if as_of_date is not None:
        as_of = _date8_value(as_of_date, "as_of_date")
    else:
        as_of = None
    normalized: list[Mapping[str, Any]] = []
    weeks: list[int] = []
    epochs: list[str] = []
    decisions: list[date] = []
    valuations: list[date] = []
    for index, raw_row in enumerate(rows):
        row = _mapping(raw_row, f"weekly_record[{index}]")
        week = _week_index(row)
        if weeks and week != weeks[-1] + 1:
            _fail("calendar_week_index must be consecutive and ordered")
        decision = _date8_value(_required(row, "decision_date", "weekly_record"), "decision_date")
        valuation = _date8_value(_required(row, "valuation_date", "weekly_record"), "valuation_date")
        if valuation > decision:
            _fail("valuation_date cannot be after decision_date")
        if decisions and decision <= decisions[-1]:
            _fail("decision_date must be strictly increasing")
        if valuations and valuation <= valuations[-1]:
            _fail("valuation_date must be strictly increasing")
        if as_of is not None and (decision > as_of or valuation > as_of):
            _fail("future diagnostic data is not allowed")
        window_id = _required(row, "window_id", "weekly_record")
        if not isinstance(window_id, str):
            _fail("window_id must be a string")
        epoch = _required(row, "diagnostic_epoch", "weekly_record")
        if not isinstance(epoch, str) or not epoch:
            _fail("diagnostic_epoch must be non-empty")
        fingerprint = _sha(
            _required(row, "strategy_ruleset_fingerprint", "weekly_record"),
            "strategy_ruleset_fingerprint",
        )
        strategy = _mapping(_required(row, "strategy", "weekly_record"), "strategy")
        _validate_strategy(strategy)
        benchmarks = _mapping(_required(row, "benchmarks", "weekly_record"), "benchmarks")
        if set(benchmarks) != set(BENCHMARKS):
            _fail("weekly record must contain exactly VTI, IWB, SPY, and QQQ")
        for symbol in BENCHMARKS:
            _validate_benchmark(_mapping(benchmarks[symbol], f"benchmarks.{symbol}"), strategy, symbol)
        source_refs = row.get("source_refs")
        if not isinstance(source_refs, Sequence) or isinstance(source_refs, (str, bytes)) or not source_refs:
            _fail("weekly_record.source_refs must be a non-empty digest list")
        for source_ref in source_refs:
            _sha(source_ref, "weekly_record.source_refs")
        boundary = _mapping(_required(row, "boundary", "weekly_record"), "boundary")
        if dict(boundary) != BOUNDARY:
            _fail("weekly record crosses the diagnostic boundary")
        reminder = _mapping(_required(row, "v1_1_reminder", "weekly_record"), "v1_1_reminder")
        if reminder.get("status") not in {"pending", "ready_for_v1_1_implementation", "overdue", "active"}:
            _fail("v1_1_reminder.status is unknown")
        count = reminder.get("evaluable_week_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            _fail("v1_1_reminder.evaluable_week_count must be a non-negative integer")
        if not isinstance(reminder.get("text"), str) or not reminder["text"]:
            _fail("v1_1_reminder.text must be non-empty")
        weeks.append(week)
        epochs.append(epoch)
        decisions.append(decision)
        valuations.append(valuation)
        normalized.append(row)
    start_week, end_week = weeks[0], weeks[-1]
    canonical_window = window_for_week(end_week)
    if canonical_window is None or canonical_window["window_start_week"] != start_week:
        _fail("window does not start on a canonical non-overlapping 26-week boundary")
    canonical_window_id = canonical_window["window_id"]
    if any(row["window_id"] != canonical_window_id for row in normalized):
        _fail("window_id does not match the canonical 26-week clock")
    if len(set(epochs)) != 1:
        _fail("diagnostic_epoch cannot be silently joined across one window")
    _strategy_returns(normalized)
    return {
        "rows": normalized,
        "start_week": start_week,
        "end_week": end_week,
        "window_id": canonical_window["window_id"],
        "diagnostic_epoch": epochs[0],
    }


def validate_weekly_record(
    row: Mapping[str, Any], *, as_of_date: str | None = None
) -> dict[str, Any]:
    """Validate one weekly record before lifecycle persistence.

    ``validate_window`` intentionally requires all 26 rows.  Knife 3 needs a
    smaller gate at the point a settled week is published, so this function
    applies the same field, evaluability, source, and diagnostic-boundary
    checks to one row and additionally enforces the canonical 26-week window
    id for that row's calendar week.
    """

    record = _mapping(row, "weekly_record")
    if record.get("schema_name") != "us_short_market_diagnostic_weekly_record":
        _fail("weekly_record.schema_name is unknown")
    if record.get("schema_version") != "1.0.0":
        _fail("weekly_record.schema_version is unsupported")
    week = _week_index(record)
    decision = _date8_value(_required(record, "decision_date", "weekly_record"), "decision_date")
    valuation = _date8_value(_required(record, "valuation_date", "weekly_record"), "valuation_date")
    if valuation > decision:
        _fail("valuation_date cannot be after decision_date")
    if as_of_date is not None:
        as_of = _date8_value(as_of_date, "as_of_date")
        if decision > as_of or valuation > as_of:
            _fail("future diagnostic data is not allowed")

    containing_window = window_containing_week(week)
    expected_window_id = containing_window["window_id"]
    window_id = _required(record, "window_id", "weekly_record")
    if window_id != expected_window_id:
        _fail("weekly_record.window_id does not match the canonical 26-week clock")

    epoch = _required(record, "diagnostic_epoch", "weekly_record")
    if not isinstance(epoch, str) or not epoch:
        _fail("diagnostic_epoch must be non-empty")
    _sha(_required(record, "diagnostic_policy_sha256", "weekly_record"), "diagnostic_policy_sha256")
    _sha(_required(record, "strategy_ruleset_fingerprint", "weekly_record"), "strategy_ruleset_fingerprint")

    strategy = _mapping(_required(record, "strategy", "weekly_record"), "strategy")
    _validate_strategy(strategy)
    benchmarks = _mapping(_required(record, "benchmarks", "weekly_record"), "benchmarks")
    if set(benchmarks) != set(BENCHMARKS):
        _fail("weekly record must contain exactly VTI, IWB, SPY, and QQQ")
    for symbol in BENCHMARKS:
        _validate_benchmark(_mapping(benchmarks[symbol], f"benchmarks.{symbol}"), strategy, symbol)

    source_refs = record.get("source_refs")
    if not isinstance(source_refs, Sequence) or isinstance(source_refs, (str, bytes)) or not source_refs:
        _fail("weekly_record.source_refs must be a non-empty digest list")
    for source_ref in source_refs:
        _sha(source_ref, "weekly_record.source_refs")
    boundary = _mapping(_required(record, "boundary", "weekly_record"), "boundary")
    if dict(boundary) != BOUNDARY:
        _fail("weekly record crosses the diagnostic boundary")
    reminder = _mapping(_required(record, "v1_1_reminder", "weekly_record"), "v1_1_reminder")
    if reminder.get("status") not in {"pending", "ready_for_v1_1_implementation", "overdue", "active"}:
        _fail("v1_1_reminder.status is unknown")
    count = reminder.get("evaluable_week_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        _fail("v1_1_reminder.evaluable_week_count must be a non-negative integer")
    if not isinstance(reminder.get("text"), str) or not reminder["text"]:
        _fail("v1_1_reminder.text must be non-empty")
    _strategy_returns([record])
    return {
        "calendar_week_index": week,
        "decision_date": decision,
        "valuation_date": valuation,
        "window_id": containing_window["window_id"],
        "window_start_week": containing_window["window_start_week"],
        "window_end_week": containing_window["window_end_week"],
        "calendar_weeks": containing_window["calendar_weeks"],
        "diagnostic_epoch": epoch,
    }


def validate_window(rows: Sequence[Mapping[str, Any]], *, as_of_date: str | None = None) -> dict[str, Any]:
    """Validate and return the canonical identity of one 26-week window."""

    result = _validate_rows(rows, as_of_date=as_of_date)
    return {key: result[key] for key in ("window_id", "start_week", "end_week", "diagnostic_epoch")}


def segment_epoch_and_ruleset(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return consecutive epoch/ruleset segments with evaluable-week counts."""

    if not rows:
        return []
    segments: list[dict[str, Any]] = []
    previous_week: int | None = None
    for raw_row in rows:
        row = _mapping(raw_row, "weekly_record")
        week = _week_index(row)
        epoch = _required(row, "diagnostic_epoch", "weekly_record")
        fingerprint = _sha(
            _required(row, "strategy_ruleset_fingerprint", "weekly_record"),
            "strategy_ruleset_fingerprint",
        )
        strategy = _mapping(_required(row, "strategy", "weekly_record"), "strategy")
        evaluable = bool(strategy.get("strategy_evaluable", False))
        key = (epoch, fingerprint)
        if previous_week is not None and week != previous_week + 1:
            _fail("segment input weeks must be consecutive")
        if not segments or segments[-1]["_key"] != key:
            segments.append(
                {
                    "diagnostic_epoch": epoch,
                    "strategy_ruleset_fingerprint": fingerprint,
                    "start_week": week,
                    "end_week": week,
                    "calendar_weeks": 1,
                    "strategy_evaluable_weeks": int(evaluable),
                    "_key": key,
                }
            )
        else:
            segment = segments[-1]
            segment["end_week"] = week
            segment["calendar_weeks"] += 1
            segment["strategy_evaluable_weeks"] += int(evaluable)
        previous_week = week
    for segment in segments:
        segment.pop("_key", None)
    return segments


def ruleset_fingerprints(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return first-seen ruleset fingerprints for a window."""

    result: list[str] = []
    for segment in segment_epoch_and_ruleset(rows):
        fingerprint = segment["strategy_ruleset_fingerprint"]
        if fingerprint not in result:
            result.append(fingerprint)
    return result


def mixed_ruleset_window(rows: Sequence[Mapping[str, Any]]) -> bool:
    """Return whether no single ruleset has 20 strategy-evaluable weeks."""

    counts: Counter[str] = Counter()
    fingerprints: set[str] = set()
    for row in rows:
        fingerprint = _sha(row["strategy_ruleset_fingerprint"], "strategy_ruleset_fingerprint")
        strategy = _mapping(row["strategy"], "strategy")
        fingerprints.add(fingerprint)
        if strategy.get("strategy_evaluable") is True:
            counts[fingerprint] += 1
    return len(fingerprints) > 1 and max(counts.values(), default=0) < MIN_JOINT_EVALUABLE_WEEKS


def window_containing_week(calendar_week_index: int) -> dict[str, Any]:
    """Return the one canonical non-overlapping window containing a calendar week.

    This is the single source for window boundary arithmetic and the ``26w-``
    identity.  All callers that need either a boundary trigger or a week-level
    window identity must delegate here.
    """

    if isinstance(calendar_week_index, bool) or not isinstance(calendar_week_index, int) or calendar_week_index < 1:
        _fail("calendar_week_index must be a positive integer")
    start_week = ((calendar_week_index - 1) // WINDOW_WEEKS) * WINDOW_WEEKS + 1
    end_week = start_week + WINDOW_WEEKS - 1
    return {
        "window_id": f"26w-{start_week}-{end_week}",
        "window_start_week": start_week,
        "window_end_week": end_week,
        "calendar_weeks": WINDOW_WEEKS,
    }


def window_for_week(calendar_week_index: int) -> dict[str, Any] | None:
    """Return the containing window only when the supplied week closes it."""

    window = window_containing_week(calendar_week_index)
    if calendar_week_index != window["window_end_week"]:
        return None
    return window


def evaluate_window_trigger(
    calendar_week_index: int, *, emitted_window_ids: Iterable[str] = ()
) -> dict[str, Any]:
    """Return an idempotent trigger decision without mutating any state."""

    emitted = list(emitted_window_ids)
    if any(not isinstance(value, str) or not value for value in emitted):
        _fail("emitted_window_ids must contain non-empty strings")
    if len(emitted) != len(set(emitted)):
        _fail("emitted_window_ids must not contain duplicates")
    window = window_for_week(calendar_week_index)
    if window is None:
        return {
            "trigger": False,
            "already_emitted": False,
            "reason": "window_not_complete",
            "window": None,
        }
    already_emitted = window["window_id"] in set(emitted)
    return {
        "trigger": not already_emitted,
        "already_emitted": already_emitted,
        "reason": "already_emitted" if already_emitted else "window_complete",
        "window": window,
    }


def _full_metric(values: Sequence[float | None], function: Any) -> float | None:
    if len(values) != WINDOW_WEEKS or any(value is None for value in values):
        return None
    return function([value for value in values if value is not None])


def _average_ratio(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values: list[float] = []
    for row in rows:
        strategy = _mapping(row["strategy"], "strategy")
        amount = _money(strategy[field], f"strategy.{field}", allow_none=True)
        nav = _money(strategy["nav"], "strategy.nav")
        if amount is None or nav is None:
            return None
        if nav <= 0:
            _fail("strategy.nav must be positive")
        values.append(float(amount / nav))
    return sum(values) / len(values) if values else None


def _summary_strategy(rows: Sequence[Mapping[str, Any]], strategy_returns: Sequence[float | None]) -> dict[str, Any]:
    strategies = [_mapping(row["strategy"], "strategy") for row in rows]
    evaluable_weeks = sum(int(strategy["strategy_evaluable"]) for strategy in strategies)
    no_count_weeks = sum(int(strategy["no_count"]) for strategy in strategies)
    paper_degraded_weeks = sum(
        int(not strategy["paper_evaluable"] or strategy["performance_status"] != "evaluable")
        for strategy in strategies
    )
    if evaluable_weeks == 0:
        status = "not_evaluable"
    elif paper_degraded_weeks == 0 and all(value is not None for value in strategy_returns):
        status = "evaluable"
    else:
        status = "diagnostic_data_degraded"
    costs = [_money(strategy["cumulative_cost_paid"], "strategy.cumulative_cost_paid", allow_none=True) for strategy in strategies]
    cumulative_cost = costs[-1] if costs and all(cost is not None for cost in costs) else None
    turnovers = [
        _finite_nonnegative(strategy.get("turnover"), "strategy.turnover", allow_none=True)
        for strategy in strategies
    ]
    turnover = sum(value for value in turnovers if value is not None) if all(value is not None for value in turnovers) else None
    unfilled = [strategy.get("unfilled_order_count") for strategy in strategies]
    unfilled_count = sum(int(value) for value in unfilled if value is not None) if all(value is not None for value in unfilled) else None
    return {
        "status": status,
        "final_nav": _money_text(_money(strategies[-1]["nav"], "strategy.nav")),
        "cumulative_return": _full_metric(strategy_returns, cumulative_return),
        "since_inception_return": _full_metric(strategy_returns, cumulative_return),
        "strategy_evaluable_weeks": evaluable_weeks,
        "no_count_weeks": no_count_weeks,
        "paper_degraded_weeks": paper_degraded_weeks,
        "max_drawdown": _full_metric(strategy_returns, maximum_drawdown),
        "cumulative_cost_paid": _money_text(cumulative_cost),
        "cash_ratio": _average_ratio(rows, "cash"),
        "equity_ratio": _average_ratio(rows, "market_value"),
        "turnover": turnover,
        "unfilled_order_count": unfilled_count,
        "data_coverage": sum(value is not None for value in strategy_returns) / WINDOW_WEEKS,
    }


def _benchmark_summary(
    rows: Sequence[Mapping[str, Any]],
    strategy_returns: Sequence[float | None],
    symbol: str,
) -> tuple[dict[str, Any], str | None]:
    observations = [_mapping(row["benchmarks"][symbol], f"benchmarks.{symbol}") for row in rows]
    benchmark_returns: list[float | None] = [
        _finite(observation["weekly_return"], f"benchmarks.{symbol}.weekly_return", allow_none=True)
        if observation["benchmark_evaluable"]
        else None
        for observation in observations
    ]
    joint_excesses: list[float] = []
    joint_strategy: list[float] = []
    joint_benchmark: list[float] = []
    for strategy_return, observation in zip(strategy_returns, observations):
        if observation["joint_evaluable"] and strategy_return is not None:
            benchmark_return = _finite(observation["weekly_return"], f"benchmarks.{symbol}.weekly_return")
            assert benchmark_return is not None
            joint_strategy.append(strategy_return)
            joint_benchmark.append(benchmark_return)
            joint_excesses.append(weekly_excess(strategy_return, benchmark_return))
    joint_count = len(joint_excesses)
    benchmark_evaluable_count = sum(value is not None for value in benchmark_returns)
    total_count = sum(
        observation["benchmark_evaluable"] and observation["return_quality"] == "total_return_evaluable"
        for observation in observations
    )
    price_only_count = sum(
        observation["benchmark_evaluable"] and observation["return_quality"] == "price_return_diagnostic"
        for observation in observations
    )
    unavailable_count = WINDOW_WEEKS - benchmark_evaluable_count
    quality_degraded = any(
        observation["return_quality"] == "price_return_diagnostic" or not observation["benchmark_evaluable"]
        for observation in observations
    )
    if joint_count == 0:
        status = "unavailable" if benchmark_evaluable_count == 0 else "data_insufficient"
    elif joint_count < MIN_JOINT_EVALUABLE_WEEKS:
        status = "data_insufficient"
    elif quality_degraded:
        status = "data_degraded"
    else:
        joint_excess_total = compound_wealth(joint_strategy) - compound_wealth(joint_benchmark)
        status = (
            "ahead_diagnostic"
            if joint_excess_total > 0
            else "behind_diagnostic"
            if joint_excess_total < 0
            else "flat_diagnostic"
        )
    joint_strategy_wealth = compound_wealth(joint_strategy) if joint_strategy else None
    joint_benchmark_wealth = compound_wealth(joint_benchmark) if joint_benchmark else None
    raw_excess = (
        joint_strategy_wealth - joint_benchmark_wealth
        if joint_strategy_wealth is not None and joint_benchmark_wealth is not None
        else None
    )
    relative_wealth = (
        joint_strategy_wealth / joint_benchmark_wealth - 1.0
        if joint_strategy_wealth is not None and joint_benchmark_wealth not in (None, 0)
        else None
    )
    summary = {
        "role": BENCHMARK_ROLES[symbol],
        "cumulative_return": _full_metric(benchmark_returns, cumulative_return),
        "relative_wealth": relative_wealth,
        "raw_excess": raw_excess,
        "information_ratio": information_ratio(joint_excesses),
        "hac_t": newey_west_hac_t(joint_excesses),
        "joint_evaluable_weeks": joint_count,
        "total_return_evaluable_weeks": total_count,
        "price_only_weeks": price_only_count,
        "unavailable_weeks": unavailable_count,
        "max_drawdown": _full_metric(benchmark_returns, maximum_drawdown),
        "data_coverage": benchmark_evaluable_count / WINDOW_WEEKS,
        "status": status,
    }
    return summary, status


def _overall_status(benchmark_statuses: Mapping[str, str]) -> tuple[str, str]:
    statuses = list(benchmark_statuses.values())
    if "unavailable" in statuses:
        return "unavailable", "at_least_one_benchmark_unavailable"
    if "data_insufficient" in statuses:
        return "data_insufficient", "at_least_one_benchmark_below_20_joint_weeks"
    if "data_degraded" in statuses:
        return "data_degraded", "at_least_one_benchmark_is_price_only_or_incomplete"
    directions = set(statuses)
    if directions == {"ahead_diagnostic"}:
        return "ahead_diagnostic", "all_four_benchmarks_show_diagnostic_excess"
    if directions == {"behind_diagnostic"}:
        return "behind_diagnostic", "all_four_benchmarks_show_diagnostic_underperformance"
    return "mixed_across_benchmarks", "benchmark_directions_are_not_uniform"


def summarize_window(
    rows: Sequence[Mapping[str, Any]], *, as_of_date: str | None = None
) -> dict[str, Any]:
    """Build a schema-shaped 26-week summary from already supplied weekly records."""

    validated = _validate_rows(rows, as_of_date=as_of_date)
    normalized = validated["rows"]
    strategy_returns = _strategy_returns(normalized)
    strategy_summary = _summary_strategy(normalized, strategy_returns)
    benchmark_summaries: dict[str, dict[str, Any]] = {}
    benchmark_statuses: dict[str, str] = {}
    for symbol in BENCHMARKS:
        summary, status = _benchmark_summary(normalized, strategy_returns, symbol)
        benchmark_summaries[symbol] = summary
        benchmark_statuses[symbol] = status
    overall_status, reason = _overall_status(benchmark_statuses)
    reminders = [_mapping(row["v1_1_reminder"], "v1_1_reminder") for row in normalized]
    reminder = dict(reminders[-1])
    source_digests: list[str] = []
    for row in normalized:
        for source_ref in row["source_refs"]:
            if source_ref not in source_digests:
                source_digests.append(source_ref)
    if not source_digests:
        _fail("summary requires at least one source digest")
    return {
        "schema_name": "us_short_market_diagnostic_summary",
        "schema_version": "1.0.0",
        "window_id": validated["window_id"],
        "diagnostic_epoch": validated["diagnostic_epoch"],
        "window_start_week": validated["start_week"],
        "window_end_week": validated["end_week"],
        "calendar_weeks": WINDOW_WEEKS,
        "mixed_ruleset_window": mixed_ruleset_window(normalized),
        "strategy": strategy_summary,
        "benchmarks": benchmark_summaries,
        "overall_status": overall_status,
        "status_reason": reason,
        "ruleset_fingerprints": ruleset_fingerprints(normalized),
        "v1_1_reminder": reminder,
        "source_week_record_sha256": source_digests,
        "boundary": dict(BOUNDARY),
    }


__all__ = [
    "BENCHMARKS",
    "BENCHMARK_ROLES",
    "BENCHMARK_STATUSES",
    "BOUNDARY",
    "HAC_MAX_LAGS",
    "MIN_JOINT_EVALUABLE_WEEKS",
    "MarketDiagnosticError",
    "STATUS_PRIORITY",
    "WINDOW_WEEKS",
    "compound_wealth",
    "construct_simple_return",
    "construct_weekly_return",
    "cumulative_return",
    "evaluate_window_trigger",
    "information_ratio",
    "maximum_drawdown",
    "max_drawdown",
    "mixed_ruleset_window",
    "newey_west_hac_t",
    "ruleset_fingerprints",
    "segment_epoch_and_ruleset",
    "summarize_window",
    "validate_weekly_record",
    "validate_window",
    "weekly_excess",
    "window_containing_week",
    "window_for_week",
]
