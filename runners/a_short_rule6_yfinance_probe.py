"""Bounded feasibility probe for Rule6's three non-wired A-share D-tier needs.

This runner is intentionally not imported by EGS, the weekly pipeline, or the
Rule6 gate.  It records only response shapes in the tracked summary; vendor
payloads stay below the gitignored ``provider_samples/`` root.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd


PROBE_DATE = "20260714"
SYMBOLS = ("600519.SS", "000001.SZ")
RAW_ROOT = Path(f"provider_samples/a_short_rule6_yfinance_probe_{PROBE_DATE}")
SUMMARY_PATH = Path(f"docs/a_short_rule6_yfinance_probe_summary_{PROBE_DATE}.json")
ENDPOINTS: dict[str, Callable[[Any], Any]] = {
    "market_price_history": lambda ticker: ticker.history(period="5d", auto_adjust=False),
    "analyst_recommendations": lambda ticker: ticker.recommendations,
    "news_items": lambda ticker: ticker.news,
    "institutional_holders_proxy": lambda ticker: ticker.institutional_holders,
}


def _raw_json_value(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return {"kind": "dataframe", "rows": value.to_dict(orient="records")}
    if isinstance(value, pd.Series):
        return {"kind": "series", "values": value.to_dict()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return list(value)
    return {"kind": type(value).__name__}


def _shape(value: Any) -> dict[str, Any]:
    if isinstance(value, pd.DataFrame):
        return {
            "kind": "dataframe", "row_count": int(len(value)),
            "columns": sorted(str(column) for column in value.columns),
        }
    if isinstance(value, pd.Series):
        return {"kind": "series", "row_count": int(len(value)), "columns": sorted(str(index) for index in value.index)}
    if isinstance(value, dict):
        return {"kind": "object", "row_count": 1, "columns": sorted(str(key) for key in value)}
    if isinstance(value, (list, tuple)):
        keys = set()
        for item in value:
            if isinstance(item, dict):
                keys.update(str(key) for key in item)
        return {"kind": "list", "row_count": len(value), "columns": sorted(keys)}
    return {"kind": type(value).__name__, "row_count": 0 if value is None else 1, "columns": []}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def run_probe(yfinance_module: Any, raw_root: Path = RAW_ROOT) -> dict[str, Any]:
    """Run the fixed two-symbol shape probe with an injected yfinance module."""
    raw_root = Path(raw_root)
    results = []
    completed_calls = 0
    error_calls = 0
    for symbol in SYMBOLS:
        ticker = yfinance_module.Ticker(symbol)
        endpoint_results = {}
        raw_payload = {}
        for endpoint, reader in ENDPOINTS.items():
            try:
                payload = reader(ticker)
                raw_payload[endpoint] = _raw_json_value(payload)
                endpoint_results[endpoint] = {"status": "ok", "shape": _shape(payload)}
                completed_calls += 1
            except Exception as exc:  # vendor exceptions are summarized without text/URLs.
                endpoint_results[endpoint] = {"status": "error", "error_class": type(exc).__name__}
                error_calls += 1
        _write_json(raw_root / f"{symbol.replace('.', '_')}.json", raw_payload)
        results.append({"symbol": symbol, "endpoints": endpoint_results})

    return {
        "schema_name": "a_short_rule6_yfinance_probe_summary",
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": {
            "market": "A-share", "purpose": "rule6_d_tier_feasibility_probe_only",
            "yfinance_is_wired_into_rule6": False,
            "egs_or_weekly_behavior_changed": False,
            "production_or_ship_gate_claimed": False,
            "broker_or_order_action": False,
        },
        "sample": {"symbols": list(SYMBOLS), "endpoint_names": list(ENDPOINTS)},
        "execution": {
            "status": "completed" if error_calls == 0 else "completed_with_errors",
            "planned_endpoint_reads": len(SYMBOLS) * len(ENDPOINTS),
            "completed_endpoint_reads": completed_calls,
            "error_endpoint_reads": error_calls,
        },
        "shape_results": results,
        "d_tier_disposition": {
            "northbound_per_stock": {
                "usable_as_rule6_hard_veto_source": False,
                "reason": "institutional-holders proxy is not an exchange northbound holding feed",
            },
            "good_data_bad_reaction": {
                "usable_as_rule6_hard_veto_source": False,
                "reason": "recommendation shape cannot establish required A-share consensus coverage",
            },
            "regulatory_48h": {
                "usable_as_rule6_hard_veto_source": False,
                "reason": "generic news shape is not an official inquiry or concern feed",
            },
        },
        "storage": {
            # The tracked artifact pins the production raw-root contract.  Tests
            # may supply a temporary physical root without changing that contract.
            "raw_payload_root": RAW_ROOT.as_posix(),
            "raw_payload_root_gitignored": True,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_secret": False,
        },
        "decision": {
            "rule6_d_tier_status_remains_not_applicable": True,
            "downstream_rule6_wiring_authorized": False,
            "separate_review_required_before_any_future_use": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded A-short Rule6 yfinance feasibility probe")
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--out", type=Path, default=SUMMARY_PATH)
    args = parser.parse_args(argv)
    try:
        import yfinance
    except ModuleNotFoundError as exc:
        raise RuntimeError("yfinance is not installed; install it only with explicit approval") from exc
    summary = run_probe(yfinance, args.raw_root)
    _write_json(args.out, summary)
    print(f"[a-short Rule6 yfinance probe] {summary['execution']['status']} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
