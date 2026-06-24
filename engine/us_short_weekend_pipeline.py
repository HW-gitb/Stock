# -*- coding: utf-8 -*-
"""US-short weekend-pipeline orchestrator — batch4 slice 4d (selection front = 4d-i).

Design authority: docs/us_short_system_design.md §2 (architecture) / §2.1 (canonical decision day)
/ §4.0 (two-pass) / §18.2 batch4. First module to CHAIN the batch-4/2/3 pieces into one offline
run (confirmed no prior orchestrator). This 4d-i sub-slice wires the SELECTION FRONT:

    resolve_canonical_asof (4a)  →  [out-of-window → no-emit, §2.1]
      → universe (injected, NYSE/NASDAQ active-only)
      → Pass1: cheap_eligible (4c-ii) per row  +  inject_catalyst_recall (4c-ii)  → candidate set
      → Pass2: pass2_safety_admit (4c-ii, reuses §5 hard_veto); holdings forced in (§4.0)

The ANALYSIS chain (hard_veto→price_engine→regime→sizing→forward_events→action_rank), the §10
machine_record assembly + no-dangling validation, the lifecycle eval (before render), and the
§11.2 weekly_report render are slice 4d-ii (next) — NOT here.

All inputs are INJECTED via `data_context` (batch4 offline/fixture); batch5 fills `data_context`
from the real provider behind the same seam. The canonical `decision_date` is threaded from the
resolver into every consumer (§2.1). Pure/offline; no provider/live/network; no A-share crossing.
"""
from __future__ import annotations

from engine.us_short_canonical_asof import resolve_canonical_asof, OutOfWindowError
from engine.us_short_eligibility_gate import (
    canonical_us_ticker,
    cheap_eligible,
    inject_catalyst_recall,
    pass2_safety_admit,
    validate_eligibility_governance,
)

_REQUIRED_DATA_CONTEXT_KEYS = {"universe", "catalyst_recall_feed", "holdings", "candidate_pass2_signals"}


class WeekendPipelineError(Exception):
    """The injected pipeline data_context is malformed (fail-closed before any stage runs)."""


def _validate_data_context(dc):
    """Fail-closed shape gate for the injected data_context (closed-world top-level)."""
    if not isinstance(dc, dict):
        raise WeekendPipelineError("data_context 须为 dict")
    if set(dc) != _REQUIRED_DATA_CONTEXT_KEYS:
        raise WeekendPipelineError(
            f"data_context 顶层键须恰为 {sorted(_REQUIRED_DATA_CONTEXT_KEYS)}（closed-world）: {sorted(dc)}")
    if not isinstance(dc["universe"], list):
        raise WeekendPipelineError("data_context.universe 须为 list")
    if not isinstance(dc["holdings"], list):
        raise WeekendPipelineError("data_context.holdings 须为 list")
    if not isinstance(dc["candidate_pass2_signals"], dict):
        raise WeekendPipelineError("data_context.candidate_pass2_signals 须为 dict")
    # catalyst_recall_feed (None | list) is validated downstream by inject_catalyst_recall.
    for h in dc["holdings"]:
        if not (isinstance(h, dict) and isinstance(h.get("ticker"), str) and h["ticker"]
                and isinstance(h.get("signals"), dict)):
            raise WeekendPipelineError(f"holdings 行须为 {{'ticker': str, 'signals': dict}}: {h!r}")
    return dc


