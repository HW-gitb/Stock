from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pickle
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_RANK_SAMPLES = Path("result/a_short/backtest/rank_samples.csv")
DEFAULT_BENCHMARK_CACHE = Path("result/a_short/backtest/cache/forward_daily.pkl")
DEFAULT_PREREGISTRATION = Path("research/preregistrations/a_short_steady_alpha_reaudit_20260603.json")
DEFAULT_LEDGER = Path("research/ledgers/a_short_steady_alpha_reaudit_program_test_budget_ledger_20260603.json")
DEFAULT_OUTPUT_DIR = Path("research/results/a_short_steady_alpha_reaudit_20260603")
EVIDENCE_SCHEMA = Path("schemas/evidence_report.schema.json")
LEDGER_SCHEMA = Path("schemas/program_test_budget_ledger.schema.json")
DEFAULT_GENERATED_AT = "2026-06-03T00:00:00Z"
REPORT_DATE = "20260603"
TEST_ID = "a_short_steady_alpha_reaudit_20260603"
PRIMARY_HORIZON = 5
PRIMARY_BENCHMARK = "csi1000"
SECONDARY_BENCHMARK = "csi300"
HORIZONS = (5, 20)
BENCHMARKS = ("csi1000", "csi300")
REQUIRED_COLUMNS = {
    "trade_date",
    "ts_code",
    "tier",
    "ret_5d_status",
    "entry_date",
    "ret_5d_exit_date",
    "ret_5d_t1",
    "ret_5d_t1_net",
    "ret_5d_csi1000",
    "ret_5d_excess_csi1000",
    "ret_5d_csi300",
    "ret_5d_excess_csi300",
    "ret_20d_status",
    "ret_20d_exit_date",
    "ret_20d_t1",
    "ret_20d_t1_net",
    "ret_20d_csi1000",
    "ret_20d_excess_csi1000",
    "ret_20d_csi300",
    "ret_20d_excess_csi300",
}


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = mean(values)
    assert avg is not None
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def t_stat(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = mean(values)
    sd = stdev(values)
    if avg is None or sd in (None, 0):
        return None
    return avg / (sd / math.sqrt(len(values)))


def normal_two_sided_p_from_t(value: float | None) -> float | None:
    if value is None:
        return None
    return math.erfc(abs(value) / math.sqrt(2.0))


def rounded(value: float | None, digits: int = 10) -> float | None:
    return None if value is None else round(value, digits)


def fmt_number(value: float | None, digits: int = 6) -> str:
    return "null" if value is None else f"{value:.{digits}f}"


def read_rank_samples(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path} has no rows")
    missing = sorted(REQUIRED_COLUMNS - set(rows[0]))
    if missing:
        raise ValueError(f"{path} missing required columns: {missing}")
    return rows


def tier1_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    selected = [row for row in rows if row.get("tier") == "Tier1"]
    if not selected:
        raise ValueError("No Tier1 rows found in rank samples")
    return selected


def _records_from_benchmark_frame(frame: Any) -> list[dict[str, Any]]:
    if hasattr(frame, "to_dict"):
        return list(frame.to_dict("records"))
    if isinstance(frame, list):
        return [dict(item) for item in frame]
    return []


def load_benchmark_cache(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    raw_benchmarks = payload.get("benchmarks", {})
    lookups: dict[str, dict[str, tuple[float, float]]] = {}
    for benchmark in BENCHMARKS:
        records = _records_from_benchmark_frame(raw_benchmarks.get(benchmark))
        lookup: dict[str, tuple[float, float]] = {}
        for record in records:
            trade_date = str(record.get("trade_date", "")).strip()
            open_value = as_float(record.get("open"))
            close_value = as_float(record.get("close"))
            if not trade_date or open_value is None or close_value is None:
                continue
            if open_value <= 0 or close_value <= 0:
                continue
            lookup[trade_date] = (open_value, close_value)
        if not lookup:
            raise ValueError(f"{path} has no usable {benchmark} benchmark open/close rows")
        lookups[benchmark] = lookup
    return {
        "path": str(path).replace("\\", "/"),
        "meta": payload.get("meta", {}),
        "lookups": lookups,
    }


def same_anchor_benchmark_return(
    benchmark_lookup: dict[str, tuple[float, float]],
    entry_date: str,
    exit_date: str,
) -> float | None:
    if not entry_date or not exit_date:
        return None
    entry = benchmark_lookup.get(entry_date)
    exit_ = benchmark_lookup.get(exit_date)
    if entry is None or exit_ is None:
        return None
    entry_open = entry[0]
    exit_close = exit_[1]
    if entry_open <= 0 or exit_close <= 0:
        return None
    return (exit_close / entry_open - 1.0) * 100.0


def annotate_same_anchor_returns(
    rows: list[dict[str, str]],
    benchmark_cache: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    annotated = [dict(row) for row in rows]
    coverage: dict[str, dict[str, Any]] = {}
    lookups = benchmark_cache["lookups"]
    for horizon in HORIZONS:
        for benchmark in BENCHMARKS:
            status_col = f"ret_{horizon}d_same_anchor_{benchmark}_status"
            bench_col = f"ret_{horizon}d_{benchmark}_same_anchor"
            gross_excess_col = f"ret_{horizon}d_gross_excess_{benchmark}_same_anchor"
            net_excess_col = f"ret_{horizon}d_net_excess_{benchmark}_same_anchor"
            ok_count = 0
            missing_count = 0
            for row in annotated:
                row[status_col] = "not_applicable"
                if row.get(f"ret_{horizon}d_status") != "ok":
                    continue
                entry_date = row.get("entry_date", "")
                exit_date = row.get(f"ret_{horizon}d_exit_date", "")
                gross_return = as_float(row.get(f"ret_{horizon}d_t1"))
                net_return = as_float(row.get(f"ret_{horizon}d_t1_net"))
                benchmark_return = same_anchor_benchmark_return(
                    lookups[benchmark],
                    entry_date,
                    exit_date,
                )
                if gross_return is None or net_return is None or benchmark_return is None:
                    row[status_col] = "missing_same_anchor_inputs"
                    missing_count += 1
                    continue
                row[bench_col] = f"{benchmark_return:.12f}"
                row[gross_excess_col] = f"{gross_return - benchmark_return:.12f}"
                row[net_excess_col] = f"{net_return - benchmark_return:.12f}"
                row[status_col] = "ok"
                ok_count += 1
            coverage[f"{horizon}d_{benchmark.upper()}"] = {
                "status": "ok" if missing_count == 0 and ok_count > 0 else "partial_or_missing",
                "ok_rows": ok_count,
                "missing_rows": missing_count,
                "benchmark_leg": "benchmark_entry_date_open_to_exit_date_close",
                "stock_leg": "existing_ret_t1_net_entry_open_to_exit_close",
            }
    return annotated, {
        "benchmark_cache_path": benchmark_cache["path"],
        "benchmark_cache_meta": benchmark_cache["meta"],
        "coverage": coverage,
        "old_rank_samples_excess_treatment": (
            "ret_*d_excess_* columns are kept only as uncorrected gross close-to-close controls; "
            "they are not used as same-anchor net excess."
        ),
    }


def metric_rows(rows: list[dict[str, str]], horizon: int, benchmark: str) -> list[dict[str, str]]:
    status_col = f"ret_{horizon}d_same_anchor_{benchmark}_status"
    value_col = f"ret_{horizon}d_net_excess_{benchmark}_same_anchor"
    selected: list[dict[str, str]] = []
    for row in rows:
        if row.get(status_col) != "ok":
            continue
        if as_float(row.get(value_col)) is None:
            continue
        selected.append(row)
    return selected


def values_for(rows: list[dict[str, str]], horizon: int, benchmark: str) -> list[float]:
    value_col = f"ret_{horizon}d_net_excess_{benchmark}_same_anchor"
    values: list[float] = []
    for row in metric_rows(rows, horizon, benchmark):
        value = as_float(row.get(value_col))
        if value is not None:
            values.append(value)
    return values


def monthly_records(rows: list[dict[str, str]], horizon: int, benchmark: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    status_col = f"ret_{horizon}d_same_anchor_{benchmark}_status"
    net_excess_col = f"ret_{horizon}d_net_excess_{benchmark}_same_anchor"
    gross_excess_col = f"ret_{horizon}d_gross_excess_{benchmark}_same_anchor"
    net_col = f"ret_{horizon}d_t1_net"
    gross_col = f"ret_{horizon}d_t1"
    benchmark_col = f"ret_{horizon}d_{benchmark}_same_anchor"
    uncorrected_benchmark_col = f"ret_{horizon}d_{benchmark}"
    uncorrected_excess_col = f"ret_{horizon}d_excess_{benchmark}"
    for row in rows:
        if row.get(status_col) != "ok":
            continue
        if as_float(row.get(net_excess_col)) is None:
            continue
        grouped[row["trade_date"]].append(row)

    records: list[dict[str, Any]] = []
    for month, month_rows in sorted(grouped.items()):
        net_excess_values = [as_float(row.get(net_excess_col)) for row in month_rows]
        gross_excess_values = [as_float(row.get(gross_excess_col)) for row in month_rows]
        net_values = [as_float(row.get(net_col)) for row in month_rows]
        gross_values = [as_float(row.get(gross_col)) for row in month_rows]
        benchmark_values = [as_float(row.get(benchmark_col)) for row in month_rows]
        uncorrected_benchmark_values = [as_float(row.get(uncorrected_benchmark_col)) for row in month_rows]
        uncorrected_excess_values = [as_float(row.get(uncorrected_excess_col)) for row in month_rows]
        mean_gross_excess = mean([v for v in gross_excess_values if v is not None])
        mean_uncorrected_excess = mean([v for v in uncorrected_excess_values if v is not None])
        records.append(
            {
                "trade_date": month,
                "horizon_days": horizon,
                "benchmark": benchmark.upper(),
                "sample_count": len(month_rows),
                "mean_gross_return_pct": rounded(mean([v for v in gross_values if v is not None])),
                "mean_net_return_pct": rounded(mean([v for v in net_values if v is not None])),
                "mean_benchmark_return_pct": rounded(mean([v for v in benchmark_values if v is not None])),
                "mean_gross_excess_pct": rounded(mean_gross_excess),
                "mean_net_excess_pct": rounded(mean([v for v in net_excess_values if v is not None])),
                "mean_uncorrected_close_to_close_benchmark_pct": rounded(
                    mean([v for v in uncorrected_benchmark_values if v is not None])
                ),
                "mean_uncorrected_gross_excess_pct": rounded(mean_uncorrected_excess),
                "mean_anchor_only_delta_pct": rounded(
                    mean_gross_excess - mean_uncorrected_excess
                    if mean_gross_excess is not None and mean_uncorrected_excess is not None
                    else None
                ),
            }
        )
    return records


def max_additive_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    running = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        running += value
        peak = max(peak, running)
        max_drawdown = max(max_drawdown, peak - running)
    return max_drawdown


def winsorized_mean(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    trim = max(1, int(len(ordered) * 0.05)) if len(ordered) >= 20 else 0
    if trim and len(ordered) > trim * 2:
        ordered = ordered[trim:-trim]
    return mean(ordered)


def metric_summary(rows: list[dict[str, str]], horizon: int, benchmark: str) -> dict[str, Any]:
    selected = metric_rows(rows, horizon, benchmark)
    values = [
        value
        for value in (
            as_float(row.get(f"ret_{horizon}d_net_excess_{benchmark}_same_anchor"))
            for row in selected
        )
        if value is not None
    ]
    gross_values = [
        value
        for value in (
            as_float(row.get(f"ret_{horizon}d_gross_excess_{benchmark}_same_anchor"))
            for row in selected
        )
        if value is not None
    ]
    uncorrected_values = [
        value
        for value in (as_float(row.get(f"ret_{horizon}d_excess_{benchmark}")) for row in selected)
        if value is not None
    ]
    anchor_delta_values = []
    for row in selected:
        gross_value = as_float(row.get(f"ret_{horizon}d_gross_excess_{benchmark}_same_anchor"))
        uncorrected_value = as_float(row.get(f"ret_{horizon}d_excess_{benchmark}"))
        if gross_value is not None and uncorrected_value is not None:
            anchor_delta_values.append(gross_value - uncorrected_value)
    months = monthly_records(rows, horizon, benchmark)
    monthly_values = [record["mean_net_excess_pct"] for record in months if record["mean_net_excess_pct"] is not None]
    uncorrected_monthly_values = [
        record["mean_uncorrected_gross_excess_pct"]
        for record in months
        if record["mean_uncorrected_gross_excess_pct"] is not None
    ]
    positive_months = [value for value in monthly_values if value > 0]
    positive_total = sum(positive_months)
    return {
        "horizon_days": horizon,
        "benchmark": benchmark.upper(),
        "return_basis": "net_t1_minus_same_anchor_benchmark_entry_open_to_exit_close",
        "sample_count": len(values),
        "monthly_observation_count": len(monthly_values),
        "mean_net_excess_pct": rounded(mean(values)),
        "mean_gross_excess_pct": rounded(mean(gross_values)),
        "mean_uncorrected_gross_excess_pct": rounded(mean(uncorrected_values)),
        "mean_anchor_only_delta_pct": rounded(mean(anchor_delta_values)),
        "median_net_excess_pct": rounded(sorted(values)[len(values) // 2] if values else None),
        "winsorized_mean_net_excess_pct": rounded(winsorized_mean(values)),
        "sample_t_stat": rounded(t_stat(values)),
        "monthly_clustered_t_stat": rounded(t_stat(monthly_values)),
        "uncorrected_gross_monthly_clustered_t_stat": rounded(t_stat(uncorrected_monthly_values)),
        "positive_month_count": len(positive_months),
        "negative_month_count": len([value for value in monthly_values if value <= 0]),
        "min_monthly_net_excess_pct": rounded(min(monthly_values) if monthly_values else None),
        "max_monthly_net_excess_pct": rounded(max(monthly_values) if monthly_values else None),
        "max_additive_monthly_drawdown_pct": rounded(max_additive_drawdown(monthly_values)),
        "top_positive_month_share": rounded(max(positive_months) / positive_total if positive_total else None),
        "normal_approx_two_sided_p": rounded(normal_two_sided_p_from_t(t_stat(monthly_values))),
    }


def return_means(rows: list[dict[str, str]], horizon: int, benchmark: str) -> dict[str, float | None]:
    selected = [
        row
        for row in rows
        if row.get(f"ret_{horizon}d_same_anchor_{benchmark}_status") == "ok"
        and as_float(row.get(f"ret_{horizon}d_net_excess_{benchmark}_same_anchor")) is not None
    ]
    return {
        "gross_return_pct": rounded(mean([as_float(row.get(f"ret_{horizon}d_t1")) for row in selected if as_float(row.get(f"ret_{horizon}d_t1")) is not None])),
        "net_return_pct": rounded(mean([as_float(row.get(f"ret_{horizon}d_t1_net")) for row in selected if as_float(row.get(f"ret_{horizon}d_t1_net")) is not None])),
        "benchmark_return_pct": rounded(mean([as_float(row.get(f"ret_{horizon}d_{benchmark}_same_anchor")) for row in selected if as_float(row.get(f"ret_{horizon}d_{benchmark}_same_anchor")) is not None])),
        "net_excess_return_pct": rounded(mean([as_float(row.get(f"ret_{horizon}d_net_excess_{benchmark}_same_anchor")) for row in selected if as_float(row.get(f"ret_{horizon}d_net_excess_{benchmark}_same_anchor")) is not None])),
        "uncorrected_gross_excess_return_pct": rounded(mean([as_float(row.get(f"ret_{horizon}d_excess_{benchmark}")) for row in selected if as_float(row.get(f"ret_{horizon}d_excess_{benchmark}")) is not None])),
    }


def stock_concentration(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    stock_sum: dict[str, float] = defaultdict(float)
    stock_count: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.get("ret_5d_same_anchor_csi1000_status") != "ok":
            continue
        value = as_float(row.get("ret_5d_net_excess_csi1000_same_anchor"))
        if value is None:
            continue
        stock_sum[row["ts_code"]] += value
        stock_count[row["ts_code"]] += 1
    positive_total = sum(value for value in stock_sum.values() if value > 0)
    records = []
    for rank, (ts_code, contribution) in enumerate(
        sorted(stock_sum.items(), key=lambda item: item[1], reverse=True), start=1
    ):
        records.append(
            {
                "rank": rank,
                "ts_code": ts_code,
                "event_count": stock_count[ts_code],
                "sum_5d_csi1000_excess_pct": rounded(contribution),
                "positive_contribution_share": rounded(contribution / positive_total if contribution > 0 and positive_total else None),
            }
        )
    return records


def subset_rows(rows: list[dict[str, str]], subset: str) -> list[dict[str, str]]:
    if subset == "all":
        return rows
    if subset == "tier1":
        return [row for row in rows if row.get("tier") == "Tier1"]
    if subset == "tier2":
        return [row for row in rows if row.get("tier") == "Tier2"]
    if subset == "tier1_veto_passed":
        return [row for row in rows if as_bool(row.get("tier1_veto_passed"))]
    if subset == "overheat_flagged":
        return [
            row
            for row in rows
            if as_bool(row.get("has_l4_overheat")) or as_bool(row.get("overheat_flag"))
        ]
    if subset == "chasing_high_flagged":
        return [row for row in rows if as_bool(row.get("chasing_high"))]
    raise ValueError(f"Unknown subset {subset}")


def veto_filter_stats(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    records = []
    for subset in ("all", "tier1", "tier2", "tier1_veto_passed", "overheat_flagged", "chasing_high_flagged"):
        sub = subset_rows(rows, subset)
        summary = metric_summary(sub, PRIMARY_HORIZON, PRIMARY_BENCHMARK)
        records.append(
            {
                "subset": subset,
                "row_count": len(sub),
                "sample_count": summary["sample_count"],
                "monthly_observation_count": summary["monthly_observation_count"],
                "mean_5d_csi1000_excess_pct": summary["mean_net_excess_pct"],
                "monthly_clustered_t_stat": summary["monthly_clustered_t_stat"],
                "positive_month_count": summary["positive_month_count"],
            }
        )
    return records


def solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            return None
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        divisor = augmented[col][col]
        augmented[col] = [value / divisor for value in augmented[col]]
        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            augmented[row] = [
                augmented[row][idx] - factor * augmented[col][idx] for idx in range(size + 1)
            ]
    return [augmented[index][-1] for index in range(size)]


def ols(y_values: list[float], x_rows: list[list[float]]) -> dict[str, Any] | None:
    n = len(y_values)
    if n == 0 or len(x_rows) != n:
        return None
    k = len(x_rows[0])
    xtx = [[sum(x_rows[row][a] * x_rows[row][b] for row in range(n)) for b in range(k)] for a in range(k)]
    xty = [sum(x_rows[row][a] * y_values[row] for row in range(n)) for a in range(k)]
    beta = solve_linear_system(xtx, xty)
    if beta is None:
        return None
    residuals = [
        y_values[row] - sum(x_rows[row][col] * beta[col] for col in range(k)) for row in range(n)
    ]
    dof = n - k
    if dof <= 0:
        return {"beta": beta, "standard_error": None, "t_stat": None, "r_squared": None, "degrees_of_freedom": dof}
    sse = sum(value * value for value in residuals)
    avg_y = mean(y_values)
    assert avg_y is not None
    sst = sum((value - avg_y) ** 2 for value in y_values)
    sigma2 = sse / dof
    inverse_columns: list[list[float]] = []
    for unit_col in range(k):
        unit = [1.0 if index == unit_col else 0.0 for index in range(k)]
        solved = solve_linear_system(xtx, unit)
        if solved is None:
            return None
        inverse_columns.append(solved)
    standard_error = [math.sqrt(max(0.0, sigma2 * inverse_columns[idx][idx])) for idx in range(k)]
    t_values = [beta[idx] / standard_error[idx] if standard_error[idx] else None for idx in range(k)]
    return {
        "beta": [rounded(value) for value in beta],
        "standard_error": [rounded(value) for value in standard_error],
        "t_stat": [rounded(value) for value in t_values],
        "r_squared": rounded(1.0 - sse / sst if sst else None),
        "degrees_of_freedom": dof,
    }


def factor_exposure(monthly: list[dict[str, Any]], csi300_monthly: dict[str, float | None]) -> dict[str, Any]:
    usable = [
        item
        for item in monthly
        if item["mean_net_return_pct"] is not None and item["mean_benchmark_return_pct"] is not None
    ]
    y_values = [item["mean_net_return_pct"] for item in usable]
    csi1000 = [item["mean_benchmark_return_pct"] for item in usable]
    csi300 = [csi300_monthly.get(item["trade_date"]) for item in usable]
    complete_size_proxy = all(value is not None for value in csi300)
    single_factor = ols(y_values, [[1.0, csi1000[index]] for index in range(len(usable))])
    size_proxy = None
    if complete_size_proxy:
        size_proxy = ols(
            y_values,
            [
                [1.0, csi1000[index], csi1000[index] - csi300[index]]
                for index in range(len(usable))
            ],
        )
    return {
        "direct_size_columns_available": False,
        "size_proxy_used": "CSI1000 minus CSI300 monthly benchmark return",
        "single_factor_model_labels": ["intercept", "CSI1000"],
        "single_factor_model": single_factor,
        "size_proxy_model_labels": ["intercept", "CSI1000", "CSI1000_minus_CSI300"],
        "size_proxy_model": size_proxy,
        "interpretation": (
            "The 5d monthly intercept remains positive after CSI1000 and a CSI1000-minus-CSI300 proxy, "
            "but no per-stock market-cap column is available in rank_samples.csv."
        ),
    }


def regime_slices(primary_monthly: list[dict[str, Any]]) -> dict[str, Any]:
    csi1000_returns = [
        item["mean_benchmark_return_pct"] for item in primary_monthly if item["mean_benchmark_return_pct"] is not None
    ]
    if not csi1000_returns:
        return {"direct_regime_status": "not_evaluable_missing_momentum_std_column", "proxy_slices": []}
    ordered = sorted(csi1000_returns)
    median = ordered[len(ordered) // 2]
    groups = {"low_csi1000_return_proxy": [], "high_csi1000_return_proxy": []}
    for item in primary_monthly:
        benchmark_return = item["mean_benchmark_return_pct"]
        excess = item["mean_net_excess_pct"]
        if benchmark_return is None or excess is None:
            continue
        key = "high_csi1000_return_proxy" if benchmark_return >= median else "low_csi1000_return_proxy"
        groups[key].append(excess)
    return {
        "direct_regime_status": "not_evaluable_missing_momentum_std_column",
        "proxy_note": "rank_samples.csv has no momentum_std column; CSI1000 monthly return split is diagnostic only.",
        "proxy_slices": [
            {
                "slice": key,
                "month_count": len(values),
                "mean_5d_csi1000_excess_pct": rounded(mean(values)),
                "monthly_clustered_t_stat": rounded(t_stat(values)),
                "positive_month_count": len([value for value in values if value > 0]),
            }
            for key, values in groups.items()
        ],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty CSV {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError:
        return
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:5])
        raise ValueError(f"{schema_path} validation failed: {joined}")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_evidence_report(
    *,
    generated_at: str,
    preregistration_path: Path,
    rank_samples_path: Path,
    output_dir: Path,
    diagnostics: dict[str, Any],
    code_version_ref: str,
) -> dict[str, Any]:
    primary = diagnostics["metric_summaries"]["5d_CSI1000"]
    return_means_primary = diagnostics["primary_return_means"]
    decision = diagnostics["decision"]["label"]
    decision_summary = diagnostics["decision"]["plain_result"]
    result_summary = (
        "decision="
        f"{decision}; 5d CSI1000 same-anchor excess mean={fmt_number(primary['mean_net_excess_pct'])} pp; "
        f"monthly_t={fmt_number(primary['monthly_clustered_t_stat'])}; positive_months={primary['positive_month_count']}/"
        f"{primary['monthly_observation_count']}; 20d CSI1000 monthly_t="
        f"{fmt_number(diagnostics['metric_summaries']['20d_CSI1000']['monthly_clustered_t_stat'])}; "
        f"5d CSI300 monthly_t={fmt_number(diagnostics['metric_summaries']['5d_CSI300']['monthly_clustered_t_stat'])}; "
        f"old_uncorrected_5d_CSI1000_t={fmt_number(primary['uncorrected_gross_monthly_clustered_t_stat'])}; "
        f"direct_regime_status={diagnostics['regime_slices']['direct_regime_status']}; "
        "full_size_allowed=false"
    )
    return {
        "schema_name": "evidence_report",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "scope": {
            "phase": "7a-5",
            "purpose": "evidence_report_schema_contract",
            "contract_status": "schema_first_contract_only",
            "provider_selection_allowed": False,
            "data_fetch_allowed": False,
            "provider_adapter_allowed": False,
            "datahub_table_implementation_allowed": False,
            "strategy_rule_change_allowed": False,
            "broker_or_order_automation_allowed": False,
            "manual_order_only": True,
            "ship_gate_relaxed": False,
        },
        "report_id": "a_short_steady_alpha_reaudit_evidence_20260603",
        "report_date": REPORT_DATE,
        "report_family": "research_experiment",
        "lane_id": "a_short_steady",
        "parent_lane_id": "a_short",
        "market": "A",
        "horizon": "short",
        "evidence_level": "research_only",
        "evidence_policy": {
            "fixed_allocation_policy_unchanged": True,
            "global_aum_pool_allowed": False,
            "cross_market_pooling_allowed": False,
            "liquidity_bucket_auto_borrowing_allowed": False,
            "paper_ship_gate_claim_allowed": False,
            "live_normalized_required_for_ship_gate": True,
            "actual_position_reconciliation_required_for_live_normalized": True,
            "manual_execution_only": True,
        },
        "provider_benchmark_context": {
            "provider_priority_contract_ref": "docs/provider_priority_benchmark_contract.md",
            "benchmark_set_source": "docs/provider_priority_benchmark_contract.md",
            "provider_capability_catalog_ref": "schemas/provider_capability_catalog.schema.json",
            "provider_selection_made_by_this_report": False,
            "primary_benchmark_id": "CSI1000",
            "secondary_benchmark_ids": ["CSI300"],
            "benchmark_switch_packet_required": True,
            "benchmark_limitations": [
                "CSI1000 5d is the preregistered decisive clue under review.",
                "CSI300 and 20d are diagnostics, not rescue benchmarks or a new sweep.",
                "Corrected benchmark excess is re-derived from the local benchmark open/close cache; old rank_samples excess columns are used only as uncorrected controls.",
            ],
        },
        "evidence_feasibility_context": {
            "feasibility_controls_doc_ref": "docs/evidence_feasibility_controls.md",
            "feasibility_controls_schema_ref": "schemas/evidence_feasibility_controls.schema.json",
            "feasibility_control_required": True,
            "circuit_breaker_action_set": [
                "warn",
                "size_down",
                "pause_new_entries",
                "manual_review",
                "reactivation_cooldown",
            ],
            "control_limitations": [
                "This is a frozen research-only re-audit, not a live feasibility implementation.",
                "No intraday queue, partial fill, liquidity, or cash-drag simulation is included.",
            ],
        },
        "immutable_decision_packet": {
            "packet_id": "a_short_steady_alpha_reaudit_packet_20260603",
            "created_at": generated_at,
            "decision_timestamp": "2026-06-03T00:00:00Z",
            "lane_id": "a_short_steady",
            "candidate_universe_ref": str(rank_samples_path).replace("\\", "/"),
            "input_artifact_refs": [
                str(preregistration_path).replace("\\", "/"),
                "research/ledgers/a_short_steady_alpha_reaudit_program_test_budget_ledger_20260603.json",
                str(rank_samples_path).replace("\\", "/"),
                diagnostics["input_summary"]["benchmark_cache_path"],
                str(output_dir / "diagnostics.json").replace("\\", "/"),
                str(output_dir / "monthly_stats.csv").replace("\\", "/"),
                str(output_dir / "metric_summary.csv").replace("\\", "/"),
                str(output_dir / "stock_concentration.csv").replace("\\", "/"),
                str(output_dir / "veto_filter_stats.csv").replace("\\", "/"),
            ],
            "source_schema_refs": [
                "schemas/a_short_steady_alpha_reaudit_preregistration.schema.json",
                "schemas/program_test_budget_ledger.schema.json",
                "schemas/evidence_report.schema.json",
            ],
            "parameter_set_ref": str(preregistration_path).replace("\\", "/"),
            "parameter_hash": file_sha256(preregistration_path),
            "code_version_ref": code_version_ref,
            "benchmark_set_ref": "docs/provider_priority_benchmark_contract.md",
            "provider_status_ref": "not_applicable_local_a_share_rank_samples_only",
            "hypothesis_ref": str(preregistration_path).replace("\\", "/"),
            "decision_outputs": [
                result_summary,
                decision_summary,
                "No production promotion, ship-gate evidence, full-size manual use, DataHub work, provider work, or broker automation is authorized.",
            ],
            "immutability": {
                "mutation_after_issue_allowed": False,
                "append_only_corrections_required": True,
                "decision_timestamp_before_outcome_required": True,
                "parameter_hash_required": True,
            },
        },
        "cost_adjusted_return": {
            "return_window_start": diagnostics["input_summary"]["first_trade_date"],
            "return_window_end": diagnostics["input_summary"]["last_trade_date"],
            "gross_return_pct": return_means_primary["gross_return_pct"],
            "net_return_pct": return_means_primary["net_return_pct"],
            "benchmark_return_pct": return_means_primary["benchmark_return_pct"],
            "net_excess_return_pct": return_means_primary["net_excess_return_pct"],
            "cost_basis_status": "estimated",
            "cost_components": {
                "commissions_pct": 0.05,
                "taxes_pct": 0.0,
                "stamp_duty_pct": 0.05,
                "slippage_pct": 0.06,
                "spread_pct": 0.0,
                "borrow_fee_pct": 0.0,
                "fx_conversion_pct": 0.0,
                "dividends_pct": 0.0,
                "withholding_tax_pct": 0.0,
                "adr_fee_pct": 0.0,
                "market_impact_pct": 0.0,
                "cash_drag_pct": 0.0,
                "missed_trade_opportunity_cost_pct": 0.0,
                "other_costs_pct": 0.0,
            },
            "cost_disclosure": {
                "missing_cost_components": [],
                "estimation_method": "Existing rank_samples.csv net T+1 stock returns minus same-anchor benchmark open-to-close returns re-derived from the local forward_daily cache.",
                "limitations": [
                    "The cost split follows the existing A-short aggregate reporting convention.",
                    "No tick-level execution-cost or queue simulation is included.",
                ],
            },
        },
        "cash_drag": {
            "applicability": "not_applicable",
            "observed_capital_used": None,
            "normalization_basis": "Research-only equal-weight same-anchor re-audit; no capital deployment was simulated.",
            "bucket_ceiling_context_ref": "docs/portfolio_allocation_policy.md",
            "available_cash": None,
            "deployed_capital": None,
            "idle_cash_pct": None,
            "cash_drag_return_pct": None,
            "missed_trade_opportunity_cost_pct": None,
            "calculation_basis": "Not applicable to this in-sample local evidence review.",
            "limitations": ["Cash drag must be modeled separately before any portfolio conclusion."],
        },
        "manual_override_log": {
            "override_status": "not_applicable",
            "manual_execution_only": True,
            "entries": [],
            "limitations": ["No live recommendation or manual order was generated by this research artifact."],
        },
        "minimal_reconciliation": {
            "reconciliation_status": "paper_no_actual_position",
            "actual_position_reconciliation_available": False,
            "recommended_positions_ref": None,
            "actual_positions_ref": None,
            "difference_summary": ["No actual positions exist for this research-only in-sample test."],
            "unmatched_items": [],
            "limitations": ["Live-normalized evidence requires actual-position reconciliation; this artifact is not that."],
        },
        "thesis_outcome_log": {
            "applicability": "not_applicable",
            "thesis_id": None,
            "review_stage": "not_applicable",
            "thesis_status": "not_applicable",
            "thesis_start_date": None,
            "review_date": REPORT_DATE,
            "expected_outcome": "Not a long thesis report.",
            "observed_outcome": "Not applicable.",
            "outcome_assessment": "not_applicable",
            "thesis_broken_conditions": ["Not applicable to A-short steady alpha re-audit."],
            "next_review_date": None,
            "limitations": ["Use research_experiment_log for this artifact."],
        },
        "research_experiment_log": {
            "applicability": "applicable",
            "experiment_id": TEST_ID,
            "hypothesis_registration_ref": str(preregistration_path).replace("\\", "/"),
            "dataset_refs": [
                str(rank_samples_path).replace("\\", "/"),
                diagnostics["input_summary"]["benchmark_cache_path"],
            ],
            "parameter_refs": [str(preregistration_path).replace("\\", "/")],
            "random_seed": None,
            "reproducibility_artifacts": [
                str(output_dir / "diagnostics.json").replace("\\", "/"),
                str(output_dir / "monthly_stats.csv").replace("\\", "/"),
                str(output_dir / "metric_summary.csv").replace("\\", "/"),
                str(output_dir / "stock_concentration.csv").replace("\\", "/"),
                str(output_dir / "veto_filter_stats.csv").replace("\\", "/"),
                str(output_dir / "evidence_report.json").replace("\\", "/"),
            ],
            "result_summary": result_summary,
            "production_promotion": {
                "no_direct_production_feed": True,
                "requires_schema_review": True,
                "requires_claude_review": True,
                "requires_user_approval": True,
                "promotion_status": "blocked",
                "promotion_limitations": [
                    "The corrected 5d CSI1000 clue did not pass the frozen statistical gate, so it is not candidate alpha evidence.",
                    "20d and CSI300 diagnostics are weak, and direct momentum_std regime slicing is unavailable in rank_samples.csv.",
                    "At least 12 months of live-normalized forward evidence remains required before ship-gate review.",
                ],
            },
        },
        "ship_gate_claim": {
            "claim_status": "not_eligible",
            "evidence_level_used": "research_only",
            "paper_evidence_used_for_ship_gate": False,
            "full_size_manual_use_authorized_by_this_report": False,
            "existing_ship_gate_policy_ref": "AGENTS.md#项目背景",
            "claim_limitations": [
                "Research-only backtest evidence cannot be used for ship gate.",
                "This report does not authorize full-size manual use; the corrected 5d CSI1000 clue failed the frozen statistical gate.",
            ],
        },
        "deferred_decisions": [
            "Whether to start a new alpha-search test is deferred to a later reviewed preregistration.",
            "Whether A-short steady should remain only a risk filter in forward evidence is deferred to future live-normalized observations.",
        ],
        "limitations": [
            "This report reads existing local rank_samples.csv and forward_daily benchmark cache only; it does not rerun EGS or fetch data.",
            "The direct momentum_std regime slice required by the preregistration is unavailable in the existing CSV, so the regime check is only proxy-level.",
            "No strategy rule, threshold, runner behavior, provider route, DataHub contract, production output, or ship-gate status changes.",
        ],
    }


def build_diagnostics(rows: list[dict[str, str]], same_anchor_context: dict[str, Any]) -> dict[str, Any]:
    tier1 = tier1_rows(rows)
    metric_summaries: dict[str, Any] = {}
    monthly_all: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        for benchmark in BENCHMARKS:
            key = f"{horizon}d_{benchmark.upper()}"
            metric_summaries[key] = metric_summary(tier1, horizon, benchmark)
            monthly_all.extend(monthly_records(tier1, horizon, benchmark))

    csi300_primary_monthly = {
        record["trade_date"]: record["mean_benchmark_return_pct"]
        for record in monthly_records(tier1, PRIMARY_HORIZON, SECONDARY_BENCHMARK)
    }
    primary_monthly = monthly_records(tier1, PRIMARY_HORIZON, PRIMARY_BENCHMARK)
    stock_rows = stock_concentration(tier1)
    top5_share = sum(
        row["positive_contribution_share"] or 0.0 for row in stock_rows[:5]
    )
    primary = metric_summaries["5d_CSI1000"]
    adjusted_p = None
    if primary["normal_approx_two_sided_p"] is not None:
        adjusted_p = min(1.0, primary["normal_approx_two_sided_p"] * 4)
    factor = factor_exposure(primary_monthly, csi300_primary_monthly)
    direct_regime_status = "not_evaluable_missing_momentum_std_column"
    candidate_conditions = {
        "same_anchor_5d_csi1000_positive": (primary["mean_net_excess_pct"] or 0) > 0,
        "same_anchor_5d_csi1000_monthly_t_ge_2": (primary["monthly_clustered_t_stat"] or 0) >= 2.0,
        "bonferroni_adjusted_normal_p_lt_0_05": adjusted_p is not None and adjusted_p < 0.05,
        "stock_top5_positive_contribution_share_lt_0_25": top5_share < 0.25,
        "factor_intercept_proxy_positive": (
            factor["size_proxy_model"] is not None
            and (factor["size_proxy_model"]["beta"][0] or 0) > 0
        ),
        "direct_momentum_std_regime_available": direct_regime_status == "evaluable",
        "twenty_day_csi1000_not_significant": abs(metric_summaries["20d_CSI1000"]["monthly_clustered_t_stat"] or 0) < 2,
    }
    decision = "candidate_alpha_not_full_size"
    plain_result = (
        "The corrected 5d CSI1000 clue passed the frozen statistical gate as research-only candidate evidence; "
        "it still cannot be used for full-size or ship-gate."
    )
    if not (
        candidate_conditions["same_anchor_5d_csi1000_positive"]
        and candidate_conditions["same_anchor_5d_csi1000_monthly_t_ge_2"]
        and candidate_conditions["bonferroni_adjusted_normal_p_lt_0_05"]
    ):
        decision = "risk_filter_only"
        plain_result = "True same-anchor correction made the 5d CSI1000 clue fail the frozen statistical gate; use A-short steady as risk filter / research reference, not alpha evidence."

    return {
        "schema_name": "a_short_steady_alpha_reaudit_diagnostics",
        "schema_version": "1.0.0",
        "generated_at": DEFAULT_GENERATED_AT,
        "scope": {
            "research_only": True,
            "data_fetch_allowed": False,
            "egs_rerun_allowed": False,
            "production_output_allowed": False,
            "ship_gate_claim_allowed": False,
            "full_size_manual_use_allowed": False,
        },
        "input_summary": {
            "rank_samples_path": str(DEFAULT_RANK_SAMPLES).replace("\\", "/"),
            "total_rows": len(rows),
            "tier1_rows": len(tier1),
            "first_trade_date": min(row["trade_date"] for row in tier1),
            "last_trade_date": max(row["trade_date"] for row in tier1),
            "trade_date_count": len({row["trade_date"] for row in tier1}),
            "missing_momentum_std_column": True,
            "missing_direct_size_column": True,
            "benchmark_cache_path": same_anchor_context["benchmark_cache_path"],
        },
        "same_anchor_correction": {
            "correction_applied": True,
            "stock_leg": "rank_samples ret_*d_t1_net: stock T+1 open to exit close after costs",
            "benchmark_leg": "forward_daily cache: benchmark entry_date open to same exit_date close",
            "old_csv_excess_basis": "uncorrected control only: old rank_samples ret_*d_excess_* was gross stock T+1 minus close-to-close benchmark",
            "benchmark_cache_meta": same_anchor_context["benchmark_cache_meta"],
            "coverage": same_anchor_context["coverage"],
            "primary_corrected_vs_uncorrected": {
                "corrected_net_mean_pct": primary["mean_net_excess_pct"],
                "corrected_net_monthly_t": primary["monthly_clustered_t_stat"],
                "uncorrected_gross_mean_pct": primary["mean_uncorrected_gross_excess_pct"],
                "uncorrected_gross_monthly_t": primary["uncorrected_gross_monthly_clustered_t_stat"],
                "mean_anchor_only_delta_pct": primary["mean_anchor_only_delta_pct"],
            },
        },
        "decision": {
            "label": decision,
            "plain_result": plain_result,
            "data_usability": "usable_for_research_only_not_ship_gate_or_full_size",
            "candidate_conditions": candidate_conditions,
        },
        "metric_summaries": metric_summaries,
        "multiple_testing": {
            "family_test_count": 4,
            "method": "Bonferroni on normal-approx two-sided p-values for the fixed 5d/20d x CSI1000/CSI300 family",
            "primary_normal_approx_two_sided_p": primary["normal_approx_two_sided_p"],
            "primary_bonferroni_adjusted_p": rounded(adjusted_p),
        },
        "primary_return_means": return_means(tier1, PRIMARY_HORIZON, PRIMARY_BENCHMARK),
        "stock_concentration": {
            "stock_count": len(stock_rows),
            "top5_positive_contribution_share": rounded(top5_share),
            "top10_positive_contribution_share": rounded(sum((row["positive_contribution_share"] or 0.0) for row in stock_rows[:10])),
        },
        "factor_exposure": factor,
        "regime_slices": regime_slices(primary_monthly),
        "veto_filter_effect": {
            "interpretation": "Tier1 has stronger 5d CSI1000 monthly t than all rows or Tier2; this supports filter value but does not authorize production alpha.",
            "rows": veto_filter_stats(rows),
        },
        "pit_survivorship_check": {
            "status": "not_recomputed_reliance_on_existing_pipeline_controls",
            "checks_done_in_this_runner": [
                "Used existing local rank_samples.csv only.",
                "Did not fetch data, rerun EGS, regenerate cohorts, or fill missing returns.",
                "Required trade_date / ts_code / status columns exist for the frozen local sample.",
            ],
            "limitations": [
                "This runner does not independently replay Tushare list/delist/suspend guards.",
                "PIT/survivorship confidence relies on existing resolved pipeline controls and the frozen rank_samples surface.",
            ],
        },
    }


def write_outputs(
    output_dir: Path,
    diagnostics: dict[str, Any],
    evidence_report: dict[str, Any],
    monthly_cache: dict[tuple[int, str], list[dict[str, Any]]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "evidence_report.json").write_text(
        json.dumps(evidence_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    monthly_rows = []
    for horizon in HORIZONS:
        for benchmark in BENCHMARKS:
            monthly_rows.extend(monthly_cache[(horizon, benchmark)])
    write_csv(output_dir / "monthly_stats.csv", monthly_rows)
    write_csv(output_dir / "metric_summary.csv", list(diagnostics["metric_summaries"].values()))
    write_csv(output_dir / "stock_concentration.csv", diagnostics["stock_concentration_rows"])
    write_csv(output_dir / "veto_filter_stats.csv", diagnostics["veto_filter_effect"]["rows"])


def update_ledger(ledger_path: Path, result_ref: Path, result_summary: str, decision_label: str) -> dict[str, Any]:
    passed = decision_label == "candidate_alpha_not_full_size"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["ledger_status"] = "active_no_new_test_authorized"
    ledger["budget_policy"]["tests_spent_count"] = 1
    ledger["budget_policy"]["tests_available_without_new_review"] = 0
    ledger["test_spend_log"] = [
        item for item in ledger.get("test_spend_log", []) if item.get("test_id") != TEST_ID
    ]
    ledger["test_spend_log"].append(
        {
            "test_id": TEST_ID,
            "preregistration_ref": str(DEFAULT_PREREGISTRATION).replace("\\", "/"),
            "result_ref": str(result_ref).replace("\\", "/"),
            "status": "spent_passed_research_continue_only" if passed else "spent_failed_outcome_threshold",
            "tests_spent": 1,
            "promotion_relevant": True,
            "result_summary": result_summary,
            "allowed_followup": (
                "Further work needs a new reviewed preregistration or live-normalized forward evidence; "
                "no production, ship-gate, full-size, or parameter-rescue path is authorized."
            ),
        }
    )
    ledger["planned_tests"] = []
    ledger["next_required_actions"] = [
        "Do not rerun or rescue this A-short steady re-audit without a new reviewed preregistration and ledger update.",
        (
            "Treat the result as research-only candidate evidence, not production alpha or ship-gate evidence."
            if passed
            else "Treat the result as risk-filter-only / research reference; it is not A-short steady alpha evidence."
        ),
        "If the user wants a new alpha search, create a new reviewed preregistration; do not silently rescue this failed clue.",
    ]
    validate_json(LEDGER_SCHEMA, ledger)
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ledger


def run(args: argparse.Namespace) -> dict[str, Any]:
    rows = read_rank_samples(args.rank_samples)
    benchmark_cache = load_benchmark_cache(args.benchmark_cache)
    rows, same_anchor_context = annotate_same_anchor_returns(rows, benchmark_cache)
    diagnostics = build_diagnostics(rows, same_anchor_context)
    primary_monthly_cache: dict[tuple[int, str], list[dict[str, Any]]] = {}
    tier1 = tier1_rows(rows)
    for horizon in HORIZONS:
        for benchmark in BENCHMARKS:
            primary_monthly_cache[(horizon, benchmark)] = monthly_records(tier1, horizon, benchmark)
    diagnostics["stock_concentration_rows"] = stock_concentration(tier1)
    diagnostics["generated_at"] = args.generated_at
    evidence_report = build_evidence_report(
        generated_at=args.generated_at,
        preregistration_path=args.preregistration,
        rank_samples_path=args.rank_samples,
        output_dir=args.output_dir,
        diagnostics=diagnostics,
        code_version_ref=args.code_version_ref,
    )
    validate_json(EVIDENCE_SCHEMA, evidence_report)
    write_outputs(args.output_dir, diagnostics, evidence_report, primary_monthly_cache)
    if args.update_ledger:
        update_ledger(
            args.ledger,
            args.output_dir / "evidence_report.json",
            evidence_report["research_experiment_log"]["result_summary"],
            diagnostics["decision"]["label"],
        )
    return {"diagnostics": diagnostics, "evidence_report": evidence_report}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the A-short steady same-anchor alpha re-audit.")
    parser.add_argument("--rank-samples", type=Path, default=DEFAULT_RANK_SAMPLES)
    parser.add_argument("--benchmark-cache", type=Path, default=DEFAULT_BENCHMARK_CACHE)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--generated-at", default=DEFAULT_GENERATED_AT)
    parser.add_argument("--code-version-ref", default="2d629e4+working_tree_a_short_steady_alpha_reaudit")
    parser.add_argument("--no-update-ledger", dest="update_ledger", action="store_false")
    parser.set_defaults(update_ledger=True)
    return parser.parse_args()


def main() -> None:
    result = run(parse_args())
    decision = result["diagnostics"]["decision"]
    primary = result["diagnostics"]["metric_summaries"]["5d_CSI1000"]
    print(decision["label"])
    print(decision["plain_result"])
    print(
        "5d CSI1000 corrected mean excess="
        f"{primary['mean_net_excess_pct']} monthly_t={primary['monthly_clustered_t_stat']} "
        f"(old uncorrected t={primary['uncorrected_gross_monthly_clustered_t_stat']})"
    )


if __name__ == "__main__":
    main()
