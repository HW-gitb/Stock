from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.backtest_rank import BENCHMARKS, BENCHMARK_RETURN_BASIS, FORWARD_DAILY_CACHE
from runners.materialize_benchmark_monthly_returns_tushare import (
    fetch_index_daily,
    normalized_index_rows,
)
from runners.materialize_execution_price_data_tushare import tushare_pro

API_FAMILIES = ["index_daily", "tushare_provider"]
CACHE_UPDATE_METHOD = "benchmark_only_index_daily_open_close_patch"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh only the benchmark frames inside the shared forward_daily.pkl "
            "cache. This fetches CSI300/CSI1000 index_daily open/close and does not "
            "refresh stock daily, adj_factor, stk_limit, or trade_cal payloads."
        )
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=FORWARD_DAILY_CACHE,
        help="Path to the shared forward_daily.pkl cache.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate benchmark frames but do not write the cache.",
    )
    parser.add_argument(
        "--generated-at",
        help="Optional deterministic timestamp for tests / replay metadata.",
    )
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_cache(cache_path: Path) -> dict[str, Any]:
    if not cache_path.exists():
        raise FileNotFoundError(f"forward_daily cache not found: {cache_path}")
    with cache_path.open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("forward_daily cache payload must be a dict")
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("forward_daily cache missing meta dict")
    for key in ["start_date", "end_date"]:
        value = str(meta.get(key, ""))
        if len(value) != 8 or not value.isdigit():
            raise ValueError(f"forward_daily cache meta.{key} must be YYYYMMDD")
    if not isinstance(payload.get("stocks"), pd.DataFrame) or payload["stocks"].empty:
        raise ValueError("forward_daily cache missing non-empty stocks DataFrame")
    if not isinstance(payload.get("limits"), pd.DataFrame) or payload["limits"].empty:
        raise ValueError("forward_daily cache missing non-empty limits DataFrame")
    return payload


def fetch_benchmark_frames(pro: Any, start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for name, ts_code in BENCHMARKS.items():
        rows = normalized_index_rows(
            fetch_index_daily(pro, ts_code, start_date, end_date),
            start_date,
            end_date,
        )
        frames[name] = rows[["trade_date", "open", "close"]].reset_index(drop=True)
    return frames


def benchmark_frame_summary(name: str, ts_code: str, frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "benchmark": name,
        "ts_code": ts_code,
        "source": f"tushare:index_daily/{ts_code}",
        "fields": ["trade_date", "open", "close"],
        "rows": int(len(frame)),
        "first_trade_date": str(frame["trade_date"].iloc[0]),
        "last_trade_date": str(frame["trade_date"].iloc[-1]),
    }


def atomic_write_pickle(payload: dict[str, Any], cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_name(f"{cache_path.name}.tmp")
    with tmp_path.open("wb") as handle:
        pickle.dump(payload, handle)
    tmp_path.replace(cache_path)


def refresh_forward_daily_benchmark_open(
    pro: Any,
    cache_path: Path = FORWARD_DAILY_CACHE,
    dry_run: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    cached = load_cache(cache_path)
    meta = dict(cached["meta"])
    start_date = str(meta["start_date"])
    end_date = str(meta["end_date"])
    generated_at = generated_at or iso_now()

    frames = fetch_benchmark_frames(pro, start_date, end_date)
    benchmark_summaries = [
        benchmark_frame_summary(name, ts_code, frames[name])
        for name, ts_code in BENCHMARKS.items()
    ]

    patched = dict(cached)
    patched["benchmarks"] = frames
    meta["benchmarks"] = list(BENCHMARKS.keys())
    meta["benchmark_return_basis"] = BENCHMARK_RETURN_BASIS
    meta["benchmark_open_patch"] = {
        "schema_name": "forward_daily_benchmark_open_cache_patch",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "update_method": CACHE_UPDATE_METHOD,
        "api_families": API_FAMILIES,
        "date_range": {"start_date": start_date, "end_date": end_date},
        "stock_daily_refetch_allowed": False,
        "limit_refetch_allowed": False,
        "benchmarks": benchmark_summaries,
    }
    patched["meta"] = meta

    if not dry_run:
        atomic_write_pickle(patched, cache_path)

    return {
        "cache_path": str(cache_path),
        "dry_run": bool(dry_run),
        "date_range": {"start_date": start_date, "end_date": end_date},
        "update_method": CACHE_UPDATE_METHOD,
        "benchmark_return_basis": BENCHMARK_RETURN_BASIS,
        "stock_rows_preserved": int(len(cached["stocks"])),
        "limit_rows_preserved": int(len(cached["limits"])),
        "benchmarks": benchmark_summaries,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = refresh_forward_daily_benchmark_open(
        tushare_pro(),
        cache_path=args.cache_path,
        dry_run=args.dry_run,
        generated_at=args.generated_at,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
