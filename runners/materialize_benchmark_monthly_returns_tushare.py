from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.backtest_execution import iso_now
from runners.materialize_execution_price_data_tushare import ts_call, tushare_pro


DEFAULT_OUT_DIR = ROOT / "result" / "a_short" / "backtest" / "execution" / "forward_aggregate"
API_FAMILIES = ["index_daily", "tushare_provider"]
MONTHLY_RETURN_METHOD = "first_trade_day_open_to_last_trade_day_close"
BENCHMARKS = {
    "csi1000": {
        "ts_code": "000852.SH",
        "role": "primary",
        "source": "tushare:index_daily/000852.SH",
    },
    "csi300": {
        "ts_code": "000300.SH",
        "role": "secondary",
        "source": "tushare:index_daily/000300.SH",
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize Phase 6 A-short benchmark monthly return JSON files "
            "from Tushare index_daily. Output return files are directly usable "
            "by aggregate_execution_reports.py --benchmark-monthly-returns."
        )
    )
    parser.add_argument("--start-date", required=True, help="Start date in YYYYMMDD form.")
    parser.add_argument("--end-date", required=True, help="End date in YYYYMMDD form.")
    parser.add_argument(
        "--benchmark",
        action="append",
        choices=sorted(BENCHMARKS),
        help="Benchmark to materialize. May be repeated. Defaults to csi1000 and csi300.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Output directory for benchmark_monthly_returns_<benchmark>.json files.",
    )
    parser.add_argument(
        "--generated-at",
        help="Optional deterministic generated_at timestamp for metadata tests or replay.",
    )
    return parser.parse_args(argv)


def selected_benchmarks(values: list[str] | None) -> list[str]:
    if not values:
        return ["csi1000", "csi300"]
    selected: list[str] = []
    for value in values:
        if value not in selected:
            selected.append(value)
    return selected


def validate_date_range(start_date: str, end_date: str) -> None:
    if len(start_date) != 8 or not start_date.isdigit():
        raise ValueError(f"start_date must be YYYYMMDD: {start_date!r}")
    if len(end_date) != 8 or not end_date.isdigit():
        raise ValueError(f"end_date must be YYYYMMDD: {end_date!r}")
    if start_date > end_date:
        raise ValueError(f"start_date must be <= end_date: {start_date}..{end_date}")


def fetch_index_daily(pro: Any, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    frame = ts_call(
        pro.index_daily,
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
        fields="ts_code,trade_date,open,close",
    )
    if frame is None:
        return pd.DataFrame()
    return frame


def normalized_index_rows(frame: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    required = {"trade_date", "open", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"index_daily missing required columns: {', '.join(missing)}")
    if frame.empty:
        raise ValueError(f"index_daily returned no rows for {start_date}..{end_date}")

    normalized = frame.copy()
    normalized["trade_date"] = normalized["trade_date"].astype(str)
    for col in ["open", "close"]:
        normalized[col] = pd.to_numeric(normalized[col], errors="coerce")
    normalized = normalized[
        (normalized["trade_date"] >= start_date)
        & (normalized["trade_date"] <= end_date)
    ]
    normalized = normalized.dropna(subset=["open", "close"])
    if normalized.empty:
        raise ValueError(f"index_daily returned no numeric open/close rows for {start_date}..{end_date}")
    if (normalized[["open", "close"]] <= 0).any().any():
        raise ValueError("index_daily open/close values must be positive")
    normalized = normalized.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    return normalized


def monthly_returns_from_rows(rows: pd.DataFrame) -> tuple[dict[str, float], list[dict[str, Any]], list[dict[str, Any]]]:
    returns: dict[str, float] = {}
    month_rows: list[dict[str, Any]] = []
    skipped_months: list[dict[str, Any]] = []
    for month, group in rows.groupby(rows["trade_date"].str[:6], sort=True):
        ordered = group.sort_values("trade_date")
        if len(ordered) < 2:
            skipped_months.append(
                {
                    "month": str(month),
                    "row_count": int(len(ordered)),
                    "reason": "requires at least two index_daily rows",
                }
            )
            continue
        first = ordered.iloc[0]
        last = ordered.iloc[-1]
        first_open = float(first["open"])
        first_close = float(first["close"])
        last_close = float(last["close"])
        if first_open <= 0:
            raise ValueError(f"benchmark month {month} first open must be positive")
        monthly_return = last_close / first_open - 1.0
        returns[str(month)] = round(monthly_return, 10)
        month_rows.append(
            {
                "month": str(month),
                "first_trade_date": str(first["trade_date"]),
                "last_trade_date": str(last["trade_date"]),
                "first_open": first_open,
                "first_close": first_close,
                "last_close": last_close,
                "return": round(monthly_return, 10),
            }
        )
    if not returns:
        raise ValueError("benchmark monthly returns require at least one month with two index_daily rows")
    return returns, month_rows, skipped_months


def build_benchmark_payload(
    pro: Any,
    benchmark: str,
    start_date: str,
    end_date: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    validate_date_range(start_date, end_date)
    spec = BENCHMARKS[benchmark]
    rows = normalized_index_rows(
        fetch_index_daily(pro, str(spec["ts_code"]), start_date, end_date),
        start_date,
        end_date,
    )
    returns, month_rows, skipped_months = monthly_returns_from_rows(rows)
    return {
        "returns": returns,
        "metadata": {
            "schema_name": "benchmark_monthly_returns_metadata",
            "schema_version": "1.0.0",
            "generated_at": generated_at or iso_now(),
            "benchmark": benchmark,
            "role": spec["role"],
            "ts_code": spec["ts_code"],
            "source": spec["source"],
            "api_families": API_FAMILIES,
            "date_range": {"start_date": start_date, "end_date": end_date},
            "monthly_return_method": MONTHLY_RETURN_METHOD,
            "months": month_rows,
            "skipped_months": skipped_months,
            "limitations": [
                "Return JSON is a plain YYYYMM -> return object for aggregate_execution_reports.py compatibility.",
                "Monthly return uses the first available index_daily open and last available index_daily close within each month in the requested date range.",
                "Boundary months with fewer than two usable index_daily rows are omitted and listed in skipped_months.",
                "Per-candidate corrected revalidation uses runners/backtest_rank.py same-anchor benchmark T+1 open to exit close; this monthly file is for execution aggregate compatibility.",
                "CSI1000 is the Phase 6a primary A-short benchmark; CSI300 is mandatory secondary sensitivity.",
            ],
        },
    }


def return_output_path(out_dir: Path, benchmark: str) -> Path:
    return out_dir / f"benchmark_monthly_returns_{benchmark}.json"


def metadata_output_path(out_dir: Path, benchmark: str) -> Path:
    return out_dir / f"benchmark_monthly_returns_{benchmark}_metadata.json"


def write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_outputs(payload: dict[str, Any], out_dir: Path, benchmark: str) -> tuple[Path, Path]:
    returns_path = return_output_path(out_dir, benchmark)
    metadata_path = metadata_output_path(out_dir, benchmark)
    write_json(payload["returns"], returns_path)
    write_json(payload["metadata"], metadata_path)
    return returns_path, metadata_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pro = tushare_pro()
    for benchmark in selected_benchmarks(args.benchmark):
        payload = build_benchmark_payload(
            pro,
            benchmark=benchmark,
            start_date=args.start_date,
            end_date=args.end_date,
            generated_at=args.generated_at,
        )
        returns_path, metadata_path = write_outputs(payload, args.out_dir, benchmark)
        print(f"[OK] wrote {returns_path}")
        print(f"[OK] wrote {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
