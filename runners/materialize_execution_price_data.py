from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.backtest_execution import (
    PRICE_DATA_SCHEMA_PATH,
    iso_now,
    validate_json_schema,
)

DEFAULT_OUT_DIR = Path("result") / "a_short" / "backtest" / "execution" / "price_data"
CSV_API_FAMILIES = ["daily", "adj_factor", "stk_limit", "trade_cal", "csv_fixture"]
REQUIRED_COLUMNS = {
    "ts_code",
    "trade_date",
    "open_qfq",
    "high_qfq",
    "low_qfq",
    "close_qfq",
    "pre_close_qfq",
    "adj_factor",
    "up_limit",
    "down_limit",
}
DEFAULT_SOURCE_FLAGS = ["daily", "adj_factor", "stk_limit"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize a schema-valid execution_price_data JSON from a local CSV. "
            "This is a Phase 5 provider-boundary helper; it does not fetch prices or "
            "simulate fills."
        )
    )
    parser.add_argument("--as-of", required=True, help="Candidate trade date in YYYYMMDD form.")
    parser.add_argument("--csv-path", type=Path, required=True, help="Source CSV path.")
    parser.add_argument(
        "--out-path",
        type=Path,
        help=(
            "Output JSON path. Defaults to "
            "result/a_short/backtest/execution/price_data/execution_price_data_<as-of>.json."
        ),
    )
    parser.add_argument(
        "--symbols",
        help="Optional comma-separated ts_code allowlist. Defaults to symbols present in CSV rows.",
    )
    parser.add_argument(
        "--start-date",
        help="Optional date_range.start_date. Defaults to the minimum CSV trade_date.",
    )
    parser.add_argument(
        "--end-date",
        help="Optional date_range.end_date. Defaults to the maximum CSV trade_date.",
    )
    return parser.parse_args(argv)


def output_path(as_of: str, out_path: Path | None) -> Path:
    if out_path is not None:
        return out_path
    return DEFAULT_OUT_DIR / f"execution_price_data_{as_of}.json"


def parse_symbols(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    symbols = sorted({item.strip() for item in raw.split(",") if item.strip()})
    if not symbols:
        raise ValueError("--symbols was provided but no non-empty symbol was found")
    return symbols


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - fieldnames)
        if missing:
            raise ValueError(f"CSV missing required columns: {', '.join(missing)}")
        return [dict(row) for row in reader]


def parse_optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def parse_source_flags(value: str | None) -> list[str]:
    if value is None or value.strip() == "":
        return list(DEFAULT_SOURCE_FLAGS)
    flags = [item.strip() for item in value.replace("|", ",").split(",") if item.strip()]
    if not flags:
        raise ValueError("source_flags must contain at least one non-empty flag")
    return flags


def parse_trade_day(value: str | None) -> bool:
    if value is None or value.strip() == "":
        return True
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y"}:
        return True
    if normalized in {"0", "false", "f", "no", "n"}:
        return False
    raise ValueError(f"invalid is_trade_day value: {value!r}")


def build_price_row(row: dict[str, str]) -> dict[str, Any]:
    is_trade_day = parse_trade_day(row.get("is_trade_day"))
    if not is_trade_day:
        raise ValueError(
            "CSV row "
            f"ts_code={row['ts_code']} trade_date={row['trade_date']} "
            "has is_trade_day=false; execution_price_data schema requires "
            "trading-day observations only; non-trading dates are represented "
            "by trade_cal lineage"
        )
    return {
        "ts_code": row["ts_code"],
        "trade_date": row["trade_date"],
        "is_trade_day": is_trade_day,
        "open_qfq": float(row["open_qfq"]),
        "high_qfq": float(row["high_qfq"]),
        "low_qfq": float(row["low_qfq"]),
        "close_qfq": float(row["close_qfq"]),
        "pre_close_qfq": parse_optional_float(row.get("pre_close_qfq")),
        "adj_factor": float(row["adj_factor"]),
        "up_limit": parse_optional_float(row.get("up_limit")),
        "down_limit": parse_optional_float(row.get("down_limit")),
        "volume": parse_optional_float(row.get("volume")),
        "source_flags": parse_source_flags(row.get("source_flags")),
    }


def materialize_payload(
    rows: list[dict[str, str]],
    as_of: str,
    symbols: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    generated_at: str | None = None,
    source_csv_path: Path | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("CSV must contain at least one price row")

    derived_symbols = sorted({row["ts_code"] for row in rows})
    selected_symbols = symbols or derived_symbols
    selected_set = set(selected_symbols)
    selected_raw_rows = [row for row in rows if row["ts_code"] in selected_set]
    if not selected_raw_rows:
        raise ValueError("CSV contains no rows for the requested symbols")
    filtered_rows = [build_price_row(row) for row in selected_raw_rows]
    available_as_of_symbols = {
        row["ts_code"] for row in filtered_rows if row["trade_date"] == as_of
    }
    missing_as_of_symbols = sorted(selected_set - available_as_of_symbols)
    if missing_as_of_symbols:
        raise ValueError(
            "CSV must include an --as-of price row for each selected symbol: "
            + ", ".join(missing_as_of_symbols)
        )

    dates = sorted({str(row["trade_date"]) for row in filtered_rows})
    effective_start = start_date or dates[0]
    effective_end = end_date or dates[-1]
    if effective_start > effective_end:
        raise ValueError(
            f"date_range.start_date must be <= end_date: {effective_start}..{effective_end}"
        )
    if not (effective_start <= as_of <= effective_end):
        raise ValueError(
            f"date_range must cover --as-of {as_of}: {effective_start}..{effective_end}"
        )
    limitations = [
        "Materialized from a local CSV provider fixture; no Tushare fetch is performed by this helper.",
        "Rows are schema-validated price observations only; fill simulation remains outside this step.",
        f"Candidate as_of for downstream loader validation is {as_of}.",
    ]
    if source_csv_path is not None:
        limitations.append(f"Materialized from CSV: {source_csv_path}")

    return {
        "schema_name": "execution_price_data",
        "schema_version": "1.0.0",
        "generated_at": generated_at or iso_now(),
        "preset": "a_short",
        "data_provider": "tushare",
        "source": {
            "api_families": CSV_API_FAMILIES,
            "adjustment_mode": "qfq_via_adj_factor",
            "price_basis": "daily_eod",
            "calendar_source": "csv",
            "pit_policy": "trade_date_eod",
        },
        "date_range": {
            "start_date": effective_start,
            "end_date": effective_end,
        },
        "symbols": selected_symbols,
        "trade_calendar": dates,
        "rows": filtered_rows,
        "limitations": limitations,
    }


def write_payload(payload: dict[str, Any], path: Path) -> None:
    validate_json_schema(payload, PRICE_DATA_SCHEMA_PATH, "execution_price_data")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = read_csv_rows(args.csv_path)
    payload = materialize_payload(
        rows,
        args.as_of,
        symbols=parse_symbols(args.symbols),
        start_date=args.start_date,
        end_date=args.end_date,
        source_csv_path=args.csv_path,
    )
    out_path = output_path(args.as_of, args.out_path)
    write_payload(payload, out_path)
    print(f"[OK] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
