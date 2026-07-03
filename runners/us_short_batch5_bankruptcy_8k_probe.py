from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_status_source import build_bankruptcy_screen_from_sec_submissions  # noqa: E402
from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_batch5_bankruptcy_8k_preflight as preflight  # noqa: E402


ACCESS_PACKET_PATH = ROOT / "docs" / "us_short_batch5_bankruptcy_8k_access_packet_20260703.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_bankruptcy_8k_probe_summary_20260703.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_bankruptcy_8k_probe_summary.schema.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_bankruptcy_8k_20260703")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"

AUTHORIZATION_REF = "user_chat_20260703_execute_after_claude_pass"
EXPECTED_SYMBOLS = ["AAPL", "MSFT", "JPM"]
EXPECTED_CIK_BY_SYMBOL = {"AAPL": 320193, "MSFT": 789019, "JPM": 19617}
MAX_TOTAL_ENDPOINT_CALLS = 3
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_STATUS_AS_OF = "2026-07-06"
SEC_DATA_BASE_URL = "https://data.sec.gov/submissions"


@dataclass
class FetchRecord:
    symbol: str
    cik: int
    source_id: str
    provider_id: str
    endpoint_family: str
    raw_sample_ref: str
    ok: bool
    http_status: int | None
    error_type: str | None
    payload: Any


class JsonHttpClient:
    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> tuple[Any, int | None, bool, str | None]:
        request = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return _parse_json_bytes(response.read()), int(response.status), True, None
        except urllib.error.HTTPError as exc:
            return _parse_json_bytes(exc.read(), preserve_non_json_body=True), int(exc.code), False, "http_error"
        except urllib.error.URLError as exc:
            return {"error": str(exc.reason)}, None, False, "url_error"
        except TimeoutError as exc:
            return {"error": str(exc)}, None, False, "timeout"


