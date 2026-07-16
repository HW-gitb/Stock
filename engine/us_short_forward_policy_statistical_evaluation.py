# -*- coding: utf-8 -*-
"""US-short A1 Cut-D-analysis: pure offline verdict engine for the frozen Path-A plan.

This consumer reads caller-supplied, already materialized Cut-A selection captures, Cut-B scorecard comparisons,
Cut-C decision diffs, and future outcome values.  It never fetches or writes a capture/outcome, and it cannot
create, replay, backfill, or count any earlier week as forward evidence.  The sole threshold authority is the
validated Cut-D manifest loaded by :mod:`engine.us_short_forward_policy_statistical_plan`.

The caller keeps ticker-bearing inputs outside tracked output.  This module returns only a closed-world,
de-identified summary of counts, flags, aggregate gate statistics, and review-only verdicts.  It does not change
the primary selection, a ship gate, a lifecycle ledger, or the deferred execution-off second wave.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
from pathlib import Path
import random

import jsonschema

from engine import us_short_forward_policy_statistical_plan as statistical_plan
from engine.us_short_forward_policy_decision_diff import (
    ForwardPolicyDecisionDiffError,
    build_forward_policy_decision_diff_log,
    validate_forward_policy_decision_diff_log,
)
from engine.us_short_forward_policy_heads import SELECTION_POLICY_IDS
from engine.us_short_forward_policy_shadow_stage import (
    ForwardPolicyShadowStageError,
    validate_forward_shadow_selection_record,
)
from engine.us_short_paper_scorecard_comparison import (
    ScorecardComparisonError,
    validate_policy_scorecard_comparison,
)


ROOT = Path(__file__).resolve().parent.parent
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_statistical_evaluation_summary.schema.json"

BOUNDARY = {
    "track": "comparison_non_production",
    "evidence_level": "forward_policy_statistical_calibration_only",
    "shadow_counts_ship_gate": False,
    "full_size_ship_gate_allowed": False,
    "changes_primary_selection": False,
    "provider_calls_added": False,
    "broker_or_order_automation_allowed": False,
    "historical_replay_is_forward": False,
    "writes_outcome_data": False,
    "produces_forward_evidence": False,
}
_WEEK_KEYS = frozenset({
    "capture", "decision_diff", "scorecard_comparison", "outcome_as_of",
    "candidate_after_cost_net_return", "outcome_metric", "outcome_basis", "forward_evidence",
})
_FORWARD_EVIDENCE = {
    "recording_mode": "same_run_live_capture_only",
    "historical_replay_counts_as_forward": False,
    "backfill_allowed": False,
}
_OUTCOME_METRIC = "policy_minus_balanced_after_cost_net_return"
_OUTCOME_BASIS = "same_decision_week_h10_after_cost_common_pool"
_SUMMARY_KEYS = frozenset({
    "schema_name", "schema_version", "as_of", "evaluated_decision_week_count", "selection_policies",
    "primary_policy", "policy_verdicts", "boundary",
})
_VERDICT_KEYS = frozenset({"divergence_week_count", "review_flags", "outcome_gate", "verdict"})
_REVIEW_FLAG_KEYS = frozenset({"futility", "harm_turnover", "harm_fill"})
_OUTCOME_GATE_KEYS = frozenset({
    "evaluated", "mean_paired_advantage", "paired_win_count", "paired_win_fraction",
    "placebo_95th_percentile", "gate_a_mean_advantage", "gate_b_paired_wins", "gate_c_placebo",
})


class ForwardPolicyStatisticalEvaluationError(ValueError):
    """Raised when a Cut-D-analysis input, evidence binding, or de-identified verdict is invalid."""


def _strict_yyyymmdd(value: object) -> bool:
    if not (type(value) is str and len(value) == 8 and value.isascii() and value.isdigit()):
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


def _capture_sha256(capture: dict) -> str:
    return hashlib.sha256(
        json.dumps(capture, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_summary_schema() -> dict:
    try:
        return json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyStatisticalEvaluationError("cannot load Cut-D-analysis summary schema") from exc


def _selection_sets(capture: dict, *, selection_count: int) -> dict[str, set[str]]:
    decisions = capture["selection_decisions"]
    selected = {}
    for policy_id in SELECTION_POLICY_IDS:
        admitted = decisions[policy_id]["admitted"]
        if len(admitted) != selection_count:
            raise ForwardPolicyStatisticalEvaluationError(
                "policy %r must retain the manifest fixed Top%d selection" % (policy_id, selection_count)
            )
        selected[policy_id] = set(admitted)
    return selected


def _candidate_values(record: dict, capture: dict, selections: dict[str, set[str]]) -> dict[str, float]:
    candidates = capture["common_selection_pool"]
    if not isinstance(candidates, list) or len(candidates) != len(set(candidates)) or any(
        type(ticker) is not str or not ticker for ticker in candidates
    ):
        raise ForwardPolicyStatisticalEvaluationError("Cut-A common selection pool must be a unique non-blank ticker list")
    candidate_set = set(candidates)
    if not candidate_set:
        raise ForwardPolicyStatisticalEvaluationError("Cut-D placebo requires the non-empty Pass2-clean common pool")
    for policy_id, selected in selections.items():
        if not selected <= candidate_set:
            raise ForwardPolicyStatisticalEvaluationError(
                "policy %r selected a ticker outside the Cut-A candidate pool" % (policy_id,)
            )
    values = record["candidate_after_cost_net_return"]
    if not isinstance(values, dict) or set(values) != candidate_set:
        raise ForwardPolicyStatisticalEvaluationError(
            "candidate_after_cost_net_return must cover exactly the Pass2-clean common pool"
        )
    if any(not _finite(value) for value in values.values()):
        raise ForwardPolicyStatisticalEvaluationError("candidate_after_cost_net_return values must be finite numeric")
    return {ticker: float(value) for ticker, value in values.items()}


def _validate_week(record: object, *, as_of: str, selection_count: int) -> dict:
    if not isinstance(record, dict) or set(record) != _WEEK_KEYS:
        raise ForwardPolicyStatisticalEvaluationError("weekly evidence must carry the exact Cut-D-analysis input keys")
    if record["outcome_metric"] != _OUTCOME_METRIC or record["outcome_basis"] != _OUTCOME_BASIS:
        raise ForwardPolicyStatisticalEvaluationError(
            "weekly outcome metric/basis is not the preregistered same-decision-week H10 direct after-cost return"
        )
    if record["forward_evidence"] != _FORWARD_EVIDENCE:
        raise ForwardPolicyStatisticalEvaluationError("weekly evidence may not be replayed, backfilled, or non-live-capture")
    if not _strict_yyyymmdd(record["outcome_as_of"]) or record["outcome_as_of"] > as_of:
        raise ForwardPolicyStatisticalEvaluationError("outcome_as_of must be a real date no later than the analysis as_of")

    capture = record["capture"]
    try:
        validate_forward_shadow_selection_record(capture)
    except ForwardPolicyShadowStageError as exc:
        raise ForwardPolicyStatisticalEvaluationError("invalid Cut-A capture: %s" % exc) from exc
    if capture["selection_policies"] != list(SELECTION_POLICY_IDS):
        raise ForwardPolicyStatisticalEvaluationError("Cut-A capture policy namespace drifted")
    if capture["decision_date"] >= record["outcome_as_of"]:
        raise ForwardPolicyStatisticalEvaluationError("outcome_as_of must follow the source decision date")

    decision_diff = record["decision_diff"]
    try:
        validate_forward_policy_decision_diff_log(decision_diff)
    except ForwardPolicyDecisionDiffError as exc:
        raise ForwardPolicyStatisticalEvaluationError("invalid Cut-C decision diff: %s" % exc) from exc
    expected_diff = build_forward_policy_decision_diff_log(capture)["private"]
    if decision_diff != expected_diff:
        raise ForwardPolicyStatisticalEvaluationError("Cut-C decision diff is not exactly derived from the supplied Cut-A capture")

    scorecard_comparison = record["scorecard_comparison"]
    try:
        validate_policy_scorecard_comparison(scorecard_comparison)
    except ScorecardComparisonError as exc:
        raise ForwardPolicyStatisticalEvaluationError("invalid Cut-B scorecard comparison: %s" % exc) from exc
    capture_binding = {
        "decision_date": capture["decision_date"],
        "source_context_sha256": capture["source_context_sha256"],
        "capture_sha256": _capture_sha256(capture),
    }
    if scorecard_comparison.get("capture_binding") != capture_binding:
        raise ForwardPolicyStatisticalEvaluationError("Cut-B scorecard comparison is not bound to the supplied Cut-A capture")
    if scorecard_comparison["as_of"] != capture["decision_date"] \
            or scorecard_comparison["source_context_sha256"] != capture["source_context_sha256"]:
        raise ForwardPolicyStatisticalEvaluationError("Cut-B scorecard comparison clock/source is stale relative to Cut-A")

    selections = _selection_sets(capture, selection_count=selection_count)
    for policy_id in SELECTION_POLICY_IDS:
        scorecard = scorecard_comparison["policies"][policy_id]
        if scorecard["selected_total"] != selection_count or scorecard["fully_resolved"] is not True:
            raise ForwardPolicyStatisticalEvaluationError(
                "policy %r scorecard must be fully resolved over the manifest fixed Top%d" % (policy_id, selection_count)
            )

    values = _candidate_values(record, capture, selections)
    balanced = selections[SELECTION_POLICY_IDS[0]]
    swap_counts, membership_symmetric_differences = {}, {}
    for policy_id in SELECTION_POLICY_IDS[1:]:
        block = decision_diff["diffs_vs_balanced"][policy_id]["counts"]
        balanced_only = block["balanced_only_count"]
        policy_only = block["policy_only_count"]
        if balanced_only != policy_only:
            raise ForwardPolicyStatisticalEvaluationError("Cut-C Top15 replacement counts must be symmetric")
        if balanced_only > len(set(values) - balanced):
            raise ForwardPolicyStatisticalEvaluationError("candidate pool cannot support the realized data-bound placebo swaps")
        swap_counts[policy_id] = balanced_only
        membership_symmetric_differences[policy_id] = block["top15_membership_changed_count"]

    return {
        "decision_date": capture["decision_date"],
        "outcome_as_of": record["outcome_as_of"],
        "selections": selections,
        "candidate_values": values,
        "scorecards": scorecard_comparison["policies"],
        "swap_counts": swap_counts,
        "membership_symmetric_differences": membership_symmetric_differences,
    }


def _turnover_rate(previous: set[str] | None, current: set[str], *, selection_count: int) -> float:
    if previous is None:
        return 0.0
    return len(current - previous) / selection_count


def _has_sustained(condition_by_week: list[bool], *, required_weeks: int) -> bool:
    consecutive = 0
    for condition in condition_by_week:
        consecutive = consecutive + 1 if condition else 0
        if consecutive >= required_weeks:
            return True
    return False


def _mean(values: list[float]) -> float:
    if not values:
        raise ForwardPolicyStatisticalEvaluationError("mean requires at least one value")
    return sum(values) / len(values)


def _basket_net_excess(values: dict[str, float], selected: set[str]) -> float:
    return _mean([values[ticker] for ticker in sorted(selected)])


def _placebo_95th_percentile(divergence_weeks: list[dict], *, policy_id: str, plan: dict) -> float:
    placebo = plan["statistics"]["placebo"]
    seed_start = placebo["seed_start"]
    seed_end = placebo["seed_end_inclusive"]
    replicates = placebo["replicates"]
    seeds = list(range(seed_start, seed_end + 1))
    if len(seeds) != replicates:
        raise ForwardPolicyStatisticalEvaluationError("manifest placebo seed span must equal its replicate count")
    null_means = []
    for seed in seeds:
        weekly_advantages = []
        for week in divergence_weeks:
            balanced = week["selections"][SELECTION_POLICY_IDS[0]]
            swaps = week["swap_counts"][policy_id]
            pool = set(week["candidate_values"])
            rng = random.Random("us-short-a1-cut-d|%d|%s|%s" % (seed, policy_id, week["decision_date"]))
            outgoing = set(rng.sample(sorted(balanced), swaps))
            incoming = set(rng.sample(sorted(pool - balanced), swaps))
            placebo_selection = (balanced - outgoing) | incoming
            weekly_advantages.append(
                _basket_net_excess(week["candidate_values"], placebo_selection)
                - _basket_net_excess(week["candidate_values"], balanced)
            )
        null_means.append(_mean(weekly_advantages))
    percentile = plan["statistics"]["elimination_rule"]["formal_recommendation_gate"]["placebo_percentile_exclusive_gt"]
    if not (0.0 < percentile <= 1.0):
        raise ForwardPolicyStatisticalEvaluationError("manifest placebo percentile is invalid")
    ordered = sorted(null_means)
    # Nearest-rank is deterministic and uses the manifest percentile directly (for 0.95 and 1,000: rank 950).
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _empty_outcome_gate() -> dict:
    return {
        "evaluated": False,
        "mean_paired_advantage": None,
        "paired_win_count": None,
        "paired_win_fraction": None,
        "placebo_95th_percentile": None,
        "gate_a_mean_advantage": None,
        "gate_b_paired_wins": None,
        "gate_c_placebo": None,
    }


def _evaluate_outcomes(divergence_weeks: list[dict], *, policy_id: str, plan: dict) -> dict:
    promotion_gate = plan["statistics"]["elimination_rule"]["formal_recommendation_gate"]
    advantages = []
    for week in divergence_weeks:
        values = week["candidate_values"]
        advantages.append(
            _basket_net_excess(values, week["selections"][policy_id])
            - _basket_net_excess(values, week["selections"][SELECTION_POLICY_IDS[0]])
        )
    mean_advantage = _mean(advantages)
    wins = sum(advantage >= 0.0 for advantage in advantages)
    wins_fraction = wins / len(advantages)
    placebo_95th = _placebo_95th_percentile(divergence_weeks, policy_id=policy_id, plan=plan)
    numerator, denominator = promotion_gate["paired_win_consistency_fraction"]
    return {
        "evaluated": True,
        "mean_paired_advantage": mean_advantage,
        "paired_win_count": wins,
        "paired_win_fraction": wins_fraction,
        "placebo_95th_percentile": placebo_95th,
        "gate_a_mean_advantage": mean_advantage >= plan["statistics"]["comparison_win_margin"],
        "gate_b_paired_wins": wins * denominator >= numerator * len(advantages),
        "gate_c_placebo": mean_advantage > placebo_95th,
    }


def _policy_flags(weeks: list[dict], *, policy_id: str, plan: dict) -> dict:
    elimination = plan["statistics"]["elimination_rule"]
    futility = elimination["futility"]
    harm = elimination["harm"]
    selection_count = plan["statistics"]["selection_divergence"]["selection_count"]
    first_window = weeks[:futility["within_first_decision_weeks"]]
    futility_flag = len(first_window) == futility["within_first_decision_weeks"] and sum(
        week["membership_symmetric_differences"][policy_id]
        >= plan["statistics"]["selection_divergence"]["membership_symmetric_difference_at_least"]
        for week in first_window
    ) < futility["minimum_divergence_weeks"]

    turnover_conditions, fill_conditions = [], []
    previous = {name: None for name in SELECTION_POLICY_IDS}
    for week in weeks:
        balanced_rate = _turnover_rate(
            previous[SELECTION_POLICY_IDS[0]], week["selections"][SELECTION_POLICY_IDS[0]], selection_count=selection_count,
        )
        policy_rate = _turnover_rate(previous[policy_id], week["selections"][policy_id], selection_count=selection_count)
        turnover_conditions.append(policy_rate > balanced_rate * harm["turnover"]["threshold_multiplier_vs_balanced"])
        fill_conditions.append(
            week["scorecards"][policy_id]["filled_count"]
            < harm["fill"]["threshold_fraction"] * week["scorecards"][SELECTION_POLICY_IDS[0]]["selected_total"]
        )
        for name in SELECTION_POLICY_IDS:
            previous[name] = week["selections"][name]

    return {
        "futility": futility_flag,
        "harm_turnover": _has_sustained(
            turnover_conditions, required_weeks=harm["turnover"]["sustained_decision_weeks"],
        ),
        "harm_fill": _has_sustained(
            fill_conditions, required_weeks=harm["fill"]["sustained_decision_weeks"],
        ),
    }


def _verdict_for_policy(weeks: list[dict], *, policy_id: str, plan: dict) -> dict:
    statistics = plan["statistics"]
    divergence_weeks = [
        week for week in weeks
        if week["membership_symmetric_differences"][policy_id]
        >= statistics["selection_divergence"]["membership_symmetric_difference_at_least"]
    ]
    flags = _policy_flags(weeks, policy_id=policy_id, plan=plan)
    if flags["harm_turnover"] or flags["harm_fill"]:
        verdict, outcome_gate = "diagnostic_harm_flag", _empty_outcome_gate()
    elif flags["futility"]:
        verdict, outcome_gate = "diagnostic_futility_flag", _empty_outcome_gate()
    elif len(divergence_weeks) < statistics["minimum_divergence_weeks_before_formal_recommendation"]:
        verdict, outcome_gate = "diagnostic_accumulating", _empty_outcome_gate()
    else:
        outcome_gate = _evaluate_outcomes(divergence_weeks, policy_id=policy_id, plan=plan)
        verdict = "diagnostic_pass_not_formal_recommendation" if all(
            outcome_gate[key] for key in (
                "gate_a_mean_advantage", "gate_b_paired_wins", "gate_c_placebo",
            )
        ) else "diagnostic_not_passed_not_formal_recommendation"
    return {
        "divergence_week_count": len(divergence_weeks),
        "review_flags": flags,
        "outcome_gate": outcome_gate,
        "verdict": verdict,
    }


def _validate_summary_with_plan(summary: object, *, plan: dict) -> None:
    if not isinstance(summary, dict) or set(summary) != _SUMMARY_KEYS:
        raise ForwardPolicyStatisticalEvaluationError("Cut-D-analysis summary key set drifted")
    try:
        jsonschema.validate(summary, _load_summary_schema())
    except jsonschema.ValidationError as exc:
        raise ForwardPolicyStatisticalEvaluationError("Cut-D-analysis summary schema rejected: %s" % exc.message) from exc
    if not _strict_yyyymmdd(summary["as_of"]) or summary["selection_policies"] != list(SELECTION_POLICY_IDS) \
            or summary["primary_policy"] != SELECTION_POLICY_IDS[0] or summary["boundary"] != BOUNDARY:
        raise ForwardPolicyStatisticalEvaluationError("Cut-D-analysis summary identity/boundary drifted")
    if not isinstance(summary["evaluated_decision_week_count"], int) \
            or isinstance(summary["evaluated_decision_week_count"], bool) \
            or summary["evaluated_decision_week_count"] < 0:
        raise ForwardPolicyStatisticalEvaluationError("Cut-D-analysis decision-week count is invalid")
    verdicts = summary["policy_verdicts"]
    if not isinstance(verdicts, dict) or tuple(verdicts) != SELECTION_POLICY_IDS[1:]:
        raise ForwardPolicyStatisticalEvaluationError("Cut-D-analysis summary must cover exactly the five shadow heads")
    minimum = plan["statistics"]["minimum_divergence_weeks_before_formal_recommendation"]
    for policy_id, block in verdicts.items():
        if not isinstance(block, dict) or set(block) != _VERDICT_KEYS:
            raise ForwardPolicyStatisticalEvaluationError("summary verdict block for %r is malformed" % (policy_id,))
        divergence = block["divergence_week_count"]
        if not isinstance(divergence, int) or isinstance(divergence, bool) or divergence < 0:
            raise ForwardPolicyStatisticalEvaluationError("summary divergence count for %r is invalid" % (policy_id,))
        flags, gate, verdict = block["review_flags"], block["outcome_gate"], block["verdict"]
        if not isinstance(flags, dict) or set(flags) != _REVIEW_FLAG_KEYS or any(type(value) is not bool for value in flags.values()):
            raise ForwardPolicyStatisticalEvaluationError("summary review flags for %r are malformed" % (policy_id,))
        if not isinstance(gate, dict) or set(gate) != _OUTCOME_GATE_KEYS or type(gate["evaluated"]) is not bool:
            raise ForwardPolicyStatisticalEvaluationError("summary outcome gate for %r is malformed" % (policy_id,))
        if gate["evaluated"] is False:
            if any(gate[key] is not None for key in _OUTCOME_GATE_KEYS - {"evaluated"}):
                raise ForwardPolicyStatisticalEvaluationError("outcome-blind summary for %r leaked outcome data" % (policy_id,))
            expected = "diagnostic_harm_flag" if flags["harm_turnover"] or flags["harm_fill"] else \
                "diagnostic_futility_flag" if flags["futility"] else "diagnostic_accumulating"
            if verdict != expected:
                raise ForwardPolicyStatisticalEvaluationError("outcome-blind verdict for %r is inconsistent" % (policy_id,))
        else:
            if divergence < minimum or any(flags.values()):
                raise ForwardPolicyStatisticalEvaluationError("outcome gate for %r was examined before a clean minimum" % (policy_id,))
            if not all(_finite(gate[key]) for key in (
                "mean_paired_advantage", "paired_win_fraction", "placebo_95th_percentile",
            )) or not isinstance(gate["paired_win_count"], int) or isinstance(gate["paired_win_count"], bool):
                raise ForwardPolicyStatisticalEvaluationError("summary outcome metrics for %r are invalid" % (policy_id,))
            if any(type(gate[key]) is not bool for key in (
                "gate_a_mean_advantage", "gate_b_paired_wins", "gate_c_placebo",
            )):
                raise ForwardPolicyStatisticalEvaluationError("summary outcome gate flags for %r are invalid" % (policy_id,))
            expected = "diagnostic_pass_not_formal_recommendation" if all(
                gate[key] for key in ("gate_a_mean_advantage", "gate_b_paired_wins", "gate_c_placebo")
            ) else "diagnostic_not_passed_not_formal_recommendation"
            if verdict != expected:
                raise ForwardPolicyStatisticalEvaluationError("summary promotion verdict for %r is inconsistent" % (policy_id,))


def validate_forward_policy_statistical_evaluation_summary(summary: object) -> None:
    """Validate a de-identified Cut-D-analysis verdict summary against the loaded manifest."""
    _validate_summary_with_plan(summary, plan=statistical_plan.load_forward_policy_statistical_plan())


def evaluate_forward_policy_statistical_evaluation(weekly_evidence: object, *, as_of: str) -> dict:
    """Apply the frozen Cut-D manifest to already supplied forward-week inputs.

    ``weekly_evidence`` is an ordered in-memory list.  Each item binds a validated Cut-A capture, its exact Cut-C
    decision diff, a capture-bound Cut-B scorecard comparison, and a complete candidate-pool map of same-week,
    H10 after-cost return values over the exact Pass2-clean common pool.  No caller-side input is persisted or
    mutated.  This blade only updates the legacy three-gate diagnostic to the v2 pool/24-week contract; the later
    v2 verdict blade adds the frozen non-overlap/regime/Holm/risk/family-winner gates before any user-facing advice.
    An empty list is a
    valid zero-real-week query and returns only diagnostic-accumulating, outcome-blind summaries.
    """
    plan = statistical_plan.load_forward_policy_statistical_plan()
    if not _strict_yyyymmdd(as_of):
        raise ForwardPolicyStatisticalEvaluationError("analysis as_of must be a strict real YYYYMMDD")
    if not isinstance(weekly_evidence, list):
        raise ForwardPolicyStatisticalEvaluationError("weekly_evidence must be an ordered list")
    selection_count = plan["statistics"]["selection_divergence"]["selection_count"]
    weeks = []
    previous_date = None
    for record in weekly_evidence:
        week = _validate_week(record, as_of=as_of, selection_count=selection_count)
        if previous_date is not None and week["decision_date"] <= previous_date:
            raise ForwardPolicyStatisticalEvaluationError("decision weeks must be strictly ordered and non-duplicate")
        previous_date = week["decision_date"]
        weeks.append(week)

    result = {
        "schema_name": "us_short_forward_policy_statistical_evaluation_summary",
        "schema_version": "2.0.0",
        "as_of": as_of,
        "evaluated_decision_week_count": len(weeks),
        "selection_policies": list(SELECTION_POLICY_IDS),
        "primary_policy": SELECTION_POLICY_IDS[0],
        "policy_verdicts": {
            policy_id: _verdict_for_policy(weeks, policy_id=policy_id, plan=plan)
            for policy_id in SELECTION_POLICY_IDS[1:]
        },
        "boundary": dict(BOUNDARY),
    }
    _validate_summary_with_plan(result, plan=plan)
    return result
