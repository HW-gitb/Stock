"""Offline Knife-2 adjudication for the private A-short v2 comparison ledger.

This module consumes only frozen v2 capture/outcome/source-receipt artifacts.
It never fetches, captures a week, changes production configuration, or wires
itself into the weekly pipeline.  Recommendations remain human-gated receipts.
"""
from __future__ import annotations

import copy
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any

from engine.a_short_factor_comparison_v2 import (
    ComparisonV2Error,
    PROGRAM_ID,
    SCHEMA_VERSION,
    _atomic_write,
    _boundary,
    _digest,
    _load_json,
    _load_experiment_batches,
    _private_root,
    _validate_source_receipt,
    load_v2_governance,
    validate_v2_decision_receipt,
    validate_v2_governance,
    validate_v2_ledger,
    validate_v2_weekly_record,
)
from engine import a_short_evidence_epoch_mode as _epoch_mode


ADJUDICATION_PATH = "adjudication.json"
RECEIPTS_PATH = "decision_receipts.json"
REMINDER_PATH = "reminder.json"
PRIMARY_HORIZON = "h10"


def _comparison_contract_sha256(governance: dict) -> str:
    return _digest({
        "adjudication_contract": governance["adjudication_contract"],
        "formal_checkpoints": governance["formal_adjudication_contract"],
        "questions": [{
            "question_id": question["question_id"],
            "experiment_batch_id": question["experiment_batch_id"],
            "multiplicity_family_id": question["multiplicity_family_id"],
            "ordered_arm_ids": question["ordered_arm_ids"],
        } for question in governance["questions"]],
    })


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sample_variance(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = _mean(values)
    assert mean is not None
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _bootstrap_mean_ci(values: list[float], *, draws: int, confidence: float, label: str) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    seed = int(_digest({"kind": "v2_bootstrap", "label": label, "values": values, "draws": draws,
                        "confidence": confidence})[:16], 16)
    rng = random.Random(seed)
    count = len(values)
    samples = sorted(sum(values[rng.randrange(count)] for _ in range(count)) / count for _ in range(draws))
    tail = (1.0 - confidence) / 2.0
    lower_index = max(0, min(len(samples) - 1, math.floor(tail * len(samples))))
    upper_index = max(0, min(len(samples) - 1, math.ceil((1.0 - tail) * len(samples)) - 1))
    return samples[lower_index], samples[upper_index]


def _sign_flip_two_sided_pvalue(values: list[float], *, draws: int) -> float | None:
    """Deterministic exact sign-flip through 16 blocks, seeded simulation above it."""
    if not values:
        return None
    observed = abs(sum(values) / len(values))
    if observed <= 1e-12:
        return 1.0
    count = len(values)
    if count <= 16:
        total, extreme = 1 << count, 0
        for mask in range(total):
            signed = sum(value if (mask >> index) & 1 else -value for index, value in enumerate(values)) / count
            if abs(signed) >= observed - 1e-12:
                extreme += 1
        return extreme / total
    seed = int(_digest({"kind": "v2_sign_flip", "values": values, "draws": draws})[:16], 16)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(draws):
        signed = sum(value if rng.getrandbits(1) else -value for value in values) / count
        if abs(signed) >= observed - 1e-12:
            extreme += 1
    return (extreme + 1) / (draws + 1)


def _one_sided_sign_test(values: list[float]) -> float | None:
    nonzero = [value for value in values if abs(value) > 1e-12]
    if not nonzero:
        return None
    wins, count = sum(value > 0 for value in nonzero), len(nonzero)
    return sum(math.comb(count, value) for value in range(wins, count + 1)) / (2 ** count)


def _holm_bonferroni(pvalues: dict[str, float | None]) -> dict[str, float | None]:
    """Adjust only the declared challengers inside one question family."""
    ordered = sorted((1.0 if value is None else float(value), arm_id) for arm_id, value in pvalues.items())
    adjusted = {arm_id: None for arm_id in pvalues}
    running = 0.0
    for index, (pvalue, arm_id) in enumerate(ordered):
        current = min(1.0, pvalue * (len(ordered) - index))
        running = max(running, current)
        if pvalues[arm_id] is not None:
            adjusted[arm_id] = running
    return adjusted


def _nonoverlap_blocks(rows: list[dict]) -> list[dict]:
    """Retain H10 pairs whose decision date starts after the preceding paired exit."""
    chosen: list[dict] = []
    prior_exit: str | None = None
    for row in sorted(rows, key=lambda item: item["decision_date"]):
        exit_date = row.get("evaluation_exit_date")
        if not isinstance(exit_date, str) or not exit_date:
            continue
        if prior_exit is None or row["decision_date"] > prior_exit:
            chosen.append(row)
            prior_exit = exit_date
    return chosen


def _t_critical_975(degrees_of_freedom: int) -> float:
    # Hartung-Knapp intervals have only a few epoch estimates in normal use.
    table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
             7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
             13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
             19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042}
    if degrees_of_freedom <= 1:
        return table[1]
    if degrees_of_freedom in table:
        return table[degrees_of_freedom]
    if degrees_of_freedom < 25:
        return table[20]
    if degrees_of_freedom < 30:
        return table[25]
    return table[30]


def _reml_tau_squared(means: list[float], variances: list[float]) -> float:
    """One-dimensional restricted-likelihood optimisation for epoch random effects."""
    if len(means) < 2:
        return 0.0
    upper = max(1e-12, max(variances) + max((left - right) ** 2 for left in means for right in means))

    def objective(tau_squared: float) -> float:
        weights = [1.0 / max(1e-12, variance + tau_squared) for variance in variances]
        weighted_mean = sum(weight * value for weight, value in zip(weights, means)) / sum(weights)
        return 0.5 * (sum(math.log(variance + tau_squared) for variance in variances) +
                      math.log(sum(weights)) +
                      sum(weight * (value - weighted_mean) ** 2 for weight, value in zip(weights, means)))

    left, right = 0.0, upper
    for _ in range(72):
        one = left + (right - left) / 3.0
        two = right - (right - left) / 3.0
        if objective(one) <= objective(two):
            right = two
        else:
            left = one
    return max(0.0, (left + right) / 2.0)


