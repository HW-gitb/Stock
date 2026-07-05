from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
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

from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_batch5_bankruptcy_8k_source_packet as source_packet_runner  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


AUTHORIZATION_REF = "user_chat_20260705_us_short_bankruptcy_8k_source_packet_producer"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_bankruptcy_8k_source_packet_producer_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_bankruptcy_8k_source_packet_producer_summary_20260705.json"
CONSUMER_SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_bankruptcy_8k_source_packet_from_producer_summary_20260705.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_bankruptcy_8k_source_packet_producer_20260705")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
DOCS_DIR = ROOT / "docs"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_SOURCE_PACKET_PATH = STATE_US_SHORT_DIR / "us_short_batch5_bankruptcy_8k_source_packet_producer_20260705_packet.json"
DEFAULT_SCREEN_PATH = STATE_US_SHORT_DIR / "us_short_batch5_bankruptcy_8k_source_packet_producer_20260705_screen.json"

SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
ENDPOINT_TICKER_MAP = "company_tickers_exchange"
ENDPOINT_SUBMISSIONS = "company_submissions_recent_filings"
SOURCE_PACKET_INPUT_SOURCE = "provider_fetched_candidate_sec_submissions_source_packet"
MAX_SYMBOLS = 3
MAX_TOTAL_ENDPOINT_CALLS = 1 + MAX_SYMBOLS
LOOKBACK_DAYS = 90
SEC_SLEEP_SECONDS = sample_validation.SEC_FAIR_ACCESS_SLEEP_SECONDS


class Bankruptcy8kSourcePacketProducerError(ValueError):
    """The bounded SEC bankruptcy 8-K source-packet producer cannot run safely."""


@dataclass
class FetchRecord:
    provider_id: str
    endpoint_family: str
    symbol: str | None
    raw_sample_ref: str
    ok: bool
    http_status: int | None
    error_type: str | None
    payload: Any


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _display_path(path: Path) -> str:
    try:
        return _repo_rel(path)
    except ValueError:
        return str(path)


def _resolve_repo_path(path: Path | str, *, field: str) -> Path:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise Bankruptcy8kSourcePacketProducerError(f"{field} must stay under the repository root") from exc
    return resolved


def _git_ignored(path: Path) -> bool:
    rel = _repo_rel(path)
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", rel],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _validate_state_json_path(path: Path | str, *, field: str, must_exist: bool = False) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise Bankruptcy8kSourcePacketProducerError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise Bankruptcy8kSourcePacketProducerError(f"{field} must be a .json path")
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise Bankruptcy8kSourcePacketProducerError(f"{field} must be an existing file: {_display_path(resolved)}")
    if not _git_ignored(resolved):
        raise Bankruptcy8kSourcePacketProducerError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    if resolved.suffix != ".json":
        raise Bankruptcy8kSourcePacketProducerError(f"{field} must be a .json path")
    try:
        resolved.parent.relative_to(DOCS_DIR.resolve())
    except ValueError as exc:
        raise Bankruptcy8kSourcePacketProducerError(f"{field} must stay under docs/") from exc
    if _git_ignored(resolved):
        raise Bankruptcy8kSourcePacketProducerError(f"{field} must not be gitignored")
    return resolved


def _validate_raw_root(raw_root: Path | str) -> Path:
    resolved = _resolve_repo_path(raw_root, field="raw_root")
    approved = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise Bankruptcy8kSourcePacketProducerError(
            "raw_root must stay under provider_samples/us_short_batch5_bankruptcy_8k_source_packet_producer_20260705/"
        ) from exc
    try:
        sample_validation.validate_raw_root(resolved)
    except ValueError as exc:
        raise Bankruptcy8kSourcePacketProducerError(str(exc)) from exc
    if not _git_ignored(resolved):
        raise Bankruptcy8kSourcePacketProducerError("raw_root must be gitignored")
    return resolved


