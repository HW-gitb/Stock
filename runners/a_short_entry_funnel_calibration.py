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

from engine.a_short_nullable_bool import fail_closed_risk_bool
from engine.a_short_rule6_contract import assess_rule6_checks
from runners.a_short_phase5_engine import (
    breakout_source_agreement,
    compute_indicators,
    effective_support,
    entry_exit_geometry,
    entry_type,
)

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
    "iv_feed_not_ready",
    "insufficient_pit_price_window",
)
CALIBRATION_POLICY = {
    "minimum_distinct_weeks": 12,
    "minimum_diagnostic_candidates": 120,
    "target_pre_capital_build_rate": [0.02, 0.20],
    "target_active_week_rate": [0.25, 0.75],
    "band_points": [0.015, 0.02, 0.03, 0.05],
}
CALIBRATION_STATUSES = {
    "insufficient_sample",
    "within_calibration_band",
    "too_lax",
    "egs_entry_mismatch",
    "specific_gate_too_strict",
}


class HistoricalInputError(ValueError):
    """A structural historical-input defect: do not replace the active report."""


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 8) if denominator else None


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "minimum": min(values) if values else None,
        "median": statistics.median(values) if values else None,
        "maximum": max(values) if values else None,
    }


def _metrics_from_weeks(weeks: dict[tuple[int, int], dict[str, int]]) -> dict[str, dict[str, float | None]]:
    candidate_count = sum(row["candidates"] for row in weeks.values())
    plan_count = sum(row["plans"] for row in weeks.values())
    active_week_count = sum(row["plans"] > 0 for row in weeks.values())
    active_candidate_count = sum(row["candidates"] for row in weeks.values() if row["plans"] > 0)
    equal_weighted_build_rates = [row["plans"] / row["candidates"] for row in weeks.values() if row["candidates"]]
    return {
        "candidate_weighted": {
            "pre_capital_build_rate": _rate(plan_count, candidate_count),
            "active_week_rate": _rate(active_candidate_count, candidate_count),
        },
        "equal_weighted": {
            "pre_capital_build_rate": round(statistics.mean(equal_weighted_build_rates), 8)
            if equal_weighted_build_rates else None,
            "active_week_rate": _rate(active_week_count, len(weeks)),
        },
        "decision": {
            "pre_capital_build_rate": _rate(plan_count, candidate_count),
            "active_week_rate": _rate(active_week_count, len(weeks)),
        },
    }


def _within_target(metrics: dict[str, float | None]) -> bool:
    build = metrics.get("pre_capital_build_rate")
    active = metrics.get("active_week_rate")
    return (
        isinstance(build, (int, float))
        and isinstance(active, (int, float))
        and CALIBRATION_POLICY["target_pre_capital_build_rate"][0] <= build <= CALIBRATION_POLICY["target_pre_capital_build_rate"][1]
        and CALIBRATION_POLICY["target_active_week_rate"][0] <= active <= CALIBRATION_POLICY["target_active_week_rate"][1]
    )


def _observed_bottleneck(metrics: dict[str, float | None], *, fallback: str) -> str:
    below = []
    above = []
    for name, bounds in (
        ("pre_capital_build_rate", CALIBRATION_POLICY["target_pre_capital_build_rate"]),
        ("active_week_rate", CALIBRATION_POLICY["target_active_week_rate"]),
    ):
        value = metrics.get(name)
        if not isinstance(value, (int, float)):
            continue
        if value < bounds[0]:
            below.append(name)
        elif value > bounds[1]:
            above.append(name)
    if below:
        return "_and_".join(below)
    if above:
        return "_and_".join(above)
    return fallback


