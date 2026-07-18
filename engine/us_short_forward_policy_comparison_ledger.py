# -*- coding: utf-8 -*-
"""US-short A1 v2 source-gated private comparison accumulation and adjudication.

This module closes the *consumer* half of the comparison track: a H10 projection can enter the
private ledger only with a same-run source receipt bound to the exact retained 20-session price
window, frozen costs and corporate-action evidence.  It then calculates the registered H10
metrics, a fixed-seed one-sided paired block bootstrap, Holm correction, five-state advice and a
non-production persistent reminder.  It fetches nothing and never switches ``balanced``.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import random
from collections import defaultdict
from pathlib import Path

import jsonschema

from engine.us_short_forward_policy_heads import SELECTION_POLICY_IDS
from engine.us_short_forward_policy_private_week import validate_forward_policy_private_week_record
from engine.us_short_forward_policy_statistical_plan import load_forward_policy_statistical_plan, statistical_plan_sha256
from engine.us_short_forward_policy_effect_surface import baseline_epoch_sha256
from engine.us_short_forward_policy_weekly_evidence import build_forward_policy_h10_weekly_evidence, validate_forward_policy_h10_weekly_evidence
from engine.us_short_paper_fill import simulate_fill
from engine.us_short_paper_multi_day_exit import simulate_multi_day_exit
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path


ROOT = Path(__file__).resolve().parent.parent
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_comparison_ledger.schema.json"
RECEIPT_SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_source_receipt.schema.json"
PRIVATE_ROOT = ROOT / "state" / "us_short" / "shadow_compare_private"
BOUNDARY = {
    "track": "comparison_non_production", "shadow_counts_ship_gate": False,
    "changes_primary_selection": False, "provider_calls_added": False,
    "broker_or_order_automation_allowed": False, "automatic_production_switch": False,
    "private_ticker_bearing_records_only": True,
}
_RECEIPT_KEYS = frozenset({
    "schema_name", "schema_version", "run_id", "decision_date", "capture_sha256", "source_context_sha256", "baseline_epoch_sha256",
    "source_packet_sha256", "common_price_snapshot_sha256", "price_window_sha256", "cost_prior_sha256",
    "adjustment_evidence_sha256", "same_run_live_source", "provider_calls_added",
})
_LEDGER_KEYS = frozenset({"schema_name", "schema_version", "comparison_contract_sha256", "records", "user_decisions", "boundary"})


class ForwardPolicyComparisonLedgerError(ValueError):
    """Raised when private comparison evidence lacks an auditable source/provenance or ledger binding."""


def _canonical_sha256(value: object) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ForwardPolicyComparisonLedgerError("comparison value is not finite canonical JSON") from exc
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_schema(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyComparisonLedgerError("cannot load comparison-ledger schema") from exc


def _strict_date(value: object) -> bool:
    if not (type(value) is str and value.isascii() and len(value) == 8 and value.isdigit()):
        return False
    try:
        datetime.date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return False
    return True


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _finite(value: object) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _validate_schema(value: object, path: Path, label: str) -> None:
    try:
        jsonschema.validate(value, _load_schema(path))
    except jsonschema.ValidationError as exc:
        raise ForwardPolicyComparisonLedgerError(f"{label} schema rejected: {exc.message}") from exc


def build_same_run_source_receipt(private_week_record: object, *, run_id: str, source_packet_sha256: str) -> dict:
    """Build the only receipt shape the future weekly source stage may emit.

    The receipt is deliberately separate from the retained week: the source stage must supply its
    own opaque source-packet digest and run id.  This function cannot manufacture that digest.
    """
    private_week = validate_forward_policy_private_week_record(private_week_record)
    if not isinstance(run_id, str) or not run_id or not _sha(source_packet_sha256):
        raise ForwardPolicyComparisonLedgerError("source receipt run_id/source packet digest is invalid")
    if private_week["materialization_status"] != "ready_for_accumulation":
        raise ForwardPolicyComparisonLedgerError("a source receipt can only bind an accumulation-ready private week")
    inputs, outcome = private_week["forward_inputs"], private_week["outcome_packet"]
    return {
        "schema_name": "us_short_forward_policy_source_receipt", "schema_version": "1.0.0",
        "run_id": run_id, "decision_date": private_week["capture_binding"]["decision_date"],
        "capture_sha256": private_week["capture_sha256"],
        "source_context_sha256": private_week["capture_binding"]["source_context_sha256"],
        "baseline_epoch_sha256": private_week["capture_binding"]["baseline_epoch_sha256"],
        "source_packet_sha256": source_packet_sha256,
        "common_price_snapshot_sha256": outcome["common_price_snapshot_sha256"],
        "price_window_sha256": _canonical_sha256(inputs["daily_bars_by_ticker"]),
        "cost_prior_sha256": _canonical_sha256(inputs["cost_prior"]),
        "adjustment_evidence_sha256": _canonical_sha256(inputs["adjustment_evidence"]),
        "same_run_live_source": True, "provider_calls_added": False,
    }


def validate_same_run_source_receipt(receipt: object, private_week_record: object) -> dict:
    """Require a source-stage receipt to bind every retained forward input exactly.

    The receipt refuses a caller's arbitrary price/cost/adjustment digest and also refuses a
    precomputed outcome without its source private week.  It does not make a provider call.
    """
    private_week = validate_forward_policy_private_week_record(private_week_record)
    if private_week["materialization_status"] != "ready_for_accumulation":
        raise ForwardPolicyComparisonLedgerError("only a ready private week can enter the source-bound accumulator")
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_KEYS:
        raise ForwardPolicyComparisonLedgerError("same-run source receipt must use its exact closed-world key set")
    _validate_schema(receipt, RECEIPT_SCHEMA_PATH, "same-run source receipt")
    if not isinstance(receipt["run_id"], str) or not receipt["run_id"] or not _strict_date(receipt["decision_date"]):
        raise ForwardPolicyComparisonLedgerError("same-run source receipt run/date is invalid")
    if any(not _sha(receipt[key]) for key in _RECEIPT_KEYS - {"schema_name", "schema_version", "run_id", "decision_date", "same_run_live_source", "provider_calls_added"}):
        raise ForwardPolicyComparisonLedgerError("same-run source receipt digest is invalid")
    inputs, outcome, binding = private_week["forward_inputs"], private_week["outcome_packet"], private_week["capture_binding"]
    expected = {
        "decision_date": binding["decision_date"], "capture_sha256": private_week["capture_sha256"],
        "source_context_sha256": binding["source_context_sha256"],
        "baseline_epoch_sha256": binding["baseline_epoch_sha256"],
        "common_price_snapshot_sha256": outcome["common_price_snapshot_sha256"],
        "price_window_sha256": _canonical_sha256(inputs["daily_bars_by_ticker"]),
        "cost_prior_sha256": _canonical_sha256(inputs["cost_prior"]),
        "adjustment_evidence_sha256": _canonical_sha256(inputs["adjustment_evidence"]),
    }
    if any(receipt[key] != value for key, value in expected.items()):
        raise ForwardPolicyComparisonLedgerError("same-run source receipt does not match the retained private source week")
    return dict(receipt)


def empty_forward_policy_comparison_ledger() -> dict:
    return {
        "schema_name": "us_short_forward_policy_comparison_ledger", "schema_version": "1.0.0",
        "comparison_contract_sha256": statistical_plan_sha256(), "records": [], "user_decisions": {},
        "boundary": dict(BOUNDARY),
    }


def comparison_banner_from_private_ledger_path(ledger_path: object) -> str:
    """Render the non-blocking, de-identified A1 reminder from the canonical private ledger.

    A missing, unreadable, or invalid comparison ledger can never stop the official weekly report:
    this track is advisory-only.  The banner makes that loss of comparison evidence visible while
    keeping ``balanced`` unchanged and disclosing no ticker or price data.
    """
    path = Path(ledger_path)
    if path.name != "forward_policy_comparison_ledger.json" or path.parent.name != "shadow_compare_private":
        raise ForwardPolicyComparisonLedgerError("comparison reminder requires a shadow_compare_private canonical ledger name")
    if not path.exists():
        adjudication = evaluate_forward_policy_comparison_ledger(empty_forward_policy_comparison_ledger())
        return render_forward_policy_comparison_banner(adjudication)
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
        adjudication = evaluate_forward_policy_comparison_ledger(ledger)
        return render_forward_policy_comparison_banner(adjudication, ledger=ledger)
    except (OSError, ValueError, json.JSONDecodeError, ForwardPolicyComparisonLedgerError):
        return (
            "US-SHORT A1 comparison track: inconclusive (private comparison evidence unavailable); "
            "advisory only, never auto-switch balanced"
        )


def validate_forward_policy_comparison_ledger(ledger: object) -> dict:
    if not isinstance(ledger, dict) or set(ledger) != _LEDGER_KEYS:
        raise ForwardPolicyComparisonLedgerError("comparison ledger must use its exact closed-world key set")
    _validate_schema(ledger, LEDGER_SCHEMA_PATH, "comparison ledger")
    if ledger["comparison_contract_sha256"] != statistical_plan_sha256() or ledger["boundary"] != BOUNDARY:
        raise ForwardPolicyComparisonLedgerError("comparison ledger contract/boundary drifted")
    last_date, seen = None, set()
    for record in ledger["records"]:
        if not isinstance(record, dict) or set(record) != {"decision_date", "weekly_evidence", "source_receipt"}:
            raise ForwardPolicyComparisonLedgerError("comparison ledger record shape drifted")
        evidence = validate_forward_policy_h10_weekly_evidence(record["weekly_evidence"])
        source = validate_same_run_source_receipt(record["source_receipt"], evidence["source_private_week_record"])
        date = evidence["capture_binding"]["decision_date"]
        if record["decision_date"] != date or source["decision_date"] != date or date in seen or (last_date is not None and date <= last_date):
            raise ForwardPolicyComparisonLedgerError("comparison ledger decision dates must be unique and strictly ordered")
        if evidence["projection_status"] != "ready_for_private_accumulation":
            raise ForwardPolicyComparisonLedgerError("a no-count projection cannot appear in the counted source-bound ledger")
        seen.add(date); last_date = date
    if not isinstance(ledger["user_decisions"], dict):
        raise ForwardPolicyComparisonLedgerError("comparison ledger user decision store is invalid")
    for decision_key, decision in ledger["user_decisions"].items():
        if not isinstance(decision_key, str) or not isinstance(decision, dict) or set(decision) != {"receipt", "decision", "decided_at"}:
            raise ForwardPolicyComparisonLedgerError("comparison ledger user decision shape drifted")
        if decision["decision"] not in {"accept", "reject", "defer"} or not isinstance(decision["decided_at"], str):
            raise ForwardPolicyComparisonLedgerError("comparison ledger user decision value/date is invalid")
        receipt = decision["receipt"]
        if not isinstance(receipt, dict) or set(receipt) != {"question_id", "arm_id", "status", "verdict_sha256", "contract_sha256", "baseline_epoch_sha256", "decision", "decided_at"} \
                or decision_key != f"{receipt.get('baseline_epoch_sha256')}:{receipt.get('question_id')}" or receipt["decision"] is not None or receipt["decided_at"] is not None \
                or not isinstance(receipt["arm_id"], str) or not receipt["arm_id"] or not _sha(receipt["verdict_sha256"]) \
                or receipt["contract_sha256"] != statistical_plan_sha256() or not _sha(receipt["baseline_epoch_sha256"]):
            raise ForwardPolicyComparisonLedgerError("comparison ledger user decision receipt is invalid")
    return ledger


def _daily_asset_returns(private_week: dict) -> dict[str, list[float]]:
    """Reconstruct H1..H10 marked returns with the same fill/exit/cost rules as the outcome core."""
    inputs, orders = private_week["forward_inputs"], private_week["order_snapshot"]["orders_by_ticker"]
    total_cost = sum((inputs["cost_prior"]["commission_fee"], inputs["cost_prior"]["spread_cost"], inputs["cost_prior"]["slippage_bps"] / 10000.0))
    values = {}
    for ticker, order in orders.items():
        bars, fill = inputs["daily_bars_by_ticker"][ticker], simulate_fill(order, inputs["daily_bars_by_ticker"][ticker][0])
        daily, held, locked = [], None, None
        if fill["status"] == "not_filled":
            values[ticker] = [0.0] * 10; continue
        if fill["status"] != "filled_held":
            locked = (fill["exit_price"] - fill["fill_price"]) / fill["fill_price"] - total_cost
        else:
            held = {"fill_price": fill["fill_price"], "stop_clear_price": order["stop_clear_price"], "take_profit_exit_price": order["take_profit_exit_price"]}
        for index, bar in enumerate(bars[:10]):
            if locked is not None:
                daily.append(locked); continue
            if index:
                stepped = simulate_multi_day_exit(held, [bar])
                if stepped["status"] != "filled_held":
                    locked = (stepped["exit_price"] - stepped["fill_price"]) / stepped["fill_price"] - total_cost
                    daily.append(locked); continue
            daily.append((bar["close"] - held["fill_price"]) / held["fill_price"] - total_cost)
        values[ticker] = daily
    return values


def _max_drawdown(returns: list[float]) -> float:
    navs, high, worst = [], 1.0, 0.0
    for value in returns:
        navs.append(1.0 + value)
        high = max(high, navs[-1])
        worst = min(worst, navs[-1] / high - 1.0)
    return -worst


def _weekly_policy_metrics(evidence: dict) -> dict[str, dict]:
    private_week = evidence["source_private_week_record"]
    daily = _daily_asset_returns(private_week)
    outcome_rows = {row["ticker"]: row["h10"] for row in private_week["outcome_packet"]["candidate_outcomes"]}
    result = {}
    for policy_id, selected in evidence["policy_selections"].items():
        h10 = [outcome_rows[ticker]["candidate_after_cost_net_return"] for ticker in selected]
        path = [sum(daily[ticker][index] for ticker in selected) / len(selected) for index in range(10)]
        result[policy_id] = {
            "net_return": sum(h10) / len(h10), "max_drawdown": _max_drawdown(path),
            "bad_pick_rate": sum(value < 0.0 for value in h10) / len(h10),
            "tail_loss": sum(sorted(h10)[:max(1, math.ceil(len(h10) * 0.2))]) / max(1, math.ceil(len(h10) * 0.2)),
            "total_cost_fraction": sum(outcome_rows[ticker]["total_cost_fraction"] for ticker in selected) / len(selected),
            "unfilled_cash_count": sum(outcome_rows[ticker]["unfilled_cash"] for ticker in selected),
            "fill_rate": sum(not outcome_rows[ticker]["unfilled_cash"] for ticker in selected) / len(selected),
            "turnover": None,
        }
    return result


def _nonoverlap(records: list[dict]) -> list[dict]:
    kept, last_h10 = [], None
    for record in records:
        evidence = record["weekly_evidence"]
        entry = evidence["source_private_week_record"]["outcome_packet"]["entry_session_date"]
        h10 = evidence["h10_session_date"]
        if last_h10 is None or entry > last_h10:
            kept.append(record); last_h10 = h10
    return kept


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))]


def _holm(raw: dict[str, float]) -> dict[str, float]:
    ordered, out, prior = sorted(raw.items(), key=lambda item: item[1]), {}, 0.0
    count = len(ordered)
    for index, (arm, value) in enumerate(ordered):
        prior = max(prior, min(1.0, value * (count - index)))
        out[arm] = prior
    return out


def _segment_random_effects(deltas_by_segment: dict[str, list[float]]) -> dict:
    """Pool compatible effect-surface segments with an intercept-only REML random-effects mean."""
    populated = {segment: values for segment, values in deltas_by_segment.items() if values}
    if not populated:
        return {"method": "reml_random_effects", "segment_count": 0, "mean_advantage": None, "tau_squared": None}
    all_values = [value for values in populated.values() for value in values]
    fallback_variance = (
        sum((value - sum(all_values) / len(all_values)) ** 2 for value in all_values) / (len(all_values) - 1)
        if len(all_values) > 1 else 1.0
    )
    summaries = []
    for values in populated.values():
        mean = sum(values) / len(values)
        variance = (
            sum((value - mean) ** 2 for value in values) / ((len(values) - 1) * len(values))
            if len(values) > 1 else fallback_variance
        )
        summaries.append((mean, max(variance, 1e-12)))
    if len(summaries) == 1:
        return {"method": "reml_random_effects", "segment_count": 1, "mean_advantage": summaries[0][0], "tau_squared": 0.0}

    def reml_score(tau_squared: float) -> float:
        weights = [1.0 / (variance + tau_squared) for _mean, variance in summaries]
        weighted_mean = sum(weight * mean for weight, (mean, _variance) in zip(weights, summaries)) / sum(weights)
        return sum(weights) - sum(weight ** 2 for weight in weights) / sum(weights) - sum(
            weight ** 2 * (mean - weighted_mean) ** 2 for weight, (mean, _variance) in zip(weights, summaries)
        )

    tau_squared = 0.0
    if reml_score(0.0) < 0.0:
        upper = max(variance for _mean, variance in summaries)
        while reml_score(upper) < 0.0:
            upper *= 2.0
        lower = 0.0
        for _ in range(80):
            midpoint = (lower + upper) / 2.0
            if reml_score(midpoint) < 0.0:
                lower = midpoint
            else:
                upper = midpoint
        tau_squared = (lower + upper) / 2.0
    random_weights = [1.0 / (variance + tau_squared) for _mean, variance in summaries]
    mean = sum(weight * value for weight, (value, _variance) in zip(random_weights, summaries)) / sum(random_weights)
    return {"method": "reml_random_effects", "segment_count": len(summaries), "mean_advantage": mean, "tau_squared": tau_squared}


def _segment_orthogonality_summary(records: list[dict]) -> list[dict]:
    """Expose the three source-bound invariants required before segment pooling."""
    by_epoch: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        evidence = record["weekly_evidence"]
        binding = evidence["capture_binding"]
        pool = evidence["common_selection_pool"]
        selections = evidence["policy_selections"]
        balanced = selections[SELECTION_POLICY_IDS[0]]
        if binding["common_selection_pool_sha256"] != _canonical_sha256(pool):
            raise ForwardPolicyComparisonLedgerError("segment common-pool membership binding drifted")
        if any(not set(selected).issubset(pool) for selected in selections.values()):
            raise ForwardPolicyComparisonLedgerError("segment arm selection difference escaped the common pool")
        source = record["source_receipt"]
        if source["price_window_sha256"] != _canonical_sha256(evidence["source_private_week_record"]["forward_inputs"]["daily_bars_by_ticker"]):
            raise ForwardPolicyComparisonLedgerError("segment H10 outcome calculation binding drifted")
        segment = by_epoch[binding["baseline_epoch_sha256"]]
        segment["pool_memberships"].append(binding["common_selection_pool_sha256"])
        segment["selection_differences"].append({
            arm: sorted(set(selections[arm]) ^ set(balanced)) for arm in SELECTION_POLICY_IDS[1:]
        })
        segment["h10_calculations"].append({
            "price_window_sha256": source["price_window_sha256"],
            "cost_prior_sha256": source["cost_prior_sha256"],
            "adjustment_evidence_sha256": source["adjustment_evidence_sha256"],
        })
    return [
        {
            "baseline_epoch_sha256": epoch,
            "counted_week_count": len(items["pool_memberships"]),
            "orthogonality_invariants": {
                "common_selection_pool_membership": _canonical_sha256(items["pool_memberships"]),
                "per_arm_selection_difference": _canonical_sha256(items["selection_differences"]),
                "h10_outcome_calculation": _canonical_sha256(items["h10_calculations"]),
            },
        }
        for epoch, items in sorted(by_epoch.items())
    ]


def _arm_summary(
    records: list[dict], arm: str, plan: dict, *, formal_look: int | None = None, formal_alpha: float | None = None,
) -> dict:
    balanced = SELECTION_POLICY_IDS[0]
    all_divergent = [r for r in records if set(r["weekly_evidence"]["policy_selections"][arm]) != set(r["weekly_evidence"]["policy_selections"][balanced])]
    divergent = all_divergent if formal_look is None else all_divergent[:formal_look]
    metrics = [_weekly_policy_metrics(r["weekly_evidence"]) for r in divergent]
    deltas = [m[arm]["net_return"] - m[balanced]["net_return"] for m in metrics]
    deltas_by_segment: dict[str, list[float]] = defaultdict(list)
    for record, delta in zip(divergent, deltas):
        deltas_by_segment[record["weekly_evidence"]["capture_binding"]["baseline_epoch_sha256"]].append(delta)
    random_effects = _segment_random_effects(deltas_by_segment)
    blocks = _nonoverlap(divergent)
    block_deltas = [_weekly_policy_metrics(r["weekly_evidence"])[arm]["net_return"] - _weekly_policy_metrics(r["weekly_evidence"])[balanced]["net_return"] for r in blocks]
    mean = random_effects["mean_advantage"]
    win = sum(value >= plan["statistics"]["comparison_win_margin"] for value in deltas) / len(deltas) if deltas else None
    bootstrap = []
    if block_deltas:
        for seed in range(plan["statistics"]["placebo"]["seed_start"], plan["statistics"]["placebo"]["seed_end_inclusive"] + 1):
            generator = random.Random(f"us_short_a1_v2_paired_block_bootstrap|{arm}|{seed}")
            bootstrap.append(sum(generator.choice(block_deltas) for _ in block_deltas) / len(block_deltas))
    lower_alpha = plan["statistics"]["paired_block_confidence_lower_alpha"] if formal_alpha is None else formal_alpha
    lower = _percentile(bootstrap, lower_alpha) if bootstrap else None
    # The pre-registered null perturbs balanced through exactly the arm's observed same-week
    # in/out count, sampled only from that week's frozen Pass2-clean common pool.
    null = []
    if block_deltas:
        for seed in range(plan["statistics"]["placebo"]["seed_start"], plan["statistics"]["placebo"]["seed_end_inclusive"] + 1):
            generator = random.Random(f"us_short_a1_v2_placebo|{arm}|{seed}")
            placebo_deltas = []
            for record in blocks:
                evidence = record["weekly_evidence"]
                selected = evidence["policy_selections"]
                base, arm_selected, pool = selected[balanced], selected[arm], evidence["common_selection_pool"]
                swap_count = len(set(arm_selected) - set(base))
                if not swap_count:
                    placebo_deltas.append(0.0); continue
                outside = [ticker for ticker in pool if ticker not in set(base)]
                removed = generator.sample(base, swap_count)
                added = generator.sample(outside, swap_count)
                values = evidence["candidate_after_cost_net_return"]
                pseudo = [ticker for ticker in base if ticker not in set(removed)] + added
                placebo_deltas.append(sum(values[ticker] for ticker in pseudo) / len(pseudo) - sum(values[ticker] for ticker in base) / len(base))
            null.append(sum(placebo_deltas) / len(placebo_deltas))
    pvalue = (1 + sum(value >= mean for value in null)) / (1 + len(null)) if null and mean is not None else None
    metric_keys = ("max_drawdown", "bad_pick_rate", "tail_loss", "total_cost_fraction", "unfilled_cash_count", "fill_rate")
    means = {key: (sum(m[arm][key] for m in metrics) / len(metrics) if metrics else None) for key in metric_keys}
    balanced_means = {key: (sum(m[balanced][key] for m in metrics) / len(metrics) if metrics else None) for key in metric_keys}
    turnover, balanced_turnover = [], []
    prior = {policy: None for policy in SELECTION_POLICY_IDS}
    for record in records:
        selections = record["weekly_evidence"]["policy_selections"]
        if prior[arm] is not None:
            turnover.append(len(set(selections[arm]) ^ set(prior[arm])) / len(selections[arm]))
            balanced_turnover.append(len(set(selections[balanced]) ^ set(prior[balanced])) / len(selections[balanced]))
        for policy in SELECTION_POLICY_IDS: prior[policy] = selections[policy]
    return {"available_divergence_weeks": len(all_divergent), "formal_look_divergence_weeks": formal_look,
            "formal_look_one_sided_alpha": formal_alpha,
            "divergence_weeks": len(divergent), "nonoverlap_h10_blocks": len(blocks), "mean_advantage": mean,
            "segment_random_effects": random_effects,
            "paired_win_fraction": win, "bootstrap_lower_one_sided": lower, "raw_pvalue": pvalue,
            "placebo_95th_percentile": _percentile(null, 0.95) if null else None,
            "metrics": means, "balanced_metrics": balanced_means,
            "mean_turnover": sum(turnover) / len(turnover) if turnover else 0.0,
            "balanced_mean_turnover": sum(balanced_turnover) / len(balanced_turnover) if balanced_turnover else 0.0,
            "regimes": {regime: sum(r["weekly_evidence"]["market_risk_regime"] == regime for r in divergent) for regime in sorted({r["weekly_evidence"]["market_risk_regime"] for r in divergent})}}


def _apply_formal_gates(candidates: dict[str, dict], plan: dict, *, formal_alpha: float) -> None:
    """Apply one planned look's Holm/risk gates to already frozen first-N summaries."""
    raw = {arm: summary["raw_pvalue"] for arm, summary in candidates.items() if summary["raw_pvalue"] is not None}
    adjusted = _holm(raw) if raw else {}
    risk = plan["statistics"]["risk_guardrails"]
    for arm, summary in candidates.items():
        enough = summary["divergence_weeks"] >= plan["statistics"]["minimum_divergence_weeks_before_formal_recommendation"] \
            and summary["nonoverlap_h10_blocks"] >= plan["statistics"]["minimum_nonoverlap_h10_blocks_before_formal_recommendation"] \
            and sum(count >= plan["statistics"]["minimum_divergence_weeks_per_required_regime"] for count in summary["regimes"].values()) >= plan["statistics"]["minimum_market_risk_regimes_before_formal_recommendation"]
        risk_ok = all((
            summary["metrics"]["max_drawdown"] - summary["balanced_metrics"]["max_drawdown"] <= risk["max_drawdown_worsening_fraction_max"],
            summary["metrics"]["bad_pick_rate"] - summary["balanced_metrics"]["bad_pick_rate"] <= risk["bad_pick_rate_worsening_max"],
            summary["balanced_metrics"]["tail_loss"] - summary["metrics"]["tail_loss"] <= risk["tail_loss_worsening_fraction_max"],
            summary["mean_turnover"] <= max(1e-12, summary["balanced_mean_turnover"]) * risk["turnover_harm_multiplier_vs_balanced"],
            summary["metrics"]["fill_rate"] >= summary["balanced_metrics"]["fill_rate"] * risk["fill_harm_fraction_vs_balanced"],
        )) if enough else False
        summary["holm_adjusted_pvalue"] = adjusted.get(arm)
        summary["formal_coverage_ready"] = enough
        summary["formal_pass"] = bool(
            enough and risk_ok and summary["mean_advantage"] >= plan["statistics"]["comparison_win_margin"]
            and summary["paired_win_fraction"] >= 2 / 3
            and summary["mean_advantage"] > summary["placebo_95th_percentile"]
            and summary["bootstrap_lower_one_sided"] > 0.0
            and adjusted.get(arm, 1.0) <= formal_alpha
        )


