# -*- coding: utf-8 -*-
"""US-short weekend-pipeline per-row analysis stage — batch4 slice 4d-ii-a (analysis evidence).

Design authority: docs/us_short_system_design.md §5 (hard veto) / §6 (price engine + 优先级链) /
§7 (market risk regime) / §8 (sizing — only the regime cap input is read here) / §8.1 (forward
events) / §4.2 (core_score) / §18.2 batch4.

The second batch-4 stage (after 4d-i selection). For each pre-assembled analysis row it gathers the
per-row ANALYSIS EVIDENCE by running the existing pure engines under ONE market regime computed once
for the run:

    compute_market_risk_regime (§7, once)        → regime + position cap (the §8 sizing input)
    per row →
        classify_hard_veto (§5)                  → veto tier / effect / reasons
        support_atr_engine | holding_exit_engine → §6 priority routing by row_source context
        forward_event_effect + event_data_gap_status (§8.1)
        core_score (§4.2; rows that carry score blocks)

This is EVIDENCE ONLY. It does NOT decide final_action, run the §8 reduction stack with cross-row
caps, allocate cash, or rank (§9) — that is slice 4d-ii-b; it does not assemble / validate the §10
machine_record (4d-ii-c) or render (4d-ii-d). The price engine is run with the row's RESOLVED
sub_mode: the §8 防御-档 "default pullback, no breakout chase" guard is applied here because the
price geometry depends on the sub_mode, but the breakout-probe exception's min-size / ≤1-slot /
in-band caps stay in §8 sizing = 4d-ii-b. A candidate's veto is computed as evidence but does NOT
suppress its price plan here (the §6 hard-veto gate on the build plan is a 4d-ii-b decision).

All inputs are INJECTED (batch4 offline/fixture); batch5 fills them from the real provider behind the
same seam. Ticker identity is canonicalized with the SAME policy as 4c/4d-i (one identity per stock,
unique across rows). Pure/offline; no provider/live/network; no A-share crossing.
"""
from __future__ import annotations

from engine.us_short_core_score import PRIMARY_PROFILE, core_score
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_forward_events import event_data_gap_status, forward_event_effect
from engine.us_short_hard_veto import classify_hard_veto, row_source_to_context
from engine.us_short_overextension import validate_overextension_result
from engine.us_short_price_engine import PRICE_SUB_MODES, holding_exit_engine, support_atr_engine
from engine.us_short_regime import compute_market_risk_regime
from engine.us_short_risk_downgrade import validate_risk_downgrade_input

# §8 防御/极度防御: new entries default to pullback only — no breakout chase in a weak market. The
# single exception (a theme-extreme min-size probe) is caller-asserted via the row flag below; its
# min-size / ≤1-slot / in-band caps live in §8 sizing = 4d-ii-b.
_NO_CHASE_BREAKOUT_REGIMES = ("防御", "极度防御")


class WeekendAnalysisError(Exception):
    """An injected analysis row is malformed (fail-closed before / around the engines run)."""


def _resolve_candidate_sub_mode(requested, regime, defensive_breakout_probe_allowed):
    """§6/§8 sub_mode for a candidate. `requested` MUST be a valid price sub_mode (PRICE_SUB_MODES =
    pullback|breakout) — an invalid value is a malformed injected row and fails CLOSED (never silently
    rewritten to pullback). A pullback request → pullback. A breakout request is honored in 进攻/震荡; in
    防御/极度防御 it is downgraded to pullback (no chase in a weak market) UNLESS the caller asserts the
    §8 防御 breakout-probe exception (a real-True `defensive_breakout_probe_allowed`: theme_opportunity_state
    extreme + 当周不跳空) — and even then only in 防御 (极度防御 caps at 0.0 → no new entry at all, §8).
    Returns (sub_mode, downgraded)."""
    if requested not in PRICE_SUB_MODES:
        raise WeekendAnalysisError(
            f"candidate sub_mode 非法（须 ∈ {PRICE_SUB_MODES} 或缺省 pullback，不静默改写）: {requested!r}")
    if requested != "breakout":
        return "pullback", False
    if regime in _NO_CHASE_BREAKOUT_REGIMES:
        if regime == "防御" and defensive_breakout_probe_allowed is True:
            return "breakout", False
        return "pullback", True
    return "breakout", False