def _adjudicate_calibration(*, source_status: str, diagnostic_week_count: int,
                            diagnostic_candidate_count: int,
                            metrics: dict[str, float | None],
                            counterfactuals: dict[str, dict[str, dict[str, float | None]]]) -> dict[str, Any]:
    sample_sufficient = (
        source_status != "source_missing"
        and diagnostic_week_count >= CALIBRATION_POLICY["minimum_distinct_weeks"]
        and diagnostic_candidate_count >= CALIBRATION_POLICY["minimum_diagnostic_candidates"]
    )
    if not sample_sufficient:
        status = "insufficient_sample"
        mismatch_kind = None
        candidate_gates: list[dict[str, Any]] = []
        next_evidence = "provide_or_expand_authorized_historical_pit_source"
        bottleneck = "source_missing" if source_status == "source_missing" else _observed_bottleneck(
            metrics, fallback="insufficient_sample")
    elif _within_target(metrics):
        status = "within_calibration_band"
        mismatch_kind = None
        candidate_gates = []
        next_evidence = "retain_production_baseline_and_seek_forward_confirmation"
        bottleneck = "none"
    else:
        build = metrics.get("pre_capital_build_rate")
        active = metrics.get("active_week_rate")
        lower_met = (
            isinstance(build, (int, float)) and isinstance(active, (int, float))
            and build >= CALIBRATION_POLICY["target_pre_capital_build_rate"][0]
            and active >= CALIBRATION_POLICY["target_active_week_rate"][0]
        )
        above_upper = (
            isinstance(build, (int, float)) and build > CALIBRATION_POLICY["target_pre_capital_build_rate"][1]
        ) or (
            isinstance(active, (int, float)) and active > CALIBRATION_POLICY["target_active_week_rate"][1]
        )
        egs_metrics = (counterfactuals.get("egs_only_as_breakout") or {}).get("decision") or {}
        rescues = [
            {"gate": name, "metrics": row["decision"]}
            for name, row in counterfactuals.items()
            if name != "egs_only_as_breakout" and _within_target(row.get("decision") or {})
        ]
        if lower_met and above_upper:
            status = "too_lax"
            mismatch_kind = None
            candidate_gates = []
            next_evidence = "open_reviewed_tightening_candidate"
            bottleneck = _observed_bottleneck(metrics, fallback="too_lax")
        elif _within_target(egs_metrics):
            status = "egs_entry_mismatch"
            mismatch_kind = "egs_pipeline_breakout_disagreement"
            candidate_gates = []
            next_evidence = "manual_review_selection_entry_alignment_no_production_change"
            bottleneck = "egs_pipeline_breakout_disagreement"
        elif rescues:
            status = "specific_gate_too_strict"
            mismatch_kind = None
            candidate_gates = rescues
            next_evidence = "open_reviewed_rule_change_candidate"
            bottleneck = _observed_bottleneck(metrics, fallback="specific_gate_too_strict")
        else:
            status = "egs_entry_mismatch"
            mismatch_kind = "structural_no_tested_entry_fit"
            candidate_gates = []
            next_evidence = "manual_review_selection_entry_alignment_no_production_change"
            bottleneck = _observed_bottleneck(metrics, fallback="structural_no_tested_entry_fit")
    return {
        "status": status,
        "observed_bottleneck": bottleneck,
        "sample_sufficient": sample_sufficient,
        "mismatch_kind": mismatch_kind,
        "candidate_gates": candidate_gates,
        "next_evidence": next_evidence,
        "production_threshold_change": False,
    }


def _empty_entry_diagnostic(status: str) -> dict[str, Any]:
    empty_distribution = _distribution([])
    empty_metrics = _metrics_from_weeks({})
    support_methods = {
        name: {
            "support_count": 0,
            "recent_low_20": dict(empty_distribution),
            "required_band_pct": dict(empty_distribution),
            "band_observations": [
                {"band_pct": band, "within_count": 0, "within_rate": None}
                for band in CALIBRATION_POLICY["band_points"]
            ],
        }
        for name in ("effective_support", "close_low_20", "ma20")
    }
    return {
        "status": status,
        "price_window_required": 20,
        "capital_gate": "not_evaluable_private_account",
        "ma_shape_pass_count": 0,
        "breakout_source_agreement_counts": {
            "agree_true": 0, "agree_false": 0, "egs_only": 0, "pipeline_only": 0,
        },
        "entry_trigger_counts": {"low_pullback_hit": 0, "breakout_hit": 0, "neither": 0},
        "pre_capital_plan_count": 0,
        "active_week_count": 0,
        "metrics": empty_metrics,
        "support_methods": support_methods,
        "counterfactuals": {},
    }


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


def _historical_decision_policy(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        **CALIBRATION_POLICY,
        "provider_calls": 0,
        "production_threshold_change": False,
    }


