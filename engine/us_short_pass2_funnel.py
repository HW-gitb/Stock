from __future__ import annotations

import math
from typing import Any


class Pass2FunnelError(ValueError):
    """The Pass 2 funnel target cannot be derived safely (bad momentum-score / eligible / holdings / top_k input)."""


def _canonical_str_set(value: Any, *, field: str) -> set[str]:
    if type(value) not in (set, frozenset, list, tuple):
        raise Pass2FunnelError(f"{field} must be a set/frozenset/list/tuple of exact ticker strings")
    out: set[str] = set()
    for item in value:
        if type(item) is not str:
            raise Pass2FunnelError(f"{field} must contain exact ticker strings")
        out.add(item)
    return out


def select_pass2_targets(
    *,
    momentum_scores: Any,
    eligible: Any,
    forced_holdings: Any,
    top_k: int,
) -> list[str]:
    """Derive the Pass 2 funnel target =
        sorted( top-K( momentum-scored ∩ eligible, ranked by score DESC then canonical ticker ASC ) ∪ forced_holdings ).

    This is the SINGLE source of the funnel selection, imported by BOTH the Pass2 preflight
    (`_pass2_target_universe`) and the live source-packet runner (`_rederive_and_verify_pass2_targets`) so the two
    are PROVABLY identical — preserving the R-USSHORT-BATCH5-LIVE-RUNNER-TRUSTS-PREFLIGHT-FUNNEL-NOT-REDERIVED
    hardening (the runner still independently re-derives and must equal the preflight target). Pure / offline /
    deterministic; fails closed (typed `Pass2FunnelError`) on any bad-shaped input.

    momentum_scores: {ticker: score} — the momentum-scored map (exact dict; exact-str canonical keys; finite
        numeric scores; the tickers are assumed already canonicalized by the caller, matching `eligible`).
    eligible / forced_holdings: iterables of canonical tickers (exact-str); forced_holdings must be a subset of
        eligible (they are re-evaluated every week and are always kept even if below the top-K).
    top_k: positive int cap on the momentum-selected count. Forced holdings are added ON TOP of the top-K and are
        always kept, so the returned count can exceed top_k by the number of holdings not already in the top-K.
    """
    if type(top_k) is not int or isinstance(top_k, bool) or top_k <= 0:
        raise Pass2FunnelError("top_k must be a positive int")
    if type(momentum_scores) is not dict:
        raise Pass2FunnelError("momentum_scores must be an exact dict")
    eligible_set = _canonical_str_set(eligible, field="eligible")
    holdings_set = _canonical_str_set(forced_holdings, field="forced_holdings")
    missing_holdings = sorted(holdings_set - eligible_set)
    if missing_holdings:
        raise Pass2FunnelError(f"forced_holdings must be within the eligible set: {missing_holdings[:10]}")

    scored_eligible: list[tuple[str, float]] = []
    seen: set[str] = set()
    for ticker, score in momentum_scores.items():
        if type(ticker) is not str:
            raise Pass2FunnelError("momentum_scores keys must be exact str")
        if ticker in seen:
            raise Pass2FunnelError(f"momentum_scores contains a duplicate ticker: {ticker}")
        seen.add(ticker)
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise Pass2FunnelError(f"momentum_scores[{ticker}] must be a finite number")
        if ticker in eligible_set:
            scored_eligible.append((ticker, float(score)))

    # Deterministic across weeks: score DESC, then canonical ticker ASC as the tie-break.
    scored_eligible.sort(key=lambda item: (-item[1], item[0]))
    selected = {ticker for ticker, _ in scored_eligible[:top_k]}
    target = selected | holdings_set
    return sorted(target)