def _pairwise_direct_summary(records: list[dict], left: str, right: str, *, formal_look: int, alpha: float) -> dict:
    divergent = [
        record for record in records
        if set(record["weekly_evidence"]["policy_selections"][left])
        != set(record["weekly_evidence"]["policy_selections"][right])
    ][:formal_look]
    blocks = _nonoverlap(divergent)
    deltas = []
    deltas_by_segment: dict[str, list[float]] = defaultdict(list)
    for record in blocks:
        metrics = _weekly_policy_metrics(record["weekly_evidence"])
        delta = metrics[left]["net_return"] - metrics[right]["net_return"]
        deltas.append(delta)
        deltas_by_segment[record["weekly_evidence"]["capture_binding"]["baseline_epoch_sha256"]].append(delta)
    random_effects = _segment_random_effects(deltas_by_segment)
    bootstrap = []
    if deltas:
        for seed in range(1000):
            generator = random.Random(f"us_short_a1_v2_1_direct_pairwise|{left}|{right}|{formal_look}|{seed}")
            bootstrap.append(sum(generator.choice(deltas) for _ in deltas) / len(deltas))
    regimes = {
        regime: sum(record["weekly_evidence"]["market_risk_regime"] == regime for record in divergent)
        for regime in sorted({record["weekly_evidence"]["market_risk_regime"] for record in divergent})
    }
    return {
        "left_arm": left,
        "right_arm": right,
        "pairwise_divergence_weeks": len(divergent),
        "nonoverlap_h10_blocks": len(blocks),
        "regimes": regimes,
        "mean_advantage": random_effects["mean_advantage"],
        "segment_random_effects": random_effects,
        "bonferroni_one_sided_lower": _percentile(bootstrap, alpha) if bootstrap else None,
    }


