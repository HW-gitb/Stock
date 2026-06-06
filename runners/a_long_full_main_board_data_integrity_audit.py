from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.data.a_share_board_scope import is_main_board_ts_code
from runners import a_long_data_integrity_audit as base_audit


SUMMARY_PATH = ROOT / "docs" / "a_long_full_main_board_materialization_execution_summary_20260605.json"
PACKET_PATH = ROOT / "docs" / "a_long_full_main_board_signal_search_execution_packet_20260605.json"
BOUNDARY_PATH = ROOT / "docs" / "a_long_scaled_delisted_no_industry_boundary_decision_20260605.json"
SW_REPAIR_SUMMARY_PATH = ROOT / "docs" / "a_long_main_board_sw_coverage_repair_execution_summary_20260604.json"
PREREGISTRATION_PATH = ROOT / "research" / "preregistrations" / "a_long_data_integrity_audit_20260603.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/full_main_board_signal_search_20260605")
RAW_ROOT = ROOT / RAW_ROOT_REL
SW_REPAIR_RAW_ROOT_REL = Path("data/a_long/raw/tushare/main_board_sw_coverage_repair_20260604")
SW_REPAIR_RAW_ROOT = ROOT / SW_REPAIR_RAW_ROOT_REL
OUTPUT_DIR = ROOT / "research" / "results" / "a_long_full_main_board_data_integrity_audit_20260605"
SCHEMA_PATH = ROOT / "schemas" / "a_long_full_main_board_data_integrity_audit_report.schema.json"

START_DATE = "20180101"
END_DATE = "20251231"
EXPECTED_ACTIVE_COUNT = 3200
EXPECTED_DELISTED_COUNT = 187
EXPECTED_UNIVERSE_COUNT = 3387
REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT = 191
ACTIVE_DELISTING_SHELL_SYMBOLS = ["600421.SH", "600599.SH", "600636.SH", "600696.SH"]
EXPECTED_ENDPOINT_RESULTS_COUNT = 23718
BENCHMARKS = {"CSI300": "H00300.CSI", "CSI1000": "H00852.CSI"}
BENCHMARK_RETURN_BASIS = "benchmark_total_return_index_next_trading_day_close_to_same_exit_close"
SELECTION_STATUS_CALL_ID = "namechange_2018_2025"
FUNDAMENTAL_TABLES = ["income", "balancesheet", "cashflow", "fina_indicator"]
FULL_PERIOD_SUFFIX = "2018_2025"
TEMPORAL_COVERAGE_THRESHOLD_PCT = 80.0
SAME_ANN_DATE_NON_NULL_PREFERENCE_FIELDS = {"profit_dedt"}
RESTATEMENT_EXCLUSION_LIST_REL = Path("research/results/a_long_full_main_board_data_integrity_audit_20260605/restatement_ambiguous_exclusions.csv")
CHECK_IDS = [
    "fundamental_pit",
    "restatement_revision_asof",
    "selection_time_status_source",
    "survivorship_pit_universe",
    "return_benchmark_measurement_basis",
    "temporal_coverage_bias",
]
HARD_CHECK_IDS = set(CHECK_IDS) - {"temporal_coverage_bias"}
MAX_SAMPLE_ITEMS = 20


@dataclass(frozen=True)
class AuditContext:
    active_symbols: list[str]
    delisted_symbols: list[str]
    exception_symbols: list[str]
    active_delisting_shell_symbols: list[str]
    as_ofs: list[str]

    @property
    def symbols(self) -> list[str]:
        return self.active_symbols + self.delisted_symbols


class PayloadStore:
    def __init__(self, *, raw_root: Path, manifest: dict[str, dict[str, Any]] | None = None, payloads: dict[str, dict[str, Any]] | None = None):
        self.raw_root = raw_root
        self.manifest = manifest or {}
        self.payloads = payloads or {}

    def payload(self, call_id: str) -> dict[str, Any]:
        if call_id in self.payloads:
            return self.payloads[call_id]
        item = self.manifest.get(call_id)
        if item is None:
            raise KeyError(f"endpoint result missing for {call_id}")
        if item.get("call_status") not in {"success", "empty"}:
            raise ValueError(f"endpoint did not succeed for {call_id}: {item.get('call_status')}")
        raw_ref = item.get("raw_payload_ref")
        if not raw_ref:
            raise ValueError(f"endpoint result lacks raw_payload_ref for {call_id}")
        path = resolve_raw_ref(self.raw_root, str(raw_ref))
        return read_json(path)

    def records(self, call_id: str) -> list[dict[str, Any]]:
        value = self.payload(call_id).get("records")
        if not isinstance(value, list):
            raise ValueError(f"raw payload records missing for {call_id}")
        return [row for row in value if isinstance(row, dict)]

    def columns(self, call_id: str) -> set[str]:
        value = self.payload(call_id).get("columns")
        if not isinstance(value, list):
            return set()
        return {str(item) for item in value}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the already-materialized A-long full main-board raw panel. "
            "This reads local gitignored raw payloads only. It does not call Tushare, "
            "search signals, calculate alpha, or authorize production use."
        )
    )
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def json_default(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required for A-long schema-gated data-integrity audit; "
            "install project requirements before running this producer."
        ) from exc
    schema = read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
        raise ValueError(f"{schema_path} validation failed: {joined}")


