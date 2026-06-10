#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short 赛道热度 overlay — comparison-track runner (Slice A).

实现冻结设计 `docs/a_short_theme_overlay_slice_a_design_20260610.md`(commit `4ba5617`)。

定位:**非 production、comparison-track**。本 runner **只读消费** EGS 已产出的 artifacts +
缓存 + L3 快照,对**现有候选池重排序**,产出一份与 baseline 并行的 overlay artifact。
它 **不修改 `egs_main.py`、不改 production `final_score`/`tier`/准入、不新抓数据**;
缺数据的输入按设计 forward-only(记 `pit_source` / unavailable,绝不编造)。

纯计算函数对 plain dict/DataFrame 操作(可用合成 fixture 单测);I/O 在 `main` 薄层。
冻结阈值镜像在 `presets/a_short_theme_overlay_governance_20260610.json`(parity 测试守)。

NOTE: 本 runner 是 comparison-track。它不产生买卖建议、不动真钱、不过 ship-gate;
overlay 升 production 排序需 ≥12 forward observations 稳定胜出(见设计 §6)。
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

SCHEMA_NAME = "a_short_theme_overlay_comparison"
SCHEMA_VERSION = "1.0.0"

# ── 冻结设计常量(与 governance artifact 逐字 parity)──────────────────────────
OVERLAY_WEIGHTS = {"esp": 0.15, "l4": 0.45, "theme": 0.25, "industry": 0.15}
THEME_WINDOW_BLEND = {"d5": 0.5, "d20": 0.5}          # theme_heat 5d/20d 融合
PASS_PERCENTILE = 70.0                                 # theme/industry pass 阈值(0-100)
BREADTH_UP_FRAC_MIN = 0.50                             # breadth 门槛:上涨成分占比
BREADTH_VOL_FRAC_MIN = 0.40                            # breadth 门槛:放量成分占比
PERSISTENCE_TOP_QUANTILE = 0.30                        # 概念强度高分位定义(top 30%)
PERSISTENCE_WINDOW_DAYS = 5                            # 连续性观察窗口
FIT_FLOOR = 0.40                                       # fit_pass 下限
ELIGIBILITY_MIN_PASS = 2                               # theme/industry/breadth 至少 N 项过

# 赛道红利门(唯一):eligible(≥2 项过 ∧ fit_pass)且无 crowding。
# crowding 命中 = 一次硬处理 → 剥夺赛道红利(热度不得救回),overlay 退回 esp+l4 base。
# 进 summary 的冻结阈值(与 governance artifact 逐字 parity;每个 key 在 schema const-pin)
EMITTED_THRESHOLDS = {
    "theme_window_blend": THEME_WINDOW_BLEND,
    "pass_percentile": PASS_PERCENTILE,
    "breadth_up_frac_min": BREADTH_UP_FRAC_MIN,
    "breadth_vol_frac_min": BREADTH_VOL_FRAC_MIN,
    "persistence_top_quantile": PERSISTENCE_TOP_QUANTILE,
    "persistence_window_days": PERSISTENCE_WINDOW_DAYS,
    "fit_floor": FIT_FLOOR,
    "eligibility_min_pass": ELIGIBILITY_MIN_PASS,
}


# ── 工具 ──────────────────────────────────────────────────────────────────────
def _pct_rank_0_100(values: pd.Series) -> pd.Series:
    """横截面百分位 → 0-100。NaN 保持 NaN。"""
    return values.rank(pct=True) * 100.0


def _safe_float(x):
    try:
        f = float(x)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ── 组件计算(纯函数)─────────────────────────────────────────────────────────
def concept_intensity(daily_window: pd.DataFrame, members: list[str]) -> float | None:
    """单概念在给定窗口的成交额加权涨跌强度。daily_window 含 ts_code/pct_chg/amount。"""
    sub = daily_window[daily_window["ts_code"].isin(members)]
    sub = sub.dropna(subset=["pct_chg", "amount"])
    if sub.empty:
        return None
    total_amt = float(sub["amount"].sum())
    if total_amt <= 0:
        return None
    return float((sub["pct_chg"] * sub["amount"]).sum() / total_amt)