def _direct_pairwise_winner(
    records: list[dict], passers: list[str], *, formal_look: int, formal_alpha: float, plan: dict,
) -> tuple[str | None, list[dict]]:
    """Return a unique direct winner only when it beats every other passer at Bonferroni alpha."""
    direct = plan["decision_contract"]["direct_pairwise_final"]
    comparisons = max(1, len(passers) - 1)
    alpha = min(direct["confidence_lower_alpha"], formal_alpha) / comparisons
    summaries: list[dict] = []
    winners = []
    for left in passers:
        left_wins_all = True
        for right in passers:
            if left == right:
                continue
            summary = _pairwise_direct_summary(records, left, right, formal_look=formal_look, alpha=alpha)
            summary["bonferroni_one_sided_alpha"] = alpha
            summaries.append(summary)
            coverage_ready = (
                summary["pairwise_divergence_weeks"] >= formal_look
                and summary["nonoverlap_h10_blocks"] >= direct["minimum_nonoverlap_h10_blocks"]
                and sum(count >= direct["minimum_divergence_weeks_per_required_regime"] for count in summary["regimes"].values()) >= direct["minimum_market_risk_regimes"]
            )
            if not coverage_ready or summary["bonferroni_one_sided_lower"] is None \
                    or summary["bonferroni_one_sided_lower"] <= direct["economic_margin"]:
                left_wins_all = False
        if left_wins_all:
            winners.append(left)
    return (winners[0] if len(winners) == 1 else None), summaries


