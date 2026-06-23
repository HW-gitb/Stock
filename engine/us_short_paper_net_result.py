# -*- coding: utf-8 -*-
"""US-short §12.1 纸面净结果口径 — batch-3 (#8 follow-up): deterministic net result of one simulated fill.

Design authority: docs/us_short_system_design.md §12.1 (净结果口径: paper_performance 含 commission_fee /
slippage_bps / spread_cost / unfilled_cash / net_return — 算净收益、未成交按现金、不把没买上的当收益; 成本假设
= prior §13 #18) / §12 (paper 仅设计迭代、绝不判满仓 ship-gate). Consumes the result of
``engine.us_short_paper_fill.simulate_fill``.

Turns one simulated fill into its REPRODUCIBLE net return (same fill_result + same cost prior → same number, no
randomness — what makes paper evidence reproducible). The §13 #18 cost prior is applied as round-trip
return-DRAG (no ``$`` — consistent with §12.1's normalized, ``$``-free output): ``total_cost_fraction =
commission_fee + spread_cost + slippage_bps / 10000`` (commission / spread are round-trip return fractions,
slippage is round-trip basis points). Per-status:

  * ``not_filled`` → ``net_return = 0`` (cash, no return — a name we did not buy is NEVER booked as return,
    §12.1 不把没买上的当收益), ``unfilled_cash = True``;
  * ``filled_stopped`` / ``filled_tp_exit`` (same-day CLOSED) → realized ``gross_return = (exit - fill) / fill``,
    ``net_return = gross_return - total_cost_fraction`` (round-trip cost charged on the realized round trip);
  * ``filled_held`` (open at day end) → ``realized = False`` / ``net_return = None`` — a position open past the
    single session is UNREALIZED; its realized net (with the full round trip) is computed when it exits, a later
    multi-day cut. An unrealized mark is deliberately NOT booked as net (§12.1 不虚高).

This is a PAPER number only — paper_performance is design-iteration evidence and is NEVER full-size ship-gate
eligible (§12; the corporate-action evaluability + ship-gate isolation are engine.us_short_paper_eval_gate).
Pure / offline: arithmetic on dicts; no provider / live / DataHub / network; no persistence; no A-share crossing.
Malformed input fails closed (``PaperNetResultError``); the function re-checks the FULL per-status fill_result
shape itself (status ⇔ price / reason — see ``_validate_fill_shape``) rather than trusting it came from
``simulate_fill``, so an inconsistent record (not_filled carrying prices, filled_held with an exit, a closed
status with the wrong exit_reason) can never be converted into paper accounting.
"""
from __future__ import annotations

import math

# the fill statuses simulate_fill emits (mirrors engine.us_short_paper_fill; the integration test feeds real
# simulate_fill outputs through here so a new status can't silently drift past this consumer)
_REALIZED_CLOSED = ("filled_stopped", "filled_tp_exit")
_FILL_STATUSES = ("not_filled", "filled_held") + _REALIZED_CLOSED
# the exit_reason(s) a CLOSED status may carry — the same-day variant from engine.us_short_paper_fill OR the
# multi-day variant from engine.us_short_paper_multi_day_exit (both feed this consumer; the integration tests feed
# real outputs so a reason rename can't silently drift past here)
_STATUS_EXIT_REASONS = {"filled_stopped": ("same_day_stop", "multi_day_stop"),
                        "filled_tp_exit": ("same_day_tp_exit", "multi_day_tp_exit")}
_COST_KEYS = ("commission_fee", "slippage_bps", "spread_cost")
_COST_KEYS = ("commission_fee", "slippage_bps", "spread_cost")


class PaperNetResultError(ValueError):
    """Raised when a fill_result / cost prior violates the §12.1 net-result contract (shape, status, price, cost)."""


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _finite_pos(x) -> bool:
    return _finite(x) and x > 0


