"""Pure P3 HAC adjudication; never changes production configuration."""
from __future__ import annotations

import math
from statistics import median
from typing import Any

from engine.a_short_experiment_admission_registry import get_admission


class FinalActionAdjudicationError(ValueError):
    """The sealed P3 statistical contract or evidence is malformed."""


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise FinalActionAdjudicationError("P3 adjudication evidence is malformed")
    return float(value)


def _contract() -> dict[str, Any]:
    definition = get_admission("p3_managed_exit_vs_hold")["statistical_contract"]["definition"]
    try:
        hac, minimums, operation = definition["hac"], definition["minimums"], definition["operation"]
        if (hac["method"] != "newey_west" or type(hac["maxlags"]) is not int or hac["maxlags"] < 0
                or _number(hac["t_min"]) <= 0 or type(minimums["full_edge_forward_weeks"]) is not int
                or type(minimums["mature_managed_plans"]) is not int
                or minimums["full_edge_forward_weeks"] <= 0 or minimums["mature_managed_plans"] <= 0
                or _number(operation["mean_improvement_pp_min"]) <= 0 or operation["median"] != ">0"
                or not 0 < _number(operation["favorable_week_ratio_min"]) <= 1
                or _number(operation["max_drawdown_worsening_pp_max"]) < 0):
            raise ValueError
    except (KeyError, TypeError, ValueError, FinalActionAdjudicationError) as exc:
        raise FinalActionAdjudicationError("P3 statistical contract is malformed") from exc
    return definition


def _hac_t(values: list[float], maxlags: int) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    centered = [value - mean for value in values]
    lag = min(maxlags, len(values) - 1)
    long_run_variance = sum(value * value for value in centered) / len(values)
    for index in range(1, lag + 1):
        covariance = sum(centered[pos] * centered[pos - index] for pos in range(index, len(values))) / len(values)
        long_run_variance += 2 * (1 - index / (lag + 1)) * covariance
    if long_run_variance <= 0:
        return None
    return mean / math.sqrt(long_run_variance / len(values))


def adjudicate_full_edge(rows: list[dict[str, Any]], *, evidence_counts: bool) -> dict[str, Any]:
    """Return the only P3 public verdict; incomplete risk evidence is not adjudicated."""
    contract = _contract(); hac = contract["hac"]; minimums = contract["minimums"]; operation = contract["operation"]
    effects = [_number(row.get("managed_minus_simple_hold_pct")) for row in rows]
    plan_counts = [_number(row.get("managed_plan_count")) for row in rows]
    if any(value < 0 or not value.is_integer() for value in plan_counts):
        raise FinalActionAdjudicationError("P3 managed-plan evidence is malformed")
    plans = sum(int(value) for value in plan_counts)
    progress = {"full_edge_forward_weeks": len(rows), "mature_managed_plans": plans,
                "required_full_edge_forward_weeks": minimums["full_edge_forward_weeks"],
                "required_mature_managed_plans": minimums["mature_managed_plans"]}
    if (not contract.get("formal_hac_adjudication_implemented")
            or not evidence_counts or len(rows) < minimums["full_edge_forward_weeks"]
            or plans < minimums["mature_managed_plans"]):
        return {"verdict": "not_adjudicated", "progress": progress, "reason": "evidence_not_due"}
    try:
        worsening = [_number(row["drawdown_worsening_pct"]) for row in rows]
    except (KeyError, FinalActionAdjudicationError):
        return {"verdict": "not_adjudicated", "progress": progress, "reason": "drawdown_evidence_unavailable"}
    hac_t = _hac_t(effects, hac["maxlags"])
    gates = {"mean": sum(effects) / len(effects) >= _number(operation["mean_improvement_pp_min"]),
             "median": median(effects) > 0,
             "favorable_ratio": sum(value > 0 for value in effects) / len(effects) >= _number(operation["favorable_week_ratio_min"]),
             "hac_t": hac_t is not None and hac_t >= _number(hac["t_min"]),
             "drawdown": max(worsening) <= _number(operation["max_drawdown_worsening_pp_max"])}
    progress.update({"hac_t": hac_t, "gates": gates})
    return {"verdict": "preliminary_edge_positive" if all(gates.values()) else "edge_not_proven",
            "progress": progress, "reason": "all_gates_pass" if all(gates.values()) else "gate_not_met"}
