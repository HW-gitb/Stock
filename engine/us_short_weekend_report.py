# -*- coding: utf-8 -*-
"""US-short weekend-pipeline §11.2 weekly_report assembly — batch4 slice 4d-ii-m2 (report_data 装配 + render).

Design authority: docs/us_short_system_design.md §11.2 (周报 13 节 + 诚实横幅①②③④⑤ + price_clock + lifecycle 数量对账)
/ §11.1 (周报从机器层渲染) / §13 (lifecycle 提醒) / §12 (ship-gate) / §18.2 batch4 slice 4d.

The post-pass after 4d-ii-k (machine record) + 4d-ii-l (lifecycle eval) + 4d-ii-m1 (action_table projection). It
ASSEMBLES the §11.2 `report_data` (the 13 sections + the honest banner ①②③④⑤ + the lifecycle-count reconcile)
and renders it via the content-agnostic `us_short_weekly_report_renderer.render_weekly_report`. It DERIVES what the
machine layer + lifecycle eval own, WIRES the batch-3 §11.2 formatters, and takes the genuinely non-derivable
inputs (price_clock, the editorial sections, provider health, exclusion / hot-excluded / coverage raw inputs) from
an injected `report_context`, and the canonical resolver clock from `run_context` (batch4 offline fixture; batch5
fills the same seams):

  * banner ① true/false observe split  ← machine-record observe rows (aggregate_observe_split → render);
  * banner ④ price_clock (ALWAYS shown) ← report_context, reconciled against resolver run_context
    (validated by validate_price_clock + the renderer);
  * banner ③ ship-gate + matured lifecycle count ← frozen batch4 paper-only ship-gate engine + L readiness;
  * banner ⑤ hot_excluded notice ← selection-derived exclusion_data via build_exclusion_summary(...)["public"],
    then render_hot_excluded_banner — the SINGLE source the §9 detail also uses (banner count == §11.4 detail,
    §18.1 #19; there is NO separate report_context hot-excluded summary input);
  * banner ② macro_cluster ← report_context (optional; omitted when blank);
  * §11.5 持仓覆盖诚实度 (in §6) ← report_context coverage; §9 剔除摘要 (§11.4) ← actual selection rejects;
  * §12 字段·模块生命周期提醒 + the §11.2 lifecycle-count reconcile ← L readiness due scan;
  * the row sections (5 操作表 / 6 持仓复核 / 7 Top15 / 8 观察池) ← the flattened §11.3 machine rows (slice m1).

Consumer-validation at the boundary (the recurring batch4 lesson — a stage that RE-EMITS official output must
value-validate the inputs it now owns): `report_context` and `run_context` are CLOSED-WORLD (exact key sets),
`lifecycle_result` is re-validated for shape, the machine record is flattened via the m1 §10/§6 gate, and the
formatters / the renderer re-validate their own inputs (single source). Pure/offline; no provider/live/network;
no broker/auto-order; no A-share crossing.
"""
from __future__ import annotations

from datetime import datetime

from engine.us_short_coverage_honesty import build_row_coverage, render_coverage_section
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_exclusion_summary import build_exclusion_summary, render_exclusion_section
from engine.us_short_hot_excluded import render_hot_excluded_banner
from engine.us_short_lifecycle_readiness import LifecycleReadinessError, _assert_readiness
from engine.us_short_observe_split import aggregate_observe_split, render_observe_split
from engine.us_short_portfolio_guard import PORTFOLIO_GUARD_STATES
from engine.us_short_price_clock import validate_price_clock
from engine.us_short_provider_health import validate_provider_health_result
from engine.us_short_run_origin import (
    OFFLINE_TEST_RUN_ORIGIN,
    assert_offline_report_invariants,
    build_offline_honesty,
    build_run_status,
    canonical_offline_sections,
    canonical_section_1,
    require_research_live_capability,
    require_research_live_provider_health_result,
    validate_run_origin,
)
from engine.us_short_selection_exclusions import build_selection_exclusion_data
from engine.us_short_ship_gate_sizing import ship_gate_sizing
from engine.us_short_theme_probe import THEME_OPPORTUNITY_STATES
from engine.us_short_theme_selection import THEME_SELECTION_MODES
from engine.us_short_weekend_action_table import flatten_machine_record
from engine.us_short_weekly_report_renderer import render_weekly_report