def _question_status(candidates: dict[str, dict], plan: dict, *, direct_pairwise_winner: str | None = None) -> tuple[str, str | None]:
    """Map frozen evidence gates to one question-level five-state advisory status."""
    max_weeks = max((summary["divergence_weeks"] for summary in candidates.values()), default=0)
    passers = [arm for arm, summary in candidates.items() if summary["formal_pass"]]
    if max_weeks < plan["statistics"]["minimum_divergence_weeks_before_formal_recommendation"]:
        return "continue_accumulation", None
    if not any(summary["formal_coverage_ready"] for summary in candidates.values()):
        return "inconclusive", None
    if len(passers) == 1:
        return "recommend_adopt_arm", passers[0]
    if len(passers) > 1:
        return ("recommend_adopt_arm", direct_pairwise_winner) if direct_pairwise_winner else ("inconclusive", None)
    if max_weeks >= plan["statistics"]["retire_after_divergence_weeks"]:
        return "recommend_discard_arm", None
    return "recommend_retain_balanced", None


def _latest_reached_formal_look(availability: dict[str, int], plan: dict) -> int | None:
    """Select one of the preregistered frozen looks; intermediate weeks never create a new look."""
    reached = [
        look for look in plan["statistics"]["formal_look_divergence_weeks"]
        if max(availability.values(), default=0) >= look
    ]
    return reached[-1] if reached else None


