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
PLAN_PATH = ROOT / "presets" / "us_short_forward_policy_statistical_plan_20260718.json"
SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_statistical_plan_v2_1.schema.json"
LIFECYCLE_THRESHOLD_AUTHORITY_PATH = ROOT / "presets" / "us_short_lifecycle_threshold_authority_20260622.json"
_EXPECTED_SECOND_WAVE = ("overextension_execution_off",)
_EXPECTED_AS_OF = "20260718"
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

    if plan["schema_version"] != "2.1.0" or plan["as_of"] != _EXPECTED_AS_OF \
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
        "baseline_epoch_sha256",
        "common_selection_pool_sha256", "capture_sha256",
    }
    if set(manifest["capture_binding_fields"]) != required_bindings \
            or len(manifest["capture_binding_fields"]) != len(required_bindings):
        raise ForwardPolicyStatisticalPlanError("capture binding fields must cover the v2.1 source/epoch/pool/contract identity exactly")
    if manifest["recording_mode"] != "same_run_live_capture_only" \
            or manifest["common_selection_pool_basis"] != "pass2_clean_after_all_hard_gates_before_policy_ranking" \
            or manifest["historical_replay_counts_as_forward"] is not False \
            or manifest["backfill_allowed"] is not False:
        raise ForwardPolicyStatisticalPlanError("forward-only source/pool/replay boundary drifted")

    epoch = plan["baseline_epoch"]
    if epoch != {
        "effect_surface_contract": "presets/us_short_forward_policy_effect_surface_20260718.json",
        "capture_binding_field": "baseline_epoch_sha256",
        "formal_evaluation_unit": "single_qualified_epoch_block_inference",
        "semantic_identity": "python_ast_without_docstrings_or_attributes_and_canonical_json",
        "effect_surface_change_policy": "start_source_bound_segment_single_epoch_adjudication_authoritative_multi_segment_deferred",
        "cross_epoch_formal_pooling_forbidden": False,
        "per_record_source_binding_invariants": [
            "common_selection_pool_membership",
            "per_arm_selection_difference",
            "h10_outcome_calculation",
        ],
        "multi_segment_cross_epoch_adjudication": "deferred_to_later_reviewed_cut_emit_inconclusive",
        "deferred_cut_scope": "reml_hartung_knapp_interval_plus_frozen_heterogeneity_gate_plus_direction_conflict_not_yet_implemented",
        "segment_mean_pooling_is_reporting_only": True,
        "legacy_v2_counted_records_must_not_migrate": True,
        "epoch_change_disposition": "start_source_bound_segment_record_identity_only_single_epoch_block_inference_authoritative",
    }:
        raise ForwardPolicyStatisticalPlanError("baseline segment/pooling contract drifted")

    if plan["execution_cuts"] != {
        "authorized_execution_cut_count": 2,
        "one_shot_complete_per_cut": True,
        "subcut_execution_forbidden": True,
        "cuts": [
            {
                "cut_id": "a1_v2_1_offline_epoch_formal_look_and_direct_final",
                "scope": "semantic_effect_segment_capture_single_epoch_adjudication_multi_segment_deferred_fixed_24_36_looks_and_direct_multi_passer_final",
                "provider_calls_added": False,
            },
            {
                "cut_id": "a1_corporate_action_evidence_and_maturity_wiring",
                "scope": "authorized_corporate_action_evidence_sidecar_maturity_binding_and_global_no_count_observability",
                "requires_separate_provider_authorization": True,
            },
        ],
    }:
        raise ForwardPolicyStatisticalPlanError("two-cut one-shot execution boundary drifted")

    statistics = plan["statistics"]
    preliminary = statistics["minimum_forward_weeks_before_preliminary_review"]
    formal = statistics["minimum_divergence_weeks_before_formal_recommendation"]
    retire = statistics["retire_after_divergence_weeks"]
    if preliminary != MINIMUM_FORWARD_WEEKS_BEFORE_PROMOTION_REVIEW or preliminary != _item_28_minimum_weeks():
        raise ForwardPolicyStatisticalPlanError("12-week preliminary clock must match the grid and lifecycle item #28")
    if formal != 24 or formal < preliminary or retire != 36 or retire <= formal:
        raise ForwardPolicyStatisticalPlanError("12/24/36 comparison clock drifted")
    if statistics["formal_look_divergence_weeks"] != [24, 36] \
            or statistics["one_sided_alpha_spending"] != [0.0125, 0.0125] \
            or statistics["one_sided_alpha_total"] != 0.025 \
            or statistics["formal_look_disposition"] != "only_frozen_first_n_divergence_weeks_are_formally_tested_at_each_look":
        raise ForwardPolicyStatisticalPlanError("formal looks or alpha-spending schedule drifted")
    if statistics["minimum_nonoverlap_h10_blocks_before_formal_recommendation"] != 12:
        raise ForwardPolicyStatisticalPlanError("formal inference must retain 12 non-overlap H10 blocks")
    if statistics["minimum_market_risk_regimes_before_formal_recommendation"] != 2 \
            or statistics["minimum_divergence_weeks_per_required_regime"] != 4:
        raise ForwardPolicyStatisticalPlanError("formal recommendation regime coverage drifted")
    if statistics["comparison_win_margin"] != _EXPECTED_MARGIN:
        raise ForwardPolicyStatisticalPlanError("comparison win margin drifted")
    if statistics["selection_divergence"] != {
        "selection_count": 15,
        "membership_symmetric_difference_at_least": 1,
        "rank_and_selection_bucket_diagnostics_are_secondary": True,
        "action_and_size_outcomes_available": False,
    } or statistics["placebo"] != {
        "replicates": 1000,
        "seed_start": 0,
        "seed_end_inclusive": 999,
        "match_frequency": "data_bound_to_each_head_weekly_divergence_count",
        "method": "balanced_top15_same_pass2_clean_pool_random_in_out_swaps",
    }:
        raise ForwardPolicyStatisticalPlanError("selection-divergence or placebo identity drifted")
    if statistics["familywise_correction"] != "holm_bonferroni" \
            or statistics["adjusted_pvalue_max"] != 0.025 \
            or statistics["paired_block_confidence_lower_alpha"] != 0.025:
        raise ForwardPolicyStatisticalPlanError("family-wise correction drifted")

    formal_gate = statistics["elimination_rule"]["formal_recommendation_gate"]
    if formal_gate["minimum_divergence_weeks"] != formal \
            or formal_gate["minimum_nonoverlap_h10_blocks"] != statistics["minimum_nonoverlap_h10_blocks_before_formal_recommendation"] \
            or formal_gate["minimum_market_risk_regimes"] != statistics["minimum_market_risk_regimes_before_formal_recommendation"] \
            or formal_gate["minimum_divergence_weeks_per_required_regime"] != statistics["minimum_divergence_weeks_per_required_regime"] \
            or formal_gate["mean_paired_advantage_gte"] != statistics["comparison_win_margin"] \
            or formal_gate["holm_adjusted_pvalue_lte"] != statistics["adjusted_pvalue_max"] \
            or formal_gate["paired_win_consistency_fraction"] != [2, 3] \
            or formal_gate["placebo_percentile_exclusive_gt"] != 0.95 \
            or formal_gate["paired_block_confidence_interval_lower_gt"] != 0.0 \
            or formal_gate["all_risk_guardrails_must_pass"] is not True:
        raise ForwardPolicyStatisticalPlanError("formal recommendation gate drifted from top-level authorities")

    attribution = plan["outcome_contract"]["selection_attribution"]
    if attribution["primary_horizon_trading_sessions"] != 10 \
            or attribution["diagnostic_horizons_trading_sessions"] != [5, 20] \
            or attribution["incomplete_price_or_corporate_action_disposition"] != "data_degraded_whole_week_no_count":
        raise ForwardPolicyStatisticalPlanError("frozen H10/common whole-week outcome boundary drifted")

    risk = statistics["risk_guardrails"]
    harm = statistics["elimination_rule"]["harm"]
    if harm["turnover"]["threshold_multiplier_vs_balanced"] != risk["turnover_harm_multiplier_vs_balanced"] \
            or harm["fill"]["threshold_fraction"] != risk["fill_harm_fraction_vs_balanced"]:
        raise ForwardPolicyStatisticalPlanError("early structural harm rules drifted from risk guardrails")

    direct = plan["decision_contract"]["direct_pairwise_final"]
    if direct != {
        "activation": "only_at_reached_formal_look_when_multiple_arms_pass",
        "comparison_basis": "behaviorally_orthogonal_segments_first_n_pairwise_selection_divergence_weeks",
        "minimum_pairwise_divergence_weeks": 24,
        "minimum_nonoverlap_h10_blocks": 12,
        "minimum_market_risk_regimes": 2,
        "minimum_divergence_weeks_per_required_regime": 4,
        "economic_margin": _EXPECTED_MARGIN,
        "simultaneous_inference": "bonferroni_one_sided_paired_block_bootstrap",
        "confidence_lower_alpha": 0.025,
        "unique_winner_requires_all_pairwise_lower_bounds_gt_margin": True,
        "otherwise_status": "inconclusive",
    }:
        raise ForwardPolicyStatisticalPlanError("direct multi-passer final contract drifted")
    receipt_fields = plan["decision_contract"]["user_decision_receipt_required_fields"]
    if receipt_fields != [
        "question_id", "arm_id", "verdict_sha256", "contract_sha256", "baseline_epoch_sha256", "decision", "decided_at",
    ]:
        raise ForwardPolicyStatisticalPlanError("user decision receipt must bind one baseline epoch")

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
