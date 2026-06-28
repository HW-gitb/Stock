# -*- coding: utf-8 -*-
"""US-short weekend-pipeline orchestrator — batch4 slice 4d (selection front = 4d-i).

Design authority: docs/us_short_system_design.md §2 (architecture) / §2.1 (canonical decision day)
/ §4.0 (two-pass) / §18.2 batch4. First module to CHAIN the batch-4/2/3 pieces into one offline
run (confirmed no prior orchestrator). This 4d-i sub-slice wires the SELECTION FRONT:

    resolve_canonical_asof (4a)  →  [out-of-window → no-emit, §2.1]
      → universe (injected, NYSE/NASDAQ active-only)
      → Pass1: cheap_eligible (4c-ii) per row  +  inject_catalyst_recall (4c-ii)  → candidate set
      → Pass2: pass2_safety_admit (4c-ii, reuses §5 hard_veto); holdings forced in (§4.0)
      → injected selection_inputs: dynamic core/theme seats → Top15 admitted set (§4.5)

The ANALYSIS chain (hard_veto→price_engine→regime→sizing→forward_events→action_rank), the §10
machine_record assembly + no-dangling validation, the lifecycle eval (before render), and the
§11.2 weekly_report render are slice 4d-ii (next) — NOT here.

All inputs are INJECTED via `data_context` (batch4 offline/fixture); batch5 fills `data_context`
from the real provider behind the same seam. `selection_inputs` is likewise injected: batch4 fixtures / batch5
provider evidence supply the expensive post-Pass2 score inputs behind the same closed-world seam. The canonical
`decision_date` is threaded from the resolver into every consumer (§2.1). Pure/offline; no provider/live/network;
no A-share crossing.
"""
from __future__ import annotations

import math

from engine.us_short_canonical_asof import resolve_canonical_asof, OutOfWindowError
from engine.us_short_dynamic_seats import SELECTION_SEAT_TOTAL, selection_seats
from engine.us_short_eligibility_gate import (
    canonical_us_ticker,
    cheap_eligible,
    inject_catalyst_recall,
    pass2_safety_admit,
    validate_eligibility_governance,
)
from engine.us_short_selection_exclusions import pass1_category, pass2_category

_REQUIRED_DATA_CONTEXT_KEYS = {
    "universe", "catalyst_recall_feed", "holdings", "candidate_pass2_signals", "selection_inputs"}
_SELECTION_INPUT_KEYS = {"theme_opportunity_state", "per_ticker"}
_SELECTION_ROW_KEYS = {"core_score", "theme_momentum_score"}


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
    if not isinstance(dc["selection_inputs"], dict):
        raise WeekendPipelineError("data_context.selection_inputs 须为 dict")
    # catalyst_recall_feed (None | list) is validated downstream by inject_catalyst_recall.
    for h in dc["holdings"]:
        if not (isinstance(h, dict) and isinstance(h.get("ticker"), str) and h["ticker"]
                and isinstance(h.get("signals"), dict)):
            raise WeekendPipelineError(f"holdings 行须为 {{'ticker': str, 'signals': dict}}: {h!r}")
    return dc


