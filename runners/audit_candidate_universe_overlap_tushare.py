from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.backtest_execution import (
    candidate_code,
    iso_now,
    load_analysis_input,
    normalized_analysis_input_schema_version,
    relative_ref,
    validate_json_schema,
)
from runners.materialize_execution_price_data_tushare import ts_call, tushare_pro


SCHEMA_PATH = ROOT / "schemas" / "candidate_universe_overlap_audit.schema.json"
DEFAULT_INPUT_ROOT = ROOT / "result" / "a_short"
DEFAULT_OUT_DIR = ROOT / "result" / "a_short" / "backtest" / "execution" / "forward_aggregate"
DEFAULT_LOOKBACK_DAYS = 450
API_FAMILIES = ["index_weight", "tushare_provider"]
OVERLAP_METHOD = "candidate_ts_code_vs_index_constituents_by_count"
BENCHMARKS = {
    "csi1000": {
        "index_code": "000852.SH",
        "role": "primary",
        "source": "tushare:index_weight/000852.SH",
    },
    "csi300": {
        "index_code": "000300.SH",
        "role": "secondary",
        "source": "tushare:index_weight/000300.SH",
    },
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit one captured A-short candidate universe against CSI1000 and "
            "CSI300 Tushare index_weight constituents. The output is Phase 6b "
            "benchmark-policy evidence only; it does not switch the primary benchmark."
        )
    )
    parser.add_argument("--as-of", required=True, help="Captured candidate trade date in YYYYMMDD form.")
    parser.add_argument(
        "--analysis-input",
        type=Path,
        help="analysis_input.json for --as-of. Defaults to result/a_short/<as-of>/analysis_input.json.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="Calendar-day lookback for Tushare index_weight membership rows.",
    )
    parser.add_argument(
        "--out-path",
        type=Path,
        help=(
            "Output JSON path. Defaults to "
            "result/a_short/backtest/execution/forward_aggregate/"
            "candidate_universe_overlap_audit_<as-of>.json."
        ),
    )
    parser.add_argument(
        "--generated-at",
        help="Optional deterministic generated_at timestamp for tests or replay.",
    )
    return parser.parse_args(argv)


def validate_date8(value: str, label: str = "date") -> None:
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"{label} must be YYYYMMDD: {value!r}")
    datetime.strptime(value, "%Y%m%d")


def default_analysis_input_path(as_of: str) -> Path:
    return DEFAULT_INPUT_ROOT / as_of / "analysis_input.json"


def output_path(as_of: str, out_path: Path | None) -> Path:
    if out_path is not None:
        return out_path
    return DEFAULT_OUT_DIR / f"candidate_universe_overlap_audit_{as_of}.json"


def membership_start_date(as_of: str, lookback_days: int) -> str:
    validate_date8(as_of, "--as-of")
    if lookback_days < 0:
        raise ValueError("--lookback-days must be non-negative")
    return (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=lookback_days)).strftime("%Y%m%d")


def candidate_symbols_from_payload(payload: dict[str, Any]) -> tuple[list[str], int]:
    raw_symbols = [
        candidate_code(candidate)
        for candidate in payload.get("candidates", [])
        if isinstance(candidate, dict) and candidate_code(candidate)
    ]
    symbols = sorted(set(raw_symbols))
    if not symbols:
        raise ValueError("analysis_input contains no candidate symbols")
    return symbols, len(raw_symbols)


def load_candidate_universe(path: Path, as_of: str) -> tuple[dict[str, Any], list[str], int]:
    payload = load_analysis_input(path)
    trade_date = str(payload.get("trade_date") or "")
    if trade_date != as_of:
        raise ValueError(
            f"--as-of {as_of} must match analysis_input.trade_date {trade_date!r}: {path}"
        )
    symbols, raw_count = candidate_symbols_from_payload(payload)
    return payload, symbols, raw_count


def fetch_index_weight(pro: Any, index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    frame = ts_call(
        pro.index_weight,
        index_code=index_code,
        start_date=start_date,
        end_date=end_date,
        fields="index_code,con_code,trade_date,weight",
    )
    if frame is None:
        return pd.DataFrame()
    return frame


def latest_membership_from_rows(
    frame: pd.DataFrame,
    index_code: str,
    start_date: str,
    as_of: str,
) -> tuple[str, list[str]]:
    if frame.empty:
        raise ValueError(f"index_weight returned no rows for {index_code} {start_date}..{as_of}")
    required = {"con_code", "trade_date"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"index_weight missing required columns: {', '.join(missing)}")

    normalized = frame.copy()
    normalized["trade_date"] = normalized["trade_date"].astype(str)
    normalized["con_code"] = normalized["con_code"].astype(str).str.strip()
    normalized = normalized[
        (normalized["trade_date"] >= start_date)
        & (normalized["trade_date"] <= as_of)
        & (normalized["con_code"] != "")
    ]
    if normalized.empty:
        raise ValueError(f"index_weight returned no usable rows for {index_code} {start_date}..{as_of}")

    membership_trade_date = str(normalized["trade_date"].max())
    latest = normalized[normalized["trade_date"] == membership_trade_date]
    constituents = sorted(set(str(item) for item in latest["con_code"].tolist()))
    if not constituents:
        raise ValueError(f"index_weight latest membership has no constituents for {index_code}")
    return membership_trade_date, constituents


def benchmark_audit(
    benchmark: str,
    candidate_symbols: list[str],
    membership_trade_date: str,
    constituents: list[str],
) -> dict[str, Any]:
    candidate_set = set(candidate_symbols)
    constituent_set = set(constituents)
    overlap_symbols = sorted(candidate_set & constituent_set)
    overlap_count = len(overlap_symbols)
    candidate_count = len(candidate_symbols)
    ratio = round(overlap_count / candidate_count, 10)
    spec = BENCHMARKS[benchmark]
    return {
        "benchmark": benchmark,
        "role": spec["role"],
        "index_code": spec["index_code"],
        "source": spec["source"],
        "membership_trade_date": membership_trade_date,
        "constituent_count": len(constituent_set),
        "overlap_count": overlap_count,
        "overlap_ratio": ratio,
        "overlap_symbols": overlap_symbols,
        "non_overlap_count": candidate_count - overlap_count,
    }


def benchmark_ranking(benchmarks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "benchmark": benchmark,
            "overlap_count": int(audit["overlap_count"]),
            "overlap_ratio": float(audit["overlap_ratio"]),
        }
        for benchmark, audit in benchmarks.items()
    ]
    return sorted(rows, key=lambda row: (-row["overlap_count"], -row["overlap_ratio"], row["benchmark"]))


