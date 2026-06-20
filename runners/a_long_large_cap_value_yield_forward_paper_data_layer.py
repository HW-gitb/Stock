#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-long value-yield forward-PAPER capture **数据层**(段3 universe + 段4 store/context/scored-items/prices,lean top-500 路线)。

定位:为 forward 单 as_of capture 产出编排核心(brain,见 `..._capture.py::build_forward_accumulator`)所需的输入
——scored_items(每项含 cash_flow_to_circ_mv/sales_to_circ_mv/industry_l2·l1/size_bucket/market_cap)+ stock_price_cache
+ csi300_prices + trade_dates + delist_by_symbol——**通过复用冻结 bf/base 函数不变**(prereg
reuses_frozen_rules_unchanged):因子 = `bf.batch_factor_values`、收益价格 = `base.stock_total_return_close_rows` /
`base.index_total_return_close_rows`、行业 = `base.industry_context_for_symbol`、改名否决 = `base.symbol_vetoed_at_selection_time`、
主板排名 = `cap_audit.ranked_main_board_by_market_cap`。

两层:
- **assemble_forward_inputs(纯函数,mock 可测)**:raw records → top-500 universe → 内存 `base.audit.PayloadStore`
  (冻结 call_id 格式)+ 手建 `base.SignalContext` → 镜像 `monthly_cohort_rows` 单 as_of 体(过滤 list/delist/name-veto →
  batch_factor_values 取 2 value 因子 → 行业/size/market_cap)→ scored_items + 价格缓存。
- **fetch_forward_panel(gated,`pro` 注入)**:月末 PIT 真抓数(daily_basic 市值 / cashflow / income / daily+adj_factor /
  CSI300 index_daily / SW index_member / stock_basic 上市退市 / namechange / trade_cal)→ assemble 的 kwargs。
  **每次抓数需用户单独授权;真 provider 形状在第一笔真捕获(as_of≥20260630)现写现验**。

lean = 只 top-500、只拉算 2 value 因子 + 收益 + 中性化所需表(**非**全主板 23,718-call materialization)。
不改冻结 batch runner;不碰真钱;非 production。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from runners import a_long_large_cap_batch_factor_search_signal_search as bf
from runners import a_long_full_main_board_signal_search as base
from runners import a_long_large_cap_market_cap_audit as cap_audit

CSI300_CODE = bf.BENCHMARKS[bf.PRIMARY_BENCHMARK]            # "H00300.CSI"
VALUE_YIELD_FAMILIES = ("cash_flow_to_circ_mv", "sales_to_circ_mv")
UNIVERSE_SIZE_N = bf.UNIVERSE_SIZE_N                         # 500

# ── 段4 gated 抓数 call-plan 契约(Finding 3:explicit window + min-field + call 对账 + 显式 pacing/raw 决策)──
FORWARD_REQUIRED_FIELDS = {
    "daily_basic": {"ts_code", "trade_date", "circ_mv"},
    "cashflow": {"ts_code", "ann_date", "f_ann_date", "end_date", "n_cashflow_act"},
    "income": {"ts_code", "ann_date", "f_ann_date", "end_date", "revenue", "n_income_attr_p"},
    "daily": {"ts_code", "trade_date", "close"},
    "adj_factor": {"ts_code", "trade_date", "adj_factor"},
    "index_daily": {"ts_code", "trade_date", "close"},
    "index_member_all": {"ts_code", "in_date", "out_date"},  # O3:行业身份 l1/l2 由冻结 industry_values 取 code-or-name(name 是合法 fallback),此处只校 interval 字段
    "stock_basic": {"ts_code", "list_date", "delist_date"},  # delist_date value 可空,但键必须在,否则 active/delisted 语义不可审计
    "namechange": {"ts_code", "name", "start_date", "end_date"},  # end_date value 可空,但键必须在,否则当前名区间不可审计
    "trade_cal": {"cal_date", "is_open"},
}
FORWARD_FUND_HISTORY_YEARS = 3       # 基本面/价格回溯 3 年:覆盖 TTM(~2y)+ 早期 cohort 的 PIT 报表与建仓价
FORWARD_ENTRY_ANCHOR_LOOKAHEAD_DAYS = 14  # 默认只向前拿足建仓日历锚,不默认跨到 21d horizon
FORWARD_CALL_BUDGET_CAP = 10000      # runaway 兜底上限(精确对账见 fetch 内 expected_calls);真实 top-500+历史篮子约 ≤6k
# 显式决策(Finding 3):**no 自动 pacer**——lean 切片单次 gated 授权、约 4N+2P 调用,依赖 pinned tushare 客户端;真跑撞限流再加。
# **no raw payload 落盘**——纯内存装配,accumulator 是唯一 artifact(需 raw 审计另路由 gitignored;本切片不留 raw)。
FORWARD_PACING_DECISION = "none_per_run_gated"
FORWARD_RAW_PERSISTENCE = "none_in_memory_only_accumulator_is_sole_artifact"