def _score_0_100(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise WeekendPipelineError(f"{where} 须为 0-100 有限数值: {value!r}")
    score = float(value)
    if not 0.0 <= score <= 100.0:
        raise WeekendPipelineError(f"{where} 须在 0-100: {value!r}")
    return score


def _select_top15(admitted_candidates, selection_inputs):
    """Apply §4.5 dynamic Top15 seats to the Pass2-clean candidate set.

    The injected `selection_inputs` must canonically cover Pass2-clean admitted candidates exactly. This keeps
    batch4 offline/fixture-only while still enforcing the actual Top15 contract before analysis runs.
    """
    if set(selection_inputs) != _SELECTION_INPUT_KEYS:
        raise WeekendPipelineError(
            f"selection_inputs 顶层键须恰为 {sorted(_SELECTION_INPUT_KEYS)}（closed-world）: {sorted(selection_inputs)}")
    if not isinstance(selection_inputs["per_ticker"], dict):
        raise WeekendPipelineError("selection_inputs.per_ticker 须为 dict")

    admitted_set = set(admitted_candidates)
    scores = {}
    for k, v in selection_inputs["per_ticker"].items():
        ck = canonical_us_ticker(k)
        if ck is None:
            raise WeekendPipelineError(f"selection_inputs.per_ticker 键非规范 US ticker: {k!r}")
        if ck in scores:
            raise WeekendPipelineError(f"selection_inputs.per_ticker 含规范化后重复键: {ck!r}")
        if not (isinstance(v, dict) and set(v) == _SELECTION_ROW_KEYS):
            raise WeekendPipelineError(
                f"selection_inputs.per_ticker[{k!r}] 须为 {{{sorted(_SELECTION_ROW_KEYS)}}}: {v!r}")
        scores[ck] = {
            "core_score": _score_0_100(v["core_score"], f"selection_inputs[{ck}].core_score"),
            "theme_momentum_score": _score_0_100(
                v["theme_momentum_score"], f"selection_inputs[{ck}].theme_momentum_score"),
        }
    if set(scores) != admitted_set:
        raise WeekendPipelineError(
            "selection_inputs.per_ticker 须恰覆盖 Pass2-clean admitted 候选（缺 %s / 多 %s）"
            % (sorted(admitted_set - set(scores)), sorted(set(scores) - admitted_set)))

    state = selection_inputs["theme_opportunity_state"]
    seats = selection_seats(state if isinstance(state, str) else None)
    target_total = min(SELECTION_SEAT_TOTAL, len(admitted_candidates))
    core_rank = sorted(admitted_candidates, key=lambda t: (-scores[t]["core_score"], t))
    theme_rank = sorted(admitted_candidates,
                        key=lambda t: (-scores[t]["theme_momentum_score"], -scores[t]["core_score"], t))
    selected, details = [], {}

    def add(ticker, bucket):
        if ticker not in details:
            selected.append(ticker)
            details[ticker] = {"ticker": ticker, "selection_bucket": bucket,
                               "core_score": scores[ticker]["core_score"],
                               "theme_momentum_score": scores[ticker]["theme_momentum_score"]}
        elif bucket == "overlap":
            details[ticker]["selection_bucket"] = "overlap"

    for ticker in core_rank[:seats["core_top"]]:
        add(ticker, "core_top")

    theme_added = 0
    for ticker in theme_rank:
        if ticker in details:
            add(ticker, "overlap")  # same row, theme seat rolls forward to the next theme-ranked name
            continue
        add(ticker, "theme_momentum")
        theme_added += 1
        if theme_added >= seats["theme_momentum"]:
            break

    for ticker in core_rank:
        if len(selected) >= target_total:
            break
        if ticker not in details:
            add(ticker, "core_backfill")

    selected = selected[:target_total]
    return {"admitted": selected, "selection_seats": seats,
            "selection_details": [{**details[t], "selection_rank": i}
                                  for i, t in enumerate(selected, start=1)]}


def run_selection(now_et, sessions, data_context, *, eligibility_governance):
    """4d-i selection front. Returns the candidate set + Pass2 admit decisions (no render/persist).

    now_et / sessions -> resolve_canonical_asof (§2.1). On the intraday DEAD ZONE the resolver
    raises OutOfWindowError; this returns an out-of-window NO-EMIT result (no candidates, nothing
    to persist downstream) per §2.1.

    data_context = {"universe": [cheap_eligible-shape row, ...],
                    "catalyst_recall_feed": None | [ticker, ...],   # batch5 feed; None offline
                    "holdings": [{"ticker": str, "signals": <hard_veto signals>}, ...],  # forced into Pass2;
                        # ticker canonicalized (invalid / A-share-code / post-canonical-dup -> fail-closed)
                    "candidate_pass2_signals": {ticker: <hard_veto signals dict>},  # keys canonicalized;
                        # MUST exactly cover the final candidate set (incl. recall-added); a missing /
                        # non-canonical / duplicate / stale-extra key fails closed — NO default-clean (§3.3)
                    "selection_inputs": {"theme_opportunity_state": str,
                                         "per_ticker": {ticker: {"core_score": 0-100,
                                                                "theme_momentum_score": 0-100}}}}
    eligibility_governance = a dict (validated here via validate_eligibility_governance — runtime
    consumer-validation edge; never trust an unvalidated governance artifact).

    Returns {decision_date, price_basis_date, run_date, out_of_window: bool, cheap_eligible: [ticker],
             candidates: [ticker], recall_available: bool, recall_added: [ticker],
             recall_excluded: [{ticker, reason}],   # off-universe / below-floor recalls (not admitted, §4.0)
             admitted: [Top15 ticker], selection_seats, selection_details,
             holdings: [{ticker, admit_to_topn, veto_tier}]}.
    """
    try:
        canon = resolve_canonical_asof(now_et, sessions)
    except OutOfWindowError:
        return {
            "out_of_window": True, "decision_date": None, "price_basis_date": None,
            "run_date": now_et.strftime("%Y%m%d"),
            "cheap_eligible": [], "candidates": [], "recall_available": False, "recall_added": [],
            "recall_excluded": [],
            "exclusion_records": [],
            "admitted": [], "selection_seats": None, "selection_details": [], "holdings": [],
        }

    gov = validate_eligibility_governance(eligibility_governance)
    dc = _validate_data_context(data_context)

    # Pass1: cheap eligibility -> canonical eligible tickers (cheap_eligible emits the canonical id). Build the
    # per-row tradability-floor verdict map (canonical ticker -> eligible bool) so the catalyst recall lane gates
    # against the SAME floor — a recalled name must be an active universe row that passes Pass1, not a bypass.
    cheap_eligible_tickers = []
    universe_eligibility = {}
    exclusion_records = []
    for row in dc["universe"]:
        res = cheap_eligible(row, governance=gov)
        ct = res["ticker"]
        if ct is not None:
            # ONE canonical identity = ONE Pass1 verdict: a duplicate canonical universe row fails closed (never
            # silent last-row-wins, which could overwrite an eligible verdict with a below-floor one or vice versa).
            if ct in universe_eligibility:
                raise WeekendPipelineError(
                    f"universe 含规范化后重复 ticker（一身份一行一裁决，不静默 last-row-wins）: {ct!r}")
            universe_eligibility[ct] = res["eligible"]            # floor verdict (eligible OR below-floor)
        if res["eligible"]:
            cheap_eligible_tickers.append(ct)
        else:
            exclusion_records.append({
                "stage": "pass1_eligibility", "ticker": ct,
                "category": pass1_category(res["reasons"]), "reasons": list(res["reasons"]),
            })

    # Pass1 + catalyst_recall injection -> candidate set (unique canonical tickers). Recall is FLOORED: an
    # off-universe / below-floor recalled name is recorded recall_excluded (not admitted), never a tradability bypass.
    recall = inject_catalyst_recall(cheap_eligible_tickers, recall_feed=dc["catalyst_recall_feed"],
                                    universe_eligibility=universe_eligibility)
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
    pass2_admitted = []
    for ticker in candidates:
        verdict = pass2_safety_admit(canon_pass2[ticker], row_context="candidate")
        if verdict["admit_to_topn"]:
            pass2_admitted.append(ticker)
        else:
            exclusion_records.append({
                "stage": "pass2_audit_gate", "ticker": ticker,
                "category": pass2_category(verdict["reasons"]), "reasons": list(verdict["reasons"]),
            })
    top15 = _select_top15(pass2_admitted, dc["selection_inputs"])
    selected_set = set(top15["admitted"])
    for ticker in pass2_admitted:
        if ticker not in selected_set:
            exclusion_records.append({
                "stage": "top15_selection", "ticker": ticker, "category": "分不够",
                "reasons": ["outside_top15_by_frozen_selection_rank"],
            })

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
        "recall_excluded": recall["recall_excluded"],
        "exclusion_records": exclusion_records,
        "admitted": top15["admitted"],
        "selection_seats": top15["selection_seats"],
        "selection_details": top15["selection_details"],
        "holdings": holdings,
    }