def _parse_json_bytes(body: bytes, *, preserve_non_json_body: bool = False) -> Any:
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        payload: dict[str, Any] = {"non_json_response_bytes": len(body)}
        if preserve_non_json_body:
            payload["non_json_response_body_text"] = body.decode("utf-8", errors="replace")
        return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the US-short batch5 bankruptcy 8-K small-sample SEC company-submissions shape probe: "
            "exactly AAPL/MSFT/JPM, max three SEC calls, zero retry, raw samples only under gitignored "
            "provider_samples/, tracked no-secret/no-URL summary. No runner/DataHub/production consumption."
        )
    )
    parser.add_argument("--access-packet-path", type=Path, default=ACCESS_PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--status-as-of", default=DEFAULT_STATUS_AS_OF)
    parser.add_argument("--source-observed-at", help="Optional tz-aware observed_at used for parser shape validation.")
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument(
        "--confirm-user-authorization",
        action="store_true",
        help="Required for live execution; confirms the user authorized this exact bankruptcy 8-K shape probe.",
    )
    parser.add_argument(
        "--confirm-post-preflight-execute",
        action="store_true",
        help="Required for live execution; confirms preflight passed and the user issued the execute command.",
    )
    parser.add_argument(
        "--dry-run-env",
        action="store_true",
        help="Validate packet, gitignore, and environment boundary without fetching feeds or writing summary.",
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


def as_repo_relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def cik10(cik: int) -> str:
    return f"{cik:010d}"


def submissions_url(cik: int) -> str:
    return f"{SEC_DATA_BASE_URL}/CIK{cik10(cik)}.json"


def raw_sample_ref(raw_root: Path, symbol: str) -> Path:
    return raw_root / "sec_edgar" / symbol / "company_submissions_recent_filings.json"


def validate_raw_root(raw_root: Path) -> None:
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_SAMPLE_REL_ROOT / "raw").resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError("raw samples must stay under provider_samples/us_short_batch5_bankruptcy_8k_20260703/raw/") from exc


def require_live_execution_confirmations(
    *,
    dry_run_env: bool,
    confirm_user_authorization: bool,
    confirm_post_preflight_execute: bool,
) -> None:
    if dry_run_env:
        return
    if not confirm_user_authorization:
        raise RuntimeError("live execution requires --confirm-user-authorization")
    if not confirm_post_preflight_execute:
        raise RuntimeError("live execution requires --confirm-post-preflight-execute")


def assert_endpoint_budget_available(records: list[FetchRecord], *, next_call_count: int = 1) -> None:
    attempted = len(records) + next_call_count
    if attempted > MAX_TOTAL_ENDPOINT_CALLS:
        raise RuntimeError(
            f"bankruptcy 8-K endpoint call budget would be exceeded before next fetch: "
            f"{attempted} > {MAX_TOTAL_ENDPOINT_CALLS}"
        )


def fetch_and_store(
    client: JsonHttpClient,
    *,
    symbol: str,
    cik: int,
    raw_root: Path,
    headers: dict[str, str],
) -> FetchRecord:
    payload, http_status, ok, error_type = client.get_json(submissions_url(cik), headers=headers)
    raw_path = raw_sample_ref(raw_root, symbol)
    write_json_atomic(
        {
            "provider_id": "sec_edgar",
            "source_id": "sec_8k_item_103",
            "endpoint_family": "company_submissions_recent_filings",
            "symbol": symbol,
            "cik": cik,
            "http_status": http_status,
            "ok": ok,
            "error_type": error_type,
            "payload": payload,
        },
        raw_path,
    )
    return FetchRecord(
        symbol=symbol,
        cik=cik,
        source_id="sec_8k_item_103",
        provider_id="sec_edgar",
        endpoint_family="company_submissions_recent_filings",
        raw_sample_ref=as_repo_relative(raw_path),
        ok=ok,
        http_status=http_status,
        error_type=error_type,
        payload=payload,
    )


def _recent_arrays(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    filings = payload.get("filings")
    if not isinstance(filings, dict):
        return {}
    recent = filings.get("recent")
    return recent if isinstance(recent, dict) else {}


def recent_field_presence(payload: Any) -> dict[str, bool]:
    recent = _recent_arrays(payload)
    return {field: isinstance(recent.get(field), list) for field in ["form", "filingDate", "accessionNumber", "items"]}


def recent_row_count(payload: Any) -> int | None:
    recent = _recent_arrays(payload)
    forms = recent.get("form")
    return len(forms) if isinstance(forms, list) else None


def recent_arrays_equal_length(payload: Any) -> bool | None:
    recent = _recent_arrays(payload)
    lengths = [len(recent.get(field)) for field in ["form", "filingDate", "accessionNumber", "items"] if isinstance(recent.get(field), list)]
    if len(lengths) != 4:
        return None
    return len(set(lengths)) == 1


def item_103_count(payload: Any) -> int:
    recent = _recent_arrays(payload)
    forms = recent.get("form")
    items = recent.get("items")
    if not isinstance(forms, list) or not isinstance(items, list):
        return 0
    count = 0
    for form, raw_items in zip(forms, items):
        if form not in {"8-K", "8-K/A"} or not isinstance(raw_items, str):
            continue
        tokens = [token.strip().lower() for token in raw_items.replace(";", ",").split(",")]
        if any(token == "1.03" or token == "item 1.03" for token in tokens):
            count += 1
    return count


def form_8k_count(payload: Any) -> int:
    forms = _recent_arrays(payload).get("form")
    if not isinstance(forms, list):
        return 0
    return sum(1 for form in forms if form in {"8-K", "8-K/A"})


def payload_shape(payload: Any) -> dict[str, Any]:
    return {
        "payload_type": type(payload).__name__,
        "top_level_key_count": len(payload) if isinstance(payload, dict) else None,
        "recent_row_count": recent_row_count(payload),
        "recent_arrays_equal_length": recent_arrays_equal_length(payload),
        "required_recent_fields_present": recent_field_presence(payload),
    }


def shape_valid(payload: Any) -> bool:
    presence = recent_field_presence(payload)
    return all(presence.values()) and recent_arrays_equal_length(payload) is True


def summarize_endpoint(record: FetchRecord) -> dict[str, Any]:
    return {
        "symbol": record.symbol,
        "cik": record.cik,
        "source_id": record.source_id,
        "provider_id": record.provider_id,
        "endpoint_family": record.endpoint_family,
        "status": "ok" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith(RAW_SAMPLE_REL_ROOT.as_posix() + "/raw/"),
        "payload_shape": payload_shape(record.payload),
        "shape_validation_status": "ok" if record.ok and shape_valid(record.payload) else "invalid_or_error",
    }


def summarize_symbol_shape(
    symbol: str,
    payload: Any | None,
    *,
    screen_result: dict[str, Any] | None,
    parser_error: str | None,
) -> dict[str, Any]:
    screen_row = ((screen_result or {}).get("by_ticker") or {}).get(symbol)
    parser_status = "ok" if parser_error is None and isinstance(screen_row, dict) else "error"
    screen_status = "parser_error"
    accession = None
    if isinstance(screen_row, dict):
        screen_status = str(screen_row.get("screen_status"))
        accession = screen_row.get("filing_accession") if isinstance(screen_row.get("filing_accession"), str) else None
    return {
        "submission_shape_valid": shape_valid(payload),
        "recent_fields_present": recent_field_presence(payload),
        "recent_array_lengths_equal": recent_arrays_equal_length(payload),
        "recent_row_count": recent_row_count(payload),
        "form_8k_count": form_8k_count(payload),
        "item_103_candidate_count": item_103_count(payload),
        "parser_status": parser_status,
        "bankruptcy_screen_status": screen_status,
        "filing_accession_if_found": accession,
    }


def build_parser_screen(
    records: list[FetchRecord],
    *,
    status_as_of: str,
    source_observed_at: str,
) -> tuple[dict[str, Any] | None, str | None]:
    submissions = {record.symbol: record.payload for record in records if record.ok}
    try:
        return (
            build_bankruptcy_screen_from_sec_submissions(
                as_of=status_as_of,
                observed_at=source_observed_at,
                submissions_by_ticker=submissions,
            ),
            None,
        )
    except Exception as exc:
        return None, exc.__class__.__name__


def aggregate_shape_metrics(endpoint_results: list[dict[str, Any]], by_symbol: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "endpoint_success_count": sum(1 for item in endpoint_results if item["status"] == "ok"),
        "endpoint_error_count": sum(1 for item in endpoint_results if item["status"] == "error"),
        "shape_valid_symbol_count": sum(1 for item in by_symbol.values() if item["submission_shape_valid"] is True),
        "parser_ok_symbol_count": sum(1 for item in by_symbol.values() if item["parser_status"] == "ok"),
        "bankruptcy_8k_positive_count": sum(
            1 for item in by_symbol.values() if item["bankruptcy_screen_status"] == "bankrupt_8k_found"
        ),
    }


def build_summary(
    *,
    packet: dict[str, Any],
    generated_at: str,
    source_observed_at: str,
    status_as_of: str,
    env_summary: dict[str, Any],
    pre_execution_checks: dict[str, Any],
    endpoint_records: list[FetchRecord],
    dry_run_env: bool,
) -> dict[str, Any]:
    if dry_run_env:
        return {
            "schema_name": "us_short_batch5_bankruptcy_8k_probe_summary",
            "schema_version": "1.0.0",
            "generated_at": generated_at,
            "scope": {
                "probe_status": "dry_run_env_only",
                "bankruptcy_8k_probe_performed": False,
            },
            "endpoint_call_budget": {"actual_total_endpoint_calls": 0},
        }

    screen_result, parser_error = build_parser_screen(
        endpoint_records,
        status_as_of=status_as_of,
        source_observed_at=source_observed_at,
    )
    payloads = {record.symbol: record.payload for record in endpoint_records}
    by_symbol = {
        symbol: summarize_symbol_shape(
            symbol,
            payloads.get(symbol),
            screen_result=screen_result,
            parser_error=parser_error,
        )
        for symbol in EXPECTED_SYMBOLS
    }
    endpoint_results = [summarize_endpoint(record) for record in endpoint_records]
    endpoint_errors = sum(1 for item in endpoint_results if item["status"] == "error")
    probe_status = "completed_with_endpoint_errors" if endpoint_errors else "completed"
    decision = (
        "bounded_bankruptcy_8k_shape_probe_completed_with_errors_keep_sr_provider_001_open"
        if endpoint_errors or parser_error
        else "bounded_bankruptcy_8k_shape_probe_completed_keep_sr_provider_001_open"
    )
    parser_shape_valid = parser_error is None and all(item["parser_status"] == "ok" for item in by_symbol.values())
    return {
        "schema_name": "us_short_batch5_bankruptcy_8k_probe_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "access_packet_ref": "docs/us_short_batch5_bankruptcy_8k_access_packet_20260703.json",
        "authorization_ref": AUTHORIZATION_REF,
        "schema_ref": "schemas/us_short_batch5_bankruptcy_8k_probe_summary.schema.json",
        "status_as_of": status_as_of,
        "source_observed_at": source_observed_at,
        "source_parser_ref": "engine.us_short_status_source.build_bankruptcy_screen_from_sec_submissions",
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "purpose": "small_sample_bankruptcy_8k_company_submissions_shape_probe",
            "probe_status": probe_status,
            "bankruptcy_8k_probe_performed": True,
            "status_source_calls_performed": True,
            "sec_company_submissions_calls_performed": True,
            "validation_only_parse_performed": True,
            "raw_storage_performed": True,
            "tracked_summary_written": True,
            "status_records_written": False,
            "run_fetch_bankruptcy_wiring_performed": False,
            "full_market_application_performed": False,
            "candidate_artifact_written": False,
            "candidate_artifact_schema_changed": False,
            "runner_consumption_allowed": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "provider_selection_allowed": False,
            "live_normalized_evidence_claimed": False,
            "ship_gate_evidence_claimed": False,
            "production_ready_claimed": False,
            "broker_or_order_automation": False,
        },
        "pre_execution_checks": {
            **pre_execution_checks,
            "parser_shape_validation_passed": parser_shape_valid,
        },
        "environment": env_summary,
        "sample_universe": {
            "symbols": packet["bankruptcy_8k_scan_boundary"]["sample_universe"]["symbols"],
            "cik_by_symbol": packet["bankruptcy_8k_scan_boundary"]["sample_universe"]["cik_by_symbol"],
            "max_symbols": packet["bankruptcy_8k_scan_boundary"]["sample_universe"]["max_symbols"],
            "universe_role": "bounded_shape_validation_sample_not_runner_consumable",
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "planned_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "actual_total_endpoint_calls": len(endpoint_records),
            "sec_company_submissions_calls": len(endpoint_records),
            "bankruptcy_8k_calls": len(endpoint_records),
            "retry_count_allowed": 0,
            "retry_count_used": 0,
            "within_budget": len(endpoint_records) <= MAX_TOTAL_ENDPOINT_CALLS,
        },
        "exact_endpoint_confirmation": [
            {
                "symbol": symbol,
                "cik": EXPECTED_CIK_BY_SYMBOL[symbol],
                "source_id": "sec_8k_item_103",
                "provider_id": "sec_edgar",
                "endpoint_family": "company_submissions_recent_filings",
                "request_url_in_summary": False,
            }
            for symbol in EXPECTED_SYMBOLS
        ],
        "storage": {
            "raw_sample_storage_path": RAW_SAMPLE_REL_ROOT.as_posix() + "/",
            "raw_samples_gitignored": True,
            "tracked_summary_path": "docs/us_short_batch5_bankruptcy_8k_probe_summary_20260703.json",
            "tracked_summary_contains_raw_payloads": False,
            "tracked_summary_contains_request_urls": False,
            "secrets_in_summary": False,
        },
        "endpoint_results": endpoint_results,
        "sample_shape_results": {"by_symbol": by_symbol},
        "aggregate_shape_metrics": aggregate_shape_metrics(endpoint_results, by_symbol),
        "validation_decision": {
            "decision": decision,
            "sr_provider_001_closed": False,
            "runner_consumption_allowed": False,
            "rationale": (
                "This validates only a bounded three-symbol SEC company-submissions response shape and parser "
                "compatibility for Item 1.03 screening. It does not authorize runner consumption, status_records, "
                "full-market bankruptcy screening, DataHub, production storage, provider selection, live_normalized "
                "evidence, or ship-gate evidence."
            ),
        },
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_application_performed": False,
            "bankruptcy_8k_full_universe_scanned": False,
            "status_records_runner_consumable": False,
            "candidate_artifact_written": False,
            "datahub_or_adapter_implemented": False,
            "production_runner_consumption_authorized": False,
            "live_normalized_evidence_claimed": False,
            "ship_gate_evidence_claimed": False,
            "production_ready_claimed": False,
            "broker_or_order_automation": False,
        },
        "limitations": [
            "This is a three-symbol SEC company-submissions shape probe, not a full-market or candidate-universe bankruptcy screen.",
            "A missing Item 1.03 observation is not proof that the universe is clean; bankruptcy remains positive-detection-only and best-effort.",
            "Raw provider payloads are stored only under gitignored provider_samples; tracked summary contains counts, shapes, accessions-if-positive, and boundary flags only.",
            "No run_fetch wiring, status_records, candidate artifact, DataHub, production storage, provider selection, live_normalized evidence, or ship-gate evidence is claimed.",
        ],
        "next_steps": [
            "Have Claude review the runner, schema, tracked summary, raw-path boundary, no-secret/no-URL scan, endpoint budget, parser shape result, and SR-PROVIDER-001 wording before commit.",
            "If accepted, use this as bounded shape evidence only; full/candidate-universe bankruptcy screening and run_fetch consumption require a separate reviewed packet.",
        ],
    }