def _prepare_json_target(path: Path, *, field: str) -> None:
    if path.parent.exists() and not path.parent.is_dir():
        raise Bankruptcy8kSourcePacketProducerError(f"{field} parent must be a directory: {_display_path(path.parent)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_dir():
        raise Bankruptcy8kSourcePacketProducerError(f"{field} must be a file path: {_display_path(path)}")


def _write_json_atomic(payload: Any, path: Path, *, field: str) -> None:
    _prepare_json_target(path, field=field)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise Bankruptcy8kSourcePacketProducerError(f"{field} could not be written atomically") from exc


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise Bankruptcy8kSourcePacketProducerError("jsonschema is required for source-packet producer validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise Bankruptcy8kSourcePacketProducerError(f"{label} schema rejected {len(errors)} field(s): {joined}") from errors[0]


def _date8_to_ymd(value: str, *, field: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise Bankruptcy8kSourcePacketProducerError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise Bankruptcy8kSourcePacketProducerError(f"{field} must be a real calendar date") from exc


def _selected_symbols(raw_symbols: list[str] | tuple[str, ...] | None, artifact: dict[str, Any]) -> list[str]:
    if raw_symbols is None:
        raw_symbols = list(artifact["eligible_tickers"][:MAX_SYMBOLS])
    if type(raw_symbols) not in (list, tuple) or not raw_symbols or len(raw_symbols) > MAX_SYMBOLS:
        raise Bankruptcy8kSourcePacketProducerError("selected_symbols must be a 1-3 item list/tuple")
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_symbols:
        if type(raw) is not str:
            raise Bankruptcy8kSourcePacketProducerError("selected_symbols must contain exact strings")
        ticker = canonical_us_ticker(raw)
        if ticker is None:
            raise Bankruptcy8kSourcePacketProducerError("selected_symbols must be canonicalizable US tickers")
        if ticker in seen:
            raise Bankruptcy8kSourcePacketProducerError(f"duplicate selected symbol: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _candidate_context(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    selected_symbols: list[str] | tuple[str, ...] | None,
) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    try:
        universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=governance,
        )
    except Exception as exc:
        raise Bankruptcy8kSourcePacketProducerError(f"candidate artifact failed validation: {exc}") from exc
    selected = _selected_symbols(selected_symbols, artifact)
    rows_by_ticker = {row["ticker"]: row for row in artifact["rows"]}
    eligible = set(artifact["eligible_tickers"])
    missing = [ticker for ticker in selected if ticker not in rows_by_ticker]
    not_eligible = [ticker for ticker in selected if ticker not in eligible]
    if missing or not_eligible:
        raise Bankruptcy8kSourcePacketProducerError(
            f"selected_symbols must exist and be Pass1-eligible (missing {missing}, not_eligible {not_eligible})"
        )
    status_as_of = _date8_to_ymd(artifact["decision_date"], field="candidate.decision_date")
    return {
        "artifact": artifact,
        "selected_symbols": selected,
        "expected_decision_date": artifact["decision_date"],
        "status_as_of": status_as_of,
        "candidate_artifact_row_count": len(artifact["rows"]),
        "candidate_artifact_eligible_count": len(artifact["eligible_tickers"]),
    }


def _raw_ref_for(raw_root: Path, endpoint_family: str, symbol: str | None = None) -> Path:
    if endpoint_family == ENDPOINT_TICKER_MAP:
        return raw_root / "sec_edgar" / "company_tickers_exchange.json"
    assert symbol is not None
    return raw_root / "sec_edgar" / symbol / "company_submissions_recent_filings.json"


def _fetch_and_store(
    *,
    client: sample_validation.JsonHttpClient,
    url: str,
    headers: dict[str, str],
    raw_root: Path,
    endpoint_family: str,
    symbol: str | None = None,
) -> FetchRecord:
    payload, http_status, ok, error_type = client.get_json(url, headers=headers)
    raw_path = _raw_ref_for(raw_root, endpoint_family, symbol)
    _write_json_atomic(
        {
            "provider_id": "sec_edgar",
            "endpoint_family": endpoint_family,
            "symbol": symbol,
            "http_status": http_status,
            "ok": ok,
            "error_type": error_type,
            "payload": payload,
        },
        raw_path,
        field="raw_sample",
    )
    return FetchRecord(
        provider_id="sec_edgar",
        endpoint_family=endpoint_family,
        symbol=symbol,
        raw_sample_ref=_repo_rel(raw_path),
        ok=ok,
        http_status=http_status,
        error_type=error_type,
        payload=payload,
    )


def _submissions_url(cik: int) -> str:
    return f"{SEC_SUBMISSIONS_BASE_URL}/CIK{cik:010d}.json"


def _parse_sec_ticker_map(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        raise Bankruptcy8kSourcePacketProducerError("SEC ticker reference payload must be an object")
    fields = payload.get("fields")
    rows = payload.get("data")
    if not isinstance(fields, list) or not isinstance(rows, list):
        raise Bankruptcy8kSourcePacketProducerError("SEC ticker reference payload must contain fields[] and data[]")
    for field in ("ticker", "exchange", "cik"):
        if field not in fields:
            raise Bankruptcy8kSourcePacketProducerError(f"SEC ticker reference missing field {field!r}")
    t_idx = fields.index("ticker")
    e_idx = fields.index("exchange")
    c_idx = fields.index("cik")
    exchange_norm = {"Nasdaq": "NASDAQ", "NASDAQ": "NASDAQ", "NYSE": "NYSE"}
    out: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, list) or max(t_idx, e_idx, c_idx) >= len(row):
            continue
        ticker = canonical_us_ticker(row[t_idx])
        exchange = exchange_norm.get(str(row[e_idx]), "")
        cik = row[c_idx]
        if ticker is None or exchange not in {"NYSE", "NASDAQ"} or not isinstance(cik, int):
            continue
        out.setdefault(ticker, cik)
    return out


def _fetch_records(
    *,
    client: sample_validation.JsonHttpClient,
    selected_symbols: list[str],
    raw_root: Path,
    sec_user_agent: sample_validation.EnvValue,
    sec_sleep_seconds: float,
) -> tuple[list[FetchRecord], dict[str, int]]:
    records: list[FetchRecord] = []
    headers = {"User-Agent": sec_user_agent.value}
    ticker_ref = _fetch_and_store(
        client=client,
        url=SEC_TICKER_MAP_URL,
        headers={**headers, "Host": "www.sec.gov"},
        raw_root=raw_root,
        endpoint_family=ENDPOINT_TICKER_MAP,
    )
    records.append(ticker_ref)
    if not ticker_ref.ok:
        raise Bankruptcy8kSourcePacketProducerError("SEC ticker reference fetch failed")
    cik_by_symbol = _parse_sec_ticker_map(ticker_ref.payload)
    missing = [symbol for symbol in selected_symbols if symbol not in cik_by_symbol]
    if missing:
        raise Bankruptcy8kSourcePacketProducerError(f"SEC ticker reference missing CIK for selected symbols: {missing}")

    for symbol in selected_symbols:
        if len(records) + 1 > MAX_TOTAL_ENDPOINT_CALLS:
            raise Bankruptcy8kSourcePacketProducerError("SEC endpoint call budget would be exceeded")
        if len(records) > 1 and sec_sleep_seconds > 0:
            time.sleep(sec_sleep_seconds)
        record = _fetch_and_store(
            client=client,
            url=_submissions_url(cik_by_symbol[symbol]),
            headers={**headers, "Host": "data.sec.gov"},
            raw_root=raw_root,
            endpoint_family=ENDPOINT_SUBMISSIONS,
            symbol=symbol,
        )
        records.append(record)
        if not record.ok:
            raise Bankruptcy8kSourcePacketProducerError(f"SEC submissions fetch failed for {symbol}")
    return records, cik_by_symbol


def _submissions_by_symbol(records: list[FetchRecord], selected_symbols: list[str]) -> dict[str, Any]:
    by_symbol = {record.symbol: record for record in records if record.endpoint_family == ENDPOINT_SUBMISSIONS}
    missing = [symbol for symbol in selected_symbols if symbol not in by_symbol]
    if missing:
        raise Bankruptcy8kSourcePacketProducerError(f"missing SEC submissions records for {missing}")
    return {symbol: by_symbol[symbol].payload for symbol in selected_symbols}


def _build_source_packet(
    *,
    generated_at: str,
    observed_at: str,
    status_as_of: str,
    screen_path: Path,
    submissions_by_ticker: dict[str, Any],
) -> dict[str, Any]:
    packet = {
        "schema_name": "us_short_batch5_bankruptcy_8k_source_packet",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "source_packet_ref": SOURCE_PACKET_INPUT_SOURCE,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "purpose": "local_sec_submissions_to_bankruptcy_8k_screen",
            "packet_status": "local_source_packet_ready_for_bankruptcy_screen",
            "network_access_performed": False,
            "provider_calls_performed": False,
            "raw_payload_capture_performed": False,
            "full_market_scan_performed": False,
            "candidate_artifact_written": False,
            "status_records_written": False,
            "run_fetch_invoked": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "status_as_of": status_as_of,
            "source_observed_at": observed_at,
        },
        "source_contract": {
            "source_id": "sec_8k_item_103",
            "provider_id": "sec_edgar",
            "endpoint_family": ENDPOINT_SUBMISSIONS,
            "parser_ref": source_packet_runner.SOURCE_PARSER_REF,
            "input_source": SOURCE_PACKET_INPUT_SOURCE,
            "lookback_days": LOOKBACK_DAYS,
        },
        "paths": {
            "bankruptcy_screen_output_path": _repo_rel(screen_path),
        },
        "sec_submissions_by_ticker": submissions_by_ticker,
        "preflight_gates": {
            "local_files_only": True,
            "source_packet_must_be_gitignored": True,
            "output_screen_must_be_gitignored": True,
            "no_provider_fetch": True,
            "no_datahub_or_production": True,
            "tracked_summary_must_exclude_raw_payload": True,
        },
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_scan_performed": False,
            "candidate_artifact_written": False,
            "status_records_runner_consumable": False,
            "datahub_consumed": False,
            "production_ready_claimed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation": False,
            "a_share_crossing_performed": False,
        },
    }
    _validate_schema(packet, source_packet_runner.SCHEMA_PATH, label="bankruptcy 8-K source packet")
    return packet


