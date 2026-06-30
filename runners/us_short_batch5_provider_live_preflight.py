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


PACKET_PATH = ROOT / "docs" / "us_short_batch5_provider_live_packet_20260625.json"
EXPECTED_SYMBOLS = ["AAPL", "MSFT", "JPM"]
EXPECTED_ENDPOINTS = {
    ("financial_modeling_prep", "profile_or_company_metadata"): 3,
    ("financial_modeling_prep", "historical_eod_price_volume"): 3,
    ("sec_edgar", "company_tickers_mapping"): 1,
    ("sec_edgar", "company_submissions"): 3,
}
FUTURE_RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_v1_provider_live_20260625")
FUTURE_SUMMARY_REL_PATH = Path("docs/us_short_batch5_provider_live_probe_summary_20260625.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline preflight for the US-short batch5 provider/live first-version packet. "
            "This command validates the packet boundary only; it never reads secrets, fetches provider data, "
            "writes provider_samples, writes a tracked summary, or authorizes live/provider execution."
        )
    )
    parser.add_argument("--packet-path", type=Path, default=PACKET_PATH)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def _repo_relative_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path must be repo-relative and non-traversing: {path_text}")
    return path


def _expect_false(errors: list[str], obj: dict[str, Any], field: str, prefix: str) -> None:
    if obj.get(field) is not False:
        errors.append(f"{prefix}.{field} must be false")


def _expect_true(errors: list[str], obj: dict[str, Any], field: str, prefix: str) -> None:
    if obj.get(field) is not True:
        errors.append(f"{prefix}.{field} must be true")


def load_and_validate_packet(path: Path) -> dict[str, Any]:
    packet = read_json(path)
    errors: list[str] = []
    if packet.get("schema_name") != "us_short_batch5_provider_live_packet":
        errors.append("schema_name must be us_short_batch5_provider_live_packet")
    if packet.get("schema_version") != "1.0.0":
        errors.append("schema_version must be 1.0.0")

    scope = packet.get("scope") or {}
    expected_scope_values = {
        "market": "US",
        "lane": "us_short",
        "batch": "batch5_provider_live",
        "first_version_status": "offline_readiness_packet_recorded_for_review_not_executed",
    }
    for field, expected in expected_scope_values.items():
        if scope.get(field) != expected:
            errors.append(f"scope.{field} must be {expected}")
    for field in [
        "provider_calls_executed_by_this_artifact",
        "raw_payloads_read_by_this_artifact",
        "network_access_required_for_this_artifact",
        "provider_calls_allowed_without_future_authorization",
        "provider_selection_allowed",
        "provider_adapter_allowed",
        "datahub_consumption_allowed",
        "skill_runtime_allowed",
        "production_storage_allowed",
        "full_market_or_broad_universe_allowed",
        "yfinance_allowed",
        "web_x_allowed",
        "sec_parser_implementation_allowed",
        "field_mapping_or_derivation_implementation_allowed",
        "return_calculation_allowed",
        "corporate_action_reconciliation_allowed",
        "broker_or_order_automation_allowed",
        "paper_results_as_live_normalized_allowed",
        "ship_gate_evidence_allowed",
        "production_ready_claim_allowed",
    ]:
        _expect_false(errors, scope, field, "scope")
    for field in [
        "small_sample_first_required",
        "future_provider_live_probe_requires_explicit_user_authorization",
        "future_provider_live_probe_requires_reviewed_execution_packet",
    ]:
        _expect_true(errors, scope, field, "scope")

    boundary = packet.get("future_provider_live_probe_boundary") or {}
    if boundary.get("authorization_status") != "not_authorized_by_this_artifact_requires_future_user_confirmation":
        errors.append("future_provider_live_probe_boundary.authorization_status must keep future authorization required")
    sample = boundary.get("sample_universe") or {}
    if sample.get("symbols") != EXPECTED_SYMBOLS:
        errors.append("future_provider_live_probe_boundary.sample_universe.symbols must be exactly AAPL/MSFT/JPM")
    if sample.get("active_symbols") != EXPECTED_SYMBOLS:
        errors.append("future_provider_live_probe_boundary.sample_universe.active_symbols must be exactly AAPL/MSFT/JPM")
    if sample.get("max_symbols") != 3:
        errors.append("future_provider_live_probe_boundary.sample_universe.max_symbols must be 3")
    if sample.get("inactive_or_delisted_historical_scope") != "scoped_out_for_current_active_only_forward_model":
        errors.append("inactive/delisted historical scope must stay scoped out")
    _expect_true(errors, sample, "not_full_market_or_security_master", "sample_universe")
    _expect_false(errors, sample, "forward_universe_snapshot_written_by_this_artifact", "sample_universe")

    budget = boundary.get("endpoint_call_budget") or {}
    expected_budget = {
        "max_total_endpoint_calls": 10,
        "fmp_planned_endpoint_calls": 6,
        "sec_endpoint_calls": 4,
        "retry_count_allowed": 0,
    }
    for field, expected in expected_budget.items():
        if budget.get(field) != expected:
            errors.append(f"endpoint_call_budget.{field} must be {expected}")
    _expect_true(errors, budget, "abort_if_budget_exceeded", "endpoint_call_budget")
    _expect_false(errors, budget, "budget_authorized_by_this_artifact", "endpoint_call_budget")

    families = {
        (item.get("provider_id"), item.get("endpoint_family")): item
        for item in boundary.get("endpoint_families", [])
        if isinstance(item, dict)
    }
    if set(families) != set(EXPECTED_ENDPOINTS):
        errors.append("endpoint_families must stay fixed to FMP profile/EOD and SEC tickers/submissions")
    for key, expected_count in EXPECTED_ENDPOINTS.items():
        family = families.get(key) or {}
        if family.get("call_count") != expected_count:
            errors.append(f"endpoint_families.{key} call_count must be {expected_count}")
        for field in [
            "authorizes_provider_call_now",
            "authorizes_datahub_or_runner_consumption",
            "authorizes_return_calculation",
            "authorizes_corporate_action_reconciliation",
        ]:
            _expect_false(errors, family, field, f"endpoint_families.{key}")
        _expect_true(errors, family, "raw_parse_allowed_after_future_authorization", f"endpoint_families.{key}")

    storage = packet.get("storage_and_secret_boundary") or {}
    try:
        raw_path = _repo_relative_path(str(storage.get("future_raw_sample_storage_path", "")))
        raw_path.resolve().relative_to((ROOT / "provider_samples").resolve())
    except Exception:
        errors.append("future_raw_sample_storage_path must stay under provider_samples/")
    if storage.get("future_raw_sample_storage_path") != FUTURE_RAW_SAMPLE_REL_ROOT.as_posix() + "/":
        errors.append("future_raw_sample_storage_path mismatch")
    try:
        summary_path = _repo_relative_path(str(storage.get("future_tracked_summary_path", "")))
        summary_path.resolve().relative_to((ROOT / "docs").resolve())
    except Exception:
        errors.append("future_tracked_summary_path must stay under docs/")
    if storage.get("future_tracked_summary_path") != FUTURE_SUMMARY_REL_PATH.as_posix():
        errors.append("future_tracked_summary_path mismatch")
    for field in [
        "provider_samples_gitignore_check_required",
        "tracked_summary_must_exclude_raw_payloads",
        "tracked_summary_must_exclude_request_urls",
        "tracked_summary_must_exclude_secrets",
    ]:
        _expect_true(errors, storage, field, "storage_and_secret_boundary")
    for field in [
        "tracked_summary_write_authorized_by_this_artifact",
        "raw_payload_write_authorized_by_this_artifact",
        "production_storage_authorized",
    ]:
        _expect_false(errors, storage, field, "storage_and_secret_boundary")

    preflight_gates = packet.get("preflight_gates")
    if not isinstance(preflight_gates, dict) or not preflight_gates:
        errors.append("preflight_gates must be a non-empty object")
    else:
        for field, value in preflight_gates.items():
            if value is not True:
                errors.append(f"preflight_gates.{field} must be true")
    prohibited_claims = packet.get("prohibited_claims")
    if not isinstance(prohibited_claims, dict) or not prohibited_claims:
        errors.append("prohibited_claims must be a non-empty object")
    else:
        for field, value in prohibited_claims.items():
            if value is not False:
                errors.append(f"prohibited_claims.{field} must be false")

    if errors:
        raise ValueError("; ".join(errors))
    return packet


