# -*- coding: utf-8 -*-
"""US-short A1 comparison v2: pure private H5/H10/H20 outcome production.

The first v2 blade freezes the Pass2-clean pool and policy selections but deliberately does not retain a
counterfactual entry order for every pool member.  This module is the narrow, provider-free bridge for the next
stage: it accepts exactly one caller-supplied model-paper order and exactly twenty caller-supplied daily bars per
member of that frozen pool, then produces H5/H10/H20 after-cost candidate values.  Every policy later reads the
same per-ticker values; a policy cannot inject a different execution rule for its own selection.

It reuses the established model-paper fill, multi-day stop/take-profit, net-result, and corporate-action gates.
A position still open at H5/H10/H20 receives a comparison-only close mark with the frozen round-trip cost.  That
mark never becomes a production exit and this module never writes it into the model-paper ledger.  If the
corporate-action gate is not evaluable or any common-pool series is incomplete, it emits a whole-week
``data_degraded_whole_week_no_count`` packet with no candidate values.  Malformed complete data and malformed
contracts fail closed instead of being silently counted as data degradation.

Pure/offline: no provider, network, persistence, scheduler, production selection change, broker/order automation,
ship-gate evidence, or A-share interaction.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
from pathlib import Path

import jsonschema

from engine.us_short_forward_policy_shadow_stage import (
    ForwardPolicyShadowStageError,
    validate_forward_shadow_selection_record,
)
from engine.us_short_forward_policy_statistical_plan import statistical_plan_sha256
from engine.us_short_paper_eval_gate import (
    PaperEvalGateError,
    paper_performance_evaluability_from_offline_evidence,
)
from engine.us_short_paper_fill import PaperFillError, simulate_fill
from engine.us_short_paper_multi_day_exit import PaperMultiDayExitError, simulate_multi_day_exit
from engine.us_short_paper_net_result import PaperNetResultError, paper_net_result


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_outcome_packet.schema.json"
HORIZONS = (("h5", 5), ("h10", 10), ("h20", 20))
_COST_KEYS = frozenset({"commission_fee", "slippage_bps", "spread_cost"})
BOUNDARY = {
    "track": "comparison_non_production",
    "evidence_level": "forward_policy_private_paper_outcome",
    "shadow_counts_ship_gate": False,
    "full_size_ship_gate_allowed": False,
    "changes_primary_selection": False,
    "provider_calls_added": False,
    "broker_or_order_automation_allowed": False,
    "writes_outcome_data": False,
    "evaluation_mark_is_production_exit": False,
    "evaluation_mark_changes_model_paper_ledger": False,
}
_PACKET_KEYS = frozenset({
    "schema_name", "schema_version", "outcome_status", "capture_binding", "common_selection_pool",
    "common_order_snapshot_sha256", "common_price_snapshot_sha256", "frozen_cost_prior", "adjustment_evaluability",
    "entry_session_date", "outcome_as_of", "horizon_session_dates", "degradation_reason", "candidate_outcomes", "boundary",
})
_HORIZON_RESULT_KEYS = frozenset({
    "outcome", "model_paper_status", "realized", "gross_return", "total_cost_fraction",
    "candidate_after_cost_net_return", "unfilled_cash",
})


class ForwardPolicyOutcomeError(ValueError):
    """The frozen capture, injected common order/bars, or private outcome packet is unsafe to use."""


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _strict_yyyymmdd(value: object) -> bool:
    if not (type(value) is str and value.isascii() and len(value) == 8 and value.isdigit()):
        return False
    try:
        datetime.date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return False
    return True


def _finite(value: object) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _finite_positive(value: object) -> bool:
    return _finite(value) and value > 0.0


def _load_schema() -> dict:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyOutcomeError("cannot load forward-policy outcome packet schema") from exc


def _validate_schema(packet: object) -> None:
    try:
        jsonschema.validate(packet, _load_schema())
    except jsonschema.ValidationError as exc:
        raise ForwardPolicyOutcomeError(f"forward-policy outcome packet schema rejected: {exc.message}") from exc


def _validate_cost_prior(cost_prior: object) -> tuple[dict, float]:
    if not isinstance(cost_prior, dict) or set(cost_prior) != _COST_KEYS:
        raise ForwardPolicyOutcomeError("cost_prior must contain exactly commission_fee, slippage_bps, and spread_cost")
    if any(not (_finite(cost_prior[key]) and cost_prior[key] >= 0.0) for key in _COST_KEYS):
        raise ForwardPolicyOutcomeError("cost_prior values must be finite non-negative numbers")
    frozen = {key: float(cost_prior[key]) for key in ("commission_fee", "slippage_bps", "spread_cost")}
    total = frozen["commission_fee"] + frozen["spread_cost"] + frozen["slippage_bps"] / 10000.0
    return frozen, total


def _capture_binding(capture: dict) -> dict:
    return {
        "decision_date": capture["decision_date"],
        "price_basis_date": capture["price_basis_date"],
        "source_context_sha256": capture["source_context_sha256"],
        "comparison_contract_sha256": capture["comparison_contract_sha256"],
        "baseline_epoch_sha256": capture["baseline_epoch_sha256"],
        "common_selection_pool_sha256": capture["common_selection_pool_sha256"],
        "capture_sha256": _canonical_sha256(capture),
    }


def _validated_capture(capture: object) -> tuple[dict, list[str]]:
    try:
        capture = validate_forward_shadow_selection_record(capture)
    except ForwardPolicyShadowStageError as exc:
        raise ForwardPolicyOutcomeError(f"invalid v2 Cut-A capture: {exc}") from exc
    if capture["comparison_contract_sha256"] != statistical_plan_sha256():
        raise ForwardPolicyOutcomeError("Cut-A capture is bound to a stale comparison contract")
    return capture, list(capture["common_selection_pool"])


def _validate_orders(orders_by_ticker: object, *, common_pool: list[str]) -> dict:
    if not isinstance(orders_by_ticker, dict):
        raise ForwardPolicyOutcomeError("orders_by_ticker must be a ticker-keyed dict")
    if set(orders_by_ticker) != set(common_pool):
        raise ForwardPolicyOutcomeError(
            "orders_by_ticker must cover exactly the Pass2-clean common pool; policy-specific/missing/extra orders are refused"
        )
    if any(not isinstance(orders_by_ticker[ticker], dict) for ticker in common_pool):
        raise ForwardPolicyOutcomeError("each common-pool outcome order must be a dict")
    # Retain caller order values as a canonical snapshot for the later private accumulator.  The established fill
    # engine validates order semantics before each calculation; this local gate locks only common-pool coverage.
    return {ticker: dict(orders_by_ticker[ticker]) for ticker in common_pool}


def _validate_bar_shape(bar: object, *, ticker: str, expected_index: int) -> tuple[str, dict]:
    if not isinstance(bar, dict):
        raise ForwardPolicyOutcomeError(f"{ticker} session {expected_index} bar must be a dict")
    if bar.get("session_index") != expected_index:
        raise ForwardPolicyOutcomeError(f"{ticker} session_index must be the exact 1..20 trading-session sequence")
    session_date = bar.get("session_date")
    if not _strict_yyyymmdd(session_date):
        raise ForwardPolicyOutcomeError(f"{ticker} session_date must be a strict real YYYYMMDD")
    values = {field: bar.get(field) for field in ("open", "high", "low", "close")}
    if any(not _finite_positive(value) for value in values.values()):
        raise ForwardPolicyOutcomeError(f"{ticker} session {expected_index} OHLC must be finite and positive")
    if not (values["low"] <= values["open"] <= values["high"] and values["low"] <= values["close"] <= values["high"]):
        raise ForwardPolicyOutcomeError(f"{ticker} session {expected_index} OHLC is inconsistent")
    return session_date, dict(bar)


def _complete_common_bars(daily_bars_by_ticker: object, *, common_pool: list[str]) -> tuple[dict | None, dict | None]:
    """Return normalized bars/date markers, or ``(None, None)`` only for genuine incomplete series.

    A caller may have no row or fewer than 20 rows for a pool member when the forward window has not yet completed.
    That is a normal whole-week no-count state.  Extra tickers, malformed rows, mismatched calendars, and ambiguous
    longer windows are contract errors rather than silently tolerated data degradation.
    """
    if not isinstance(daily_bars_by_ticker, dict):
        raise ForwardPolicyOutcomeError("daily_bars_by_ticker must be a ticker-keyed dict")
    extra = set(daily_bars_by_ticker) - set(common_pool)
    if extra:
        raise ForwardPolicyOutcomeError("daily_bars_by_ticker contains a ticker outside the Pass2-clean common pool")
    if any(ticker not in daily_bars_by_ticker for ticker in common_pool):
        return None, None

    normalized, reference_dates = {}, None
    for ticker in common_pool:
        series = daily_bars_by_ticker[ticker]
        if not isinstance(series, list):
            raise ForwardPolicyOutcomeError(f"{ticker} daily bar series must be a list")
        if len(series) < HORIZONS[-1][1]:
            return None, None
        if len(series) != HORIZONS[-1][1]:
            raise ForwardPolicyOutcomeError("daily bar series must contain exactly the frozen H20 window, not a look-ahead tail")
        dates, bars = [], []
        for index, bar in enumerate(series, start=1):
            session_date, normalized_bar = _validate_bar_shape(bar, ticker=ticker, expected_index=index)
            dates.append(session_date)
            bars.append(normalized_bar)
        if any(later <= earlier for earlier, later in zip(dates, dates[1:])):
            raise ForwardPolicyOutcomeError(f"{ticker} session dates must be strictly increasing")
        if reference_dates is None:
            reference_dates = dates
        elif dates != reference_dates:
            raise ForwardPolicyOutcomeError("all common-pool members must use the same H5/H10/H20 session calendar")
        normalized[ticker] = bars
    return normalized, {
        "entry": reference_dates[0],
        "h5": reference_dates[4],
        "h10": reference_dates[9],
        "h20": reference_dates[19],
    }


def _horizon_fill_result(order: dict, bars: list[dict], *, horizon: int) -> dict:
    entry = simulate_fill(order, bars[0])
    if entry["status"] != "filled_held":
        return entry
    held = {
        "fill_price": entry["fill_price"],
        "stop_clear_price": order["stop_clear_price"],
        "take_profit_exit_price": order["take_profit_exit_price"],
    }
    for bar in bars[1:horizon]:
        updated = simulate_multi_day_exit(held, [bar])
        if updated["status"] != "filled_held":
            return updated
    return entry


def _horizon_outcome(order: dict, bars: list[dict], *, horizon: int, cost_prior: dict, total_cost: float) -> dict:
    fill_result = _horizon_fill_result(order, bars, horizon=horizon)
    status = fill_result["status"]
    if status == "filled_held":
        fill_price = fill_result["fill_price"]
        gross = (bars[horizon - 1]["close"] - fill_price) / fill_price
        return {
            "outcome": "evaluation_mark_only",
            "model_paper_status": "filled_held",
            "realized": False,
            "gross_return": gross,
            "total_cost_fraction": total_cost,
            "candidate_after_cost_net_return": gross - total_cost,
            "unfilled_cash": False,
        }
    net = paper_net_result(fill_result, cost_prior=cost_prior)
    if status == "not_filled":
        return {
            "outcome": "cash_unfilled",
            "model_paper_status": "not_filled",
            "realized": True,
            "gross_return": 0.0,
            "total_cost_fraction": 0.0,
            "candidate_after_cost_net_return": 0.0,
            "unfilled_cash": True,
        }
    return {
        "outcome": "model_paper_exit",
        "model_paper_status": status,
        "realized": True,
        "gross_return": net["gross_return"],
        "total_cost_fraction": net["cost_fraction"],
        "candidate_after_cost_net_return": net["net_return"],
        "unfilled_cash": False,
    }


def _base_packet(*, capture: dict, common_pool: list[str], orders: dict, cost_prior: dict, adjustment: dict) -> dict:
    return {
        "schema_name": "us_short_forward_policy_outcome_packet",
        "schema_version": "1.0.0",
        "capture_binding": _capture_binding(capture),
        "common_selection_pool": list(common_pool),
        "common_order_snapshot_sha256": _canonical_sha256(orders),
        "common_price_snapshot_sha256": None,
        "frozen_cost_prior": dict(cost_prior),
        "adjustment_evaluability": adjustment,
        "entry_session_date": None,
        "boundary": dict(BOUNDARY),
    }


def _degraded_packet(*, capture: dict, common_pool: list[str], orders: dict, cost_prior: dict,
                     adjustment: dict, reason: str) -> dict:
    packet = _base_packet(
        capture=capture, common_pool=common_pool, orders=orders, cost_prior=cost_prior, adjustment=adjustment,
    )
    packet.update({
        "outcome_status": "data_degraded_whole_week_no_count",
        "outcome_as_of": None,
        "horizon_session_dates": None,
        "degradation_reason": reason,
        "candidate_outcomes": [],
    })
    validate_forward_policy_outcome_packet(packet)
    return packet


def produce_forward_policy_outcome(*, capture: object, orders_by_ticker: object, daily_bars_by_ticker: object,
                                   cost_prior: object, adjustment_evidence: object) -> dict:
    """Produce one private comparison outcome packet from one frozen Cut-A capture.

    ``orders_by_ticker`` and ``daily_bars_by_ticker`` must span exactly the capture's Pass2-clean common pool;
    they are not policy-keyed, so policy-specific execution changes cannot enter this layer.  H5/H10/H20 are trading
    session indices 5/10/20 inclusive of the first regular-session entry bar.  A held position is marked at each
    horizon only for the comparison packet; it remains open in the separate production paper ledger.  This function
    returns an in-memory private packet and never writes a file.
    """
    frozen_capture, common_pool = _validated_capture(capture)
    frozen_orders = _validate_orders(orders_by_ticker, common_pool=common_pool)
    frozen_cost, total_cost = _validate_cost_prior(cost_prior)
    try:
        adjustment = paper_performance_evaluability_from_offline_evidence(adjustment_evidence)
    except PaperEvalGateError as exc:
        raise ForwardPolicyOutcomeError(f"invalid corporate-action adjustment evidence: {exc}") from exc
    if adjustment_evidence.get("decision_date") != frozen_capture["decision_date"]:
        raise ForwardPolicyOutcomeError("corporate-action adjustment evidence decision_date must match the Cut-A capture")
    if adjustment["status"] != "evaluable":
        return _degraded_packet(
            capture=frozen_capture, common_pool=common_pool, orders=frozen_orders, cost_prior=frozen_cost,
            adjustment=adjustment, reason="adjustment_evidence_not_evaluable",
        )

    bars, horizon_dates = _complete_common_bars(daily_bars_by_ticker, common_pool=common_pool)
    if bars is None:
        return _degraded_packet(
            capture=frozen_capture, common_pool=common_pool, orders=frozen_orders, cost_prior=frozen_cost,
            adjustment=adjustment, reason="incomplete_price_series",
        )

    candidate_outcomes = []
    try:
        for ticker in common_pool:
            candidate_outcomes.append({
                "ticker": ticker,
                **{
                    label: _horizon_outcome(
                        frozen_orders[ticker], bars[ticker], horizon=horizon, cost_prior=frozen_cost,
                        total_cost=total_cost,
                    )
                    for label, horizon in HORIZONS
                },
            })
    except (PaperFillError, PaperMultiDayExitError, PaperNetResultError, KeyError) as exc:
        raise ForwardPolicyOutcomeError("common-pool model-paper outcome could not be produced") from exc

    packet = _base_packet(
        capture=frozen_capture, common_pool=common_pool, orders=frozen_orders, cost_prior=frozen_cost,
        adjustment=adjustment,
    )
    packet.update({
        "outcome_status": "ready_for_comparison",
        "common_price_snapshot_sha256": _canonical_sha256(bars),
        "entry_session_date": horizon_dates["entry"],
        "outcome_as_of": horizon_dates["h20"],
        "horizon_session_dates": {label: horizon_dates[label] for label, _ in HORIZONS},
        "degradation_reason": None,
        "candidate_outcomes": candidate_outcomes,
    })
    validate_forward_policy_outcome_packet(packet)
    return packet


def _validate_horizon_result(value: object, *, label: str, total_cost: float) -> None:
    if not isinstance(value, dict) or set(value) != _HORIZON_RESULT_KEYS:
        raise ForwardPolicyOutcomeError(f"{label} horizon result key set drifted")
    if any(not _finite(value[key]) for key in ("gross_return", "total_cost_fraction", "candidate_after_cost_net_return")):
        raise ForwardPolicyOutcomeError(f"{label} horizon result contains a non-finite number")
    outcome, status = value["outcome"], value["model_paper_status"]
    if type(value["realized"]) is not bool or type(value["unfilled_cash"]) is not bool:
        raise ForwardPolicyOutcomeError(f"{label} horizon booleans must be literal bools")
    gross, cost, net = value["gross_return"], value["total_cost_fraction"], value["candidate_after_cost_net_return"]
    if cost < 0.0 or not math.isclose(net, gross - cost, abs_tol=1e-12):
        raise ForwardPolicyOutcomeError(f"{label} net return must equal gross return minus total cost")
    if outcome == "cash_unfilled":
        expected = status == "not_filled" and value["realized"] is True and value["unfilled_cash"] is True \
            and gross == 0.0 and cost == 0.0 and net == 0.0
    elif outcome == "model_paper_exit":
        expected = status in {"filled_stopped", "filled_tp_exit"} and value["realized"] is True \
            and value["unfilled_cash"] is False and math.isclose(cost, total_cost, abs_tol=1e-12)
    else:
        expected = status == "filled_held" and value["realized"] is False and value["unfilled_cash"] is False \
            and math.isclose(cost, total_cost, abs_tol=1e-12)
    if not expected:
        raise ForwardPolicyOutcomeError(f"{label} outcome/status/cost invariant drifted")


def validate_forward_policy_outcome_packet(packet: object) -> dict:
    """Fail closed on private outcome identity, pool/order binding, no-count, or H5/H10/H20 arithmetic drift."""
    if not isinstance(packet, dict) or set(packet) != _PACKET_KEYS:
        raise ForwardPolicyOutcomeError("forward-policy outcome packet must carry its exact closed-world key set")
    _validate_schema(packet)
    if packet["boundary"] != BOUNDARY:
        raise ForwardPolicyOutcomeError("forward-policy outcome boundary drifted from comparison-only/no-write policy")
    binding = packet["capture_binding"]
    if not (_strict_yyyymmdd(binding["decision_date"]) and _strict_yyyymmdd(binding["price_basis_date"])
            and binding["price_basis_date"] < binding["decision_date"]):
        raise ForwardPolicyOutcomeError("capture binding decision/price dates are invalid")
    if binding["comparison_contract_sha256"] != statistical_plan_sha256():
        raise ForwardPolicyOutcomeError("outcome packet comparison-contract digest drifted")
    common_pool = packet["common_selection_pool"]
    if len(common_pool) != len(set(common_pool)) or any(type(ticker) is not str or not ticker for ticker in common_pool):
        raise ForwardPolicyOutcomeError("outcome common_selection_pool must be an ordered unique ticker list")
    if binding["common_selection_pool_sha256"] != _canonical_sha256(common_pool):
        raise ForwardPolicyOutcomeError("outcome common_selection_pool digest is inconsistent")
    if not isinstance(packet["common_order_snapshot_sha256"], str) or len(packet["common_order_snapshot_sha256"]) != 64:
        raise ForwardPolicyOutcomeError("common order snapshot digest is invalid")
    cost_prior, total_cost = _validate_cost_prior(packet["frozen_cost_prior"])
    if cost_prior != packet["frozen_cost_prior"]:
        raise ForwardPolicyOutcomeError("frozen cost prior must use stable numeric values")
    adjustment = packet["adjustment_evaluability"]
    if adjustment["full_size_ship_gate_allowed"] is not False \
            or adjustment["ship_gate_evidence_level"] != "paper_not_live_normalized":
        raise ForwardPolicyOutcomeError("adjustment evaluability cannot authorize the full-size ship gate")

    status = packet["outcome_status"]
    if status == "data_degraded_whole_week_no_count":
        if packet["candidate_outcomes"] != [] or packet["outcome_as_of"] is not None \
                or packet["entry_session_date"] is not None or packet["horizon_session_dates"] is not None \
                or packet["common_price_snapshot_sha256"] is not None or packet["degradation_reason"] is None:
            raise ForwardPolicyOutcomeError("whole-week no-count packet must not carry a partial outcome value")
        if packet["degradation_reason"] == "adjustment_evidence_not_evaluable" and adjustment["status"] != "not_evaluable":
            raise ForwardPolicyOutcomeError("adjustment no-count packet requires a non-evaluable corporate-action gate")
        if packet["degradation_reason"] == "incomplete_price_series" and adjustment["status"] != "evaluable":
            raise ForwardPolicyOutcomeError("incomplete-price no-count packet requires a separately evaluable adjustment gate")
        return packet

    if adjustment["status"] != "evaluable" or packet["degradation_reason"] is not None:
        raise ForwardPolicyOutcomeError("ready outcome packet requires an evaluable gate and no degradation reason")
    dates = packet["horizon_session_dates"]
    if not isinstance(dates, dict) or not all(_strict_yyyymmdd(dates[key]) for key, _ in HORIZONS):
        raise ForwardPolicyOutcomeError("ready outcome packet must carry strict H5/H10/H20 session dates")
    entry_date = packet["entry_session_date"]
    if not _strict_yyyymmdd(entry_date) or entry_date < binding["decision_date"]:
        raise ForwardPolicyOutcomeError("entry session must be the decision session or a later first regular session")
    if not (binding["decision_date"] < dates["h5"] < dates["h10"] < dates["h20"]
            and entry_date < dates["h5"] and packet["outcome_as_of"] == dates["h20"]):
        raise ForwardPolicyOutcomeError("outcome packet must close its finite window at the H20 session")
    price_digest = packet["common_price_snapshot_sha256"]
    if not isinstance(price_digest, str) or len(price_digest) != 64:
        raise ForwardPolicyOutcomeError("ready outcome packet must bind its canonical common-pool price snapshot")
    candidates = packet["candidate_outcomes"]
    if not isinstance(candidates, list) or [row.get("ticker") if isinstance(row, dict) else None for row in candidates] != common_pool:
        raise ForwardPolicyOutcomeError("candidate outcomes must cover exactly the ordered Pass2-clean common pool")
    for candidate in candidates:
        if set(candidate) != {"ticker", "h5", "h10", "h20"}:
            raise ForwardPolicyOutcomeError("candidate outcome key set drifted")
        for label, _horizon in HORIZONS:
            _validate_horizon_result(candidate[label], label=f"{candidate['ticker']} {label}", total_cost=total_cost)
    return packet
