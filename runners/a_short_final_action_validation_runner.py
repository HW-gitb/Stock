#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 final-action validation accumulator (comparison-only).

The runner owns a gitignored private ledger and a de-identified public
summary.  It only consumes already-published M6.7, the forward tracker and an
optional pre-existing execution cache; it never fetches data and never changes
the official selection, M6.7 action, sizing, stop or target.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from statistics import median

from engine import a_short_evidence_epoch_mode as _epoch_mode
from typing import Any

import jsonschema

from engine.a_short_managed_exit import (
    ROUND_TRIP_COST_FRACTION,
    evaluate_managed_exit,
    net_excess_after_round_trip_cost_pct,
)
from runners.a_short_phase5_engine import ATR_MULT
from engine.a_short_experiment_admission_registry import admission_snapshot


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_LEDGER_DEFAULT = ROOT / "logs" / "a_short_final_action_validation.json"
PUBLIC_SUMMARY_DEFAULT = ROOT / "research" / "results" / "a_short" / "final_action_validation_summary.json"
PUBLIC_MARKDOWN_DEFAULT = ROOT / "research" / "results" / "a_short" / "final_action_validation_summary.md"
TRACKER_DEFAULT = ROOT / "logs" / "forward_tracker.csv"
SCHEMA_PATH = ROOT / "schemas" / "a_short_final_action_validation_summary.schema.json"
SCHEMA_NAME = "a_short_final_action_validation_summary"
SCHEMA_VERSION = "1.0.0"
HORIZON = 20
ROUND_TRIP_COST_PCT = ROUND_TRIP_COST_FRACTION * 100.0
HOLD_REVIEW_WEEKS = 12
FULL_EDGE_REVIEW_WEEKS = 12
HAC_REVIEW_WEEKS = 26
HAC_MIN_PLANS = 20
ADMISSION_IDS = ("p3_selected_vs_candidate_pool", "p3_selected_vs_csi1000", "p3_managed_exit_vs_hold")
P3B_EXTERNAL_PUBLIC_SUMMARIES = (
    ROOT / "research" / "results" / "a_short" / "regime_candidate_effect_summary.json",
    ROOT / "research" / "results" / "a_short" / "target_policy_comparison_summary.json",
)


class FinalActionValidationError(ValueError):
    """A source-bound P3 sidecar cannot prove a valid comparison observation."""


