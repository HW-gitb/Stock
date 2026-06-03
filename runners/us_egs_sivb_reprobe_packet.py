from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_egs_sample_validation as sample_validation


EXECUTION_PACKET_PATH = ROOT / "docs" / "provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json"
SUMMARY_PATH = ROOT / "docs" / "provider_evidence_p1_us_sivb_reprobe_execution_summary_20260603.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_egs_sivb_reprobe_20260603")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"

EXPECTED_SYMBOL = "SIVB"
EXPECTED_FMP_ENDPOINT_FAMILIES = [
    "income_statement",
    "balance_sheet_statement",
    "cash_flow_statement",
    "financial_ratios_or_key_metrics",
    "historical_eod_price_volume",
]
MAX_TOTAL_ENDPOINT_CALLS = 5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the reviewed 2026-06-03 SIVB-only FMP HTTP 402 re-probe packet: "
            "five fixed FMP stable endpoint families, zero retries, raw payloads "
            "only under gitignored provider_samples/, tracked no-secret summary."
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


def stable_endpoint_by_family() -> dict[str, dict[str, Any]]:
    return {item["endpoint_family"]: item for item in sample_validation.FMP_STABLE_ENDPOINTS}


def load_and_validate_execution_packet(path: Path) -> dict[str, Any]:
    packet = read_json(path)
    if packet.get("schema_name") != "provider_p1_sivb_reprobe_execution_packet":
        raise ValueError("SIVB re-probe execution packet schema_name mismatch")
    if packet.get("authorization_ref") != "docs/provider_evidence_p1_us_validation_authorization_packet_20260603.json":
        raise ValueError("SIVB re-probe packet authorization_ref mismatch")

    scope = packet.get("scope") or {}
    expected_true_scope = [
        "ready_for_later_execution_after_independent_review",
        "actual_provider_calls_require_post_review_execute_command",
        "network_access_required_for_later_execution",
        "fmp_existing_key_use_allowed",
    ]
    for field in expected_true_scope:
        if scope.get(field) is not True:
            raise ValueError(f"SIVB re-probe packet must keep scope.{field}=true")
    if scope.get("phase") != "7b-2":
        raise ValueError("SIVB re-probe packet phase mismatch")
    if scope.get("purpose") != "p1_sivb_only_fmp_402_reprobe_execution_packet":
        raise ValueError("SIVB re-probe packet purpose mismatch")
    if scope.get("packet_status") != "execution_packet_contract_recorded_for_review_not_executed":
        raise ValueError("SIVB re-probe packet status mismatch")
    if scope.get("spend_usd") != 0:
        raise ValueError("SIVB re-probe packet spend must stay zero")
    for field in [
        "provider_calls_executed_by_this_artifact",
        "raw_payloads_read_by_this_artifact",
        "runner_implemented_by_this_artifact",
        "provider_selection_allowed",
        "provider_adapter_allowed",
        "datahub_table_implementation_allowed",
        "production_runner_consumption_allowed",
        "phase7c_authorized_by_this_artifact",
        "ship_gate_evidence_allowed",
        "production_ready_claim_allowed",
        "broker_or_order_automation_allowed",
        "new_token_trial_paid_or_provider_contact_allowed",
        "yfinance_allowed",
        "full_market_download_allowed",
    ]:
        if scope.get(field) is not False:
            raise ValueError(f"SIVB re-probe packet must keep scope.{field}=false")

    universe = packet.get("sample_universe") or {}
    if universe.get("symbols") != [EXPECTED_SYMBOL]:
        raise ValueError("SIVB re-probe packet symbol must be SIVB only")
    if universe.get("max_symbols") != 1:
        raise ValueError("SIVB re-probe packet max_symbols must be 1")
    if universe.get("active_symbols") != []:
        raise ValueError("SIVB re-probe packet must not include active symbols")
    if universe.get("inactive_or_delisted_candidate_symbols") != [EXPECTED_SYMBOL]:
        raise ValueError("SIVB re-probe packet inactive/delisted symbol mismatch")
    if universe.get("not_full_market_or_security_master") is not True:
        raise ValueError("SIVB re-probe packet must not be full-market/security-master")
    if universe.get("security_master_implementation_allowed") is not False:
        raise ValueError("SIVB re-probe packet must not authorize security-master implementation")

    budget = packet.get("endpoint_call_budget") or {}
    if budget.get("max_total_endpoint_calls") != MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("SIVB re-probe packet max_total_endpoint_calls must be 5")
    if budget.get("fmp_planned_endpoint_calls") != MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("SIVB re-probe packet FMP planned calls must be 5")
    if budget.get("sec_endpoint_calls") != 0:
        raise ValueError("SIVB re-probe packet must not authorize SEC calls")
    if budget.get("retry_count_allowed") != 0:
        raise ValueError("SIVB re-probe packet retry_count_allowed must be zero")
    for field in ["abort_if_budget_exceeded", "budget_precheck_required"]:
        if budget.get(field) is not True:
            raise ValueError(f"SIVB re-probe packet must keep endpoint_call_budget.{field}=true")

    families = packet.get("endpoint_families") or []
    if len(families) != len(EXPECTED_FMP_ENDPOINT_FAMILIES):
        raise ValueError("SIVB re-probe packet must include exactly five endpoint families")
    family_calls = {item.get("endpoint_family"): item for item in families if isinstance(item, dict)}
    if set(family_calls) != set(EXPECTED_FMP_ENDPOINT_FAMILIES):
        raise ValueError("SIVB re-probe packet endpoint families must stay fixed")
    for family in EXPECTED_FMP_ENDPOINT_FAMILIES:
        item = family_calls[family]
        expected = {
            "provider_id": "financial_modeling_prep",
            "symbol": EXPECTED_SYMBOL,
            "call_count": 1,
            "previous_http_status": 402,
            "capture_non_json_body_in_raw": True,
            "tracked_summary_body_text_allowed": False,
            "tracked_summary_request_url_allowed": False,
            "classification_signal_allowed": True,
            "authorizes_return_calculation": False,
            "authorizes_corporate_action_reconciliation": False,
            "authorizes_fixture_generation": False,
            "authorizes_field_mapping_implementation": False,
            "authorizes_provider_selection": False,
            "authorizes_datahub_or_runner": False,
        }
        for field, value in expected.items():
            if item.get(field) != value:
                raise ValueError(f"SIVB re-probe packet must keep {family}.{field}={value!r}")

    environment = packet.get("environment_precheck") or {}
    for field in [
        "fmp_key_required_before_any_network_call",
        "fmp_key_must_not_be_logged",
        "abort_before_network_if_fmp_key_missing",
        "existing_fmp_key_only",
    ]:
        if environment.get(field) is not True:
            raise ValueError(f"SIVB re-probe packet must keep environment_precheck.{field}=true")
    for field in ["new_token_trial_paid_or_provider_contact_allowed", "yfinance_allowed", "full_market_fetch_allowed"]:
        if environment.get(field) is not False:
            raise ValueError(f"SIVB re-probe packet must keep environment_precheck.{field}=false")

    storage = packet.get("storage_and_secret_boundary") or {}
    if storage.get("raw_sample_storage_path") != RAW_SAMPLE_REL_ROOT.as_posix() + "/":
        raise ValueError("SIVB re-probe packet raw sample path mismatch")
    if storage.get("tracked_summary_path") != "docs/provider_evidence_p1_us_sivb_reprobe_execution_summary_20260603.json":
        raise ValueError("SIVB re-probe packet summary path mismatch")
    for field in [
        "raw_sample_storage_must_be_gitignored",
        "capture_non_json_body_in_raw",
        "tracked_summary_must_exclude_raw_payloads",
        "tracked_summary_must_exclude_error_body_text",
        "tracked_summary_must_exclude_request_urls",
        "assert_no_secret_summary_must_remain",
    ]:
        if storage.get(field) is not True:
            raise ValueError(f"SIVB re-probe packet must keep storage.{field}=true")
    for field in ["api_key_logging_allowed", "secrets_in_repo_allowed"]:
        if storage.get(field) is not False:
            raise ValueError(f"SIVB re-probe packet must keep storage.{field}=false")

    gates = packet.get("pre_execution_gates") or {}
    for field in [
        "independent_review_pass_required",
        "post_review_execute_command_required",
        "environment_precheck_required",
        "exact_symbol_and_family_fixed",
        "provider_samples_gitignore_check_required",
        "no_secret_summary_scan_required",
        "budget_precheck_required",
        "abort_on_budget_or_scope_violation",
        "no_new_token_paid_or_contact_precheck",
    ]:
        if gates.get(field) is not True:
            raise ValueError(f"SIVB re-probe packet must keep pre_execution_gates.{field}=true")

    classification = packet.get("classification_strategy") or {}
    for field in [
        "read_captured_402_body_for_classification",
        "tracked_summary_body_text_allowed",
        "tracked_summary_request_url_allowed",
    ]:
        expected = field == "read_captured_402_body_for_classification"
        if classification.get(field) is not expected:
            raise ValueError(f"SIVB re-probe packet classification field mismatch: {field}")
    if classification.get("classification_output") != "category_signal_only_no_body_text_no_url":
        raise ValueError("SIVB re-probe packet classification output mismatch")
    if classification.get("direct_paid_wall_conclusion_without_body_or_plan_evidence_allowed") is not False:
        raise ValueError("SIVB re-probe packet must forbid direct paid-wall conclusions")
    hypotheses = {item.get("hypothesis_id") for item in classification.get("hypothesis_map") or []}
    if hypotheses != {
        "endpoint_entitlement",
        "symbol_lifecycle",
        "historical_or_delisted_paid_tier",
        "transient_quota_or_provider_incident",
    }:
        raise ValueError("SIVB re-probe packet classification hypotheses mismatch")

    no_silent = packet.get("no_silent_default_policy") or {}
    for field, expected in {
        "fmp_http_402_is_not_missing_data_default": True,
        "twtr_success_is_not_inactive_delisted_coverage_proof": True,
        "null_fill_allowed": False,
        "zero_fill_allowed": False,
        "drop_failed_symbol_allowed": False,
        "latest_only_substitution_allowed": False,
        "production_default_allowed": False,
    }.items():
        if no_silent.get(field) is not expected:
            raise ValueError(f"SIVB re-probe packet no-silent-default mismatch: {field}")

    for field, value in (packet.get("prohibited_claims") or {}).items():
        if value is not False:
            raise ValueError(f"SIVB re-probe packet prohibited claim must stay false: {field}")
    return packet


