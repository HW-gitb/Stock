from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ROUTE_PLAN_PATH = ROOT / "docs" / "a_long_tushare_data_route_repair_plan_20260603.json"
SUMMARY_PATH = ROOT / "docs" / "a_long_tushare_route_validation_execution_summary_20260604.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/route_validation_20260604")
RAW_ROOT = ROOT / RAW_ROOT_REL

ACTIVE_SYMBOLS = ["000001.SZ", "600519.SH"]
FUNDAMENTAL_PERIOD = "20231231"
PRICE_START_DATE = "20240102"
PRICE_END_DATE = "20240105"
BENCHMARK_INDEX = "000300.SH"
MAX_TOTAL_CALLS = 24
SW_INDUSTRY_CLASSIFICATION_STANDARD = "SW2021"
SW_INDUSTRY_CLASSIFICATION_FIELDS = "index_code,industry_name,parent_code,level,src"

COMPONENTS = [
    "calendar_schedule",
    "pit_universe_survivorship",
    "raw_pit_fundamentals",
    "restatement_revision_lineage",
    "industry_taxonomy_history",
    "total_return_and_benchmark",
    "terminal_delisting_return",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the small A-long Tushare route-validation packet. This is field-presence "
            "and storage-shape validation only; it does not materialize full history, rerun "
            "the data audit, search signals, or calculate alpha."
        )
    )
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument(
        "--dry-run-env",
        action="store_true",
        help="Validate route plan, gitignore, and environment boundary without Tushare calls.",
    )
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")
    tmp_path.replace(path)


def validate_route_plan(path: Path = ROUTE_PLAN_PATH) -> dict[str, Any]:
    plan = read_json(path)
    if plan.get("schema_name") != "a_long_tushare_data_route_repair_plan":
        raise ValueError("A-long Tushare route plan schema_name mismatch")
    scope = plan.get("scope") or {}
    if scope.get("route_plan_only") is not True:
        raise ValueError("route plan must remain plan-only")
    if scope.get("existing_tushare_account_candidate_only") is not True:
        raise ValueError("route plan must use existing Tushare account candidate only")
    for field in [
        "provider_call_allowed_by_this_artifact",
        "tushare_call_allowed_by_this_artifact",
        "data_fetch_allowed_by_this_artifact",
        "audit_rerun_allowed_by_this_artifact",
        "signal_search_allowed",
        "alpha_backtest_allowed",
        "new_data_purchase_allowed",
        "provider_expansion_allowed",
        "datahub_allowed",
        "production_use_allowed",
        "ship_gate_claim_allowed",
        "full_size_manual_use_allowed",
        "broker_or_order_automation_allowed",
    ]:
        if scope.get(field) is not False:
            raise ValueError(f"route plan must keep scope.{field}=false")

    boundary = plan.get("next_execution_packet_boundary") or {}
    if boundary.get("packet_type") != "a_long_tushare_route_validation_packet":
        raise ValueError("route plan next packet type mismatch")
    if boundary.get("allowed_provider_family") != "existing_tushare_account":
        raise ValueError("route plan must keep next packet provider family fixed")
    if boundary.get("allowed_goal") != "confirm field_presence_endpoint_behavior_and_storage_shape_only":
        raise ValueError("route plan must keep next packet goal field-presence only")
    if boundary.get("allowed_raw_output_root") != "data/a_long/raw/tushare/":
        raise ValueError("route plan raw output root mismatch")

    components = {item.get("component_id") for item in plan.get("required_route_components", [])}
    if components != set(COMPONENTS):
        raise ValueError("route plan components mismatch")
    policy = plan.get("no_silent_default_policy") or {}
    for field in [
        "derived_a_short_cache_substitution_allowed",
        "latest_only_fundamental_substitution_allowed",
        "missing_ann_date_fill_allowed",
        "zero_return_fill_allowed",
        "drop_delisted_holding_allowed",
        "close_to_close_benchmark_fallback_allowed",
        "price_only_return_claims_total_return_allowed",
        "current_active_list_as_history_allowed",
        "akshare_substitution_allowed_without_review",
    ]:
        if policy.get(field) is not False:
            raise ValueError(f"route plan must keep no_silent_default_policy.{field}=false")
    return plan