def compute_theme_heat(stock_concepts: dict, concept_members: dict,
                       daily_5d: pd.DataFrame, daily_20d: pd.DataFrame) -> dict:
    """每股 theme_heat_score(0-100)。各窗口先算全市场概念强度→百分位,
    每股取其所属概念里 blended 百分位最高者。返回 {ts_code: score|None}。"""
    int5 = {cid: concept_intensity(daily_5d, m) for cid, m in concept_members.items()}
    int20 = {cid: concept_intensity(daily_20d, m) for cid, m in concept_members.items()}
    s5 = pd.Series({c: v for c, v in int5.items() if v is not None}, dtype=float)
    s20 = pd.Series({c: v for c, v in int20.items() if v is not None}, dtype=float)
    r5 = (s5.rank(pct=True) * 100.0) if not s5.empty else pd.Series(dtype=float)
    r20 = (s20.rank(pct=True) * 100.0) if not s20.empty else pd.Series(dtype=float)
    out, best_concept = {}, {}
    for code, cids in stock_concepts.items():
        blended = []
        for c in cids:
            p5, p20 = r5.get(c), r20.get(c)
            if p5 is None and p20 is None:
                continue
            p5 = p5 if p5 is not None else p20
            p20 = p20 if p20 is not None else p5
            blended.append((THEME_WINDOW_BLEND["d5"] * p5 + THEME_WINDOW_BLEND["d20"] * p20, c))
        if not blended:
            out[code], best_concept[code] = None, None
            continue
        val, c = max(blended, key=lambda t: t[0])
        out[code], best_concept[code] = float(val), c
    return {"score": out, "best_concept": best_concept}


def industry_window_strength(daily_window: pd.DataFrame, sw_map: dict,
                             bench_ret: float) -> pd.Series:
    """每 SW L2 的成交额加权窗口收益减基准。返回 {l2_name: rel_ret}。"""
    rows = []
    for code, info in sw_map.items():
        rows.append({"ts_code": code, "l2_name": info.get("l2_name", "未知")})
    map_df = pd.DataFrame(rows)
    dw = daily_window.merge(map_df, on="ts_code", how="inner").dropna(subset=["pct_chg", "amount"])
    dw = dw[dw["l2_name"] != "未知"]
    if dw.empty:
        return pd.Series(dtype=float)
    g = dw.groupby("l2_name").apply(
        lambda s: (s["pct_chg"] * s["amount"]).sum() / max(float(s["amount"].sum()), 1e-9)
    )
    return g - (bench_ret if bench_ret is not None else 0.0)


def compute_industry_heat(sw_map: dict, daily_20d: pd.DataFrame, daily_60d: pd.DataFrame,
                          bench20: float, bench60: float) -> dict:
    """每 SW L2 的 industry_heat_score(0-100,跨行业百分位,20d/60d 等权)。"""
    s20 = industry_window_strength(daily_20d, sw_map, bench20)
    s60 = industry_window_strength(daily_60d, sw_map, bench60)
    r20 = (s20.rank(pct=True) * 100.0) if not s20.empty else pd.Series(dtype=float)
    r60 = (s60.rank(pct=True) * 100.0) if not s60.empty else pd.Series(dtype=float)
    industries = set(r20.index) | set(r60.index)
    out = {}
    for ind in industries:
        a, b = r20.get(ind), r60.get(ind)
        if a is None and b is None:
            continue
        a = a if a is not None else b
        b = b if b is not None else a
        out[ind] = float(0.5 * a + 0.5 * b)
    return out


def orthogonalize_industry_on_theme(df: pd.DataFrame) -> pd.Series:
    """R-ASLICEA-INDUSTRY-ORTHO-SCALE: 横截面把 industry_heat 对 theme_heat 回归取残差,
    再百分位归一化回 0-100 → industry_heat_norm⊥。仅对两者皆非空的行参与回归。"""
    sub = df.dropna(subset=["theme_heat_score", "industry_heat_score"])
    norm = pd.Series(np.nan, index=df.index, dtype=float)
    if len(sub) < 3 or sub["theme_heat_score"].std(ddof=0) < 1e-9:
        # 退化:无法回归 → 直接用 industry_heat 的百分位(theme 无信息可剔除)
        norm.loc[df["industry_heat_score"].notna()] = _pct_rank_0_100(
            df.loc[df["industry_heat_score"].notna(), "industry_heat_score"])
        return norm
    x = sub["theme_heat_score"].to_numpy(float)
    y = sub["industry_heat_score"].to_numpy(float)
    slope, intercept = np.polyfit(x, y, 1)
    resid = pd.Series(y - (slope * x + intercept), index=sub.index)
    norm.loc[sub.index] = resid.rank(pct=True) * 100.0
    return norm


