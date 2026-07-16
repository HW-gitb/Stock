# -*- coding: utf-8 -*-
"""US-short A1 Cut A: immediate, same-decision-date shadow-selection materialization.

This module consumes the already source-bound score composition written by the Batch5-to-Batch4 seam, runs the six
Path-A selection heads through the authoritative ``run_selection`` delegate, and emits two artifacts:

* a ticker-bearing private record under ``state/us_short/shadow_compare_private``; and
* a de-identified, count-only summary eligible for repository tracking.

It does not fetch data, replay a past week, compute a paper outcome, update lifecycle observations, or touch the
ship-gate.  Those operations require later forward outcomes and belong to the subsequent cuts.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path

import jsonschema

from engine.us_short_forward_policy_heads import (
    SELECTION_POLICY_IDS,
    ForwardPolicyHeadError,
    build_selection_policy_decisions,
)
from engine.us_short_forward_policy_statistical_plan import statistical_plan_sha256
from engine.us_short_private_paths import reject_nonprivate_output_path


ROOT = Path(__file__).resolve().parent.parent
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_shadow_summary.schema.json"
SUMMARY_ROOT = ROOT / "research" / "results" / "us_short_forward_policy_shadow"
PRIVATE_RECORD_KEYS = frozenset({
    "schema_name", "schema_version", "decision_date", "price_basis_date", "generated_at",
    "source_context_sha256", "comparison_contract_sha256", "common_selection_pool",
    "common_selection_pool_sha256", "selection_policies", "selection_decisions", "boundary",
})
SELECTION_DECISION_KEYS = frozenset({
    "out_of_window", "decision_date", "price_basis_date", "run_date", "cheap_eligible", "candidates",
    "recall_available", "recall_added", "recall_excluded", "exclusion_records", "admitted",
    "selection_seats", "theme_selection_mode", "full_analysis_leader_upgrades", "selection_details", "holdings",
})
BOUNDARY = {
    "track": "comparison_non_production",
    "evidence_level": "shadow_selection_only",
    "shadow_counts_ship_gate": False,
    "full_size_ship_gate_allowed": False,
    "provider_calls_added": False,
    "broker_or_order_automation_allowed": False,
}


class ForwardPolicyShadowStageError(ValueError):
    """The A1 decision snapshot, private path, or de-identified summary is invalid."""


def _strict_yyyymmdd(value: object) -> bool:
    if not (isinstance(value, str) and value.isascii() and len(value) == 8 and value.isdigit()):
        return False
    try:
        datetime.date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return False
    return True


def _load_schema() -> dict:
    return json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_summary(summary: object) -> None:
    try:
        jsonschema.validate(summary, _load_schema())
    except jsonschema.ValidationError as exc:
        raise ForwardPolicyShadowStageError(f"forward-policy summary schema rejected: {exc.message}") from exc
    if not _strict_yyyymmdd(summary["decision_date"]) or not _strict_yyyymmdd(summary["price_basis_date"]):
        raise ForwardPolicyShadowStageError("forward-policy summary dates must be strict real YYYYMMDD")
    if summary["price_basis_date"] >= summary["decision_date"]:
        raise ForwardPolicyShadowStageError("price_basis_date must precede decision_date")
    for field in ("source_context_sha256", "comparison_contract_sha256", "common_selection_pool_sha256"):
        digest = summary.get(field)
        if not isinstance(digest, str) or len(digest) != 64 \
                or any(char not in "0123456789abcdef" for char in digest):
            raise ForwardPolicyShadowStageError(f"forward-policy summary {field} must be a lowercase SHA256")
    if summary["comparison_contract_sha256"] != statistical_plan_sha256():
        raise ForwardPolicyShadowStageError("forward-policy summary comparison contract digest drifted")
    counts = summary["selected_counts"]
    if any(count > summary["common_selection_pool_count"] for count in counts.values()):
        raise ForwardPolicyShadowStageError("selected count cannot exceed the Pass2-clean common pool count")
    for policy_id, divergence in summary["divergence_vs_balanced"].items():
        if divergence["balanced_only_count"] + divergence["overlap_count"] != counts["balanced"]:
            raise ForwardPolicyShadowStageError(f"{policy_id} balanced divergence count is inconsistent")
        if divergence["policy_only_count"] + divergence["overlap_count"] != counts[policy_id]:
            raise ForwardPolicyShadowStageError(f"{policy_id} policy divergence count is inconsistent")


def _private_path_is_canonical(path: Path, *, decision_date: str) -> None:
    expected_name = f"forward_policy_selection_{decision_date}.json"
    resolved = path.resolve()
    expected_parent = (ROOT / "state" / "us_short" / "shadow_compare_private").resolve()
    try:
        in_repo = resolved.is_relative_to(ROOT.resolve())
    except AttributeError:  # pragma: no cover - Python >=3.9 supports is_relative_to in supported environments
        in_repo = str(resolved).startswith(str(ROOT.resolve()))
    if in_repo and (resolved.parent != expected_parent or resolved.name != expected_name):
        raise ForwardPolicyShadowStageError(
            "in-repo A1 private selection record must use the canonical shadow_compare_private decision bucket")
    if not in_repo and resolved.name == expected_name:
        return
    if not in_repo and resolved.name != expected_name:
        raise ForwardPolicyShadowStageError("external A1 private selection record must retain its decision-date filename")


def _summary_path_is_canonical(path: Path, *, decision_date: str) -> None:
    expected_name = f"forward_policy_summary_{decision_date}.json"
    resolved = path.resolve()
    expected_parent = SUMMARY_ROOT.resolve()
    try:
        in_repo = resolved.is_relative_to(ROOT.resolve())
    except AttributeError:  # pragma: no cover
        in_repo = str(resolved).startswith(str(ROOT.resolve()))
    if in_repo and (resolved.parent != expected_parent or resolved.name != expected_name):
        raise ForwardPolicyShadowStageError(
            "in-repo A1 de-identified summary must use the canonical research/results decision bucket")
    if not in_repo and resolved.name != expected_name:
        raise ForwardPolicyShadowStageError("external A1 summary must retain its decision-date filename")


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _validate_decisions(decisions: object, *, decision_date: str, price_basis_date: str) -> dict:
    if not isinstance(decisions, dict) or tuple(decisions) != SELECTION_POLICY_IDS:
        raise ForwardPolicyShadowStageError("selection decisions must cover the frozen immediate policy set in grid order")
    for policy_id, decision in decisions.items():
        if not isinstance(decision, dict):
            raise ForwardPolicyShadowStageError(f"{policy_id} selection decision must be a dict")
        if set(decision) != SELECTION_DECISION_KEYS:
            raise ForwardPolicyShadowStageError(f"{policy_id} selection decision shape drifted")
        if decision.get("out_of_window") is not False:
            raise ForwardPolicyShadowStageError(f"{policy_id} did not materialize in the live decision window")
        if decision.get("decision_date") != decision_date or decision.get("price_basis_date") != price_basis_date:
            raise ForwardPolicyShadowStageError(f"{policy_id} decision clock differs from the capstone canonical clock")
        admitted = decision.get("admitted")
        if not isinstance(admitted, list) or len(admitted) != len(set(admitted)) or any(
            not isinstance(ticker, str) or not ticker for ticker in admitted
        ):
            raise ForwardPolicyShadowStageError(f"{policy_id} admitted selection is not a unique ticker list")
    return decisions


def _common_pool_for_decision(decision: dict, *, policy_id: str) -> list[str]:
    """Derive the Pass2-clean pool: candidates minus only Pass2 hard-gate exclusions.

    Top15 rank exclusions remain in the pool.  Pass1 and recall failures never enter
    ``candidates``.  The six heads must derive the identical ordered pool because
    their only allowed change is the registered scoring/selection factor.
    """
    candidates = decision.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(set(candidates)) or any(
        not isinstance(ticker, str) or not ticker for ticker in candidates
    ):
        raise ForwardPolicyShadowStageError(f"{policy_id} candidates must be a unique non-blank ticker list")
    records = decision.get("exclusion_records")
    if not isinstance(records, list):
        raise ForwardPolicyShadowStageError(f"{policy_id} exclusion_records must be a list")
    pass2_excluded: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ForwardPolicyShadowStageError(f"{policy_id} exclusion_records[{index}] must be an object")
        if record.get("stage") != "pass2_audit_gate":
            continue
        ticker = record.get("ticker")
        if ticker not in candidates or ticker in pass2_excluded:
            raise ForwardPolicyShadowStageError(
                f"{policy_id} Pass2 exclusion must identify one unique candidate ticker"
            )
        pass2_excluded.add(ticker)
    pool = [ticker for ticker in candidates if ticker not in pass2_excluded]
    if not pool:
        raise ForwardPolicyShadowStageError(f"{policy_id} Pass2-clean common selection pool is empty")
    if not set(decision["admitted"]).issubset(set(pool)):
        raise ForwardPolicyShadowStageError(f"{policy_id} selected a ticker outside its Pass2-clean pool")
    return pool


def _derive_common_selection_pool(decisions: dict) -> list[str]:
    pools = {
        policy_id: _common_pool_for_decision(decision, policy_id=policy_id)
        for policy_id, decision in decisions.items()
    }
    reference = pools[SELECTION_POLICY_IDS[0]]
    for policy_id in SELECTION_POLICY_IDS[1:]:
        if pools[policy_id] != reference:
            raise ForwardPolicyShadowStageError(
                f"{policy_id} Pass2-clean pool differs from balanced; a shadow head changed a hard gate or candidate order"
            )
    return reference


def validate_forward_shadow_selection_record(record: object) -> dict:
    """Closed-world consumer gate for the persisted Cut-A ticker-bearing record."""
    if not isinstance(record, dict) or set(record) != PRIVATE_RECORD_KEYS:
        raise ForwardPolicyShadowStageError("private A1 record key set drifted")
    if record.get("schema_name") != "us_short_forward_policy_shadow_selection" \
            or record.get("schema_version") != "2.0.0" \
            or not isinstance(record.get("generated_at"), str) or not record["generated_at"]:
        raise ForwardPolicyShadowStageError("private A1 record identity/generated_at is invalid")
    decision_date, price_basis_date = record.get("decision_date"), record.get("price_basis_date")
    if not _strict_yyyymmdd(decision_date) or not _strict_yyyymmdd(price_basis_date) \
            or price_basis_date >= decision_date:
        raise ForwardPolicyShadowStageError("private A1 record decision/price-basis clock is invalid")
    digest = record.get("source_context_sha256")
    if not isinstance(digest, str) or len(digest) != 64 \
            or any(char not in "0123456789abcdef" for char in digest):
        raise ForwardPolicyShadowStageError("private A1 record source_context_sha256 is invalid")
    if record.get("selection_policies") != list(SELECTION_POLICY_IDS) or record.get("boundary") != BOUNDARY:
        raise ForwardPolicyShadowStageError("private A1 record policy set/boundary drifted")
    decisions = _validate_decisions(
        record.get("selection_decisions"), decision_date=decision_date, price_basis_date=price_basis_date,
    )
    common_pool = _derive_common_selection_pool(decisions)
    if record.get("common_selection_pool") != common_pool:
        raise ForwardPolicyShadowStageError("private A1 common_selection_pool is not the derived Pass2-clean pool")
    if record.get("common_selection_pool_sha256") != _canonical_sha256(common_pool):
        raise ForwardPolicyShadowStageError("private A1 common_selection_pool digest drifted")
    if record.get("comparison_contract_sha256") != statistical_plan_sha256():
        raise ForwardPolicyShadowStageError("private A1 comparison contract digest drifted")
    return record


def _build_summary(*, decision_date: str, price_basis_date: str, source_context_sha256: str,
                   common_selection_pool: list[str], common_selection_pool_sha256: str,
                   comparison_contract_sha256: str, decisions: dict) -> dict:
    balanced = set(decisions["balanced"]["admitted"])
    summary = {
        "schema_name": "us_short_forward_policy_shadow_summary",
        "schema_version": "2.0.0",
        "decision_date": decision_date,
        "price_basis_date": price_basis_date,
        "source_context_sha256": source_context_sha256,
        "comparison_contract_sha256": comparison_contract_sha256,
        "common_selection_pool_count": len(common_selection_pool),
        "common_selection_pool_sha256": common_selection_pool_sha256,
        "selection_policies": list(SELECTION_POLICY_IDS),
        "selected_counts": {policy_id: len(decisions[policy_id]["admitted"]) for policy_id in SELECTION_POLICY_IDS},
        "divergence_vs_balanced": {},
        "boundary": dict(BOUNDARY),
    }
    for policy_id in SELECTION_POLICY_IDS:
        if policy_id == "balanced":
            continue
        selected = set(decisions[policy_id]["admitted"])
        summary["divergence_vs_balanced"][policy_id] = {
            "balanced_only_count": len(balanced - selected),
            "policy_only_count": len(selected - balanced),
            "overlap_count": len(balanced & selected),
        }
    _validate_summary(summary)
    return summary


def materialize_forward_policy_shadow(
    *, now_et, sessions, data_context, eligibility_governance, score_composition, overextension_by_ticker,
    decision_date: str, price_basis_date: str, generated_at: str, source_context_sha256: str,
    private_output_path: Path, summary_output_path: Path,
) -> dict:
    """Run and persist the six immediate Path-A selection heads for THIS canonical decision only.

    ``source_context_sha256`` binds the record to the exact context-components file consumed by the capstone.  It is
    audit identity only: this function has no load/replay entry point and cannot convert an earlier week into a
    forward observation.  Ticker-bearing decisions go only to the private path; the companion summary is schema-
    constrained to count-only data and can be tracked.
    """
    if not _strict_yyyymmdd(decision_date) or not _strict_yyyymmdd(price_basis_date):
        raise ForwardPolicyShadowStageError("capstone decision and price-basis dates must be strict real YYYYMMDD")
    if price_basis_date >= decision_date:
        raise ForwardPolicyShadowStageError("capstone price_basis_date must precede decision_date")
    if not isinstance(generated_at, str) or not generated_at:
        raise ForwardPolicyShadowStageError("generated_at must be a non-empty string")
    if not isinstance(source_context_sha256, str) or len(source_context_sha256) != 64 \
            or any(char not in "0123456789abcdef" for char in source_context_sha256):
        raise ForwardPolicyShadowStageError("source_context_sha256 must be a lowercase SHA256 hex digest")

    private_output_path = Path(private_output_path)
    summary_output_path = Path(summary_output_path)
    reject_nonprivate_output_path(private_output_path)
    _private_path_is_canonical(private_output_path, decision_date=decision_date)
    _summary_path_is_canonical(summary_output_path, decision_date=decision_date)

    try:
        output = build_selection_policy_decisions(
            now_et=now_et,
            sessions=sessions,
            data_context=data_context,
            eligibility_governance=eligibility_governance,
            score_composition=score_composition,
            overextension_by_ticker=overextension_by_ticker,
        )
    except ForwardPolicyHeadError as exc:
        raise ForwardPolicyShadowStageError(f"A1 selection heads rejected the frozen source context: {exc}") from exc
    decisions = _validate_decisions(
        output["selection_decisions"], decision_date=decision_date, price_basis_date=price_basis_date,
    )
    common_selection_pool = _derive_common_selection_pool(decisions)
    common_selection_pool_sha256 = _canonical_sha256(common_selection_pool)
    comparison_contract_sha256 = statistical_plan_sha256()
    summary = _build_summary(
        decision_date=decision_date,
        price_basis_date=price_basis_date,
        source_context_sha256=source_context_sha256,
        common_selection_pool=common_selection_pool,
        common_selection_pool_sha256=common_selection_pool_sha256,
        comparison_contract_sha256=comparison_contract_sha256,
        decisions=decisions,
    )
    private_record = {
        "schema_name": "us_short_forward_policy_shadow_selection",
        "schema_version": "2.0.0",
        "decision_date": decision_date,
        "price_basis_date": price_basis_date,
        "generated_at": generated_at,
        "source_context_sha256": source_context_sha256,
        "comparison_contract_sha256": comparison_contract_sha256,
        "common_selection_pool": common_selection_pool,
        "common_selection_pool_sha256": common_selection_pool_sha256,
        "selection_policies": list(SELECTION_POLICY_IDS),
        "selection_decisions": decisions,
        "boundary": dict(BOUNDARY),
    }
    if set(private_record) != PRIVATE_RECORD_KEYS:
        raise ForwardPolicyShadowStageError("private A1 record shape drifted")
    validate_forward_shadow_selection_record(private_record)
    _atomic_json_write(private_output_path, private_record)
    _atomic_json_write(summary_output_path, summary)
    return {
        "private_record_path": str(private_output_path),
        "summary_path": str(summary_output_path),
        "summary": summary,
    }
