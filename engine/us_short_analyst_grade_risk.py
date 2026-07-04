"""US-short analyst-grade -> risk_downgrade seam.

Pure/offline consumer for the Cut 5-c FMP analyst-grades fact layer. It does
not fetch data and does not reinterpret grade strings; it only consumes the
already validated `analyst_actions_recent` summary and projects the section 5.2
collective-downgrade basis into the existing section 4.2 soft risk_downgrade input.
"""
from __future__ import annotations

from typing import Any

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_risk_downgrade import risk_downgrade


COVERAGE_SCORED = "scored_analyst_grade_signal"
COVERAGE_NEUTRAL_CHECKED = "neutral_checked_no_recent_analyst_activity"
COVERAGE_EXCLUDED = "neutral_source_excluded"
COVERAGE_MISSING = "neutral_source_missing"

MIN_COLLECTIVE_DOWNGRADES = 2
MIN_COLLECTIVE_DISTINCT_FIRMS = 2

_RESULT_KEYS = frozenset({"signals", "records", "provenance", "checked", "excluded"})
_SIGNAL_KEYS = frozenset({"analyst_actions_recent"})
_SUMMARY_KEYS = frozenset({
    "upgrades",
    "downgrades",
    "neutrals",
    "net",
    "distinct_firms",
    "distinct_downgrading_firms",
    "window_days",
})
_CHECKED_DISPOSITION = "checked_no_recent_activity"


class AnalystGradeRiskError(ValueError):
    """Malformed analyst-grade risk projection input."""


def _fail(message: str) -> None:
    raise AnalystGradeRiskError(message)


def _canonical_ticker(raw: Any, *, where: str) -> str:
    if type(raw) is not str:
        _fail(f"{where} must be exact str")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        _fail(f"{where} must be a canonicalizable US ticker")
    return ticker