def nearest_benchmark_by_overlap(ranking: list[dict[str, Any]]) -> str:
    best_count = ranking[0]["overlap_count"]
    winners = [row["benchmark"] for row in ranking if row["overlap_count"] == best_count]
    if len(winners) == 1:
        return str(winners[0])
    return "tie:" + ",".join(sorted(winners))


def analysis_input_ref(path: Path, payload: dict[str, Any], raw_count: int, unique_count: int) -> dict[str, Any]:
    return {
        "path": relative_ref(path),
        "schema_name": str(payload.get("schema_name") or "analysis_input"),
        "schema_version": normalized_analysis_input_schema_version(payload),
        "trade_date": str(payload["trade_date"]),
        "preset": str(payload.get("preset") or "a_short"),
        "market": str(payload.get("market") or "A"),
        "horizon": str(payload.get("horizon") or "short"),
        "candidate_count_raw": raw_count,
        "candidate_count_unique": unique_count,
    }


def build_audit_payload(
    pro: Any,
    analysis_input_path: Path,
    as_of: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    validate_date8(as_of, "--as-of")
    start_date = membership_start_date(as_of, lookback_days)
    payload, candidate_symbols, raw_count = load_candidate_universe(analysis_input_path, as_of)

    benchmark_outputs: dict[str, dict[str, Any]] = {}
    for benchmark, spec in BENCHMARKS.items():
        membership_trade_date, constituents = latest_membership_from_rows(
            fetch_index_weight(pro, str(spec["index_code"]), start_date, as_of),
            str(spec["index_code"]),
            start_date,
            as_of,
        )
        benchmark_outputs[benchmark] = benchmark_audit(
            benchmark,
            candidate_symbols,
            membership_trade_date,
            constituents,
        )

    ranking = benchmark_ranking(benchmark_outputs)
    unique_count = len(candidate_symbols)
    audit_payload = {
        "schema_name": "candidate_universe_overlap_audit",
        "schema_version": "1.0.0",
        "generated_at": generated_at or iso_now(),
        "as_of": as_of,
        "scope": {
            "market": "A",
            "system": "a_short",
            "phase": "6b",
            "purpose": "candidate_universe_overlap_audit",
            "audit_status": "audit_only",
            "primary_switch_allowed": False,
        },
        "inputs": {
            "analysis_input": analysis_input_ref(
                analysis_input_path,
                payload,
                raw_count=raw_count,
                unique_count=unique_count,
            )
        },
        "settings": {
            "candidate_symbol_source": "analysis_input.candidates[*].ts_code",
            "provider": "tushare",
            "api_families": API_FAMILIES,
            "membership_source": "tushare:index_weight",
            "membership_window": {
                "start_date": start_date,
                "end_date": as_of,
                "lookback_days": lookback_days,
            },
            "overlap_method": OVERLAP_METHOD,
            "primary_benchmark": "csi1000",
            "secondary_benchmarks": ["csi300"],
        },
        "candidate_universe": {
            "symbols": candidate_symbols,
            "candidate_count_raw": raw_count,
            "candidate_count_unique": unique_count,
            "duplicate_candidate_count": raw_count - unique_count,
        },
        "benchmarks": benchmark_outputs,
        "conclusion": {
            "nearest_benchmark_by_overlap_count": nearest_benchmark_by_overlap(ranking),
            "benchmark_ranking_by_overlap": ranking,
            "primary_switch_allowed": False,
            "benchmark_policy_action": "no_primary_switch_from_single_audit",
        },
        "limitations": [
            "This audit uses index membership overlap by count only; it does not include market-cap percentiles or sector concentration.",
            "A single candidate-universe audit cannot switch the Phase 6a primary benchmark.",
            "Primary benchmark switch review still requires at least 6 forward live months and consecutive cohort evidence per the Phase 6a handoff.",
            "This artifact is benchmark-policy evidence only; it does not promote variants or authorize full-size manual use.",
        ],
    }
    validate_json_schema(audit_payload, SCHEMA_PATH, "candidate_universe_overlap_audit")
    return audit_payload


def write_payload(payload: dict[str, Any], path: Path) -> None:
    validate_json_schema(payload, SCHEMA_PATH, "candidate_universe_overlap_audit")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    analysis_input_path = args.analysis_input or default_analysis_input_path(args.as_of)
    payload = build_audit_payload(
        tushare_pro(),
        analysis_input_path=analysis_input_path,
        as_of=args.as_of,
        lookback_days=args.lookback_days,
        generated_at=args.generated_at,
    )
    out_path = output_path(args.as_of, args.out_path)
    write_payload(payload, out_path)
    print(f"[OK] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
