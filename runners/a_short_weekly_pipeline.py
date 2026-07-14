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
import hashlib
import json
import os
import re
import sys
import tempfile
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
PRESET_PATH = ROOT / "presets" / "a_short.yaml"
HOLDING_RATCHET_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                           "schemas", "a_short_holding_ratchet.schema.json")
# S3b R4b: 跨周持久收紧 ratchet sidecar 默认路径(gitignored 私密 `state/a_short/holding_ratchet/`;含真实持仓 → 写前过私密路径守门)。
HOLDING_RATCHET_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                            "state", "a_short", "holding_ratchet", "ratchet_state.json")


def _validate_official_publish_marker(analysis_path: str | Path, marker: dict,
                                      source_identity: dict) -> None:
    """Bind the consumed analysis file bytes to the final EGS publish marker."""
    if marker.get("stage_status") != "complete" or \
            marker.get("run_id") != source_identity.get("run_id") or \
            marker.get("candidate_digest") != source_identity.get("candidate_digest"):
        raise SystemExit("[FATAL] official publish marker does not match analysis_input run identity")
    file_ref = ((marker.get("files") or {}).get("analysis_input") or {})
    path = Path(analysis_path)
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if file_ref.get("path") != path.name or file_ref.get("sha256") != actual_sha:
        raise SystemExit("[FATAL] official publish marker does not bind the consumed analysis_input bytes")


def _is_valid_date(s) -> bool:
    # 严格 canonical(P1 修复,与 engine _is_valid_date 同口径):strptime 单用会接受 '202606 5'/'2026065',
    # 非真 canonical;account/事件日期等契约门必须拒非规范值。要求恰好 8 个 ASCII 数字 + 合法历法日。
    from datetime import datetime
    t = str(s)
    if len(t) != 8 or not (t.isascii() and t.isdigit()):
        return False
    try:
        datetime.strptime(t, "%Y%m%d")
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

    # A-short 主板边界(消费真相源处强制,P1 修复):converter 输入层已校 is_a_share_main_board,但手写/外部生成的
    # account_state.json 可绕过 converter → 在此对 positions/rule13 的 ts_code 同样校验,拒 B股/非主板/畸形码进持仓状态。
    from engine.data.a_share_board_scope import is_a_share_main_board
    seen_pos = set()
    for idx, pos in enumerate(account.get("positions") or []):
        code = str(pos.get("ts_code"))
        if not is_a_share_main_board(code):
            raise SystemExit(f"[FATAL] --account positions[{idx}].ts_code {code} 非 A 股主板(A-short 只操作主板)")
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
        if not is_a_share_main_board(code):
            raise SystemExit(f"[FATAL] --account rule13_cooldowns[{idx}].ts_code {code} 非 A 股主板(A-short 只操作主板)")
        if code in seen_cd:
            raise SystemExit(f"[FATAL] --account rule13_cooldowns 含重复 ts_code {code}")
        seen_cd.add(code)
        _date_leq_as_of(cd.get("exit_date"), as_of, f"rule13_cooldowns[{idx}].exit_date")
        if cd.get("cooldown_until") is not None and not _is_valid_date(cd.get("cooldown_until")):
            raise SystemExit(f"[FATAL] --account rule13_cooldowns[{idx}].cooldown_until 非合法 YYYYMMDD")
        if cd.get("status") == "active_cooldown" and str(cd.get("cooldown_until") or "") < str(as_of):
            raise SystemExit(f"[FATAL] --account Rule13 {code} active_cooldown 已过期;请更新为 pending_recheck/cleared_for_reentry")
    return account


def load_account_bundle(path: str, decision_as_of: str) -> tuple[dict, dict, dict]:
    """Load the only production-facing A-short account input: one bound account+lineage bundle.

    Legacy bare ``a_short_account_state`` files are rejected because they cannot prove the true facts
    date or that the account and lineage came from the same converter publication.
    """
    try:
        with open(path, encoding="utf-8") as f:
            bundle = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"[FATAL] --account bundle 无法读取/解析: {exc}") from exc
    if not isinstance(bundle, dict) or bundle.get("schema_name") != "a_short_account_bundle":
        raise SystemExit(
            "[FATAL] --account 必须是 a_short_account_bundle；旧裸 account_state 无法证明真实 facts_as_of/"
            "account-lineage 同批，须先用转换器重新生成")
    from runners.a_short_account_state_from_manual_tables import ConvertError, validate_account_bundle
    try:
        validate_account_bundle(bundle, decision_as_of)
    except ConvertError as exc:
        raise SystemExit(str(exc)) from exc
    return bundle["account"], bundle["lineage"], bundle


def load_bucket_ceiling_pct(path: Path = PRESET_PATH) -> float:
    """Load the A-short capital ceiling from its reviewed preset; fail closed on drift/missing data."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"[FATAL] 无法读取 A-short capital preset {path}: {exc}") from exc
    match = re.search(r"(?m)^\s{2}bucket_ceiling_pct:\s*([0-9]+(?:\.[0-9]+)?)\s*(?:#.*)?$", text)
    value = float(match.group(1)) if match else None
    if value is None or not (0 < value <= 1):
        raise SystemExit("[FATAL] presets/a_short.yaml capital.bucket_ceiling_pct 缺失/非法")
    return value


def account_integrity_from_lineage(lineage: dict) -> dict:
    """Classify converter reconciliation evidence; ambiguity blocks only new entries."""
    warnings = list((lineage or {}).get("consistency_warnings") or [])
    blocking = [w for w in warnings if w.get("kind") in {"net_buy_not_in_positions", "shares_mismatch"}]
    return {
        "status": "blocked" if blocking else "clear",
        "blocking_kinds": sorted({str(w.get("kind")) for w in blocking}),
        "blocking_count": len(blocking),
        "new_entry_blocked": bool(blocking),
    }


def account_consistency_warnings_by_code(lineage: dict) -> dict:
    """Return the bound bundle's reconciliation warnings keyed by security code."""
    out = {}
    for warning in (lineage or {}).get("consistency_warnings") or []:
        code = str(warning.get("ts_code") or "")
        if code:
            out[code] = str(warning.get("message") or "")
    return out


def stateful_risk_for_candidate(account: dict | None, ts_code: str, as_of: str,
                                account_integrity: dict | None = None) -> dict:
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
        "account_integrity": dict(account_integrity or {"status": "clear", "blocking_kinds": [],
                                                        "blocking_count": 0, "new_entry_blocked": False}),
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
    integrity = ctx["account_integrity"]
    if integrity.get("new_entry_blocked"):
        if has_position:
            ctx["reasons"].append("account_integrity blocked:已有持仓仅管理/禁止加仓")
        else:
            ctx["reasons"].append("account_integrity blocked:持仓对账未闭环,禁止新开仓")
    return ctx


def _build_holdings(acct, cand_codes, as_of, price_provider, iv_pct, account, regime,
                    regime_fallback, price_data_through, egs_full=None, iv_value=None, hv_value=None,
                    semantic_provider=None, web_llm_provider=None, account_integrity=None):
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
                                stateful_risk=stateful_risk_for_candidate(
                                    acct, code, as_of, account_integrity=account_integrity),
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
    fund = cand.get("fundamental", {}) or {}
    prof = fund.get("profitability", {}) or {}      # 4.2 财报质量①(复用):egs_main 已取的 fina_indicator 派生(零新取数)
    fqual = fund.get("quality", {}) or {}
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
        # 4.2 财报质量①(复用,comparison-only):egs_main 已取的 fina_indicator 派生(扣非净利/同比/ROE/经营现金流质量/质量旗标),
        # 仅作为 advisory operation_impact 在 M6.7 解释,**绝不改 EGS/选股/股数/否决**(这些值本就已被 EGS 评分消费,此处只落地透明化)。
        "financial_quality": {
            "roe": prof.get("roe"),
            "q0_dt_yoy": prof.get("q0_dt_yoy"), "q1_dt_yoy": prof.get("q1_dt_yoy"),
            "q0_profit_dedt": prof.get("q0_profit_dedt"), "ttm_profit_dedt": prof.get("ttm_profit_dedt"),
            "q0_net_income": prof.get("q0_net_income"),
            "ttm_ocf_ratio": fqual.get("ttm_ocf_ratio"),
            "l2_flags": sc.get("l2_flags"),
        },
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


def _allocate_cash(reports: list, available_cash, new_exposure_capacity=None) -> dict:
    """#3 全局现金分配(价格提案 §4 + §11.3/11.4):多只建仓按**区间上沿 entry_high**(最不利价)统一消耗
    available_cash,确定性排序;不足一手/最小金额 → 转观察。**原地改 reports(只动建仓票)**;返回 weekly 现金摘要 | None。
    只 re-rank 建仓,不 rescue hard veto、不把观察/否决变建仓、不碰持仓/Rule12·13。"""
    from runners.a_short_phase5_engine import MIN_SHARES, MIN_AMOUNT
    if available_cash is None:
        return None
    builds = [(i, r) for i, r in enumerate(reports) if r["m67"]["table"]["操作"] == "建仓"]

    def _key(ir):
        i, r = ir
        es = r["machine"]["entry_exit_size_star"]; plan = es.get("plan") or {}
        return (-(es.get("star") or 0), -(r["m67"]["table"].get("EGS分") or 0),
                -(plan.get("rr_at_entry_high") or 0.0), -(plan.get("avg_amount_5d") or 0.0),
                i, str(r.get("ts_code", "")))     # original_topN_rank=i;ts_code 末位 tie-break 保确定性

    remaining, allocated_total = max(0.0, float(available_cash)), 0.0
    exposure_remaining = (None if new_exposure_capacity is None
                          else max(0.0, float(new_exposure_capacity)))
    for rank, (i, r) in enumerate(sorted(builds, key=_key), start=1):
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        eh, raw = plan["entry_high"], plan["shares"]
        effective_remaining = remaining if exposure_remaining is None else min(remaining, exposure_remaining)
        affordable = int(effective_remaining // eh // 100) * 100 if eh > 0 else 0
        allocated = min(raw, affordable)
        if allocated < MIN_SHARES or allocated * eh < MIN_AMOUNT:
            _demote_build_to_observe(r, rank)        # 不足 → 转观察(不输出按上沿买不起的建仓)
            continue
        cost = round(allocated * eh, 2)              # 2dp:与展示/审计的 cash_budget_used 同口径,摘要可精确对账
        remaining -= cost; allocated_total += cost
        if exposure_remaining is not None:
            exposure_remaining -= cost
        plan["raw_shares"], plan["shares"], plan["allocated_shares"] = raw, allocated, allocated
        plan["cash_budget_used"], plan["cash_allocation_rank"] = cost, rank
        r["m67"]["table"]["股数"] = allocated         # table 同步 plan(过 validator 建仓一致性)
        if allocated < raw:
            r["m67"]["精简结论区"]["操作建议"] += f"(组合现金分配:股数由 {raw} 降至 {allocated},占用现金 {cost})"
    summary = {"available_cash_start": round(float(available_cash), 2),
               "allocated_cash_total": round(allocated_total, 2), "remaining_cash": round(remaining, 2)}
    if new_exposure_capacity is not None:
        summary.update({"new_exposure_capacity_start": round(float(new_exposure_capacity), 2),
                        "remaining_new_exposure_capacity": round(exposure_remaining, 2)})
    return summary


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
            "m67_text": "本轮上游过滤(无 M6.7 个股行,批次级;按原因计数、可能重叠、非去重票数): " + "、".join(parts) + "。",
            "evidence_ref": {"kind": "lineage_key",
                             "value": _EXCL_EVIDENCE_LINEAGE_KEY,
                             "as_of": str(as_of)}}


