# -*- coding: utf-8 -*-
"""US-short A1 comparison v2 immutable preregistration validator.

The v2 contract supersedes the pre-outcome v1 manifest before any authorized
live outcome existed.  It freezes the six immediate Path-A heads, the
Pass2-clean common selection pool, finite H10 comparison basis, 12/24/36
decision clock, question/arm identities, statistical/risk gates, decision
receipts, and combination boundary.

This module validates and fingerprints the contract only.  It fetches nothing,
writes no capture or outcome, never replays/backfills history, and cannot change
the primary selection, paper ledger, production rules, or ship-gate path.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

import jsonschema

from engine.us_short_forward_policy_heads import (
    MINIMUM_FORWARD_WEEKS_BEFORE_PROMOTION_REVIEW,
    SECOND_WAVE_LIVE_POLICY_IDS,
    SELECTION_POLICY_IDS,
)


ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = ROOT / "presets" / "us_short_forward_policy_statistical_plan_20260716.json"
SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_statistical_plan.schema.json"
LIFECYCLE_THRESHOLD_AUTHORITY_PATH = ROOT / "presets" / "us_short_lifecycle_threshold_authority_20260622.json"
_EXPECTED_SECOND_WAVE = ("overextension_execution_off",)
_EXPECTED_AS_OF = "20260716"
_EXPECTED_MARGIN = 0.001
_EXPECTED_BOUNDARY = {
    "shadow_only": True,
    "changes_primary_selection": False,
    "shadow_counts_ship_gate": False,
    "provider_calls_added": False,
    "broker_or_order_automation_allowed": False,
    "historical_replay_is_forward": False,
    "automatic_production_switch": False,
}


class ForwardPolicyStatisticalPlanError(ValueError):
    """Raised when the immutable comparison v2 preregistration drifts."""


def _strict_yyyymmdd(value) -> bool:
    if not (type(value) is str and len(value) == 8 and value.isascii() and value.isdigit()):
        return False
    try:
        datetime.date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return False
    return True


def _load_json(path: Path, *, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyStatisticalPlanError(f"cannot load {label}") from exc
    if type(payload) is not dict:
        raise ForwardPolicyStatisticalPlanError(f"{label} must be an object")
    return payload


def _item_28_minimum_weeks() -> int:
    """Read #28 so the 12-week preliminary clock cannot drift from lifecycle authority."""
    authority = _load_json(LIFECYCLE_THRESHOLD_AUTHORITY_PATH, label="lifecycle threshold authority")
    try:
        category = authority["item_category"]["28"]
        minimum = authority["category_thresholds"][category]["min_count"]
    except (KeyError, TypeError) as exc:
        raise ForwardPolicyStatisticalPlanError("cannot resolve lifecycle threshold item #28") from exc
    if type(minimum) is not int or minimum < 1:
        raise ForwardPolicyStatisticalPlanError("lifecycle threshold authority item #28 minimum is invalid")
    return minimum