# the genuinely non-machine / non-lifecycle inputs the §11.2 assembly needs (closed-world — an unknown / missing
# key fails closed, so a section can never silently render blank from a forgotten input). batch4 = offline fixture.
# Exclusion and ship-gate facts are intentionally absent: selection rejects and the batch4 paper-only gate are
# their single sources, so detached prose/counts cannot contradict the run.
_REPORT_CONTEXT_KEYS = frozenset({
    "price_clock", "coverage_inputs",
    "core_conclusion", "risk_downgrade_note",
    "macro_cluster_banner",
})
_OPTIONAL_REPORT_CONTEXT_KEYS = frozenset({"forward_policy_comparison_reminder"})
# the STRUCTURED decision-stage status the §11.2 report BINDS to (no free-text status, R-USSHORT-BATCH4-OFFICIAL-
# REPORT-SOURCE-BINDING-GAP): provider health from `classify_provider_health`, the account portfolio_guard, and
# the theme opportunity state — the EXACT inputs/outputs the decision used, so the report can never contradict the
# run. `account_risk_note` / `provider_health_note` remain in report_context as EDITORIAL commentary (rendered
# AFTER the structured status), never the source of the status itself.
_STAGE_STATUS_KEYS = frozenset({"provider_health", "portfolio_guard_status", "theme_opportunity_state"})
_RUN_CONTEXT_KEYS = frozenset({"decision_date", "price_basis_date", "run_date"})
_HOLDING_SOURCES = frozenset({"holding_in_top15", "holding_pass2_only", "holding_account_only"})
_SELECTED_SOURCES = frozenset({"top15_candidate", "holding_in_top15"})
_OBSERVE, _BUILD = "观察", "建仓"


class WeekendReportError(Exception):
    """The injected machine record / lifecycle result / report_context is malformed (fail-closed before render)."""


def report_row_groups(rows):
    """Single-source §11.2 row classification from the flattened §11.3 machine rows — used by build_weekly_report
    (sections + run_status counts) AND the private-write source-reconciliation boundary, so the persisted
    run_status counts are RE-DERIVED from the same machine rows, never trusted from caller report_data
    (R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP)."""
    return {
        "builds": [r for r in rows if isinstance(r, dict) and r.get("final_action") == _BUILD],
        "observes": [r for r in rows if isinstance(r, dict) and r.get("final_action") == _OBSERVE],
        "holdings": [r for r in rows if isinstance(r, dict) and r.get("row_source") in _HOLDING_SOURCES],
        "selected": [r for r in rows if isinstance(r, dict) and r.get("row_source") in _SELECTED_SOURCES],
    }


def canonical_lifecycle_section(readiness):
    """Single-source §12 lifecycle-reminder lines, derived PURELY from a validated readiness (due_count /
    total_items / due_items / upgrade_eligible_items) — used by build_weekly_report AND the private-write boundary,
    so the §12 due-item / upgrade DETAIL (not only the count) cannot be forged in report_data independent of the
    lifecycle source (R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP lifecycle-source detail)."""
    if readiness["due_count"]:
        return ["本周 %d/%d 个 §13.1 校准项达到复审线: %s"
                % (readiness["due_count"], readiness["total_items"],
                   "、".join("#%d" % n for n in readiness["due_items"])),
                "升级可评估(§12.2 margin 已冻): %s; 升级须用户决定、绝不自动切生产"
                % ("、".join("#%d" % n for n in readiness["upgrade_eligible_items"]) or "无")]
    return ["本周无 §13.1 校准项达到复审线 (0/%d)" % readiness["total_items"]]


