# -*- coding: utf-8 -*-
"""Project one validated private forward-week record into six-head H10 comparison evidence.

This deliberately read-only bridge is the first consumer of the fourth-blade private record.  It revalidates that
record (which re-runs the H5/H10/H20 outcome core), then uses every head's frozen Cut-A selection against the SAME
common-pool H10 after-cost candidate values.  It produces the preregistered per-policy H10 basket means and paired
policy-minus-balanced deltas, while preserving an explicit whole-week no-count state.

The result is an in-memory private accumulator input only.  It neither establishes same-run live provenance nor scans
or writes a result directory, so it cannot itself count a forward week, issue a recommendation, alter the primary
system, or claim that an H10 evaluation mark was a production exit.  Those responsibilities remain with later, gated
source/accumulator/evaluator wiring.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
from pathlib import Path

import jsonschema

from engine.us_short_forward_policy_heads import SELECTION_POLICY_IDS
from engine.us_short_forward_policy_private_week import (
    ForwardPolicyPrivateWeekError,
    validate_forward_policy_private_week_record,
)
from engine.us_short_forward_policy_shadow_stage import (
    ForwardPolicyShadowStageError,
    validate_forward_shadow_selection_record,
)
from engine.us_short_forward_policy_statistical_plan import load_forward_policy_statistical_plan


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_h10_weekly_evidence.schema.json"
_RECORD_KEYS = frozenset({
    "schema_name", "schema_version", "projection_status", "degradation_reason", "source_private_week_record_sha256",
    "source_private_week_record", "capture_binding", "frozen_capture", "common_selection_pool",
    "common_order_snapshot_sha256", "common_price_snapshot_sha256",
    "market_risk_regime", "h10_session_date", "outcome_available_as_of", "selection_policies", "primary_policy",
    "factor_questions", "policy_selections", "candidate_after_cost_net_return", "policy_h10_after_cost_net_return",
    "policy_minus_balanced", "boundary",
})
BOUNDARY = {
    "track": "comparison_non_production",
    "evidence_level": "forward_policy_h10_private_projection",
    "shadow_counts_ship_gate": False,
    "full_size_ship_gate_allowed": False,
    "changes_primary_selection": False,
    "provider_calls_added": False,
    "broker_or_order_automation_allowed": False,
    "writes_private_evidence": False,
    "produces_forward_evidence": False,
    "issues_formal_recommendation": False,
    "evaluation_mark_is_production_exit": False,
    "evaluation_mark_changes_model_paper_ledger": False,
}


class ForwardPolicyWeeklyEvidenceError(ValueError):
    """A private forward-week record cannot safely form one common-pool H10 comparison projection."""


def _canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ForwardPolicyWeeklyEvidenceError("weekly-evidence value is not finite canonical JSON") from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _strict_yyyymmdd(value: object) -> bool:
    if not (type(value) is str and value.isascii() and len(value) == 8 and value.isdigit()):
        return False
    try:
        datetime.date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return False
    return True


def _sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _load_schema() -> dict:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyWeeklyEvidenceError("cannot load forward-policy H10 weekly-evidence schema") from exc


def _validate_schema(record: object) -> None:
    try:
        jsonschema.validate(record, _load_schema())
    except jsonschema.ValidationError as exc:
        raise ForwardPolicyWeeklyEvidenceError(f"forward-policy H10 weekly-evidence schema rejected: {exc.message}") from exc


def _plan() -> dict:
    return load_forward_policy_statistical_plan()


def _factor_questions(plan: dict) -> dict:
    return {question_id: list(arms) for question_id, arms in plan["policy_scope"]["factor_questions"].items()}


def _policy_selections(capture: dict) -> dict[str, list[str]]:
    return {policy_id: list(capture["selection_decisions"][policy_id]["admitted"]) for policy_id in SELECTION_POLICY_IDS}


def _capture_binding(capture: dict) -> dict:
    return {
        "decision_date": capture["decision_date"],
        "price_basis_date": capture["price_basis_date"],
        "source_context_sha256": capture["source_context_sha256"],
        "comparison_contract_sha256": capture["comparison_contract_sha256"],
        "common_selection_pool_sha256": capture["common_selection_pool_sha256"],
        "capture_sha256": _canonical_sha256(capture),
    }


def _validated_frozen_capture(capture: object) -> dict:
    try:
        return validate_forward_shadow_selection_record(capture)
    except ForwardPolicyShadowStageError as exc:
        raise ForwardPolicyWeeklyEvidenceError(f"frozen Cut-A capture is invalid: {exc}") from exc


def _validate_policy_selections(selections: object, *, pool: list[str], required_count: int | None) -> dict[str, list[str]]:
    if not isinstance(selections, dict) or set(selections) != set(SELECTION_POLICY_IDS):
        raise ForwardPolicyWeeklyEvidenceError("policy selections must cover exactly the frozen immediate policy set")
    pool_set = set(pool)
    normalized = {}
    for policy_id in SELECTION_POLICY_IDS:
        selected = selections[policy_id]
        if not isinstance(selected, list) or len(selected) != len(set(selected)) \
                or any(type(ticker) is not str or not ticker or ticker not in pool_set for ticker in selected):
            raise ForwardPolicyWeeklyEvidenceError(f"{policy_id} selection is not a unique common-pool ticker list")
        if required_count is not None and len(selected) != required_count:
            raise ForwardPolicyWeeklyEvidenceError(
                f"{policy_id} selection must retain the preregistered fixed Top{required_count} denominator"
            )
        normalized[policy_id] = list(selected)
    return normalized


def _candidate_h10_values(outcome: dict, *, pool: list[str]) -> dict[str, float]:
    rows = outcome["candidate_outcomes"]
    if not isinstance(rows, list) or [row.get("ticker") if isinstance(row, dict) else None for row in rows] != pool:
        raise ForwardPolicyWeeklyEvidenceError("ready outcome must retain the ordered full common-pool candidate rows")
    values = {}
    for row in rows:
        h10 = row["h10"]
        value = h10.get("candidate_after_cost_net_return") if isinstance(h10, dict) else None
        if not _finite(value):
            raise ForwardPolicyWeeklyEvidenceError(f"{row['ticker']} H10 after-cost return must be finite")
        values[row["ticker"]] = float(value)
    return values


def _policy_means(values: dict[str, float], selections: dict[str, list[str]]) -> dict[str, float]:
    return {
        policy_id: sum(values[ticker] for ticker in selections[policy_id]) / len(selections[policy_id])
        for policy_id in SELECTION_POLICY_IDS
    }


def _policy_deltas(means: dict[str, float]) -> dict[str, float]:
    balanced = means[SELECTION_POLICY_IDS[0]]
    return {policy_id: means[policy_id] - balanced for policy_id in SELECTION_POLICY_IDS[1:]}


def _base_record(*, private_week: dict, plan: dict) -> dict:
    capture = private_week["capture"]
    order_snapshot = private_week["order_snapshot"]
    return {
        "schema_name": "us_short_forward_policy_h10_weekly_evidence",
        "schema_version": "1.0.0",
        "source_private_week_record_sha256": _canonical_sha256(private_week),
        "source_private_week_record": private_week,
        "capture_binding": dict(private_week["capture_binding"]),
        "frozen_capture": private_week["capture"],
        "common_selection_pool": list(capture["common_selection_pool"]),
        "common_order_snapshot_sha256": order_snapshot["common_order_snapshot_sha256"],
        "market_risk_regime": order_snapshot["market_risk_regime"],
        "selection_policies": list(SELECTION_POLICY_IDS),
        "primary_policy": SELECTION_POLICY_IDS[0],
        "factor_questions": _factor_questions(plan),
        "policy_selections": _policy_selections(capture),
        "boundary": dict(BOUNDARY),
    }


def build_forward_policy_h10_weekly_evidence(private_week_record: object) -> dict:
    """Return one in-memory H10 projection from one validated fourth-blade private week.

    This function purposefully accepts a record object, not a filesystem path or directory.  A later accumulator must
    separately establish live same-run provenance and non-overlap before counting any projection as forward evidence.
    """
    try:
        private_week = validate_forward_policy_private_week_record(private_week_record)
    except ForwardPolicyPrivateWeekError as exc:
        raise ForwardPolicyWeeklyEvidenceError(f"private forward-week record rejected: {exc}") from exc
    plan = _plan()
    record = _base_record(private_week=private_week, plan=plan)
    outcome = private_week["outcome_packet"]
    if private_week["materialization_status"] == "data_degraded_whole_week_no_count":
        record.update({
            "projection_status": "data_degraded_whole_week_no_count",
            "degradation_reason": private_week["degradation_reason"],
            "common_price_snapshot_sha256": None,
            "h10_session_date": None,
            "outcome_available_as_of": None,
            "candidate_after_cost_net_return": None,
            "policy_h10_after_cost_net_return": None,
            "policy_minus_balanced": None,
        })
        validate_forward_policy_h10_weekly_evidence(record)
        return record
    if private_week["materialization_status"] != "ready_for_accumulation" or not isinstance(outcome, dict) \
            or outcome.get("outcome_status") != "ready_for_comparison":
        raise ForwardPolicyWeeklyEvidenceError("private forward week has an invalid ready/no-count materialization state")

    selection_count = plan["statistics"]["selection_divergence"]["selection_count"]
    pool = record["common_selection_pool"]
    selections = _validate_policy_selections(record["policy_selections"], pool=pool, required_count=selection_count)
    values = _candidate_h10_values(outcome, pool=pool)
    means = _policy_means(values, selections)
    h10_date = outcome["horizon_session_dates"]["h10"]
    available_as_of = outcome["outcome_as_of"]
    record.update({
        "projection_status": "ready_for_private_accumulation",
        "degradation_reason": None,
        "common_price_snapshot_sha256": outcome["common_price_snapshot_sha256"],
        "h10_session_date": h10_date,
        "outcome_available_as_of": available_as_of,
        "candidate_after_cost_net_return": values,
        "policy_h10_after_cost_net_return": means,
        "policy_minus_balanced": _policy_deltas(means),
    })
    validate_forward_policy_h10_weekly_evidence(record)
    return record


def validate_forward_policy_h10_weekly_evidence(record: object) -> dict:
    """Validate the closed-world private projection and rederive its policy means/deltas from H10 candidate values."""
    if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
        raise ForwardPolicyWeeklyEvidenceError("H10 weekly-evidence record must use its exact closed-world key set")
    _validate_schema(record)
    plan = _plan()
    if record["boundary"] != BOUNDARY:
        raise ForwardPolicyWeeklyEvidenceError("H10 weekly-evidence boundary drifted from projection-only policy")
    if record["selection_policies"] != list(SELECTION_POLICY_IDS) or record["primary_policy"] != SELECTION_POLICY_IDS[0]:
        raise ForwardPolicyWeeklyEvidenceError("H10 weekly-evidence policy namespace drifted")
    if record["factor_questions"] != _factor_questions(plan):
        raise ForwardPolicyWeeklyEvidenceError("H10 weekly-evidence factor-question arms drifted from the preregistration")
    if not _sha256(record["source_private_week_record_sha256"]):
        raise ForwardPolicyWeeklyEvidenceError("source private-week record digest is invalid")
    try:
        source_private_week = validate_forward_policy_private_week_record(record["source_private_week_record"])
    except ForwardPolicyPrivateWeekError as exc:
        raise ForwardPolicyWeeklyEvidenceError(f"source private-week record is invalid: {exc}") from exc
    if record["source_private_week_record_sha256"] != _canonical_sha256(source_private_week):
        raise ForwardPolicyWeeklyEvidenceError("source private-week record digest is inconsistent")
    frozen_capture = _validated_frozen_capture(record["frozen_capture"])
    binding = record["capture_binding"]
    expected_binding_keys = {
        "decision_date", "price_basis_date", "source_context_sha256", "comparison_contract_sha256",
        "common_selection_pool_sha256", "capture_sha256",
    }
    if not isinstance(binding, dict) or set(binding) != expected_binding_keys \
            or not _strict_yyyymmdd(binding["decision_date"]) or not _strict_yyyymmdd(binding["price_basis_date"]) \
            or binding["price_basis_date"] >= binding["decision_date"] \
            or any(not _sha256(binding[field]) for field in expected_binding_keys - {"decision_date", "price_basis_date"}):
        raise ForwardPolicyWeeklyEvidenceError("H10 weekly-evidence capture binding is invalid")
    pool = record["common_selection_pool"]
    if not isinstance(pool, list) or not pool or len(pool) != len(set(pool)) \
            or any(type(ticker) is not str or not ticker for ticker in pool):
        raise ForwardPolicyWeeklyEvidenceError("H10 weekly-evidence common pool is invalid")
    if binding != _capture_binding(frozen_capture) \
            or source_private_week["capture"] != frozen_capture \
            or source_private_week["capture_binding"] != binding \
            or pool != frozen_capture["common_selection_pool"] \
            or _canonical_sha256(pool) != binding["common_selection_pool_sha256"]:
        raise ForwardPolicyWeeklyEvidenceError("H10 weekly-evidence capture binding, frozen pool, or pool digest drifted")
    if record["policy_selections"] != _policy_selections(frozen_capture):
        raise ForwardPolicyWeeklyEvidenceError("H10 weekly-evidence policy selections drifted from the frozen Cut-A capture")
    source_order_snapshot = source_private_week["order_snapshot"]
    if record["common_order_snapshot_sha256"] != source_order_snapshot["common_order_snapshot_sha256"] \
            or record["market_risk_regime"] != source_order_snapshot["market_risk_regime"]:
        raise ForwardPolicyWeeklyEvidenceError("H10 weekly-evidence order digest or market regime drifted from its source week")
    if not isinstance(record["market_risk_regime"], str):
        raise ForwardPolicyWeeklyEvidenceError("H10 weekly-evidence order/regime binding is invalid")
    status = record["projection_status"]
    if status == "data_degraded_whole_week_no_count":
        _validate_policy_selections(record["policy_selections"], pool=pool, required_count=None)
        # A no-count may originate before an order exists OR after a valid complete order map meets an incomplete
        # H20/adjustment gate.  Preserve the latter order digest for audit, but never attach a price digest, H10 value,
        # or availability clock to either no-count branch.
        if (record["common_order_snapshot_sha256"] is not None and not _sha256(record["common_order_snapshot_sha256"])) \
                or not isinstance(record["degradation_reason"], str) or any(record[field] is not None for field in (
                    "common_price_snapshot_sha256", "h10_session_date", "outcome_available_as_of",
            "candidate_after_cost_net_return", "policy_h10_after_cost_net_return", "policy_minus_balanced",
        )):
            raise ForwardPolicyWeeklyEvidenceError("no-count projection must retain no price/H10 values or availability clocks")
        if source_private_week["materialization_status"] != "data_degraded_whole_week_no_count" \
                or record["degradation_reason"] != source_private_week["degradation_reason"]:
            raise ForwardPolicyWeeklyEvidenceError("no-count projection status/reason drifted from its source private week")
        return record

    if status != "ready_for_private_accumulation" or record["degradation_reason"] is not None:
        raise ForwardPolicyWeeklyEvidenceError("ready H10 projection status/degradation is inconsistent")
    source_outcome = source_private_week["outcome_packet"]
    if source_private_week["materialization_status"] != "ready_for_accumulation" \
            or not isinstance(source_outcome, dict) or source_outcome.get("outcome_status") != "ready_for_comparison":
        raise ForwardPolicyWeeklyEvidenceError("ready H10 projection must originate from one ready source private week")
    selections = _validate_policy_selections(
        record["policy_selections"], pool=pool,
        required_count=plan["statistics"]["selection_divergence"]["selection_count"],
    )
    if not _sha256(record["common_order_snapshot_sha256"]) or not _sha256(record["common_price_snapshot_sha256"]):
        raise ForwardPolicyWeeklyEvidenceError("ready H10 projection must carry its common order and price digests")
    if not (_strict_yyyymmdd(record["h10_session_date"]) and _strict_yyyymmdd(record["outcome_available_as_of"])
            and binding["decision_date"] < record["h10_session_date"] < record["outcome_available_as_of"]):
        raise ForwardPolicyWeeklyEvidenceError("ready H10 projection dates must be decision < H10 < outcome availability")
    values = record["candidate_after_cost_net_return"]
    if not isinstance(values, dict) or set(values) != set(pool) or any(not _finite(value) for value in values.values()):
        raise ForwardPolicyWeeklyEvidenceError("ready H10 projection must carry finite values for exactly the common pool")
    normalized_values = {ticker: float(values[ticker]) for ticker in pool}
    if record["common_price_snapshot_sha256"] != source_outcome["common_price_snapshot_sha256"] \
            or record["h10_session_date"] != source_outcome["horizon_session_dates"]["h10"] \
            or record["outcome_available_as_of"] != source_outcome["outcome_as_of"] \
            or normalized_values != _candidate_h10_values(source_outcome, pool=pool):
        raise ForwardPolicyWeeklyEvidenceError("ready H10 projection values, clocks, or price digest drifted from its source week")
    expected_means = _policy_means(normalized_values, selections)
    means = record["policy_h10_after_cost_net_return"]
    if not isinstance(means, dict) or set(means) != set(SELECTION_POLICY_IDS) \
            or any(not _finite(value) for value in means.values()) \
            or any(not math.isclose(means[policy_id], expected_means[policy_id], abs_tol=1e-12) for policy_id in SELECTION_POLICY_IDS):
        raise ForwardPolicyWeeklyEvidenceError("policy H10 after-cost values are not rederived from their full selected baskets")
    expected_deltas = _policy_deltas(expected_means)
    deltas = record["policy_minus_balanced"]
    if not isinstance(deltas, dict) or set(deltas) != set(SELECTION_POLICY_IDS[1:]) \
            or any(not _finite(value) for value in deltas.values()) \
            or any(not math.isclose(deltas[policy_id], expected_deltas[policy_id], abs_tol=1e-12)
                   for policy_id in SELECTION_POLICY_IDS[1:]):
        raise ForwardPolicyWeeklyEvidenceError("policy-minus-balanced H10 deltas are not rederived from the common pool")
    return record
