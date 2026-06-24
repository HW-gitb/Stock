# -*- coding: utf-8 -*-
"""US-short §12.2 比较轨 NAV 路径 / 回撤 — batch-3 (#13/#24 follow-up): the path-dependent drawdown primitive.

Design authority: docs/us_short_system_design.md §12.2 (双向诚实: 成绩单必须报每档全口径——多买的亏损票 / 成本 /
空仓·现金拖累 / 坏票率 / **回撤**, 不只 balanced 错过的大牛; ≥12 周 + 双向全口径净值对比后再升硬约束 §13) / §12.1
(净结果口径: held 不虚高——未实现持仓绝不 mark; 归一化指标无 $) / §12 / §18.1 #27 (paper 永不计 full-size ship-gate).
Consumes ``engine.us_short_paper_scorecard.build_paper_scorecard`` outputs (one per as_of week, ONE profile).

A single-week scorecard is path-INDEPENDENT (one basket, one realized ``net_basket``). DRAWDOWN is a CROSS-week
metric — so it is computed over the ORDERED sequence of a profile's weekly basket nets, NOT inside one scorecard.
The honest, §12.1-不虚高-consistent NAV path is the WEEKLY REALIZED basket-net equity curve (NOT a daily
mark-to-market path: marking an unrealized held position to its daily close would book an unrealized mark, which
§12.1 forbids — and the §12.2 forward cadence is weekly anyway). The §12.1 #8 multi-day held-exit feeds this: it
turns held positions into closed ones upstream, so more weeks ``fully_resolved`` and contribute a realized step.

  * input = an ORDERED list of ``{as_of, scorecard}`` for ONE profile; ``as_of`` STRICTLY increasing (no
    look-ahead / no reorder / no duplicate week, PIT honest), every scorecard RE-validated (never trusts upstream);
  * a week is REALIZED iff its scorecard's ``net_basket`` is finite (the scorecard contract already makes net_basket
    finite IFF ``fully_resolved`` and non-empty; an open / empty week is None → it does NOT contribute a step and is
    NOT imputed — §12.1 不虚高 — only COUNTED as coverage so the gap is visible, §13 双向诚实/覆盖保险);
  * equity curve over the realized weeks IN ORDER: ``NAV_0 = 1.0``, ``NAV_k = NAV_{k-1} * (1 + net_k)``;
  * ``max_drawdown`` = the worst peak-to-trough relative decline along that curve (a NON-POSITIVE float, mirrors the
    a_long engineering convention ``max_drawdown_on_levels``; 0.0 for a monotonic / single-point curve; None when no
    realized week — no path, no metric); ``final_cumulative_net`` = ``NAV_final − 1`` (None when no realized week);
  * a net ≤ −1 (would drive NAV ≤ 0 — impossible for an equal-weight stop-bounded LONG basket) fails closed.

PAPER only — a frozen paper-only ``boundary`` (mirrors ``engine.us_short_paper_scorecard._BOUNDARY``) so a consumer
can NEVER read the drawdown as full-size ship-gate evidence (§12 / §18.1 #27; only live_normalized graduates).
``validate_nav_drawdown`` is CLOSED-WORLD and RE-DERIVES the curve from the embedded realized nets (so a doctored
drawdown / flipped boundary / count mismatch fails closed). The per-profile multi-week aggregation that rolls this drawdown
+ the cumulative full-caliber tally over weeks is engine.us_short_paper_multiweek_scorecard; wiring the 4 profiles
into a balanced-vs-shadow comparison is engine.us_short_paper_multiweek_comparison. Pure / offline: arithmetic on dicts; no provider / live /
DataHub / network; no A-share crossing; malformed input fails closed (``PaperNavDrawdownError``).
"""
from __future__ import annotations

import datetime
import math

from engine.us_short_paper_scorecard import validate_paper_scorecard

# the FROZEN paper-only evidence boundary the drawdown carries — paper is design-iteration evidence and is NEVER
# full-size ship-gate eligible (§12 / §18.1 #27). Mirrors engine.us_short_paper_scorecard._BOUNDARY so the two
# paper-evidence surfaces speak the same vocabulary.
_BOUNDARY = {
    "evidence_level": "paper",
    "full_size_ship_gate_allowed": False,
    "ship_gate_evidence_level": "paper_not_live_normalized",
}
# the EXACT top-level key set — validate_nav_drawdown is closed-world (the module is pure; this validator IS the
# reusable consumer gate), so a smuggled ticker / per-name / contradictory top-level ship-gate-or-live field can
# never validate (de-identified normalized metrics only — no $, no tickers)
_NAVDD_KEYS = frozenset({
    "n_total", "n_realized", "n_unrealized", "realized_period_nets",
    "final_cumulative_net", "max_drawdown", "boundary",
})
_ITEM_KEYS = frozenset({"as_of", "scorecard"})
_CLOSE_TOL = 1e-9


