"""Bounded paid-Tushare feasibility probe for Rule6's three D-tier needs.

This runner is deliberately outside EGS, the weekly pipeline, and the Rule6
gate.  It samples two fixed A-share symbols through three candidate paid
endpoints, keeps vendor rows under the gitignored ``provider_samples/`` root,
and writes a shape-only tracked summary.  A successful response is evidence of
an available surface only; it never authorizes Rule6 wiring.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from engine.a_short_tushare_client import SUPPORTED_TUSHARE_VERSION, init_tushare_pro


PROBE_DATE = "20260714"
SYMBOLS = ("600519.SH", "000001.SZ")
RAW_ROOT = Path(f"provider_samples/a_short_rule6_tushare_d_tier_probe_{PROBE_DATE}")
SUMMARY_PATH = Path(f"docs/a_short_rule6_tushare_d_tier_probe_summary_{PROBE_DATE}.json")
PROBE_SPECS = (
    {
        "endpoint": "hk_hold",
        "d_tier_need": "northbound_per_stock",
        "parameters": {"start_date": "20260701", "end_date": PROBE_DATE},
        "required_columns": ("ts_code", "trade_date"),
    },
    {
        "endpoint": "report_rc",
        "d_tier_need": "good_data_bad_reaction",
        "parameters": {"start_date": "20260401", "end_date": PROBE_DATE},
        "required_columns": ("ts_code",),
    },
    {
        "endpoint": "anns_d",
        "d_tier_need": "regulatory_48h",
        "parameters": {"start_date": "20260712", "end_date": PROBE_DATE},
        "required_columns": ("ts_code", "ann_date"),
    },
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _raw_json_value(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return {"kind": "dataframe", "rows": value.to_dict(orient="records")}
    if isinstance(value, pd.Series):
        return {"kind": "series", "values": value.to_dict()}
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return list(value)
    return {"kind": type(value).__name__}


def _shape(value: Any) -> dict[str, Any]:
    if isinstance(value, pd.DataFrame):
        return {
            "kind": "dataframe",
            "row_count": int(len(value)),
            "columns": sorted(str(column) for column in value.columns),
        }
    if isinstance(value, pd.Series):
        return {
            "kind": "series",
            "row_count": int(len(value)),
            "columns": sorted(str(index) for index in value.index),
        }
    if isinstance(value, dict):
        return {"kind": "object", "row_count": 1, "columns": sorted(str(key) for key in value)}
    if isinstance(value, (list, tuple)):
        keys = {str(key) for item in value if isinstance(item, dict) for key in item}
        return {"kind": "list", "row_count": len(value), "columns": sorted(keys)}
    return {"kind": type(value).__name__, "row_count": 0 if value is None else 1, "columns": []}


def _error_category(exc: Exception) -> str:
    """Classify a provider failure without retaining its text or response body."""
    message = str(exc).casefold()
    if any(marker in message for marker in ("权限", "积分", "permission", "entitlement", "access denied")):
        return "permission_or_entitlement"
    if any(marker in message for marker in ("token", "auth", "认证", "鉴权")):
        return "authentication"
    if any(marker in message for marker in ("接口", "api name", "parameter", "参数", "not found")):
        return "endpoint_or_parameter"
    return "provider_or_undetermined"


def _surface_observation(results: list[dict[str, Any]], endpoint: str, required_columns: tuple[str, ...]) -> dict[str, Any]:
    matching = [result for result in results if result["endpoint"] == endpoint]
    successful_shapes = [result["shape"] for result in matching if result["status"] == "ok"]
    return {
        "endpoint": endpoint,
        "nonempty_response_seen": any(shape["row_count"] > 0 for shape in successful_shapes),
        "required_columns_seen": any(
            set(required_columns).issubset(set(shape["columns"])) for shape in successful_shapes
        ),
    }


def run_probe(pro_client: Any, raw_root: Path = RAW_ROOT) -> dict[str, Any]:
    """Run six fixed, read-only endpoint calls against an injected Pro client."""
    raw_root = Path(raw_root)
    results: list[dict[str, Any]] = []
    raw_by_symbol: dict[str, dict[str, Any]] = {symbol: {} for symbol in SYMBOLS}
    completed_calls = 0
    error_calls = 0

    for spec in PROBE_SPECS:
        method = getattr(pro_client, spec["endpoint"], None)
        for symbol in SYMBOLS:
            parameters = {"ts_code": symbol, **spec["parameters"]}
            result: dict[str, Any] = {
                "symbol": symbol,
                "endpoint": spec["endpoint"],
                "parameters": parameters,
            }
            if not callable(method):
                result["status"] = "sdk_method_missing"
                error_calls += 1
            else:
                try:
                    payload = method(**parameters)
                    raw_by_symbol[symbol][spec["endpoint"]] = _raw_json_value(payload)
                    result.update({"status": "ok", "shape": _shape(payload)})
                    completed_calls += 1
                except Exception as exc:  # No vendor message, URL, body, or token reaches the summary.
                    result.update(
                        {
                            "status": "error",
                            "error_class": type(exc).__name__,
                            "error_category": _error_category(exc),
                        }
                    )
                    error_calls += 1
            results.append(result)

    for symbol, raw_payload in raw_by_symbol.items():
        _write_json(raw_root / f"{symbol.replace('.', '_')}.json", raw_payload)

    return {
        "schema_name": "a_short_rule6_tushare_d_tier_probe_summary",
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": {
            "market": "A-share",
            "purpose": "rule6_d_tier_paid_tushare_feasibility_probe_only",
            "tushare_is_wired_into_rule6": False,
            "egs_or_weekly_behavior_changed": False,
            "production_or_ship_gate_claimed": False,
            "broker_or_order_action": False,
        },
        "sample": {
            "symbols": list(SYMBOLS),
            "endpoint_names": [spec["endpoint"] for spec in PROBE_SPECS],
            "pinned_tushare_version": SUPPORTED_TUSHARE_VERSION,
        },
        "execution": {
            "status": "completed" if error_calls == 0 else "completed_with_errors",
            "planned_endpoint_reads": len(SYMBOLS) * len(PROBE_SPECS),
            "completed_endpoint_reads": completed_calls,
            "error_endpoint_reads": error_calls,
        },
        "shape_results": results,
        "surface_observations": {
            spec["d_tier_need"]: _surface_observation(results, spec["endpoint"], spec["required_columns"])
            for spec in PROBE_SPECS
        },
        "d_tier_disposition": {
            "northbound_per_stock": {
                "usable_as_rule6_hard_veto_source": False,
                "reason": "response shape alone cannot establish a PIT-safe consecutive northbound-sell Rule6 source",
            },
            "good_data_bad_reaction": {
                "usable_as_rule6_hard_veto_source": False,
                "reason": "response shape alone cannot establish a PIT-safe consensus, result, and reaction contract",
            },
            "regulatory_48h": {
                "usable_as_rule6_hard_veto_source": False,
                "reason": "announcement shape alone cannot classify official regulatory inquiries within 48 hours",
            },
        },
        "storage": {
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
    parser = argparse.ArgumentParser(description="Bounded A-short Rule6 paid-Tushare D-tier feasibility probe")
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--out", type=Path, default=SUMMARY_PATH)
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for the paid Rule6 D-tier probe")
    pro = init_tushare_pro(token)
    summary = run_probe(pro, args.raw_root)
    _write_json(args.out, summary)
    print(f"[a-short Rule6 paid-Tushare probe] {summary['execution']['status']} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
