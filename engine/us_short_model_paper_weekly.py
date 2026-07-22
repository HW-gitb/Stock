# -*- coding: utf-8 -*-
"""Offline weekly wiring for the isolated US-short model-paper portfolio.

This layer deliberately sits between the pure portfolio engine/store and a
capstone source adapter.  It accepts only already-fetched local OHLCV and a
paper-account-bound action plan; it never reads a manual account, invokes a
provider, or treats the paper ledger as ship-gate evidence.
"""
from __future__ import annotations

import copy
from datetime import datetime
from decimal import Decimal
from typing import Any

from engine.us_short_model_paper_portfolio import (
    ModelPaperPortfolioError,
    artifact_sha256,
    build_nav_snapshot,
    seed_portfolio_state,
    settle_decision_bundle,
    validate_decision_bundle,
)
from engine.us_short_model_paper_store import (
    ModelPaperStoreError,
    commit_settlement_and_freeze_next,
    freeze_decision_bundle,
    initialize_store,
    load_current_nav,
    load_current_state,
    load_head,
    load_pending_decision,
)


RUN_ACCOUNT_MODES = frozenset({"paper_only", "manual_actual", "dual"})
_BOUNDARY = {
    "paper_only": True,
    "provider_fetch": False,
    "automatic_broker_execution": False,
    "manual_account_read": False,
    "ship_gate_eligible": False,
}


class ModelPaperWeeklyError(RuntimeError):
    """The capstone-side weekly composition failed before a paper head move."""


