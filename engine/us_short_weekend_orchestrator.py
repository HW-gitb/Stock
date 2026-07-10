# -*- coding: utf-8 -*-
"""US-short weekend-pipeline end-to-end orchestrator — batch4 slice 4d-ii-o (周末 pipeline 工程闭环).

Design authority: docs/us_short_system_design.md §2 / §2.1 (canonical decision_date / out-of-window no-emit /
幂等) / §11 / §13 (lifecycle eval 先于 render) / §18.0 / §18.2 batch4 slice 4d (编排器).

The capstone. It CHAINS the batch3/batch4 stages into one offline weekend run, threading the ONE canonical
decision_date through every stage and persisting the official private artifacts:

    resolve_canonical_asof (in 4d-i run_selection) → [intraday dead zone → OUT-OF-WINDOW NO-EMIT, §2.1]
      → 4d-i selection (universe → Pass1 → Pass2; holdings forced in)
      → build the 4d-ii-a analysis rows for the selection-determined tickers (admitted candidates + holdings)
      → 4d-ii-a analyze → b decide → c size → e/f/g build-gate → h cost-floor → i cash → j action_rank
      → K assemble_machine_record (as_of = decision_date)
      → L run_lifecycle_eval_stage (decision_date)            # §13: BEFORE the m2 render
      → m2 build_weekly_report (machine_record + lifecycle_result + report_context + resolver run_context)
      → N write_run_private (decision_date, machine_record, weekly_report_md)

It WIRES only — every stage keeps its own consumer-validation / fail-closed contract (single source, not
re-implemented here). The orchestrator adds: (1) the §2.1 canonical decision_date threading — the resolver's
decision_date is the single anchor passed to K's as_of, L, and N (m2 / N then reconcile their injected
report_context price-clock / resolver price_basis_date / run_date / machine as_of against it, fail-closed
cross-week or stale/future-clock); (2) §2.1 out-of-window NO-EMIT — on the intraday dead zone run_selection
returns no candidates and the orchestrator produces NO machine
record / report / private artifact; (3) the selection→analysis seam — the injected per_ticker_analysis map must
EXACTLY cover the canonical admitted ∪ holding identity UNION (admitted ∩ holdings is the legal holding_in_top15
overlap, deduped to one row; only a repeat WITHIN admitted or WITHIN holdings is malformed), and each row's
row_source must match where the selection placed the ticker — a missing / stale / non-canonical / wrong-identity /
mislabeled payload fails closed, never a silent default-clean row; and (4) the §2.1 PIT provenance reconcile —
every CONSUMED input family's as_of / observed_at / price-basis / session / adjustment is reconciled against the
one canonical clock BEFORE analysis (future / stale / cross-run / mixed-session / mixed-adjustment → fail-closed),
so data tagged for another run cannot launder into the official chain behind a plausible decision_date banner.
All inputs are INJECTED via the closed-world
`pipeline_context` (batch4 offline fixture; batch5 fills it from the real provider behind the same seam).
Pure/offline beyond the N private writes; no provider/live/network/DataHub; no broker/auto-order; no A-share crossing.
"""
from __future__ import annotations

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_market_calendar import sessions_for_window, validate_market_calendar
from engine.us_short_provider_health import classify_provider_health
from engine.us_short_run_origin import is_capstone_research_live_capability, run_origin_for_mode
from engine.us_short_run_provenance import reconcile_run_provenance
from engine.us_short_weekend_action_rank import apply_action_rank
from engine.us_short_weekend_analysis import analyze_rows
from engine.us_short_weekend_basket import resolve_build_capacity
from engine.us_short_weekend_cash import apply_cash_allocation
from engine.us_short_weekend_cost_floor import apply_probe_cost_floor
from engine.us_short_weekend_decision import decide_actions
from engine.us_short_weekend_lifecycle_stage import run_lifecycle_eval_stage
from engine.us_short_weekend_machine_record import assemble_machine_record
from engine.us_short_weekend_pipeline import run_selection
from engine.us_short_weekend_private_write import write_run_private
from engine.us_short_weekend_report import build_weekly_report
from engine.us_short_weekend_sizing import size_rows

