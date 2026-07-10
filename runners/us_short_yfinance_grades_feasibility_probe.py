"""Bounded, low-trust feasibility probe for yfinance analyst-grade signals in the 20260710 US-short cohort.

This is an experiment only. It does not select a provider, feed the weekly runner, alter §4.2 scoring, or create
production / ship-gate evidence. The default invocation is dry-run: it reads the existing local cohort artifacts,
prints the exact sample plan, imports nothing, fetches nothing, and writes nothing. A live probe requires the
explicit ``--confirm-user-authorization`` switch and an already-installed ``yfinance`` package; this script never
installs dependencies.

The live sample is source-bound to the freshday Pass2 result: 12 symbols from the FMP-402 small-cap cohort, 30
highest-momentum symbols from the same top-200 cohort, and the two FMP-200 controls HOOD/MRNA. Raw yfinance tables
stay under the gitignored provider_samples root. The tracked summary contains aggregate counts and field-shape only;
it contains neither raw rows, ticker names, URLs, nor secrets.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if _PYTHON_LIBS.exists() and str(_PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(_PYTHON_LIBS))


DECISION_DATE = "20260710"
PRICE_BASIS_DATE = "20260709"
CANDIDATE_SUBSET_PATH = ROOT / "state" / "us_short" / "us_short_batch5_capstone_20260710_candidate_subset.json"
MOMENTUM_PROJECTION_PATH = ROOT / "state" / "us_short" / "us_short_batch5_capstone_20260710_momentum_projection.json"
FMP_GRADE_ACTIONS_PATH = ROOT / "state" / "us_short" / "us_short_batch5_capstone_20260710_analyst_grade_actions.json"
RAW_REL_ROOT = Path("provider_samples/us_short_yfinance_grades_feasibility_20260710")
RAW_ROOT = ROOT / RAW_REL_ROOT / "raw"
SUMMARY_PATH = ROOT / "docs" / "us_short_yfinance_grades_feasibility_probe_summary_20260710.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_yfinance_grades_feasibility_probe_summary.schema.json"

FMP_402_EXEMPLARS = ("ABCL", "YEXT", "ZBIO", "ZURA")
FMP_200_CONTROLS = ("HOOD", "MRNA")
FMP_402_SMALL_CAP_SAMPLE_COUNT = 12
MOMENTUM_TOP200_SAMPLE_COUNT = 30
TOTAL_PLANNED_SYMBOLS = FMP_402_SMALL_CAP_SAMPLE_COUNT + MOMENTUM_TOP200_SAMPLE_COUNT + len(FMP_200_CONTROLS)
RECENT_DAYS = 90
DEFAULT_PACE_SECONDS = 1.0
_SUMMARY_FORBIDDEN = re.compile(r"(?i)(https?://|api[_-]?key|authorization|cookie|\btoken\b)")


class YFinanceGradesProbeError(RuntimeError):
    """The feasibility probe cannot safely produce a result."""


class _YFinanceClient:
    def __init__(self, module):
        self._module = module

    def ticker(self, symbol: str):
        return self._module.Ticker(symbol)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise YFinanceGradesProbeError(f"required local artifact is unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise YFinanceGradesProbeError(f"required local artifact must be a JSON object: {path.name}")
    return value


def _canonical_symbol(value: Any) -> str:
    if not (isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", value)):
        raise YFinanceGradesProbeError("candidate ticker must be canonical uppercase US symbol")
    return value


def _finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise YFinanceGradesProbeError("momentum / market-cap source value must be numeric")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise YFinanceGradesProbeError("momentum / market-cap source value must be finite")
    return number


def build_probe_plan(candidate_subset: dict[str, Any], momentum_projection: dict[str, Any],
                     analyst_grade_actions: dict[str, Any]) -> dict[str, Any]:
    """Bind the fixed experiment to the 20260710 top-200 and its observed FMP grades result."""
    rows = candidate_subset.get("rows")
    if not (isinstance(rows, list) and len(rows) == 200 and candidate_subset.get("row_count") == 200):
        raise YFinanceGradesProbeError("candidate subset must be the exact 20260710 top-200 cohort")
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise YFinanceGradesProbeError("candidate subset row must be an object")
        symbol = _canonical_symbol(row.get("ticker"))
        if symbol in by_symbol:
            raise YFinanceGradesProbeError("candidate subset contains duplicate ticker")
        by_symbol[symbol] = row

    momentum = momentum_projection.get("momentum_by_ticker")
    if not isinstance(momentum, dict):
        raise YFinanceGradesProbeError("momentum projection missing momentum_by_ticker")
    scores = {symbol: _finite_number(momentum.get(symbol)) for symbol in by_symbol if symbol in momentum}
    if set(scores) != set(by_symbol):
        raise YFinanceGradesProbeError("momentum projection must exactly cover the top-200 cohort")

    records = analyst_grade_actions.get("records")
    if not isinstance(records, dict):
        raise YFinanceGradesProbeError("FMP grades artifact missing records")
    success_symbols = {_canonical_symbol(symbol) for symbol, value in records.items() if isinstance(value, list)}
    if success_symbols != set(FMP_200_CONTROLS):
        raise YFinanceGradesProbeError("20260710 FMP grades success controls must be exactly HOOD and MRNA")
    if not success_symbols.issubset(by_symbol):
        raise YFinanceGradesProbeError("FMP grades controls must belong to the top-200 cohort")

    cohort_402 = set(by_symbol) - success_symbols
    if len(cohort_402) != 198 or not set(FMP_402_EXEMPLARS).issubset(cohort_402):
        raise YFinanceGradesProbeError("FMP-402 cohort does not match the 20260710 freshday fact")

    exemplars = list(FMP_402_EXEMPLARS)
    remaining_small_cap = sorted(
        (symbol for symbol in cohort_402 if symbol not in exemplars),
        key=lambda symbol: (_finite_number(by_symbol[symbol].get("market_cap_usd")), symbol),
    )
    small_caps = exemplars + remaining_small_cap[:FMP_402_SMALL_CAP_SAMPLE_COUNT - len(exemplars)]
    excluded = set(small_caps) | success_symbols
    momentum_sample = sorted(
        (symbol for symbol in by_symbol if symbol not in excluded),
        key=lambda symbol: (-scores[symbol], symbol),
    )[:MOMENTUM_TOP200_SAMPLE_COUNT]
    if len(small_caps) != FMP_402_SMALL_CAP_SAMPLE_COUNT or len(momentum_sample) != MOMENTUM_TOP200_SAMPLE_COUNT:
        raise YFinanceGradesProbeError("source-bound cohort cannot fill the fixed yfinance sample")

    items = ([{"ticker": symbol, "group": "fmp_402_small_cap"} for symbol in small_caps]
             + [{"ticker": symbol, "group": "momentum_top200"} for symbol in momentum_sample]
             + [{"ticker": symbol, "group": "fmp_200_control"} for symbol in FMP_200_CONTROLS])
    if len({item["ticker"] for item in items}) != TOTAL_PLANNED_SYMBOLS:
        raise YFinanceGradesProbeError("probe sample groups must be disjoint")
    return {
        "decision_date": DECISION_DATE,
        "price_basis_date": PRICE_BASIS_DATE,
        "items": items,
        "counts": {
            "fmp_402_small_cap": FMP_402_SMALL_CAP_SAMPLE_COUNT,
            "momentum_top200": MOMENTUM_TOP200_SAMPLE_COUNT,
            "fmp_200_control": len(FMP_200_CONTROLS),
            "total": TOTAL_PLANNED_SYMBOLS,
        },
    }


def load_default_plan() -> dict[str, Any]:
    return build_probe_plan(
        _load_json(CANDIDATE_SUBSET_PATH),
        _load_json(MOMENTUM_PROJECTION_PATH),
        _load_json(FMP_GRADE_ACTIONS_PATH),
    )


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _validate_write_paths(raw_root: Path, summary_path: Path) -> None:
    approved_root = (ROOT / RAW_REL_ROOT).resolve()
    try:
        raw_root.resolve().relative_to(approved_root)
    except ValueError as exc:
        raise YFinanceGradesProbeError("raw path must stay under this probe's provider_samples root") from exc
    if summary_path.resolve() != SUMMARY_PATH.resolve():
        try:
            summary_path.resolve().relative_to(approved_root)
        except ValueError as exc:
            raise YFinanceGradesProbeError(
                "summary path must be the canonical tracked summary or stay under this probe's provider_samples root"
            ) from exc
    if "provider_samples/" not in (ROOT / ".gitignore").read_text(encoding="utf-8"):
        raise YFinanceGradesProbeError("provider_samples must remain gitignored before a yfinance probe can run")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _table_rows(table: Any) -> tuple[list[str], list[dict[str, Any]]]:
    """Convert a pandas-like table or a simple test list to JSON-safe records without importing pandas."""
    if table is None:
        return [], []
    if isinstance(table, list):
        if not all(isinstance(row, dict) for row in table):
            raise YFinanceGradesProbeError("yfinance table list must contain objects")
        fields = sorted({str(key) for row in table for key in row})
        return fields, [{str(key): _jsonable(value) for key, value in row.items()} for row in table]
    if not (hasattr(table, "reset_index") and hasattr(table, "to_dict")):
        raise YFinanceGradesProbeError("yfinance table must be pandas-like or a list of objects")
    normalized = table.reset_index()
    fields = [str(column) for column in getattr(normalized, "columns", [])]
    records = normalized.to_dict(orient="records")
    if not (isinstance(records, list) and all(isinstance(row, dict) for row in records)):
        raise YFinanceGradesProbeError("yfinance table cannot be converted to records")
    return fields, [{str(key): _jsonable(value) for key, value in row.items()} for row in records]


def _date_value(value: Any) -> date | None:
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            return value.date()
        except (TypeError, ValueError, OverflowError):
            return None
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _grade_summary(fields: list[str], rows: list[dict[str, Any]], *, as_of: date) -> dict[str, Any]:
    date_field = next((field for field in ("GradeDate", "Date", "Datetime", "date", "datetime", "index") if field in fields), None)
    canonical_fields = set(fields)
    if date_field is not None:
        canonical_fields.add("GradeDate")
    recent_usable = 0
    date_parseable = 0
    future = 0
    stale = 0
    for row in rows:
        grade_date = _date_value(row.get(date_field)) if date_field else None
        if grade_date is None:
            continue
        date_parseable += 1
        if grade_date > as_of:
            future += 1
            continue
        if (as_of - grade_date).days > RECENT_DAYS:
            stale += 1
            continue
        if all(isinstance(row.get(field), str) and row[field].strip() for field in ("Action", "Firm", "ToGrade")):
            recent_usable += 1
    return {
        "row_count": len(rows),
        "field_presence": {field: field in canonical_fields for field in ("Action", "Firm", "ToGrade", "GradeDate")},
        "date_parseable_count": date_parseable,
        "future_date_count": future,
        "stale_date_count": stale,
        "recent90_usable_count": recent_usable,
        "has_recent90_usable_signal": recent_usable > 0,
    }


def _recommendation_summary(fields: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"row_count": len(rows), "field_count": len(fields), "nonempty": bool(rows)}


def _error_category(exc: Exception) -> str:
    text = str(exc).lower()
    if "429" in text or "too many" in text or "crumb" in text:
        return "rate_limit_or_crumb_failure"
    return "fetch_error"


def _fetch_one(client, symbol: str, *, as_of: date) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        ticker = client.ticker(symbol)
        upgrades = ticker.upgrades_downgrades
        recommendations = ticker.recommendations
        upgrade_fields, upgrade_rows = _table_rows(upgrades)
        recommendation_fields, recommendation_rows = _table_rows(recommendations)
    except Exception as exc:  # provider exceptions are converted to no-secret categories, never surfaced in a summary
        return {"status": _error_category(exc)}, None
    upgrade_summary = _grade_summary(upgrade_fields, upgrade_rows, as_of=as_of)
    recommendation_summary = _recommendation_summary(recommendation_fields, recommendation_rows)
    return {
        "status": "ok",
        "upgrades_downgrades": upgrade_summary,
        "recommendations": recommendation_summary,
    }, {
        "ticker": symbol,
        "upgrades_downgrades": upgrade_rows,
        "recommendations": recommendation_rows,
    }


def _empty_group_counts() -> dict[str, dict[str, int]]:
    return {group: {"attempted_count": 0, "recent90_usable_count": 0}
            for group in ("fmp_402_small_cap", "momentum_top200", "fmp_200_control")}


def _coverage_percent(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 4) if denominator else 0.0


def _build_summary(plan: dict[str, Any], attempts: list[dict[str, Any]], *, as_of: date,
                   pace_seconds: float, halted: bool) -> dict[str, Any]:
    groups = _empty_group_counts()
    field_presence = {field: 0 for field in ("Action", "Firm", "ToGrade", "GradeDate")}
    recommendation_nonempty = 0
    date_parseable = future_dates = stale_dates = rate_failures = fetch_errors = 0
    first_rate_failure = None
    for index, attempt in enumerate(attempts, start=1):
        group = attempt["group"]
        groups[group]["attempted_count"] += 1
        status = attempt["status"]
        if status == "rate_limit_or_crumb_failure":
            rate_failures += 1
            first_rate_failure = index if first_rate_failure is None else first_rate_failure
            continue
        if status != "ok":
            fetch_errors += 1
            continue
        upgrades = attempt["upgrades_downgrades"]
        groups[group]["recent90_usable_count"] += int(upgrades["has_recent90_usable_signal"])
        for field, present in upgrades["field_presence"].items():
            field_presence[field] += int(present)
        recommendation_nonempty += int(attempt["recommendations"]["nonempty"])
        date_parseable += upgrades["date_parseable_count"]
        future_dates += upgrades["future_date_count"]
        stale_dates += upgrades["stale_date_count"]

    coverage = {
        group: {**counts, "recent90_coverage_pct": _coverage_percent(
            counts["recent90_usable_count"], counts["attempted_count"])}
        for group, counts in groups.items()
    }
    completed_all = len(attempts) == plan["counts"]["total"]
    reason_codes = []
    if coverage["fmp_402_small_cap"]["recent90_coverage_pct"] < 50.0:
        reason_codes.append("small_cap_coverage_below_50_percent")
    if rate_failures:
        reason_codes.append("rate_limit_or_crumb_failure")
    if fetch_errors:
        reason_codes.append("fetch_error")
    if not completed_all:
        reason_codes.append("incomplete_sample")
    verdict = "worth_building" if not reason_codes else "not_worth_building"
    status = "halted_rate_limit_or_crumb_failure" if halted else (
        "completed_with_fetch_errors" if fetch_errors else "completed")
    return {
        "schema_name": "us_short_yfinance_grades_feasibility_probe_summary",
        "schema_version": "1.0.0",
        "scope": {
            "status": status,
            "decision_date": DECISION_DATE,
            "price_basis_date": PRICE_BASIS_DATE,
            "yfinance_low_trust_feasibility_only": True,
            "provider_selected": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "ship_gate_evidence_claimed": False,
        },
        "input_artifacts": {
            "candidate_subset_path": _repo_relative(CANDIDATE_SUBSET_PATH),
            "momentum_projection_path": _repo_relative(MOMENTUM_PROJECTION_PATH),
            "fmp_grade_actions_path": _repo_relative(FMP_GRADE_ACTIONS_PATH),
            "fmp_200_success_control_count": len(FMP_200_CONTROLS),
        },
        "sample": {
            "planned_total": plan["counts"]["total"],
            "fmp_402_small_cap_planned": plan["counts"]["fmp_402_small_cap"],
            "momentum_top200_planned": plan["counts"]["momentum_top200"],
            "fmp_200_control_planned": plan["counts"]["fmp_200_control"],
            "ticker_names_in_summary": False,
        },
        "execution": {
            "attempted_symbol_count": len(attempts),
            "successful_symbol_count": sum(item["status"] == "ok" for item in attempts),
            "pace_seconds": pace_seconds,
            "stopped_early": halted,
        },
        "coverage": coverage,
        "field_shape": {
            "upgrades_downgrades_field_presence_count": field_presence,
            "recommendations_nonempty_symbol_count": recommendation_nonempty,
        },
        "freshness_and_pit": {
            "as_of": as_of.isoformat(),
            "recent_window_days": RECENT_DAYS,
            "grade_date_parseable_count": date_parseable,
            "future_grade_date_count": future_dates,
            "stale_grade_date_count": stale_dates,
        },
        "rate_limit": {
            "rate_limit_or_crumb_failure_count": rate_failures,
            "first_failure_symbol_index": first_rate_failure,
            "pacing_controlled": rate_failures == 0 and completed_all,
        },
        "fmp_cross_check": {
            "fmp_200_control_symbol_count": len(FMP_200_CONTROLS),
            "yfinance_recent90_control_count": coverage["fmp_200_control"]["recent90_usable_count"],
        },
        "decision": {
            "pass_criterion": "small_cap_recent90_coverage_pct_gte_50_and_no_rate_limit_or_crumb_failure",
            "verdict": verdict,
            "reason_codes": reason_codes,
        },
        "storage": {
            "raw_payload_root": _repo_relative(RAW_ROOT),
            "raw_payload_root_gitignored": True,
            "tracked_summary_path": _repo_relative(SUMMARY_PATH),
            "tracked_summary_contains_tickers": False,
        },
    }


def validate_summary(summary: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise YFinanceGradesProbeError("jsonschema is required to validate the feasibility summary") from exc
    schema = _load_json(SUMMARY_SCHEMA_PATH)
    errors = sorted(Draft7Validator(schema).iter_errors(summary), key=lambda err: list(err.path))
    if errors:
        raise YFinanceGradesProbeError("yfinance feasibility summary failed schema validation: " + errors[0].message)


def _assert_summary_safe(summary: dict[str, Any]) -> None:
    text = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    if _SUMMARY_FORBIDDEN.search(text):
        raise YFinanceGradesProbeError("tracked yfinance feasibility summary may not contain secrets, URLs, or raw payload fields")


def _write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_yfinance_client(importer) -> _YFinanceClient:
    try:
        module = importer("yfinance")
    except ModuleNotFoundError as exc:
        raise YFinanceGradesProbeError(
            "yfinance is not installed; install it only through a separate dependency decision before a live probe"
        ) from exc
    return _YFinanceClient(module)


def run_probe(plan: dict[str, Any], *, client=None, importer=importlib.import_module,
              confirm_user_authorization: bool, raw_root: Path = RAW_ROOT, summary_path: Path = SUMMARY_PATH,
              as_of: date | None = None, pace_seconds: float = DEFAULT_PACE_SECONDS) -> dict[str, Any]:
    """Run the networked half only after explicit per-execution approval; injected clients keep all tests offline."""
    if not confirm_user_authorization:
        raise YFinanceGradesProbeError("live yfinance execution requires --confirm-user-authorization")
    if not isinstance(pace_seconds, (int, float)) or isinstance(pace_seconds, bool) or not 0 <= pace_seconds <= 60:
        raise YFinanceGradesProbeError("pace_seconds must be finite and within [0, 60]")
    _validate_write_paths(raw_root, summary_path)
    as_of = as_of or date.today()
    client = _load_yfinance_client(importer) if client is None else client
    raw_root.mkdir(parents=True, exist_ok=True)

    attempts: list[dict[str, Any]] = []
    halted = False
    for index, item in enumerate(plan["items"], start=1):
        symbol = item["ticker"]
        result, raw = _fetch_one(client, symbol, as_of=as_of)
        attempts.append({"group": item["group"], **result})
        if raw is not None:
            _write_json_atomic(raw, raw_root / f"{symbol}.json")
        if result["status"] == "rate_limit_or_crumb_failure":
            halted = True
            break
        if index < len(plan["items"]) and pace_seconds:
            time.sleep(float(pace_seconds))

    summary = _build_summary(plan, attempts, as_of=as_of, pace_seconds=float(pace_seconds), halted=halted)
    validate_summary(summary)
    _assert_summary_safe(summary)
    _write_json_atomic(summary, summary_path)
    return summary


def _dry_run_result(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": {
            "status": "dry_run_only",
            "network_access_performed": False,
            "yfinance_import_attempted": False,
            "raw_payload_written": False,
            "tracked_summary_written": False,
        },
        "sample": {
            "planned_total": plan["counts"]["total"],
            "items": plan["items"],
        },
        "decision": {
            "live_requires": "--confirm-user-authorization",
            "pass_criterion": "small_cap_recent90_coverage_pct_gte_50_and_no_rate_limit_or_crumb_failure",
        },
    }


def run_default(*, dry_run: bool, importer=importlib.import_module, plan_loader=load_default_plan) -> dict[str, Any]:
    plan = plan_loader()
    if dry_run:
        return _dry_run_result(plan)
    return run_probe(plan, importer=importer, confirm_user_authorization=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded yfinance analyst-grade feasibility probe (dry-run by default).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the fixed sample plan without import, fetch, or write")
    mode.add_argument("--confirm-user-authorization", action="store_true",
                      help="perform the bounded yfinance fetch; requires separately authorized execution")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_default(dry_run=not args.confirm_user_authorization)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
