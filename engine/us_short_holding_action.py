# -*- coding: utf-8 -*-
"""US-short first-cut holding action planner and private TP state.

This module turns a reconciled holding plus the *previously published* TP1/TP2
levels into a manual action proposal.  It deliberately does not create add
position actions and never treats a recommendation as an executed manual
trade.  The private state stores levels because calculating TP from this same
week's close would always put the target above that close and could not
honestly trigger a later action.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from engine.us_short_cost_floor import apply_cost_floor
from engine.us_short_eligibility_gate import canonical_us_ticker

ROOT = Path(__file__).resolve().parent.parent
STATE_FILENAME = "holding_action_state.json"
STATE_SCHEMA_PATH = ROOT / "schemas" / "us_short_holding_action_state.schema.json"
GOVERNANCE_PATH = ROOT / "presets" / "us_short_action_governance_20260620.json"

_A_HOLD, _A_OBSERVE = "持有", "观察"
_A_REDUCE, _A_CLEAR_STOP, _A_CLEAR_TP, _A_CLEAR_EVENT = "减仓", "清仓-止损", "清仓-止盈", "清仓-事件"
_R_ACCOUNT = "cash_or_account_missing"
MAX_MANUAL_HOLDING_SHARES = 1_000_000_000
_PRICE_FIELDS = {
    _A_REDUCE: "take_profit_reduce_price",
    _A_CLEAR_STOP: "stop_clear_price",
    _A_CLEAR_TP: "take_profit_exit_price",
    _A_CLEAR_EVENT: "event_clear_reference_price",
}
TP1_REDUCE_FRACTION = 0.10


class HoldingActionError(Exception):
    """Holding action state, reconciliation, or proposal input is not trustworthy."""


def _finite_positive(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0.0)


def _real_date(value):
    if not (isinstance(value, str) and len(value) == 8 and value.isdigit()):
        return False
    try:
        from datetime import datetime
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _policy():
    try:
        data = json.loads(GOVERNANCE_PATH.read_text(encoding="utf-8"))
        policy = data["holding_action_policy"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HoldingActionError("holding action governance is unavailable") from exc
    if not (isinstance(policy, dict) and policy.get("tp1_reduce_fraction") == TP1_REDUCE_FRACTION
            and policy.get("add_position_enabled") is False):
        raise HoldingActionError("holding action governance is not the frozen first-cut policy")
    return policy


def load_holding_action_state(path, *, decision_date):
    """Load a prior private state.  Missing is a valid first-run condition; malformed is not."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HoldingActionError("private holding action state is unreadable") from exc
    validate_holding_action_state(state, decision_date=decision_date)
    return state