def _epoch_meta(blocks: list[dict], *, contract: dict) -> dict:
    values = [float(row["effect_pct"]) for row in blocks]
    variance = _sample_variance(values)
    return {
        "block_count": len(blocks),
        "mean_effect_pct": _mean(values),
        "sampling_variance": (variance / len(values)) if variance is not None and values else None,
        "qualified_for_cross_epoch": len(blocks) >= int(contract["min_epoch_blocks"]),
    }


def _cross_epoch_summary(blocks: list[dict], *, current_epoch_id: str, contract: dict) -> dict:
    grouped: dict[str, list[dict]] = {}
    for block in blocks:
        grouped.setdefault(block["epoch_id"], []).append(block)
    summaries = {epoch_id: _epoch_meta(epoch_blocks, contract=contract)
                 for epoch_id, epoch_blocks in sorted(grouped.items())}
    eligible = [(epoch_id, summary) for epoch_id, summary in summaries.items()
                if summary["qualified_for_cross_epoch"]]
    current = summaries.get(current_epoch_id)
    current_qualified = bool(current and current["qualified_for_cross_epoch"])
    current_mean = current.get("mean_effect_pct") if current else None
    current_harm = bool(current_qualified and current_mean is not None and
                        current_mean < -float(contract["min_economic_advantage_pct"]))
    current_direction_consistent = bool(current_qualified and current_mean is not None and current_mean > 0.0)
    if not eligible:
        return {"method": "insufficient_epoch_blocks", "epochs": summaries, "mean_effect_pct": None,
                "ci_lower_pct": None, "ci_upper_pct": None, "tau_squared": None,
                "heterogeneity_i2_pct": None, "direction_conflict": False,
                "current_epoch_qualified": current_qualified,
                "current_epoch_direction_consistent": current_direction_consistent,
                "current_epoch_harm": current_harm}
    if len(eligible) == 1:
        epoch_id, summary = eligible[0]
        values = [float(row["effect_pct"]) for row in grouped[epoch_id]]
        lower, upper = _bootstrap_mean_ci(values, draws=int(contract["bootstrap_draws"]),
                                           confidence=float(contract["confidence_level"]), label=f"epoch:{epoch_id}")
        return {"method": "single_epoch_blocks", "epochs": summaries,
                "mean_effect_pct": summary["mean_effect_pct"], "ci_lower_pct": lower, "ci_upper_pct": upper,
                "tau_squared": 0.0, "heterogeneity_i2_pct": 0.0, "direction_conflict": False,
                "current_epoch_qualified": current_qualified,
                "current_epoch_direction_consistent": current_direction_consistent,
                "current_epoch_harm": current_harm}
    means = [float(summary["mean_effect_pct"]) for _, summary in eligible]
    variances = [max(1e-12, float(summary["sampling_variance"] or 0.0)) for _, summary in eligible]
    tau_squared = _reml_tau_squared(means, variances)
    weights = [1.0 / (variance + tau_squared) for variance in variances]
    pooled = sum(weight * mean for weight, mean in zip(weights, means)) / sum(weights)
    degrees = len(eligible) - 1
    q = sum(weight * (mean - pooled) ** 2 for weight, mean in zip(weights, means))
    hk_scale = q / degrees if degrees else 1.0
    standard_error = math.sqrt(max(0.0, hk_scale / sum(weights)))
    critical = _t_critical_975(degrees)
    directions = {1 if mean > 1e-12 else -1 if mean < -1e-12 else 0 for mean in means}
    return {"method": "random_effects_reml_hartung_knapp", "epochs": summaries,
            "mean_effect_pct": pooled, "ci_lower_pct": pooled - critical * standard_error,
            "ci_upper_pct": pooled + critical * standard_error, "tau_squared": tau_squared,
            "heterogeneity_i2_pct": max(0.0, (q - degrees) / q * 100.0) if q > 0 else 0.0,
            "direction_conflict": 1 in directions and -1 in directions,
            "current_epoch_qualified": current_qualified,
            "current_epoch_direction_consistent": current_direction_consistent,
            "current_epoch_harm": current_harm}


def _state_label(capture: dict) -> str | None:
    labels = {str(row.get("market_regime") or "") for row in capture["payload"]["candidate_universe"]}
    labels.discard("")
    return f"market_regime:{next(iter(labels))}" if len(labels) == 1 else None


def _question_and_arms(capture: dict, outcome: dict, question_id: str) -> tuple[dict, dict]:
    capture_question = next((row for row in capture["payload"]["questions"] if row["question_id"] == question_id), None)
    outcome_question = next((row for row in outcome["payload"]["questions"] if row["question_id"] == question_id), None)
    if not isinstance(capture_question, dict) or not isinstance(outcome_question, dict):
        raise ComparisonV2Error(f"v2 adjudication missing question {question_id}")
    capture_ids = [row["arm_definition"]["arm_id"] for row in capture_question["arms"]]
    outcome_ids = [row["arm_id"] for row in outcome_question.get("arms") or []]
    if outcome_question["status"] == "settled" and capture_ids != outcome_ids:
        raise ComparisonV2Error(f"v2 adjudication arm identity drift for {question_id}")
    return capture_question, outcome_question


def _outcome_payload_digest(payload: dict) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("outcome_sha256"), str):
        raise ComparisonV2Error("v2 adjudication outcome payload digest is malformed")
    return _digest({key: value for key, value in payload.items() if key != "outcome_sha256"})


