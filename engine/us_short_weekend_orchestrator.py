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

import math
from pathlib import Path

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_holding_action import (
    STATE_FILENAME,
    HoldingActionError,
    attach_holding_action_context,
    build_holding_action_context,
    build_next_holding_action_state,
    load_holding_action_state,
)
from engine.us_short_result_effects import (
    PORTFOLIO_GUARD_STATE_FILENAME,
    ResultEffectsError,
    apply_result_effects,
    build_next_portfolio_guard_state,
    extend_result_effects,
    build_portfolio_guard_result,
    load_portfolio_guard_state,
    unavailable_cooldown_records,
)
from engine.us_short_regime import (
    MARKET_REGIME_STATE_FILENAME,
    MarketRegimeStateError,
    load_market_regime_state,
    build_market_regime_state,
)
from engine.us_short_result_source_linkage import (  # Cut4 source facts → the existing Cut2 effect reducer
    ResultSourceLinkageError,
    bind_result_source_facts,
    source_coverage_effect_records,
)
from engine.us_short_execution_cost_prior import ExecutionCostPriorError, dollar_costs
from engine.us_short_macro_cluster import apply_macro_cluster_two_pass
from engine.us_short_theme_result_linkage import (
    ThemeResultLinkageError,
    apply_theme_lifecycle_effects,
    bind_theme_contexts,
)
from engine.us_short_symbol_cooldown_state import (
    STATE_FILENAME as SYMBOL_COOLDOWN_STATE_FILENAME,
    SymbolCooldownStateError,
    build_next_symbol_cooldown_state,
    empty_symbol_cooldown_state,
    load_symbol_cooldown_state,
    resolve_symbol_cooldowns,
)
from engine.us_short_market_calendar import sessions_for_window, validate_market_calendar
from engine.us_short_private_paths import PrivatePathError
from engine.us_short_provider_health import EMIT_ALLOWED_RUN_STATES, classify_provider_health
from engine.us_short_run_origin import (
    RunOriginError,
    is_capstone_research_live_capability,
    require_research_live_provider_health,
    run_origin_for_mode,
)
from engine.us_short_run_provenance import reconcile_run_provenance
from engine.us_short_weekend_action_rank import apply_action_rank
from engine.us_short_weekend_analysis import analyze_rows
from engine.us_short_weekend_basket import resolve_build_capacity
from engine.us_short_weekend_cash import apply_cash_allocation
from engine.us_short_weekend_cost_floor import apply_probe_cost_floor
from engine.us_short_decision_exposure import (
    build_decision_exposure_record, write_decision_exposure)
from engine.us_short_weekend_decision import decide_actions
from engine.us_short_weekend_lifecycle_stage import run_lifecycle_eval_stage
from engine.us_short_weekend_machine_record import assemble_machine_record
from engine.us_short_weekend_pipeline import run_selection
from engine.us_short_weekend_private_write import (
    validate_prior_run_dir,
    write_run_private,
)
from engine.us_short_weekend_report import build_weekly_report

# the closed-world injected context for one weekend run (batch4 offline fixture; batch5 fills from provider).
_PIPELINE_CONTEXT_KEYS = frozenset({
    "data_context", "eligibility_governance",          # 4d-i selection
    "per_ticker_analysis",                             # selection→4d-ii-a seam (per admitted candidate + holding)
    "run_provenance",                                  # §2.1 PIT 来源对账（消费输入族 as_of/observed_at/price-basis/session/adjustment）
    "provider_health", "calendar",                     # §3.7 跑前健康门 + §2.1/§3.5 live 须 authoritative 日历 artifact
    "market_axis_regimes", "prior_regime", "prior_upgrade_count", "prior_run_dir", "prior_runs_private_root",   # 4d-ii-a regime
    "sizing_context", "basket_context", "cost_inputs", "available_cash", "account_state", "paper_track",   # 4d-ii-c..i
    "report_context",                                  # m2
    "lifecycle_register_path", "lifecycle_readiness_out_path",   # L
    "runs_private_root", "weekly_private_root",        # N
})

# §2.1/§3.5: a live/forward run must run off an AUTHORITATIVE-cross-checked calendar (the official NYSE cross-check
# is batch5 / SR-PROVIDER-001). batch4 cannot trust an OFFLINE-injected calendar's self-reported status, so live
# mode is gated entirely here; offline_test runs on the injected fixture sessions (deterministic, calendar-bound).
RUN_MODES = frozenset({"offline_test", "research_live", "mixed_source", "live"})