def _formal_look_alpha(plan: dict, formal_look: int) -> float:
    """Return the preregistered one-sided family alpha allocated to one formal look."""
    looks = plan["statistics"]["formal_look_divergence_weeks"]
    spending = plan["statistics"]["one_sided_alpha_spending"]
    try:
        return spending[looks.index(formal_look)]
    except ValueError as exc:
        raise ForwardPolicyComparisonLedgerError("formal look has no preregistered alpha allocation") from exc


def evaluate_forward_policy_comparison_ledger(ledger: object) -> dict:
    """Return de-identified five-state recommendations; it never persists or switches production."""
    ledger = validate_forward_policy_comparison_ledger(ledger)
    plan, all_records = load_forward_policy_statistical_plan(), list(ledger["records"])
    active_epoch = baseline_epoch_sha256()
    records = all_records
    segments = _segment_orthogonality_summary(records)
    # Option (ii), user-ratified 2026-07-18 (register R-RE): cross-epoch RE ADJUDICATION is
    # deferred. Single-qualified-epoch block inference is authoritative; once the counted window
    # spans >=2 effect-surface segments the pooled CI/placebo are still fixed-effect (no
    # Hartung-Knapp / heterogeneity gate), so a cross-epoch adopt would overstate confidence ->
    # emit inconclusive. Segment identity + per-record bindings are still recorded/validated.
    multi_segment = len(segments) >= 2
    questions = plan["policy_scope"]["factor_questions"]
    result = {"schema_name": "us_short_forward_policy_comparison_adjudication", "schema_version": "1.0.0",
              "comparison_contract_sha256": statistical_plan_sha256(), "baseline_epoch_sha256": active_epoch,
              "counted_week_count": len(records), "archived_epoch_counted_week_count": 0,
              "segments": segments, "multi_segment_cross_epoch_adjudication_deferred": multi_segment,
              "questions": {}, "boundary": dict(BOUNDARY)}
    for question, arms in questions.items():
        arms_without_balanced = [arm for arm in arms if arm != SELECTION_POLICY_IDS[0]]
        availability = {arm: _arm_summary(records, arm, plan)["available_divergence_weeks"] for arm in arms_without_balanced}
        formal_look = _latest_reached_formal_look(availability, plan)
        if formal_look is None:
            candidates = {arm: _arm_summary(records, arm, plan) for arm in arms_without_balanced}
            for summary in candidates.values():
                summary.update({"formal_coverage_ready": False, "formal_pass": False, "holm_adjusted_pvalue": None})
            status, arm, direct_summaries = "continue_accumulation", None, []
        else:
            formal_alpha = _formal_look_alpha(plan, formal_look)
            candidates = {
                arm: _arm_summary(records, arm, plan, formal_look=formal_look, formal_alpha=formal_alpha)
                for arm in arms_without_balanced
            }
            _apply_formal_gates(candidates, plan, formal_alpha=formal_alpha)
            if multi_segment:
                # Cross-epoch adjudication deferred (option ii): report the per-arm evidence but
                # never adopt/discard on a fixed-effect pool of >=2 heterogeneous segments.
                status, arm, direct_summaries = "inconclusive", None, []
            else:
                passers = [arm for arm, summary in candidates.items() if summary["formal_pass"]]
                direct_winner, direct_summaries = _direct_pairwise_winner(
                    records, passers, formal_look=formal_look, formal_alpha=formal_alpha, plan=plan,
                ) if len(passers) > 1 else (None, [])
                status, arm = _question_status(candidates, plan, direct_pairwise_winner=direct_winner)
        result["questions"][question] = {
            "status": status, "recommended_arm": arm, "formal_look_divergence_weeks": formal_look,
            "cross_epoch_adjudication_deferred": bool(formal_look is not None and multi_segment),
            "arms": candidates, "direct_pairwise_final": direct_summaries,
            "requires_user_decision": status.startswith("recommend_"),
        }
    return result