def load_restatement_exclusion_policy(preregistration_path: Path = PREREGISTRATION_PATH) -> dict[str, Any]:
    preregistration = read_json(preregistration_path)
    checks = {item.get("check_id"): item for item in preregistration.get("audit_checks", []) if isinstance(item, dict)}
    restatement = checks.get("restatement_revision_asof") or {}
    tolerance = restatement.get("non_blocking_tolerance") or {}
    if tolerance.get("metric") != "same_ann_date_ambiguous_exclusion_rate_pct":
        raise ValueError("restatement exclusion tolerance is not preregistered")
    if tolerance.get("operator") != "<=" or tolerance.get("unit") != "percent":
        raise ValueError("restatement exclusion tolerance has invalid operator/unit")

    amendments = [
        item for item in preregistration.get("reviewed_repair_amendments", [])
        if isinstance(item, dict) and item.get("applies_to_check_id") == "restatement_revision_asof"
    ]
    if len(amendments) != 1:
        raise ValueError("restatement repair amendment must have exactly one preregistered home")
    amendment = amendments[0]
    max_pct = float(amendment.get("max_ambiguous_exclusion_rate_pct"))
    if not math.isclose(float(tolerance.get("value")), max_pct, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("restatement exclusion cap mismatch between audit check and repair amendment")
    if amendment.get("ambiguous_group_signal_treatment") != "mandatory_exclusion_from_signal_inputs":
        raise ValueError("restatement ambiguous groups must be mandatory signal exclusions")
    if amendment.get("signal_search_preregistration_must_consume_exclusion_list") is not True:
        raise ValueError("signal-search preregistration must consume the restatement exclusion list")
    if amendment.get("silent_use_of_ambiguous_groups_allowed") is not False:
        raise ValueError("silent use of ambiguous restatement groups is not allowed")
    if amendment.get("exclusion_list_artifact") != RESTATEMENT_EXCLUSION_LIST_REL.as_posix():
        raise ValueError("restatement exclusion list path mismatch")
    return {
        "max_pct": max_pct,
        "amendment_id": amendment.get("amendment_id"),
        "cap_rationale": amendment.get("cap_rationale"),
        "below_cap_action": amendment.get("below_cap_action"),
        "above_cap_action": amendment.get("above_cap_action"),
    }


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(resolved).replace("\\", "/")


def normalize_yyyymmdd(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip().replace("-", "")
    return text if len(text) == 8 and text.isdigit() else None


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d")


def sample(values: list[Any] | set[Any], limit: int = MAX_SAMPLE_ITEMS) -> list[Any]:
    return list(sorted(values))[:limit]


def call_id_for(table: str, symbol: str) -> str:
    return f"{table}_{symbol.replace('.', '_')}_{FULL_PERIOD_SUFFIX}"


def dividend_call_id(symbol: str) -> str:
    return f"dividend_{symbol.replace('.', '_')}"


def index_call_id(benchmark: str) -> str:
    return f"index_daily_{benchmark.replace('.', '_')}_{FULL_PERIOD_SUFFIX}"


def resolve_raw_ref(raw_root: Path, raw_ref: str) -> Path:
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


def load_endpoint_manifest(summary: dict[str, Any], raw_root: Path) -> dict[str, dict[str, Any]]:
    endpoint_manifest = summary.get("endpoint_manifest") or {}
    if endpoint_manifest.get("tracked_summary_embeds_endpoint_results") is not False:
        raise ValueError("tracked summary must not embed endpoint results")
    manifest_ref = endpoint_manifest.get("manifest_ref")
    if not manifest_ref:
        raise ValueError("materialization summary lacks endpoint manifest ref")
    manifest = read_json(resolve_raw_ref(raw_root, str(manifest_ref)))
    rows = manifest.get("endpoint_results")
    if not isinstance(rows, list):
        raise ValueError("endpoint manifest lacks endpoint_results")
    by_call_id: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict) or not item.get("call_id"):
            raise ValueError("endpoint manifest contains malformed item")
        by_call_id[str(item["call_id"])] = item
    return by_call_id


def validate_materialization_summary(summary: dict[str, Any]) -> None:
    if summary.get("schema_name") != "a_long_full_main_board_materialization_execution_summary":
        raise ValueError("materialization summary schema_name mismatch")
    decision = summary.get("decision") or {}
    if decision.get("materialization_status") != "passed_full_main_board_materialization_shape":
        raise ValueError("full main-board materialization must pass before audit")
    if decision.get("data_can_be_used_for_alpha_now") is not False:
        raise ValueError("materialization summary must not claim alpha readiness")
    if decision.get("next_reviewed_step_can_be_full_data_integrity_audit") is not True:
        raise ValueError("materialization summary must route to the audit gate")

    execution = summary.get("execution") or {}
    if execution.get("endpoint_results_count") != EXPECTED_ENDPOINT_RESULTS_COUNT:
        raise ValueError("materialization summary endpoint count mismatch")
    if execution.get("token_logged") is not False or execution.get("request_url_logged") is not False:
        raise ValueError("materialization summary must stay no-secret/no-url")

    boundary = summary.get("execution_boundary") or {}
    expected = {
        "board_scope": "main_board_only",
        "start_date": START_DATE,
        "end_date": END_DATE,
        "expected_active_count": EXPECTED_ACTIVE_COUNT,
        "expected_delisted_count": EXPECTED_DELISTED_COUNT,
        "expected_candidate_universe_count": EXPECTED_UNIVERSE_COUNT,
        "reviewed_no_industry_exception_count": REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT,
        "active_investable_missing_industry_allowed": False,
        "manual_industry_fill_allowed": False,
        "silent_unknown_or_default_industry_allowed": False,
        "drop_boundary_names_from_returns_or_risk_allowed": False,
        "industry_denominator_exclusion_only": True,
        "terminal_delisting_return_required": True,
    }
    for key, value in expected.items():
        if boundary.get(key) != value:
            raise ValueError(f"materialization boundary mismatch: {key}")
    if boundary.get("active_delisting_shell_symbols") != ACTIVE_DELISTING_SHELL_SYMBOLS:
        raise ValueError("active delisting shell boundary mismatch")
    rollups = summary.get("table_rollup") or []
    if not rollups or any(item.get("calls_error") != 0 for item in rollups):
        raise ValueError("all materialization table rollups must have zero endpoint errors")


def validate_boundary_refs() -> dict[str, Any]:
    boundary = read_json(BOUNDARY_PATH)
    reviewed = boundary.get("reviewed_boundary") or {}
    if reviewed.get("scaled_no_industry_boundary_count_if_approved") != REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT:
        raise ValueError("reviewed no-industry exception count mismatch")
    treatment = reviewed.get("boundary_treatment") or {}
    required_treatment = {
        "manual_industry_fill_allowed": False,
        "silent_unknown_or_default_industry_allowed": False,
        "drop_from_universe_returns_or_risk_allowed": False,
        "exclude_only_from_industry_normalization_denominators": True,
        "keep_in_pit_universe_returns_risk_drawdown_and_coverage": True,
        "terminal_delisting_return_required": True,
    }
    for key, value in required_treatment.items():
        if treatment.get(key) != value:
            raise ValueError(f"boundary treatment mismatch: {key}")

    repair = read_json(SW_REPAIR_SUMMARY_PATH)
    if repair.get("schema_name") != "a_long_main_board_sw_coverage_repair_execution_summary":
        raise ValueError("SW repair summary schema mismatch")
    active = repair.get("active_sw_supplement") or {}
    shell = repair.get("active_delisting_shell_boundary") or {}
    delisted = repair.get("delisted_no_industry_boundary") or {}
    if active.get("supplement_success_count") != 1189:
        raise ValueError("active SW supplement count mismatch")
    if shell.get("detected_symbols") != ACTIVE_DELISTING_SHELL_SYMBOLS:
        raise ValueError("active delisting-shell symbols mismatch")
    if shell.get("active_investable_unresolved_count") != 0:
        raise ValueError("active investable unresolved count must stay zero")
    if delisted.get("no_usable_sw_source_evidence_count") != EXPECTED_DELISTED_COUNT:
        raise ValueError("delisted no-source count mismatch")
    if delisted.get("threshold_passed") is not True:
        raise ValueError("delisted no-industry threshold must pass")
    return repair


def main_board_delisted_in_window(row: dict[str, Any]) -> bool:
    code = str(row.get("ts_code") or "")
    delist_date = normalize_yyyymmdd(row.get("delist_date"))
    list_date = normalize_yyyymmdd(row.get("list_date"))
    return bool(
        is_main_board_ts_code(code)
        and delist_date
        and START_DATE <= delist_date <= END_DATE
        and (list_date is None or list_date <= END_DATE)
    )


def build_context(store: PayloadStore, repair: dict[str, Any]) -> AuditContext:
    active = sorted(
        str(row["ts_code"])
        for row in store.records("stock_basic_active_L")
        if row.get("list_status") == "L" and is_main_board_ts_code(str(row.get("ts_code")))
    )
    repair_delisted = (repair.get("delisted_no_industry_boundary") or {}).get("no_usable_sw_source_symbols") or []
    delisted = sorted({str(symbol) for symbol in repair_delisted})
    raw_delisted = sorted(str(row["ts_code"]) for row in store.records("stock_basic_delisted_D") if main_board_delisted_in_window(row))
    if len(active) != EXPECTED_ACTIVE_COUNT or len(delisted) != EXPECTED_DELISTED_COUNT:
        raise ValueError(f"full main-board universe mismatch: active={len(active)} delisted={len(delisted)}")
    if not set(raw_delisted).issubset(set(delisted)):
        raise ValueError("stock_basic delisted raw contains symbols outside the reviewed delisted boundary")
    exceptions = sorted(set(repair_delisted) | set(ACTIVE_DELISTING_SHELL_SYMBOLS))
    if len(exceptions) != REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT:
        raise ValueError("reviewed no-industry exception symbol count mismatch")
    return AuditContext(
        active_symbols=active,
        delisted_symbols=delisted,
        exception_symbols=exceptions,
        active_delisting_shell_symbols=list(ACTIVE_DELISTING_SHELL_SYMBOLS),
        as_ofs=monthly_last_open_days(store),
    )


def monthly_last_open_days(store: PayloadStore) -> list[str]:
    days = sorted(
        {
            str(row["cal_date"])
            for row in store.records("trade_calendar_2018_2025")
            if row.get("is_open") in {1, "1"}
        }
    )
    by_month: dict[str, str] = {}
    for day in days:
        by_month[day[:6]] = day
    return [by_month[month] for month in sorted(by_month)]


def make_check(check_id: str, status: str, metrics: dict[str, Any], findings: list[str]) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "hard_check": check_id in HARD_CHECK_IDS,
        "blocks_signal_search": True,
        "metrics": metrics,
        "findings": findings,
        "allowed_followup": (
            "If this full main-board audit passes, the next separate gate is the frozen A-long signal search. "
            "Do not run signal search or claim alpha from this audit report alone."
        ),
    }