def compute_breadth(best_concept: dict, concept_members: dict, daily_5d: pd.DataFrame,
                    amount_5d: dict, amount_20d: dict) -> dict:
    """每股 top 概念的 breadth(上涨占比/放量占比),返回 {ts_code: {up_frac, vol_frac, pass}}。"""
    out = {}
    for code, cid in best_concept.items():
        if cid is None or cid not in concept_members:
            out[code] = {"up_frac": None, "vol_frac": None, "pass": False}
            continue
        members = concept_members[cid]
        sub = daily_5d[daily_5d["ts_code"].isin(members)]
        ret_by = sub.groupby("ts_code")["pct_chg"].sum()
        n = int(ret_by.notna().sum())
        up_frac = float((ret_by > 0).sum() / n) if n else None
        vols = [(amount_5d.get(m), amount_20d.get(m)) for m in members]
        vols = [(a, b) for a, b in vols if a is not None and b is not None and b > 0]
        vol_frac = float(sum(1 for a, b in vols if a > b) / len(vols)) if vols else None
        passed = (up_frac is not None and up_frac >= BREADTH_UP_FRAC_MIN
                  and vol_frac is not None and vol_frac >= BREADTH_VOL_FRAC_MIN)
        out[code] = {"up_frac": up_frac, "vol_frac": vol_frac, "pass": bool(passed)}
    return out


def compute_persistence(best_concept: dict, concept_daily_intensity: dict) -> dict:
    """persistence 乘子(0-1):top 概念近 N 日处于高分位的天数 / 窗口。
    concept_daily_intensity: {date: {cid: intensity}},date 升序。"""
    dates = sorted(concept_daily_intensity.keys())[-PERSISTENCE_WINDOW_DAYS:]
    high_sets = {}
    for d in dates:
        s = pd.Series(concept_daily_intensity[d], dtype=float).dropna()
        if s.empty:
            high_sets[d] = set()
            continue
        thr = s.quantile(1.0 - PERSISTENCE_TOP_QUANTILE)
        high_sets[d] = set(s[s >= thr].index)
    out = {}
    for code, cid in best_concept.items():
        if cid is None or not dates:
            out[code] = 0.0
            continue
        days = sum(1 for d in dates if cid in high_sets.get(d, set()))
        out[code] = float(days / len(dates))
    return out


def compute_fit(best_concept: dict, concept_members: dict, amount_latest: dict,
                stock_concepts: dict) -> dict:
    """candidate_theme_fit ∈ [0,1] 或 None(unknown)。代理:① top 概念内成交额权重;
    ③ 多概念交叉确认(归一)。(② 相关性留 runner 子能力,缺则不计入,不编造。)"""
    out = {}
    for code, cid in best_concept.items():
        proxies = []
        if cid is not None and cid in concept_members:
            members = concept_members[cid]
            amts = [amount_latest.get(m) for m in members]
            amts = [a for a in amts if a is not None]
            self_amt = amount_latest.get(code)
            if self_amt is not None and amts and sum(amts) > 0:
                w = self_amt / sum(amts)
                proxies.append(min(1.0, w * len(amts)))   # 相对均权的权重(>1 截断)
        ncross = len([c for c in stock_concepts.get(code, []) if c in concept_members])
        if ncross > 0:
            proxies.append(min(1.0, ncross / 3.0))
        out[code] = float(np.mean(proxies)) if proxies else None  # None = unknown
    return out


def crowding_hit(row) -> bool:
    return bool(row.get("overheat_flag") or row.get("chasing_high") or row.get("chase_flag")
                or row.get("high_pos_shrink"))


