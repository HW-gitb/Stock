from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.backtest_execution import (
    PRICE_DATA_SCHEMA_PATH,
    candidate_code,
    iso_now,
    load_analysis_input,
    validate_json_schema,
)

DEFAULT_INPUT_ROOT = ROOT / "result" / "a_short"
DEFAULT_OUT_DIR = ROOT / "result" / "a_short" / "backtest" / "execution" / "price_data"
DEFAULT_CACHE_DIR = ROOT / "result" / "a_short" / "backtest" / "cache" / "execution_price_data"
TUSHARE_API_FAMILIES = ["daily", "adj_factor", "stk_limit", "trade_cal", "tushare_provider"]
DEFAULT_CALENDAR_DAYS = 30


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize execution_price_data JSON from Tushare daily/adj_factor/"
            "stk_limit/trade_cal. This is a Phase 5 provider-boundary helper; it "
            "does not simulate fills."
        )
    )
    parser.add_argument("--as-of", required=True, help="Candidate trade date in YYYYMMDD form.")
    parser.add_argument(
        "--analysis-input",
        type=Path,
        help="analysis_input.json used to derive symbols. Defaults to result/a_short/<as-of>/analysis_input.json.",
    )
    parser.add_argument(
        "--symbols",
        help="Optional comma-separated ts_code list. Overrides symbols from --analysis-input.",
    )
    parser.add_argument("--start-date", help="Optional date_range.start_date. Defaults to --as-of.")
    parser.add_argument(
        "--end-date",
        help="Optional date_range.end_date. Defaults to --as-of + --calendar-days.",
    )
    parser.add_argument(
        "--calendar-days",
        type=int,
        default=DEFAULT_CALENDAR_DAYS,
        help="Calendar days to add when --end-date is omitted.",
    )
    parser.add_argument(
        "--out-path",
        type=Path,
        help=(
            "Output JSON path. Defaults to "
            "result/a_short/backtest/execution/price_data/execution_price_data_tushare_<as-of>.json."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="Directory for schema-validated provider cache JSON.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore any matching provider cache and refetch from Tushare.",
    )
    return parser.parse_args(argv)


def output_path(as_of: str, out_path: Path | None) -> Path:
    if out_path is not None:
        return out_path
    return DEFAULT_OUT_DIR / f"execution_price_data_tushare_{as_of}.json"


def default_analysis_input_path(as_of: str) -> Path:
    return DEFAULT_INPUT_ROOT / as_of / "analysis_input.json"


def parse_symbols(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    symbols = sorted({item.strip() for item in raw.split(",") if item.strip()})
    if not symbols:
        raise ValueError("--symbols was provided but no non-empty symbol was found")
    return symbols


def symbols_from_analysis_input(path: Path) -> list[str]:
    payload = load_analysis_input(path)
    symbols = sorted(
        {
            candidate_code(candidate)
            for candidate in payload.get("candidates", [])
            if candidate_code(candidate)
        }
    )
    if not symbols:
        raise ValueError(f"analysis_input contains no candidate symbols: {path}")
    return symbols


def resolve_symbols(symbols_arg: str | None, analysis_input_path: Path) -> list[str]:
    symbols = parse_symbols(symbols_arg)
    if symbols is not None:
        return symbols
    return symbols_from_analysis_input(analysis_input_path)


def add_calendar_days(date_str: str, days: int) -> str:
    return (datetime.strptime(date_str, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")


def resolve_date_range(as_of: str, start_date: str | None, end_date: str | None, calendar_days: int) -> tuple[str, str]:
    effective_start = start_date or as_of
    effective_end = end_date or add_calendar_days(as_of, calendar_days)
    if effective_start > effective_end:
        raise ValueError(f"start_date must be <= end_date: {effective_start}..{effective_end}")
    if not (effective_start <= as_of <= effective_end):
        raise ValueError(f"date_range must cover --as-of {as_of}: {effective_start}..{effective_end}")
    return effective_start, effective_end


def _pin_tushare_base_url() -> None:
    from tushare.pro.client import DataApi

    base_url = os.environ.get("TUSHARE_BASE_URL", "https://api.tushare.pro/dataapi")
    attr = "_DataApi__http_url"
    if hasattr(DataApi, attr):
        setattr(DataApi, attr, base_url)
    else:
        raise RuntimeError(
            f"tushare.DataApi has no attribute {attr}; cannot apply TUSHARE_BASE_URL. "
            "Update _pin_tushare_base_url for the installed tushare client version."
        )


def tushare_pro() -> Any:
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for Tushare price materialization")
    import tushare as ts

    _pin_tushare_base_url()
    return ts.pro_api(token)


def _fn_label(fn: Callable[..., Any]) -> str:
    return (
        getattr(fn, "__name__", None)
        or getattr(getattr(fn, "func", None), "__name__", None)
        or repr(fn)
    )


def ts_call(fn: Callable[..., Any], retries: int = 3, base_delay: float = 0.6, **kwargs: Any) -> Any:
    last_err = None
    name = _fn_label(fn)
    for attempt in range(retries):
        try:
            return fn(**kwargs)
        except Exception as exc:  # pragma: no cover - retry path is environment-bound
            last_err = exc
            wait = base_delay * (2**attempt)
            print(f"[RETRY] {name} attempt {attempt + 1} failed ({exc}); sleep {wait:.1f}s")
            time.sleep(wait)
    raise RuntimeError(f"Tushare call {name} failed after {retries} retries: {last_err}")


def trade_calendar(pro: Any, start_date: str, end_date: str) -> list[str]:
    df = ts_call(
        pro.trade_cal,
        exchange="SSE",
        start_date=start_date,
        end_date=end_date,
        is_open="1",
        fields="cal_date",
    )
    if df is None or df.empty:
        raise RuntimeError(f"Tushare trade_cal returned no open dates for {start_date}..{end_date}")
    return sorted(df["cal_date"].astype(str).tolist())


def fetch_symbol_frames(pro: Any, symbol: str, start_date: str, end_date: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily = ts_call(
        pro.daily,
        ts_code=symbol,
        start_date=start_date,
        end_date=end_date,
        fields="ts_code,trade_date,open,high,low,close,pre_close,vol",
    )
    adj = ts_call(
        pro.adj_factor,
        ts_code=symbol,
        start_date=start_date,
        end_date=end_date,
        fields="ts_code,trade_date,adj_factor",
    )
    limit = ts_call(
        pro.stk_limit,
        ts_code=symbol,
        start_date=start_date,
        end_date=end_date,
        fields="ts_code,trade_date,up_limit,down_limit",
    )
    return (
        empty_frame_if_none(daily),
        empty_frame_if_none(adj),
        empty_frame_if_none(limit),
    )


def empty_frame_if_none(value: Any) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    return value


def numeric_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def adjusted_price(value: Any, adj_factor: Any) -> float:
    return float(value) * float(adj_factor)


def adjusted_optional_price(value: Any, adj_factor: Any) -> float | None:
    parsed = numeric_or_none(value)
    if parsed is None:
        return None
    return parsed * float(adj_factor)


def build_rows_for_symbol(
    symbol: str,
    daily: pd.DataFrame,
    adj: pd.DataFrame,
    limit: pd.DataFrame,
    open_dates: set[str],
) -> list[dict[str, Any]]:
    if daily.empty:
        return []
    daily = daily.copy()
    daily["trade_date"] = daily["trade_date"].astype(str)
    daily = daily[daily["trade_date"].isin(open_dates)]
    if daily.empty:
        return []

    adj = adj.copy() if not adj.empty else pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])
    if not adj.empty:
        adj["trade_date"] = adj["trade_date"].astype(str)
    limit = limit.copy() if not limit.empty else pd.DataFrame(columns=["ts_code", "trade_date", "up_limit", "down_limit"])
    if not limit.empty:
        limit["trade_date"] = limit["trade_date"].astype(str)

    merged = daily.merge(adj, on=["ts_code", "trade_date"], how="left")
    merged = merged.merge(limit, on=["ts_code", "trade_date"], how="left")
    merged = merged.sort_values("trade_date").drop_duplicates(["ts_code", "trade_date"], keep="last")

    rows: list[dict[str, Any]] = []
    missing_adj_dates: list[str] = []
    for row in merged.itertuples(index=False):
        adj_factor = getattr(row, "adj_factor")
        if adj_factor is None or pd.isna(adj_factor) or float(adj_factor) <= 0:
            missing_adj_dates.append(str(row.trade_date))
            continue
        rows.append(
            {
                "ts_code": symbol,
                "trade_date": str(row.trade_date),
                "is_trade_day": True,
                "open_qfq": adjusted_price(row.open, adj_factor),
                "high_qfq": adjusted_price(row.high, adj_factor),
                "low_qfq": adjusted_price(row.low, adj_factor),
                "close_qfq": adjusted_price(row.close, adj_factor),
                "pre_close_qfq": adjusted_optional_price(row.pre_close, adj_factor),
                "adj_factor": float(adj_factor),
                "up_limit": adjusted_optional_price(row.up_limit, adj_factor),
                "down_limit": adjusted_optional_price(row.down_limit, adj_factor),
                "volume": numeric_or_none(getattr(row, "vol", None)),
                "source_flags": ["daily", "adj_factor", "stk_limit"],
            }
        )
    if missing_adj_dates:
        raise ValueError(f"Tushare adj_factor missing for {symbol}: {', '.join(missing_adj_dates)}")
    return rows


def build_payload_from_tushare(
    pro: Any,
    symbols: list[str],
    as_of: str,
    start_date: str,
    end_date: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if not symbols:
        raise ValueError("at least one symbol is required")
    open_dates = set(trade_calendar(pro, start_date, end_date))
    if as_of not in open_dates:
        raise ValueError(
            f"--as-of {as_of} is not a trading day per Tushare trade_cal "
            f"{start_date}..{end_date}"
        )
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        daily, adj, limit = fetch_symbol_frames(pro, symbol, start_date, end_date)
        rows.extend(build_rows_for_symbol(symbol, daily, adj, limit, open_dates))

    available_as_of = {row["ts_code"] for row in rows if row["trade_date"] == as_of}
    missing_as_of = sorted(set(symbols) - available_as_of)
    if missing_as_of:
        raise ValueError(
            "Tushare price data must include an --as-of price row for each selected symbol: "
            + ", ".join(missing_as_of)
        )
    return {
        "schema_name": "execution_price_data",
        "schema_version": "1.0.0",
        "generated_at": generated_at or iso_now(),
        "preset": "a_short",
        "data_provider": "tushare",
        "source": {
            "api_families": TUSHARE_API_FAMILIES,
            "adjustment_mode": "qfq_via_adj_factor",
            "price_basis": "daily_eod",
            "calendar_source": "tushare.trade_cal",
            "pit_policy": "trade_date_eod",
        },
        "date_range": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "symbols": symbols,
        "trade_calendar": sorted(open_dates),
        "rows": sorted(rows, key=lambda item: (item["ts_code"], item["trade_date"])),
        "limitations": [
            "Materialized from Tushare daily/adj_factor/stk_limit/trade_cal; no fill simulation is performed by this helper.",
            "QFQ OHLC and limit fields are reconstructed as raw price multiplied by same-day adj_factor.",
            "Rows are trading-day price observations only; suspended or missing daily rows are absent and handled by downstream validation/fill logic.",
        ],
    }


def cache_path_for_request(cache_dir: Path, symbols: list[str], start_date: str, end_date: str) -> Path:
    digest_src = "|".join(sorted(symbols))
    digest = hashlib.sha1(digest_src.encode("utf-8")).hexdigest()[:12]
    return cache_dir / f"execution_price_data_tushare_{start_date}_{end_date}_{digest}.json"


def load_cached_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    validate_json_schema(payload, PRICE_DATA_SCHEMA_PATH, "cached execution_price_data")
    return payload


def validate_payload_matches_request(
    payload: dict[str, Any],
    symbols: list[str],
    as_of: str,
    start_date: str,
    end_date: str,
) -> None:
    if payload.get("date_range") != {"start_date": start_date, "end_date": end_date}:
        raise ValueError(
            "cached execution_price_data date_range does not match request: "
            f"{payload.get('date_range')} vs {start_date}..{end_date}"
        )
    payload_symbols = sorted(str(symbol) for symbol in payload.get("symbols", []))
    if payload_symbols != sorted(symbols):
        raise ValueError(
            "cached execution_price_data symbols do not match request: "
            + ", ".join(payload_symbols)
            + " vs "
            + ", ".join(sorted(symbols))
        )
    rows = payload.get("rows", [])
    available_as_of = {
        str(row.get("ts_code"))
        for row in rows
        if isinstance(row, dict) and str(row.get("trade_date")) == as_of
    }
    missing_as_of = sorted(set(symbols) - available_as_of)
    if missing_as_of:
        raise ValueError(
            "cached execution_price_data rows must include each selected symbol "
            f"on --as-of {as_of}: " + ", ".join(missing_as_of)
        )


def write_payload(payload: dict[str, Any], path: Path) -> None:
    validate_json_schema(payload, PRICE_DATA_SCHEMA_PATH, "execution_price_data")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    analysis_input_path = args.analysis_input or default_analysis_input_path(args.as_of)
    symbols = resolve_symbols(args.symbols, analysis_input_path)
    start_date, end_date = resolve_date_range(
        args.as_of, args.start_date, args.end_date, args.calendar_days
    )
    out_path = output_path(args.as_of, args.out_path)
    cache_path = cache_path_for_request(args.cache_dir, symbols, start_date, end_date)

    payload = None if args.refresh else load_cached_payload(cache_path)
    if payload is None:
        payload = build_payload_from_tushare(
            tushare_pro(),
            symbols=symbols,
            as_of=args.as_of,
            start_date=start_date,
            end_date=end_date,
        )
        write_payload(payload, cache_path)
        print(f"[OK] cached {cache_path}")
    else:
        validate_payload_matches_request(payload, symbols, args.as_of, start_date, end_date)
        print(f"[CACHE] reused {cache_path}")

    write_payload(payload, out_path)
    print(f"[OK] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
