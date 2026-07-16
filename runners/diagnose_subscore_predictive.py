#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3.3 sub-score predictive analysis (BACKTEST-MODE SCOPE ONLY).

Reads existing rank_samples.csv from the latest 24p backtest. For each
EGS sub-score (final_score / esp_score / l4_score), groups Tier1 names
by score level and computes forward 5d / 10d / 20d t1_net stats split
into discovery / validation.

IMPORTANT scope limit — backtest runs with `--mode production` use
`--l3-mode neutralize` by default (CURRENT.md, AGENTS.md). Under
neutralize, EGS hard-codes `cat_score = 50.0` for all candidates
(egs_main.py) to avoid L3 look-ahead since current HiThink concept membership
has no historical as-of endpoint. So:
  * cat_score is excluded from this analysis NOT because EGS lacks
    discrimination, but because the backtest data path zeros it out.
    Live `--l3-mode today` runs produce varying cat_score in 12-100.
  * final_score under neutralize = 0.20*esp + 0.50*l4 + 15. Live
    final_score adds the 0.30*cat term, so live ranking behavior
    can diverge meaningfully from backtest ranking behavior.
  * esp_score and l4_score ARE reflected normally under neutralize;
    findings about those two are valid for backtest-mode behavior
    but should not be assumed to hold unchanged in live mode.
  * cat_score's real predictive power cannot be retroactively tested
    until L3 PIT snapshots accumulate ~6 months (target 2026-12 per
    CURRENT.md P2.6); then re-run with `--l3-mode pit`.

Question this answers (within scope): in BACKTEST mode, does any
sub-score predict forward returns better than the composite
final_score? Live mode answer requires PIT data.

This script does not run EGS, does not fetch new forward daily, and
does not change candidate pools or strategy variants. It is a
read-only diagnostic, like runners/diagnose_tier1_bad_signals.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.backtest_rank import _cluster_stats

BACKTEST_DIR = ROOT / "result" / "a_short" / "backtest"
DEFAULT_SAMPLES = BACKTEST_DIR / "rank_samples.csv"
DEFAULT_OUT_DIR = BACKTEST_DIR


def parse_args():
    parser = argparse.ArgumentParser(description="Diagnose EGS sub-score predictive power on Tier1 within 24p.")
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES))
    parser.add_argument("--split-date", default="20250101")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args()