def check_fundamental_pit(store: PayloadStore, context: AuditContext) -> dict[str, Any]:
    rows_checked = 0
    valid_ann = 0
    missing_ann = 0
    future_ann_after_panel_end = 0
    missing_columns: list[str] = []
    covered_by_table: dict[str, set[str]] = {table: set() for table in FUNDAMENTAL_TABLES}
    empty_payloads_by_table: dict[str, int] = {table: 0 for table in FUNDAMENTAL_TABLES}

    for table in FUNDAMENTAL_TABLES:
        for symbol in context.symbols:
            cid = call_id_for(table, symbol)
            columns = store.columns(cid)
            missing = sorted({"ts_code", "ann_date", "end_date"} - columns)
            if missing:
                missing_columns.extend(f"{cid}:{field}" for field in missing[:3])
                continue
            rows = store.records(cid)
            if not rows:
                empty_payloads_by_table[table] += 1
            for row in rows:
                rows_checked += 1
                ann_date = normalize_yyyymmdd(row.get("ann_date"))
                end_date = normalize_yyyymmdd(row.get("end_date"))
                if ann_date is None or end_date is None:
                    missing_ann += 1
                    continue
                if ann_date > END_DATE:
                    future_ann_after_panel_end += 1
                    continue
                valid_ann += 1
                covered_by_table[table].add(symbol)

    missing_rate_pct = (missing_ann / rows_checked * 100.0) if rows_checked else 0.0
    status = "pass_full_main_board" if not missing_columns and missing_rate_pct <= 5.0 else "fail_data_not_ready"
    if missing_columns:
        status = "blocked_missing_required_source"
    return make_check(
        "fundamental_pit",
        status,
        {
            "rows_checked": rows_checked,
            "valid_ann_date_rows": valid_ann,
            "missing_or_invalid_ann_date_rows": missing_ann,
            "missing_or_invalid_ann_date_exclusion_rate_pct": round(missing_rate_pct, 6),
            "future_ann_date_rows_after_panel_end_excluded": future_ann_after_panel_end,
            "missing_required_columns_count": len(missing_columns),
            "missing_required_columns_sample": sample(missing_columns),
            "covered_symbol_count_by_table": {table: len(symbols) for table, symbols in covered_by_table.items()},
            "empty_payload_count_by_table": empty_payloads_by_table,
            "ann_date_asof_gating_feasible": not missing_columns and missing_rate_pct <= 5.0,
        },
        [
            "Raw full-main-board fundamentals include ann_date/end_date for PIT gating checks.",
            "Invalid or missing ann_date rows are excluded and reported; they are not latest-only filled.",
        ],
    )


def compact_value(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def row_signature(row: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in row.items() if k not in {"request_url", "token"}}, ensure_ascii=False, sort_keys=True, default=json_default)


def differing_fields(rows: list[dict[str, Any]]) -> list[str]:
    keys = sorted({key for item in rows for key in item if key not in {"request_url", "token"}})
    out = []
    for key in keys:
        values = {
            json.dumps(compact_value(item.get(key)), ensure_ascii=False, sort_keys=True, default=json_default)
            for item in rows
        }
        if len(values) > 1:
            out.append(key)
    return out


def same_ann_duplicate_resolution(rows: list[dict[str, Any]]) -> tuple[bool, list[str], str]:
    fields = differing_fields(rows)
    if not fields:
        return True, [], "identical_rows"
    if not set(fields).issubset(SAME_ANN_DATE_NON_NULL_PREFERENCE_FIELDS):
        f_ann_dates = [normalize_yyyymmdd(row.get("f_ann_date")) for row in rows]
        if all(f_ann_dates) and len(set(f_ann_dates)) > 1:
            grouped_by_f_ann: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row, f_ann_date in zip(rows, f_ann_dates):
                grouped_by_f_ann[str(f_ann_date)].append(row)
            if all(len({row_signature(item) for item in f_rows}) == 1 for f_rows in grouped_by_f_ann.values()):
                return True, fields, "resolved_by_f_ann_date_asof_disambiguation"
        return False, fields, "unresolved_value_conflict"
    for field in fields:
        non_null_values = {
            json.dumps(compact_value(row.get(field)), ensure_ascii=False, sort_keys=True, default=json_default)
            for row in rows
            if compact_value(row.get(field)) is not None
        }
        if len(non_null_values) != 1:
            return False, fields, "unresolved_nullable_preference"
    return True, fields, "resolved_by_single_non_null_preference"


