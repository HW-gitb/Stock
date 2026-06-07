from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.data.a_share_board_scope import is_main_board_ts_code
from runners import a_long_large_cap_market_cap_materialization as materialization


PACKET_PATH = ROOT / "docs" / "a_long_large_cap_market_cap_audit_packet_20260607.json"
PACKET_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_market_cap_audit_packet.schema.json"
REPORT_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_market_cap_audit_report.schema.json"
REPORT_PATH = ROOT / "research" / "results" / "a_long_large_cap_market_cap_audit_20260607" / "audit_report.json"
MONTHLY_COVERAGE_PATH = ROOT / "research" / "results" / "a_long_large_cap_market_cap_audit_20260607" / "monthly_coverage.csv"
MATERIALIZATION_SUMMARY_PATH = ROOT / "docs" / "a_long_large_cap_market_cap_materialization_execution_summary_20260607.json"
PREREGISTRATION_PATH = ROOT / "research" / "preregistrations" / "a_long_large_cap_pure_quality_20260607.json"
LEDGER_PATH = ROOT / "research" / "ledgers" / "a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json"
PRIOR_FULL_AUDIT_REPORT_PATH = ROOT / "research" / "results" / "a_long_full_main_board_data_integrity_audit_20260605" / "audit_report.json"
SW_REPAIR_SUMMARY_PATH = ROOT / "docs" / "a_long_main_board_sw_coverage_repair_execution_summary_20260604.json"
MARKET_CAP_RAW_ROOT_REL = Path("data/a_long/raw/tushare/large_cap_market_cap_materialization_20260607")
MARKET_CAP_RAW_ROOT = ROOT / MARKET_CAP_RAW_ROOT_REL
PRIOR_FULL_RAW_ROOT_REL = Path("data/a_long/raw/tushare/full_main_board_signal_search_20260605")
PRIOR_FULL_RAW_ROOT = ROOT / PRIOR_FULL_RAW_ROOT_REL

SELECTED_MARKET_CAP_FIELD = "circ_mv"
UNIVERSE_SIZE_N = 500
MONTHLY_AS_OF_DATES = materialization.MONTHLY_AS_OF_DATES
MIN_SIZE_QUINTILE_COUNT = 50
EXPECTED_ACTIVE_MAIN_BOARD_COUNT = 3200
EXPECTED_DELISTED_MAIN_BOARD_COUNT = 187
EXPECTED_PRIOR_AUDITED_UNIVERSE_COUNT = 3387
SELF_TEST_IDS = [
    "materialization_summary_scope_creep_blocks",
    "missing_raw_ref_blocks",
    "main_board_filter_excludes_non_main_high_caps",
    "sparse_top500_blocks",
    "prior_universe_gap_blocks",
]
CHECK_IDS = [
    "materialization_summary_gate",
    "raw_payload_shape_and_refs",
    "top500_rederivation_consistency",
    "main_board_filter_integrity",
    "prior_full_main_board_universe_bridge",
    "size_quintile_coverage",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the already-materialized A-long large-cap monthly market-cap raw payloads. "
            "This is local-only: no Tushare calls, no signal search, no alpha calculation."
        )
    )
    parser.add_argument("--packet-path", type=Path, default=PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=MATERIALIZATION_SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=MARKET_CAP_RAW_ROOT)
    parser.add_argument("--prior-full-raw-root", type=Path, default=PRIOR_FULL_RAW_ROOT)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--monthly-coverage-path", type=Path, default=MONTHLY_COVERAGE_PATH)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument("--confirm-independent-review-pass", action="store_true")
    parser.add_argument("--confirm-post-review-execute", action="store_true")
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: Any) -> None:
    materialization.write_json_atomic(payload, path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required for A-long schema-gated large-cap market-cap audit; "
            "install project requirements before running this producer."
        ) from exc
    schema = read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
        raise ValueError(f"{schema_path} validation failed: {joined}")


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved).replace("\\", "/")


def _positive_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def resolve_raw_ref(raw_root: Path, raw_ref: str | None) -> Path:
    if not raw_ref:
        raise ValueError("raw_payload_ref is required")
    raw_path = Path(raw_ref)
    path = raw_path.resolve() if raw_path.is_absolute() else (ROOT / raw_path).resolve()
    approved = raw_root.resolve()
    try:
        path.relative_to(approved)
    except ValueError as exc:
        raise ValueError(f"raw payload ref escapes approved root: {raw_ref}") from exc
    if not path.exists():
        raise FileNotFoundError(f"raw payload missing: {raw_ref}")
    return path