def path_is_gitignored_by_policy(raw_root: Path) -> bool:
    gitignore_path = ROOT / ".gitignore"
    if not gitignore_path.exists():
        return False
    normalized = raw_root.resolve().relative_to(ROOT.resolve()).as_posix().rstrip("/") + "/"
    lines = [
        line.strip().replace("\\", "/")
        for line in gitignore_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return (
        "data/a_long/raw/" in lines
        or "data/a_long/raw/tushare/" in lines
        or normalized in lines
    )


def validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_ROOT_REL).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError("raw output must stay under data/a_long/raw/tushare/route_validation_20260604/") from exc
    if not path_is_gitignored_by_policy(raw_root):
        raise ValueError("raw output root is not protected by .gitignore policy")


def redact_error(exc: BaseException) -> str:
    message = str(exc)
    token = os.environ.get("TUSHARE_TOKEN")
    if token:
        message = message.replace(token, "[REDACTED_TOKEN]")
    return message[:240]


def normalize_records(value: Any) -> tuple[list[str], int | None, list[dict[str, Any]]]:
    try:
        import pandas as pd  # type: ignore
    except ModuleNotFoundError:
        pd = None  # type: ignore

    if pd is not None and isinstance(value, pd.DataFrame):
        frame = value.copy()
        columns = [str(col) for col in frame.columns]
        records = frame.where(frame.notna(), None).to_dict(orient="records")
        return columns, int(len(frame)), records
    if value is None:
        return [], None, []
    if isinstance(value, list):
        records = [item if isinstance(item, dict) else {"value": item} for item in value]
        columns = sorted({str(key) for row in records for key in row})
        return columns, len(records), records
    if isinstance(value, dict):
        return [str(key) for key in value], 1, [value]
    return [], None, [{"value": str(value)}]


def raw_payload_path(raw_root: Path, call_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in call_id)
    return raw_root / f"{safe}.json"