# The only producer mapping for a new candidate's existing two price sub-modes.  The selection producer emits
# exactly these four bucket values; an out-of-table value must not silently become pullback.
_SELECTION_BUCKET_TO_SUB_MODE = {
    "theme_momentum": "breakout",
    "overlap": "breakout",
    "core_top": "pullback",
    "core_backfill": "pullback",
}


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
    selection_themes = {}
    for d in selection.get("selection_details") or []:
        ticker = canonical_us_ticker(d.get("ticker"))
        sel_records[ticker] = {
            "selection_rank": d["selection_rank"], "selection_bucket": d["selection_bucket"],
            "core_score": d["core_score"], "theme_momentum_score": d["theme_momentum_score"]}
        selection_themes[ticker] = dict(d["theme_selection"])
    rows = []
    for ct in union_order:
        row = dict(canon_map[ct])
        selection_record = sel_records.get(ct)
        # Only a new candidate gets the automatic mode.  Holding rows, including a legal admitted+holding
        # overlap, continue through the existing holding path and do not participate in build-mode production.
        if ct in admitted_set and ct not in holdings_set and "sub_mode" not in row:
            if not isinstance(selection_record, dict):
                raise WeekendOrchestratorError(
                    f"{ct}: 新候选缺 selection_record，无法按 selection_bucket 生产 sub_mode")
            bucket = selection_record.get("selection_bucket")
            try:
                row["sub_mode"] = _SELECTION_BUCKET_TO_SUB_MODE[bucket]
            except (KeyError, TypeError) as exc:
                raise WeekendOrchestratorError(
                    f"{ct}: selection_bucket {bucket!r} 无 sub_mode 映射（fail-closed）") from exc
        row["selection_record"] = selection_record
        row["selection_theme"] = selection_themes.get(ct)
        rows.append(row)
    return rows


def _portfolio_capacity_context(selection, analysis_rows, *, account_state, sizing_context, available_cash,
                                decision_date):
    """Bind §8 dollar-cap inputs to the same account, holding rows, prices, and themes this run consumes.

    Account identity/date/bucket/cash disagreements are structural errors. A holding with a missing current mark
    or theme is represented as unavailable and is handled by the cash stage as a conservative all-new-build
    deferral; it is never valued at average cost or silently assigned a fallback theme.
    """
    if not isinstance(account_state, dict) or not isinstance(account_state.get("positions"), list):
        raise WeekendOrchestratorError("account_state 须为含 positions(list) 的私密账户对象")
    if account_state.get("as_of") != decision_date:
        raise WeekendOrchestratorError("account_state.as_of 必须等于本次 decision_date（容量不得跨期复用）")
    bucket = account_state.get("us_short_bucket_capital")
    sizing_bucket = sizing_context.get("short_bucket_dollars") if isinstance(sizing_context, dict) else None
    cash = account_state.get("us_short_available_cash")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0.0
           for value in (bucket, sizing_bucket)):
        raise WeekendOrchestratorError("账户/定仓 short bucket 须为正有限数")
    if not isinstance(cash, (int, float)) or isinstance(cash, bool) or not math.isfinite(cash) or cash < 0.0:
        raise WeekendOrchestratorError("account_state.us_short_available_cash 须为非负有限数")
    if abs(float(bucket) - float(sizing_bucket)) > 1e-9 or available_cash != cash:
        raise WeekendOrchestratorError("账户 bucket/cash 与本次 sizing/cash 输入不一致（容量不得分叉）")
    account_positions, account_tickers = {}, set()
    for position in account_state["positions"]:
        ticker = canonical_us_ticker(position.get("ticker")) if isinstance(position, dict) else None
        shares = position.get("shares") if isinstance(position, dict) else None
        if ticker is None or ticker in account_tickers or not (isinstance(shares, int) and not isinstance(shares, bool) and shares >= 1):
            raise WeekendOrchestratorError("account_state.positions 含非法/重复 ticker 或 shares")
        account_tickers.add(ticker)
        account_positions[ticker] = position
    selection_holdings = {canonical_us_ticker(h.get("ticker")) for h in selection["holdings"] if isinstance(h, dict)}
    if None in selection_holdings or selection_holdings != account_tickers:
        raise WeekendOrchestratorError("selection holdings 与 account_state.positions 须一一对应（容量覆盖不得漏持仓）")

    rows_by_ticker = {row["ticker"]: row for row in analysis_rows}
    existing_positions = []
    for ticker in sorted(account_tickers):
        row = rows_by_ticker.get(ticker)
        price_input = row.get("price_input") if isinstance(row, dict) else None
        close = price_input.get("close") if isinstance(price_input, dict) else None
        mark = float(close) if isinstance(close, (int, float)) and not isinstance(close, bool) and math.isfinite(close) and close > 0.0 else None
        theme = row.get("theme_context") if isinstance(row, dict) else None
        theme_id = theme.get("theme_id") if isinstance(theme, dict) else None
        existing_positions.append({"ticker": ticker, "shares": account_positions[ticker]["shares"],
                                   "mark_price": mark, "theme": theme_id})
    return {"short_bucket_dollars": float(bucket), "existing_positions": existing_positions}