def load_and_validate_packet(path: Path = PACKET_PATH) -> dict[str, Any]:
    packet = read_json(path)
    validate_json(PACKET_SCHEMA_PATH, packet)
    if packet.get("schema_name") != "a_long_large_cap_market_cap_audit_packet":
        raise ValueError("audit packet schema_name mismatch")

    scope = packet.get("scope") or {}
    for field in [
        "research_only",
        "ready_for_later_execution_after_independent_review",
        "actual_audit_requires_post_review_execute_command",
        "local_raw_audit_allowed_after_gates",
        "manual_order_only",
    ]:
        if scope.get(field) is not True:
            raise ValueError(f"packet scope.{field} must be true")
    for field in [
        "provider_calls_executed_by_this_artifact",
        "tushare_calls_executed_by_this_artifact",
        "data_fetch_executed_by_this_artifact",
        "raw_payloads_read_by_this_artifact",
        "signal_search_allowed",
        "alpha_backtest_allowed",
        "datahub_allowed",
        "production_use_allowed",
        "ship_gate_claim_allowed",
        "full_size_manual_use_allowed",
        "broker_or_order_automation_allowed",
    ]:
        if scope.get(field) is not False:
            raise ValueError(f"packet scope.{field} must be false")

    inputs = packet.get("input_boundary") or {}
    expected_inputs = {
        "materialization_summary_ref": "docs/a_long_large_cap_market_cap_materialization_execution_summary_20260607.json",
        "market_cap_raw_root": MARKET_CAP_RAW_ROOT_REL.as_posix() + "/",
        "prior_full_main_board_audit_report_ref": "research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json",
        "prior_full_main_board_raw_root": PRIOR_FULL_RAW_ROOT_REL.as_posix() + "/",
        "sw_repair_summary_ref": "docs/a_long_main_board_sw_coverage_repair_execution_summary_20260604.json",
        "preregistration_ref": "research/preregistrations/a_long_large_cap_pure_quality_20260607.json",
        "ledger_ref": "research/ledgers/a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json",
    }
    for key, value in expected_inputs.items():
        if inputs.get(key) != value:
            raise ValueError(f"packet input boundary mismatch: {key}")

    audit_boundary = packet.get("audit_boundary") or {}
    if audit_boundary.get("monthly_as_of_dates") != MONTHLY_AS_OF_DATES:
        raise ValueError("packet monthly_as_of_dates drifted")
    if audit_boundary.get("selected_market_cap_field") != SELECTED_MARKET_CAP_FIELD:
        raise ValueError("packet selected market-cap field must be circ_mv")
    if audit_boundary.get("universe_size_n") != UNIVERSE_SIZE_N:
        raise ValueError("packet universe size drifted")
    if audit_boundary.get("size_bucket_count") != 5:
        raise ValueError("packet size bucket count drifted")
    if audit_boundary.get("minimum_size_bucket_count_for_primary_percentile") != MIN_SIZE_QUINTILE_COUNT:
        raise ValueError("packet size bucket minimum drifted")
    if audit_boundary.get("top500_symbols_written_to_tracked_report") is not False:
        raise ValueError("packet must forbid top500 symbol lists in tracked report")

    check_ids = [item.get("check_id") for item in packet.get("audit_checks", [])]
    if check_ids != CHECK_IDS:
        raise ValueError("packet audit_checks drifted")

    output = packet.get("output_contract") or {}
    if output.get("report_schema_ref") != "schemas/a_long_large_cap_market_cap_audit_report.schema.json":
        raise ValueError("packet report schema ref mismatch")
    if output.get("report_path") != "research/results/a_long_large_cap_market_cap_audit_20260607/audit_report.json":
        raise ValueError("packet report path mismatch")
    if output.get("monthly_coverage_path") != "research/results/a_long_large_cap_market_cap_audit_20260607/monthly_coverage.csv":
        raise ValueError("packet monthly coverage path mismatch")
    for field in [
        "tracked_report_must_not_contain_raw_rows",
        "tracked_report_must_not_contain_top500_symbols",
        "tracked_report_must_not_contain_secret",
        "tracked_report_must_not_contain_request_url",
    ]:
        if output.get(field) is not True:
            raise ValueError(f"packet output.{field} must be true")

    for field, value in (packet.get("pre_execution_gates") or {}).items():
        if value is not True:
            raise ValueError(f"packet gate must stay true: {field}")
    for field, value in (packet.get("prohibited_claims") or {}).items():
        if value is not False:
            raise ValueError(f"packet prohibited claim must stay false: {field}")
    return packet


