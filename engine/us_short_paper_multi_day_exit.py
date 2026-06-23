# -*- coding: utf-8 -*-
"""US-short §12.1 model_paper_track 多日平仓 — batch-3 (#8 follow-up): the multi-day held-position exit simulator.

Design authority: docs/us_short_system_design.md §12.1 (held = open past the single session; its realized net waits
for the multi-day exit) / §6.1 (v1 passive exit levels stop_clear_price / take_profit_exit_price; active scale-out
/ time-stop is the deferred lifecycle candidate #34, NOT v1) / §12 (paper 仅设计迭代). Pairs with
engine.us_short_paper_fill (entry/same-day) → engine.us_short_paper_net_result (net).

A position that filled but did NOT close on the entry day (``engine.us_short_paper_fill`` → ``filled_held``) is OPEN
past the single regular session; its realized net is computed when it EXITS. This simulates that exit
DETERMINISTICALLY over the SUBSEQUENT daily bars, by the SAME conservative §12.1 rule as the same-day exit, applied
per day:

  * for each subsequent day in order: if ``low <= stop_clear_price`` → exit @ stop (STOP priority on a both-triggered
    day, §12.1 ②); else if ``high >= take_profit_exit_price`` → tp exit @ tp; else keep holding to the next day;
  * if NO level is hit across the provided window → still ``filled_held`` (UNREALIZED — v1 has NO time-stop / active
    scale-out [#34]; the realized net waits for more bars, §12.1 不虚高).

Conservative (daily bars can't see intraday order, so STOP wins a both-triggered day — under-counts, never
inflates). Returns a fill_result of the SAME shape ``engine.us_short_paper_fill`` emits (status ∈ filled_stopped /
filled_tp_exit / filled_held), so ``engine.us_short_paper_net_result`` consumes it unchanged (its exit_reason gate
accepts the ``multi_day_*`` variant). Pure / offline: arithmetic on dicts; no provider / live / DataHub / network;
no persistence; no A-share crossing. Malformed input fails closed (``PaperMultiDayExitError``).
"""
from __future__ import annotations

import math


class PaperMultiDayExitError(ValueError):
    """Raised when a held position / day bar violates the §12.1 multi-day exit contract (shape, price, OHLC sanity)."""


def _finite_pos(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def _price(container, key):
    v = container.get(key)
    if not _finite_pos(v):
        raise PaperMultiDayExitError("%s must be a finite positive number, got %r" % (key, v))
    return v


def _bar_high_low(day_bar, i) -> tuple:
    if not isinstance(day_bar, dict):
        raise PaperMultiDayExitError("day_bars[%d] must be a dict, got %r" % (i, type(day_bar).__name__))
    o = _price(day_bar, "open")
    h = _price(day_bar, "high")
    low = _price(day_bar, "low")
    c = _price(day_bar, "close")
    if not (low <= h and low <= o <= h and low <= c <= h):  # OHLC sanity: low is the floor, high the ceiling
        raise PaperMultiDayExitError("day_bars[%d] OHLC inconsistent (need low <= open/close <= high): %r" % (i, day_bar))
    return h, low


def simulate_multi_day_exit(held_position, day_bars) -> dict:
    """Deterministically simulate a ``filled_held`` position's exit over the SUBSEQUENT daily bars per §12.1.

    ``held_position`` = ``{fill_price, stop_clear_price, take_profit_exit_price}`` (the held entry fill + its passive
    §6.1 exit levels; the passive levels MUST bracket the held entry — ``stop_clear_price < fill_price <
    take_profit_exit_price`` [a long's stop below entry, tp above; an inverted / equal geometry is refused]);
    ``day_bars`` = the days AFTER the entry day, in
    order, each ``{open, high, low, close}``. Returns a fill_result ``{status, fill_price, exit_price, exit_reason,
    reason}`` (same shape as ``engine.us_short_paper_fill``): the first day with ``low <= stop`` → ``filled_stopped``
    @ stop (``multi_day_stop``; STOP priority §12.1 ②), else the first with ``high >= tp`` → ``filled_tp_exit`` @ tp
    (``multi_day_tp_exit``); no level hit across the window → ``filled_held`` (UNREALIZED — v1 no time-stop, §12.1
    不虚高). Feed the result to ``engine.us_short_paper_net_result``. Raises ``PaperMultiDayExitError`` on malformed
    input."""
    if not isinstance(held_position, dict):
        raise PaperMultiDayExitError("held_position must be a dict, got %r" % (type(held_position).__name__,))
    fill = _price(held_position, "fill_price")
    stop = _price(held_position, "stop_clear_price")
    tp = _price(held_position, "take_profit_exit_price")
    if not (stop < fill < tp):  # a LONG position's passive levels MUST bracket the entry: stop below, tp above —
        # else an impossible geometry (stop>=fill / tp<=fill) would book a "stop" as a gain or a "take-profit" as a loss
        raise PaperMultiDayExitError(
            "passive levels must bracket the held entry — stop_clear_price %s < fill_price %s < take_profit_exit_price %s "
            "(a long's stop below entry, tp above); an inverted / equal geometry is refused" % (stop, fill, tp))
    if not isinstance(day_bars, list):
        raise PaperMultiDayExitError("day_bars must be a list, got %r" % (type(day_bars).__name__,))
    for i, bar in enumerate(day_bars):
        h, low = _bar_high_low(bar, i)
        if low <= stop:  # STOP first (priority) — don't assume it survived the day (daily-bar conservative, §12.1 ②)
            return {"status": "filled_stopped", "fill_price": fill, "exit_price": stop, "exit_reason": "multi_day_stop", "reason": None}
        if h >= tp:
            return {"status": "filled_tp_exit", "fill_price": fill, "exit_price": tp, "exit_reason": "multi_day_tp_exit", "reason": None}
    return {"status": "filled_held", "fill_price": fill, "exit_price": None, "exit_reason": None, "reason": None}
