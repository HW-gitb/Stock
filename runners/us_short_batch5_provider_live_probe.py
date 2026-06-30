from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# F5 (cc_r1_v1): make jsonschema resolvable when it is only vendored under .tools/python_libs — the probe's
# mandatory pre-write _validate_summary_against_schema imports jsonschema; mirror the incident-log writer's
# bootstrap so the two batch5 writers guarantee the dependency the same way.
_PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if _PYTHON_LIBS.exists() and str(_PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(_PYTHON_LIBS))

from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_batch5_provider_live_preflight as preflight  # noqa: E402


PACKET_PATH = ROOT / "docs" / "us_short_batch5_provider_live_packet_20260625.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_provider_live_probe_summary_20260625.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_provider_live_probe_summary.schema.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_v1_provider_live_20260625")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"
EXPECTED_SYMBOLS = ["AAPL", "MSFT", "JPM"]
MAX_TOTAL_ENDPOINT_CALLS = 10
PLANNED_FMP_ENDPOINT_CALLS = 6
PLANNED_SEC_PUBLIC_API_CALLS = 4
AUTHORIZATION_REF = "user_chat_20260625_batch5_provider_live_probe_10_call_boundary"

FMP_ENDPOINTS = [
    endpoint
    for endpoint in sample_validation.FMP_STABLE_ENDPOINTS
    if endpoint["endpoint_family"] in {"profile_or_company_metadata", "historical_eod_price_volume"}
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the explicitly authorized US-short batch5 10-call provider/live small-sample probe. "
            "Raw payloads are written only under gitignored provider_samples/; the tracked summary "
            "must not contain URLs, secrets, or raw payload rows."
        )
    )
    parser.add_argument("--packet-path", type=Path, default=PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at")
    parser.add_argument(
        "--dry-run-env",
        action="store_true",
        help="Validate packet/env/storage boundary in memory only; no network and no writes.",
    )
    parser.add_argument(
        "--confirm-user-authorization",
        action="store_true",
        help="Required for live/provider execution; documents the separate user authorization.",
    )
    parser.add_argument(
        "--rebuild-from-existing-raw",
        action="store_true",
        help="Rebuild the tracked summary from the already authorized gitignored raw samples; no env read, no network.",
    )
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _validate_batch5_packet(packet_path: Path) -> dict[str, Any]:
    packet = preflight.load_and_validate_packet(packet_path)
    boundary = packet["future_provider_live_probe_boundary"]
    if boundary["sample_universe"]["symbols"] != EXPECTED_SYMBOLS:
        raise ValueError("batch5 probe symbols must remain AAPL/MSFT/JPM")
    if boundary["endpoint_call_budget"]["max_total_endpoint_calls"] != MAX_TOTAL_ENDPOINT_CALLS:
        raise ValueError("batch5 probe budget must remain exactly 10 calls")
    if boundary["endpoint_call_budget"]["retry_count_allowed"] != 0:
        raise ValueError("batch5 probe retry budget must remain zero")
    return packet


def _validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError("raw_root must stay under provider_samples/us_short_batch5_v1_provider_live_20260625/") from exc
    sample_validation.validate_raw_root(raw_root)


def _read_env_summary() -> tuple[sample_validation.EnvValue, sample_validation.EnvValue, dict[str, Any]]:
    fmp_env = sample_validation.read_required_env("FMP_API_KEY")
    sec_user_agent_env = sample_validation.read_required_env("SEC_USER_AGENT")
    return (
        fmp_env,
        sec_user_agent_env,
        {
            "fmp_api_key_present": True,
            "fmp_api_key_source": fmp_env.source,
            "sec_user_agent_present": True,
            "sec_user_agent_source": sec_user_agent_env.source,
            "environment_values_logged": False,
            "secrets_logged": False,
        },
    )


def _assert_budget(endpoint_records: list[sample_validation.FetchRecord], next_call_count: int = 1) -> None:
    sample_validation.assert_endpoint_budget_available(
        endpoint_records,
        MAX_TOTAL_ENDPOINT_CALLS,
        next_call_count=next_call_count,
    )


def _payload_shape(endpoint_family: str, payload: Any) -> dict[str, Any]:
    rows = sample_validation.payload_rows(endpoint_family, payload)
    if rows is not None:
        return {"kind": "list", "row_count": len(rows)}
    if isinstance(payload, dict):
        return {"kind": "object", "row_count": None}
    if payload is None:
        return {"kind": "null", "row_count": None}
    return {"kind": type(payload).__name__, "row_count": None}


def _fields_for_record(record: sample_validation.FetchRecord) -> list[str]:
    if record.provider_id == "financial_modeling_prep":
        return sample_validation.fields_for_endpoint(record.endpoint_family, endpoint_mode="stable")
    if record.endpoint_family == "company_tickers_mapping":
        return ["ticker", "cik_str"]
    if record.endpoint_family in {"company_submissions", "submissions"}:
        return sample_validation.fields_for_endpoint("submissions")
    return []


def _first_row_for_record(record: sample_validation.FetchRecord) -> dict[str, Any] | None:
    if record.endpoint_family in {"company_submissions", "submissions"}:
        return sample_validation.first_row("submissions", record.payload)
    rows = sample_validation.payload_rows(record.endpoint_family, record.payload)
    if rows and isinstance(rows[0], dict):
        return rows[0]
    if record.endpoint_family == "company_tickers_mapping" and isinstance(record.payload, dict):
        for item in record.payload.values():
            if isinstance(item, dict):
                return item
    return None


def summarize_endpoint_record(record: sample_validation.FetchRecord) -> dict[str, Any]:
    required_fields = _fields_for_record(record)
    row = _first_row_for_record(record)
    if row is None:
        field_presence = {field: False for field in required_fields}
    else:
        field_presence = {field: field in row and row.get(field) is not None for field in required_fields}
    provider = "FMP" if record.provider_id == "financial_modeling_prep" else "SEC"
    family = "company_submissions" if record.endpoint_family == "submissions" else record.endpoint_family
    return {
        "provider": provider,
        "endpoint_family": family,
        "symbol": record.symbol,
        "status": "success" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": True,
        "payload_shape": _payload_shape(record.endpoint_family, record.payload),
        "field_presence": field_presence,
        "missing_required_fields": [field for field, present in field_presence.items() if not present],
    }


def _status_for(records: list[sample_validation.FetchRecord], symbol: str | None, family: str) -> str:
    helper_family = "submissions" if family == "company_submissions" else family
    for record in records:
        if record.symbol == symbol and record.endpoint_family == helper_family:
            return "success" if record.ok else "error"
    return "not_called"


def summarize_symbol(
    symbol: str,
    records: list[sample_validation.FetchRecord],
    cik_by_symbol: dict[str, str],
) -> dict[str, Any]:
    cik10 = cik_by_symbol.get(symbol)
    observations: list[str] = []
    for family in ["profile_or_company_metadata", "historical_eod_price_volume"]:
        if _status_for(records, symbol, family) == "error":
            observations.append(f"FMP {family} returned an endpoint error")
    if not cik10:
        observations.append("SEC CIK not found in company_tickers mapping")
    elif _status_for(records, symbol, "company_submissions") == "error":
        observations.append("SEC submissions returned an endpoint error")
    return {
        "symbol": symbol,
        "active_symbol_assumption": True,
        "sec_cik_found": cik10 is not None,
        "sec_cik10": cik10,
        "fmp_endpoint_status": {
            "profile_or_company_metadata": _status_for(records, symbol, "profile_or_company_metadata"),
            "historical_eod_price_volume": _status_for(records, symbol, "historical_eod_price_volume"),
        },
        "sec_endpoint_status": {
            "company_submissions": _status_for(records, symbol, "company_submissions"),
        },
        "observations": observations,
    }


def _count_symbols_with_required_fields(
    endpoint_summaries: list[dict[str, Any]],
    family: str,
    provider: str,
) -> int:
    symbols = {
        item["symbol"]
        for item in endpoint_summaries
        if item["provider"] == provider
        and item["endpoint_family"] == family
        and item["status"] == "success"
        and not item["missing_required_fields"]
    }
    return len(symbols)


def build_summary(
    *,
    generated_at: str,
    env_summary: dict[str, Any],
    endpoint_records: list[sample_validation.FetchRecord],
    cik_by_symbol: dict[str, str],
    dry_run_env: bool,
    authorization_confirmed: bool,
) -> dict[str, Any]:
    endpoint_summaries = [summarize_endpoint_record(record) for record in endpoint_records]
    symbol_summaries = [summarize_symbol(symbol, endpoint_records, cik_by_symbol) for symbol in EXPECTED_SYMBOLS]
    actual_fmp_calls = sum(1 for record in endpoint_records if record.provider_id == "financial_modeling_prep")
    actual_sec_calls = sum(1 for record in endpoint_records if record.provider_id == "sec_edgar")
    endpoint_errors = sum(1 for record in endpoint_records if not record.ok)
    if dry_run_env:
        status = "dry_run_env_only"
        first_version_status = "dry_run_env_only"
    elif endpoint_errors:
        status = "bounded_probe_completed_with_endpoint_errors"
        first_version_status = "provider_live_probe_executed_small_sample_only"
    else:
        status = "bounded_probe_completed"
        first_version_status = "provider_live_probe_executed_small_sample_only"

    return {
        "schema_name": "us_short_batch5_provider_live_probe_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_provider_live_probe_summary.schema.json",
        "packet_ref": "docs/us_short_batch5_provider_live_packet_20260625.json",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "first_version_status": first_version_status,
            "provider_live_probe_performed": not dry_run_env,
            "raw_payload_storage_performed": not dry_run_env,
            "validation_only_raw_parse_performed": not dry_run_env,
            "datahub_consumption_performed": False,
            "web_x_consumption_performed": False,
            "yfinance_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "broker_or_order_execution_performed": False,
            "manual_order_only": True,
            "ship_gate_or_live_normalized_evidence_claimed": False,
        },
        "pre_execution_checks": {
            "user_authorization_confirmed": authorization_confirmed,
            "packet_contract_validated": True,
            "provider_samples_gitignore_confirmed": True,
            "environment_precheck_passed": True,
            "fmp_api_key_present": env_summary["fmp_api_key_present"],
            "sec_user_agent_present": env_summary["sec_user_agent_present"],
            "budget_precheck_passed": True,
            "no_yfinance": True,
            "no_web_x": True,
            "no_datahub": True,
            "no_full_market": True,
            "no_production_storage": True,
            "no_ship_gate_or_live_normalized_claim": True,
            "no_broker_or_order_execution": True,
        },
        "environment": env_summary,
        "storage": {
            "raw_payload_root": (RAW_SAMPLE_REL_ROOT / "raw").as_posix(),
            "raw_payload_root_gitignored": True,
            "tracked_summary_path": "docs/us_short_batch5_provider_live_probe_summary_20260625.json",
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_raw_payload": False,
            "secrets_in_summary": False,
            "request_urls_in_summary": False,
            "sec_user_agent_value_in_summary": False,
        },
        "sample_universe": {
            "symbol_source": "batch5_v1_packet_authorized_active_only_sample",
            "symbols": EXPECTED_SYMBOLS,
            "active_symbols_only": True,
            "max_symbols": 3,
            "full_market_sample": False,
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "planned_fmp_endpoint_calls": PLANNED_FMP_ENDPOINT_CALLS,
            "planned_sec_public_api_calls": PLANNED_SEC_PUBLIC_API_CALLS,
            "actual_total_endpoint_calls": len(endpoint_records),
            "actual_fmp_endpoint_calls": actual_fmp_calls,
            "actual_sec_public_api_calls": actual_sec_calls,
            "retry_count": 0,
            "within_budget": len(endpoint_records) <= MAX_TOTAL_ENDPOINT_CALLS
            and actual_fmp_calls <= PLANNED_FMP_ENDPOINT_CALLS
            and actual_sec_calls <= PLANNED_SEC_PUBLIC_API_CALLS,
        },
        "endpoint_results": endpoint_summaries,
        "symbol_results": symbol_summaries,
        "aggregate_validation_metrics": {
            "endpoint_success_count": len(endpoint_records) - endpoint_errors,
            "endpoint_error_count": endpoint_errors,
            "symbols_with_profile_shape": _count_symbols_with_required_fields(
                endpoint_summaries, "profile_or_company_metadata", "FMP"
            ),
            "symbols_with_price_volume_shape": _count_symbols_with_required_fields(
                endpoint_summaries, "historical_eod_price_volume", "FMP"
            ),
            "symbols_with_sec_cik": len(cik_by_symbol),
            "symbols_with_sec_submissions_shape": _count_symbols_with_required_fields(
                endpoint_summaries, "company_submissions", "SEC"
            ),
        },
        "validation_decision": {
            "status": status,
            "sr_provider_001_remains_open": True,
            "provider_selection_allowed": False,
            "datahub_allowed": False,
            "production_storage_allowed": False,
            "full_market_fetch_allowed": False,
            "ship_gate_evidence_allowed": False,
        },
        "prohibited_claims": {
            "live_normalized_evidence_claimed": False,
            "ship_gate_evidence_claimed": False,
            "production_readiness_claimed": False,
            "provider_selected": False,
            "datahub_ready": False,
            "paper_result_relabelled_as_live": False,
        },
        "limitations": [
            "This is a three-symbol active-only provider/live response-shape probe, not coverage evidence.",
            "Raw payloads are stored only under gitignored provider_samples; the tracked summary excludes secrets, request URLs, and raw rows.",
            "This does not resolve license/storage, PIT, price adjustment, corporate-action, SEC parser/mapping, fallback/stability, provider selection, DataHub, production-readiness, live_normalized, or ship-gate gates.",
        ],
        "next_steps": [
            "Codex review before any commit.",
            "Do not broaden symbols, endpoints, providers, DataHub consumption, production storage, or market coverage without separate authorization.",
        ],
    }


