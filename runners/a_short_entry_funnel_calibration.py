from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PREREG_PATH = ROOT / "research" / "preregistrations" / "a_short_entry_funnel_calibration_20260713.json"
PREREG_SCHEMA_PATH = ROOT / "schemas" / "a_short_entry_funnel_calibration_preregistration.schema.json"
REPORT_SCHEMA_PATH = ROOT / "schemas" / "a_short_entry_funnel_calibration_report.schema.json"
DEFAULT_OUT = ROOT / "research" / "results" / "a_short" / "entry_funnel_calibration_20260713" / "calibration_report.json"


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


def write_report(report: dict[str, Any], path: Path) -> None:
    validate(report, REPORT_SCHEMA_PATH, "calibration report")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline preregistered A-short funnel/IV/overlay calibration.")
    parser.add_argument("--preregistration", type=Path, default=PREREG_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--generated-at", default="2026-07-13T18:30:00+08:00")
    args = parser.parse_args(argv)
    if args.preregistration.resolve() != PREREG_PATH.resolve():
        raise ValueError("only the frozen reviewed preregistration path is accepted")
    report = build_report(load_json(args.preregistration), args.generated_at)
    write_report(report, args.out)
    print(f"[OK] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
