"""Bounded shape probe for the market-level margin (两融) surface.

Row 21 of the A-short queue.  Rows 19 (#16 全市场融资过热) and the northbound
lookback both need to know the endpoint, entitlement, field names, unit and
usable history depth BEFORE any code is written against them -- the cninfo
``orgId`` round proved that coding against an assumed vendor shape costs a
whole review cycle.

This runner is deliberately outside EGS and the weekly pipeline.  It performs
a fixed, read-only, budgeted set of calls, keeps vendor rows under the
gitignored ``provider_samples/`` root, and writes a shape-only tracked
summary.  A successful response is evidence of an available surface only; it
authorizes no wiring, no percentile computation and no consumer.
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


PROBE_DATE = "20260804"
CALL_BUDGET = 12
RAW_ROOT = Path(f"provider_samples/a_short_margin_market_shape_probe_{PROBE_DATE}")
SUMMARY_PATH = Path(f"docs/a_short_margin_market_shape_probe_summary_{PROBE_DATE}.json")

# 3 recent sessions establish fields/units; 2 far-back windows establish how far
# the history reaches, which decides how long a percentile window row 19 can open.
RECENT_TRADE_DATES = ("20260731", "20260730", "20260729")
HISTORY_WINDOWS = (
    {"label": "about_one_year_back", "start_date": "20250728", "end_date": "20250801"},
    {"label": "about_three_years_back", "start_date": "20230731", "end_date": "20230804"},
)
# Only probed when every ``margin`` call failed: can per-stock rows be summed
# into a market total instead?
FALLBACK_SPEC = {"endpoint": "margin_detail", "parameters": {"trade_date": RECENT_TRADE_DATES[0]}}

# Field-name markers that would tell us what the vendor calls each quantity.
# Presence only -- no row value ever reaches the tracked summary.
FIELD_MARKERS = {
    "financing_balance": ("rzye",),
    "short_selling_balance": ("rqye", "rqyl"),
    "combined_balance": ("rzrqye",),
    "exchange_key": ("exchange_id", "exchange"),
    "date_key": ("trade_date",),
}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )


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
    """Columns, counts and per-column emptiness only -- never a row value."""
    if isinstance(value, pd.DataFrame):
        columns = [str(column) for column in value.columns]
        return {
            "kind": "dataframe",
            "row_count": int(len(value)),
            "columns": sorted(columns),
            "column_dtypes": {name: str(value[name].dtype) for name in columns},
            "all_null_columns": sorted(
                name for name in columns if bool(value[name].isna().all())
            ),
        }
    if isinstance(value, pd.Series):
        return {"kind": "series", "row_count": int(len(value)),
                "columns": sorted(str(index) for index in value.index),
                "column_dtypes": {}, "all_null_columns": []}
    if isinstance(value, dict):
        return {"kind": "object", "row_count": 1, "columns": sorted(str(k) for k in value),
                "column_dtypes": {}, "all_null_columns": []}
    if isinstance(value, (list, tuple)):
        keys = {str(key) for item in value if isinstance(item, dict) for key in item}
        return {"kind": "list", "row_count": len(value), "columns": sorted(keys),
                "column_dtypes": {}, "all_null_columns": []}
    return {"kind": type(value).__name__, "row_count": 0 if value is None else 1,
            "columns": [], "column_dtypes": {}, "all_null_columns": []}


def _error_category(exc: Exception) -> str:
    """Four distinguishable failure classes; collapsing them would defeat the probe."""
    message = str(exc).casefold()
    if any(m in message for m in ("权限", "积分", "permission", "entitlement", "access denied")):
        return "permission_or_entitlement"
    if any(m in message for m in ("token", "auth", "认证", "鉴权")):
        return "authentication"
    if any(m in message for m in ("每分钟", "频率", "rate", "too many", "limit")):
        return "rate_limited"
    if any(m in message for m in ("接口", "api name", "parameter", "参数", "not found", "不存在")):
        return "endpoint_or_parameter"
    return "provider_or_undetermined"


def _field_presence(shapes: list[dict[str, Any]]) -> dict[str, Any]:
    seen = set()
    for shape in shapes:
        seen.update(shape.get("columns") or [])
    return {
        role: {"markers": list(markers),
               "present": sorted(m for m in markers if m in seen)}
        for role, markers in FIELD_MARKERS.items()
    }


def run_probe(pro_client: Any, raw_root: Path = RAW_ROOT) -> dict[str, Any]:
    """Run a budgeted set of read-only market-margin calls against an injected client."""
    raw_root = Path(raw_root)
    results: list[dict[str, Any]] = []
    raw_by_label: dict[str, Any] = {}
    calls = 0

    def _call(label: str, endpoint: str, parameters: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        record: dict[str, Any] = {"label": label, "endpoint": endpoint,
                                  "parameters": dict(parameters)}
        if calls >= CALL_BUDGET:
            record["status"] = "budget_exhausted"
            results.append(record)
            return record
        method = getattr(pro_client, endpoint, None)
        if not callable(method):
            record["status"] = "sdk_method_missing"
            results.append(record)
            return record
        calls += 1
        try:
            payload = method(**parameters)
            raw_by_label[label] = _raw_json_value(payload)
            record.update({"status": "ok", "shape": _shape(payload)})
        except Exception as exc:  # No vendor message, URL, body or token reaches the summary.
            record.update({"status": "error", "error_class": type(exc).__name__,
                           "error_category": _error_category(exc)})
        results.append(record)
        return record

    for trade_date in RECENT_TRADE_DATES:
        _call(f"margin_recent_{trade_date}", "margin", {"trade_date": trade_date})
    for window in HISTORY_WINDOWS:
        _call(f"margin_{window['label']}", "margin",
              {"start_date": window["start_date"], "end_date": window["end_date"]})

    margin_ok = [r for r in results if r["endpoint"] == "margin" and r["status"] == "ok"]
    fallback_probed = False
    if not margin_ok:
        fallback_probed = True
        _call("margin_detail_aggregation_feasibility",
              FALLBACK_SPEC["endpoint"], FALLBACK_SPEC["parameters"])

    for label, raw_payload in raw_by_label.items():
        _write_json(raw_root / f"{label}.json", raw_payload)

    margin_shapes = [r["shape"] for r in margin_ok]
    nonempty_recent = [
        r for r in margin_ok
        if r["label"].startswith("margin_recent_") and r["shape"]["row_count"] > 0
    ]
    history_reach = {
        window["label"]: next(
            (r["shape"]["row_count"] > 0 for r in margin_ok
             if r["label"] == f"margin_{window['label']}"),
            None,
        )
        for window in HISTORY_WINDOWS
    }
    error_categories = sorted({
        r["error_category"] for r in results if r.get("error_category")
    })

    return {
        "schema_name": "a_short_margin_market_shape_probe_summary",
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": {
            "market": "A-share",
            "purpose": "market_level_margin_endpoint_shape_probe_only",
            "queue_row": 21,
            "downstream_rows_blocked_until_reviewed": ["19_margin_overheat", "northbound_lookback"],
            "percentile_computed": False,
            "consumer_wired": False,
            "egs_or_weekly_behavior_changed": False,
            "production_or_ship_gate_claimed": False,
            "broker_or_order_action": False,
        },
        "sample": {
            "recent_trade_dates": list(RECENT_TRADE_DATES),
            "history_windows": [dict(window) for window in HISTORY_WINDOWS],
            "fallback_probed": fallback_probed,
            "pinned_tushare_version": SUPPORTED_TUSHARE_VERSION,
        },
        "execution": {
            "call_budget": CALL_BUDGET,
            "calls_made": calls,
            "within_budget": calls <= CALL_BUDGET,
            "ok_calls": sum(1 for r in results if r["status"] == "ok"),
            "error_calls": sum(1 for r in results if r["status"] == "error"),
            "status": "completed" if all(r["status"] == "ok" for r in results) else "completed_with_errors",
        },
        "shape_results": results,
        "surface_observations": {
            "market_margin_endpoint_available": bool(margin_ok),
            "nonempty_recent_session_seen": bool(nonempty_recent),
            "field_presence": _field_presence(margin_shapes),
            "history_reach_by_window": history_reach,
            "distinct_error_categories": error_categories,
        },
        "unit_determination": {
            # The probe can only observe column names and magnitudes; the unit
            # must be stated by a human from vendor docs before row 19 uses it.
            "resolved": False,
            "reason": "column names alone do not fix the unit; northbound already cost a 万元-vs-元 trap",
            "must_be_settled_before": "19_margin_overheat",
        },
        "storage": {
            "raw_payload_root": RAW_ROOT.as_posix(),
            "raw_payload_root_gitignored": True,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_secret": False,
        },
        "decision": {
            "row_19_wiring_authorized": False,
            "northbound_lookback_wiring_authorized": False,
            "separate_review_required_before_any_future_use": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded A-share market-level margin shape probe (queue row 21)")
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--out", type=Path, default=SUMMARY_PATH)
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for the market-margin shape probe")
    pro = init_tushare_pro(token)
    summary = run_probe(pro, args.raw_root)
    _write_json(args.out, summary)
    print(f"[a-short margin market shape probe] {summary['execution']['status']} "
          f"calls={summary['execution']['calls_made']}/{CALL_BUDGET} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
