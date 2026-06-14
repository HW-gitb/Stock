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

import jsonschema

SCHEMA_NAME = "a_short_weekly_report"
SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schemas", "a_short_weekly_report.schema.json")
M67_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "schemas", "a_short_m67_report.schema.json")
OVERLAY_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "schemas", "a_short_theme_overlay_comparison.schema.json")


def normalize_candidate(cand: dict, price_series: list, overlay_row: dict, iv_pct,
                        account: dict, regime: str, industry_trend: str = "neutral",
                        llm_enrichment=None, observe_only=None, semantic=None,
                        semantic_web_llm=None, regime_fallback=None) -> dict:
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
        "overlay": {"eligible": bool((overlay_row or {}).get("eligible")),
                    "crowding_hit": bool((overlay_row or {}).get("crowding_hit"))},
        "industry_trend": industry_trend,
        # 真实 EGS analysis_input 契约:derived_flags.{is_lock,is_breakout,has_crash_veto,
        # overheat_flag,chasing_high,vol_confirm,hard_veto};suspension 在 event_risk.suspension.is_suspended。
        # vol_confirm 可选:缺失/false → 走保守非突破路径(低吸/观察);true → 启用 Phase 5 突破分支。
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
        "iv": {"iv_percentile_252d": iv_pct},
        "market_regime": regime,
        "regime_fallback": dict(regime_fallback or {}),
        "account": account or {},
        "portfolio": {},
        "observe_only": list(observe_only or []),
        "llm_enrichment": list(llm_enrichment or []),
        # 语义官方层(Slice 1):official_structured dict {status, events[severity], had_pit_announcements}
        # 或 None(无输入→引擎按 unknown 中性处理)。Phase5 引擎据此融进 M6.7(证据齐全[非空URL]high→否决;缺URL high·medium→待核)。
        "semantic": semantic,
        # 语义 web/LLM 层(Slice 2):{"web_llm": {...}, "sources": [...]} 或 None(无输入→引擎按 unknown 中性)。
        # DeepSeek 判官产出;引擎据此 downgrade(有 sources 证据的 risk/headwind;**绝不 hard_veto**);非法→中性化。
        "semantic_web_llm": semantic_web_llm,
    }