def _date(value: object) -> str:
    text = str(value or "")
    try:
        datetime.strptime(text, "%Y%m%d")
    except (TypeError, ValueError) as exc:
        raise FinalActionValidationError("invalid_date") from exc
    return text


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _atomic_write(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _contract_fingerprint() -> str:
    """A rule/evaluator change starts a new evidence epoch.

    Pre-freeze this returns a stable constant (see
    ``engine/a_short_evidence_epoch_mode``); the real whole-file binding below
    dropped every accumulated week whenever an unrelated file changed.
    """
    return _epoch_mode.fingerprint_or_pre_freeze("p3_final_action_validation", _real_contract_fingerprint)


def _real_contract_fingerprint() -> str:
    """The enforced fingerprint used once the design is frozen."""
    paths = (
        Path(__file__),
        ROOT / "engine" / "a_short_managed_exit.py",
        ROOT / "runners" / "a_short_phase5_engine.py",
        ROOT / "runners" / "a_short_factor_comparison_v2_cache_build.py",
        ROOT / "runners" / "forward_tracker.py",
        ROOT / "runners" / "a_short_weekly_pipeline.py",
        ROOT / "schemas" / "a_short_weekly_report.schema.json",
        ROOT / "schemas" / "a_short_m67_effect_contract.json",
        ROOT / "presets" / "a_short_m67_runtime_policy_20260715.json",
        SCHEMA_PATH,
    )
    chunks: list[bytes] = []
    for path in paths:
        try:
            chunks.append(path.read_bytes())
        except OSError as exc:
            raise FinalActionValidationError("contract_fingerprint_unavailable") from exc
    return _digest({"source_sha256": hashlib.sha256(b"\0".join(chunks)).hexdigest(),
                    "admission_bindings": admission_snapshot(*ADMISSION_IDS)})


def _initial_ledger() -> dict[str, Any]:
    return {
        "schema_name": "a_short_final_action_validation_private_ledger",
        "schema_version": "1.0.0",
        "epochs": [],
    }


def _capture_digest(record: dict[str, Any]) -> str:
    """Bind immutable capture input while allowing later settlement/conflict annotations."""
    return _digest({key: value for key, value in record.items()
                    if key not in {"capture_sha256", "hold_result", "full_edge_result", "conflict"}})


def _validate_ledger(ledger: dict[str, Any]) -> None:
    if not isinstance(ledger, dict) or ledger.get("schema_name") != "a_short_final_action_validation_private_ledger":
        raise FinalActionValidationError("private_ledger_contract_invalid")
    epochs = ledger.get("epochs")
    if not isinstance(epochs, list):
        raise FinalActionValidationError("private_ledger_contract_invalid")
    fingerprints: set[str] = set()
    current_fingerprint = _contract_fingerprint()
    current_admissions = admission_snapshot(*ADMISSION_IDS)
    for epoch in epochs:
        if not isinstance(epoch, dict) or not isinstance(epoch.get("contract_fingerprint"), str):
            raise FinalActionValidationError("private_ledger_contract_invalid")
        fingerprint = epoch["contract_fingerprint"]
        if fingerprint in fingerprints or not isinstance(epoch.get("records"), list):
            raise FinalActionValidationError("private_ledger_contract_invalid")
        fingerprints.add(fingerprint)
        is_current_epoch = fingerprint == current_fingerprint
        if is_current_epoch and epoch.get("admission_bindings") != current_admissions:
            raise FinalActionValidationError("private_ledger_admission_binding_drifted")
        dates: set[str] = set()
        for record in epoch["records"]:
            if not isinstance(record, dict):
                raise FinalActionValidationError("private_ledger_contract_invalid")
            if is_current_epoch and (
                    record.get("epoch_fingerprint") != fingerprint or
                    record.get("admission_bindings") != current_admissions or
                    record.get("capture_sha256") != _capture_digest(record)):
                raise FinalActionValidationError("private_record_epoch_binding_drifted")
            decision_date = _date(record.get("decision_date"))
            if decision_date in dates:
                raise FinalActionValidationError("private_ledger_duplicate_week")
            dates.add(decision_date)


def _load_or_initialize(root: str | Path) -> tuple[Path, dict[str, Any]]:
    path = Path(root)
    if not path.exists():
        return path, _initial_ledger()
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalActionValidationError("private_ledger_unreadable") from exc
    _validate_ledger(ledger)
    return path, ledger


def _active_epoch(ledger: dict[str, Any], *, create: bool) -> dict[str, Any] | None:
    fingerprint = _contract_fingerprint()
    existing = next((epoch for epoch in ledger["epochs"] if epoch["contract_fingerprint"] == fingerprint), None)
    if existing is not None or not create:
        return existing
    epoch = {"contract_fingerprint": fingerprint, "records": [], "admission_bindings": admission_snapshot(*ADMISSION_IDS)}
    ledger["epochs"].append(epoch)
    return epoch


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise FinalActionValidationError("non_finite_return")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FinalActionValidationError("non_finite_return") from exc
    if not math.isfinite(result):
        raise FinalActionValidationError("non_finite_return")
    return result


def _load_tracker(path: str | Path) -> list[dict[str, str]]:
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise FinalActionValidationError("forward_tracker_unreadable") from exc
    required = {"as_of", "run_id", "candidate_digest", "ts_code", "forward_live",
                "ret_5d_t1_net", "ret_5d_excess_csi1000", "ret_5d_status",
                "ret_10d_t1_net", "ret_10d_excess_csi1000", "ret_10d_status",
                "ret_20d_t1_net", "ret_20d_excess_csi1000", "ret_20d_status"}
    if not rows or not required.issubset(set(rows[0])):
        raise FinalActionValidationError("forward_tracker_contract_invalid")
    return rows


def _tracker_cohort(rows: list[dict[str, str]], decision_date: str, source_identity: dict[str, Any]) -> list[dict[str, str]]:
    cohort = [row for row in rows if str(row.get("as_of")) == decision_date]
    if not cohort:
        raise FinalActionValidationError("tracker_cohort_missing")
    run_ids = {str(row.get("run_id") or "") for row in cohort}
    digests = {str(row.get("candidate_digest") or "") for row in cohort}
    codes = [str(row.get("ts_code") or "") for row in cohort]
    if (run_ids != {str(source_identity.get("run_id") or "")} or
            digests != {str(source_identity.get("candidate_digest") or "")} or
            not all(codes) or len(set(codes)) != len(codes)):
        raise FinalActionValidationError("tracker_cohort_binding_invalid")
    return sorted(cohort, key=lambda row: str(row["ts_code"]))


def _verify_published_bundle(out_path: str | Path, receipt_path: str | Path, decision_date: str,
                             source_identity: dict[str, Any]) -> dict[str, Any]:
    out_file, receipt_file = Path(out_path), Path(receipt_path)
    markdown = out_file.with_suffix(".md")
    try:
        weekly = json.loads(out_file.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalActionValidationError("published_bundle_unreadable") from exc
    lineage = weekly.get("run_lineage") or {}
    if (str(weekly.get("as_of")) != decision_date or lineage.get("run_id") != source_identity.get("run_id") or
            lineage.get("candidate_digest") != source_identity.get("candidate_digest") or
            receipt.get("stage_status") != "complete" or receipt.get("as_of") != decision_date or
            receipt.get("run_id") != lineage.get("run_id") or
            receipt.get("candidate_digest") != lineage.get("candidate_digest") or not markdown.is_file()):
        raise FinalActionValidationError("published_bundle_binding_invalid")
    return weekly


def _freeze_plan(plan: dict[str, Any], series: list[dict[str, Any]], decision_date: str,
                 regime: str) -> dict[str, Any] | None:
    if not isinstance(plan, dict) or not isinstance(series, list) or not series:
        return None
    reference = series[-1]
    try:
        return {
            "decision_date": decision_date,
            "entry_low": _number(plan.get("entry_low")),
            "entry_high": _number(plan.get("entry_high")),
            "stop": _number(plan.get("stop")),
            "t1": _number(plan.get("t1")),
            "t2": _number(plan.get("t2")),
            "atr_multiplier": ATR_MULT.get(str(regime), 1.25),
            "price_basis": "qfq",
            "reference_trade_date": _date(reference.get("trade_date")),
            "reference_close": _number(reference.get("close")),
        }
    except FinalActionValidationError:
        return None


def _record_is_mature(record: dict[str, Any]) -> bool:
    return (record.get("hold_result") or {}).get("status") == "settled" or \
        (record.get("full_edge_result") or {}).get("status") == "settled"


def capture_after_published_weekly(*, root: str | Path, decision_date: str, candidates: list[dict[str, Any]],
                                   source_identity: dict[str, Any], out_path: str | Path, receipt_path: str | Path,
                                   forward_eligible: bool, tracker_path: str | Path = TRACKER_DEFAULT,
                                   summary_path: str | Path = PUBLIC_SUMMARY_DEFAULT,
                                   markdown_path: str | Path = PUBLIC_MARKDOWN_DEFAULT) -> dict[str, Any]:
    """Freeze P3 selection only after the source-bound M6.7 bundle is complete."""
    decision_date = _date(decision_date)
    private_path, ledger = _load_or_initialize(root)
    weekly = _verify_published_bundle(out_path, receipt_path, decision_date, source_identity)
    if forward_eligible:
        freshness = (weekly.get("run_lineage") or {}).get("price_freshness") or {}
        if freshness.get("mode") != "intraday_prior_settled" or not freshness.get("run_date"):
            raise FinalActionValidationError("forward_capture_requires_live_price_freshness")
    tracker_rows = _tracker_cohort(_load_tracker(tracker_path), decision_date, source_identity)
    if forward_eligible and not all(str(row.get("forward_live") or "").strip().lower() == "true"
                                    for row in tracker_rows):
        raise FinalActionValidationError("forward_tracker_not_live")
    reports = {str(row.get("ts_code")): row for row in (weekly.get("reports") or []) if isinstance(row, dict)}
    candidates_by_code = {str(candidate.get("ts_code")): candidate for candidate in candidates if isinstance(candidate, dict)}
    selected_codes: list[str] = []
    managed_plans: dict[str, dict[str, Any]] = {}
    for code, report in reports.items():
        machine = report.get("machine") or {}
        if report.get("row_source") != "egs_candidate" or machine.get("model_build_eligible") is not True:
            continue
        if code not in candidates_by_code:
            raise FinalActionValidationError("selected_candidate_source_missing")
        selected_codes.append(code)
        official_plan = (machine.get("entry_exit_size_star") or {}).get("plan")
        frozen = _freeze_plan(official_plan, candidates_by_code[code].get("price_series") or [], decision_date,
                              str(candidates_by_code[code].get("market_regime") or ""))
        if frozen is not None:
            managed_plans[code] = frozen
    selected_codes.sort()
    pool_codes = [str(row["ts_code"]) for row in tracker_rows]
    if not set(selected_codes).issubset(set(pool_codes)):
        raise FinalActionValidationError("selected_set_not_in_tracker_cohort")
    price_through = str(((weekly.get("run_lineage") or {}).get("price_freshness") or {}).get("price_data_through") or "")
    _date(price_through)
    record = {
        "decision_date": decision_date,
        "forward_eligible": bool(forward_eligible),
        "source_identity": {
            "run_id": str(source_identity["run_id"]),
            "candidate_digest": str(source_identity["candidate_digest"]),
            "official_m67_sha256": hashlib.sha256(Path(out_path).read_bytes()).hexdigest(),
            "price_data_through": price_through,
            "tracker_cohort_digest": _digest([{
                "ts_code": row["ts_code"], "run_id": row["run_id"], "candidate_digest": row["candidate_digest"],
            } for row in tracker_rows]),
        },
        "admission_bindings": admission_snapshot(*ADMISSION_IDS),
        "epoch_fingerprint": _contract_fingerprint(),
        "pool_codes": pool_codes,
        "selected_codes": selected_codes,
        "managed_plans": managed_plans,
        "hold_result": {"status": "pending"},
        "full_edge_result": {"status": "pending"},
    }
    record["capture_sha256"] = _capture_digest(record)
    epoch = _active_epoch(ledger, create=True)
    assert epoch is not None
    existing = next((item for item in epoch["records"] if item["decision_date"] == decision_date), None)
    if existing is not None:
        if existing.get("capture_sha256") == record["capture_sha256"]:
            return {"status": "idempotent", "record": existing}
        if _record_is_mature(existing):
            existing["conflict"] = "mature_source_identity_changed"
            _atomic_write(private_path, ledger)
            summary = settle_and_summarize(root=root, as_of=decision_date, tracker_path=tracker_path,
                                           summary_path=summary_path, markdown_path=markdown_path)
            return {"status": "conflict", "record": existing, "summary": summary}
        epoch["records"].remove(existing)
    epoch["records"].append(record)
    epoch["records"].sort(key=lambda item: item["decision_date"])
    _validate_ledger(ledger)
    _atomic_write(private_path, ledger)
    summary = settle_and_summarize(root=root, as_of=decision_date, tracker_path=tracker_path,
                                   summary_path=summary_path, markdown_path=markdown_path)
    return {"status": "captured", "record": record, "summary": summary}


def _horizon(row: dict[str, str], days: int) -> tuple[float, float]:
    if str(row.get(f"ret_{days}d_status") or "") != "ok":
        raise FinalActionValidationError(f"h{days}_not_mature")
    stock_net = _number(row.get(f"ret_{days}d_t1_net"))
    gross_excess = _number(row.get(f"ret_{days}d_excess_csi1000"))
    # Tracker excess is gross stock-minus-index. Only the strategy pays its
    # round-trip trading cost, so the net spread must retain that deduction.
    return stock_net, net_excess_after_round_trip_cost_pct(gross_excess)


def _aggregate_horizon(by_code: dict[str, dict[str, str]], pool_codes: list[str],
                       selected_codes: list[str], days: int) -> dict[str, float]:
    pool = [_horizon(by_code[code], days) for code in pool_codes]
    selected = [_horizon(by_code[code], days) for code in selected_codes]
    csi_values = [stock_net - net_excess for stock_net, net_excess in pool]
    if max(csi_values) - min(csi_values) > 1e-7:
        raise FinalActionValidationError("csi1000_cohort_inconsistent")
    selected_net = sum(value[0] for value in selected) / len(selected)
    pool_net = sum(value[0] for value in pool) / len(pool)
    csi_return = sum(csi_values) / len(csi_values)
    selected_minus_csi = sum(value[1] for value in selected) / len(selected)
    return {
        "selected_net_pct": round(selected_net, 8), "pool_net_pct": round(pool_net, 8),
        "csi1000_return_pct": round(csi_return, 8),
        "selected_minus_pool_pct": round(selected_net - pool_net, 8),
        "selected_minus_csi1000_pct": round(selected_minus_csi, 8),
    }


def _settle_hold(record: dict[str, Any], tracker_rows: list[dict[str, str]]) -> None:
    if not record.get("forward_eligible"):
        record["hold_result"] = {"status": "no_count", "reason": "historical_replay"}
        return
    if record.get("conflict"):
        record["hold_result"] = {"status": "no_count", "reason": "source_identity_conflict"}
        return
    by_code = {str(row.get("ts_code")): row for row in tracker_rows}
    pool_codes, selected_codes = record.get("pool_codes") or [], record.get("selected_codes") or []
    if not selected_codes:
        record["hold_result"] = {"status": "no_count", "reason": "no_model_build_eligible"}
        return
    if not pool_codes or set(pool_codes) != set(by_code) or not set(selected_codes).issubset(set(by_code)):
        record["hold_result"] = {"status": "no_count", "reason": "tracker_identity_conflict"}
        return
    try:
        diagnostics = {f"h{days}": _aggregate_horizon(by_code, pool_codes, selected_codes, days)
                       for days in (5, 10)}
        h20 = _aggregate_horizon(by_code, pool_codes, selected_codes, 20)
    except FinalActionValidationError as exc:
        record["hold_result"] = {"status": "no_count", "reason": str(exc)}
        return
    record["hold_result"] = {
        "status": "settled",
        "selected_h20_net_pct": h20["selected_net_pct"],
        "pool_h20_net_pct": h20["pool_net_pct"],
        "csi1000_h20_return_pct": h20["csi1000_return_pct"],
        "selected_minus_pool_pct": h20["selected_minus_pool_pct"],
        "selected_minus_csi1000_pct": h20["selected_minus_csi1000_pct"],
        "h5_h10_diagnostics": diagnostics,
        "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
    }


def _load_execution_cache(path: str | Path | None) -> dict[str, list[dict[str, Any]]] | None:
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("ts_code"):
            return None
        by_code.setdefault(str(row["ts_code"]), []).append({key: value for key, value in row.items() if key != "ts_code"})
    return by_code


def _settle_full_edge(record: dict[str, Any], execution_rows: dict[str, list[dict[str, Any]]] | None) -> None:
    hold = record.get("hold_result") or {}
    selected_codes = record.get("selected_codes") or []
    plans = record.get("managed_plans") or {}
    if hold.get("status") != "settled":
        record["full_edge_result"] = {"status": "no_count", "reason": "hold_h20_not_comparable"}
        return
    if not selected_codes or any(code not in plans for code in selected_codes):
        record["full_edge_result"] = {"status": "no_count", "reason": "managed_plan_missing"}
        return
    if execution_rows is None:
        record["full_edge_result"] = {"status": "no_count", "reason": "execution_cache_unavailable"}
        return
    outcomes = []
    for code in selected_codes:
        rows = execution_rows.get(code)
        if not rows:
            record["full_edge_result"] = {"status": "no_count", "reason": "execution_rows_missing"}
            return
        outcome = evaluate_managed_exit(plans[code], rows)
        if outcome.get("status") != "settled":
            record["full_edge_result"] = {"status": "no_count", "reason": str(outcome.get("reason") or "managed_exit_unavailable")}
            return
        outcomes.append(_number(outcome.get("net_return_pct")))
    managed = sum(outcomes) / len(outcomes)
    record["full_edge_result"] = {
        "status": "settled",
        "managed_h20_net_pct": round(managed, 8),
        "managed_minus_simple_hold_pct": round(managed - _number(hold["selected_h20_net_pct"]), 8),
        "managed_minus_csi1000_pct": round(managed - _number(hold["csi1000_h20_return_pct"]), 8),
        "managed_plan_count": len(outcomes),
        "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
    }


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean_pct": None, "median_pct": None, "favorable_ratio": None}
    return {
        "mean_pct": round(sum(values) / len(values), 8),
        "median_pct": round(float(median(values)), 8),
        "favorable_ratio": round(sum(1 for value in values if value > 0) / len(values), 8),
    }


def _reminder(reminder_id: str, status: str, current: int, threshold: int, message: str) -> dict[str, Any]:
    return {"reminder_id": reminder_id, "status": status, "current": current, "threshold": threshold,
            "message": message, "automatic_policy_switch": False}


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_current_external_public_summary(path: Path, payload: dict[str, Any]) -> bool:
    """Accept only a named current-epoch lane summary, never a hash-shaped stand-in."""
    try:
        if path.name == "regime_candidate_effect_summary.json":
            from engine.a_short_regime_action_comparison import validate_candidate_effect_summary
            validate_candidate_effect_summary(payload)
            return True
        if path.name == "target_policy_comparison_summary.json":
            from runners.a_short_target_policy_comparison_runner import validate_public_summary
            validate_public_summary(payload)
            return True
        if path.name == "industry_weight_comparison_progress_summary.json":
            from engine.a_short_industry_weight_comparison import validate_public_progress
            validate_public_progress(payload)
            return True
    except Exception:
        return False
    return False


def _valid_external_public_verdicts() -> int:
    """Count only future public tracks with a complete, independently auditable verdict surface."""
    count = 0
    for path in P3B_EXTERNAL_PUBLIC_SUMMARIES:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not _is_current_external_public_summary(path, payload):
            continue
        verdict = payload.get("verdict")
        progress = payload.get("evidence_progress") or payload.get("progress")
        fingerprint = ((payload.get("policy") or {}).get("policy_fingerprint") or
                       payload.get("evidence_fingerprint") or payload.get("fingerprint"))
        evidence_date = payload.get("data_through") or payload.get("latest_evidence_as_of") or payload.get("as_of")
        source_hash = payload.get("source_hash") or payload.get("source_sha256")
        try:
            _date(evidence_date)
        except FinalActionValidationError:
            continue
        if (isinstance(verdict, str) and verdict not in {"", "insufficient_data", "not_adjudicated"} and
                isinstance(progress, dict) and _is_sha256(fingerprint) and _is_sha256(source_hash)):
            count += 1
    return count


def _summary_from_ledger(ledger: dict[str, Any], as_of: str) -> dict[str, Any]:
    epoch = _active_epoch(ledger, create=False)
    records = list((epoch or {}).get("records") or [])
    valid = [record for record in records if record.get("forward_eligible") and not record.get("conflict")]
    holds = [record["hold_result"] for record in valid if (record.get("hold_result") or {}).get("status") == "settled"]
    edges = [record["full_edge_result"] for record in valid if (record.get("full_edge_result") or {}).get("status") == "settled"]
    hold_pool = [float(item["selected_minus_pool_pct"]) for item in holds]
    hold_csi = [float(item["selected_minus_csi1000_pct"]) for item in holds]
    edge_hold = [float(item["managed_minus_simple_hold_pct"]) for item in edges]
    edge_csi = [float(item["managed_minus_csi1000_pct"]) for item in edges]
    managed_plans = sum(int(item.get("managed_plan_count") or 0) for item in edges)
    first_forward = min((record["decision_date"] for record in valid), default=None)
    epoch_fingerprint = (epoch or {}).get("contract_fingerprint")
    latest_source_hash = _digest([
        {"decision_date": record["decision_date"], "source_identity": record.get("source_identity")}
        for record in valid
    ])
    counts = _epoch_mode.evidence_counts_toward_clock("p3_final_action_validation")
    hold_status = "review_due" if counts and len(holds) >= HOLD_REVIEW_WEEKS else "accumulating"
    edge_status = "review_due" if counts and len(edges) >= FULL_EDGE_REVIEW_WEEKS else "accumulating"
    hac_status = "review_due" if counts and len(edges) >= HAC_REVIEW_WEEKS and managed_plans >= HAC_MIN_PLANS else "accumulating"
    ship_status = "accumulating"
    if counts and first_forward:
        months_ready = (datetime.strptime(as_of, "%Y%m%d") - datetime.strptime(first_forward, "%Y%m%d")).days >= 365
        if months_ready:
            ship_status = "review_due"
    public_verdict = "not_adjudicated"
    external_verdicts = _valid_external_public_verdicts()
    p3b_ready = public_verdict != "not_adjudicated" and external_verdicts >= 2
    reminders = [
        _reminder("hold_based_midterm_review", hold_status, len(holds), HOLD_REVIEW_WEEKS,
                  "模型选择/市场中期复核" if hold_status == "review_due" else "模型选择与市场基准证据积累中"),
        _reminder("full_edge_integrity_review", edge_status, len(edges), FULL_EDGE_REVIEW_WEEKS,
                  "完整 edge 完整性复核" if edge_status == "review_due" else "共享受管退出完整 edge 证据积累中"),
        _reminder("hac_and_cumulative_judgement", hac_status, len(edges), HAC_REVIEW_WEEKS,
                  "可审查 HAC/累计判断（不自动裁决）" if hac_status == "review_due" else "待满 26 周且至少 20 个受管计划后提醒 HAC/累计判断"),
        _reminder("ship_gate_calendar_review", ship_status, 1 if first_forward else 0, 1,
                  "自首个有效 forward-live 样本满 12 个自然月，需人工审查 ship-gate（不自动放行）"
                  if ship_status == "review_due" else "尚未达到从首个有效 forward-live 样本起 12 个自然月"),
        _reminder("P3b_overview_review_due", "review_due" if p3b_ready else "accumulating",
                  (1 if public_verdict != "not_adjudicated" else 0) + external_verdicts, 3,
                  "P3b 总览已具备建设条件" if p3b_ready else "等待 P3 有效公开裁决及另外两条完整公开裁决后再建设 P3b 总览"),
    ]
    status = "review_due" if any(item["status"] == "review_due" for item in reminders) else "accumulating"
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "summary_id": "a_short_final_action_validation",
        "as_of": as_of,
        "data_through": max((record["decision_date"] for record in records), default=None),
        "status": status,
        "comparison_only": True,
        "automatic_policy_switch": False,
        "verdict": public_verdict,
        "evidence_epoch_fingerprint": epoch_fingerprint,
        "latest_evidence_as_of": max((record["decision_date"] for record in valid), default=None),
        "source_hash": latest_source_hash,
        "admissions": admission_snapshot(*ADMISSION_IDS),
        "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        "hold_based_forward_weeks": len(holds),
        "full_edge_forward_weeks": len(edges),
        "hold_based": {
            "forward_weeks": len(holds), "review_threshold_weeks": HOLD_REVIEW_WEEKS,
            "selection_minus_pool": _stats(hold_pool), "selection_minus_csi1000": _stats(hold_csi),
        },
        "full_edge": {
            "forward_weeks": len(edges), "review_threshold_weeks": FULL_EDGE_REVIEW_WEEKS,
            "managed_plan_count": managed_plans,
            "managed_minus_simple_hold": _stats(edge_hold), "managed_minus_csi1000": _stats(edge_csi),
        },
        "first_forward_live_as_of": first_forward,
        "reminders": reminders,
        "message": "P3 最终建议验证：仅累计脱敏 forward 证据；不改变正式 M6.7。",
        "production_unchanged": True,
    }


def unavailable_public_summary(as_of: str) -> dict[str, Any]:
    return {
        "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "summary_id": "a_short_final_action_validation", "as_of": _date(as_of), "data_through": None,
        "status": "unavailable", "comparison_only": True, "automatic_policy_switch": False,
        "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        "hold_based": {"forward_weeks": 0, "review_threshold_weeks": HOLD_REVIEW_WEEKS,
                       "selection_minus_pool": _stats([]), "selection_minus_csi1000": _stats([])},
        "full_edge": {"forward_weeks": 0, "review_threshold_weeks": FULL_EDGE_REVIEW_WEEKS,
                      "managed_plan_count": 0, "managed_minus_simple_hold": _stats([]),
                      "managed_minus_csi1000": _stats([])},
        "first_forward_live_as_of": None,
        "verdict": "not_adjudicated", "evidence_epoch_fingerprint": None,
        "latest_evidence_as_of": None, "source_hash": None,
        "admissions": admission_snapshot(*ADMISSION_IDS),
        "hold_based_forward_weeks": 0, "full_edge_forward_weeks": 0,
        "reminders": [_reminder("p3_evidence_unavailable", "unavailable", 0, HOLD_REVIEW_WEEKS,
                                "P3 证据不可用；不复用旧提醒，正式 M6.7 不变。")],
        "message": "P3 最终建议验证：当前证据不可用；不复用旧提醒，正式 M6.7 不变。",
        "production_unchanged": True,
    }


