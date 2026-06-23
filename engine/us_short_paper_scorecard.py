# -*- coding: utf-8 -*-
"""US-short §12.2 比较轨 paper scorecard — batch-3 (#13/#24 follow-up): per-basket full-caliber aggregation.

Design authority: docs/us_short_system_design.md §12.2 (双向诚实: 成绩单必须报每档全口径——多买的亏损票 / 成本 /
空仓·现金拖累 / 坏票率, 不只 balanced 错过的大牛; 禁止挑样本: 必须按固定 TopN 全量输出) / §12.1 (净结果口径:
未成交按现金、held 不虚高) / §12 / §18.1 #27 (paper 仅设计迭代, 永不计 full-size ship-gate). Consumes
``engine.us_short_paper_net_result.paper_net_result`` outputs.

Aggregates ONE basket's per-position net results into the §12.2 full-caliber metrics — DETERMINISTIC, path-
INDEPENDENT. The §12.2 禁止挑样本/全量 rule is enforced STRUCTURALLY by a basket-LINEAGE contract: the function
takes the FROZEN selection identity (``selected_tickers`` — a profile's fixed TopN, unique non-blank strings) plus
a ticker-keyed net-result map, and FAILS CLOSED unless the map covers EXACTLY that selection (no omitted selected
name, no duplicate identity, no extra stale ticker). So a winner-only subset, an omitted loser, or a smuggled
stale row can no longer produce a clean-looking scorecard. Returns (no ticker names — de-identified counts only):

  * counts: filled (same-day closed) / unfilled-cash (现金拖累) / open-unrealized (held, not yet realized);
  * realized win / loss / flat + ``bad_pick_rate`` = loss / filled (§12.2 坏票率; None when nothing filled);
  * ``total_cost_fraction`` (the round-trip cost drag actually charged, §12.1 #18);
  * ``net_basket``: the EQUAL-WEIGHT realized basket net over the WHOLE selection (a closed position's net, an
    unfilled position's 0.0 cash — so 现金拖累 is reflected), booked ONLY when ``fully_resolved`` (no open
    position) and the selection is non-empty, else None (an unrealized / empty basket is never marked, §12.1 不虚高);
  * a FROZEN paper-only ``boundary`` (``evidence_level="paper"`` / ``full_size_ship_gate_allowed=False`` /
    ``ship_gate_evidence_level="paper_not_live_normalized"``) so a consumer can NEVER read the scorecard as
    full-size ship-gate evidence (§12 / §18.1 #27); ``validate_paper_scorecard`` re-checks it + the count
    consistency, so a flipped boundary / doctored count fails closed.

The path-dependent drawdown (needs the daily NAV path), the balanced-vs-shadow two-way comparison, the multi-day
held-exit realized net (§12.1 #8 — turns an open position into a closed one upstream so more baskets fully
resolve), and the §12.1 复权/公司行动 evaluability gate (not_evaluable → no alpha conclusion) are later §12.2 cuts.
Pure / offline: arithmetic on dicts; no provider / live / DataHub / network; no A-share crossing. The function
RE-CHECKS every net_result's full per-outcome shape itself (never trusts the producer); malformed input fails
closed (``PaperScorecardError``).
"""
from __future__ import annotations

import math

# the paper_net_result outcomes + the exact entry key set (mirrors engine.us_short_paper_net_result /
# engine.us_short_paper_ledger; the integration drift-guard test feeds real paper_net_result outputs through here)
_CLOSED = ("filled_stopped", "filled_tp_exit")
_OUTCOMES = ("cash_unfilled", "open_unrealized") + _CLOSED
_ENTRY_KEYS = frozenset({"outcome", "realized", "gross_return", "cost_fraction", "net_return", "unfilled_cash"})
_CLOSE_TOL = 1e-9
# the FROZEN paper-only evidence boundary every scorecard carries — paper is design-iteration evidence and is
# NEVER full-size ship-gate eligible (§12 / §18.1 #27; only live_normalized graduates). Mirrors the vocabulary of
# engine.us_short_paper_eval_gate so the two paper-evidence surfaces agree.
_BOUNDARY = {
    "evidence_level": "paper",
    "full_size_ship_gate_allowed": False,
    "ship_gate_evidence_level": "paper_not_live_normalized",
}
# the EXACT top-level key set a scorecard carries — validate_paper_scorecard is closed-world (the module is pure,
# so there is no additionalProperties:false schema; this validator IS the reusable consumer gate), so a smuggled
# ticker / per-name / contradictory top-level ship-gate-or-live field can never validate (de-identified + paper-only)
_SCORECARD_KEYS = frozenset({
    "selected_total", "filled_count", "unfilled_cash_count", "open_unrealized_count",
    "win_count", "loss_count", "flat_count", "bad_pick_rate", "total_cost_fraction",
    "fully_resolved", "net_basket", "boundary",
})