def build_weekly_report(normalized_list: list, as_of: str, generated_at: str,
                        iv_feed_ref: str = "", run_lineage: dict = None, available_cash=None,
                        new_exposure_capacity=None) -> dict:
    from runners.a_short_phase5_engine import build_m67_report, build_holding_report
    # 持仓恒列入 S1: 标了 egs_coverage="uncovered" 的(Tier-3 粗筛未覆盖持仓)走 build_holding_report
    # (不跑 EGS 风险分类,避免在缺失数据上伪造 veto);其余(候选 / Tier-1 / Tier-2)走 build_m67_report。
    reports = [(build_holding_report(n, as_of, generated_at)
                if n.get("egs_coverage") == "uncovered" else build_m67_report(n, as_of, generated_at))
               for n in normalized_list]
    cash_summary = _allocate_cash(reports, available_cash, new_exposure_capacity)
    # run_lineage ties the consumed selection + IV feed + account/sizing status to this M6.7 artifact
    # (Slice 3b-2: selection 在 result/a_short、M6.7 在 research lane,靠此机器可读 lineage 绑定);
    # default = no-account observation-only,使直接 builder/测试仍 schema-valid。
    fallback_digest = hashlib.sha256(json.dumps(
        [n.get("ts_code") for n in normalized_list], ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    lineage = dict(run_lineage) if run_lineage is not None else {
        "run_id": f"a-short-{as_of}-{fallback_digest[:16]}",
        "candidate_digest": fallback_digest,
        "stage_status": "complete",
        "analysis_input": "", "selection_bucket": "", "iv_feed": iv_feed_ref,
        "account_ref": "",
        "account_status": "absent", "sizing_mode": "observation_only_no_account",
        "account_snapshot": None,
        "price_freshness": {"mode": "strict_as_of", "run_date": None,
                            "accepted_prior_settled_date": None, "price_data_through": str(as_of)}}
    lineage.setdefault("run_id", f"a-short-{as_of}-{fallback_digest[:16]}")
    lineage.setdefault("candidate_digest", fallback_digest)
    lineage.setdefault("stage_status", "complete")
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
    if rl.get("stage_status") != "complete":
        raise ValueError("run_lineage.stage_status must be complete before publish")
    if not re.fullmatch(rf"a-short-{weekly['as_of']}-[0-9a-f]{{16}}", str(rl.get("run_id") or "")):
        raise ValueError("run_lineage.run_id is not bound to weekly as_of")
    if not re.fullmatch(r"[0-9a-f]{64}", str(rl.get("candidate_digest") or "")):
        raise ValueError("run_lineage.candidate_digest is invalid")
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
    snap = rl.get("account_snapshot")
    if sized:
        if not isinstance(snap, dict):
            raise ValueError("run_lineage=(provided,sized) 但 account_snapshot 非对象")
        if snap.get("decision_as_of") != weekly.get("as_of"):
            raise ValueError("run_lineage.account_snapshot.decision_as_of 与周报 as_of 不一致")
        if str(snap.get("facts_as_of") or "") > str(weekly.get("as_of") or ""):
            raise ValueError("run_lineage.account_snapshot.facts_as_of 晚于周报 as_of")
        if snap.get("integrity_status") == "blocked" and not snap.get("blocking_kinds"):
            raise ValueError("account_snapshot integrity_status=blocked 但无 blocking_kinds")
        if snap.get("blocking_count", 0) < len(snap.get("blocking_kinds") or []):
            raise ValueError("account_snapshot blocking_count 小于 blocking_kinds 数量")
    elif snap is not None:
        raise ValueError("无账户 observation-only 报告不得带 account_snapshot")
    ivf = rl.get("iv_freshness")
    pf = rl.get("price_freshness") or {}
    if ivf is not None:
        if ivf.get("status") != "aligned" or ivf.get("iv_data_through") != pf.get("price_data_through") or \
                ivf.get("price_data_through") != pf.get("price_data_through"):
            raise ValueError("run_lineage.iv_freshness 未与 price_freshness.price_data_through 对齐")
    mr = rl.get("market_regime")
    if mr is not None:
        source = mr.get("source_status")
        effective = mr.get("effective_status")
        if source in ("unknown", "missing"):
            if effective != "shock" or mr.get("effective_regime") != "震荡期" or not mr.get("fallback_active"):
                raise ValueError("unknown/missing production regime 必须 fail-closed 为 effective shock/震荡期")
        elif effective != source or mr.get("fallback_active"):
            raise ValueError("已知 production regime 的 source/effective/fallback 不一致")
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
        if "new_exposure_capacity_start" in ca:
            exp_start = ca["new_exposure_capacity_start"]
            exp_rem = ca["remaining_new_exposure_capacity"]
            if abs(exp_rem - (exp_start - total)) > 0.011 or exp_rem < -0.011:
                raise ValueError("cash_allocation bucket 新增敞口额度对账失败")
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
        # main() 调用顺序)——reports[] 行须有 forward_event_{type} operation_impact(per-(票,类));只在 manual_review 的票须 reason 含落地标记。
        if _ue.get("status") == "checked":
            _rep_by = {r["ts_code"]: r for r in weekly["reports"]}
            _mr_by = {h["ts_code"]: h for h in (weekly.get("holdings_manual_review") or [])}
            for _e in _uevs:
                _rep = _rep_by.get(_e["ts_code"])
                if _rep is not None:
                    _expect_sf = f"forward_event_{_e['event_type']}"
                    if not any(i.get("source_field") == _expect_sf
                               for i in ((_rep.get("machine") or {}).get("operation_impact") or [])):
                        raise ValueError(f"upcoming_events event {_e['ts_code']}/{_e['event_type']} 未落到该 report 逐票 operation_impact(forward_event 悬空)")
                elif _FORWARD_EVENT_MARKER not in str((_mr_by.get(_e["ts_code"]) or {}).get("reason", "")):
                    raise ValueError(f"upcoming_events event {_e['ts_code']} 未落到 holdings_manual_review reason(forward_event 悬空)")
        # per-code coverage(PARTIAL-UNKNOWN): unchecked_codes 的 ts_code 也须 ∈ 候选/持仓集(不张冠李戴)
        for _uc in (_ue.get("unchecked_codes") or []):
            if _uc["ts_code"] not in _valid_codes:
                raise ValueError(f"upcoming_events unchecked_codes ts_code {_uc['ts_code']} 不在本周候选/持仓集")
    # 反向 evidence guard(IMPACT-EVIDENCE-GUARD-GAP):每个 report 的 forward_event_ impact 必须有匹配的 checked calendar event
    # (同 ts_code + event_type),否则=伪造/悬空 advisory(日历无此事件/不支持类型)。与上面的正向落地强制成双向闭合;放 _ue block
    # 外以 catch _ue=None/unknown 却有 impact 的伪造。不删 marker guard(engine ⑫,第二层)——双层。
    _checked_evs = {(_e["ts_code"], _e["event_type"]) for _e in ((_ue or {}).get("events") or [])
                    if (_ue or {}).get("status") == "checked"}
    for _r in weekly["reports"]:
        for _imp in ((_r.get("machine") or {}).get("operation_impact") or []):
            _sf = str(_imp.get("source_field", ""))
            if not _sf.startswith("forward_event_"):
                continue
            _etype = _sf[len("forward_event_"):]
            if _etype not in _FORWARD_EVENT_DATE_FIELD:        # 允许枚举=已注册类型(加新类先扩 _FORWARD_EVENT_* map + schema enum)
                raise ValueError(f"operation_impact {_sf}({_r['ts_code']}) event_type={_etype!r} 不在允许枚举(伪造/未支持类型)")
            if (_r["ts_code"], _etype) not in _checked_evs:
                raise ValueError(f"operation_impact {_sf}({_r['ts_code']}) 无匹配 checked upcoming_events 事件(impact 无证据/悬空)")
            if (_imp.get("evidence_ref") or {}).get("value") != f"upcoming_events.events[{_etype}]":
                raise ValueError(f"operation_impact {_sf}({_r['ts_code']}) evidence_ref.value 未对齐 upcoming_events.events[{_etype}]")
    # 4.2 财报质量趋势 financial_trends 一致性(analysis-only comparison-only **candidate-only**;schema 管类型/enum,此处管历法+PIT+张冠李戴+双向 no-dangling):
    # unknown 必空 records;checked 每 record: ts_code∈本周候选报告(**非持仓**——financial_trends candidate-only)、period/observed_at 合法、observed_at<=as_of(PIT)、
    # red_flags/summary 非空、且真落到该候选 report 逐票 operation_impact(financial_trend_{type})。复用上面的 _asd/_valid_codes/_dt。
    _ft = weekly.get("financial_trends")
    if _ft is not None:
        if _ft.get("as_of") != weekly["as_of"]:
            raise ValueError(f"financial_trends.as_of {_ft.get('as_of')} != 周报 as_of {weekly['as_of']}")
        _ftrecs = _ft.get("records") or []
        _ft_unck = _ft.get("unchecked_codes") or []
        _ft_status = _ft.get("status")
        if _ft_status == "unknown_or_unavailable" and _ftrecs:
            raise ValueError("financial_trends status=unknown_or_unavailable 却带 records(unknown 不得带红旗)")
        # COVERAGE-KEY-CONSISTENCY:unknown 路径不产 per-key 列表 → unknown 不得带 unchecked_codes
        if _ft_status == "unknown_or_unavailable" and _ft_unck:
            raise ValueError("financial_trends status=unknown_or_unavailable 却带 unchecked_codes(unknown 路径无 per-key 覆盖列表)")
        _rep_by_ft = {r["ts_code"]: r for r in weekly["reports"]}
        _rec_keys, _unck_keys = set(), set()
        for _rec in _ftrecs:
            if _rec["ts_code"] not in _valid_codes:
                raise ValueError(f"financial_trends ts_code {_rec['ts_code']} 不在本周候选/持仓集(张冠李戴)")
            try:
                _obs = _dt.strptime(_rec["observed_at"], "%Y%m%d")
                _per = _dt.strptime(_rec["period"], "%Y%m%d")
            except (ValueError, KeyError):
                raise ValueError(f"financial_trends period/observed_at 非合法日历日({_rec['ts_code']})")
            if _obs > _asd:
                raise ValueError(f"financial_trends observed_at 晚于 as_of(非 PIT/look-ahead;{_rec['ts_code']})")
            # REALIZED-PERIOD-PIT:income/balancesheet 是**已实现**报表,报告期 end_date 不得晚于 as_of(未来报告期=PIT 不可能;forecast 业绩预告可指未来期,豁免)
            if _rec.get("statement_type") in ("income", "balancesheet") and _per > _asd:
                raise ValueError(f"financial_trends {_rec['statement_type']} record {_rec['ts_code']} 报告期 {_rec['period']} 晚于 as_of(已实现报表未来期=非 PIT)")
            if not (_rec.get("red_flags") and _rec.get("summary")):
                raise ValueError(f"financial_trends record 无 red_flags/summary({_rec['ts_code']})")
            # COVERAGE-KEY-CONSISTENCY:(ts_code, statement_type) 是唯一覆盖键,records 内不得重复(同键证据重复 → 虚增/重复落点)
            _k = (_rec["ts_code"], _rec.get("statement_type"))
            if _k in _rec_keys:
                raise ValueError(f"financial_trends 重复 record (ts_code,statement_type)={_k}(同键证据重复)")
            _rec_keys.add(_k)
            if _ft_status == "checked":
                # row no-dangling(candidate-only):每个 checked 红旗 record 必须落到对应**候选**报告(非持仓)的逐票 operation_impact
                _rep = _rep_by_ft.get(_rec["ts_code"])
                if _rep is None:
                    raise ValueError(f"financial_trends record {_rec['ts_code']} 无对应候选报告(candidate-only,持仓不产红旗)")
                if ((_rep.get("machine") or {}).get("stateful_risk") or {}).get("position_state") == "held":
                    raise ValueError(f"financial_trends record {_rec['ts_code']} 落在持仓(held)报告(candidate-only,持仓财报趋势留后续刀)")
                _expect_sf = f"financial_trend_{_rec['statement_type']}"
                if not any(i.get("source_field") == _expect_sf
                           for i in ((_rep.get("machine") or {}).get("operation_impact") or [])):
                    raise ValueError(f"financial_trends record {_rec['ts_code']}/{_rec['statement_type']} 未落到该候选 report 逐票 operation_impact(财报趋势悬空)")
        # per-(票,类) coverage(COVERAGE-KEY-CONSISTENCY):unchecked_codes ts_code ∈ 候选/持仓集、唯一键、不得与 records 同键、candidate-only(非 held)
        for _uc in _ft_unck:
            if _uc["ts_code"] not in _valid_codes:
                raise ValueError(f"financial_trends unchecked_codes ts_code {_uc['ts_code']} 不在本周候选/持仓集")
            _uk = (_uc["ts_code"], _uc.get("statement_type"))
            if _uk in _unck_keys:
                raise ValueError(f"financial_trends 重复 unchecked_codes 键 {_uk}")
            _unck_keys.add(_uk)
            if _uk in _rec_keys:
                raise ValueError(f"financial_trends (ts_code,statement_type)={_uk} 同时为 record 与 unchecked(既查成又未查成,矛盾)")
            # candidate-only:unchecked_codes 同样不得是持仓(held)——持仓财报趋势留后续刀,不得把 held scope 泄漏进 candidate-only 顶层字段
            _ucrep = _rep_by_ft.get(_uc["ts_code"])
            if _ucrep is not None and ((_ucrep.get("machine") or {}).get("stateful_risk") or {}).get("position_state") == "held":
                raise ValueError(f"financial_trends unchecked_codes {_uc['ts_code']} 是持仓(held)(candidate-only,持仓财报趋势留后续刀)")
    # 反向 evidence guard:每个 report 的 financial_trend_ impact 必须有匹配的 checked financial_trends 红旗 record(同 ts_code + statement_type),
    # 否则=伪造/悬空 advisory。放 _ft block 外以 catch _ft=None/unknown 却有 impact 的伪造。与 engine guard ⑯ 双层(本层=证据对齐,engine=source-class 隔离)。
    _ft_recs_keyed = {(_r["ts_code"], _r["statement_type"]) for _r in ((_ft or {}).get("records") or [])
                      if (_ft or {}).get("status") == "checked"}
    for _r in weekly["reports"]:
        for _imp in ((_r.get("machine") or {}).get("operation_impact") or []):
            _sf = str(_imp.get("source_field", ""))
            if not _sf.startswith("financial_trend_"):
                continue
            _stype = _sf[len("financial_trend_"):]
            if _stype not in _FIN_RED_FLAG_FN:                # 允许枚举=已注册类型(加新类先扩 _FIN_RED_FLAG_FN map + schema enum)
                raise ValueError(f"operation_impact {_sf}({_r['ts_code']}) statement_type={_stype!r} 不在允许枚举(伪造/未支持类型)")
            if (_r["ts_code"], _stype) not in _ft_recs_keyed:
                raise ValueError(f"operation_impact {_sf}({_r['ts_code']}) 无匹配 checked financial_trends record(impact 无证据/悬空)")
            if (_imp.get("evidence_ref") or {}).get("value") != f"financial_trends.records[{_stype}]":
                raise ValueError(f"operation_impact {_sf}({_r['ts_code']}) evidence_ref.value 未对齐 financial_trends.records[{_stype}]")
    # 4.2 财报质量趋势 ⑤ industry_fundamentals 一致性(advisory-only summary_only candidate-scope;schema 管形态,此处管历法+张冠李戴+rollup↔源双向 + summary-only 必产):
    # SUMMARY-ONLY-ROLLUP(#4):financial_trends checked 有 income/balancesheet 红旗记录 ⟹ industry_fundamentals 必存在,并 roll 每个 unique 源码**恰一次**(不漏、不重);
    # 行业内 red_flag_codes 不得重复、跨行业每码恰一次、count==唯一码数;scope 必 candidates_only;rollup↔源双向。(行级 operation_impact 伪装见 engine guard ⑰)
    _bf_codes = {r["ts_code"] for r in ((_ft or {}).get("records") or [])
                 if (_ft or {}).get("status") == "checked" and r.get("statement_type") in ("income", "balancesheet")}
    _if = weekly.get("industry_fundamentals")
    if _bf_codes and _if is None:
        raise ValueError("financial_trends 有 income/balancesheet 红旗记录但缺 industry_fundamentals rollup(⑤ summary-only 必产行业上下文)")
    if _if is not None:
        if _if.get("as_of") != weekly["as_of"]:
            raise ValueError(f"industry_fundamentals.as_of {_if.get('as_of')} != 周报 as_of {weekly['as_of']}")
        if _if.get("scope") != "candidates_only":
            raise ValueError("industry_fundamentals scope 必须 candidates_only(候选 scope,非全行业普查)")
        _rolled = set()
        for _ind in (_if.get("by_industry") or []):
            _codes = _ind.get("red_flag_codes") or []
            if not _codes:
                raise ValueError(f"industry_fundamentals 行业 {_ind.get('sw_l2_name')} 无红旗候选(只列有红旗行业)")
            if len(set(_codes)) != len(_codes):
                raise ValueError(f"industry_fundamentals {_ind.get('sw_l2_name')} red_flag_codes 含重复码(同码聚合重复,虚增计数)")
            if _ind.get("red_flag_candidate_count") != len(set(_codes)):
                raise ValueError(f"industry_fundamentals {_ind.get('sw_l2_name')} red_flag_candidate_count 与 red_flag_codes 唯一数不符")
            if _ind.get("candidate_count", 0) < len(set(_codes)):
                raise ValueError(f"industry_fundamentals {_ind.get('sw_l2_name')} candidate_count(分母)< 红旗数")
            for _c in _codes:
                if _c not in _valid_codes:
                    raise ValueError(f"industry_fundamentals red_flag_codes {_c} 不在本周候选/持仓集(张冠李戴)")
                if _c not in _bf_codes:
                    raise ValueError(f"industry_fundamentals red_flag_codes {_c} 无对应 income/balancesheet financial_trends 记录(rollup 无源)")
                if _c in _rolled:
                    raise ValueError(f"industry_fundamentals red_flag_codes {_c} 在多个行业重复 rollup(每 unique 源码恰一次)")
                _rolled.add(_c)
        if _bf_codes - _rolled:                       # 反向:income/balancesheet 记录未进 rollup(行业聚合漏票)
            raise ValueError(f"financial_trends income/balancesheet 记录 {sorted(_bf_codes - _rolled)} 未进 industry_fundamentals rollup(行业聚合漏票)")
    # 4.2 Round5 龙虎榜 dragon_list 一致性(analysis-only comparison-only;schema 管类型/pattern,此处管历法+PIT+窗口+张冠李戴+双向 no-dangling):
    # unknown 必空 events;window_dates 合法且 <=as_of;checked 每 event: ts_code∈本周候选报告(events 只对候选生成)、trade_date 合法
    # 且 <=as_of(PIT:龙虎榜盘后发布)、∈window_dates;unchecked_dates ⊆ window_dates。复用上面的 _asd/_dt。
    _dl = weekly.get("dragon_list")
    if _dl is not None:
        if _dl.get("as_of") != weekly["as_of"]:
            raise ValueError(f"dragon_list.as_of {_dl.get('as_of')} != 周报 as_of {weekly['as_of']}")
        _wd = _dl.get("window_dates") or []
        _dlevs = _dl.get("events") or []
        if _dl.get("status") == "unknown_or_unavailable" and _dlevs:
            raise ValueError("dragon_list status=unknown_or_unavailable 却带 events(unknown 不得带上榜记录)")
        for _d in _wd:
            try:
                _dd = _dt.strptime(_d, "%Y%m%d")
            except ValueError:
                raise ValueError(f"dragon_list window_dates {_d} 非合法日历日")
            if (_dd - _asd).days > 0:
                raise ValueError(f"dragon_list window_dates {_d} 晚于 as_of(非 PIT)")
        _wdset = set(_wd)
        _dl_report_codes = {r["ts_code"] for r in weekly["reports"]}   # dragon events 对候选+账户持仓生成,均 ∈ reports
        for _e in _dlevs:
            if _e["ts_code"] not in _dl_report_codes:
                raise ValueError(f"dragon_list event ts_code {_e['ts_code']} 不在本周候选报告(张冠李戴/越界到非候选)")
            try:
                _td = _dt.strptime(_e["trade_date"], "%Y%m%d")
            except ValueError:
                raise ValueError(f"dragon_list event trade_date {_e['trade_date']} 非合法日历日({_e['ts_code']})")
            if (_td - _asd).days > 0:
                raise ValueError(f"dragon_list event trade_date 晚于 as_of(非 PIT;{_e['ts_code']})")
            if _e["trade_date"] not in _wdset:
                raise ValueError(f"dragon_list event trade_date {_e['trade_date']} 不在 window_dates(窗口外;{_e['ts_code']})")
        for _ud in (_dl.get("unchecked_dates") or []):
            if _ud not in _wdset:
                raise ValueError(f"dragon_list unchecked_dates {_ud} 不在 window_dates")
        # 第二刀 席位覆盖**双向闭合**(R-ASHORT-GAP42-ROUND5-DRAGON-SEATS-COVERAGE-GUARD-GAP):seats_status ⟺ 逐 event seats/inst_net_buy。
        # (a) 任一 event 带 seats/inst_net_buy ⟹ seats_status 必 checked(席位证据须有覆盖状态托管);
        # (b) seats_status=checked ⟹ 非 unchecked_seat_date 的每个 event 必带 seats(array)+ inst_net_buy(key,值可 null);
        # (c) unchecked_seat_date 上的 event 不得带 seats/inst_net_buy(席位未查成不附);
        # (d) seats_status=unknown_or_unavailable ⟹ 无 event 带 seats/inst_net_buy(unknown 不漏席位);
        # unchecked_seat_dates ⊆ window 且仅 checked 下有意义。
        _ss = _dl.get("seats_status")
        _usd = set(_dl.get("unchecked_seat_dates") or [])
        _has_any_seats = any(("seats" in _e or "inst_net_buy" in _e) for _e in _dlevs)
        if _has_any_seats and _ss != "checked":
            raise ValueError("dragon_list event 带 seats/inst_net_buy 但 seats_status 非 checked(席位证据无覆盖状态托管)")
        if _usd and _ss != "checked":
            raise ValueError("dragon_list unchecked_seat_dates 仅在 seats_status=checked 时有意义")
        for _ud in _usd:
            if _ud not in _wdset:
                raise ValueError(f"dragon_list unchecked_seat_dates {_ud} 不在 window_dates")
        if _ss == "checked":
            for _e in _dlevs:
                _has = ("seats" in _e) or ("inst_net_buy" in _e)
                if _e["trade_date"] in _usd:
                    if _has:
                        raise ValueError(f"dragon_list event {_e['ts_code']} 在 unchecked_seat_date {_e['trade_date']} 却带 seats/inst_net_buy(席位未查成日不应附)")
                else:
                    if "seats" not in _e or "inst_net_buy" not in _e:
                        raise ValueError(f"dragon_list event {_e['ts_code']} 席位查成日缺 seats/inst_net_buy(seats_status=checked 须逐 event 覆盖)")
                    if not isinstance(_e.get("seats"), list):
                        raise ValueError(f"dragon_list event {_e['ts_code']} seats 非数组")
        elif _ss == "unknown_or_unavailable":
            for _e in _dlevs:
                if "seats" in _e or "inst_net_buy" in _e:
                    raise ValueError(f"dragon_list seats_status=unknown_or_unavailable 却有 event 带 seats/inst_net_buy({_e['ts_code']})")
        # forward landing(checked):每 event 的候选 report 必须有 dragon_list_appearance impact(消费者强制,不靠 main 调用顺序)。
        if _dl.get("status") == "checked":
            # 覆盖闭合(R-ASHORT-GAP42-ROUND5-TRADE-EVENT-COVERAGE-PRIVACY-GUARD-GAP):checked 必须有实际查成的交易日 ——
            # window_dates 非空 且 (window_dates − unchecked_dates) 非空;无任何查成日应为 unknown(拒 checked-空窗口/全 unchecked)。
            if not _wd or not (set(_wd) - set(_dl.get("unchecked_dates") or [])):
                raise ValueError("dragon_list status=checked 但无任何实际查成交易日(window_dates 空 或 全在 unchecked_dates)→ 应为 unknown_or_unavailable")
            _dl_rep_by = {r["ts_code"]: r for r in weekly["reports"]}
            for _e in _dlevs:
                _rep = _dl_rep_by.get(_e["ts_code"])
                if _rep is not None and not any(
                        i.get("source_field") == "dragon_list_appearance"
                        for i in ((_rep.get("machine") or {}).get("operation_impact") or [])):
                    raise ValueError(f"dragon_list event {_e['ts_code']} 未落到该 report 逐票 dragon_list_appearance impact(悬空)")
    # 反向 evidence guard:每个 dragon_list_appearance impact 必须有匹配的 checked dragon_list 事件(同 ts_code)+ evidence_ref
    # 对齐 _DRAGON_LIST_EVIDENCE_VALUE,否则=伪造/悬空(无上榜证据)。与正向落地成双向闭合;放 _dl block 外 catch _dl=None/unknown 却有 impact。
    _dl_ev_codes = {_e["ts_code"] for _e in ((_dl or {}).get("events") or []) if (_dl or {}).get("status") == "checked"}
    for _r in weekly["reports"]:
        for _imp in ((_r.get("machine") or {}).get("operation_impact") or []):
            if str(_imp.get("source_field", "")) != "dragon_list_appearance":
                continue
            if _r["ts_code"] not in _dl_ev_codes:
                raise ValueError(f"operation_impact dragon_list_appearance({_r['ts_code']}) 无匹配 checked dragon_list 事件(impact 无证据/悬空)")
            if (_imp.get("evidence_ref") or {}).get("value") != _DRAGON_LIST_EVIDENCE_VALUE:
                raise ValueError(f"operation_impact dragon_list_appearance({_r['ts_code']}) evidence_ref.value 未对齐 {_DRAGON_LIST_EVIDENCE_VALUE}")
    # 4.2 Round5 大宗交易 block_trade 一致性(analysis-only comparison-only;镜像 dragon_list,无席位):历法 + PIT + 窗口 + 张冠李戴 + 双向 no-dangling。
    _bt = weekly.get("block_trade")
    if _bt is not None:
        if _bt.get("as_of") != weekly["as_of"]:
            raise ValueError(f"block_trade.as_of {_bt.get('as_of')} != 周报 as_of {weekly['as_of']}")
        _btwd = _bt.get("window_dates") or []
        _btevs = _bt.get("events") or []
        if _bt.get("status") == "unknown_or_unavailable" and _btevs:
            raise ValueError("block_trade status=unknown_or_unavailable 却带 events(unknown 不得带大宗记录)")
        for _d in _btwd:
            try:
                _dd = _dt.strptime(_d, "%Y%m%d")
            except ValueError:
                raise ValueError(f"block_trade window_dates {_d} 非合法日历日")
            if (_dd - _asd).days > 0:
                raise ValueError(f"block_trade window_dates {_d} 晚于 as_of(非 PIT)")
        _btwdset = set(_btwd)
        _bt_report_codes = {r["ts_code"] for r in weekly["reports"]}   # 候选+账户持仓 均 ∈ reports
        for _e in _btevs:
            if _e["ts_code"] not in _bt_report_codes:
                raise ValueError(f"block_trade event ts_code {_e['ts_code']} 不在本周候选报告(张冠李戴)")
            try:
                _td = _dt.strptime(_e["trade_date"], "%Y%m%d")
            except ValueError:
                raise ValueError(f"block_trade event trade_date {_e['trade_date']} 非合法日历日({_e['ts_code']})")
            if (_td - _asd).days > 0:
                raise ValueError(f"block_trade event trade_date 晚于 as_of(非 PIT;{_e['ts_code']})")
            if _e["trade_date"] not in _btwdset:
                raise ValueError(f"block_trade event trade_date {_e['trade_date']} 不在 window_dates(窗口外;{_e['ts_code']})")
            # 第二刀 parties no-dangling:checked block_trade event 必有 parties 且 len==trade_count(schema 焊 required+buyer/seller/amount keys;此处焊数量,
            # 防「买卖方第二刀」落成空/缺笔;party 值可 null=单元格空白,但每笔须有 buyer/seller/amount 键、笔数对齐)。
            if len(_e.get("parties") or []) != _e.get("trade_count"):
                raise ValueError(f"block_trade event {_e['ts_code']}/{_e['trade_date']} parties 数({len(_e.get('parties') or [])}) != trade_count({_e.get('trade_count')})(买卖方逐笔须与笔数一致)")
        for _ud in (_bt.get("unchecked_dates") or []):
            if _ud not in _btwdset:
                raise ValueError(f"block_trade unchecked_dates {_ud} 不在 window_dates")
        # 4.2 Round5 第三刀 折价率覆盖一致性(镜像席位 seats 覆盖;unknown-not-clear):
        # (a) 任何 event 带 close 或 party 带 discount ⟹ discount_status=checked(折价证据须有覆盖状态托管);
        # (b) checked ⟹ 非 unchecked_discount_date 的 event 必带 close(值可 null)且其每 party 必带 price + discount 键(值可 null,但 price 证据键必须在,否则折价层缺料却标 checked);
        # (c) unchecked_discount_date 上的 event 不得带 close/discount;(d) unknown ⟹ 无 close/discount。unchecked_discount_dates ⊆ window 且仅 checked 有意义。
        _ds = _bt.get("discount_status")
        _udd = set(_bt.get("unchecked_discount_dates") or [])
        _has_any_disc = any(("close" in _e) or any("discount" in (_p or {}) for _p in (_e.get("parties") or [])) for _e in _btevs)
        if _has_any_disc and _ds != "checked":
            raise ValueError("block_trade event 带 close/discount 但 discount_status 非 checked(折价证据无覆盖状态托管)")
        if _udd and _ds != "checked":
            raise ValueError("block_trade unchecked_discount_dates 仅在 discount_status=checked 时有意义")
        for _ud in _udd:
            if _ud not in _btwdset:
                raise ValueError(f"block_trade unchecked_discount_dates {_ud} 不在 window_dates")
        if _ds == "checked":
            for _e in _btevs:
                _hasc = ("close" in _e) or any("discount" in (_p or {}) for _p in (_e.get("parties") or []))
                if _e["trade_date"] in _udd:
                    if _hasc:
                        raise ValueError(f"block_trade event {_e['ts_code']} 在 unchecked_discount_date {_e['trade_date']} 却带 close/discount(折价未查成日不应附)")
                else:
                    if "close" not in _e:
                        raise ValueError(f"block_trade event {_e['ts_code']} 折价查成日缺 close(discount_status=checked 须逐 event 覆盖)")
                    for _p in (_e.get("parties") or []):
                        if "price" not in (_p or {}) or "discount" not in (_p or {}):
                            raise ValueError(f"block_trade event {_e['ts_code']} 折价查成日 party 缺 price/discount 键(discount_status=checked 须逐笔带 price 证据 + discount;值可 null 但键必须在)")
        elif _ds == "unknown_or_unavailable":
            for _e in _btevs:
                if ("close" in _e) or any("discount" in (_p or {}) for _p in (_e.get("parties") or [])):
                    raise ValueError(f"block_trade discount_status=unknown_or_unavailable 却有 event 带 close/discount({_e['ts_code']})")
        if _bt.get("status") == "checked":
            # 覆盖闭合(同 dragon_list):checked 必须有实际查成的交易日 —— window_dates 非空 且 (window − unchecked) 非空,否则应为 unknown。
            if not _btwd or not (set(_btwd) - set(_bt.get("unchecked_dates") or [])):
                raise ValueError("block_trade status=checked 但无任何实际查成交易日(window_dates 空 或 全在 unchecked_dates)→ 应为 unknown_or_unavailable")
            _bt_rep_by = {r["ts_code"]: r for r in weekly["reports"]}
            for _e in _btevs:
                _rep = _bt_rep_by.get(_e["ts_code"])
                if _rep is not None and not any(
                        i.get("source_field") == "block_trade_appearance"
                        for i in ((_rep.get("machine") or {}).get("operation_impact") or [])):
                    raise ValueError(f"block_trade event {_e['ts_code']} 未落到该 report 逐票 block_trade_appearance impact(悬空)")
    # 反向 evidence guard:每个 block_trade_appearance impact 必须有匹配 checked block_trade 事件(同 ts_code)+ evidence_ref 对齐。
    _bt_ev_codes = {_e["ts_code"] for _e in ((_bt or {}).get("events") or []) if (_bt or {}).get("status") == "checked"}
    for _r in weekly["reports"]:
        for _imp in ((_r.get("machine") or {}).get("operation_impact") or []):
            if str(_imp.get("source_field", "")) != "block_trade_appearance":
                continue
            if _r["ts_code"] not in _bt_ev_codes:
                raise ValueError(f"operation_impact block_trade_appearance({_r['ts_code']}) 无匹配 checked block_trade 事件(impact 无证据/悬空)")
            if (_imp.get("evidence_ref") or {}).get("value") != _BLOCK_TRADE_EVIDENCE_VALUE:
                raise ValueError(f"operation_impact block_trade_appearance({_r['ts_code']}) evidence_ref.value 未对齐 {_BLOCK_TRADE_EVIDENCE_VALUE}")


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


def _replace_many_with_rollback(payloads: dict[str, bytes]) -> None:
    """Best-effort multi-file transaction for the small weekly publish set."""
    staged = {}
    old = {}
    replaced = []
    try:
        for path, data in payloads.items():
            absolute = os.path.abspath(path)
            os.makedirs(os.path.dirname(absolute), exist_ok=True)
            old[absolute] = Path(absolute).read_bytes() if os.path.exists(absolute) else None
            fd, tmp = tempfile.mkstemp(prefix=f".{Path(absolute).name}.", suffix=".tmp",
                                       dir=os.path.dirname(absolute))
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            staged[absolute] = tmp
        for absolute, tmp in staged.items():
            os.replace(tmp, absolute)
            replaced.append(absolute)
        staged.clear()
    except Exception:
        for absolute in reversed(replaced):
            previous = old[absolute]
            if previous is None:
                try:
                    os.unlink(absolute)
                except FileNotFoundError:
                    pass
            else:
                fd, restore = tempfile.mkstemp(prefix=f".{Path(absolute).name}.", suffix=".restore",
                                               dir=os.path.dirname(absolute))
                with os.fdopen(fd, "wb") as handle:
                    handle.write(previous)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(restore, absolute)
        raise
    finally:
        for tmp in staged.values():
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


def publish_weekly_bundle(weekly: dict, iv_feed_summary: dict, out_path: str, md_path: str,
                          *, allow_nonprivate_account_out: bool = False,
                          ratchet_publish: tuple[str, dict, str, str] | None = None) -> str:
    """Validate all final surfaces, then publish JSON/Markdown/ratchet/receipt together."""
    from runners.a_short_m67_render import render_weekly_markdown, _weekly_has_account_data

    _reject_production_output_path(out_path)
    if _weekly_has_account_data(weekly):
        _reject_nonprivate_account_output_path(md_path, True, allow_nonprivate_account_out)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        jsonschema.validate(weekly, json.load(f))
    with open(M67_SCHEMA_PATH, "r", encoding="utf-8") as f:
        m67schema = json.load(f)
    for report in weekly["reports"]:
        jsonschema.validate(report, m67schema)
    validate_weekly_report(weekly, iv_feed_summary)
    markdown = render_weekly_markdown(weekly)
    lineage = weekly["run_lineage"]
    receipt = {
        "schema_name": "a_short_weekly_publish_receipt",
        "schema_version": "1.0.0",
        "as_of": weekly["as_of"],
        "run_id": lineage["run_id"],
        "candidate_digest": lineage["candidate_digest"],
        "account_snapshot": lineage.get("account_snapshot"),
        "stage_status": "complete",
        "outputs": [os.path.basename(out_path), os.path.basename(md_path)],
    }
    receipt_path = os.path.splitext(out_path)[0] + ".receipt.json"
    payloads = {
        out_path: (json.dumps(weekly, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        md_path: markdown.encode("utf-8"),
        receipt_path: (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    }
    if ratchet_publish is not None:
        ratchet_path, state, as_of, generated_at = ratchet_publish
        ratchet_doc = _holding_ratchet_doc(state, as_of, generated_at)
        payloads[ratchet_path] = (json.dumps(ratchet_doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _replace_many_with_rollback(payloads)
    return receipt_path


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


def validate_iv_feed_freshness(iv_feed_summary: dict, price_data_through: str) -> dict:
    """Bind the consumed IV observation to the same settled clock as the price features."""
    series = iv_feed_summary.get("series") or []
    latest = str((series[-1] if series else {}).get("trade_date") or "")
    if not latest:
        raise SystemExit("[FATAL] IV feed 无可用 trade_date，无法执行 IV 新鲜度闸门")
    if latest != str(price_data_through):
        raise SystemExit(
            f"[FATAL] IV feed latest_trade_date {latest} != price_data_through {price_data_through};"
            "IV 与价格时钟不一致/陈旧，拒绝生成周报")
    return {"status": "aligned", "iv_data_through": latest,
            "price_data_through": str(price_data_through)}


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
# 4.2 forward_events per-type 元数据(builder emit event 用):provider rec 的事件日字段 / source_id / 置信度(解禁日确定=high;财报预约可改期=medium)/ 中文标签。
# 加第 N 类事件只在此 4 个 map + provider + schema enum 扩,builder/attach/validator/render/guard 全 type-agnostic。
_FORWARD_EVENT_DATE_FIELD = {"limit_unlock": "float_date", "earnings_disclosure": "pre_date"}
_FORWARD_EVENT_SOURCE_ID = {"limit_unlock": "tushare.share_float", "earnings_disclosure": "tushare.disclosure_date"}
_FORWARD_EVENT_CONFIDENCE = {"limit_unlock": "high", "earnings_disclosure": "medium"}
_FORWARD_EVENT_TYPE_LABEL = {"limit_unlock": "限售解禁", "earnings_disclosure": "财报预约披露"}


def _upcoming_events(code_names, as_of, unlock_provider, earnings_provider=None, window_days=FORWARD_EVENT_WINDOW_DAYS):
    """4.2 forward_events: 未来已知事件日历(analysis-only,**不改任何决策**;只进 M6.7 提示)。
    第1刀=限售解禁(limit_unlock,share_float float_date);第2刀=财报预约披露(earnings_disclosure,disclosure_date pre_date)。
    PIT 安全: 只收 `observed_at`(ann_date)<=as_of(已公告,非 look-ahead) 且 `as_of<=event_date<=as_of+window`
    的事件;每(票,类)取最近一次。每个 `provider(ts_code)` → list[{"ann_date", <_FORWARD_EVENT_DATE_FIELD[type]>}](YYYYMMDD|None)。
    **unknown-not-clear**: 全 provider 为 None(没授权取数/不可用)→ status=`unknown_or_unavailable`(绝不当「无未来事件」);
    全(票,类)取数失败→ 同 unknown;**部分(票,类)失败**→ status `checked` 但失败项进 `unchecked_codes`(per-(票,类)粒度,绝不把
    没查成的当「无事件」);跑成但某(票,类)真无近端事件 → 不计。非法/缺日期跳过(不伪造)。返回 {as_of,status,events[],unchecked_codes?}。
    type-agnostic: 加第 N 类事件只扩 `_FORWARD_EVENT_*` map + provider + schema enum,本函数不动。"""
    from datetime import datetime
    sources = [(unlock_provider, "limit_unlock"), (earnings_provider, "earnings_disclosure")]
    if all(p is None for p, _ in sources):
        return {"as_of": str(as_of), "status": "unknown_or_unavailable", "events": []}
    try:
        as_of_d = datetime.strptime(str(as_of), "%Y%m%d")
    except ValueError:
        raise ValueError(f"upcoming_events as_of {as_of!r} 非合法日历日")
    best, any_ok, unchecked = {}, False, []
    for provider, etype in sources:
        if provider is None:
            continue                                  # 该类未启用(无 provider)→ 不标 unchecked(区别于查询失败)
        date_field = _FORWARD_EVENT_DATE_FIELD[etype]
        for ts_code, name in code_names:
            try:
                recs = provider(ts_code)
            except Exception:
                recs = None                           # 单(票,类)查询失败 → 未查成
            if recs is None:
                unchecked.append({"ts_code": ts_code, "name": name or "", "event_type": etype})   # 未查成 → per-(票,类) unknown(不当无事件)
                continue                              # 不计 any_ok(区别于真无事件的 [])
            any_ok = True                             # 该(票,类)查成(含真无事件返回的空 list)
            for rec in recs:
                ed = (rec or {}).get(date_field)
                ann = (rec or {}).get("ann_date")
                if not ed or ann is None:
                    continue                          # 无事件日/无公告日 → 无法 PIT 证明,跳过(不伪造)
                try:
                    ed_d = datetime.strptime(str(ed), "%Y%m%d")
                    ann_d = datetime.strptime(str(ann), "%Y%m%d")
                except ValueError:
                    continue                          # 非法日期 → 跳过
                if ann_d > as_of_d:
                    continue                          # 公告晚于 as_of → look-ahead,跳过
                days = (ed_d - as_of_d).days
                if 0 <= days <= window_days:          # 近端将至(含当日)
                    key = (ts_code, etype)
                    if key not in best or days < best[key]["days_to_event"]:
                        best[key] = {"ts_code": ts_code, "name": name or "",
                                     "event_type": etype, "event_date": str(ed),
                                     "observed_at": str(ann), "source_id": _FORWARD_EVENT_SOURCE_ID[etype],
                                     "expected_effect": "manual_review", "confidence": _FORWARD_EVENT_CONFIDENCE[etype],
                                     "days_to_event": days}
    # unknown-not-clear(§4.4): 有 provider 但**所有(票,类)都没查成**(取数全失败)→ unknown_or_unavailable,
    # 绝不把「没查成」当「查了无未来事件」(只有真查成 — 含真无事件的空 — 才 checked)。
    if code_names and not any_ok:
        return {"as_of": str(as_of), "status": "unknown_or_unavailable", "events": []}
    events = sorted(best.values(), key=lambda e: (e["days_to_event"], e["ts_code"], e["event_type"]))
    out = {"as_of": str(as_of), "status": "checked", "events": events}
    if unchecked:                                     # 部分(票,类)未查成(全失败已上面 return unknown)→ per-(票,类) coverage,绝不静默当无事件
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


def _fetch_earnings_schedule(pro, ts_code: str):
    """4.2 forward_events 第2刀 真财报预约披露 provider: tushare `pro.disclosure_date`(逐票财报预约披露,**带公告日 ann_date 做
    PIT**)→ [{"ann_date","pre_date"}](YYYYMMDD|None;`pre_date`=预约披露日(未来),`actual_date` 通常空=未披露)。**fail-closed**:
    缺 ann_date/pre_date 列 → None(无法 PIT/数据形态异常→标未查成,不静默当真无);异常/None → None;空 → [](该票真无预约,查成了)。
    **仓库内未测真接口**: `pro.disclosure_date` 没跑过,真取数 gated --confirm;mock 注入可单测。字段名据 tushare 文档(ann_date/pre_date)。"""
    try:
        df = pro.disclosure_date(ts_code=ts_code, fields="ts_code,ann_date,pre_date,actual_date")
    except Exception:
        return None                                   # 取数失败 → 未查成(区别于真无预约的 [];builder 据此标 unknown)
    if df is None:
        return None                                   # provider 没返回 → 未查成
    if not {"ann_date", "pre_date"}.issubset(set(getattr(df, "columns", []))):
        return None                                   # 缺 PIT 列(数据形态异常)→ 未查成(不静默当真无)
    if getattr(df, "empty", True):
        return []                                     # 成功返回空 → 该票真无预约披露记录(查成了)
    def _clean(v):
        return str(v) if (v is not None and str(v).strip() not in ("", "nan", "None", "NaT")) else None
    return [{"ann_date": _clean(r.get("ann_date")), "pre_date": _clean(r.get("pre_date"))}
            for _, r in df.iterrows()]


def _attach_forward_event_impacts(weekly, as_of):
    """4.2 forward_events row landing(R-ASHORT-GAP42-FORWARD-EVENTS-ROW-LANDING-GUARD-GAP): 把 weekly-global
    upcoming_events 的每个事件按 ts_code 落到对应 report 的**逐票** M6.7 —— `machine.operation_impact`(候选→
    candidate_row_impact / 持仓→holding_row_impact)+ 精简结论区.风控触发 文本。**analysis-only**:veto_class=none、
    production_effect_enabled=False、new_entry_effect 非 hard_veto(绝不 hard_veto / 绝不 rescue 已有 hard veto /
    不改 操作·EGS·选股·TopN —— 只追加 advisory impact+文本)。status!=checked(unknown/无)→ 不落(不伪造逐票影响)。
    §4.4 影响:候选→manual_review、持仓→hold_watch + blocked_add(临近解禁谨慎加仓);hold_watch 不产 R3 减仓/清仓价(仅 reduce/clear disposition)→ price_cross 恒 none;移保本=R4a(disposition 无关,仅看浮盈);跨周持久收紧 ratchet=R4b。"""
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
        # 文本面 per-code 写一次(汇总所有 type 的 events;_evtxt 已含 event_type 详情)。
        txt = _evtxt(evs)
        cut = rep["m67"]["精简结论区"]
        prev = cut.get("风控触发") or "无"
        cut["风控触发"] = txt if prev in ("无", "") else f"{prev}|{txt}"
        # ADVICE-LANDING(R-...-ADVICE-LANDING-GAP):未来事件也落用户主看的 操作建议(不只风控触发),否则候选仍像干净建仓。
        # advisory 文本(不改 table 操作/EGS/TopN);候选→人工复核/谨慎建仓、持仓→持有观察/谨慎加仓;含 _FORWARD_EVENT_MARKER 供 guard 判落地。
        _adv = (f"⚠️ {_FORWARD_EVENT_MARKER}({len(evs)}项近端将至):"
                + ("持有观察、谨慎加仓" if held else "先人工复核/转观察/谨慎建仓")
                + ",不改 EGS/TopN/生产决策(advisory)")
        _ap = cut.get("操作建议") or ""
        cut["操作建议"] = f"{_ap}｜{_adv}" if _ap else _adv
        # 结构化 impact per-(票,类)(source_field=forward_event_{type}):validator 按 type 查逐票落地;一个 code 多类 → 多 impact。
        by_type = {}
        for e in evs:
            by_type.setdefault(e["event_type"], []).append(e)
        for etype, tevs in by_type.items():
            label = _FORWARD_EVENT_TYPE_LABEL[etype]
            rep["machine"].setdefault("operation_impact", []).append({
                "source_field": f"forward_event_{etype}",
                "field_class": "structured",
                "visibility_shape": "holding_row_impact" if held else "candidate_row_impact",
                "impact_scope": "existing_holding" if held else "new_entry",
                "new_entry_effect": "none" if held else "manual_review",
                "holding_effect": "hold_watch" if held else "none",
                "blocked_add_required": bool(held),
                "veto_class": "none",
                "reason": f"未来已知事件({label}){len(tevs)}项近端将至 → advisory 提示(不改决策/EGS/选股/TopN)",
                "evidence_ref": {"kind": "lineage_key", "value": f"upcoming_events.events[{etype}]", "as_of": str(as_of)},
                "confidence": "high",
                "pit_basis": "disclosure_date",
                "production_effect_enabled": False,
                "implementation_status": "implemented",  # S3b 已收官:held 信号经 _merge_holding_disposition 落持仓处置(已结构化),非 held 落操作建议
                "m67_landing_surface": "精简结论区.风控触发+操作建议(未来事件)",
                "terminal_surface_target": "s3b_持仓处置_列+减仓价" if held else "already_structured",
                "pending_successor_slice": None,  # S3b R1-R4b 已实现,held forward_event 不再 pending
                "privacy_class": "private_account" if held else "public_tracked",
            })
    # 4.2 forward_events: holdings_manual_review(无价/停牌/价格陈旧旁路持仓,无 machine 结构、只 ts_code/name/reason、不进
    # reports[])的票若有 checked 事件 → validator 接受(universe = reports ∪ holdings_manual_review)却无逐票行,故 append
    # 到该持仓 reason(render 直接渲染);advisory/人工管理本不下系统决策——不改 EGS/TopN/动作、不 veto/rescue、不 S3b 减仓。
    for h in (weekly.get("holdings_manual_review") or []):
        evs = by_code.get(h["ts_code"])
        if not evs:
            continue
        note = f"{_FORWARD_EVENT_MARKER}({len(evs)}项近端将至 → {_evtxt(evs)})(advisory,人工核查;不改决策)"
        h["reason"] = f"{h['reason']}｜{note}" if h.get("reason") else note


# ── 4.2 财报质量趋势(财报报表 per-stock fetch · analysis-only · comparison-only · candidate-only)──────────
# ②业绩预告 forecast / ③利润表 income / ④资产负债表 balancesheet:逐票新增报表取数 → **自然符号红旗**(tushare 自有分类 / 同期方向比较,
# **不新设阈值**·决策4)→ advisory priority_down operation_impact + 落 精简结论区.风控触发(财报趋势对照)。**candidate-only**(镜像①
# financial_quality;持仓财报趋势留后续刀,held 排除)、**绝不 hard_veto / 非生产 / 不改 EGS·TopN·选股·股数·否决**。镜像 forward_events
# type-agnostic 框架:加第 N 类报表只扩 _FIN_STATEMENT_*/_FIN_RED_FLAG_FN map + provider + red-flag fn + schema enum,builder/attach/validator/render/guard 全 type-agnostic。
# 与①区分:① 复用 egs_main 既有 fina_indicator(source_field=financial_quality、marker「财报质量对照」);本框架=**新增报表取数**(source_field=financial_trend_{type}、marker「财报趋势对照」)。
_FIN_STATEMENT_MARKER = "财报趋势对照"   # 风控触发 落地标记:_attach 写入 + engine guard ⑯ 据此判 row no-dangling(单一来源;字面同步 phase5_engine guard ⑯)
_FIN_STATEMENT_SOURCE_ID = {"forecast": "tushare.forecast", "income": "tushare.income", "balancesheet": "tushare.balancesheet"}
_FIN_STATEMENT_LABEL = {"forecast": "业绩预告", "income": "利润表", "balancesheet": "资产负债表"}
# tushare forecast.type 负面分类(自然分类红旗,**非阈值**;tushare 自有 enum,镜像①复用 EGS 既有 ESP-Q 旗标):预减/略减/首亏/续亏。
# 不含 扭亏/续盈/略增/预增(正面)——「扭亏」含「亏」但不含下列任一,substring 匹配安全。
_FORECAST_NEG_TYPES = ("预减", "略减", "首亏", "续亏")


def _fin_num(v):
    """财报字段数值清洗:非有限(NaN/Inf)/空/不可解析 → None(不伪造 0)。"""
    if v is None or str(v).strip() in ("", "nan", "None", "NaT"):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if (f == f and f not in (float("inf"), float("-inf"))) else None


def _fin_pit_periods(recs, as_of, realized=False):
    """财报报表 PIT helper:recs=[{"ann_date","end_date",...}],只保留 ann_date<=as_of(已公告,非 look-ahead)且 ann_date/end_date 合法,
    按 end_date 去重(同一报告期多次公告取 ann_date 最新=最终数)后按 end_date 倒序。返回 [(end_date, rec)](最近报告期在前)。
    非法/缺日期丢弃(不伪造)。**realized=True**(income/balancesheet 已实现报表):额外丢弃 end_date>as_of 的**未来报告期**
    (已实现报表的未来期=PIT 不可能;REALIZED-PERIOD-PIT-GUARD)。forecast(业绩预告可指未来期)用 realized=False(默认),不丢未来 end_date。"""
    from datetime import datetime
    try:
        as_of_d = datetime.strptime(str(as_of), "%Y%m%d")
    except ValueError:
        raise ValueError(f"financial_trends as_of {as_of!r} 非合法日历日")
    best = {}   # end_date(str) -> (ann_date(str), rec)
    for rec in (recs or []):
        ann, end = (rec or {}).get("ann_date"), (rec or {}).get("end_date")
        if not ann or not end:
            continue                              # 无公告日/报告期 → 无法 PIT,丢弃
        try:
            ann_d = datetime.strptime(str(ann), "%Y%m%d")
            end_d = datetime.strptime(str(end), "%Y%m%d")
        except ValueError:
            continue                              # 非法日期 → 丢弃
        if ann_d > as_of_d:
            continue                              # 公告晚于 as_of → look-ahead,丢弃
        if realized and end_d > as_of_d:
            continue                              # 已实现报表(income/balancesheet)未来报告期 → PIT 不可能,丢弃(forecast 豁免)
        if str(end) not in best or str(ann) > best[str(end)][0]:
            best[str(end)] = (str(ann), rec)      # 同报告期取最新公告(最终数,非更早预披)
    return [(end, best[end][1]) for end in sorted(best, reverse=True)]


def _yoy_period(end_date):
    """同比基期(去年同报告期):20250930→20240930、20251231→20241231。返回 YYYYMMDD。"""
    return f"{int(str(end_date)[:4]) - 1}{str(end_date)[4:]}"


def _fin_assessable(recs, as_of, stype):
    """coverage 判定(R-ASHORT-GAP42-FINANCIAL-TRENDS-PIT-FILTERED-COVERAGE-UNKNOWN-GAP):provider 返回**非空** recs 是否有
    PIT-valid 评估基础——用于区分「PIT-valid 已查无红旗(checked)」与「非空但全被 PIT 过滤、无评估基础(→unchecked,绝不当 checked 空)」。
    forecast/income:有任一 PIT-valid 期即可评(income q0 即可判亏损);balancesheet:全为 q0 vs 去年同期 q-4 比较,需 q0+q-4 都在才可评。
    **仅对非空 recs 调用**(真空 [] = 查成真无数据,由 builder 另判 checked)。"""
    realized = stype in ("income", "balancesheet")
    periods = _fin_pit_periods(recs, as_of, realized=realized)
    if not periods:
        return False                                  # 非空 recs 但无 PIT-valid 期(全被 ann_date/end_date 过滤)→ 无评估基础
    if stype == "balancesheet":
        ends = {e for e, _ in periods}
        return any(_yoy_period(e) in ends for e in ends)   # 全 YoY:需 q0 + 去年同期 q-4 都在,否则无可比基础
    return True


def _forecast_red_flags(recs, as_of):
    """②业绩预告 forecast 自然符号红旗(comparison-only,**不新设阈值**):取 PIT 最近一期业绩预告,红旗 =
    tushare 预告 type ∈ 负面分类(预减/略减/首亏/续亏,tushare 自有分类)**或** p_change_max<0(预告净利变动**上限**为负=必降,自然符号)。
    返回 (red_flags[], summary, period, observed_at) 或 None(无红旗/无可用数据)。绝不据此否决/改决策。"""
    periods = _fin_pit_periods(recs, as_of)
    if not periods:
        return None
    end, rec = periods[0]                          # PIT 最近一期预告
    ftype = str((rec or {}).get("type") or "").strip()
    pmin, pmax = _fin_num((rec or {}).get("p_change_min")), _fin_num((rec or {}).get("p_change_max"))
    flags = []
    if ftype and any(t in ftype for t in _FORECAST_NEG_TYPES):
        flags.append(f"业绩预告类型「{ftype}」(负面)")
    if pmax is not None and pmax < 0:
        flags.append(f"预告净利变动上限{pmax}%为负(必降)")
    if not flags:
        return None
    rng = (f";预告净利变动 {pmin if pmin is not None else '?'}~{pmax if pmax is not None else '?'}%"
           if (pmin is not None or pmax is not None) else "")
    return (flags, f"{'、'.join(flags)}{rng}(报告期{end})", str(end), str((rec or {}).get("ann_date")))


def _income_red_flags(recs, as_of):
    """③利润表 income 自然符号红旗(comparison-only,**不新设阈值**,income-only):PIT 最近报告期 q0 与去年同期 q-4(均 ann_date<=as_of)——
    红旗 = 归母净利润<0(亏损,q0 自然符号)/ 营收同比下滑(total_revenue q0<q-4)/ 毛利率同比下滑((revenue−oper_cost)/revenue q0<q-4)/
    净利率同比下滑(归母净利/total_revenue q0<q-4)。同比类需 q-4 可得(缺则只判亏损,绝不伪造)。利润表 cumulative(YTD,合并报表 report_type=1)同口径可比。
    返回 (red_flags[], summary, period, observed_at) 或 None。绝不据此否决/改决策。与①(扣非净利同比/ROE/现金流质量)互补,本刀聚焦 营收/毛利率/净利率/亏损。"""
    periods = _fin_pit_periods(recs, as_of, realized=True)   # income 已实现报表:丢弃未来报告期(REALIZED-PERIOD-PIT)
    if not periods:
        return None
    end, rec = periods[0]                          # PIT 最近报告期
    by_end = {e: r for e, r in periods}
    prior = by_end.get(_yoy_period(end))           # 去年同期(缺=None → 只判 q0 亏损)
    def _profit(r):                                # 归母净利(缺退总净利)
        v = _fin_num((r or {}).get("n_income_attr_p"))
        return v if v is not None else _fin_num((r or {}).get("n_income"))
    def _gm(r):                                    # 毛利率 =(营业收入−营业成本)/营业收入
        rev, cost = _fin_num((r or {}).get("revenue")), _fin_num((r or {}).get("oper_cost"))
        return (rev - cost) / rev if (rev not in (None, 0) and cost is not None) else None
    def _nm(r):                                    # 净利率 = 归母净利 / 营业总收入
        rev, ni = _fin_num((r or {}).get("total_revenue")), _profit(r)
        return ni / rev if (rev not in (None, 0) and ni is not None) else None
    flags, bits = [], []
    p0 = _profit(rec)
    if p0 is not None and p0 < 0:
        flags.append("归母净利润为负(亏损)")
        bits.append(f"归母净利{p0}")
    if prior is not None:
        r0, r1 = _fin_num((rec or {}).get("total_revenue")), _fin_num((prior or {}).get("total_revenue"))
        if r0 is not None and r1 is not None and r0 < r1:
            flags.append("营收同比下滑")
            bits.append(f"营收 {r1}→{r0}")
        g0, g1 = _gm(rec), _gm(prior)
        if g0 is not None and g1 is not None and g0 < g1:
            flags.append("毛利率同比下滑")
            bits.append(f"毛利率 {round(g1 * 100, 2)}%→{round(g0 * 100, 2)}%")
        n0, n1 = _nm(rec), _nm(prior)
        if n0 is not None and n1 is not None and n0 < n1:
            flags.append("净利率同比下滑")
            bits.append(f"净利率 {round(n1 * 100, 2)}%→{round(n0 * 100, 2)}%")
    if not flags:
        return None
    note = f"(报告期{end} vs {_yoy_period(end)})" if prior is not None else f"(报告期{end},无同期基数)"
    return (flags, f"{'、'.join(flags)};{' / '.join(bits)}{note}", str(end), str((rec or {}).get("ann_date")))


def _balancesheet_red_flags(recs, as_of):
    """④资产负债表 balancesheet 自然符号红旗(comparison-only,**不新设阈值**,balancesheet-only):PIT 最近报告期 q0 与去年同期 q-4——
    红旗(全为**同期方向比较**,非绝对阈值)= 资产负债率上升(total_liab/total_assets q0>q-4)/ 应收占总资产比上升(accounts_receiv/total_assets q0>q-4)/
    存货占总资产比上升(inventories/total_assets q0>q-4)/ 商誉减值迹象(goodwill q0<q-4 且 q-4>0:CAS 商誉不摊销,YoY 降=减值/处置)。
    **全为 YoY 比较,需 q-4 可得**(缺则无红旗,绝不伪造;无 q0-only 绝对阈值红旗——决策4 禁阈值)。返回 (red_flags[], summary, period, observed_at) 或 None。
    绝不据此否决/改决策。与③(营收/毛利率/净利率/亏损)互补,本刀聚焦 应收/存货/商誉/负债。"""
    periods = _fin_pit_periods(recs, as_of, realized=True)   # balancesheet 已实现报表:丢弃未来报告期(REALIZED-PERIOD-PIT)
    if not periods:
        return None
    end, rec = periods[0]                          # PIT 最近报告期
    prior = {e: r for e, r in periods}.get(_yoy_period(end))
    if prior is None:
        return None                               # 全为同期比较,无去年同期基数 → 无红旗(不伪造,不用绝对阈值兜底)

    def _ratio(r, key):                           # 某项 / 总资产(总资产缺/0 → None,不除零)
        num, ta = _fin_num((r or {}).get(key)), _fin_num((r or {}).get("total_assets"))
        return num / ta if (ta not in (None, 0) and num is not None) else None
    flags, bits = [], []
    for key, label in (("total_liab", "资产负债率"), ("accounts_receiv", "应收占比"), ("inventories", "存货占比")):
        c0, c1 = _ratio(rec, key), _ratio(prior, key)
        if c0 is not None and c1 is not None and c0 > c1:      # 占比/比率同比上升(自然方向)
            flags.append(f"{label}上升")
            bits.append(f"{label} {round(c1 * 100, 2)}%→{round(c0 * 100, 2)}%")
    g0, g1 = _fin_num((rec or {}).get("goodwill")), _fin_num((prior or {}).get("goodwill"))
    if g0 is not None and g1 is not None and g1 > 0 and g0 < g1:   # 商誉 YoY 降 + 去年有商誉 → 减值/处置迹象(自然符号)
        flags.append("商誉减值迹象")
        bits.append(f"商誉 {g1}→{g0}")
    if not flags:
        return None
    return (flags, f"{'、'.join(flags)};{' / '.join(bits)}(报告期{end} vs {_yoy_period(end)})",
            str(end), str((rec or {}).get("ann_date")))


_FIN_RED_FLAG_FN = {"forecast": _forecast_red_flags, "income": _income_red_flags,
                    "balancesheet": _balancesheet_red_flags}   # type-agnostic builder 据此分派(加第 N 类只扩此表 + provider + schema enum)


def _fetch_forecast(pro, ts_code: str):
    """②业绩预告 forecast provider:tushare `pro.forecast(ts_code=)`(逐票业绩预告,**带公告日 ann_date 做 PIT**)→
    [{"ann_date","end_date","type","p_change_min","p_change_max"}](YYYYMMDD/原值|None)。**fail-closed**:缺 ann_date/end_date/type 列 →
    None(无法 PIT/数据形态异常 → 标未查成,不静默当真无);异常/None → None;空 → [](该票真无预告,查成了)。**仓库内未测真接口**:
    `pro.forecast` 字段名据 tushare 文档(决策5 已探可得性),真取数 gated --confirm;mock 注入可单测。"""
    try:
        df = pro.forecast(ts_code=ts_code, fields="ts_code,ann_date,end_date,type,p_change_min,p_change_max")
    except Exception:
        return None                                   # 取数失败 → 未查成(区别于真无预告的 [])
    if df is None:
        return None
    # fail-closed 要求**所有 red-flag 输入列**(非仅 PIT 列):type(分类红旗输入)+ p_change_min/p_change_max(数值红旗输入,
    # p_change_max<0 是红旗判据)。缺任一 → None(无法跑声明的红旗判据 → 该(票,类)未查成,builder 标 unchecked/unknown,
    # 绝不静默当「已查无红旗」)。列存在但单元格空白 → 值 None 合法(blank cell),仍算查成。(R-ASHORT-GAP42-FINANCIAL-TRENDS-PROVIDER-FIELD-COVERAGE-GUARD-GAP)
    if not {"ann_date", "end_date", "type", "p_change_min", "p_change_max"}.issubset(set(getattr(df, "columns", []))):
        return None                                   # 缺 PIT/分类/数值红旗输入列(数据形态异常)→ 未查成(不静默当真无)
    if getattr(df, "empty", True):
        return []                                     # 成功返回空 → 该票真无业绩预告(查成了)
    def _s(v):
        return str(v) if (v is not None and str(v).strip() not in ("", "nan", "None", "NaT")) else None
    return [{"ann_date": _s(r.get("ann_date")), "end_date": _s(r.get("end_date")), "type": _s(r.get("type")),
             "p_change_min": _fin_num(r.get("p_change_min")), "p_change_max": _fin_num(r.get("p_change_max"))}
            for _, r in df.iterrows()]


def _fetch_income(pro, ts_code: str):
    """③利润表 income provider: tushare `pro.income(ts_code=, report_type='1')`(逐票**合并报表** cumulative YTD 利润表,**带公告日 ann_date 做
    PIT**)→ [{"ann_date","end_date","total_revenue","revenue","oper_cost","n_income","n_income_attr_p"}](YYYYMMDD/原值|None)。
    **fail-closed**: 缺 ann_date/end_date 列 → None(无法 PIT/数据形态异常→标未查成);异常/None → None;空 → [](该票真无利润表,查成了)。
    report_type='1' 取合并报表(避免单季/调整口径混淆 YoY)。**仓库内未测真接口**: 字段名据 tushare 文档(决策5 已探可得性),真取数 gated --confirm;mock 注入可单测。"""
    try:
        df = pro.income(ts_code=ts_code, report_type="1",
                        fields="ts_code,ann_date,end_date,total_revenue,revenue,oper_cost,n_income,n_income_attr_p")
    except Exception:
        return None                                   # 取数失败 → 未查成(区别于真无利润表的 [])
    if df is None:
        return None
    # fail-closed 要求**所有 red-flag 输入列**(非仅 PIT 列):total_revenue/revenue/oper_cost(营收·毛利率红旗输入)+ 至少一个利润列
    # (n_income_attr_p 退 n_income,亏损·净利率红旗输入)。缺任一 → None(无法跑声明的红旗判据 → 未查成,builder 标 unchecked/unknown,
    # 绝不静默当「已查无红旗」)。列存在但单元格空白 → 值 None 合法。(R-ASHORT-GAP42-FINANCIAL-TRENDS-PROVIDER-FIELD-COVERAGE-GUARD-GAP)
    _cols = set(getattr(df, "columns", []))
    if not {"ann_date", "end_date", "total_revenue", "revenue", "oper_cost"}.issubset(_cols):
        return None                                   # 缺 PIT/营收/成本红旗输入列 → 未查成
    if not ({"n_income_attr_p", "n_income"} & _cols):
        return None                                   # 缺利润列(归母/总净利至少一个)→ 无法判亏损/净利率 → 未查成
    if getattr(df, "empty", True):
        return []                                     # 成功返回空 → 该票真无利润表记录(查成了)
    def _s(v):
        return str(v) if (v is not None and str(v).strip() not in ("", "nan", "None", "NaT")) else None
    return [{"ann_date": _s(r.get("ann_date")), "end_date": _s(r.get("end_date")),
             "total_revenue": _fin_num(r.get("total_revenue")), "revenue": _fin_num(r.get("revenue")),
             "oper_cost": _fin_num(r.get("oper_cost")), "n_income": _fin_num(r.get("n_income")),
             "n_income_attr_p": _fin_num(r.get("n_income_attr_p"))}
            for _, r in df.iterrows()]


def _fetch_balancesheet(pro, ts_code: str):
    """④资产负债表 balancesheet provider: tushare `pro.balancesheet(ts_code=, report_type='1')`(逐票**合并报表**资产负债表,**带公告日 ann_date 做
    PIT**)→ [{"ann_date","end_date","total_assets","total_liab","accounts_receiv","inventories","goodwill"}](YYYYMMDD/原值|None)。
    **fail-closed**: 缺 ann_date/end_date 列 → None(无法 PIT/数据形态异常→标未查成);异常/None → None;空 → [](该票真无资产负债表,查成了)。
    **仓库内未测真接口**: 字段名据 tushare 文档(决策5 已探可得性),真取数 gated --confirm;mock 注入可单测。"""
    try:
        df = pro.balancesheet(ts_code=ts_code, report_type="1",
                              fields="ts_code,ann_date,end_date,total_assets,total_liab,accounts_receiv,inventories,goodwill")
    except Exception:
        return None                                   # 取数失败 → 未查成(区别于真无资产负债表的 [])
    if df is None:
        return None
    # fail-closed 要求**所有 red-flag 输入列**(非仅 PIT 列):total_assets/total_liab/accounts_receiv/inventories/goodwill
    # (资产负债率·应收占比·存货占比·商誉减值红旗输入,均为 q0 vs q-4 方向比较的算子)。缺任一 → None(无法跑声明的红旗判据 →
    # 未查成,builder 标 unchecked/unknown,绝不静默当「已查无红旗」)。列存在但单元格空白 → 值 None 合法。(R-ASHORT-GAP42-FINANCIAL-TRENDS-PROVIDER-FIELD-COVERAGE-GUARD-GAP)
    if not {"ann_date", "end_date", "total_assets", "total_liab", "accounts_receiv",
            "inventories", "goodwill"}.issubset(set(getattr(df, "columns", []))):
        return None                                   # 缺 PIT/资产负债表红旗输入列(数据形态异常)→ 未查成(不静默当真无)
    if getattr(df, "empty", True):
        return []                                     # 成功返回空 → 该票真无资产负债表记录(查成了)
    def _s(v):
        return str(v) if (v is not None and str(v).strip() not in ("", "nan", "None", "NaT")) else None
    return [{"ann_date": _s(r.get("ann_date")), "end_date": _s(r.get("end_date")),
             "total_assets": _fin_num(r.get("total_assets")), "total_liab": _fin_num(r.get("total_liab")),
             "accounts_receiv": _fin_num(r.get("accounts_receiv")), "inventories": _fin_num(r.get("inventories")),
             "goodwill": _fin_num(r.get("goodwill"))}
            for _, r in df.iterrows()]


def _financial_trends(cand_names, as_of, forecast_provider=None, income_provider=None,
                      balancesheet_provider=None, held_codes=frozenset()):
    """4.2 财报质量趋势 builder(analysis-only · comparison-only · candidate-only)。
    每 (provider, statement_type) × 候选(非持仓)ts_code:provider(ts_code)→报表 recs(list|None);PIT 过滤(_fin_pit_periods,ann_date<=as_of)
    后由 `_FIN_RED_FLAG_FN[type]` 算**自然符号红旗**(无阈值·决策4);仅有红旗才落 record(无红旗=查成无红旗,不落、不噪声,镜像①)。
    **unknown-not-clear**:全 provider None → status unknown_or_unavailable(绝不当无红旗);有 provider 但全(票,类)取数失败 → 同 unknown;
    **部分(票,类)失败** → status checked 但失败项进 unchecked_codes(per-(票,类),绝不静默当无)。**held 排除**(持仓财报趋势留后续刀,镜像①候选 only)。
    返回 {as_of,status,records[],unchecked_codes?}。type-agnostic:加第 N 类只扩 _FIN_STATEMENT_*/_FIN_RED_FLAG_FN map + provider + schema enum。"""
    sources = [(forecast_provider, "forecast"), (income_provider, "income"), (balancesheet_provider, "balancesheet")]
    if all(p is None for p, _ in sources):
        return {"as_of": str(as_of), "status": "unknown_or_unavailable", "records": []}
    held = {str(c) for c in (held_codes or ())}
    records, any_ok, unchecked = [], False, []
    for provider, stype in sources:
        if provider is None:
            continue                                  # 该类未启用(无 provider)→ 不标 unchecked(区别于查询失败)
        red_fn = _FIN_RED_FLAG_FN[stype]
        for ts_code, name in cand_names:
            if str(ts_code) in held:
                continue                              # candidate-only:持仓排除(持仓财报趋势留后续刀)
            try:
                recs = provider(ts_code)
            except Exception:
                recs = None                           # 单(票,类)查询失败 → 未查成
            if recs is None:
                unchecked.append({"ts_code": str(ts_code), "name": name or "", "statement_type": stype})   # 取数失败 → per-(票,类) unknown(不当无)
                continue                              # 不计 any_ok(区别于真无红旗)
            # PIT-filtered coverage(R-...-PIT-FILTERED-COVERAGE-UNKNOWN-GAP):provider **非空**但无 PIT-valid 评估基础
            # (income 全未来报告期 / balancesheet 无可比 q-4 / 全 look-ahead ann_date)→ 未查成(false-clean 防护);**真空 [] 仍属查成**(真无数据)。
            if recs and not _fin_assessable(recs, as_of, stype):
                unchecked.append({"ts_code": str(ts_code), "name": name or "", "statement_type": stype})
                continue                              # 不计 any_ok(无 PIT-valid 评估基础,绝不当「已查无红旗」)
            any_ok = True                             # 真空 [] 或 有 PIT-valid 评估基础 → 查成(含真无红旗)
            res = red_fn(recs, as_of)
            if res is None:
                continue                              # 查成但无红旗 → 不落(避免噪声;coverage 由 status/unchecked 体现)
            flags, summary, period, observed_at = res
            records.append({"ts_code": str(ts_code), "name": name or "", "statement_type": stype,
                            "period": str(period), "observed_at": str(observed_at),
                            "red_flags": list(flags), "summary": str(summary)})
    if cand_names and not any_ok:                      # 有候选 + 有 provider 但全没查成 → unknown(绝不当无红旗)
        return {"as_of": str(as_of), "status": "unknown_or_unavailable", "records": []}
    records.sort(key=lambda r: (r["ts_code"], r["statement_type"]))
    out = {"as_of": str(as_of), "status": "checked", "records": records}
    if unchecked:                                     # 部分(票,类)未查成(全失败已上面 return unknown)→ per-(票,类) coverage,绝不静默当无
        out["unchecked_codes"] = unchecked
    return out


def _attach_financial_trend_impacts(weekly, as_of):
    """4.2 财报质量趋势 row landing(candidate-only · comparison-only):financial_trends 每条红旗 record 按 ts_code 落到对应**候选**
    report 逐票 M6.7 —— machine.operation_impact(source_field=financial_trend_{type})+ 精简结论区.风控触发(含 _FIN_STATEMENT_MARKER)。
    **绝不 hard_veto / 非生产 / 不改 操作·EGS·选股·TopN·股数·否决**(advisory priority_down,镜像①)。held(持仓)报告跳过
    (财报趋势 candidate-only;builder 本已排除 held,此处兜底防漂移)。status!=checked(unknown/无)→ 不落(不伪造)。"""
    ft = weekly.get("financial_trends") or {}
    if ft.get("status") != "checked":
        return
    rep_by = {r["ts_code"]: r for r in weekly["reports"]}
    for rec in (ft.get("records") or []):
        rep = rep_by.get(rec["ts_code"])
        if rep is None:
            continue
        if ((rep.get("machine") or {}).get("stateful_risk") or {}).get("position_state") == "held":
            continue                                  # candidate-only:持仓跳过(builder 已排除,兜底)
        stype = rec["statement_type"]
        label = _FIN_STATEMENT_LABEL[stype]
        cut = rep["m67"]["精简结论区"]
        txt = f"{_FIN_STATEMENT_MARKER}({label}):{rec['summary']}(财报红旗,仅 advisory 降优先级参考,绝不否决/不改 EGS/选股/股数)"
        prev = cut.get("风控触发") or "无"
        cut["风控触发"] = txt if prev in ("无", "") else f"{prev}｜{txt}"
        rep["machine"].setdefault("operation_impact", []).append({
            "source_field": f"financial_trend_{stype}",
            "field_class": "structured",
            "visibility_shape": "candidate_row_impact",
            "impact_scope": "new_entry",
            "new_entry_effect": "priority_down",
            "holding_effect": "none",
            "blocked_add_required": False,
            "veto_class": "none",
            "reason": f"{_FIN_STATEMENT_MARKER}({label}):{rec['summary']}(财报红旗,仅 advisory 降优先级;不改决策/EGS/选股/TopN/股数)",
            "evidence_ref": {"kind": "lineage_key", "value": f"financial_trends.records[{stype}]", "as_of": str(as_of)},
            "confidence": "high",
            "pit_basis": "disclosure_date",
            "production_effect_enabled": False,
            "implementation_status": "implemented",
            "m67_landing_surface": "精简结论区.风控触发(财报趋势对照)",
            "terminal_surface_target": "already_structured",
            "pending_successor_slice": None,
            "privacy_class": "public_tracked",
        })


def _attach_holding_disposition(weekly):
    """S3b R1+R2: pipeline 在 attach 各持仓信号(build 时内联 semantic + attach 后 forward_event held)之后,对每个持仓行
    (table.操作=='持有')**重算** 持仓处置/禁止加仓(machine.holding_management_signal/blocked_add_required),纳入 build 后晚到的
    forward_event held 信号。复用 engine `_apply_holding_disposition`(从全量 operation_impact 重算 → 幂等;非持有行 no-op)。"""
    from runners.a_short_phase5_engine import _apply_holding_disposition
    for rep in weekly.get("reports", []):
        _apply_holding_disposition(rep)


# ── S3b R4b: 跨周持久收紧 ratchet 持久层(IO + apply;纯 ratchet 数学在 engine `_holding_ratchet`/`_ratchet_report_error`)──────
# 镜像 V14.3 regime-ledger 的**结构**(gitignored sidecar、load→apply→validate→save、idempotent re-run、bootstrap、PIT envelope),
# 但 ratchet 是**per-(ts_code,entry_date) 就地更新-单向只升不降**(非 regime 的 append-only-immutable-by-date)。涉真实持仓 → 私密路由。
def _holding_ratchet_key(ts_code, entry_date):
    return f"{ts_code}|{entry_date}"


def load_holding_ratchet(path):
    """读跨周 ratchet sidecar → dict{(ts_code|entry_date): row}。文件缺失 → {}(bootstrap)。读时过 schema(防损坏/手改污染)。
    **(ts_code,entry_date) 复合唯一性 + 行 last_as_of ≤ envelope as_of 的 PIT 不变式由本函数在 Python 强制**(draft-07 schema 表达不了复合唯一/跨字段约束):
    R-ASHORT-S3B-R4B-RATCHET-SIDECAR-DUPLICATE-PIT-BYPASS —— **dict 折叠前**检测重复 key,否则后一行会静默覆盖前一行,可把未来 last_as_of 行
    藏在重复 key 后绕过 `_apply_holding_ratchet` 的 PIT future-state guard(损坏/手改/merge-conflict/未来写入的 sidecar 须 fail-closed)。"""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    with open(HOLDING_RATCHET_SCHEMA_PATH, "r", encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))
    rows = doc.get("holdings") or []
    keys = [_holding_ratchet_key(r["ts_code"], r["entry_date"]) for r in rows]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:                                  # **折叠前**检测:dict 折叠会静默用后一行覆盖前一行、藏未来 last_as_of 绕 PIT → 重复 (ts_code,entry_date) 即拒
        raise ValueError(f"R4b ratchet sidecar 含重复 (ts_code,entry_date) 行 {dup[:3]}(dict 折叠静默覆盖、可藏未来 last_as_of 绕过 PIT future-state guard;拒)")
    env_as_of = str(doc.get("as_of") or "")
    future = sorted({k for k, r in zip(keys, rows) if str(r.get("last_as_of") or "") > env_as_of})
    if future:                               # envelope PIT:行 last_as_of 不得 > sidecar 自身 as_of(内部未来污染;load 时 fail-closed,不只靠 apply 时比 run as_of)
        raise ValueError(f"R4b ratchet sidecar 行 last_as_of > envelope as_of {env_as_of} {future[:3]}(PIT envelope 未来污染;拒)")
    return {k: dict(r) for k, r in zip(keys, rows)}


def _apply_holding_ratchet(weekly, state, as_of):
    """对每个持仓行(table.操作=='持有')应用跨周 ratchet:从 machine 取本周态 → engine `_holding_ratchet`(本周, 上周持久) →
    set machine.ratchet + 更新 state[key]。持仓身份=(ts_code, entry_date)(entry_date 取 machine.stateful_risk.position;
    无 entry_date → 无稳定身份,跳过 ratchet,诚实不伪造)。re-entry(新 entry_date)= 新 key → bootstrap。写后过 `_ratchet_report_error`
    弱不变式(与 validate_m67_consistency 持有分支单一来源)。返回更新后的 state(就地)。非持仓行 no-op。"""
    from runners.a_short_phase5_engine import (_apply_holding_disposition, _holding_ratchet,
                                                _ratchet_report_error)
    _future = [k for k, r in state.items() if str(r.get("last_as_of") or "") > str(as_of)]
    if _future:                                     # PIT:sidecar 含未来态(乱序/replay 旧周配新 sidecar)→ 拒(镜像 regime ledger future-contamination)
        raise ValueError(f"R4b ratchet sidecar 含未来态(last_as_of > as_of {as_of}):{_future[:3]}(PIT 违反/乱序 run)")
    for rep in weekly.get("reports", []):
        mc = rep.get("machine") or {}
        if ((rep.get("m67") or {}).get("table") or {}).get("操作") != "持有":
            continue
        pos = (mc.get("stateful_risk") or {}).get("position") or {}
        ed = pos.get("entry_date")
        if not ed:                                  # 无 entry_date → 无稳定身份 → 不 ratchet(不伪造)
            continue
        ts = str(rep.get("ts_code") or "")
        plan = (mc.get("entry_exit_size_star") or {}).get("plan") or {}
        this_week = {"ts_code": ts, "entry_date": str(ed), "as_of": str(as_of),
                     "close": mc.get("current_close"), "stop": plan.get("stop"),
                     "breakeven": (mc.get("move_to_breakeven") or {}).get("breakeven_price"),
                     "disposition": mc.get("holding_management_signal"),
                     "reduce_price": mc.get("reduce_price"), "clear_price": mc.get("clear_price")}
        key = _holding_ratchet_key(ts, str(ed))
        machine_ratchet, row = _holding_ratchet(this_week, state.get(key))
        mc["ratchet"] = machine_ratchet
        final_stop = machine_ratchet.get("ratcheted_stop")
        if isinstance(final_stop, (int, float)) and not isinstance(final_stop, bool) and plan:
            # Ratchet is the effective stop, not an advisory side channel. Keep the machine plan,
            # final table and downstream disposition prices on one value.
            old_stop = plan.get("stop")
            plan["stop"] = final_stop
            table = rep["m67"]["table"]
            table["损"] = final_stop
            if isinstance(mc.get("current_close"), (int, float)) and mc["current_close"] <= final_stop:
                plan.update({"breached": True, "t1": None, "t2": None})
                table["盈一"] = table["盈二"] = None
                rep["m67"]["精简结论区"]["操作建议"] = (
                    f"已有持仓，本周禁止自动加仓。⚠️ 现价已跌破跨周最终止损 {final_stop}"
                    " —— 触发后由你盘中无条件手动执行并人工复核。")
            else:
                advice = str(rep["m67"]["精简结论区"].get("操作建议") or "")
                old_phrase = f"系统跟踪止损 {old_stop}"
                if old_phrase not in advice:
                    raise ValueError(f"R4b ratchet 无法在操作建议定位旧系统止损 {old_stop}，拒绝留下双口径")
                rep["m67"]["精简结论区"]["操作建议"] = advice.replace(
                    old_phrase, f"跨周最终止损 {final_stop}", 1)
            _apply_holding_disposition(rep)
        _err = _ratchet_report_error(mc)
        if _err:
            raise ValueError(f"R4b ratchet apply 弱不变式失败({ts}/{ed}): {_err}")
        state[key] = row
    return state


def _holding_ratchet_doc(state, as_of, generated_at):
    rows = sorted(state.values(), key=lambda r: (str(r.get("ts_code")), str(r.get("entry_date"))))
    _keys = [_holding_ratchet_key(r.get("ts_code"), r.get("entry_date")) for r in rows]
    if len(_keys) != len(set(_keys)):        # reader/writer 对称 fail-closed:state 是 dict 本就唯一,此 guard 防手构非-dict-derived state 写出重复行(同 load 复合唯一)
        raise ValueError("R4b ratchet sidecar 写入含重复 (ts_code,entry_date) 行(reader/writer 须对称 fail-closed on duplicate)")
    _fut = [k for k, r in zip(_keys, rows) if str(r.get("last_as_of") or "") > str(as_of)]
    if _fut:                                 # save-time PIT envelope:行 last_as_of 不得 > 写回 as_of(reader/writer 对称,镜像 load envelope guard)
        raise ValueError(f"R4b ratchet sidecar 写入行 last_as_of > as_of {as_of} {_fut[:3]}(PIT envelope;reader/writer 对称 fail-closed)")
    doc = {"schema_name": "a_short_holding_ratchet", "schema_version": "1.0.0",
           "generated_at": str(generated_at), "as_of": str(as_of),
           "boundary": {"production": False, "comparison_only": True, "advisory_only": True},
           "holdings": rows}
    with open(HOLDING_RATCHET_SCHEMA_PATH, "r", encoding="utf-8") as f:
        jsonschema.validate(doc, json.load(f))
    return doc


def save_holding_ratchet(path, state, as_of, generated_at):
    """写跨周 ratchet sidecar(assemble envelope + boundary,过 schema)。调用方须先过私密路径守门(gitignored)。
    rows = state 全量(含上轮持仓的历史行:无害,lookup 按当周身份;re-entry 留旧行不删——不剪枝避免误删暂离本周的持仓态)。"""
    doc = _holding_ratchet_doc(state, as_of, generated_at)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _industry_fundamentals(financial_trends, code_to_industry, as_of):
    """⑤行业基本面(advisory-only · summary_only · **零新取数**):按 SW L2 行业聚合③④(income/balancesheet)候选财报红旗。
    **candidate-scope**(基于本周候选,**非全行业普查** → scope=candidates_only 诚实标注,避免误读为完整行业景气;真全行业普查需另起单独 slice)。
    只列有≥1 红旗候选的行业(无红旗行业不列,避噪声);②预告 forecast **不计**(行业基本面=已实现 income/balancesheet,非预告)。
    financial_trends status!=checked → None(无可聚合)。**无 operation_impact**(summary_only,逐票红旗已由③④落地;本层只加行业上下文摘要)。
    返回 {as_of,scope,by_industry[{sw_l2_name,candidate_count(分母,该行业候选总数),red_flag_candidate_count,red_flag_codes,summary}]} 或 None(无红旗行业)。"""
    if (financial_trends or {}).get("status") != "checked":
        return None
    recs = [r for r in (financial_trends.get("records") or []) if r.get("statement_type") in ("income", "balancesheet")]
    if not recs:
        return None
    ind_of = {str(c): (i or "未知") for c, i in (code_to_industry or {}).items()}
    cand_count = {}                                    # 行业 → 候选总数(分母,context)
    for ind in ind_of.values():
        cand_count[ind] = cand_count.get(ind, 0) + 1
    by_ind = {}                                        # 行业 → {codes:{ts:name}, flags:set}
    for r in recs:
        ind = ind_of.get(r["ts_code"], "未知")
        slot = by_ind.setdefault(ind, {"codes": {}, "flags": set()})
        slot["codes"][r["ts_code"]] = r.get("name", "")
        slot["flags"].update(r.get("red_flags") or [])
    out = []
    for ind in sorted(by_ind):
        codes = sorted(by_ind[ind]["codes"])
        flags = sorted(by_ind[ind]["flags"])
        denom = max(cand_count.get(ind, 0), len(codes))   # 分母 >= 红旗数 >= 1
        out.append({"sw_l2_name": ind, "candidate_count": denom,
                    "red_flag_candidate_count": len(codes), "red_flag_codes": codes,
                    "summary": f"{ind}:{denom} 候选中 {len(codes)} 只有财报红旗({'、'.join(flags)})"})
    return {"as_of": str(as_of), "scope": "candidates_only", "by_industry": out}


# ── 4.2 Round5 龙虎榜(top_list)第一刀: analysis-only · comparison-only ───────────────────────
# 记**候选 + 账户持仓**近 N 交易日上榜事实+净买卖(第一刀)+ 席位分析(第二刀 top_inst)+ 持仓覆盖(第三刀),落 板块资金事件 + operation_impact(source_field=dragon_list_appearance);
# **绝不改 EGS/TopN/选股/股数/操作/否决**(comparison-only,阈值未定·4.2.md §9 决策4)。
# 复用 forward_events analysis-only 模式: fail-closed provider / unknown-not-clear / 双向 no-dangling / source-isolation guard。
DRAGON_LIST_LOOKBACK_TRADING_DAYS = 5   # 近 N 交易日窗口(§4.1/§11.5 prior,未来进 governance;非生产阈值,不静默写 runner 魔数)
_DRAGON_LIST_MARKER = "龙虎榜对照"        # 板块资金事件 落地标记:_attach 写入 + engine guard ⑬ 据此判 row no-dangling(单一来源,防文案漂移)
_DRAGON_LIST_EVIDENCE_VALUE = "dragon_list.events[appearance]"   # operation_impact.evidence_ref.value(_attach 写入 + 反向 evidence guard 校验共用单一来源)


def _recent_trading_days(pro, as_of: str, n: int = DRAGON_LIST_LOOKBACK_TRADING_DAYS):
    """最近 `n` 个 **<= as_of** 的 SSE 交易日(经 `trade_cal`,升序)。龙虎榜回望窗口的真交易日来源
    (非日历日近似)。取不到/异常/列缺 → None(调用方退回 unknown,fail-closed,绝不静默当无窗口)。"""
    from datetime import datetime, timedelta
    start = (datetime.strptime(str(as_of), "%Y%m%d") - timedelta(days=max(40, n * 5))).strftime("%Y%m%d")
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=str(as_of),
                            is_open="1", fields="cal_date")
    except Exception:
        return None
    if cal is None or len(cal) == 0 or "cal_date" not in cal.columns:
        return None
    days = sorted(str(d) for d in cal["cal_date"] if str(d) <= str(as_of))
    return days[-n:] if days else None


def _fetch_dragon_list(pro, trade_date: str):
    """4.2 Round5 真龙虎榜 provider: tushare `pro.top_list(trade_date=)`(当日全市场上榜票,**收盘后发布 → trade_date<=as_of
    即 PIT-safe**)→ [{"ts_code","name","net_amount"(净买卖原值),"reason"(上榜原因)}]。按 trade_date 查(已验证接口形态,
    每日 ~数十行),builder 再过滤到候选。**fail-closed**: 缺 ts_code/net_amount/reason 列(数据形态异常)→ None(未查成,
    builder 据此标该日 unchecked,绝不静默当无上榜);异常/None → None;空 → [](该日真无上榜,查成了)。net_amount 不做单位换算。"""
    try:
        df = pro.top_list(trade_date=str(trade_date), fields="trade_date,ts_code,name,net_amount,reason")
    except Exception:
        return None
    if df is None:
        return None
    if not {"ts_code", "net_amount", "reason"}.issubset(set(getattr(df, "columns", []))):
        return None
    if getattr(df, "empty", True):
        return []
    def _s(v):
        return str(v) if (v is not None and str(v).strip() not in ("", "nan", "None", "NaT")) else None
    def _num(v):
        if v is None or str(v).strip() in ("", "nan", "None", "NaT"):
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if (f == f and f not in (float("inf"), float("-inf"))) else None   # 非有限(NaN/Inf)→ None(防写出非法 JSON)
    return [{"ts_code": _s(r.get("ts_code")), "name": _s(r.get("name")) or "",
             "net_amount": _num(r.get("net_amount")), "reason": _s(r.get("reason"))}
            for _, r in df.iterrows()]


_DRAGON_INST_SEAT_TAG = "机构专用"   # top_inst.exalter 机构席位标记(tushare 约定,**非阈值**;只做数据标注、不分类决策)


def _fetch_dragon_inst(pro, trade_date: str):
    """4.2 Round5 第二刀 真席位 provider: tushare `pro.top_inst(trade_date=)`(当日全市场上榜票逐席位,**同 trade_date<=as_of
    PIT-safe**)→ [{"ts_code","exalter"(席位/营业部名),"side"(0买/1卖,原值),"net_buy"(该席位净买入,原值)}]。按 trade_date 查,
    builder 再按 (ts_code,trade_date) join 到上榜 event。**fail-closed**: 缺 ts_code/exalter/net_buy 列→None(未查成);异常/None→None;
    空→[](该日真无席位记录,查成了)。net_buy 不做单位换算;`exalter` 含『机构专用』= 机构席位。"""
    try:
        df = pro.top_inst(trade_date=str(trade_date), fields="trade_date,ts_code,exalter,side,buy,sell,net_buy")
    except Exception:
        return None
    if df is None:
        return None
    if not {"ts_code", "exalter", "net_buy"}.issubset(set(getattr(df, "columns", []))):
        return None
    if getattr(df, "empty", True):
        return []
    def _s(v):
        return str(v) if (v is not None and str(v).strip() not in ("", "nan", "None", "NaT")) else None
    def _num(v):
        if v is None or str(v).strip() in ("", "nan", "None", "NaT"):
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if (f == f and f not in (float("inf"), float("-inf"))) else None
    return [{"ts_code": _s(r.get("ts_code")), "exalter": _s(r.get("exalter")),
             "side": _s(r.get("side")), "net_buy": _num(r.get("net_buy"))}
            for _, r in df.iterrows()]


def _sum_inst_net(seats):
    """机构席位(exalter 含『机构专用』)净买入合计。无机构席位 → None(不伪造 0);有则求和(None-safe;全 None → None)。"""
    inst = [s for s in seats if _DRAGON_INST_SEAT_TAG in (s.get("exalter") or "")]
    if not inst:
        return None
    vals = [s["net_buy"] for s in inst if s.get("net_buy") is not None]
    return round(sum(vals), 2) if vals else None


def _attach_seats(out, events, inst_provider):
    """第二刀 席位分析:为有上榜的交易日抓 top_inst,按 (ts_code,trade_date) join 到 event 的 `seats` + `inst_net_buy`。
    **仅当 inst_provider 已接线(非 None)时启用** —— 第一刀式调用(无 inst_provider)→ 不加 seats_status,输出不变。
    **unknown-not-clear**: inst_provider 在但所有有上榜交易日都取数失败 → seats_status=`unknown_or_unavailable`(绝不当「无席位」);
    部分失败 → seats_status=`checked` 但失败日进 `unchecked_seat_dates`(该日 events 不附 seats)。查成日 → event 附 seats(含真空 [])。"""
    if inst_provider is None:
        return                                            # 席位层未请求(第一刀式调用)→ 输出不变
    event_days = sorted({e["trade_date"] for e in events})
    if not event_days:
        out["seats_status"] = "checked"                   # 无上榜 → 无席位可查,trivially 完整
        return
    by_day, unchecked, any_ok = {}, [], False
    for day in event_days:
        try:
            rows = inst_provider(day)
        except Exception:
            rows = None
        if rows is None:
            unchecked.append(day)                         # 该日席位取数失败 → 未查成(不当无席位)
            continue
        any_ok = True
        g = {}
        for r in rows:
            code = (r or {}).get("ts_code")
            if code is None:
                continue
            g.setdefault(code, []).append({"exalter": (r or {}).get("exalter"),
                                           "side": (r or {}).get("side"), "net_buy": (r or {}).get("net_buy")})
        by_day[day] = g
    if not any_ok:                                        # 有上榜日但席位全没查成 → unknown(绝不当无席位)
        out["seats_status"] = "unknown_or_unavailable"
        return
    out["seats_status"] = "checked"
    if unchecked:
        out["unchecked_seat_dates"] = sorted(set(unchecked))
    for e in events:
        if e["trade_date"] in by_day:                     # 该日席位查成 → 附(含真空);失败日不附(render 标未核查)
            seats = by_day[e["trade_date"]].get(e["ts_code"], [])
            e["seats"] = seats
            e["inst_net_buy"] = _sum_inst_net(seats)


def _dragon_list_events(cand_names, as_of, dragon_provider, trade_days, inst_provider=None,
                        lookback=DRAGON_LIST_LOOKBACK_TRADING_DAYS):
    """4.2 Round5 龙虎榜 builder(analysis-only,**不改任何决策**;只进 M6.7 板块资金事件对照)。
    `dragon_provider(trade_date)` → list[{"ts_code","name","net_amount","reason"}]|None(失败)。`trade_days` =
    近 N 个 SSE 交易日(均 <= as_of,见 `_recent_trading_days`)。PIT: 只收 trade_date<=as_of(provider 按 trade_days 查,
    天然满足;再防御性核 as_of)。**unknown-not-clear**: provider None / trade_days 空 / 全交易日取数失败 → status
    `unknown_or_unavailable`(绝不当「无上榜」);部分交易日失败 → status `checked` 但失败日进 `unchecked_dates`。
    只收 `cand_names`(第三刀起 = 候选 + 账户持仓,main 用 reports 行装配)上榜行,其它票丢弃。一票多日上榜 → 多条 event。
    第二刀 席位分析: 传 `inst_provider(trade_date)` 时,为有上榜的交易日抓 top_inst,join 到 event 的 `seats`/`inst_net_buy`
    (见 `_attach_seats`;不传则第一刀式输出不变)。"""
    from datetime import datetime
    wd = sorted({str(d) for d in (trade_days or [])})
    base = {"as_of": str(as_of), "lookback_trading_days": lookback, "window_dates": wd}
    if dragon_provider is None or not wd:
        return {**base, "status": "unknown_or_unavailable", "events": []}
    try:
        as_of_d = datetime.strptime(str(as_of), "%Y%m%d")
    except ValueError:
        raise ValueError(f"dragon_list as_of {as_of!r} 非合法日历日")
    name_by = {str(c): (n or "") for c, n in cand_names}
    cand_codes = set(name_by)
    events, any_ok, unchecked = [], False, []
    for day in wd:
        try:
            rows = dragon_provider(day)
        except Exception:
            rows = None
        if rows is None:
            unchecked.append(day)                         # 该交易日取数失败 → 未查成(不当无上榜)
            continue
        any_ok = True                                     # 该日查成(含真无上榜的空 list)
        try:
            day_d = datetime.strptime(str(day), "%Y%m%d")
        except ValueError:
            continue                                      # 非法交易日(防御)→ 跳过
        if (day_d - as_of_d).days > 0:
            continue                                      # 防御: 未来交易日 → 非 PIT,跳过(trade_days 本就 <=as_of)
        for row in rows:
            code = (row or {}).get("ts_code")
            if code not in cand_codes:
                continue                                  # 非覆盖票(既非候选也非账户持仓)→ 丢弃
            events.append({"ts_code": code, "name": name_by.get(code, ""), "trade_date": str(day),
                           "net_amount": (row or {}).get("net_amount"), "reason": (row or {}).get("reason")})
    if not any_ok:                                         # 有窗口但所有交易日都没查成 → unknown(绝不当无上榜)
        return {**base, "status": "unknown_or_unavailable", "events": []}
    events.sort(key=lambda e: (e["trade_date"], e["ts_code"]), reverse=True)
    out = {**base, "status": "checked", "events": events}
    if unchecked:
        out["unchecked_dates"] = sorted(set(unchecked))
    _attach_seats(out, events, inst_provider)             # 第二刀: 席位 join(仅 inst_provider 接线时;否则输出不变)
    return out


def _attach_dragon_list_impacts(weekly, as_of):
    """4.2 Round5 龙虎榜 row landing: weekly-global dragon_list 的每条上榜按 ts_code 落到对应 report(候选/持仓)的**逐票** M6.7 ——
    精简结论区.板块资金事件 文本(含 `_DRAGON_LIST_MARKER`)+ machine.operation_impact(source_field=dragon_list_appearance)。
    **comparison-only**: new_entry_effect=informational(候选)/none(held-candidate)、holding_effect=none、blocked_add=False、
    veto_class=none、production_effect_enabled=False —— 绝不改 操作/EGS/选股/TopN/股数/否决(比 forward_event 更严:无任何动作)。
    status!=checked(unknown/无)→ 不落(不伪造)。第三刀起覆盖 reports 行(候选 + 账户持仓);held(持仓)→ holding_row_impact
    (comparison-only,同候选无任何动作);Tier-3 account_position_only 的 板块资金事件 render 掩面已由 _card_field 放行『龙虎榜对照』(独立真取数,非 EGS 维度)。"""
    dl = weekly.get("dragon_list") or {}
    if dl.get("status") != "checked":
        return
    n = dl.get("lookback_trading_days")
    by_code = {}
    for e in (dl.get("events") or []):
        by_code.setdefault(e["ts_code"], []).append(e)
    for rep in weekly["reports"]:
        evs = by_code.get(rep["ts_code"])
        if not evs:
            continue
        held = ((rep.get("machine") or {}).get("stateful_risk") or {}).get("position_state") == "held"
        recent = max(evs, key=lambda e: e["trade_date"])
        net = recent.get("net_amount")
        _rseats = recent.get("seats")                              # 第二刀: 最近一次上榜的席位(查成才有)
        _seat_txt = ""
        if _rseats is not None:
            _inb = recent.get("inst_net_buy")
            _seat_txt = f",席位{len(_rseats)}家" + (f"(机构净{_inb})" if _inb is not None else "")
        detail = (f"最近{recent['trade_date']}"
                  + (f",净额{net}" if net is not None else "")
                  + _seat_txt
                  + (f",{recent['reason']}" if recent.get("reason") else ""))
        txt = f"{_DRAGON_LIST_MARKER}(comparison-only,不改决策):近{n}交易日{len(evs)}次上龙虎榜({detail})"
        cut = rep["m67"]["精简结论区"]
        prev = cut.get("板块资金事件") or ""
        cut["板块资金事件"] = f"{prev}｜{txt}" if prev and prev != "unknown" else txt
        rep["machine"].setdefault("operation_impact", []).append({
            "source_field": "dragon_list_appearance",
            "field_class": "structured",
            "visibility_shape": "holding_row_impact" if held else "candidate_row_impact",
            "impact_scope": "existing_holding" if held else "new_entry",
            "new_entry_effect": "none" if held else "informational",   # comparison-only: 只解释,不改动作
            "holding_effect": "none",                                  # comparison-only: 不 hold_watch/reduce/clear
            "blocked_add_required": False,                             # comparison-only: 不禁止加仓
            "veto_class": "none",
            "reason": f"近{n}交易日{len(evs)}次上龙虎榜 → 资金面对照(comparison-only,不改决策/EGS/选股/TopN;阈值未定)",
            "evidence_ref": {"kind": "lineage_key", "value": _DRAGON_LIST_EVIDENCE_VALUE, "as_of": str(as_of)},
            "confidence": "high",
            "pit_basis": "trade_date_window",
            "production_effect_enabled": False,
            "implementation_status": "implemented",
            "m67_landing_surface": "精简结论区.板块资金事件(龙虎榜对照)",
            "terminal_surface_target": "already_structured",
            "pending_successor_slice": None,
            "privacy_class": "private_account" if held else "public_tracked",
        })


# ── 4.2 Round5 大宗交易(block_trade)第一刀: analysis-only · comparison-only(镜像龙虎榜第一刀)──────────
# 记**候选 + 账户持仓**近 N 交易日大宗成交事实 + 成交金额(amount 当日合计 + trade_count 笔数);**绝不改 EGS/TopN/选股/股数/操作/否决**。
# 买卖方(营业部)分析 = 第二刀;折价率(对齐当日**未复权** close,单位口径已隔离)= 第三刀。复用龙虎榜 analysis-only 模式(含持仓 holding_row_impact/私密、Tier-3 掩面放行)。
BLOCK_TRADE_LOOKBACK_TRADING_DAYS = 5   # 近 N 交易日窗口(prior,未来进 governance;非生产阈值)
_BLOCK_TRADE_MARKER = "大宗交易对照"        # 板块资金事件 落地标记:_attach 写入 + engine guard ⑭ 据此判 row no-dangling(单一来源)
_BLOCK_TRADE_EVIDENCE_VALUE = "block_trade.events[appearance]"   # operation_impact.evidence_ref.value(_attach + 反向 guard 共用)


def _fetch_block_trade(pro, trade_date: str):
    """4.2 Round5 真大宗交易 provider: tushare `pro.block_trade(trade_date=)`(当日全市场大宗成交,**收盘后发布 → trade_date<=as_of
    PIT-safe**)→ [{"ts_code","amount"(成交金额原值),"buyer"(买方营业部),"seller"(卖方营业部)}]。按 trade_date 查,builder 按 (票,日)
    聚合(笔数 + 金额合计 + 第二刀逐笔买卖方 parties)再过滤候选。**fail-closed**: 缺 ts_code/amount 列 → None(未查成);异常/None → None;
    空 → [](该日真无大宗,查成了)。amount 不做单位换算。**第二刀 buyer/seller 同一 fetch + fail-closed 要求该列**:缺 buyer/seller 列 → None
    (该日 unchecked,绝不把 ?→? 当查成的买卖方;单元格本身空白→该笔 buyer/seller=None 合法,但列必须存在)。**第三刀 price 同样 fail-closed
    要求该列**:缺 price 列 → None(该日折价证据不可得 → unchecked,绝不标 discount checked;单元格空白→该笔 price=None 合法,但列必须存在);
    折价率所需当日**未复权**收盘价由独立 _fetch_daily_close 取(绝不复用前复权 price_series)。"""
    try:
        df = pro.block_trade(trade_date=str(trade_date), fields="trade_date,ts_code,price,vol,amount,buyer,seller")
    except Exception:
        return None
    if df is None:
        return None
    if not {"ts_code", "amount", "buyer", "seller", "price"}.issubset(set(getattr(df, "columns", []))):
        return None
    if getattr(df, "empty", True):
        return []
    def _s(v):
        return str(v) if (v is not None and str(v).strip() not in ("", "nan", "None", "NaT")) else None
    def _num(v):
        if v is None or str(v).strip() in ("", "nan", "None", "NaT"):
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if (f == f and f not in (float("inf"), float("-inf"))) else None
    return [{"ts_code": _s(r.get("ts_code")), "amount": _num(r.get("amount")), "price": _num(r.get("price")),
             "buyer": _s(r.get("buyer")), "seller": _s(r.get("seller"))} for _, r in df.iterrows()]


def _fetch_daily_close(pro, trade_date: str):
    """4.2 Round5 第三刀 折价率: 当日**未复权**收盘价 provider(tushare pro.daily,raw OHLC)→ {ts_code: close}。
    **必须未复权**: block_trade.price 是原始成交价,折价率 = (price − raw_close)/raw_close,绝不能用前复权 close
    (历史日若除权,前复权 close ≠ 当日原值,会算出假折价)。**fail-closed**: 缺 ts_code/close 列 → None(该日折价
    不可算 → unchecked,不伪造);异常/None → None;空 df → {}(该日确无收盘,已查成)。"""
    try:
        df = pro.daily(trade_date=str(trade_date), fields="ts_code,trade_date,close")
    except Exception:
        return None
    if df is None:
        return None
    if not {"ts_code", "close"}.issubset(set(getattr(df, "columns", []))):
        return None
    if getattr(df, "empty", True):
        return {}

    def _cnum(v):
        if v is None or str(v).strip() in ("", "nan", "None", "NaT"):
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if (f == f and f not in (float("inf"), float("-inf"))) else None

    closes = {}
    for _, r in df.iterrows():
        code = r.get("ts_code")
        if code is not None and str(code).strip() not in ("", "nan", "None", "NaT"):
            closes[str(code)] = _cnum(r.get("close"))
    return closes


def _attach_block_discount(out, events, close_provider):
    """第三刀 折价率: 为有大宗的交易日抓**未复权收盘价**,按 (ts_code,trade_date) 算每笔折价率
    discount=(price−close)/close(负=折价/抛压,正=溢价)。**仅当 close_provider 已接线(非 None)时启用**
    (否则不加 discount_status,输出与第二刀一致)。**unknown-not-clear**: close_provider 在但所有有大宗交易日
    都取数失败 → discount_status=`unknown_or_unavailable`(绝不当「无折价」);部分失败 → checked 但失败日进
    `unchecked_discount_dates`(该日 event 不附 close/discount)。查成日 → event 附 raw `close`(审计)+ 每 party
    附 `discount`(该股当日无 close 或 close=0 → 该 party discount=None,不伪造)。"""
    if close_provider is None:
        return                                            # 折价层未请求(第二刀式调用)→ 输出不变
    event_days = sorted({e["trade_date"] for e in events})
    if not event_days:
        out["discount_status"] = "checked"                # 无大宗 → 无折价可算,trivially 完整
        return
    by_day, unchecked, any_ok = {}, [], False
    for day in event_days:
        try:
            closes = close_provider(day)
        except Exception:
            closes = None
        if closes is None:
            unchecked.append(day)                         # 该日收盘取数失败 → 未查成(不当无折价)
            continue
        any_ok = True
        by_day[day] = closes
    if not any_ok:                                        # 有大宗日但收盘全没查成 → unknown(绝不当无折价)
        out["discount_status"] = "unknown_or_unavailable"
        return
    out["discount_status"] = "checked"
    if unchecked:
        out["unchecked_discount_dates"] = sorted(set(unchecked))
    for e in events:
        if e["trade_date"] in by_day:                     # 该日收盘查成 → 附 raw close + 逐笔 discount;失败日不附
            close = by_day[e["trade_date"]].get(e["ts_code"])
            e["close"] = close
            for p in (e.get("parties") or []):
                price = p.get("price")
                p["discount"] = (round((price - close) / close, 6)
                                 if (price is not None and close is not None and close != 0) else None)


def _block_trade_events(cand_names, as_of, block_provider, trade_days, close_provider=None,
                        lookback=BLOCK_TRADE_LOOKBACK_TRADING_DAYS):
    """4.2 Round5 大宗交易 builder(analysis-only,**不改任何决策**;只进 M6.7 板块资金事件对照)。
    `block_provider(trade_date)` → list[{"ts_code","amount"}]|None(失败)。`trade_days` = 近 N 个 SSE 交易日(均 <= as_of)。
    PIT: 只收 trade_date<=as_of。**unknown-not-clear**: provider None / trade_days 空 / 全交易日取数失败 → status
    `unknown_or_unavailable`(绝不当「无大宗」);部分交易日失败 → status `checked` 但失败日进 `unchecked_dates`。
    按 (票,日) 聚合: event = {ts_code,name,trade_date,amount(当日合计,全缺→None),trade_count(笔数),parties(逐笔
    {buyer,seller,amount,price})};**price 溯源**:仅当源行带 `price` 键(值可 None=空白 cell)才落该键,缺键=无 price 证据不补
    (折价层下 validator 据此拒,绝不伪造 checked)。close_provider 接线时(第三刀)再 _attach_block_discount 附 raw `close` + 逐笔 `discount`。
    只收 `cand_names`(= 候选 + 账户持仓,main 用 reports 行装配),其它票丢弃。买卖方=第二刀、折价率=第三刀,均已含。"""
    from datetime import datetime
    wd = sorted({str(d) for d in (trade_days or [])})
    base = {"as_of": str(as_of), "lookback_trading_days": lookback, "window_dates": wd}
    if block_provider is None or not wd:
        return {**base, "status": "unknown_or_unavailable", "events": []}
    try:
        as_of_d = datetime.strptime(str(as_of), "%Y%m%d")
    except ValueError:
        raise ValueError(f"block_trade as_of {as_of!r} 非合法日历日")
    name_by = {str(c): (n or "") for c, n in cand_names}
    cand_codes = set(name_by)
    events, any_ok, unchecked = [], False, []
    for day in wd:
        try:
            rows = block_provider(day)
        except Exception:
            rows = None
        if rows is None:
            unchecked.append(day)                         # 该交易日取数失败 → 未查成(不当无大宗)
            continue
        any_ok = True                                     # 该日查成(含真无大宗的空 list)
        try:
            day_d = datetime.strptime(str(day), "%Y%m%d")
        except ValueError:
            continue
        if (day_d - as_of_d).days > 0:
            continue                                      # 防御: 未来交易日 → 跳过
        agg = {}                                          # ts_code -> [amount_sum|None, count, parties]
        for row in rows:
            code = (row or {}).get("ts_code")
            if code not in cand_codes:
                continue                                  # 非覆盖票(既非候选也非账户持仓)→ 丢弃
            cur = agg.setdefault(code, [None, 0, []])
            cur[1] += 1
            amt = (row or {}).get("amount")
            if amt is not None:
                cur[0] = (cur[0] or 0.0) + amt
            _party = {"buyer": (row or {}).get("buyer"), "seller": (row or {}).get("seller"), "amount": amt}   # 第二刀 买卖方
            if "price" in (row or {}):                     # 第三刀 price 溯源:行**带 price 键**(值可 None=空白 cell)才落;缺键=无 price 证据,绝不补 None 伪造 checked
                _party["price"] = (row or {}).get("price")
            cur[2].append(_party)
        for code, (amt_sum, cnt, parties) in agg.items():
            events.append({"ts_code": code, "name": name_by.get(code, ""), "trade_date": str(day),
                           "amount": (round(amt_sum, 2) if amt_sum is not None else None),
                           "trade_count": cnt, "parties": parties})
    if not any_ok:                                         # 有窗口但所有交易日都没查成 → unknown(绝不当无大宗)
        return {**base, "status": "unknown_or_unavailable", "events": []}
    events.sort(key=lambda e: (e["trade_date"], e["ts_code"]), reverse=True)
    out = {**base, "status": "checked", "events": events}
    if unchecked:
        out["unchecked_dates"] = sorted(set(unchecked))
    _attach_block_discount(out, events, close_provider)   # 第三刀: close_provider 接线才附折价(否则输出不变)
    return out


def _attach_block_trade_impacts(weekly, as_of):
    """4.2 Round5 大宗交易 row landing(镜像 _attach_dragon_list_impacts): block_trade 每条按 ts_code 落到对应 report 逐票 M6.7 ——
    精简结论区.板块资金事件 文本(含 `_BLOCK_TRADE_MARKER`)+ machine.operation_impact(source_field=block_trade_appearance)。
    **comparison-only**: new_entry_effect=informational(候选)/none(held-candidate)、holding_effect=none、blocked_add=False、
    veto_class=none、production_effect_enabled=False —— 绝不改 操作/EGS/选股/TopN/股数/否决。status!=checked → 不落(不伪造)。
    第一刀即覆盖 reports(候选 + 账户持仓);held(持仓)→ holding_row_impact 私密(private_account);买卖方营业部 = 第二刀、折价率(最大笔)= 第三刀,均已落 板块资金事件文本。"""
    bt = weekly.get("block_trade") or {}
    if bt.get("status") != "checked":
        return
    n = bt.get("lookback_trading_days")
    by_code = {}
    for e in (bt.get("events") or []):
        by_code.setdefault(e["ts_code"], []).append(e)
    for rep in weekly["reports"]:
        evs = by_code.get(rep["ts_code"])
        if not evs:
            continue
        held = ((rep.get("machine") or {}).get("stateful_risk") or {}).get("position_state") == "held"
        recent = max(evs, key=lambda e: e["trade_date"])
        total_cnt = sum(e["trade_count"] for e in evs)
        amt = recent.get("amount")
        _bp = recent.get("parties") or []                         # 第二刀 最大笔买卖方 + 第三刀折价率
        _ptxt = ""
        if _bp:
            _top = max(_bp, key=lambda p: (p.get("amount") or 0))
            _ptxt = f",买卖方{_top.get('buyer') or '?'}→{_top.get('seller') or '?'}"
            _td = _top.get("discount")
            if _td is not None:
                _ptxt += f",折价率{_td * 100:+.2f}%"               # 第三刀: 最大笔折价率(负=折价/抛压,正=溢价)
        detail = f"最近{recent['trade_date']}" + (f",成交{amt}" if amt is not None else "") + f",{recent['trade_count']}笔" + _ptxt
        txt = f"{_BLOCK_TRADE_MARKER}(comparison-only,不改决策):近{n}交易日{total_cnt}笔大宗交易({detail})"
        cut = rep["m67"]["精简结论区"]
        prev = cut.get("板块资金事件") or ""
        cut["板块资金事件"] = f"{prev}｜{txt}" if prev and prev != "unknown" else txt
        rep["machine"].setdefault("operation_impact", []).append({
            "source_field": "block_trade_appearance",
            "field_class": "structured",
            "visibility_shape": "holding_row_impact" if held else "candidate_row_impact",
            "impact_scope": "existing_holding" if held else "new_entry",
            "new_entry_effect": "none" if held else "informational",   # comparison-only: 只解释,不改动作
            "holding_effect": "none",
            "blocked_add_required": False,
            "veto_class": "none",
            "reason": f"近{n}交易日{total_cnt}笔大宗交易 → 资金面对照(comparison-only,不改决策/EGS/选股/TopN;阈值未定)",
            "evidence_ref": {"kind": "lineage_key", "value": _BLOCK_TRADE_EVIDENCE_VALUE, "as_of": str(as_of)},
            "confidence": "high",
            "pit_basis": "trade_date_window",
            "production_effect_enabled": False,
            "implementation_status": "implemented",
            "m67_landing_surface": "精简结论区.板块资金事件(大宗交易对照)",
            "terminal_surface_target": "already_structured",
            "pending_successor_slice": None,
            "privacy_class": "private_account" if held else "public_tracked",
        })
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
        "effective_status": "shock",
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
    reviewed tolerance」):若给出 `accept_prior_settled_date`(= as_of 的前一交易日;仅由 main 在 **live 运行**
    [`as_of >= run_date`:今日 或 前瞻 canonical 周一,as_of 当日 EOD 尚未发布]传入,真·过去回放 `as_of < run_date`
    不传),则最新 bar 亦可 == 该「最新已结算交易日」。仍拒**更早**(真陈旧)与**未来** bar;历史回放不传该参数
    → 严格 == end。语义:在决策时点(as_of>=今天:今日 或 即将到来的交易日)最新已结算行情就是前一交易日,
    使用它非 look-ahead、亦非陈旧。

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
         holding_semantic_provider=None, holding_web_llm_provider=None, unlock_provider=None,
         earnings_provider=None, dragon_list_provider=None, dragon_list_days=None,
         dragon_list_inst_provider=None, block_trade_provider=None, daily_close_provider=None,
         forecast_provider=None, income_provider=None, balancesheet_provider=None):
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
    p.add_argument("--run-date", help="实际运行日 YYYYMMDD(记进 run_lineage;intraday_prior_settled 模式要求存在且 <= --as-of)")
    p.add_argument("--price-freshness-mode", choices=["strict_as_of", "intraday_prior_settled"],
                   default="strict_as_of",
                   help="价格新鲜度模式(显式,记进 run_lineage.price_freshness):strict_as_of(默认,最新 bar 必须 ==as_of);"
                        "intraday_prior_settled(实盘当天/前瞻 canonical、as_of 当日 EOD 未发布 → 容忍最新 bar==前一交易日;要求 --as-of >= --run-date)")
    p.add_argument("--skip-semantic", action="store_true",
                   help="跳过语义官方层自动取数(advisory;不影响 M6.7 确定性 base)")
    p.add_argument("--allow-nonprivate-account-out", action="store_true",
                   help="显式放行:带 --account 时允许输出落仓库内非私密目录(默认拒,防真实持仓被 git 提交泄漏)")
    p.add_argument("--ratchet-path", default=HOLDING_RATCHET_DEFAULT_PATH,
                   help="S3b R4b 跨周持久收紧 ratchet sidecar 路径(默认 gitignored state/a_short/holding_ratchet/;含真实持仓,过私密路径守门)")
    p.add_argument("--skip-ratchet", action="store_true",
                   help="跳过 S3b R4b 跨周 ratchet 持久层(不读写 sidecar、不注入 machine.ratchet)")
    args = p.parse_args(argv)
    if not _is_valid_yyyymmdd(args.as_of):
        raise SystemExit(f"[FATAL] --as-of {args.as_of} 不是合法日历日期")
    if args.run_date and not _is_valid_yyyymmdd(args.run_date):
        raise SystemExit(f"[FATAL] --run-date {args.run_date} 不是合法日历日期")
    # intraday tolerance is an EXPLICIT mode, not inferred; valid when as_of's own EOD may not be published
    # yet — i.e. as_of is today (run_date==as_of) OR a prospective canonical session (as_of>run_date, e.g.
    # weekly canonical 解析器把周末/周一盘前运行解析成「即将到来的周一」as_of)。两者最新已结算 bar 都 ==
    # as_of 前一交易日。真·过去回放(as_of<run_date,EOD 已发布) / 缺 run-date 仍须 strict_as_of。
    if args.price_freshness_mode == "intraday_prior_settled" and (
            not args.run_date or str(args.as_of) < str(args.run_date)):
        raise SystemExit("[FATAL] --price-freshness-mode intraday_prior_settled 要求 --run-date 存在且 "
                         "--as-of >= --run-date(实盘当天/前瞻 canonical:as_of 当日 EOD 未发布);"
                         "历史回放(as_of<run-date)/缺 run-date 请用 strict_as_of")
    # 持仓恒列入隐私护栏(固化):带 --account 的周报含真实持仓 → 拒绝落仓库内非私密目录(防 git 提交泄漏)。
    # 早于任何取数/落盘,fail-fast。
    _reject_nonprivate_account_output_path(args.out, bool(args.account), args.allow_nonprivate_account_out)
    # 同守自动派生的 Markdown 旁产物(P0 修复):write_weekly_markdown 写 <out>.md,同含真实持仓;.json 可能被
    # state/*/*.json 忽略而放行,但 .md 不被同一规则覆盖、会落未忽略路径泄漏 → 必须用同守门先校验(fail-fast,早于任何写盘)。
    _reject_nonprivate_account_output_path(os.path.splitext(args.out)[0] + ".md", bool(args.account),
                                           args.allow_nonprivate_account_out)

    def _load(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # analysis_input 消费方校验(#R-ASHORT-WEEKLY-ANALYSIS-INPUT-CONSUMER-VALIDATION-GAP):
    # 用仓库契约校验 schema + PIT,并强制 trade_date == --as-of(拒错配/未来/陈旧批次)。
    ai = validate_analysis_input_file(args.analysis_input, label="weekly analysis_input")
    if str(ai.get("trade_date")) != args.as_of:
        raise SystemExit(f"[FATAL] analysis_input.trade_date {ai.get('trade_date')} != --as-of {args.as_of}"
                         "(批次错配/未来/陈旧,拒跑周报)")
    from engine.data.analysis_input_contract import build_a_short_run_identity
    source_identity = dict(((ai.get("source") or {}).get("run_identity") or {}))
    try:
        Path(args.analysis_input).resolve().relative_to((ROOT / "result" / "a_short").resolve())
        official_input = True
    except ValueError:
        official_input = False
    if official_input:
        if not source_identity:
            raise SystemExit("[FATAL] official analysis_input missing run_identity")
        marker_path = Path(args.analysis_input).resolve().parent / "official_publish.json"
        if not marker_path.exists():
            raise SystemExit("[FATAL] official analysis_input has no final publish marker")
        marker = _load(marker_path)
        _validate_official_publish_marker(args.analysis_input, marker, source_identity)
    elif not source_identity:
        # Hermetic fixtures/research callers outside result/a_short get a
        # deterministic identity; production paths never take this branch.
        source_identity = build_a_short_run_identity(args.as_of, ai.get("candidates") or [])
    feed = _load(args.iv_feed)
    from runners.a_short_iv_feed_build import validate_feed_summary_consistency
    validate_feed_summary_consistency(feed)
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
    if args.account:
        acct, account_lineage, account_bundle = load_account_bundle(args.account, args.as_of)
    else:
        acct, account_lineage, account_bundle = {}, {}, {}
    account_integrity = account_integrity_from_lineage(account_lineage)
    # 市场 regime 只取自 analysis_input(EGS 分类)。unknown/missing 不允许被账户配置覆盖成进攻期;
    # 按 2026-06-14 用户决策:unknown → 震荡期 + 降级 + 保守减半 + M6.7 明确提示。
    regime, regime_fallback = resolve_market_regime(ai)
    # available_cash 是用户必填输入。零现金仍须管理已有持仓,但不得建立新仓;
    # 未提供 --account → observation-only(sizing_mode 标进 run_lineage,读者不会把 sizing 假象的「观察」当真 avoid 信号)。
    available_cash = acct.get("available_cash")
    if args.account:
        if isinstance(available_cash, bool) or not isinstance(available_cash, (int, float)) or available_cash < 0:
            raise SystemExit(f"[FATAL] --account {args.account} 提供但 available_cash 缺失/为负数;拒跑")
        account_status, sizing_mode = "provided", "sized"
    else:
        account_status, sizing_mode = "absent", "observation_only_no_account"
    bucket_ceiling_pct = load_bucket_ceiling_pct() if args.account else None
    total_equity = acct.get("total_equity")
    current_gross_exposure = acct.get("current_gross_exposure")
    if args.account and (isinstance(total_equity, bool) or not isinstance(total_equity, (int, float)) or
                         total_equity <= 0 or isinstance(current_gross_exposure, bool) or
                         not isinstance(current_gross_exposure, (int, float)) or current_gross_exposure < 0):
        raise SystemExit("[FATAL] --account 缺 total_equity/current_gross_exposure,无法执行 bucket 敞口门")
    bucket_capital = (float(total_equity) * bucket_ceiling_pct) if args.account else None
    new_exposure_capacity = (max(0.0, bucket_capital - float(current_gross_exposure))
                             if args.account else None)
    account = {"available_cash": available_cash,
               "total_equity": total_equity,
               "current_gross_exposure": current_gross_exposure,
               "bucket_ceiling_pct": bucket_ceiling_pct,
               "bucket_capital": bucket_capital,
               "new_exposure_capacity": new_exposure_capacity,
               "positions_count": len(acct.get("positions") or [])}
    # 价格序列:注入(测试)或执行期抓取(需授权)
    prior_settled = None     # 实际接受的前一交易日(仅 intraday_prior_settled 模式;记进 lineage)
    if price_provider is None:
        if not args.confirm_fetch_authorized:
            raise SystemExit("[FATAL] 需 --confirm-fetch-authorized:周末 run 会抓前复权价")
        import tushare as ts
        pro = pro_factory() if pro_factory else init_tushare_pro(os.environ["TUSHARE_TOKEN"])
        start = (datetime.strptime(args.as_of, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
        # 显式 intraday_prior_settled 模式(已 guard as_of>=run_date)→ 价格门容忍最新 bar==前一交易日
        # (as_of 当日 EOD 未发布的实盘当天/前瞻 canonical);strict_as_of → prior_settled=None → 严格 == as_of。仅放前一交易日,
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
        # 4.2 forward_events 第2刀 真财报预约披露 provider(同上下文;pro.disclosure_date 仓库未测,真取数 gated 此处 --confirm)。
        if earnings_provider is None:
            earnings_provider = lambda code: _fetch_earnings_schedule(pro, code)
        # 4.2 Round5 真龙虎榜 provider + 近 N 交易日窗口(同上下文;top_list 按 trade_date 查、trade_cal 取交易日;analysis-only comparison-only)。
        if dragon_list_provider is None:
            dragon_list_provider = lambda d: _fetch_dragon_list(pro, d)
        if dragon_list_days is None:
            dragon_list_days = _recent_trading_days(pro, args.as_of, DRAGON_LIST_LOOKBACK_TRADING_DAYS)
        # 4.2 Round5 第二刀 真席位 provider(同上下文;top_inst 按 trade_date 查;analysis-only comparison-only)。
        if dragon_list_inst_provider is None:
            dragon_list_inst_provider = lambda d: _fetch_dragon_inst(pro, d)
        # 4.2 Round5 大宗交易 provider(同上下文;block_trade 按 trade_date 查;analysis-only comparison-only)。
        if block_trade_provider is None:
            block_trade_provider = lambda d: _fetch_block_trade(pro, d)
        # 4.2 Round5 第三刀 折价率: 当日**未复权**收盘价 provider(同上下文;pro.daily raw close 按 trade_date 查;绝不复用前复权)。
        if daily_close_provider is None:
            daily_close_provider = lambda d: _fetch_daily_close(pro, d)
        # 4.2 财报质量趋势 ②业绩预告 provider(analysis-only advisory 旁路;注入优先;同一已授权 fetch 上下文;pro.forecast 仓库未测真接口,gated --confirm)。
        if forecast_provider is None:
            forecast_provider = lambda code: _fetch_forecast(pro, code)
        # 4.2 财报质量趋势 ③利润表 provider(同上下文;pro.income report_type=1 合并报表,仓库未测真接口,gated --confirm)。
        if income_provider is None:
            income_provider = lambda code: _fetch_income(pro, code)
        # 4.2 财报质量趋势 ④资产负债表 provider(同上下文;pro.balancesheet report_type=1 合并报表,仓库未测真接口,gated --confirm)。
        if balancesheet_provider is None:
            balancesheet_provider = lambda code: _fetch_balancesheet(pro, code)
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
                                      stateful_risk=stateful_risk_for_candidate(
                                          acct, c["ts_code"], args.as_of,
                                          account_integrity=account_integrity),
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
    iv_freshness = validate_iv_feed_freshness(feed, price_data_through)
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
    run_lineage = {"run_id": source_identity["run_id"],
                   "candidate_digest": source_identity["candidate_digest"],
                   "stage_status": "complete",
                   "analysis_input": _rel(args.analysis_input),
                   "selection_bucket": _rel(os.path.dirname(args.analysis_input)),
                   "iv_feed": _rel(args.iv_feed),
                   "account_ref": (_rel(args.account) if args.account else ""),
                   "account_status": account_status, "sizing_mode": sizing_mode,
                   "account_snapshot": ({"snapshot_id": account_bundle["snapshot_id"],
                                         "snapshot_digest": account_bundle["snapshot_digest"],
                                         "facts_as_of": account_bundle["facts_as_of"],
                                         "decision_as_of": account_bundle["decision_as_of"],
                                         "positions_count": len(acct.get("positions") or []),
                                         "integrity_status": account_integrity["status"],
                                         "blocking_kinds": account_integrity["blocking_kinds"],
                                         "blocking_count": account_integrity["blocking_count"]}
                                        if args.account else None),
                   "iv_freshness": iv_freshness,
                   "market_regime": {"source_status": ((ai.get("market_context") or {}).get("market_regime") or {}).get("status") or "missing",
                                     "effective_status": ((regime_fallback or {}).get("effective_status") or
                                                          next(k for k, v in REGIME_MAP.items() if v == regime)),
                                     "effective_regime": regime,
                                     "fallback_active": bool(regime_fallback)},
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
            semantic_provider=holding_semantic_provider, web_llm_provider=holding_web_llm_provider,
            account_integrity=account_integrity)
    weekly = build_weekly_report(normalized + holding_normalized, args.as_of, gen,
                                 iv_feed_ref=os.path.basename(args.iv_feed), run_lineage=run_lineage,
                                 available_cash=(available_cash if args.account else None),
                                 new_exposure_capacity=new_exposure_capacity)
    # S1: 每行打 row_source / coverage_status;持仓行挂 4.3-D 对账警告;无价/停牌持仓单列 manual_review。
    held_codes_all = {str(p.get("ts_code")) for p in (acct.get("positions") or [])}
    cons_by = account_consistency_warnings_by_code(account_lineage) if args.account else {}
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
    weekly["upcoming_events"] = _upcoming_events(_exdiv_codes, args.as_of, unlock_provider, earnings_provider)
    # 4.2 forward_events row landing: upcoming events 按 ts_code 落到对应 report 逐票 operation_impact + 风控触发文本(advisory,不改决策)。
    _attach_forward_event_impacts(weekly, args.as_of)
    # 4.2 Round5 龙虎榜(comparison-only):候选近 N 交易日上榜对照 → 板块资金事件 + operation_impact(不改决策/EGS/选股/TopN/股数)。
    # unknown-not-clear: provider 不可用(无 --confirm)/trade_cal 取不到 → status=unknown_or_unavailable(绝不当「无上榜」)。
    # 第三刀: 覆盖**候选 + 账户持仓**(reports 行 = normalized 候选 ∪ holding_normalized);非候选持仓由此纳入龙虎榜/席位对照。
    _dragon_covered_names = [(str(r["ts_code"]), r.get("name", "")) for r in weekly["reports"]]
    weekly["dragon_list"] = _dragon_list_events(_dragon_covered_names, args.as_of, dragon_list_provider,
                                                dragon_list_days, inst_provider=dragon_list_inst_provider)
    _attach_dragon_list_impacts(weekly, args.as_of)
    # 4.2 Round5 大宗交易(comparison-only,一/二/三刀):候选+账户持仓近 N 交易日大宗成交 + 买卖方 + 折价率(未复权)对照 → 板块资金事件 + operation_impact(不改决策/EGS/选股/TopN/股数)。复用 reports universe + trade_cal 窗口。
    weekly["block_trade"] = _block_trade_events(_dragon_covered_names, args.as_of, block_trade_provider,
                                                dragon_list_days, close_provider=daily_close_provider)
    _attach_block_trade_impacts(weekly, args.as_of)
    # 4.2 财报质量趋势(②forecast/③income/④balancesheet, candidate-only · comparison-only):候选(**非持仓**)新增报表取数 → 自然符号红旗 →
    # 风控触发(财报趋势对照)+ operation_impact(不改决策/EGS/选股/TopN/股数)。unknown-not-clear: provider 不可用(无 --confirm)→ status=unknown(绝不当无红旗)。
    # held 排除(持仓财报趋势留后续刀,镜像①候选 only);universe = EGS 候选 ∖ 账户持仓。
    _fin_trend_names = [(str(c.get("ts_code")), c.get("name", "")) for c in cands if str(c.get("ts_code")) not in held_codes_all]
    weekly["financial_trends"] = _financial_trends(_fin_trend_names, args.as_of, forecast_provider=forecast_provider,
                                                   income_provider=income_provider,
                                                   balancesheet_provider=balancesheet_provider, held_codes=held_codes_all)
    _attach_financial_trend_impacts(weekly, args.as_of)
    # S3b R1+R2: 所有持仓 operation_impact 已 attach(semantic 内联 + forward_event held);对每个持仓行(操作=持有)重算 持仓处置/禁止加仓,
    # 纳入 build 后晚到的 forward_event held 信号(幂等全量重算)。
    _attach_holding_disposition(weekly)
    # S3b R4b: 跨周持久收紧 ratchet(仅 --account 真持仓 run;持仓处置/R4a 已就位后,沉淀 stop/disposition 跨周只升不降 + 滚动到价)。
    # 涉真实持仓(entry_date/ratcheted_stop/prices)→ sidecar 必 gitignored(私密路径守门,git check-ignore 真值);re-entry 重置;bootstrap。
    _pending_ratchet = None
    if args.account and not args.skip_ratchet:
        _rt_path = os.path.abspath(args.ratchet_path)
        _reject_nonprivate_account_output_path(_rt_path, True, args.allow_nonprivate_account_out)   # sidecar 含真实持仓,须 gitignored
        _rt_state = load_holding_ratchet(_rt_path)
        _apply_holding_ratchet(weekly, _rt_state, args.as_of)
        _pending_ratchet = (_rt_path, _rt_state, args.as_of, gen)
    # 4.2 财报质量趋势 ⑤ 行业基本面(advisory-only · summary_only · 零新取数):按 SW L2 行业聚合③④(income/balancesheet)候选红旗 → 行业上下文。
    # candidate-scope(基于本周候选,非全行业普查);只列有红旗行业;无 operation_impact(逐票已由③④落地,本层只加行业摘要)。
    _fin_trend_ind = {str(c.get("ts_code")): ((c.get("industry") or {}).get("sw_l2_name") or "未知")
                      for c in cands if str(c.get("ts_code")) not in held_codes_all}
    _indf = _industry_fundamentals(weekly.get("financial_trends"), _fin_trend_ind, args.as_of)
    if _indf:
        weekly["industry_fundamentals"] = _indf
    # 4.2 Round2: 上游过滤批次级摘要(counts-only, public) — 复用 analysis_input.universe_summary.excluded_counts
    # (egs_main filter_l0 已记 unlock/suspended/relisted/holder_reduction_veto_10d), 不改 egs_main、不抓数。
    _excl = _build_exclusion_summary((ai.get("universe_summary") or {}).get("excluded_counts") or {}, args.as_of)
    if _excl:
        weekly["exclusion_summary"] = _excl
    md_path = os.path.splitext(args.out)[0] + ".md"
    receipt_path = publish_weekly_bundle(
        weekly, feed, args.out, md_path,
        allow_nonprivate_account_out=args.allow_nonprivate_account_out,
        ratchet_publish=_pending_ratchet,
    )
    actions = {}
    for r in weekly["reports"]:
        actions[r["m67"]["table"]["操作"]] = actions.get(r["m67"]["table"]["操作"], 0) + 1
    print(f"[weekly] n={weekly['n_stocks']} actions={actions} iv_pct={iv_pct} -> {args.out} (+ {md_path}; receipt={receipt_path})")


if __name__ == "__main__":
    main()