class PaperNavDrawdownError(ValueError):
    """Raised when the §12.2 NAV-path / drawdown contract is violated (item shape, as_of order, net, boundary)."""


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _strict_yyyymmdd(s) -> bool:
    # inlined (with the isascii() guard — the whole-class DATE-ASCII lesson) so this stays jsonschema-free
    if not (isinstance(s, str) and len(s) == 8 and s.isascii() and s.isdigit()):
        return False
    try:
        datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return True
    except ValueError:
        return False


def _curve_metrics(realized_nets):
    """Build the equity curve from an ordered list of realized basket nets and return
    ``(final_cumulative_net, max_drawdown)`` — both None for an empty list (no path, §12.1 不虚高). ``max_drawdown``
    is the worst peak-to-trough relative decline (NON-POSITIVE; mirrors the a_long ``max_drawdown_on_levels``
    convention). Each net MUST be finite and ``> -1`` (a net ≤ −1 would drive NAV ≤ 0 — impossible for an
    equal-weight stop-bounded LONG basket); the caller validates that before calling."""
    if not realized_nets:
        return None, None
    nav = 1.0
    peak = 1.0
    worst = 0.0
    for net in realized_nets:
        nav *= (1.0 + net)
        if nav > peak:
            peak = nav
        if peak > 0:
            drawdown = (nav / peak) - 1.0
            if drawdown < worst:
                worst = drawdown
    return nav - 1.0, worst


def build_nav_drawdown(period_scorecards) -> dict:
    """Build the §12.2 per-profile NAV-path drawdown from a profile's ORDERED weekly scorecards.

    ``period_scorecards`` = an ORDERED list of ``{"as_of": "YYYYMMDD", "scorecard": build_paper_scorecard output}``
    for ONE scoring_profile; ``as_of`` must be STRICTLY increasing (no look-ahead / no reorder / no duplicate week)
    and every scorecard is re-validated. A week is REALIZED iff its ``net_basket`` is finite (open / empty weeks are
    counted as coverage but contribute no step and are NOT imputed — §12.1 不虚高). Returns de-identified normalized
    metrics: coverage counts, the realized basket-net sequence, ``final_cumulative_net`` and the NON-POSITIVE
    ``max_drawdown`` (both None when no realized week), and a frozen paper-only ``boundary``. Re-validated through
    ``validate_nav_drawdown`` before return. Raises ``PaperNavDrawdownError`` / ``PaperScorecardError`` on malformed
    input. PAPER only — never full-size ship-gate eligible (§12)."""
    if not isinstance(period_scorecards, list):
        raise PaperNavDrawdownError("period_scorecards must be a list, got %r" % (type(period_scorecards).__name__,))
    realized_nets = []
    n_unrealized = 0
    prev_as_of = None
    for i, item in enumerate(period_scorecards):
        if not isinstance(item, dict) or set(item) != _ITEM_KEYS:
            raise PaperNavDrawdownError(
                "period_scorecards[%d] must be a dict over EXACTLY %s, got %s"
                % (i, sorted(_ITEM_KEYS), sorted(map(str, item)) if isinstance(item, dict) else type(item).__name__))
        as_of = item["as_of"]
        if not _strict_yyyymmdd(as_of):
            raise PaperNavDrawdownError("period_scorecards[%d].as_of must be a strict real YYYYMMDD, got %r" % (i, as_of))
        if prev_as_of is not None and not as_of > prev_as_of:
            raise PaperNavDrawdownError(
                "period_scorecards must be STRICTLY increasing by as_of (no look-ahead / reorder / duplicate week): "
                "[%d] %r not > previous %r" % (i, as_of, prev_as_of))
        prev_as_of = as_of
        scorecard = item["scorecard"]
        validate_paper_scorecard(scorecard)            # never trust upstream — re-validate the full-caliber scorecard
        net = scorecard["net_basket"]                  # finite IFF fully_resolved & non-empty (scorecard contract)
        if net is None:
            n_unrealized += 1                          # open / empty week — counted as coverage, NOT imputed (不虚高)
        elif not _finite(net):                         # defensive: a valid scorecard's net_basket is finite-or-None
            raise PaperNavDrawdownError("period_scorecards[%d].scorecard net_basket must be finite or None, got %r" % (i, net))
        elif net <= -1.0:
            raise PaperNavDrawdownError(
                "period_scorecards[%d] net_basket %r <= -1 would drive NAV <= 0 (impossible for an equal-weight "
                "stop-bounded long basket)" % (i, net))
        else:
            realized_nets.append(net)
    final_cumulative_net, max_drawdown = _curve_metrics(realized_nets)
    result = {
        "n_total": len(period_scorecards),
        "n_realized": len(realized_nets),
        "n_unrealized": n_unrealized,
        "realized_period_nets": realized_nets,
        "final_cumulative_net": final_cumulative_net,
        "max_drawdown": max_drawdown,
        "boundary": dict(_BOUNDARY),
    }
    validate_nav_drawdown(result)
    return result


