"""§4c-only, read-only ON/OFF soft-boost comparison adjudication.

K4b receipts remain immutable one-week captures.  This module consumes a separate
source-bound pairwise ledger once maturity receipts exist; it cannot fetch data,
alter K4b, alter production, or change a route automatically.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import statistics
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
PAIRWISE_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_pairwise_ledger.schema.json"
ADJUDICATION_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_adjudication_receipt.schema.json"
MATURITY_OBSERVATION_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_maturity_observation.schema.json"
PLAN_PATH = ROOT / "presets" / "us_short_soft_boost_statistical_plan_20260727.json"
PLAN_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_statistical_plan.schema.json"


class SoftBoostComparisonAdjudicationError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(value: Any, schema: Path) -> None:
    jsonschema.validate(value, _load(schema))


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_statistical_plan() -> tuple[dict[str, Any], str]:
    plan = _load(PLAN_PATH)
    _validate(plan, PLAN_SCHEMA)
    return plan, _canonical_sha256(plan)


def _eligible(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record["divergent"] and record["matured"] and record["eligible"]]


_METRIC_KEYS = (
    "on_net_return", "off_net_return", "on_max_drawdown", "off_max_drawdown",
    "on_bad_pick_rate", "off_bad_pick_rate", "on_tail_loss", "off_tail_loss",
    "on_turnover", "off_turnover", "on_fill_fraction", "off_fill_fraction",
)

# Offline paper evidence has no execution simulator or partial-fill source.  The
# receipt must retain the structural fact (1.0), but it is deliberately retired
# from ``passed``: a structural constant is not evidence that a risk gate passed.
STRUCTURAL_DECISION_INPUT_EXEMPTIONS = {
    "on_fill_fraction": "Offline paper H10 has no partial-fill model; this structural 1.0 is retained for lineage, not evaluated.",
    "off_fill_fraction": "Offline paper H10 has no partial-fill model; this structural 1.0 is retained for lineage, not evaluated.",
}


def build_pairwise_capture(*, decision_date: str, consumption_receipt_sha256: str,
                           shadow_receipt_sha256: str, divergent: bool,
                           market_risk_regime: str = "unknown") -> dict[str, Any]:
    """Create one immutable-at-capture record; maturity is filled only by a later bound observation."""
    return {
        "decision_date": decision_date, "consumption_receipt_sha256": consumption_receipt_sha256,
        "shadow_receipt_sha256": shadow_receipt_sha256, "maturity_receipt_sha256": None,
        "market_risk_regime": market_risk_regime, "divergent": divergent, "matured": False,
        "eligible": False, "non_overlap_h10_block": False,
        **{key: None for key in _METRIC_KEYS},
    }


def append_pairwise_capture(previous: object | None, capture: dict[str, Any]) -> dict[str, Any]:
    """Append exactly the current decision capture; duplicate/reordered capture is fail-closed."""
    records: list[dict[str, Any]] = []
    if previous is not None:
        _validate(previous, PAIRWISE_SCHEMA)
        records = [dict(record) for record in previous["records"]]
        if capture.get("decision_date") <= records[-1]["decision_date"]:
            if capture.get("decision_date") == records[-1]["decision_date"] and capture == records[-1]:
                return build_pairwise_ledger(records)
            raise SoftBoostComparisonAdjudicationError("pairwise capture must append one new decision date")
    return build_pairwise_ledger(records + [capture])


def apply_maturity_observations(ledger: object, observations: list[dict[str, Any]], *, maturity_as_of: str) -> dict[str, Any]:
    """One-way mature previously captured weeks from source-bound local observations; never backfill captures."""
    _validate(ledger, PAIRWISE_SCHEMA)
    if not isinstance(observations, list):
        raise SoftBoostComparisonAdjudicationError("maturity observations must be a list")
    by_date = {record["decision_date"]: dict(record) for record in ledger["records"]}
    seen = set()
    for observation in observations:
        try:
            _validate(observation, MATURITY_OBSERVATION_SCHEMA)
        except (jsonschema.ValidationError, OSError, UnicodeDecodeError, ValueError) as exc:
            raise SoftBoostComparisonAdjudicationError("maturity observation has an unexpected shape") from exc
        date = observation["decision_date"]
        if date in seen or date >= maturity_as_of or date not in by_date:
            raise SoftBoostComparisonAdjudicationError("maturity observation is duplicate, premature, or uncaptured")
        seen.add(date)
        prior = by_date[date]
        if prior["matured"] or any(prior[key] != observation[key] for key in (
                "consumption_receipt_sha256", "shadow_receipt_sha256")):
            raise SoftBoostComparisonAdjudicationError("maturity observation does not bind an unmatured capture")
        if type(observation["eligible"]) is not bool or type(observation["non_overlap_h10_block"]) is not bool:
            raise SoftBoostComparisonAdjudicationError("maturity eligibility flags must be exact bool")
        by_date[date] = {**prior, **observation, "matured": True}
    return build_pairwise_ledger([by_date[record["decision_date"]] for record in ledger["records"]])


def read_pairwise_ledger(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    _validate(value, PAIRWISE_SCHEMA)
    return value


def persist_pairwise_ledger(path: Path, ledger: object) -> None:
    """Atomically replace the private state ledger only after its closed schema validates."""
    _validate(ledger, PAIRWISE_SCHEMA)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def build_pairwise_ledger(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Seal ordered post-maturity paired observations; no historical backfill is accepted."""
    if not isinstance(records, list) or not records:
        raise SoftBoostComparisonAdjudicationError("pairwise ledger needs at least one observation")
    plan, plan_sha = load_statistical_plan()
    dates = [record.get("decision_date") if isinstance(record, dict) else None for record in records]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise SoftBoostComparisonAdjudicationError("pairwise observations must be uniquely chronological")
    matured = sum(record.get("matured") is True for record in records)
    eligible = _eligible(records)
    non_overlap = sum(record["non_overlap_h10_block"] is True for record in eligible)
    latest = records[-1]
    ledger = {
        "schema_name": "us_short_soft_boost_pairwise_ledger", "schema_version": "1.0.0",
        "epoch_id": plan["epoch_id"], "comparison_statistical_plan_sha256": plan_sha,
        "records": records, "captured_week_count": len(records), "matured_week_count": matured,
        "eligible_divergence_week_count": len(eligible), "non_overlap_h10_block_count": non_overlap,
        "latest_decision_date": latest["decision_date"],
        "latest_consumption_receipt_sha256": latest["consumption_receipt_sha256"],
        "latest_shadow_receipt_sha256": latest["shadow_receipt_sha256"],
        "historical_backfill_allowed": False, "automatic_route_change_allowed": False, "production_flag": False,
    }
    _validate(ledger, PAIRWISE_SCHEMA)
    return ledger


