# -*- coding: utf-8 -*-
"""US-short §12.2 比较轨 per-profile 多周聚合 — batch-3 (#13/#24 follow-up): one profile's ≥12-week full-caliber view.

Design authority: docs/us_short_system_design.md §12.2 (双向诚实: 成绩单必须报每档全口径——多买的亏损票 / 成本 /
空仓·现金拖累 / 坏票率 / 回撤; ≥12 周 + 双向全口径净值对比后再升硬约束 §13) / §12.1 (净结果口径: held 不虚高) /
§12 / §18.1 #27 (paper 永不计 full-size ship-gate). Consumes ONE scoring_profile's ORDERED weekly
``engine.us_short_paper_scorecard.build_paper_scorecard`` outputs and the
``engine.us_short_paper_nav_drawdown.build_nav_drawdown`` equity-curve drawdown.

A single-week scorecard is one basket; the §12.2 upgrade evidence is the ≥12-WEEK accumulation. This rolls ONE
profile's weekly scorecards into its multi-week full-caliber summary — the building block the multi-week
balanced-vs-shadow comparison (a later cut) puts side by side. It reports TWO honestly-DISTINCT calibers (different
denominators, never conflated):

  * ``cumulative`` — the full-caliber position tally over ALL weeks (every basket, realized or not): summed filled /
    unfilled-cash (现金拖累) / open-unrealized (held, §12.1 不虚高 — counted, never booked) / win / loss / flat, the
    summed ``total_cost_fraction`` (round-trip cost drag, §12.1 #18), and the OVERALL ``bad_pick_rate`` = cumulative
    loss / cumulative filled (§12.2 坏票率; None when nothing filled). Denominator = positions across weeks;
  * ``nav_drawdown`` — the path-dependent equity-curve metric over the REALIZED-basket weeks only (a week with an
    open position has no booked basket net, so it is coverage-counted but NOT on the curve — §12.1 不虚高). It
    carries ``max_drawdown`` / ``final_cumulative_net`` / the realized-week coverage. Denominator = realized weeks.

So a heavier-theme shadow's extra losers / cost / cash drag / bad-pick rate AND its drawdown are both visible — the
§12.2 防"赛道越激进越好"偏结论 honesty. A FROZEN paper-only ``boundary`` (mirrors
``engine.us_short_paper_scorecard._BOUNDARY``) keeps it un-readable as full-size ship-gate evidence (§12 / §18.1 #27).

The artifact is SOURCE-TRACEABLE: it carries the de-identified per-week ``period_source`` (each ``{as_of,
scorecard}`` — scorecards are de-identified counts, no tickers / $) from which BOTH the cumulative tally AND the
nav_drawdown are re-derivable. ``validate_multiweek_scorecard`` is CLOSED-WORLD and RE-DERIVES from that source: it
re-builds the nav_drawdown and the cumulative from ``period_source`` and rejects any mismatch, so a doctored tally /
self-consistent-but-source-divergent cumulative (e.g. forged to all-zeros) / flipped boundary / mismatched coverage
fails closed — the §12.2 evidence contract can never bless cost / cash / bad-pick / drawdown that diverge from its
own weekly source. Count fields (``n_weeks`` + the cumulative counts) must be STRICT non-negative ints (a float /
bool that compares numerically equal is refused). Pure / offline: arithmetic on dicts; no provider / live / DataHub
/ network; no A-share crossing; malformed input fails closed (``PaperMultiweekScorecardError``).
"""
from __future__ import annotations

import math

from engine.us_short_paper_nav_drawdown import build_nav_drawdown, validate_nav_drawdown

# the FROZEN paper-only evidence boundary — mirrors engine.us_short_paper_scorecard._BOUNDARY /
# engine.us_short_paper_nav_drawdown._BOUNDARY (the same paper-evidence vocabulary; a test pins the three equal).
# PAPER is design-iteration evidence and is NEVER full-size ship-gate eligible (§12 / §18.1 #27).
_BOUNDARY = {
    "evidence_level": "paper",
    "full_size_ship_gate_allowed": False,
    "ship_gate_evidence_level": "paper_not_live_normalized",
}
# the per-week scorecard count fields summed into the cumulative tally (mirror engine.us_short_paper_scorecard keys)
_SUM_COUNTS = ("selected_total", "filled_count", "unfilled_cash_count", "open_unrealized_count",
               "win_count", "loss_count", "flat_count")
