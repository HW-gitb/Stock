"""Pure, comparison-only P5b industry-weight adjudication.

All numeric policy comes from the P5 governance payload.  This module is
intentionally outside the P5 capture/settlement fingerprint closure.
"""
from __future__ import annotations

import math
from statistics import mean
from collections.abc import Callable
from typing import Any

from engine.a_short_overlay_adjudication import _signflip_p

P5B_IMPLEMENTED = True


def _finite(value: object) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _blocks(rows: list[dict]) -> list[dict]:
    """Use only decision dates strictly after the prior h10 exit."""
    result, prior_exit = [], None
    for row in sorted(rows, key=lambda item: item["decision_date"]):
        exit_date = row.get("exit_date")
        if not isinstance(exit_date, str):
            continue
        if prior_exit is None or row["decision_date"] > prior_exit:
            result.append(row)
            prior_exit = exit_date
    return result


def holm_bonferroni(p_values: dict[str, float | None], alpha: float) -> set[str]:
    """Return the step-down Holm rejection set; missing p-values never reject."""
    ordered = sorted(((name, value) for name, value in p_values.items() if value is not None),
                     key=lambda item: item[1])
    rejected: set[str] = set()
    total = len(p_values)
    for index, (name, value) in enumerate(ordered):
        if value <= alpha / (total - index):
            rejected.add(name)
        else:
            break
    return rejected


def _risk(rows: list[dict], mature: int, no_count: int, policy: dict) -> dict:
    tickets, drawdowns, drawdown_worsenings = [], [], []
    invalid_ticket = False
    for row in rows:
        for ticket in row.get("challenger_ticket_returns") or []:
            value = _finite(ticket)
            if value is None:
                invalid_ticket = True
            else:
                tickets.append(value)
        drawdown = _finite(row.get("challenger_close_drawdown_pct"))
        if drawdown is not None:
            drawdowns.append(drawdown)
        worsening = _finite(row.get("relative_close_drawdown_worsening_pct"))
        if worsening is not None:
            drawdown_worsenings.append(worsening)
    no_count_rate = (no_count / mature * 100.0) if mature else None
    bad = [value for value in tickets if value <= policy["bad_ticket_h10_threshold_pct"]]
    bad_rate = (len(bad) / len(tickets) * 100.0) if tickets else None
    tail = min(tickets) if tickets else None
    worst_drawdown_worsening = max(drawdown_worsenings, default=None)
    worst_drawdown = max(drawdowns, default=None)
    adjustment_coverage = (len(rows) / mature * 100.0) if mature else None
    return {
        "no_count_rate_pct": no_count_rate,
        "bad_ticket_h10_rate_pct": bad_rate,
        "tail_h10_pct": tail,
        "max_relative_drawdown_worsening_pct": worst_drawdown_worsening,
        "max_close_drawdown_pct": worst_drawdown,
        "adjustment_coverage_pct": adjustment_coverage,
        "risk_ok": all((
            no_count_rate is not None and no_count_rate <= policy["no_count_rate_max_pct"],
            bad_rate is not None and bad_rate <= policy["bad_ticket_h10_max_pct"],
            tail is not None and tail >= policy["tail_loss_h10_min_pct"],
            worst_drawdown is not None and worst_drawdown <= policy["max_drawdown_close_based_max_pct"],
            worst_drawdown_worsening is not None and worst_drawdown_worsening <= policy["max_relative_drawdown_worsening_pct"],
            adjustment_coverage is not None and adjustment_coverage >= policy["adjustment_coverage_required_pct"],
            not invalid_ticket,
        )),
    }


def adjudicate_question(rows: list[dict], *, mature: int, no_count: int, governance: dict,
                        question: dict, holm_rejected: set[str],
                        p_value_function: Callable[[list[float]], float | None] = _signflip_p) -> dict[str, Any]:
    """Adjudicate one question; insufficient checkpoint separation always wins."""
    clock, policy = governance["clock_contract"], governance["risk_and_statistics_contract"]
    checkpoints, minimums = clock["checkpoints"], clock["difference_minimums"]
    stages = question["p5b_adjudication_governance"]["checkpoint_stages"]
    if not (len(checkpoints) == len(minimums) == 3 and all(isinstance(x, int) and x > 0 for x in checkpoints)):
        raise ValueError("p5b_clock_contract_invalid")
    reached = max((index for index, checkpoint in enumerate(checkpoints) if len(rows) >= checkpoint), default=None)
    checkpoint_stage = "not_reached" if reached is None else stages[str(checkpoints[reached])]
    invalid_effect = any(_finite(row.get("effect_pct")) is None for row in rows)
    values = [_finite(row["effect_pct"]) for row in rows if _finite(row.get("effect_pct")) is not None]
    difference = sum(row["same_list"] is False for row in rows)
    blocks = _blocks(rows)
    block_values = [_finite(row["effect_pct"]) for row in blocks if _finite(row.get("effect_pct")) is not None]
    p_value = p_value_function(block_values)
    metrics = {
        "eligible_policy_weeks": len(rows), "difference_weeks": difference,
        "nonoverlap_blocks": len(blocks), "mean_effect_pct": mean(values) if values else None,
        "block_win_rate_pct": (sum(value > 0 for value in block_values) / len(block_values) * 100.0) if block_values else None,
        "signflip_p_value": p_value, **_risk(rows, mature, no_count, policy),
    }
    if invalid_effect:
        verdict, reason = "continue_accumulating", "nonfinite_effect_evidence"
    elif not question["evidence_counts"]:
        verdict, reason = "continue_accumulating", "pre_freeze_audit_only"
    else:
        if reached is None:
            verdict, reason = "continue_accumulating", "checkpoint_not_reached"
        elif difference < minimums[reached]:
            verdict, reason = "continue_accumulating", "insufficient_policy_separation"
        else:
            positive_preliminary = metrics["mean_effect_pct"] >= policy["preliminary_mean_effect_pct"] and \
                metrics["block_win_rate_pct"] >= policy["preliminary_block_win_rate_pct"] and metrics["risk_ok"]
            if reached == 0:
                verdict, reason = (question["positive_permission"], "preliminary_gates_pass") if positive_preliminary else \
                    (question["negative_permission"], "preliminary_gates_not_met")
            elif positive_preliminary and question["question_id"] in holm_rejected:
                verdict, reason = question["positive_permission"], "formal_holm_and_risk_gates_pass"
            elif reached == 2:
                verdict, reason = question["negative_permission"], "terminal_gates_not_met"
            else:
                verdict, reason = "continue_accumulating", "formal_gates_not_met"
    return {"question_id": question["question_id"], "verdict": verdict, "reason": reason,
            "checkpoint_stage": checkpoint_stage,
            "progress": {"eligible_policy_weeks": len(rows), "difference_weeks": difference,
                         "mature_opportunities": mature, "no_count_weeks": no_count,
                         "remaining_eligible_weeks": max(0, checkpoints[0] - len(rows)),
                         "remaining_difference_weeks": max(0, minimums[0] - difference)},
            "metrics": metrics, "comparison_only": True}