def _validate_fill_shape(fill_result, status) -> None:
    """Fully lock the per-status fill_result shape (status ⇔ price/reason) — the consumer never trusts that an
    inconsistent record came from ``simulate_fill``: ``not_filled`` carries NO fill_price / exit_price / exit_reason;
    ``filled_held`` carries a finite positive fill_price and NO exit_price / exit_reason (it is OPEN); a closed
    status (``filled_stopped`` / ``filled_tp_exit``) carries finite positive fill_price + exit_price and the
    status-specific exit_reason (``same_day_*`` from same-day fill OR ``multi_day_*`` from the multi-day exit).
    Raises ``PaperNetResultError`` on any
    mismatch."""
    fill_price, exit_price, exit_reason = fill_result.get("fill_price"), fill_result.get("exit_price"), fill_result.get("exit_reason")
    if status == "not_filled":
        if fill_price is not None or exit_price is not None or exit_reason is not None:
            raise PaperNetResultError(
                "not_filled must carry NO fill_price / exit_price / exit_reason, got fill=%r exit=%r reason=%r"
                % (fill_price, exit_price, exit_reason))
    elif status == "filled_held":
        if not _finite_pos(fill_price):
            raise PaperNetResultError("filled_held fill_price must be a finite positive number, got %r" % (fill_price,))
        if exit_price is not None or exit_reason is not None:
            raise PaperNetResultError(
                "filled_held is OPEN — it must carry no exit_price / exit_reason, got exit=%r reason=%r" % (exit_price, exit_reason))
    else:  # filled_stopped / filled_tp_exit
        if not _finite_pos(fill_price):
            raise PaperNetResultError("%s fill_price must be a finite positive number, got %r" % (status, fill_price))
        if not _finite_pos(exit_price):
            raise PaperNetResultError("%s exit_price must be a finite positive number, got %r" % (status, exit_price))
        if exit_reason not in _STATUS_EXIT_REASONS[status]:
            raise PaperNetResultError("%s exit_reason must be one of %r, got %r" % (status, _STATUS_EXIT_REASONS[status], exit_reason))


def _total_cost_fraction(cost_prior) -> float:
    if not isinstance(cost_prior, dict) or set(cost_prior) != set(_COST_KEYS):
        raise PaperNetResultError(
            "cost_prior must be a dict over EXACTLY %s, got %s"
            % (list(_COST_KEYS), sorted(map(str, cost_prior)) if isinstance(cost_prior, dict) else type(cost_prior).__name__)
        )
    for k in _COST_KEYS:
        if not (_finite(cost_prior[k]) and cost_prior[k] >= 0):
            raise PaperNetResultError("cost_prior[%r] must be a finite NON-NEGATIVE number, got %r" % (k, cost_prior[k]))
    return cost_prior["commission_fee"] + cost_prior["spread_cost"] + cost_prior["slippage_bps"] / 10000.0


def paper_net_result(fill_result, *, cost_prior) -> dict:
    """Deterministic §12.1 net result of one simulated fill. ``fill_result`` is a ``simulate_fill`` output (its
    FULL per-status shape — status ⇔ price/reason — is RE-CHECKED here, not trusted); ``cost_prior`` =
    ``{commission_fee, slippage_bps, spread_cost}`` (the
    §13 #18 round-trip cost prior, no ``$``). Returns ``{"outcome", "realized", "gross_return", "cost_fraction",
    "net_return", "unfilled_cash"}`` — ``net_return`` is 0 for not_filled (cash), the cost-charged realized return
    for a same-day close, and ``None`` for an open (held) position (unrealized). Raises ``PaperNetResultError`` on
    malformed input."""
    if not isinstance(fill_result, dict):
        raise PaperNetResultError("fill_result must be a dict, got %r" % (type(fill_result).__name__,))
    status = fill_result.get("status")
    if status not in _FILL_STATUSES:
        raise PaperNetResultError("fill_result status %r not in %s" % (status, list(_FILL_STATUSES)))
    _validate_fill_shape(fill_result, status)       # full per-status shape lock (status ⇔ price/reason)
    total_cost = _total_cost_fraction(cost_prior)   # validates the cost prior for every status (one contract)

    if status == "not_filled":
        # a name we did not buy is NEVER booked as return (§12.1 不把没买上的当收益)
        return {"outcome": "cash_unfilled", "realized": True, "gross_return": 0.0, "cost_fraction": 0.0,
                "net_return": 0.0, "unfilled_cash": True}
    if status == "filled_held":
        # open past the single session → UNREALIZED; realized net waits for the multi-day exit (later cut),
        # an unrealized mark is deliberately not booked as net (§12.1 不虚高)
        return {"outcome": "open_unrealized", "realized": False, "gross_return": None, "cost_fraction": None,
                "net_return": None, "unfilled_cash": False}

    # same-day CLOSED (filled_stopped / filled_tp_exit): realized round trip (shape validated above)
    fill_price, exit_price = fill_result["fill_price"], fill_result["exit_price"]
    gross = (exit_price - fill_price) / fill_price
    return {"outcome": status, "realized": True, "gross_return": gross, "cost_fraction": total_cost,
            "net_return": gross - total_cost, "unfilled_cash": False}