def validate_materialization_summary(summary: dict[str, Any]) -> None:
    materialization.validate_json(materialization.SUMMARY_SCHEMA_PATH, summary)
    if summary.get("schema_name") != "a_long_large_cap_market_cap_materialization_execution_summary":
        raise ValueError("materialization summary schema_name mismatch")
    scope = summary.get("scope") or {}
    if scope.get("tracked_summary_contains_raw_rows") is not False:
        raise ValueError("materialization summary must not contain raw rows")
    if scope.get("tracked_summary_contains_top500_symbols") is not False:
        raise ValueError("materialization summary must not contain top500 symbols")
    decision = summary.get("decision") or {}
    if decision.get("market_cap_materialization_status") != "passed_market_cap_materialization_shape":
        raise ValueError("market-cap materialization must pass before audit")
    if decision.get("raw_market_cap_materialization_shape_available") is not True:
        raise ValueError("market-cap raw shape must be available before audit")
    if decision.get("audit_rerun_authorized_by_this_summary") is not False:
        raise ValueError("materialization summary must not self-authorize audit")
    if decision.get("signal_search_authorized_by_this_summary") is not False:
        raise ValueError("materialization summary must not authorize signal search")

    execution = summary.get("execution") or {}
    if execution.get("endpoint_results_count") != len(MONTHLY_AS_OF_DATES):
        raise ValueError("materialization endpoint_results_count mismatch")
    if execution.get("token_logged") is not False or execution.get("request_url_logged") is not False:
        raise ValueError("materialization summary must stay no-secret/no-url")

    boundary = summary.get("materialization_boundary") or {}
    if boundary.get("selected_market_cap_field") != SELECTED_MARKET_CAP_FIELD:
        raise ValueError("materialization selected market-cap field mismatch")
    if boundary.get("monthly_as_of_dates") != MONTHLY_AS_OF_DATES:
        raise ValueError("materialization as-of dates drifted")
    if boundary.get("universe_size_n") != UNIVERSE_SIZE_N:
        raise ValueError("materialization universe size drifted")
    if boundary.get("top_500_selection_written_to_tracked_summary") is not False:
        raise ValueError("materialization summary must not carry top500 lists")


def validate_preregistration_and_ledger() -> None:
    prereg = read_json(PREREGISTRATION_PATH)
    ledger = read_json(LEDGER_PATH)
    if prereg.get("scope", {}).get("preregistration_review_status") != "passed_independent_review_ready_for_freeze":
        raise ValueError("large-cap preregistration is not review-passed")
    gate = prereg.get("data_dependency_gate") or {}
    if gate.get("selected_market_cap_field_status") != SELECTED_MARKET_CAP_FIELD:
        raise ValueError("large-cap preregistration must freeze circ_mv")
    if (prereg.get("frozen_design", {}).get("universe_rule") or {}).get("universe_size_n") != UNIVERSE_SIZE_N:
        raise ValueError("large-cap preregistration universe size drifted")
    neutralization = prereg.get("frozen_design", {}).get("neutralization_rule") or {}
    if neutralization.get("size_bucket_count") != 5:
        raise ValueError("large-cap preregistration size bucket count drifted")
    if neutralization.get("minimum_size_bucket_count_for_primary_percentile") != MIN_SIZE_QUINTILE_COUNT:
        raise ValueError("large-cap preregistration size bucket minimum drifted")
    if ledger.get("budget_policy", {}).get("tests_spent_count") != 0:
        raise ValueError("large-cap singleton signal-search ledger must remain unspent before audit")
    if ledger.get("test_spend_log") != []:
        raise ValueError("large-cap singleton signal-search ledger spend log must remain empty before audit")


def validate_prior_full_audit_report() -> None:
    report = read_json(PRIOR_FULL_AUDIT_REPORT_PATH)
    if report.get("schema_name") != "a_long_full_main_board_data_integrity_audit_report":
        raise ValueError("prior full main-board audit schema_name mismatch")
    decision = report.get("decision") or {}
    if decision.get("audit_status") != "passed_full_main_board_data_integrity_for_signal_search":
        raise ValueError("prior full main-board audit must have passed")
    if decision.get("hard_checks_pass") is not True:
        raise ValueError("prior full main-board hard checks must pass")
    if decision.get("signal_search_authorized_by_this_report") is not False:
        raise ValueError("prior full main-board audit must not self-authorize signal search")