class PaperScorecardError(ValueError):
    """Raised when the basket lineage / a net_result shape / the scorecard contract is violated."""


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _validate_net_result(e, label) -> None:
    """Re-check one ``paper_net_result`` output's FULL per-outcome shape (the aggregator never trusts the producer):
    EXACTLY the 6 keys, and the per-outcome invariants — ``cash_unfilled`` = realized True / gross=cost=net=0.0 /
    unfilled_cash True; ``open_unrealized`` = realized False / gross=cost=net=None / unfilled_cash False; a closed
    outcome = realized True / unfilled_cash False / finite gross & net / finite NON-NEGATIVE cost /
    ``net_return == gross_return - cost_fraction``. Raises ``PaperScorecardError`` on any mismatch."""
    if not isinstance(e, dict):
        raise PaperScorecardError("net_result for %r must be a dict, got %r" % (label, type(e).__name__))
    if set(e) != _ENTRY_KEYS:
        raise PaperScorecardError("net_result for %r must carry EXACTLY %s, got %s" % (label, sorted(_ENTRY_KEYS), sorted(map(str, e))))
    outcome, r, g, c, n, u = e["outcome"], e["realized"], e["gross_return"], e["cost_fraction"], e["net_return"], e["unfilled_cash"]
    if outcome not in _OUTCOMES:
        raise PaperScorecardError("net_result for %r outcome %r not in %s" % (label, outcome, list(_OUTCOMES)))
    if outcome == "cash_unfilled":
        if not (r is True and u is True and _finite(g) and g == 0.0 and _finite(c) and c == 0.0 and _finite(n) and n == 0.0):
            raise PaperScorecardError("net_result for %r cash_unfilled must be realized=True / gross=cost=net=0.0 / unfilled_cash=True, got %r" % (label, e))
    elif outcome == "open_unrealized":
        if not (r is False and u is False and g is None and c is None and n is None):
            raise PaperScorecardError("net_result for %r open_unrealized must be realized=False / gross=cost=net=None / unfilled_cash=False, got %r" % (label, e))
    else:  # filled_stopped / filled_tp_exit
        if not (r is True and u is False and _finite(g) and _finite(c) and c >= 0 and _finite(n)):
            raise PaperScorecardError("net_result for %r %s must be realized=True / unfilled_cash=False / finite gross & net / finite non-negative cost, got %r" % (label, outcome, e))
        if not math.isclose(n, g - c, abs_tol=_CLOSE_TOL):
            raise PaperScorecardError("net_result for %r %s net_return %r != gross_return - cost_fraction (%r - %r)" % (label, outcome, n, g, c))


def _validate_selection(selected_tickers):
    """The frozen selection identity must be a list of UNIQUE non-blank strings (a real fixed TopN). Returns the
    set of tickers. Raises ``PaperScorecardError``."""
    if not isinstance(selected_tickers, list):
        raise PaperScorecardError("selected_tickers must be a list, got %r" % (type(selected_tickers).__name__,))
    seen = set()
    for t in selected_tickers:
        if not isinstance(t, str) or not t.strip():
            raise PaperScorecardError("selected_tickers must be non-blank strings, got %r" % (t,))
        if t in seen:
            raise PaperScorecardError("duplicate ticker %r in selected_tickers (a frozen selection is unique)" % (t,))
        seen.add(t)
    return seen


def build_paper_scorecard(net_results_by_ticker, *, selected_tickers) -> dict:
    """Aggregate ONE basket's per-position ``paper_net_result`` outputs into the §12.2 full-caliber scorecard.

    ``selected_tickers`` = the FROZEN selection identity (a profile's fixed TopN, unique non-blank strings);
    ``net_results_by_ticker`` = ``{ticker: paper_net_result output}``. FAILS CLOSED unless the map keys EXACTLY
    equal the selection (§12.2 禁止挑样本/全量 — no omitted selected name, no extra stale ticker), and every
    net_result is re-validated against the §12.1 contract. Returns de-identified counts + ``net_basket`` (equal-
    weight realized basket net over the whole selection, booked only when ``fully_resolved`` and non-empty, else
    None — §12.1 不虚高) + a FROZEN paper-only ``boundary``. Re-validated through ``validate_paper_scorecard`` before
    return. Raises ``PaperScorecardError`` on malformed input. PAPER only — never full-size ship-gate eligible (§12)."""
    selected = _validate_selection(selected_tickers)
    if not isinstance(net_results_by_ticker, dict):
        raise PaperScorecardError("net_results_by_ticker must be a dict, got %r" % (type(net_results_by_ticker).__name__,))
    keys = set(net_results_by_ticker)
    if keys != selected:
        raise PaperScorecardError(
            "net_results_by_ticker must cover EXACTLY the frozen selection (§12.2 禁止挑样本/全量): missing %s, extra %s"
            % (sorted(map(str, selected - keys)), sorted(map(str, keys - selected))))
    filled = unfilled = open_unrealized = win = loss = flat = 0
    total_cost = 0.0
    net_sum = 0.0  # equal-weight numerator over the whole selection (closed net + unfilled 0.0)
    for t in selected_tickers:                            # iterate the selection (deterministic) — coverage proven above
        e = net_results_by_ticker[t]
        _validate_net_result(e, t)
        outcome, n = e["outcome"], e["net_return"]
        if outcome == "cash_unfilled":
            unfilled += 1                                 # net 0.0 contributes to net_sum as cash (现金拖累)
        elif outcome == "open_unrealized":
            open_unrealized += 1                          # unrealized — excluded from net_sum; blocks a booked basket net
        else:                                             # closed
            filled += 1
            total_cost += e["cost_fraction"]
            net_sum += n
            if n > 0:
                win += 1
            elif n < 0:
                loss += 1
            else:
                flat += 1
    selected_total = len(selected_tickers)
    fully_resolved = open_unrealized == 0
    bad_pick_rate = (loss / filled) if filled else None   # fraction of FILLED positions that lost (§12.2 坏票率)
    net_basket = (net_sum / selected_total) if (fully_resolved and selected_total) else None
    result = {
        "selected_total": selected_total,
        "filled_count": filled,
        "unfilled_cash_count": unfilled,
        "open_unrealized_count": open_unrealized,
        "win_count": win,
        "loss_count": loss,
        "flat_count": flat,
        "bad_pick_rate": bad_pick_rate,
        "total_cost_fraction": total_cost,
        "fully_resolved": fully_resolved,
        "net_basket": net_basket,
        "boundary": dict(_BOUNDARY),
    }
    validate_paper_scorecard(result)
    return result


