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
      → m2 build_weekly_report (machine_record + lifecycle_result + report_context)
      → N write_run_private (decision_date, machine_record, weekly_report_md)

It WIRES only — every stage keeps its own consumer-validation / fail-closed contract (single source, not
re-implemented here). The orchestrator adds: (1) the §2.1 canonical decision_date threading — the resolver's
decision_date is the single anchor passed to K's as_of, L, and N (m2 / N then reconcile their injected
report_context price-clock / machine as_of against it, fail-closed cross-week); (2) §2.1 out-of-window NO-EMIT
— on the intraday dead zone run_selection returns no candidates and the orchestrator produces NO machine
record / report / private artifact; (3) the selection→analysis seam — the injected per_ticker_analysis map must
EXACTLY cover the canonical admitted ∪ holding identity UNION (admitted ∩ holdings is the legal holding_in_top15
overlap, deduped to one row; only a repeat WITHIN admitted or WITHIN holdings is malformed), and each row's
row_source must match where the selection placed the ticker — a missing / stale / non-canonical / wrong-identity /
mislabeled payload fails closed, never a silent default-clean row. All inputs are INJECTED via the closed-world
`pipeline_context` (batch4 offline fixture; batch5 fills it from the real provider behind the same seam).
Pure/offline beyond the N private writes; no provider/live/network/DataHub; no broker/auto-order; no A-share crossing.
"""
from __future__ import annotations

from engine.us_short_eligibility_gate import canonical_us_ticker
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
    "market_axis_regimes", "prior_regime", "prior_upgrade_count",   # 4d-ii-a regime
    "sizing_context", "basket_context", "cost_inputs", "available_cash",   # 4d-ii-c..i
    "report_context",                                  # m2
    "lifecycle_register_path", "lifecycle_readiness_out_path",   # L
    "runs_private_root", "weekly_private_root",        # N
})


class WeekendOrchestratorError(Exception):
    """The pipeline_context is malformed, or the selection→analysis seam does not reconcile (fail-closed)."""


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
    return [canon_map[ct] for ct in union_order]


def run_weekend_pipeline(now_et, sessions, pipeline_context):
    """4d-ii-o end-to-end weekend pipeline. Resolves the canonical decision_date, runs selection + the full
    4d-ii decision chain + machine-record assembly + lifecycle eval + weekly-report render + private write,
    threading the one decision_date throughout.

    now_et / sessions = the §2.1 resolver inputs (ET wall clock + the static NYSE sessions).
    pipeline_context = the closed-world injected run context (see _PIPELINE_CONTEXT_KEYS).

    Returns, on the intraday dead zone, {"out_of_window": True, "emitted": False, "decision_date": None,
    "run_date", "selection"} (NO machine record / report / private artifact produced). Otherwise
    {"out_of_window": False, "emitted": True, "decision_date", "run_date", "selection", "machine_record",
    "lifecycle_result", "report_data", "written"}. Raises WeekendOrchestratorError on a malformed
    pipeline_context / selection→analysis seam; each wired stage raises its own typed error on its contract."""
    if not (isinstance(pipeline_context, dict) and set(pipeline_context) == _PIPELINE_CONTEXT_KEYS):
        raise WeekendOrchestratorError(
            "pipeline_context 顶层键须恰为 %s（closed-world）: %s"
            % (sorted(_PIPELINE_CONTEXT_KEYS), sorted(pipeline_context) if isinstance(pipeline_context, dict) else pipeline_context))
    pc = pipeline_context

    selection = run_selection(now_et, sessions, pc["data_context"], eligibility_governance=pc["eligibility_governance"])
    if selection["out_of_window"]:
        # §2.1 intraday dead zone: NO-EMIT — do not run the downstream chain, produce no machine record /
        # report / private artifact (a run that cannot have a canonical decision_date emits nothing).
        return {"out_of_window": True, "emitted": False, "decision_date": None,
                "run_date": selection["run_date"], "selection": selection}
    decision_date = selection["decision_date"]   # §2.1 the ONE canonical anchor threaded below

    rows = _build_analysis_rows(selection, pc["per_ticker_analysis"])
    analysis = analyze_rows(rows, market_axis_regimes=pc["market_axis_regimes"],
                            prior_regime=pc["prior_regime"], prior_upgrade_count=pc["prior_upgrade_count"])
    decided = decide_actions(analysis)
    sized = size_rows(decided, sizing_context=pc["sizing_context"])
    basket = resolve_build_capacity(sized, basket_context=pc["basket_context"])
    cost_floored = apply_probe_cost_floor(basket, cost_inputs=pc["cost_inputs"])
    cash = apply_cash_allocation(cost_floored, available_cash=pc["available_cash"])
    ranked = apply_action_rank(cash)

    machine_record = assemble_machine_record(ranked, as_of=decision_date)        # decision_date → K as_of
    lifecycle_result = run_lifecycle_eval_stage(                                  # §13: L BEFORE the m2 render
        decision_date=decision_date, register_path=pc["lifecycle_register_path"],
        readiness_out_path=pc["lifecycle_readiness_out_path"])
    report = build_weekly_report(machine_record, lifecycle_result, report_context=pc["report_context"])
    written = write_run_private(                                                  # decision_date → N (idempotent)
        decision_date=decision_date, machine_record=machine_record, weekly_report_md=report["weekly_report_md"],
        runs_private_root=pc["runs_private_root"], weekly_private_root=pc["weekly_private_root"])

    return {"out_of_window": False, "emitted": True, "decision_date": decision_date,
            "run_date": selection["run_date"], "selection": selection, "machine_record": machine_record,
            "lifecycle_result": lifecycle_result, "report_data": report["report_data"], "written": written}