def _validate_overextension(value):
    """Validate an injected §4.3 overextension result (from the scoring-stage `build_overextension_projection`
    map, threaded onto the row). None (absent — the ticker had insufficient data or wasn't scored) → None (no
    signal, no-op). A PRESENT record must satisfy the shared closed-world state/strip/flags contract — else it
    fails CLOSED (缺数据≠安全; a malformed or contradictory record must not silently skip/add an execution lever).
    Returns the record or None."""
    if value is None:
        return None
    try:
        validate_overextension_result(value)
    except ValueError as exc:
        raise WeekendAnalysisError(f"overextension 违反 §4.3 状态/效果闭集契约: {value!r}") from exc
    return value


def _analyze_one(row, regime):
    """Run the per-row evidence chain for one pre-assembled analysis row under the (already computed)
    market `regime`. Fail-closed on a malformed row shape / non-canonical ticker / unknown row_source /
    unknown scoring_profile; the engines themselves degrade-to-observe on missing price/score inputs."""
    if not isinstance(row, dict):
        raise WeekendAnalysisError(f"analysis row 须为 dict: {row!r}")
    ticker = canonical_us_ticker(row.get("ticker"))
    if ticker is None:
        raise WeekendAnalysisError(f"analysis row ticker 非规范 US ticker（拒 A 股码/坏形）: {row.get('ticker')!r}")
    try:
        context = row_source_to_context(row.get("row_source"))   # raises ValueError on unknown row_source
    except ValueError as e:
        raise WeekendAnalysisError(str(e))

    veto = classify_hard_veto(row.get("signals"), context)       # fail-closed on a non-dict signals object

    # §4.3 overextension (computed at the scoring/producer stage, injected onto the row): the `warning` tier's
    # execution_flags carry force_pullback — a candidate execution lever applied here; chasing_extreme carries NO
    # execution_flags. A chasing_extreme record also makes score recomputation remove only the selected profile's
    # theme contribution; the two tiers are mutually exclusive. A PRESENT-but-malformed record fails CLOSED;
    # absent → no signal (no-op).
    overext = _validate_overextension(row.get("overextension"))

    if context == "holding":
        price = holding_exit_engine(row.get("price_input"), regime, row.get("event_reference_price"))
        sub_mode_resolved, sub_mode_downgraded, overext_forced_pullback = None, False, False
        holding_action_context = row.get("holding_action_context")
        if isinstance(holding_action_context, dict):
            price_input = row.get("price_input")
            holding_action_context = {**holding_action_context,
                                      "price_basis_value": price_input.get("close") if isinstance(price_input, dict) else None}
    else:  # candidate
        requested_sub_mode = row["sub_mode"] if "sub_mode" in row else "pullback"   # absent → pullback default
        probe = row.get("defensive_breakout_probe_allowed", False)                 # absent → not allowed
        if not isinstance(probe, bool):   # a PRESENT probe assertion must be a real bool — surface a bad caller flag
            raise WeekendAnalysisError(f"defensive_breakout_probe_allowed 须为 bool 或缺省: {probe!r}")
        sub_mode_resolved, sub_mode_downgraded = _resolve_candidate_sub_mode(requested_sub_mode, regime, probe)
        # §4.3 warning → 强制 pullback_mode 入场（不追突破）: an execution-side downgrade applied AFTER the §8
        # defensive downgrade (both only ever force breakout→pullback, never the reverse — so composing them is safe).
        overext_forced_pullback = (sub_mode_resolved == "breakout" and overext is not None
                                   and overext["execution_flags"].get("force_pullback") is True)
        if overext_forced_pullback:
            sub_mode_resolved = "pullback"
        # §4.3 warning → raise the RR gate (+WARNING_RR_BONUS, stricter only): another warning execution lever,
        # independent of the pullback downgrade (entry mode) and the §8 size reduction (4d-ii-c).
        overext_raise_rr = (overext is not None and overext["execution_flags"].get("raise_rr_gate") is True)
        price = support_atr_engine(row.get("price_input"), regime, sub_mode_resolved, raise_rr_gate=overext_raise_rr)
        holding_action_context = None

    # §8.1 forward known-date events (sizing/risk/display only — never selection, never a hard veto).
    fe = row.get("forward_event")
    if fe is None:
        forward = None
    elif isinstance(fe, dict):
        forward = forward_event_effect(fe.get("event_type"), fe.get("days_to_event"), fe.get("window_days"))
        # A non-neutral calendar effect is only allowed to reach formal output with its own source reference.
        # The pure event classifier owns direction/window; this stage merely preserves the source-bound producer
        # input for the second-cut result-effects reducer to validate against the canonical decision date.
        if forward["in_window"]:
            forward = {**forward, "evidence_ref": fe.get("evidence_ref")}
    else:
        raise WeekendAnalysisError(f"forward_event 须为 dict 或缺省: {fe!r}")

    # §8.1 event_sensitive_type data gap — only meaningful when the row declares itself event-sensitive;
    # a missing has_event_data is treated as absent (fail-closed, 缺数据≠安全).
    est = row.get("event_sensitive_type")
    event_gap = event_data_gap_status(est, row.get("has_event_data", False)) if est is not None else None

    # §4.2 score — only for rows carrying score blocks (candidates); an unknown profile fails closed. A scored
    # candidate MUST carry the closed-world §4.2 risk_downgrade input (the typed engine output), whose points are
    # SUBTRACTED in core_score (R-USSHORT-BATCH4-RISK-DOWNGRADE-WIRING-GAP) — the designed soft penalty was
    # previously omitted from the weekend recommendation path. Missing / malformed risk input fails CLOSED (缺数据
    # ≠安全, §3.3); a genuinely clean stock carries an explicit zero-points input, not an omission.
    sb = row.get("score_blocks")
    if sb is None:
        score, risk_dg = None, None
    else:
        profile = row.get("scoring_profile", PRIMARY_PROFILE)
        try:
            risk_dg = validate_risk_downgrade_input(row.get("risk_downgrade"))
        except ValueError as e:
            raise WeekendAnalysisError(f"{ticker}: {e}")
        try:
            score = core_score(
                sb,
                profile,
                risk_downgrade_points=risk_dg["points"],
                strip_theme_score=(overext is not None and overext["strips_theme_score"] is True),
            )
        except KeyError:
            raise WeekendAnalysisError(f"score_blocks 的 scoring_profile 非法（fail-closed）: {profile!r}")

    # §4.0/§4.5 canonical selection identity: the orchestrator carries the Top15 selection record
    # (selection_rank / selection_bucket / selection-time core+theme scores) onto each admitted row. It rides
    # through analysis into the machine record. When this row ALSO recomputed a §4.2 core_score, the selection-
    # time and the analysis-time core_score MUST agree (one core_score per run) — a divergence is a seam bug and
    # fails CLOSED (R-USSHORT-BATCH4-SELECTION-TRACE-AND-RECALL-CLOSURE-GAP: no silent same-run score fork).
    sel_rec = row.get("selection_record")
    if sel_rec is not None:
        if not isinstance(sel_rec, dict):
            raise WeekendAnalysisError(f"selection_record 须为 dict 或缺省: {sel_rec!r}")
        if score is not None:
            sel_core = sel_rec.get("core_score")
            if (isinstance(sel_core, bool) or not isinstance(sel_core, (int, float))
                    or abs(score["core_score"] - sel_core) > 1e-6):
                raise WeekendAnalysisError(
                    f"{ticker}: 选择期 core_score {sel_rec.get('core_score')!r} != 分析期 §4.2 core_score "
                    f"{score['core_score']!r}（同一 run 须单源、不可分叉）")
    theme_context = row.get("theme_context")
    if theme_context is not None and not isinstance(theme_context, dict):
        raise WeekendAnalysisError("theme_context 须为 dict 或缺省")

    return {
        "ticker": ticker,
        "row_source": row.get("row_source"),
        "row_context": context,
        "veto": veto,
        "price": price,
        "sub_mode_resolved": sub_mode_resolved,
        "sub_mode_downgraded": sub_mode_downgraded,
        "overextension": overext,                       # §4.3 tier result (or None) — rides to the §11.3 overextension_state column (cut 2d)
        "overextension_forced_pullback": overext_forced_pullback,
        "forward_event": forward,
        "event_data_gap": event_gap,
        "score": score,
        "risk_downgrade": risk_dg,   # §4.2 typed penalty (points + components), None for an unscored holding
        "selection_record": sel_rec,
        "theme_context": dict(theme_context) if theme_context is not None else None,
        # Cut4 source-bound row facts are not re-derived here.  They carry the exact Batch5 coverage, catalyst
        # availability, and permitted price input onward to the final reducer/machine/report surfaces.
        **({
            "source_result_facts": row["source_result_facts"],
            "coverage_status": row["coverage_status"],
            "coverage_gap_tags": list(row["coverage_gap_tags"]),
            "data_quality_tags": list(row["data_quality_tags"]),
            "execution_constraints": list(row["execution_constraints"]),
        } if "source_result_facts" in row else {}),
        **({"holding_action_context": holding_action_context}
           if context == "holding" and "holding_action_context" in row else {}),
    }