def validate_paper_scorecard(scorecard) -> None:
    """Fail-closed self-check of a scorecard (so a consumer can't be handed a flipped boundary / doctored counts /
    smuggled ticker fields): a CLOSED-WORLD top-level key set (EXACTLY ``_SCORECARD_KEYS`` — no unknown key, so a
    ``tickers`` / per-name field or a contradictory top-level ship-gate / live field can never validate, keeping the
    artifact de-identified + paper-only); the FROZEN paper-only boundary (never full-size ship-gate); non-negative
    int counts; ``filled == win+loss+flat``; ``selected_total == filled + unfilled_cash + open_unrealized``;
    ``fully_resolved == (open_unrealized == 0)``; ``bad_pick_rate == loss/filled`` (None iff nothing filled); and
    ``net_basket`` booked IFF fully_resolved and non-empty. Raises ``PaperScorecardError``."""
    if not isinstance(scorecard, dict):
        raise PaperScorecardError("scorecard must be a dict, got %r" % (type(scorecard).__name__,))
    if set(scorecard) != _SCORECARD_KEYS:
        raise PaperScorecardError(
            "scorecard must carry EXACTLY %s (closed-world — no ticker / ship-gate field may be smuggled in): missing %s, extra %s"
            % (sorted(_SCORECARD_KEYS), sorted(map(str, _SCORECARD_KEYS - set(scorecard))), sorted(map(str, set(scorecard) - _SCORECARD_KEYS))))
    if scorecard.get("boundary") != _BOUNDARY:
        raise PaperScorecardError("scorecard boundary must be the frozen paper-only block %r, got %r" % (_BOUNDARY, scorecard.get("boundary")))
    for k in ("selected_total", "filled_count", "unfilled_cash_count", "open_unrealized_count", "win_count", "loss_count", "flat_count"):
        v = scorecard.get(k)
        if not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
            raise PaperScorecardError("scorecard %s must be a non-negative int, got %r" % (k, v))
    st, fc, uc, oc = scorecard["selected_total"], scorecard["filled_count"], scorecard["unfilled_cash_count"], scorecard["open_unrealized_count"]
    win, loss, flat = scorecard["win_count"], scorecard["loss_count"], scorecard["flat_count"]
    if fc != win + loss + flat:
        raise PaperScorecardError("filled_count %d != win+loss+flat %d" % (fc, win + loss + flat))
    if st != fc + uc + oc:
        raise PaperScorecardError("selected_total %d != filled+unfilled+open %d" % (st, fc + uc + oc))
    if scorecard.get("fully_resolved") is not (oc == 0):
        raise PaperScorecardError("fully_resolved must be %r (open_unrealized == 0), got %r" % (oc == 0, scorecard.get("fully_resolved")))
    bpr = scorecard.get("bad_pick_rate")
    if fc == 0:
        if bpr is not None:
            raise PaperScorecardError("bad_pick_rate must be None when nothing filled, got %r" % (bpr,))
    elif not (_finite(bpr) and math.isclose(bpr, loss / fc, abs_tol=_CLOSE_TOL)):
        raise PaperScorecardError("bad_pick_rate %r != loss/filled %r" % (bpr, loss / fc))
    nb = scorecard.get("net_basket")
    if (oc == 0 and st):
        if not _finite(nb):
            raise PaperScorecardError("net_basket must be a finite number for a fully-resolved non-empty basket, got %r" % (nb,))
    elif nb is not None:
        raise PaperScorecardError("net_basket must be None for an unrealized / empty basket, got %r" % (nb,))
