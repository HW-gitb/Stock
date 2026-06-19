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
落 analysis/accumulator 核心 + 前向 rolling-NAV(parity);**live-fetch 数据层 + cohort-from-data 编排是下一刀**
(标 `_DEFERRED`,需另读 bf.batch_factor_values / base.compute_return / base.add_industry_neutral_scores 主体并接 gated 抓数)。

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
    # construction_metrics:恰好覆盖 3 构造各一次(无重/缺)+ role↔id + primary matured == paper_read.matured
    _check_construction_id_coverage(acc["construction_metrics"], "construction_metrics")
    for m in acc["construction_metrics"]:
        _check_role_id(m)
        if m["construction_id"] == PRIMARY_CONSTRUCTION_ID and m["matured_cohort_count"] != n:
            raise ValueError(f"primary 构造 matured_cohort_count({m['matured_cohort_count']})≠ paper_read({n})")
    # matured_cohort_count 必须 == 实际 primary(composite)504-horizon 已 matured 的 cohort 数(防虚报成熟数越过 12 门 promote)
    actual_matured = sum(
        1 for c in acc["cohorts"] for con in c["constructions"]
        if con["construction_id"] == PRIMARY_CONSTRUCTION_ID
        and (con["horizons"].get(str(PRIMARY_HORIZON)) or {}).get("status") == "matured")
    if n != actual_matured:
        raise ValueError(f"paper_read.matured_cohort_count({n})≠ 实际 primary {PRIMARY_HORIZON}-horizon matured cohort 数({actual_matured})")
    # source_refs 必含 prereg/ledger/batch/schema 四类**精确路径**(exact match,非子串:防 evil/...含子串却脱离血缘的伪路径)
    present = {r["path"] for r in acc["source_refs"]}
    for need in REQUIRED_SOURCE_REF_PATHS:
        if need not in present:
            raise ValueError(f"source_refs 缺必备精确引用(exact path,非子串匹配):{need}")


def write_accumulator(acc: dict, out_path: str) -> None:
    """唯一 sanctioned 写盘:schema(shape/enum/if-then)+ 跨字段一致性 双校验后原子写。"""
    import jsonschema
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        jsonschema.validate(acc, json.load(f))
    validate_accumulator_consistency(acc)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(acc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def main(argv=None):
    p = argparse.ArgumentParser(description="A-long value-yield forward-PAPER capture (research-only, paper, gated)")
    p.add_argument("--as-of", required=True, help="month-end YYYYMMDD (last open A-share trading day of the month; ≥ 20260630)")
    p.add_argument("--out", required=True, help="accumulator artifact path (research/results/...)")
    p.add_argument("--confirm-fetch-authorized", action="store_true",
                   help="per-run authorization for the live month-end PIT pull (no standing grant)")
    p.add_argument("--confirm-research-paper", action="store_true",
                   help="confirm research-only / paper / non-production / no-real-money run")
    args = p.parse_args(argv)
    if not (args.confirm_research_paper and args.confirm_fetch_authorized):
        raise SystemExit("[FATAL] 需 --confirm-research-paper + --confirm-fetch-authorized:本 runner 仅 research/paper、"
                         "且每次前向抓数需单独授权(prereg: ongoing pulls require separate authorization)。")
    # _DEFERRED(下一刀):live month-end PIT 抓数(gated)→ 装配 bf.batch_factor_values 所需 panel → 中性化
    # (base.add_industry_neutral_scores + bf.add_size_neutral_scores + bf.add_marginal_industry_size_neutral_scores)
    # + value_yield_composite_score → 单 as_of cohort(bf.cohort_excess_by_as_of)→ snapshot 追加 + backfill-as-mature
    # (base.compute_return per 成熟 horizon)→ construction_metrics(base.newey_west_hac_t_stat +
    # forward_rolling_relative_nav_drawdown)→ compute_paper_read → build_accumulator → write_accumulator。
    raise SystemExit("[INFO] live-fetch data layer + cohort-from-data orchestration are the deferred next slice "
                     "(see module docstring _DEFERRED). This slice lands the parity-pinned forward rolling-NAV + "
                     "paper-read + accumulator assembly/schema. First real capture as_of ≥ 20260630, per-pull authorized.")


if __name__ == "__main__":
    main()
