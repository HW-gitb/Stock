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

from runners import a_long_tushare_route_validation_packet as base


PRIOR_SUMMARY_PATH = ROOT / "docs" / "a_long_tushare_route_validation_execution_summary_20260604.json"
SUMMARY_PATH = ROOT / "docs" / "a_long_tushare_route_gap_repair_execution_summary_20260604.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/route_gap_repair_20260604")
RAW_ROOT = ROOT / RAW_ROOT_REL
MAX_TOTAL_CALLS = 8
REPAIR_TARGETS = ["industry_taxonomy_history", "terminal_delisting_return"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the narrow A-long Tushare route-gap repair packet. This checks only "
            "SW membership field mapping and older-delisted terminal price coverage."
        )
    )
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument("--dry-run-env", action="store_true", help="Write an env-only no-call summary.")
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


def validate_prior_summary(path: Path = PRIOR_SUMMARY_PATH) -> dict[str, Any]:
    summary = read_json(path)
    if summary.get("schema_name") != "a_long_tushare_route_validation_execution_summary":
        raise ValueError("prior A-long route-validation summary schema_name mismatch")
    decision = summary.get("decision") or {}
    if decision.get("route_validation_status") != "partial_or_failed_field_presence":
        raise ValueError("prior summary must be the partial route-validation result")
    failed = {
        item.get("component_id")
        for item in summary.get("component_rollup", [])
        if item.get("status") != "passed_field_presence"
    }
    if failed != set(REPAIR_TARGETS):
        raise ValueError("prior summary failed components must match the narrow repair targets")
    return summary


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
    return "data/a_long/raw/" in lines or "data/a_long/raw/tushare/" in lines or normalized in lines


def validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_ROOT_REL).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError("raw output must stay under data/a_long/raw/tushare/route_gap_repair_20260604/") from exc
    if not path_is_gitignored_by_policy(raw_root):
        raise ValueError("raw output root is not protected by .gitignore policy")


def raw_payload_path(raw_root: Path, call_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in call_id)
    return raw_root / f"{safe}.json"


def write_raw_payload(raw_root: Path, call_id: str, payload: dict[str, Any]) -> str:
    path = raw_payload_path(raw_root, call_id)
    write_json_atomic(payload, path)
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def normalize_records(value: Any) -> tuple[list[str], int | None, list[dict[str, Any]]]:
    return base.normalize_records(value)


def call_status(row_count: int | None) -> str:
    return "success" if row_count and row_count > 0 else "empty"


