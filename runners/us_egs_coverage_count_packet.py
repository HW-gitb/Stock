from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.us_egs_sample_validation import (
    DEFAULT_TIMEOUT_SECONDS,
    FMP_STABLE_ENDPOINTS,
    FetchRecord,
    JsonHttpClient,
    endpoint_field_presence,
    fetch_and_store,
    fmp_url,
    payload_rows,
    read_required_env,
    validate_raw_root,
    write_json_atomic,
)


APPROVAL_PATH = ROOT / "docs" / "provider_evidence_p1_us_coverage_count_access_packet_approval_20260602.json"
SUMMARY_PATH = ROOT / "docs" / "provider_evidence_p1_us_coverage_count_execution_summary_20260602.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_egs_coverage_count_20260602/fmp_stable")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"
EXPECTED_SYMBOLS = ["AAPL", "MSFT", "NVDA", "JPM", "XOM"]
EXPECTED_ENDPOINT_FAMILIES = [endpoint["endpoint_family"] for endpoint in FMP_STABLE_ENDPOINTS]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the user-approved narrow US EGS coverage-count packet: "
            "5 active symbols x 6 FMP stable endpoint families, raw payloads only "
            "under gitignored provider_samples/, tracked summary with no secrets."
        )
    )
    parser.add_argument("--approval-path", type=Path, default=APPROVAL_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument(
        "--dry-run-env",
        action="store_true",
        help="Validate approval and environment boundary without fetching provider data.",
    )
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_and_validate_approval(path: Path) -> dict[str, Any]:
    approval = read_json(path)
    scope = approval.get("scope") or {}
    universe = approval.get("sample_universe") or {}
    call_budget = approval.get("endpoint_call_budget") or {}
    cost = approval.get("cost_and_access_boundary") or {}
    storage = approval.get("storage_and_secret_boundary") or {}
    prohibited = approval.get("prohibited_claims") or {}

    if approval.get("schema_name") != "provider_p1_coverage_count_access_packet_approval":
        raise ValueError("coverage-count approval schema_name mismatch")
    if approval.get("approval_ref") != "user_chat_20260602_approved_and_execute":
        raise ValueError("coverage-count approval must reference the user approval")
    if scope.get("approval_status") != "approved_by_user_for_exact_packet":
        raise ValueError("coverage-count approval_status must be exact-packet approved")
    for field in [
        "coverage_count_execution_allowed",
        "fmp_stable_endpoint_calls_allowed",
        "count_only_response_inspection_allowed",
        "raw_payload_storage_allowed",
    ]:
        if scope.get(field) is not True:
            raise ValueError(f"approval must keep {field}=true")
    for field in [
        "sec_api_calls_allowed",
        "yfinance_allowed",
        "new_token_or_trial_allowed",
        "paid_access_allowed",
        "full_market_download_allowed",
        "provider_status_polling_allowed",
        "fallback_execution_allowed",
        "fixture_generation_allowed",
        "field_mapping_or_parser_implementation_allowed",
        "return_calculation_allowed",
        "corporate_action_reconciliation_allowed",
        "provider_selection_allowed",
        "provider_adapter_allowed",
        "datahub_table_implementation_allowed",
        "production_runner_consumption_allowed",
        "phase7c_authorized_by_this_approval",
        "production_ready_claim_allowed",
    ]:
        if scope.get(field) is not False:
            raise ValueError(f"approval must keep {field}=false")
    if universe.get("symbols") != EXPECTED_SYMBOLS:
        raise ValueError("coverage-count universe must be exactly AAPL/MSFT/NVDA/JPM/XOM")
    if universe.get("max_symbols") != 5 or universe.get("inactive_or_delisted_in_scope") is not False:
        raise ValueError("coverage-count universe must stay bounded to 5 active symbols")
    approved_families = [item.get("endpoint_family") for item in approval.get("endpoint_families", [])]
    if approved_families != EXPECTED_ENDPOINT_FAMILIES:
        raise ValueError("coverage-count endpoint families must match the FMP stable endpoint list")
    if call_budget.get("max_total_endpoint_calls") != 30:
        raise ValueError("coverage-count max_total_endpoint_calls must be 30")
    if call_budget.get("retry_count_allowed") != 0:
        raise ValueError("coverage-count packet must not retry without a new approval")
    if cost.get("approved_spend_usd") != 0 or cost.get("existing_fmp_key_only") is not True:
        raise ValueError("coverage-count packet must be $0 and use only the existing FMP key")
    for field in ["new_token_request_allowed", "trial_request_allowed", "paid_upgrade_allowed", "provider_contact_allowed"]:
        if cost.get(field) is not False:
            raise ValueError(f"coverage-count approval must keep {field}=false")
    if storage.get("raw_sample_storage_path") != RAW_SAMPLE_REL_ROOT.as_posix() + "/":
        raise ValueError("raw sample storage path must stay under the approved coverage provider_samples folder")
    for field in [
        "raw_sample_storage_must_be_gitignored",
    ]:
        if storage.get(field) is not True:
            raise ValueError(f"coverage-count approval must keep {field}=true")
    for field in [
        "tracked_summary_contains_raw_rows",
        "request_urls_in_summary_allowed",
        "api_key_logging_allowed",
        "secrets_in_repo_allowed",
        "raw_retention_authorizes_production_storage",
    ]:
        if storage.get(field) is not False:
            raise ValueError(f"coverage-count approval must keep {field}=false")
    for field, value in prohibited.items():
        if value is not False:
            raise ValueError(f"coverage-count prohibited claim must stay false: {field}")
    return approval


def run_coverage_count_packet(
    *,
    approval_path: Path = APPROVAL_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    generated_at: str | None = None,
    client: JsonHttpClient | None = None,
    dry_run_env: bool = False,
) -> dict[str, Any]:
    approval = load_and_validate_approval(approval_path)
    validate_raw_root(raw_root)
    generated_at = generated_at or iso_now()
    fmp_env = read_required_env("FMP_API_KEY")
    env_summary = {
        "fmp_api_key_present": True,
        "fmp_api_key_source": fmp_env.source,
        "secrets_logged": False,
    }
    if dry_run_env:
        return build_summary(
            approval=approval,
            generated_at=generated_at,
            env_summary=env_summary,
            endpoint_records=[],
            dry_run_env=True,
        )

    max_calls = int(approval["endpoint_call_budget"]["max_total_endpoint_calls"])
    client = client or JsonHttpClient()
    endpoint_records: list[FetchRecord] = []
    for symbol in EXPECTED_SYMBOLS:
        for endpoint in FMP_STABLE_ENDPOINTS:
            if len(endpoint_records) >= max_calls:
                raise RuntimeError("coverage-count endpoint call budget exceeded")
            url = fmp_url(
                endpoint["path_template"],
                symbol,
                dict(endpoint.get("params") or {}),
                fmp_env.value,
                endpoint_mode="stable",
            )
            endpoint_records.append(
                fetch_and_store(
                    client,
                    url=url,
                    provider_id="financial_modeling_prep",
                    endpoint_family=endpoint["endpoint_family"],
                    symbol=symbol,
                    raw_root=raw_root,
                )
            )

    summary = build_summary(
        approval=approval,
        generated_at=generated_at,
        env_summary=env_summary,
        endpoint_records=endpoint_records,
        dry_run_env=False,
    )
    write_json_atomic(summary, summary_path)
    return summary


def build_summary(
    *,
    approval: dict[str, Any],
    generated_at: str,
    env_summary: dict[str, Any],
    endpoint_records: list[FetchRecord],
    dry_run_env: bool,
) -> dict[str, Any]:
    endpoint_results = [summarize_endpoint(record) for record in endpoint_records]
    endpoint_errors = sum(1 for record in endpoint_records if not record.ok)
    validation_status = "completed_with_endpoint_errors" if endpoint_errors else "completed"
    if dry_run_env:
        validation_status = "completed"
    aggregate = aggregate_count_metrics(endpoint_results)
    symbol_results = [summarize_symbol(symbol, endpoint_results) for symbol in EXPECTED_SYMBOLS]
    decision = (
        "bounded_coverage_smoke_completed_with_errors_keep_sr_provider_001_open"
        if endpoint_errors
        else "bounded_coverage_smoke_completed_keep_sr_provider_001_open"
    )
    return {
        "schema_name": "provider_p1_coverage_count_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "approval_ref": "docs/provider_evidence_p1_us_coverage_count_access_packet_approval_20260602.json",
        "schema_ref": "schemas/provider_p1_coverage_count_execution_summary.schema.json",
        "scope": {
            "phase": "7b-2",
            "purpose": "fmp_stable_coverage_count_execution_summary",
            "validation_status": validation_status,
            "coverage_count_execution_performed": not dry_run_env,
            "fmp_stable_endpoint_calls_performed": not dry_run_env,
            "count_only_response_inspection_performed": not dry_run_env,
            "raw_payload_storage_performed": not dry_run_env,
            "sec_api_calls_performed": False,
            "yfinance_used": False,
            "full_market_download_performed": False,
            "provider_status_polling_performed": False,
            "fallback_execution_performed": False,
            "fixture_generation_performed": False,
            "return_calculation_performed": False,
            "corporate_action_reconciliation_performed": False,
            "field_mapping_or_parser_implementation_performed": False,
            "provider_selection_allowed": False,
            "provider_adapter_allowed": False,
            "datahub_table_implementation_allowed": False,
            "production_runner_consumption_allowed": False,
            "phase7c_authorized_by_this_summary": False,
            "manual_order_only": True,
            "ship_gate_relaxed": False,
            "production_ready_claim_allowed": False,
        },
        "environment": env_summary,
        "storage": {
            "raw_sample_storage_path": RAW_SAMPLE_REL_ROOT.as_posix() + "/",
            "raw_samples_gitignored": True,
            "tracked_summary_contains_raw_rows": False,
            "secrets_in_summary": False,
            "request_urls_in_summary": False,
        },
        "sample_universe": {
            "symbols": approval["sample_universe"]["symbols"],
            "max_symbols": approval["sample_universe"]["max_symbols"],
            "universe_role": approval["sample_universe"]["universe_role"],
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": approval["endpoint_call_budget"]["max_total_endpoint_calls"],
            "actual_total_endpoint_calls": len(endpoint_records),
            "within_budget": len(endpoint_records) <= int(approval["endpoint_call_budget"]["max_total_endpoint_calls"]),
        },
        "endpoint_results": endpoint_results,
        "symbol_results": symbol_results,
        "aggregate_count_metrics": aggregate,
        "coverage_smoke_decision": {
            "decision": decision,
            "sr_provider_001_closed": False,
            "provider_selection_allowed": False,
            "phase7c_allowed": False,
            "rationale": (
                "This packet verifies bounded FMP stable response-shape and required-field counts "
                "for five active symbols only. It does not cover inactive / delisted names, "
                "current terms, production storage, PIT row validation, price adjustment, "
                "corporate actions, SEC parser work, fallback execution, stability, provider "
                "selection, DataHub, Phase 7c, or ship-gate evidence."
            ),
        },
        "prohibited_claims": {
            "provider_selected": False,
            "provider_ranked": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "sec_api_used": False,
            "paid_access_used": False,
            "raw_rows_in_tracked_summary": False,
            "fixture_generated": False,
            "return_calculation_performed": False,
            "corporate_action_reconciliation_performed": False,
            "field_mapping_or_parser_implemented": False,
            "provider_status_polled": False,
            "fallback_executed": False,
            "datahub_or_adapter_implemented": False,
            "production_runner_consumption_authorized": False,
            "phase7c_authorized": False,
            "ship_gate_evidence_claimed": False,
            "production_ready_claimed": False,
        },
        "limitations": [
            "This is a five-symbol active-name coverage smoke, not full-market coverage or survivorship-safe security-master evidence.",
            "FMP stable endpoint response success does not prove current terms, production storage rights, PIT semantics, adjustment mode, corporate-action handling, fallback behavior, stability, or production readiness.",
            "Count-only response inspection summarizes row counts and required-field presence; it does not implement field mapping, parser logic, fixtures, returns, or corporate-action reconciliation.",
            "No SEC EDGAR, yfinance, provider status polling, provider contact, paid access, adapter, DataHub table, production runner consumption, Phase 7c authorization, or ship-gate evidence is included.",
        ],
        "next_steps": [
            "Have Claude review the approval, runner, raw-storage boundary, no-secret summary, schema tests, and SR-PROVIDER-001 wording before any commit.",
            "Keep SR-PROVIDER-001 open for current terms / production storage, PIT row validation, price adjustment, corporate actions, SEC parser implementation, fallback execution, stability evidence, provider selection, DataHub, runner consumption, and Phase 7c.",
        ],
    }


def summarize_endpoint(record: FetchRecord) -> dict[str, Any]:
    payload = record.payload
    rows = payload_rows(record.endpoint_family, payload)
    field_presence = endpoint_field_presence(record.endpoint_family, payload, endpoint_mode="stable")
    return {
        "provider_id": record.provider_id,
        "endpoint_family": record.endpoint_family,
        "symbol": record.symbol,
        "status": "ok" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith("provider_samples/"),
        "fmp_endpoint_mode": "stable",
        "payload_shape": {
            "payload_type": type(payload).__name__,
            "top_level_key_count": len(payload) if isinstance(payload, dict) else None,
            "row_count": len(rows) if rows is not None else None,
        },
        "field_presence": field_presence,
        "missing_required_fields": missing_required_fields(record.endpoint_family, field_presence),
    }


def missing_required_fields(endpoint_family: str, field_presence: dict[str, bool]) -> list[str]:
    if endpoint_family in {"income_statement", "balance_sheet_statement", "cash_flow_statement"}:
        missing = [field for field in ["date", "acceptedDate"] if not field_presence.get(field)]
        if not (field_presence.get("filingDate") or field_presence.get("fillingDate")):
            missing.append("filingDate_or_fillingDate")
        return missing
    return [field for field, present in field_presence.items() if not present]


def aggregate_count_metrics(endpoint_results: list[dict[str, Any]]) -> dict[str, Any]:
    by_family: dict[str, list[int | None]] = {family: [] for family in EXPECTED_ENDPOINT_FAMILIES}
    for result in endpoint_results:
        by_family.setdefault(result["endpoint_family"], []).append(result["payload_shape"]["row_count"])
    row_counts = []
    for family in EXPECTED_ENDPOINT_FAMILIES:
        values = by_family.get(family, [])
        numeric = [value for value in values if isinstance(value, int)]
        row_counts.append(
            {
                "endpoint_family": family,
                "min_row_count": min(numeric) if numeric else None,
                "max_row_count": max(numeric) if numeric else None,
            }
        )
    return {
        "endpoint_success_count": sum(1 for result in endpoint_results if result["status"] == "ok"),
        "endpoint_error_count": sum(1 for result in endpoint_results if result["status"] == "error"),
        "symbol_all_endpoint_success_count": sum(
            1
            for symbol in EXPECTED_SYMBOLS
            if all(
                result["status"] == "ok"
                for result in endpoint_results
                if result["symbol"] == symbol
            )
            and sum(1 for result in endpoint_results if result["symbol"] == symbol) == len(EXPECTED_ENDPOINT_FAMILIES)
        ),
        "missing_required_field_count": sum(len(result["missing_required_fields"]) for result in endpoint_results),
        "statement_observed_date_endpoint_count": sum(
            1
            for result in endpoint_results
            if result["endpoint_family"] in {"income_statement", "balance_sheet_statement", "cash_flow_statement"}
            and result["field_presence"].get("date")
            and (result["field_presence"].get("filingDate") or result["field_presence"].get("fillingDate"))
            and result["field_presence"].get("acceptedDate")
        ),
        "price_ohlcv_presence_count": sum(
            1
            for result in endpoint_results
            if result["endpoint_family"] == "historical_eod_price_volume"
            and all(result["field_presence"].get(field) for field in ["date", "open", "high", "low", "close", "volume"])
        ),
        "endpoint_family_row_counts": row_counts,
    }


def summarize_symbol(symbol: str, endpoint_results: list[dict[str, Any]]) -> dict[str, Any]:
    records = [result for result in endpoint_results if result["symbol"] == symbol]
    missing_count = sum(len(result["missing_required_fields"]) for result in records)
    statement_observed = sum(
        1
        for result in records
        if result["endpoint_family"] in {"income_statement", "balance_sheet_statement", "cash_flow_statement"}
        and result["field_presence"].get("date")
        and (result["field_presence"].get("filingDate") or result["field_presence"].get("fillingDate"))
        and result["field_presence"].get("acceptedDate")
    )
    price_present = any(
        result["endpoint_family"] == "historical_eod_price_volume"
        and all(result["field_presence"].get(field) for field in ["date", "open", "high", "low", "close", "volume"])
        for result in records
    )
    endpoints_ok = sum(1 for result in records if result["status"] == "ok")
    endpoints_error = sum(1 for result in records if result["status"] == "error")
    return {
        "symbol": symbol,
        "fmp": {
            "endpoints_ok": endpoints_ok,
            "endpoints_error": endpoints_error,
            "all_endpoint_families_successful": endpoints_ok == len(EXPECTED_ENDPOINT_FAMILIES) and endpoints_error == 0,
            "missing_required_field_count": missing_count,
            "statement_observed_date_endpoint_count": statement_observed,
            "price_ohlcv_fields_present": price_present,
        },
        "validation_observations": [
            f"{symbol}: FMP stable endpoint families ok={endpoints_ok}, error={endpoints_error}.",
            f"{symbol}: missing required field count={missing_count}; no silent default or production mapping is claimed.",
            f"{symbol}: no provider selection, production readiness, alpha evidence, DataHub, Phase 7c, or ship-gate evidence is claimed.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_coverage_count_packet(
        approval_path=args.approval_path,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
    )
    print(
        json.dumps(
            {
                "summary_path": None if args.dry_run_env else str(args.summary_path),
                "summary_written": not args.dry_run_env,
                "validation_status": summary["scope"]["validation_status"],
                "actual_total_endpoint_calls": summary["endpoint_call_budget"]["actual_total_endpoint_calls"],
                "endpoint_success_count": summary["aggregate_count_metrics"]["endpoint_success_count"],
                "endpoint_error_count": summary["aggregate_count_metrics"]["endpoint_error_count"],
                "secrets_logged": summary["environment"]["secrets_logged"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