# ── 段3:forward universe(top-N 主板 circ_mv)────────────────────────────────────────────────
def rank_forward_universe(market_cap_records: list, *, universe_size: int = UNIVERSE_SIZE_N) -> list:
    """复用冻结 `cap_audit.ranked_main_board_by_market_cap`(主板过滤 is_main_board_ts_code + circ_mv>0 + 降序)取 top-N,
    size bucket = `q{index//100+1}`(镜像 load_large_cap_signal_universes 415 行)。返回 [{symbol, market_cap, raw_rank, size_bucket}]。"""
    ranked = cap_audit.ranked_main_board_by_market_cap(market_cap_records)
    members = []
    for index, (symbol, market_cap) in enumerate(ranked[:universe_size]):
        members.append({"symbol": symbol, "market_cap": market_cap, "raw_rank": index + 1,
                        "size_bucket": f"q{(index // 100) + 1}"})
    return members


# ── 段4:内存 store / 手建 context / scored_items / 价格缓存 ─────────────────────────────────
def _payload(call_id: str, records: list) -> dict:
    return {"call_id": call_id, "call_status": "success",
            "columns": sorted({k for r in records for k in r.keys()}), "records": list(records)}


def build_forward_store(*, cashflow_by_symbol: dict, income_by_symbol: dict, daily_by_symbol: dict,
                        adj_by_symbol: dict, csi300_records: list):
    """内存 `base.audit.PayloadStore`(键 = `base.call_id_for(table, symbol)` / `base.benchmark_call_id`),
    供 `bf.batch_factor_values` / `base.stock_total_return_close_rows` / `base.index_total_return_close_rows` 原样读。"""
    payloads: dict = {}
    for table, by_symbol in (("cashflow", cashflow_by_symbol), ("income", income_by_symbol),
                             ("daily", daily_by_symbol), ("adj_factor", adj_by_symbol)):
        for symbol, records in by_symbol.items():
            cid = base.call_id_for(table, symbol)
            payloads[cid] = _payload(cid, records)
    # `bf.batch_factor_values` 还会 `store.records(balancesheet)`(算 book/accruals/roa/asset_growth)——这些**非本线构造**,
    # 但 `PayloadStore.records` 缺 call_id 会 KeyError;给每个 universe 票注册**空** balancesheet payload(→那 4 因子 missing,
    # cash_flow/sales 只读 cashflow/income 故不受影响,parity 保持)。
    for symbol in cashflow_by_symbol:
        cid = base.call_id_for("balancesheet", symbol)
        payloads.setdefault(cid, _payload(cid, []))
    csi_key = base.benchmark_call_id(CSI300_CODE)
    payloads[csi_key] = _payload(csi_key, csi300_records)
    return base.audit.PayloadStore(raw_root=Path("."), payloads=payloads)


def industry_records_by_symbol(index_member_records: list) -> dict:
    """SW 行业成员按 ts_code 分组,直接喂 `base.industry_context_for_symbol`。**不走 `base.load_industry_records` 的
    SW-repair 补丁**(那要全 materialized SW-repair artifact)。**缺成员行的票**:冻结 industry_context_for_symbol 对「活跃+无成员源」
    会 **raise**(非排除,行 822-825),故 `assemble_forward_inputs` 把无成员行的 member 放进 `exception_symbols` → industry_context
    返回 industry_excluded=True(不 raise)→ 退出行业中性、不入篮子(与冻结对 exception/缺行业的处置一致)。"""
    out: dict = {}
    for row in index_member_records:
        out.setdefault(str(row["ts_code"]), []).append(row)
    return out