def build_weekly_report(normalized_list: list, as_of: str, generated_at: str,
                        iv_feed_ref: str = "", run_lineage: dict = None) -> dict:
    from runners.a_short_phase5_engine import build_m67_report
    reports = [build_m67_report(n, as_of, generated_at) for n in normalized_list]
    # run_lineage ties the consumed selection + IV feed + account/sizing status to this M6.7 artifact
    # (Slice 3b-2: selection 在 result/a_short、M6.7 在 research lane,靠此机器可读 lineage 绑定);
    # default = no-account observation-only,使直接 builder/测试仍 schema-valid。
    lineage = run_lineage if run_lineage is not None else {
        "analysis_input": "", "selection_bucket": "", "iv_feed": iv_feed_ref,
        "account_status": "absent", "sizing_mode": "observation_only_no_account"}
    return {
        "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at, "as_of": as_of,
        "iv_feed_ref": iv_feed_ref, "n_stocks": len(reports), "reports": reports,
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
    seen = set()
    for rep in weekly["reports"]:
        if rep["as_of"] != weekly["as_of"]:
            raise ValueError("report.as_of 与周报 as_of 不一致")
        if rep["ts_code"] in seen:
            raise ValueError(f"周报含重复 ts_code {rep['ts_code']}")
        seen.add(rep["ts_code"])
        validate_m67_consistency(rep)                        # 逐票 §4 不变量


def _reject_production_output_path(out_path: str) -> None:
    """周报是 non-production artifact。输出路径由调用方指定(约定写 research/results/),
    但**绝不写 production 输出根 result/a_short/<date>**(CLAUDE.md 硬约束)。"""
    norm = os.path.normpath(os.path.abspath(out_path)).replace("\\", "/").lower()
    if "/result/a_short/" in norm:
        raise ValueError(f"禁止写入 production 路径 {out_path}(result/a_short/<date>);"
                         "周报输出由调用方指定(约定 research/results/),但绝不落 production 根")


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


MIN_PRICE_OBS = 20               # 指标(支撑/压力 20d、ATR 14d)所需最少 PIT 交易日
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


def _fetch_price_series(ts_module, pro, ts_code: str, start: str, end: str) -> list:
    """前复权日线 → [{high,low,close}](oldest→newest)。A 股主板个股用 asset='E'。`end` == 周报 as_of。
    **provider 异常 → 中止(不 fail-open)**:provider 失败 ≠ 无交易,不能默默退化成观察。
    **PIT + 新鲜度门(R-ASHORT-WEEKLY-PRICE-SERIES-PIT-FRESHNESS-GAP)**:每个 `trade_date` 必须是
    合法日历日;拒任何 `trade_date > end`(未来 bar);**最新 bar 必须 == `end`(==as_of)**,否则数据
    陈旧 → 中止不写。返回空(provider 成功但无行)由 main 覆盖门统一拦截。"""
    from datetime import datetime
    try:
        df = ts_module.pro_bar(ts_code=ts_code, adj="qfq", asset="E",
                               start_date=start, end_date=end, api=pro)
    except Exception as exc:
        raise SystemExit(f"[FATAL] pro_bar {ts_code} provider 失败: {type(exc).__name__};"
                         "不写周报(provider 失败 ≠ 无交易,不可 fail-open 成观察)")
    if df is None or df.empty:
        return []
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
        raise SystemExit(f"[FATAL] pro_bar {ts_code} 最新 bar {rows[-1]['trade_date']} != as_of {end}"
                         "(数据陈旧,未含 as_of 当日);不写周报")
    return [{"high": r["high"], "low": r["low"], "close": r["close"]} for r in rows]


def _build_cninfo_semantic_provider(codes, as_of, lookback_days, fetcher=None):
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
        main_codes, _dropped = main_board_top15(codes)   # 已审有界 universe;非主板/超 Top15 不取不喂
        if not main_codes:
            return None
        raws = (fetcher or _fetch)(main_codes, as_of, lookback_days)
        # malformed/无 ts_code 行丢弃 → 该码在 build_summary_from_fetches 里缺映射 → not_fetched → unknown
        # (绝不建 "None" 键、绝不把残缺/缺响应当 clear)。
        cninfo_results = {str(r["ts_code"]): r for r in raws
                          if isinstance(r, dict) and r.get("ts_code")}
        summary = build_summary_from_fetches(main_codes, as_of, cninfo_results, None,
                                             "weekly-semantic-provider")  # generated_at 仅占位,不被消费
        by = {c["ts_code"]: c["official_structured"] for c in summary["candidates"]}
        return lambda ts: by.get(str(ts))
    except Exception as exc:
        print(f"[weekly] 语义 cninfo 取数失败({type(exc).__name__});语义层全 unknown(advisory,不阻断周报)")
        return None


def _build_deepseek_web_llm_provider(codes, names_by_code, sina_fetcher=None, ds_client=None):
    """非阻断 DeepSeek web/LLM 判官 provider(Slice 2,advisory 旁路)。一次性批量抓 sina,逐票经 DeepSeek 判 →
    `{web_llm, sources}`(非 unknown)或 None(unknown/中性)。**缺 key/SDK → None(整层 unknown)**;抓取失败
    → None;单票判定异常 → 该票 None。任何失败都不阻断周报、不伪装 clear、不返回/打印 key。"""
    from runners.a_short_deepseek_semantic_adapter import judge_web_llm, build_deepseek_client
    client = ds_client if ds_client is not None else build_deepseek_client()
    if client is None:
        return None                                      # 缺 key/SDK → 整层 unknown(advisory,不阻断)
    try:
        from runners.a_short_semantic_risk_probe import fetch_sina, main_board_top15
        from runners.a_short_semantic_risk_summary import _sina_sources
        # 复用 cninfo provider 同一已审门:主板 Top15(去重 + 有界 cap15 + 非主板剔除)。**抓 sina/判 DeepSeek 前先过滤**,
        # 否则非标/扩大 analysis_input(如含创业板 300/科创 688)会触发超界的 sina/DeepSeek 成本与覆盖。
        main_codes, _dropped = main_board_top15(codes)
        if not main_codes:
            return None
        allowed = {str(c) for c in main_codes}
        raws = (sina_fetcher or fetch_sina)(list(main_codes))      # 只抓主板 Top15
        items_by = {str(r["ts_code"]): _sina_sources(r) for r in raws
                    if isinstance(r, dict) and r.get("ts_code")}
    except Exception as exc:
        print(f"[weekly] 语义 web/LLM sina 抓取失败({type(exc).__name__});web 层全 unknown(advisory,不阻断)")
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
         web_llm_provider=None):
    from datetime import datetime, timedelta
    from runners.a_short_iv_feed_probe import init_tushare_pro, _is_valid_yyyymmdd
    from engine.data.analysis_input_contract import validate_analysis_input_file
    p = argparse.ArgumentParser(description="A-short weekly pipeline (EGS→overlay→IV→engine→weekly M6.7)")
    p.add_argument("--as-of", required=True, help="YYYYMMDD")
    p.add_argument("--analysis-input", required=True, help="EGS analysis_input.json (top-N 候选)")
    p.add_argument("--iv-feed", required=True, help="a_short_iv_feed.json")
    p.add_argument("--overlay", help="overlay artifact(可选)")
    p.add_argument("--account", help="账户/环境 JSON(available_cash / market_regime)")
    p.add_argument("--out", required=True)
    p.add_argument("--confirm-fetch-authorized", action="store_true")
    p.add_argument("--cninfo-lookback-days", type=int, default=90,
                   help="语义官方层 cninfo 取数回溯天数(默认 90;真 run --confirm 时自动取数)")
    p.add_argument("--skip-semantic", action="store_true",
                   help="跳过语义官方层自动取数(advisory;不影响 M6.7 确定性 base)")
    args = p.parse_args(argv)
    if not _is_valid_yyyymmdd(args.as_of):
        raise SystemExit(f"[FATAL] --as-of {args.as_of} 不是合法日历日期")

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
    overlay = _load_validated_overlay(args.overlay, args.as_of) if args.overlay else {}
    weekly_candidates = [c.get("ts_code") for c in ai.get("candidates", [])]
    # overlay 血缘门(#R-ASHORT-WEEKLY-AUX-ARTIFACT-CANDIDATE-SET-MISMATCH):overlay 必须**恰好覆盖**
    # 本周报候选集(同一批)。缺行会被 `overlay.get(ts)` 静默 default 成 eligible/crowding=false,悄悄改
    # M6.7 星级;多行说明非同批。任一不符 → 写盘前 abort。
    if args.overlay and set(overlay) != set(weekly_candidates):
        raise SystemExit(f"[FATAL] overlay 候选集 {sorted(overlay)} != 周报候选 {sorted(weekly_candidates)}"
                         "(同日错批/缺行/多行,缺行会被静默降级;须同一批全覆盖,拒跑)")
    acct = _load(args.account) if args.account else {}
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
    account = {"available_cash": available_cash}
    # 价格序列:注入(测试)或执行期抓取(需授权)
    if price_provider is None:
        if not args.confirm_fetch_authorized:
            raise SystemExit("[FATAL] 需 --confirm-fetch-authorized:周末 run 会抓前复权价")
        import tushare as ts
        pro = pro_factory() if pro_factory else init_tushare_pro(os.environ["TUSHARE_TOKEN"])
        start = (datetime.strptime(args.as_of, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
        price_provider = lambda code: _fetch_price_series(ts, pro, code, start, args.as_of)
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
            {str(c.get("ts_code")): c.get("name", "") for c in _cands})
    normalized = [normalize_candidate(c, price_provider(c["ts_code"]), overlay.get(c["ts_code"]),
                                      iv_pct, account, regime,
                                      regime_fallback=regime_fallback,
                                      semantic=(semantic_provider(c["ts_code"]) if semantic_provider else None),
                                      semantic_web_llm=(web_llm_provider(c["ts_code"]) if web_llm_provider else None))
                  for c in ai.get("candidates", [])]
    # 价格覆盖门(#2):任一被纳入候选缺足够价格 → 中止不写(不可 fail-open 成观察)
    short = [(n["ts_code"], len(n["price_series"])) for n in normalized
             if len(n["price_series"]) < MIN_PRICE_OBS]
    if short:
        raise SystemExit(f"[FATAL] 以下候选价格序列不足(<{MIN_PRICE_OBS} 交易日):{short};"
                         "不写周报(价格抓取失败/停牌须排查,不可静默退化成观察)")
    gen = datetime.now().astimezone().isoformat(timespec="seconds")
    def _rel(pth):
        try:
            return os.path.relpath(pth).replace("\\", "/")
        except Exception:
            return os.path.basename(pth)
    run_lineage = {"analysis_input": _rel(args.analysis_input),
                   "selection_bucket": _rel(os.path.dirname(args.analysis_input)),
                   "iv_feed": _rel(args.iv_feed),
                   "account_status": account_status, "sizing_mode": sizing_mode}
    weekly = build_weekly_report(normalized, args.as_of, gen,
                                 iv_feed_ref=os.path.basename(args.iv_feed), run_lineage=run_lineage)
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