# ── 组装 ──────────────────────────────────────────────────────────────────────
def assemble_overlay(pool_df: pd.DataFrame, theme_heat: dict, industry_heat_by_l2: dict,
                     breadth: dict, persistence: dict, fit: dict, sw_l2_by_code: dict) -> pd.DataFrame:
    """把组件拼到候选池,算 industry_norm⊥、fit_pass、资格、theme_eff、overlay_score、rank。"""
    df = pool_df.copy()
    df["theme_heat_score"] = df["ts_code"].map(theme_heat["score"])
    df["industry_heat_score"] = df["ts_code"].map(
        lambda c: industry_heat_by_l2.get(sw_l2_by_code.get(c)))
    df["industry_heat_norm_ortho"] = orthogonalize_industry_on_theme(df)
    df["breadth_up_frac"] = df["ts_code"].map(lambda c: breadth.get(c, {}).get("up_frac"))
    df["breadth_pass"] = df["ts_code"].map(lambda c: bool(breadth.get(c, {}).get("pass")))
    df["persistence_mult"] = df["ts_code"].map(lambda c: persistence.get(c, 0.0))
    df["fit_score"] = df["ts_code"].map(lambda c: fit.get(c))
    df["fit_unknown"] = df["fit_score"].isna()
    df["fit_pass"] = (~df["fit_unknown"]) & (df["fit_score"].fillna(-1.0) >= FIT_FLOOR)

    df["theme_pass"] = df["theme_heat_score"].fillna(-1.0) >= PASS_PERCENTILE
    df["industry_pass"] = df["industry_heat_score"].fillna(-1.0) >= PASS_PERCENTILE
    n_pass = df[["theme_pass", "industry_pass", "breadth_pass"]].sum(axis=1)
    df["eligible"] = (n_pass >= ELIGIBILITY_MIN_PASS) & df["fit_pass"]

    df["crowding_hit"] = df.apply(crowding_hit, axis=1)
    # 赛道红利唯一门:eligible(≥2 项过 ∧ fit_pass)且无 crowding。
    # R-ASLICEA-RUNNER-ELIGIBILITY-BONUS-GATE + R-ASLICEA-RUNNER-CROWDING-HARD-GATE:
    # 不满足 → theme 与 industry 项均置 0,overlay 退回 esp+l4 base(crowding 命中时热度不得救回)。
    df["bonus_gate"] = df["eligible"] & (~df["crowding_hit"])
    fit_mult = df["fit_pass"].astype(float)
    df["theme_eff"] = df["theme_heat_score"].fillna(0.0) * df["persistence_mult"] * fit_mult
    theme_term = df["theme_eff"].where(df["bonus_gate"], 0.0)
    industry_term = df["industry_heat_norm_ortho"].fillna(0.0).where(df["bonus_gate"], 0.0)

    df["overlay_base"] = (OVERLAY_WEIGHTS["esp"] * df["esp_score"].fillna(0.0)
                          + OVERLAY_WEIGHTS["l4"] * df["l4_score"].fillna(0.0))
    df["overlay_score"] = (df["overlay_base"]
                           + OVERLAY_WEIGHTS["theme"] * theme_term
                           + OVERLAY_WEIGHTS["industry"] * industry_term)
    df = df.sort_values("overlay_score", ascending=False).reset_index(drop=True)
    df["overlay_rank"] = np.arange(1, len(df) + 1)
    return df


def build_summary(overlay_df: pd.DataFrame, as_of: str, pit_source: dict,
                  dropped_at_l0_l5: list, generated_at: str) -> dict:
    candidates = []
    for _, r in overlay_df.iterrows():
        candidates.append({
            "ts_code": str(r["ts_code"]),
            "baseline_rank": _safe_int(r.get("baseline_rank")),
            "overlay_rank": _safe_int(r.get("overlay_rank")),
            "overlay_score": _safe_float(r.get("overlay_score")),
            "esp_score": _safe_float(r.get("esp_score")),
            "l4_score": _safe_float(r.get("l4_score")),
            "theme_heat_score": _safe_float(r.get("theme_heat_score")),
            "industry_heat_score": _safe_float(r.get("industry_heat_score")),
            "industry_heat_norm_ortho": _safe_float(r.get("industry_heat_norm_ortho")),
            "breadth_pass": bool(r.get("breadth_pass")),
            "persistence_mult": _safe_float(r.get("persistence_mult")),
            "fit_score": _safe_float(r.get("fit_score")),
            "fit_unknown": bool(r.get("fit_unknown")),
            "fit_pass": bool(r.get("fit_pass")),
            "theme_pass": bool(r.get("theme_pass")),
            "industry_pass": bool(r.get("industry_pass")),
            "theme_eff": _safe_float(r.get("theme_eff")),
            "eligible": bool(r.get("eligible")),
            "crowding_hit": bool(r.get("crowding_hit")),
        })
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "as_of": as_of,
        "preset": "a_short",
        "track": "comparison_non_production",
        "weights": OVERLAY_WEIGHTS,
        "thresholds": EMITTED_THRESHOLDS,
        "pit_source": pit_source,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "dropped_at_l0_l5": dropped_at_l0_l5,
        "boundary": {
            "production": False,
            "changes_final_score_or_tier": False,
            "is_buy_advice": False,
            "satisfies_ship_gate": False,
        },
    }