def build_forward_context(*, symbols: list, trade_dates: list, list_date_by_symbol: dict,
                          delist_date_by_symbol: dict, selection_status_by_symbol: dict,
                          exception_symbols=frozenset(), list_status_by_symbol=None, as_of: str):
    """直接构 `base.SignalContext`(frozen dataclass),只填 forward 过滤/收益/name-veto 实际读到的字段;
    绕 `build_signal_context`(它要全 materialized manifest)。"""
    syms = list(symbols)
    lsbs = list_status_by_symbol or {}

    def _is_delisted(s: str) -> bool:
        # F2(security-master origin 保真):**优先 list_status**——D=已退市、L=在市,直接采用 provider 给的上市状态,
        # **不**靠 delist_date 字段推断(provider 常出现 list_status=D 但 delist_date 字段为空,纯 delist_date 判法会把
        # 这种已退市票误判成 active,继而喂进冻结 industry_context_for_symbol 的 active raise 路径)。
        st = lsbs.get(s)
        if st is not None:
            return st == "D"
        # 无 list_status 时(纯装配 / 历史 fixture 未带 origin)回退 PIT:as_of 时已过退市日才算 delisted(未来退市仍活跃)。
        d = delist_date_by_symbol.get(s)
        return bool(d and d <= as_of)

    return base.SignalContext(
        symbols=syms,
        active_symbols=[s for s in syms if not _is_delisted(s)],
        delisted_symbols=[s for s in syms if _is_delisted(s)],
        exception_symbols=set(exception_symbols),
        as_ofs=[as_of],
        trade_dates=list(trade_dates),
        list_date_by_symbol=dict(list_date_by_symbol),
        delist_date_by_symbol=dict(delist_date_by_symbol),
        selection_status_by_symbol=dict(selection_status_by_symbol),
    )


def forward_scored_items(*, store, context, ind_records_by_symbol: dict, universe_members: list, as_of: str) -> list:
    """镜像 `monthly_cohort_rows` 单 as_of 体(865-918):list/delist/name-veto 过滤 → `bf.batch_factor_values`
    (restatement_exclusions=∅:forward 无在册重述;price_rows/index_ret=∅:只取 2 value 因子,价格因子 missing 不报错)
    → 取 2 value 因子 + 行业 l2/l1 + size_bucket + market_cap。返回 scored_items(brain neutralize 的输入)。"""
    scored = []
    delisted_set = set(context.delisted_symbols)   # round 3:消费 list_status origin 分类结果,不只看 delist_date 字段
    for member in universe_members:
        symbol = member["symbol"]
        list_date = context.list_date_by_symbol.get(symbol, "00000000")
        delist_date = context.delist_date_by_symbol.get(symbol)
        if as_of < list_date:
            continue
        if symbol in delisted_set:   # round 3:D-origin / 已退市(含 list_status=D 但 delist_date 字段空)不入新 forward 篮子
            continue
        if delist_date is not None and as_of >= delist_date:
            continue
        if base.symbol_vetoed_at_selection_time(context, symbol, as_of):
            continue
        values, _status = bf.batch_factor_values(
            store=store, symbol=symbol, as_of=as_of, restatement_exclusions=frozenset(),
            circ_mv=member["market_cap"], price_rows={}, index_ret_by_date={}, trade_dates=context.trade_dates)
        if not any(family in values for family in VALUE_YIELD_FAMILIES):
            continue
        # F1:无 SW 成员行的票已由 assemble 放进 context.exception_symbols → 此处返回 industry_excluded=True(不 raise)。
        # carry industry_excluded 到 item:冻结 add_industry_neutral_scores 据它跳过该项 → 退出行业中性 → isn=None → 不入篮子。
        l2, l1, _source, excluded = base.industry_context_for_symbol(ind_records_by_symbol, context, symbol, as_of)
        item = {"symbol": symbol, "as_of": as_of, "industry_l2": l2, "industry_l1": l1,
                "industry_excluded": bool(excluded),
                "size_bucket": member["size_bucket"], "market_cap": member["market_cap"]}
        for family in VALUE_YIELD_FAMILIES:
            if family in values:
                item[family] = values[family]
        scored.append(item)
    return scored


