#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short 周末 pipeline(批②).

把已审过的各块串成一次周末跑:EGS top-N 候选(analysis_input.json) → Slice A overlay(eligible/
crowding) → IV feed(252d 分位,市场级) → Phase 5 引擎(逐票 M6.7) → 一份周报(per-stock M6.7)。

**消费方必须校验(关闭 register P2 consumer-validation):** 读 IV feed 后调
`validate_feed_summary_consistency`;每张 M6.7 调 `validate_m67_consistency` + schema。
纯函数(normalize_candidate / build_weekly_report / validate_weekly_report)合成 fixture 可测;
真实价格抓取(前复权日线)+ 读 artifacts 在薄 main(执行期授权)。

边界:非 production、不真钱、不接券商、不自动下单;A-short 仍 risk_filter_only,M6.7 为辅助建议
非验证 alpha。不动 egs_main / V14.2。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure the project root is importable when run directly as `python runners\<this>.py`
# (sys.path[0] is then runners/, so the `from runners.*` imports in main() would fail).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402

SCHEMA_NAME = "a_short_weekly_report"
SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schemas", "a_short_weekly_report.schema.json")
M67_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "schemas", "a_short_m67_report.schema.json")
OVERLAY_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "schemas", "a_short_theme_overlay_comparison.schema.json")
ACCOUNT_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "schemas", "a_short_account_state.schema.json")


def _is_valid_date(s) -> bool:
    from datetime import datetime
    try:
        datetime.strptime(str(s), "%Y%m%d")
        return True
    except ValueError:
        return False


def _date_leq_as_of(value, as_of: str, field: str) -> None:
    if value in (None, ""):
        return
    if not _is_valid_date(value):
        raise SystemExit(f"[FATAL] --account {field}={value!r} 不是合法 YYYYMMDD")
    if str(value) > str(as_of):
        raise SystemExit(f"[FATAL] --account {field}={value} > --as-of {as_of}(未来状态,拒跑)")