def reconcile_holding_coverage(holdings, coverage_inputs):
    """Single-source §11.5 coverage reconciliation: bind coverage_inputs ONE-TO-ONE to the machine holding rows by
    canonical ticker + exact row_source, returning the validated coverage_records — used by build_weekly_report
    AND the private-write boundary, so `coverage_non_full_count` is bound to validated holding coverage, never
    trusted from caller report_data (R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP). Fail-closed on a
    non-list input, a malformed row, a non-canonical ticker, a swapped row_source, or a coverage set that does
    not exactly cover the holding rows."""
    if not isinstance(coverage_inputs, list):
        raise WeekendReportError("report_context.coverage_inputs 须为 list")
    holding_source_by_ticker = {r["ticker"]: r.get("row_source") for r in holdings}
    holding_tickers = sorted(holding_source_by_ticker)
    coverage_records, cov_tickers = [], []
    for ci in coverage_inputs:
        if not (isinstance(ci, dict) and set(ci) == {"ticker", "row_source", "data_checks"}):
            raise WeekendReportError(f"coverage_inputs 行须为 {{'ticker','row_source','data_checks'}}: {ci!r}")
        ct = canonical_us_ticker(ci["ticker"])
        if ct is None:
            raise WeekendReportError(f"coverage_inputs ticker 非规范 US ticker: {ci['ticker']!r}")
        # reconcile each coverage row to the EXACT machine holding-row source (not just ticker): a swapped
        # row_source (e.g. holding_pass2_only ↔ holding_account_only) for the same ticker fails closed.
        if ct in holding_source_by_ticker and ci["row_source"] != holding_source_by_ticker[ct]:
            raise WeekendReportError(
                "coverage_inputs[%s] row_source %r 与持仓行 %r 不符（须对账 machine 行身份）"
                % (ct, ci["row_source"], holding_source_by_ticker[ct]))
        cov_tickers.append(ct)
        coverage_records.append(build_row_coverage(ci["row_source"], ci["data_checks"]))
    if sorted(cov_tickers) != holding_tickers:
        raise WeekendReportError(
            "coverage_inputs 须一对一覆盖持仓行（无空/缺/多/重）: coverage=%s holdings=%s"
            % (sorted(cov_tickers), holding_tickers))
    return coverage_records


def _as_lines(value, where):
    """An injected editorial section/banner value → a list of non-blank lines (or a non-blank str). Fail-closed:
    a blank / non-str / list-with-blank value is refused so a §11.2 section can never render empty."""
    if isinstance(value, str):
        if not value.strip():
            raise WeekendReportError(f"{where} 不得为空白")
        return [value.strip()]
    if isinstance(value, (list, tuple)) and value and all(isinstance(x, str) and x.strip() for x in value):
        return [x.strip() for x in value]
    raise WeekendReportError(f"{where} 须为非空白 str 或非空 str 列表: {value!r}")


def _validate_report_context(rc):
    if not (isinstance(rc, dict) and set(rc) in {
        _REPORT_CONTEXT_KEYS,
        _REPORT_CONTEXT_KEYS | _OPTIONAL_REPORT_CONTEXT_KEYS,
    }):
        raise WeekendReportError(
            f"report_context 顶层键须恰为 {sorted(_REPORT_CONTEXT_KEYS)}（closed-world）: {sorted(rc) if isinstance(rc, dict) else rc!r}")


def _validate_stage_status(ss):
    """The structured decision-stage status the report binds §2/§3/§11 to (never a free-text status). Fail-closed:
    provider_health must be a `classify_provider_health` result (overall_run_state ∈ RUN_STATES); portfolio_guard
    and theme_opportunity_state must be the frozen §8/§4.5 vocab values the basket actually used."""
    if not (isinstance(ss, dict) and set(ss) == _STAGE_STATUS_KEYS):
        raise WeekendReportError(
            f"stage_status 顶层键须恰为 {sorted(_STAGE_STATUS_KEYS)}（closed-world）: {sorted(ss) if isinstance(ss, dict) else ss!r}")
    if not validate_provider_health_result(ss["provider_health"]):
        raise WeekendReportError(
            f"stage_status.provider_health 须为内部一致的 classify_provider_health 结果（拒伪造 health dict）: {ss['provider_health']!r}")
    if ss["portfolio_guard_status"] not in PORTFOLIO_GUARD_STATES:
        raise WeekendReportError(
            f"stage_status.portfolio_guard_status 非法（须 ∈ {sorted(PORTFOLIO_GUARD_STATES)}）: {ss['portfolio_guard_status']!r}")
    if ss["theme_opportunity_state"] not in THEME_OPPORTUNITY_STATES:
        raise WeekendReportError(
            f"stage_status.theme_opportunity_state 非法（须 ∈ {sorted(THEME_OPPORTUNITY_STATES)}）: {ss['theme_opportunity_state']!r}")


def _strict_yyyymmdd(value):
    if not (isinstance(value, str) and len(value) == 8 and value.isascii() and value.isdigit()):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
        return True
    except ValueError:
        return False