def write_raw_payload(raw_root: Path, call_id: str, payload: dict[str, Any]) -> str:
    path = raw_payload_path(raw_root, call_id)
    write_json_atomic(payload, path)
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def call_plan() -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = [
        {
            "call_id": "calendar_trade_cal_201801",
            "component_id": "calendar_schedule",
            "api_family": "trade_cal",
            "method": "trade_cal",
            "kwargs": {
                "exchange": "SSE",
                "start_date": "20180101",
                "end_date": "20180131",
                "is_open": "1",
                "fields": "cal_date,is_open,exchange",
            },
            "required_fields": ["cal_date", "is_open"],
        },
        {
            "call_id": "stock_basic_active_L",
            "component_id": "pit_universe_survivorship",
            "api_family": "stock_basic",
            "method": "stock_basic",
            "kwargs": {
                "exchange": "",
                "list_status": "L",
                "fields": "ts_code,symbol,name,exchange,market,list_status,list_date,delist_date",
            },
            "required_fields": ["ts_code", "name", "list_status", "list_date", "delist_date"],
        },
        {
            "call_id": "stock_basic_delisted_D",
            "component_id": "terminal_delisting_return",
            "api_family": "stock_basic",
            "method": "stock_basic",
            "kwargs": {
                "exchange": "",
                "list_status": "D",
                "fields": "ts_code,symbol,name,exchange,market,list_status,list_date,delist_date",
            },
            "required_fields": ["ts_code", "name", "list_status", "list_date", "delist_date"],
            "also_component_ids": ["pit_universe_survivorship"],
            "save_context": "first_delisted_symbol",
        },
        {
            "call_id": "index_classify_sw_L1",
            "component_id": "industry_taxonomy_history",
            "api_family": "index_classify",
            "method": "index_classify",
            "kwargs": {
                "level": "L1",
                "src": SW_INDUSTRY_CLASSIFICATION_STANDARD,
                "fields": SW_INDUSTRY_CLASSIFICATION_FIELDS,
            },
            "required_fields": ["index_code", "level", "src"],
        },
        {
            "call_id": "index_classify_sw_L2",
            "component_id": "industry_taxonomy_history",
            "api_family": "index_classify",
            "method": "index_classify",
            "kwargs": {
                "level": "L2",
                "src": SW_INDUSTRY_CLASSIFICATION_STANDARD,
                "fields": SW_INDUSTRY_CLASSIFICATION_FIELDS,
            },
            "required_fields": ["index_code", "level", "parent_code", "src"],
            "save_context": "first_l2_index_code",
        },
    ]
    for symbol in ACTIVE_SYMBOLS:
        for api_family, fields, required_fields in [
            (
                "income",
                "ts_code,ann_date,f_ann_date,end_date,report_type,revenue,n_income_attr_p",
                ["ts_code", "ann_date", "end_date"],
            ),
            (
                "balancesheet",
                "ts_code,ann_date,f_ann_date,end_date,report_type,total_assets,total_liab,total_hldr_eqy_exc_min_int",
                ["ts_code", "ann_date", "end_date"],
            ),
            (
                "cashflow",
                "ts_code,ann_date,f_ann_date,end_date,report_type,n_cashflow_act",
                ["ts_code", "ann_date", "end_date"],
            ),
            (
                "fina_indicator",
                "ts_code,ann_date,end_date,roe,profit_dedt",
                ["ts_code", "ann_date", "end_date"],
            ),
        ]:
            calls.append(
                {
                    "call_id": f"{api_family}_{symbol}_{FUNDAMENTAL_PERIOD}",
                    "component_id": "raw_pit_fundamentals",
                    "api_family": api_family,
                    "method": api_family,
                    "kwargs": {
                        "ts_code": symbol,
                        "period": FUNDAMENTAL_PERIOD,
                        "fields": fields,
                    },
                    "required_fields": required_fields,
                    "also_component_ids": ["restatement_revision_lineage"],
                }
            )
        for api_family, fields, required_fields in [
            (
                "daily",
                "ts_code,trade_date,open,close",
                ["ts_code", "trade_date", "open", "close"],
            ),
            (
                "adj_factor",
                "ts_code,trade_date,adj_factor",
                ["ts_code", "trade_date", "adj_factor"],
            ),
            (
                "dividend",
                "ts_code,end_date,ann_date,record_date,ex_date,pay_date,cash_div,cash_div_tax",
                ["ts_code", "ann_date"],
            ),
        ]:
            kwargs = {"ts_code": symbol, "fields": fields}
            if api_family in {"daily", "adj_factor"}:
                kwargs["start_date"] = PRICE_START_DATE
                kwargs["end_date"] = PRICE_END_DATE
            calls.append(
                {
                    "call_id": f"{api_family}_{symbol}_{PRICE_START_DATE}_{PRICE_END_DATE}",
                    "component_id": "total_return_and_benchmark",
                    "api_family": api_family,
                    "method": api_family,
                    "kwargs": kwargs,
                    "required_fields": required_fields,
                }
            )
    calls.append(
        {
            "call_id": f"index_daily_{BENCHMARK_INDEX}_{PRICE_START_DATE}_{PRICE_END_DATE}",
            "component_id": "total_return_and_benchmark",
            "api_family": "index_daily",
            "method": "index_daily",
            "kwargs": {
                "ts_code": BENCHMARK_INDEX,
                "start_date": PRICE_START_DATE,
                "end_date": PRICE_END_DATE,
                "fields": "ts_code,trade_date,open,close",
            },
            "required_fields": ["ts_code", "trade_date", "open", "close"],
        }
    )
    for api_family, fields, required_fields in [
        (
            "daily",
            "ts_code,trade_date,open,close",
            ["ts_code", "trade_date", "open", "close"],
        ),
        (
            "adj_factor",
            "ts_code,trade_date,adj_factor",
            ["ts_code", "trade_date", "adj_factor"],
        ),
    ]:
        calls.append(
            {
                "call_id": f"{api_family}_first_delisted_terminal_window",
                "component_id": "terminal_delisting_return",
                "api_family": api_family,
                "method": api_family,
                "kwargs_from_context": "first_delisted_terminal_window",
                "kwargs": {
                    "fields": fields,
                },
                "required_fields": required_fields,
            }
        )
    calls.append(
        {
            "call_id": "index_member_all_sw_shape",
            "component_id": "industry_taxonomy_history",
            "api_family": "index_member_all",
            "method": "index_member_all",
            "kwargs": {
                "fields": "index_code,con_code,in_date,out_date",
            },
            "required_fields": ["index_code", "con_code", "in_date", "out_date"],
        }
    )
    return calls


def get_tushare_client() -> Any:
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required before A-long route validation network calls")
    import tushare as ts  # type: ignore

    try:
        from tushare.pro.client import DataApi  # type: ignore

        attr = "_DataApi__http_url"
        if hasattr(DataApi, attr):
            setattr(DataApi, attr, os.environ.get("TUSHARE_BASE_URL", "https://api.tushare.pro/dataapi"))
    except Exception:
        # The validation packet is about provider field presence, not the pin helper itself.
        pass
    ts.set_token(token)
    return ts.pro_api()