def build_forward_policy_decision_receipts(adjudication: object) -> dict[str, dict]:
    """Build immutable, de-identified pending receipts for every formal recommendation.

    A receipt is deliberately not a production switch.  ``decision`` and ``decided_at`` remain
    null until :func:`record_forward_policy_user_decision` binds the user's explicit action.
    """
    if not isinstance(adjudication, dict) or adjudication.get("schema_name") != "us_short_forward_policy_comparison_adjudication" \
            or adjudication.get("comparison_contract_sha256") != statistical_plan_sha256():
        raise ForwardPolicyComparisonLedgerError("decision receipt requires the current comparison adjudication")
    receipts = {}
    for question, block in adjudication.get("questions", {}).items():
        status, arm = block.get("status"), block.get("recommended_arm")
        if status not in {"recommend_adopt_arm", "recommend_retain_balanced", "recommend_discard_arm"}:
            continue
        # Retaining balanced has a concrete baseline arm.  A retirement is a question-level
        # disposition, so it carries an explicit, de-identified sentinel rather than inventing a winner.
        arm_id = arm or (SELECTION_POLICY_IDS[0] if status == "recommend_retain_balanced" else "question_level_disposition")
        verdict = {"question_id": question, "status": status, "recommended_arm": arm, "arms": block.get("arms")}
        receipts[question] = {
            "question_id": question, "arm_id": arm_id, "status": status,
            "verdict_sha256": _canonical_sha256(verdict), "contract_sha256": statistical_plan_sha256(),
            "baseline_epoch_sha256": adjudication["baseline_epoch_sha256"],
            "decision": None, "decided_at": None,
        }
    return receipts