def validate_forward_policy_statistical_plan(plan: dict) -> None:
    """Fail closed on schema drift and the cross-authority invariants draft-07 cannot express."""
    if type(plan) is not dict:
        raise ForwardPolicyStatisticalPlanError("plan must be an exact dict")
    schema = _load_json(SCHEMA_PATH, label="comparison v2 schema")
    try:
        jsonschema.validate(plan, schema)
    except jsonschema.ValidationError as exc:
        raise ForwardPolicyStatisticalPlanError(f"comparison v2 schema rejected: {exc.message}") from exc

    if plan["schema_version"] != "2.0.0" or plan["as_of"] != _EXPECTED_AS_OF \
            or not _strict_yyyymmdd(plan["as_of"]):
        raise ForwardPolicyStatisticalPlanError("comparison v2 identity/as_of drifted")

    scope = plan["policy_scope"]
    if tuple(scope["selection_policies"]) != SELECTION_POLICY_IDS or scope["primary_policy"] != SELECTION_POLICY_IDS[0]:
        raise ForwardPolicyStatisticalPlanError("policy scope must match the exact immediate Path-A grid")
    if tuple(SECOND_WAVE_LIVE_POLICY_IDS) != _EXPECTED_SECOND_WAVE \
            or scope["excluded_second_wave_policy"] != _EXPECTED_SECOND_WAVE[0]:
        raise ForwardPolicyStatisticalPlanError("second-wave execution boundary drifted")

    manifest = plan["weekly_manifest"]
    required_bindings = {
        "decision_date", "price_basis_date", "source_context_sha256", "comparison_contract_sha256",
        "common_selection_pool_sha256", "capture_sha256",
    }
    if set(manifest["capture_binding_fields"]) != required_bindings \
            or len(manifest["capture_binding_fields"]) != len(required_bindings):
        raise ForwardPolicyStatisticalPlanError("capture binding fields must cover the v2 source/pool/contract identity exactly")

    statistics = plan["statistics"]
    preliminary = statistics["minimum_forward_weeks_before_preliminary_review"]
    formal = statistics["minimum_divergence_weeks_before_formal_recommendation"]
    retire = statistics["retire_after_divergence_weeks"]
    if preliminary != MINIMUM_FORWARD_WEEKS_BEFORE_PROMOTION_REVIEW or preliminary != _item_28_minimum_weeks():
        raise ForwardPolicyStatisticalPlanError("12-week preliminary clock must match the grid and lifecycle item #28")
    if formal != 24 or formal < preliminary or retire != 36 or retire <= formal:
        raise ForwardPolicyStatisticalPlanError("12/24/36 comparison clock drifted")
    if statistics["minimum_nonoverlap_h10_blocks_before_formal_recommendation"] != 12:
        raise ForwardPolicyStatisticalPlanError("formal inference must retain 12 non-overlap H10 blocks")
    if statistics["minimum_market_risk_regimes_before_formal_recommendation"] != 2 \
            or statistics["minimum_divergence_weeks_per_required_regime"] != 4:
        raise ForwardPolicyStatisticalPlanError("formal recommendation regime coverage drifted")
    if statistics["comparison_win_margin"] != _EXPECTED_MARGIN:
        raise ForwardPolicyStatisticalPlanError("comparison win margin drifted")
    if statistics["familywise_correction"] != "holm_bonferroni" \
            or statistics["adjusted_pvalue_max"] != 0.05:
        raise ForwardPolicyStatisticalPlanError("family-wise correction drifted")

    formal_gate = statistics["elimination_rule"]["formal_recommendation_gate"]
    if formal_gate["minimum_divergence_weeks"] != formal \
            or formal_gate["minimum_nonoverlap_h10_blocks"] != statistics["minimum_nonoverlap_h10_blocks_before_formal_recommendation"] \
            or formal_gate["minimum_market_risk_regimes"] != statistics["minimum_market_risk_regimes_before_formal_recommendation"] \
            or formal_gate["minimum_divergence_weeks_per_required_regime"] != statistics["minimum_divergence_weeks_per_required_regime"] \
            or formal_gate["mean_paired_advantage_gte"] != statistics["comparison_win_margin"] \
            or formal_gate["holm_adjusted_pvalue_lte"] != statistics["adjusted_pvalue_max"]:
        raise ForwardPolicyStatisticalPlanError("formal recommendation gate drifted from top-level authorities")

    risk = statistics["risk_guardrails"]
    harm = statistics["elimination_rule"]["harm"]
    if harm["turnover"]["threshold_multiplier_vs_balanced"] != risk["turnover_harm_multiplier_vs_balanced"] \
            or harm["fill"]["threshold_fraction"] != risk["fill_harm_fraction_vs_balanced"]:
        raise ForwardPolicyStatisticalPlanError("early structural harm rules drifted from risk guardrails")

    if plan["boundary"] != _EXPECTED_BOUNDARY:
        raise ForwardPolicyStatisticalPlanError("shadow-only/no-auto-switch boundary drifted")


def load_forward_policy_statistical_plan() -> dict:
    """Load the sole comparison v2 preregistration; no capture or outcome is read or written."""
    plan = _load_json(PLAN_PATH, label="comparison v2 statistical plan")
    validate_forward_policy_statistical_plan(plan)
    return plan


def statistical_plan_sha256(plan: dict | None = None) -> str:
    """Canonical digest bound into every v2 capture and user decision receipt."""
    # Read the pinned artifact directly rather than delegating through the public
    # loader.  Consumers may inject a validated in-memory plan to exercise a
    # threshold, but that must not silently rewrite the contract identity a
    # previously captured week is bound to.
    payload = _load_json(PLAN_PATH, label="comparison v2 statistical plan") if plan is None else plan
    validate_forward_policy_statistical_plan(payload)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
