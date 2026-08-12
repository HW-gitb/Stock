from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PREREG_PATH = ROOT / "research" / "preregistrations" / "a_short_entry_funnel_calibration_20260713.json"
PREREG_SCHEMA_PATH = ROOT / "schemas" / "a_short_entry_funnel_calibration_preregistration.schema.json"
REPORT_SCHEMA_PATH = ROOT / "schemas" / "a_short_entry_funnel_calibration_report.schema.json"
ANALYSIS_INPUT_SCHEMA_PATH = ROOT / "schemas" / "analysis_input.schema.json"
HISTORICAL_REPORT_SCHEMA_PATH = ROOT / "schemas" / "a_short_entry_funnel_historical_report.schema.json"
DEFAULT_OUT = ROOT / "research" / "results" / "a_short" / "entry_funnel_calibration_20260713" / "calibration_report.json"
HISTORICAL_DEFAULT_OUT = ROOT / "research" / "results" / "a_short" / "entry_funnel_calibration" / "calibration_report.json"
HISTORICAL_PRICE_COLUMNS = ("as_of", "ts_code", "trade_date", "high", "low", "close")
HISTORICAL_SOURCE_ID = "authorized_local_historical_pit"
HISTORICAL_GAP_REASONS = (
    "missing_rule6_hard_veto",
    "missing_egs_breakout",
    "missing_m05_rule3",
    "insufficient_pit_price_window",
)