def _collect_evidence(root: Path, governance: dict, active_batch_ids: dict[str, str]) -> dict[str, dict]:
    ledger_path = root / "ledger.json"
    if not ledger_path.exists():
        raise ComparisonV2Error("v2 adjudication requires a private ledger")
    ledger = _load_json(ledger_path)
    validate_v2_ledger(ledger)
    configured = {row["question_id"]: row for row in governance["questions"]}
    collected = {question_id: {"experiment_batch_id": active_batch_ids[question_id],
                              "rows_by_arm": {arm["arm_id"]: [] for arm in question["arms"] if arm["kind"] == "challenger"},
                              "terminal_by_arm": {arm["arm_id"]: 0 for arm in question["arms"]},
                              "no_count_by_arm": {arm["arm_id"]: 0 for arm in question["arms"]},
                              "latest_epoch_id": None}
                 for question_id, question in configured.items()}
    for entry in sorted(ledger["entries"], key=lambda row: (row["decision_date"], row["question_id"])):
        question_id = entry["question_id"]
        if question_id not in configured or not entry["forward_eligible"] or \
                entry["experiment_batch_id"] != active_batch_ids[question_id]:
            continue
        day = root / "weeks" / entry["decision_date"]
        capture_path, outcome_path, receipt_path = day / "capture.json", day / "outcome.json", day / "source_receipt.json"
        if not capture_path.exists() or not outcome_path.exists() or not receipt_path.exists():
            raise ComparisonV2Error(f"{entry['decision_date']}: ledger points to incomplete v2 evidence")
        capture, outcome, receipt = _load_json(capture_path), _load_json(outcome_path), _load_json(receipt_path)
        _validate_source_receipt(root, capture, receipt)
        validate_v2_weekly_record(outcome)
        outcome_digest = _outcome_payload_digest(outcome["payload"])
        if entry["capture_sha256"] != capture["payload"]["capture_sha256"] or \
                outcome["payload"]["outcome_sha256"] != outcome_digest or entry["outcome_sha256"] != outcome_digest:
            raise ComparisonV2Error(f"{entry['decision_date']}: ledger source hash drift")
        capture_question, outcome_question = _question_and_arms(capture, outcome, question_id)
        if capture_question.get("experiment_batch_id") != entry["experiment_batch_id"]:
            raise ComparisonV2Error(f"{entry['decision_date']}: ledger experiment batch does not match capture")
        bucket = collected[question_id]
        bucket["latest_epoch_id"] = entry["epoch_id"]
        if outcome_question["status"] not in {"settled", "no_count"}:
            continue
        capture_arms = {row["arm_definition"]["arm_id"]: row for row in capture_question["arms"]}
        outcome_arms = {row["arm_id"]: row for row in outcome_question.get("arms") or []}
        for arm_id in capture_arms:
            bucket["terminal_by_arm"][arm_id] += 1
            if outcome_question["status"] == "no_count":
                bucket["no_count_by_arm"][arm_id] += 1
        if outcome_question["status"] != "settled":
            continue
        baseline_capture = capture_arms.get("baseline")
        baseline_outcome = outcome_arms.get("baseline")
        if not isinstance(baseline_capture, dict) or not isinstance(baseline_outcome, dict):
            raise ComparisonV2Error(f"{entry['decision_date']}: settled question lost baseline")
        baseline_horizon = baseline_outcome["outcome"]["horizons"].get(PRIMARY_HORIZON)
        if not isinstance(baseline_horizon, dict) or baseline_horizon.get("status") != "settled":
            raise ComparisonV2Error(f"{entry['decision_date']}: settled baseline lacks H10")
        for arm_id, arm_capture in capture_arms.items():
            if arm_id == "baseline":
                continue
            arm_outcome = outcome_arms.get(arm_id)
            if not isinstance(arm_outcome, dict):
                raise ComparisonV2Error(f"{entry['decision_date']}: settled challenger missing outcome")
            horizon = arm_outcome["outcome"]["horizons"].get(PRIMARY_HORIZON)
            if not isinstance(horizon, dict) or horizon.get("status") != "settled":
                raise ComparisonV2Error(f"{entry['decision_date']}: settled challenger lacks H10")
            if arm_capture["selected_symbols"] == baseline_capture["selected_symbols"] and \
                    arm_capture["decisions"] == baseline_capture["decisions"]:
                continue
            exit_date = max(str(baseline_horizon.get("evaluation_exit_date") or baseline_horizon.get("exit_date") or ""),
                            str(horizon.get("evaluation_exit_date") or horizon.get("exit_date") or ""))
            if not exit_date:
                raise ComparisonV2Error(f"{entry['decision_date']}: H10 exit date is absent")
            bucket["rows_by_arm"][arm_id].append({
                "decision_date": entry["decision_date"], "evaluation_exit_date": exit_date,
                "epoch_id": entry["epoch_id"], "state": _state_label(capture),
                "effect_pct": float(horizon["net_return_pct"]) - float(baseline_horizon["net_return_pct"]),
                "risk_evidence": copy.deepcopy(arm_outcome["outcome"]["risk_evidence"]),
                "baseline_risk_evidence": copy.deepcopy(baseline_outcome["outcome"]["risk_evidence"]),
                "arm_definition_sha256": arm_capture["arm_definition_sha256"],
            })
    return collected


def _risk_gate(rows: list[dict], *, no_count_rate: float | None, contract: dict) -> dict:
    limits = contract["risk_limits"]
    results: dict[str, dict] = {}
    for field, limit in limits.items():
        if field == "no_count_rate":
            values = [] if no_count_rate is None else [no_count_rate]
        else:
            values = [row["risk_evidence"].get(field) for row in rows]
        if not values or any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value))
                             for value in values):
            results[field] = {"value": None, "limit": limit, "passed": False}
            continue
        value = max(float(item) for item in values) if "maximum" in limit else min(float(item) for item in values)
        passed = value <= float(limit["maximum"]) if "maximum" in limit else value >= float(limit["minimum"])
        results[field] = {"value": value, "limit": limit, "passed": passed}
    basis_ok = all(row["risk_evidence"].get("loss_distribution_basis") == "filled_positions_only" for row in rows)
    results["loss_distribution_basis"] = {"value": "filled_positions_only" if basis_ok else None,
                                           "passed": basis_ok}
    return {"passed": all(item["passed"] for item in results.values()), "metrics": results}


def _risk_worsened(rows: list[dict], *, contract: dict) -> bool:
    for field, limit in contract["risk_limits"].items():
        if field == "no_count_rate":
            continue
        candidate = [row["risk_evidence"].get(field) for row in rows]
        baseline = [row["baseline_risk_evidence"].get(field) for row in rows]
        if not candidate or any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in candidate + baseline):
            return True
        if "maximum" in limit and max(candidate) > max(baseline) + 1e-12:
            return True
        if "minimum" in limit and min(candidate) < min(baseline) - 1e-12:
            return True
    return False