def _summary(records: list[dict[str, Any]], *, winner: str, plan: dict[str, Any]) -> dict[str, Any]:
    loser = "off" if winner == "on" else "on"
    deltas = [record[f"{winner}_net_return"] - record[f"{loser}_net_return"] for record in records]
    mean = statistics.fmean(deltas)
    if len(deltas) < 2:
        lower, pvalue = float("-inf"), 1.0
    elif statistics.pstdev(deltas) == 0.0:
        lower, pvalue = mean, 0.0 if mean > 0.0 else 1.0
    else:
        se = statistics.stdev(deltas) / math.sqrt(len(deltas))
        z = mean / se
        lower = mean - 2.2414 * se  # frozen one-sided alpha=0.0125 normal approximation
        pvalue = 0.5 * math.erfc(z / math.sqrt(2.0))
    # The frozen placebo gate is an actual deterministic sign-permutation test,
    # independent of the normal-approximation confidence gate above.
    generator = random.Random("us_short_soft_boost_permutation|%s|%d|%s" % (winner, len(deltas), deltas))
    observed = abs(mean)
    permutations = 20000
    extreme = sum(abs(sum((1 if generator.getrandbits(1) else -1) * delta for delta in deltas) / len(deltas)) >= observed
                  for _ in range(permutations))
    permutation_pvalue = (extreme + 1) / (permutations + 1)
    gate = plan["outcome_gate"]
    risk = plan["risk_guardrails"]
    regimes = {record["market_risk_regime"] for record in records}
    regime_ready = sum(sum(record["market_risk_regime"] == regime for record in records) >= plan["minimum_divergence_weeks_per_required_regime"] for regime in regimes) >= plan["minimum_market_risk_regimes"]
    winner_turnover = statistics.fmean(record[f"{winner}_turnover"] for record in records)
    loser_turnover = statistics.fmean(record[f"{loser}_turnover"] for record in records)
    risk_ok = all((
        statistics.fmean(record[f"{winner}_max_drawdown"] - record[f"{loser}_max_drawdown"] for record in records) <= risk["max_drawdown_worsening_fraction_max"],
        statistics.fmean(record[f"{winner}_bad_pick_rate"] - record[f"{loser}_bad_pick_rate"] for record in records) <= risk["bad_pick_rate_worsening_max"],
        statistics.fmean(record[f"{loser}_tail_loss"] - record[f"{winner}_tail_loss"] for record in records) <= risk["tail_loss_worsening_fraction_max"],
        winner_turnover <= max(1e-12, loser_turnover) * risk["turnover_harm_multiplier_max"],
    ))
    passed = bool(
        len(records) >= 24 and sum(record["non_overlap_h10_block"] is True for record in records) >= plan["minimum_non_overlap_h10_blocks"]
        and regime_ready and risk_ok and mean >= gate["mean_paired_advantage_gte"]
        and sum(delta > 0 for delta in deltas) / len(deltas) >= gate["paired_win_fraction_gte"][0] / gate["paired_win_fraction_gte"][1]
        and 1.0 - permutation_pvalue > gate["placebo_percentile_exclusive_gt"] and lower > gate["paired_block_ci_lower_gt"]
        and pvalue <= max(gate["formal_one_sided_alpha_spending"])
    )
    return {"mean_paired_advantage": mean, "paired_win_fraction": sum(delta > 0 for delta in deltas) / len(deltas),
            "one_sided_ci_lower": lower, "one_sided_pvalue": pvalue, "permutation_pvalue": permutation_pvalue, "risk_ok": risk_ok,
            "regime_ready": regime_ready, "passed": passed}


