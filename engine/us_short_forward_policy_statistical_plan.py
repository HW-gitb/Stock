# -*- coding: utf-8 -*-
"""US-short A1 Cut-D immutable statistical-plan manifest validator.

This module validates one declarative preregistration for the six immediate
Path-A selection heads.  It writes no capture, does not load historical
selection results, makes no provider call, and cannot change the primary
selection or ship-gate path.  Downstream statistical analysis remains a later
cut; this contract fixes its method before the first authorized live capture.
"""
from __future__ import annotations

import datetime
import json
import math
from pathlib import Path

from engine.us_short_forward_policy_heads import (
    MINIMUM_FORWARD_WEEKS_BEFORE_PROMOTION_REVIEW,
    SECOND_WAVE_LIVE_POLICY_IDS,
    SELECTION_POLICY_IDS,
)


ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = ROOT / "presets" / "us_short_forward_policy_statistical_plan_20260712.json"
LIFECYCLE_THRESHOLD_AUTHORITY_PATH = ROOT / "presets" / "us_short_lifecycle_threshold_authority_20260622.json"
_EXPECTED_SECOND_WAVE = ("overextension_execution_off",)
_EXPECTED_AS_OF = "20260712"
_EXPECTED_MARGIN = 0.001
_EXPECTED_BOUNDARY = {
    "shadow_only": True,
    "changes_primary_selection": False,
    "shadow_counts_ship_gate": False,
    "provider_calls_added": False,
    "broker_or_order_automation_allowed": False,
    "historical_replay_is_forward": False,
}


class ForwardPolicyStatisticalPlanError(ValueError):
    """Raised when the Cut-D preregistration is malformed or drifts."""


def _strict_yyyymmdd(value) -> bool:
    if not (type(value) is str and len(value) == 8 and value.isascii() and value.isdigit()):
        return False
    try:
        datetime.date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return False
    return True


def _exact_dict(value, *, where: str) -> dict:
    if type(value) is not dict:
        raise ForwardPolicyStatisticalPlanError(f"{where} must be an exact dict")
    return value