def run_selection(now_et, sessions, data_context, *, eligibility_governance):
    """4d-i selection front. Returns the candidate set + Pass2 admit decisions (no render/persist).

    now_et / sessions -> resolve_canonical_asof (§2.1). On the intraday DEAD ZONE the resolver
    raises OutOfWindowError; this returns an out-of-window NO-EMIT result (no candidates, nothing
    to persist downstream) per §2.1.

    data_context = {"universe": [cheap_eligible-shape row, ...],
                    "catalyst_recall_feed": None | [ticker, ...],   # batch5 feed; None offline
                    "holdings": [{"ticker": str, "signals": <hard_veto signals>}, ...],  # forced into Pass2;
                        # ticker canonicalized (invalid / A-share-code / post-canonical-dup -> fail-closed)
                    "candidate_pass2_signals": {ticker: <hard_veto signals dict>}}  # keys canonicalized;
                        # MUST exactly cover the final candidate set (incl. recall-added); a missing /
                        # non-canonical / duplicate / stale-extra key fails closed — NO default-clean (§3.3)
    eligibility_governance = a dict (validated here via validate_eligibility_governance — runtime
    consumer-validation edge; never trust an unvalidated governance artifact).

    Returns {decision_date, price_basis_date, run_date, out_of_window: bool, cheap_eligible: [ticker],
             candidates: [ticker], recall_available: bool, recall_added: [ticker],
             admitted: [ticker], holdings: [{ticker, admit_to_topn, veto_tier}]}.
    """
    try:
        canon = resolve_canonical_asof(now_et, sessions)
    except OutOfWindowError:
        return {
            "out_of_window": True, "decision_date": None, "price_basis_date": None,
            "run_date": now_et.strftime("%Y%m%d"),
            "cheap_eligible": [], "candidates": [], "recall_available": False, "recall_added": [],
            "admitted": [], "holdings": [],
        }

    gov = validate_eligibility_governance(eligibility_governance)
    dc = _validate_data_context(data_context)

    # Pass1: cheap eligibility -> canonical eligible tickers (cheap_eligible emits the canonical id).
    cheap_eligible_tickers = []
    for row in dc["universe"]:
        res = cheap_eligible(row, governance=gov)
        if res["eligible"]:
            cheap_eligible_tickers.append(res["ticker"])

    # Pass1 + catalyst_recall injection -> candidate set (unique canonical tickers).
    recall = inject_catalyst_recall(cheap_eligible_tickers, recall_feed=dc["catalyst_recall_feed"])
    candidates = recall["candidates"]

    # Pass2 audit-safety-gate (reuses §5 hard_veto). The Pass2 signal map must cover the final
    # candidate set EXACTLY under the canonical identity — a missing / miscased / stale / non-canonical
    # key is NOT a clean payload by default (§3.3: a missing audit signal must not pass the gate).
    canon_pass2 = {}
    for k, v in dc["candidate_pass2_signals"].items():
        ck = canonical_us_ticker(k)
        if ck is None:
            raise WeekendPipelineError(f"candidate_pass2_signals 键非规范 US ticker: {k!r}")
        if ck in canon_pass2:
            raise WeekendPipelineError(f"candidate_pass2_signals 含规范化后重复键: {ck!r}")
        if not isinstance(v, dict):
            raise WeekendPipelineError(f"candidate_pass2_signals[{k!r}] 须为 dict（hard_veto signals）")
        canon_pass2[ck] = v
    cand_set = set(candidates)
    missing = cand_set - set(canon_pass2)
    if missing:
        raise WeekendPipelineError(f"candidate_pass2_signals 缺候选 Pass2 信号（不得默认 clean）: {sorted(missing)}")
    stale = set(canon_pass2) - cand_set
    if stale:
        raise WeekendPipelineError(f"candidate_pass2_signals 含非候选陈旧键: {sorted(stale)}")
    admitted = [t for t in candidates
                if pass2_safety_admit(canon_pass2[t], row_context="candidate")["admit_to_topn"]]

    # Holdings forced into Pass2 (§4.0); canonicalize identity with the SAME policy as candidates
    # (no second identity space; reject invalid / A-share-code / post-canonical duplicate); veto surfaced.
    holdings = []
    seen_holdings = set()
    for h in dc["holdings"]:
        ct = canonical_us_ticker(h["ticker"])
        if ct is None:
            raise WeekendPipelineError(f"holding ticker 非规范 US ticker（拒 A 股码/坏形）: {h['ticker']!r}")
        if ct in seen_holdings:
            raise WeekendPipelineError(f"holdings 含规范化后重复 ticker: {ct!r}")
        seen_holdings.add(ct)
        adm = pass2_safety_admit(h["signals"], row_context="holding")
        holdings.append({"ticker": ct, "admit_to_topn": adm["admit_to_topn"], "veto_tier": adm["veto_tier"]})

    return {
        "out_of_window": False,
        "decision_date": canon["decision_date"],
        "price_basis_date": canon["price_basis_date"],
        "run_date": canon["run_date"],
        "cheap_eligible": cheap_eligible_tickers,
        "candidates": candidates,
        "recall_available": recall["recall_available"],
        "recall_added": recall["recall_added"],
        "admitted": admitted,
        "holdings": holdings,
    }