def _safe_int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# ── 不变量校验(消费完整性 / 热度不覆盖硬风控 / fit 门控 / 同尺度)──────────────
def validate_overlay_summary_consistency(summary: dict) -> None:
    cands = summary["candidates"]
    # R-ASLICEA-SCHEMA-OUTPUT-INVARIANTS: producer-side count + rank integrity
    if summary.get("candidate_count") != len(cands):
        raise ValueError("candidate_count 与 candidates 长度不一致")
    ranks = [c["overlay_rank"] for c in cands]
    if sorted(r for r in ranks if r is not None) != list(range(1, len(cands) + 1)):
        raise ValueError("overlay_rank 非 1..N 连续唯一")
    for c in cands:
        npass = sum([c["theme_pass"], c["industry_pass"], c["breadth_pass"]])
        # 资格:eligible == (fit_pass ∧ ≥2 项过)
        if bool(c["eligible"]) != (bool(c["fit_pass"]) and npass >= ELIGIBILITY_MIN_PASS):
            raise ValueError(f"{c['ts_code']}: eligible 与 fit_pass/≥2pass 不一致")
        if c["fit_unknown"] and c["fit_pass"]:
            raise ValueError(f"{c['ts_code']}: fit_unknown 与 fit_pass 同真")
        # 赛道红利门 = eligible 且无 crowding;否则 overlay = esp+l4 base(热度不得救回)
        bonus_gate = bool(c["eligible"]) and not bool(c["crowding_hit"])
        if not bonus_gate and c["overlay_score"] is not None:
            base = (OVERLAY_WEIGHTS["esp"] * (c["esp_score"] or 0.0)
                    + OVERLAY_WEIGHTS["l4"] * (c["l4_score"] or 0.0))
            if abs(c["overlay_score"] - base) > 1e-6:
                raise ValueError(f"{c['ts_code']}: 不满足红利门(ineligible/crowding)却含赛道红利")
        # 同尺度:industry_heat_norm_ortho ∈ 0-100 或 None(禁止零中心残差)
        v = c["industry_heat_norm_ortho"]
        if v is not None and not (0.0 <= v <= 100.0):
            raise ValueError(f"{c['ts_code']}: industry_heat_norm_ortho={v} 不在 0-100(未归一化)")


# ── main(薄 I/O,只读消费 EGS 产出/缓存/快照;不新抓、不改 production)────────────
def main(argv=None):
    p = argparse.ArgumentParser(description="A-short 赛道热度 overlay comparison-track runner (Slice A)")
    p.add_argument("--as-of", required=True, help="YYYYMMDD")
    p.add_argument("--analysis-input", required=True, help="EGS analysis_input.json (候选池 + 每股 EGS 分)")
    p.add_argument("--out", required=True, help="overlay artifact 输出路径")
    p.add_argument("--confirm-non-production", action="store_true",
                   help="确认这是 comparison-track 非 production 运行")
    args = p.parse_args(argv)
    if not args.confirm_non_production:
        raise SystemExit("[FATAL] 需 --confirm-non-production:本 runner 仅产出 comparison-track artifact")
    # NOTE: 数据装载(L3 snapshot / daily_all cache / SW map / index series)在此薄层接 EGS;
    # 真实数据装载 + 任何缺失 fetch 需用户 `执行` 授权,故装载实现留给执行期接线。
    # 本提交聚焦可测纯计算契约;装载层在 `执行` 时按 EGS 缓存路径补全并校验。
    raise SystemExit("[INFO] data-loading wiring is execution-time (authorized) work; "
                     "pure-function contract is unit-tested. See design doc + tests.")


if __name__ == "__main__":
    main()