def forward_price_caches(*, store, price_symbols: list) -> tuple:
    """每 symbol 的 total-return adj close(`base.stock_total_return_close_rows`)+ CSI300(`base.index_total_return_close_rows`)。
    price_symbols = 当期 universe ∪ 历史 cohort 篮子成员(后者供 backfill 旧 cohort 收益)。"""
    spc = {symbol: base.stock_total_return_close_rows(store, symbol) for symbol in price_symbols}
    csi = base.index_total_return_close_rows(store, CSI300_CODE)
    return spc, csi


def assemble_forward_inputs(*, as_of: str, market_cap_records: list, cashflow_by_symbol: dict,
                            income_by_symbol: dict, daily_by_symbol: dict, adj_by_symbol: dict,
                            csi300_records: list, index_member_records: list, list_date_by_symbol: dict,
                            delist_date_by_symbol: dict, selection_status_by_symbol: dict, trade_dates: list,
                            list_status_by_symbol=None, extra_price_symbols=(),
                            universe_size: int = UNIVERSE_SIZE_N) -> dict:
    """纯装配(mock 可测):raw records → brain `build_forward_accumulator` 直接用的 kwargs:
    {scored_items, stock_price_cache, csi300_prices, trade_dates, delist_by_symbol, universe_size}。
    `extra_price_symbols` = 历史 cohort 篮子成员(并入价格缓存,供 backfill 旧 cohort)。"""
    members = rank_forward_universe(market_cap_records, universe_size=universe_size)
    member_symbols = [m["symbol"] for m in members]
    store = build_forward_store(cashflow_by_symbol=cashflow_by_symbol, income_by_symbol=income_by_symbol,
                                daily_by_symbol=daily_by_symbol, adj_by_symbol=adj_by_symbol,
                                csi300_records=csi300_records)
    ind = industry_records_by_symbol(index_member_records)
    # F1:无 SW 成员行的 member 放进 exception_symbols → 冻结 industry_context_for_symbol 返回 industry_excluded=True(不 raise),
    # 退出行业中性(与冻结对缺行业的 exception 处置一致),避免「活跃票无行业成员源」首捕 abort。
    missing_membership = {s for s in member_symbols if s not in ind}
    context = build_forward_context(symbols=member_symbols, trade_dates=trade_dates,
                                    list_date_by_symbol=list_date_by_symbol,
                                    delist_date_by_symbol=delist_date_by_symbol,
                                    selection_status_by_symbol=selection_status_by_symbol,
                                    exception_symbols=missing_membership,
                                    list_status_by_symbol=list_status_by_symbol, as_of=as_of)
    scored = forward_scored_items(store=store, context=context, ind_records_by_symbol=ind,
                                  universe_members=members, as_of=as_of)
    price_symbols = list(dict.fromkeys(member_symbols + [s for s in extra_price_symbols if s in daily_by_symbol]))
    # round 3(Codex re-审查):D-origin(list_status=D)票要算 terminal/delist return lineage 必须有 delist_date;缺则
    # fail-closed——不得以 delist_by_symbol=None 让 backfill 把已退市票当未退市处理(污染 survivorship/terminal-return)。
    lsbs = list_status_by_symbol or {}
    d_origin_missing = [s for s in price_symbols if lsbs.get(s) == "D" and not delist_date_by_symbol.get(s)]
    if d_origin_missing:
        raise ValueError(f"D-origin securities lack delist_date needed for return/delist lineage: {d_origin_missing[:10]}")
    spc, csi = forward_price_caches(store=store, price_symbols=price_symbols)
    delist_by_symbol = {s: delist_date_by_symbol.get(s) for s in price_symbols}
    return {"scored_items": scored, "stock_price_cache": spc, "csi300_prices": csi,
            "trade_dates": list(trade_dates), "delist_by_symbol": delist_by_symbol,
            "universe_size": len(members)}


# ── 段4 gated 抓数(`pro` 注入,mock 可测接线;真 provider 形状 6-30 现写现验)────────────────
def _records(result) -> list:
    """tushare `pro.*` 返回 DataFrame → list[dict];mock/已是 list 直接放行。"""
    if result is None:
        return []
    if hasattr(result, "to_dict"):
        return result.to_dict("records")
    return list(result)