def first_non_empty(records: list[dict[str, Any]], key: str) -> str | None:
    for row in records:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def latest_delisted_symbol(records: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    candidates: list[tuple[str, str]] = []
    for row in records:
        ts_code = row.get("ts_code")
        delist_date = row.get("delist_date")
        if not ts_code or not delist_date:
            continue
        value = str(delist_date)
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError:
            continue
        candidates.append((str(ts_code), value))
    if not candidates:
        return None, None
    return max(candidates, key=lambda item: item[1])


def terminal_window_kwargs(context: dict[str, Any]) -> dict[str, str] | None:
    ts_code = context.get("first_delisted_ts_code")
    delist_date = context.get("first_delisted_delist_date")
    if not ts_code or not delist_date:
        return None
    try:
        end_dt = datetime.strptime(str(delist_date), "%Y%m%d")
    except ValueError:
        return None
    start_dt = end_dt - timedelta(days=30)
    return {
        "ts_code": str(ts_code),
        "start_date": start_dt.strftime("%Y%m%d"),
        "end_date": end_dt.strftime("%Y%m%d"),
    }


def execute_call(
    pro: Any,
    call: dict[str, Any],
    raw_root: Path,
    context: dict[str, Any],
    call_index: int,
) -> dict[str, Any]:
    kwargs = dict(call.get("kwargs") or {})
    if call.get("kwargs_from_context") == "first_l2_index_code":
        index_code = context.get("first_l2_index_code")
        if not index_code:
            raw_ref = write_raw_payload(
                raw_root,
                call["call_id"],
                {
                    "call_status": "skipped",
                    "reason": "first_l2_index_code unavailable from index_classify L2",
                },
            )
            return {
                "call_id": call["call_id"],
                "component_id": call["component_id"],
                "api_family": call["api_family"],
                "request_shape_without_token": dict(kwargs),
                "call_status": "skipped",
                "row_count": 0,
                "columns": [],
                "required_fields_present": [],
                "required_fields_missing": list(call["required_fields"]),
                "raw_payload_ref": raw_ref,
                "tracked_summary_excludes_raw_rows": True,
                "error_class": None,
                "error_message_redacted": "first_l2_index_code unavailable",
            }
        kwargs["index_code"] = str(index_code)
    elif call.get("kwargs_from_context") == "first_delisted_terminal_window":
        dynamic = terminal_window_kwargs(context)
        if dynamic is None:
            raw_ref = write_raw_payload(
                raw_root,
                call["call_id"],
                {
                    "call_status": "skipped",
                    "reason": "first delisted ts_code/delist_date unavailable from stock_basic D",
                },
            )
            return {
                "call_id": call["call_id"],
                "component_id": call["component_id"],
                "api_family": call["api_family"],
                "request_shape_without_token": dict(kwargs),
                "call_status": "skipped",
                "row_count": 0,
                "columns": [],
                "required_fields_present": [],
                "required_fields_missing": list(call["required_fields"]),
                "raw_payload_ref": raw_ref,
                "tracked_summary_excludes_raw_rows": True,
                "error_class": None,
                "error_message_redacted": "first delisted ts_code/delist_date unavailable",
            }
        kwargs.update(dynamic)

    method = getattr(pro, call["method"])
    request_shape_without_token = dict(kwargs)
    try:
        value = method(**kwargs)
        columns, row_count, records = normalize_records(value)
        required = list(call["required_fields"])
        present = [field for field in required if field in columns]
        missing = [field for field in required if field not in columns]
        status = "success" if row_count and row_count > 0 else "empty"
        raw_ref = write_raw_payload(
            raw_root,
            call["call_id"],
            {
                "call_id": call["call_id"],
                "api_family": call["api_family"],
                "request_shape_without_token": request_shape_without_token,
                "call_status": status,
                "row_count": row_count,
                "columns": columns,
                "records": records,
            },
        )
        if call.get("save_context") == "first_l2_index_code":
            context["first_l2_index_code"] = first_non_empty(records, "index_code")
        elif call.get("save_context") == "first_delisted_symbol":
            ts_code, delist_date = latest_delisted_symbol(records)
            context["first_delisted_ts_code"] = ts_code
            context["first_delisted_delist_date"] = delist_date
        return {
            "call_id": call["call_id"],
            "component_id": call["component_id"],
            "api_family": call["api_family"],
            "request_shape_without_token": request_shape_without_token,
            "call_status": status,
            "row_count": row_count,
            "columns": columns,
            "required_fields_present": present,
            "required_fields_missing": missing,
            "raw_payload_ref": raw_ref,
            "tracked_summary_excludes_raw_rows": True,
            "error_class": None,
            "error_message_redacted": None,
        }
    except Exception as exc:
        raw_ref = write_raw_payload(
            raw_root,
            call["call_id"],
            {
                "call_id": call["call_id"],
                "api_family": call["api_family"],
                "request_shape_without_token": request_shape_without_token,
                "call_status": "error",
                "error_class": type(exc).__name__,
                "error_message_redacted": redact_error(exc),
            },
        )
        return {
            "call_id": call["call_id"],
            "component_id": call["component_id"],
            "api_family": call["api_family"],
            "request_shape_without_token": request_shape_without_token,
            "call_status": "error",
            "row_count": None,
            "columns": [],
            "required_fields_present": [],
            "required_fields_missing": list(call["required_fields"]),
            "raw_payload_ref": raw_ref,
            "tracked_summary_excludes_raw_rows": True,
            "error_class": type(exc).__name__,
            "error_message_redacted": redact_error(exc),
        }


def endpoint_components(call: dict[str, Any]) -> list[str]:
    return [call["component_id"], *list(call.get("also_component_ids") or [])]


def component_rollup(results: list[dict[str, Any]], calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_call = {result["call_id"]: result for result in results}
    out: list[dict[str, Any]] = []
    for component_id in COMPONENTS:
        component_call_ids = [
            call["call_id"]
            for call in calls
            if component_id in endpoint_components(call)
        ]
        component_results = [by_call[call_id] for call_id in component_call_ids if call_id in by_call]
        missing = sorted(
            {
                field
                for result in component_results
                for field in result.get("required_fields_missing", [])
            }
        )
        success_count = sum(1 for result in component_results if result["call_status"] == "success")
        total = len(component_results)
        status = (
            "passed_field_presence"
            if total > 0
            and success_count == total
            and not missing
            else "partial_or_failed_field_presence"
            if total > 0
            else "not_tested"
        )
        plain = (
            "小样本字段存在。"
            if status == "passed_field_presence"
            else "小样本字段不完整或接口失败，不能继续放大。"
            if status == "partial_or_failed_field_presence"
            else "本组件未测试。"
        )
        out.append(
            {
                "component_id": component_id,
                "status": status,
                "calls_total": total,
                "calls_success": success_count,
                "missing_required_fields": missing,
                "plain_result": plain,
            }
        )
    return out


def build_summary(
    *,
    results: list[dict[str, Any]],
    calls: list[dict[str, Any]],
    generated_at: str,
    raw_root: Path,
    summary_path: Path,
    environment_precheck_passed: bool,
    network_call_attempted: bool,
) -> dict[str, Any]:
    rollup = component_rollup(results, calls)
    passed = all(item["status"] == "passed_field_presence" for item in rollup)
    if not environment_precheck_passed:
        status = "not_executed_environment_missing"
        plain_result = "没有跑数据：缺 Tushare 环境。"
        next_action = "补齐 TUSHARE_TOKEN 后，按同一 runner 重新执行小范围 route-validation。"
    elif passed:
        status = "passed_field_presence_only"
        plain_result = "小范围 Tushare 字段验证通过，但数据还不能用于找 alpha。"
        next_action = "下一步才是 reviewed incremental materialization packet；仍不能直接全量抓取或信号搜索。"
    else:
        status = "partial_or_failed_field_presence"
        plain_result = "小范围 Tushare 字段验证不完整；A 股长线仍不能找 alpha。"
        next_action = "先修 route 或决定是否换/补数据源；不要放大抓取或重跑审计。"
    return {
        "schema_name": "a_long_tushare_route_validation_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_tushare_route_validation_execution_summary_20260604",
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_tushare_route_validation_execution",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "route_validation_only": True,
            "field_presence_only": True,
            "provider_family": "tushare_existing_account",
            "provider_call_executed": network_call_attempted,
            "tushare_call_executed": network_call_attempted,
            "data_fetch_executed": network_call_attempted,
            "raw_payload_written_to_gitignored_path": network_call_attempted,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_secret": False,
            "full_materialization_executed": False,
            "audit_rerun_executed": False,
            "signal_search_executed": False,
            "alpha_backtest_executed": False,
            "datahub_allowed": False,
            "production_use_allowed": False,
            "ship_gate_claim_allowed": False,
            "full_size_manual_use_allowed": False,
            "broker_or_order_automation_allowed": False,
            "manual_order_only": True,
        },
        "execution": {
            "route_plan_ref": "docs/a_long_tushare_data_route_repair_plan_20260603.json",
            "summary_path": "docs/a_long_tushare_route_validation_execution_summary_20260604.json",
            "raw_output_root": "data/a_long/raw/tushare/route_validation_20260604/",
            "raw_output_root_is_gitignored": True,
            "max_total_calls": MAX_TOTAL_CALLS,
            "planned_call_count": len(calls),
            "actual_call_count": len(results),
            "budget_exceeded": False,
            "network_call_attempted": network_call_attempted,
            "environment_precheck_passed": environment_precheck_passed,
            "token_logged": False,
            "request_url_logged": False,
        },
        "sample_boundary": {
            "active_symbols": list(ACTIVE_SYMBOLS),
            "fundamental_period": FUNDAMENTAL_PERIOD,
            "price_window": {
                "start_date": PRICE_START_DATE,
                "end_date": PRICE_END_DATE,
            },
            "benchmark_index": BENCHMARK_INDEX,
            "sw_index_member_selection_rule": "index_member_all_endpoint_for_membership_shape_only",
            "full_market_materialization_allowed": False,
            "signal_universe_build_allowed": False,
        },
        "endpoint_results": results,
        "component_rollup": rollup,
        "decision": {
            "route_validation_status": status,
            "data_can_be_used_now": False,
            "signal_search_allowed_by_this_summary": False,
            "full_materialization_allowed_by_this_summary": False,
            "plain_result": plain_result,
            "next_action": next_action,
        },
        "prohibited_claims": {
            "a_long_data_ready": False,
            "a_long_alpha_found": False,
            "signal_search_authorized": False,
            "full_materialization_authorized": False,
            "audit_rerun_authorized": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "provider_selected": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "limitations": [
            "This is a tiny route-validation execution, not 2018-2025 materialization.",
            "Tracked summary records endpoint shape and field presence only; raw rows stay under gitignored data/a_long/raw/.",
            "A pass only means the next reviewed materialization packet can be designed; it does not make A-long data ready.",
            "No signal search, alpha backtest, audit rerun, production use, ship-gate claim, full-size use, or broker/order automation is authorized.",
        ],
    }


def execute_route_validation(
    *,
    pro_factory: Callable[[], Any] = get_tushare_client,
    raw_root: Path = RAW_ROOT,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
    dry_run_env: bool = False,
) -> dict[str, Any]:
    validate_route_plan()
    validate_raw_root(raw_root)
    calls = call_plan()
    if len(calls) > MAX_TOTAL_CALLS:
        raise ValueError("planned route-validation calls exceed max budget")
    generated = generated_at or iso_now()

    if dry_run_env:
        token_present = bool(os.environ.get("TUSHARE_TOKEN"))
        summary = build_summary(
            results=[],
            calls=calls,
            generated_at=generated,
            raw_root=raw_root,
            summary_path=summary_path,
            environment_precheck_passed=token_present,
            network_call_attempted=False,
        )
        write_json_atomic(summary, summary_path)
        return summary

    if pro_factory is get_tushare_client and not os.environ.get("TUSHARE_TOKEN"):
        summary = build_summary(
            results=[],
            calls=calls,
            generated_at=generated,
            raw_root=raw_root,
            summary_path=summary_path,
            environment_precheck_passed=False,
            network_call_attempted=False,
        )
        write_json_atomic(summary, summary_path)
        return summary

    pro = pro_factory()
    results: list[dict[str, Any]] = []
    context: dict[str, Any] = {}
    for index, call in enumerate(calls, start=1):
        if index > MAX_TOTAL_CALLS:
            raise ValueError("route-validation call budget exceeded")
        results.append(execute_call(pro, call, raw_root, context, index))
    summary = build_summary(
        results=results,
        calls=calls,
        generated_at=generated,
        raw_root=raw_root,
        summary_path=summary_path,
        environment_precheck_passed=True,
        network_call_attempted=True,
    )
    write_json_atomic(summary, summary_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = execute_route_validation(
        raw_root=args.raw_root,
        summary_path=args.summary_path,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
    )
    decision = summary["decision"]
    print(
        json.dumps(
            {
                "route_validation_status": decision["route_validation_status"],
                "plain_result": decision["plain_result"],
                "next_action": decision["next_action"],
                "actual_call_count": summary["execution"]["actual_call_count"],
                "summary_path": summary["execution"]["summary_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