class HistoricalInputError(ValueError):
    """A structural historical-input defect: do not replace the active report."""


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def validate(payload: dict[str, Any], schema_path: Path, label: str) -> None:
    errors = sorted(
        Draft7Validator(load_json(schema_path)).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        first = errors[0]
        where = "/".join(str(part) for part in first.path) or "<root>"
        raise ValueError(f"{label} schema validation failed at {where}: {first.message}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_sources(prereg: dict[str, Any]) -> dict[str, list[tuple[dict[str, Any], Path]]]:
    verified: dict[str, list[tuple[dict[str, Any], Path]]] = {}
    for family, refs in prereg["source_refs"].items():
        rows: list[tuple[dict[str, Any], Path]] = []
        for ref in refs:
            path = ROOT / ref["path"]
            if not path.is_file() or sha256(path) != ref["sha256"]:
                raise ValueError(f"source missing or digest drifted: {ref['path']}")
            rows.append((ref, path))
        verified[family] = rows
    return verified


def classify_report(report: dict[str, Any], prereg: dict[str, Any]) -> str:
    machine = report.get("machine") or {}
    layer = machine.get("layer") or {}
    if layer.get("hard_veto"):
        return "hard_veto"
    entry = machine.get("entry_exit_size_star") or {}
    reason = str(entry.get("reject_reason") or "")
    frozen = prereg["frozen_measurement"]
    if frozen["ma_failure_marker"] in reason:
        return "ma_shape_failure"
    if frozen["entry_trigger_failure_marker"] in reason:
        return "entry_trigger_failure"
    if entry.get("plan") is not None:
        return "plan_present"
    return "unclassified"


def validate_iv_policy(prereg: dict[str, Any]) -> None:
    from runners.a_short_iv_feed_build import MIN_ROLL_OBS, ROLL_WINDOW, rolling_percentile_252
    from runners.a_short_phase5_engine import IV_HALVE_PCT, IV_NOBUILD_PCT
    import pandas as pd

    policy = prereg["iv_policy"]
    if (ROLL_WINDOW, MIN_ROLL_OBS, IV_HALVE_PCT, IV_NOBUILD_PCT) != (
        policy["window"], policy["minimum_observations"], 80.0, 90.0
    ):
        raise ValueError("runtime IV constants drifted from frozen calibration policy")
    tied = pd.DataFrame(
        {"trade_date": [f"d{i:03d}" for i in range(MIN_ROLL_OBS)], "iv_value": [0.2] * MIN_ROLL_OBS}
    )
    if float(rolling_percentile_252(tied).iloc[-1]["iv_percentile_252d"]) != 100.0:
        raise ValueError("runtime IV tie policy is not inclusive <= current")


def build_report(prereg: dict[str, Any], generated_at: str) -> dict[str, Any]:
    validate(prereg, PREREG_SCHEMA_PATH, "preregistration")
    sources = verified_sources(prereg)
    validate_iv_policy(prereg)

    classifications: list[str] = []
    weeks: set[str] = set()
    for ref, path in sources["weekly_reports_seen"]:
        weekly = load_json(path)
        if weekly.get("schema_name") != "a_short_weekly_report":
            raise ValueError(f"not an A-short weekly report: {ref['path']}")
        if any(bool(value) for value in (weekly.get("boundary") or {}).values()):
            raise ValueError(f"weekly source boundary is not research-only: {ref['path']}")
        weeks.add(str(weekly.get("as_of")))
        classifications.extend(classify_report(row, prereg) for row in weekly.get("reports", []))

    counts = {name: classifications.count(name) for name in prereg["frozen_measurement"]["classification_priority"]}
    candidate_count = len(classifications)
    no_hard_veto = candidate_count - counts["hard_veto"]
    ma_pass = no_hard_veto - counts["ma_shape_failure"]
    entry_pass = counts["plan_present"]
    rr_pass = counts["plan_present"]
    def rate(value: int, denominator: int) -> float | None:
        return round(value / denominator, 8) if denominator else None

    iv_values: list[float] = []
    for _, path in sources["iv_feeds_seen"]:
        feed = load_json(path)
        latest = (feed.get("series") or [])[-1]
        value = latest.get("iv_percentile_252d")
        if not isinstance(value, (int, float)):
            raise ValueError(f"IV source lacks latest percentile: {path}")
        iv_values.append(float(value))

    seen_candidates = 0
    seen_eligible = 0
    for _, path in sources["overlays_seen"]:
        overlay = load_json(path)
        if overlay.get("track") != "comparison_non_production":
            raise ValueError(f"overlay is not comparison-only: {path}")
        rows = overlay.get("candidates") or []
        seen_candidates += len(rows)
        seen_eligible += sum(bool(row.get("eligible")) for row in rows)

    future_min_weeks = int(prereg["decision_gates"]["future_confirmatory_min_weeks"])
    future_min_candidates = int(prereg["decision_gates"]["future_confirmatory_min_candidates"])
    sample_sufficient = len(weeks) >= future_min_weeks and candidate_count >= future_min_candidates
    conclusion_status = (
        "insufficient_sample_with_entry_trigger_bottleneck"
        if not sample_sufficient and counts["entry_trigger_failure"] > 0 and entry_pass == 0
        else "within_calibration_band"
    )

    prereg_rel = PREREG_PATH.relative_to(ROOT).as_posix()
    return {
        "schema_name": "a_short_entry_funnel_calibration_report",
        "schema_version": "1.1.0",
        "generated_at": generated_at,
        "preregistration_ref": {"path": prereg_rel, "sha256": sha256(PREREG_PATH)},
        "source_integrity": {
            "status": "all_sha256_verified",
            "verified_files": sum(len(rows) for rows in sources.values()),
            "provider_calls": 0,
            "random_simulations": 0
        },
        "funnel": {
            "distinct_weeks": len(weeks),
            "candidate_count": candidate_count,
            "hard_veto_count": counts["hard_veto"],
            "ma_shape_failure_count": counts["ma_shape_failure"],
            "entry_trigger_failure_count": counts["entry_trigger_failure"],
            "rr_plan_count": rr_pass,
            "capital_gate_evaluable_count": 0,
            "unclassified_count": counts["unclassified"],
            "stages": [
                {"stage": "egs_candidate", "passed_count": candidate_count, "pass_rate": 1.0, "status": "observed"},
                {"stage": "no_hard_veto", "passed_count": no_hard_veto, "pass_rate": rate(no_hard_veto, candidate_count), "status": "observed"},
                {"stage": "ma_shape", "passed_count": ma_pass, "pass_rate": rate(ma_pass, no_hard_veto), "status": "observed"},
                {"stage": "low_pullback_or_breakout", "passed_count": entry_pass, "pass_rate": rate(entry_pass, ma_pass), "status": "observed"},
                {"stage": "reward_risk", "passed_count": rr_pass, "pass_rate": rate(rr_pass, entry_pass), "status": "observed"},
                {"stage": "capital_gate", "passed_count": 0, "pass_rate": None, "status": "not_evaluable_private_account"}
            ]
        },
        "iv_boundary": {
            "observation_count": len(iv_values),
            "minimum": min(iv_values),
            "median": statistics.median(iv_values),
            "maximum": max(iv_values),
            "above_80_count": sum(value > 80.0 for value in iv_values),
            "above_90_count": sum(value > 90.0 for value in iv_values),
            "exact_80_count": sum(value == 80.0 for value in iv_values),
            "exact_90_count": sum(value == 90.0 for value in iv_values),
            "policy_verified": True
        },
        "overlay_evidence": {
            "seen_observations": len(sources["overlays_seen"]),
            "seen_candidate_count": seen_candidates,
            "seen_eligible_count": seen_eligible,
            "future_confirmatory_observations": 0,
            "future_confirmatory_required": 12,
            "promotion_evaluable": False
        },
        "calibration_conclusion": {
            "status": conclusion_status,
            "observed_bottleneck": "low_pullback_or_breakout" if entry_pass == 0 else "none",
            "egs_entry_mismatch_proven": False,
            "specific_threshold_too_strict_proven": False,
            "sample_sufficient": sample_sufficient,
            "production_threshold_change": False,
            "next_evidence": "collect_frozen_future_confirmatory_weeks_without_threshold_changes"
        },
        "boundary": {
            "lane_role": "risk_filter_only",
            "calibration_only": True,
            "is_alpha": False,
            "is_buy_advice": False,
            "satisfies_ship_gate": False,
            "full_size_allowed": False
        }
    }


def write_report(report: dict[str, Any], path: Path, *, schema_path: Path = REPORT_SCHEMA_PATH,
                 label: str = "calibration report") -> None:
    """Validate then atomically publish a report without permitting non-finite JSON."""
    validate(report, schema_path, label)
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _canonical_date(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise HistoricalInputError(f"{label} must be canonical YYYYMMDD")
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise HistoricalInputError(f"{label} is not a real calendar date") from exc
    if parsed.strftime("%Y%m%d") != value:
        raise HistoricalInputError(f"{label} must be canonical YYYYMMDD")
    return value


def _finite_price(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise HistoricalInputError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HistoricalInputError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise HistoricalInputError(f"{label} must be a finite number")
    return number


def _historical_source_missing_report(generated_at: str) -> dict[str, Any]:
    return {
        "schema_name": "a_short_entry_funnel_historical_report",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "source_readiness": {
            "status": "source_missing",
            "logical_source_id": HISTORICAL_SOURCE_ID,
            "input_filenames": ["analysis_input.json", "prices.csv"],
            "date_range": {"first_as_of": None, "last_as_of": None},
            "distinct_weeks": 0,
            "price_row_count": 0,
            "analysis_input_schema_versions": [],
            "provider_calls": 0,
        },
        "decision_policy": {
            "mode": "historical_input_readiness_only",
            "provider_calls": 0,
            "production_threshold_change": False,
        },
        "funnel": {
            "candidate_count": 0,
            "evaluable_candidate_count": 0,
            "not_evaluable_candidate_count": 0,
            "not_evaluable_reason_counts": {reason: 0 for reason in HISTORICAL_GAP_REASONS},
        },
        "entry_diagnostic": {
            "status": "not_run_source_missing",
            "price_window_required": 20,
        },
        "calibration_conclusion": {
            "status": "insufficient_sample",
            "sample_sufficient": False,
            "next_evidence": "provide_authorized_historical_pit_source",
        },
        "boundary": {
            "calibration_only": True,
            "production_unchanged": True,
            "is_buy_advice": False,
            "satisfies_ship_gate": False,
            "full_size_allowed": False,
        },
    }


def _historical_analysis_inputs(historical_root: Path) -> list[tuple[str, dict[str, Any]]] | None:
    analysis_root = historical_root / "analysis_inputs"
    if not historical_root.is_dir() or not analysis_root.is_dir():
        return None
    dated_directories = sorted(path for path in analysis_root.iterdir() if path.is_dir())
    if not dated_directories:
        return None
    inputs: list[tuple[str, dict[str, Any]]] = []
    for directory in dated_directories:
        as_of = _canonical_date(directory.name, "analysis input directory")
        path = directory / "analysis_input.json"
        if not path.is_file():
            return None
        try:
            analysis_input = load_json(path)
            validate(analysis_input, ANALYSIS_INPUT_SCHEMA_PATH, "historical analysis input")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise HistoricalInputError(str(exc)) from exc
        trade_date = _canonical_date(analysis_input.get("trade_date"), "analysis input trade_date")
        if trade_date != as_of:
            raise HistoricalInputError("analysis input trade_date does not match its as_of directory")
        inputs.append((as_of, analysis_input))
    return inputs


def _historical_prices(prices_path: Path, known_as_of: set[str]) -> tuple[dict[tuple[str, str], int], int]:
    if not prices_path.is_file():
        raise FileNotFoundError(prices_path)
    price_counts: dict[tuple[str, str], int] = {}
    primary_keys: set[tuple[str, str, str]] = set()
    row_count = 0
    try:
        with prices_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != HISTORICAL_PRICE_COLUMNS:
                raise HistoricalInputError("prices.csv columns must be as_of,ts_code,trade_date,high,low,close")
            for line_number, row in enumerate(reader, start=2):
                as_of = _canonical_date(row.get("as_of"), f"prices.csv line {line_number} as_of")
                if as_of not in known_as_of:
                    raise HistoricalInputError("prices.csv contains an as_of without a matching analysis input")
                ts_code = str(row.get("ts_code") or "")
                if not ts_code:
                    raise HistoricalInputError(f"prices.csv line {line_number} ts_code is missing")
                trade_date = _canonical_date(row.get("trade_date"), f"prices.csv line {line_number} trade_date")
                if trade_date > as_of:
                    raise HistoricalInputError("prices.csv contains a future trade_date")
                key = (as_of, ts_code, trade_date)
                if key in primary_keys:
                    raise HistoricalInputError("prices.csv contains a duplicate (as_of,ts_code,trade_date)")
                primary_keys.add(key)
                for field in ("high", "low", "close"):
                    _finite_price(row.get(field), f"prices.csv line {line_number} {field}")
                price_counts[(as_of, ts_code)] = price_counts.get((as_of, ts_code), 0) + 1
                row_count += 1
    except OSError as exc:
        raise HistoricalInputError(f"could not read prices.csv: {exc}") from exc
    return price_counts, row_count


def _candidate_gap_reasons(candidate: dict[str, Any], volatility: dict[str, Any],
                           as_of: str, price_counts: dict[tuple[str, str], int]) -> list[str]:
    reasons: list[str] = []
    derived = candidate.get("derived_flags") or {}
    rule6_checks = ((candidate.get("event_risk") or {}).get("rule6_checks"))
    if not isinstance(rule6_checks, list) or not rule6_checks or not isinstance(derived.get("hard_veto"), bool):
        reasons.append("missing_rule6_hard_veto")
    if not isinstance(derived.get("is_breakout"), bool):
        reasons.append("missing_egs_breakout")
    m05_keys = (
        "iv_change_abs_1d_pctpt", "rule3_status", "awakening_status", "cash_reclaim_pct",
    )
    if (
        not isinstance(volatility, dict)
        or any(key not in volatility for key in m05_keys)
        or volatility.get("rule3_status") is None
        or volatility.get("awakening_status") is None
    ):
        reasons.append("missing_m05_rule3")
    if price_counts.get((as_of, str(candidate.get("ts_code") or "")), 0) < 20:
        reasons.append("insufficient_pit_price_window")
    return reasons


def build_historical_report(historical_root: Path, generated_at: str) -> tuple[dict[str, Any], int]:
    """Build the 15A readiness report from local PIT inputs only; never call a provider."""
    inputs = _historical_analysis_inputs(historical_root)
    prices_path = historical_root / "prices.csv"
    if inputs is None or not prices_path.is_file():
        return _historical_source_missing_report(generated_at), 2
    known_as_of = {as_of for as_of, _ in inputs}
    price_counts, price_row_count = _historical_prices(prices_path, known_as_of)
    candidate_count = 0
    evaluable_candidate_count = 0
    reason_counts = {reason: 0 for reason in HISTORICAL_GAP_REASONS}
    versions: set[str] = set()
    as_of_dates: list[str] = []
    for as_of, analysis_input in inputs:
        as_of_dates.append(as_of)
        versions.add(str(analysis_input.get("schema_version")))
        volatility = ((analysis_input.get("market_context") or {}).get("volatility") or {})
        for candidate in analysis_input.get("candidates") or []:
            candidate_count += 1
            reasons = _candidate_gap_reasons(candidate, volatility, as_of, price_counts)
            if reasons:
                for reason in reasons:
                    reason_counts[reason] += 1
            else:
                evaluable_candidate_count += 1
    distinct_weeks = len({datetime.strptime(as_of, "%Y%m%d").isocalendar()[:2] for as_of in as_of_dates})
    not_evaluable_candidate_count = candidate_count - evaluable_candidate_count
    readiness_status = "ready" if not_evaluable_candidate_count == 0 else "ready_with_candidate_gaps"
    return {
        "schema_name": "a_short_entry_funnel_historical_report",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "source_readiness": {
            "status": readiness_status,
            "logical_source_id": HISTORICAL_SOURCE_ID,
            "input_filenames": ["analysis_input.json", "prices.csv"],
            "date_range": {"first_as_of": min(as_of_dates), "last_as_of": max(as_of_dates)},
            "distinct_weeks": distinct_weeks,
            "price_row_count": price_row_count,
            "analysis_input_schema_versions": sorted(versions),
            "provider_calls": 0,
        },
        "decision_policy": {
            "mode": "historical_input_readiness_only",
            "provider_calls": 0,
            "production_threshold_change": False,
        },
        "funnel": {
            "candidate_count": candidate_count,
            "evaluable_candidate_count": evaluable_candidate_count,
            "not_evaluable_candidate_count": not_evaluable_candidate_count,
            "not_evaluable_reason_counts": reason_counts,
        },
        "entry_diagnostic": {
            "status": "not_run_15b_pending",
            "price_window_required": 20,
        },
        "calibration_conclusion": {
            "status": "insufficient_sample",
            "sample_sufficient": False,
            "next_evidence": "complete_15b_production_replay_before_any_rule_change",
        },
        "boundary": {
            "calibration_only": True,
            "production_unchanged": True,
            "is_buy_advice": False,
            "satisfies_ship_gate": False,
            "full_size_allowed": False,
        },
    }, 0


def _active_generated_at(value: str | None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline preregistered A-short funnel/IV/overlay calibration.")
    parser.add_argument("--preregistration", type=Path)
    parser.add_argument("--historical-root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--generated-at")
    args = parser.parse_args(argv)
    if args.historical_root is not None:
        if args.preregistration is not None:
            print("[ERROR] --historical-root cannot be combined with legacy --preregistration", file=sys.stderr)
            return 1
        out = args.out or HISTORICAL_DEFAULT_OUT
        if out.resolve() == DEFAULT_OUT.resolve():
            print("[ERROR] historical mode cannot write the legacy replay output", file=sys.stderr)
            return 1
        try:
            report, exit_code = build_historical_report(args.historical_root, _active_generated_at(args.generated_at))
            write_report(report, out, schema_path=HISTORICAL_REPORT_SCHEMA_PATH,
                         label="historical calibration report")
        except (HistoricalInputError, OSError, ValueError) as exc:
            print(f"[ERROR] historical input rejected: {exc}", file=sys.stderr)
            return 1
        print(f"[historical-readiness] status={report['source_readiness']['status']} wrote {out}")
        return exit_code
    preregistration = args.preregistration or PREREG_PATH
    out = args.out or DEFAULT_OUT
    if out.resolve() == HISTORICAL_DEFAULT_OUT.resolve():
        print("[ERROR] legacy replay cannot write the active historical output", file=sys.stderr)
        return 1
    if preregistration.resolve() != PREREG_PATH.resolve():
        raise ValueError("only the frozen reviewed preregistration path is accepted")
    report = build_report(load_json(preregistration), args.generated_at or "2026-07-13T18:30:00+08:00")
    write_report(report, out)
    print(f"[OK] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