def check_restatement_revision(store: PayloadStore, context: AuditContext, sidecars: dict[str, Any] | None = None) -> dict[str, Any]:
    exclusion_policy = load_restatement_exclusion_policy()
    groups_checked = 0
    multi_ann_groups = 0
    same_ann_conflicts = 0
    resolved_same_ann_duplicates = 0
    resolved_by_non_null_preference = 0
    resolved_by_f_ann_date = 0
    conflict_examples: list[dict[str, Any]] = []
    ambiguous_exclusion_rows: list[dict[str, Any]] = []
    resolution_examples: list[dict[str, Any]] = []
    tables_with_f_ann_date: set[str] = set()

    for table in FUNDAMENTAL_TABLES:
        for symbol in context.symbols:
            cid = call_id_for(table, symbol)
            if "f_ann_date" in store.columns(cid):
                tables_with_f_ann_date.add(table)
            by_period: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in store.records(cid):
                ann_date = normalize_yyyymmdd(row.get("ann_date"))
                end_date = normalize_yyyymmdd(row.get("end_date"))
                if ann_date and ann_date <= END_DATE and end_date:
                    by_period[end_date].append(row)
            for end_date, rows in by_period.items():
                groups_checked += 1
                by_ann: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for row in rows:
                    by_ann[normalize_yyyymmdd(row.get("ann_date")) or ""].append(row)
                if len([date for date in by_ann if date]) > 1:
                    multi_ann_groups += 1
                for ann_date, ann_rows in by_ann.items():
                    signatures = {row_signature(row) for row in ann_rows}
                    if len(signatures) <= 1:
                        continue
                    is_resolved, fields, resolution_rule = same_ann_duplicate_resolution(ann_rows)
                    if is_resolved:
                        resolved_same_ann_duplicates += 1
                        if resolution_rule == "resolved_by_f_ann_date_asof_disambiguation":
                            resolved_by_f_ann_date += 1
                        if resolution_rule == "resolved_by_single_non_null_preference":
                            resolved_by_non_null_preference += 1
                        if fields and len(resolution_examples) < MAX_SAMPLE_ITEMS:
                            resolution_examples.append(
                                {
                                    "table": table,
                                    "symbol": symbol,
                                    "end_date": end_date,
                                    "ann_date": ann_date,
                                    "row_count": len(ann_rows),
                                    "resolved_fields": fields,
                                    "resolution_rule": resolution_rule,
                                }
                            )
                        continue
                    same_ann_conflicts += 1
                    ambiguous_exclusion_rows.append(
                        {
                            "table_id": table,
                            "symbol": symbol,
                            "end_date": end_date,
                            "ann_date": ann_date,
                            "row_count": len(ann_rows),
                            "differing_fields": "|".join(fields),
                            "required_signal_treatment": "exclude_this_table_symbol_period_ann_date_group",
                        }
                    )
                    if len(conflict_examples) < MAX_SAMPLE_ITEMS:
                        conflict_examples.append(
                            {
                                "table": table,
                                "symbol": symbol,
                                "end_date": end_date,
                                "ann_date": ann_date,
                                "row_count": len(ann_rows),
                                "differing_fields": fields,
                            }
                        )

    ambiguous_exclusion_rate_pct = (same_ann_conflicts / groups_checked * 100.0) if groups_checked else 0.0
    max_exclusion_pct = float(exclusion_policy["max_pct"])
    status = "pass_full_main_board" if ambiguous_exclusion_rate_pct <= max_exclusion_pct else "fail_data_not_ready"
    if sidecars is not None:
        sidecars["restatement_ambiguous_exclusions"] = ambiguous_exclusion_rows
    return make_check(
        "restatement_revision_asof",
        status,
        {
            "period_groups_checked": groups_checked,
            "groups_with_multiple_ann_dates": multi_ann_groups,
            "same_ann_date_conflicting_duplicate_groups": same_ann_conflicts,
            "same_ann_date_ambiguous_exclusion_rate_pct": round(ambiguous_exclusion_rate_pct, 6),
            "same_ann_date_ambiguous_exclusion_max_allowed_pct": max_exclusion_pct,
            "same_ann_date_ambiguous_exclusion_policy_ref": exclusion_policy["amendment_id"],
            "same_ann_date_ambiguous_exclusion_cap_rationale": exclusion_policy["cap_rationale"],
            "same_ann_date_ambiguous_groups_must_be_excluded_from_signal_inputs": True,
            "same_ann_date_ambiguous_exclusion_rows_count": len(ambiguous_exclusion_rows),
            "same_ann_date_ambiguous_exclusion_rows_sample": ambiguous_exclusion_rows[:MAX_SAMPLE_ITEMS],
            "same_ann_date_ambiguous_exclusion_list_ref": RESTATEMENT_EXCLUSION_LIST_REL.as_posix(),
            "same_ann_date_conflict_examples": conflict_examples,
            "same_ann_date_duplicate_groups_resolved_total": resolved_same_ann_duplicates,
            "same_ann_date_duplicate_groups_resolved_by_non_null_preference": resolved_by_non_null_preference,
            "same_ann_date_duplicate_groups_resolved_by_f_ann_date_asof": resolved_by_f_ann_date,
            "same_ann_date_duplicate_resolution_examples": resolution_examples,
            "tables_with_f_ann_date_column": sorted(tables_with_f_ann_date),
            "resolution_rule": (
                "Same-ann-date duplicates may resolve only by a narrow nullable-field preference or by valid f_ann_date "
                "as-of disambiguation. Future signal code must choose the latest f_ann_date <= as_of, not latest-only."
            ),
        },
        [
            "The audit checks same-ann-date duplicate conflicts and multi-ann-date period groups.",
            "Latest-known selection must use ann_date / f_ann_date <= as_of; no later restatement is silently used.",
            "Unresolved same-ann-date groups without a version disambiguator are allowed only below the exclusion-rate cap and must be excluded from signal inputs.",
        ],
    )


def listing_rows(store: PayloadStore, context: AuditContext) -> dict[str, dict[str, Any]]:
    wanted = set(context.symbols)
    out: dict[str, dict[str, Any]] = {}
    for call_id in ["stock_basic_active_L", "stock_basic_delisted_D"]:
        for row in store.records(call_id):
            code = str(row.get("ts_code") or "")
            if code in wanted:
                out[code] = row
    return out


def panel_eligible_listing(row: dict[str, Any]) -> bool:
    list_date = normalize_yyyymmdd(row.get("list_date"))
    delist_date = normalize_yyyymmdd(row.get("delist_date"))
    return bool(list_date and list_date <= END_DATE and (delist_date is None or delist_date >= START_DATE))


def panel_eligible_symbols(store: PayloadStore, context: AuditContext) -> list[str]:
    listings = listing_rows(store, context)
    return sorted(symbol for symbol, row in listings.items() if panel_eligible_listing(row))


def raw_membership_symbols(store: PayloadStore, context: AuditContext) -> set[str]:
    wanted = set(context.symbols)
    out: set[str] = set()
    for row in store.records("index_member_all_sw_membership"):
        code = str(row.get("ts_code") or "")
        if code in wanted and normalize_yyyymmdd(row.get("in_date")) and row.get("l2_code"):
            out.add(code)
    return out


def repair_supplement_membership_symbols(repair: dict[str, Any], context: AuditContext) -> tuple[set[str], list[str]]:
    wanted = set(context.active_symbols)
    out: set[str] = set()
    invalid: list[str] = []
    for item in (repair.get("active_sw_supplement") or {}).get("symbol_results", []):
        symbol = str(item.get("symbol") or item.get("ts_code") or "")
        if symbol not in wanted or item.get("supplement_success") is not True:
            continue
        raw_ref = item.get("raw_payload_ref")
        if not raw_ref:
            invalid.append(symbol)
            continue
        payload = read_json(resolve_raw_ref(SW_REPAIR_RAW_ROOT, str(raw_ref)))
        records = payload.get("records")
        if not isinstance(records, list):
            invalid.append(symbol)
            continue
        has_valid_membership = any(
            isinstance(row, dict)
            and str(row.get("ts_code") or "") == symbol
            and normalize_yyyymmdd(row.get("in_date")) is not None
            and bool(row.get("l2_code"))
            for row in records
        )
        if has_valid_membership:
            out.add(symbol)
        else:
            invalid.append(symbol)
    return out, sorted(set(invalid))


def check_selection_time_status_source(store: PayloadStore, context: AuditContext) -> dict[str, Any]:
    failures: list[str] = []
    try:
        columns = store.columns(SELECTION_STATUS_CALL_ID)
        rows = store.records(SELECTION_STATUS_CALL_ID)
    except (KeyError, ValueError) as exc:
        columns = set()
        rows = []
        failures.append(type(exc).__name__)

    required_columns = {"ts_code", "name", "start_date", "end_date"}
    missing_columns = sorted(required_columns - columns)
    parseable_rows = 0
    veto_like_rows = 0
    universe_symbols = set(context.symbols)
    covered_universe_symbols: set[str] = set()
    for row in rows:
        symbol = str(row.get("ts_code") or "")
        if symbol in universe_symbols:
            covered_universe_symbols.add(symbol)
        if normalize_yyyymmdd(row.get("start_date")) is not None:
            parseable_rows += 1
        name = str(row.get("name") or "")
        if any(marker in name for marker in ["ST", "*ST", "S*ST", "SST", "退", "退市"]):
            veto_like_rows += 1

    ok = not failures and not missing_columns and parseable_rows > 0
    return make_check(
        "selection_time_status_source",
        "pass_full_main_board" if ok else "blocked_missing_required_source",
        {
            "source_call_id": SELECTION_STATUS_CALL_ID,
            "source_table": "security_name_change",
            "required_columns": sorted(required_columns),
            "missing_columns": missing_columns,
            "source_load_failures": failures,
            "row_count": len(rows),
            "parseable_start_date_row_count": parseable_rows,
            "universe_symbol_with_status_history_count": len(covered_universe_symbols),
            "veto_like_status_row_count": veto_like_rows,
            "current_stock_basic_name_veto_allowed": False,
        },
        [
            "Selection-time ST / delisting-name veto must be based on PIT name/status history.",
            "Current or final stock_basic.name is not a valid historical veto source.",
        ],
    )