def validate_account_state(account: dict, as_of: str) -> dict:
    """Validate the manual account/position state consumed by weekly M6.7.

    This is deliberately a user-maintained local JSON state. It records cash, current holdings,
    Rule12 portfolio-circuit status, and Rule13 per-stock re-entry cooldowns; it never connects to
    brokers or updates itself from live accounts.
    """
    if not isinstance(account, dict):
        raise SystemExit(f"[FATAL] --account 须为 JSON object, got {type(account).__name__}")
    with open(ACCOUNT_SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    try:
        jsonschema.validate(account, schema)
    except jsonschema.ValidationError as exc:
        path = ".".join(str(p) for p in exc.absolute_path) or "<root>"
        raise SystemExit(f"[FATAL] --account schema invalid at {path}: {exc.message}") from exc
    if str(account.get("as_of")) != str(as_of):
        raise SystemExit(f"[FATAL] --account as_of {account.get('as_of')} != --as-of {as_of}(账户状态错批/陈旧/未来)")

    seen_pos = set()
    for idx, pos in enumerate(account.get("positions") or []):
        code = str(pos.get("ts_code"))
        if code in seen_pos:
            raise SystemExit(f"[FATAL] --account positions 含重复 ts_code {code}")
        seen_pos.add(code)
        _date_leq_as_of(pos.get("entry_date"), as_of, f"positions[{idx}].entry_date")
        _date_leq_as_of(pos.get("last_exit_date"), as_of, f"positions[{idx}].last_exit_date")

    r12 = account.get("rule12") or {}
    _date_leq_as_of(r12.get("triggered_at"), as_of, "rule12.triggered_at")
    if r12.get("cooldown_until") is not None and not _is_valid_date(r12.get("cooldown_until")):
        raise SystemExit(f"[FATAL] --account rule12.cooldown_until={r12.get('cooldown_until')!r} 不是合法 YYYYMMDD")
    if r12.get("status") == "active_cooldown" and str(r12.get("cooldown_until") or "") < str(as_of):
        raise SystemExit("[FATAL] --account rule12 active_cooldown 但 cooldown_until 已早于 as_of;请先更新为 recovery_1/inactive")

    seen_cd = set()
    for idx, cd in enumerate(account.get("rule13_cooldowns") or []):
        code = str(cd.get("ts_code"))
        if code in seen_cd:
            raise SystemExit(f"[FATAL] --account rule13_cooldowns 含重复 ts_code {code}")
        seen_cd.add(code)
        _date_leq_as_of(cd.get("exit_date"), as_of, f"rule13_cooldowns[{idx}].exit_date")
        if cd.get("cooldown_until") is not None and not _is_valid_date(cd.get("cooldown_until")):
            raise SystemExit(f"[FATAL] --account rule13_cooldowns[{idx}].cooldown_until 非合法 YYYYMMDD")
        if cd.get("status") == "active_cooldown" and str(cd.get("cooldown_until") or "") < str(as_of):
            raise SystemExit(f"[FATAL] --account Rule13 {code} active_cooldown 已过期;请更新为 pending_recheck/cleared_for_reentry")
    return account


def stateful_risk_for_candidate(account: dict | None, ts_code: str, as_of: str) -> dict:
    """Derive per-candidate Rule12/Rule13/position context from the validated account state."""
    if not account:
        return {}
    positions = {str(p.get("ts_code")): p for p in (account.get("positions") or [])}
    cooldowns = {str(c.get("ts_code")): c for c in (account.get("rule13_cooldowns") or [])}
    position = positions.get(str(ts_code))
    has_position = position is not None
    ctx = {
        "position_state": "held" if has_position else "flat",
        "position": position,
        "rule12": {"status": (account.get("rule12") or {}).get("status", "inactive")},
        "rule13": {"status": "none"},
        "size_multiplier": 1.0,
        "reasons": [],
        "as_of": as_of,
    }

    r12 = account.get("rule12") or {"status": "inactive"}
    if r12.get("status") == "active_cooldown":
        ctx["rule12"] = {
            "status": "active_cooldown",
            "cooldown_until": r12.get("cooldown_until"),
            "reason": r12.get("reason"),
            "new_entry_blocked": True,
            "existing_position_only": has_position,
        }
        ctx["reasons"].append("Rule12 active_cooldown:block_new_entries")
    elif r12.get("status") == "recovery_1":
        mult = r12.get("recovery_position_multiplier")
        if not isinstance(mult, (int, float)) or mult <= 0 or mult > 1:
            mult = 0.5
        ctx["rule12"] = {
            "status": "recovery_1",
            "cooldown_until": r12.get("cooldown_until"),
            "reason": r12.get("reason"),
            "new_entry_blocked": False,
            "recovery_position_multiplier": float(mult),
        }
        ctx["size_multiplier"] = min(ctx["size_multiplier"], float(mult))
        ctx["reasons"].append(f"Rule12 recovery_1:size_multiplier={float(mult):.2f}")

    cd = cooldowns.get(str(ts_code))
    if cd and not has_position:
        ctx["rule13"] = dict(cd)
        status = cd.get("status")
        if status == "active_cooldown":
            ctx["rule13"]["reentry_blocked"] = True
            ctx["reasons"].append("Rule13 active_cooldown:block_reentry")
        elif status == "pending_recheck":
            needs_catalyst = bool(cd.get("requires_new_catalyst")) and not bool(cd.get("new_catalyst_confirmed"))
            needs_m4 = bool(cd.get("requires_m4_recheck")) and not bool(cd.get("m4_recheck_passed"))
            if needs_catalyst or needs_m4:
                ctx["rule13"]["reentry_blocked"] = True
                ctx["reasons"].append("Rule13 pending_recheck:block_reentry")
            else:
                mult = cd.get("max_reentry_position_pct") if isinstance(cd.get("max_reentry_position_pct"), (int, float)) else 0.5
                ctx["size_multiplier"] = min(ctx["size_multiplier"], float(mult))
                ctx["reasons"].append(f"Rule13 pending_recheck:size_multiplier={float(mult):.2f}")
        elif status == "cleared_for_reentry":
            mult = cd.get("max_reentry_position_pct") if isinstance(cd.get("max_reentry_position_pct"), (int, float)) else 0.5
            ctx["size_multiplier"] = min(ctx["size_multiplier"], float(mult))
            ctx["reasons"].append(f"Rule13 cleared_for_reentry:size_multiplier={float(mult):.2f}")
    elif cd and has_position:
        ctx["rule13"] = {"status": "not_applicable_existing_position", "source_status": cd.get("status")}
    return ctx


def _load_account_consistency_warnings(account_path: str) -> dict:
    """持仓恒列入 S1: best-effort 读 4.3 转换器的 lineage 旁产物(`<account 主名>_lineage.json`,与
    account_state.json 同目录),取 4.3-D `consistency_warnings` → {ts_code: message}。旁产物缺失/坏
    → {}(advisory,绝不阻断周报)。"""
    if not account_path:
        return {}
    try:
        p = Path(account_path)
        lineage_path = p.with_name(p.stem + "_lineage.json")
        if not lineage_path.is_file():
            return {}
        with open(lineage_path, encoding="utf-8") as f:
            data = json.load(f)
        out = {}
        for w in (data.get("consistency_warnings") or []):
            code = str(w.get("ts_code") or "")
            if code:
                out[code] = str(w.get("message") or "")
        return out
    except Exception:
        return {}


def _build_holdings(acct, cand_codes, as_of, price_provider, iv_pct, account, regime,
                    regime_fallback, price_data_through, egs_full=None, iv_value=None, hv_value=None,
                    semantic_provider=None, web_llm_provider=None):
    """持仓恒列入 S1: 为"持仓 ∖ top-N"构造 M6.7 待分析行(Tier 路由)。**不改 egs_main / 选股 / 语义 /
    user-stop**。返回 (holding_normalized, holding_meta, manual_review):
    - Tier-2(在 `egs_full`): 复用 egs_full 的 EGS 分/风险;**现价取 price provider 最新 bar**(非 egs_full
      快照,见 close 覆盖);`row_source=account_position_egs_full`。
    - Tier-3(不在 `egs_full`,粗筛未覆盖): 仅价格/技术 + 账户,EGS 标未覆盖;`row_source=account_position_only`。
    - **coverage_status 一律 partial**:S1 对注入持仓**不跑语义/新闻**,故没有 full 的注入持仓(full 仅
      top-N 候选行)。Tier-2 vs Tier-3 的区别在 `row_source`,**不在** coverage;EGS『未核查』渲染覆盖只对 Tier-3。
    - 无价/停牌/价格陈旧(最新 bar != price_data_through): **旁路候选价格门**(绝不中止整轮、不参与候选一致性
      判定),入 manual_review,**不伪造"持有"**。
    4.2 S2: 持仓 semantic 经 semantic_provider/web_llm_provider 注入(全持仓覆盖、绕 Top15 cap);
    provider 为 None → semantic=None(S1 向后兼容,build_holding_report 保持「未核查」)。"""
    from engine.a_short_egs_full_adapter import load_egs_full, egs_full_row_to_candidate
    positions = [p for p in (acct.get("positions") or []) if str(p.get("ts_code")) not in cand_codes]
    if not positions:
        return [], {}, []
    if egs_full is None:                      # 测试可注入;生产从 A-EGS/Result/egs_full_<as_of>.csv 读
        egs_full = load_egs_full(as_of)
    holding_normalized, holding_meta, manual_review = [], {}, []
    for p in positions:
        code = str(p.get("ts_code"))
        series, latest = _price_provider_result(price_provider, code, as_of)
        if len(series) < MIN_PRICE_OBS or not latest or str(latest) != str(price_data_through):
            reason = (f"无价/停牌(价格序列不足 < {MIN_PRICE_OBS} 交易日)"
                      if (len(series) < MIN_PRICE_OBS or not latest)
                      else f"价格最新 bar {latest} != 本周决策价格日 {price_data_through}(陈旧/停牌)")
            manual_review.append({"ts_code": code, "name": str(p.get("name") or ""), "reason": reason})
            continue
        row = egs_full.get(code)
        if row is not None:
            cand = egs_full_row_to_candidate(row)                 # Tier-2: 复用本轮 EGS 评分/风险
            rs = "account_position_egs_full"
        else:
            cand = {"ts_code": code, "name": str(p.get("name") or "")}  # Tier-3: 粗筛未覆盖,无 EGS 数据
            rs = "account_position_only"
        # 价格钟一致性(R-ASHORT-HOLDINGS-S1-TIER2-EGSFULL-CLOSE-PRICE-CLOCK-DRIFT):现价**一律取本次
        # price provider 的最新已结算 bar**,绝不让 egs_full 快照 close 当现价权威(否则 Tier-2 现价与
        # price_data_through 漂移)。egs_full 只作 EGS 分/风险 lineage,不作现价。
        cand["quote"] = {"close": series[-1].get("close")}
        n = normalize_candidate(cand, series, None, iv_pct, account, regime,
                                regime_fallback=regime_fallback,
                                stateful_risk=stateful_risk_for_candidate(acct, code, as_of),
                                semantic=(semantic_provider(code) if semantic_provider else None),
                                semantic_web_llm=(web_llm_provider(code) if web_llm_provider else None),
                                iv_value=iv_value, hv_value=hv_value)
        if rs == "account_position_only":     # Tier-3: 走 build_holding_report(不跑 EGS 风险分类、不伪造 veto)
            n["egs_coverage"] = "uncovered"
        holding_normalized.append(n)
        # S1 对**所有**注入持仓:semantic/news 层未跑 → coverage 一律 partial(绝不伪装 full/已核查);
        # Tier-2 与 Tier-3 的区别在 row_source(EGS 复用 vs 粗筛未覆盖),不在 coverage。
        holding_meta[code] = {"row_source": rs, "coverage_status": "partial"}
    return holding_normalized, holding_meta, manual_review


def normalize_candidate(cand: dict, price_series: list, overlay_row: dict, iv_pct,
                        account: dict, regime: str, industry_trend: str = "neutral",
                        llm_enrichment=None, observe_only=None, semantic=None,
                        semantic_web_llm=None, regime_fallback=None, stateful_risk=None,
                        iv_value=None, hv_value=None) -> dict:
    """把一个 EGS analysis_input 候选 + 价格序列 + overlay 行 + 市场级 IV 分位 + 账户/环境
    归一化成 Phase 5 引擎输入。字段缺失 → 引擎按保守/observe 处理。"""
    d = cand.get("derived_flags", {}) or {}
    ev = cand.get("event_risk", {}) or {}
    hr = ev.get("holder_reduction", {}) or {}
    delist = ev.get("delisting", {}) or {}
    susp = ev.get("suspension", {}) or {}
    liq = cand.get("liquidity", {}) or {}
    sc = cand.get("scores", {}) or {}
    return {
        "ts_code": cand.get("ts_code"), "name": cand.get("name"),
        "close": (cand.get("quote") or {}).get("close"),
        "price_series": list(price_series or []),
        "esp_score": sc.get("esp_score"), "l4_score": sc.get("l4_score"),
        "egs_score": sc.get("final_score"),   # EGS 质量总分(M6.7 渲染并列展示,与风控星级区分)
        "overlay": {"eligible": bool((overlay_row or {}).get("eligible")),
                    "crowding_hit": bool((overlay_row or {}).get("crowding_hit"))},
        "industry_trend": industry_trend,
        # 真实 EGS analysis_input 契约:derived_flags.{is_lock,is_breakout,has_crash_veto,
        # overheat_flag,chasing_high,vol_confirm,hard_veto};suspension 在 event_risk.suspension.is_suspended。
        # vol_confirm 可选:EGS 量能旁证(近5日上涨日额>下跌日额),仅进 EGS l4_score 评分;**不再门控 M6.7 突破**
        # (#6-ii:突破改由 is_breakout=v14.2 spec[站稳MA10 + 当日量>5日均量×1.2]触发,见 a_short_phase5_engine.entry_type)。
        "derived": {"overheat": bool(d.get("overheat_flag")), "chasing_high": bool(d.get("chasing_high")),
                    "breakout": bool(d.get("is_breakout")), "vol_confirm": bool(d.get("vol_confirm")),
                    "crash_veto": bool(d.get("has_crash_veto")), "limit_locked": bool(d.get("is_lock")),
                    "suspended": bool(susp.get("is_suspended")), "hard_veto": bool(d.get("hard_veto"))},
        # regulatory_legacy_vetoed 恒 False:EGS Stage3 CNINFO REGULATOR-VETO 在上游已剔除被否票
        # (§10),analysis_input 里的票均已过 cninfo;契约无顶层 veto 字段,pipeline 不再二次硬杀。
        "event": {"holder_reduction_active": bool(hr.get("active_plan")),
                  "st_or_delisting": bool(delist.get("st_flag") or delist.get("delisting_warning")),
                  "regulatory_legacy_vetoed": False},
        "liquidity": {"avg_amount_5d": liq.get("avg_amount_5d"), "avg_amount_20d": liq.get("avg_amount_20d")},
        "iv": {"iv_percentile_252d": iv_pct, "iv_value": iv_value, "hv_value": hv_value},
        "market_regime": regime,
        "regime_fallback": dict(regime_fallback or {}),
        "account": account or {},
        "portfolio": {},
        "stateful_risk": dict(stateful_risk or {}),
        "observe_only": list(observe_only or []),
        "llm_enrichment": list(llm_enrichment or []),
        # 语义官方层(Slice 1):official_structured dict {status, events[severity], had_pit_announcements}
        # 或 None(无输入→引擎按 unknown 中性处理)。Phase5 引擎据此融进 M6.7(证据齐全[非空URL]high→否决;缺URL high·medium→待核)。
        "semantic": semantic,
        # 语义 web/LLM 层(Slice 2):{"web_llm": {...}, "sources": [...]} 或 None(无输入→引擎按 unknown 中性)。
        # DeepSeek 判官产出;引擎据此 downgrade(有 sources 证据的 risk/headwind;**绝不 hard_veto**);非法→中性化。
        "semantic_web_llm": semantic_web_llm,
    }


def _demote_build_to_observe(report: dict, rank: int) -> None:
    """#3:某建仓票全局现金分配后不足一手/最小金额 → 转「观察」。table/machine action 同步、交易字段全 null、
    原拟 plan 留 machine.diagnostic_raw_plan(诊断)、advice 说明。须过 validate_m67_consistency 的观察分支(交易字段全 null)。"""
    tbl = report["m67"]["table"]
    es = report["machine"]["entry_exit_size_star"]
    es["diagnostic_raw_plan"] = es.get("plan")     # 原拟建仓 plan 留诊断(machine 为 loose object,允许)
    es["plan"], es["action"] = None, "观察"
    es["reject_reason"] = "组合现金分配后不足一手/最小金额"
    tbl["操作"] = "观察"
    for k in ("股数", "入", "盈一", "盈二", "损"):
        tbl[k] = None
    tbl["触发条件"] = "组合现金分配后不足一手/最小金额(原拟建仓价位见 machine.diagnostic_raw_plan)"
    report["m67"]["精简结论区"]["操作建议"] = (
        f"组合现金分配后不足一手/最小金额 → 转观察(分配排序第 {rank};原拟建仓价位见 machine.diagnostic_raw_plan)。本周不建仓。")


def _allocate_cash(reports: list, available_cash) -> dict:
    """#3 全局现金分配(价格提案 §4 + §11.3/11.4):多只建仓按**区间上沿 entry_high**(最不利价)统一消耗
    available_cash,确定性排序;不足一手/最小金额 → 转观察。**原地改 reports(只动建仓票)**;返回 weekly 现金摘要 | None。
    只 re-rank 建仓,不 rescue hard veto、不把观察/否决变建仓、不碰持仓/Rule12·13。"""
    from runners.a_short_phase5_engine import MIN_SHARES, MIN_AMOUNT
    if available_cash is None or available_cash <= 0:
        return None
    builds = [(i, r) for i, r in enumerate(reports) if r["m67"]["table"]["操作"] == "建仓"]

    def _key(ir):
        i, r = ir
        es = r["machine"]["entry_exit_size_star"]; plan = es.get("plan") or {}
        return (-(es.get("star") or 0), -(r["m67"]["table"].get("EGS分") or 0),
                -(plan.get("rr_at_entry_high") or 0.0), -(plan.get("avg_amount_5d") or 0.0),
                i, str(r.get("ts_code", "")))     # original_topN_rank=i;ts_code 末位 tie-break 保确定性

    remaining, allocated_total = float(available_cash), 0.0
    for rank, (i, r) in enumerate(sorted(builds, key=_key), start=1):
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        eh, raw = plan["entry_high"], plan["shares"]
        affordable = int(remaining // eh // 100) * 100 if eh > 0 else 0
        allocated = min(raw, affordable)
        if allocated < MIN_SHARES or allocated * eh < MIN_AMOUNT:
            _demote_build_to_observe(r, rank)        # 不足 → 转观察(不输出按上沿买不起的建仓)
            continue
        cost = round(allocated * eh, 2)              # 2dp:与展示/审计的 cash_budget_used 同口径,摘要可精确对账
        remaining -= cost; allocated_total += cost
        plan["raw_shares"], plan["shares"], plan["allocated_shares"] = raw, allocated, allocated
        plan["cash_budget_used"], plan["cash_allocation_rank"] = cost, rank
        r["m67"]["table"]["股数"] = allocated         # table 同步 plan(过 validator 建仓一致性)
        if allocated < raw:
            r["m67"]["精简结论区"]["操作建议"] += f"(组合现金分配:股数由 {raw} 降至 {allocated},占用现金 {cost})"
    return {"available_cash_start": round(float(available_cash), 2),
            "allocated_cash_total": round(allocated_total, 2), "remaining_cash": round(remaining, 2)}


# 4.2 Round2: analysis_input.universe_summary.excluded_counts 键 → exclusion_summary by_reason 元信息
# (全部 L0 上游过滤 = production_hard_veto;counts-only → public_tracked,不暴露个股/持仓)。
_EXCL_REASON_META = {
    "holder_reduction_veto_10d": ("holder_reduction_veto_10d", "l0_filter", "disclosure_date", "10日减持"),
    "unlock": ("share_float_unlock", "l0_filter", "disclosure_date", "大额解禁"),
    "suspended": ("suspended", "l0_filter", "trade_date_window", "停牌"),
    "relisted": ("relisted", "l0_filter", "trade_date_window", "次新/relisted"),
}

# exclusion_summary.evidence_ref 的唯一受审 lineage key:builder 发射 + validator 精确校验共用单一来源,
# 防"乱写 value 仍过"。本轮 evidence 只支持 lineage_key(指向已消费的 analysis_input 派生 key);
# artifact_path 在真实产出可解析 artifact 前不开放(4.2.md §6.2/§10.2)。
_EXCL_EVIDENCE_LINEAGE_KEY = "analysis_input.universe_summary.excluded_counts"


def _build_exclusion_summary(excluded_counts: dict, as_of: str):
    """4.2 Round2: 把 analysis_input.universe_summary.excluded_counts(egs_main filter_l0 已记)转成周报
    批次级 exclusion_summary(counts-only, public_tracked;不暴露个股代码/持仓)。total==0 → None(无可报)。
    不改 egs_main、不抓数、不虚构个股行。**完整性 fail-closed**(R-ASHORT-GAP42-ROUND2):excluded_counts 是开放契约
    (analysis_input schema additionalProperties),任何 count>0 的未映射键 → raise(绝不静默丢一个上游过滤原因);
    新原因须先在 _EXCL_REASON_META 映射 stage/veto_class/pit_basis 后才能进摘要。"""
    excluded_counts = excluded_counts or {}
    _unknown = sorted(k for k, v in excluded_counts.items()
                      if int(v or 0) > 0 and k not in _EXCL_REASON_META)
    if _unknown:
        raise ValueError(f"exclusion_summary 完整性: 未映射的上游过滤原因(count>0) {_unknown} —— "
                         "须先在 _EXCL_REASON_META 映射 stage/veto_class/pit_basis(no-dangling fail-closed)")
    by_reason, parts, total = [], [], 0
    for key, (sf, stage, pit, label) in _EXCL_REASON_META.items():
        n = int(excluded_counts.get(key) or 0)
        if n <= 0:
            continue
        by_reason.append({"source_field": sf, "stage": stage, "veto_class": "production_hard_veto",
                          "count": n, "pit_basis": pit, "production_effect_enabled": True,
                          "privacy_class": "public_tracked"})
        parts.append(f"{label} {n} 只")
        total += n
    if total == 0:
        return None
    return {"as_of": str(as_of), "total_excluded": total, "by_reason": by_reason,
            "m67_text": "本轮上游过滤(无 M6.7 个股行,批次级): " + "、".join(parts) + "。",
            "evidence_ref": {"kind": "lineage_key",
                             "value": _EXCL_EVIDENCE_LINEAGE_KEY,
                             "as_of": str(as_of)}}


def build_weekly_report(normalized_list: list, as_of: str, generated_at: str,
                        iv_feed_ref: str = "", run_lineage: dict = None, available_cash=None) -> dict:
    from runners.a_short_phase5_engine import build_m67_report, build_holding_report
    # 持仓恒列入 S1: 标了 egs_coverage="uncovered" 的(Tier-3 粗筛未覆盖持仓)走 build_holding_report
    # (不跑 EGS 风险分类,避免在缺失数据上伪造 veto);其余(候选 / Tier-1 / Tier-2)走 build_m67_report。
    reports = [(build_holding_report(n, as_of, generated_at)
                if n.get("egs_coverage") == "uncovered" else build_m67_report(n, as_of, generated_at))
               for n in normalized_list]
    cash_summary = _allocate_cash(reports, available_cash)   # #3 全局现金分配(原地改建仓票:股数/分配字段;归零转观察)
    # run_lineage ties the consumed selection + IV feed + account/sizing status to this M6.7 artifact
    # (Slice 3b-2: selection 在 result/a_short、M6.7 在 research lane,靠此机器可读 lineage 绑定);
    # default = no-account observation-only,使直接 builder/测试仍 schema-valid。
    lineage = run_lineage if run_lineage is not None else {
        "analysis_input": "", "selection_bucket": "", "iv_feed": iv_feed_ref,
        "account_ref": "",
        "account_status": "absent", "sizing_mode": "observation_only_no_account",
        "price_freshness": {"mode": "strict_as_of", "run_date": None,
                            "accepted_prior_settled_date": None, "price_data_through": str(as_of)}}
    return {
        "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at, "as_of": as_of,
        "iv_feed_ref": iv_feed_ref, "n_stocks": len(reports), "reports": reports,
        "cash_allocation": cash_summary,
        "run_lineage": lineage,
        "boundary": {"production": False, "real_money": False,
                     "is_validated_alpha": False, "satisfies_ship_gate": False},
    }


def validate_weekly_report(weekly: dict, iv_feed_summary: dict) -> None:
    """关闭 P2:消费方校验它读入的 IV feed + 每张 M6.7。"""
    from datetime import datetime
    from runners.a_short_iv_feed_build import validate_feed_summary_consistency
    from runners.a_short_phase5_engine import validate_m67_consistency
    # weekly as_of 必须是合法日历日(空报告时也要校验;schema 的 ^\d{8}$ 不查历法,20260631 会漏过)
    try:
        datetime.strptime(str(weekly["as_of"]), "%Y%m%d")
    except ValueError:
        raise ValueError(f"weekly as_of {weekly['as_of']} 非合法日历日期")
    validate_feed_summary_consistency(iv_feed_summary)        # 读取方校验 feed(P2)
    # 跨-as_of PIT:feed 不得来自周报 as_of 之后(否则用了未来波动率)
    if str(iv_feed_summary.get("as_of")) > weekly["as_of"]:
        raise ValueError(f"IV feed as_of {iv_feed_summary.get('as_of')} 晚于周报 as_of {weekly['as_of']}(未来 feed)")
    fs = iv_feed_summary.get("series") or []
    if fs and str(fs[-1]["trade_date"]) > weekly["as_of"]:
        raise ValueError(f"IV feed 最新 trade_date {fs[-1]['trade_date']} 晚于周报 as_of {weekly['as_of']}(PIT 违规)")
    if weekly["n_stocks"] != len(weekly["reports"]):
        raise ValueError("n_stocks 与 reports 长度不一致")
    if any(b for b in weekly["boundary"].values()):
        raise ValueError("weekly boundary 必须全 false")
    rl = weekly.get("run_lineage") or {}
    # (account_status, sizing_mode) 是严格双态:恰为 (provided,sized) 或 (absent,observation_only_no_account)。
    # 任何其他配对——含矛盾的 (provided, observation_only_no_account)——都必须 raise,以免错标的 lineage 让
    # sizing-less 的「观察」被读成有账户支撑(或反之)。main 只会产出合法配对;此处兜住外部/手构的报告。
    if (rl.get("account_status"), rl.get("sizing_mode")) not in {
            ("provided", "sized"), ("absent", "observation_only_no_account")}:
        raise ValueError(
            f"run_lineage 配对非法 (account_status={rl.get('account_status')!r}, "
            f"sizing_mode={rl.get('sizing_mode')!r});须 (provided,sized) 或 (absent,observation_only_no_account)")
    # #3 lineage⟺cash_allocation 双向不变式(R-ASHORT-M67-PRICE-CASH-ALLOCATION-LINEAGE-GUARD):仅校验
    # (account_status,sizing_mode) 配对不够——还须把它绑死 cash_allocation,否则手构/refactor 的报告可声称
    # 账户定量(sized)却静默跳过全局现金分配(重开多股过度分配 bug),或声称无账户却带分配。main 永远一致;此处兜底。
    sized = (rl.get("account_status"), rl.get("sizing_mode")) == ("provided", "sized")
    ca = weekly.get("cash_allocation")
    if sized and not isinstance(ca, dict):
        raise ValueError("run_lineage=(provided,sized) 但 cash_allocation 非对象(sized 必有全局现金分配摘要)")
    if not sized and ca is not None:
        raise ValueError("run_lineage=(absent,observation_only_no_account) 但 cash_allocation 非 null(observation-only 不得有现金分配)")
    # 4.2 Round2: exclusion_summary 一致性(counts-only 批次级,可选;无则跳过)
    es = weekly.get("exclusion_summary")
    if es is not None:
        if es.get("as_of") != weekly["as_of"]:
            raise ValueError(f"exclusion_summary.as_of {es.get('as_of')} != 周报 as_of {weekly['as_of']}")
        br = es.get("by_reason") or []
        if any(int(r.get("count") or 0) <= 0 for r in br):
            raise ValueError("exclusion_summary.by_reason 含非正 count(零计数不入摘要)")
        ssum = sum(int(r.get("count") or 0) for r in br)
        if ssum != es.get("total_excluded"):
            raise ValueError(f"exclusion_summary total_excluded {es.get('total_excluded')} != Σby_reason {ssum}")
        if not es.get("m67_text"):
            raise ValueError("exclusion_summary 缺 m67_text(用户可见摘要)")
        ev = es.get("evidence_ref")
        # evidence_ref 必须真正绑到受审 lineage:本轮仅 lineage_key + 唯一受审 dotted path(_EXCL_EVIDENCE_LINEAGE_KEY),
        # 且 as_of==报告日期、run_lineage.analysis_input 非空。乱写 value 或 artifact_path 伪路径均拒(R-ASHORT-GAP42-ROUND2)。
        if not isinstance(ev, dict) or ev.get("kind") != "lineage_key":
            raise ValueError("exclusion_summary.evidence_ref 缺失/坏 kind(本轮仅 lineage_key;artifact_path 未实现,不开放)")
        if ev.get("value") != _EXCL_EVIDENCE_LINEAGE_KEY:
            raise ValueError(f"exclusion_summary.evidence_ref.value {ev.get('value')!r} != 受审 lineage key "
                             f"{_EXCL_EVIDENCE_LINEAGE_KEY!r}(不可解析/伪造)")
        if ev.get("as_of") != weekly["as_of"]:
            raise ValueError(f"exclusion_summary.evidence_ref.as_of {ev.get('as_of')} != 周报 as_of {weekly['as_of']}(证据陈旧)")
        if not ((weekly.get("run_lineage") or {}).get("analysis_input")):
            raise ValueError("exclusion_summary 存在但 run_lineage.analysis_input 为空(无源 artifact lineage,无法溯源)")
        # 4.2 第3轮 visibility exclusivity:同一 source_field 不能既是 row-level operation_impact 又是
        # batch_exclusion(同一风险同一运行只能一种可见性形态;若未来旁路使某 source 双落点[如 has_crash_veto
        # 旁路 score_l2 复活成候选行],此处 fail)。row-impact source_field 来自各 report 的 machine.operation_impact。
        _row_impact_fields = {imp.get("source_field")
                              for rep in weekly["reports"]
                              for imp in ((rep.get("machine") or {}).get("operation_impact") or [])}
        _excl_fields = {r.get("source_field") for r in (es.get("by_reason") or [])}
        _overlap = _row_impact_fields & _excl_fields
        if _overlap:
            raise ValueError(f"visibility exclusivity 违反:{sorted(_overlap)} 同时是 row operation_impact 和 "
                             "exclusion_summary batch_exclusion(同一风险同一运行只能一种可见性形态)")
    if sized:
        from runners.a_short_phase5_engine import MIN_SHARES
    seen, alloc_ranks, budget_sum = set(), [], 0.0       # audit-math:跨建仓累计,循环后对账 cash_allocation 摘要
    for rep in weekly["reports"]:
        if rep["as_of"] != weekly["as_of"]:
            raise ValueError("report.as_of 与周报 as_of 不一致")
        if rep["ts_code"] in seen:
            raise ValueError(f"周报含重复 ts_code {rep['ts_code']}")
        seen.add(rep["ts_code"])
        validate_m67_consistency(rep)                        # 逐票 §4 不变量
        if rep["m67"]["table"]["操作"] != "建仓":
            continue
        pl = (rep["machine"]["entry_exit_size_star"].get("plan") or {})
        ts = rep["ts_code"]
        if not sized:
            if pl.get("cash_allocation_rank") is not None:   # observation-only 反向:建仓不应带分配字段
                raise ValueError(f"observation-only 模式建仓 plan 不应带现金分配字段 cash_allocation_rank(ts={ts})")
            continue
        # #3 audit-math(R-ASHORT-M67-PRICE-CASH-ALLOCATION-AUDIT-MATH-GUARD):审计字段不仅须存在,还须**数值自洽**
        # ——否则伪造 allocated_shares/cash_budget_used/摘要仍能冒充"已做全局现金分配"。
        for fld in ("cash_allocation_rank", "cash_budget_used", "raw_shares", "allocated_shares", "shares", "entry_high"):
            if pl.get(fld) is None:
                raise ValueError(f"sized 模式建仓 plan 缺审计/定量字段 {fld}(ts={ts})")
        shares, eh = pl["shares"], pl["entry_high"]
        if not (pl["allocated_shares"] == shares == rep["m67"]["table"]["股数"]):
            raise ValueError(f"sized 建仓 allocated_shares/shares/table 股数 不一致(ts={ts})")
        if abs(pl["cash_budget_used"] - round(shares * eh, 2)) > 0.011:
            raise ValueError(f"sized 建仓 cash_budget_used != round(shares×entry_high,2)(ts={ts})")
        if not (pl["raw_shares"] >= pl["allocated_shares"] >= MIN_SHARES):
            raise ValueError(f"sized 建仓须 raw_shares>=allocated_shares>=MIN_SHARES(ts={ts})")
        rank = pl["cash_allocation_rank"]
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise ValueError(f"sized 建仓 cash_allocation_rank 须正整数(ts={ts})")
        alloc_ranks.append(rank)
        budget_sum += pl["cash_budget_used"]
    if sized:
        if len(alloc_ranks) != len(set(alloc_ranks)):
            raise ValueError("sized 建仓 cash_allocation_rank 重复(须唯一)")
        start, total, rem = ca.get("available_cash_start"), ca.get("allocated_cash_total"), ca.get("remaining_cash")
        if None in (start, total, rem):
            raise ValueError("cash_allocation 摘要字段缺失")
        if abs(total - round(budget_sum, 2)) > 0.011:
            raise ValueError("cash_allocation.allocated_cash_total != Σcash_budget_used")
        if abs(rem - (start - total)) > 0.011:
            raise ValueError("cash_allocation.remaining_cash != available_cash_start - allocated_cash_total")
        if rem < -0.011:
            raise ValueError("cash_allocation.remaining_cash 为负(超额分配)")
    # #1 除权除息提示一致性(schema 管类型/pattern;此处管历法 + 跨字段 + 范围:ex_date 合法日历日、
    # ex_date>=as_of、days_to_ex==ex_date−as_of、**days_to_ex<=EX_DIV_WINDOW_DAYS**、**ts_code 必属本周候选/持仓**。
    # advisory 但仍校验,防伪造/错算/越界/张冠李戴的提示混入周报。)
    from datetime import datetime as _dt
    _asd = _dt.strptime(weekly["as_of"], "%Y%m%d")
    _valid_codes = ({r["ts_code"] for r in weekly["reports"]}
                    | {h["ts_code"] for h in (weekly.get("holdings_manual_review") or [])})
    for n in (weekly.get("ex_div_notices") or []):
        if n["ts_code"] not in _valid_codes:
            raise ValueError(f"ex_div_notices ts_code {n['ts_code']} 不在本周候选/持仓集(张冠李戴)")
        try:
            _exd = _dt.strptime(n["ex_date"], "%Y%m%d")
        except ValueError:
            raise ValueError(f"ex_div_notices ex_date {n['ex_date']} 非合法日历日({n['ts_code']})")
        _days = (_exd - _asd).days
        if _days < 0:
            raise ValueError(f"ex_div_notices ex_date 早于 as_of({n['ts_code']})")
        if _days != n["days_to_ex"]:
            raise ValueError(f"ex_div_notices days_to_ex 与 ex_date−as_of 不一致({n['ts_code']})")
        if _days > EX_DIV_WINDOW_DAYS:
            raise ValueError(f"ex_div_notices 超出 {EX_DIV_WINDOW_DAYS} 日窗口(days_to_ex={_days};{n['ts_code']})")
    # 4.2 forward_events upcoming_events 一致性(advisory analysis-only;schema 管类型/pattern/enum,此处管历法+跨字段+PIT+范围+张冠李戴):
    # unknown_or_unavailable 必空 events;checked 每 event: ts_code∈候选/持仓、event_date 合法且 >=as_of、observed_at<=as_of(PIT)、
    # days_to_event==event_date−as_of、days_to_event<=window。复用上面的 _asd/_valid_codes/_dt。
    _ue = weekly.get("upcoming_events")
    if _ue is not None:
        if _ue.get("as_of") != weekly["as_of"]:
            raise ValueError(f"upcoming_events.as_of {_ue.get('as_of')} != 周报 as_of {weekly['as_of']}")
        _uevs = _ue.get("events") or []
        if _ue.get("status") == "unknown_or_unavailable" and _uevs:
            raise ValueError("upcoming_events status=unknown_or_unavailable 却带 events(unknown 不得带事件)")
        for _e in _uevs:
            if _e["ts_code"] not in _valid_codes:
                raise ValueError(f"upcoming_events ts_code {_e['ts_code']} 不在本周候选/持仓集(张冠李戴)")
            try:
                _evd = _dt.strptime(_e["event_date"], "%Y%m%d")
                _obs = _dt.strptime(_e["observed_at"], "%Y%m%d")
            except ValueError:
                raise ValueError(f"upcoming_events event_date/observed_at 非合法日历日({_e['ts_code']})")
            if _obs > _asd:
                raise ValueError(f"upcoming_events observed_at 晚于 as_of(非 PIT/look-ahead;{_e['ts_code']})")
            _ed = (_evd - _asd).days
            if _ed < 0:
                raise ValueError(f"upcoming_events event_date 早于 as_of({_e['ts_code']})")
            if _ed != _e["days_to_event"]:
                raise ValueError(f"upcoming_events days_to_event 与 event_date−as_of 不一致({_e['ts_code']})")
            if _ed > FORWARD_EVENT_WINDOW_DAYS:
                raise ValueError(f"upcoming_events 超出 {FORWARD_EVENT_WINDOW_DAYS} 日窗口(days_to_event={_ed};{_e['ts_code']})")
        # row no-dangling(R-...-ROW-LANDING-GUARD-GAP):每个 checked event 必须真落到对应逐票面(消费者 validator 强制,不靠
        # main() 调用顺序)——reports[] 行须有 forward_event_limit_unlock operation_impact;只在 manual_review 的票须 reason 含落地标记。
        if _ue.get("status") == "checked":
            _rep_by = {r["ts_code"]: r for r in weekly["reports"]}
            _mr_by = {h["ts_code"]: h for h in (weekly.get("holdings_manual_review") or [])}
            for _e in _uevs:
                _rep = _rep_by.get(_e["ts_code"])
                if _rep is not None:
                    if not any(i.get("source_field") == "forward_event_limit_unlock"
                               for i in ((_rep.get("machine") or {}).get("operation_impact") or [])):
                        raise ValueError(f"upcoming_events event {_e['ts_code']} 未落到该 report 逐票 operation_impact(forward_event 悬空)")
                elif _FORWARD_EVENT_MARKER not in str((_mr_by.get(_e["ts_code"]) or {}).get("reason", "")):
                    raise ValueError(f"upcoming_events event {_e['ts_code']} 未落到 holdings_manual_review reason(forward_event 悬空)")
        # per-code coverage(PARTIAL-UNKNOWN): unchecked_codes 的 ts_code 也须 ∈ 候选/持仓集(不张冠李戴)
        for _uc in (_ue.get("unchecked_codes") or []):
            if _uc["ts_code"] not in _valid_codes:
                raise ValueError(f"upcoming_events unchecked_codes ts_code {_uc['ts_code']} 不在本周候选/持仓集")


def _reject_production_output_path(out_path: str) -> None:
    """周报是 non-production artifact。输出路径由调用方指定(约定写 research/results/),
    但**绝不写 production 输出根 result/a_short/<date>**(CLAUDE.md 硬约束)。"""
    norm = os.path.normpath(os.path.abspath(out_path)).replace("\\", "/").lower()
    if "/result/a_short/" in norm:
        raise ValueError(f"禁止写入 production 路径 {out_path}(result/a_short/<date>);"
                         "周报输出由调用方指定(约定 research/results/),但绝不落 production 根")


def _is_account_output_git_ignored(abs_path: str, repo_root: str) -> bool:
    """问 git:该路径是否被 .gitignore 忽略(= commit 不到)。**用 git 真值而非路径名启发式**,故仓库内
    假 `weekly_private`、未被 `state/*/weekly_private/` 覆盖的嵌套层级、大小写变体都按 git 实际是否忽略判定。
    git 不可用/出错 → False(fail-closed:无法证明安全就当未忽略,宁拒勿漏)。"""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", repo_root, "check-ignore", "-q", "--", abs_path],
                           capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def _reject_nonprivate_account_output_path(out_path: str, has_account: bool,
                                           allow_override: bool = False) -> None:
    """持仓恒列入隐私护栏(固化):带 --account 的周报含**真实持仓**(代码/成本/股数/止损)。判据 =
    输出落在**本仓库内、且 git 未忽略它**(`git check-ignore` 未命中)→ 一次 `git add` 即提交泄漏 → 拒。
    **以 git 真实忽略判定为准**(非路径名启发式):仓库内假 `weekly_private`、未被 `state/*/weekly_private/`
    覆盖的嵌套层级、大小写变体都按 git 实际行为正确处理(此即 Codex 审查指出的两个绕过的根治)。
    仓库外路径(临时目录/外部盘)git 提交不到 → 放行;无 --account(无持仓)/ `--allow-nonprivate-account-out`
    → 放行。约定私密目录 = gitignored `state/<系统类型>/weekly_private/<as_of>/`。"""
    if not has_account or allow_override:
        return
    out_abs = os.path.abspath(out_path)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_l = os.path.normpath(out_abs).replace("\\", "/").lower()
    root_l = os.path.normpath(os.path.abspath(repo_root)).replace("\\", "/").lower()
    inside_repo = out_l == root_l or out_l.startswith(root_l + "/")
    if not inside_repo:
        return                                       # 仓库外:git 提交不到
    if _is_account_output_git_ignored(out_abs, repo_root):
        return                                       # 仓库内但确被 gitignore:安全
    raise SystemExit(
        f"[FATAL] --account 提供(周报含真实持仓),但 --out {out_path} 落在仓库内、且 git 未忽略它"
        "(`git check-ignore` 未命中)→ 会被 git 提交泄漏持仓;请输出到 gitignored 的"
        " state/<系统类型>/weekly_private/<as_of>/。确需写仓库内他处请显式传 --allow-nonprivate-account-out。")


def write_weekly_report(weekly: dict, iv_feed_summary: dict, out_path: str) -> None:
    _reject_production_output_path(out_path)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        wschema = json.load(f)
    with open(M67_SCHEMA_PATH, "r", encoding="utf-8") as f:
        m67schema = json.load(f)
    jsonschema.validate(weekly, wschema)
    for rep in weekly["reports"]:
        jsonschema.validate(rep, m67schema)                  # 每张 M6.7 过 m67 schema
    validate_weekly_report(weekly, iv_feed_summary)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(weekly, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def _load_validated_overlay(overlay_path: str, weekly_as_of: str) -> dict:
    """#5 消费方校验:overlay 必须过 schema + `validate_overlay_summary_consistency`,
    且 as_of 必须 == 周报 as_of(同一周末批;拒未来/陈旧)。返回 {ts_code: row}。"""
    from runners.a_short_theme_overlay_comparison import validate_overlay_summary_consistency
    with open(overlay_path, encoding="utf-8") as f:
        ov = json.load(f)
    with open(OVERLAY_SCHEMA_PATH, encoding="utf-8") as f:
        jsonschema.validate(ov, json.load(f))
    validate_overlay_summary_consistency(ov)
    if str(ov.get("as_of")) != str(weekly_as_of):
        raise SystemExit(f"[FATAL] overlay as_of {ov.get('as_of')} != 周报 as_of {weekly_as_of}"
                         "(未来/陈旧 overlay,须同一周末批)")
    # 重复 ts_code 行检测 **在 dict 折叠之前**(#R-ASHORT-WEEKLY-AUX-ARTIFACT-CANDIDATE-SET-MISMATCH):
    # `{c["ts_code"]: c}` 会静默用后一行覆盖前一行,使 main 的 set 比对看不到重复(3 行折叠成 2 → set 相等);
    # 若重复行带不同 eligible/crowding,会悄改 M6.7 星级。重复即拒。
    raw_codes = [c["ts_code"] for c in ov.get("candidates", [])]
    if len(raw_codes) != len(set(raw_codes)):
        dupes = sorted({c for c in raw_codes if raw_codes.count(c) > 1})
        raise SystemExit(f"[FATAL] overlay 含重复 ts_code {dupes}(dict 折叠会静默覆盖,星级可能被悄改);拒跑")
    return {c["ts_code"]: c for c in ov.get("candidates", [])}


def latest_iv_percentile(iv_feed_summary: dict):
    """取 feed 最新一天的 252d 分位(市场级 IV 闸门输入);无则 None。"""
    series = iv_feed_summary.get("series") or []
    return series[-1]["iv_percentile_252d"] if series else None


def latest_iv_hv(iv_feed_summary: dict):
    """取 feed 最新一天的 (iv_value, hv_value)(市场级 #6 IV-HV advisory 输入);无则 (None, None)。"""
    series = iv_feed_summary.get("series") or []
    if not series:
        return None, None
    last = series[-1]
    return last.get("iv_value"), last.get("hv_value")


MIN_PRICE_OBS = 20               # 指标(支撑/压力 20d、ATR 14d)所需最少 PIT 交易日
EX_DIV_WINDOW_DAYS = 14          # #1 除权除息提示:as_of 起 N 个日历日内将除权 → advisory 提示(不改决策)


def _ex_div_notices(code_names, as_of, dividend_provider, window_days=EX_DIV_WINDOW_DAYS):
    """#1 除权除息提示(advisory,**不改任何决策**:价格已前复权,此为提醒用户**未复权市价/持仓成本**会在
    除权日跳变)。PIT 安全:只提示 `ann_date<=as_of`(已公告,非 look-ahead)且 `as_of<=ex_date<=as_of+window`
    (近端将除权)的事件;每票取最近一次。`dividend_provider(ts_code)` → list[{"ann_date","ex_date"}]
    (YYYYMMDD|None);None provider 或非法日期 → 跳过(绝不伪造)。返回 [{ts_code,name,ex_date,days_to_ex}] 排序。"""
    from datetime import datetime
    if dividend_provider is None:
        return []
    try:
        as_of_d = datetime.strptime(str(as_of), "%Y%m%d")
    except ValueError:
        raise ValueError(f"ex_div as_of {as_of!r} 非合法日历日")
    best = {}
    for ts_code, name in code_names:
        for rec in (dividend_provider(ts_code) or []):
            ex = (rec or {}).get("ex_date")
            if not ex:
                continue
            try:
                ex_d = datetime.strptime(str(ex), "%Y%m%d")
            except ValueError:
                continue                                  # 非法 ex_date → 跳过,不伪造
            ann = (rec or {}).get("ann_date")
            if ann is None:
                continue                                  # PIT:无公告日 → 无法证明 as_of 时已公告 → 跳过(不伪造非 PIT 提示)
            try:
                if datetime.strptime(str(ann), "%Y%m%d") > as_of_d:
                    continue                              # 公告晚于 as_of → look-ahead,跳过
            except ValueError:
                continue                                  # ann 非法 → 无法证 PIT,跳过
            days = (ex_d - as_of_d).days
            if 0 <= days <= window_days:                  # 近端将除权(含当日)
                if ts_code not in best or days < best[ts_code]["days_to_ex"]:
                    best[ts_code] = {"ts_code": ts_code, "name": name or "",
                                     "ex_date": str(ex), "days_to_ex": days}
    return sorted(best.values(), key=lambda n: (n["days_to_ex"], n["ts_code"]))


FORWARD_EVENT_WINDOW_DAYS = 21   # 4.2 forward_events: as_of 起 N 个日历日内的已公告未来事件 → advisory 日历(§4.4 prior,未来进 governance)
_FORWARD_EVENT_MARKER = "未来已知事件"   # holdings_manual_review reason 落地标记:_attach 写入 + validator 据此判 row no-dangling(单一来源,防文案漂移)


def _upcoming_events(code_names, as_of, unlock_provider, window_days=FORWARD_EVENT_WINDOW_DAYS):
    """4.2 forward_events 第1刀: 未来已知事件日历(analysis-only,**不改任何决策**;只进 M6.7 提示)。第1刀只做限售解禁。
    PIT 安全: 只收 `observed_at`(ann_date)<=as_of(已公告,非 look-ahead) 且 `as_of<=event_date`(float_date)<=as_of+window
    的事件;每票取最近一次。`unlock_provider(ts_code)` → list[{"ann_date","float_date"}](YYYYMMDD|None)。
    **unknown-not-clear**: unlock_provider 为 None(没授权取数/不可用)→ status=`unknown_or_unavailable`(绝不当「无未来事件」);
    全票取数失败(无一查成)→ 同 unknown;**部分票失败**→ status `checked` 但失败票进 `unchecked_codes`(per-code 粒度,绝不把没
    查成的票当「无事件」);跑成但某票真无近端解禁 → 不计该票。非法/缺日期跳过(不伪造)。返回 {as_of,status,events[],unchecked_codes?}。"""
    from datetime import datetime
    if unlock_provider is None:
        return {"as_of": str(as_of), "status": "unknown_or_unavailable", "events": []}
    try:
        as_of_d = datetime.strptime(str(as_of), "%Y%m%d")
    except ValueError:
        raise ValueError(f"upcoming_events as_of {as_of!r} 非合法日历日")
    best, any_ok, unchecked = {}, False, []
    for ts_code, name in code_names:
        try:
            recs = unlock_provider(ts_code)
        except Exception:
            recs = None                               # 单票查询失败 → 未查成
        if recs is None:
            unchecked.append({"ts_code": ts_code, "name": name or ""})   # 未查成 → per-code unknown(不当无事件)
            continue                                  # 不计 any_ok(区别于真无解禁的 [])
        any_ok = True                                 # 该票查成(含真无解禁返回的空 list)
        for rec in recs:
            fd = (rec or {}).get("float_date")
            ann = (rec or {}).get("ann_date")
            if not fd or ann is None:
                continue                              # 无解禁日/无公告日 → 无法 PIT 证明,跳过(不伪造)
            try:
                fd_d = datetime.strptime(str(fd), "%Y%m%d")
                ann_d = datetime.strptime(str(ann), "%Y%m%d")
            except ValueError:
                continue                              # 非法日期 → 跳过
            if ann_d > as_of_d:
                continue                              # 公告晚于 as_of → look-ahead,跳过
            days = (fd_d - as_of_d).days
            if 0 <= days <= window_days:              # 近端将解禁(含当日)
                if ts_code not in best or days < best[ts_code]["days_to_event"]:
                    best[ts_code] = {"ts_code": ts_code, "name": name or "",
                                     "event_type": "limit_unlock", "event_date": str(fd),
                                     "observed_at": str(ann), "source_id": "tushare.share_float",
                                     "expected_effect": "manual_review", "confidence": "high",
                                     "days_to_event": days}
    # unknown-not-clear(§4.4): provider 非 None 但**所有票都没查成**(取数全失败)→ unknown_or_unavailable,
    # 绝不把「没查成」当「查了无未来事件」(只有真查成 — 含真无解禁的空 — 才 checked)。
    if code_names and not any_ok:
        return {"as_of": str(as_of), "status": "unknown_or_unavailable", "events": []}
    events = sorted(best.values(), key=lambda e: (e["days_to_event"], e["ts_code"]))
    out = {"as_of": str(as_of), "status": "checked", "events": events}
    if unchecked:                                     # 部分票未查成(全失败已上面 return unknown)→ per-code coverage,绝不静默当无事件
        out["unchecked_codes"] = unchecked
    return out


def _fetch_unlocks(pro, ts_code: str):
    """4.2 forward_events 真解禁 provider: tushare `pro.share_float`(逐票未来解禁,**带公告日 ann_date 做 PIT** —— egs_main
    的 get_unlock_future 只取 float_date 做二元过滤,不带 ann_date,故 forward 日历自取)→ [{"ann_date","float_date"}]
    (YYYYMMDD|None)。**fail-closed**: 缺 ann_date/float_date 列 → [](无法 PIT,不伪造);异常/空 → [](旁路不阻断)。"""
    try:
        df = pro.share_float(ts_code=ts_code, fields="ts_code,ann_date,float_date,float_share,float_ratio")
    except Exception:
        return None                                   # 取数失败 → 未查成(区别于真无解禁的 [];builder 据此标 unknown)
    if df is None:
        return None                                   # provider 没返回 → 未查成
    if not {"ann_date", "float_date"}.issubset(set(getattr(df, "columns", []))):
        return None                                   # 缺 PIT 列(数据形态异常)→ 未查成(不静默当真无)
    if getattr(df, "empty", True):
        return []                                     # 成功返回空 → 该票真无未来解禁记录(查成了)
    def _clean(v):
        return str(v) if (v is not None and str(v).strip() not in ("", "nan", "None", "NaT")) else None
    return [{"ann_date": _clean(r.get("ann_date")), "float_date": _clean(r.get("float_date"))}
            for _, r in df.iterrows()]


def _attach_forward_event_impacts(weekly, as_of):
    """4.2 forward_events row landing(R-ASHORT-GAP42-FORWARD-EVENTS-ROW-LANDING-GUARD-GAP): 把 weekly-global
    upcoming_events 的每个事件按 ts_code 落到对应 report 的**逐票** M6.7 —— `machine.operation_impact`(候选→
    candidate_row_impact / 持仓→holding_row_impact)+ 精简结论区.风控触发 文本。**analysis-only**:veto_class=none、
    production_effect_enabled=False、new_entry_effect 非 hard_veto(绝不 hard_veto / 绝不 rescue 已有 hard veto /
    不改 操作·EGS·选股·TopN —— 只追加 advisory impact+文本)。status!=checked(unknown/无)→ 不落(不伪造逐票影响)。
    §4.4 影响:候选→manual_review、持仓→hold_watch + blocked_add(临近解禁谨慎加仓);减仓/清仓价待 S3b。"""
    ue = weekly.get("upcoming_events") or {}
    if ue.get("status") != "checked":
        return
    by_code = {}
    for e in (ue.get("events") or []):
        by_code.setdefault(e["ts_code"], []).append(e)
    def _evtxt(evs):
        return "；".join(f"未来事件 {e['event_type']}@{e['event_date']}(公告{e['observed_at']}/{e['expected_effect']})"
                         for e in evs)
    for rep in weekly["reports"]:
        evs = by_code.get(rep["ts_code"])
        if not evs:
            continue
        held = ((rep.get("machine") or {}).get("stateful_risk") or {}).get("position_state") == "held"
        txt = _evtxt(evs)
        cut = rep["m67"]["精简结论区"]
        prev = cut.get("风控触发") or "无"
        cut["风控触发"] = txt if prev in ("无", "") else f"{prev}|{txt}"
        # ADVICE-LANDING(R-...-ADVICE-LANDING-GAP):未来事件也落用户主看的 操作建议(不只风控触发),否则候选仍像干净建仓。
        # advisory 文本(不改 table 操作/EGS/TopN);候选→人工复核/谨慎建仓、持仓→持有观察/谨慎加仓;含 _FORWARD_EVENT_MARKER 供 guard 判落地。
        _adv = (f"⚠️ {_FORWARD_EVENT_MARKER}(限售解禁{len(evs)}项近端将至):"
                + ("持有观察、谨慎加仓" if held else "先人工复核/转观察/谨慎建仓")
                + ",不改 EGS/TopN/生产决策(advisory)")
        _ap = cut.get("操作建议") or ""
        cut["操作建议"] = f"{_ap}｜{_adv}" if _ap else _adv
        rep["machine"].setdefault("operation_impact", []).append({
            "source_field": "forward_event_limit_unlock",
            "field_class": "structured",
            "visibility_shape": "holding_row_impact" if held else "candidate_row_impact",
            "impact_scope": "existing_holding" if held else "new_entry",
            "new_entry_effect": "none" if held else "manual_review",
            "holding_effect": "hold_watch" if held else "none",
            "blocked_add_required": bool(held),
            "veto_class": "none",
            "reason": f"未来已知事件(限售解禁){len(evs)}项近端将至 → advisory 提示(不改决策/EGS/选股/TopN)",
            "evidence_ref": {"kind": "lineage_key", "value": "upcoming_events.events[limit_unlock]", "as_of": str(as_of)},
            "confidence": "high",
            "pit_basis": "disclosure_date",
            "production_effect_enabled": False,
            "implementation_status": "future_s3b_schema_render_required" if held else "implemented",
            "m67_landing_surface": "精简结论区.风控触发(未来事件)",
            "terminal_surface_target": "s3b_持仓处置_列+减仓价" if held else "already_structured",
            "pending_successor_slice": "S3b" if held else None,
            "privacy_class": "private_account" if held else "public_tracked",
        })
    # 4.2 forward_events: holdings_manual_review(无价/停牌/价格陈旧旁路持仓,无 machine 结构、只 ts_code/name/reason、不进
    # reports[])的票若有 checked 事件 → validator 接受(universe = reports ∪ holdings_manual_review)却无逐票行,故 append
    # 到该持仓 reason(render 直接渲染);advisory/人工管理本不下系统决策——不改 EGS/TopN/动作、不 veto/rescue、不 S3b 减仓。
    for h in (weekly.get("holdings_manual_review") or []):
        evs = by_code.get(h["ts_code"])
        if not evs:
            continue
        note = f"{_FORWARD_EVENT_MARKER}(限售解禁){len(evs)}项近端将至 → {_evtxt(evs)}(advisory,人工核查;不改决策)"
        h["reason"] = f"{h['reason']}｜{note}" if h.get("reason") else note
# analysis_input.market_context.market_regime.status(EGS 英文枚举)→ 引擎中文 regime
REGIME_MAP = {"attack": "进攻期", "shock": "震荡期", "defense": "防御期", "contraction": "收缩期"}


def resolve_market_regime(ai: dict) -> tuple[str, dict | None]:
    """Resolve production regime for M6.7.

    EGS still emits ``unknown`` for the production V14.2 M1 slot. Per 2026-06-14 decision, that
    state must NOT be upgraded by an account-file override; it is treated as shock with conservative
    downgrade/halving and an explicit M6.7 caveat.
    """
    status = ((ai.get("market_context") or {}).get("market_regime") or {}).get("status")
    if status in REGIME_MAP:
        return REGIME_MAP[status], None
    return "震荡期", {
        "active": True,
        "source_status": status or "missing",
        "fallback_regime": "震荡期",
        "reason": "EGS market_regime unknown/missing→按震荡期保守处理",
        "action": "downgrade_and_halve",
    }


def _fetch_dividends(pro, ts_code: str):
    """#1 真除权数据 provider:tushare `pro.dividend`(只取 `div_proc=='实施'` —— 预案/通过的 ex_date 未定,
    不据此提示)→ [{"ann_date","ex_date"}](YYYYMMDD|None;空白→None)。**fail-closed**:缺证明 实施/公告日/
    除权日 所需列(div_proc/ann_date/ex_date)→ 返回 [](无法据不全数据提示,绝不伪造)。异常/空 → [](旁路不阻断)。"""
    try:
        df = pro.dividend(ts_code=ts_code, fields="ts_code,ann_date,div_proc,ex_date")
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    if not {"div_proc", "ann_date", "ex_date"}.issubset(set(getattr(df, "columns", []))):
        return []                                  # fail-closed:缺必要列,无法证 实施/PIT → 不提示
    df = df[df["div_proc"] == "实施"]
    def _clean(v):
        return str(v) if (v is not None and str(v).strip() not in ("", "nan", "None", "NaT")) else None
    return [{"ann_date": _clean(r.get("ann_date")), "ex_date": _clean(r.get("ex_date"))}
            for _, r in df.iterrows()]


def _fetch_price_series(ts_module, pro, ts_code: str, start: str, end: str,
                        accept_prior_settled_date: str | None = None) -> tuple:
    """前复权日线 → [{high,low,close}](oldest→newest)。A 股主板个股用 asset='E'。`end` == 周报 as_of。
    **provider 异常 → 中止(不 fail-open)**:provider 失败 ≠ 无交易,不能默默退化成观察。
    **PIT + 新鲜度门(R-ASHORT-WEEKLY-PRICE-SERIES-PIT-FRESHNESS-GAP)**:每个 `trade_date` 必须是
    合法日历日;拒任何 `trade_date > end`(未来 bar);**最新 bar 默认必须 == `end`(==as_of)**,否则数据
    陈旧 → 中止不写。返回空(provider 成功但无行)由 main 覆盖门统一拦截。

    **实盘盘中 reviewed-tolerance**(register 原始 repair 已显式预留「or document and test an explicit
    reviewed tolerance」):若给出 `accept_prior_settled_date`(= as_of 的前一交易日;仅由 main 在
    `--run-date == --as-of`、即实盘当天 as_of 当日 EOD 尚未发布的盘中场景传入),则最新 bar 亦可 == 该
    「最新已结算交易日」。仍拒**更早**(真陈旧)与**未来** bar;历史回放不传该参数 → 严格 == end。语义:在
    决策时点(as_of=今天)最新已结算行情就是前一交易日,使用它非 look-ahead、亦非陈旧。

    返回 `(series, latest_trade_date)`:series=[{high,low,close}](engine 形状,不含日期);latest_trade_date=
    实际最新已结算 bar 日期(供 main 记 `price_data_through` lineage,诚实标注真实价格时钟);无行 → `([], None)`。"""
    from datetime import datetime
    try:
        df = ts_module.pro_bar(ts_code=ts_code, adj="qfq", asset="E",
                               start_date=start, end_date=end, api=pro)
    except Exception as exc:
        raise SystemExit(f"[FATAL] pro_bar {ts_code} provider 失败: {type(exc).__name__};"
                         "不写周报(provider 失败 ≠ 无交易,不可 fail-open 成观察)")
    if df is None or df.empty:
        return [], None
    df = df.sort_values("trade_date")
    rows = []
    for _, r in df.iterrows():
        td = str(r["trade_date"])
        try:
            datetime.strptime(td, "%Y%m%d")
        except ValueError:
            raise SystemExit(f"[FATAL] pro_bar {ts_code} 返回非法日历日期 {td};不写周报")
        if td > str(end):
            raise SystemExit(f"[FATAL] pro_bar {ts_code} 返回未来 bar {td} > as_of {end}(PIT 违规);不写周报")
        rows.append({"trade_date": td, "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])})
    if rows and rows[-1]["trade_date"] != str(end):
        latest = rows[-1]["trade_date"]
        # 实盘盘中容忍:当日 EOD 未发布 → 最新已结算 == 前一交易日(accept_prior_settled_date)放行;凡比它更早
        # (真陈旧)仍中止。未来 bar 已在上面逐行 `td > end` 拦截,不可能落到这里(故 tolerance 永不放未来)。
        if not (accept_prior_settled_date is not None and latest == str(accept_prior_settled_date)):
            raise SystemExit(f"[FATAL] pro_bar {ts_code} 最新 bar {latest} != as_of {end}"
                             "(数据陈旧,未含 as_of 当日);不写周报")
    series = [{"high": r["high"], "low": r["low"], "close": r["close"]} for r in rows]
    return series, (rows[-1]["trade_date"] if rows else None)


def _prev_trading_day(pro, as_of: str) -> str | None:
    """最近一个**严格早于** `as_of` 的 SSE 交易日(经 `trade_cal`)。用于实盘盘中价格新鲜度门容忍:as_of
    当日 EOD 未发布时,最新已结算交易日即此前一交易日。取不到/异常 → None(调用方退回严格门,fail-closed)。"""
    from datetime import datetime, timedelta
    start = (datetime.strptime(str(as_of), "%Y%m%d") - timedelta(days=30)).strftime("%Y%m%d")
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=str(as_of),
                            is_open="1", fields="cal_date")
    except Exception:
        return None
    if cal is None or len(cal) == 0 or "cal_date" not in cal.columns:
        return None
    days = sorted(str(d) for d in cal["cal_date"] if str(d) < str(as_of))
    return days[-1] if days else None


def _price_provider_result(provider, code: str, as_of: str) -> tuple:
    """Normalize a price_provider(code) call to ``(series, latest_trade_date)``. The real fetcher
    (`_fetch_price_series`) returns that tuple; an injected list-only provider (tests) is treated as a
    strict ``as_of`` clock (latest == as_of) so the run_lineage price clock is honest in both paths."""
    res = provider(code)
    if isinstance(res, tuple):
        series, latest = res
        return list(series), (str(latest) if latest is not None else None)
    return list(res), str(as_of)


def _build_cninfo_semantic_provider(codes, as_of, lookback_days, fetcher=None, cap=None):
    """非阻断 cninfo official provider(advisory 旁路),**复用 summary 已审门**——不另写薄版:
    `build_summary_from_fetches` 内含 `main_board_top15`(只取/喂主板 Top15)+ 缺码→unknown + 批量空响应门
    (大面积 ok-empty → 降 unknown 不报 clear)。返回 ts_code→official_structured;**任何失败 / 非法 lookback
    → None**(语义全 unknown 中性,绝不阻断周报)。cninfo 偶缺 adjunctUrl → url_or_pdf 空,引擎按方案 A 把
    缺 URL 的 high 降 pending 待核(不否决、不崩)。"""
    try:
        if not (isinstance(lookback_days, int) and lookback_days > 0):
            return None                                  # 非法窗口 → 不取数(绝不因坏窗口产 false-clear)
        from runners.a_short_semantic_risk_summary import build_summary_from_fetches
        from runners.a_short_semantic_risk_probe import fetch_cninfo as _fetch, main_board_top15
        # 候选默认 Top15;持仓传 cap=持仓数全覆盖(绕 Top15——持仓不能因 >15 被截), 仍主板过滤 + 去重。
        main_codes, _dropped = (main_board_top15(codes, cap) if cap is not None else main_board_top15(codes))
        if not main_codes:
            return None
        raws = (fetcher or _fetch)(main_codes, as_of, lookback_days)
        # malformed/无 ts_code 行丢弃 → 该码在 build_summary_from_fetches 里缺映射 → not_fetched → unknown
        # (绝不建 "None" 键、绝不把残缺/缺响应当 clear)。
        cninfo_results = {str(r["ts_code"]): r for r in raws
                          if isinstance(r, dict) and r.get("ts_code")}
        # Finding 1 fix: build_summary_from_fetches 内部再过 main_board_top15(默认 Top15)+ validate ≤15(候选 watch-pool
        # 契约),会把持仓 provider 二次截到 15(第 16+ 持仓 provider(code)=None)。持仓全覆盖(cap>15)→ 按 Top15 一批分批调用
        # 并合并 by map(每批仍走同一已审门 + batch-anomaly 降级);候选(cap=None,main_codes≤15)= 单批,行为不变。
        from runners.a_short_semantic_risk_probe import TOP15_CAP
        by = {}
        for i in range(0, len(main_codes), TOP15_CAP):
            batch = main_codes[i:i + TOP15_CAP]
            summary = build_summary_from_fetches(batch, as_of, cninfo_results, None,
                                                 "weekly-semantic-provider")  # generated_at 仅占位,不被消费
            by.update({c["ts_code"]: c["official_structured"] for c in summary["candidates"]})
        return lambda ts: by.get(str(ts))
    except Exception as exc:
        print(f"[weekly] 语义 cninfo 取数失败({type(exc).__name__});语义层全 unknown(advisory,不阻断周报)")
        return None


def _build_deepseek_web_llm_provider(codes, names_by_code, as_of, lookback_days=None,
                                     news_fetcher=None, ds_client=None, cap=None):
    """非阻断 DeepSeek web/LLM 判官 provider(advisory 旁路)。**em 资讯为主源**(取代失效的 sina roll):一次性批量
    抓 em 逐股近期新闻(PIT 近 N 天),逐票经 DeepSeek 判 → `{web_llm, sources}`(非 unknown)或 None(unknown/
    中性)。**缺 key/SDK → None(整层 unknown)**;抓取失败 → None;单票判定异常 → 该票 None。任何失败都不阻断周报、
    不伪装 clear、不返回/打印 key。"""
    from runners.a_short_deepseek_semantic_adapter import judge_web_llm, build_deepseek_client
    client = ds_client if ds_client is not None else build_deepseek_client()
    if client is None:
        return None                                      # 缺 key/SDK → 整层 unknown(advisory,不阻断)
    try:
        from runners.a_short_semantic_risk_probe import fetch_em_news, main_board_top15
        from runners.a_short_semantic_risk_summary import _em_sources
        # 复用 cninfo provider 同一已审门:主板 Top15(去重 + 有界 cap15 + 非主板剔除)。**抓 em/判 DeepSeek 前先过滤**,
        # 否则非标/扩大 analysis_input(如含创业板 300/科创 688)会触发超界的 em/DeepSeek 成本与覆盖。
        main_codes, _dropped = (main_board_top15(codes, cap) if cap is not None else main_board_top15(codes))
        if not main_codes:
            return None
        allowed = {str(c) for c in main_codes}
        raws = (news_fetcher or fetch_em_news)(list(main_codes), names_by_code, as_of, lookback_days)
        items_by = {str(r["ts_code"]): _em_sources(r) for r in raws
                    if isinstance(r, dict) and r.get("ts_code")}
    except Exception as exc:
        print(f"[weekly] 语义 web/LLM em 抓取失败({type(exc).__name__});web 层全 unknown(advisory,不阻断)")
        return None
    cache = {}
    def provider(code):
        code = str(code)
        if code not in allowed:
            return None                                  # 主板 Top15 之外 → 中性(不抓不判,边界一致)
        if code not in cache:
            try:
                web, sources, _trace = judge_web_llm(
                    code, names_by_code.get(code, ""), items_by.get(code, []), client=client)
                cache[code] = ({"web_llm": web, "sources": sources}
                               if web["status"] != "unknown" else None)
            except Exception:
                cache[code] = None                       # 单票判定异常 → 中性(不阻断)
        return cache[code]
    return provider


def main(argv=None, pro_factory=None, price_provider=None, semantic_provider=None,
         web_llm_provider=None, dividend_provider=None,
         holding_semantic_provider=None, holding_web_llm_provider=None, unlock_provider=None):
    from datetime import datetime, timedelta
    from runners.a_short_iv_feed_probe import init_tushare_pro, _is_valid_yyyymmdd
    from engine.data.analysis_input_contract import validate_analysis_input_file
    p = argparse.ArgumentParser(description="A-short weekly pipeline (EGS→overlay→IV→engine→weekly M6.7)")
    p.add_argument("--as-of", required=True, help="YYYYMMDD")
    p.add_argument("--analysis-input", required=True, help="EGS analysis_input.json (top-N 候选)")
    p.add_argument("--iv-feed", required=True, help="a_short_iv_feed.json")
    p.add_argument("--overlay", help="overlay artifact(可选)")
    p.add_argument("--account", help="账户状态 JSON(available_cash / positions / rule12 / rule13_cooldowns)")
    p.add_argument("--out", required=True)
    p.add_argument("--confirm-fetch-authorized", action="store_true")
    p.add_argument("--cninfo-lookback-days", type=int, default=90,
                   help="语义官方层 cninfo 取数回溯天数(默认 90;真 run --confirm 时自动取数)")
    p.add_argument("--web-news-lookback-days", type=int, default=30,
                   help="web_llm em 资讯新鲜度窗(天,默认 30;只把近 N 天新闻喂判官)")
    p.add_argument("--run-date", help="实际运行日 YYYYMMDD(记进 run_lineage;intraday_prior_settled 模式要求 ==--as-of)")
    p.add_argument("--price-freshness-mode", choices=["strict_as_of", "intraday_prior_settled"],
                   default="strict_as_of",
                   help="价格新鲜度模式(显式,记进 run_lineage.price_freshness):strict_as_of(默认,最新 bar 必须 ==as_of);"
                        "intraday_prior_settled(实盘盘中、as_of 当日 EOD 未发布 → 容忍最新 bar==前一交易日;仅 --run-date==--as-of 有效)")
    p.add_argument("--skip-semantic", action="store_true",
                   help="跳过语义官方层自动取数(advisory;不影响 M6.7 确定性 base)")
    p.add_argument("--allow-nonprivate-account-out", action="store_true",
                   help="显式放行:带 --account 时允许输出落仓库内非私密目录(默认拒,防真实持仓被 git 提交泄漏)")
    args = p.parse_args(argv)
    if not _is_valid_yyyymmdd(args.as_of):
        raise SystemExit(f"[FATAL] --as-of {args.as_of} 不是合法日历日期")
    if args.run_date and not _is_valid_yyyymmdd(args.run_date):
        raise SystemExit(f"[FATAL] --run-date {args.run_date} 不是合法日历日期")
    # intraday tolerance is an EXPLICIT mode, not inferred; and only valid on the actual run day (when
    # as_of's own EOD may not be published yet). Historical replay / missing run-date must stay strict.
    if args.price_freshness_mode == "intraday_prior_settled" and str(args.run_date or "") != str(args.as_of):
        raise SystemExit("[FATAL] --price-freshness-mode intraday_prior_settled 仅在 --run-date == --as-of"
                         "(实盘当天、as_of 当日 EOD 未发布)有效;历史回放/缺 run-date 请用 strict_as_of")
    # 持仓恒列入隐私护栏(固化):带 --account 的周报含真实持仓 → 拒绝落仓库内非私密目录(防 git 提交泄漏)。
    # 早于任何取数/落盘,fail-fast。
    _reject_nonprivate_account_output_path(args.out, bool(args.account), args.allow_nonprivate_account_out)

    def _load(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # analysis_input 消费方校验(#R-ASHORT-WEEKLY-ANALYSIS-INPUT-CONSUMER-VALIDATION-GAP):
    # 用仓库契约校验 schema + PIT,并强制 trade_date == --as-of(拒错配/未来/陈旧批次)。
    ai = validate_analysis_input_file(args.analysis_input, label="weekly analysis_input")
    if str(ai.get("trade_date")) != args.as_of:
        raise SystemExit(f"[FATAL] analysis_input.trade_date {ai.get('trade_date')} != --as-of {args.as_of}"
                         "(批次错配/未来/陈旧,拒跑周报)")
    feed = _load(args.iv_feed)
    iv_pct = latest_iv_percentile(feed)        # 市场级 IV 分位(None → 引擎按 missing 处理)
    iv_value, hv_value = latest_iv_hv(feed)    # #6 IV-HV advisory:市场级 IV/HV 原始值(引擎算标签)
    overlay = _load_validated_overlay(args.overlay, args.as_of) if args.overlay else {}
    weekly_candidates = [c.get("ts_code") for c in ai.get("candidates", [])]
    # overlay 血缘门(#R-ASHORT-WEEKLY-AUX-ARTIFACT-CANDIDATE-SET-MISMATCH):overlay 必须**恰好覆盖**
    # 本周报候选集(同一批)。缺行会被 `overlay.get(ts)` 静默 default 成 eligible/crowding=false,悄悄改
    # M6.7 星级;多行说明非同批。任一不符 → 写盘前 abort。
    if args.overlay and set(overlay) != set(weekly_candidates):
        raise SystemExit(f"[FATAL] overlay 候选集 {sorted(overlay)} != 周报候选 {sorted(weekly_candidates)}"
                         "(同日错批/缺行/多行,缺行会被静默降级;须同一批全覆盖,拒跑)")
    acct = validate_account_state(_load(args.account), args.as_of) if args.account else {}
    # 市场 regime 只取自 analysis_input(EGS 分类)。unknown/missing 不允许被账户配置覆盖成进攻期;
    # 按 2026-06-14 用户决策:unknown → 震荡期 + 降级 + 保守减半 + M6.7 明确提示。
    regime, regime_fallback = resolve_market_regime(ai)
    # available_cash 是用户必填输入。**--account 提供则必须有正数 available_cash**(拒静默无 sizing);
    # 未提供 --account → observation-only(sizing_mode 标进 run_lineage,读者不会把 sizing 假象的「观察」当真 avoid 信号)。
    available_cash = acct.get("available_cash")
    if args.account:
        if isinstance(available_cash, bool) or not isinstance(available_cash, (int, float)) or available_cash <= 0:
            raise SystemExit(f"[FATAL] --account {args.account} 提供但 available_cash 缺失/非正数;拒跑(不静默退化成无 sizing 的观察)")
        account_status, sizing_mode = "provided", "sized"
    else:
        account_status, sizing_mode = "absent", "observation_only_no_account"
    account = {"available_cash": available_cash,
               "total_equity": acct.get("total_equity"),
               "current_gross_exposure": acct.get("current_gross_exposure"),
               "positions_count": len(acct.get("positions") or [])}
    # 价格序列:注入(测试)或执行期抓取(需授权)
    prior_settled = None     # 实际接受的前一交易日(仅 intraday_prior_settled 模式;记进 lineage)
    if price_provider is None:
        if not args.confirm_fetch_authorized:
            raise SystemExit("[FATAL] 需 --confirm-fetch-authorized:周末 run 会抓前复权价")
        import tushare as ts
        pro = pro_factory() if pro_factory else init_tushare_pro(os.environ["TUSHARE_TOKEN"])
        start = (datetime.strptime(args.as_of, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
        # 显式 intraday_prior_settled 模式(已 guard --run-date==--as-of)→ 价格门容忍最新 bar==前一交易日
        # (as_of 当日 EOD 未发布的实盘盘中);strict_as_of → prior_settled=None → 严格 == as_of。仅放前一交易日,
        # 更早(真陈旧)仍拒、未来恒拒;实际接受的最新日期记进 run_lineage.price_freshness。
        prior_settled = (_prev_trading_day(pro, args.as_of)
                         if args.price_freshness_mode == "intraday_prior_settled" else None)
        price_provider = lambda code: _fetch_price_series(ts, pro, code, start, args.as_of,
                                                          accept_prior_settled_date=prior_settled)
        # #1 除权除息提示真 provider(advisory 旁路;注入优先用于测试):同一已授权 fetch 上下文。
        if dividend_provider is None:
            dividend_provider = lambda code: _fetch_dividends(pro, code)
        # 4.2 forward_events 真解禁 provider(analysis-only advisory 旁路;注入优先;同一已授权 fetch 上下文)。
        if unlock_provider is None:
            unlock_provider = lambda code: _fetch_unlocks(pro, code)
    # 语义官方层 provider(advisory 旁路,非阻断):注入优先(测试);否则真 run(--confirm 且未 --skip-semantic)
    # 时自动 cninfo 取数。取数失败 → None(语义全 unknown 中性)。语义只融进非生产 M6.7,不碰确定性 base 决策外的逻辑。
    if semantic_provider is None and args.confirm_fetch_authorized and not args.skip_semantic:
        semantic_provider = _build_cninfo_semantic_provider(
            weekly_candidates, args.as_of, args.cninfo_lookback_days)
    # 语义 web/LLM provider(Slice 2,advisory 旁路,非阻断):注入优先;否则真 run(--confirm 且未 --skip-semantic)
    # 自动建 DeepSeek 判官 provider(缺 key/SDK/抓取失败 → None,该层全 unknown 中性,绝不阻断周报)。
    if web_llm_provider is None and args.confirm_fetch_authorized and not args.skip_semantic:
        _cands = ai.get("candidates", [])
        web_llm_provider = _build_deepseek_web_llm_provider(
            [c.get("ts_code") for c in _cands],
            {str(c.get("ts_code")): c.get("name", "") for c in _cands},
            args.as_of, args.web_news_lookback_days)
    cands = ai.get("candidates", [])
    # capture (series, latest_trade_date) per candidate so the artifact can record the real price clock
    price_results = {c["ts_code"]: _price_provider_result(price_provider, c["ts_code"], args.as_of) for c in cands}
    normalized = [normalize_candidate(c, price_results[c["ts_code"]][0], overlay.get(c["ts_code"]),
                                      iv_pct, account, regime,
                                      regime_fallback=regime_fallback,
                                      stateful_risk=stateful_risk_for_candidate(acct, c["ts_code"], args.as_of),
                                      semantic=(semantic_provider(c["ts_code"]) if semantic_provider else None),
                                      semantic_web_llm=(web_llm_provider(c["ts_code"]) if web_llm_provider else None),
                                      iv_value=iv_value, hv_value=hv_value)
                  for c in cands]
    # 价格覆盖门(#2):任一被纳入候选缺足够价格 → 中止不写(不可 fail-open 成观察)
    short = [(n["ts_code"], len(n["price_series"])) for n in normalized
             if len(n["price_series"]) < MIN_PRICE_OBS]
    if short:
        raise SystemExit(f"[FATAL] 以下候选价格序列不足(<{MIN_PRICE_OBS} 交易日):{short};"
                         "不写周报(价格抓取失败/停牌须排查,不可静默退化成观察)")
    # 价格时钟 lineage(诚实标注 M6.7 技术指标实际用到的最新已结算 bar 日期):候选间日期不一致(端点不均/部分
    # 陈旧)→ 中止,不静默混用;一致 → price_data_through = 该日(strict 恒 ==as_of;intraday ==as_of 或前一交易日)。
    latest_dates = sorted({d for d in (price_results[c["ts_code"]][1] for c in cands) if d})
    if len(latest_dates) > 1:
        raise SystemExit(f"[FATAL] 候选价格最新 bar 日期不一致(混合时钟 {latest_dates});不写周报"
                         "(端点不均/部分陈旧须排查,不可静默混用不同价格日)")
    price_data_through = latest_dates[0] if latest_dates else str(args.as_of)
    accepted_psd = str(prior_settled) if (prior_settled is not None and price_data_through == str(prior_settled)) else None
    price_freshness = {"mode": args.price_freshness_mode,
                       "run_date": (str(args.run_date) if args.run_date else None),
                       "accepted_prior_settled_date": accepted_psd,
                       "price_data_through": price_data_through}
    gen = datetime.now().astimezone().isoformat(timespec="seconds")
    def _rel(pth):
        try:
            return os.path.relpath(pth).replace("\\", "/")
        except Exception:
            return os.path.basename(pth)
    run_lineage = {"analysis_input": _rel(args.analysis_input),
                   "selection_bucket": _rel(os.path.dirname(args.analysis_input)),
                   "iv_feed": _rel(args.iv_feed),
                   "account_ref": (_rel(args.account) if args.account else ""),
                   "account_status": account_status, "sizing_mode": sizing_mode,
                   "price_freshness": price_freshness}
    # 持仓恒列入 S1 + 语义(4.2 S2): 注入"持仓 ∖ top-N"(Tier 路由 / 价格门旁路 / 语义经持仓 provider 注入 advisory);选股、引擎决策、user-stop 不变。
    holding_normalized, holding_meta, holdings_manual_review = ([], {}, [])
    if args.account:
        cand_codes = {str(c.get("ts_code")) for c in cands}
        # 4.2 S2: 持仓 semantic provider(全持仓覆盖,cap=持仓数 绕 Top15;real fetch 同候选 gated on --confirm + 未 --skip-semantic;
        # 注入优先用于测试)。持仓涉真实持仓 → 结果走 weekly_private 私密路由(带 --account 自动私密,见 _reject_nonprivate_account_output_path)。
        h_codes = sorted({str(p.get("ts_code")) for p in (acct.get("positions") or [])} - cand_codes)
        if holding_semantic_provider is None and h_codes and args.confirm_fetch_authorized and not args.skip_semantic:
            holding_semantic_provider = _build_cninfo_semantic_provider(
                h_codes, args.as_of, args.cninfo_lookback_days, cap=len(h_codes))
        if holding_web_llm_provider is None and h_codes and args.confirm_fetch_authorized and not args.skip_semantic:
            h_names = {str(p.get("ts_code")): str(p.get("name") or "") for p in (acct.get("positions") or [])}
            holding_web_llm_provider = _build_deepseek_web_llm_provider(
                h_codes, h_names, args.as_of, args.web_news_lookback_days, cap=len(h_codes))
        holding_normalized, holding_meta, holdings_manual_review = _build_holdings(
            acct, cand_codes, args.as_of, price_provider, iv_pct, account, regime,
            regime_fallback, price_data_through, iv_value=iv_value, hv_value=hv_value,
            semantic_provider=holding_semantic_provider, web_llm_provider=holding_web_llm_provider)
    weekly = build_weekly_report(normalized + holding_normalized, args.as_of, gen,
                                 iv_feed_ref=os.path.basename(args.iv_feed), run_lineage=run_lineage,
                                 available_cash=(available_cash if args.account else None))   # #3 全局现金分配仅 sized 模式
    # S1: 每行打 row_source / coverage_status;持仓行挂 4.3-D 对账警告;无价/停牌持仓单列 manual_review。
    held_codes_all = {str(p.get("ts_code")) for p in (acct.get("positions") or [])}
    cons_by = _load_account_consistency_warnings(args.account) if args.account else {}
    for rep in weekly["reports"]:
        code = rep["ts_code"]
        if code in holding_meta:
            rep["row_source"] = holding_meta[code]["row_source"]
            rep["coverage_status"] = holding_meta[code]["coverage_status"]
        elif code in held_codes_all:
            rep["row_source"], rep["coverage_status"] = "egs_candidate_with_position", "full"
        else:
            rep["row_source"], rep["coverage_status"] = "egs_candidate", "full"
        if cons_by.get(code):
            rep["consistency_warning"] = cons_by[code]
    if holdings_manual_review:
        weekly["holdings_manual_review"] = holdings_manual_review
    # #1 除权除息提示(advisory):候选 + 账户持仓近端将除权 → 提示(PIT;不改任何决策)。
    _exdiv_codes = [(str(c.get("ts_code")), c.get("name", "")) for c in cands]
    _exdiv_codes += [(str(p.get("ts_code")), p.get("name", "")) for p in (acct.get("positions") or [])]
    _notices = _ex_div_notices(_exdiv_codes, args.as_of, dividend_provider)
    if _notices:
        weekly["ex_div_notices"] = _notices
    # 4.2 forward_events 第1刀: 未来已知事件日历(analysis-only advisory;候选+持仓近端限售解禁)。恒 set(checked/unknown)——
    # unknown-not-clear: unlock_provider 不可用(无 --confirm/未授权)→ status=unknown_or_unavailable(绝不当「无未来事件」)。
    weekly["upcoming_events"] = _upcoming_events(_exdiv_codes, args.as_of, unlock_provider)
    # 4.2 forward_events row landing: upcoming events 按 ts_code 落到对应 report 逐票 operation_impact + 风控触发文本(advisory,不改决策)。
    _attach_forward_event_impacts(weekly, args.as_of)
    # 4.2 Round2: 上游过滤批次级摘要(counts-only, public) — 复用 analysis_input.universe_summary.excluded_counts
    # (egs_main filter_l0 已记 unlock/suspended/relisted/holder_reduction_veto_10d), 不改 egs_main、不抓数。
    _excl = _build_exclusion_summary((ai.get("universe_summary") or {}).get("excluded_counts") or {}, args.as_of)
    if _excl:
        weekly["exclusion_summary"] = _excl
    from runners.a_short_m67_render import write_weekly_markdown
    md_path = os.path.splitext(args.out)[0] + ".md"
    write_weekly_report(weekly, feed, args.out)
    write_weekly_markdown(weekly, md_path)
    actions = {}
    for r in weekly["reports"]:
        actions[r["m67"]["table"]["操作"]] = actions.get(r["m67"]["table"]["操作"], 0) + 1
    print(f"[weekly] n={weekly['n_stocks']} actions={actions} iv_pct={iv_pct} -> {args.out} (+ {md_path})")


if __name__ == "__main__":
    main()