def evaluate_pairwise_ledger(ledger: object) -> dict[str, Any]:
    """Evaluate only frozen first-N eligible observations at the 24/36 looks."""
    _validate(ledger, PAIRWISE_SCHEMA)
    plan, plan_sha = load_statistical_plan()
    if ledger["comparison_statistical_plan_sha256"] != plan_sha:
        raise SoftBoostComparisonAdjudicationError("pairwise ledger is not bound to the current frozen plan")
    eligible = _eligible(ledger["records"])
    if len(eligible) != ledger["eligible_divergence_week_count"]:
        raise SoftBoostComparisonAdjudicationError("pairwise ledger count mismatch")
    looks = plan["formal_look_divergence_weeks"]
    formal_look = max((look for look in looks if len(eligible) >= look), default=None)
    if formal_look is None:
        return {"status": "continue_accumulation", "formal_look": None, "recommendation": "continue_accumulating",
                "on": None, "off": None, "eligible_divergence_week_count": len(eligible)}
    frozen = eligible[:formal_look]
    on, off = _summary(frozen, winner="on", plan=plan), _summary(frozen, winner="off", plan=plan)
    recommendation = "continue_on" if on["passed"] and not off["passed"] else (
        "recommend_switch_off" if off["passed"] and not on["passed"] else "insufficient_evidence")
    return {"status": "formal_adjudicated", "formal_look": formal_look, "recommendation": recommendation,
            "on": on, "off": off, "eligible_divergence_week_count": len(eligible)}


def build_adjudication_receipt(ledger_path: Path, *, decision_date: str, user_decision: str = "none") -> dict[str, Any]:
    raw = Path(ledger_path).read_bytes()
    ledger = json.loads(raw.decode("utf-8"))
    result = evaluate_pairwise_ledger(ledger)
    if result["formal_look"] is None:
        raise SoftBoostComparisonAdjudicationError("formal adjudication is unavailable before the 24/36 fixed looks")
    _, plan_sha = load_statistical_plan()
    receipt = {
        "schema_name": "us_short_soft_boost_adjudication_receipt", "schema_version": "1.0.0",
        "epoch_id": ledger["epoch_id"], "decision_date": decision_date,
        "comparison_ledger_sha256": hashlib.sha256(raw).hexdigest(), "comparison_statistical_plan_sha256": plan_sha,
        "formal_look": result["formal_look"],
        "comparison_counts": {key: ledger[key] for key in ("captured_week_count", "matured_week_count", "eligible_divergence_week_count", "non_overlap_h10_block_count")},
        "formal_evidence": {"on_gate_passed": result["on"]["passed"], "off_gate_passed": result["off"]["passed"],
                            "inconclusive": result["recommendation"] == "insufficient_evidence"},
        "recommendation": result["recommendation"], "user_decision": user_decision,
        "automatic_replacement_allowed": False, "production_flag": False,
    }
    _validate(receipt, ADJUDICATION_SCHEMA)
    return receipt
