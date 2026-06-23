# -*- coding: utf-8 -*-
"""US-short §12.1 model_paper_track 纸面成交 — batch-3 (#8): the deterministic single-order daily fill simulator.

Design authority: docs/us_short_system_design.md §12.1 (纸面成交规则 写死、可复现) / §6 (order modes) / §11.3
(action_table order fields) / §18.1 #8 / §12 (paper 仅设计迭代、绝不判满仓 ship-gate). order_type enum authority
= the FROZEN us_short_action_table_contract ``design_locked_enums.order_type`` (single source).

paper_track simulates fills on DAILY OHLC only, by the §12.1 WRITTEN, REPRODUCIBLE rules (same order + same bar
→ same result, no randomness — that is what makes the paper evidence reproducible). Order validity is
``first_regular_session_only`` (v1 locked) — the simulator REFUSES any missing / non-v1 ``order_expiry``
(``PaperFillError``; multi-day GTC is a lifecycle candidate, NOT implemented in v1, so it is never simulated with
single-session logic); the order is judged on the one regular session; not filled at the close → ``not_filled``
(no carry-over). The deterministic order:

  * Step 0 — ``open`` NOT in ``[valid_entry_low, valid_entry_high]`` → ``not_filled`` (cash, no return);
  * Step 1 (open in band, by order_type) — ``pullback_limit``: ``low <= limit_order_price`` → fill @
    ``limit_order_price``; ``breakout_stop_limit``: ``high >= breakout_entry_price`` → fill @
    ``min(max(open, breakout_entry_price), valid_entry_high)``; else ``not_filled``;
  * same-day conservative exit (daily bars can't see intraday order, so we under-count, never inflate): if filled
    AND ``low <= stop_clear_price`` → entered-then-STOPPED (do NOT assume it survived the day); else if
    ``high >= take_profit_exit_price`` → tp exit. STOP takes priority when both same-day triggers fire (§12.1 ②).

Order GEOMETRY is enforced fail-closed before any bookable output: a pullback ``limit_order_price`` must be inside
the valid entry band, and the passive levels must BRACKET the actual fill (``stop_clear_price < fill <
take_profit_exit_price``) — an inverted / equal / out-of-band geometry would book a "stop" as a gain or a
"take-profit" as a loss (R-USSHORT-BATCH3-PAPER-FILL-ORDER-GEOMETRY-GAP).

Pure / offline: applies arithmetic rules to dicts; no provider / live / DataHub / network; no persistence (the
private paper_*.csv writer + the corporate-action / not_evaluable hard gate + performance accounting are later
cuts); no A-share crossing. Malformed input fails closed (``PaperFillError``).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CONTRACT_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"

_CACHE: dict = {}


class PaperFillError(ValueError):
    """Raised when a paper-fill order / day bar violates the §12.1 contract (shape, price, OHLC sanity, enum)."""


def _enums() -> dict:
    if "enums" not in _CACHE:
        _CACHE["enums"] = json.loads(_CONTRACT_PRESET.read_text(encoding="utf-8"))["design_locked_enums"]
    return _CACHE["enums"]


def _order_types() -> list:
    return list(_enums()["order_type"])


def _order_expiries() -> list:
    return list(_enums()["order_expiry"])  # v1-locked = ["first_regular_session_only"] (§12.1)


def _finite_pos(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def _price(container, key, where):
    v = container.get(key)
    if not _finite_pos(v):
        raise PaperFillError("%s %s must be a finite positive number, got %r" % (where, key, v))
    return v


def _validate_bar(day_bar) -> tuple:
    if not isinstance(day_bar, dict):
        raise PaperFillError("day_bar must be a dict, got %r" % (type(day_bar).__name__,))
    o = _price(day_bar, "open", "day_bar")
    h = _price(day_bar, "high", "day_bar")
    low = _price(day_bar, "low", "day_bar")
    c = _price(day_bar, "close", "day_bar")
    if not (low <= h and low <= o <= h and low <= c <= h):  # OHLC sanity: low is the floor, high the ceiling
        raise PaperFillError("day_bar OHLC inconsistent (need low <= open/close <= high): %r" % (day_bar,))
    return o, h, low, c


def simulate_fill(order, day_bar) -> dict:
    """Deterministically simulate one order's daily fill per §12.1. Returns
    ``{"status", "fill_price", "exit_price", "exit_reason", "reason"}`` where ``status`` is one of
    ``not_filled`` / ``filled_held`` / ``filled_stopped`` / ``filled_tp_exit``. ``order`` carries ``order_type``
    (frozen enum), ``valid_entry_low`` / ``valid_entry_high`` (the band), the type-specific entry price
    (``limit_order_price`` for pullback / ``breakout_entry_price`` for breakout), ``stop_clear_price`` and
    ``take_profit_exit_price``; ``day_bar`` carries ``open`` / ``high`` / ``low`` / ``close``. Same order + same
    bar always yield the same result (reproducible). Order GEOMETRY is enforced fail-closed before any bookable
    output: a ``pullback_limit``'s ``limit_order_price`` must sit inside ``[valid_entry_low, valid_entry_high]``, and
    (after the deterministic fill candidate is known, both order types) the passive levels must bracket it —
    ``stop_clear_price < fill < take_profit_exit_price`` (a long's stop below entry, tp above; inverted / equal
    geometry would book a "stop" as a gain or a "take-profit" as a loss). Raises ``PaperFillError`` on malformed
    input / impossible geometry."""
    if not isinstance(order, dict):
        raise PaperFillError("order must be a dict, got %r" % (type(order).__name__,))
    ot = order.get("order_type")
    if ot not in set(_order_types()):
        raise PaperFillError("order_type %r not in the frozen enum %s" % (ot, _order_types()))
    # §12.1 v1 LOCK: only first_regular_session_only is supported — refuse a missing / non-string / GTC / unknown
    # expiry before any fill (multi-day GTC is a lifecycle candidate, NOT implemented in v1; simulating it with
    # single-session logic would produce a misleading fill and contaminate paper evidence)
    if order.get("order_expiry") not in set(_order_expiries()):
        raise PaperFillError(
            "order_expiry %r not in the frozen v1-locked set %s (§12.1: only first_regular_session_only; multi-day "
            "GTC is a lifecycle candidate, not implemented in v1)" % (order.get("order_expiry"), _order_expiries())
        )
    elo = _price(order, "valid_entry_low", "order")
    ehi = _price(order, "valid_entry_high", "order")
    if not elo <= ehi:
        raise PaperFillError("valid_entry_low %s must be <= valid_entry_high %s" % (elo, ehi))
    stop = _price(order, "stop_clear_price", "order")
    tp = _price(order, "take_profit_exit_price", "order")
    o, h, low, _c = _validate_bar(day_bar)

    def _result(status, fill_price=None, exit_price=None, exit_reason=None, reason=None):
        return {"status": status, "fill_price": fill_price, "exit_price": exit_price, "exit_reason": exit_reason, "reason": reason}

    # --- Step 0: open must be inside the valid entry band ---
    if not elo <= o <= ehi:
        return _result("not_filled", reason="open_out_of_band")

    # --- Step 1: fill by order_type (deterministic) ---
    if ot == "pullback_limit":
        limit = _price(order, "limit_order_price", "order")
        if not (elo <= limit <= ehi):  # a pullback limit MUST sit inside the valid entry band (else fill out-of-zone)
            raise PaperFillError("pullback limit_order_price %s must be inside the valid entry band [%s, %s]" % (limit, elo, ehi))
        if low <= limit:
            fill = limit
        else:
            return _result("not_filled", reason="pullback_not_reached")
    else:  # breakout_stop_limit
        bp = _price(order, "breakout_entry_price", "order")
        if h >= bp:
            fill = min(max(o, bp), ehi)  # can't fill below the open; never chase above valid_entry_high
        else:
            return _result("not_filled", reason="breakout_not_reached")

    # the passive levels MUST bracket the actual fill (a long: stop below entry, tp above) — else a same-day "stop"
    # would book a gain or a "take-profit" a loss (R-USSHORT-BATCH3-PAPER-FILL-ORDER-GEOMETRY-GAP); checked AFTER
    # the deterministic fill candidate is known, before any same-day stop/tp/held output can be booked
    if not (stop < fill < tp):
        raise PaperFillError(
            "passive levels must bracket the fill: stop_clear_price %s < fill %s < take_profit_exit_price %s "
            "(a long's stop below entry, tp above); inverted / equal geometry is refused" % (stop, fill, tp))

    # --- same-day conservative exit: STOP first (priority), then tp exit (§12.1 ①②) ---
    if low <= stop:
        return _result("filled_stopped", fill_price=fill, exit_price=stop, exit_reason="same_day_stop")
    if h >= tp:
        return _result("filled_tp_exit", fill_price=fill, exit_price=tp, exit_reason="same_day_tp_exit")
    return _result("filled_held", fill_price=fill)