def _validate_run_context(run_context):
    if not (isinstance(run_context, dict) and set(run_context) == _RUN_CONTEXT_KEYS):
        raise WeekendReportError(
            f"run_context 顶层键须恰为 {sorted(_RUN_CONTEXT_KEYS)}（closed-world）: "
            f"{sorted(run_context) if isinstance(run_context, dict) else run_context!r}")
    for key in _RUN_CONTEXT_KEYS:
        if not _strict_yyyymmdd(run_context[key]):
            raise WeekendReportError(f"run_context.{key} 须为真实 ASCII YYYYMMDD: {run_context[key]!r}")
    if not (run_context["price_basis_date"] <= run_context["run_date"] <= run_context["decision_date"]):
        raise WeekendReportError(
            "run_context 日期顺序非法（须 price_basis_date <= run_date <= decision_date）: %r" % run_context)


def _validate_lifecycle_result(lr):
    """Re-validate the 4d-ii-l result at this official boundary (never trust upstream shape). The readiness's
    FULL contract — schema + due_count==len(due_items) + ids in [1, total_items] + upgrade ⊆ due + real as_of —
    is re-asserted via the SINGLE-SOURCE readiness validator `_assert_readiness` (not just broad shape), so an
    inconsistent readiness (e.g. due_count=2 with due_items=[]) fails closed here even if it bypassed L."""
    if not (isinstance(lr, dict) and isinstance(lr.get("readiness"), dict)
            and isinstance(lr.get("decision_date"), str) and lr["decision_date"].strip()
            and isinstance(lr.get("banner"), str) and lr["banner"].strip()):
        raise WeekendReportError("lifecycle_result 须为含 readiness(dict)+decision_date(str)+非空 banner(str) 的 4d-ii-l 输出")
    try:
        _assert_readiness(lr["readiness"])   # single source: schema + due_count/ids/upgrade-subset/real as_of
    except LifecycleReadinessError as e:
        raise WeekendReportError(f"lifecycle_result.readiness 不一致（单源 readiness 契约）: {e}")


def _reconcile_decision_date(canonical, price_clock, lifecycle_result, exclusion_data):
    """§2.1 / §11: ONE canonical decision_date must thread through every official-report artifact. The
    machine_record as_of is the reference; price_clock.decision_date, the lifecycle decision_date + readiness
    as_of, and exclusion_data.as_of must ALL equal it — else the report would stitch rows from one week,
    lifecycle reminders from another, a price clock for a third, and exclusions for a fourth (the gap §2.1
    exists to prevent)."""
    anchors = {
        "price_clock.decision_date": price_clock.get("decision_date") if isinstance(price_clock, dict) else None,
        "lifecycle_result.decision_date": lifecycle_result.get("decision_date"),
        "lifecycle_result.readiness.as_of": lifecycle_result["readiness"].get("as_of"),
        "exclusion_data.as_of": exclusion_data.get("as_of") if isinstance(exclusion_data, dict) else None,
    }
    mismatched = {k: v for k, v in anchors.items() if v != canonical}
    if mismatched:
        raise WeekendReportError(
            f"decision_date 不一致（须全 == machine_record.as_of={canonical!r}，§2.1 单一 decision_date 穿线）: {mismatched}")


def _reconcile_price_clock(canonical, price_clock, run_context):
    """The visible §11.2 price clock must be the resolver's canonical clock, not merely an internally ordered
    date triple. This closes the stale-price / future-news gap: price_data_through equals the resolved prior
    closed session, news_window_through equals the run date at date granularity, and decision_date equals the
    canonical upcoming session."""
    anchors = {
        "run_context.decision_date": run_context["decision_date"],
        "price_clock.decision_date": price_clock.get("decision_date") if isinstance(price_clock, dict) else None,
    }
    mismatched = {k: v for k, v in anchors.items() if v != canonical}
    if mismatched:
        raise WeekendReportError(
            f"run_context/price_clock decision_date 不一致（须全 == machine_record.as_of={canonical!r}）: {mismatched}")
    if price_clock.get("price_data_through") != run_context["price_basis_date"]:
        raise WeekendReportError(
            "price_clock.price_data_through %r != resolved price_basis_date %r（§2.1 canonical prior session）"
            % (price_clock.get("price_data_through"), run_context["price_basis_date"]))
    if price_clock.get("news_window_through") != run_context["run_date"]:
        raise WeekendReportError(
            "price_clock.news_window_through %r != resolved run_date %r（§2.1 news window must stop at run time）"
            % (price_clock.get("news_window_through"), run_context["run_date"]))


