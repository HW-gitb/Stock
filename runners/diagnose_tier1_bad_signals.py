#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 3.2 Tier1 bad-signal diagnostics.

Reads existing rank backtest outputs and generated full-rank CSVs. It does not
run EGS and does not change candidate pools.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_rank import _cluster_stats, build_group_columns, build_stats


ROOT = Path(__file__).resolve().parents[1]
BACKTEST_DIR = ROOT / "result" / "a_short" / "backtest"
DEFAULT_SAMPLES = BACKTEST_DIR / "rank_samples.csv"
DEFAULT_GENERATED = BACKTEST_DIR / "generated"
DEFAULT_OUT_DIR = BACKTEST_DIR
BAD_THRESHOLD_PCT = -5.0


FULL_RANK_COLUMNS = [
    "trade_date",
    "ts_code",
    "z_group",
    "cat_flag",
    "alpha_flag",
    "big_ratio",
    "vol_confirm",
    "vol_shrink",
    "limit_20d",
    "limit_10d",
    "ind_mom_cnt",
    "alpha_excess",
    "q0_profit_dedt",
    "q0_net_income",
    "ttm_profit_dedt",
    "ttm_ocf_ratio",
    "roe",
    "l2_pe_mkt_pct",
    "pe_ttm",
    "pb",
    "turnover_rate",
    "total_mv",
    "circ_mv",
    "low_base_growth_flag",
    "downgrade_reasons",
    "score_penalty_reasons",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Diagnose Tier1 bad-signal candidates from existing backtest outputs.")
    parser.add_argument("--samples", default=str(DEFAULT_SAMPLES), help="Path to rank_samples.csv.")
    parser.add_argument("--generated-root", default=str(DEFAULT_GENERATED), help="Path to generated backtest root.")
    parser.add_argument("--split-date", default="20250101", help="YYYYMMDD discovery/validation split.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory.")
    parser.add_argument("--bad-threshold-pct", type=float, default=BAD_THRESHOLD_PCT,
                        help="Bad outcome threshold for t1_net returns, default -5%%.")
    parser.add_argument("--min-discovery-n", type=int, default=8)
    parser.add_argument("--min-validation-n", type=int, default=5)
    return parser.parse_args()


def load_samples(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["trade_date"] = df["trade_date"].astype(str)
    df["ts_code"] = df["ts_code"].astype(str)
    return df


def load_full_rank_fields(generated_root: Path, dates: list[str], codes_by_date: dict[str, set[str]]) -> pd.DataFrame:
    rows = []
    for trade_date in dates:
        path = generated_root / "_intermediate" / f"egs_full_{trade_date}.csv"
        if not path.exists():
            continue
        full = pd.read_csv(path)
        full["trade_date"] = str(trade_date)
        full["ts_code"] = full["ts_code"].astype(str)
        keep = full[full["ts_code"].isin(codes_by_date.get(str(trade_date), set()))].copy()
        cols = [col for col in FULL_RANK_COLUMNS if col in keep.columns]
        if cols:
            rows.append(keep[cols])
    if not rows:
        return pd.DataFrame(columns=["trade_date", "ts_code"])
    return pd.concat(rows, ignore_index=True)


def enrich_samples(samples: pd.DataFrame, generated_root: Path) -> pd.DataFrame:
    tier1 = samples[samples["tier"].astype(str).eq("Tier1")].copy()
    codes_by_date = {
        str(d): set(grp["ts_code"].astype(str))
        for d, grp in tier1.groupby("trade_date", dropna=True)
    }
    full = load_full_rank_fields(generated_root, sorted(codes_by_date), codes_by_date)
    if not full.empty:
        tier1 = tier1.merge(full, on=["trade_date", "ts_code"], how="left", suffixes=("", "_full"))
    return add_diagnostic_columns(tier1)


def add_diagnostic_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = build_group_columns(df)
    for window in [5, 10, 20]:
        col = f"ret_{window}d_t1_net"
        df[f"bad_{window}d"] = pd.to_numeric(df[col], errors="coerce") <= BAD_THRESHOLD_PCT

    df["pct_5d_bucket"] = pd.cut(
        numeric_series(df, "pct_5d_n"),
        bins=[-999, -5, 0, 5, 10, 999],
        labels=["pct5_lt_-5", "pct5_-5_0", "pct5_0_5", "pct5_5_10", "pct5_10_plus"],
    )
    df["pct_20d_bucket"] = pd.cut(
        numeric_series(df, "pct_20d_n"),
        bins=[-999, -10, 0, 10, 20, 40, 999],
        labels=["pct20_lt_-10", "pct20_-10_0", "pct20_0_10", "pct20_10_20", "pct20_20_40", "pct20_40_plus"],
    )
    df["drawdown_20d_bucket"] = pd.cut(
        numeric_series(df, "drawdown_20d"),
        bins=[-999, -20, -10, -5, 0, 999],
        labels=["dd20_lt_-20", "dd20_-20_-10", "dd20_-10_-5", "dd20_-5_0", "dd20_0_plus"],
    )
    df["q1_dt_yoy_bucket"] = pd.cut(
        numeric_series(df, "q1_dt_yoy"),
        bins=[-99999, -100, -30, 0, 30, 100, 200, 99999],
        labels=["q1_lt_-100", "q1_-100_-30", "q1_-30_0", "q1_0_30", "q1_30_100", "q1_100_200", "q1_200_plus"],
    )
    df["esp_raw_bucket"] = pd.cut(
        numeric_series(df, "esp_raw"),
        bins=[-99999, 0, 50, 100, 200, 99999],
        labels=["esp_lt_0", "esp_0_50", "esp_50_100", "esp_100_200", "esp_200_plus"],
        include_lowest=True,
    )
    df["market_cap_bucket"] = pd.qcut(
        numeric_series(df, "total_mv"),
        q=4,
        labels=["mv_q1_small", "mv_q2", "mv_q3", "mv_q4_large"],
        duplicates="drop",
    )
    return df


def numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(np.nan, index=df.index)
    value = df[column]
    if isinstance(value, pd.DataFrame):
        value = value.iloc[:, 0]
    return pd.to_numeric(value, errors="coerce")


def period_label(trade_date: str, split_date: str) -> str:
    return "discovery" if str(trade_date) < str(split_date) else "validation"


def baseline_rows(df: pd.DataFrame, split_date: str, bad_threshold: float) -> pd.DataFrame:
    rows = []
    for split, grp in split_groups(df, split_date):
        row = {
            "period_split": split,
            "sample_count": int(len(grp)),
            "bad_5d_rate_pct": rate(grp["bad_5d"]),
            "bad_10d_rate_pct": rate(grp["bad_10d"]),
            "bad_20d_rate_pct": rate(grp["bad_20d"]),
        }
        for window in [5, 10, 20]:
            ret_col = f"ret_{window}d_t1_net"
            values = pd.to_numeric(grp[ret_col], errors="coerce").dropna()
            stats = _cluster_stats(grp[["trade_date", ret_col]].rename(columns={ret_col: "value"}))
            row[f"mean_{window}d_t1_net"] = float(values.mean()) if len(values) else None
            row[f"monthly_t_{window}d_t1_net"] = stats["monthly_t"]
            row[f"win_rate_{window}d_pct"] = float((values > 0).mean() * 100) if len(values) else None
        rows.append(row)
    return pd.DataFrame(rows)


def split_groups(df: pd.DataFrame, split_date: str):
    yield "all", df
    yield "discovery", df[df["trade_date"].astype(str) < str(split_date)]
    yield "validation", df[df["trade_date"].astype(str) >= str(split_date)]


def rate(series: pd.Series) -> float | None:
    vals = series.dropna()
    if len(vals) == 0:
        return None
    return float(vals.mean() * 100)


def feature_specs():
    return [
        ("rank_bucket", "rank"),
        ("final_score_bucket_fine", "score"),
        ("l4_flag_group", "technical"),
        ("entry_flag_group", "entry"),
        ("data_quality_bucket", "data_quality"),
        ("risk_reasons", "risk"),
        ("pct_5d_bucket", "technical"),
        ("pct_20d_bucket", "technical"),
        ("drawdown_20d_bucket", "technical"),
        ("q1_dt_yoy_bucket", "fundamental"),
        ("esp_raw_bucket", "expectation"),
        ("l1_name", "industry_l1"),
        ("l2_name", "industry_l2"),
        ("board", "board"),
        ("market_cap_bucket", "size"),
    ]


def summarize_feature(df: pd.DataFrame, feature: str, family: str, split_date: str) -> list[dict]:
    rows = []
    if feature not in df.columns:
        return rows
    for value, grp in df.groupby(feature, dropna=False):
        label = "<NA>" if pd.isna(value) else str(value)
        row = {
            "feature_family": family,
            "feature": feature,
            "feature_value": label,
        }
        for split, sgrp in split_groups(grp, split_date):
            prefix = f"{split}_"
            row[prefix + "sample_count"] = int(len(sgrp))
            row[prefix + "bad_5d_rate_pct"] = rate(sgrp["bad_5d"])
            row[prefix + "bad_10d_rate_pct"] = rate(sgrp["bad_10d"])
            row[prefix + "bad_20d_rate_pct"] = rate(sgrp["bad_20d"])
            for window in [5, 10, 20]:
                ret_col = f"ret_{window}d_t1_net"
                vals = pd.to_numeric(sgrp[ret_col], errors="coerce").dropna()
                stats = _cluster_stats(sgrp[["trade_date", ret_col]].rename(columns={ret_col: "value"}))
                row[prefix + f"mean_{window}d_t1_net"] = float(vals.mean()) if len(vals) else None
                row[prefix + f"monthly_t_{window}d_t1_net"] = stats["monthly_t"]
                row[prefix + f"win_rate_{window}d_pct"] = float((vals > 0).mean() * 100) if len(vals) else None
        rows.append(row)
    return rows


def build_feature_table(df: pd.DataFrame, split_date: str, min_discovery: int, min_validation: int) -> pd.DataFrame:
    rows = []
    for feature, family in feature_specs():
        rows.extend(summarize_feature(df, feature, family, split_date))
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    baseline = baseline_rows(df, split_date, BAD_THRESHOLD_PCT).set_index("period_split")
    disc_bad_base = baseline.loc["discovery", "bad_20d_rate_pct"]
    val_bad_base = baseline.loc["validation", "bad_20d_rate_pct"]
    disc_mean_base = baseline.loc["discovery", "mean_20d_t1_net"]
    val_mean_base = baseline.loc["validation", "mean_20d_t1_net"]
    out["discovery_bad20_lift_pctpt"] = out["discovery_bad_20d_rate_pct"] - disc_bad_base
    out["validation_bad20_lift_pctpt"] = out["validation_bad_20d_rate_pct"] - val_bad_base
    out["discovery_mean20_delta_pct"] = out["discovery_mean_20d_t1_net"] - disc_mean_base
    out["validation_mean20_delta_pct"] = out["validation_mean_20d_t1_net"] - val_mean_base
    out["candidate_flag"] = np.where(
        (out["discovery_sample_count"] >= min_discovery)
        & (out["validation_sample_count"] >= min_validation)
        & (out["discovery_bad20_lift_pctpt"] > 10)
        & (out["validation_bad20_lift_pctpt"] > 0)
        & (out["discovery_mean20_delta_pct"] < 0)
        & (out["validation_mean20_delta_pct"] < 0),
        "candidate_negative",
        "observation",
    )
    return out.sort_values(
        ["candidate_flag", "validation_mean20_delta_pct", "validation_bad20_lift_pctpt", "discovery_bad20_lift_pctpt"],
        ascending=[True, True, False, False],
    )


def bad_sample_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "trade_date", "ts_code", "name", "rank", "final_score", "rank_bucket",
        "l1_name", "l2_name", "l4_flag", "entry_flag", "risk_reasons",
        "pct_5d_n", "pct_20d_n", "drawdown_20d", "q1_dt_yoy", "esp_raw",
        "ret_5d_t1_net", "ret_10d_t1_net", "ret_20d_t1_net",
    ]
    cols = [col for col in cols if col in df.columns]
    bad = df[pd.to_numeric(df["ret_20d_t1_net"], errors="coerce") <= BAD_THRESHOLD_PCT].copy()
    return bad.sort_values(["trade_date", "ret_20d_t1_net"])[cols]


def build_replay_variants(df: pd.DataFrame, split_date: str) -> pd.DataFrame:
    q1_bucket = pd.cut(
        numeric_series(df, "q1_dt_yoy"),
        bins=[-99999, -100, -30, 0, 30, 100, 200, 99999],
        labels=["q1_lt_-100", "q1_-100_-30", "q1_-30_0", "q1_0_30", "q1_30_100", "q1_100_200", "q1_200_plus"],
    ).astype(str)
    variants = {
        "tier1_only": df,
        "score_ge_60": df[numeric_series(df, "final_score") >= 60],
        "score_ge_65": df[numeric_series(df, "final_score") >= 65],
        "drop_q1_30_100": df[~q1_bucket.eq("q1_30_100")],
        "drop_q1_neg_100_30": df[~q1_bucket.eq("q1_-100_-30")],
    }
    rows = []
    for name, vdf in variants.items():
        summary, *_ = build_stats(vdf, [5, 10, 20], split_date=split_date)
        if summary.empty:
            continue
        sub = summary[
            summary["period_split"].isin(["all", "discovery", "validation"])
            & summary["variant"].eq("t1_net")
        ].copy()
        if (sub["subset"] == "tier1_only").any():
            sub = sub[sub["subset"].eq("tier1_only")]
        else:
            sub = sub[sub["subset"].eq("all")]
        sub.insert(0, "replay_variant", name)
        rows.append(sub[[
            "replay_variant", "period_split", "window", "sample_count",
            "mean_return_pct", "monthly_t", "win_rate_pct",
        ]])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def write_markdown(path: Path, baseline: pd.DataFrame, features: pd.DataFrame,
                   replay: pd.DataFrame, bad_samples: pd.DataFrame, args) -> None:
    top_candidates = features[features["candidate_flag"].eq("candidate_negative")].head(20)
    top_observations = features[
        (features["discovery_sample_count"] >= args.min_discovery_n)
        & (features["validation_sample_count"] >= args.min_validation_n)
    ].sort_values(["validation_mean20_delta_pct", "validation_bad20_lift_pctpt"], ascending=[True, False]).head(20)

    lines = [
        "# Phase 3.2 Tier1 Bad-Signal Diagnostics",
        "",
        f"- Source: `{Path(args.samples).as_posix()}`",
        f"- Split date: `{args.split_date}`",
        f"- Bad threshold: `t1_net <= {args.bad_threshold_pct:.2f}%`",
        "- Scope: Tier1 only. This diagnostic does not change candidate pools or primary reporting.",
        "",
        "## Baseline",
        "",
        markdown_table(baseline),
        "",
        "## Candidate Negative Features",
        "",
    ]
    if top_candidates.empty:
        lines.append("No feature passed the conservative discovery + validation candidate filter.")
    else:
        lines.append(markdown_table(display_feature_columns(top_candidates)))
    lines.extend([
        "",
        "## Replay Checks",
        "",
        markdown_table(replay) if not replay.empty else "No replay checks available.",
        "",
        "## Strongest Validation Observations",
        "",
        markdown_table(display_feature_columns(top_observations)) if not top_observations.empty else "No observations with enough validation support.",
        "",
        "## Worst 20d Tier1 Samples",
        "",
        markdown_table(bad_samples.head(40)) if not bad_samples.empty else "No bad samples under the configured threshold.",
        "",
        "## Interpretation Boundary",
        "",
        "- A feature is not a veto just because it appears here.",
        "- Promote only if discovery and validation both support it, N is adequate, and the rule has a plausible mechanism.",
        "- Keep `tier1_only` as the primary baseline until a replay subset materially improves it.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def display_feature_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "feature_family",
        "feature",
        "feature_value",
        "discovery_sample_count",
        "discovery_bad_20d_rate_pct",
        "discovery_mean_20d_t1_net",
        "validation_sample_count",
        "validation_bad_20d_rate_pct",
        "validation_mean_20d_t1_net",
        "validation_monthly_t_20d_t1_net",
        "discovery_bad20_lift_pctpt",
        "validation_bad20_lift_pctpt",
        "validation_mean20_delta_pct",
        "candidate_flag",
    ]
    return df[[col for col in cols if col in df.columns]].copy()


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
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(x).replace("|", "\\|") for x in row) + " |")
    return "\n".join(lines)