def _macro_existing_positions(account_state, analysis_rows):
    """Private in-memory current-holding exposure for the Cut3 provisional macro pass."""
    rows = {row["ticker"]: row for row in analysis_rows}
    out = []
    for position in account_state.get("positions", []):
        ticker = canonical_us_ticker(position.get("ticker")) if isinstance(position, dict) else None
        row = rows.get(ticker)
        price_input = row.get("price_input") if isinstance(row, dict) else None
        mark = price_input.get("close") if isinstance(price_input, dict) else None
        theme = row.get("theme_context") if isinstance(row, dict) else None
        cluster = theme.get("macro_cluster") if isinstance(theme, dict) else None
        out.append({"ticker": ticker, "shares": position.get("shares"), "mark_price": mark,
                    "macro_cluster": cluster})
    return out


def _runtime_basket_context(rows, supplied):
    """Join source-bound theme facts to the non-theme probe inputs; callers cannot inject theme defaults."""
    if not (isinstance(supplied, dict)
            and set(supplied) == {"per_ticker", "theme_opportunity_state"}
            and isinstance(supplied["per_ticker"], dict)):
        raise WeekendOrchestratorError(
            "basket_context 须为 {'per_ticker','theme_opportunity_state'}；theme/lifecycle 由正式行生成")
    expected_source, by_ticker = set(), {}
    for row in rows:
        ticker = row["ticker"]
        override = ((row.get("result_effects") or {}).get("action_override")
                    if isinstance(row.get("result_effects"), dict) else None)
        consumes_probe = row.get("final_action") == "建仓" or (
            row.get("final_action") == "观察" and isinstance(override, dict)
            and override.get("final_action") == "观察"
        )
        # A second-pass macro discount may turn a provisionally sized build into below-minimum observe.  The
        # bridge legitimately supplied that build's probe before the internal second pass, so validate and
        # consume the source identity without feeding an inapplicable row into the basket resolver.
        source_supplied = consumes_probe or isinstance(row.get("sizing"), dict)
        if source_supplied:
            expected_source.add(ticker)
            theme = row.get("theme_context")
            if not isinstance(theme, dict):
                raise WeekendOrchestratorError(f"{ticker}: build/effect-observe 缺 theme_context")
            raw = supplied["per_ticker"].get(ticker)
            probe = raw.get("theme_probe") if isinstance(raw, dict) else None
            if not (isinstance(raw, dict) and set(raw) == {"theme_probe"}
                    and isinstance(probe, dict)
                    and set(probe) == {"high_confidence", "coverage_status", "no_gap_week", "entry_in_band"}):
                raise WeekendOrchestratorError(f"{ticker}: basket probe source fields 非法")
            if consumes_probe:
                by_ticker[ticker] = {
                    "theme": theme["theme_id"],
                    "theme_probe": {"theme_lifecycle_state": theme["theme_lifecycle_state"], **probe},
                }
    if set(supplied["per_ticker"]) != expected_source:
        raise WeekendOrchestratorError(
            "basket_context.per_ticker 须恰覆盖 provisional build/effect-observe source rows")
    return {"per_ticker": by_ticker, "holding_themes": {},
            "theme_opportunity_state": supplied["theme_opportunity_state"]}


