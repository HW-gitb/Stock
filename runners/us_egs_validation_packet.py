from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_egs_sample_validation as sample_validation


EXECUTION_PACKET_PATH = ROOT / "docs" / "provider_evidence_p1_us_validation_execution_packet_20260603.json"
SUMMARY_PATH = ROOT / "docs" / "provider_evidence_p1_us_validation_execution_summary_20260603.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_egs_validation_packet_20260603")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"

EXPECTED_SYMBOLS = ["AAPL", "MSFT", "JPM", "TWTR", "SIVB"]
EXPECTED_ACTIVE_SYMBOLS = ["AAPL", "MSFT", "JPM"]
EXPECTED_INACTIVE_OR_DELISTED_CANDIDATES = ["TWTR", "SIVB"]
EXPECTED_FMP_ENDPOINT_FAMILIES = [endpoint["endpoint_family"] for endpoint in sample_validation.FMP_STABLE_ENDPOINTS]
EXPECTED_SEC_ENDPOINT_FAMILIES = ["company_tickers_mapping", "company_submissions", "companyfacts"]
MAX_TOTAL_ENDPOINT_CALLS = 41
SEC_FAIR_ACCESS_SLEEP_SECONDS = sample_validation.SEC_FAIR_ACCESS_SLEEP_SECONDS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the reviewed 2026-06-03 US EGS provider validation packet: "
            "AAPL/MSFT/JPM/TWTR/SIVB, 30 FMP stable calls plus up to 11 SEC EDGAR "
            "public calls, raw payloads only under gitignored provider_samples/, "
            "tracked no-secret summary."
        )
    )
    parser.add_argument("--execution-packet-path", type=Path, default=EXECUTION_PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument(
        "--confirm-independent-review-pass",
        action="store_true",
        help="Required for live execution; confirms the reviewed execution packet has a clean Pass.",
    )
    parser.add_argument(
        "--confirm-post-review-execute",
        action="store_true",
        help="Required for live execution; confirms the user issued the post-review execute command.",
    )
    parser.add_argument(
        "--dry-run-env",
        action="store_true",
        help="Validate packet, gitignore, and environment boundary without fetching provider data or writing summary.",
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
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)


def load_and_validate_execution_packet(path: Path) -> dict[str, Any]:
    packet = read_json(path)
    if packet.get("schema_name") != "provider_p1_validation_execution_packet":
        raise ValueError("execution packet schema_name mismatch")
    scope = packet.get("scope") or {}
    if scope.get("ready_for_later_execution_after_independent_review") is not True:
        raise ValueError("execution packet must require independent review")
    if scope.get("actual_provider_calls_require_post_review_execute_command") is not True:
        raise ValueError("execution packet must require a later execute command")
    for field in [
        "provider_calls_executed_by_this_artifact",
        "raw_payloads_read_by_this_artifact",
        "provider_selection_allowed",
        "provider_adapter_allowed",
        "datahub_table_implementation_allowed",
        "production_runner_consumption_allowed",
        "phase7c_authorized_by_this_artifact",
        "ship_gate_evidence_allowed",
        "production_ready_claim_allowed",
        "broker_or_order_automation_allowed",
    ]:
        if scope.get(field) is not False:
            raise ValueError(f"execution packet must keep scope.{field}=false")

    universe = packet.get("sample_universe") or {}
    if universe.get("symbols") != EXPECTED_SYMBOLS:
        raise ValueError("execution packet symbols must stay fixed to AAPL/MSFT/JPM/TWTR/SIVB")
    if universe.get("active_symbols") != EXPECTED_ACTIVE_SYMBOLS:
        raise ValueError("execution packet active symbols mismatch")
    if universe.get("inactive_or_delisted_candidate_symbols") != EXPECTED_INACTIVE_OR_DELISTED_CANDIDATES:
        raise ValueError("execution packet inactive/delisted candidate symbols mismatch")
    if universe.get("inactive_or_delisted_candidates_are_best_effort") is not True:
        raise ValueError("inactive/delisted candidates must stay best-effort")

    budget = packet.get("endpoint_call_budget") or {}
    if budget.get("max_total_endpoint_calls") != MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("execution packet max_total_endpoint_calls must be 41")
    if budget.get("fmp_planned_endpoint_calls") != 30:
        raise ValueError("execution packet FMP planned calls must be 30")
    if budget.get("sec_endpoint_calls") != 11:
        raise ValueError("execution packet SEC planned calls must be 11")
    if budget.get("retry_count_allowed") != 0:
        raise ValueError("execution packet retry_count_allowed must be zero")
    if budget.get("abort_if_budget_exceeded") is not True:
        raise ValueError("execution packet must abort if budget is exceeded")

    families = packet.get("endpoint_families") or []
    family_calls = {
        (item.get("provider_id"), item.get("endpoint_family")): int(item.get("call_count", -1))
        for item in families
        if isinstance(item, dict)
    }
    for family in EXPECTED_FMP_ENDPOINT_FAMILIES:
        if family_calls.get(("financial_modeling_prep", family)) != 5:
            raise ValueError(f"execution packet must keep FMP {family} call_count=5")
    for family in ["stock_split_candidate", "dividend_or_distribution_candidate"]:
        if family_calls.get(("financial_modeling_prep", family)) != 0:
            raise ValueError(f"execution packet must keep FMP {family} call_count=0")
    if family_calls.get(("sec_edgar", "company_tickers_mapping")) != 1:
        raise ValueError("execution packet must keep SEC company_tickers_mapping call_count=1")
    for family in ["company_submissions", "companyfacts"]:
        if family_calls.get(("sec_edgar", family)) != 5:
            raise ValueError(f"execution packet must keep SEC {family} call_count=5")

    environment = packet.get("environment_precheck") or {}
    for field in [
        "requires_fmp_api_key_presence",
        "requires_sec_user_agent_presence",
        "environment_values_must_not_be_logged",
        "missing_environment_aborts_before_network",
    ]:
        if environment.get(field) is not True:
            raise ValueError(f"execution packet must keep environment_precheck.{field}=true")
    for field in ["new_token_trial_paid_or_provider_contact_allowed", "yfinance_allowed", "full_market_fetch_allowed"]:
        if environment.get(field) is not False:
            raise ValueError(f"execution packet must keep environment_precheck.{field}=false")

    storage = packet.get("storage_and_secret_boundary") or {}
    if storage.get("raw_sample_storage_path") != RAW_SAMPLE_REL_ROOT.as_posix() + "/":
        raise ValueError("execution packet raw sample path mismatch")
    if storage.get("tracked_summary_path") != "docs/provider_evidence_p1_us_validation_execution_summary_20260603.json":
        raise ValueError("execution packet tracked summary path mismatch")
    for field in [
        "raw_sample_storage_must_be_gitignored",
        "tracked_summary_must_exclude_raw_payloads",
        "tracked_summary_must_exclude_request_urls",
    ]:
        if storage.get(field) is not True:
            raise ValueError(f"execution packet must keep storage.{field}=true")
    for field in [
        "api_key_logging_allowed",
        "authorization_header_logging_allowed",
        "sec_user_agent_value_logging_allowed",
        "secrets_in_repo_allowed",
        "raw_retention_authorizes_production_storage",
    ]:
        if storage.get(field) is not False:
            raise ValueError(f"execution packet must keep storage.{field}=false")

    gates = packet.get("pre_execution_gates") or {}
    for field in [
        "independent_review_pass_required",
        "post_review_execute_command_required",
        "environment_precheck_required",
        "provider_samples_gitignore_check_required",
        "no_secret_summary_scan_required",
        "budget_precheck_required",
        "abort_on_budget_or_scope_violation",
        "sec_fair_access_user_agent_required",
        "no_new_token_trial_paid_or_contact_precheck_required",
    ]:
        if gates.get(field) is not True:
            raise ValueError(f"execution packet must keep pre_execution_gates.{field}=true")
    for field, value in (packet.get("prohibited_claims") or {}).items():
        if value is not False:
            raise ValueError(f"execution packet prohibited claim must stay false: {field}")
    return packet


def validate_raw_root(raw_root: Path) -> None:
    sample_validation.validate_raw_root(raw_root)
    resolved_root = raw_root.resolve()
    approved_root = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved_root.relative_to(approved_root)
    except ValueError as exc:
        raise ValueError("raw samples must stay under provider_samples/us_egs_validation_packet_20260603/") from exc


def provider_samples_gitignored() -> bool:
    gitignore_path = ROOT / ".gitignore"
    if not gitignore_path.exists():
        return False
    lines = [
        line.strip().replace("\\", "/")
        for line in gitignore_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return "provider_samples/" in lines or "provider_samples" in lines


def require_live_execution_confirmations(
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


def run_validation_packet(
    *,
    execution_packet_path: Path = EXECUTION_PACKET_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    generated_at: str | None = None,
    client: sample_validation.JsonHttpClient | None = None,
    dry_run_env: bool = False,
    confirm_independent_review_pass: bool = False,
    confirm_post_review_execute: bool = False,
    sec_sleep_seconds: float = SEC_FAIR_ACCESS_SLEEP_SECONDS,
) -> dict[str, Any]:
    packet = load_and_validate_execution_packet(execution_packet_path)
    validate_raw_root(raw_root)
    if not provider_samples_gitignored():
        raise RuntimeError("provider_samples/ is not confirmed in .gitignore")
    require_live_execution_confirmations(
        dry_run_env=dry_run_env,
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )
    generated_at = generated_at or iso_now()
    fmp_env = sample_validation.read_required_env("FMP_API_KEY")
    sec_user_agent_env = sample_validation.read_required_env("SEC_USER_AGENT")
    env_summary = {
        "fmp_api_key_present": True,
        "fmp_api_key_source": fmp_env.source,
        "sec_user_agent_present": True,
        "sec_user_agent_source": sec_user_agent_env.source,
        "environment_values_logged": False,
        "secrets_logged": False,
    }
    pre_execution_checks = {
        "independent_review_pass_confirmed": bool(confirm_independent_review_pass),
        "post_review_execute_command_confirmed": bool(confirm_post_review_execute),
        "provider_samples_gitignore_confirmed": True,
        "environment_precheck_passed": True,
        "fmp_api_key_present": True,
        "sec_user_agent_present": True,
        "budget_precheck_passed": True,
        "no_new_token_trial_paid_or_contact_used": True,
        "yfinance_not_used": True,
        "full_market_fetch_not_used": True,
        "sec_fair_access_user_agent_present": True,
    }

    if dry_run_env:
        summary = build_summary(
            packet=packet,
            generated_at=generated_at,
            env_summary=env_summary,
            pre_execution_checks=pre_execution_checks,
            endpoint_records=[],
            skipped_endpoint_results=blocked_corporate_action_skips(),
            cik_by_symbol={},
            dry_run_env=True,
        )
        return summary

    client = client or sample_validation.JsonHttpClient()
    endpoint_records: list[sample_validation.FetchRecord] = []
    skipped_endpoint_results = blocked_corporate_action_skips()

    fmp_headers = {"User-Agent": "StockSystem/0.1 provider-validation-packet"}
    for symbol in EXPECTED_SYMBOLS:
        for endpoint in sample_validation.FMP_STABLE_ENDPOINTS:
            sample_validation.assert_endpoint_budget_available(endpoint_records, MAX_TOTAL_ENDPOINT_CALLS)
            endpoint_records.append(
                sample_validation.fetch_and_store(
                    client,
                    url=sample_validation.fmp_url(
                        endpoint["path_template"],
                        symbol,
                        dict(endpoint.get("params") or {}),
                        fmp_env.value,
                        endpoint_mode="stable",
                    ),
                    provider_id="financial_modeling_prep",
                    endpoint_family=endpoint["endpoint_family"],
                    symbol=symbol,
                    raw_root=raw_root,
                    headers=fmp_headers,
                )
            )

    sec_headers = {
        "User-Agent": sec_user_agent_env.value,
        "Host": "www.sec.gov",
    }
    sample_validation.assert_endpoint_budget_available(endpoint_records, MAX_TOTAL_ENDPOINT_CALLS)
    endpoint_records.append(
        sample_validation.fetch_and_store(
            client,
            url=sample_validation.sec_url("company_tickers_mapping"),
            provider_id="sec_edgar",
            endpoint_family="company_tickers_mapping",
            symbol=None,
            raw_root=raw_root,
            headers=sec_headers,
        )
    )
    cik_by_symbol = sample_validation.parse_sec_cik_map(endpoint_records[-1].payload, EXPECTED_SYMBOLS)

    for symbol in EXPECTED_SYMBOLS:
        cik10 = cik_by_symbol.get(symbol)
        if not cik10:
            skipped_endpoint_results.extend(
                [
                    skipped_sec_endpoint(symbol, "company_submissions", "sec_cik_not_found_in_company_tickers_mapping"),
                    skipped_sec_endpoint(symbol, "companyfacts", "sec_cik_not_found_in_company_tickers_mapping"),
                ]
            )
            continue
        for packet_family, sec_family in [("company_submissions", "submissions"), ("companyfacts", "companyfacts")]:
            sample_validation.assert_endpoint_budget_available(endpoint_records, MAX_TOTAL_ENDPOINT_CALLS)
            if sec_sleep_seconds:
                time.sleep(sec_sleep_seconds)
            endpoint_records.append(
                sample_validation.fetch_and_store(
                    client,
                    url=sample_validation.sec_url(sec_family, cik10),
                    provider_id="sec_edgar",
                    endpoint_family=packet_family,
                    symbol=symbol,
                    raw_root=raw_root,
                    headers={
                        "User-Agent": sec_user_agent_env.value,
                        "Host": "data.sec.gov",
                    },
                )
            )

    if len(endpoint_records) > MAX_TOTAL_ENDPOINT_CALLS:
        raise RuntimeError(f"endpoint call count {len(endpoint_records)} exceeded packet budget {MAX_TOTAL_ENDPOINT_CALLS}")

    summary = build_summary(
        packet=packet,
        generated_at=generated_at,
        env_summary=env_summary,
        pre_execution_checks=pre_execution_checks,
        endpoint_records=endpoint_records,
        skipped_endpoint_results=skipped_endpoint_results,
        cik_by_symbol=cik_by_symbol,
        dry_run_env=False,
    )
    write_json_atomic(summary, summary_path)
    assert_no_secret_summary(summary_path, [fmp_env.value, sec_user_agent_env.value])
    return summary


def blocked_corporate_action_skips() -> list[dict[str, Any]]:
    return [
        {
            "provider_id": "financial_modeling_prep",
            "endpoint_family": "stock_split_candidate",
            "symbol": None,
            "skipped_reason": "blocked_pending_current_template_review",
            "call_count": 0,
            "raw_parse_allowed_for_validation": False,
        },
        {
            "provider_id": "financial_modeling_prep",
            "endpoint_family": "dividend_or_distribution_candidate",
            "symbol": None,
            "skipped_reason": "blocked_pending_current_template_review",
            "call_count": 0,
            "raw_parse_allowed_for_validation": False,
        },
    ]


def skipped_sec_endpoint(symbol: str, endpoint_family: str, reason: str) -> dict[str, Any]:
    return {
        "provider_id": "sec_edgar",
        "endpoint_family": endpoint_family,
        "symbol": symbol,
        "skipped_reason": reason,
        "call_count": 0,
        "raw_parse_allowed_for_validation": False,
    }


def helper_family(endpoint_family: str) -> str:
    if endpoint_family == "company_submissions":
        return "submissions"
    return endpoint_family


def summarize_endpoint(record: sample_validation.FetchRecord) -> dict[str, Any]:
    payload = record.payload
    rows = sample_validation.payload_rows(helper_family(record.endpoint_family), payload)
    field_presence = endpoint_field_presence(record.endpoint_family, payload)
    return {
        "provider_id": record.provider_id,
        "endpoint_family": record.endpoint_family,
        "symbol": record.symbol,
        "status": "ok" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith(RAW_SAMPLE_REL_ROOT.as_posix() + "/"),
        "fmp_endpoint_mode": "stable" if record.provider_id == "financial_modeling_prep" else None,
        "payload_shape": {
            "payload_type": type(payload).__name__,
            "top_level_key_count": len(payload) if isinstance(payload, dict) else None,
            "row_count": len(rows) if rows is not None else None,
        },
        "field_presence": field_presence,
        "missing_required_fields": missing_required_fields(record.endpoint_family, field_presence),
    }


def endpoint_field_presence(endpoint_family: str, payload: Any) -> dict[str, bool]:
    if endpoint_family in EXPECTED_FMP_ENDPOINT_FAMILIES:
        return sample_validation.endpoint_field_presence(endpoint_family, payload, endpoint_mode="stable")
    fields = sample_validation.fields_for_endpoint(helper_family(endpoint_family), endpoint_mode="stable")
    row = sample_validation.first_row(helper_family(endpoint_family), payload)
    if not fields:
        return {}
    if not isinstance(row, dict):
        return {field: False for field in fields}
    return {field: field in row and row.get(field) is not None for field in fields}


def missing_required_fields(endpoint_family: str, field_presence: dict[str, bool]) -> list[str]:
    if endpoint_family in {"income_statement", "balance_sheet_statement", "cash_flow_statement"}:
        missing = [field for field in ["date", "acceptedDate"] if not field_presence.get(field)]
        if not (field_presence.get("filingDate") or field_presence.get("fillingDate")):
            missing.append("filingDate_or_fillingDate")
        return missing
    if endpoint_family == "historical_eod_price_volume":
        return [field for field in ["date", "open", "high", "low", "close", "volume"] if not field_presence.get(field)]
    if endpoint_family == "financial_ratios_or_key_metrics":
        return [
            field
            for field in ["date", "marketCap", "peRatio", "revenuePerShare", "netIncomePerShare"]
            if not field_presence.get(field)
        ]
    return [field for field, present in field_presence.items() if not present]


def build_summary(
    *,
    packet: dict[str, Any],
    generated_at: str,
    env_summary: dict[str, Any],
    pre_execution_checks: dict[str, Any],
    endpoint_records: list[sample_validation.FetchRecord],
    skipped_endpoint_results: list[dict[str, Any]],
    cik_by_symbol: dict[str, str],
    dry_run_env: bool,
) -> dict[str, Any]:
    endpoint_results = [summarize_endpoint(record) for record in endpoint_records]
    aggregate = aggregate_validation_metrics(endpoint_results, skipped_endpoint_results, cik_by_symbol)
    endpoint_errors = aggregate["endpoint_error_count"]
    skipped_count = aggregate["skipped_endpoint_count"]
    if dry_run_env:
        validation_status = "dry_run_env_only"
        execution_performed = False
    elif endpoint_errors and skipped_count > 2:
        validation_status = "completed_with_skips_and_endpoint_errors"
        execution_performed = True
    elif endpoint_errors:
        validation_status = "completed_with_endpoint_errors"
        execution_performed = True
    elif skipped_count > 2:
        validation_status = "completed_with_skips"
        execution_performed = True
    else:
        validation_status = "completed"
        execution_performed = True
    symbol_results = [summarize_symbol(symbol, endpoint_results, skipped_endpoint_results, cik_by_symbol) for symbol in EXPECTED_SYMBOLS]
    return {
        "schema_name": "provider_p1_validation_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "execution_packet_ref": "docs/provider_evidence_p1_us_validation_execution_packet_20260603.json",
        "authorization_ref": packet["authorization_ref"],
        "schema_ref": "schemas/provider_p1_validation_execution_summary.schema.json",
        "scope": {
            "phase": "7b-2",
            "purpose": "p1_bounded_provider_validation_execution_summary",
            "validation_status": validation_status,
            "provider_validation_execution_performed": execution_performed,
            "fmp_stable_endpoint_calls_performed": execution_performed,
            "sec_edgar_public_api_calls_performed": execution_performed,
            "validation_only_raw_payload_parse_performed": execution_performed,
            "raw_payload_storage_performed": execution_performed,
            "split_or_dividend_endpoint_calls_performed": False,
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
            "ship_gate_evidence_claimed": False,
            "production_ready_claim_allowed": False,
        },
        "pre_execution_checks": pre_execution_checks,
        "environment": env_summary,
        "storage": {
            "raw_sample_storage_path": RAW_SAMPLE_REL_ROOT.as_posix() + "/",
            "raw_samples_gitignored": True,
            "tracked_summary_contains_raw_rows": False,
            "secrets_in_summary": False,
            "request_urls_in_summary": False,
            "sec_user_agent_value_in_summary": False,
        },
        "sample_universe": {
            "symbols": EXPECTED_SYMBOLS,
            "active_symbols": EXPECTED_ACTIVE_SYMBOLS,
            "inactive_or_delisted_candidate_symbols": EXPECTED_INACTIVE_OR_DELISTED_CANDIDATES,
            "inactive_or_delisted_candidates_are_best_effort": True,
            "universe_role": "bounded_validation_sample_not_full_market_or_security_master",
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "planned_fmp_endpoint_calls": 30,
            "planned_sec_endpoint_calls": 11,
            "actual_total_endpoint_calls": len(endpoint_records),
            "actual_fmp_endpoint_calls": sum(1 for item in endpoint_results if item["provider_id"] == "financial_modeling_prep"),
            "actual_sec_endpoint_calls": sum(1 for item in endpoint_results if item["provider_id"] == "sec_edgar"),
            "skipped_endpoint_count": skipped_count,
            "retry_count_allowed": 0,
            "retry_count_used": 0,
            "within_budget": len(endpoint_records) <= MAX_TOTAL_ENDPOINT_CALLS,
        },
        "endpoint_results": endpoint_results,
        "skipped_endpoint_results": skipped_endpoint_results,
        "symbol_results": symbol_results,
        "aggregate_validation_metrics": aggregate,
        "validation_decision": {
            "decision": "bounded_validation_execution_completed_keep_sr_provider_001_open"
            if not endpoint_errors
            else "bounded_validation_execution_completed_with_errors_keep_sr_provider_001_open",
            "sr_provider_001_closed": False,
            "provider_selection_allowed": False,
            "phase7c_allowed": False,
            "rationale": (
                "This execution validates only bounded response shape and field-presence clues for five fixed symbols. "
                "It does not prove current terms, production storage, PIT at scale, price adjustment at scale, "
                "corporate-action handling, SEC parser implementation, provider stability, provider selection, "
                "DataHub, Phase 7c, production readiness, alpha, or ship-gate evidence."
            ),
        },
        "prohibited_claims": {
            "provider_selected": False,
            "provider_ranked": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "paid_access_used": False,
            "new_token_trial_or_provider_contact_used": False,
            "raw_rows_in_tracked_summary": False,
            "request_urls_in_tracked_summary": False,
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
            "alpha_evidence_claimed": False,
            "production_ready_claimed": False,
            "current_terms_cleared": False,
            "production_storage_rights_cleared": False,
            "inactive_delisted_coverage_proven": False,
            "pit_proven_at_scale": False,
            "price_adjustment_proven_at_scale": False,
            "corporate_actions_proven_at_scale": False,
            "sec_parser_proven_at_scale": False,
            "fmp_corporate_action_endpoint_template_proven": False,
        },
        "limitations": [
            "This is a five-symbol validation sample, not a full market, not a security master, and not proof of inactive / delisted coverage.",
            "FMP stable response shape and field presence do not prove current terms, production storage rights, PIT semantics at scale, price-adjustment semantics at scale, fallback behavior, provider stability, or production readiness.",
            "FMP split and dividend endpoint calls remain blocked because no current FMP corporate-action endpoint template is reviewed in repo evidence.",
            "SEC EDGAR checks are parser and field-family feasibility probes only; no parser, field mapping, fixture, or DataHub / runner consumption is implemented or authorized.",
            "No provider selection, Phase 7c authorization, alpha evidence, production-readiness claim, or ship-gate evidence is claimed.",
        ],
        "next_steps": [
            "Have Claude review the runner, schema, tracked summary, no-secret boundary, raw-path gitignore boundary, endpoint budget, and SR-PROVIDER-001 wording before commit.",
            "Keep SR-PROVIDER-001 open for current terms / production storage rights, PIT row validation at scale, price adjustment, corporate actions, SEC parser / field mapping, minimized fixtures, derivation lineage, fallback execution, stability evidence, provider selection, DataHub, runner consumption, and Phase 7c.",
            "Do not broaden symbols, endpoint families, retries, split / dividend endpoint calls, yfinance checks, full-market fetches, implementation, DataHub work, or production claims without separate explicit approval and reviewed decision.",
        ],
    }


def aggregate_validation_metrics(
    endpoint_results: list[dict[str, Any]],
    skipped_endpoint_results: list[dict[str, Any]],
    cik_by_symbol: dict[str, str],
) -> dict[str, Any]:
    return {
        "endpoint_success_count": sum(1 for result in endpoint_results if result["status"] == "ok"),
        "endpoint_error_count": sum(1 for result in endpoint_results if result["status"] == "error"),
        "skipped_endpoint_count": len(skipped_endpoint_results),
        "fmp_endpoint_success_count": sum(
            1 for result in endpoint_results if result["provider_id"] == "financial_modeling_prep" and result["status"] == "ok"
        ),
        "fmp_endpoint_error_count": sum(
            1 for result in endpoint_results if result["provider_id"] == "financial_modeling_prep" and result["status"] == "error"
        ),
        "sec_endpoint_success_count": sum(
            1 for result in endpoint_results if result["provider_id"] == "sec_edgar" and result["status"] == "ok"
        ),
        "sec_endpoint_error_count": sum(
            1 for result in endpoint_results if result["provider_id"] == "sec_edgar" and result["status"] == "error"
        ),
        "sec_cik_found_count": sum(1 for symbol in EXPECTED_SYMBOLS if symbol in cik_by_symbol),
        "sec_cik_missing_count": sum(1 for symbol in EXPECTED_SYMBOLS if symbol not in cik_by_symbol),
        "fmp_statement_observed_date_endpoint_count": sum(
            1
            for result in endpoint_results
            if result["provider_id"] == "financial_modeling_prep"
            and result["endpoint_family"] in {"income_statement", "balance_sheet_statement", "cash_flow_statement"}
            and result["field_presence"].get("date")
            and (result["field_presence"].get("filingDate") or result["field_presence"].get("fillingDate"))
            and result["field_presence"].get("acceptedDate")
        ),
        "fmp_price_ohlcv_presence_count": sum(
            1
            for result in endpoint_results
            if result["provider_id"] == "financial_modeling_prep"
            and result["endpoint_family"] == "historical_eod_price_volume"
            and all(result["field_presence"].get(field) for field in ["date", "open", "high", "low", "close", "volume"])
        ),
        "fmp_key_metrics_missing_direct_field_count": sum(
            len(result["missing_required_fields"])
            for result in endpoint_results
            if result["provider_id"] == "financial_modeling_prep"
            and result["endpoint_family"] == "financial_ratios_or_key_metrics"
        ),
        "corporate_action_endpoint_call_count": 0,
    }


def summarize_symbol(
    symbol: str,
    endpoint_results: list[dict[str, Any]],
    skipped_endpoint_results: list[dict[str, Any]],
    cik_by_symbol: dict[str, str],
) -> dict[str, Any]:
    records = [result for result in endpoint_results if result["symbol"] == symbol]
    fmp_records = [result for result in records if result["provider_id"] == "financial_modeling_prep"]
    sec_records = [result for result in records if result["provider_id"] == "sec_edgar"]
    skipped = [result for result in skipped_endpoint_results if result.get("symbol") == symbol]
    statement_observed = sum(
        1
        for result in fmp_records
        if result["endpoint_family"] in {"income_statement", "balance_sheet_statement", "cash_flow_statement"}
        and result["field_presence"].get("date")
        and (result["field_presence"].get("filingDate") or result["field_presence"].get("fillingDate"))
        and result["field_presence"].get("acceptedDate")
    )
    price_present = any(
        result["endpoint_family"] == "historical_eod_price_volume"
        and all(result["field_presence"].get(field) for field in ["date", "open", "high", "low", "close", "volume"])
        for result in fmp_records
    )
    key_metrics_missing = next(
        (
            result["missing_required_fields"]
            for result in fmp_records
            if result["endpoint_family"] == "financial_ratios_or_key_metrics"
        ),
        [],
    )
    cik_found = symbol in cik_by_symbol
    return {
        "symbol": symbol,
        "sample_role": "active" if symbol in EXPECTED_ACTIVE_SYMBOLS else "inactive_or_delisted_candidate_best_effort",
        "fmp": {
            "endpoints_ok": sum(1 for result in fmp_records if result["status"] == "ok"),
            "endpoints_error": sum(1 for result in fmp_records if result["status"] == "error"),
            "all_endpoint_families_attempted": len(fmp_records) == len(EXPECTED_FMP_ENDPOINT_FAMILIES),
            "statement_observed_date_endpoint_count": statement_observed,
            "price_ohlcv_fields_present": price_present,
            "key_metrics_missing_direct_fields": key_metrics_missing,
        },
        "sec_edgar": {
            "cik_found": cik_found,
            "cik": cik_by_symbol.get(symbol),
            "endpoints_attempted": len(sec_records),
            "endpoints_ok": sum(1 for result in sec_records if result["status"] == "ok"),
            "endpoints_error": sum(1 for result in sec_records if result["status"] == "error"),
            "endpoints_skipped": len(skipped),
        },
        "validation_observations": [
            f"{symbol}: FMP stable endpoint families attempted={len(fmp_records)}; ok={sum(1 for result in fmp_records if result['status'] == 'ok')}; error={sum(1 for result in fmp_records if result['status'] == 'error')}.",
            f"{symbol}: SEC CIK found={cik_found}; SEC endpoints attempted={len(sec_records)}; skipped={len(skipped)}.",
            f"{symbol}: no provider selection, production readiness, alpha evidence, DataHub, Phase 7c, or ship-gate evidence is claimed.",
        ],
    }


def assert_no_secret_summary(summary_path: Path, sensitive_values: list[str]) -> None:
    text = summary_path.read_text(encoding="utf-8")
    lower_text = text.lower()
    for fragment in ["apikey=", "financialmodelingprep.com/", "sec.gov/"]:
        if fragment in lower_text:
            raise RuntimeError(f"tracked summary contains forbidden fragment: {fragment}")
    for fragment in ["FMP_API_KEY", "SEC_USER_AGENT", "Bearer "]:
        if fragment in text:
            raise RuntimeError(f"tracked summary contains forbidden fragment: {fragment}")
    for value in sensitive_values:
        if value and value in text:
            raise RuntimeError("tracked summary contains an environment value")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_validation_packet(
        execution_packet_path=args.execution_packet_path,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
        confirm_independent_review_pass=args.confirm_independent_review_pass,
        confirm_post_review_execute=args.confirm_post_review_execute,
    )
    print(
        json.dumps(
            {
                "summary_path": None if args.dry_run_env else str(args.summary_path),
                "summary_written": not args.dry_run_env,
                "validation_status": summary["scope"]["validation_status"],
                "actual_total_endpoint_calls": summary["endpoint_call_budget"]["actual_total_endpoint_calls"],
                "endpoint_success_count": summary["aggregate_validation_metrics"]["endpoint_success_count"],
                "endpoint_error_count": summary["aggregate_validation_metrics"]["endpoint_error_count"],
                "skipped_endpoint_count": summary["aggregate_validation_metrics"]["skipped_endpoint_count"],
                "secrets_logged": summary["environment"]["secrets_logged"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