def main():
    args = parse_args()
    samples_path = Path(args.samples)
    generated_root = Path(args.generated_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    samples = load_samples(samples_path)
    tier1 = enrich_samples(samples, generated_root)
    baseline = baseline_rows(tier1, args.split_date, args.bad_threshold_pct)
    features = build_feature_table(tier1, args.split_date, args.min_discovery_n, args.min_validation_n)
    replay = build_replay_variants(tier1, args.split_date)
    bad_samples = bad_sample_table(tier1)

    baseline_path = out_dir / "phase3_tier1_bad_signal_baseline.csv"
    features_path = out_dir / "phase3_tier1_bad_signal_features.csv"
    bad_path = out_dir / "phase3_tier1_bad_signal_samples.csv"
    replay_path = out_dir / "phase3_tier1_bad_signal_replay_variants.csv"
    report_path = out_dir / "Phase3_tier1_bad_signal_diagnostics.md"

    baseline.to_csv(baseline_path, index=False, encoding="utf-8-sig")
    features.to_csv(features_path, index=False, encoding="utf-8-sig")
    replay.to_csv(replay_path, index=False, encoding="utf-8-sig")
    bad_samples.to_csv(bad_path, index=False, encoding="utf-8-sig")
    write_markdown(report_path, baseline, features, replay, bad_samples, args)

    candidate_count = int((features["candidate_flag"] == "candidate_negative").sum()) if not features.empty else 0
    print(f"[OK] tier1 samples={len(tier1)} bad20={len(bad_samples)} candidate_features={candidate_count}")
    print(f"[OK] wrote {baseline_path.relative_to(ROOT)}")
    print(f"[OK] wrote {features_path.relative_to(ROOT)}")
    print(f"[OK] wrote {replay_path.relative_to(ROOT)}")
    print(f"[OK] wrote {bad_path.relative_to(ROOT)}")
    print(f"[OK] wrote {report_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