def _historical_source_missing_report(generated_at: str) -> dict[str, Any]:
    entry_diagnostic = _empty_entry_diagnostic("source_missing")
    conclusion = _adjudicate_calibration(
        source_status="source_missing",
        diagnostic_week_count=0,
        diagnostic_candidate_count=0,
        metrics=entry_diagnostic["metrics"]["decision"],
        counterfactuals={},
    )
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
        "decision_policy": _historical_decision_policy("historical_production_replay"),
        "funnel": {
            "candidate_count": 0,
            "evaluable_candidate_count": 0,
            "not_evaluable_candidate_count": 0,
            "not_evaluable_reason_counts": {reason: 0 for reason in HISTORICAL_GAP_REASONS},
            "diagnostic_candidate_count": 0,
            "diagnostic_week_count": 0,
            "upstream_blocked_candidate_count": 0,
            "upstream_blocked_reason_counts": {"hard_veto": 0, "rule6_not_clear": 0},
        },
        "entry_diagnostic": entry_diagnostic,
        "calibration_conclusion": conclusion,
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


def _historical_prices(prices_path: Path, known_as_of: set[str]) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], int]:
    if not prices_path.is_file():
        raise FileNotFoundError(prices_path)
    price_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
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
                price_rows.setdefault((as_of, ts_code), []).append({
                    "trade_date": trade_date,
                    "high": _finite_price(row.get("high"), f"prices.csv line {line_number} high"),
                    "low": _finite_price(row.get("low"), f"prices.csv line {line_number} low"),
                    "close": _finite_price(row.get("close"), f"prices.csv line {line_number} close"),
                })
                row_count += 1
    except OSError as exc:
        raise HistoricalInputError(f"could not read prices.csv: {exc}") from exc
    for rows in price_rows.values():
        rows.sort(key=lambda row: str(row["trade_date"]))
    return price_rows, row_count


def _candidate_gap_reasons(candidate: dict[str, Any], volatility: dict[str, Any],
                           as_of: str, price_rows: dict[tuple[str, str], list[dict[str, Any]]]) -> list[str]:
    reasons: list[str] = []
    derived = candidate.get("derived_flags") or {}
    rule6_checks = ((candidate.get("event_risk") or {}).get("rule6_checks"))
    if not isinstance(rule6_checks, list) or not rule6_checks or not isinstance(derived.get("hard_veto"), bool):
        reasons.append("missing_rule6_hard_veto")
    if not isinstance(derived.get("is_breakout"), bool):
        reasons.append("missing_egs_breakout")
    if "iv_feed_status" in volatility:
        if volatility.get("iv_feed_status") != "ready":
            reasons.append("iv_feed_not_ready")
        else:
            m05_keys = (
                "iv_change_abs_1d_pctpt", "rule3_status", "awakening_status", "cash_reclaim_pct",
            )
            if (
                any(key not in volatility for key in m05_keys)
                or volatility.get("rule3_status") in (None, "unknown")
                or volatility.get("awakening_status") in (None, "unknown")
            ):
                reasons.append("missing_m05_rule3")
    else:
        # Pre-2026-08-08 historical inputs legitimately lack iv_feed_status.
        # Their older M0.5 facts remain usable only when substantively complete.
        if (
            volatility.get("iv_percentile_252d") is None
            or volatility.get("rule3_status") in (None, "unknown")
            or volatility.get("awakening_status") in (None, "unknown")
        ):
            reasons.append("missing_m05_rule3")
    if len(price_rows.get((as_of, str(candidate.get("ts_code") or "")), [])) < 20:
        reasons.append("insufficient_pit_price_window")
    return reasons