def _payload_shape(record: FetchRecord) -> dict[str, Any]:
    payload = record.payload
    if isinstance(payload, dict):
        if record.endpoint_family == ENDPOINT_SUBMISSIONS:
            recent = ((payload.get("filings") or {}).get("recent") or {}) if isinstance(payload.get("filings"), dict) else {}
            forms = recent.get("form") if isinstance(recent, dict) else None
            return {"kind": "object_recent", "row_count": len(forms) if isinstance(forms, list) else None}
        rows = payload.get("data")
        return {"kind": "object", "row_count": len(rows) if isinstance(rows, list) else None}
    if isinstance(payload, list):
        return {"kind": "list", "row_count": len(payload)}
    if payload is None:
        return {"kind": "null", "row_count": None}
    return {"kind": "scalar", "row_count": None}


def _summarize_endpoint(record: FetchRecord) -> dict[str, Any]:
    return {
        "provider_id": record.provider_id,
        "endpoint_family": record.endpoint_family,
        "symbol": record.symbol,
        "status": "success" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith("provider_samples/"),
        "payload_shape": _payload_shape(record),
    }


def _screen_counts(consumer_summary: dict[str, Any]) -> dict[str, int | bool]:
    metrics = consumer_summary["aggregate_shape_metrics"]
    return {
        "bankruptcy_screen_written": True,
        "screen_symbol_count": metrics["screen_symbol_count"],
        "bankruptcy_8k_positive_count": metrics["bankruptcy_8k_positive_count"],
        "screened_no_filing_count": metrics["screened_no_filing_count"],
        "parser_error_count": metrics["parser_error_count"],
    }