def _arm_statistics(rows: list[dict], *, checkpoint: int | None, current_epoch_id: str | None, contract: dict,
                    adjusted_pvalue: float | None, no_count_rate: float | None) -> dict:
    analysis_rows = rows if checkpoint is None else sorted(rows, key=lambda row: row["decision_date"])[:checkpoint]
    blocks = _nonoverlap_blocks(analysis_rows)
    block_values = [float(row["effect_pct"]) for row in blocks]
    mean_effect = _mean([float(row["effect_pct"]) for row in analysis_rows])
    block_mean = _mean(block_values)
    ci_lower, ci_upper = _bootstrap_mean_ci(block_values, draws=int(contract["bootstrap_draws"]),
                                             confidence=float(contract["confidence_level"]), label="arm")
    state_counts: dict[str, int] = {}
    state_effects: dict[str, list[float]] = {}
    for row in analysis_rows:
        state = row.get("state")
        if state:
            state_counts[state] = state_counts.get(state, 0) + 1
            state_effects.setdefault(state, []).append(float(row["effect_pct"]))
    state_means = {state: _mean(values) for state, values in state_effects.items()}
    direction_conflict = any(float(value or 0.0) > 1e-12 for value in state_means.values()) and \
                         any(float(value or 0.0) < -1e-12 for value in state_means.values())
    half = len(block_values) // 2
    first_half, second_half = (_mean(block_values[:half]) if half else None,
                               _mean(block_values[half:]) if half else None)
    temporal_conflict = first_half is not None and second_half is not None and first_half * second_half < 0.0
    cross_epoch = _cross_epoch_summary(blocks, current_epoch_id=current_epoch_id or "", contract=contract)
    risk = _risk_gate(analysis_rows, no_count_rate=no_count_rate, contract=contract)
    has_state_coverage = len([state for state, count in state_counts.items()
                              if count >= int(contract["min_state_effective_weeks"])]) >= int(contract["min_distinct_states"])
    statistical_pass = (len(analysis_rows) >= int(contract["min_effective_weeks_formal"]) and
                        len(block_values) >= int(contract["min_nonoverlap_blocks"]) and
                        block_mean is not None and block_mean >= float(contract["min_economic_advantage_pct"]) and
                        sum(value > 0 for value in block_values) / len(block_values) >= float(contract["min_block_win_rate"]) and
                        ci_lower is not None and ci_lower >= float(contract["min_economic_advantage_pct"]) and adjusted_pvalue is not None and
                        adjusted_pvalue <= float(contract["alpha_spending"][str(checkpoint)]) and
                        cross_epoch["mean_effect_pct"] is not None and cross_epoch["ci_lower_pct"] is not None and
                        cross_epoch["ci_lower_pct"] > 0.0 and
                        float(cross_epoch["heterogeneity_i2_pct"] or 0.0) <= float(contract["max_heterogeneity_i2_pct"]) and
                        not cross_epoch["direction_conflict"] and cross_epoch["current_epoch_qualified"] and
                        cross_epoch["current_epoch_direction_consistent"] and not cross_epoch["current_epoch_harm"] and
                        has_state_coverage and not direction_conflict and not temporal_conflict and risk["passed"])
    reliable_harm = (len(analysis_rows) >= int(contract["retire_after_effective_weeks"]) and
                     len(block_values) >= int(contract["min_nonoverlap_blocks"]) and block_mean is not None and
                     block_mean <= -float(contract["min_economic_advantage_pct"]) and ci_upper is not None and
                     ci_upper < 0.0 and adjusted_pvalue is not None and
                     adjusted_pvalue <= float(contract["alpha_spending"][str(checkpoint)]) and
                     _risk_worsened(analysis_rows, contract=contract))
    return {
        "effective_difference_weeks": len(rows), "analysis_effective_weeks": len(analysis_rows),
        "nonoverlap_blocks": len(block_values), "mean_paired_net_excess_pct": mean_effect,
        "nonoverlap_mean_paired_net_excess_pct": block_mean,
        "nonoverlap_block_win_rate": (sum(value > 0 for value in block_values) / len(block_values)
                                       if block_values else None),
        "paired_bootstrap_ci": {"confidence_level": contract["confidence_level"], "lower_pct": ci_lower,
                                  "upper_pct": ci_upper},
        "paired_sign_flip_two_sided_pvalue": _sign_flip_two_sided_pvalue(block_values,
                                                                            draws=int(contract["permutation_draws"])),
        "holm_bonferroni_adjusted_pvalue": adjusted_pvalue,
        "sign_test_one_sided_pvalue": _one_sided_sign_test(block_values),
        "state_effective_weeks": state_counts, "state_mean_effect_pct": state_means,
        "temporal_direction_conflict": temporal_conflict, "state_direction_conflict": direction_conflict,
        "cross_epoch": cross_epoch, "risk_gate": risk, "eligible_for_adopt": statistical_pass,
        "reliable_harm": reliable_harm, "blocks": blocks,
    }


def _simultaneous_winner(eligible: list[str], rows_by_arm: dict[str, list[dict]], *, checkpoint: int,
                         contract: dict) -> tuple[str | None, dict[str, dict]]:
    if len(eligible) <= 1:
        return (eligible[0] if eligible else None), {}
    comparisons = len(eligible) - 1
    confidence = 1.0 - (1.0 - float(contract["simultaneous_confidence_level"])) / comparisons
    details: dict[str, dict] = {}
    winners: list[str] = []
    for contender in eligible:
        contender_rows = {row["decision_date"]: row for row in rows_by_arm[contender][:checkpoint]}
        pairwise: dict[str, dict] = {}
        passes = True
        for opponent in eligible:
            if opponent == contender:
                continue
            opponent_rows = {row["decision_date"]: row for row in rows_by_arm[opponent][:checkpoint]}
            common = []
            for decision_date in sorted(set(contender_rows) & set(opponent_rows)):
                left, right = contender_rows[decision_date], opponent_rows[decision_date]
                common.append({"decision_date": decision_date,
                               "evaluation_exit_date": max(left["evaluation_exit_date"], right["evaluation_exit_date"]),
                               "effect_pct": float(left["effect_pct"]) - float(right["effect_pct"])})
            values = [float(row["effect_pct"]) for row in _nonoverlap_blocks(common)]
            lower, upper = _bootstrap_mean_ci(values, draws=int(contract["bootstrap_draws"]), confidence=confidence,
                                               label=f"finalist:{contender}:{opponent}")
            passed = (len(values) >= int(contract["min_nonoverlap_blocks"]) and lower is not None and
                      lower >= float(contract["min_economic_advantage_pct"]))
            pairwise[opponent] = {"common_nonoverlap_blocks": len(values), "mean_difference_pct": _mean(values),
                                  "simultaneous_confidence_level": confidence, "lower_pct": lower,
                                  "upper_pct": upper, "passed": passed}
            passes = passes and passed
        details[contender] = pairwise
        if passes:
            winners.append(contender)
    return (winners[0] if len(winners) == 1 else None), details


