# -*- coding: utf-8 -*-
"""US-short weekend-pipeline §11.2 weekly_report assembly — batch4 slice 4d-ii-m2 (report_data 装配 + render).

Design authority: docs/us_short_system_design.md §11.2 (周报 13 节 + 诚实横幅①②③④⑤ + price_clock + lifecycle 数量对账)
/ §11.1 (周报从机器层渲染) / §13 (lifecycle 提醒) / §12 (ship-gate) / §18.2 batch4 slice 4d.

The post-pass after 4d-ii-k (machine record) + 4d-ii-l (lifecycle eval) + 4d-ii-m1 (action_table projection). It
ASSEMBLES the §11.2 `report_data` (the 13 sections + the honest banner ①②③④⑤ + the lifecycle-count reconcile)
and renders it via the content-agnostic `us_short_weekly_report_renderer.render_weekly_report`. It DERIVES what the
machine layer + lifecycle eval own, WIRES the batch-3 §11.2 formatters, and takes the genuinely non-derivable
inputs (price_clock, the editorial sections, provider health, exclusion / hot-excluded / coverage raw inputs) from
an injected `report_context` (batch4 offline fixture; batch5 fills it real behind the same seam):

  * banner ① true/false observe split  ← machine-record observe rows (aggregate_observe_split → render);
  * banner ④ price_clock (ALWAYS shown) ← report_context (validated by validate_price_clock + the renderer);
  * banner ③ ship-gate + matured lifecycle count ← report_context ship_gate note + L readiness;
  * banner ⑤ hot_excluded notice ← exclusion_data["hot_excluded"] via build_exclusion_summary(...)["public"],
    then render_hot_excluded_banner — the SINGLE source the §9 detail also uses (banner count == §11.4 detail,
    §18.1 #19; there is NO separate report_context hot-excluded summary input);
  * banner ② macro_cluster ← report_context (optional; omitted when blank);
  * §11.5 持仓覆盖诚实度 (in §6) + §9 剔除摘要 (§11.4) ← report_context coverage / exclusion inputs via formatters;
  * §12 字段·模块生命周期提醒 + the §11.2 lifecycle-count reconcile ← L readiness due scan;
  * the row sections (5 操作表 / 6 持仓复核 / 7 Top15 / 8 观察池) ← the flattened §11.3 machine rows (slice m1).

Consumer-validation at the boundary (the recurring batch4 lesson — a stage that RE-EMITS official output must
value-validate the inputs it now owns): `report_context` is CLOSED-WORLD (exact key set), `lifecycle_result` is
re-validated for shape, the machine record is flattened via the m1 §10/§6 gate, and the formatters / the renderer
re-validate their own inputs (single source). Pure/offline; no provider/live/network; no broker/auto-order; no
A-share crossing.
"""
from __future__ import annotations

from engine.us_short_coverage_honesty import build_row_coverage, render_coverage_section
from engine.us_short_exclusion_summary import build_exclusion_summary, render_exclusion_section
from engine.us_short_hot_excluded import render_hot_excluded_banner
from engine.us_short_lifecycle_readiness import LifecycleReadinessError, _assert_readiness
from engine.us_short_observe_split import aggregate_observe_split, render_observe_split
from engine.us_short_price_clock import validate_price_clock
from engine.us_short_weekend_action_table import flatten_machine_record
from engine.us_short_weekly_report_renderer import render_weekly_report

# the genuinely non-machine / non-lifecycle inputs the §11.2 assembly needs (closed-world — an unknown / missing
# key fails closed, so a section can never silently render blank from a forgotten input). batch4 = offline fixture.
# NOTE: hot_excluded is NOT a separate key — its banner ⑤ is derived from exclusion_data["hot_excluded"] (the
# SINGLE source) so the §11.2 banner count can never disagree with the §11.4 exclusion detail (§18.1 #19).
_REPORT_CONTEXT_KEYS = frozenset({
    "price_clock", "exclusion_data", "coverage_inputs", "account_risk_note",
    "theme_opportunity_state", "core_conclusion", "risk_downgrade_note", "provider_health_note",
    "macro_cluster_banner", "ship_gate_note",
})
_HOLDING_SOURCES = frozenset({"holding_in_top15", "holding_pass2_only", "holding_account_only"})
_OBSERVE, _BUILD = "观察", "建仓"