def _check_min_fields(records: list, table: str) -> list:
    """assembly 前 fail-closed:每条**已返回**记录必须含该 endpoint 的 min 字段(空返回合法——该票无该表数据)。"""
    required = FORWARD_REQUIRED_FIELDS[table]
    for row in records:
        missing = required - set(row.keys())
        if missing:
            raise ValueError(f"forward fetch `{table}`: provider 记录缺必备字段 {sorted(missing)}(契约不符,assembly 前 fail-closed)")
    return records


def _check_expected_value(records: list, table: str, field: str, expected: str, *, normalize_date: bool = False) -> list:
    """Per-call lineage guard: returned rows must belong to the requested symbol/date before assembly stores them."""
    for row in records:
        actual = base.normalize_yyyymmdd(row.get(field)) if normalize_date else str(row.get(field))
        if actual != expected:
            raise ValueError(f"forward fetch `{table}`: provider row {field}={actual!r} != requested {expected!r}")
    return records


def _parse_yyyymmdd(value: str, name: str) -> datetime:
    # round 3:strptime("%Y%m%d") 容忍非标准串(如 "2026071" / "202607 1"),先强制恰好 8 ASCII 数字再 round-trip 校历法日。
    s = str(value)
    if not (len(s) == 8 and s.isascii() and s.isdigit()):
        raise ValueError(f"{name} must be exactly 8 digits YYYYMMDD, got {value!r}")
    try:
        return datetime.strptime(s, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYYMMDD, got {value!r}") from exc


def _default_data_through(as_of: str) -> str:
    """默认向前取短日历窗口,只为冻结 next-open entry anchor;不默认跨到 21d horizon 造成早期 missing_exit。"""
    return (_parse_yyyymmdd(as_of, "as_of") + timedelta(days=FORWARD_ENTRY_ANCHOR_LOOKAHEAD_DAYS)).strftime("%Y%m%d")


def _resolve_data_through(as_of: str, data_through: str | None) -> str:
    parsed_as_of = _parse_yyyymmdd(as_of, "as_of")
    if data_through is None:
        return _default_data_through(as_of)
    parsed_end = _parse_yyyymmdd(data_through, "data_through")
    if parsed_end < parsed_as_of:
        raise ValueError(f"data_through {data_through} must be >= as_of {as_of}")
    return parsed_end.strftime("%Y%m%d")   # round 3:返回 canonical 8 位,不回传原始 noncanonical 串


def _forward_windows(as_of: str, data_through: str) -> dict:
    """explicit 抓数窗口:基本面/价格/日历回溯 FORWARD_FUND_HISTORY_YEARS 年(覆盖 TTM + 早期 cohort);价格/日历到
    data_through(供 backfill 旧 cohort 收益)。"""
    fund_start = f"{int(as_of[:4]) - FORWARD_FUND_HISTORY_YEARS}0101"
    return {"fund_start": fund_start, "fund_end": as_of, "price_start": fund_start,
            "price_end": data_through, "cal_start": fund_start, "cal_end": data_through}


def validate_as_of_month_end(as_of: str, trade_dates: list) -> None:
    """pre-broad-fetch fail-closed:as_of 须是其自然月在 trade_dates 里的**最后一个开市日**(月末决策日);
    缺当月开市日视为 calendar 证据不完整。**在拉 top-500 broad 数据前**校:非月末 as_of 一次 trade_cal 后即拒,不白拉数百 gated call。"""
    same_month = [d for d in trade_dates if d[:6] == as_of[:6]]
    if not same_month:
        raise ValueError(f"trade_cal 未覆盖 as_of {as_of} 所在月份的开市日,无法验证月末决策日")
    if max(same_month) != as_of:
        raise ValueError(f"as_of {as_of} 不是 {as_of[:6]} 的最后开市日(应为 {max(same_month)});forward-paper 用月末决策日")


def validate_entry_anchor(as_of: str, trade_dates: list) -> None:
    """pre-broad-fetch fail-closed:trade calendar 必须含 as_of 之后的首个开市日,否则新 cohort 会冻结 entry_date=None 永远无法 backfill。"""
    if not any(d > as_of for d in trade_dates):
        raise ValueError(f"trade_cal 未覆盖 as_of {as_of} 之后的首个开市日,无法冻结 forward entry anchor")


def fetch_forward_panel(*, as_of: str, pro, extra_price_symbols=(), data_through: str | None = None) -> dict:
    """gated 月末 PIT 真抓数 → `assemble_forward_inputs(**panel)` 的 kwargs。**call-plan 契约(Finding 3)**:每个 dated
    endpoint 带 explicit `start_date`/`end_date`(基本面回溯 FORWARD_FUND_HISTORY_YEARS 年覆盖 TTM;价格/日历到 data_through
    供 backfill);每次返回过 `_check_min_fields` fail-closed;call 数确定性对账(实==预期、且 ≤ runaway cap,否则 raise);
    **no 自动 pacer / no raw 落盘**(FORWARD_PACING_DECISION / FORWARD_RAW_PERSISTENCE)。`pro` 注入 → mock 可测接线;真
    provider 字段/分页在第一笔真捕获(as_of≥20260630)现写现验。data_through 默认 = as_of 后短窗口,
    只为冻结 next-open entry anchor;更长 backfill 窗口必须显式传入。"""
    data_through = _resolve_data_through(as_of, data_through)
    w = _forward_windows(as_of, data_through)
    calls = 0

    # pre-broad calendar guard(Codex re-审查):先拉**轻量** trade_cal → 校 as_of 月末 + next-open entry anchor,**再**拉
    # top-500 broad 数据;非月末 / 无 entry 的 as_of 在 1 次 trade_cal 后即 fail-closed,不白拉数百 gated call。
    trade_cal_records = _check_min_fields(_records(pro.trade_cal(
        exchange="SSE", start_date=w["cal_start"], end_date=w["cal_end"], fields="cal_date,is_open")), "trade_cal"); calls += 1
    trade_dates = sorted(base.normalize_yyyymmdd(r.get("cal_date")) for r in trade_cal_records
                         if str(r.get("is_open")) == "1" and base.normalize_yyyymmdd(r.get("cal_date")))
    validate_as_of_month_end(as_of, trade_dates)
    validate_entry_anchor(as_of, trade_dates)

    market_cap_records = _check_expected_value(
        _check_min_fields(_records(pro.daily_basic(trade_date=as_of, fields="ts_code,trade_date,circ_mv")),
                          "daily_basic"),
        "daily_basic", "trade_date", as_of, normalize_date=True,
    ); calls += 1
    members = rank_forward_universe(market_cap_records)
    member_symbols = [m["symbol"] for m in members]
    # round 3(Codex re-审查):live fetch 路径必须能从 daily_basic 组出非空 top-N investable universe;空(provider 宕机/
    # 错 endpoint/坏授权/全非主板/circ_mv<=0)即 fail-closed,不得静默写出 universe_size=0 的「假 insufficient」paper 月。
    if not member_symbols:
        raise ValueError("forward fetch daily_basic 组不出非空 top-N 主板 universe(空返回/全非主板/circ_mv<=0);fail-closed")
    price_symbols = list(dict.fromkeys(member_symbols + list(extra_price_symbols)))

    cashflow_by_symbol, income_by_symbol, daily_by_symbol, adj_by_symbol = {}, {}, {}, {}
    for symbol in member_symbols:
        cashflow_by_symbol[symbol] = _check_expected_value(_check_min_fields(_records(pro.cashflow(
            ts_code=symbol, start_date=w["fund_start"], end_date=w["fund_end"],
            fields="ts_code,ann_date,f_ann_date,end_date,n_cashflow_act")), "cashflow"), "cashflow", "ts_code", symbol); calls += 1
        income_by_symbol[symbol] = _check_expected_value(_check_min_fields(_records(pro.income(
            ts_code=symbol, start_date=w["fund_start"], end_date=w["fund_end"],
            fields="ts_code,ann_date,f_ann_date,end_date,revenue,n_income_attr_p")), "income"), "income", "ts_code", symbol); calls += 1
    for symbol in price_symbols:
        daily_by_symbol[symbol] = _check_expected_value(_check_min_fields(_records(pro.daily(
            ts_code=symbol, start_date=w["price_start"], end_date=w["price_end"],
            fields="ts_code,trade_date,close")), "daily"), "daily", "ts_code", symbol); calls += 1
        adj_by_symbol[symbol] = _check_expected_value(_check_min_fields(_records(pro.adj_factor(
            ts_code=symbol, start_date=w["price_start"], end_date=w["price_end"],
            fields="ts_code,trade_date,adj_factor")), "adj_factor"), "adj_factor", "ts_code", symbol); calls += 1

    csi300_records = _check_expected_value(_check_min_fields(_records(pro.index_daily(
        ts_code=CSI300_CODE, start_date=w["price_start"], end_date=w["price_end"],
        fields="ts_code,trade_date,close")), "index_daily"), "index_daily", "ts_code", CSI300_CODE); calls += 1
    index_member_records, namechange_records = [], []
    for symbol in member_symbols:
        # F3-guard:index_member_all(ts_code=symbol) 容忍 provider 返回额外行——只保留 ts_code==symbol 的成员行(对齐已验证的
        # SW-repair runner 模式:数匹配、不强求每行匹配);缺成员→空(assemble 据 exception_symbols 优雅排除,不 abort)。
        member_rows = [r for r in _check_min_fields(_records(pro.index_member_all(
            ts_code=symbol, fields="ts_code,name,l1_code,l1_name,l2_code,l2_name,in_date,out_date,is_new")),
            "index_member_all") if str(r.get("ts_code")) == symbol]
        index_member_records.extend(member_rows); calls += 1
        namechange_records.extend(_check_expected_value(_check_min_fields(_records(pro.namechange(
            ts_code=symbol,
            fields="ts_code,name,start_date,end_date")), "namechange"), "namechange", "ts_code", symbol)); calls += 1
    basic_l = _check_min_fields(_records(pro.stock_basic(list_status="L", fields="ts_code,list_date,delist_date")), "stock_basic"); calls += 1
    basic_d = _check_min_fields(_records(pro.stock_basic(list_status="D", fields="ts_code,list_date,delist_date")), "stock_basic"); calls += 1

    expected_calls = 1 + 4 * len(member_symbols) + 2 * len(price_symbols) + 4
    if calls != expected_calls or calls > FORWARD_CALL_BUDGET_CAP:
        raise ValueError(f"forward fetch call 对账失败:实 {calls} ≠ 预期 {expected_calls}(或超 cap {FORWARD_CALL_BUDGET_CAP})")

    list_date_by_symbol, delist_date_by_symbol, list_status_by_symbol = {}, {}, {}
    for row in basic_l:
        list_status_by_symbol[str(row.get("ts_code"))] = "L"
    for row in basic_d:
        list_status_by_symbol[str(row.get("ts_code"))] = "D"   # security-master origin 保真;同票两表都有时 D(已退市)覆盖
    for row in basic_l + basic_d:
        ts = str(row.get("ts_code"))
        list_date_by_symbol[ts] = base.normalize_yyyymmdd(row.get("list_date")) or "00000000"
        delist_date_by_symbol[ts] = base.normalize_yyyymmdd(row.get("delist_date"))
    missing_master = [symbol for symbol in price_symbols if symbol not in list_date_by_symbol]
    if missing_master:
        raise ValueError(f"forward fetch stock_basic missing security-master rows for {missing_master[:10]}")
    selection_status_by_symbol: dict = {}
    for row in namechange_records:
        ts = str(row.get("ts_code"))
        selection_status_by_symbol.setdefault(ts, []).append(
            {"name": row.get("name"), "start_date": base.normalize_yyyymmdd(row.get("start_date")),
             "end_date": base.normalize_yyyymmdd(row.get("end_date"))})

    return {"as_of": as_of, "market_cap_records": market_cap_records,
            "cashflow_by_symbol": cashflow_by_symbol, "income_by_symbol": income_by_symbol,
            "daily_by_symbol": daily_by_symbol, "adj_by_symbol": adj_by_symbol,
            "csi300_records": csi300_records, "index_member_records": index_member_records,
            "list_date_by_symbol": list_date_by_symbol, "delist_date_by_symbol": delist_date_by_symbol,
            "list_status_by_symbol": list_status_by_symbol,
            "selection_status_by_symbol": selection_status_by_symbol, "trade_dates": trade_dates,
            "extra_price_symbols": tuple(extra_price_symbols)}