def _num(v):
    """A price/size cell for a one-line summary: a finite number → its str, else '·' (the cell was not produced)."""
    return str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else "·"


def _one_glance(row):
    """§11.2 §5 精简一眼表 one-liner from a flattened §11.3 row: 操作 / 股数 / 入·盈一·盈二·损 / 类型 / 优先级."""
    return ("%s %s | shares=%s | entry=%s tp1=%s tp2=%s stop=%s | %s | rank=%s"
            % (row.get("ticker"), row.get("final_action"), _num(row.get("model_position_size_shares")),
               _num(row.get("valid_entry_high")), _num(row.get("take_profit_reduce_price")),
               _num(row.get("take_profit_exit_price")), _num(row.get("stop_clear_price")),
               row.get("order_type") or "·", _num(row.get("action_rank"))))


def _rows_section(rows, label):
    """A non-blank section body from a list of one-liner strings (an empty group renders an honest '无' line)."""
    return rows if rows else ["%s：无" % label]


def _theme_selection_status(selection):
    """Render the source-bound Top15 theme mode; never infer cross-industry discovery from a theme score."""
    if not isinstance(selection, dict):
        raise WeekendReportError("selection must be a dict")
    mode = selection.get("theme_selection_mode")
    upgrades = selection.get("full_analysis_leader_upgrades")
    if mode not in THEME_SELECTION_MODES:
        raise WeekendReportError("selection.theme_selection_mode is missing or invalid")
    if not isinstance(upgrades, list) or any(
        not isinstance(ticker, str) or canonical_us_ticker(ticker) != ticker for ticker in upgrades
    ) or len(set(upgrades)) != len(upgrades):
        raise WeekendReportError("selection.full_analysis_leader_upgrades must be unique canonical tickers")
    if mode == "industry_heat_v1_cross_industry_disabled":
        mode_line = "industry heat v1；cross-industry path disabled"
    else:
        mode_line = "source-bound provisional cross-industry gate enabled"
    return "主题选择=%s（%s）；Top6-15 龙头完整分析升级=%s" % (
        mode, mode_line, ",".join(upgrades) if upgrades else "无")