# the closed-world injected context for one weekend run (batch4 offline fixture; batch5 fills from provider).
_PIPELINE_CONTEXT_KEYS = frozenset({
    "data_context", "eligibility_governance",          # 4d-i selection
    "per_ticker_analysis",                             # selection→4d-ii-a seam (per admitted candidate + holding)
    "run_provenance",                                  # §2.1 PIT 来源对账（消费输入族 as_of/observed_at/price-basis/session/adjustment）
    "provider_health", "calendar",                     # §3.7 跑前健康门 + §2.1/§3.5 live 须 authoritative 日历 artifact
    "market_axis_regimes", "prior_regime", "prior_upgrade_count",   # 4d-ii-a regime
    "sizing_context", "basket_context", "cost_inputs", "available_cash",   # 4d-ii-c..i
    "report_context",                                  # m2
    "lifecycle_register_path", "lifecycle_readiness_out_path",   # L
    "runs_private_root", "weekly_private_root",        # N
})

# §2.1/§3.5: a live/forward run must run off an AUTHORITATIVE-cross-checked calendar (the official NYSE cross-check
# is batch5 / SR-PROVIDER-001). batch4 cannot trust an OFFLINE-injected calendar's self-reported status, so live
# mode is gated entirely here; offline_test runs on the injected fixture sessions (deterministic, calendar-bound).
RUN_MODES = frozenset({"offline_test", "research_live", "live"})


class WeekendOrchestratorError(Exception):
    """The pipeline_context is malformed, or the selection→analysis seam does not reconcile (fail-closed)."""


def _assert_calendar(calendar, run_mode):
    """(1c) Validate the injected calendar ARTIFACT + gate live mode. batch4 GATES `live`/forward mode entirely:
    the authoritative cross-checked NYSE calendar is a batch5 deliverable (SR-PROVIDER-001), and an OFFLINE-injected
    calendar's SELF-REPORTED `verification_status` cannot be trusted to authorize live — a `live` run fails closed
    REGARDLESS of the injected calendar (a forged `authoritative_verified` does not enable live; that anchor comes
    from batch5, not the caller). `offline_test` derives the sessions from the validated calendar via
    `build_sessions` (NOT a caller-supplied list), so missing / extra / duplicate / wrong-open-close / wrong-day
    sessions are impossible by construction (Codex re-review 4: omitted-close & omitted-middle-session). Returns the
    validated calendar dict."""
    if run_mode == "live":
        raise WeekendOrchestratorError(
            "live/forward mode 须 batch5 权威核对的日历 artifact（SR-PROVIDER-001）；offline 注入日历的自报 "
            "verification_status 不可信、不足以授权 live → gated（live 留批5、不由调用方自报启用）")
    return validate_market_calendar(calendar)   # raises MarketCalendarError on a malformed / non-artifact calendar


# the frozen action_table row_source (§11.3/§11.5) a row may carry, BY the ticker's selection membership.
# admitted ∩ holdings is the LEGAL holding_in_top15 overlap (a current holding that also ranks into this week's
# Top15), NOT a duplicate error; the §11.2 report / §11.3 machine record split holdings vs candidates by
# row_source, so the seam must reconcile each row's source against where the selection placed the ticker.
def _expected_row_sources(in_admitted, in_holdings):
    if in_admitted and in_holdings:
        return {"holding_in_top15"}
    if in_admitted:
        return {"top15_candidate"}
    return {"holding_pass2_only", "holding_account_only"}   # holding that did not rank into Top15


def _canon_unique(tickers, what):
    """Canonicalize ONE identity space (admitted, or holdings) and reject a non-canonical or a repeat ticker
    WITHIN it. A ticker may still appear across BOTH spaces — that is the legal holding_in_top15 overlap."""
    canon, seen = [], set()
    for t in tickers:
        ct = canonical_us_ticker(t)
        if ct is None:
            raise WeekendOrchestratorError(f"{what} ticker 非规范 US ticker: {t!r}")
        if ct in seen:
            raise WeekendOrchestratorError(f"{what} 含规范化后重复 ticker: {ct!r}")
        seen.add(ct)
        canon.append(ct)
    return canon, seen