def load_tier1(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["trade_date"] = df["trade_date"].astype(str)
    df = df[df["tier"].astype(str) == "Tier1"].copy()
    for col in ["final_score", "esp_score", "l4_score"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def group_specs(df: pd.DataFrame):
    """Hand-picked bin boundaries that respect actual sub-score clumping.

    esp_score in 24p has 11 distinct values with 58% at default 50; l4_score
    has 8 values with 75% at 100. Equal-N quintile would put all the default
    50 in one bin and skew analysis. These hand-picked groups carve along
    the real value clusters so each bin has at least N>=30 and the boundaries
    correspond to interpretable EGS signal states.
    """
    return [
        ("final_score", "final_score_group", [
            ("lt_60", df["final_score"] < 60),
            ("60_70", (df["final_score"] >= 60) & (df["final_score"] < 70)),
            ("70_75", (df["final_score"] >= 70) & (df["final_score"] < 75)),
            ("75_80", (df["final_score"] >= 75) & (df["final_score"] < 80)),
            ("ge_80", df["final_score"] >= 80),
        ]),
        ("esp_score", "esp_score_group", [
            ("low_lt_50", df["esp_score"] < 50),
            ("neutral_50", df["esp_score"] == 50),
            ("high_gt_50", df["esp_score"] > 50),
        ]),
        ("l4_score", "l4_score_group", [
            ("lt_70", df["l4_score"] < 70),
            ("70_99", (df["l4_score"] >= 70) & (df["l4_score"] < 100)),
            ("eq_100", df["l4_score"] == 100),
        ]),
    ]


def split_groups(df: pd.DataFrame, split_date: str):
    yield "all", df
    yield "discovery", df[df["trade_date"] < str(split_date)]
    yield "validation", df[df["trade_date"] >= str(split_date)]


def bucket_stats(grp: pd.DataFrame, window: int) -> dict:
    col = f"ret_{window}d_t1_net"
    if col not in grp.columns:
        return {"sample_count": 0, "mean_return_pct": None, "monthly_t": None, "win_rate_pct": None}
    vals = pd.to_numeric(grp[col], errors="coerce").dropna()
    stats = _cluster_stats(grp[["trade_date", col]].rename(columns={col: "value"}))
    return {
        "sample_count": int(len(vals)),
        "mean_return_pct": float(vals.mean()) if len(vals) else None,
        "monthly_t": stats["monthly_t"],
        "win_rate_pct": float((vals > 0).mean() * 100) if len(vals) else None,
    }


def build_table(df: pd.DataFrame, split_date: str) -> pd.DataFrame:
    rows = []
    for score_col, group_col, bin_specs in group_specs(df):
        for bin_label, bin_mask in bin_specs:
            sub = df[bin_mask]
            for split_label, sgrp in split_groups(sub, split_date):
                row = {
                    "score": score_col,
                    "group": bin_label,
                    "period_split": split_label,
                }
                for window in [5, 10, 20]:
                    stats = bucket_stats(sgrp, window)
                    for k, v in stats.items():
                        row[f"{k}_{window}d"] = v
                rows.append(row)
    return pd.DataFrame(rows)


def monotonicity_score(table: pd.DataFrame, score_col: str, window: int, period_split: str) -> float:
    """Simple monotonicity score: Spearman corr between bin rank and mean return.

    Returns NaN if fewer than 2 bins with samples. Positive means higher score
    bins have higher returns (the desired direction). Magnitude shows strength
    of monotonicity, not statistical significance.
    """
    sub = table[
        (table["score"] == score_col)
        & (table["period_split"] == period_split)
        & table[f"sample_count_{window}d"].fillna(0).gt(0)
    ].copy()
    if len(sub) < 2:
        return float("nan")
    sub["bin_index"] = range(len(sub))
    means = pd.to_numeric(sub[f"mean_return_pct_{window}d"], errors="coerce")
    if means.notna().sum() < 2:
        return float("nan")
    return float(pd.Series(sub["bin_index"]).corr(means, method="spearman"))


def write_markdown(path: Path, table: pd.DataFrame, args) -> None:
    lines = [
        "# Phase 3.3 Sub-Score Predictive Analysis (BACKTEST scope)",
        "",
        f"- Source: `{Path(args.samples).as_posix()}` (Tier1 only)",
        f"- Split date: `{args.split_date}` (discovery < split, validation >=)",
        "- Bins respect 24p sub-score clumping: esp_score 58% at default 50, l4_score 75% at 100.",
        "- Question: in BACKTEST mode (`--l3-mode neutralize`), does any sub-score predict forward 5d / 10d / 20d returns better than final_score?",
        "",
        "**SCOPE WARNING — cat_score is excluded for a data-path reason, not a model reason.**",
        "",
        "Backtest production runs default to `--l3-mode neutralize`, which hard-codes",
        "`cat_score = 50.0` for all candidates (egs_main.py:2202). Live weekly runs",
        "default to `--l3-mode today` where the complete HiThink main-board graph gives real cat_score in",
        "12-100. So:",
        "- This analysis reflects `final_score ≈ 0.20*esp + 0.50*l4 + 15` (backtest);",
        "  live `final_score = 0.20*esp + 0.30*cat + 0.50*l4` may behave differently.",
        "- cat_score's predictive power can only be tested once L3 PIT snapshots",
        "  accumulate enough history (target ~2026-12); re-run with `--l3-mode pit` then.",
        "- esp_score and l4_score findings here are valid for backtest mode; live",
        "  behavior may diverge if cat_score modulates the effect.",
        "",
        "## Monotonicity (Spearman bin-rank vs mean return; positive = higher score → higher return)",
        "",
    ]
    mono_rows = []
    for score_col in ["final_score", "esp_score", "l4_score"]:
        for window in [5, 10, 20]:
            mono_rows.append({
                "score": score_col,
                "window": window,
                "all": monotonicity_score(table, score_col, window, "all"),
                "discovery": monotonicity_score(table, score_col, window, "discovery"),
                "validation": monotonicity_score(table, score_col, window, "validation"),
            })
    mono_df = pd.DataFrame(mono_rows)
    lines.append(markdown_table(mono_df))
    lines.append("")
    lines.append("Interpretation guide:")
    lines.append("- |rho| > 0.7 and same sign across discovery + validation: real monotonic predictor.")
    lines.append("- rho flips sign between splits: regime-dependent, not stable.")
    lines.append("- |rho| < 0.3 in both splits: no usable signal.")
    lines.append("")
    lines.append("## Per-bin detail")
    lines.append("")
    show_cols = [
        "score", "group", "period_split",
        "sample_count_5d", "mean_return_pct_5d", "monthly_t_5d", "win_rate_pct_5d",
        "sample_count_10d", "mean_return_pct_10d", "monthly_t_10d", "win_rate_pct_10d",
        "sample_count_20d", "mean_return_pct_20d", "monthly_t_20d", "win_rate_pct_20d",
    ]
    lines.append(markdown_table(table[show_cols]))
    lines.append("")
    lines.append("## Interpretation Boundary")
    lines.append("")
    lines.append("- This is exploratory on Tier1 only (N=305, 24p, BACKTEST mode under l3_mode=neutralize). Sub-scores that look strong here may still be regime artifacts.")
    lines.append("- Do not promote a sub-score to a strategy variant unless monotonicity holds in both discovery + validation and at least 3 bins have N>=20.")
    lines.append("- cat_score is excluded because backtest runs hard-code it to 50 (l3_mode=neutralize). This is NOT evidence that the EGS catalyst signal lacks power — it cannot be tested here.")
    lines.append("- Live `--l3-mode today` cat_score behavior is unobserved in this analysis; do not assume final_score under neutralize behaves the same as live.")
    path.write_text("\n".join(lines), encoding="utf-8")


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    frame = df.copy()
    for col in frame.columns:
        if pd.api.types.is_float_dtype(frame[col]):
            frame[col] = frame[col].map(lambda x: "" if pd.isna(x) else f"{x:.4f}")
        else:
            frame[col] = frame[col].map(lambda x: "" if pd.isna(x) else str(x))
    headers = list(frame.columns)
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        out.append("| " + " | ".join(str(x).replace("|", "\\|") for x in row) + " |")
    return "\n".join(out)


def main():
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_tier1(Path(args.samples))
    table = build_table(df, args.split_date)

    detail_path = out_dir / "phase3_3_subscore_detail.csv"
    table.to_csv(detail_path, index=False, encoding="utf-8-sig")

    mono_rows = []
    for score_col in ["final_score", "esp_score", "l4_score"]:
        for window in [5, 10, 20]:
            mono_rows.append({
                "score": score_col,
                "window": window,
                "all": monotonicity_score(table, score_col, window, "all"),
                "discovery": monotonicity_score(table, score_col, window, "discovery"),
                "validation": monotonicity_score(table, score_col, window, "validation"),
            })
    mono_df = pd.DataFrame(mono_rows)
    mono_path = out_dir / "phase3_3_subscore_monotonicity.csv"
    mono_df.to_csv(mono_path, index=False, encoding="utf-8-sig")

    md_path = out_dir / "Phase3_3_subscore_predictive.md"
    write_markdown(md_path, table, args)

    print(f"[OK] Tier1 N={len(df)}")
    print(f"[OK] wrote {detail_path.relative_to(ROOT)}")
    print(f"[OK] wrote {mono_path.relative_to(ROOT)}")
    print(f"[OK] wrote {md_path.relative_to(ROOT)}")
    print("\nMonotonicity summary (Spearman; positive = higher score wins):")
    print(mono_df.to_string(index=False))


if __name__ == "__main__":
    main()
