from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_batch5_status_source_preflight as preflight  # noqa: E402


ACCESS_PACKET_PATH = ROOT / "docs" / "us_short_batch5_status_source_access_packet_20260630.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_status_source_probe_summary_20260630.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_status_source_probe_summary.schema.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_status_source_20260630")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"

AUTHORIZATION_REF = "user_chat_20260703_execute_if_needed_authorized"
EXPECTED_SYMBOLS = ["AAPL", "MSFT", "JPM"]
MAX_TOTAL_ENDPOINT_CALLS = 2
DEFAULT_TIMEOUT_SECONDS = 30

SEC_TICKER_REFERENCE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
NASDAQ_TRADE_HALTS_RSS_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"


@dataclass
class BytesFetchRecord:
    provider_id: str
    source_id: str
    endpoint_family: str
    raw_sample_ref: str
    ok: bool
    http_status: int | None
    error_type: str | None
    content_type: str | None
    payload: Any


class BytesHttpClient:
    def get_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> tuple[bytes, str | None, int | None, bool, str | None]:
        request = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return (
                    response.read(),
                    response.headers.get("Content-Type"),
                    int(response.status),
                    True,
                    None,
                )
        except urllib.error.HTTPError as exc:
            return exc.read(), exc.headers.get("Content-Type"), int(exc.code), False, "http_error"
        except urllib.error.URLError as exc:
            return str(exc.reason).encode("utf-8", errors="replace"), None, None, False, "url_error"
        except TimeoutError as exc:
            return str(exc).encode("utf-8", errors="replace"), None, None, False, "timeout"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the US-short batch5 status-source small-sample shape probe: exactly one ticker-reference "
            "bulk observation plus one exchange-halt bulk observation, raw samples only under gitignored "
            "provider_samples/, tracked no-secret/no-URL summary. No runner/DataHub/production consumption."
        )
    )
    parser.add_argument("--access-packet-path", type=Path, default=ACCESS_PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument(
        "--confirm-user-authorization",
        action="store_true",
        help="Required for live execution; confirms the user authorized this exact status-source shape probe.",
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


def raw_sample_ref(raw_root: Path, provider_id: str, source_id: str) -> Path:
    return raw_root / provider_id / "_market" / f"{source_id}.json"


def validate_raw_root(raw_root: Path) -> None:
    sample_validation.validate_raw_root(raw_root)
    resolved = raw_root.resolve()
    approved = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ValueError("raw samples must stay under provider_samples/us_short_batch5_status_source_20260630/") from exc


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


def _decode_bytes(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def _raw_payload_for_storage(body: bytes, content_type: str | None, source_id: str) -> Any:
    text = _decode_bytes(body)
    if source_id == "ticker_reference":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"non_json_response_bytes": len(body), "non_json_response_body_text": text}
    return {"response_text": text, "response_bytes": len(body), "content_type": content_type}


def _payload_for_summary(body: bytes, source_id: str) -> Any:
    text = _decode_bytes(body)
    if source_id == "ticker_reference":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"parse_error": "non_json_response", "response_bytes": len(body)}
    return text


def fetch_and_store(
    client: BytesHttpClient,
    *,
    url: str,
    provider_id: str,
    source_id: str,
    endpoint_family: str,
    raw_root: Path,
    headers: dict[str, str] | None = None,
) -> BytesFetchRecord:
    body, content_type, http_status, ok, error_type = client.get_bytes(url, headers=headers)
    raw_path = raw_sample_ref(raw_root, provider_id, source_id)
    write_json_atomic(
        {
            "provider_id": provider_id,
            "source_id": source_id,
            "endpoint_family": endpoint_family,
            "http_status": http_status,
            "ok": ok,
            "error_type": error_type,
            "content_type": content_type,
            "payload": _raw_payload_for_storage(body, content_type, source_id),
        },
        raw_path,
    )
    return BytesFetchRecord(
        provider_id=provider_id,
        source_id=source_id,
        endpoint_family=endpoint_family,
        raw_sample_ref=as_repo_relative(raw_path),
        ok=ok,
        http_status=http_status,
        error_type=error_type,
        content_type=content_type,
        payload=_payload_for_summary(body, source_id),
    )


def assert_endpoint_budget_available(records: list[BytesFetchRecord], *, next_call_count: int = 1) -> None:
    attempted = len(records) + next_call_count
    if attempted > MAX_TOTAL_ENDPOINT_CALLS:
        raise RuntimeError(
            f"status-source endpoint call budget would be exceeded before next fetch: "
            f"{attempted} > {MAX_TOTAL_ENDPOINT_CALLS}"
        )


def _field_index(fields: list[Any], name: str) -> int | None:
    try:
        return [str(field) for field in fields].index(name)
    except ValueError:
        return None


def summarize_ticker_reference_shape(payload: Any, symbols: list[str]) -> dict[str, Any]:
    shape = {
        "source_id": "ticker_reference",
        "feed_shape_valid": False,
        "sample_symbols_checked": symbols,
        "required_fields_present": {"ticker": False, "exchange": False, "cik": False},
        "observed_row_count": None,
        "sample_symbol_presence": {
            symbol: {"row_present": False, "primary_exchange_present": False, "cik_present": False}
            for symbol in symbols
        },
    }
    if not isinstance(payload, dict):
        return shape
    fields = payload.get("fields")
    rows = payload.get("data")
    if not isinstance(fields, list) or not isinstance(rows, list):
        return shape
    t_idx = _field_index(fields, "ticker")
    e_idx = _field_index(fields, "exchange")
    c_idx = _field_index(fields, "cik")
    shape["required_fields_present"] = {
        "ticker": t_idx is not None,
        "exchange": e_idx is not None,
        "cik": c_idx is not None,
    }
    shape["observed_row_count"] = len(rows)
    if t_idx is None or e_idx is None or c_idx is None:
        return shape
    wanted = set(symbols)
    for row in rows:
        if not isinstance(row, list) or t_idx >= len(row):
            continue
        ticker = str(row[t_idx]).upper()
        if ticker not in wanted:
            continue
        exchange = row[e_idx] if e_idx < len(row) else None
        cik = row[c_idx] if c_idx < len(row) else None
        shape["sample_symbol_presence"][ticker] = {
            "row_present": True,
            "primary_exchange_present": isinstance(exchange, str) and bool(exchange.strip()),
            "cik_present": isinstance(cik, int),
        }
    shape["feed_shape_valid"] = all(
        item["row_present"] and item["primary_exchange_present"] and item["cik_present"]
        for item in shape["sample_symbol_presence"].values()
    )
    return shape


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(item: ElementTree.Element, name: str) -> str:
    for child in item:
        if _local_name(child.tag).lower() == name:
            return "".join(child.itertext()).strip()
    return ""


def _symbol_from_halt_item(item: ElementTree.Element) -> str | None:
    text = " ".join([_child_text(item, "title"), _child_text(item, "description")])
    match = re.search(r"\bSymbol\s*:?\s*([A-Z][A-Z0-9.\-]{0,9})\b", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()
    title = _child_text(item, "title").strip().upper()
    if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", title):
        return title
    return None


def summarize_halt_feed_shape(payload: Any, symbols: list[str]) -> dict[str, Any]:
    shape = {
        "source_id": "exchange_halt_feed",
        "feed_shape_valid": False,
        "sample_symbols_checked": symbols,
        "rss_channel_present": False,
        "observed_item_count": None,
        "halted_symbol_count": None,
        "sample_symbols_in_halt_feed": [],
    }
    if not isinstance(payload, str):
        return shape
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return shape
    channel_present = any(_local_name(elem.tag).lower() == "channel" for elem in root.iter())
    items = [elem for elem in root.iter() if _local_name(elem.tag).lower() == "item"]
    halted = sorted({symbol for item in items if (symbol := _symbol_from_halt_item(item))})
    sample_hits = [symbol for symbol in symbols if symbol in set(halted)]
    shape.update(
        {
            "feed_shape_valid": channel_present,
            "rss_channel_present": channel_present,
            "observed_item_count": len(items),
            "halted_symbol_count": len(halted),
            "sample_symbols_in_halt_feed": sample_hits,
        }
    )
    return shape


def endpoint_payload_shape(record: BytesFetchRecord) -> dict[str, Any]:
    if record.source_id == "ticker_reference" and isinstance(record.payload, dict):
        rows = record.payload.get("data") if isinstance(record.payload.get("data"), list) else None
        return {
            "payload_type": "dict",
            "top_level_key_count": len(record.payload),
            "row_count": len(rows) if rows is not None else None,
        }
    if record.source_id == "exchange_halt_feed" and isinstance(record.payload, str):
        shape = summarize_halt_feed_shape(record.payload, EXPECTED_SYMBOLS)
        return {
            "payload_type": "xml_text",
            "top_level_key_count": None,
            "row_count": shape["observed_item_count"],
        }
    return {
        "payload_type": type(record.payload).__name__,
        "top_level_key_count": None,
        "row_count": None,
    }


def summarize_endpoint(record: BytesFetchRecord, sample_shape: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": record.source_id,
        "provider_id": record.provider_id,
        "endpoint_family": record.endpoint_family,
        "status": "ok" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith(RAW_SAMPLE_REL_ROOT.as_posix() + "/"),
        "payload_shape": endpoint_payload_shape(record),
        "shape_validation_status": "ok" if record.ok and sample_shape.get("feed_shape_valid") else "invalid_or_error",
    }


def _sample_shapes(records: list[BytesFetchRecord]) -> dict[str, dict[str, Any]]:
    by_source = {record.source_id: record for record in records}
    ticker_record = by_source.get("ticker_reference")
    halt_record = by_source.get("exchange_halt_feed")
    return {
        "ticker_reference": summarize_ticker_reference_shape(
            ticker_record.payload if ticker_record else None,
            EXPECTED_SYMBOLS,
        ),
        "exchange_halt_feed": summarize_halt_feed_shape(
            halt_record.payload if halt_record else None,
            EXPECTED_SYMBOLS,
        ),
    }


def aggregate_shape_metrics(endpoint_results: list[dict[str, Any]], shapes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ticker_shape = shapes["ticker_reference"]
    halt_shape = shapes["exchange_halt_feed"]
    return {
        "endpoint_success_count": sum(1 for item in endpoint_results if item["status"] == "ok"),
        "endpoint_error_count": sum(1 for item in endpoint_results if item["status"] == "error"),
        "shape_valid_source_count": sum(1 for item in shapes.values() if item.get("feed_shape_valid") is True),
        "sample_ticker_reference_rows_found": sum(
            1 for item in ticker_shape["sample_symbol_presence"].values() if item["row_present"]
        ),
        "sample_halt_feed_hit_count": len(halt_shape["sample_symbols_in_halt_feed"]),
    }


def build_summary(
    *,
    packet: dict[str, Any],
    generated_at: str,
    env_summary: dict[str, Any],
    pre_execution_checks: dict[str, Any],
    endpoint_records: list[BytesFetchRecord],
    dry_run_env: bool,
) -> dict[str, Any]:
    shapes = _sample_shapes(endpoint_records)
    endpoint_results = [
        summarize_endpoint(record, shapes[record.source_id])
        for record in endpoint_records
    ]
    endpoint_errors = sum(1 for result in endpoint_results if result["status"] == "error")
    if dry_run_env:
        probe_status = "dry_run_env_only"
        performed = False
    elif endpoint_errors:
        probe_status = "completed_with_endpoint_errors"
        performed = True
    else:
        probe_status = "completed"
        performed = True
    return {
        "schema_name": "us_short_batch5_status_source_probe_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "access_packet_ref": "docs/us_short_batch5_status_source_access_packet_20260630.json",
        "authorization_ref": AUTHORIZATION_REF,
        "schema_ref": "schemas/us_short_batch5_status_source_probe_summary.schema.json",
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "purpose": "small_sample_status_source_shape_probe",
            "probe_status": probe_status,
            "status_source_probe_performed": performed,
            "status_source_calls_performed": performed,
            "validation_only_parse_performed": performed,
            "raw_storage_performed": performed,
            "tracked_summary_written": performed,
            "status_records_written": False,
            "bankruptcy_8k_scan_performed": False,
            "full_market_application_performed": False,
            "security_master_built": False,
            "parser_into_runner_integration_performed": False,
            "candidate_artifact_schema_changed": False,
            "runner_consumption_allowed": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "provider_selection_allowed": False,
            "ship_gate_evidence_claimed": False,
            "production_ready_claimed": False,
            "broker_or_order_automation": False,
        },
        "pre_execution_checks": pre_execution_checks,
        "environment": env_summary,
        "sample_universe": {
            "symbols": packet["status_source_probe_boundary"]["sample_universe"]["symbols"],
            "max_symbols": packet["status_source_probe_boundary"]["sample_universe"]["max_symbols"],
            "universe_role": "bounded_shape_validation_sample_not_runner_consumable",
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "planned_total_endpoint_calls": 0 if dry_run_env else MAX_TOTAL_ENDPOINT_CALLS,
            "actual_total_endpoint_calls": len(endpoint_records),
            "ticker_reference_calls": sum(1 for item in endpoint_records if item.source_id == "ticker_reference"),
            "halt_feed_calls": sum(1 for item in endpoint_records if item.source_id == "exchange_halt_feed"),
            "bankruptcy_8k_calls": 0,
            "retry_count_allowed": 0,
            "retry_count_used": 0,
            "within_budget": len(endpoint_records) <= MAX_TOTAL_ENDPOINT_CALLS,
        },
        "exact_endpoint_confirmation": [
            {
                "source_id": "ticker_reference",
                "provider_id": "sec_edgar",
                "endpoint_family": "company_tickers_exchange_json",
                "request_url_in_summary": False,
            },
            {
                "source_id": "exchange_halt_feed",
                "provider_id": "nasdaq_trader",
                "endpoint_family": "trade_halts_rss",
                "request_url_in_summary": False,
            },
        ],
        "storage": {
            "raw_sample_storage_path": RAW_SAMPLE_REL_ROOT.as_posix() + "/",
            "raw_samples_gitignored": True,
            "tracked_summary_path": "docs/us_short_batch5_status_source_probe_summary_20260630.json",
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_request_urls": False,
            "secrets_in_summary": False,
        },
        "endpoint_results": endpoint_results,
        "sample_shape_results": shapes,
        "aggregate_shape_metrics": aggregate_shape_metrics(endpoint_results, shapes),
        "validation_decision": {
            "decision": (
                "bounded_status_source_shape_probe_completed_keep_sr_provider_001_open"
                if not endpoint_errors
                else "bounded_status_source_shape_probe_completed_with_errors_keep_sr_provider_001_open"
            ) if not dry_run_env else "dry_run_env_only_no_status_source_call",
            "sr_provider_001_closed": False,
            "runner_consumption_allowed": False,
            "rationale": (
                "This validates only the response-shape feasibility of two public bulk status-source families "
                "for AAPL/MSFT/JPM. It does not authorize runner consumption, DataHub, production storage, "
                "full-market application, bankruptcy screening, provider selection, alpha evidence, or ship-gate evidence."
            ),
        },
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_application_performed": False,
            "bankruptcy_8k_scanned": False,
            "status_records_runner_consumable": False,
            "candidate_artifact_written": False,
            "datahub_or_adapter_implemented": False,
            "production_runner_consumption_authorized": False,
            "ship_gate_evidence_claimed": False,
            "production_ready_claimed": False,
            "broker_or_order_automation": False,
        },
        "limitations": [
            "This is a two-feed shape probe for three active sample symbols, not a runner-consumable status universe.",
            "Ticker-reference and halt-feed observations are stored only as gitignored samples; tracked summary contains counts and shape flags only.",
            "Bankruptcy 8-K screening, full-market application, status-record production, DataHub, production storage, provider selection, and ship-gate evidence remain gated.",
        ],
        "next_steps": [
            "Have Claude review the runner, schema, tracked summary, raw-path boundary, no-secret/no-URL scan, endpoint budget, and SR-PROVIDER-001 wording before commit.",
            "Keep live runner wiring and any status-record consumption as a separate reviewed packet after this shape result is accepted.",
        ],
    }


def validate_summary_errors(summary: dict[str, Any]) -> list[str]:
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema is required for status-source probe summary validation") from exc
    schema = json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
    return [str(error.message) for error in jsonschema.Draft7Validator(schema).iter_errors(summary)]


def _assert_summary_safe_text(text: str, sensitive_values: list[str]) -> None:
    lower = text.lower()
    for fragment in ["https://", "http://", "sec.gov", "nasdaqtrader", "rss.aspx", "apikey="]:
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
        raise RuntimeError(f"status-source probe summary schema validation failed: {errors[:3]}")
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_summary_safe_text(text, sensitive_values)
    write_json_atomic(summary, path)
    _assert_summary_safe_text(path.read_text(encoding="utf-8"), sensitive_values)


def run_status_source_probe(
    *,
    access_packet_path: Path = ACCESS_PACKET_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    generated_at: str | None = None,
    client: BytesHttpClient | None = None,
    dry_run_env: bool = False,
    confirm_user_authorization: bool = False,
    confirm_post_preflight_execute: bool = False,
) -> dict[str, Any]:
    packet = preflight.load_and_validate_packet(access_packet_path)
    validate_raw_root(raw_root)
    if not preflight.provider_samples_gitignored():
        raise RuntimeError("provider_samples/ is not confirmed in .gitignore")
    require_live_execution_confirmations(
        dry_run_env=dry_run_env,
        confirm_user_authorization=confirm_user_authorization,
        confirm_post_preflight_execute=confirm_post_preflight_execute,
    )
    generated_at = generated_at or iso_now()
    sec_user_agent = sample_validation.read_required_env("SEC_USER_AGENT")
    env_summary = {
        "sec_fair_access_user_agent_present": True,
        "sec_fair_access_user_agent_source": sec_user_agent.source,
        "environment_values_logged": False,
        "secrets_logged": False,
        "status_source_credentials_required": False,
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
        "no_bankruptcy_8k_scan_guard_passed": True,
        "no_full_market_application_guard_passed": True,
        "no_datahub_consumption_guard_passed": True,
        "no_ship_gate_claim_guard_passed": True,
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

    client = client or BytesHttpClient()
    endpoint_records: list[BytesFetchRecord] = []

    assert_endpoint_budget_available(endpoint_records)
    endpoint_records.append(
        fetch_and_store(
            client,
            url=SEC_TICKER_REFERENCE_URL,
            provider_id="sec_edgar",
            source_id="ticker_reference",
            endpoint_family="company_tickers_exchange_json",
            raw_root=raw_root,
            headers={"User-Agent": sec_user_agent.value, "Host": "www.sec.gov"},
        )
    )

    assert_endpoint_budget_available(endpoint_records)
    endpoint_records.append(
        fetch_and_store(
            client,
            url=NASDAQ_TRADE_HALTS_RSS_URL,
            provider_id="nasdaq_trader",
            source_id="exchange_halt_feed",
            endpoint_family="trade_halts_rss",
            raw_root=raw_root,
            headers={"User-Agent": "StockSystem/0.1 us-short-status-source"},
        )
    )

    if len(endpoint_records) > MAX_TOTAL_ENDPOINT_CALLS:
        raise RuntimeError("status-source endpoint call budget exceeded")
    summary = build_summary(
        packet=packet,
        generated_at=generated_at,
        env_summary=env_summary,
        pre_execution_checks=pre_execution_checks,
        endpoint_records=endpoint_records,
        dry_run_env=False,
    )
    write_summary_validated(summary, summary_path, [sec_user_agent.value])
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_status_source_probe(
        access_packet_path=args.access_packet_path,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
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
                "endpoint_success_count": summary["aggregate_shape_metrics"]["endpoint_success_count"],
                "endpoint_error_count": summary["aggregate_shape_metrics"]["endpoint_error_count"],
                "shape_valid_source_count": summary["aggregate_shape_metrics"]["shape_valid_source_count"],
                "secrets_logged": summary["environment"]["secrets_logged"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
