#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-EGS 生产打分:SW L2 行业热度(industry_heat)+ 可治理权重 profile —— 纯模块,单一真相源.

用户决策(2026-06-11,Codex 优化):把行业/赛道权重提进**生产选股打分**(sector beta:热门赛道
带动全行业)。本模块是 `A-EGS/egs_main.py` 打分段(原 egs_base + final_score + tier)的纯函数抽取,
egs_main 与每周非生产对比 diff(egs_main 运行期调本模块的 `write_weight_comparison`)**共用本模块**,杜绝重实现漂移(无独立 runner)。

**激活契约:生产 `active_profile=balanced`(esp .20 / cat .25 / l4 .40 / industry_heat .15)= 已生效
(LIVE)** —— 提高行业/赛道权重、改变选股(用户目的)。`legacy`(esp .20 / cat .30 / l4 .50 /
industry_heat 0 = 改前原式)**仅作一键回滚锚 + 回归基准**(把 `active_profile` 翻回 `legacy` 即还原,
不改代码)。industry_heat_score 永远算出并作为新字段输出。

行业热度只**加分排序**,绝不救回 hard_veto/停牌/涨停锁/ST/减持/闪崩;`chasing_high·overheat→Tier2`
等准入降级原样保留(都在 final_score_and_tier 里忠实复制)。industry_heat 是**生产钉死**定义(每 SW L2
成员动量中位数 → 跨行业百分位 0-100,20d/60d 等权),**借鉴** Slice A overlay 的"跨行业百分位"概念、
**非字面复用**(overlay 用独立 benchmark 窗口强度序列,打分 df 没有);v1 无 SW L1 / CSI-relative fallback。纯 pandas/numpy,无 I/O 副作用、
不 import egs_main/tushare(故可单测;egs_main import 期有 set_token 副作用,不可被测试 import)。
"""
from __future__ import annotations

import json
import hashlib
import os

import numpy as np
import pandas as pd

GOV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "presets", "egs_industry_heat_governance_20260611.json")
WEIGHT_KEYS = ("esp", "cat", "l4", "industry_heat")
UNKNOWN_INDUSTRY = "未知"


# ── industry_heat(SW L2 行业热度,生产钉死定义;借鉴 overlay 百分位概念,非字面复用)──────
def compute_industry_heat_score(df: pd.DataFrame) -> pd.Series:
    """每只票的 industry_heat_score(0-100)= 其 SW L2 行业的跨行业热度百分位。
    行业强度 = 成员 pct_20d_n 中位数(若有 pct_60d(_n)再等权混入),跨 L2 百分位×100。
    未知行业 / 缺 l2_name / 缺动量 → NaN(下游加权时按 0 处理,且未知行业本就降 Tier2)。"""
    n = len(df)
    if n == 0 or "l2_name" not in df.columns:
        return pd.Series([np.nan] * n, index=df.index, dtype=float)
    p20 = pd.to_numeric(df.get("pct_20d_n", pd.Series(np.nan, index=df.index)), errors="coerce")
    p60_src = df.get("pct_60d_n", df.get("pct_60d"))
    p60 = pd.to_numeric(p60_src, errors="coerce") if p60_src is not None else pd.Series(np.nan, index=df.index)
    l2 = df["l2_name"]
    valid = l2.notna() & (l2 != UNKNOWN_INDUSTRY)
    work = pd.DataFrame({"_l2": l2, "_p20": p20, "_p60": p60})[valid]
    if work.empty:
        return pd.Series([np.nan] * n, index=df.index, dtype=float)
    med20 = work.groupby("_l2")["_p20"].median()
    r20 = med20.rank(pct=True) * 100.0 if med20.notna().any() else med20 * np.nan
    med60 = work.groupby("_l2")["_p60"].median()
    if med60.notna().any():
        r60 = med60.rank(pct=True) * 100.0
        by_l2 = pd.concat([r20, r60], axis=1).mean(axis=1, skipna=True)  # 等权;一端缺用另一端
    else:
        by_l2 = r20
    mapped = l2.map(by_l2)
    return pd.to_numeric(mapped, errors="coerce").astype(float)


# ── 权重 profile(治理 artifact;active_profile 决定生产口径,v1=balanced 生效;legacy 仅回滚锚)──
def load_governance(path: str = GOV_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_active_weights(path: str = GOV_PATH) -> tuple[str, dict]:
    gov = load_governance(path)
    name = gov["active_profile"]
    return name, dict(gov["profiles"][name])


def egs_base(df: pd.DataFrame, weights: dict) -> pd.Series:
    """egs_base = Σ score×weight。industry_heat 缺失按 0 计(不污染、与未知行业降级一致)。
    legacy(industry_heat 权重 0)时与原式 esp*.20+cat*.30+l4*.50 逐值一致。"""
    ind = df.get("industry_heat_score")
    ind = pd.to_numeric(ind, errors="coerce").fillna(0.0) if ind is not None else 0.0
    return (df["esp_score"] * weights["esp"]
            + df["cat_score"] * weights["cat"]
            + df["l4_score"] * weights["l4"]
            + ind * weights["industry_heat"])


# ── final_score + tier(忠实复制 egs_main 原 2743-2784;两处共用,杜绝漂移)─────────
def final_score_and_tier(df: pd.DataFrame, weights: dict) -> tuple[pd.DataFrame, dict]:
    """复制 egs_main 打分尾段:egs_base→mult→deduct→val_bonus→final_score→tier 分位→准入降级。
    行业热度只进 egs_base 排序;veto/降级逻辑不被它改变。返回 (df, info) ,info 供日志。"""
    df = df.copy()
    df["egs_base"] = egs_base(df, weights)

    df["mult"] = 1.0
    df.loc[df["l2_flags"].astype(str).str.contains("ESP-Q", na=False), "mult"] *= 0.7
    df.loc[df["cat_flag"].astype(str).str.contains("CAT-0", na=False), "mult"] *= 0.5

    df["deduct"] = 0.0
    if "l1_flag" in df.columns:
        df.loc[df["l1_flag"] == "ITF-2", "deduct"] += 15
    if "itf_adj" in df.columns:
        df.loc[df["itf_adj"] == True, "deduct"] += 10  # noqa: E712 (parity w/ egs_main)
    df["deduct"] += df.get("reduce_penalty", pd.Series(0, index=df.index)).fillna(0)
    df["deduct"] += df.get("val_penalty", pd.Series(0, index=df.index)).fillna(0)
    df["val_bonus"] = df.get("val_bonus", pd.Series(0, index=df.index)).fillna(0)

    df["final_score"] = (
        (df["egs_base"] * df["mult"]).clip(lower=df["egs_base"] * 0.3)
        + df["val_bonus"] - df["deduct"]
    ).clip(lower=0).round(2)

    p75 = df["final_score"].quantile(0.75)
    p55 = df["final_score"].quantile(0.55)
    df["tier"] = "Other"
    df.loc[df["final_score"] >= p55, "tier"] = "Tier2"
    df.loc[df["final_score"] >= p75, "tier"] = "Tier1"
    df.loc[df["final_score"] < 50, "tier"] = "Other"

    info = {"p75": float(p75), "p55": float(p55)}
    fin_coverage = (df["q0_dt_yoy"].notna().sum() / max(len(df), 1)) if "q0_dt_yoy" in df.columns else 0.0
    info["fin_coverage"] = float(fin_coverage)
    if fin_coverage >= 0.70:
        esp_neg = df["esp_raw"].fillna(0) <= 0
        demote = (df["tier"] == "Tier1") & esp_neg
        df.loc[demote, "tier"] = "Tier2"
        info["esp_neg_demoted"] = int(demote.sum())
    else:
        info["esp_neg_demoted"] = 0

    # 准入降级:行业热度绝不救回这些(都在 egs_base 之后施加)
    ch = df.get("chasing_high", pd.Series(False, index=df.index)).fillna(False)
    df.loc[ch & (df["tier"] == "Tier1"), "tier"] = "Tier2"
    oh = df.get("overheat_flag", pd.Series(False, index=df.index)).fillna(False)
    df.loc[oh & (df["tier"] == "Tier1"), "tier"] = "Tier2"
    if "l4_flag" in df.columns:
        df.loc[df["l4_flag"].astype(str).str.contains("TIER2_FORCED", na=False), "tier"] = "Tier2"
    if "l2_name" in df.columns:
        df.loc[(df["tier"] == "Tier1") & (df["l2_name"] == UNKNOWN_INDUSTRY), "tier"] = "Tier2"
    return df, info


# ── 非生产对比:某 profile vs legacy 的选股 diff(供"上线不盲改")─────────────────
def selection_diff(df: pd.DataFrame, base_weights: dict, cand_weights: dict) -> dict:
    """同一份候选数据,分别用 base / cand 权重跑 final_score_and_tier,比较 Tier1 名单变动
    与过热票占比。横截面(不含前向收益——前向记分牌是 register forward-item 的后续件)。"""
    base_df, _ = final_score_and_tier(df, base_weights)
    cand_df, _ = final_score_and_tier(df, cand_weights)
    code = df["ts_code"] if "ts_code" in df.columns else pd.Series(df.index, index=df.index)
    base_t1 = set(code[base_df["tier"] == "Tier1"])
    cand_t1 = set(code[cand_df["tier"] == "Tier1"])
    oh = df.get("overheat_flag", pd.Series(False, index=df.index)).fillna(False)
    ch = df.get("chasing_high", pd.Series(False, index=df.index)).fillna(False)
    hot = (oh | ch)
    hot_codes = set(code[hot])

    def _hot_share(t1):
        return round(len(t1 & hot_codes) / len(t1), 4) if t1 else 0.0
    return {
        "base_tier1_n": len(base_t1), "cand_tier1_n": len(cand_t1),
        "added": sorted(cand_t1 - base_t1), "removed": sorted(base_t1 - cand_t1),
        "kept_n": len(base_t1 & cand_t1),
        "base_overheat_share": _hot_share(base_t1),
        "cand_overheat_share": _hot_share(cand_t1),
    }


COMPARISON_TOP_N = 15           # 每 variant 输出的 top-N 清单长度(对齐 EGS watch_n;comparison-only)
PROFILE_WATCH_POOL_TOP_N = 15   # P5 唯一正式观察池的固定槽位数


def select_profile_watch_pool(scored_df: pd.DataFrame, top_n: int = PROFILE_WATCH_POOL_TOP_N) -> pd.DataFrame:
    """Return the one governed Tier1 watch-pool selection for a scored profile.

    This is the production selection shape extracted from ``score_l5``: only
    Tier1 rows, deterministic score ordering, the existing oversized-L2
    truncation, then the existing incremental L1/L2 concentration checks.
    It deliberately leaves a short pool short rather than filling it with
    Tier2 rows.  P5 must use this exact function for production balanced and
    every comparison profile.
    """
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n <= 0:
        raise ValueError("top_n 必须为正整数")
    required = {"tier", "final_score", "l4_score", "pct_20d_n", "l1_name", "l2_name"}
    missing = sorted(required - set(scored_df.columns))
    if missing:
        raise ValueError(f"profile watch pool 缺少字段: {','.join(missing)}")

    tier1 = scored_df[scored_df["tier"] == "Tier1"].sort_values(
        ["final_score", "l4_score", "pct_20d_n"], ascending=[False, False, False]
    )

    # Keep the existing production rule byte-for-byte in behavior: a very
    # large L2 first releases room for other industries before concentration
    # selection begins.
    l2_counts = tier1["l2_name"].value_counts()
    overflow = set(l2_counts[l2_counts > 20].index)
    if overflow:
        l2_seen: dict[object, int] = {}
        kept_rows = []
        for _, row in tier1.iterrows():
            l2 = row["l2_name"]
            count = l2_seen.get(l2, 0)
            if l2 in overflow and count >= 15:
                continue
            kept_rows.append(row)
            l2_seen[l2] = count + 1
        tier1 = pd.DataFrame(kept_rows, columns=scored_df.columns)

    selected_rows = []
    l1_counts: dict[object, int] = {}
    l2_selected_counts: dict[object, int] = {}
    for _, row in tier1.iterrows():
        l1, l2 = row["l1_name"], row["l2_name"]
        l1_key = l2 if l1 == UNKNOWN_INDUSTRY else l1
        denominator = max(len(selected_rows), 1)
        if l1_counts.get(l1_key, 0) / denominator > 0.4:
            continue
        if l2_selected_counts.get(l2, 0) / denominator > 0.3:
            continue
        selected_rows.append(row)
        l1_counts[l1_key] = l1_counts.get(l1_key, 0) + 1
        l2_selected_counts[l2] = l2_selected_counts.get(l2, 0) + 1

    return pd.DataFrame(selected_rows, columns=scored_df.columns).head(top_n)


def _watch_pool_rows(scored_df: pd.DataFrame) -> list[dict]:
    """Render a P5 selector result without altering its selection semantics."""
    rows = []
    for _, row in scored_df.iterrows():
        rows.append({
            "ts_code": str(row.get("ts_code", row.name)),
            "final_score": float(row["final_score"]),
            "l4_score": float(row["l4_score"]),
            "pct_20d_n": float(row["pct_20d_n"]),
            "tier": str(row["tier"]),
            "l1_name": str(row["l1_name"]),
            "l2_name": str(row["l2_name"]),
            "industry_heat_score": (None if pd.isna(row.get("industry_heat_score"))
                                    else float(row["industry_heat_score"])),
            "overheat_flag": bool(row.get("overheat_flag", False)),
            "chasing_high": bool(row.get("chasing_high", False)),
        })
    return rows


def _canonical_digest(value) -> str:
    """Stable JSON digest for a P5 source-bound EGS universe artifact."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _digest_scalar(value):
    if value is None or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return None
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (np.floating, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return str(value)


def _full_universe_digest(df: pd.DataFrame) -> str:
    """Fingerprint every scored-universe value in deterministic code/column order.

    It is deliberately separate from the candidate digest: P5 must be able to
    prove that all four profile pools came from one complete scored universe.
    """
    columns = sorted(str(column) for column in df.columns)
    records = []
    for _, row in df.sort_values("ts_code", kind="mergesort").iterrows():
        records.append({column: _digest_scalar(row[column]) for column in columns})
    return _canonical_digest({"columns": columns, "rows": records})


def _real_p5_source_fingerprint() -> str:
    import sys as _sys
    from engine import a_short_evidence_epoch_mode as epoch_mode
    return _canonical_digest(epoch_mode.semantic_function_contract(
        _sys.modules[__name__],
        ("select_profile_watch_pool", "final_score_and_tier", "compute_industry_heat_score"),
    ))


def _p5_source_fingerprint() -> str:
    from engine import a_short_evidence_epoch_mode as epoch_mode
    return epoch_mode.fingerprint_or_pre_freeze(
        "p5_industry_weight",
        _real_p5_source_fingerprint,
    )


def _p5_governance_digest(governance_path) -> str:
    """Content digest of the profile governance, insensitive to JSON formatting."""
    with open(governance_path, "r", encoding="utf-8") as handle:
        return _canonical_digest(json.load(handle))


def _profile_top_n(df: pd.DataFrame, weights: dict, top_n: int) -> list:
    """某 profile 下按 final_score 降序的 top-N 选股清单(comparison-only,非生产、不可照做)。"""
    scored, _ = final_score_and_tier(df, weights)
    code = scored["ts_code"] if "ts_code" in scored.columns else pd.Series(scored.index, index=scored.index)
    scored = scored.assign(_code=code).sort_values("final_score", ascending=False).head(top_n)
    rows = []
    for _, r in scored.iterrows():
        rows.append({
            "ts_code": str(r["_code"]),
            "final_score": float(r["final_score"]),
            "tier": str(r["tier"]),
            "industry_heat_score": (None if pd.isna(r.get("industry_heat_score"))
                                    else float(r.get("industry_heat_score"))),
            "l2_name": (None if r.get("l2_name") is None or pd.isna(r.get("l2_name"))
                        else str(r.get("l2_name"))),
        })
    return rows


def build_weight_comparison(full_df: pd.DataFrame, gov_path: str = GOV_PATH,
                            top_n: int = COMPARISON_TOP_N, as_of=None) -> dict:
    """非生产对比产物:每个非 legacy profile vs legacy 的选股 diff(横截面 Tier1 变动 + 过热占比),
    外加 **每个 profile(含 legacy)的 top-N 选股清单**(comparison-only,仅供并排比较,不可照做)。
    用全量已打分 universe df。前向收益记分牌 + 自动 flag = register forward-item 后续件。"""
    gov = load_governance(gov_path)
    legacy_w = gov["profiles"]["legacy"]
    df = full_df.copy()
    if "industry_heat_score" not in df.columns:
        df["industry_heat_score"] = compute_industry_heat_score(df)
    legacy_vs = {name: selection_diff(df, legacy_w, w)
                 for name, w in gov["profiles"].items() if name != "legacy"}
    variant_top_n = {name: _profile_top_n(df, w, top_n) for name, w in gov["profiles"].items()}
    profile_watch_pool_top15 = {}
    for name, weights in gov["profiles"].items():
        scored, _ = final_score_and_tier(df, weights)
        profile_watch_pool_top15[name] = _watch_pool_rows(
            select_profile_watch_pool(scored, top_n=PROFILE_WATCH_POOL_TOP_N)
        )
    governance_path = os.path.abspath(gov_path)
    # Digest the PARSED governance, not its bytes: reformatting or a line-ending
    # change must not invalidate an already-published comparison bundle.
    governance_sha256 = _p5_governance_digest(governance_path)
    return {
        "schema_name": "egs_weight_comparison", "schema_version": "1.0.0",
        "as_of": (None if as_of is None else str(as_of)),
        "universe_digest": _full_universe_digest(df),
        "governance_sha256": governance_sha256,
        "source_fingerprint": _p5_source_fingerprint(),
        "active_profile": gov["active_profile"], "universe_n": int(len(df)),
        "legacy_vs": legacy_vs,
        "variant_top_n": {
            "_label": ("comparison-only / non-production / NOT tradeable — informational side-by-side "
                       "of what each weight profile would pick; the production picks are the ACTIVE "
                       "profile only; do NOT trade a non-active variant's list"),
            "top_n": top_n,
            "profiles": variant_top_n,
        },
        "profile_watch_pool_top15": {
            "_label": ("P5 governed watch-pool selector output. It is the only profile-list shape "
                       "allowed for future P5 evidence capture; it is comparison-only and cannot trade "
                       "or alter the active profile."),
            "top_n": PROFILE_WATCH_POOL_TOP_N,
            "profiles": profile_watch_pool_top15,
        },
        "note": ("non-production cross-sectional Tier1 diff + per-profile top-N lists (no forward "
                 "returns); forward-return scoreboard + promotion auto-flag = register forward-item follow-up"),
        "boundary": {"production": False, "changes_selection": False, "is_promotion_decision": False,
                     "variant_lists_are_tradeable": False},
    }


def write_weight_comparison(full_df: pd.DataFrame, out_path: str, gov_path: str = GOV_PATH,
                            top_n: int = COMPARISON_TOP_N, as_of=None) -> dict:
    out = build_weight_comparison(full_df, gov_path, top_n, as_of)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)
    return out
