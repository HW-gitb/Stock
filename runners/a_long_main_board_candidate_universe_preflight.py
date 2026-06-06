from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.data.a_share_board_scope import is_main_board_ts_code
from runners import a_long_tushare_route_validation_packet as route_base
from runners import a_long_tushare_incremental_materialization_packet as raw_base


SUMMARY_PATH = ROOT / "docs" / "a_long_main_board_candidate_universe_preflight_execution_summary_20260604.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/main_board_candidate_universe_preflight_20260604")
RAW_ROOT = ROOT / RAW_ROOT_REL
SOURCE_RAW_ROOT = ROOT / "data" / "a_long" / "raw" / "tushare" / "materialization_full_period_panel_20260604"
SCHEMA_PATH = ROOT / "schemas" / "a_long_main_board_candidate_universe_preflight_execution_summary.schema.json"

START_DATE = "20180101"
END_DATE = "20251231"
MAX_TOTAL_CALLS = 4
MISSING_ACTIVE_PROBE_SYMBOL = "000004.SZ"
PRESENT_ACTIVE_PROBE_SYMBOL = "000001.SZ"
L2_INDEX_CODE_PROBE = "801010.SI"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight the A-long main-board candidate universe before any full alpha run. "
            "This records whether the current free Tushare SW industry route covers the full main-board "
            "candidate universe. Raw probe payloads stay under gitignored data/a_long/raw/."
        )
    )
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--source-raw-root", type=Path, default=SOURCE_RAW_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument("--dry-run-env", action="store_true", help="Write env-only summary without Tushare calls.")
    parser.add_argument(
        "--confirm-independent-review-pass",
        action="store_true",
        help="Required for live execution; confirms the preregistration review passed.",
    )
    parser.add_argument(
        "--confirm-post-review-execute",
        action="store_true",
        help="Required for live execution; confirms the user issued execute.",
    )
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(payload: Any, path: Path) -> None:
    raw_base.write_json_atomic(payload, path)


def validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_ROOT_REL).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError("raw output must stay under data/a_long/raw/tushare/main_board_candidate_universe_preflight_20260604/") from exc
    if not raw_base.path_is_gitignored_by_policy(raw_root):
        raise ValueError("raw output root is not protected by .gitignore policy")


def validate_source_raw_root(source_raw_root: Path) -> None:
    required = [
        "stock_basic_active_L.json",
        "stock_basic_delisted_D.json",
        "index_member_all_sw_membership.json",
    ]
    missing = [name for name in required if not (source_raw_root / name).exists()]
    if missing:
        raise FileNotFoundError(f"candidate-universe preflight source raw files missing: {missing}")


def require_live_confirmations(
    *,
    dry_run_env: bool,
    confirm_independent_review_pass: bool,
    confirm_post_review_execute: bool,
) -> None:
    if dry_run_env:
        return
    if not confirm_independent_review_pass:
        raise RuntimeError("live execution requires --confirm-independent-review-pass")
    if not confirm_post_review_execute:
        raise RuntimeError("live execution requires --confirm-post-review-execute")