def _build_analysis_rows(selection, per_ticker_analysis):
    """Collect the 4d-ii-a analysis rows for the selection-determined tickers (admitted candidates + holdings)
    from the injected per_ticker_analysis map. The map must EXACTLY cover the canonical identity UNION admitted ∪
    holdings, where admitted ∩ holdings is a LEGAL holding_in_top15 overlap (deduped to ONE row) and only a repeat
    WITHIN admitted or WITHIN holdings is malformed; and each row's row_source must match where the selection
    placed the ticker. A missing / stale / non-canonical / wrong-identity / row_source-mismatched payload fails
    closed (never a silent default-clean or mislabeled row)."""
    if not isinstance(per_ticker_analysis, dict):
        raise WeekendOrchestratorError("per_ticker_analysis 须为 dict")
    admitted_canon, admitted_set = _canon_unique(selection["admitted"], "admitted")
    holdings_canon, holdings_set = _canon_unique([h["ticker"] for h in selection["holdings"]], "holdings")
    # canonical identity union; a holding that also ranks into Top15 appears once, in its admitted position.
    union_order = admitted_canon + [ct for ct in holdings_canon if ct not in admitted_set]
    union_set = admitted_set | holdings_set

    canon_map = {}
    for k, v in per_ticker_analysis.items():
        ck = canonical_us_ticker(k)
        if ck is None:
            raise WeekendOrchestratorError(f"per_ticker_analysis 键非规范 US ticker: {k!r}")
        if ck in canon_map:
            raise WeekendOrchestratorError(f"per_ticker_analysis 规范化后重复键: {ck!r}")
        # the payload row's OWN canonical ticker MUST equal its key — key-only coverage does not prove identity;
        # a stale / swapped row hidden behind a valid selected key must fail closed (else the official chain
        # would proceed on the wrong symbol after analyze_rows canonicalizes the payload's ticker).
        pt = v.get("ticker") if isinstance(v, dict) else v
        if not (isinstance(v, dict) and canonical_us_ticker(pt) == ck):
            raise WeekendOrchestratorError(
                f"per_ticker_analysis[{k!r}] 的 payload ticker {pt!r} 与键 {ck!r} 身份不匹配（key-only 覆盖不证明 payload 身份）")
        canon_map[ck] = v
    if set(canon_map) != union_set:
        raise WeekendOrchestratorError(
            "per_ticker_analysis 须恰覆盖 admitted∪holdings（缺 %s / 多 %s）"
            % (sorted(union_set - set(canon_map)), sorted(set(canon_map) - union_set)))
    # each row's row_source must match where the selection placed the ticker (overlap → holding_in_top15,
    # admitted-only → top15_candidate, holding-only → a holding source); a mislabel would corrupt the
    # holdings-vs-candidates split in the official report / machine record.
    for ct in union_order:
        expected = _expected_row_sources(ct in admitted_set, ct in holdings_set)
        rs = canon_map[ct].get("row_source")
        if rs not in expected:
            raise WeekendOrchestratorError(
                f"per_ticker_analysis[{ct!r}] row_source {rs!r} 与选择身份不符"
                f"（admitted={ct in admitted_set} holding={ct in holdings_set}，须 ∈ {sorted(expected)}）")
    # carry the canonical Top15 selection identity (selection_rank / selection_bucket / selection-time core+theme
    # scores) onto each admitted row so analysis → machine record → report can RECONCILE + display it
    # (R-USSHORT-BATCH4-SELECTION-TRACE-AND-RECALL-CLOSURE-GAP); a holding-only row (not in Top15) carries None.
    sel_records = {}
    for d in selection.get("selection_details") or []:
        sel_records[canonical_us_ticker(d.get("ticker"))] = {
            "selection_rank": d["selection_rank"], "selection_bucket": d["selection_bucket"],
            "core_score": d["core_score"], "theme_momentum_score": d["theme_momentum_score"]}
    return [{**canon_map[ct], "selection_record": sel_records.get(ct)} for ct in union_order]