def execute_call(
    pro: Any,
    *,
    call_id: str,
    component_id: str,
    api_family: str,
    method: str,
    kwargs: dict[str, Any],
    required_fields: list[str],
    mapped_field_roles: dict[str, str] | None = None,
    raw_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    request_shape_without_token = dict(kwargs)
    try:
        value = getattr(pro, method)(**kwargs)
        columns, row_count, records = normalize_records(value)
        present = [field for field in required_fields if field in columns]
        missing = [field for field in required_fields if field not in columns]
        status = call_status(row_count)
        raw_ref = write_raw_payload(
            raw_root,
            call_id,
            {
                "call_id": call_id,
                "api_family": api_family,
                "request_shape_without_token": request_shape_without_token,
                "call_status": status,
                "row_count": row_count,
                "columns": columns,
                "records": records,
            },
        )
        return (
            {
                "call_id": call_id,
                "component_id": component_id,
                "api_family": api_family,
                "request_shape_without_token": request_shape_without_token,
                "call_status": status,
                "row_count": row_count,
                "columns": columns,
                "required_fields_present": present,
                "required_fields_missing": missing,
                "mapped_field_roles": mapped_field_roles or {},
                "raw_payload_ref": raw_ref,
                "tracked_summary_excludes_raw_rows": True,
                "error_class": None,
                "error_message_redacted": None,
            },
            records,
        )
    except Exception as exc:
        raw_ref = write_raw_payload(
            raw_root,
            call_id,
            {
                "call_id": call_id,
                "api_family": api_family,
                "request_shape_without_token": request_shape_without_token,
                "call_status": "error",
                "error_class": type(exc).__name__,
                "error_message_redacted": base.redact_error(exc),
            },
        )
        return (
            {
                "call_id": call_id,
                "component_id": component_id,
                "api_family": api_family,
                "request_shape_without_token": request_shape_without_token,
                "call_status": "error",
                "row_count": None,
                "columns": [],
                "required_fields_present": [],
                "required_fields_missing": list(required_fields),
                "mapped_field_roles": mapped_field_roles or {},
                "raw_payload_ref": raw_ref,
                "tracked_summary_excludes_raw_rows": True,
                "error_class": type(exc).__name__,
                "error_message_redacted": base.redact_error(exc),
            },
            [],
        )


def select_older_delisted_sample(records: list[dict[str, Any]]) -> dict[str, str] | None:
    candidates: list[dict[str, str]] = []
    for row in records:
        ts_code = row.get("ts_code")
        delist_date = row.get("delist_date")
        if not ts_code or not delist_date:
            continue
        value = str(delist_date)
        try:
            parsed = datetime.strptime(value, "%Y%m%d")
        except ValueError:
            continue
        if datetime(2020, 1, 1) <= parsed <= datetime(2023, 12, 31):
            candidates.append({"ts_code": str(ts_code), "delist_date": value})
    if not candidates:
        return None
    return max(candidates, key=lambda item: item["delist_date"])


def terminal_window(sample: dict[str, str]) -> tuple[str, str]:
    end_dt = datetime.strptime(sample["delist_date"], "%Y%m%d")
    start_dt = end_dt - timedelta(days=90)
    return start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d")


def component_rollup(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for component_id in REPAIR_TARGETS:
        component_results = [item for item in results if item["component_id"] == component_id]
        missing = sorted({field for item in component_results for field in item.get("required_fields_missing", [])})
        success_count = sum(1 for item in component_results if item["call_status"] == "success")
        total = len(component_results)
        status = (
            "passed_field_presence"
            if total > 0 and success_count == total and not missing
            else "partial_or_failed_field_presence"
            if total > 0
            else "not_tested"
        )
        plain = (
            "Small repair sample fields are present."
            if status == "passed_field_presence"
            else "Repair sample fields are incomplete or the endpoint returned no rows."
            if status == "partial_or_failed_field_presence"
            else "This repair target was not tested."
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
    generated_at: str,
    environment_precheck_passed: bool,
    network_call_attempted: bool,
    planned_call_count: int,
) -> dict[str, Any]:
    rollup = component_rollup(results)
    passed = all(item["status"] == "passed_field_presence" for item in rollup)
    if not environment_precheck_passed:
        status = "not_executed_environment_missing"
        plain_result = "No data call ran because the Tushare environment was missing."
        next_action = "Set TUSHARE_TOKEN and rerun this narrow route-gap repair packet."
    elif passed:
        status = "passed_route_gap_field_presence_only"
        plain_result = "两个路线缺口的小样本修复验证通过，但 A 股长线数据仍不能直接用来找 alpha。"
        next_action = "下一步才是 reviewed incremental materialization packet；之后还要重新跑数据完整性 audit。"
    else:
        status = "partial_or_failed_route_gap_repair"
        plain_result = "两个路线缺口仍未完全修好；A 股长线仍不能找 alpha。"
        next_action = "先修失败的 route gap；不要 full materialize、重跑 audit 或开始 signal search。"
    return {
        "schema_name": "a_long_tushare_route_gap_repair_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_tushare_route_gap_repair_execution_summary_20260604",
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_tushare_route_gap_repair_execution",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "route_gap_repair_only": True,
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
            "prior_summary_ref": "docs/a_long_tushare_route_validation_execution_summary_20260604.json",
            "summary_path": "docs/a_long_tushare_route_gap_repair_execution_summary_20260604.json",
            "raw_output_root": "data/a_long/raw/tushare/route_gap_repair_20260604/",
            "raw_output_root_is_gitignored": True,
            "max_total_calls": MAX_TOTAL_CALLS,
            "planned_call_count": planned_call_count,
            "actual_call_count": len(results),
            "budget_exceeded": False,
            "network_call_attempted": network_call_attempted,
            "environment_precheck_passed": environment_precheck_passed,
            "token_logged": False,
            "request_url_logged": False,
        },
        "repair_targets": list(REPAIR_TARGETS),
        "endpoint_results": results,
        "component_rollup": rollup,
        "decision": {
            "gap_repair_status": status,
            "data_can_be_used_now": False,
            "materialization_allowed_by_this_summary": False,
            "signal_search_allowed_by_this_summary": False,
            "plain_result": plain_result,
            "next_action": next_action,
        },
        "prohibited_claims": {
            "a_long_data_ready": False,
            "a_long_alpha_found": False,
            "route_fully_validated_for_materialization": False,
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
            "This repairs only two route-validation gaps with tiny samples.",
            "Tracked summary records endpoint shape and field presence only; raw rows stay under gitignored data/a_long/raw/.",
            "A pass only allows the next reviewed materialization packet to be designed; it does not make A-long data ready.",
            "No signal search, alpha backtest, audit rerun, production use, ship-gate claim, full-size use, or broker/order automation is authorized.",
        ],
    }


def execute_route_gap_repair(
    *,
    pro_factory: Callable[[], Any] = base.get_tushare_client,
    raw_root: Path = RAW_ROOT,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
    dry_run_env: bool = False,
) -> dict[str, Any]:
    validate_prior_summary()
    validate_raw_root(raw_root)
    generated = generated_at or iso_now()
    planned_call_count = 5

    if dry_run_env:
        token_present = bool(os.environ.get("TUSHARE_TOKEN"))
        summary = build_summary(
            results=[],
            generated_at=generated,
            environment_precheck_passed=token_present,
            network_call_attempted=False,
            planned_call_count=planned_call_count,
        )
        write_json_atomic(summary, summary_path)
        return summary

    if pro_factory is base.get_tushare_client and not os.environ.get("TUSHARE_TOKEN"):
        summary = build_summary(
            results=[],
            generated_at=generated,
            environment_precheck_passed=False,
            network_call_attempted=False,
            planned_call_count=planned_call_count,
        )
        write_json_atomic(summary, summary_path)
        return summary

    pro = pro_factory()
    results: list[dict[str, Any]] = []

    result, _ = execute_call(
        pro,
        call_id="index_classify_sw_L2_repair_context",
        component_id="industry_taxonomy_history",
        api_family="index_classify",
        method="index_classify",
        kwargs={"level": "L2", "fields": "index_code,industry_name,level,parent_code"},
        required_fields=["index_code", "level"],
        raw_root=raw_root,
    )
    results.append(result)

    result, _ = execute_call(
        pro,
        call_id="index_member_all_current_field_mapping",
        component_id="industry_taxonomy_history",
        api_family="index_member_all",
        method="index_member_all",
        kwargs={"fields": "ts_code,name,l1_code,l1_name,l2_code,l2_name,in_date,out_date,is_new"},
        required_fields=["ts_code", "l2_code", "in_date", "out_date"],
        mapped_field_roles={
            "member_symbol": "ts_code",
            "industry_code": "l2_code",
            "industry_name": "l2_name",
            "effective_start": "in_date",
            "effective_end": "out_date",
        },
        raw_root=raw_root,
    )
    results.append(result)

    result, delisted_records = execute_call(
        pro,
        call_id="stock_basic_delisted_D_older_sample_selector",
        component_id="terminal_delisting_return",
        api_family="stock_basic",
        method="stock_basic",
        kwargs={
            "exchange": "",
            "list_status": "D",
            "fields": "ts_code,symbol,name,exchange,market,list_status,list_date,delist_date",
        },
        required_fields=["ts_code", "list_status", "delist_date"],
        raw_root=raw_root,
    )
    results.append(result)

    sample = select_older_delisted_sample(delisted_records)
    if sample is None:
        for api_family, required_fields in [
            ("daily", ["ts_code", "trade_date", "open", "close"]),
            ("adj_factor", ["ts_code", "trade_date", "adj_factor"]),
        ]:
            raw_ref = write_raw_payload(
                raw_root,
                f"{api_family}_older_delisted_terminal_window",
                {
                    "call_status": "skipped",
                    "reason": "no delisted sample with delist_date between 20200101 and 20231231",
                },
            )
            results.append(
                {
                    "call_id": f"{api_family}_older_delisted_terminal_window",
                    "component_id": "terminal_delisting_return",
                    "api_family": api_family,
                    "request_shape_without_token": {},
                    "call_status": "skipped",
                    "row_count": 0,
                    "columns": [],
                    "required_fields_present": [],
                    "required_fields_missing": required_fields,
                    "mapped_field_roles": {},
                    "raw_payload_ref": raw_ref,
                    "tracked_summary_excludes_raw_rows": True,
                    "error_class": None,
                    "error_message_redacted": "no older delisted sample available",
                }
            )
    else:
        start_date, end_date = terminal_window(sample)
        for api_family, fields, required_fields in [
            ("daily", "ts_code,trade_date,open,close", ["ts_code", "trade_date", "open", "close"]),
            ("adj_factor", "ts_code,trade_date,adj_factor", ["ts_code", "trade_date", "adj_factor"]),
        ]:
            result, _ = execute_call(
                pro,
                call_id=f"{api_family}_older_delisted_terminal_window",
                component_id="terminal_delisting_return",
                api_family=api_family,
                method=api_family,
                kwargs={
                    "ts_code": sample["ts_code"],
                    "start_date": start_date,
                    "end_date": end_date,
                    "fields": fields,
                },
                required_fields=required_fields,
                raw_root=raw_root,
            )
            results.append(result)

    if len(results) > MAX_TOTAL_CALLS:
        raise ValueError("route-gap repair call budget exceeded")

    summary = build_summary(
        results=results,
        generated_at=generated,
        environment_precheck_passed=True,
        network_call_attempted=True,
        planned_call_count=planned_call_count,
    )
    write_json_atomic(summary, summary_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = execute_route_gap_repair(
        raw_root=args.raw_root,
        summary_path=args.summary_path,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
    )
    decision = summary["decision"]
    print(
        json.dumps(
            {
                "gap_repair_status": decision["gap_repair_status"],
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
