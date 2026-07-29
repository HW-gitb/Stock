"""Comparison-only P2 target-exit adjudication.

All decision thresholds arrive from the sealed admission registry.  This
module is deliberately outside the P2 accumulator's fingerprint closure.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _max_drawdown(values: list[float]) -> float:
    total = peak = 0.0
    worst = 0.0
    for value in values:
        total += value
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return worst


def adjudicate_target_exit(records: list[dict[str, Any]], statistical_contract: dict[str, Any], *,
                           evidence_counts: bool) -> dict[str, Any]:
    """Return an auditable target-exit verdict without changing production."""
    minimums = statistical_contract["minimums"]
    required = ("forward_weeks", "difference_weeks", "evaluable_plans",
                "mean_net_improvement_pp_min", "favorable_week_ratio_min",
                "max_drawdown_worsening_pp_max")
    if any(key not in minimums and key not in statistical_contract for key in required) or statistical_contract.get("primary_window") != "h20" or \
            statistical_contract.get("weekly_median") != ">0" or \
            statistical_contract.get("h5_h10_not_both_materially_adverse") is not True:
        raise ValueError("target_adjudication_contract_invalid")
    forward = [row for row in records if row.get("forward_eligible") is True]
    differing = [row for row in forward if row.get("target_difference") is True]
    weekly: dict[str, list[tuple[float, float, float]]] = {}
    for row in differing:
        values = weekly.setdefault(str(row.get("decision_date") or ""), [])
        for entry in row.get("target_entries") or []:
            outcome = entry.get("outcomes") or {}
            base, challenger = outcome.get("baseline") or {}, outcome.get("challenger") or {}
            delta = _finite(outcome.get("net_delta_pct"))
            h5 = _finite(((challenger.get("diagnostics") or {}).get("h5") or {}).get("net_return_pct"))
            h5_base = _finite(((base.get("diagnostics") or {}).get("h5") or {}).get("net_return_pct"))
            h10 = _finite(((challenger.get("diagnostics") or {}).get("h10") or {}).get("net_return_pct"))
            h10_base = _finite(((base.get("diagnostics") or {}).get("h10") or {}).get("net_return_pct"))
            if entry.get("changed") is True and outcome.get("status") == "settled" and None not in (delta, h5, h5_base, h10, h10_base):
                values.append((delta, h5 - h5_base, h10 - h10_base))
    week_values = [values for _date, values in sorted(weekly.items()) if values]
    deltas = [sum(item[0] for item in values) / len(values) for values in week_values]
    h5_deltas = [sum(item[1] for item in values) / len(values) for values in week_values]
    h10_deltas = [sum(item[2] for item in values) / len(values) for values in week_values]
    progress = {"forward_weeks": len(forward), "difference_weeks": len(differing),
                "evaluable_plans": sum(len(values) for values in week_values),
                "evaluable_weeks": len(deltas)}
    enough = evidence_counts and progress["forward_weeks"] >= minimums["forward_weeks"] and \
        progress["difference_weeks"] >= minimums["difference_weeks"] and \
        progress["evaluable_plans"] >= minimums["evaluable_plans"]
    metrics = {"mean_net_improvement_pp": (sum(deltas) / len(deltas)) if deltas else None,
               "weekly_median_net_improvement_pp": median(deltas) if deltas else None,
               "favorable_week_ratio": (sum(value > 0 for value in deltas) / len(deltas)) if deltas else None,
               "max_drawdown_worsening_pp": _max_drawdown(deltas) if deltas else None,
               "h5_mean_delta_pp": (sum(h5_deltas) / len(h5_deltas)) if h5_deltas else None,
               "h10_mean_delta_pp": (sum(h10_deltas) / len(h10_deltas)) if h10_deltas else None}
    if not enough:
        return {"verdict": "not_adjudicated", "progress": progress, "metrics": metrics,
                "reason": "minimum_evidence_not_met", "comparison_only": True}
    positive = metrics["mean_net_improvement_pp"] >= statistical_contract["mean_net_improvement_pp_min"] and \
        metrics["weekly_median_net_improvement_pp"] > 0 and \
        metrics["favorable_week_ratio"] >= statistical_contract["favorable_week_ratio_min"] and \
        metrics["max_drawdown_worsening_pp"] <= statistical_contract["max_drawdown_worsening_pp_max"] and \
        not (metrics["h5_mean_delta_pp"] < 0 and metrics["h10_mean_delta_pp"] < 0)
    return {"verdict": "edge_positive" if positive else "edge_not_supported", "progress": progress,
            "metrics": metrics, "reason": "all_formal_gates_pass" if positive else "formal_gate_not_met",
            "comparison_only": True}