def validate_holding_action_state(state, *, decision_date):
    """Validate shape plus cross-row/private-state invariants before it can affect an action."""
    try:
        import jsonschema
        schema = json.loads(STATE_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(state, schema)
    except (OSError, json.JSONDecodeError, ImportError, Exception) as exc:
        # jsonschema.ValidationError intentionally shares the fail-closed holding-state surface.
        raise HoldingActionError("private holding action state fails its schema") from exc
    if not _real_date(decision_date) or state["as_of"] > decision_date:
        raise HoldingActionError("private holding action state is future-dated")
    seen = set()
    for item in state["positions"]:
        ticker = canonical_us_ticker(item.get("ticker"))
        if ticker is None or ticker in seen:
            raise HoldingActionError("private holding action state has a bad or duplicate ticker")
        seen.add(ticker)
        if item["tp1_completed"] is False and item["tp1_completed_at"] is not None:
            raise HoldingActionError("uncompleted TP1 may not carry a completion date")
        if item["tp1_completed"] is True and not _real_date(item["tp1_completed_at"]):
            raise HoldingActionError("completed TP1 requires a real completion date")
        if item["tp1_completed"] is True and item["tp1_completed_at"] > decision_date:
            raise HoldingActionError("private TP1 completion may not be future-dated")
        p1, p2 = item["active_tp1_price"], item["active_tp2_price"]
        if (p1 is None) != (p2 is None):
            raise HoldingActionError("private TP state must carry TP1 and TP2 together")
        if p1 is not None and not (_finite_positive(p1) and _finite_positive(p2) and p2 >= p1):
            raise HoldingActionError("private TP prices are invalid")
        if p1 is not None and not _real_date(item["levels_as_of"]):
            raise HoldingActionError("private TP prices need their price-basis date")


def build_holding_action_context(account_state, prior_state):
    """Make one fail-closed action context per account holding.

    ``holding_action_reconciliation`` comes from the manual account converter.  It is the only source that
    may mark TP1 completed; the sidecar is only the system's previous target-level memory.
    """
    positions = account_state.get("positions") if isinstance(account_state, dict) else None
    reconciliation = account_state.get("holding_action_reconciliation") if isinstance(account_state, dict) else None
    if not isinstance(positions, list):
        raise HoldingActionError("account state has no positions list")
    if not (isinstance(reconciliation, dict) and isinstance(reconciliation.get("positions"), list)):
        return {canonical_us_ticker(p.get("ticker")): {"status": "untrusted"}
                for p in positions if isinstance(p, dict) and canonical_us_ticker(p.get("ticker")) is not None}
    recon = {}
    untrusted_tickers = set()
    for item in reconciliation["positions"]:
        ticker = canonical_us_ticker(item.get("ticker")) if isinstance(item, dict) else None
        if (ticker is None or ticker in recon or ticker in untrusted_tickers
                or not isinstance(item.get("remaining_shares"), int)
                or isinstance(item.get("remaining_shares"), bool) or item["remaining_shares"] < 1
                or item["remaining_shares"] > MAX_MANUAL_HOLDING_SHARES
                or not _real_date(item.get("entry_date"))
                or not isinstance(item.get("source_reconciliation_ref"), str)
                or not item["source_reconciliation_ref"].strip()
                or not isinstance(item.get("tp1_completed"), bool)
                or (item.get("tp1_completed") and not _real_date(item.get("tp1_completed_at")))
                or (not item.get("tp1_completed") and item.get("tp1_completed_at") is not None)):
            # One malformed manual row must not erase the usable context of every other holding.  Its own
            # ticker remains untrusted; an unidentifiable stray row cannot be attached to a real holding.
            if ticker is not None:
                untrusted_tickers.add(ticker)
                recon.pop(ticker, None)
            continue
        recon[ticker] = item
    prior = {}
    if prior_state is not None:
        prior = {item["ticker"]: item for item in prior_state["positions"]}
    out = {}
    for position in positions:
        ticker = canonical_us_ticker(position.get("ticker")) if isinstance(position, dict) else None
        if ticker is None or ticker in untrusted_tickers or ticker not in recon:
            if ticker is not None:
                out[ticker] = {"status": "untrusted"}
            continue
        item = recon[ticker]
        if (position.get("shares") != item["remaining_shares"]
                or position.get("entry_date") != item["entry_date"]):
            out[ticker] = {"status": "untrusted"}
            continue
        saved = prior.get(ticker)
        if saved is not None and saved["entry_date"] != item["entry_date"]:
            saved = None  # a new manual entry resets old TP completion and target levels
        completed = item["tp1_completed"] or bool(saved and saved["tp1_completed"])
        completed_at = item["tp1_completed_at"] if item["tp1_completed"] else (saved["tp1_completed_at"] if saved and saved["tp1_completed"] else None)
        out[ticker] = {
            "status": "ready" if saved is not None else "seed_required",
            "shares": item["remaining_shares"],
            "entry_date": item["entry_date"],
            "avg_cost_usd": position.get("avg_cost_usd"),
            "tp1_completed": completed,
            "tp1_completed_at": completed_at,
            "active_tp1_price": saved["active_tp1_price"] if saved is not None else None,
            "active_tp2_price": saved["active_tp2_price"] if saved is not None else None,
            "levels_as_of": saved["levels_as_of"] if saved is not None else None,
            "source_reconciliation_ref": item["source_reconciliation_ref"],
        }
    return out


def attach_holding_action_context(rows, contexts, *, price_basis_date):
    """Attach reconciled private context only to holding analysis rows, including price-clock provenance."""
    out = []
    for row in rows:
        if "holding" not in str(row.get("row_source")):
            out.append(row)
            continue
        ticker = canonical_us_ticker(row.get("ticker"))
        ctx = dict(contexts.get(ticker, {"status": "untrusted"}))
        ci = row.get("holding_action_cost_input")
        ctx.update({"price_basis_date": price_basis_date, "price_session": "RTH",
                    "price_adjustment": "split_adjusted", "cost_input": ci})
        out.append({**row, "holding_action_context": ctx})
    return out


def _proposal(*, shares=None, price_field=None, reason=None, context=None):
    context = context if isinstance(context, dict) else {}
    return {
        "recommended_action_shares": shares,
        "price_target_field": price_field,
        "price_basis_date": context.get("price_basis_date"),
        "price_session": context.get("price_session"),
        "price_adjustment": context.get("price_adjustment"),
        "reason": reason,
        "tp1_completed": context.get("tp1_completed"),
        "tp1_completed_at": context.get("tp1_completed_at"),
        "remaining_shares": context.get("shares"),
        "source_reconciliation_ref": context.get("source_reconciliation_ref"),
    }


def _cost_floor_clears(context, shares, target):
    ci = context.get("cost_input")
    if not isinstance(ci, dict):
        return False, "tp1_deferred_unverifiable_cost"
    result = apply_cost_floor(shares, context.get("avg_cost_usd"), target,
                              ci.get("commission_round_trip"), ci.get("slippage_dollars"),
                              ci.get("spread_dollars"))
    return result["status"] == "ok", ("tp1_cost_floor_cleared" if result["status"] == "ok" else "tp1_deferred_cost_floor")


def plan_holding_action(evidence, base_action, base_reason):
    """Return an action/reason/proposal/price coherent with the first-cut TP policy.

    Base event/stop precedence is supplied by the decision stage.  A missing account/state reconciliation
    downgrades the holding to observe rather than emitting a sell quantity guessed from a target position size.
    """
    context = evidence.get("holding_action_context")
    if "holding_action_context" not in evidence:
        # Isolated legacy engine tests can exercise the base priority chain without claiming an official
        # account-linked output. The orchestrator always attaches this context before an emitted run.
        return base_action, base_reason, None, evidence["price"]
    # Protective exits are never swallowed because manual share reconciliation is unavailable. The price/action
    # remains actionable; quantity is deliberately blank and requires a manual account check.
    if base_action in (_A_CLEAR_EVENT, _A_CLEAR_STOP):
        trusted_context = (isinstance(context, dict) and context.get("status") in ("ready", "seed_required")
                           and isinstance(context.get("shares"), int)
                           and not isinstance(context.get("shares"), bool)
                           and 1 <= context["shares"] <= MAX_MANUAL_HOLDING_SHARES)
        if not trusted_context:
            return (base_action, base_reason,
                    _proposal(price_field=_PRICE_FIELDS[base_action],
                              reason="mandatory_holding_exit_manual_share_confirmation", context=context),
                    evidence["price"])
    if not isinstance(context, dict) or context.get("status") not in ("ready", "seed_required"):
        return _A_OBSERVE, _R_ACCOUNT, _proposal(reason="holding_action_state_untrusted", context=context), evidence["price"]
    shares = context.get("shares")
    if not (isinstance(shares, int) and not isinstance(shares, bool) and 1 <= shares <= MAX_MANUAL_HOLDING_SHARES):
        return _A_OBSERVE, _R_ACCOUNT, _proposal(reason="holding_shares_untrusted", context=context), evidence["price"]
    price = evidence["price"]
    fields = price.get("action_fields") if isinstance(price, dict) else None
    if not isinstance(fields, dict):
        return _A_OBSERVE, _R_ACCOUNT, _proposal(reason="holding_price_untrusted", context=context), price
    updated_fields = dict(fields)
    for state_field, output_field in (("active_tp1_price", "take_profit_reduce_price"),
                                      ("active_tp2_price", "take_profit_exit_price")):
        if _finite_positive(context.get(state_field)):
            updated_fields[output_field] = context[state_field]
    planned_price = {**price, "action_fields": updated_fields}
    if base_action in (_A_CLEAR_EVENT, _A_CLEAR_STOP):
        return base_action, base_reason, _proposal(shares=shares, price_field=_PRICE_FIELDS[base_action],
                                                   reason="mandatory_holding_exit", context=context), planned_price
    if base_action != _A_HOLD:
        return base_action, base_reason, _proposal(reason="non_actionable_holding", context=context), planned_price
    close = context.get("price_basis_value")
    tp1, tp2 = context.get("active_tp1_price"), context.get("active_tp2_price")
    if not _finite_positive(close):
        return _A_OBSERVE, _R_ACCOUNT, _proposal(reason="price_basis_untrusted", context=context), planned_price
    if _finite_positive(tp2) and close >= tp2:
        return _A_CLEAR_TP, None, _proposal(shares=shares, price_field=_PRICE_FIELDS[_A_CLEAR_TP],
                                             reason="tp2_reached", context=context), planned_price
    if _finite_positive(tp1) and not context.get("tp1_completed") and close >= tp1:
        reduce_shares = int(shares * _policy()["tp1_reduce_fraction"])
        if reduce_shares < 1:
            return _A_HOLD, None, _proposal(reason="tp1_deferred_below_min", context=context), planned_price
        cleared, reason = _cost_floor_clears(context, reduce_shares, tp1)
        if not cleared:
            return _A_HOLD, None, _proposal(reason=reason, context=context), planned_price
        return _A_REDUCE, None, _proposal(shares=reduce_shares, price_field=_PRICE_FIELDS[_A_REDUCE],
                                           reason=reason, context=context), planned_price
    return _A_HOLD, None, _proposal(reason=("tp1_levels_seeded" if context["status"] == "seed_required" else "hold"),
                                     context=context), planned_price


def build_next_holding_action_state(decision_date, rows):
    """Persist target levels and manual reconciliation facts after an emitted run.

    Recommendations never toggle ``tp1_completed``: only the next account-state conversion of an executed
    manual ``减仓`` can do that.  A corrupt prior state is deliberately not passed here by the orchestrator.
    """
    if not _real_date(decision_date) or not isinstance(rows, list):
        raise HoldingActionError("cannot build private holding action state")
    positions = []
    for row in rows:
        if not (isinstance(row, dict) and row.get("row_context") == "holding"):
            continue
        ctx = row.get("holding_action_context")
        if not isinstance(ctx, dict) or ctx.get("status") not in ("ready", "seed_required"):
            continue
        fields = row.get("price", {}).get("action_fields", {}) if isinstance(row.get("price"), dict) else {}
        p1 = ctx.get("active_tp1_price") or fields.get("take_profit_reduce_price")
        p2 = ctx.get("active_tp2_price") or fields.get("take_profit_exit_price")
        if not (_finite_positive(p1) and _finite_positive(p2) and p2 >= p1):
            p1, p2, levels_as_of = None, None, None
        else:
            levels_as_of = ctx.get("levels_as_of") or ctx.get("price_basis_date")
        positions.append({
            "ticker": row["ticker"], "entry_date": ctx["entry_date"],
            "tp1_completed": bool(ctx["tp1_completed"]), "tp1_completed_at": ctx.get("tp1_completed_at"),
            "active_tp1_price": float(p1) if p1 is not None else None,
            "active_tp2_price": float(p2) if p2 is not None else None,
            "levels_as_of": levels_as_of,
            "remaining_shares": ctx["shares"],
            "source_reconciliation_ref": ctx["source_reconciliation_ref"],
            "price_session": ctx["price_session"], "price_adjustment": ctx["price_adjustment"],
        })
    state = {"schema_name": "us_short_holding_action_state", "schema_version": "1.0.0",
             "as_of": decision_date, "positions": sorted(positions, key=lambda p: p["ticker"])}
    validate_holding_action_state(state, decision_date=decision_date)
    return state