def _formal_checkpoint(effective_weeks: int, contract: dict) -> int | None:
    if effective_weeks >= int(contract["retire_after_effective_weeks"]):
        return int(contract["retire_after_effective_weeks"])
    if effective_weeks >= int(contract["min_effective_weeks_formal"]):
        return int(contract["min_effective_weeks_formal"])
    return None


def _prior_formal_status(previous: dict | None, question_id: str, experiment_batch_id: str, checkpoint: int) -> str | None:
    if not isinstance(previous, dict):
        return None
    for question in previous.get("questions") or []:
        if question.get("question_id") != question_id or question.get("experiment_batch_id") != experiment_batch_id:
            continue
        for entry in question.get("formal_history") or []:
            if entry.get("checkpoint_effective_weeks") == checkpoint:
                return entry.get("status")
    return None


def _question_adjudication(question: dict, evidence: dict, *, governance: dict, previous: dict | None,
                           experiment_batch_id: str) -> dict:
    contract = dict(governance["adjudication_contract"])
    contract["alpha_spending"] = governance["formal_adjudication_contract"]["alpha_spending"]
    rows_by_arm = {arm_id: sorted(rows, key=lambda row: row["decision_date"])
                   for arm_id, rows in evidence["rows_by_arm"].items()}
    effective_by_arm = {arm_id: len(rows) for arm_id, rows in rows_by_arm.items()}
    effective_weeks = min(effective_by_arm.values(), default=0)
    no_count_rates = {arm_id: (evidence["no_count_by_arm"][arm_id] / evidence["terminal_by_arm"][arm_id]
                               if evidence["terminal_by_arm"][arm_id] else None)
                      for arm_id in evidence["terminal_by_arm"]}
    if not _epoch_mode.evidence_counts_toward_clock("p0_factor_comparison_v2"):
        return {"question_id": question["question_id"], "experiment_batch_id": experiment_batch_id,
                "status": "continue_accumulation", "formal_checkpoint_effective_weeks": None,
                "effective_difference_weeks": effective_weeks, "arm_verdicts": [], "finalist_comparisons": {},
                "recommendations": [], "no_count_rate_by_arm": no_count_rates, "formal_history": []}
    checkpoint = _formal_checkpoint(effective_weeks, contract)
    if checkpoint is None:
        status = "continue_accumulation" if effective_weeks < int(contract["min_effective_weeks_preliminary"]) else "preliminary_review_due"
        return {"question_id": question["question_id"], "experiment_batch_id": experiment_batch_id,
                "status": status, "formal_checkpoint_effective_weeks": None,
                "effective_difference_weeks": effective_weeks, "arm_verdicts": [], "finalist_comparisons": {},
                "recommendations": [], "no_count_rate_by_arm": no_count_rates, "formal_history": []}
    analysis_rows_by_arm = {arm_id: rows[:checkpoint] for arm_id, rows in rows_by_arm.items()}
    raw_pvalues = {arm_id: _sign_flip_two_sided_pvalue(
        [float(row["effect_pct"]) for row in _nonoverlap_blocks(rows)], draws=int(contract["permutation_draws"]))
        for arm_id, rows in analysis_rows_by_arm.items()}
    adjusted = _holm_bonferroni(raw_pvalues)
    arm_verdicts = []
    for arm_id in question["ordered_arm_ids"]:
        if arm_id == "baseline":
            continue
        stats = _arm_statistics(rows_by_arm[arm_id], checkpoint=checkpoint,
                                current_epoch_id=evidence["latest_epoch_id"], contract=contract,
                                adjusted_pvalue=adjusted[arm_id], no_count_rate=no_count_rates[arm_id])
        arm_verdicts.append({"arm_id": arm_id, **{key: value for key, value in stats.items() if key != "blocks"}})
    eligible = [row["arm_id"] for row in arm_verdicts if row["eligible_for_adopt"]]
    winner, finalist = _simultaneous_winner(eligible, analysis_rows_by_arm, checkpoint=checkpoint, contract=contract)
    conflicts = any(row["temporal_direction_conflict"] or row["state_direction_conflict"] or
                    row["cross_epoch"]["direction_conflict"] or
                    (row["cross_epoch"]["heterogeneity_i2_pct"] is not None and
                     row["cross_epoch"]["heterogeneity_i2_pct"] > float(contract["max_heterogeneity_i2_pct"]))
                    for row in arm_verdicts)
    harms = [row["arm_id"] for row in arm_verdicts if row["reliable_harm"]]
    recommendations: list[dict] = []
    if winner:
        status = "recommend_adopt_arm"
        recommendations.append({"arm_id": winner, "status": status})
    elif checkpoint == int(contract["retire_after_effective_weeks"]) and harms:
        status = "recommend_discard_arm"
        recommendations.extend({"arm_id": arm_id, "status": status} for arm_id in harms)
    elif checkpoint == int(contract["retire_after_effective_weeks"]) and not conflicts:
        status = "recommend_retain_baseline"
        recommendations.append({"arm_id": "baseline", "status": status})
    elif checkpoint == int(contract["retire_after_effective_weeks"]) and \
            _prior_formal_status(previous, question["question_id"], experiment_batch_id,
                                 int(contract["min_effective_weeks_formal"])) == "inconclusive":
        status = "dormant_inconclusive"
    else:
        status = "inconclusive"
    prior_history = []
    if isinstance(previous, dict):
        prior = next((row for row in previous.get("questions") or []
                      if row.get("question_id") == question["question_id"] and
                      row.get("experiment_batch_id") == experiment_batch_id), None)
        prior_history = copy.deepcopy((prior or {}).get("formal_history") or [])
    history_entry = {"checkpoint_effective_weeks": checkpoint, "status": status}
    formal_history = [row for row in prior_history if row.get("checkpoint_effective_weeks") != checkpoint] + [history_entry]
    return {"question_id": question["question_id"], "experiment_batch_id": experiment_batch_id,
            "status": status, "formal_checkpoint_effective_weeks": checkpoint,
            "effective_difference_weeks": effective_weeks, "arm_verdicts": arm_verdicts,
            "finalist_comparisons": finalist, "recommendations": recommendations,
            "no_count_rate_by_arm": no_count_rates, "formal_history": formal_history}