def check_survivorship(store: PayloadStore, context: AuditContext, repair: dict[str, Any]) -> dict[str, Any]:
    listings = listing_rows(store, context)
    missing_symbols = sorted(set(context.symbols) - set(listings))
    active_status_failures = [
        symbol for symbol in context.active_symbols if str(listings.get(symbol, {}).get("list_status")) != "L"
    ]
    delisted_status_failures = [
        symbol for symbol in context.delisted_symbols if str(listings.get(symbol, {}).get("list_status")) != "D"
    ]

    eligible_decisions = 0
    invalid_listing_date_rows = 0
    for as_of in context.as_ofs:
        for symbol, row in listings.items():
            list_date = normalize_yyyymmdd(row.get("list_date"))
            delist_date = normalize_yyyymmdd(row.get("delist_date"))
            if list_date is None:
                invalid_listing_date_rows += 1
                continue
            if as_of < list_date:
                continue
            if delist_date is not None and as_of >= delist_date:
                continue
            eligible_decisions += 1

    terminal_failures: list[str] = []
    terminal_metrics: list[dict[str, Any]] = []
    post_panel_delist_not_terminal_required: list[str] = []
    extended_no_trade_terminal_symbols: list[str] = []
    extended_no_trade_unverified_symbols: list[str] = []
    for symbol in context.delisted_symbols:
        row = listings.get(symbol, {})
        delist_date = normalize_yyyymmdd(row.get("delist_date"))
        daily_payload = store.payload(call_id_for("daily", symbol))
        daily = [item for item in daily_payload.get("records", []) if isinstance(item, dict)]
        adj = store.records(call_id_for("adj_factor", symbol))
        last_trade_date = max((normalize_yyyymmdd(item.get("trade_date")) for item in daily), default=None)
        last_adj_date = max((normalize_yyyymmdd(item.get("trade_date")) for item in adj), default=None)
        terminal_gap_days = None
        post_last_trade_daily_rows_count = None
        extended_no_trade_verified = None
        terminal_required = bool(delist_date and START_DATE <= delist_date <= END_DATE)
        ok = not terminal_required
        if delist_date and delist_date > END_DATE:
            post_panel_delist_not_terminal_required.append(symbol)
        if terminal_required and last_trade_date and last_adj_date:
            terminal_gap_days = (parse_date(delist_date) - parse_date(last_trade_date)).days
            ok = 0 <= terminal_gap_days and last_adj_date >= last_trade_date
            if ok and terminal_gap_days > 90:
                post_last_trade_daily_rows_count = len(
                    [
                        item for item in daily
                        if (trade_date := normalize_yyyymmdd(item.get("trade_date"))) is not None
                        and last_trade_date < trade_date <= delist_date
                    ]
                )
                extended_no_trade_verified = daily_payload.get("call_status") in {"success", "empty"} and post_last_trade_daily_rows_count == 0
                if extended_no_trade_verified:
                    extended_no_trade_terminal_symbols.append(symbol)
                else:
                    extended_no_trade_unverified_symbols.append(symbol)
        if not ok:
            terminal_failures.append(symbol)
        terminal_metrics.append(
            {
                "symbol": symbol,
                "delist_date": delist_date,
                "terminal_return_required_for_2018_2025_panel": terminal_required,
                "last_trade_date": last_trade_date,
                "last_adj_factor_date": last_adj_date,
                "terminal_gap_days": terminal_gap_days,
                "terminal_return_input_available": ok,
                "post_last_trade_daily_rows_count": post_last_trade_daily_rows_count,
                "extended_no_trade_terminal_policy_verified": extended_no_trade_verified,
            }
        )

    raw_membership = raw_membership_symbols(store, context)
    active_supplement_symbols, invalid_supplement_symbols = repair_supplement_membership_symbols(repair, context)
    active_with_membership = (set(context.active_symbols) & raw_membership) | active_supplement_symbols
    active_non_exception = set(context.active_symbols) - set(context.active_delisting_shell_symbols)
    active_missing_non_exception = sorted(active_non_exception - active_with_membership)
    delisted_exception_symbols = sorted(set(context.delisted_symbols) & set(context.exception_symbols))
    exception_threshold_passed = len(context.exception_symbols) == REVIEWED_NO_INDUSTRY_EXCEPTION_COUNT

    status = (
        "pass_full_main_board"
        if not missing_symbols
        and not active_status_failures
        and not delisted_status_failures
        and invalid_listing_date_rows == 0
        and not terminal_failures
        and not extended_no_trade_unverified_symbols
        and not active_missing_non_exception
        and not invalid_supplement_symbols
        and exception_threshold_passed
        else "fail_data_not_ready"
    )
    return make_check(
        "survivorship_pit_universe",
        status,
        {
            "active_symbol_count": len(context.active_symbols),
            "delisted_symbol_count": len(context.delisted_symbols),
            "candidate_universe_count": len(context.symbols),
            "missing_symbols_count": len(missing_symbols),
            "missing_symbols_sample": sample(missing_symbols),
            "active_status_failure_count": len(active_status_failures),
            "active_status_failure_sample": sample(active_status_failures),
            "delisted_status_failure_count": len(delisted_status_failures),
            "delisted_status_failure_sample": sample(delisted_status_failures),
            "pit_membership_decisions_checked": eligible_decisions,
            "invalid_listing_date_rows": invalid_listing_date_rows,
            "terminal_return_input_failed_count": len(terminal_failures),
            "terminal_return_input_failed_symbols": terminal_failures,
            "delisted_terminal_return_inputs_sample": terminal_metrics[:MAX_SAMPLE_ITEMS],
            "post_panel_delisted_symbols_without_terminal_requirement_count": len(post_panel_delist_not_terminal_required),
            "post_panel_delisted_symbols_without_terminal_requirement_sample": sample(post_panel_delist_not_terminal_required),
            "extended_no_trade_terminal_return_symbols_count": len(extended_no_trade_terminal_symbols),
            "extended_no_trade_terminal_return_symbols_sample": sample(extended_no_trade_terminal_symbols),
            "extended_no_trade_terminal_policy": "If an in-panel delisted symbol has no later daily rows through delist_date, the last available daily+adj_factor row is treated as the terminal no-trade input; future return code must not manufacture a clean exit.",
            "extended_no_trade_terminal_unverified_count": len(extended_no_trade_unverified_symbols),
            "extended_no_trade_terminal_unverified_sample": sample(extended_no_trade_unverified_symbols),
            "raw_sw_membership_symbol_count": len(raw_membership),
            "active_supplemented_sw_symbol_count": len(active_supplement_symbols),
            "active_supplemented_sw_symbols_verified_from_repair_raw": True,
            "active_supplemented_sw_invalid_raw_count": len(invalid_supplement_symbols),
            "active_supplemented_sw_invalid_raw_sample": sample(invalid_supplement_symbols),
            "active_investable_missing_industry_count": len(active_missing_non_exception),
            "active_investable_missing_industry_sample": sample(active_missing_non_exception),
            "reviewed_no_industry_exception_count": len(context.exception_symbols),
            "delisted_no_industry_exception_count": len(delisted_exception_symbols),
            "active_delisting_shell_exception_symbols": list(context.active_delisting_shell_symbols),
            "industry_normalization_policy": {
                "silent_industry_fill_allowed": False,
                "drop_exception_names_from_returns_or_risk_allowed": False,
                "exclude_exception_symbols_from_industry_neutral_denominators": True,
                "keep_exception_symbols_in_returns_risk_drawdown_and_coverage": True,
            },
            "industry_normalization_exclusion_symbols_sample": sample(context.exception_symbols),
            "industry_normalization_exclusion_symbol_count": len(context.exception_symbols),
        },
        [
            "Full main-board active and 2018-2025 delisted symbols stay in the PIT universe.",
            "Reviewed no-industry exceptions are excluded only from industry-normalization denominators, not returns or risk.",
            "Delisted names must have terminal daily and adj_factor inputs near delisting.",
            "Extended no-trade delisted names must have no later daily rows through delist date before the last available row can be accepted as terminal input.",
        ],
    )