def build_weekly_report(machine_record, lifecycle_result, *, report_context, run_context, stage_status, selection,
                        run_origin=OFFLINE_TEST_RUN_ORIGIN, research_live_capability=None):
    """4d-ii-m2 §11.2 weekly_report assembly + render.

    machine_record = the 4d-ii-k `assemble_machine_record` output (flattened here via slice m1 for the §11.3 rows).
    lifecycle_result = the 4d-ii-l `run_lifecycle_eval_stage` output {decision_date, readiness, banner}.
    report_context = the injected closed-world non-derivable inputs (price_clock + editorial sections +
        coverage raw inputs); batch4 offline fixture, batch5 real. Exclusions are derived from ``selection``.
    run_context = the resolver/selection clock {decision_date, price_basis_date, run_date}; the visible
        price_clock must match it exactly at date granularity.
    stage_status = the STRUCTURED decision-stage status {provider_health (classify_provider_health result),
        portfolio_guard_status, theme_opportunity_state} the report BINDS §2/§3/§11 to — the exact inputs/outputs
        the decision used, so the report can never contradict the run (no free-text status).

    Returns {"weekly_report_md": <markdown str>, "report_data": <the assembled §11.2 report_data dict>}. Raises
    WeekendReportError on a malformed machine record / lifecycle result / report_context (and the formatters /
    renderer raise their own typed errors on a malformed formatter input / a §11.2 render-invariant violation —
    incomplete price_clock, lifecycle-count mismatch, a section without content)."""
    require_research_live_capability(
        run_origin, research_live_capability,
        decision_date=(run_context.get("decision_date") if isinstance(run_context, dict) else None),
    )   # consumer-layer honesty gate (Required A) — first
    _validate_report_context(report_context)
    _validate_run_context(run_context)
    _validate_stage_status(stage_status)
    if isinstance(run_origin, dict) and run_origin.get("run_mode") == "research_live":
        require_research_live_provider_health_result(
            research_live_capability, stage_status["provider_health"]
        )
    _validate_lifecycle_result(lifecycle_result)
    validate_run_origin(run_origin)   # batch4 honesty provenance (offline_test / caller_supplied_fixture)
    # flatten through the m1 §10/§6 gate (re-validates the machine record + projects the §11.3 columns).
    flat = flatten_machine_record(machine_record)
    rows = flat["rows"]
    # §2.1 / §11: reconcile ONE canonical decision_date across every official-report artifact before rendering,
    # so the report can never stitch rows / lifecycle / price clock / exclusions from different weeks.
    theme_selection_status = _theme_selection_status(selection)
    exclusion_data = build_selection_exclusion_data(selection)
    _reconcile_decision_date(flat.get("as_of"), report_context["price_clock"], lifecycle_result, exclusion_data)
    _reconcile_price_clock(flat.get("as_of"), report_context["price_clock"], run_context)
    readiness = lifecycle_result["readiness"]
    due_count = readiness["due_count"]

    # --- row groups from the flattened §11.3 machine rows (single-source classification, also re-derived at the
    # private-write boundary so the persisted run_status counts cannot be forged in report_data) ---
    groups = report_row_groups(rows)
    builds, observes, holdings = groups["builds"], groups["observes"], groups["holdings"]
    # The Top15 view includes the legal admitted+holding overlap. Use the same selected-row identity as the
    # action-table consumer and order by the preserved selection rank, independent of machine/action row order.
    candidates = sorted(groups["selected"], key=lambda r: r["selection_record"]["selection_rank"])
    actionable = [r for r in rows if r.get("final_action") not in (_OBSERVE,)]
    regime_value = rows[0].get("market_risk_regime") if rows else None   # run-level regime, carried per-row by K

    # §9 exclusion summary built FIRST (build_exclusion_summary fully validates exclusion_data incl. its
    # hot_excluded) so the banner ⑤ + the §11.4 detail are ONE source — their hot counts cannot disagree (§18.1 #19).
    exclusion_public = build_exclusion_summary(exclusion_data)["public"]
    exclusion_lines = render_exclusion_section(exclusion_public)

    # --- honest banner (① observe split derived; ②③⑤ via formatter / lifecycle / context; ④ price_clock) ---
    observe_split = aggregate_observe_split([r.get("observe_reason_type") for r in observes])
    price_clock = report_context["price_clock"]
    validate_price_clock(price_clock)   # §21 gate also re-run by the renderer; fail clear here too
    batch4_ship_gate = ship_gate_sizing(0.0, 0, hard_veto=False,
                                        evidence_level="paper", graduated_full_size=False)
    banner = {
        "price_clock": price_clock,                                                       # ④ always shown
        "true_false_observe_split": render_observe_split(observe_split),                  # ①
        "ship_gate_progress": "live_permission=%s; warning=%s | lifecycle 达标(升级可评估) %d 项"  # ③
                              % (batch4_ship_gate["live_permission_status"],
                                 batch4_ship_gate["live_size_warning"],
                                 len(readiness["upgrade_eligible_items"])),
        # ⑤ derived from the SAME validated exclusion public summary the §9 detail uses (single source) — so the
        # §11.2 banner hot count can never disagree with the §11.4 exclusion detail (§18.1 #19).
        "hot_excluded_notice": render_hot_excluded_banner(
            {"public_heat_count": exclusion_public["hot_excluded_public_heat_count"], "holdings": []}),
    }
    macro = report_context["macro_cluster_banner"]
    if isinstance(macro, str) and macro.strip():
        banner["macro_cluster_warning"] = macro.strip()                                   # ② (optional)
    reminder = report_context.get("forward_policy_comparison_reminder")
    if isinstance(reminder, str) and reminder.strip():
        banner["forward_policy_comparison_reminder"] = reminder.strip()

    # --- §11.5 coverage (in §6): bind ONE-TO-ONE to the machine record's holding rows BY TICKER (R-USSHORT-
    # BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP) — every holding must carry exactly one coverage record; an empty
    # / missing / extra / duplicate coverage set fails closed, so a held position can never render "全 full 无
    # 缺口" with no coverage proof.
    coverage_records = reconcile_holding_coverage(holdings, report_context["coverage_inputs"])
    coverage_lines = render_coverage_section(coverage_records)
    not_clean = [c for c in coverage_records if c["coverage_status"] != "full"]   # §13 不 clean 项 = 覆盖非 full

    # --- §12 lifecycle reminders + the §11.2 count reconcile (section 1 == section 12) ---
    # single-source §12 detail (also re-derived at the private-write boundary from the independent lifecycle source).
    lifecycle_lines = canonical_lifecycle_section(readiness)

    offline_honesty = build_offline_honesty(
        stage_status["provider_health"]["overall_run_state"], len(not_clean))
    offline_s11, offline_s13 = canonical_offline_sections(offline_honesty, run_origin)
    # §1 is the system-owned authoritative run-status section: build it from the immutable run_origin + a typed
    # closed-world run_status, so the consumer can recompute it canonically (no extra operational line after the
    # sentinel) — R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP §1 canonical repair.
    run_status = build_run_status(price_clock["decision_date"], len(builds), len(observes),
                                  len(holdings), len(candidates), due_count)
    sections = {
        # always-visible offline/fixture disclosure FIRST (R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP):
        # a batch4 run is always an offline_test run over a caller-supplied fixture, so the very first section
        # states it before any status/counts can read as operational.
        1: canonical_section_1(run_origin, run_status),
        # §2/§3/§11 render ONLY the STRUCTURED stage_status (portfolio_guard / theme / provider health the run
        # actually used). The status-bearing free-text notes were REMOVED (Codex re-review 2): an editorial
        # "portfolio_guard=normal" could otherwise sit beside a structured cooldown — the authoritative status now
        # carries NO contradicting prose (R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP).
        2: ["账户组合风险闸: portfolio_guard=%s（结构化、权威，无自由文本状态）" % stage_status["portfolio_guard_status"]],
        3: ["市场环境 两轴: market_risk_regime=%s / theme_opportunity_state=%s"
            % (regime_value or "·", stage_status["theme_opportunity_state"]), theme_selection_status],
        4: _as_lines(report_context["core_conclusion"], "core_conclusion"),
        5: _rows_section([_one_glance(r) for r in actionable], "最终操作表"),
        6: _rows_section([_one_glance(r) for r in holdings], "当前持仓复核") + coverage_lines,
        # §7 Top15 = the SELECTION view (多强): display the PRESERVED selection_rank + selection-time core_score
        # (slice 2b, from the threaded selection_record), NOT action_rank (先干哪个 = the §5 操作表 view) — they are
        # deliberately different orderings (R-USSHORT-BATCH4-SELECTION-TRACE-AND-RECALL-CLOSURE-GAP).
        7: _rows_section(["%s core_score=%s rank=%s %s" % (r.get("ticker"),
                          _num((r.get("selection_record") or {}).get("core_score")),
                          _num((r.get("selection_record") or {}).get("selection_rank")), r.get("final_action"))
                          for r in candidates], "Top15 选股"),
        8: _rows_section(["%s 观察(%s)" % (r.get("ticker"), r.get("observe_reason_type")) for r in observes], "观察池"),
        9: exclusion_lines,
        10: _as_lines(report_context["risk_downgrade_note"], "risk_downgrade_note"),
        # §3.7 provider health is the INJECTED fixture's self-report, NOT a real provider call — an offline run
        # must never describe it as operationally 权威 clean (R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP).
        11: offline_s11,
        12: lifecycle_lines,
        # §13 不 clean 项 ALWAYS leads with the non-operational offline limitation (so an offline run can never
        # render the misleading “本周无不 clean 项” / operational-clean surface), then any coverage-non-full rows.
        13: offline_s13,
    }
    report_data = {"banner": banner, "lifecycle_reminder_count": {"section_1": due_count, "section_12": due_count},
                   "sections": sections, "run_origin": run_origin, "offline_honesty": offline_honesty,
                   "run_status": run_status}
    # self-check the structured offline invariants (single source) before rendering — the private-write consumer
    # re-runs the SAME assertion, so the builder's output and the persistence boundary cannot drift.
    assert_offline_report_invariants(report_data, run_origin)
    return {"weekly_report_md": render_weekly_report(report_data), "report_data": report_data}