def validate_raw_root(raw_root: Path) -> None:
    sample_validation.validate_raw_root(raw_root)
    resolved_root = raw_root.resolve()
    approved_root = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved_root.relative_to(approved_root)
    except ValueError as exc:
        raise ValueError("raw samples must stay under provider_samples/us_egs_sivb_reprobe_20260603/") from exc


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


def run_sivb_reprobe_packet(
    *,
    execution_packet_path: Path = EXECUTION_PACKET_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    generated_at: str | None = None,
    client: sample_validation.JsonHttpClient | None = None,
    dry_run_env: bool = False,
    confirm_independent_review_pass: bool = False,
    confirm_post_review_execute: bool = False,
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
    env_summary = {
        "fmp_api_key_present": True,
        "fmp_api_key_source": fmp_env.source,
        "environment_values_logged": False,
        "secrets_logged": False,
    }
    pre_execution_checks = {
        "independent_review_pass_confirmed": bool(confirm_independent_review_pass),
        "post_review_execute_command_confirmed": bool(confirm_post_review_execute),
        "provider_samples_gitignore_confirmed": True,
        "environment_precheck_passed": True,
        "fmp_api_key_present": True,
        "budget_precheck_passed": True,
        "exact_symbol_and_family_fixed": True,
        "no_new_token_trial_paid_or_contact_used": True,
        "yfinance_not_used": True,
        "full_market_fetch_not_used": True,
    }

    if dry_run_env:
        return build_summary(
            packet=packet,
            generated_at=generated_at,
            env_summary=env_summary,
            pre_execution_checks=pre_execution_checks,
            endpoint_records=[],
            dry_run_env=True,
        )

    client = client or sample_validation.JsonHttpClient()
    endpoint_records: list[sample_validation.FetchRecord] = []
    endpoint_defs = stable_endpoint_by_family()
    fmp_headers = {"User-Agent": "StockSystem/0.1 sivb-fmp-402-reprobe"}
    for family in EXPECTED_FMP_ENDPOINT_FAMILIES:
        sample_validation.assert_endpoint_budget_available(endpoint_records, MAX_TOTAL_ENDPOINT_CALLS)
        endpoint = endpoint_defs[family]
        endpoint_records.append(
            sample_validation.fetch_and_store(
                client,
                url=sample_validation.fmp_url(
                    endpoint["path_template"],
                    EXPECTED_SYMBOL,
                    dict(endpoint.get("params") or {}),
                    fmp_env.value,
                    endpoint_mode="stable",
                ),
                provider_id="financial_modeling_prep",
                endpoint_family=family,
                symbol=EXPECTED_SYMBOL,
                raw_root=raw_root,
                headers=fmp_headers,
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
        dry_run_env=False,
    )
    write_json_atomic(summary, summary_path)
    assert_no_secret_summary(summary_path, [fmp_env.value])
    return summary


def build_summary(
    *,
    packet: dict[str, Any],
    generated_at: str,
    env_summary: dict[str, Any],
    pre_execution_checks: dict[str, Any],
    endpoint_records: list[sample_validation.FetchRecord],
    dry_run_env: bool,
) -> dict[str, Any]:
    endpoint_results = [summarize_endpoint(record) for record in endpoint_records]
    aggregate = aggregate_reprobe_metrics(endpoint_results)
    if dry_run_env:
        validation_status = "dry_run_env_only"
        execution_performed = False
    elif aggregate["endpoint_error_count"]:
        validation_status = "completed_with_endpoint_errors"
        execution_performed = True
    else:
        validation_status = "completed"
        execution_performed = True
    return {
        "schema_name": "provider_p1_sivb_reprobe_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "execution_packet_ref": "docs/provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json",
        "authorization_ref": packet["authorization_ref"],
        "schema_ref": "schemas/provider_p1_sivb_reprobe_execution_summary.schema.json",
        "scope": {
            "phase": "7b-2",
            "purpose": "p1_sivb_only_fmp_402_reprobe_execution_summary",
            "validation_status": validation_status,
            "provider_reprobe_execution_performed": execution_performed,
            "fmp_stable_endpoint_calls_performed": execution_performed,
            "raw_payload_storage_performed": execution_performed,
            "non_json_body_capture_supported": True,
            "sec_edgar_public_api_calls_performed": False,
            "retry_performed": False,
            "fmp_split_or_dividend_endpoint_calls_performed": False,
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
            "broker_or_order_automation_allowed": False,
        },
        "pre_execution_checks": pre_execution_checks,
        "environment": env_summary,
        "storage": {
            "raw_sample_storage_path": RAW_SAMPLE_REL_ROOT.as_posix() + "/",
            "raw_samples_gitignored": True,
            "tracked_summary_contains_raw_rows": False,
            "response_body_text_in_summary": False,
            "request_urls_in_summary": False,
            "secrets_in_summary": False,
        },
        "sample_universe": {
            "symbols": [EXPECTED_SYMBOL],
            "active_symbols": [],
            "inactive_or_delisted_candidate_symbols": [EXPECTED_SYMBOL],
            "universe_role": "sivb_only_reprobe_not_full_market_or_security_master",
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "planned_fmp_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "planned_sec_endpoint_calls": 0,
            "actual_total_endpoint_calls": len(endpoint_records),
            "actual_fmp_endpoint_calls": len(endpoint_records),
            "actual_sec_endpoint_calls": 0,
            "retry_count_allowed": 0,
            "retry_count_used": 0,
            "within_budget": len(endpoint_records) <= MAX_TOTAL_ENDPOINT_CALLS,
        },
        "endpoint_results": endpoint_results,
        "aggregate_reprobe_metrics": aggregate,
        "classification_decision": {
            "decision": "sivb_reprobe_completed_keep_sr_provider_001_open"
            if not aggregate["endpoint_error_count"]
            else "sivb_reprobe_completed_with_endpoint_errors_keep_sr_provider_001_open",
            "sr_provider_001_closed": False,
            "sivb_402_paid_wall_proven": False,
            "inactive_delisted_coverage_proven": False,
            "provider_selection_allowed": False,
            "phase7c_allowed": False,
            "rationale": (
                "This execution classifies only SIVB HTTP-status and response-shape signals for five fixed FMP "
                "stable endpoint families. It does not prove paid-wall status, inactive / delisted coverage, "
                "current terms, production storage rights, PIT, price adjustment, corporate actions, provider "
                "selection, DataHub, Phase 7c, production readiness, alpha, or ship-gate evidence."
            ),
        },
        "no_silent_default_policy": {
            "fmp_http_402_is_not_missing_data_default": True,
            "twtr_success_is_not_inactive_delisted_coverage_proof": True,
            "null_fill_allowed": False,
            "zero_fill_allowed": False,
            "drop_failed_symbol_allowed": False,
            "latest_only_substitution_allowed": False,
            "production_default_allowed": False,
        },
        "prohibited_claims": {
            "sivb_402_paid_wall_proven": False,
            "endpoint_entitlement_proven": False,
            "symbol_lifecycle_proven": False,
            "historical_or_delisted_paid_tier_proven": False,
            "transient_quota_or_provider_incident_proven": False,
            "inactive_delisted_coverage_proven": False,
            "provider_selected": False,
            "provider_ranked": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "paid_access_used": False,
            "new_token_trial_or_provider_contact_used": False,
            "raw_rows_in_tracked_summary": False,
            "response_body_text_in_tracked_summary": False,
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
            "broker_or_order_automation": False,
        },
        "limitations": [
            "This is a SIVB-only / five-FMP-family re-probe, not a coverage proof or security-master test.",
            "Classification signals are category signals only and do not prove paid-wall status or any single hypothesis.",
            "Tracked summary excludes response body text, request URLs, secrets, and raw rows; raw wrappers remain gitignored.",
            "No SEC, yfinance, split / dividend endpoint, retry, provider selection, DataHub, Phase 7c, production, alpha, or ship-gate claim is made.",
        ],
        "next_steps": [
            "Independent review should verify the five-call boundary, raw/summary secret boundary, and no-silent-default policy before commit.",
            "Use this result only to route SR-PROVIDER-001; any broader inactive / delisted follow-up, split / dividend call, provider selection, or Phase 7c work requires a separate reviewed decision.",
        ],
    }


def summarize_endpoint(record: sample_validation.FetchRecord) -> dict[str, Any]:
    base = sample_validation.summarize_endpoint_record(record, endpoint_mode="stable")
    payload = record.payload
    return {
        "provider_id": base["provider_id"],
        "endpoint_family": base["endpoint_family"],
        "symbol": base["symbol"],
        "status": base["status"],
        "http_status": base["http_status"],
        "error_type": base["error_type"],
        "raw_sample_ref": base["raw_sample_ref"],
        "raw_sample_ref_gitignored": base["raw_sample_ref"].startswith(RAW_SAMPLE_REL_ROOT.as_posix() + "/"),
        "fmp_endpoint_mode": base["fmp_endpoint_mode"],
        "payload_shape": base["payload_shape"],
        "body_capture": body_capture_summary(payload),
        "classification_signal": classify_record(record),
    }


def body_capture_summary(payload: Any) -> dict[str, Any]:
    body_text = non_json_body_text(payload)
    bytes_value = None
    if isinstance(payload, dict):
        maybe_bytes = payload.get("non_json_response_bytes")
        bytes_value = maybe_bytes if isinstance(maybe_bytes, int) else None
    return {
        "non_json_response_body_captured_in_raw": body_text is not None,
        "non_json_response_bytes": bytes_value,
        "body_text_in_summary": False,
        "request_url_in_summary": False,
        "raw_rows_in_summary": False,
    }


def non_json_body_text(payload: Any) -> str | None:
    if isinstance(payload, dict):
        body = payload.get("non_json_response_body_text")
        if isinstance(body, str) and body:
            return body
    return None


def classification_text(payload: Any) -> str:
    body_text = non_json_body_text(payload)
    if body_text:
        return body_text
    try:
        return json.dumps(payload, ensure_ascii=False)
    except TypeError:
        return str(payload)


def classify_record(record: sample_validation.FetchRecord) -> dict[str, Any]:
    if record.http_status != 402:
        return classification_payload(
            category="not_402_response",
            confidence="none",
            basis="http_status_not_402",
            captured_body_available=non_json_body_text(record.payload) is not None,
        )
    text = classification_text(record.payload).lower()
    if not text or text in {"null", "none"}:
        return classification_payload(
            category="no_clear_signal",
            confidence="none",
            basis="http_402_without_classifiable_body_signal",
            captured_body_available=False,
        )
    if any(keyword in text for keyword in ["quota", "rate limit", "rate-limit", "too many", "temporary", "temporarily", "incident", "throttle"]):
        return classification_payload(
            category="transient_quota_or_provider_incident",
            confidence="weak",
            basis="http_402_body_keyword_signal",
            captured_body_available=non_json_body_text(record.payload) is not None,
        )
    if any(keyword in text for keyword in ["receivership", "bankrupt", "bankruptcy", "fdic", "delisted", "lifecycle", "sivb"]):
        return classification_payload(
            category="symbol_lifecycle",
            confidence="weak",
            basis="http_402_body_keyword_signal",
            captured_body_available=non_json_body_text(record.payload) is not None,
        )
    if any(keyword in text for keyword in ["historical", "history", "premium", "paid", "payment", "upgrade", "subscription", "plan"]):
        return classification_payload(
            category="historical_or_delisted_paid_tier",
            confidence="weak",
            basis="http_402_body_keyword_signal",
            captured_body_available=non_json_body_text(record.payload) is not None,
        )
    if any(keyword in text for keyword in ["entitlement", "permission", "access", "unauthorized", "not available", "endpoint"]):
        return classification_payload(
            category="endpoint_entitlement",
            confidence="weak",
            basis="http_402_body_keyword_signal",
            captured_body_available=non_json_body_text(record.payload) is not None,
        )
    return classification_payload(
        category="no_clear_signal",
        confidence="none",
        basis="http_402_body_present_without_known_keyword_signal",
        captured_body_available=non_json_body_text(record.payload) is not None,
    )


def classification_payload(
    *,
    category: str,
    confidence: str,
    basis: str,
    captured_body_available: bool,
) -> dict[str, Any]:
    return {
        "category": category,
        "confidence": confidence,
        "basis": basis,
        "captured_body_available": captured_body_available,
        "body_text_copied_to_summary": False,
        "request_url_copied_to_summary": False,
        "hypothesis_proven": False,
        "paid_wall_proven": False,
    }


def aggregate_reprobe_metrics(endpoint_results: list[dict[str, Any]]) -> dict[str, Any]:
    category_counts = Counter(item["classification_signal"]["category"] for item in endpoint_results)
    return {
        "endpoint_success_count": sum(1 for item in endpoint_results if item["status"] == "ok"),
        "endpoint_error_count": sum(1 for item in endpoint_results if item["status"] == "error"),
        "fmp_endpoint_success_count": sum(1 for item in endpoint_results if item["provider_id"] == "financial_modeling_prep" and item["status"] == "ok"),
        "fmp_endpoint_error_count": sum(1 for item in endpoint_results if item["provider_id"] == "financial_modeling_prep" and item["status"] == "error"),
        "http_402_count": sum(1 for item in endpoint_results if item["http_status"] == 402),
        "non_json_body_captured_count": sum(
            1 for item in endpoint_results if item["body_capture"]["non_json_response_body_captured_in_raw"]
        ),
        "classification_signal_counts": {category: category_counts.get(category, 0) for category in [
            "endpoint_entitlement",
            "symbol_lifecycle",
            "historical_or_delisted_paid_tier",
            "transient_quota_or_provider_incident",
            "not_402_response",
            "no_clear_signal",
        ]},
        "retry_count_used": 0,
        "sec_endpoint_call_count": 0,
        "split_or_dividend_endpoint_call_count": 0,
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
    summary = run_sivb_reprobe_packet(
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
                "endpoint_success_count": summary["aggregate_reprobe_metrics"]["endpoint_success_count"],
                "endpoint_error_count": summary["aggregate_reprobe_metrics"]["endpoint_error_count"],
                "http_402_count": summary["aggregate_reprobe_metrics"]["http_402_count"],
                "non_json_body_captured_count": summary["aggregate_reprobe_metrics"]["non_json_body_captured_count"],
                "classification_signal_counts": summary["aggregate_reprobe_metrics"]["classification_signal_counts"],
                "secrets_logged": summary["environment"]["secrets_logged"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