# the cumulative count fields that must be STRICT non-negative ints (a numerically-equal float / bool is refused —
# the §12.2 evidence contract is the reusable consumer gate, not a shape-only summary)
_CUM_COUNT_KEYS = ("cum_selected_total", "cum_filled", "cum_unfilled_cash", "cum_open_unrealized",
                   "cum_win", "cum_loss", "cum_flat")
_CUMULATIVE_KEYS = frozenset(_CUM_COUNT_KEYS + ("cum_total_cost_fraction", "overall_bad_pick_rate"))
_MULTIWEEK_KEYS = frozenset({"n_weeks", "period_source", "cumulative", "nav_drawdown", "boundary"})


class PaperMultiweekScorecardError(ValueError):
    """Raised when the §12.2 per-profile multi-week aggregation contract is violated (input / cumulative / boundary)."""


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _nonneg_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def _derive_cumulative(period_scorecards) -> dict:
    """The SINGLE cumulative-tally derivation (build computes it; validate RE-derives it from the embedded source and
    rejects any mismatch). Sums each week's scorecard count fields + ``total_cost_fraction`` and forms the overall
    ``bad_pick_rate`` = cumulative loss / cumulative filled (None when nothing filled). Assumes each item is
    ``{as_of, scorecard}`` with a VALID scorecard (the caller validates via ``build_nav_drawdown`` first)."""
    sums = {k: 0 for k in _SUM_COUNTS}
    cum_cost = 0.0
    for item in period_scorecards:
        sc = item["scorecard"]
        for k in _SUM_COUNTS:
            sums[k] += sc[k]
        cum_cost += sc["total_cost_fraction"]
    cum_filled = sums["filled_count"]
    overall_bad_pick_rate = (sums["loss_count"] / cum_filled) if cum_filled else None  # §12.2 坏票率 over ALL filled
    return {
        "cum_selected_total": sums["selected_total"],
        "cum_filled": cum_filled,
        "cum_unfilled_cash": sums["unfilled_cash_count"],
        "cum_open_unrealized": sums["open_unrealized_count"],
        "cum_win": sums["win_count"],
        "cum_loss": sums["loss_count"],
        "cum_flat": sums["flat_count"],
        "cum_total_cost_fraction": cum_cost,
        "overall_bad_pick_rate": overall_bad_pick_rate,
    }


def build_multiweek_scorecard(period_scorecards) -> dict:
    """Aggregate ONE scoring_profile's ORDERED weekly scorecards into its §12.2 multi-week full-caliber summary.

    ``period_scorecards`` = an ORDERED list of ``{"as_of": "YYYYMMDD", "scorecard": build_paper_scorecard output}``
    for ONE profile (the SAME shape ``build_nav_drawdown`` consumes — STRICTLY increasing as_of, every scorecard
    re-validated). Returns ``{n_weeks, period_source, cumulative, nav_drawdown, boundary}`` — ``period_source`` is
    the de-identified per-week source (each ``{as_of, scorecard}``) from which both ``cumulative`` (the full-caliber
    position tally over ALL weeks + overall bad_pick_rate) and ``nav_drawdown`` (the realized-basket equity-curve
    drawdown, §12.1 不虚高) are re-derivable. Re-validated through ``validate_multiweek_scorecard`` before return.
    Raises ``PaperMultiweekScorecardError`` / ``PaperNavDrawdownError`` / ``PaperScorecardError`` on malformed input.
    PAPER only — never full-size ship-gate eligible (§12)."""
    nav = build_nav_drawdown(period_scorecards)  # validates item shape + strict as_of order + every scorecard, builds the curve
    # build_nav_drawdown returned → every item is {as_of, scorecard} with a valid (de-identified) scorecard; embed a
    # copied de-identified per-week source so the artifact is self-contained + re-derivable (not aliased to the caller)
    period_source = [{"as_of": it["as_of"], "scorecard": dict(it["scorecard"])} for it in period_scorecards]
    result = {
        "n_weeks": nav["n_total"],
        "period_source": period_source,
        "cumulative": _derive_cumulative(period_scorecards),
        "nav_drawdown": nav,
        "boundary": dict(_BOUNDARY),
    }
    validate_multiweek_scorecard(result)
    return result