def _canonical_targets(target_tickers: Any) -> list[str]:
    if type(target_tickers) is not list and type(target_tickers) is not tuple:
        _fail("target_tickers must be an exact list/tuple")
    out: list[str] = []
    seen: set[str] = set()
    for raw in target_tickers:
        ticker = _canonical_ticker(raw, where="target_tickers item")
        if ticker in seen:
            _fail(f"target_tickers contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _canonical_map(value: Any, *, name: str, value_kind: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(f"analyst_grade_actions.{name} must be an exact dict")
    out: dict[str, Any] = {}
    for raw_ticker, raw_row in value.items():
        ticker = _canonical_ticker(raw_ticker, where=f"analyst_grade_actions.{name} key")
        if ticker in out:
            _fail(f"analyst_grade_actions.{name} contains duplicate canonical ticker: {ticker}")
        if value_kind == "dict" and type(raw_row) is not dict:
            _fail(f"analyst_grade_actions.{name}[{ticker}] must be an exact dict")
        if value_kind == "str" and type(raw_row) is not str:
            _fail(f"analyst_grade_actions.{name}[{ticker}] must be exact str")
        out[ticker] = raw_row
    return out


def _strict_nonnegative_int(value: Any, *, name: str) -> int:
    if type(value) is not int or value < 0:
        _fail(f"{name} must be an exact non-negative int")
    return value


def _strict_int(value: Any, *, name: str) -> int:
    if type(value) is not int:
        _fail(f"{name} must be an exact int")
    return value


def _summary(row: Any, *, ticker: str) -> dict[str, int]:
    if type(row) is not dict or set(row) != _SIGNAL_KEYS:
        _fail(f"signals[{ticker}] must contain exactly analyst_actions_recent")
    recent = row["analyst_actions_recent"]
    if type(recent) is not dict or set(recent) != _SUMMARY_KEYS:
        _fail(f"signals[{ticker}].analyst_actions_recent keys drifted from Cut 5-c contract")
    upgrades = _strict_nonnegative_int(recent["upgrades"], name=f"{ticker}.upgrades")
    downgrades = _strict_nonnegative_int(recent["downgrades"], name=f"{ticker}.downgrades")
    neutrals = _strict_nonnegative_int(recent["neutrals"], name=f"{ticker}.neutrals")
    net = _strict_int(recent["net"], name=f"{ticker}.net")
    distinct_firms = _strict_nonnegative_int(recent["distinct_firms"], name=f"{ticker}.distinct_firms")
    distinct_downgrading_firms = _strict_nonnegative_int(
        recent["distinct_downgrading_firms"],
        name=f"{ticker}.distinct_downgrading_firms",
    )
    window_days = _strict_nonnegative_int(recent["window_days"], name=f"{ticker}.window_days")
    if window_days <= 0:
        _fail(f"{ticker}.window_days must be positive")
    if net != upgrades - downgrades:
        _fail(f"{ticker}.net must equal upgrades - downgrades")
    if distinct_firms > upgrades + downgrades + neutrals:
        _fail(f"{ticker}.distinct_firms cannot exceed recent action count")
    if distinct_downgrading_firms > distinct_firms or distinct_downgrading_firms > downgrades:
        _fail(f"{ticker}.distinct_downgrading_firms exceeds downgrade/firms bounds")
    return {
        "upgrades": upgrades,
        "downgrades": downgrades,
        "neutrals": neutrals,
        "net": net,
        "distinct_firms": distinct_firms,
        "distinct_downgrading_firms": distinct_downgrading_firms,
        "window_days": window_days,
    }


def _collective_downgrade(summary: dict[str, int]) -> bool:
    return (
        summary["downgrades"] >= MIN_COLLECTIVE_DOWNGRADES
        and summary["distinct_downgrading_firms"] >= MIN_COLLECTIVE_DISTINCT_FIRMS
        and summary["net"] < 0
    )


def _validate_checked(row: Any, *, ticker: str) -> None:
    if type(row) is not dict:
        _fail(f"checked[{ticker}] must be an exact dict")
    if row.get("disposition") != _CHECKED_DISPOSITION:
        _fail(f"checked[{ticker}].disposition must be {_CHECKED_DISPOSITION!r}")


def project_analyst_grade_risk_downgrade(*, target_tickers: Any, analyst_grade_actions: Any) -> dict[str, Any]:
    """Project resolved FMP analyst grades into the typed risk_downgrade input map.

    Missing/excluded analyst-grade source does not fabricate an analyst penalty.
    The returned `coverage_by_ticker` keeps that distinction so a caller can
    route the data-quality gap separately from the soft-risk component.
    """
    targets = _canonical_targets(target_tickers)
    if type(analyst_grade_actions) is not dict or set(analyst_grade_actions) != _RESULT_KEYS:
        _fail("analyst_grade_actions keys drifted from resolve_analyst_grade_actions output")
    signals = _canonical_map(analyst_grade_actions["signals"], name="signals", value_kind="dict")
    checked = _canonical_map(analyst_grade_actions["checked"], name="checked", value_kind="dict")
    excluded = _canonical_map(analyst_grade_actions["excluded"], name="excluded", value_kind="str")
    owner: dict[str, str] = {}
    for disposition, rows in (("signals", signals), ("checked", checked), ("excluded", excluded)):
        for ticker in rows:
            if ticker in owner:
                _fail(f"analyst_grade_actions has ambiguous disposition for {ticker}: {owner[ticker]} and {disposition}")
            owner[ticker] = disposition

    risk_by_ticker: dict[str, dict[str, Any]] = {}
    coverage_by_ticker: dict[str, str] = {}
    flag_by_ticker: dict[str, bool] = {}
    for ticker in targets:
        collective = False
        if ticker in signals:
            collective = _collective_downgrade(_summary(signals[ticker], ticker=ticker))
            coverage = COVERAGE_SCORED
        elif ticker in checked:
            _validate_checked(checked[ticker], ticker=ticker)
            coverage = COVERAGE_NEUTRAL_CHECKED
        elif ticker in excluded:
            coverage = COVERAGE_EXCLUDED
        else:
            coverage = COVERAGE_MISSING
        flag_by_ticker[ticker] = collective
        coverage_by_ticker[ticker] = coverage
        risk_by_ticker[ticker] = risk_downgrade(analyst_collective_downgrade=collective)

    return {
        "risk_downgrade_by_ticker": risk_by_ticker,
        "coverage_by_ticker": coverage_by_ticker,
        "analyst_collective_downgrade_by_ticker": flag_by_ticker,
        "policy": {
            "min_collective_downgrades": MIN_COLLECTIVE_DOWNGRADES,
            "min_collective_distinct_firms": MIN_COLLECTIVE_DISTINCT_FIRMS,
            "requires_net_negative": True,
        },
    }