def record_forward_policy_user_decision(*, ledger: object, receipt: object, decision: object, decided_at: object) -> dict:
    """Persist an explicit accept/reject/defer acknowledgement without changing ``balanced``."""
    current = validate_forward_policy_comparison_ledger(ledger)
    if not isinstance(receipt, dict) or set(receipt) != {"question_id", "arm_id", "status", "verdict_sha256", "contract_sha256", "baseline_epoch_sha256", "decision", "decided_at"} \
            or receipt.get("decision") is not None or receipt.get("decided_at") is not None \
            or not isinstance(receipt.get("question_id"), str) or not isinstance(receipt.get("arm_id"), str) \
            or not _sha(receipt.get("verdict_sha256")) or receipt.get("contract_sha256") != statistical_plan_sha256() \
            or receipt.get("baseline_epoch_sha256") != baseline_epoch_sha256():
        raise ForwardPolicyComparisonLedgerError("user decision receipt is invalid or already decided")
    if decision not in {"accept", "reject", "defer"} or not _strict_date(decided_at):
        raise ForwardPolicyComparisonLedgerError("user decision must be accept/reject/defer with a strict decision date")
    question = receipt["question_id"]
    decision_key = f"{receipt['baseline_epoch_sha256']}:{question}"
    if decision_key in current["user_decisions"]:
        raise ForwardPolicyComparisonLedgerError("a comparison question already has an immutable user decision")
    expected = build_forward_policy_decision_receipts(evaluate_forward_policy_comparison_ledger(current)).get(question)
    if expected != receipt:
        raise ForwardPolicyComparisonLedgerError("user decision receipt is not the current immutable adjudication receipt")
    updated = dict(current)
    updated["user_decisions"] = dict(current["user_decisions"])
    updated["user_decisions"][decision_key] = {"receipt": dict(receipt), "decision": decision, "decided_at": decided_at}
    validate_forward_policy_comparison_ledger(updated)
    return updated