def validate_summary_errors(summary: dict[str, Any]) -> list[str]:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required for bankruptcy 8-K probe summary validation") from exc
    schema = json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
    return [str(error.message) for error in jsonschema.Draft7Validator(schema).iter_errors(summary)]


def _assert_summary_safe_text(text: str, sensitive_values: list[str]) -> None:
    lower = text.lower()
    for fragment in ["https://", "http://", "data.sec.gov", "submissions/cik", "apikey="]:
        if fragment in lower:
            raise RuntimeError(f"tracked summary contains forbidden fragment: {fragment}")
    for fragment in ["SEC_USER_AGENT", "Authorization", "Bearer "]:
        if fragment in text:
            raise RuntimeError(f"tracked summary contains forbidden fragment: {fragment}")
    for value in sensitive_values:
        if value and value in text:
            raise RuntimeError("tracked summary contains a sensitive environment value")


def write_summary_validated(summary: dict[str, Any], path: Path, sensitive_values: list[str]) -> None:
    errors = validate_summary_errors(summary)
    if errors:
        raise RuntimeError(f"bankruptcy 8-K probe summary schema validation failed: {errors[:3]}")
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_summary_safe_text(text, sensitive_values)
    write_json_atomic(summary, path)
    _assert_summary_safe_text(path.read_text(encoding="utf-8"), sensitive_values)