def _exact_keys(value: dict, expected: set[str], *, where: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ForwardPolicyStatisticalPlanError(
            f"{where} keys drifted: missing={sorted(expected - actual)!r} extra={sorted(actual - expected)!r}"
        )


def _finite_number(value, *, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ForwardPolicyStatisticalPlanError(f"{where} must be finite numeric")
    return float(value)


def _item_28_minimum_weeks() -> int:
    """Read the #28 lifecycle threshold so Cut-D cannot drift from the calibration authority."""
    try:
        authority = json.loads(LIFECYCLE_THRESHOLD_AUTHORITY_PATH.read_text(encoding="utf-8"))
        category = authority["item_category"]["28"]
        minimum = authority["category_thresholds"][category]["min_count"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ForwardPolicyStatisticalPlanError("cannot read lifecycle threshold authority for item #28") from exc
    if type(minimum) is not int or minimum < 1:
        raise ForwardPolicyStatisticalPlanError("lifecycle threshold authority item #28 minimum is invalid")
    return minimum


def validate_forward_policy_statistical_plan(plan: dict) -> None:
    """Fail closed on any drift from the one Cut-D, before-live preregistration."""
    plan = _exact_dict(plan, where="plan")
    _exact_keys(
        plan,
        {"schema_name", "schema_version", "as_of", "status", "policy_scope", "weekly_manifest", "statistics", "boundary"},
        where="plan",
    )
    if plan["schema_name"] != "us_short_forward_policy_statistical_plan" or plan["schema_version"] != "1.0.0":
        raise ForwardPolicyStatisticalPlanError("schema identity drifted")
    if plan["as_of"] != _EXPECTED_AS_OF or not _strict_yyyymmdd(plan["as_of"]):
        raise ForwardPolicyStatisticalPlanError("immutable preregistration as_of drifted")
    if plan["status"] != "preregistered_before_first_authorized_live_capture":
        raise ForwardPolicyStatisticalPlanError("plan must remain preregistered before any authorized live capture")

    scope = _exact_dict(plan["policy_scope"], where="policy_scope")
    _exact_keys(scope, {"primary_policy", "selection_policies", "excluded_second_wave_policy", "sizing_neutral_in_scope"}, where="policy_scope")
    if scope["primary_policy"] != "balanced" or tuple(scope["selection_policies"]) != SELECTION_POLICY_IDS:
        raise ForwardPolicyStatisticalPlanError("policy scope must match the exact immediate selection grid")
    if scope["excluded_second_wave_policy"] not in SECOND_WAVE_LIVE_POLICY_IDS or tuple(SECOND_WAVE_LIVE_POLICY_IDS) != _EXPECTED_SECOND_WAVE:
        raise ForwardPolicyStatisticalPlanError("second-wave policy boundary drifted")
    if scope["sizing_neutral_in_scope"] is not False:
        raise ForwardPolicyStatisticalPlanError("sizing_neutral is not in the Cut-D policy scope")

    manifest = _exact_dict(plan["weekly_manifest"], where="weekly_manifest")
    _exact_keys(
        manifest,
        {"recording_mode", "capture_binding_fields", "unit_of_independence", "dedupe_key", "historical_replay_counts_as_forward", "backfill_allowed"},
        where="weekly_manifest",
    )
    if manifest["recording_mode"] != "same_run_live_capture_only":
        raise ForwardPolicyStatisticalPlanError("weekly manifest must be same-run live capture only")
    if manifest["capture_binding_fields"] != ["decision_date", "price_basis_date", "source_context_sha256", "capture_sha256"]:
        raise ForwardPolicyStatisticalPlanError("weekly manifest capture binding drifted")
    if manifest["unit_of_independence"] != "decision_week" or manifest["dedupe_key"] != "decision_date_and_policy":
        raise ForwardPolicyStatisticalPlanError("weekly unit or dedupe basis drifted")
    if manifest["historical_replay_counts_as_forward"] is not False or manifest["backfill_allowed"] is not False:
        raise ForwardPolicyStatisticalPlanError("historical replay or backfill cannot count as forward evidence")

    statistics = _exact_dict(plan["statistics"], where="statistics")
    _exact_keys(
        statistics,
        {"primary_metric", "primary_delta", "selection_divergence", "minimum_forward_weeks_before_promotion_review", "comparison_win_margin", "comparison_margin_unit", "placebo", "paired_basis", "elimination_rule"},
        where="statistics",
    )
    if statistics["primary_metric"] != "net_benchmark_excess" or statistics["primary_delta"] != "policy_minus_balanced":
        raise ForwardPolicyStatisticalPlanError("primary paired metric drifted")
    if statistics["selection_divergence"] != {
        "selection_count": 15,
        "membership_symmetric_difference_at_least": 1,
        "rank_and_selection_bucket_diagnostics_are_secondary": True,
        "action_and_size_outcomes_available": False,
    }:
        raise ForwardPolicyStatisticalPlanError("selection divergence definition drifted")
    if statistics["minimum_forward_weeks_before_promotion_review"] != MINIMUM_FORWARD_WEEKS_BEFORE_PROMOTION_REVIEW \
            or statistics["minimum_forward_weeks_before_promotion_review"] != _item_28_minimum_weeks():
        raise ForwardPolicyStatisticalPlanError("minimum forward weeks must match the policy grid and lifecycle item #28")
    if _finite_number(statistics["comparison_win_margin"], where="comparison_win_margin") != _EXPECTED_MARGIN:
        raise ForwardPolicyStatisticalPlanError("comparison win margin drifted")
    if statistics["comparison_margin_unit"] != "net_return_fraction":
        raise ForwardPolicyStatisticalPlanError("comparison margin unit drifted")
    if statistics["placebo"] != {
        "replicates": 1000,
        "seed_start": 0,
        "seed_end_inclusive": 999,
        "match_frequency": "data_bound_to_each_head_weekly_divergence_count",
        "method": "balanced_top15_same_pool_random_in_out_swaps",
    }:
        raise ForwardPolicyStatisticalPlanError("placebo method drifted")
    if statistics["paired_basis"] != "same_decision_week_policy_minus_balanced":
        raise ForwardPolicyStatisticalPlanError("paired basis drifted")
    if statistics["elimination_rule"] != {
        "no_automatic_promotion": True,
        "early_action": "futility_or_harm_only",
        "outcome_blind_before_minimum": True,
        "futility": {
            "comparison": "lt",
            "minimum_divergence_weeks": 2,
            "within_first_decision_weeks": 8,
        },
        "harm": {
            "combine": "or",
            "turnover": {
                "metric": "mean_weekly_top15_turnover",
                "comparison": "gt",
                "threshold_multiplier_vs_balanced": 2.0,
                "sustained_decision_weeks": 2,
            },
            "fill": {
                "metric": "top15_fill_vs_balanced_seat_count",
                "comparison": "lt",
                "threshold_fraction": 0.5,
                "sustained_decision_weeks": 2,
            },
        },
        "flag_effect": "surface_for_human_review_only",
        "promotion_gate": {
            "minimum_divergence_weeks": 12,
            "mean_paired_advantage_gte": 0.001,
            "paired_win_consistency_fraction": [2, 3],
            "placebo_percentile_exclusive_gt": 0.95,
        },
    }:
        raise ForwardPolicyStatisticalPlanError("elimination rule drifted")

    if plan["boundary"] != _EXPECTED_BOUNDARY:
        raise ForwardPolicyStatisticalPlanError("shadow-only boundary drifted")


def load_forward_policy_statistical_plan() -> dict:
    """Load and validate the sole immutable Cut-D preregistration; no capture is read or written."""
    try:
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyStatisticalPlanError("cannot load the Cut-D statistical plan") from exc
    validate_forward_policy_statistical_plan(plan)
    return plan
