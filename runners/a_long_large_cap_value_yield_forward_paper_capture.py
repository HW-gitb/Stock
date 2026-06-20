#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-long large-cap value-yield FORWARD-PAPER capture runner (the separate slice authorized by the
reviewed prereg `a_long_large_cap_value_yield_forward_paper_tracking_20260609`).

定位:**research-only · PAPER 证据 · 非 production · 不碰真钱 · 不满足 ship-gate**。对 2 条样本内幸存但
NOT-tradeable 的研究线索(`cash_flow_to_circ_mv` / `sales_to_circ_mv`)+ 1 个唯一可升级合成
(`value_yield_composite_cf_sales`)做每月 month-end snapshot + backfill-as-mature 的前向(out-of-sample)
累积,产出 `a_long_large_cap_value_yield_forward_paper_accumulator` artifact(schema 校验)。

**复用冻结规则不变(prereg `reuses_batch_frozen_rules_unchanged`)**:因子/中性化/篮子/收益度量直接 import
冻结的 batch runner `a_long_large_cap_batch_factor_search_signal_search`(下称 bf)+ base 的 pure 函数,**绝不改那个
冻结、已 review、已提交的 artifact**。bf 的**编排层**(`monthly_cohort_rows`/`rolling_relative_nav_drawdown`/
`load_large_cap_signal_universes`)写死在固定样本内 `MONTHLY_AS_OF_DATES` 上,无法直接指向前向月;故本 runner
**重写薄前向编排**(单 as_of cohort + 前向 rolling-NAV),其中 rolling-NAV 是 `bf.rolling_relative_nav_drawdown`
的逐字镜像、唯一差别是 `checkpoints` 改为参数 —— 由 parity 测试钉死「checkpoints==sorted(bf.MONTHLY_AS_OF_DATES)
时与冻结函数逐字段相等」。

**Commit-safe but NOT execution-safe**:实盘前向数据(月末 PIT top-500 + cashflow/revenue TTM + 价格 + 基准)
样本内面板(2018-2025)没有,需逐月 gated 抓数;**每次抓数需用户单独授权**;第一笔 as_of ≥ 2026-06-30。本切片
落 analysis/accumulator 核心 + 前向 rolling-NAV(parity)+ **编排核心 brain(`build_forward_accumulator`)+ lean top-500
数据层(`..._data_layer.py`:gated fetch + 纯装配,复用冻结 bf/base 因子·收益·行业·name-veto 函数)+ main 接线
(`run_forward_capture`)全建、mock 测**;**只剩第一笔真捕获(as_of≥20260630)的 live provider 形状现写现验**(可能按
真返回字段微调 `dl.fetch_forward_panel`)。lean = 只 top-500、只拉算 2 value 因子 + 收益 + 中性化所需表(非全主板 materialization)。

