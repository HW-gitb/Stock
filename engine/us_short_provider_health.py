# -*- coding: utf-8 -*-
"""US-short provider health-check — batch-3 OFFLINE strategy/structure (§18.1 #3 离线 / §3.7 / §3.2 / §18.0 P0).

Design authority: docs/us_short_system_design.md §3.1 (数据三档 / 授权源) / §3.2 (运行状态
clean/usable_with_fallback/restricted/blocked) / §3.7 (数据源分层健康检查, 跑前必做) / §18.1 #3 / §18.0 P0
(SR-PROVIDER-001 数据授权硬边界).

OFFLINE classifier ONLY — it takes INJECTED per-source health for the AUTHORIZED sources and computes the
run-state; it performs NO live probe / network / provider import (live 探活 is batch 5, gated). Two hard rules
from §3.1 / §18.1 #3:

  * a critical authorized source that is degraded / down does NOT stay `clean` — it fails closed to
    `restricted` / `blocked` (关键源坏 → 不输出 clean);
  * UNAUTHORIZED sources (yfinance / Web·X / FMP full-market / paid feeds — not in the current $0 small-sample
    authorization, SR-PROVIDER-001) are ALWAYS `disabled_unapproved` and may NEVER be probed or counted toward
    `clean`. This is enforced STRUCTURALLY: `classify_provider_health` REFUSES a status for any non-authorized
    source (you cannot even hand it an unauthorized source's health), so the health check can never touch one
    (§18.1 #3 「健康检查绝不触达未授权源」).

Pure / offline: no provider/live/DataHub/network import; no A-share crossing.
"""
from __future__ import annotations

# Current $0 small-sample authorization (§3.1 / §18.0 P0, SR-PROVIDER-001). FMP (existing key, small sample) +
# public SEC EDGAR only; both are CRITICAL (price/score/veto + audit/veto), so either degraded/down ⇒ not clean.
AUTHORIZED_SOURCES = frozenset({"fmp", "sec_edgar"})
CRITICAL_SOURCES = frozenset({"fmp", "sec_edgar"})
# Explicitly NOT authorized → always disabled_unapproved, never probed (full-market FMP / yfinance / Web·X /
# paid feeds all need a separate reviewed approval, §18.0 P0).
UNAUTHORIZED_SOURCES = frozenset({"fmp_full_market", "yfinance", "web_x", "sec_parser", "paid_borrow_options", "dark_pool"})

_INPUT_STATES = frozenset({"ok", "degraded", "down", "missing"})
RUN_STATES = frozenset({"clean", "usable_with_fallback", "restricted", "blocked", "disabled_unapproved"})
_SEVERITY = {"clean": 0, "usable_with_fallback": 1, "restricted": 2, "blocked": 3}  # worst-of ordering


class ProviderHealthError(ValueError):
    """Raised when the health check is handed a non-authorized source (it must never probe/consider one)."""


def _source_state(source: str, status: str) -> str:
    """Map an AUTHORIZED source's injected status to a §3.2 run-state. A critical source degraded/down fails
    closed (restricted/blocked); a non-critical one may run usable_with_fallback."""
    critical = source in CRITICAL_SOURCES
    if status == "ok":
        return "clean"
    if status == "degraded":
        return "restricted" if critical else "usable_with_fallback"
    # down / missing
    return "blocked" if critical else "usable_with_fallback"


def classify_provider_health(authorized_statuses) -> dict:
    """Classify the run-state from INJECTED authorized-source statuses (offline; no live probe).

    ``authorized_statuses`` maps an AUTHORIZED source id → one of {ok, degraded, down, missing}. Passing ANY
    non-authorized source id raises ``ProviderHealthError`` — the health check structurally cannot probe /
    consider an unauthorized source (§18.1 #3 「绝不触达未授权源」). A missing AUTHORIZED source (absent from the
    map) is treated as `missing` → blocked (a critical source we could not check is not clean). Returns
    ``{sources: {id: state}, overall_run_state, disabled_unapproved: [...sorted unauthorized...]}``; the overall
    is the worst-of the authorized states, and the always-`disabled_unapproved` unauthorized sources never
    participate in it.
    """
    if not isinstance(authorized_statuses, dict):
        raise ProviderHealthError("authorized_statuses must be a dict of {authorized_source: status}")
    sources: dict = {}
    for src, status in authorized_statuses.items():
        if src not in AUTHORIZED_SOURCES:
            raise ProviderHealthError(
                "health check must NOT probe / consider non-authorized source %r — it is disabled_unapproved "
                "(§3.1 / §18.0 SR-PROVIDER-001); only %s are authorized" % (src, sorted(AUTHORIZED_SOURCES))
            )
        if status not in _INPUT_STATES:
            raise ProviderHealthError("source %r has an invalid status %r (expected %s)" % (src, status, sorted(_INPUT_STATES)))
        sources[src] = _source_state(src, status)
    # every authorized source must be accounted for — a critical source we did not check is `missing` → blocked
    for src in AUTHORIZED_SOURCES:
        if src not in sources:
            sources[src] = _source_state(src, "missing")
    overall = max((sources[s] for s in AUTHORIZED_SOURCES), key=lambda st: _SEVERITY[st])
    return {
        "sources": sources,
        "overall_run_state": overall,
        "disabled_unapproved": sorted(UNAUTHORIZED_SOURCES),
    }


def validate_provider_health_result(result) -> bool:
    """True iff `result` is a structurally-valid, INTERNALLY-CONSISTENT `classify_provider_health` output — the
    exact {sources, overall_run_state, disabled_unapproved} shape; `sources` covering EXACTLY the authorized
    sources with valid §3.2 run-states; `overall_run_state` == the worst-of those states; and `disabled_unapproved`
    == the sorted unauthorized sources. Lets a consumer (e.g. the §11.2 weekly report) REJECT a FABRICATED health
    dict (e.g. `{"overall_run_state":"clean"}` with no real sources) that this classifier did not produce."""
    if not (isinstance(result, dict) and set(result) == {"sources", "overall_run_state", "disabled_unapproved"}):
        return False
    sources = result["sources"]
    if not (isinstance(sources, dict) and set(sources) == set(AUTHORIZED_SOURCES)
            and all(st in _SEVERITY for st in sources.values())):
        return False
    overall = result["overall_run_state"]
    if overall not in _SEVERITY or overall != max(sources.values(), key=lambda st: _SEVERITY[st]):
        return False
    return result["disabled_unapproved"] == sorted(UNAUTHORIZED_SOURCES)