def _validate_adjudication(payload: dict, governance: dict) -> None:
    required = {"schema_name", "schema_version", "program_id", "stage", "comparison_contract_sha256", "questions",
                "queue", "combination_scheduler", "reactivation_requests", "boundary"}
    if set(payload) != required or payload.get("schema_name") != "a_short_factor_comparison_v2_adjudication" or \
            payload.get("schema_version") != SCHEMA_VERSION or payload.get("program_id") != PROGRAM_ID or \
            payload.get("stage") != "knife_2_offline_adjudication":
        raise ComparisonV2Error("v2 adjudication payload identity drifted")
    if payload["boundary"] != _boundary(governance) or any(payload["boundary"].values()):
        raise ComparisonV2Error("v2 adjudication crossed the comparison-only boundary")
    if payload["comparison_contract_sha256"] != _comparison_contract_sha256(governance):
        raise ComparisonV2Error("v2 adjudication comparison contract drifted")
    expected = [row["question_id"] for row in governance["questions"]]
    if [row.get("question_id") for row in payload["questions"]] != expected:
        raise ComparisonV2Error("v2 adjudication question ordering drifted")
    if any(not isinstance(row.get("experiment_batch_id"), str) or not row["experiment_batch_id"]
           for row in payload["questions"]):
        raise ComparisonV2Error("v2 adjudication question batch identity drifted")


def _receipt_collection(root: Path) -> dict:
    path = root / RECEIPTS_PATH
    if not path.exists():
        return {"schema_name": "a_short_factor_comparison_v2_decision_receipts", "schema_version": SCHEMA_VERSION,
                "program_id": PROGRAM_ID, "receipts": [], "boundary": {"production": False,
                "automatic_policy_switch": False}}
    payload = _load_json(path)
    required = {"schema_name", "schema_version", "program_id", "receipts", "boundary"}
    if set(payload) != required or payload["schema_name"] != "a_short_factor_comparison_v2_decision_receipts" or \
            payload["schema_version"] != SCHEMA_VERSION or payload["program_id"] != PROGRAM_ID or \
            payload["boundary"] != {"production": False, "automatic_policy_switch": False}:
        raise ComparisonV2Error("v2 decision receipt collection drifted")
    seen = set()
    for row in payload["receipts"]:
        if set(row) != {"receipt_sha256", "receipt"} or row["receipt_sha256"] in seen or \
                row["receipt_sha256"] != row["receipt"].get("verdict_sha256"):
            raise ComparisonV2Error("v2 decision receipt collection is malformed")
        seen.add(row["receipt_sha256"])
        validate_v2_decision_receipt(row["receipt"])
    return payload


def _build_receipts(root: Path, adjudication: dict, evidence: dict, governance: dict) -> dict:
    collection = _receipt_collection(root)
    existing = {row["receipt_sha256"]: row for row in collection["receipts"]}
    for question_result in adjudication["questions"]:
        question = next(row for row in governance["questions"] if row["question_id"] == question_result["question_id"])
        for recommendation in question_result["recommendations"]:
            arm_id = recommendation["arm_id"]
            if arm_id == "baseline":
                arm_digest = _digest({"baseline": question["question_id"],
                                      "batch": question_result["experiment_batch_id"]})
            else:
                rows = evidence[question["question_id"]]["rows_by_arm"][arm_id]
                arm_digest = rows[-1]["arm_definition_sha256"] if rows else _digest({"arm": arm_id})
            verdict = {"question_id": question["question_id"], "arm_id": arm_id, "status": recommendation["status"],
                       "formal_checkpoint_effective_weeks": question_result["formal_checkpoint_effective_weeks"],
                       "experiment_batch_id": question_result["experiment_batch_id"],
                       "comparison_contract_sha256": _comparison_contract_sha256(governance),
                       "arm_definition_sha256": arm_digest}
            receipt = {"schema_name": "a_short_factor_comparison_v2_decision_receipt", "schema_version": SCHEMA_VERSION,
                       "program_id": PROGRAM_ID, "question_id": question["question_id"], "arm_id": arm_id,
                       "epoch_id": evidence[question["question_id"]]["latest_epoch_id"],
                       "experiment_batch_id": question_result["experiment_batch_id"], "verdict_sha256": _digest(verdict),
                       "comparison_contract_sha256": verdict["comparison_contract_sha256"],
                       "arm_definition_sha256": arm_digest, "status": "pending", "decision": None,
                       "decided_at": None, "boundary": {"production": False, "automatic_policy_switch": False}}
            validate_v2_decision_receipt(receipt)
            receipt_sha = receipt["verdict_sha256"]
            existing.setdefault(receipt_sha, {"receipt_sha256": receipt_sha, "receipt": receipt})
            recommendation["receipt_sha256"] = receipt_sha
    return {"schema_name": "a_short_factor_comparison_v2_decision_receipts", "schema_version": SCHEMA_VERSION,
            "program_id": PROGRAM_ID, "receipts": [existing[key] for key in sorted(existing)],
            "boundary": {"production": False, "automatic_policy_switch": False}}