def valid_date_count(rows: list[dict[str, Any]], field: str) -> int:
    return sum(1 for row in rows if normalize_yyyymmdd(row.get(field)) is not None)


def check_return_benchmark(store: PayloadStore, context: AuditContext) -> dict[str, Any]:
    failures: list[str] = []
    empty_daily = 0
    empty_adj = 0
    empty_dividend = 0
    sample_metrics: list[dict[str, Any]] = []
    total_daily_rows = 0
    total_adj_rows = 0
    total_dividend_rows = 0
    eligible_symbols = panel_eligible_symbols(store, context)
    post_panel_symbols = sorted(set(context.symbols) - set(eligible_symbols))
    for symbol in eligible_symbols:
        daily = store.records(call_id_for("daily", symbol))
        adj = store.records(call_id_for("adj_factor", symbol))
        dividend = store.records(dividend_call_id(symbol))
        daily_dates = {normalize_yyyymmdd(row.get("trade_date")) for row in daily}
        adj_dates = {normalize_yyyymmdd(row.get("trade_date")) for row in adj}
        daily_dates.discard(None)
        adj_dates.discard(None)
        overlap_count = len(daily_dates & adj_dates)
        dividend_columns = store.columns(dividend_call_id(symbol))
        has_dividend_source = {"ann_date", "ex_date"}.issubset(dividend_columns)
        ok = bool(daily_dates) and bool(adj_dates) and overlap_count > 0 and has_dividend_source
        if not ok:
            failures.append(symbol)
        if not daily_dates:
            empty_daily += 1
        if not adj_dates:
            empty_adj += 1
        if not dividend:
            empty_dividend += 1
        total_daily_rows += len(daily)
        total_adj_rows += len(adj)
        total_dividend_rows += len(dividend)
        if len(sample_metrics) < MAX_SAMPLE_ITEMS:
            sample_metrics.append(
                {
                    "symbol": symbol,
                    "daily_row_count": len(daily),
                    "adj_factor_row_count": len(adj),
                    "daily_adj_overlap_count": overlap_count,
                    "dividend_row_count": len(dividend),
                    "valid_dividend_ex_date_count": valid_date_count(dividend, "ex_date"),
                    "return_input_shape_ok": ok,
                }
            )

    benchmark_failures: list[str] = []
    benchmark_metrics = []
    first_symbol = eligible_symbols[0] if eligible_symbols else context.symbols[0]
    first_dates = {normalize_yyyymmdd(row.get("trade_date")) for row in store.records(call_id_for("daily", first_symbol))}
    first_dates.discard(None)
    for benchmark_label, benchmark_code in BENCHMARKS.items():
        try:
            rows = store.records(index_call_id(benchmark_code))
            columns = store.columns(index_call_id(benchmark_code))
            load_error = None
        except (KeyError, ValueError) as exc:
            rows = []
            columns = set()
            load_error = type(exc).__name__
        dates = {normalize_yyyymmdd(row.get("trade_date")) for row in rows}
        dates.discard(None)
        overlap = len(dates & first_dates)
        ok = {"trade_date", "close"}.issubset(columns) and len(rows) > 0 and overlap > 0
        if not ok:
            benchmark_failures.append(benchmark_code)
        benchmark_metrics.append(
            {
                "benchmark": benchmark_label,
                "benchmark_code": benchmark_code,
                "row_count": len(rows),
                "has_trade_date_close": {"trade_date", "close"}.issubset(columns),
                "open_required": False,
                "overlap_with_stock_trade_dates": overlap,
                "load_error": load_error,
            }
        )

    status = "pass_full_main_board" if not failures and not benchmark_failures else "fail_data_not_ready"
    return make_check(
        "return_benchmark_measurement_basis",
        status,
        {
            "candidate_universe_count": len(context.symbols),
            "symbols_checked": len(eligible_symbols),
            "post_panel_listing_symbols_excluded_from_return_shape_count": len(post_panel_symbols),
            "post_panel_listing_symbols_excluded_from_return_shape_sample": sample(post_panel_symbols),
            "total_daily_rows": total_daily_rows,
            "total_adj_factor_rows": total_adj_rows,
            "total_dividend_rows": total_dividend_rows,
            "symbols_with_empty_daily": empty_daily,
            "symbols_with_empty_adj_factor": empty_adj,
            "symbols_with_empty_dividend": empty_dividend,
            "symbols_with_failed_return_input_shape_count": len(failures),
            "symbols_with_failed_return_input_shape_sample": sample(failures),
            "symbol_return_inputs_sample": sample_metrics,
            "benchmark_inputs": benchmark_metrics,
            "benchmarks_with_failed_anchor_input_shape": benchmark_failures,
            "benchmark_return_basis": BENCHMARK_RETURN_BASIS,
            "same_anchor_policy": "Future return calculation must use stock adj_factor close-to-close and H-code benchmark total-return close-to-close on the same entry/exit anchors; this audit checks input shape only and does not calculate returns.",
            "silent_zero_fill_used": False,
        },
        [
            "Daily close, adj_factor, dividend-source, and H-code total-return benchmark close input shapes are checked.",
            "No return, benchmark excess, signal, or alpha is calculated in this audit.",
        ],
    )


def eligible_symbols_for_year(store: PayloadStore, context: AuditContext, year: int) -> list[str]:
    year_start = f"{year}0101"
    year_end = f"{year}1231"
    out = []
    for symbol, row in listing_rows(store, context).items():
        list_date = normalize_yyyymmdd(row.get("list_date"))
        delist_date = normalize_yyyymmdd(row.get("delist_date"))
        if list_date and list_date <= year_end and (delist_date is None or delist_date >= year_start):
            out.append(symbol)
    return sorted(out)


def check_temporal_coverage(store: PayloadStore, context: AuditContext) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for year in range(2018, 2026):
        eligible = eligible_symbols_for_year(store, context, year)
        for table in FUNDAMENTAL_TABLES:
            covered: set[str] = set()
            for symbol in eligible:
                for row in store.records(call_id_for(table, symbol)):
                    ann_date = normalize_yyyymmdd(row.get("ann_date"))
                    if ann_date and START_DATE <= ann_date <= END_DATE and ann_date.startswith(str(year)):
                        covered.add(symbol)
            pct = (len(covered) / len(eligible) * 100.0) if eligible else 0.0
            rows.append(
                {
                    "year": year,
                    "table_id": table,
                    "eligible_symbol_count": len(eligible),
                    "covered_symbol_count": len(covered),
                    "coverage_pct": round(pct, 6),
                    "status": "pass_full_main_board" if pct >= TEMPORAL_COVERAGE_THRESHOLD_PCT else "below_threshold",
                }
            )
    below = [row for row in rows if row["status"] != "pass_full_main_board"]
    usable_start_year = None
    for year in range(2018, 2026):
        candidate = [row for row in rows if row["year"] >= year]
        if candidate and all(row["status"] == "pass_full_main_board" for row in candidate):
            usable_start_year = year
            break
    return make_check(
        "temporal_coverage_bias",
        "coverage_characterized_full_main_board",
        {
            "threshold_pct": TEMPORAL_COVERAGE_THRESHOLD_PCT,
            "usable_start_year": usable_start_year,
            "below_threshold_cell_count": len(below),
            "below_threshold_cells": below,
        },
        [
            "Coverage is characterized by year and table for the full main-board candidate universe.",
            "Low early coverage narrows or blocks the usable signal-search window; it is not silently ignored.",
        ],
    ), rows


def self_test_payload(call_id: str, columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"call_id": call_id, "call_status": "success", "columns": columns, "records": rows}


