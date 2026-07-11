from __future__ import annotations

import math
from typing import Any


class Pass2FunnelError(ValueError):
    """The Pass 2 funnel target cannot be derived safely."""


def _canonical_str_set(value: Any, *, field: str) -> set[str]:
    if type(value) not in (set, frozenset, list, tuple):
        raise Pass2FunnelError(f"{field} must be a set/frozenset/list/tuple of exact ticker strings")
    out: set[str] = set()
    for item in value:
        if type(item) is not str:
            raise Pass2FunnelError(f"{field} must contain exact ticker strings")
        out.add(item)
    return out


def _score_map(value: Any, *, field: str) -> dict[str, float]:
    if type(value) is not dict:
        raise Pass2FunnelError(f"{field} must be an exact dict")
    out: dict[str, float] = {}
    for ticker, score in value.items():
        if type(ticker) is not str:
            raise Pass2FunnelError(f"{field} keys must be exact str")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise Pass2FunnelError(f"{field}[{ticker}] must be a finite number")
        out[ticker] = float(score)
    return out


def select_pass2_targets(
    *,
    momentum_scores: Any,
    theme_scores: Any,
    eligible: Any,
    catalyst_recall: Any,
    forced_holdings: Any,
    top_k: int,
) -> list[str]:
    """Return cheap two-axis top-K plus bounded catalyst recall and mandatory holdings.

    The ranked lane averages available momentum/theme scores, using 50 as the neutral value when only one cheap
    component is present. Catalyst recall must remain inside the reviewed Pass1-eligible universe. Holdings are a
    separate mandatory risk lane and may be outside today's eligible set. Both callers import this pure selector.
    """
    if type(top_k) is not int or isinstance(top_k, bool) or top_k <= 0:
        raise Pass2FunnelError("top_k must be a positive int")
    eligible_set = _canonical_str_set(eligible, field="eligible")
    recall_set = _canonical_str_set(catalyst_recall, field="catalyst_recall")
    holdings_set = _canonical_str_set(forced_holdings, field="forced_holdings")
    stale_recall = sorted(recall_set - eligible_set)
    if stale_recall:
        raise Pass2FunnelError(f"catalyst_recall must be within the eligible set: {stale_recall[:10]}")

    momentum = _score_map(momentum_scores, field="momentum_scores")
    theme = _score_map(theme_scores, field="theme_scores")
    scored_eligible: list[tuple[str, float]] = []
    for ticker in sorted((set(momentum) | set(theme)) & eligible_set):
        cheap_score = (momentum.get(ticker, 50.0) + theme.get(ticker, 50.0)) / 2.0
        scored_eligible.append((ticker, cheap_score))

    scored_eligible.sort(key=lambda item: (-item[1], item[0]))
    selected = {ticker for ticker, _ in scored_eligible[:top_k]}
    return sorted(selected | recall_set | holdings_set)