def _assert_text_safe(text: str, sensitive_values: list[str]) -> None:
    lower = text.lower()
    forbidden_fragments = [
        "apikey=",
        "financialmodelingprep.com",
        "data.sec.gov",
        "www.sec.gov",
        "\"payload\"",
        "\"request_url\"",
        "\"raw_payload\"",
    ]
    for fragment in forbidden_fragments:
        if fragment in lower:
            raise RuntimeError(f"tracked summary contains forbidden fragment: {fragment}")
    for value in sensitive_values:
        if value and value in text:
            raise RuntimeError("tracked summary contains a sensitive environment value")


def _assert_summary_safe(summary_path: Path, sensitive_values: list[str]) -> None:
    _assert_text_safe(summary_path.read_text(encoding="utf-8"), sensitive_values)


def _validate_summary_against_schema(summary: dict) -> None:
    """Draft7-validate the summary against its schema BEFORE any write (R-USSHORT-BATCH5-RUNTIME-SCHEMA-
    ENFORCEMENT-GAP): a schema-invalid summary — a flipped safety flag, an out-of-range count, an illegal
    status — must NEVER be written (no write-then-validate). The schema accepts the legal success / error /
    dry-run branches while pinning the safety/honesty flags."""
    from jsonschema import Draft7Validator
    schema = json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft7Validator(schema).iter_errors(summary), key=lambda err: list(err.path))
    if errors:
        raise RuntimeError("probe summary failed schema validation: "
                           + "; ".join(err.message for err in errors[:5]))