def build_self_test_store() -> tuple[PayloadStore, AuditContext, dict[str, Any]]:
    active = ["000001.SZ", "600001.SH"]
    delisted = ["000666.SZ"]
    symbols = active + delisted
    payloads: dict[str, dict[str, Any]] = {
        "trade_calendar_2018_2025": self_test_payload(
            "trade_calendar_2018_2025",
            ["cal_date", "is_open"],
            [{"cal_date": f"{year}{month:02d}28", "is_open": "1"} for year in range(2018, 2026) for month in range(1, 13)],
        ),
        "stock_basic_active_L": self_test_payload(
            "stock_basic_active_L",
            ["ts_code", "list_status", "list_date", "delist_date"],
            [{"ts_code": symbol, "list_status": "L", "list_date": "20000101", "delist_date": None} for symbol in active],
        ),
        "stock_basic_delisted_D": self_test_payload(
            "stock_basic_delisted_D",
            ["ts_code", "list_status", "list_date", "delist_date"],
            [{"ts_code": "000666.SZ", "list_status": "D", "list_date": "19961231", "delist_date": "20231026"}],
        ),
        "index_member_all_sw_membership": self_test_payload(
            "index_member_all_sw_membership",
            ["ts_code", "l2_code", "l2_name", "in_date", "out_date"],
            [{"ts_code": symbol, "l2_code": "L2", "l2_name": "Industry", "in_date": "20100101", "out_date": None} for symbol in symbols],
        ),
        SELECTION_STATUS_CALL_ID: self_test_payload(
            SELECTION_STATUS_CALL_ID,
            ["ts_code", "name", "start_date", "end_date", "change_reason"],
            [{"ts_code": "000666.SZ", "name": "退市示例", "start_date": "20230101", "end_date": None, "change_reason": "unit_test"}],
        ),
    }
    for table in FUNDAMENTAL_TABLES:
        columns = ["ts_code", "ann_date", "f_ann_date", "end_date"]
        if table == "income":
            columns += ["revenue", "n_income_attr_p"]
        elif table == "balancesheet":
            columns += ["total_assets", "total_liab", "total_hldr_eqy_exc_min_int"]
        elif table == "cashflow":
            columns += ["n_cashflow_act"]
        else:
            columns += ["roe", "profit_dedt"]
        for symbol in symbols:
            rows = [{"ts_code": symbol, "ann_date": f"{year}0430", "f_ann_date": f"{year}0430", "end_date": f"{year - 1}1231"} for year in range(2018, 2026)]
            payloads[call_id_for(table, symbol)] = self_test_payload(call_id_for(table, symbol), columns, rows)
    price_rows = [{"trade_date": f"{year}1231", "open": 10.0, "close": 10.5} for year in range(2018, 2026)]
    terminal = [{"trade_date": "20231025", "open": 8.0, "close": 8.5}]
    for symbol in symbols:
        symbol_rows = [row for row in price_rows if symbol != "000666.SZ" or row["trade_date"] <= "20221231"]
        rows = [{"ts_code": symbol, **row} for row in (symbol_rows + terminal if symbol == "000666.SZ" else symbol_rows)]
        payloads[call_id_for("daily", symbol)] = self_test_payload(call_id_for("daily", symbol), ["ts_code", "trade_date", "open", "close"], rows)
        payloads[call_id_for("adj_factor", symbol)] = self_test_payload(
            call_id_for("adj_factor", symbol),
            ["ts_code", "trade_date", "adj_factor"],
            [{"ts_code": symbol, "trade_date": row["trade_date"], "adj_factor": 1.0} for row in rows],
        )
        payloads[dividend_call_id(symbol)] = self_test_payload(
            dividend_call_id(symbol),
            ["ts_code", "ann_date", "ex_date"],
            [{"ts_code": symbol, "ann_date": "20200430", "ex_date": "20200701"}],
        )
    for benchmark in BENCHMARKS.values():
        payloads[index_call_id(benchmark)] = self_test_payload(
            index_call_id(benchmark),
            ["ts_code", "trade_date", "close"],
            [{"ts_code": benchmark, "trade_date": row["trade_date"], "close": row["close"]} for row in price_rows],
        )
    store = PayloadStore(raw_root=Path("."), payloads=payloads)
    context = AuditContext(active_symbols=active, delisted_symbols=delisted, exception_symbols=[], active_delisting_shell_symbols=[], as_ofs=monthly_last_open_days(store))
    repair = {"active_sw_supplement": {"symbol_results": []}}
    return store, context, repair


def full_board_self_test_result(fixture_id: str, target_check_id: str, check: dict[str, Any], detected: bool) -> dict[str, Any]:
    return {
        "fixture_id": fixture_id,
        "checker_origin": "full_main_board_data_integrity_runner",
        "target_check_id": target_check_id,
        "status": "pass" if detected else "fail",
        "detected_expected_violation": detected,
        "observed_check_status": check["status"],
        "metrics": check["metrics"],
    }


def run_full_board_runner_self_tests() -> list[dict[str, Any]]:
    store, context, repair = build_self_test_store()
    tests: list[dict[str, Any]] = []

    payloads = copy.deepcopy(store.payloads)
    payloads[call_id_for("income", "000001.SZ")]["columns"] = [c for c in payloads[call_id_for("income", "000001.SZ")]["columns"] if c != "ann_date"]
    check = check_fundamental_pit(PayloadStore(raw_root=Path("."), payloads=payloads), context)
    tests.append(full_board_self_test_result("full_main_board_fundamental_missing_ann_date_column_blocks", "fundamental_pit", check, check["status"] == "blocked_missing_required_source"))

    payloads = copy.deepcopy(store.payloads)
    payloads[call_id_for("income", "000001.SZ")]["records"].append({"ts_code": "000001.SZ", "ann_date": "20200430", "f_ann_date": "20200430", "end_date": "20191231", "revenue": 999.0})
    check = check_restatement_revision(PayloadStore(raw_root=Path("."), payloads=payloads), context)
    tests.append(full_board_self_test_result("full_main_board_restatement_same_ann_date_conflict_fails", "restatement_revision_asof", check, check["status"] == "fail_data_not_ready"))

    payloads = copy.deepcopy(store.payloads)
    payloads.pop(SELECTION_STATUS_CALL_ID)
    check = check_selection_time_status_source(PayloadStore(raw_root=Path("."), payloads=payloads), context)
    tests.append(full_board_self_test_result("full_main_board_selection_status_source_missing_fails", "selection_time_status_source", check, check["status"] == "blocked_missing_required_source"))

    payloads = copy.deepcopy(store.payloads)
    payloads[call_id_for("daily", "000666.SZ")]["records"] = []
    check = check_survivorship(PayloadStore(raw_root=Path("."), payloads=payloads), context, repair)
    tests.append(full_board_self_test_result("full_main_board_survivorship_missing_terminal_return_fails", "survivorship_pit_universe", check, check["status"] == "fail_data_not_ready"))

    payloads = copy.deepcopy(store.payloads)
    payloads[index_call_id(BENCHMARKS["CSI300"])]["records"] = []
    check = check_return_benchmark(PayloadStore(raw_root=Path("."), payloads=payloads), context)
    tests.append(full_board_self_test_result("full_main_board_return_benchmark_missing_total_return_close_fails", "return_benchmark_measurement_basis", check, check["status"] == "fail_data_not_ready"))

    payloads = copy.deepcopy(store.payloads)
    for symbol in context.symbols:
        cid = call_id_for("income", symbol)
        payloads[cid]["records"] = [row for row in payloads[cid]["records"] if not row["ann_date"].startswith("2018")]
    check, _rows = check_temporal_coverage(PayloadStore(raw_root=Path("."), payloads=payloads), context)
    tests.append(full_board_self_test_result("full_main_board_temporal_coverage_below_threshold_detected", "temporal_coverage_bias", check, check["metrics"]["below_threshold_cell_count"] > 0))

    return tests