def _historical_production_input(candidate: dict[str, Any], price_series: list[dict[str, Any]],
                                 analysis_input: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Use the existing weekly normalizer; it is a pure source-binding adapter here."""
    from runners.a_short_weekly_pipeline import normalize_candidate, resolve_market_regime

    volatility = ((analysis_input.get("market_context") or {}).get("volatility") or {})
    regime, _ = resolve_market_regime(analysis_input)
    return normalize_candidate(
        candidate, price_series, {}, volatility.get("iv_percentile_252d"), {}, regime,
        iv_value=volatility.get("iv_value"),
        iv_change_abs_1d_pctpt=volatility.get("iv_change_abs_1d_pctpt"),
        rule3_status=volatility.get("rule3_status"),
        awakening_status=volatility.get("awakening_status"),
        cash_reclaim_pct=volatility.get("cash_reclaim_pct"),
        iv_feed_status=volatility.get("iv_feed_status"),
    ), regime


def _counterfactual_plan(inp: dict[str, Any], ind: dict[str, Any], regime: str, *,
                         lowxi_band: float | None = None,
                         allow_egs_only_breakout: bool = False) -> bool:
    etype, _ = entry_type(
        inp, ind, lowxi_band=lowxi_band, allow_egs_only_breakout=allow_egs_only_breakout,
    )
    if etype == "观察":
        return False
    geometry, _ = entry_exit_geometry(inp, ind, regime, etype)
    return geometry is not None


def _record_counterfactual(weeks: dict[tuple[int, int], dict[str, int]], week: tuple[int, int],
                           has_plan: bool) -> None:
    row = weeks.setdefault(week, {"candidates": 0, "plans": 0})
    row["candidates"] += 1
    row["plans"] += int(has_plan)


def build_historical_report(historical_root: Path, generated_at: str) -> tuple[dict[str, Any], int]:
    """Replay only public production entry geometry from authorized local PIT inputs."""
    inputs = _historical_analysis_inputs(historical_root)
    prices_path = historical_root / "prices.csv"
    if inputs is None or not prices_path.is_file():
        return _historical_source_missing_report(generated_at), 2
    known_as_of = {as_of for as_of, _ in inputs}
    price_rows, price_row_count = _historical_prices(prices_path, known_as_of)
    candidate_count = 0
    evaluable_candidate_count = 0
    reason_counts = {reason: 0 for reason in HISTORICAL_GAP_REASONS}
    upstream_blocked_reason_counts = {"hard_veto": 0, "rule6_not_clear": 0}
    diagnostic_weeks: dict[tuple[int, int], dict[str, int]] = {}
    counterfactual_weeks: dict[str, dict[tuple[int, int], dict[str, int]]] = {
        "egs_only_as_breakout": {},
        "support:close_low_20": {},
        "support:ma20": {},
        **{f"low_pullback_band:{band:.3f}": {} for band in CALIBRATION_POLICY["band_points"]},
    }
    agreement_counts = {"agree_true": 0, "agree_false": 0, "egs_only": 0, "pipeline_only": 0}
    trigger_counts = {"low_pullback_hit": 0, "breakout_hit": 0, "neither": 0}
    required_bands = {"effective_support": [], "close_low_20": [], "ma20": []}
    recent_low_20 = []
    support_counts = {"effective_support": 0, "close_low_20": 0, "ma20": 0}
    ma_shape_pass_count = 0
    versions: set[str] = set()
    as_of_dates: list[str] = []
    for as_of, analysis_input in inputs:
        as_of_dates.append(as_of)
        versions.add(str(analysis_input.get("schema_version")))
        volatility = ((analysis_input.get("market_context") or {}).get("volatility") or {})
        for candidate in analysis_input.get("candidates") or []:
            candidate_count += 1
            reasons = _candidate_gap_reasons(candidate, volatility, as_of, price_rows)
            if reasons:
                for reason in reasons:
                    reason_counts[reason] += 1
                continue
            evaluable_candidate_count += 1
            code = str(candidate.get("ts_code") or "")
            series = price_rows[(as_of, code)]
            inp, regime = _historical_production_input(candidate, series, analysis_input)
            rule6_gate = assess_rule6_checks(inp.get("rule6_checks"))
            if fail_closed_risk_bool((inp.get("derived") or {}).get("hard_veto")):
                upstream_blocked_reason_counts["hard_veto"] += 1
                continue
            if rule6_gate["disposition"] != "clear":
                upstream_blocked_reason_counts["rule6_not_clear"] += 1
                continue
            week = datetime.strptime(as_of, "%Y%m%d").isocalendar()[:2]
            indicator = compute_indicators(series)
            support, support_quality, raw_recent_low = effective_support(series, indicator.get("atr14"))
            if (support, support_quality, raw_recent_low) != (
                    indicator.get("support"), indicator.get("support_quality"), indicator.get("recent_low_20")):
                raise HistoricalInputError("production effective_support drift")
            etype, entry_reason = entry_type(inp, indicator)
            base_plan = False
            if "MA5/10/20" not in entry_reason:
                ma_shape_pass_count += 1
                agreement = breakout_source_agreement(inp, indicator)
                agreement_counts[agreement] += 1
                if etype == "低吸":
                    trigger_counts["low_pullback_hit"] += 1
                elif etype == "突破":
                    trigger_counts["breakout_hit"] += 1
                else:
                    trigger_counts["neither"] += 1
                if etype != "观察":
                    geometry, _ = entry_exit_geometry(inp, indicator, regime, etype)
                    base_plan = geometry is not None
            _record_counterfactual(diagnostic_weeks, week, base_plan)
            support_values = {
                "effective_support": (support, raw_recent_low),
                "close_low_20": (min(float(row["close"]) for row in series[-20:]), None),
                "ma20": (indicator.get("ma20"), None),
            }
            for name, (support_value, recent_low_value) in support_values.items():
                if not isinstance(support_value, (int, float)) or support_value <= 0:
                    continue
                support_counts[name] += 1
                required_band = abs(float(inp["close"]) - float(support_value)) / float(support_value)
                required_bands[name].append(required_band)
                if recent_low_value is not None:
                    recent_low_20.append(float(recent_low_value))
            _record_counterfactual(
                counterfactual_weeks["egs_only_as_breakout"], week,
                _counterfactual_plan(inp, indicator, regime, allow_egs_only_breakout=True),
            )
            for name in ("close_low_20", "ma20"):
                support_value = support_values[name][0]
                counterfactual_indicator = dict(indicator)
                counterfactual_indicator["support"] = support_value
                _record_counterfactual(
                    counterfactual_weeks[f"support:{name}"], week,
                    _counterfactual_plan(inp, counterfactual_indicator, regime),
                )
            for band in CALIBRATION_POLICY["band_points"]:
                _record_counterfactual(
                    counterfactual_weeks[f"low_pullback_band:{band:.3f}"], week,
                    _counterfactual_plan(inp, indicator, regime, lowxi_band=band),
                )
    distinct_weeks = len({datetime.strptime(as_of, "%Y%m%d").isocalendar()[:2] for as_of in as_of_dates})
    not_evaluable_candidate_count = candidate_count - evaluable_candidate_count
    readiness_status = "ready" if not_evaluable_candidate_count == 0 else "ready_with_candidate_gaps"
    metrics = _metrics_from_weeks(diagnostic_weeks)
    counterfactuals = {name: _metrics_from_weeks(weeks) for name, weeks in counterfactual_weeks.items()}
    conclusion = _adjudicate_calibration(
        source_status=readiness_status,
        diagnostic_week_count=len(diagnostic_weeks),
        diagnostic_candidate_count=sum(row["candidates"] for row in diagnostic_weeks.values()),
        metrics=metrics["decision"],
        counterfactuals=counterfactuals,
    )
    support_methods = {
        name: {
            "support_count": support_counts[name],
            "recent_low_20": _distribution(recent_low_20 if name == "effective_support" else []),
            "required_band_pct": _distribution(required_bands[name]),
            "band_observations": [
                {
                    "band_pct": band,
                    "within_count": sum(value <= band for value in required_bands[name]),
                    "within_rate": _rate(sum(value <= band for value in required_bands[name]), support_counts[name]),
                }
                for band in CALIBRATION_POLICY["band_points"]
            ],
        }
        for name in ("effective_support", "close_low_20", "ma20")
    }
    entry_diagnostic = {
        "status": "completed",
        "price_window_required": 20,
        "capital_gate": "not_evaluable_private_account",
        "ma_shape_pass_count": ma_shape_pass_count,
        "breakout_source_agreement_counts": agreement_counts,
        "entry_trigger_counts": trigger_counts,
        "pre_capital_plan_count": sum(row["plans"] for row in diagnostic_weeks.values()),
        "active_week_count": sum(row["plans"] > 0 for row in diagnostic_weeks.values()),
        "metrics": metrics,
        "support_methods": support_methods,
        "counterfactuals": counterfactuals,
    }
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
        "decision_policy": _historical_decision_policy("historical_production_replay"),
        "funnel": {
            "candidate_count": candidate_count,
            "evaluable_candidate_count": evaluable_candidate_count,
            "not_evaluable_candidate_count": not_evaluable_candidate_count,
            "not_evaluable_reason_counts": reason_counts,
            "diagnostic_candidate_count": sum(row["candidates"] for row in diagnostic_weeks.values()),
            "diagnostic_week_count": len(diagnostic_weeks),
            "upstream_blocked_candidate_count": sum(upstream_blocked_reason_counts.values()),
            "upstream_blocked_reason_counts": upstream_blocked_reason_counts,
        },
        "entry_diagnostic": entry_diagnostic,
        "calibration_conclusion": conclusion,
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
