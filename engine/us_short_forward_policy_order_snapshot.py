# -*- coding: utf-8 -*-
"""US-short A1 comparison v2: pure common-candidate order-snapshot production.

The v2 Cut-A selection capture freezes every Pass2-clean candidate before the six policy heads choose their
Top15 sets.  This module is the narrow next seam: it takes one price-basis-date-bound input for *every* member of
that frozen pool, runs the established candidate price-analysis path under one shared market regime, and returns
one common model-paper order snapshot.  No policy ID is accepted here, so a head cannot substitute a different
entry, stop, target, sub-mode, or market regime for its own names.

The existing provider/Batch5 context currently does not supply all-candidate OHLCV/ATR inputs.  Therefore this is
an in-memory consumer/producer only: a later authorized source-capture/writer must supply the exact same
Pass2-clean input map and bind its digest before a real week can be counted.  If any common-pool candidate cannot
form an executable order, the module returns a whole-week no-count packet rather than silently dropping that
candidate or inventing an order.  It does not fetch prices, write a snapshot, produce forward outcomes, update an
accumulator, change the primary system, or authorize a ship-gate/broker path.
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
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_regime import REGIMES
from engine.us_short_weekend_analysis import WeekendAnalysisError, analyze_rows


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_order_snapshot_packet.schema.json"
_PRICE_INPUT_KEYS = frozenset({
    "ticker", "price_input", "sub_mode", "defensive_breakout_probe_allowed", "overextension",
})
_ORDER_KEYS = frozenset({
    "order_type", "order_expiry", "valid_entry_low", "valid_entry_high", "limit_order_price",
    "breakout_entry_price", "stop_clear_price", "take_profit_exit_price",
})
_PACKET_KEYS = frozenset({
    "schema_name", "schema_version", "order_snapshot_status", "capture_binding", "common_selection_pool",
    "common_price_input_snapshot_sha256", "market_risk_regime", "orders_by_ticker",
    "common_order_snapshot_sha256", "non_executable_tickers", "degradation_reason", "boundary",
})
BOUNDARY = {
    "track": "comparison_non_production",
    "evidence_level": "forward_policy_common_order_snapshot",
    "shadow_counts_ship_gate": False,
    "full_size_ship_gate_allowed": False,
    "changes_primary_selection": False,
    "provider_calls_added": False,
    "broker_or_order_automation_allowed": False,
    "writes_order_snapshot": False,
    "writes_outcome_data": False,
}


class ForwardPolicyOrderSnapshotError(ValueError):
    """The frozen selection capture or its common candidate-price inputs are unsafe to use."""


def _canonical_sha256(value: object) -> str:
    try:
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ForwardPolicyOrderSnapshotError("snapshot input is not finite canonical JSON") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _strict_yyyymmdd(value: object) -> bool:
    if not (type(value) is str and value.isascii() and len(value) == 8 and value.isdigit()):
        return False
    try:
        datetime.date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return False
    return True


def _finite_positive(value: object) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0.0
    except OverflowError:
        return False


def _load_schema() -> dict:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyOrderSnapshotError("cannot load forward-policy common-order snapshot schema") from exc


def _validate_schema(packet: object) -> None:
    try:
        jsonschema.validate(packet, _load_schema())
    except jsonschema.ValidationError as exc:
        raise ForwardPolicyOrderSnapshotError(
            f"forward-policy common-order snapshot schema rejected: {exc.message}"
        ) from exc


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
        raise ForwardPolicyOrderSnapshotError(f"invalid v2 Cut-A capture: {exc}") from exc
    if capture["comparison_contract_sha256"] != statistical_plan_sha256():
        raise ForwardPolicyOrderSnapshotError("Cut-A capture is bound to a stale comparison contract")
    return capture, list(capture["common_selection_pool"])


def _normalized_price_rows(candidate_price_inputs_by_ticker: object, *, common_pool: list[str]) -> dict[str, dict]:
    if not isinstance(candidate_price_inputs_by_ticker, dict) or set(candidate_price_inputs_by_ticker) != set(common_pool):
        raise ForwardPolicyOrderSnapshotError(
            "candidate_price_inputs_by_ticker must cover exactly the Pass2-clean common selection pool"
        )
    normalized: dict[str, dict] = {}
    for ticker in common_pool:
        source = candidate_price_inputs_by_ticker[ticker]
        if not isinstance(source, dict) or set(source) != _PRICE_INPUT_KEYS:
            raise ForwardPolicyOrderSnapshotError(
                f"{ticker} common candidate price input must carry exactly {sorted(_PRICE_INPUT_KEYS)}"
            )
        if canonical_us_ticker(source["ticker"]) != ticker:
            raise ForwardPolicyOrderSnapshotError(
                f"{ticker} common candidate price input ticker does not match its canonical map key"
            )
        if not isinstance(source["price_input"], dict):
            raise ForwardPolicyOrderSnapshotError(f"{ticker} price_input must be a dict, never a fabricated fallback")
        if source["sub_mode"] not in {"pullback", "breakout"}:
            raise ForwardPolicyOrderSnapshotError(f"{ticker} sub_mode must be pullback or breakout")
        if type(source["defensive_breakout_probe_allowed"]) is not bool:
            raise ForwardPolicyOrderSnapshotError(f"{ticker} defensive_breakout_probe_allowed must be a literal bool")
        # Feed only the candidate price-control inputs into the established analysis stage.  The Pass2-clean status
        # is already re-derived from Cut-A; price planning is evidence-only at this stage, so no score/selection
        # field or policy-specific decision can leak into the order geometry.
        normalized[ticker] = {
            "ticker": ticker,
            "price_input": dict(source["price_input"]),
            "sub_mode": source["sub_mode"],
            "defensive_breakout_probe_allowed": source["defensive_breakout_probe_allowed"],
            "overextension": source["overextension"],
        }
    return normalized


def _analysis_rows(common_pool: list[str], normalized_inputs: dict[str, dict]) -> list[dict]:
    return [
        {
            "ticker": ticker,
            "row_source": "top15_candidate",
            "signals": {},
            **{key: value for key, value in normalized_inputs[ticker].items() if key != "ticker"},
        }
        for ticker in common_pool
    ]


def _order_from_price_result(price: object, *, ticker: str) -> dict:
    if not isinstance(price, dict) or price.get("executable") is not True \
            or price.get("price_engine_used") != "support_atr_engine":
        raise ForwardPolicyOrderSnapshotError(f"{ticker} price result is not an executable candidate price plan")
    fields = price.get("action_fields")
    if not isinstance(fields, dict):
        raise ForwardPolicyOrderSnapshotError(f"{ticker} executable price plan is missing action fields")
    order = {key: fields.get(key) for key in _ORDER_KEYS}
    _validate_order(order, ticker=ticker)
    return order


def _validate_order(order: object, *, ticker: str) -> None:
    if not isinstance(order, dict) or set(order) != _ORDER_KEYS:
        raise ForwardPolicyOrderSnapshotError(f"{ticker} common order key set drifted")
    order_type = order["order_type"]
    if order_type not in {"pullback_limit", "breakout_stop_limit"} \
            or order["order_expiry"] != "first_regular_session_only":
        raise ForwardPolicyOrderSnapshotError(f"{ticker} common order type/expiry is outside the frozen paper contract")
    for key in ("valid_entry_low", "valid_entry_high", "stop_clear_price", "take_profit_exit_price"):
        if not _finite_positive(order[key]):
            raise ForwardPolicyOrderSnapshotError(f"{ticker} common order {key} must be finite and positive")
    low, high = order["valid_entry_low"], order["valid_entry_high"]
    if not (low <= high and order["stop_clear_price"] < low and order["take_profit_exit_price"] > high):
        raise ForwardPolicyOrderSnapshotError(f"{ticker} common order has invalid passive-level geometry")
    if order_type == "pullback_limit":
        if not _finite_positive(order["limit_order_price"]) or order["breakout_entry_price"] is not None:
            raise ForwardPolicyOrderSnapshotError(f"{ticker} pullback order must carry only a finite limit entry")
        if not low <= order["limit_order_price"] <= high:
            raise ForwardPolicyOrderSnapshotError(f"{ticker} pullback limit must remain inside its entry band")
    else:
        # The shared price engine emits the breakout chase cap in ``limit_order_price`` as well as the
        # trigger in ``breakout_entry_price``.  The model-paper fill engine consumes the trigger; retaining
        # the cap binds the complete generated geometry instead of dropping a price-control field.
        if not _finite_positive(order["breakout_entry_price"]) or not _finite_positive(order["limit_order_price"]):
            raise ForwardPolicyOrderSnapshotError(f"{ticker} breakout order must carry finite trigger and chase cap")
        if not low <= order["breakout_entry_price"] <= high:
            raise ForwardPolicyOrderSnapshotError(f"{ticker} breakout entry must remain inside its entry band")
        if not math.isclose(order["limit_order_price"], high, abs_tol=1e-12):
            raise ForwardPolicyOrderSnapshotError(f"{ticker} breakout chase cap must equal its valid entry ceiling")


def _base_packet(*, capture: dict, common_pool: list[str], price_input_digest: str, market_risk_regime: str) -> dict:
    return {
        "schema_name": "us_short_forward_policy_order_snapshot_packet",
        "schema_version": "1.0.0",
        "capture_binding": _capture_binding(capture),
        "common_selection_pool": list(common_pool),
        "common_price_input_snapshot_sha256": price_input_digest,
        "market_risk_regime": market_risk_regime,
        "boundary": dict(BOUNDARY),
    }


def produce_forward_policy_order_snapshot(
    *, capture: object, price_basis_date: object, candidate_price_inputs_by_ticker: object,
    market_axis_regimes: object, prior_regime: object = None, prior_upgrade_count: object = 0,
) -> dict:
    """Return one in-memory common-candidate order snapshot for a validated v2 Cut-A capture.

    ``candidate_price_inputs_by_ticker`` must provide the same explicit price-control input shape for every frozen
    Pass2-clean candidate, not merely for a policy's eventual Top15.  The function calls the established
    ``analyze_rows`` candidate price path exactly once under the shared market regime; it writes nothing.  An
    unbuildable common candidate (including missing price structure) returns whole-week no-count with no partial
    order map, because a partial map would let future heads compare unequal execution universes.
    """
    frozen_capture, common_pool = _validated_capture(capture)
    if not _strict_yyyymmdd(price_basis_date) or price_basis_date != frozen_capture["price_basis_date"]:
        raise ForwardPolicyOrderSnapshotError("price_basis_date must be the exact strict date bound into Cut-A")
    if not isinstance(market_axis_regimes, dict):
        raise ForwardPolicyOrderSnapshotError("market_axis_regimes must be the shared injected regime map")
    if prior_regime is not None and prior_regime not in REGIMES:
        raise ForwardPolicyOrderSnapshotError("prior_regime must be absent or in the frozen regime vocabulary")
    if type(prior_upgrade_count) is not int or prior_upgrade_count < 0:
        raise ForwardPolicyOrderSnapshotError("prior_upgrade_count must be a non-negative literal integer")
    normalized_inputs = _normalized_price_rows(candidate_price_inputs_by_ticker, common_pool=common_pool)
    price_input_digest = _canonical_sha256({
        "price_basis_date": price_basis_date,
        "candidate_price_inputs_by_ticker": normalized_inputs,
        "market_axis_regimes": market_axis_regimes,
        "prior_regime": prior_regime,
        "prior_upgrade_count": prior_upgrade_count,
    })
    try:
        analysis = analyze_rows(
            _analysis_rows(common_pool, normalized_inputs),
            market_axis_regimes=market_axis_regimes,
            prior_regime=prior_regime,
            prior_upgrade_count=prior_upgrade_count,
        )
    except WeekendAnalysisError as exc:
        raise ForwardPolicyOrderSnapshotError("common candidate price analysis rejected its injected input") from exc
    regime = analysis["regime"]["market_risk_regime"]
    packet = _base_packet(
        capture=frozen_capture, common_pool=common_pool, price_input_digest=price_input_digest,
        market_risk_regime=regime,
    )
    if analysis["regime"]["new_entry_permitted"] is not True:
        packet.update({
            "order_snapshot_status": "data_degraded_whole_week_no_count",
            "orders_by_ticker": {},
            "common_order_snapshot_sha256": None,
            "non_executable_tickers": [],
            "degradation_reason": "new_entry_not_permitted",
        })
        validate_forward_policy_order_snapshot_packet(packet)
        return packet

    by_ticker = {row["ticker"]: row for row in analysis["rows"]}
    if set(by_ticker) != set(common_pool):
        raise ForwardPolicyOrderSnapshotError("price analysis lost or added a common-pool ticker")
    non_executable = [ticker for ticker in common_pool if by_ticker[ticker]["price"].get("executable") is not True]
    if non_executable:
        packet.update({
            "order_snapshot_status": "data_degraded_whole_week_no_count",
            "orders_by_ticker": {},
            "common_order_snapshot_sha256": None,
            "non_executable_tickers": non_executable,
            "degradation_reason": "common_candidate_order_not_executable",
        })
        validate_forward_policy_order_snapshot_packet(packet)
        return packet

    orders = {ticker: _order_from_price_result(by_ticker[ticker]["price"], ticker=ticker) for ticker in common_pool}
    packet.update({
        "order_snapshot_status": "ready_for_outcome",
        "orders_by_ticker": orders,
        "common_order_snapshot_sha256": _canonical_sha256(orders),
        "non_executable_tickers": [],
        "degradation_reason": None,
    })
    validate_forward_policy_order_snapshot_packet(packet)
    return packet


def validate_forward_policy_order_snapshot_packet(packet: object) -> dict:
    """Fail closed on common-pool/order/date/boundary drift before later private outcome code consumes it."""
    if not isinstance(packet, dict) or set(packet) != _PACKET_KEYS:
        raise ForwardPolicyOrderSnapshotError("common-order snapshot packet must use its exact closed-world key set")
    _validate_schema(packet)
    if packet["boundary"] != BOUNDARY:
        raise ForwardPolicyOrderSnapshotError("common-order snapshot boundary drifted from comparison-only/no-write policy")
    binding = packet["capture_binding"]
    if not (_strict_yyyymmdd(binding["decision_date"]) and _strict_yyyymmdd(binding["price_basis_date"])
            and binding["price_basis_date"] < binding["decision_date"]):
        raise ForwardPolicyOrderSnapshotError("common-order snapshot capture dates are invalid")
    if binding["comparison_contract_sha256"] != statistical_plan_sha256():
        raise ForwardPolicyOrderSnapshotError("common-order snapshot comparison contract digest drifted")
    common_pool = packet["common_selection_pool"]
    if len(common_pool) != len(set(common_pool)) or any(type(ticker) is not str or not ticker for ticker in common_pool):
        raise ForwardPolicyOrderSnapshotError("common-order snapshot pool must be an ordered unique ticker list")
    if binding["common_selection_pool_sha256"] != _canonical_sha256(common_pool):
        raise ForwardPolicyOrderSnapshotError("common-order snapshot pool digest is inconsistent")
    if packet["market_risk_regime"] not in REGIMES:
        raise ForwardPolicyOrderSnapshotError("common-order snapshot market regime is not in the frozen regime vocabulary")
    for field in ("common_price_input_snapshot_sha256",):
        value = packet[field]
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ForwardPolicyOrderSnapshotError(f"{field} must be a lowercase SHA256")

    status = packet["order_snapshot_status"]
    orders = packet["orders_by_ticker"]
    non_executable = packet["non_executable_tickers"]
    if len(non_executable) != len(set(non_executable)) or any(ticker not in common_pool for ticker in non_executable):
        raise ForwardPolicyOrderSnapshotError("non_executable_tickers must be a unique common-pool subset")
    if status == "ready_for_outcome":
        if set(orders) != set(common_pool) or non_executable or packet["degradation_reason"] is not None:
            raise ForwardPolicyOrderSnapshotError("ready common-order snapshot must contain every pool order and no degradation")
        for ticker in common_pool:
            _validate_order(orders[ticker], ticker=ticker)
        if packet["common_order_snapshot_sha256"] != _canonical_sha256(orders):
            raise ForwardPolicyOrderSnapshotError("common-order snapshot digest is inconsistent")
    else:
        if orders or packet["common_order_snapshot_sha256"] is not None:
            raise ForwardPolicyOrderSnapshotError("no-count common-order snapshot must not retain a partial order map")
        reason = packet["degradation_reason"]
        if reason == "common_candidate_order_not_executable":
            if not non_executable:
                raise ForwardPolicyOrderSnapshotError("candidate-order no-count must name the unbuildable common candidate")
        elif reason == "new_entry_not_permitted":
            if non_executable:
                raise ForwardPolicyOrderSnapshotError("market-wide new-entry no-count must not invent candidate failures")
        else:
            raise ForwardPolicyOrderSnapshotError("unknown common-order snapshot degradation reason")
    return packet