def run_required_self_tests() -> list[dict[str, Any]]:
    preregistration = read_json(PREREGISTRATION_PATH)
    legacy = []
    for item in base_audit.run_required_self_tests(preregistration):
        copied = dict(item)
        copied["checker_origin"] = "legacy_preregistration_base_audit"
        legacy.append(copied)
    return legacy + run_full_board_runner_self_tests()


def decision_from_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [check["check_id"] for check in checks if check["hard_check"] and check["status"] == "fail_data_not_ready"]
    blocked = [check["check_id"] for check in checks if check["hard_check"] and check["status"] == "blocked_missing_required_source"]
    coverage = next(check for check in checks if check["check_id"] == "temporal_coverage_bias")
    usable_start_year = coverage["metrics"].get("usable_start_year")
    below_threshold_count = coverage["metrics"].get("below_threshold_cell_count", 0)
    if blocked:
        status = "blocked_missing_required_source"
        plain = "Full main-board audit did not pass: required data source or columns are missing. Do not search alpha."
        may_signal = False
        hard_pass = False
    elif failed:
        status = "fail_data_not_ready"
        plain = "Full main-board audit found data-integrity failures. Do not search alpha."
        may_signal = False
        hard_pass = False
    elif usable_start_year is None:
        status = "fail_data_not_ready"
        plain = "Full main-board hard checks passed, but coverage cannot define a usable start year. Do not search alpha."
        may_signal = False
        hard_pass = True
    elif below_threshold_count:
        status = "pass_hard_checks_with_limited_usable_window"
        plain = f"Full main-board hard checks passed, but signal search must start no earlier than {usable_start_year}."
        may_signal = True
        hard_pass = True
    else:
        status = "passed_full_main_board_data_integrity_for_signal_search"
        plain = "Full main-board data audit passed. The next separate gate may run the frozen signal search."
        may_signal = True
        hard_pass = True
    return {
        "audit_status": status,
        "hard_checks_pass": hard_pass,
        "usable_start_year": usable_start_year,
        "data_can_be_used_for_alpha_now": False,
        "signal_search_may_be_executed_after_review": may_signal,
        "signal_search_authorized_by_this_report": False,
        "alpha_found": False,
        "plain_result": plain,
        "next_action": "If this report passes independent review, run the separate frozen signal-search gate only when allowed; otherwise fix the failed data checks first.",
    }


def build_report(*, summary_path: Path, raw_root: Path, output_dir: Path, generated_at: str, sidecars: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = read_json(summary_path)
    validate_materialization_summary(summary)
    repair = validate_boundary_refs()
    manifest = load_endpoint_manifest(summary, raw_root)
    store = PayloadStore(raw_root=raw_root, manifest=manifest)
    context = build_context(store, repair)
    self_tests = run_required_self_tests()

    checks = [
        check_fundamental_pit(store, context),
        check_restatement_revision(store, context, sidecars),
        check_selection_time_status_source(store, context),
        check_survivorship(store, context, repair),
        check_return_benchmark(store, context),
    ]
    coverage_check, coverage_rows = check_temporal_coverage(store, context)
    checks.append(coverage_check)
    return {
        "schema_name": "a_long_full_main_board_data_integrity_audit_report",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_full_main_board_data_integrity_audit_report_20260605",
        "source_refs": [
            "docs/a_long_full_main_board_materialization_execution_summary_20260605.json",
            "docs/a_long_full_main_board_signal_search_execution_packet_20260605.json",
            "docs/a_long_scaled_delisted_no_industry_boundary_decision_20260605.json",
            "docs/a_long_main_board_sw_coverage_repair_execution_summary_20260604.json",
            "data/a_long/raw/tushare/main_board_sw_coverage_repair_20260604/",
            "research/preregistrations/a_long_data_integrity_audit_20260603.json",
            "docs/system_risk_register.md",
        ],
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_full_main_board_data_integrity_audit",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "materialized_raw_read_only": True,
            "reviewed_sw_repair_raw_read_only": True,
            "provider_call_executed": False,
            "tushare_call_executed": False,
            "data_fetch_executed": False,
            "raw_rows_in_tracked_report": False,
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
            "materialization_summary_ref": "docs/a_long_full_main_board_materialization_execution_summary_20260605.json",
            "raw_root": RAW_ROOT_REL.as_posix() + "/",
            "endpoint_results_count": len(manifest),
            "network_calls_executed": 0,
            "provider_calls_executed": 0,
            "self_tests_required": len(self_tests),
            "self_tests_passed": len([item for item in self_tests if item["status"] == "pass"]),
            "tracked_report_contains_raw_records": False,
            "tracked_report_contains_endpoint_results": False,
            "tracked_report_contains_secret": False,
            "tracked_report_contains_request_url": False,
        },
        "full_main_board_boundary": {
            "board_scope": "main_board_only",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "active_symbol_count": len(context.active_symbols),
            "delisted_symbol_count": len(context.delisted_symbols),
            "candidate_universe_count": len(context.symbols),
            "reviewed_no_industry_exception_count": len(context.exception_symbols),
            "active_delisting_shell_symbols": list(context.active_delisting_shell_symbols),
            "benchmark_indices": list(BENCHMARKS.values()),
            "monthly_as_of_count": len(context.as_ofs),
            "not_full_market_or_cross_board": True,
        },
        "required_runner_self_tests": self_tests,
        "check_results": checks,
        "coverage_by_year": coverage_rows,
        "decision": decision_from_checks(checks),
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
            display_path(output_dir / "audit_report.json"),
            display_path(output_dir / "check_summary.csv"),
            display_path(output_dir / "coverage_by_year.csv"),
            display_path(output_dir / "restatement_ambiguous_exclusions.csv"),
        ],
        "limitations": [
            "This audit reads already-materialized raw payloads only and executes no provider call.",
            "This audit does not run signal search, calculate alpha, authorize production, or provide ship-gate evidence.",
            "Reviewed no-industry names remain in returns/risk/drawdown/coverage and are excluded only from industry-normalization denominators.",
            "Unresolved restatement duplicate groups in restatement_ambiguous_exclusions.csv must be excluded from future signal inputs.",
        ],
    }


def check_summary_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "check_id": item["check_id"],
            "status": item["status"],
            "hard_check": item["hard_check"],
            "blocks_signal_search": item["blocks_signal_search"],
            "finding_count": len(item["findings"]),
        }
        for item in report["check_results"]
    ]


def restatement_exclusion_rows(report: dict[str, Any], sidecars: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if sidecars is not None:
        rows = sidecars.get("restatement_ambiguous_exclusions", [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    for item in report["check_results"]:
        if item["check_id"] == "restatement_revision_asof":
            rows = item["metrics"].get("same_ann_date_ambiguous_exclusion_rows", [])
            return [row for row in rows if isinstance(row, dict)]
    return []


def run(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = args.generated_at or iso_now()
    sidecars: dict[str, Any] = {}
    report = build_report(
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        output_dir=args.output_dir,
        generated_at=generated_at,
        sidecars=sidecars,
    )
    validate_json(SCHEMA_PATH, report)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "audit_report.json", report)
    write_csv(args.output_dir / "check_summary.csv", check_summary_rows(report))
    write_csv(args.output_dir / "coverage_by_year.csv", report["coverage_by_year"])
    write_csv(args.output_dir / "restatement_ambiguous_exclusions.csv", restatement_exclusion_rows(report, sidecars))
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run(args)
    decision = report["decision"]
    print(
        json.dumps(
            {
                "audit_status": decision["audit_status"],
                "plain_result": decision["plain_result"],
                "next_action": decision["next_action"],
                "report_ref": display_path(args.output_dir / "audit_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