def render_forward_policy_comparison_banner(adjudication: object, *, ledger: object | None = None) -> str:
    """Return one de-identified persistent top-banner line for a weekly report sidecar/injection."""
    if not isinstance(adjudication, dict) or adjudication.get("schema_name") != "us_short_forward_policy_comparison_adjudication":
        raise ForwardPolicyComparisonLedgerError("comparison banner requires an adjudication result")
    items = []
    for question, block in adjudication.get("questions", {}).items():
        status, arm = block.get("status"), block.get("recommended_arm")
        label = f"{question}={status}" + (f"({arm})" if arm else "")
        items.append(label)
    current_epoch = adjudication.get("baseline_epoch_sha256")
    acknowledged = set(validate_forward_policy_comparison_ledger(ledger)["user_decisions"]) if ledger is not None else set()
    action_required = any(f"{current_epoch}:{question}" not in acknowledged and block.get("requires_user_decision")
                          for question, block in adjudication.get("questions", {}).items())
    prefix = "US-SHORT A1 对比轨｜需人工确认｜" if action_required else "US-SHORT A1 对比轨｜"
    return prefix + "；".join(items or ["continue_accumulation"]) + "｜仅建议，不自动切换 balanced"


def append_source_bound_forward_policy_week(*, ledger: object, private_week_record: object, source_receipt: object) -> dict:
    """Append one ready, source-bound forward week immutably in memory (idempotent on exact duplicate)."""
    current = validate_forward_policy_comparison_ledger(ledger)
    evidence = build_forward_policy_h10_weekly_evidence(private_week_record)
    if evidence["projection_status"] != "ready_for_private_accumulation":
        raise ForwardPolicyComparisonLedgerError("whole-week no-count remains recorded upstream and cannot advance the evidence clock")
    receipt = validate_same_run_source_receipt(source_receipt, evidence["source_private_week_record"])
    date = evidence["capture_binding"]["decision_date"]
    item = {"decision_date": date, "weekly_evidence": evidence, "source_receipt": receipt}
    records = list(current["records"])
    if records and date < records[-1]["decision_date"]:
        raise ForwardPolicyComparisonLedgerError("historical replay/backfill cannot be appended to the forward ledger")
    if records and date == records[-1]["decision_date"]:
        if records[-1] != item:
            raise ForwardPolicyComparisonLedgerError("same decision date has conflicting source-bound comparison evidence")
        return current
    next_ledger = dict(current); next_ledger["records"] = records + [item]
    validate_forward_policy_comparison_ledger(next_ledger)
    return next_ledger


def persist_source_bound_forward_policy_week(*, ledger_path: object, ledger: object, private_week_record: object, source_receipt: object) -> dict:
    """Atomically persist a private ledger only after all gates and its post-write form validate."""
    path = Path(ledger_path)
    if not path.is_absolute() or path.resolve().parent != PRIVATE_ROOT.resolve() or path.name != "forward_policy_comparison_ledger.json":
        raise ForwardPolicyComparisonLedgerError("comparison ledger must use the canonical private shadow_compare path")
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise ForwardPolicyComparisonLedgerError(str(exc)) from exc
    updated = append_source_bound_forward_policy_week(ledger=ledger, private_week_record=private_week_record, source_receipt=source_receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    adjudication = evaluate_forward_policy_comparison_ledger(updated)
    return {"ledger": updated, "adjudication": adjudication, "banner": render_forward_policy_comparison_banner(adjudication, ledger=updated)}