def load_prior_audited_universe(prior_raw_root: Path) -> set[str]:
    active_payload = read_json(prior_raw_root / "stock_basic_active_L.json")
    active = {
        str(row.get("ts_code"))
        for row in active_payload.get("records", [])
        if isinstance(row, dict)
        and row.get("list_status") == "L"
        and is_main_board_ts_code(row.get("ts_code"))
    }
    repair = read_json(SW_REPAIR_SUMMARY_PATH)
    delisted = set((repair.get("delisted_no_industry_boundary") or {}).get("no_usable_sw_source_symbols") or [])
    if len(active) != EXPECTED_ACTIVE_MAIN_BOARD_COUNT:
        raise ValueError(f"prior active main-board universe count mismatch: {len(active)}")
    if len(delisted) != EXPECTED_DELISTED_MAIN_BOARD_COUNT:
        raise ValueError(f"prior delisted main-board universe count mismatch: {len(delisted)}")
    universe = active | {str(symbol) for symbol in delisted}
    if len(universe) != EXPECTED_PRIOR_AUDITED_UNIVERSE_COUNT:
        raise ValueError(f"prior audited universe count mismatch: {len(universe)}")
    return universe


def select_top500(records: list[dict[str, Any]]) -> list[tuple[str, float]]:
    selected: list[tuple[float, str]] = []
    for row in records:
        symbol = str(row.get("ts_code") or "")
        value = _positive_float(row.get(SELECTED_MARKET_CAP_FIELD))
        if value is not None and is_main_board_ts_code(symbol):
            selected.append((value, symbol))
    selected.sort(key=lambda item: item[0], reverse=True)
    return [(symbol, value) for value, symbol in selected[:UNIVERSE_SIZE_N]]