def run_bankruptcy_8k_probe(
    *,
    access_packet_path: Path = ACCESS_PACKET_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    generated_at: str | None = None,
    source_observed_at: str | None = None,
    status_as_of: str = DEFAULT_STATUS_AS_OF,
    client: JsonHttpClient | None = None,
    dry_run_env: bool = False,
    confirm_user_authorization: bool = False,
    confirm_post_preflight_execute: bool = False,
) -> dict[str, Any]:
    packet = preflight.load_and_validate_packet(access_packet_path)
    preflight.run_preflight(packet_path=access_packet_path, generated_at=generated_at)
    validate_raw_root(raw_root)
    if not preflight.provider_samples_gitignored():
        raise RuntimeError("provider_samples/ is not confirmed in .gitignore")
    require_live_execution_confirmations(
        dry_run_env=dry_run_env,
        confirm_user_authorization=confirm_user_authorization,
        confirm_post_preflight_execute=confirm_post_preflight_execute,
    )
    generated_at = generated_at or iso_now()
    source_observed_at = source_observed_at or generated_at
    sec_user_agent = sample_validation.read_required_env("SEC_USER_AGENT")
    env_summary = {
        "sec_fair_access_user_agent_present": True,
        "sec_fair_access_user_agent_source": sec_user_agent.source,
        "environment_values_logged": False,
        "secrets_logged": False,
        "sec_credentials_required": False,
    }
    pre_execution_checks = {
        "access_packet_validated": True,
        "offline_preflight_reused": True,
        "user_authorization_confirmed": bool(confirm_user_authorization),
        "post_preflight_execute_confirmed": bool(confirm_post_preflight_execute),
        "provider_samples_gitignore_confirmed": True,
        "raw_root_under_approved_provider_samples": True,
        "environment_precheck_passed": True,
        "sec_fair_access_user_agent_present": True,
        "exact_endpoint_confirmation_passed": True,
        "budget_precheck_passed": True,
        "no_full_market_application_guard_passed": True,
        "no_run_fetch_wiring_guard_passed": True,
        "no_datahub_consumption_guard_passed": True,
        "no_ship_gate_claim_guard_passed": True,
    }
    if dry_run_env:
        return build_summary(
            packet=packet,
            generated_at=generated_at,
            source_observed_at=source_observed_at,
            status_as_of=status_as_of,
            env_summary=env_summary,
            pre_execution_checks=pre_execution_checks,
            endpoint_records=[],
            dry_run_env=True,
        )

    client = client or JsonHttpClient()
    endpoint_records: list[FetchRecord] = []
    headers = {"User-Agent": sec_user_agent.value, "Host": "data.sec.gov"}
    for idx, symbol in enumerate(EXPECTED_SYMBOLS):
        assert_endpoint_budget_available(endpoint_records)
        endpoint_records.append(
            fetch_and_store(
                client,
                symbol=symbol,
                cik=EXPECTED_CIK_BY_SYMBOL[symbol],
                raw_root=raw_root,
                headers=headers,
            )
        )
        if idx < len(EXPECTED_SYMBOLS) - 1:
            time.sleep(sample_validation.SEC_FAIR_ACCESS_SLEEP_SECONDS)

    if len(endpoint_records) != MAX_TOTAL_ENDPOINT_CALLS:
        raise RuntimeError("bankruptcy 8-K endpoint call budget was not consumed exactly as planned")
    summary = build_summary(
        packet=packet,
        generated_at=generated_at,
        source_observed_at=source_observed_at,
        status_as_of=status_as_of,
        env_summary=env_summary,
        pre_execution_checks=pre_execution_checks,
        endpoint_records=endpoint_records,
        dry_run_env=False,
    )
    write_summary_validated(summary, summary_path, [sec_user_agent.value])
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_bankruptcy_8k_probe(
        access_packet_path=args.access_packet_path,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        status_as_of=args.status_as_of,
        source_observed_at=args.source_observed_at,
        generated_at=args.generated_at,
        dry_run_env=args.dry_run_env,
        confirm_user_authorization=args.confirm_user_authorization,
        confirm_post_preflight_execute=args.confirm_post_preflight_execute,
    )
    print(
        json.dumps(
            {
                "summary_path": None if args.dry_run_env else str(args.summary_path),
                "summary_written": not args.dry_run_env,
                "probe_status": summary["scope"]["probe_status"],
                "actual_total_endpoint_calls": summary["endpoint_call_budget"]["actual_total_endpoint_calls"],
                "endpoint_success_count": summary.get("aggregate_shape_metrics", {}).get("endpoint_success_count", 0),
                "endpoint_error_count": summary.get("aggregate_shape_metrics", {}).get("endpoint_error_count", 0),
                "shape_valid_symbol_count": summary.get("aggregate_shape_metrics", {}).get("shape_valid_symbol_count", 0),
                "bankruptcy_8k_positive_count": summary.get("aggregate_shape_metrics", {}).get("bankruptcy_8k_positive_count", 0),
                "secrets_logged": summary.get("environment", {}).get("secrets_logged", False),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