def validate_public_summary(summary: dict[str, Any]) -> None:
    try:
        with SCHEMA_PATH.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        jsonschema.validate(summary, schema)
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise FinalActionValidationError("public_summary_contract_invalid") from exc
    if summary.get("comparison_only") is not True or summary.get("automatic_policy_switch") is not False or \
            summary.get("production_unchanged") is not True:
        raise FinalActionValidationError("public_summary_boundary_invalid")
    if summary.get("admissions") != admission_snapshot(*ADMISSION_IDS):
        raise FinalActionValidationError("public_summary_admission_binding_drifted")


def _render_summary_markdown(summary: dict[str, Any]) -> str:
    hold, edge = summary["hold_based"], summary["full_edge"]
    return "\n".join([
        "# A-short P3 final-action validation",
        "",
        f"- as_of: {summary['as_of']}",
        f"- data_through: {summary['data_through'] or '无'}",
        f"- status: {summary['status']}",
        "- boundary: comparison-only；不自动切换正式 M6.7",
        "",
        "| 证据线 | forward 周数 | 受管计划 | 状态 |",
        "|---|---:|---:|---|",
        f"| 选择 vs 候选池/CSI1000 | {hold['forward_weeks']}/{hold['review_threshold_weeks']} | - | {summary['reminders'][0]['status']} |",
        f"| 受管退出完整 edge | {edge['forward_weeks']}/{edge['review_threshold_weeks']} | {edge['managed_plan_count']}/{HAC_MIN_PLANS} | {summary['reminders'][1]['status']} |",
        "",
        "> 只显示脱敏进度；逐股选择、账户、私有账本与价格均不公开。",
        "",
    ])


