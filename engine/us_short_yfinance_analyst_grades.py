"""US-short yfinance analyst-grade resolver.

This is the offline half of the low-trust yfinance grades source. It consumes
injected ``Ticker.upgrades_downgrades`` rows that have already been captured by
a gated runner, validates PIT/provenance, and emits the exact resolved grade
actions shape produced by ``engine.us_short_fmp_analyst_grades``.

yfinance grades are advisory only: missing/down/malformed provider output must
not become an emit gate. The resolver is fail-closed for malformed injected
packages and neutral for checked/missing source coverage.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.us_short_eligibility_gate import canonical_us_ticker


BINDING_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "us_short_yfinance_analyst_grades_binding_20260710.json"
)

PROVIDER_ID = "yfinance"
ENDPOINT = "upgrades_downgrades"
_DECISION_TZ_NAME = "America/New_York"
_RECENCY_WINDOW_DAYS = 90
_DIRECTION_MAP = {"up": "up", "down": "down"}
_DIRECTION_DEFAULT = "neutral"
_RECORD_REQUIRED = ("GradeDate", "Action", "Firm", "ToGrade", "FromGrade")
_PROVENANCE_FIELDS = frozenset({
    "provider_id",
    "endpoint_or_filing_type",
    "source_as_of",
    "observed_at",
    "coverage_status",
    "parser_status",
    "lineage_ref",
})
_COVERAGE_ALLOWED = frozenset({"full", "partial", "missing"})
_PARSER_ALLOWED = frozenset({"ok", "degraded", "failed"})
_COVERAGE_EMIT = "full"
_PARSER_EMIT = "ok"
_RECORD_KEYS = frozenset({"records", "provenance"})
_DECISION_CUTOFF_HHMM = (9, 30)
_CUTOFF_OPERATOR = "strictly_before"
_CUTOFF_REFERENCE = "decision_session_open"
_CHRONOLOGY_ORDER = ("record_date", "observed_at", "source_as_of", "as_of")
_DUPLICATE_IDENTITY = ("record_date", "firm", "action", "to_grade", "from_grade")
_FIRM_NORMALIZATION = "strip_and_casefold"
_DUPLICATE_POLICY = "reject"
_CHECKED_EMPTY_DISPOSITION = "checked_no_recent_activity"
_LINEAGE_REF_FORMAT = "provider_id:endpoint_or_filing_type:source_as_of#record_id"
_AUTHORIZATION_BOUNDARY = {
    "live_fetch": False,
    "network": False,
    "raw_capture": False,
    "datahub": False,
    "production": False,
    "ship_gate": False,
    "emit_gate": False,
    "critical_provider_health": False,
}
_SUMMARY_FIELDS = (
    "upgrades",
    "downgrades",
    "neutrals",
    "net",
    "distinct_firms",
    "distinct_downgrading_firms",
    "window_days",
)


class YFinanceGradesError(ValueError):
    """Injected yfinance analyst-grade rows are malformed or PIT-inconsistent."""


def _valid_ymd(value: Any) -> bool:
    if not (type(value) is str and len(value) == 10 and value.isascii()):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_observed_at(value: Any) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _et_tz():
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError as exc:  # pragma: no cover - Python 3.9+ in repo runtime.
        raise YFinanceGradesError("zoneinfo is required for yfinance grade PIT normalization") from exc
    try:
        return ZoneInfo(_DECISION_TZ_NAME)
    except ZoneInfoNotFoundError as exc:
        raise YFinanceGradesError(f"{_DECISION_TZ_NAME} timezone is unavailable") from exc


def _observed_at_et(observed_at: str) -> datetime:
    inst = datetime.fromisoformat(observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at)
    try:
        return inst.astimezone(_et_tz())
    except (OverflowError, OSError) as exc:
        raise YFinanceGradesError("observed_at is outside the timezone-normalizable range") from exc


def _decision_cutoff(as_of: str) -> datetime:
    return datetime(
        int(as_of[:4]),
        int(as_of[5:7]),
        int(as_of[8:10]),
        _DECISION_CUTOFF_HHMM[0],
        _DECISION_CUTOFF_HHMM[1],
        tzinfo=_et_tz(),
    )


def _norm_firm(value: str) -> str:
    return " ".join(value.split()).casefold()


def _norm_action(value: str) -> str:
    return " ".join(value.split()).casefold()


def _direction(action: str) -> str:
    return _DIRECTION_MAP.get(action, _DIRECTION_DEFAULT)


def _valid_lineage_ref(ref: Any, *, source_as_of: str) -> bool:
    if not (type(ref) is str and ref.isascii()):
        return False
    prefix, sep, record_id = ref.rpartition("#")
    if sep != "#" or not record_id or any(ch.isspace() for ch in record_id) or ":" in record_id or "#" in record_id:
        return False
    return prefix == f"{PROVIDER_ID}:{ENDPOINT}:{source_as_of}"


def _validate_provenance(provenance: Any, *, ticker: str, as_of: str) -> datetime:
    if not (
        isinstance(provenance, dict)
        and all(type(key) is str for key in provenance)
        and set(provenance) == _PROVENANCE_FIELDS
    ):
        raise YFinanceGradesError(f"[{ticker}].provenance must contain the frozen yfinance fields")
    if provenance["provider_id"] != PROVIDER_ID or provenance["endpoint_or_filing_type"] != ENDPOINT:
        raise YFinanceGradesError(f"[{ticker}].provenance provider/endpoint drifted from binding")
    source_as_of = provenance["source_as_of"]
    if not _valid_ymd(source_as_of):
        raise YFinanceGradesError(f"[{ticker}].provenance source_as_of must be real YYYY-MM-DD")
    if not _valid_observed_at(provenance["observed_at"]):
        raise YFinanceGradesError(f"[{ticker}].provenance observed_at must be tz-aware RFC3339")
    observed_dt = _observed_at_et(provenance["observed_at"])
    if observed_dt >= _decision_cutoff(as_of):
        raise YFinanceGradesError(f"[{ticker}].provenance observed_at must be before decision-session open")
    if observed_dt.strftime("%Y-%m-%d") > source_as_of:
        raise YFinanceGradesError(f"[{ticker}].provenance source_as_of cannot precede observed_at ET date")
    if source_as_of > as_of:
        raise YFinanceGradesError(f"[{ticker}].provenance source_as_of cannot be after as_of")
    coverage = provenance["coverage_status"]
    parser = provenance["parser_status"]
    if type(coverage) is not str or coverage not in _COVERAGE_ALLOWED:
        raise YFinanceGradesError(f"[{ticker}].provenance coverage_status drifted from binding")
    if type(parser) is not str or parser not in _PARSER_ALLOWED:
        raise YFinanceGradesError(f"[{ticker}].provenance parser_status drifted from binding")
    if not _valid_lineage_ref(provenance["lineage_ref"], source_as_of=source_as_of):
        raise YFinanceGradesError(f"[{ticker}].provenance lineage_ref must be source-bound")
    return observed_dt


def _canonical_keyed(grades_by_ticker: Any) -> dict[str, dict[str, Any]]:
    if grades_by_ticker is None:
        return {}
    if not isinstance(grades_by_ticker, dict):
        raise YFinanceGradesError(f"grades_by_ticker must be a dict or None: {type(grades_by_ticker).__name__}")
    out: dict[str, dict[str, Any]] = {}
    for raw_ticker, row in grades_by_ticker.items():
        if type(raw_ticker) is not str:
            continue
        ticker = canonical_us_ticker(raw_ticker)
        if ticker is None:
            continue
        if not isinstance(row, dict):
            raise YFinanceGradesError(f"[{ticker}] source row must be a dict")
        if not all(type(key) is str for key in row):
            raise YFinanceGradesError(f"[{ticker}] source row keys must be exact strings")
        if set(row) != _RECORD_KEYS:
            raise YFinanceGradesError(f"[{ticker}] source row keys must be exactly records/provenance")
        if ticker in out:
            raise YFinanceGradesError(f"duplicate canonical ticker after normalization: {ticker}")
        out[ticker] = row
    return out


def _days_between(later_ymd: str, earlier_ymd: str) -> int:
    return (
        datetime.strptime(later_ymd, "%Y-%m-%d").date()
        - datetime.strptime(earlier_ymd, "%Y-%m-%d").date()
    ).days


def _classify_grade_record(
    record: Any,
    *,
    ticker: str,
    as_of: str,
    observed_date: str,
    window: int,
) -> tuple[str, dict[str, Any] | None]:
    if not isinstance(record, dict):
        raise YFinanceGradesError(f"[{ticker}] grade record must be a dict")
    for field in _RECORD_REQUIRED:
        if field not in record:
            raise YFinanceGradesError(f"[{ticker}] grade record missing required field {field}")
    grade_date = record["GradeDate"]
    if not _valid_ymd(grade_date):
        raise YFinanceGradesError(f"[{ticker}] GradeDate must be real YYYY-MM-DD")
    action_raw = record["Action"]
    if not (type(action_raw) is str and action_raw.strip()):
        raise YFinanceGradesError(f"[{ticker}] Action must be a non-empty exact string")
    action = _norm_action(action_raw)
    firm_raw = record["Firm"]
    if not (type(firm_raw) is str and firm_raw.strip()):
        raise YFinanceGradesError(f"[{ticker}] Firm must be a non-empty exact string")
    firm = " ".join(firm_raw.split())
    to_grade = record["ToGrade"]
    if not (type(to_grade) is str and to_grade.strip()):
        raise YFinanceGradesError(f"[{ticker}] ToGrade must be a non-empty exact string")
    from_grade = record["FromGrade"]
    if type(from_grade) is not str:
        raise YFinanceGradesError(f"[{ticker}] FromGrade must be an exact string")
    symbol = record.get("symbol")
    if symbol is not None and (type(symbol) is not str or canonical_us_ticker(symbol) != ticker):
        raise YFinanceGradesError(f"[{ticker}] record symbol mismatches the ticker key")
    if grade_date > observed_date:
        return "future", None
    if _days_between(as_of, grade_date) > window:
        return "stale", None
    return (
        "fit",
        {
            "date": grade_date,
            "grading_company": firm,
            "new_grade": to_grade,
            "previous_grade": from_grade,
            "action": action,
            "direction": _direction(action),
        },
    )


def resolve_yfinance_grade_actions(*, as_of: str, grades_by_ticker: Any) -> dict[str, Any]:
    """Resolve injected yfinance upgrades/downgrades rows to FMP-compatible grade actions.

    The return value has the exact top-level and per-summary shape consumed by
    ``project_analyst_grade_risk_downgrade``: ``signals``, ``records``,
    ``provenance``, ``excluded``, and ``checked``.
    """
    if not _valid_ymd(as_of):
        raise YFinanceGradesError(f"as_of must be a real YYYY-MM-DD decision date: {type(as_of).__name__}")
    canon = _canonical_keyed(grades_by_ticker)
    signals: dict[str, dict[str, Any]] = {}
    records: dict[str, list[dict[str, Any]]] = {}
    provenance: dict[str, dict[str, Any]] = {}
    excluded: dict[str, str] = {}
    checked: dict[str, dict[str, Any]] = {}
    for ticker, row in canon.items():
        prov = row["provenance"]
        observed_dt = _validate_provenance(prov, ticker=ticker, as_of=as_of)
        if prov["coverage_status"] != _COVERAGE_EMIT or prov["parser_status"] != _PARSER_EMIT:
            excluded[ticker] = f"coverage={prov['coverage_status']}/parser={prov['parser_status']}"
            continue
        raw_records = row["records"]
        if not isinstance(raw_records, list):
            raise YFinanceGradesError(f"[{ticker}].records must be a list")
        observed_date = observed_dt.strftime("%Y-%m-%d")
        fit: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        future_count = 0
        stale_count = 0
        for raw in raw_records:
            disposition, parsed = _classify_grade_record(
                raw,
                ticker=ticker,
                as_of=as_of,
                observed_date=observed_date,
                window=_RECENCY_WINDOW_DAYS,
            )
            if disposition == "fit":
                assert parsed is not None
                identity = (
                    parsed["date"],
                    _norm_firm(parsed["grading_company"]),
                    parsed["action"],
                    parsed["new_grade"],
                    parsed["previous_grade"],
                )
                if identity in seen:
                    raise YFinanceGradesError(f"[{ticker}] duplicate yfinance analyst-grade row identity")
                seen.add(identity)
                fit.append(parsed)
            elif disposition == "future":
                future_count += 1
            else:
                stale_count += 1
        counts = {
            "total_record_count": len(raw_records),
            "out_of_window_count": stale_count,
            "future_excluded_count": future_count,
        }
        base_provenance = {key: prov[key] for key in _PROVENANCE_FIELDS}
        provenance[ticker] = {**base_provenance, **counts}
        if not fit:
            checked[ticker] = {
                "disposition": _CHECKED_EMPTY_DISPOSITION,
                "coverage_status": prov["coverage_status"],
                "parser_status": prov["parser_status"],
                **counts,
            }
            continue
        fit.sort(key=lambda item: (item["date"], _norm_firm(item["grading_company"])))
        upgrades = sum(1 for item in fit if item["direction"] == "up")
        downgrades = sum(1 for item in fit if item["direction"] == "down")
        neutrals = len(fit) - upgrades - downgrades
        distinct_firms = len({_norm_firm(item["grading_company"]) for item in fit})
        distinct_downgrading_firms = len({
            _norm_firm(item["grading_company"]) for item in fit if item["direction"] == "down"
        })
        signals[ticker] = {
            "analyst_actions_recent": {
                "upgrades": upgrades,
                "downgrades": downgrades,
                "neutrals": neutrals,
                "net": upgrades - downgrades,
                "distinct_firms": distinct_firms,
                "distinct_downgrading_firms": distinct_downgrading_firms,
                "window_days": _RECENCY_WINDOW_DAYS,
            }
        }
        records[ticker] = fit
    return {
        "signals": signals,
        "records": records,
        "provenance": provenance,
        "excluded": excluded,
        "checked": checked,
    }


def load_binding() -> dict[str, Any]:
    return json.loads(BINDING_PATH.read_text(encoding="utf-8"))