def _build_summary(
    *,
    generated_at: str,
    observed_at: str,
    candidate_context: dict[str, Any],
    records: list[FetchRecord],
    raw_root: Path,
    source_packet_path: Path,
    screen_path: Path,
    summary_path: Path,
    consumer_summary_path: Path,
    sec_user_agent: sample_validation.EnvValue,
    consumer_summary: dict[str, Any],
) -> dict[str, Any]:
    selected_symbols = candidate_context["selected_symbols"]
    endpoint_errors = sum(1 for record in records if not record.ok)
    return {
        "schema_name": "us_short_batch5_bankruptcy_8k_source_packet_producer_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_bankruptcy_8k_source_packet_producer_summary.schema.json",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "bounded_candidate_bankruptcy_8k_sec_submissions_source_packet",
            "status": "source_packet_and_bankruptcy_screen_written",
            "network_access_performed": True,
            "provider_calls_performed": True,
            "raw_payload_storage_performed": True,
            "source_packet_written": True,
            "bankruptcy_screen_written_by_consumer": True,
            "consumer_summary_written": True,
            "run_fetch_invoked": False,
            "status_records_written": False,
            "full_market_scan_performed": False,
            "candidate_artifact_written": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": candidate_context["expected_decision_date"],
            "status_as_of": candidate_context["status_as_of"],
            "source_observed_at": observed_at,
        },
        "environment": {
            "sec_fair_access_user_agent_present": True,
            "sec_fair_access_user_agent_source": sec_user_agent.source,
            "environment_values_logged": False,
            "secrets_logged": False,
            "sec_credentials_required": False,
        },
        "candidate_scope": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "symbols": selected_symbols,
            "max_symbols": MAX_SYMBOLS,
            "candidate_artifact_row_count": candidate_context["candidate_artifact_row_count"],
            "candidate_artifact_eligible_count": candidate_context["candidate_artifact_eligible_count"],
            "full_market_scan_performed": False,
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "actual_total_endpoint_calls": len(records),
            "sec_ticker_reference_calls": 1,
            "sec_company_submissions_calls": len(selected_symbols),
            "endpoint_error_count": endpoint_errors,
            "retry_count_allowed": 0,
            "retry_count_used": 0,
            "within_budget": len(records) <= MAX_TOTAL_ENDPOINT_CALLS,
        },
        "endpoint_results": [_summarize_endpoint(record) for record in records],
        "storage": {
            "raw_payload_root": _repo_rel(raw_root),
            "raw_payload_root_gitignored": _git_ignored(raw_root),
            "source_packet_path": _repo_rel(source_packet_path),
            "source_packet_path_gitignored": _git_ignored(source_packet_path),
            "bankruptcy_screen_output_path": _repo_rel(screen_path),
            "bankruptcy_screen_output_gitignored": _git_ignored(screen_path),
            "producer_tracked_summary_path": _repo_rel(summary_path),
            "consumer_tracked_summary_path": _repo_rel(consumer_summary_path),
            "tracked_summaries_contain_raw_payload": False,
            "tracked_summaries_contain_request_urls": False,
            "tracked_summaries_contain_secrets": False,
        },
        "source_packet": {
            "schema_ref": "schemas/us_short_batch5_bankruptcy_8k_source_packet.schema.json",
            "input_symbol_count": len(selected_symbols),
            "input_symbols": selected_symbols,
            "source_contract_input_source": SOURCE_PACKET_INPUT_SOURCE,
        },
        "consumer_screen": _screen_counts(consumer_summary),
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_scan_performed": False,
            "status_records_written": False,
            "run_fetch_invoked": False,
            "candidate_artifact_written": False,
            "datahub_consumed": False,
            "production_ready_claimed": False,
            "ship_gate_evidence_claimed": False,
            "live_normalized_evidence_claimed": False,
            "broker_or_order_automation": False,
            "a_share_crossing_performed": False,
        },
        "limitations": [
            "This is a bounded selected-candidate SEC submissions source-packet producer, not a full-market bankruptcy scan.",
            "It writes a local source packet and uses the existing local bankruptcy screen consumer; it does not invoke run_fetch or write status_records.",
            "Raw provider payloads stay under gitignored provider_samples; tracked summaries exclude raw SEC arrays, request URLs, and environment values.",
            "No DataHub, production storage, provider selection, live-normalized evidence, ship-gate evidence, broker/order automation, or A-share crossing is claimed.",
        ],
    }