def write_public_summary(summary: dict[str, Any], *, summary_path: str | Path,
                         markdown_path: str | Path) -> None:
    validate_public_summary(summary)
    _atomic_write(summary_path, summary)
    path = Path(markdown_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_render_summary_markdown(summary))
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def settle_and_summarize(*, root: str | Path | None, as_of: str, tracker_path: str | Path = TRACKER_DEFAULT,
                         daily_cache_path: str | Path | None = None,
                         summary_path: str | Path = PUBLIC_SUMMARY_DEFAULT,
                         markdown_path: str | Path = PUBLIC_MARKDOWN_DEFAULT) -> dict[str, Any]:
    as_of = _date(as_of)
    if not root:
        return unavailable_public_summary(as_of)
    try:
        private_path, ledger = _load_or_initialize(root)
        epoch = _active_epoch(ledger, create=False)
        if epoch is not None:
            tracker = _load_tracker(tracker_path)
            execution = _load_execution_cache(daily_cache_path)
            for record in epoch["records"]:
                try:
                    cohort = _tracker_cohort(tracker, record["decision_date"], record["source_identity"])
                except FinalActionValidationError as exc:
                    if _record_is_mature(record):
                        record["conflict"] = "mature_tracker_cohort_identity_changed"
                    record["hold_result"] = {"status": "no_count", "reason": str(exc)}
                    record["full_edge_result"] = {"status": "no_count", "reason": "hold_h20_not_comparable"}
                    continue
                _settle_hold(record, cohort)
                _settle_full_edge(record, execution)
            _validate_ledger(ledger)
            _atomic_write(private_path, ledger)
        summary = _summary_from_ledger(ledger, as_of)
        write_public_summary(summary, summary_path=summary_path, markdown_path=markdown_path)
        return summary
    except Exception:
        summary = unavailable_public_summary(as_of)
        try:
            write_public_summary(summary, summary_path=summary_path, markdown_path=markdown_path)
        except Exception:
            pass
        return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A-short P3 final-action validation accumulator (no provider calls)")
    parser.add_argument("command", choices=["refresh", "settle"])
    parser.add_argument("--root", default=str(PRIVATE_LEDGER_DEFAULT))
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--tracker", default=str(TRACKER_DEFAULT))
    parser.add_argument("--daily-cache")
    parser.add_argument("--summary-out", default=str(PUBLIC_SUMMARY_DEFAULT))
    parser.add_argument("--markdown-out", default=str(PUBLIC_MARKDOWN_DEFAULT))
    args = parser.parse_args(argv)
    summary = settle_and_summarize(root=args.root, as_of=args.as_of, tracker_path=args.tracker,
                                   daily_cache_path=args.daily_cache, summary_path=args.summary_out,
                                   markdown_path=args.markdown_out)
    print(summary["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
