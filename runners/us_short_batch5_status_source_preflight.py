from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_status_source import validate_access_packet_errors  # noqa: E402


PACKET_PATH = ROOT / "docs" / "us_short_batch5_status_source_access_packet_20260630.json"
EXPECTED_SYMBOLS = ["AAPL", "MSFT", "JPM"]
EXPECTED_ENDPOINTS = {
    ("ticker_reference", "active_listing_and_primary_exchange_reference"): ["delisted", "otc"],
    ("exchange_halt_feed", "public_trading_halt_feed"): ["halted"],
}
FUTURE_RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_status_source_20260630")
FUTURE_SUMMARY_REL_PATH = Path("docs/us_short_batch5_status_source_probe_summary_20260630.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline preflight for the US-short batch5 status-source access packet. "
            "This validates the packet boundary only; it never reads secrets, fetches status sources, "
            "writes provider_samples, writes a tracked summary, or authorizes live execution."
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
        raise ValueError("path must be repo-relative and non-traversing")
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

    schema_errors = validate_access_packet_errors(packet)
    if schema_errors:
        errors.append(f"canonical access-packet schema rejected {len(schema_errors)} field(s)")

    if packet.get("schema_name") != "us_short_batch5_status_source_access_packet":
        errors.append("schema_name must be us_short_batch5_status_source_access_packet")
    if packet.get("schema_version") != "1.0.0":
        errors.append("schema_version must be 1.0.0")

    scope = packet.get("scope") or {}
    for field, expected in {
        "market": "US",
        "lane": "us_short",
        "batch": "batch5_provider_live",
        "packet_status": "status_source_access_packet_recorded_for_review_not_executed",
    }.items():
        if scope.get(field) != expected:
            errors.append(f"scope.{field} must be {expected}")
    for field in [
        "status_source_calls_executed_by_this_artifact",
        "raw_payloads_read_by_this_artifact",
        "network_access_required_for_this_artifact",
        "status_calls_allowed_without_future_authorization",
        "bankruptcy_8k_per_issuer_scan_allowed",
        "full_market_or_per_symbol_fetch_allowed",
        "parser_into_runner_integration_allowed",
        "candidate_artifact_schema_change_allowed",
        "datahub_consumption_allowed",
        "production_storage_allowed",
        "yfinance_allowed",
        "web_x_allowed",
        "paid_access_allowed",
        "broker_or_order_automation_allowed",
        "live_normalized_evidence_allowed",
        "ship_gate_evidence_allowed",
        "production_ready_claim_allowed",
    ]:
        _expect_false(errors, scope, field, "scope")
    for field in [
        "user_authorized_real_status_source_integration",
        "small_sample_first_required",
        "future_status_fetch_requires_explicit_user_authorization",
        "future_status_fetch_requires_preflight",
    ]:
        _expect_true(errors, scope, field, "scope")

    boundary = packet.get("status_source_probe_boundary") or {}
    if boundary.get("authorization_status") != "not_authorized_by_this_artifact_requires_future_user_confirmation":
        errors.append("status_source_probe_boundary.authorization_status must keep future authorization required")
    sample = boundary.get("sample_universe") or {}
    if sample.get("symbols") != EXPECTED_SYMBOLS:
        errors.append("status_source_probe_boundary.sample_universe.symbols must be exactly AAPL/MSFT/JPM")
    if sample.get("active_symbols") != EXPECTED_SYMBOLS:
        errors.append("status_source_probe_boundary.sample_universe.active_symbols must be exactly AAPL/MSFT/JPM")
    if sample.get("max_symbols") != 3:
        errors.append("status_source_probe_boundary.sample_universe.max_symbols must be 3")
    _expect_true(errors, sample, "shape_validation_only", "sample_universe")
    _expect_true(errors, sample, "not_full_market_or_security_master", "sample_universe")

    budget = boundary.get("endpoint_call_budget") or {}
    for field, expected in {
        "max_total_endpoint_calls": 2,
        "ticker_reference_calls": 1,
        "halt_feed_calls": 1,
        "bankruptcy_8k_calls": 0,
        "retry_count_allowed": 0,
    }.items():
        if budget.get(field) != expected:
            errors.append(f"endpoint_call_budget.{field} must be {expected}")
    _expect_true(errors, budget, "abort_if_budget_exceeded", "endpoint_call_budget")
    _expect_false(errors, budget, "budget_authorized_by_this_artifact", "endpoint_call_budget")

    families = {
        (item.get("source_id"), item.get("endpoint_family")): item
        for item in boundary.get("endpoint_families", [])
        if isinstance(item, dict)
    }
    if set(families) != set(EXPECTED_ENDPOINTS):
        errors.append("endpoint_families must stay fixed to ticker_reference + exchange_halt_feed")
    for key, expected_flags in EXPECTED_ENDPOINTS.items():
        family = families.get(key) or {}
        if family.get("flags") != expected_flags:
            errors.append(f"endpoint_families.{key}.flags must be {expected_flags}")
        if family.get("call_count") != 1:
            errors.append(f"endpoint_families.{key}.call_count must be 1")
        if family.get("exact_endpoint_status") != "pending_preflight_confirmation":
            errors.append(f"endpoint_families.{key}.exact_endpoint_status must stay pending_preflight_confirmation")
        _expect_false(errors, family, "authorizes_status_call_now", f"endpoint_families.{key}")
        _expect_true(errors, family, "raw_parse_allowed_after_future_authorization", f"endpoint_families.{key}")
        _expect_false(errors, family, "authorizes_datahub_or_runner_consumption", f"endpoint_families.{key}")

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


def _ordered_endpoint_families(packet: dict[str, Any]) -> list[dict[str, Any]]:
    families = packet["status_source_probe_boundary"]["endpoint_families"]
    by_source = {family["source_id"]: family for family in families}
    return [by_source["ticker_reference"], by_source["exchange_halt_feed"]]


def run_preflight(
    *,
    packet_path: Path = PACKET_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    packet = load_and_validate_packet(packet_path)
    if not provider_samples_gitignored():
        raise RuntimeError("provider_samples/ is not confirmed in .gitignore")
    generated_at = generated_at or iso_now()
    boundary = {
        **packet["status_source_probe_boundary"],
        "endpoint_families": _ordered_endpoint_families(packet),
    }
    return {
        "schema_name": "us_short_batch5_status_source_preflight_result",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "packet_ref": "docs/us_short_batch5_status_source_access_packet_20260630.json",
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "preflight_status": "offline_preflight_passed_status_source_authorization_required",
            "status_source_calls_performed": False,
            "network_access_required": False,
            "raw_payloads_read": False,
            "raw_payloads_written": False,
            "tracked_summary_written": False,
            "future_status_fetch_requires_explicit_user_authorization": True,
            "future_status_fetch_requires_preflight": True,
            "future_status_fetch_requires_user_execute": True,
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
            "exact_endpoint_family_boundary_validated": True,
            "exact_endpoint_confirmation_still_required_before_probe": True,
            "no_full_market_guard_passed": True,
            "no_bankruptcy_8k_scan_guard_passed": True,
            "no_datahub_consumption_guard_passed": True,
            "no_ship_gate_claim_guard_passed": True,
        },
        "environment": {
            "environment_values_read": False,
            "status_source_credentials_present": "not_checked_offline_preflight",
            "sec_user_agent_present": "not_checked_offline_preflight",
            "secrets_logged": False,
        },
        "status_source_probe_boundary": boundary,
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
            "requires_user_execute": True,
            "source_families": ["ticker_reference", "exchange_halt_feed"],
            "symbols": EXPECTED_SYMBOLS,
            "max_total_endpoint_calls": 2,
            "retry_count_allowed": 0,
            "bankruptcy_8k_calls": 0,
            "raw_storage_path": packet["storage_and_secret_boundary"]["future_raw_sample_storage_path"],
            "tracked_summary_path": packet["storage_and_secret_boundary"]["future_tracked_summary_path"],
            "forbidden": [
                "bankruptcy_8k_scan",
                "full_market_or_per_symbol_fetch",
                "parser_into_runner_integration",
                "candidate_artifact_schema_change",
                "datahub_consumption",
                "production_storage",
                "provider_selection",
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