def analyze_rows(rows, *, market_axis_regimes, prior_regime=None, prior_upgrade_count=0):
    """4d-ii-a analysis-evidence stage. Computes the §7 market risk regime ONCE, then gathers the
    per-row evidence (veto / price levels / forward-event effect / score) for every pre-assembled
    analysis row.

    rows = [{"ticker": str,                 # canonicalized here (one identity per stock, unique)
             "row_source": <frozen action_table row_source>,   # → candidate/holding context (§11.3/§5)
             "signals": <hard_veto signals dict> | None,        # §5 (fail-closed on a non-dict)
             "price_input": {"close": float, "bars" | "indicators": ...},   # §6 (degrade-to-observe)
             # candidate-only (ignored for holdings):
             "sub_mode": "pullback" | "breakout",               # absent → pullback; an invalid value fails closed
             "defensive_breakout_probe_allowed": bool,          # §8 防御 breakout exception; present → must be a real bool
             "score_blocks": {"momentum","theme","catalyst"},   # §4.2; absent → no score
             "scoring_profile": <PROFILE_NAMES>,                # default balanced; unknown → fail closed
             # optional (any row):
             "overextension": <classify_overextension result> | None,   # §4.3 injected from the scoring-stage
                                                                        #   producer map; warning→force pullback
             "forward_event": {"event_type","days_to_event","window_days"?},  # §8.1; absent → None
             "event_sensitive_type": str, "has_event_data": bool,             # §8.1 data gap
             "event_reference_price": float}, ...]              # holding event clear reference (§6.1)
    market_axis_regimes = {"vix","market_trend","breadth"} regime values (§7; a non-dict / missing axis
        degrades conservatively inside compute_market_risk_regime — never default aggressive).
    prior_regime / prior_upgrade_count = injected cross-run anti-chatter state (§7).

    Returns {"regime": <compute_market_risk_regime result>, "rows": [<per-row evidence>, ...]}.
    Raises WeekendAnalysisError on a malformed rows container / row / ticker / row_source / sub_mode /
    probe flag / profile / forward_event, or a post-canonical duplicate ticker (one analysis row per
    stock)."""
    if not isinstance(rows, list):
        raise WeekendAnalysisError("rows 须为 list")
    regime_result = compute_market_risk_regime(market_axis_regimes, prior_regime, prior_upgrade_count)
    regime = regime_result["market_risk_regime"]

    analyzed = []
    seen = set()
    for row in rows:
        ev = _analyze_one(row, regime)
        if ev["ticker"] in seen:
            raise WeekendAnalysisError(f"analysis rows 含规范化后重复 ticker（一股一行）: {ev['ticker']!r}")
        seen.add(ev["ticker"])
        analyzed.append(ev)
    return {"regime": regime_result, "rows": analyzed}