def _date8(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ModelPaperWeeklyError(f"{label} must be YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ModelPaperWeeklyError(f"{label} must be a real YYYYMMDD date") from exc
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ModelPaperWeeklyError(f"{label} must be a lowercase SHA256")
    return value


def _finite_money(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelPaperWeeklyError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ModelPaperWeeklyError(f"{label} must be a finite number") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise ModelPaperWeeklyError(f"{label} must be a finite number")
    return result


def build_paper_track(nav: dict) -> dict:
    """Project only the fail-safe portfolio-guard inputs from a paper NAV snapshot."""
    if not isinstance(nav, dict):
        raise ModelPaperWeeklyError("NAV must be an object")
    evaluable = nav.get("paper_evaluable")
    if type(evaluable) is not bool:
        raise ModelPaperWeeklyError("NAV paper_evaluable must be boolean")
    digest = nav.get("state_sha256")
    _sha(digest, "NAV state_sha256")
    return {
        "paper_evaluable": evaluable,
        # A future reviewed guard reducer may supply these.  Absence intentionally stays fail-safe in the
        # existing guard classifier instead of inventing a clean paper history.
        "consecutive_stops": None,
        "paper_drawdown_frac": None,
        "evidence_ref": {"kind": "source_id", "value": f"model_paper_nav:{digest}"},
    }


def build_paper_account_adapter(state: dict, nav: dict, *, decision_date: str) -> dict:
    """Derive the normalized-notional paper account view used by paper action generation.

    The adapter is data, not a persisted/manual account file.  It binds the exact post-maturity state and
    valuation date so a caller cannot accidentally generate current advice from the real account or stale cash.
    """
    decision_date = _date8(decision_date, "decision_date")
    if not isinstance(state, dict) or not isinstance(nav, dict):
        raise ModelPaperWeeklyError("state and NAV must be objects")
    state_digest = artifact_sha256(state)
    if nav.get("state_sha256") != state_digest:
        raise ModelPaperWeeklyError("NAV does not bind the supplied paper state")
    valuation_as_of = _date8(state.get("as_of"), "state.as_of")
    if decision_date <= valuation_as_of:
        raise ModelPaperWeeklyError("decision_date must follow the paper valuation date")
    try:
        cash = float(Decimal(state["cash"]))
    except Exception as exc:
        raise ModelPaperWeeklyError("state cash is not numeric") from exc
    positions = []
    for position in state.get("positions", []):
        if not isinstance(position, dict):
            raise ModelPaperWeeklyError("state position must be an object")
        positions.append({
            "ticker": position["ticker"],
            "shares": position["shares"],
            "avg_cost_usd": float(Decimal(position["fill_price"])),
            "entry_date": position["entry_decision_date"],
            "current_stop": float(Decimal(position["stop_clear_price"])),
            "tp1_completed": position["tp1_completed"],
        })
    positions.sort(key=lambda row: row["ticker"])
    return {
        "schema_name": "us_short_model_paper_account_adapter",
        "schema_version": "1.0.0",
        "source_state_sha256": state_digest,
        "valuation_as_of": valuation_as_of,
        "decision_date": decision_date,
        "capital_kind": "normalized_notional",
        "us_market_equity": 300000.0,
        "us_short_bucket_capital": 100000.0,
        "us_short_available_cash": cash,
        "positions": positions,
        "paper_track": build_paper_track(nav),
        "boundary": {
            "manual_account_read": False,
            "automatic_broker_execution": False,
            "ship_gate_eligible": False,
        },
    }


def _validate_plan(plan: Any, *, adapter: dict, decision_date: str) -> dict:
    if not isinstance(plan, dict) or set(plan) != {
        "source_receipt_sha256", "source_as_of", "paper_account_adapter_sha256", "cost_prior", "orders"
    }:
        raise ModelPaperWeeklyError("paper action plan must use its exact closed-world key set")
    _sha(plan["source_receipt_sha256"], "plan.source_receipt_sha256")
    if _date8(plan["source_as_of"], "plan.source_as_of") != decision_date:
        raise ModelPaperWeeklyError("paper action plan source_as_of must equal decision_date")
    if plan["paper_account_adapter_sha256"] != artifact_sha256(adapter):
        raise ModelPaperWeeklyError("paper action plan does not bind the derived paper account adapter")
    cost = plan["cost_prior"]
    if not isinstance(cost, dict) or set(cost) != {"commission_fee", "slippage_bps", "spread_cost"}:
        raise ModelPaperWeeklyError("paper action plan cost_prior is invalid")
    for key, value in cost.items():
        if _finite_money(value, f"cost_prior.{key}") < 0:
            raise ModelPaperWeeklyError(f"cost_prior.{key} must be nonnegative")
    if not isinstance(plan["orders"], list):
        raise ModelPaperWeeklyError("paper action plan orders must be a list")
    return copy.deepcopy(plan)


def build_paper_decision_bundle(
    plan: dict,
    *,
    state: dict,
    adapter: dict,
    decision_date: str,
    price_basis_date: str,
    created_at: str,
    supersedes_sha256: str | None = None,
) -> dict:
    """Freeze a current paper-only action plan after its adapter/state binding has been checked."""
    decision_date = _date8(decision_date, "decision_date")
    price_basis_date = _date8(price_basis_date, "price_basis_date")
    if state.get("as_of") != price_basis_date:
        raise ModelPaperWeeklyError("paper decision price_basis_date must equal current paper state")
    checked = _validate_plan(plan, adapter=adapter, decision_date=decision_date)
    if supersedes_sha256 is not None:
        _sha(supersedes_sha256, "supersedes_sha256")
    bundle = {
        "schema_name": "us_short_model_paper_decision_bundle",
        "schema_version": "1.0.0",
        "decision_date": decision_date,
        "price_basis_date": price_basis_date,
        "created_at": created_at,
        "prior_state_sha256": artifact_sha256(state),
        "supersedes_sha256": supersedes_sha256,
        "source_binding": {
            "source_kind": "us_short_weekly_decision_artifact",
            "source_as_of": checked["source_as_of"],
            # The source receipt, plan and adapter must all participate; a real/manual action table is not an input.
            "decision_source_sha256": artifact_sha256({
                "source_receipt_sha256": checked["source_receipt_sha256"],
                "plan": checked,
                "adapter": adapter,
            }),
        },
        "cost_prior": checked["cost_prior"],
        "orders": checked["orders"],
        "boundary": copy.deepcopy(_BOUNDARY),
    }
    try:
        validate_decision_bundle(bundle)
    except ModelPaperPortfolioError as exc:
        raise ModelPaperWeeklyError(f"paper decision bundle is invalid: {exc}") from exc
    return bundle


def _same_pending_semantics(candidate: dict, pending: dict) -> bool:
    """Treat a rerun timestamp and an already-recorded supersession link as non-source changes."""
    left = copy.deepcopy(candidate)
    right = copy.deepcopy(pending)
    for value in (left, right):
        value.pop("created_at", None)
        value.pop("supersedes_sha256", None)
    return left == right


def _seed_if_needed(store_root: str, *, price_basis_date: str, price_packet: dict) -> str | None:
    try:
        load_head(store_root)
        return None
    except ModelPaperStoreError as exc:
        if "not initialized" not in str(exc):
            raise ModelPaperWeeklyError(f"paper store cannot be loaded: {exc}") from exc
    state = seed_portfolio_state(price_basis_date)
    evaluation = price_packet.get("paper_evaluation") if isinstance(price_packet, dict) else None
    try:
        nav = build_nav_snapshot(state, evaluation)
        return initialize_store(store_root, state, nav)
    except (ModelPaperPortfolioError, ModelPaperStoreError) as exc:
        raise ModelPaperWeeklyError(f"paper store seed failed: {exc}") from exc


def prepare_paper_account_adapter(
    *,
    store_root: str,
    decision_date: str,
    price_basis_date: str,
    price_packet: dict,
) -> dict:
    """Derive this week's paper adapter without moving the persistent head.

    The capstone needs the post-maturity cash/holdings before it can produce
    this week's recommendation.  This preview deliberately repeats the same
    maturity calculation later used by :func:`run_paper_weekly_transition`,
    but never seeds, settles, or freezes the store.  The terminal transition
    remains the sole writer, so a downstream decision failure cannot expose a
    half-matured paper week.
    """
    decision_date = _date8(decision_date, "decision_date")
    price_basis_date = _date8(price_basis_date, "price_basis_date")
    if decision_date <= price_basis_date:
        raise ModelPaperWeeklyError("decision_date must follow price_basis_date")
    if not isinstance(price_packet, dict) or price_packet.get("as_of") != price_basis_date:
        raise ModelPaperWeeklyError("price_packet.as_of must equal price_basis_date")

    seed_required = False
    try:
        load_head(store_root)
    except ModelPaperStoreError as exc:
        if "not initialized" not in str(exc):
            raise ModelPaperWeeklyError(f"paper store cannot be loaded: {exc}") from exc
        seed_required = True

    if seed_required:
        state = seed_portfolio_state(price_basis_date)
        try:
            nav = build_nav_snapshot(state, price_packet.get("paper_evaluation"))
        except ModelPaperPortfolioError as exc:
            raise ModelPaperWeeklyError(f"paper seed preview failed: {exc}") from exc
        pending = None
        maturity_status = "not_due"
    else:
        try:
            pending = load_pending_decision(store_root)
            prior_state = load_current_state(store_root)
            prior_nav = load_current_nav(store_root)
        except ModelPaperStoreError as exc:
            raise ModelPaperWeeklyError(f"paper store read failed: {exc}") from exc
        if pending is not None and pending["decision_date"] < decision_date:
            if pending["decision_date"] > price_basis_date:
                raise ModelPaperWeeklyError("pending paper decision has no arrived price-basis session to mature")
            try:
                _settlement, state, nav = settle_decision_bundle(
                    prior_state, pending, price_packet, price_basis_date)
            except ModelPaperPortfolioError as exc:
                raise ModelPaperWeeklyError(f"paper maturity rejected: {exc}") from exc
            maturity_status = "matured"
        elif pending is not None and pending["decision_date"] > decision_date:
            raise ModelPaperWeeklyError("decision date disorder: a later paper decision is already pending")
        else:
            state, nav = prior_state, prior_nav
            maturity_status = "not_due"

    adapter = build_paper_account_adapter(state, nav, decision_date=decision_date)
    return {
        "adapter": adapter,
        "seed_required": seed_required,
        "maturity_status": maturity_status,
        "pending_decision_date": None if pending is None else pending["decision_date"],
        "provider_calls_performed": False,
        "manual_account_read": False,
        "automatic_broker_execution": False,
        "ship_gate_eligible": False,
    }


def run_paper_weekly_transition(
    *,
    run_account_mode: str,
    store_root: str,
    decision_date: str,
    price_basis_date: str,
    created_at: str,
    price_packet: dict,
    plan_factory,
) -> dict:
    """Execute the offline weekly order: mature old → derive adapter/guard → build current plan → freeze.

    ``plan_factory(adapter)`` is intentionally the only action-generation seam.  It must create an independent
    paper action plan from the adapter and local source artifacts.  This driver does not accept a manual account
    or the official ``action_table.csv`` anywhere in its API.
    """
    if run_account_mode not in RUN_ACCOUNT_MODES:
        raise ModelPaperWeeklyError(f"run_account_mode must be one of {sorted(RUN_ACCOUNT_MODES)}")
    if run_account_mode == "manual_actual":
        raise ModelPaperWeeklyError("manual_actual has no model-paper branch; use paper_only or dual")
    if not callable(plan_factory):
        raise ModelPaperWeeklyError("plan_factory must be callable")
    decision_date = _date8(decision_date, "decision_date")
    price_basis_date = _date8(price_basis_date, "price_basis_date")
    if decision_date <= price_basis_date:
        raise ModelPaperWeeklyError("decision_date must follow price_basis_date")
    if not isinstance(price_packet, dict) or price_packet.get("as_of") != price_basis_date:
        raise ModelPaperWeeklyError("price_packet.as_of must equal price_basis_date")

    seed_status = _seed_if_needed(store_root, price_basis_date=price_basis_date, price_packet=price_packet)
    try:
        pending = load_pending_decision(store_root)
        prior_state = load_current_state(store_root)
        prior_nav = load_current_nav(store_root)
    except ModelPaperStoreError as exc:
        raise ModelPaperWeeklyError(f"paper store read failed: {exc}") from exc

    settlement = state = nav = None
    if pending is not None and pending["decision_date"] < decision_date:
        if pending["decision_date"] > price_basis_date:
            raise ModelPaperWeeklyError("pending paper decision has no arrived price-basis session to mature")
        try:
            settlement, state, nav = settle_decision_bundle(prior_state, pending, price_packet, price_basis_date)
        except ModelPaperPortfolioError as exc:
            raise ModelPaperWeeklyError(f"paper maturity rejected: {exc}") from exc
    elif pending is not None and pending["decision_date"] > decision_date:
        raise ModelPaperWeeklyError("decision date disorder: a later paper decision is already pending")
    else:
        state, nav = prior_state, prior_nav

    adapter = build_paper_account_adapter(state, nav, decision_date=decision_date)
    plan = plan_factory(copy.deepcopy(adapter))
    next_decision = build_paper_decision_bundle(
        plan, state=state, adapter=adapter, decision_date=decision_date,
        price_basis_date=price_basis_date, created_at=created_at,
    )
    if pending is not None and pending["decision_date"] == decision_date:
        if _same_pending_semantics(next_decision, pending):
            # created_at is an output clock, not evidence that the PIT source changed; preserve the first frozen
            # bundle byte-for-byte so a genuine same-input rerun is an idempotent no-op.
            next_decision = pending
        else:
            next_decision = build_paper_decision_bundle(
                plan, state=state, adapter=adapter, decision_date=decision_date,
                price_basis_date=price_basis_date, created_at=created_at,
                supersedes_sha256=artifact_sha256(pending),
            )

    try:
        if settlement is not None:
            publish_status = commit_settlement_and_freeze_next(
                store_root, pending, settlement, state, nav, next_decision)
        else:
            publish_status = freeze_decision_bundle(store_root, next_decision)
    except ModelPaperStoreError as exc:
        raise ModelPaperWeeklyError(f"paper weekly publish failed: {exc}") from exc

    return {
        "run_account_mode": run_account_mode,
        "seed_status": seed_status,
        "maturity_status": "matured" if settlement is not None else "not_due",
        "publish_status": publish_status,
        "decision_date": decision_date,
        "price_basis_date": price_basis_date,
        "paper_evaluable": nav["paper_evaluable"],
        "paper_performance_status": nav["performance_status"],
        "source_state_sha256": artifact_sha256(state),
        "paper_account_adapter_sha256": artifact_sha256(adapter),
        "decision_bundle_sha256": artifact_sha256(next_decision),
        "provider_calls_performed": False,
        "manual_account_read": False,
        "automatic_broker_execution": False,
        "ship_gate_eligible": False,
    }


def planned_holding_target_union(*, manual_holding_tickers: list[str] | tuple[str, ...], paper_state: dict) -> list[str]:
    """Return the deterministic manual ∪ paper holdings preflight target forecast, without fetching anything."""
    if not isinstance(paper_state, dict) or not isinstance(paper_state.get("positions"), list):
        raise ModelPaperWeeklyError("paper_state.positions must be a list")
    values = set()
    for ticker in list(manual_holding_tickers) + [row.get("ticker") for row in paper_state["positions"] if isinstance(row, dict)]:
        if not isinstance(ticker, str) or not ticker:
            raise ModelPaperWeeklyError("holding target must be a nonblank ticker")
        values.add(ticker)
    return sorted(values)


__all__ = [
    "ModelPaperWeeklyError",
    "RUN_ACCOUNT_MODES",
    "build_paper_account_adapter",
    "build_paper_decision_bundle",
    "build_paper_track",
    "planned_holding_target_union",
    "prepare_paper_account_adapter",
    "run_paper_weekly_transition",
]