class WeekendReportError(Exception):
    """The injected machine record / lifecycle result / report_context is malformed (fail-closed before render)."""


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
    if not (isinstance(rc, dict) and set(rc) == _REPORT_CONTEXT_KEYS):
        raise WeekendReportError(
            f"report_context 顶层键须恰为 {sorted(_REPORT_CONTEXT_KEYS)}（closed-world）: {sorted(rc) if isinstance(rc, dict) else rc!r}")


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


def build_weekly_report(machine_record, lifecycle_result, *, report_context):
    """4d-ii-m2 §11.2 weekly_report assembly + render.

    machine_record = the 4d-ii-k `assemble_machine_record` output (flattened here via slice m1 for the §11.3 rows).
    lifecycle_result = the 4d-ii-l `run_lifecycle_eval_stage` output {decision_date, readiness, banner}.
    report_context = the injected closed-world non-derivable inputs (price_clock + the editorial sections +
        provider health + exclusion / hot-excluded / coverage raw inputs); batch4 offline fixture, batch5 real.

    Returns {"weekly_report_md": <markdown str>, "report_data": <the assembled §11.2 report_data dict>}. Raises
    WeekendReportError on a malformed machine record / lifecycle result / report_context (and the formatters /
    renderer raise their own typed errors on a malformed formatter input / a §11.2 render-invariant violation —
    incomplete price_clock, lifecycle-count mismatch, a section without content)."""
    _validate_report_context(report_context)
    _validate_lifecycle_result(lifecycle_result)
    # flatten through the m1 §10/§6 gate (re-validates the machine record + projects the §11.3 columns).
    flat = flatten_machine_record(machine_record)
    rows = flat["rows"]
    # §2.1 / §11: reconcile ONE canonical decision_date across every official-report artifact before rendering,
    # so the report can never stitch rows / lifecycle / price clock / exclusions from different weeks.
    _reconcile_decision_date(flat.get("as_of"), report_context["price_clock"], lifecycle_result,
                             report_context["exclusion_data"])
    readiness = lifecycle_result["readiness"]
    due_count = readiness["due_count"]

    # --- row groups from the flattened §11.3 machine rows ---
    builds = [r for r in rows if r.get("final_action") == _BUILD]
    observes = [r for r in rows if r.get("final_action") == _OBSERVE]
    holdings = [r for r in rows if r.get("row_source") in _HOLDING_SOURCES]
    candidates = [r for r in rows if r.get("row_source") == "top15_candidate"]
    actionable = [r for r in rows if r.get("final_action") not in (_OBSERVE,)]
    regime_value = rows[0].get("market_risk_regime") if rows else None   # run-level regime, carried per-row by K

    # §9 exclusion summary built FIRST (build_exclusion_summary fully validates exclusion_data incl. its
    # hot_excluded) so the banner ⑤ + the §11.4 detail are ONE source — their hot counts cannot disagree (§18.1 #19).
    exclusion_public = build_exclusion_summary(report_context["exclusion_data"])["public"]
    exclusion_lines = render_exclusion_section(exclusion_public)

    # --- honest banner (① observe split derived; ②③⑤ via formatter / lifecycle / context; ④ price_clock) ---
    observe_split = aggregate_observe_split([r.get("observe_reason_type") for r in observes])
    price_clock = report_context["price_clock"]
    validate_price_clock(price_clock)   # §21 gate also re-run by the renderer; fail clear here too
    banner = {
        "price_clock": price_clock,                                                       # ④ always shown
        "true_false_observe_split": render_observe_split(observe_split),                  # ①
        "ship_gate_progress": "%s | lifecycle 达标(升级可评估) %d 项"                       # ③
                              % (_as_lines(report_context["ship_gate_note"], "ship_gate_note")[0],
                                 len(readiness["upgrade_eligible_items"])),
        # ⑤ derived from the SAME validated exclusion public summary the §9 detail uses (single source) — so the
        # §11.2 banner hot count can never disagree with the §11.4 exclusion detail (§18.1 #19).
        "hot_excluded_notice": render_hot_excluded_banner(
            {"public_heat_count": exclusion_public["hot_excluded_public_heat_count"], "holdings": []}),
    }
    macro = report_context["macro_cluster_banner"]
    if isinstance(macro, str) and macro.strip():
        banner["macro_cluster_warning"] = macro.strip()                                   # ② (optional)

    # --- §11.5 coverage (in §6) via the batch-3 formatter (self-validates each record) ---
    coverage_inputs = report_context["coverage_inputs"]
    if not isinstance(coverage_inputs, list):
        raise WeekendReportError("report_context.coverage_inputs 须为 list")
    coverage_records = []
    for ci in coverage_inputs:
        if not (isinstance(ci, dict) and set(ci) == {"row_source", "data_checks"}):
            raise WeekendReportError(f"coverage_inputs 行须为 {{'row_source','data_checks'}}: {ci!r}")
        coverage_records.append(build_row_coverage(ci["row_source"], ci["data_checks"]))
    coverage_lines = render_coverage_section(coverage_records)
    not_clean = [c for c in coverage_records if c["coverage_status"] != "full"]   # §13 不 clean 项 = 覆盖非 full

    # --- §12 lifecycle reminders + the §11.2 count reconcile (section 1 == section 12) ---
    lifecycle_lines = (["本周 %d/%d 个 §13.1 校准项达到复审线: %s"
                        % (due_count, readiness["total_items"], "、".join("#%d" % n for n in readiness["due_items"])),
                        "升级可评估(§12.2 margin 已冻): %s; 升级须用户决定、绝不自动切生产"
                        % ("、".join("#%d" % n for n in readiness["upgrade_eligible_items"]) or "无")]
                       if due_count else ["本周无 §13.1 校准项达到复审线 (0/%d)" % readiness["total_items"]])

    sections = {
        1: "本周运行状态: decision_date=%s; 建仓 %d / 观察 %d / 持仓 %d / 候选 %d; lifecycle 提醒 %d 项"
           % (price_clock["decision_date"], len(builds), len(observes), len(holdings), len(candidates), due_count),
        2: _as_lines(report_context["account_risk_note"], "account_risk_note"),
        3: ["市场环境 两轴: market_risk_regime=%s / theme_opportunity_state=%s"
            % (regime_value or "·",
               _as_lines(report_context["theme_opportunity_state"], "theme_opportunity_state")[0])],
        4: _as_lines(report_context["core_conclusion"], "core_conclusion"),
        5: _rows_section([_one_glance(r) for r in actionable], "最终操作表"),
        6: _rows_section([_one_glance(r) for r in holdings], "当前持仓复核") + coverage_lines,
        7: _rows_section(["%s core_score=%s rank=%s %s" % (r.get("ticker"),
                          _num((r.get("score") or {}).get("core_score") if isinstance(r.get("score"), dict) else None),
                          _num(r.get("action_rank")), r.get("final_action")) for r in candidates], "Top15 选股"),
        8: _rows_section(["%s 观察(%s)" % (r.get("ticker"), r.get("observe_reason_type")) for r in observes], "观察池"),
        9: exclusion_lines,
        10: _as_lines(report_context["risk_downgrade_note"], "risk_downgrade_note"),
        11: _as_lines(report_context["provider_health_note"], "provider_health_note"),
        12: lifecycle_lines,
        13: (["本周 %d 行覆盖非 full（partial/restricted/blocked），明细见 §6 持仓覆盖诚实度节" % len(not_clean)]
             if not_clean else ["本周无不 clean 项（机器记录已过 §10 no-dangling 校验、覆盖全 full）"]),
    }
    report_data = {"banner": banner, "lifecycle_reminder_count": {"section_1": due_count, "section_12": due_count},
                   "sections": sections}
    return {"weekly_report_md": render_weekly_report(report_data), "report_data": report_data}