def raw_records(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    value = payload.get("records")
    if not isinstance(value, list):
        raise ValueError(f"raw payload records missing: {path}")
    return [row for row in value if isinstance(row, dict)]


def main_board_delisted_in_window(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in records:
        ts_code = str(row.get("ts_code") or "")
        list_date = str(row.get("list_date") or "")
        delist_date = str(row.get("delist_date") or "")
        if not ts_code or not is_main_board_ts_code(ts_code):
            continue
        if list_date and list_date > END_DATE:
            continue
        if delist_date and delist_date >= START_DATE:
            out.append(row)
    return out


def build_universe_metrics(source_raw_root: Path) -> dict[str, Any]:
    active = raw_records(source_raw_root / "stock_basic_active_L.json")
    delisted = raw_records(source_raw_root / "stock_basic_delisted_D.json")
    membership = raw_records(source_raw_root / "index_member_all_sw_membership.json")

    main_active = [row for row in active if is_main_board_ts_code(row.get("ts_code"))]
    main_delisted = main_board_delisted_in_window(delisted)
    member_codes = {str(row.get("ts_code")) for row in membership if row.get("ts_code")}

    active_missing = [str(row.get("ts_code")) for row in main_active if str(row.get("ts_code")) not in member_codes]
    delisted_missing = [str(row.get("ts_code")) for row in main_delisted if str(row.get("ts_code")) not in member_codes]
    active_with_sw_count = len(main_active) - len(active_missing)

    return {
        "source_raw_root": "data/a_long/raw/tushare/materialization_full_period_panel_20260604/",
        "start_date": START_DATE,
        "end_date": END_DATE,
        "stock_basic_active_rows": len(active),
        "main_board_active_count": len(main_active),
        "stock_basic_delisted_rows": len(delisted),
        "main_board_delisted_2018_2025_count": len(main_delisted),
        "current_sw_membership_rows": len(membership),
        "active_with_sw_membership_count": active_with_sw_count,
        "active_missing_sw_membership_count": len(active_missing),
        "active_missing_sw_membership_examples": active_missing[:20],
        "delisted_missing_sw_membership_count": len(delisted_missing),
        "delisted_missing_sw_membership_examples": delisted_missing[:40],
        "main_board_active_sw_coverage_pct": round(active_with_sw_count * 100.0 / len(main_active), 6) if main_active else 0.0,
    }


def probe_call_plan() -> list[dict[str, Any]]:
    fields = "ts_code,name,l1_code,l1_name,l2_code,l2_name,in_date,out_date,is_new"
    return [
        {
            "call_id": "index_member_all_l2_index_code_probe",
            "api_family": "index_member_all",
            "method": "index_member_all",
            "kwargs": {"index_code": L2_INDEX_CODE_PROBE, "fields": fields},
            "probe_kind": "l2_index_code_filter",
            "target_symbol": None,
        },
        {
            "call_id": "index_member_all_missing_active_ts_code_probe",
            "api_family": "index_member_all",
            "method": "index_member_all",
            "kwargs": {"ts_code": MISSING_ACTIVE_PROBE_SYMBOL, "fields": fields},
            "probe_kind": "missing_active_ts_code_filter",
            "target_symbol": MISSING_ACTIVE_PROBE_SYMBOL,
        },
        {
            "call_id": "index_member_all_present_active_ts_code_probe",
            "api_family": "index_member_all",
            "method": "index_member_all",
            "kwargs": {"ts_code": PRESENT_ACTIVE_PROBE_SYMBOL, "fields": fields},
            "probe_kind": "present_active_ts_code_filter",
            "target_symbol": PRESENT_ACTIVE_PROBE_SYMBOL,
        },
        {
            "call_id": "stock_basic_active_industry_area_probe",
            "api_family": "stock_basic",
            "method": "stock_basic",
            "kwargs": {"exchange": "", "list_status": "L", "fields": "ts_code,name,industry,area"},
            "probe_kind": "stock_basic_active_industry_area_fields",
            "target_symbol": MISSING_ACTIVE_PROBE_SYMBOL,
        },
    ]


def target_match_count(records: list[dict[str, Any]], symbol: str | None) -> int:
    if not symbol:
        return 0
    return sum(1 for row in records if str(row.get("ts_code") or "") == symbol)


def execute_probe(pro: Any, call: dict[str, Any], raw_root: Path) -> dict[str, Any]:
    request_shape_without_token = dict(call["kwargs"])
    try:
        value = getattr(pro, call["method"])(**call["kwargs"])
        columns, row_count, records = route_base.normalize_records(value)
        status = "success" if row_count and row_count > 0 else "empty"
        raw_ref = raw_base.write_raw_payload(
            raw_root,
            call["call_id"],
            {
                "call_id": call["call_id"],
                "api_family": call["api_family"],
                "probe_kind": call["probe_kind"],
                "request_shape_without_token": request_shape_without_token,
                "call_status": status,
                "row_count": row_count,
                "columns": columns,
                "records": records,
            },
        )
        return {
            "call_id": call["call_id"],
            "api_family": call["api_family"],
            "probe_kind": call["probe_kind"],
            "request_shape_without_token": request_shape_without_token,
            "call_status": status,
            "row_count": row_count,
            "columns": columns,
            "target_symbol": call.get("target_symbol"),
            "target_match_count": target_match_count(records, call.get("target_symbol")),
            "raw_payload_ref": raw_ref,
            "tracked_summary_excludes_raw_rows": True,
            "error_class": None,
            "error_message_redacted": None,
        }
    except Exception as exc:
        raw_ref = raw_base.write_raw_payload(
            raw_root,
            call["call_id"],
            {
                "call_id": call["call_id"],
                "api_family": call["api_family"],
                "probe_kind": call["probe_kind"],
                "request_shape_without_token": request_shape_without_token,
                "call_status": "error",
                "error_class": type(exc).__name__,
                "error_message_redacted": route_base.redact_error(exc),
            },
        )
        return {
            "call_id": call["call_id"],
            "api_family": call["api_family"],
            "probe_kind": call["probe_kind"],
            "request_shape_without_token": request_shape_without_token,
            "call_status": "error",
            "row_count": None,
            "columns": [],
            "target_symbol": call.get("target_symbol"),
            "target_match_count": 0,
            "raw_payload_ref": raw_ref,
            "tracked_summary_excludes_raw_rows": True,
            "error_class": type(exc).__name__,
            "error_message_redacted": route_base.redact_error(exc),
        }


def build_summary(
    *,
    generated_at: str,
    universe_metrics: dict[str, Any],
    endpoint_results: list[dict[str, Any]],
    environment_precheck_passed: bool,
    independent_review_confirmed: bool,
    post_review_execute_confirmed: bool,
    dry_run_env: bool,
) -> dict[str, Any]:
    actual_call_count = len(endpoint_results)
    any_error = any(item["call_status"] == "error" for item in endpoint_results)
    active_missing = int(universe_metrics.get("active_missing_sw_membership_count") or 0)
    delisted_missing = int(universe_metrics.get("delisted_missing_sw_membership_count") or 0)
    probe_by_kind = {str(item.get("probe_kind")): item for item in endpoint_results}
    missing_active_probe = probe_by_kind.get("missing_active_ts_code_filter") or {}
    stock_basic_probe = probe_by_kind.get("stock_basic_active_industry_area_fields") or {}
    l2_probe = probe_by_kind.get("l2_index_code_filter") or {}
    probe_interpretation = {
        "active_ts_code_filter_can_supplement_missing_sw": int(missing_active_probe.get("target_match_count") or 0) > 0,
        "stock_basic_active_industry_area_available": int(stock_basic_probe.get("target_match_count") or 0) > 0,
        "l2_index_code_filter_not_sufficient_for_pagination": int(l2_probe.get("row_count") or 0) >= 3000,
        "delisted_sw_membership_still_unresolved": delisted_missing > 1,
    }

    if dry_run_env:
        status = "dry_run_environment_ready" if environment_precheck_passed else "not_executed_environment_missing"
        plain_result = "只检查环境，没有执行候选池探测。"
        next_action = "确认 review 和用户 execute 后再运行候选池 preflight。"
    elif not environment_precheck_passed:
        status = "not_executed_environment_missing"
        plain_result = "没有跑候选池探测：缺 TUSHARE_TOKEN。"
        next_action = "补齐 TUSHARE_TOKEN 后再执行；不要直接跑全量 alpha。"
    elif any_error:
        status = "partial_or_failed_candidate_universe_preflight"
        plain_result = "候选池探测有接口错误，主板全量 alpha 不能开跑。"
        next_action = "先修探测接口或记录 provider blocker；不要拉全量 alpha。"
    elif active_missing > 0 or delisted_missing > 1:
        status = "blocked_sw_industry_coverage_for_full_universe_signal_search"
        if probe_interpretation["active_ts_code_filter_can_supplement_missing_sw"]:
            plain_result = (
                f"主板全量现在还不能找 alpha：现有 raw 里 {active_missing} 只活跃主板股缺 SW 行业，"
                f"但单股 ts_code 探测证明活跃缺口可以分批补；{delisted_missing} 只 2018-2025 退市主板股仍缺 SW 行业。"
            )
            next_action = "先合并执行 active SW 分批补齐和退市股无行业边界设计；这两个过审前不要拉全量 alpha。"
        else:
            plain_result = (
                f"主板全量现在不能找 alpha：{active_missing} 只活跃主板股缺 SW 行业，"
                f"{delisted_missing} 只 2018-2025 退市主板股缺 SW 行业。"
            )
            next_action = "先解决行业覆盖口径：找到可覆盖主板的 SW/PIT 行业来源，或新预注册接受降级行业口径；通过前不要拉全量 alpha。"
    else:
        status = "candidate_universe_preflight_passed"
        plain_result = "主板候选池行业覆盖预检通过；可以进入后续全量数据拉取和信号执行包。"
        next_action = "继续按预注册执行全量数据材料化和信号搜索；正结果仍只是研究线索。"

    return {
        "schema_name": "a_long_main_board_candidate_universe_preflight_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_main_board_candidate_universe_preflight_execution_summary_20260604",
        "preregistration_ref": "research/preregistrations/a_long_signal_search_preregistration_20260604.json",
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_main_board_candidate_universe_preflight",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "provider_family": "tushare_existing_account",
            "provider_call_executed": actual_call_count > 0,
            "tushare_call_executed": actual_call_count > 0,
            "data_fetch_executed": actual_call_count > 0,
            "raw_payload_written_to_gitignored_path": actual_call_count > 0,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_secret": False,
            "full_market_materialization_executed": False,
            "full_universe_signal_search_executed": False,
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
            "summary_path": "docs/a_long_main_board_candidate_universe_preflight_execution_summary_20260604.json",
            "raw_output_root": RAW_ROOT_REL.as_posix() + "/",
            "raw_output_root_is_gitignored": True,
            "source_raw_root": universe_metrics["source_raw_root"],
            "max_total_calls": MAX_TOTAL_CALLS,
            "planned_call_count": len(probe_call_plan()),
            "actual_call_count": actual_call_count,
            "budget_exceeded": False,
            "network_call_attempted": actual_call_count > 0,
            "environment_precheck_passed": environment_precheck_passed,
            "independent_review_confirmed": independent_review_confirmed,
            "post_review_execute_confirmed": post_review_execute_confirmed,
            "token_logged": False,
            "request_url_logged": False,
        },
        "candidate_universe": universe_metrics,
        "probe_interpretation": probe_interpretation,
        "endpoint_results": endpoint_results,
        "decision": {
            "preflight_status": status,
            "candidate_universe_ready_for_signal_search": status == "candidate_universe_preflight_passed",
            "data_can_be_used_for_alpha_now": False,
            "signal_search_authorized_by_this_summary": False,
            "full_alpha_run_executed": False,
            "plain_result": plain_result,
            "next_action": next_action,
        },
        "prohibited_claims": {
            "a_long_alpha_found": False,
            "candidate_universe_ready": False,
            "full_universe_ready": False,
            "signal_search_authorized": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "limitations": [
            "This preflight checks the main-board candidate-universe industry coverage before a full alpha run.",
            "It does not compute signals, returns, benchmark excess, or alpha.",
            "Raw probe payloads stay under gitignored data/a_long/raw/; the tracked summary stores counts and shape only.",
            "A pass would not prove alpha. A block means do not start full alpha data pull until the listed data coverage issue is fixed or explicitly re-preregistered.",
        ],
    }


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required for schema-gated preflight outputs; "
            "install project requirements before running this producer."
        ) from exc
    schema = read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
        raise ValueError(f"{schema_path} validation failed: {joined}")


def execute_preflight(
    *,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_ROOT,
    source_raw_root: Path = SOURCE_RAW_ROOT,
    pro_factory: Callable[[], Any] = route_base.get_tushare_client,
    generated_at: str | None = None,
    dry_run_env: bool = False,
    confirm_independent_review_pass: bool = False,
    confirm_post_review_execute: bool = False,
) -> dict[str, Any]:
    validate_source_raw_root(source_raw_root)
    validate_raw_root(raw_root)
    require_live_confirmations(
        dry_run_env=dry_run_env,
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )
    universe_metrics = build_universe_metrics(source_raw_root)
    generated = generated_at or iso_now()
    endpoint_results: list[dict[str, Any]] = []

    if not dry_run_env and pro_factory is route_base.get_tushare_client and not os.environ.get("TUSHARE_TOKEN"):
        summary = build_summary(
            generated_at=generated,
            universe_metrics=universe_metrics,
            endpoint_results=[],
            environment_precheck_passed=False,
            independent_review_confirmed=confirm_independent_review_pass,
            post_review_execute_confirmed=confirm_post_review_execute,
            dry_run_env=False,
        )
        write_json_atomic(summary, summary_path)
        validate_json(SCHEMA_PATH, summary)
        return summary

    if dry_run_env:
        summary = build_summary(
            generated_at=generated,
            universe_metrics=universe_metrics,
            endpoint_results=[],
            environment_precheck_passed=bool(os.environ.get("TUSHARE_TOKEN")),
            independent_review_confirmed=confirm_independent_review_pass,
            post_review_execute_confirmed=confirm_post_review_execute,
            dry_run_env=True,
        )
        write_json_atomic(summary, summary_path)
        validate_json(SCHEMA_PATH, summary)
        return summary

    calls = probe_call_plan()
    if len(calls) > MAX_TOTAL_CALLS:
        raise ValueError("candidate-universe preflight call budget exceeded")
    pro = pro_factory()
    endpoint_results = [execute_probe(pro, call, raw_root) for call in calls]

    summary = build_summary(
        generated_at=generated,
        universe_metrics=universe_metrics,
        endpoint_results=endpoint_results,
        environment_precheck_passed=True,
        independent_review_confirmed=confirm_independent_review_pass,
        post_review_execute_confirmed=confirm_post_review_execute,
        dry_run_env=False,
    )
    write_json_atomic(summary, summary_path)
    validate_json(SCHEMA_PATH, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = execute_preflight(
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        source_raw_root=args.source_raw_root,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
        confirm_independent_review_pass=args.confirm_independent_review_pass,
        confirm_post_review_execute=args.confirm_post_review_execute,
    )
    decision = summary["decision"]
    print(
        "a_long_main_board_candidate_universe_preflight: "
        f"{decision['preflight_status']}; "
        f"ready={decision['candidate_universe_ready_for_signal_search']}; "
        f"active_missing_sw={summary['candidate_universe']['active_missing_sw_membership_count']}; "
        f"delisted_missing_sw={summary['candidate_universe']['delisted_missing_sw_membership_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