def validate_nav_drawdown(navdd) -> None:
    """Fail-closed CLOSED-WORLD self-check (so a consumer can't be handed a doctored drawdown / flipped boundary /
    count mismatch): the EXACT key set (no smuggled ticker / ship-gate field); the FROZEN paper-only boundary;
    non-negative int counts with ``n_total == n_realized + n_unrealized`` and ``n_realized == len(realized_period_nets)``;
    every realized net finite and ``> -1``; and ``final_cumulative_net`` / ``max_drawdown`` RE-DERIVED from the
    embedded realized nets (both None IFF no realized week; ``max_drawdown`` NON-POSITIVE). Raises
    ``PaperNavDrawdownError``."""
    if not isinstance(navdd, dict):
        raise PaperNavDrawdownError("nav_drawdown must be a dict, got %r" % (type(navdd).__name__,))
    if set(navdd) != _NAVDD_KEYS:
        raise PaperNavDrawdownError(
            "nav_drawdown must carry EXACTLY %s (closed-world — no ticker / ship-gate field): missing %s, extra %s"
            % (sorted(_NAVDD_KEYS), sorted(map(str, _NAVDD_KEYS - set(navdd))), sorted(map(str, set(navdd) - _NAVDD_KEYS))))
    if navdd["boundary"] != _BOUNDARY:
        raise PaperNavDrawdownError("boundary must be the frozen paper-only block %r, got %r" % (_BOUNDARY, navdd["boundary"]))
    for k in ("n_total", "n_realized", "n_unrealized"):
        v = navdd[k]
        if not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
            raise PaperNavDrawdownError("nav_drawdown %s must be a non-negative int, got %r" % (k, v))
    nt, nr, nu = navdd["n_total"], navdd["n_realized"], navdd["n_unrealized"]
    if nt != nr + nu:
        raise PaperNavDrawdownError("n_total %d != n_realized + n_unrealized %d" % (nt, nr + nu))
    nets = navdd["realized_period_nets"]
    if not isinstance(nets, list) or len(nets) != nr:
        raise PaperNavDrawdownError(
            "realized_period_nets must be a list of length n_realized %d, got %r" % (nr, nets if isinstance(nets, list) else type(nets).__name__))
    for j, net in enumerate(nets):
        if not _finite(net):
            raise PaperNavDrawdownError("realized_period_nets[%d] must be a finite number, got %r" % (j, net))
        if net <= -1.0:
            raise PaperNavDrawdownError("realized_period_nets[%d] %r <= -1 would drive NAV <= 0" % (j, net))
    exp_cum, exp_dd = _curve_metrics(nets)
    cum, dd = navdd["final_cumulative_net"], navdd["max_drawdown"]
    if exp_cum is None:                                 # no realized week — both metrics must be None (no path, 不虚高)
        if cum is not None or dd is not None:
            raise PaperNavDrawdownError("final_cumulative_net / max_drawdown must be None when no realized week, got %r / %r" % (cum, dd))
        return
    if not (_finite(cum) and math.isclose(cum, exp_cum, abs_tol=_CLOSE_TOL)):
        raise PaperNavDrawdownError("final_cumulative_net %r != re-derived %r" % (cum, exp_cum))
    if not (_finite(dd) and dd <= 0.0 and math.isclose(dd, exp_dd, abs_tol=_CLOSE_TOL)):
        raise PaperNavDrawdownError("max_drawdown %r != re-derived NON-POSITIVE %r" % (dd, exp_dd))