def _reminder(adjudication: dict, receipts: dict) -> dict:
    current = {recommendation["receipt_sha256"]: recommendation["status"]
               for result in adjudication["questions"] for recommendation in result["recommendations"]
               if isinstance(recommendation.get("receipt_sha256"), str)}
    reminders = []
    for row in receipts["receipts"]:
        receipt = row["receipt"]
        if receipt["status"] == "pending" and row["receipt_sha256"] in current:
            reminders.append({"question_id": receipt["question_id"], "arm_id": receipt["arm_id"],
                              "receipt_sha256": row["receipt_sha256"], "status": current[row["receipt_sha256"]],
                              "message": "Comparison decision requires user receipt; production remains unchanged."})
    return {"schema_name": "a_short_factor_comparison_v2_reminder", "schema_version": SCHEMA_VERSION,
            "program_id": PROGRAM_ID, "reminders": reminders, "production_unchanged": True}


def _combination_scheduler(adjudication: dict, receipts: dict, batches: dict | None = None) -> dict:
    accepted = {row["receipt"]["question_id"] for row in receipts["receipts"]
                if row["receipt"]["status"] == "accepted"}
    adopted = {result["question_id"] for result in adjudication["questions"]
               if result["status"] == "recommend_adopt_arm"}
    eligible = sorted(accepted & adopted)
    batch = None
    if batches is not None and len(eligible) >= 2:
        batch = next((row for row in batches.get("combination_batches", [])
                      if row.get("component_question_ids") == eligible), None)
    return {"status": "dormant_requires_new_forward_batch" if len(eligible) >= 2 else "not_eligible",
            "accepted_distinct_question_ids": eligible, "new_forward_batch_required": len(eligible) >= 2,
            "historical_backfill_forbidden": True,
            "combination_experiment_batch_id": batch.get("experiment_batch_id") if batch else None,
            "pre_registered_combination_question_required": len(eligible) >= 2,
            "production_unchanged": True}


def _register_combination_batch(adjudication: dict, receipts: dict, batches: dict) -> None:
    scheduler = _combination_scheduler(adjudication, receipts)
    component_ids = scheduler["accepted_distinct_question_ids"]
    if len(component_ids) < 2:
        return
    if any(row.get("component_question_ids") == component_ids for row in batches["combination_batches"]):
        return
    accepted_components = [
        {"question_id": row["receipt"]["question_id"], "arm_id": row["receipt"]["arm_id"],
         "receipt_sha256": row["receipt_sha256"]}
        for row in receipts["receipts"]
        if row["receipt"]["status"] == "accepted" and row["receipt"]["question_id"] in component_ids
    ]
    accepted_components.sort(key=lambda row: (row["question_id"], row["arm_id"], row["receipt_sha256"]))
    accepted_receipts = [row["receipt_sha256"] for row in accepted_components]
    batches["combination_batches"].append({
        "experiment_batch_id": "batch_" + _digest({
            "component_question_ids": component_ids,
            "accepted_components": accepted_components,
            "comparison_contract_sha256": adjudication["comparison_contract_sha256"],
        })[:16],
        "component_question_ids": component_ids,
        "accepted_components": accepted_components,
        "accepted_receipt_sha256s": accepted_receipts,
        "new_forward_evidence_required": True,
        "historical_backfill_forbidden": True,
        "pre_registered_combination_question_required": True,
    })


def adjudicate_v2_from_private_ledger(*, root: str | Path, governance: dict | None = None) -> dict:
    """Evaluate frozen private evidence only; no capture, provider call, weekly wiring or policy switch."""
    root = _private_root(root)
    governance = copy.deepcopy(governance or load_v2_governance())
    validate_v2_governance(governance)
    if not root.exists():
        return {"status": "no_v2_comparison_root", "production_unchanged": True}
    prior_path = root / ADJUDICATION_PATH
    prior = _load_json(prior_path) if prior_path.exists() else None
    if prior is not None:
        if prior.get("comparison_contract_sha256") != _comparison_contract_sha256(governance):
            # A separately pre-registered combination question changes the statistical question set.
            # The old summary/receipts stay historical but cannot control the new run.
            prior = None
        else:
            _validate_adjudication(prior, governance)
    batches = _load_experiment_batches(root, governance)
    active_batch_ids = {row["question_id"]: row["active_experiment_batch_id"] for row in batches["questions"]}
    for request in (prior or {}).get("reactivation_requests") or []:
        question_id, new_batch_id = request.get("question_id"), request.get("new_experiment_batch_id")
        if not isinstance(question_id, str) or not isinstance(new_batch_id, str) or \
                active_batch_ids.get(question_id) != new_batch_id:
            raise ComparisonV2Error("v2 reactivation batch registry no longer matches its recorded request")
    evidence = _collect_evidence(root, governance, active_batch_ids)
    questions = [_question_adjudication(question, evidence[question["question_id"]], governance=governance,
                                        previous=prior, experiment_batch_id=active_batch_ids[question["question_id"]])
                 for question in governance["questions"]]
    previous_requests = copy.deepcopy((prior or {}).get("reactivation_requests") or [])
    requested_ids = {row.get("question_id") for row in previous_requests}
    active = [row["question_id"] for row in questions if row["status"] != "dormant_inconclusive"]
    queued = [row["question_id"] for row in questions if row["status"] == "dormant_inconclusive" and
              row["question_id"] in requested_ids]
    queue = {"max_active_questions": governance["adjudication_contract"]["max_active_questions"],
             "active_question_ids": active, "queued_question_ids": queued,
             "released_slots": governance["adjudication_contract"]["max_active_questions"] - len(active),
             "outcome_blind_priority_only": True}
    adjudication = {"schema_name": "a_short_factor_comparison_v2_adjudication", "schema_version": SCHEMA_VERSION,
                    "program_id": PROGRAM_ID, "stage": "knife_2_offline_adjudication",
                    "comparison_contract_sha256": _comparison_contract_sha256(governance),
                    "questions": questions, "queue": queue, "combination_scheduler": {},
                    "reactivation_requests": previous_requests,
                    "boundary": _boundary(governance)}
    _validate_adjudication(adjudication, governance)
    receipts = _build_receipts(root, adjudication, evidence, governance)
    adjudication["combination_scheduler"] = _combination_scheduler(adjudication, receipts, batches)
    _validate_adjudication(adjudication, governance)
    reminder = _reminder(adjudication, receipts)
    ledger_path = root / "ledger.json"
    ledger = _load_json(ledger_path)
    validate_v2_ledger(ledger)
    ledger["stage"] = "adjudication"
    ledger["adjudication"] = {"comparison_contract_sha256": adjudication["comparison_contract_sha256"],
                               "question_statuses": {row["question_id"]: row["status"] for row in questions}}
    validate_v2_ledger(ledger)
    _atomic_write(root / ADJUDICATION_PATH, adjudication)
    _atomic_write(root / RECEIPTS_PATH, receipts)
    _atomic_write(root / REMINDER_PATH, reminder)
    _atomic_write(ledger_path, ledger)
    return {"status": "adjudicated_private_v2", "adjudication": adjudication, "reminder": reminder,
            "production_unchanged": True}