def _assert_summary_safe_text(text: str, sensitive_values: list[str]) -> None:
    lower = text.lower()
    for fragment in (
        "https://",
        "http://",
        "data.sec.gov",
        "www.sec.gov",
        "submissions/cik",
        "apikey=",
        "api_key",
        "token=",
        "bearer ",
    ):
        if fragment in lower:
            raise Bankruptcy8kSourcePacketProducerError(f"tracked summary contains forbidden fragment: {fragment}")
    raw_key_match = re.search(r'"(?:filings|recent|form|filingDate|accessionNumber|items)"\s*:', text, re.IGNORECASE)
    if raw_key_match:
        raise Bankruptcy8kSourcePacketProducerError(
            f"tracked summary contains forbidden raw key: {raw_key_match.group(0).rstrip(':')}"
        )
    for value in sensitive_values:
        if value and value in text:
            raise Bankruptcy8kSourcePacketProducerError("tracked summary contains a sensitive environment value")


def _write_summary_validated(summary: dict[str, Any], path: Path, sensitive_values: list[str]) -> None:
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="producer summary")
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_summary_safe_text(text, sensitive_values)
    _write_json_atomic(summary, path, field="producer_summary")


def run_preflight(
    *,
    candidate_artifact_path: Path | str = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    expected_decision_date: str = "20260706",
    selected_symbols: list[str] | tuple[str, ...] | None = None,
    output_source_packet_path: Path | str = DEFAULT_SOURCE_PACKET_PATH,
    output_screen_path: Path | str = DEFAULT_SCREEN_PATH,
    summary_path: Path | str = SUMMARY_PATH,
    consumer_summary_path: Path | str = CONSUMER_SUMMARY_PATH,
    raw_root: Path | str = RAW_SAMPLE_ROOT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    candidate_path = _validate_state_json_path(candidate_artifact_path, field="candidate_artifact_path", must_exist=True)
    source_packet_path = _validate_state_json_path(output_source_packet_path, field="output_source_packet_path")
    screen_path = _validate_state_json_path(output_screen_path, field="output_screen_path")
    summary_path = _validate_summary_path(summary_path, field="summary_path")
    consumer_summary_path = _validate_summary_path(consumer_summary_path, field="consumer_summary_path")
    raw_root = _validate_raw_root(raw_root)
    candidate_context = _candidate_context(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        selected_symbols=selected_symbols,
    )
    return {
        "schema_name": "us_short_batch5_bankruptcy_8k_source_packet_producer_preflight_result",
        "schema_version": "1.0.0",
        "generated_at": generated_at or iso_now(),
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "preflight_status": "offline_preflight_passed_authorization_required_for_fetch",
            "network_access_performed": False,
            "provider_calls_performed": False,
            "source_packet_written": False,
            "bankruptcy_screen_written": False,
            "run_fetch_invoked": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "ship_gate_evidence_claimed": False,
        },
        "candidate_scope": {
            "candidate_artifact_path": _repo_rel(candidate_path),
            "expected_decision_date": candidate_context["expected_decision_date"],
            "symbols": candidate_context["selected_symbols"],
            "max_symbols": MAX_SYMBOLS,
        },
        "paths": {
            "raw_root": _repo_rel(raw_root),
            "source_packet_path": _repo_rel(source_packet_path),
            "screen_path": _repo_rel(screen_path),
            "summary_path": _repo_rel(summary_path),
            "consumer_summary_path": _repo_rel(consumer_summary_path),
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "planned_total_endpoint_calls": 1 + len(candidate_context["selected_symbols"]),
            "retry_count_allowed": 0,
        },
    }