def size_quintile_counts(selected: list[tuple[str, float]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for idx in range(5):
        start = idx * 100
        end = (idx + 1) * 100
        counts[f"q{idx + 1}"] = len(selected[start:end])
    return counts


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def audit_monthly_payloads(summary: dict[str, Any], raw_root: Path, prior_universe: set[str]) -> list[dict[str, Any]]:
    monthly_rows: list[dict[str, Any]] = []
    endpoint_results = summary.get("endpoint_results") or []
    if len(endpoint_results) != len(MONTHLY_AS_OF_DATES):
        raise ValueError("materialization endpoint_results length mismatch")

    for result, expected_as_of in zip(endpoint_results, MONTHLY_AS_OF_DATES):
        if result.get("trade_date") != expected_as_of:
            raise ValueError("endpoint result order/as-of drifted")
        raw_path = resolve_raw_ref(raw_root, result.get("raw_payload_ref"))
        payload = read_json(raw_path)
        records = [row for row in payload.get("records", []) if isinstance(row, dict)]
        if payload.get("call_status") != "success":
            raise ValueError(f"raw payload did not succeed: {result.get('call_id')}")
        if set(["ts_code", "trade_date", SELECTED_MARKET_CAP_FIELD]) - set(payload.get("columns", [])):
            raise ValueError(f"raw payload missing required columns: {result.get('call_id')}")

        date_mismatch_count = sum(1 for row in records if str(row.get("trade_date")) != expected_as_of)
        main_board_rows = [row for row in records if is_main_board_ts_code(row.get("ts_code"))]
        positive_main_board = [
            row for row in main_board_rows if _positive_float(row.get(SELECTED_MARKET_CAP_FIELD)) is not None
        ]
        selected = select_top500(records)
        selected_symbols = [symbol for symbol, _value in selected]
        outside_prior = sorted(set(selected_symbols) - prior_universe)
        quintiles = size_quintile_counts(selected)
        selected_values = [value for _symbol, value in selected]

        summary_stats = result.get("top500_main_board_stats") or {}
        selected_min = min(selected_values) if selected_values else None
        selected_max = max(selected_values) if selected_values else None
        summary_mismatch = (
            len(main_board_rows) != summary_stats.get("main_board_row_count")
            or len(positive_main_board) != summary_stats.get("main_board_positive_selected_field_count")
            or len(selected) != summary_stats.get("selected_top500_count")
            or _round(selected_min) != _round(summary_stats.get("top500_min_market_cap"))
            or _round(selected_max) != _round(summary_stats.get("top500_max_market_cap"))
        )
        monthly_rows.append(
            {
                "as_of": expected_as_of,
                "raw_row_count": len(records),
                "summary_row_count": result.get("row_count"),
                "date_mismatch_count": date_mismatch_count,
                "main_board_row_count": len(main_board_rows),
                "positive_main_board_circ_mv_count": len(positive_main_board),
                "selected_top500_count": len(selected),
                "selected_top500_complete": len(selected) == UNIVERSE_SIZE_N,
                "selected_top500_min_circ_mv": _round(selected_min),
                "selected_top500_max_circ_mv": _round(selected_max),
                "summary_rederivation_mismatch": summary_mismatch,
                "outside_prior_audited_universe_count": len(outside_prior),
                "outside_prior_audited_universe_sample": outside_prior[:20],
                "size_q1_count": quintiles["q1"],
                "size_q2_count": quintiles["q2"],
                "size_q3_count": quintiles["q3"],
                "size_q4_count": quintiles["q4"],
                "size_q5_count": quintiles["q5"],
                "minimum_size_quintile_count": min(quintiles.values()),
                "top500_symbols_written_to_tracked_report": False,
            }
        )
    return monthly_rows


def make_check(check_id: str, status: str, metrics: dict[str, Any], findings: list[str]) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "hard_check": True,
        "blocks_signal_search": status != "pass_large_cap_market_cap_audit",
        "metrics": metrics,
        "findings": findings,
        "allowed_followup": (
            "If this check passes with all hard checks, the next separate reviewed step may build a signal-search package."
            if status == "pass_large_cap_market_cap_audit"
            else "Fix or rematerialize the market-cap universe before any signal-search package."
        ),
    }


def checks_from_monthly_rows(summary: dict[str, Any], monthly_rows: list[dict[str, Any]], prior_universe: set[str]) -> list[dict[str, Any]]:
    months = len(monthly_rows)
    complete_months = sum(1 for row in monthly_rows if row["selected_top500_complete"])
    raw_shape_failures = sum(
        1
        for row in monthly_rows
        if row["date_mismatch_count"] or row["raw_row_count"] != row["summary_row_count"]
    )
    summary_mismatch_count = sum(1 for row in monthly_rows if row["summary_rederivation_mismatch"])
    outside_count = sum(row["outside_prior_audited_universe_count"] for row in monthly_rows)
    size_thin_months = sum(row["minimum_size_quintile_count"] < MIN_SIZE_QUINTILE_COUNT for row in monthly_rows)

    checks = [
        make_check(
            "materialization_summary_gate",
            "pass_large_cap_market_cap_audit",
            {
                "materialization_status": summary["decision"]["market_cap_materialization_status"],
                "selected_market_cap_field": summary["decision"]["selected_market_cap_field"],
                "endpoint_results_count": summary["execution"]["endpoint_results_count"],
                "ledger_tests_spent_count": read_json(LEDGER_PATH)["budget_policy"]["tests_spent_count"],
            },
            ["Materialization summary is schema-valid, PASS-shaped, no-raw/no-top500-list, and ledger remains unspent."],
        ),
        make_check(
            "raw_payload_shape_and_refs",
            "pass_large_cap_market_cap_audit" if raw_shape_failures == 0 else "blocked_missing_required_source",
            {
                "months_checked": months,
                "raw_shape_failure_month_count": raw_shape_failures,
                "raw_row_count_min": min(row["raw_row_count"] for row in monthly_rows) if monthly_rows else None,
                "raw_row_count_max": max(row["raw_row_count"] for row in monthly_rows) if monthly_rows else None,
            },
            ["All market-cap raw refs resolve under the approved gitignored root and match their as-of dates."]
            if raw_shape_failures == 0
            else ["At least one raw payload is missing, escaped, has a date mismatch, or disagrees with the summary row count."],
        ),
        make_check(
            "top500_rederivation_consistency",
            "pass_large_cap_market_cap_audit" if complete_months == months and summary_mismatch_count == 0 else "fail_data_not_ready",
            {
                "months_checked": months,
                "complete_top500_month_count": complete_months,
                "summary_rederivation_mismatch_count": summary_mismatch_count,
                "min_selected_top500_count": min(row["selected_top500_count"] for row in monthly_rows) if monthly_rows else None,
            },
            ["The audit re-derived the same top-500 count/min/max stats from raw circ_mv for every as-of."]
            if complete_months == months and summary_mismatch_count == 0
            else ["Top-500 re-derivation is incomplete or no longer matches the materialization summary."],
        ),
        make_check(
            "main_board_filter_integrity",
            "pass_large_cap_market_cap_audit",
            {
                "filter_function": "engine.data.a_share_board_scope.is_main_board_ts_code",
                "min_main_board_row_count": min(row["main_board_row_count"] for row in monthly_rows) if monthly_rows else None,
                "min_positive_main_board_circ_mv_count": min(row["positive_main_board_circ_mv_count"] for row in monthly_rows) if monthly_rows else None,
                "top500_symbols_written_to_tracked_report": False,
            },
            ["Top-500 selection is re-derived only after applying the shared main-board filter; full symbol lists stay out of tracked output."],
        ),
        make_check(
            "prior_full_main_board_universe_bridge",
            "pass_large_cap_market_cap_audit" if outside_count == 0 else "fail_data_not_ready",
            {
                "prior_audited_universe_count": len(prior_universe),
                "total_outside_prior_audited_universe_observations": outside_count,
                "months_with_outside_prior_universe": sum(row["outside_prior_audited_universe_count"] > 0 for row in monthly_rows),
            },
            ["Every re-derived monthly top-500 symbol is inside the prior audited full-main-board raw universe."]
            if outside_count == 0
            else ["Some top-500 symbols are outside the prior audited full-main-board raw universe and cannot safely enter signal scoring."],
        ),
        make_check(
            "size_quintile_coverage",
            "pass_large_cap_market_cap_audit" if size_thin_months == 0 else "fail_data_not_ready",
            {
                "months_checked": months,
                "thin_size_quintile_month_count": size_thin_months,
                "minimum_observed_size_quintile_count": min(row["minimum_size_quintile_count"] for row in monthly_rows) if monthly_rows else None,
                "registered_minimum_size_bucket_count": MIN_SIZE_QUINTILE_COUNT,
            },
            ["Every month can form five market-cap quintiles with enough names for the registered size-neutral percentile view."]
            if size_thin_months == 0
            else ["At least one month has a size quintile below the registered minimum count."],
        ),
    ]
    return checks


def decision_from_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    hard_pass = all(check["status"] == "pass_large_cap_market_cap_audit" for check in checks)
    status = "passed_large_cap_market_cap_audit_for_signal_package" if hard_pass else "fail_data_not_ready"
    return {
        "audit_status": status,
        "hard_checks_pass": hard_pass,
        "market_cap_universe_ready_for_signal_package_after_review": hard_pass,
        "signal_search_package_may_be_built_after_review": hard_pass,
        "signal_search_authorized_by_this_report": False,
        "alpha_found": False,
        "plain_result": (
            "Large-cap market-cap universe audit passed: the 96 monthly top-500-by-circ_mv universes are re-derivable from raw, main-board-only, bridge to the prior audited full-main-board raw universe, and have usable size-quintile coverage."
            if hard_pass
            else "Large-cap market-cap universe audit failed or is blocked; do not build or run signal search."
        ),
        "next_action": (
            "Send this audit report for independent review; if review passes and it is committed, the next separate step may build the signal-search package."
            if hard_pass
            else "Fix the failed audit checks before any signal-search package."
        ),
    }


def run_runner_self_tests() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def add(fixture_id: str, detected: bool) -> None:
        results.append(
            {
                "fixture_id": fixture_id,
                "checker_origin": "large_cap_market_cap_audit_runner",
                "status": "pass" if detected else "fail",
                "detected_expected_violation": bool(detected),
            }
        )

    good_summary = {
        "schema_name": "a_long_large_cap_market_cap_materialization_execution_summary",
        "scope": {"tracked_summary_contains_raw_rows": False, "tracked_summary_contains_top500_symbols": False},
        "decision": {
            "market_cap_materialization_status": "passed_market_cap_materialization_shape",
            "raw_market_cap_materialization_shape_available": True,
            "audit_rerun_authorized_by_this_summary": False,
            "signal_search_authorized_by_this_summary": False,
            "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
        },
        "execution": {
            "endpoint_results_count": 96,
            "token_logged": False,
            "request_url_logged": False,
        },
        "materialization_boundary": {
            "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
            "monthly_as_of_dates": MONTHLY_AS_OF_DATES,
            "universe_size_n": UNIVERSE_SIZE_N,
            "top_500_selection_written_to_tracked_summary": False,
        },
    }
    try:
        bad_summary = json.loads(json.dumps(good_summary))
        bad_summary["decision"]["signal_search_authorized_by_this_summary"] = True
        # The schema validator is intentionally bypassed here; this self-test checks the runner guard itself.
        original_validate = materialization.validate_json
        materialization.validate_json = lambda _schema_path, _payload: None  # type: ignore[assignment]
        try:
            validate_materialization_summary(bad_summary)
        finally:
            materialization.validate_json = original_validate  # type: ignore[assignment]
        add("materialization_summary_scope_creep_blocks", False)
    except ValueError:
        add("materialization_summary_scope_creep_blocks", True)

    try:
        resolve_raw_ref(Path("."), "../outside.json")
        add("missing_raw_ref_blocks", False)
    except (ValueError, FileNotFoundError):
        add("missing_raw_ref_blocks", True)

    fixture_records = [
        {"ts_code": "300001.SZ", SELECTED_MARKET_CAP_FIELD: 999999999.0},
        *[
            {"ts_code": f"{600000 + idx:06d}.SH", SELECTED_MARKET_CAP_FIELD: float(1000 + idx)}
            for idx in range(UNIVERSE_SIZE_N)
        ],
    ]
    selected = select_top500(fixture_records)
    add("main_board_filter_excludes_non_main_high_caps", "300001.SZ" not in {symbol for symbol, _value in selected})

    sparse = select_top500(fixture_records[:499])
    add("sparse_top500_blocks", len(sparse) < UNIVERSE_SIZE_N)

    prior_universe = {symbol for symbol, _value in selected[:-1]}
    outside = set(symbol for symbol, _value in selected) - prior_universe
    add("prior_universe_gap_blocks", len(outside) == 1)
    return results


def build_report(
    *,
    generated_at: str,
    summary: dict[str, Any],
    monthly_rows: list[dict[str, Any]],
    prior_universe: set[str],
    self_tests: list[dict[str, Any]],
    confirm_independent_review_pass: bool,
    confirm_post_review_execute: bool,
) -> dict[str, Any]:
    checks = checks_from_monthly_rows(summary, monthly_rows, prior_universe)
    decision = decision_from_checks(checks)
    return {
        "schema_name": "a_long_large_cap_market_cap_audit_report",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_large_cap_market_cap_audit_report_20260607",
        "source_refs": [
            "docs/a_long_large_cap_market_cap_audit_packet_20260607.json",
            "docs/a_long_large_cap_market_cap_materialization_execution_summary_20260607.json",
            "research/preregistrations/a_long_large_cap_pure_quality_20260607.json",
            "research/ledgers/a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json",
            "research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json",
            "docs/a_long_main_board_sw_coverage_repair_execution_summary_20260604.json",
        ],
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_large_cap_market_cap_materialization_audit",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "local_market_cap_raw_read_only": True,
            "prior_full_main_board_raw_read_only": True,
            "provider_call_executed": False,
            "tushare_call_executed": False,
            "data_fetch_executed": False,
            "raw_rows_in_tracked_report": False,
            "top500_symbols_in_tracked_report": False,
            "endpoint_results_in_tracked_report": False,
            "signal_search_executed": False,
            "alpha_backtest_executed": False,
            "production_use_allowed": False,
            "ship_gate_claim_allowed": False,
            "full_size_manual_use_allowed": False,
            "broker_or_order_automation_allowed": False,
            "manual_order_only": True,
        },
        "execution": {
            "audit_packet_ref": "docs/a_long_large_cap_market_cap_audit_packet_20260607.json",
            "materialization_summary_ref": "docs/a_long_large_cap_market_cap_materialization_execution_summary_20260607.json",
            "market_cap_raw_root": MARKET_CAP_RAW_ROOT_REL.as_posix() + "/",
            "prior_full_main_board_raw_root": PRIOR_FULL_RAW_ROOT_REL.as_posix() + "/",
            "monthly_as_of_count": len(MONTHLY_AS_OF_DATES),
            "months_audited": len(monthly_rows),
            "network_calls_executed": 0,
            "provider_calls_executed": 0,
            "self_tests_required": len(SELF_TEST_IDS),
            "self_tests_passed": sum(1 for item in self_tests if item["status"] == "pass"),
            "independent_review_confirmed": confirm_independent_review_pass,
            "post_review_execute_confirmed": confirm_post_review_execute,
            "tracked_report_contains_raw_records": False,
            "tracked_report_contains_top500_symbols": False,
            "tracked_report_contains_endpoint_results": False,
            "tracked_report_contains_secret": False,
            "tracked_report_contains_request_url": False,
        },
        "audit_boundary": {
            "materialization_id": "a_long_large_cap_market_cap_top500_monthly_2018_2025",
            "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
            "universe_size_n": UNIVERSE_SIZE_N,
            "board_scope": "main_board_only",
            "main_board_filter_source": "engine.data.a_share_board_scope.is_main_board_ts_code",
            "monthly_as_of_count": len(MONTHLY_AS_OF_DATES),
            "monthly_as_of_dates": list(MONTHLY_AS_OF_DATES),
            "same_as_materialization_dates": True,
            "prior_audited_universe_count": len(prior_universe),
            "size_bucket_count": 5,
            "minimum_size_bucket_count_for_primary_percentile": MIN_SIZE_QUINTILE_COUNT,
            "top500_symbols_written_to_tracked_report": False,
            "not_signal_search": True,
        },
        "required_runner_self_tests": self_tests,
        "check_results": checks,
        "monthly_coverage": monthly_rows,
        "decision": decision,
        "prohibited_claims": {
            "a_long_alpha_found": False,
            "signal_search_executed": False,
            "signal_search_authorized": False,
            "alpha_backtest_executed": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "provider_selected": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "result_artifacts": [
            "research/results/a_long_large_cap_market_cap_audit_20260607/audit_report.json",
            "research/results/a_long_large_cap_market_cap_audit_20260607/monthly_coverage.csv",
        ],
        "limitations": [
            "This audit checks market-cap universe materialization only; it does not calculate signals or returns.",
            "Tracked outputs contain no raw rows and no complete monthly top-500 symbol lists.",
            "A PASS can only unlock a later reviewed signal-search package; it does not authorize running signal search by itself.",
            "Any future signal-search runner must re-derive the universe from the retained raw using the same 96 as-ofs, main-board filter, and top-500-by-circ_mv rule.",
        ],
    }


def execute_audit(
    *,
    packet_path: Path = PACKET_PATH,
    summary_path: Path = MATERIALIZATION_SUMMARY_PATH,
    raw_root: Path = MARKET_CAP_RAW_ROOT,
    prior_full_raw_root: Path = PRIOR_FULL_RAW_ROOT,
    report_path: Path = REPORT_PATH,
    monthly_coverage_path: Path = MONTHLY_COVERAGE_PATH,
    generated_at: str | None = None,
    confirm_independent_review_pass: bool = False,
    confirm_post_review_execute: bool = False,
) -> dict[str, Any]:
    if not (confirm_independent_review_pass and confirm_post_review_execute):
        raise RuntimeError("large-cap market-cap audit requires independent-review PASS and post-review execute confirmations")

    load_and_validate_packet(packet_path)
    validate_preregistration_and_ledger()
    validate_prior_full_audit_report()
    summary = read_json(summary_path)
    validate_materialization_summary(summary)
    prior_universe = load_prior_audited_universe(prior_full_raw_root)
    monthly_rows = audit_monthly_payloads(summary, raw_root, prior_universe)
    self_tests = run_runner_self_tests()
    if any(item["status"] != "pass" for item in self_tests):
        raise RuntimeError("large-cap market-cap audit self-tests failed")

    report = build_report(
        generated_at=generated_at or iso_now(),
        summary=summary,
        monthly_rows=monthly_rows,
        prior_universe=prior_universe,
        self_tests=self_tests,
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )
    if _contains_key(report, "records"):
        raise ValueError("tracked audit report must not contain raw records")
    if _contains_key(report, "top500_symbols") or _contains_key(report, "selected_symbols"):
        raise ValueError("tracked audit report must not contain top500 symbol lists")
    validate_json(REPORT_SCHEMA_PATH, report)
    write_json_atomic(report_path, report)
    write_csv(monthly_coverage_path, monthly_rows)
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = execute_audit(
        packet_path=args.packet_path,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        prior_full_raw_root=args.prior_full_raw_root,
        report_path=args.report_path,
        monthly_coverage_path=args.monthly_coverage_path,
        generated_at=args.generated_at,
        confirm_independent_review_pass=args.confirm_independent_review_pass,
        confirm_post_review_execute=args.confirm_post_review_execute,
    )
    print(
        json.dumps(
            {
                "audit_status": report["decision"]["audit_status"],
                "months_audited": report["execution"]["months_audited"],
                "hard_checks_pass": report["decision"]["hard_checks_pass"],
                "signal_search_authorized_by_this_report": report["decision"]["signal_search_authorized_by_this_report"],
                "report_path": display_path(args.report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