def validate_multiweek_scorecard(mw) -> None:
    """Fail-closed CLOSED-WORLD self-check that RE-DERIVES from the embedded de-identified ``period_source`` (so a
    consumer can never be handed a source-divergent tally / drawdown): the EXACT top-level + cumulative key sets (no
    smuggled ticker / ship-gate field); the FROZEN paper-only boundary; the embedded ``nav_drawdown`` self-validated
    AND equal to the one RE-BUILT from ``period_source`` (``build_nav_drawdown`` re-validates each de-identified
    ``{as_of, scorecard}`` + strict as_of order + net>-1); the embedded ``cumulative`` equal to the one RE-derived
    from ``period_source`` (a forged self-consistent tally — e.g. all-zeros — is refused); STRICT non-negative int
    count fields (``n_weeks`` + the cumulative counts — a numerically-equal float / bool is refused); and ``n_weeks
    == len(period_source)``. Raises ``PaperMultiweekScorecardError`` / ``PaperNavDrawdownError`` / ``PaperScorecardError``."""
    if not isinstance(mw, dict):
        raise PaperMultiweekScorecardError("multiweek_scorecard must be a dict, got %r" % (type(mw).__name__,))
    if set(mw) != _MULTIWEEK_KEYS:
        raise PaperMultiweekScorecardError(
            "multiweek_scorecard must carry EXACTLY %s (closed-world — no ticker / ship-gate field): missing %s, extra %s"
            % (sorted(_MULTIWEEK_KEYS), sorted(map(str, _MULTIWEEK_KEYS - set(mw))), sorted(map(str, set(mw) - _MULTIWEEK_KEYS))))
    if mw["boundary"] != _BOUNDARY:
        raise PaperMultiweekScorecardError("boundary must be the frozen paper-only block %r, got %r" % (_BOUNDARY, mw["boundary"]))
    # --- re-derive nav_drawdown + cumulative from the embedded de-identified per-week source (source-traceable) ---
    period_source = mw["period_source"]
    if not isinstance(period_source, list):
        raise PaperMultiweekScorecardError("period_source must be a list, got %r" % (type(period_source).__name__,))
    validate_nav_drawdown(mw["nav_drawdown"])            # embedded drawdown self-consistent (re-derives its own curve)
    re_nav = build_nav_drawdown(period_source)           # re-validates every de-identified {as_of, scorecard} + order + net>-1, re-derives the curve
    if mw["nav_drawdown"] != re_nav:
        raise PaperMultiweekScorecardError("nav_drawdown is not the one re-derived from period_source (source-divergent drawdown)")
    cum = mw["cumulative"]
    if not isinstance(cum, dict) or set(cum) != _CUMULATIVE_KEYS:
        raise PaperMultiweekScorecardError(
            "cumulative must carry EXACTLY %s, got %s"
            % (sorted(_CUMULATIVE_KEYS), sorted(map(str, cum)) if isinstance(cum, dict) else type(cum).__name__))
    # STRICT type gate on EVERY numeric field BEFORE the value re-derivation — a bool / numerically-equal wrong type
    # (False == 0.0 / True == 1.0 / 2.0 == 2) would otherwise slip through the == comparison below
    for k in _CUM_COUNT_KEYS:                             # the 7 count fields: strict non-negative int (bool refused)
        if not _nonneg_int(cum[k]):
            raise PaperMultiweekScorecardError("cumulative %s must be a non-negative int, got %r" % (k, cum[k]))
    if not (_finite(cum["cum_total_cost_fraction"]) and cum["cum_total_cost_fraction"] >= 0):  # cost: finite non-neg float (bool refused)
        raise PaperMultiweekScorecardError("cum_total_cost_fraction must be a finite non-negative number (bool refused), got %r" % (cum["cum_total_cost_fraction"],))
    bpr = cum["overall_bad_pick_rate"]
    if bpr is not None and not _finite(bpr):             # bad-pick rate: a finite number or None (bool refused)
        raise PaperMultiweekScorecardError("overall_bad_pick_rate must be a finite number or None (bool refused), got %r" % (bpr,))
    if cum != _derive_cumulative(period_source):         # the tally must MATCH the re-derivation from source (forged all-zeros refused)
        raise PaperMultiweekScorecardError("cumulative is not the one re-derived from period_source (source-divergent tally)")
    n = mw["n_weeks"]
    if not _nonneg_int(n):                                # STRICT non-negative int (float / bool refused — the n_weeks strictness gap)
        raise PaperMultiweekScorecardError("n_weeks must be a non-negative int, got %r" % (n,))
    if n != len(period_source):
        raise PaperMultiweekScorecardError("n_weeks %r != len(period_source) %r" % (n, len(period_source)))