def run_source_packet_producer(
    *,
    candidate_artifact_path: Path | str = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    expected_decision_date: str = "20260706",
    selected_symbols: list[str] | tuple[str, ...] | None = None,
    output_source_packet_path: Path | str = DEFAULT_SOURCE_PACKET_PATH,
    output_screen_path: Path | str = DEFAULT_SCREEN_PATH,
    summary_path: Path | str = SUMMARY_PATH,
    consumer_summary_path: Path | str = CONSUMER_SUMMARY_PATH,
    raw_root: Path | str = RAW_SAMPLE_ROOT,
    client: sample_validation.JsonHttpClient | None = None,
    confirm_user_authorization: bool = False,
    generated_at: str | None = None,
    observed_at: str | None = None,
    sec_sleep_seconds: float = SEC_SLEEP_SECONDS,
) -> dict[str, Any]:
    candidate_path = _validate_state_json_path(candidate_artifact_path, field="candidate_artifact_path", must_exist=True)
    source_packet_path = _validate_state_json_path(output_source_packet_path, field="output_source_packet_path")
    screen_path = _validate_state_json_path(output_screen_path, field="output_screen_path")
    summary_path = _validate_summary_path(summary_path, field="summary_path")
    consumer_summary_path = _validate_summary_path(consumer_summary_path, field="consumer_summary_path")
    raw_root = _validate_raw_root(raw_root)
    candidate_context = _candidate_context(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        selected_symbols=selected_symbols,
    )
    if not confirm_user_authorization:
        raise Bankruptcy8kSourcePacketProducerError("live SEC source-packet producer requires confirm_user_authorization")
    generated_at = generated_at or iso_now()
    observed_at = observed_at or generated_at
    sec_user_agent = sample_validation.read_required_env("SEC_USER_AGENT")
    client = client or sample_validation.JsonHttpClient()

    records, _ = _fetch_records(
        client=client,
        selected_symbols=candidate_context["selected_symbols"],
        raw_root=raw_root,
        sec_user_agent=sec_user_agent,
        sec_sleep_seconds=sec_sleep_seconds,
    )
    submissions = _submissions_by_symbol(records, candidate_context["selected_symbols"])
    packet = _build_source_packet(
        generated_at=generated_at,
        observed_at=observed_at,
        status_as_of=candidate_context["status_as_of"],
        screen_path=screen_path,
        submissions_by_ticker=submissions,
    )
    _prepare_json_target(source_packet_path, field="source_packet")
    _prepare_json_target(screen_path, field="screen")
    _prepare_json_target(summary_path, field="producer_summary")
    _prepare_json_target(consumer_summary_path, field="consumer_summary")
    _write_json_atomic(packet, source_packet_path, field="source_packet")
    consumer_summary = source_packet_runner.run_packet(
        source_packet_path,
        summary_path=consumer_summary_path,
        generated_at=generated_at,
    )
    summary = _build_summary(
        generated_at=generated_at,
        observed_at=observed_at,
        candidate_context=candidate_context,
        records=records,
        raw_root=raw_root,
        source_packet_path=source_packet_path,
        screen_path=screen_path,
        summary_path=summary_path,
        consumer_summary_path=consumer_summary_path,
        sec_user_agent=sec_user_agent,
        consumer_summary=consumer_summary,
    )
    _write_summary_validated(summary, summary_path, [sec_user_agent.value])
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded US-short Batch5 bankruptcy 8-K SEC source-packet producer. "
            "Fetches SEC company submissions for up to three Pass1-eligible candidate symbols, writes a gitignored "
            "source packet, and invokes the existing local bankruptcy screen consumer. No run_fetch/status_records, "
            "DataHub, production, broker/order, A-share, or ship-gate evidence."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--expected-decision-date", default="20260706")
    parser.add_argument("--symbols", nargs="*", help="Optional 1-3 selected Pass1-eligible symbols; default first 3 eligible.")
    parser.add_argument("--output-source-packet-path", type=Path, default=DEFAULT_SOURCE_PACKET_PATH)
    parser.add_argument("--output-screen-path", type=Path, default=DEFAULT_SCREEN_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--consumer-summary-path", type=Path, default=CONSUMER_SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at")
    parser.add_argument("--observed-at")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--sec-sleep-seconds", type=float, default=SEC_SLEEP_SECONDS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    kwargs = {
        "candidate_artifact_path": args.candidate_artifact_path,
        "expected_decision_date": args.expected_decision_date,
        "selected_symbols": args.symbols,
        "output_source_packet_path": args.output_source_packet_path,
        "output_screen_path": args.output_screen_path,
        "summary_path": args.summary_path,
        "consumer_summary_path": args.consumer_summary_path,
        "raw_root": args.raw_root,
        "generated_at": args.generated_at,
    }
    if args.preflight_only:
        result = run_preflight(**kwargs)
    else:
        result = run_source_packet_producer(
            **kwargs,
            confirm_user_authorization=args.confirm_user_authorization,
            observed_at=args.observed_at,
            sec_sleep_seconds=args.sec_sleep_seconds,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