def run_preflight(
    *,
    packet_path: Path = PACKET_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    packet = load_and_validate_packet(packet_path)
    if not provider_samples_gitignored():
        raise RuntimeError("provider_samples/ is not confirmed in .gitignore")
    generated_at = generated_at or iso_now()
    return {
        "schema_name": "us_short_batch5_provider_live_preflight_result",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "packet_ref": "docs/us_short_batch5_provider_live_packet_20260625.json",
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "preflight_status": "offline_preflight_passed_provider_authorization_required",
            "provider_calls_performed": False,
            "network_access_required": False,
            "raw_payloads_read": False,
            "raw_payloads_written": False,
            "tracked_summary_written": False,
            "future_provider_live_probe_requires_explicit_user_authorization": True,
            "future_provider_live_probe_requires_reviewed_execution_packet": True,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
        },
        "preflight_checks": {
            "packet_contract_validated": True,
            "provider_samples_gitignore_confirmed": True,
            "future_raw_path_under_provider_samples": True,
            "future_summary_path_under_docs": True,
            "budget_precheck_passed": True,
            "no_full_market_guard_passed": True,
            "no_datahub_consumption_guard_passed": True,
            "no_ship_gate_claim_guard_passed": True,
        },
        "environment": {
            "environment_values_read": False,
            "fmp_api_key_present": "not_checked_offline_preflight",
            "sec_user_agent_present": "not_checked_offline_preflight",
            "secrets_logged": False,
        },
        "future_provider_live_probe_boundary": packet["future_provider_live_probe_boundary"],
        "storage": {
            "future_raw_sample_storage_path": packet["storage_and_secret_boundary"]["future_raw_sample_storage_path"],
            "future_tracked_summary_path": packet["storage_and_secret_boundary"]["future_tracked_summary_path"],
            "raw_payloads_written": False,
            "tracked_summary_written": False,
            "tracked_summary_must_exclude_raw_payloads": True,
            "tracked_summary_must_exclude_request_urls": True,
            "tracked_summary_must_exclude_secrets": True,
        },
        "prohibited_claims": packet["prohibited_claims"],
        "next_authorization_request": {
            "requires_user_confirmation": True,
            "provider_families": ["financial_modeling_prep", "sec_edgar"],
            "symbols": EXPECTED_SYMBOLS,
            "max_total_endpoint_calls": 10,
            "retry_count_allowed": 0,
            "raw_storage_path": packet["storage_and_secret_boundary"]["future_raw_sample_storage_path"],
            "tracked_summary_path": packet["storage_and_secret_boundary"]["future_tracked_summary_path"],
            "forbidden": [
                "yfinance",
                "web_x",
                "full_market",
                "datahub_consumption",
                "production_storage",
                "provider_selection",
                "return_calculation",
                "corporate_action_reconciliation",
                "ship_gate_evidence",
                "broker_or_order_automation",
            ],
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_preflight(packet_path=args.packet_path, generated_at=args.generated_at)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