def _write_summary_validated(summary: dict, summary_path: Path, sensitive_values: list[str]) -> None:
    """Schema-validate + secret-scan the SERIALIZED summary BEFORE the atomic write — no write-then-validate and
    no schema-invalid / secret-bearing residue (the scanned text is byte-identical to what write_json_atomic writes)."""
    _validate_summary_against_schema(summary)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text, sensitive_values)
    write_json_atomic(summary, summary_path)


def _load_record_from_raw(path: Path) -> sample_validation.FetchRecord:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return sample_validation.FetchRecord(
        provider_id=raw["provider_id"],
        endpoint_family=raw["endpoint_family"],
        symbol=raw.get("symbol"),
        raw_sample_ref=_repo_relative(path),
        ok=bool(raw["ok"]),
        http_status=raw.get("http_status"),
        error_type=raw.get("error_type"),
        payload=raw.get("payload"),
    )


def load_records_from_existing_raw(raw_root: Path) -> tuple[list[sample_validation.FetchRecord], dict[str, str]]:
    _validate_raw_root(raw_root)
    expected_paths: list[Path] = [
        raw_root / "sec_edgar" / "_market" / "company_tickers_mapping.json",
    ]
    for symbol in EXPECTED_SYMBOLS:
        for endpoint in FMP_ENDPOINTS:
            expected_paths.append(
                raw_root
                / "financial_modeling_prep"
                / symbol
                / f"{endpoint['endpoint_family']}.json"
            )
    for symbol in EXPECTED_SYMBOLS:
        expected_paths.append(raw_root / "sec_edgar" / symbol / "submissions.json")

    missing = [path for path in expected_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing expected batch5 raw samples: {', '.join(str(path) for path in missing)}")

    records = [_load_record_from_raw(path) for path in expected_paths]
    cik_by_symbol = sample_validation.parse_sec_cik_map(records[0].payload, EXPECTED_SYMBOLS)
    if len(records) != MAX_TOTAL_ENDPOINT_CALLS:
        raise RuntimeError(f"expected {MAX_TOTAL_ENDPOINT_CALLS} raw records, got {len(records)}")
    return records, cik_by_symbol


def rebuild_summary_from_existing_raw(
    *,
    packet_path: Path = PACKET_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    generated_at: str | None = None,
    existing_summary_path: Path = SUMMARY_PATH,
) -> dict[str, Any]:
    _validate_batch5_packet(packet_path)   # honor the CLI --packet-path (R4: was hardcoded to PACKET_PATH)
    if not preflight.provider_samples_gitignored():
        raise RuntimeError("provider_samples/ is not confirmed in .gitignore")
    existing_summary = {}
    if existing_summary_path.exists():
        with existing_summary_path.open("r", encoding="utf-8") as handle:
            existing_summary = json.load(handle)
    env_summary = existing_summary.get("environment") or {
        "fmp_api_key_present": True,
        "fmp_api_key_source": "not_checked",
        "sec_user_agent_present": True,
        "sec_user_agent_source": "not_checked",
        "environment_values_logged": False,
        "secrets_logged": False,
    }
    records, cik_by_symbol = load_records_from_existing_raw(raw_root)
    summary = build_summary(
        generated_at=generated_at or existing_summary.get("generated_at") or iso_now(),
        env_summary=env_summary,
        endpoint_records=records,
        cik_by_symbol=cik_by_symbol,
        dry_run_env=False,
        authorization_confirmed=True,
    )
    _write_summary_validated(summary, summary_path, [])   # schema-validate + scan BEFORE write (no residue)
    return summary


def run_probe(
    *,
    packet_path: Path = PACKET_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    generated_at: str | None = None,
    client: sample_validation.JsonHttpClient | None = None,
    confirm_user_authorization: bool = False,
    dry_run_env: bool = False,
    sec_sleep_seconds: float = sample_validation.SEC_FAIR_ACCESS_SLEEP_SECONDS,
) -> dict[str, Any]:
    if not confirm_user_authorization and not dry_run_env:
        raise RuntimeError("live provider execution requires --confirm-user-authorization")
    _validate_batch5_packet(packet_path)
    if not preflight.provider_samples_gitignored():
        raise RuntimeError("provider_samples/ is not confirmed in .gitignore")
    _validate_raw_root(raw_root)
    generated_at = generated_at or iso_now()
    fmp_env, sec_user_agent_env, env_summary = _read_env_summary()

    if dry_run_env:
        return build_summary(
            generated_at=generated_at,
            env_summary=env_summary,
            endpoint_records=[],
            cik_by_symbol={},
            dry_run_env=True,
            authorization_confirmed=confirm_user_authorization,
        )

    client = client or sample_validation.JsonHttpClient()
    endpoint_records: list[sample_validation.FetchRecord] = []

    sec_headers = {
        "User-Agent": sec_user_agent_env.value,
        "Host": "www.sec.gov",
    }
    _assert_budget(endpoint_records)
    tickers_record = sample_validation.fetch_and_store(
        client,
        url=sample_validation.sec_url("company_tickers_mapping"),
        provider_id="sec_edgar",
        endpoint_family="company_tickers_mapping",
        symbol=None,
        raw_root=raw_root,
        headers=sec_headers,
    )
    endpoint_records.append(tickers_record)
    cik_by_symbol = sample_validation.parse_sec_cik_map(tickers_record.payload, EXPECTED_SYMBOLS)

    fmp_headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-provider-live-probe"}
    for symbol in EXPECTED_SYMBOLS:
        for endpoint in FMP_ENDPOINTS:
            _assert_budget(endpoint_records)
            endpoint_records.append(
                sample_validation.fetch_and_store(
                    client,
                    url=sample_validation.fmp_url(
                        endpoint["path_template"],
                        symbol,
                        endpoint["params"],
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

    for symbol in EXPECTED_SYMBOLS:
        cik10 = cik_by_symbol.get(symbol)
        if not cik10:
            # F9 (cc_r1_v1): a sample symbol with no resolvable CIK (parse_sec_cik_map dropped a malformed
            # cik_str, or SEC renamed/dropped the ticker) makes the run fall short of the fixed 10-call trace.
            # This is INTENTIONAL fail-closed: the `!= MAX_TOTAL_ENDPOINT_CALLS` guard below then raises with NO
            # summary (7-9 real calls were spent, but we will not emit a summary asserting full 10-call
            # coverage). Do NOT "fix" the bare RuntimeError by relaxing the exact-10 invariant.
            continue
        _assert_budget(endpoint_records)
        time.sleep(sec_sleep_seconds)
        endpoint_records.append(
            sample_validation.fetch_and_store(
                client,
                url=sample_validation.sec_url("submissions", cik10),
                provider_id="sec_edgar",
                endpoint_family="submissions",
                symbol=symbol,
                raw_root=raw_root,
                headers={
                    "User-Agent": sec_user_agent_env.value,
                    "Host": "data.sec.gov",
                },
            )
        )

    if len(endpoint_records) != MAX_TOTAL_ENDPOINT_CALLS:
        raise RuntimeError(f"batch5 probe must perform exactly 10 calls, got {len(endpoint_records)}")

    summary = build_summary(
        generated_at=generated_at,
        env_summary=env_summary,
        endpoint_records=endpoint_records,
        cik_by_symbol=cik_by_symbol,
        dry_run_env=False,
        authorization_confirmed=confirm_user_authorization,
    )
    if not summary["endpoint_call_budget"]["within_budget"]:
        raise RuntimeError("endpoint call budget check failed after execution")
    # schema-validate + secret-scan BEFORE write (R4: no write-then-validate, no schema-invalid/secret residue)
    _write_summary_validated(summary, summary_path, [fmp_env.value, sec_user_agent_env.value])
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if getattr(args, "rebuild_from_existing_raw", False):
        summary = rebuild_summary_from_existing_raw(
            packet_path=args.packet_path,
            summary_path=args.summary_path,
            raw_root=args.raw_root,
            generated_at=args.generated_at,
            existing_summary_path=args.summary_path,
        )
    else:
        summary = run_probe(
            packet_path=args.packet_path,
            summary_path=args.summary_path,
            raw_root=args.raw_root,
            generated_at=args.generated_at,
            confirm_user_authorization=args.confirm_user_authorization,
            dry_run_env=args.dry_run_env,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