def run_weekend_pipeline(now_et, pipeline_context, *, run_mode="offline_test", research_live_capability=None):
    """4d-ii-o end-to-end weekend pipeline. Resolves the canonical decision_date, runs selection + the full
    4d-ii decision chain + machine-record assembly + lifecycle eval + weekly-report render + private write,
    threading the one decision_date throughout. Three run gates precede analysis (closes
    R-USSHORT-BATCH4-PIPELINE-PIT-HEALTH-CALENDAR-GATE-GAP): (1c) the run-mode / calendar-authority gate — a
    `live` run is GATED in batch4 (the authoritative cross-checked calendar is batch5 / SR-PROVIDER-001); the
    sessions are DERIVED from the validated injected calendar via `build_sessions`, so a missing / extra / wrong-
    open-close session is impossible by construction; (1b) the §3.7 provider-health gate — non-clean CRITICAL
    source health (degraded/down/missing FMP or SEC) NO-EMITs (a clean official build can never ride unhealthy
    critical sources, §3.2); (1a) the §2.1 PIT provenance reconcile.

    now_et = the §2.1 resolver ET wall clock; the NYSE sessions are derived from `pipeline_context["calendar"]`.
    pipeline_context = the closed-world injected run context (see _PIPELINE_CONTEXT_KEYS).
    run_mode = 'offline_test' (default) | 'research_live' (real provider data; CAPSTONE-INTERNAL — a research_live run
    requires the process-internal capstone capability, R-USSHORT-REVIEWQ-CAT1 A) | 'live' (gated in batch4 → batch5).

    Returns a NO-EMIT result {"out_of_window"/"emitted", "no_emit_reason", "decision_date", "run_date",
    "selection", ["provider_health"]} on the intraday dead zone OR non-clean provider health (NO machine record /
    report / private artifact produced). On a clean in-window run {"out_of_window": False, "emitted": True,
    "decision_date", "run_date", "selection", "machine_record", "lifecycle_result", "report_data", "written",
    "run_provenance", "provider_health"}. Raises WeekendOrchestratorError on a malformed pipeline_context /
    run_mode / non-authoritative live calendar / selection→analysis seam; each wired stage raises its own typed
    error on its contract."""
    if run_mode not in RUN_MODES:
        raise WeekendOrchestratorError(f"run_mode 须 ∈ {sorted(RUN_MODES)}: {run_mode!r}")
    # R-USSHORT-REVIEWQ-CAT1 Required A — research_live is CAPSTONE-INTERNAL at EVERY layer, including this PUBLISHED
    # orchestrator entry (docs/README + CURRENT publish this signature). The research_live run_origin is minted below
    # via run_origin_for_mode, so a DIRECT run_weekend_pipeline caller must ALSO hold the process-internal capstone
    # capability (the batch4/e2e wrappers thread it down here). A generic caller passing run_mode="research_live"
    # without it fails closed — no false "真实 provider 数据" banner from the deepest public surface.
    if run_mode == "research_live" and not is_capstone_research_live_capability(research_live_capability):
        raise WeekendOrchestratorError(
            "research_live 为 capstone 内部 run_origin（须持 capstone 进程内能力对象，由 batch4/e2e 网关下传）；"
            "run_weekend_pipeline 通用调用方不可直接选择")
    if not (isinstance(pipeline_context, dict) and set(pipeline_context) == _PIPELINE_CONTEXT_KEYS):
        raise WeekendOrchestratorError(
            "pipeline_context 顶层键须恰为 %s（closed-world）: %s"
            % (sorted(_PIPELINE_CONTEXT_KEYS), sorted(pipeline_context) if isinstance(pipeline_context, dict) else pipeline_context))
    pc = pipeline_context

    # (1c) §2.1/§3.5 run-mode / calendar gate + session DERIVATION: validate the calendar artifact, hard-gate live
    # mode (batch5), and DERIVE the §2.1 sessions from the calendar via build_sessions (normalize, not a caller
    # list) so missing / extra / duplicate / wrong-open-close / wrong-day sessions are impossible by construction.
    cal = _assert_calendar(pc["calendar"], run_mode)
    sessions = sessions_for_window(now_et.strftime("%Y%m%d"), calendar=cal)

    selection = run_selection(now_et, sessions, pc["data_context"], eligibility_governance=pc["eligibility_governance"])
    if selection["out_of_window"]:
        # §2.1 intraday dead zone: NO-EMIT — do not run the downstream chain, produce no machine record /
        # report / private artifact (a run that cannot have a canonical decision_date emits nothing).
        return {"out_of_window": True, "emitted": False, "no_emit_reason": "out_of_window",
                "decision_date": None, "run_date": selection["run_date"], "selection": selection}
    decision_date = selection["decision_date"]   # §2.1 the ONE canonical anchor threaded below

    # (1b) §3.7 provider-health gate: classify the INJECTED authorized-source health; non-clean CRITICAL health
    # (degraded/down/missing FMP or SEC EDGAR) NO-EMITs — an official build can never ride unhealthy critical
    # sources (§3.2 不健康→restricted/blocked). The single-source classifier structurally refuses unauthorized
    # sources. (Graduated restricted-mode reporting is the report-binding slice; here non-clean fails closed.)
    provider_health = classify_provider_health(pc["provider_health"])
    if provider_health["overall_run_state"] != "clean":
        return {"out_of_window": False, "emitted": False,
                "no_emit_reason": "provider_health_" + provider_health["overall_run_state"],
                "decision_date": decision_date, "run_date": selection["run_date"],
                "selection": selection, "provider_health": provider_health}

    # §2.1 PIT 来源对账 (R-USSHORT-BATCH4-PIPELINE-PIT-HEALTH-CALENDAR-GATE-GAP, provenance half): reconcile every
    # CONSUMED input family's as_of / observed_at / price-basis / session / adjustment against the ONE canonical
    # clock BEFORE analysis — a future / stale / cross-run / mixed input fails closed here, so data tagged for
    # another run (e.g. as_of=20990101) can never reach the official chain behind a plausible decision_date banner.
    run_provenance = reconcile_run_provenance(
        pc["run_provenance"], now_et=now_et, decision_date=decision_date,
        price_basis_date=selection["price_basis_date"], run_date=selection["run_date"],
        # ①a bind the manifest to the ACTUAL consumed payload (row_count + per-row as_of/observed_at) so a clean
        # manifest can't ride alongside a dirty (as_of=2099) payload row.
        payloads={"universe": pc["data_context"]["universe"],
                  "candidate_pass2_signals": pc["data_context"]["candidate_pass2_signals"],
                  "selection_inputs": pc["data_context"]["selection_inputs"],
                  "per_ticker_analysis": pc["per_ticker_analysis"]})

    rows = _build_analysis_rows(selection, pc["per_ticker_analysis"])
    analysis = analyze_rows(rows, market_axis_regimes=pc["market_axis_regimes"],
                            prior_regime=pc["prior_regime"], prior_upgrade_count=pc["prior_upgrade_count"])
    decided = decide_actions(analysis)
    sized = size_rows(decided, sizing_context=pc["sizing_context"])
    basket = resolve_build_capacity(sized, basket_context=pc["basket_context"])
    cost_floored = apply_probe_cost_floor(basket, cost_inputs=pc["cost_inputs"])
    cash = apply_cash_allocation(cost_floored, available_cash=pc["available_cash"])
    ranked = apply_action_rank(cash)

    # batch4 honesty provenance: the immutable run-origin fact (offline_test fixture OR research_live real-data; BOTH
    # operational_use=not_authorized), threaded through K (machine record) + m2 (report) + N (private write) so neither
    # a synthetic fixture nor a pre-authoritative research run can be mistaken for operational weekly advice
    # (R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP). live (operationally authoritative) stays hard-gated above
    # (→ batch5), so run_origin_for_mode only ever returns the offline_test or research_live fact here.
    run_origin = run_origin_for_mode(run_mode)
    machine_record = assemble_machine_record(ranked, as_of=decision_date, run_origin=run_origin,   # decision_date → K as_of
                                             research_live_capability=research_live_capability)
    lifecycle_result = run_lifecycle_eval_stage(                                  # §13: L BEFORE the m2 render
        decision_date=decision_date, register_path=pc["lifecycle_register_path"],
        readiness_out_path=pc["lifecycle_readiness_out_path"])
    report = build_weekly_report(
        machine_record, lifecycle_result, report_context=pc["report_context"], run_origin=run_origin,
        research_live_capability=research_live_capability,
        run_context={"decision_date": decision_date, "price_basis_date": selection["price_basis_date"],
                     "run_date": selection["run_date"]},
        # §11.2 BINDS its boundary facts to the structured stage outputs (R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-
        # BINDING-GAP): provider health = the slice-1b classification; portfolio_guard + theme = the EXACT
        # basket_context the decision used — so the report can never claim normal/clean/different-theme.
        stage_status={"provider_health": provider_health,
                      "portfolio_guard_status": pc["basket_context"]["portfolio_guard_status"],
                      "theme_opportunity_state": pc["basket_context"]["theme_opportunity_state"]},
        selection=selection)
    written = write_run_private(                                                  # decision_date → N (idempotent)
        decision_date=decision_date, machine_record=machine_record, weekly_report_md=report["weekly_report_md"],
        report_data=report["report_data"],
        # source-fact reconciliation (R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP): the persistence boundary
        # rebinds report_data.run_status / offline_honesty to the RUN-LEVEL provider-health + holding coverage + the
        # independent lifecycle stage result the run actually used, so a forged count/state (incl. a coordinated
        # all-copies lifecycle forge) cannot ride byte-equality.
        provider_health=provider_health, coverage_inputs=pc["report_context"]["coverage_inputs"],
        lifecycle_result=lifecycle_result,
        runs_private_root=pc["runs_private_root"],
        weekly_private_root=pc["weekly_private_root"], run_origin=run_origin,
        research_live_capability=research_live_capability)

    return {"out_of_window": False, "emitted": True, "decision_date": decision_date,
            "run_date": selection["run_date"], "selection": selection, "machine_record": machine_record,
            "lifecycle_result": lifecycle_result, "report_data": report["report_data"], "written": written,
            "run_provenance": run_provenance, "provider_health": provider_health, "run_origin": run_origin}