def _probe_cost_inputs(basket_result):
    costs = {}
    for row in basket_result["rows"]:
        if row.get("final_action") != "建仓" or "theme_probe" not in row:
            continue
        sizing = row.get("sizing") if isinstance(row.get("sizing"), dict) else {}
        fields = row.get("price", {}).get("action_fields", {}) if isinstance(row.get("price"), dict) else {}
        try:
            costs[row["ticker"]] = dollar_costs(
                row.get("execution_cost_prior"),
                shares=sizing.get("desired_model_shares"),
                reference_price=fields.get("valid_entry_high"),
            )
        except (ExecutionCostPriorError, KeyError) as exc:
            raise WeekendOrchestratorError(
                f"{row.get('ticker')}: promoted probe lacks a usable execution-cost prior"
            ) from exc
    return costs


def run_weekend_pipeline(now_et, pipeline_context, *, run_mode="offline_test", research_live_capability=None):
    """4d-ii-o end-to-end weekend pipeline. Resolves the canonical decision_date, runs selection + the full
    4d-ii decision chain + machine-record assembly + lifecycle eval + weekly-report render + private write,
    threading the one decision_date throughout. Three run gates precede analysis (closes
    R-USSHORT-BATCH4-PIPELINE-PIT-HEALTH-CALENDAR-GATE-GAP): (1c) the run-mode / calendar-authority gate — a
    `live` run is GATED in batch4 (the authoritative cross-checked calendar is batch5 / SR-PROVIDER-001); the
    sessions are DERIVED from the validated injected calendar via `build_sessions`, so a missing / extra / wrong-
    open-close session is impossible by construction; (1b) the §3.7 provider-health gate — degraded/down/missing
    critical SEC health NO-EMITs, while advisory FMP-grades may continue as `usable_with_fallback` (§3.2);
    (1a) the §2.1 PIT provenance reconcile.

    now_et = the §2.1 resolver ET wall clock; the NYSE sessions are derived from `pipeline_context["calendar"]`.
    pipeline_context = the closed-world injected run context (see _PIPELINE_CONTEXT_KEYS).
    run_mode = 'offline_test' (default) | provider-backed 'research_live'/'mixed_source' (CAPSTONE-INTERNAL and receipt-
    gated) | 'live' (gated in batch4 → batch5).

    Returns a NO-EMIT result {"out_of_window"/"emitted", "no_emit_reason", "decision_date", "run_date",
    "selection", ["provider_health"]} on the intraday dead zone OR restricted/blocked provider health (NO machine
    record / report / private artifact produced). On an emit-allowed in-window run {"out_of_window": False, "emitted": True,
    "decision_date", "run_date", "selection", "machine_record", "lifecycle_result", "report_data", "written",
    "run_provenance", "provider_health"}. Raises WeekendOrchestratorError on a malformed pipeline_context /
    run_mode / non-authoritative live calendar / selection→analysis seam; each wired stage raises its own typed
    error on its contract."""
    if run_mode not in RUN_MODES:
        raise WeekendOrchestratorError(f"run_mode 须 ∈ {sorted(RUN_MODES)}: {run_mode!r}")
    # R-USSHORT-REVIEWQ-CAT1 Required A — provider-backed modes are CAPSTONE-INTERNAL at EVERY layer, including this
    # PUBLISHED orchestrator entry. Their run_origins are minted below
    # via run_origin_for_mode, so a DIRECT run_weekend_pipeline caller must ALSO hold the process-internal capstone
    # capability (the batch4/e2e wrappers thread it down here). A generic caller passing either provider-backed mode
    # without it fails closed — no false source banner from the deepest public surface.
    if run_mode in ("research_live", "mixed_source") and not is_capstone_research_live_capability(research_live_capability):
        raise WeekendOrchestratorError(
            "provider-backed run_mode 为 capstone 内部 run_origin（须持 source-bound capstone execution receipt，由 batch4/e2e 网关下传）；"
            "run_weekend_pipeline 通用调用方不可直接选择")
    if not (isinstance(pipeline_context, dict) and set(pipeline_context) == _PIPELINE_CONTEXT_KEYS):
        raise WeekendOrchestratorError(
            "pipeline_context 顶层键须恰为 %s（closed-world）: %s"
            % (sorted(_PIPELINE_CONTEXT_KEYS), sorted(pipeline_context) if isinstance(pipeline_context, dict) else pipeline_context))
    pc = pipeline_context
    if run_mode in ("research_live", "mixed_source"):
        try:
            require_research_live_provider_health(research_live_capability, pc["provider_health"])
        except RunOriginError as exc:
            raise WeekendOrchestratorError(
                "provider-backed provider health does not match the receipt-bound provider outcome"
            ) from exc

    # (1c) §2.1/§3.5 run-mode / calendar gate + session DERIVATION: validate the calendar artifact, hard-gate live
    # mode (batch5), and DERIVE the §2.1 sessions from the calendar via build_sessions (normalize, not a caller
    # list) so missing / extra / duplicate / wrong-open-close / wrong-day sessions are impossible by construction.
    cal = _assert_calendar(pc["calendar"], run_mode)
    sessions = sessions_for_window(now_et.strftime("%Y%m%d"), calendar=cal)

    selection = run_selection(
        now_et,
        sessions,
        pc["data_context"],
        eligibility_governance=pc["eligibility_governance"],
        require_pass1_exclusion_summary=(run_mode == "mixed_source"),
    )
    if selection["out_of_window"]:
        # §2.1 intraday dead zone: NO-EMIT — do not run the downstream chain, produce no machine record /
        # report / private artifact (a run that cannot have a canonical decision_date emits nothing).
        return {"out_of_window": True, "emitted": False, "no_emit_reason": "out_of_window",
                "decision_date": None, "run_date": selection["run_date"], "selection": selection}
    decision_date = selection["decision_date"]   # §2.1 the ONE canonical anchor threaded below
    report_selection = selection
    upstream_pass1 = pc["data_context"].get("pass1_exclusion_summary")
    if upstream_pass1 is not None:
        report_selection = {**selection, "pass1_exclusion_summary": upstream_pass1}

    # (1b) §3.7 provider-health gate: critical SEC health degraded/down/missing NO-EMITs. Advisory FMP grades stays
    # visible as usable_with_fallback and may emit with its §4.2 catalyst contribution neutral-filled. The classifier
    # structurally refuses unauthorized sources; restricted/blocked still fail closed.
    # Cross-week state is selected by the capstone/e2e boundary. A direct offline packet may also carry the
    # already-selected dated child, but this orchestrator never treats a root-level sidecar or a missing selected
    # file as a first run. The market state is the source of the anti-chatter pair; template values are ignored.
    prior_run_dir = pc["prior_run_dir"]
    prior_regime, prior_upgrade_count = None, 0
    if prior_run_dir is not None:
        try:
            prior_run_dir = validate_prior_run_dir(
                pc["prior_runs_private_root"], prior_run_dir, decision_date=decision_date)
            prior_market_state = load_market_regime_state(
                prior_run_dir / MARKET_REGIME_STATE_FILENAME, decision_date=decision_date)
            if prior_market_state["as_of"] != prior_run_dir.name:
                raise MarketRegimeStateError("prior market regime state date does not match its dated directory")
            prior_regime = prior_market_state["market_risk_regime"]
            prior_upgrade_count = prior_market_state["upgrade_count"]
        except (MarketRegimeStateError, PrivatePathError, ValueError, OSError) as exc:
            raise WeekendOrchestratorError("selected prior market-regime state is unavailable") from exc

    provider_health = classify_provider_health(pc["provider_health"])
    if provider_health["overall_run_state"] not in EMIT_ALLOWED_RUN_STATES:
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

    # The target levels are private state, distinct from the current account snapshot. A malformed existing
    # state is never overwritten; the planner emits observe until the manual/private state is repaired.
    state_writable = True
    try:
        prior_holding_state = (
            None if prior_run_dir is None else load_holding_action_state(
                prior_run_dir / STATE_FILENAME,
                decision_date=decision_date,
                require_present=True,
            )
        )
        if prior_holding_state is not None and prior_holding_state["as_of"] != prior_run_dir.name:
            raise HoldingActionError("prior holding-action state date does not match its dated directory")
        holding_contexts = build_holding_action_context(pc["account_state"], prior_holding_state)
    except HoldingActionError:
        holding_contexts, state_writable = {}, False
    built_rows = _build_analysis_rows(selection, pc["per_ticker_analysis"])
    try:
        themed_rows, _ = bind_theme_contexts(   # 2nd flag intentionally unused: missing-recon new-build block is enforced downstream by the cash-capacity stage

            selection, built_rows, account_state=pc["account_state"], decision_date=decision_date,
            selection_input_provenance=pc["run_provenance"]["families"]["selection_inputs"])
    except ThemeResultLinkageError as exc:
        raise WeekendOrchestratorError(f"Cut3 theme linkage rejected: {exc}") from exc
    rows = attach_holding_action_context(
        themed_rows, holding_contexts, price_basis_date=selection["price_basis_date"])
    try:
        # A Batch5/Cut4 row may only use the exact source-bound price input that arrived with its own source
        # receipt.  Legacy Batch4 fixtures without source facts keep their established offline contract.
        rows = bind_result_source_facts(
            rows, as_of=decision_date, price_basis_date=selection["price_basis_date"])
    except ResultSourceLinkageError as exc:
        raise WeekendOrchestratorError(f"Cut4 source-result linkage rejected: {exc}") from exc
    # Second-cut account guard: the run-level status is classified from a source-bound model-paper record, not
    # copied from basket_context.  A corrupt previous private state never yields normal; the classifier receives
    # an invalid prior and therefore fails closed to caution, while the corrupt file is not overwritten.
    try:
        prior_guard_state = (
            None if prior_run_dir is None else load_portfolio_guard_state(
                prior_run_dir / PORTFOLIO_GUARD_STATE_FILENAME,
                decision_date=decision_date,
                require_present=True,
            )
        )
        if prior_guard_state is not None and prior_guard_state["as_of"] != prior_run_dir.name:
            raise ResultEffectsError("prior portfolio-guard state date does not match its dated directory")
        prior_guard = "normal" if prior_guard_state is None else prior_guard_state["state"]
    except ResultEffectsError:
        prior_guard = "__malformed__"
    portfolio_guard_result = build_portfolio_guard_result(
        pc["paper_track"], prior_state=prior_guard, as_of=decision_date)

    # Symbol cooldowns are private, manual-reconciliation-backed state.  Absence/corruption is conservative
    # ``in_cooldown`` rather than the previous injected ``none`` business placeholder; no new build can pass it.
    try:
        prior_cooldown_state = (
            empty_symbol_cooldown_state(decision_date)
            if prior_run_dir is None else load_symbol_cooldown_state(
                prior_run_dir / SYMBOL_COOLDOWN_STATE_FILENAME,
                decision_date=decision_date,
                require_present=True,
            )
        )
        if prior_run_dir is not None and prior_cooldown_state["as_of"] != prior_run_dir.name:
            raise SymbolCooldownStateError("prior symbol-cooldown state date does not match its dated directory")
        next_cooldown_state = build_next_symbol_cooldown_state(
            prior_cooldown_state, pc["account_state"]["symbol_cooldown_reconciliation"], decision_date=decision_date)
        cooldown_by_ticker = resolve_symbol_cooldowns(next_cooldown_state, rows, decision_date=decision_date)
    except (KeyError, SymbolCooldownStateError):
        # Preserve the conservative current-week decision, but publish an explicit empty first-value state so a
        # later valid account reconciliation can recover instead of remaining permanently unavailable.
        next_cooldown_state = empty_symbol_cooldown_state(decision_date)
        cooldown_by_ticker = unavailable_cooldown_records(rows, as_of=decision_date)
    portfolio_capacity = _portfolio_capacity_context(
        selection, rows, account_state=pc["account_state"],
        sizing_context=pc["sizing_context"], available_cash=pc["available_cash"], decision_date=decision_date)
    analysis = analyze_rows(rows, market_axis_regimes=pc["market_axis_regimes"],
                            prior_regime=prior_regime, prior_upgrade_count=prior_upgrade_count)
    decided = decide_actions(analysis)
    effected = apply_result_effects(decided, portfolio_guard_result=portfolio_guard_result,
                                    cooldown_by_ticker=cooldown_by_ticker, as_of=decision_date)
    try:
        source_effects = source_coverage_effect_records(effected["rows"], as_of=decision_date)
        if source_effects:
            effected = extend_result_effects(effected, effects_by_ticker=source_effects, as_of=decision_date)
    except (ResultSourceLinkageError, ResultEffectsError) as exc:
        raise WeekendOrchestratorError(f"Cut4 source coverage effect rejected: {exc}") from exc
    lifecycle_effected = apply_theme_lifecycle_effects(effected, as_of=decision_date)
    sized = apply_macro_cluster_two_pass(
        lifecycle_effected, sizing_context=pc["sizing_context"],
        existing_positions=_macro_existing_positions(pc["account_state"], rows), as_of=decision_date)
    runtime_basket_context = _runtime_basket_context(sized["rows"], pc["basket_context"])
    basket = resolve_build_capacity(sized, basket_context=runtime_basket_context)
    cost_floored = apply_probe_cost_floor(basket, cost_inputs=_probe_cost_inputs(basket))
    cash = apply_cash_allocation(cost_floored, available_cash=pc["available_cash"],
                                 portfolio_capacity=portfolio_capacity)
    ranked = apply_action_rank(cash)
    # Write down the exposure limits this decision just worked to. Nothing is
    # computed here that the decision did not already have, and nothing above
    # reads the result, so selection, actions, sizing and NAV are byte-identical
    # whether or not this succeeds. Total adapter for exactly that reason: a
    # diagnostic note may never take down a week of stock selection (design
    # section 1.3), so a failure leaves no note and the diagnostic week is
    # honestly unavailable.
    try:
        write_decision_exposure(
            build_decision_exposure_record(
                decision_date=decision_date, account_state=pc["account_state"],
                regime=decided["regime"], rows=ranked["rows"],
                portfolio_capacity=portfolio_capacity),
            runs_private_root=pc["runs_private_root"])
    except Exception:                                                             # noqa: BLE001 — see above
        pass
    holding_action_state = None
    if state_writable:
        try:
            holding_action_state = build_next_holding_action_state(decision_date, ranked["rows"])
        except HoldingActionError:
            # Do not replace a private TP state unless it was rebuilt from fully reconciled facts.
            holding_action_state = None
    if holding_action_state is None:
        # A withheld week still publishes a valid first-value state so the next week can recover in-band.
        holding_action_state = build_next_holding_action_state(decision_date, [])
    portfolio_guard_state = build_next_portfolio_guard_state(portfolio_guard_result, decision_date=decision_date)
    market_regime_state = build_market_regime_state(decision_date, analysis)

    # batch4 honesty provenance: the immutable run-origin fact (offline fixture, fully provider-derived research, or
    # receipt-bound mixed source; all operational_use=not_authorized), threaded through K/m2/N so no source mix
    # can be mistaken for operational weekly advice
    # (R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP). live (operationally authoritative) stays hard-gated above
    # (→ batch5), so run_origin_for_mode only returns a non-operational permitted fact here.
    run_origin = run_origin_for_mode(run_mode)
    machine_record = assemble_machine_record(
        ranked, as_of=decision_date, run_origin=run_origin,
        research_live_capability=research_live_capability,
        require_result_effects=True,
    )   # decision_date → K as_of; second-cut formal factors cannot bypass the §10 gate
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
                      "portfolio_guard_status": portfolio_guard_result["state"],
                      "theme_opportunity_state": pc["basket_context"]["theme_opportunity_state"]},
        selection=report_selection)
    written = write_run_private(                                                  # decision_date → N (idempotent)
        decision_date=decision_date, machine_record=machine_record, weekly_report_md=report["weekly_report_md"],
        report_data=report["report_data"],
        selection=report_selection,
        # source-fact reconciliation (R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP): the persistence boundary
        # rebinds report_data.run_status / offline_honesty to the RUN-LEVEL provider-health + holding coverage + the
        # independent lifecycle stage result the run actually used, so a forged count/state (incl. a coordinated
        # all-copies lifecycle forge) cannot ride byte-equality.
        provider_health=provider_health, coverage_inputs=pc["report_context"]["coverage_inputs"],
        lifecycle_result=lifecycle_result,
        runs_private_root=pc["runs_private_root"],
        weekly_private_root=pc["weekly_private_root"], holding_action_state=holding_action_state,
        portfolio_guard_state=portfolio_guard_state,
        symbol_cooldown_state=next_cooldown_state,
        market_regime_state=market_regime_state,
        run_origin=run_origin,
        research_live_capability=research_live_capability)

    return {"out_of_window": False, "emitted": True, "decision_date": decision_date,
            "run_date": selection["run_date"], "selection": selection, "machine_record": machine_record,
            "lifecycle_result": lifecycle_result, "report_data": report["report_data"], "written": written,
            "run_provenance": run_provenance, "provider_health": provider_health, "run_origin": run_origin}