升级:per-monthly capture **不花** singleton ledger;只有 paper window 结束后对**唯一** primary 构造
`value_yield_composite_cf_sales` 的 promote/stay/drop 决策花掉(且 promote 仅意味着可提一份**新 reviewed real-money
prereg**,本 artifact 不授权真钱、不做 best-of-three)。
"""
from __future__ import annotations

import argparse
import json
import os
from statistics import mean

from runners import a_long_large_cap_batch_factor_search_signal_search as bf
from runners import a_long_full_main_board_signal_search as base
from runners import a_long_large_cap_value_yield_forward_paper_data_layer as dl

SCHEMA_NAME = "a_long_large_cap_value_yield_forward_paper_accumulator"
SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schemas", "a_long_large_cap_value_yield_forward_paper_accumulator.schema.json")
PREREG_ID = "a_long_large_cap_value_yield_forward_paper_tracking_20260609"
PREREG_PATH = "research/preregistrations/a_long_large_cap_value_yield_forward_paper_tracking_20260609.json"
SCHEMA_REL_PATH = "schemas/a_long_large_cap_value_yield_forward_paper_accumulator.schema.json"
LEDGER_PATH = "research/ledgers/a_long_large_cap_value_yield_forward_paper_tracking_program_test_budget_ledger_20260609.json"
BATCH_EXECUTION_SUMMARY_PATH = "research/results/a_long_large_cap_batch_factor_search_20260609/execution_summary.json"
# accumulator 必备 source_refs 的**精确路径**集合(exact match,非子串——防 evil/...not_the_right_...ledger.json 之类
# 仍含子串却脱离 prereg/ledger/batch 血缘的伪路径)。build_accumulator 与 validate_accumulator_consistency 共用此单一来源。
REQUIRED_SOURCE_REF_PATHS = (PREREG_PATH, LEDGER_PATH, BATCH_EXECUTION_SUMMARY_PATH, SCHEMA_REL_PATH)

# ── 冻结常量 parity-pin(与冻结 bf 逐字相等;漂移即 import 期 AssertionError,杜绝静默偏离冻结构造)──
PRIMARY_HORIZON = 504
INTERIM_HORIZONS = [21, 63, 126, 252]
ALL_HORIZONS = INTERIM_HORIZONS + [PRIMARY_HORIZON]   # [21,63,126,252,504];accumulator horizon 键集(504 主判据,interim 诊断早读)
VALUE_YIELD_FAMILIES = ("cash_flow_to_circ_mv", "sales_to_circ_mv")  # 合成的 2 个成分单因子
MIN_MONTHLY_COHORTS_FOR_PAPER_READ = 12
TRADEABLE_DRAWDOWN_FLOOR = -0.15
START_FLOOR = "20260630"
PRIMARY_CONSTRUCTION_ID = "value_yield_composite_cf_sales"
assert PRIMARY_HORIZON == bf.PRIMARY_HORIZON, "PRIMARY_HORIZON drift vs frozen batch runner"
assert bf.TOP_FRACTION == 0.2 and bf.MIN_TOP_COUNT == 10, "basket rule drift vs frozen batch runner"

# 冻结 3 构造 id(2 单因子诊断 + 1 合成 primary);construction_metrics 与每个 cohort 的 constructions 都须**恰好覆盖各一次**。
FROZEN_CONSTRUCTION_IDS = ("cash_flow_to_circ_mv", "sales_to_circ_mv", PRIMARY_CONSTRUCTION_ID)

# 3 构造:2 单因子(仅诊断)+ 1 合成(唯一可升级)。construction_id 与 accumulator schema enum 一致。
CONSTRUCTIONS = (
    {"construction_id": "cash_flow_to_circ_mv", "promotion_role": "diagnostic_supporting_only",
     "score_field": "cash_flow_to_circ_mv__industry_size_neutral"},
    {"construction_id": "sales_to_circ_mv", "promotion_role": "diagnostic_supporting_only",
     "score_field": "sales_to_circ_mv__industry_size_neutral"},
    {"construction_id": PRIMARY_CONSTRUCTION_ID, "promotion_role": "primary_promotion_construction",
     "score_field": "value_yield_composite_cf_sales__industry_size_neutral"},
)


def value_yield_composite_score(item: dict) -> float | None:
    """prereg 冻结合成 = 2 个 value yield 的 `__industry_size_neutral` 百分位等权均值(两者皆有才算;否则 None)。
    **不复用 bf.add_composite_scores**(那是 batch 的 family-balanced 合成,跨全部家族含已死的,正是 prereg 指出
    它把 value-yield 稀释、故未单独测过的原因)。此处是 prereg 新冻结的 2-因子等权 value 合成。"""
    cf = item.get("cash_flow_to_circ_mv__industry_size_neutral")
    sales = item.get("sales_to_circ_mv__industry_size_neutral")
    if cf is None or sales is None:
        return None
    return (float(cf) + float(sales)) / 2.0


# ── 前向 rolling relative-NAV(bf.rolling_relative_nav_drawdown 的逐字镜像;唯一差别:checkpoints 参数化)──
# parity(test_forward_rolling_nav_parity):checkpoints==sorted(bf.MONTHLY_AS_OF_DATES) 时与冻结函数逐字段相等。
# 复用 bf._close_lookup / bf.entry_and_scheduled_exit(用 bf.PRIMARY_HORIZON=504)/ bf.max_drawdown_on_levels /
# base.ROUND_TRIP_COST,使镜像与冻结实现共享同一份底层逻辑,差别仅 checkpoints 来源。
def forward_rolling_relative_nav_drawdown(*, primary_selections, stock_price_cache, csi300_prices,
                                          trade_dates, checkpoints) -> dict:
    cps = sorted(checkpoints)
    csi_lookup = bf._close_lookup(csi300_prices)
    symbol_lookup: dict = {}
    tranches: list = []
    for as_of in sorted(primary_selections):
        symbols = primary_selections.get(as_of) or []
        if not symbols:
            continue
        entry_date, scheduled_exit = bf.entry_and_scheduled_exit(as_of, trade_dates)
        if entry_date is None or scheduled_exit is None:
            continue
        entry_csi = csi_lookup(entry_date)
        if entry_csi is None or entry_csi <= 0:
            continue
        basket: list = []
        for symbol in symbols:
            prices = stock_price_cache.get(symbol) or {}
            entry_close = prices.get(entry_date, {}).get("close")
            if entry_close is None or entry_close <= 0:
                continue
            if symbol not in symbol_lookup:
                symbol_lookup[symbol] = bf._close_lookup(prices)
            basket.append((symbol, entry_close))
        if basket:
            tranches.append({"entry_date": entry_date, "scheduled_exit": scheduled_exit,
                             "entry_csi": entry_csi, "basket": basket})
    strategy_nav: list = []
    relative_nav: list = []
    for checkpoint in cps:
        strategy_values: list = []
        benchmark_values: list = []
        for tranche in tranches:
            if not (tranche["entry_date"] <= checkpoint <= tranche["scheduled_exit"]):
                continue
            checkpoint_csi = csi_lookup(checkpoint)
            if checkpoint_csi is None or checkpoint_csi <= 0:
                continue
            multiples: list = []
            for symbol, entry_close in tranche["basket"]:
                checkpoint_close = symbol_lookup[symbol](checkpoint)
                if checkpoint_close is None or checkpoint_close <= 0:
                    continue
                multiples.append(checkpoint_close / entry_close)
            if not multiples:
                continue
            strategy_values.append(mean(multiples) - base.ROUND_TRIP_COST)
            benchmark_values.append(checkpoint_csi / tranche["entry_csi"])
        if not strategy_values or not benchmark_values:
            continue
        strategy_level = mean(strategy_values)
        benchmark_level = mean(benchmark_values)
        strategy_nav.append(strategy_level)
        if benchmark_level > 0:
            relative_nav.append(strategy_level / benchmark_level)
    return {
        "tranche_count": len(tranches),
        "relative_nav_checkpoint_count": len(relative_nav),
        "relative_nav_max_drawdown": None if not relative_nav else round(bf.max_drawdown_on_levels(relative_nav), 10),
        "absolute_strategy_nav_max_drawdown": None if not strategy_nav else round(bf.max_drawdown_on_levels(strategy_nav), 10),
    }


# ── paper read 路由(据 primary 构造的 OOS 持续性 + 回撤;advisory,不授权真钱)─────────────────────────
def compute_paper_read(primary_metrics: dict, matured_cohort_count: int) -> dict:
    """唯一在 primary 构造 value_yield_composite_cf_sales 上判;< 12 matured cohort → insufficient(不评)。
    promote_eligible(持续为正 ∧ 回撤 ≥ -0.15)**不授权真钱**,仅意味着可提一份新 reviewed real-money prereg。"""
    read_available = matured_cohort_count >= MIN_MONTHLY_COHORTS_FOR_PAPER_READ
    meets_persistence = None
    meets_drawdown = None
    routing = "insufficient_cohorts"
    if read_available:
        dd = primary_metrics.get("rolling_relative_nav_max_drawdown")
        meets_persistence = bool(primary_metrics.get("persistence_positive"))
        meets_drawdown = (dd is not None and dd >= TRADEABLE_DRAWDOWN_FLOOR)
        routing = ("promote_eligible_pending_new_reviewed_real_money_prereg"
                   if (meets_persistence and meets_drawdown) else "stay_research_only_or_drop")
    return {
        "primary_construction_id": PRIMARY_CONSTRUCTION_ID,
        "matured_cohort_count": matured_cohort_count,
        "min_cohorts_required": MIN_MONTHLY_COHORTS_FOR_PAPER_READ,
        "read_available": read_available,
        "tradeable_drawdown_floor": TRADEABLE_DRAWDOWN_FLOOR,
        "meets_persistence": meets_persistence,
        "meets_drawdown": meets_drawdown,
        "routing": routing,
        "decision_is_advisory_not_authorization": True,
    }


def build_accumulator(*, cohorts: list, construction_metrics: list, paper_read: dict,
                      as_of_latest_capture: str, generated_at: str) -> dict:
    """组装 accumulator artifact(schema 校验前的 dict)。frozen 构造不在此复制,只引用 prereg(单一来源)。"""
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": str(generated_at),
        "as_of_latest_capture": str(as_of_latest_capture),
        "scope": {
            "lane_id": "a_long", "research_only": True, "evidence_level": "paper",
            "paper_evidence_satisfies_ship_gate": False, "real_money_committed": False,
            "production_use_allowed": False, "out_of_sample_only": True,
        },
        "source_refs": [
            {"path": PREREG_PATH, "role": "reviewed forward-paper preregistration (frozen construction + decision rule)"},
            {"path": LEDGER_PATH,
             "role": "singleton ledger (one promotion decision; monthly captures do not spend)"},
            {"path": BATCH_EXECUTION_SUMMARY_PATH,
             "role": "the executed batch result whose 2 surviving research-only clues this paper-tracks"},
            {"path": SCHEMA_REL_PATH,
             "role": "this accumulator output contract"},
        ],
        "frozen_construction_ref": {
            "prereg_artifact_id": PREREG_ID, "prereg_path": PREREG_PATH,
            "reuses_frozen_rules_unchanged": True,
        },
        "forward_window": {
            "start_floor": START_FLOOR, "capture_cadence": "monthly",
            "minimum_monthly_cohorts_for_paper_read": MIN_MONTHLY_COHORTS_FOR_PAPER_READ,
            "primary_horizon_trading_days": PRIMARY_HORIZON,
            "interim_horizons_trading_days": list(INTERIM_HORIZONS),
        },
        "cohorts": cohorts,
        "construction_metrics": construction_metrics,
        "paper_read": paper_read,
        "prohibited_claims": {
            "paper_is_ship_gate_evidence": False, "alpha_validated": False,
            "tradeable_candidate_confirmed": False, "real_money_authorized": False,
            "production_ready": False, "full_size_allowed": False,
        },
        "boundary": {"production": False, "real_money": False,
                     "is_validated_alpha": False, "satisfies_ship_gate": False},
    }


def _check_role_id(obj: dict) -> None:
    cid, role = obj["construction_id"], obj["promotion_role"]
    expected = "primary_promotion_construction" if cid == PRIMARY_CONSTRUCTION_ID else "diagnostic_supporting_only"
    if role != expected:
        raise ValueError(f"{cid}: promotion_role={role!r} 须 {expected!r}(单因子仅诊断,只有合成 value_yield_composite_cf_sales 可 primary)")


def _check_construction_id_coverage(rows: list, where: str) -> None:
    """每个 block(construction_metrics / 每个 cohort 的 constructions)须**恰好覆盖 3 冻结构造、每个一次**
    (无重复、无缺失、无未知)。schema enum 已挡未知 id、if/then 已焊 promotion_role↔id,但 draft-07 的
    uniqueItems 只能整项相等,挡不住「同 construction_id 不同字段的重复行」或「缺某构造」——故跨行 multiset 身份
    在此 Python 焊(R-ALONG-VY-FP-ACCUMULATOR residual:重复 construction_metrics / cohort 内重复构造 / cohort 缺 primary)。"""
    got = sorted(r["construction_id"] for r in rows)
    if got != sorted(FROZEN_CONSTRUCTION_IDS):
        raise ValueError(f"{where}: construction_id 须恰好覆盖 3 冻结构造各一次(无重复/缺失),实为 {got}")


def validate_accumulator_consistency(acc: dict) -> None:
    """R-ALONG-VY-FP-ACCUMULATOR-SCHEMA-PROMOTION-GATE-GAP:draft-07 表达不了的**跨字段/跨行**不变式(schema 已焊
    shape/enum/promotion_role↔id/matured-非空/horizon 键集/symbol 唯一/每 block 恰 3 项;此处焊 read↔routing↔metrics、
    pre-start、cohort as_of 唯一、as_of_latest_capture↔最新 cohort、每 block 恰好覆盖 3 构造各一次、basket↔size、matured 计数、source_refs 精确路径)。
    write_accumulator 在 schema 校验后调;hand-built/drift artifact 也 fail-closed。被 schema 已挡的此处再复核一层,
    单一来源 = 本函数 + schema 双焊。"""
    pr = acc["paper_read"]
    n = pr["matured_cohort_count"]
    # read↔routing 跨字段(promote 不得越级:< 12 cohort / 未达持续性·回撤 → 不得 promote;够 cohort 不得 insufficient)
    if pr["read_available"] != (n >= MIN_MONTHLY_COHORTS_FOR_PAPER_READ):
        raise ValueError(f"read_available={pr['read_available']} 与 matured_cohort_count({n})≥{MIN_MONTHLY_COHORTS_FOR_PAPER_READ} 不一致")
    routing = pr["routing"]
    if routing == "insufficient_cohorts" and pr["read_available"]:
        raise ValueError("routing=insufficient_cohorts 但 read_available=true(够 cohort 不得标 insufficient)")
    if routing == "promote_eligible_pending_new_reviewed_real_money_prereg" and not (
            pr["read_available"] and pr.get("meets_persistence") and pr.get("meets_drawdown")):
        raise ValueError("routing=promote_eligible 但未满足 read_available∧persistence∧drawdown(不得越级 promote)")
    if routing == "stay_research_only_or_drop" and not pr["read_available"]:
        raise ValueError("routing=stay_research_only_or_drop 但 read_available=false(不足 cohort 应为 insufficient)")
    if pr["primary_construction_id"] != PRIMARY_CONSTRUCTION_ID:
        raise ValueError(f"primary_construction_id={pr['primary_construction_id']!r} 必须是 {PRIMARY_CONSTRUCTION_ID!r}(单因子不得为 primary;no best-of-three)")
    # cohorts:as_of 唯一(防同月重复 cohort 双计 matured 越过 12 门)+ pre-start + 每 cohort 恰好 3 构造各一次 + role↔id + basket↔size + 空篮子状态
    cohort_as_ofs = [c["as_of"] for c in acc["cohorts"]]
    if len(cohort_as_ofs) != len(set(cohort_as_ofs)):
        dups = sorted(a for a in set(cohort_as_ofs) if cohort_as_ofs.count(a) > 1)
        raise ValueError(f"cohorts 含重复 as_of(monthly cohort 须唯一,防同月重复双计 matured):{dups}")
    for c in acc["cohorts"]:
        if c["as_of"] < START_FLOOR:
            raise ValueError(f"cohort as_of={c['as_of']} < start_floor {START_FLOOR}(pre-start cohort 不得计入前向 OOS)")
        _check_construction_id_coverage(c["constructions"], f"cohort {c['as_of']}")
        for con in c["constructions"]:
            _check_role_id(con)
            ss = con["selected_symbols"]
            if con["basket_size"] != len(ss) and not (con["basket_size"] == 0 and len(ss) == 0):
                raise ValueError(f"{c['as_of']}/{con['construction_id']}: basket_size({con['basket_size']})≠selected_symbols 数({len(ss)})")
            if con["basket_size"] == 0 and "insufficient" not in con["entry_status"]:
                raise ValueError(f"{c['as_of']}/{con['construction_id']}: 空篮子(basket_size=0)须标 insufficient* entry_status,实为 {con['entry_status']!r}")
    # as_of_latest_capture 必须 == 最新 cohort 的 as_of(防 capture metadata 与实际 cohort 集漂移)
    if cohort_as_ofs:
        latest = max(cohort_as_ofs)
        if acc["as_of_latest_capture"] != latest:
            raise ValueError(f"as_of_latest_capture({acc['as_of_latest_capture']})≠ 最新 cohort as_of({latest})")
    # construction_metrics:恰好覆盖 3 构造各一次(无重/缺)+ role↔id + **每个构造**(O1:不只 primary——诊断构造计数也不得伪造)
    # matured_cohort_count == 该构造实际 504-horizon matured cohort 数;primary 的再 == paper_read.matured(防虚报成熟数越 12 门 promote)。
    _check_construction_id_coverage(acc["construction_metrics"], "construction_metrics")

    def _actual_504_matured(construction_id: str) -> int:
        return sum(1 for c in acc["cohorts"] for con in c["constructions"]
                   if con["construction_id"] == construction_id
                   and (con["horizons"].get(str(PRIMARY_HORIZON)) or {}).get("status") == "matured")
    for m in acc["construction_metrics"]:
        _check_role_id(m)
        actual = _actual_504_matured(m["construction_id"])
        if m["matured_cohort_count"] != actual:
            raise ValueError(f"{m['construction_id']} matured_cohort_count({m['matured_cohort_count']})≠ 实际 {PRIMARY_HORIZON}-horizon matured cohort 数({actual})")
        if m["construction_id"] == PRIMARY_CONSTRUCTION_ID and m["matured_cohort_count"] != n:
            raise ValueError(f"primary 构造 matured_cohort_count({m['matured_cohort_count']})≠ paper_read({n})")
    # source_refs 必含 prereg/ledger/batch/schema 四类**精确路径**(exact match,非子串:防 evil/...含子串却脱离血缘的伪路径)
    present = {r["path"] for r in acc["source_refs"]}
    for need in REQUIRED_SOURCE_REF_PATHS:
        if need not in present:
            raise ValueError(f"source_refs 缺必备精确引用(exact path,非子串匹配):{need}")


def validate_accumulator_dict(acc: dict) -> None:
    """Shared accumulator guard: schema(shape/enum/if-then) + cross-field consistency."""
    import jsonschema
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        jsonschema.validate(acc, json.load(f))
    validate_accumulator_consistency(acc)


def write_accumulator(acc: dict, out_path: str) -> None:
    """唯一 sanctioned 写盘:schema(shape/enum/if-then)+ 跨字段一致性 双校验后原子写。"""
    validate_accumulator_dict(acc)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(acc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


# ── 编排核心(brain):scored items + 价格缓存 → cohort snapshot + backfill 收益 + 构造指标 + accumulator ──
# 数据层(6-30 单独建,gated)产出 scored_items(每项已含 cash_flow_to_circ_mv/sales_to_circ_mv/industry_l2/
# industry_l1/size_bucket/market_cap/symbol/as_of,由月末 PIT 抓数 + bf.batch_factor_values 算)+ stock_price_cache
# (total-return adj close,base.stock_total_return_close_rows)+ csi300_prices + trade_dates + delist_by_symbol。
# 本层纯函数、复用冻结 bf/base pure fn、可用 synthetic items/prices 单测;不碰 store/抓数。

def _construction_in(cohort: dict, construction_id: str):
    for con in cohort["constructions"]:
        if con["construction_id"] == construction_id:
            return con
    return None


def _first_trade_day_after(as_of: str, trade_dates: list):
    return next((d for d in trade_dates if d > as_of), None)


def neutralize_value_yield_scores(items: list) -> None:
    """对 scored items 原地跑冻结中性化序列(仅 2 个 value-yield family + 合成),写 3 个 score_field:
    cash_flow/sales 的 `__industry_size_neutral` + 合成 `value_yield_composite_cf_sales__industry_size_neutral`。
    镜像 batch monthly_cohort_rows 920-927:percentile→industry→size→marginal (industry+size)/2;**合成 = 2 个
    isn 等权均值**(prereg 冻结,**非** bf.add_composite_scores 的全 9-family COMPOSITE_ID)。size 中性需该 bucket
    ≥ MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY、industry 中性需该组够数(冻结 bf/base 内部门限),不足则该项 isn 缺→合成 None。"""
    for family in VALUE_YIELD_FAMILIES:
        base.percentile_scores(items, family, f"{family}__non_neutral")
        base.add_industry_neutral_scores(items, family)
        bf.add_size_neutral_scores(items, family)
    bf.add_marginal_industry_size_neutral_scores(items, list(VALUE_YIELD_FAMILIES))
    for item in items:
        composite = value_yield_composite_score(item)
        if composite is not None:
            item[f"{PRIMARY_CONSTRUCTION_ID}__industry_size_neutral"] = composite


def select_basket(items: list, score_field: str) -> list:
    """forward 篮子(**entry 即定,只按 score,不看未来收益**——in-sample cohort_excess_by_as_of 的 excess-present
    过滤是 look-ahead,forward 不可用)。镜像其 sort+top-fraction:score 非 None 的项 < MIN_TOP_COUNT 则空篮子;
    按 score desc 取 max(MIN_TOP_COUNT, int(n*TOP_FRACTION))。返回 **sorted-by-symbol**(确定序,配 schema uniqueItems;
    等权篮子成员身份才重要、序无关)。"""
    scored = [it for it in items if it.get(score_field) is not None]
    if len(scored) < bf.MIN_TOP_COUNT:
        return []
    scored.sort(key=lambda it: it[score_field], reverse=True)
    target = max(bf.MIN_TOP_COUNT, int(len(scored) * bf.TOP_FRACTION))
    return sorted(str(it["symbol"]) for it in scored[:target])


def build_cohort_snapshot(as_of: str, scored_items: list, *, captured_at: str, universe_size: int,
                          trade_dates: list) -> dict:
    """本月 as_of 的 cohort snapshot:3 构造各 select_basket;horizons 全 pending(收益随后 backfill 回填)。
    空篮子→entry_status/horizon=insufficient_basket、entry_date=None;有篮子但无 entry 交易日→missing_entry_close。
    **必须先对 scored_items 跑 neutralize_value_yield_scores**(否则 score_field 缺、篮子空)。"""
    entry_date = _first_trade_day_after(as_of, trade_dates)
    constructions = []
    for con in CONSTRUCTIONS:
        basket = select_basket(scored_items, con["score_field"])
        if not basket:
            entry_status, hz_status, eff_entry = "insufficient_basket", "insufficient_basket", None
        elif entry_date is None:
            entry_status, hz_status, eff_entry = "missing_entry_date", "missing_entry_close", None
        else:
            entry_status, hz_status, eff_entry = "ok", "pending", entry_date
        horizons = {str(h): {"status": hz_status, "relative_excess_net": None,
                             "exit_date": None, "exit_policy": None} for h in ALL_HORIZONS}
        constructions.append({
            "construction_id": con["construction_id"], "promotion_role": con["promotion_role"],
            "basket_size": len(basket), "selected_symbols": basket,
            "entry_date": eff_entry, "entry_status": entry_status, "horizons": horizons})
    return {"as_of": as_of, "captured_at": str(captured_at), "universe_size": int(universe_size),
            "pit_source": "forward_live_frozen_at_as_of", "constructions": constructions}


def backfill_cohort(cohort: dict, *, stock_price_cache: dict, csi300_prices: dict,
                    trade_dates: list, delist_by_symbol: dict) -> None:
    """原地回填一个 cohort。**Finding 1(PIT 冻结锚)**:用快照里**冻结的** `entry_date` 当锚、**绝不重算**;
    entry_status==ok ⟹ 冻结 entry 必须存在、在 trade_dates、且 == 当前日历重算的 first-open-after-as_of(不符 =
    历史日历被改 → fail-closed 拒绝静默重锚,防 OOS 证据被污染)。**Finding 2(实际 exit 政策)**:保留
    base.resolve_return_dates 的真实 exit 政策——全 scheduled 才标 `scheduled_exit_basket_equal_weight`;含
    delist/terminal/next-available → `mixed_member_exits:<组成>` 审计串(绝不把 delist 篮子伪装成 scheduled,保 survivorship 证据)。
    每 horizon:scheduled exit(冻结 entry_idx+horizon)在 trade_dates 内则算等权篮子相对超额 =
    mean_member(compute_return stock_net − bench)→ matured;未到期→pending;0 成员可算→missing_exit_close。
    exit_date 恒为 scheduled horizon 锚(PIT);实际成员 exit 组成进 exit_policy。**幂等**;空篮子/无可用冻结 entry 不动。"""
    as_of = cohort["as_of"]
    recomputed_entry = _first_trade_day_after(as_of, trade_dates)
    for con in cohort["constructions"]:
        basket = con["selected_symbols"]
        frozen_entry = con.get("entry_date")
        if not basket:
            continue
        if con.get("entry_status") == "ok":
            if not frozen_entry:
                raise ValueError(f"{as_of}/{con['construction_id']}: entry_status=ok 但缺冻结 entry_date(PIT 锚缺失)")
            if frozen_entry not in trade_dates:
                raise ValueError(f"{as_of}/{con['construction_id']}: 冻结 entry_date {frozen_entry} 不在 trade_dates(日历漂移)")
            if recomputed_entry is not None and recomputed_entry != frozen_entry:
                raise ValueError(f"{as_of}/{con['construction_id']}: 冻结 entry_date {frozen_entry} ≠ 当前 first-open-after-as_of "
                                 f"{recomputed_entry}(历史日历被改,拒绝静默重锚)")
        if not frozen_entry or frozen_entry not in trade_dates:
            continue
        entry_idx = trade_dates.index(frozen_entry)
        for h in ALL_HORIZONS:
            rec = con["horizons"][str(h)]
            exit_idx = entry_idx + h
            if exit_idx >= len(trade_dates):
                rec.update({"status": "pending", "relative_excess_net": None,
                            "exit_date": None, "exit_policy": None})
                continue
            scheduled_exit = trade_dates[exit_idx]
            excesses, policy_counts = [], {}
            for sym in basket:
                prices = stock_price_cache.get(sym) or {}
                delist = delist_by_symbol.get(sym)
                _en, _sched, _act, policy = base.resolve_return_dates(prices, trade_dates, as_of, h, delist_date=delist)
                sret, bret, _e, _x = base.compute_return(prices, csi300_prices, trade_dates, as_of, h, delist_date=delist)
                if sret is not None and bret is not None:
                    excesses.append(sret - bret)
                    policy_counts[policy] = policy_counts.get(policy, 0) + 1
            if not excesses:
                rec.update({"status": "missing_exit_close", "relative_excess_net": None,
                            "exit_date": scheduled_exit, "exit_policy": "no_basket_member_resolved"})
                continue
            if set(policy_counts) == {"scheduled_exit"}:
                exit_policy = "scheduled_exit_basket_equal_weight"
            else:
                exit_policy = "mixed_member_exits:" + ",".join(f"{k}={v}" for k, v in sorted(policy_counts.items()))
            rec.update({"status": "matured", "relative_excess_net": round(mean(excesses), 10),
                        "exit_date": scheduled_exit, "exit_policy": exit_policy})


def _matured_504_excess(cohorts: list, construction_id: str) -> list:
    out = []
    for c in sorted(cohorts, key=lambda x: x["as_of"]):
        con = _construction_in(c, construction_id)
        rec = (con or {}).get("horizons", {}).get(str(PRIMARY_HORIZON)) if con else None
        if rec and rec.get("status") == "matured" and rec.get("relative_excess_net") is not None:
            out.append(float(rec["relative_excess_net"]))
    return out


def _interim_direction_positive(cohorts: list, construction_id: str) -> bool:
    """每个「有 matured cohort」的 interim horizon 的 mean excess 都 > 0(prereg「consistent direction」窄安全侧:
    promote-gate 取严——任何 interim 方向转负即不算 persistent)。无 matured interim 不构成否定。"""
    for h in INTERIM_HORIZONS:
        vals = []
        for c in cohorts:
            con = _construction_in(c, construction_id)
            rec = (con or {}).get("horizons", {}).get(str(h)) if con else None
            if rec and rec.get("status") == "matured" and rec.get("relative_excess_net") is not None:
                vals.append(float(rec["relative_excess_net"]))
        if vals and mean(vals) <= 0:
            return False
    return True


def _validate_new_capture_order(prior_accumulator, as_of: str) -> None:
    """Forward-paper cohorts are immutable live snapshots: never replace an existing as_of or backfill an older month."""
    if not prior_accumulator:
        return
    prior_asofs = sorted(str(c.get("as_of")) for c in prior_accumulator.get("cohorts", []) if c.get("as_of"))
    if not prior_asofs:
        return
    if as_of in prior_asofs:
        raise ValueError(f"forward capture as_of {as_of} already exists in prior accumulator; refusing to replace frozen cohort")
    latest = max(prior_asofs)
    if as_of < latest:
        raise ValueError(f"forward capture as_of {as_of} is older than latest prior cohort {latest}; refusing retroactive capture")


def assemble_construction_metrics(cohorts: list, *, stock_price_cache: dict, csi300_prices: dict,
                                  trade_dates: list) -> list:
    """每构造跨 504-matured cohorts 聚合(主判据 504d vs CSI300)+ rolling relative-NAV 回撤 + persistence。
    persistence(prereg evidence_and_decision_rule.persistence_check,**窄安全侧**):504 mean>0 ∧ 504 HAC-t>0 ∧
    每个有 matured cohort 的 interim mean>0。matured_cohort_count = 该构造 504-matured cohort 数。"""
    metrics = []
    for con in CONSTRUCTIONS:
        cid = con["construction_id"]
        excesses = _matured_504_excess(cohorts, cid)
        n = len(excesses)
        mean_excess = round(mean(excesses), 10) if excesses else None
        hac_t, hac_p = (None, None)
        if n >= 2:
            hac_t, hac_p, _lag = base.newey_west_hac_t_stat(excesses, horizon=PRIMARY_HORIZON)
        primary_selections = {}
        for c in cohorts:
            cc = _construction_in(c, cid)
            if cc and cc["selected_symbols"]:
                primary_selections[c["as_of"]] = cc["selected_symbols"]
        dd = None
        if primary_selections:
            dd = forward_rolling_relative_nav_drawdown(
                primary_selections=primary_selections, stock_price_cache=stock_price_cache,
                csi300_prices=csi300_prices, trade_dates=trade_dates,
                checkpoints=sorted(c["as_of"] for c in cohorts))["relative_nav_max_drawdown"]
        persistence = None
        if n:
            persistence = bool(mean_excess is not None and mean_excess > 0
                               and hac_t is not None and hac_t > 0
                               and _interim_direction_positive(cohorts, cid))
        metrics.append({
            "construction_id": cid, "promotion_role": con["promotion_role"],
            "matured_cohort_count": n, "mean_relative_excess": mean_excess,
            "hac_t": hac_t, "hac_p": hac_p,
            "rolling_relative_nav_max_drawdown": dd, "persistence_positive": persistence})
    return metrics


def build_forward_accumulator(*, prior_accumulator, as_of: str, captured_at: str, universe_size: int,
                              scored_items: list, stock_price_cache: dict, csi300_prices: dict,
                              trade_dates: list, delist_by_symbol: dict, generated_at: str) -> dict:
    """brain 入口:上月 accumulator(或 None bootstrap)+ 本月 as_of 的 scored_items(数据层产)+ 价格缓存 →
    neutralize → 追加本月 cohort snapshot(重复/倒序 as_of 拒绝,不替换冻结快照)→ 回填所有 cohort 已成熟 horizon → 重算
    construction_metrics + paper_read → 新 accumulator dict(未写盘;调用方用 write_accumulator 校验+原子写)。"""
    _validate_new_capture_order(prior_accumulator, as_of)
    neutralize_value_yield_scores(scored_items)
    new_cohort = build_cohort_snapshot(as_of, scored_items, captured_at=captured_at,
                                       universe_size=universe_size, trade_dates=trade_dates)
    prior = list((prior_accumulator or {}).get("cohorts", []))
    cohorts = sorted(prior + [new_cohort], key=lambda c: c["as_of"])
    for c in cohorts:
        backfill_cohort(c, stock_price_cache=stock_price_cache, csi300_prices=csi300_prices,
                        trade_dates=trade_dates, delist_by_symbol=delist_by_symbol)
    metrics = assemble_construction_metrics(cohorts, stock_price_cache=stock_price_cache,
                                            csi300_prices=csi300_prices, trade_dates=trade_dates)
    primary = next(m for m in metrics if m["construction_id"] == PRIMARY_CONSTRUCTION_ID)
    paper_read = compute_paper_read(
        {"persistence_positive": primary["persistence_positive"],
         "rolling_relative_nav_max_drawdown": primary["rolling_relative_nav_max_drawdown"]},
        primary["matured_cohort_count"])
    return build_accumulator(cohorts=cohorts, construction_metrics=metrics, paper_read=paper_read,
                             as_of_latest_capture=max(c["as_of"] for c in cohorts), generated_at=generated_at)


def _prior_basket_symbols(prior_accumulator) -> tuple:
    """上月 accumulator 所有 cohort 篮子成员并集(供本月 fetch 把它们的价格也拉到 → backfill 旧 cohort 收益)。"""
    if not prior_accumulator:
        return ()
    syms: set = set()
    for cohort in prior_accumulator.get("cohorts", []):
        for con in cohort.get("constructions", []):
            syms.update(con.get("selected_symbols", []))
    return tuple(sorted(syms))


def _validate_capture_args(as_of: str, out: str) -> None:
    """Finding 4 pre-fetch fail-closed:as_of 须 8 位 YYYYMMDD 且 ≥ START_FLOOR(20260630);out 须 research-only
    (路径含 `research/`、且任意 segment 不得是生产 `result/`),拒绝把 paper artifact 写进生产线。"""
    if not (isinstance(as_of, str) and len(as_of) == 8 and as_of.isdigit()):
        raise SystemExit(f"[FATAL] --as-of 须 8 位 YYYYMMDD,实为 {as_of!r}")
    if as_of < START_FLOOR:
        raise SystemExit(f"[FATAL] --as-of {as_of} < start_floor {START_FLOOR}(forward-paper 首笔 ≥ 20260630)")
    # round 3(Codex re-审查):先 os.path.normpath 解析 `..`、再按 segment **小写**比对(Windows case-insensitive FS),
    # 防 `research/../RESULT/x`(resolve 到生产 result 却仍含 research segment)绕过 + 防 traversal 逃出 research 子树。
    normalized = os.path.normpath(str(out)).replace("\\", "/")
    parts = [p for p in normalized.split("/") if p and p != "."]
    lower_parts = [p.lower() for p in parts]
    if ".." in parts:
        raise SystemExit(f"[FATAL] --out 含 `..` 路径穿越(normpath 后仍残留),拒绝,实为 {out!r}")
    if "research" not in lower_parts:
        raise SystemExit(f"[FATAL] --out 必须在 research/ 下(research-only paper artifact),实为 {out!r}")
    if "result" in lower_parts:
        raise SystemExit(f"[FATAL] --out 不得写生产 result/ 路径(production lane),实为 {out!r}")


def run_forward_capture(*, as_of: str, out: str, prior_accumulator, pro, generated_at: str, captured_at: str,
                        data_through: str | None = None) -> dict:
    """完整 forward capture(段5 接线,`pro` 注入 → mock 可测):**arg 守门(Finding 4)** → prior 篮子(供价格 backfill)
    → `dl.fetch_forward_panel`(gated,explicit window 到 data_through;**月末 + entry-anchor 守门已前移进 fetch pre-broad**,
    见 `dl.validate_as_of_month_end` / `dl.validate_entry_anchor`)→ `dl.assemble_forward_inputs`
    → `build_forward_accumulator`(brain)→ `write_accumulator`。返回 accumulator。data_through 默认由数据层取 as_of 后短窗口,
    只保证冻结 next-open entry anchor;更长 backfill 窗口必须显式传入。"""
    _validate_capture_args(as_of, out)
    if prior_accumulator is not None:
        validate_accumulator_dict(prior_accumulator)
    extra = _prior_basket_symbols(prior_accumulator)
    panel = dl.fetch_forward_panel(as_of=as_of, pro=pro, extra_price_symbols=extra, data_through=data_through)
    inputs = dl.assemble_forward_inputs(**panel)
    acc = build_forward_accumulator(
        prior_accumulator=prior_accumulator, as_of=as_of, captured_at=captured_at,
        universe_size=inputs["universe_size"], scored_items=inputs["scored_items"],
        stock_price_cache=inputs["stock_price_cache"], csi300_prices=inputs["csi300_prices"],
        trade_dates=inputs["trade_dates"], delist_by_symbol=inputs["delist_by_symbol"], generated_at=generated_at)
    write_accumulator(acc, out)
    return acc


def main(argv=None):
    p = argparse.ArgumentParser(description="A-long value-yield forward-PAPER capture (research-only, paper, gated)")
    p.add_argument("--as-of", required=True, help="month-end YYYYMMDD (last open A-share trading day of the month; ≥ 20260630)")
    p.add_argument("--out", required=True, help="accumulator artifact path (research/results/...)")
    p.add_argument("--prior", default=None, help="上月 accumulator json 路径(增量;首月 bootstrap 留空)")
    p.add_argument("--data-through", default=None,
                   help="价格/日历拉取截止日 YYYYMMDD(backfill 旧 cohort 收益;默认=as_of 后短窗口以冻结 entry anchor)")
    p.add_argument("--confirm-fetch-authorized", action="store_true",
                   help="per-run authorization for the live month-end PIT pull (no standing grant)")
    p.add_argument("--confirm-research-paper", action="store_true",
                   help="confirm research-only / paper / non-production / no-real-money run")
    args = p.parse_args(argv)
    if not (args.confirm_research_paper and args.confirm_fetch_authorized):
        raise SystemExit("[FATAL] 需 --confirm-research-paper + --confirm-fetch-authorized:本 runner 仅 research/paper、"
                         "且每次前向抓数需单独授权(prereg: ongoing pulls require separate authorization)。")
    _validate_capture_args(args.as_of, args.out)   # O2:as_of/research-only-out fail-closed 在建 tushare 客户端 + 抓数之前
    prior = None
    if args.prior:
        with open(args.prior, "r", encoding="utf-8") as f:
            prior = json.load(f)
    if not os.environ.get("TUSHARE_TOKEN"):       # O2:缺 token 友好报错(非裸 KeyError)
        raise SystemExit("[FATAL] 缺 TUSHARE_TOKEN 环境变量(forward 月末抓数需 pinned tushare token)")
    # gated 才 import 共享 pinned init + 时间戳(provenance);mock 测走 run_forward_capture 不经此处。
    # **第一笔真捕获(as_of≥20260630)是 live provider 形状的现写现验点**(可能要按真返回字段微调 dl.fetch_forward_panel)。
    from datetime import datetime, timezone
    from runners.a_short_iv_feed_probe import init_tushare_pro
    pro = init_tushare_pro(os.environ["TUSHARE_TOKEN"])
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    acc = run_forward_capture(as_of=args.as_of, out=args.out, prior_accumulator=prior, pro=pro,
                              generated_at=stamp, captured_at=stamp, data_through=args.data_through)
    print(f"[OK] wrote {args.out}: cohorts={len(acc['cohorts'])} routing={acc['paper_read']['routing']} "
          f"matured={acc['paper_read']['matured_cohort_count']}")


if __name__ == "__main__":
    main()