def decide_v2_receipt(*, root: str | Path, receipt_sha256: str, decision: str,
                      governance: dict | None = None) -> dict:
    """Record an explicit user receipt only when it binds the current adjudication summary."""
    root = _private_root(root)
    if decision not in {"accepted", "rejected", "deferred"}:
        raise ComparisonV2Error("v2 receipt decision must be accepted, rejected or deferred")
    adjudication_path = root / ADJUDICATION_PATH
    if not adjudication_path.exists():
        raise ComparisonV2Error("v2 receipt decision requires current adjudication")
    governance = copy.deepcopy(governance or load_v2_governance())
    validate_v2_governance(governance)
    adjudication = _load_json(adjudication_path)
    _validate_adjudication(adjudication, governance)
    collection = _receipt_collection(root)
    for row in collection["receipts"]:
        if row["receipt_sha256"] != receipt_sha256:
            continue
        receipt = row["receipt"]
        current = any(result["question_id"] == receipt["question_id"] and
                      any(recommendation.get("receipt_sha256") == receipt_sha256
                          for recommendation in result["recommendations"])
                      for result in adjudication["questions"])
        if not current or receipt["status"] != "pending":
            raise ComparisonV2Error("v2 receipt is stale or already decided")
        receipt["status"] = decision
        receipt["decision"] = decision
        receipt["decided_at"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        validate_v2_decision_receipt(receipt)
        row["receipt"] = receipt
        collection["receipts"] = sorted(collection["receipts"], key=lambda item: item["receipt_sha256"])
        _atomic_write(root / RECEIPTS_PATH, collection)
        reminder = _reminder(adjudication, collection)
        batches = _load_experiment_batches(root, governance)
        _register_combination_batch(adjudication, collection, batches)
        adjudication["combination_scheduler"] = _combination_scheduler(adjudication, collection, batches)
        _validate_adjudication(adjudication, governance)
        _atomic_write(root / "experiment_batches.json", batches)
        _atomic_write(root / ADJUDICATION_PATH, adjudication)
        _atomic_write(root / REMINDER_PATH, reminder)
        return {"status": "receipt_recorded", "receipt_sha256": receipt_sha256, "decision": decision,
                "production_unchanged": True}
    raise ComparisonV2Error("v2 receipt sha256 is unknown")


def request_v2_question_reactivation(*, root: str | Path, question_id: str, reason: str,
                                    governance: dict | None = None) -> dict:
    """Record a human-requested dormant-question reactivation without creating a retroactive batch."""
    root = _private_root(root)
    if not isinstance(reason, str) or not reason.strip():
        raise ComparisonV2Error("v2 reactivation requires a nonblank human reason")
    governance = copy.deepcopy(governance or load_v2_governance())
    validate_v2_governance(governance)
    path = root / ADJUDICATION_PATH
    if not path.exists():
        raise ComparisonV2Error("v2 reactivation requires current adjudication")
    adjudication = _load_json(path)
    _validate_adjudication(adjudication, governance)
    question = next((row for row in adjudication["questions"] if row["question_id"] == question_id), None)
    if not isinstance(question, dict) or question["status"] != "dormant_inconclusive":
        raise ComparisonV2Error("only a dormant v2 question may request reactivation")
    existing = next((row for row in adjudication["reactivation_requests"] if row.get("question_id") == question_id), None)
    batches = _load_experiment_batches(root, governance)
    batch_row = next(row for row in batches["questions"] if row["question_id"] == question_id)
    if existing is None:
        old_batch_id = batch_row["active_experiment_batch_id"]
        new_batch_id = "batch_" + _digest({
            "question_id": question_id,
            "replaces": old_batch_id,
            "reason": reason.strip(),
            "comparison_contract_sha256": adjudication["comparison_contract_sha256"],
            "reactivation_count": len(batch_row["prior_experiment_batch_ids"]),
        })[:16]
        batch_row["prior_experiment_batch_ids"].append(old_batch_id)
        batch_row["active_experiment_batch_id"] = new_batch_id
        batch_row["activation_kind"] = "dormant_reactivation"
        adjudication["reactivation_requests"].append({
            "question_id": question_id, "reason": reason.strip(),
            "comparison_contract_sha256": adjudication["comparison_contract_sha256"],
            "requested_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "prior_experiment_batch_id": old_batch_id,
            "new_experiment_batch_id": new_batch_id,
            "new_forward_batch_required": True, "historical_backfill_forbidden": True,
        })
    else:
        new_batch_id = existing.get("new_experiment_batch_id")
        if not isinstance(new_batch_id, str) or batch_row["active_experiment_batch_id"] != new_batch_id:
            raise ComparisonV2Error("v2 dormant reactivation batch registry drifted")
    queue = adjudication["queue"]
    if question_id not in queue["queued_question_ids"]:
        queue["queued_question_ids"].append(question_id)
        queue["queued_question_ids"].sort()
    _validate_adjudication(adjudication, governance)
    _atomic_write(root / "experiment_batches.json", batches)
    _atomic_write(path, adjudication)
    return {"status": "reactivation_recorded_new_forward_batch_required", "question_id": question_id,
            "experiment_batch_id": new_batch_id,
            "production_unchanged": True}
