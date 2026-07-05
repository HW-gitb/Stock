from __future__ import annotations

import argparse
import json
import re
import subprocess
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

from engine.us_short_eligibility_gate import canonical_us_ticker  # noqa: E402
from engine.us_short_status_source import (  # noqa: E402
    StatusSourceError,
    build_bankruptcy_screen_from_sec_submissions,
)


SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_bankruptcy_8k_source_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_bankruptcy_8k_source_packet_summary.schema.json"
DEFAULT_PACKET_PATH = ROOT / "state" / "us_short" / "us_short_batch5_bankruptcy_8k_source_packet_20260705.json"
DEFAULT_SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_bankruptcy_8k_source_packet_summary_20260705.json"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
DOCS_DIR = ROOT / "docs"
SOURCE_PARSER_REF = "engine.us_short_status_source.build_bankruptcy_screen_from_sec_submissions"

SCOPE_FALSE_FIELDS = (
    "network_access_performed",
    "provider_calls_performed",
    "raw_payload_capture_performed",
    "full_market_scan_performed",
    "candidate_artifact_written",
    "status_records_written",
    "run_fetch_invoked",
    "datahub_consumption_allowed",
    "production_storage_allowed",
    "ship_gate_evidence_claimed",
    "broker_or_order_automation_allowed",
    "a_share_crossing_allowed",
)
PREFLIGHT_TRUE_FIELDS = (
    "local_files_only",
    "source_packet_must_be_gitignored",
    "output_screen_must_be_gitignored",
    "no_provider_fetch",
    "no_datahub_or_production",
    "tracked_summary_must_exclude_raw_payload",
)
PROHIBITED_FALSE_FIELDS = (
    "provider_selected",
    "full_market_scan_performed",
    "candidate_artifact_written",
    "status_records_runner_consumable",
    "datahub_consumed",
    "production_ready_claimed",
    "ship_gate_evidence_claimed",
    "broker_or_order_automation",
    "a_share_crossing_performed",
)
SUMMARY_FORBIDDEN_SUBSTRINGS = (
    "http://",
    "https://",
    "data.sec.gov",
    "apikey=",
    "api_key",
    "token=",
    "bearer ",
)
SUMMARY_FORBIDDEN_RAW_KEY_RE = re.compile(
    r'"(?:filings|recent|form|filingDate|accessionNumber|items)"\s*:',
    re.IGNORECASE,
)


class BankruptcySourcePacketError(ValueError):
    """The local bankruptcy 8-K source packet cannot be consumed safely."""


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


def _resolve_invocation_path(path: Path | str, *, field: str) -> Path:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise BankruptcySourcePacketError(f"{field} must stay under the repository root") from exc
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


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise BankruptcySourcePacketError(f"jsonschema is required for {label} validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise BankruptcySourcePacketError(f"{label} schema rejected {len(errors)} field(s): {joined}")


def validate_summary(summary: dict[str, Any]) -> None:
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="summary")


def _validate_source_packet_path(packet_path: Path) -> None:
    if not packet_path.exists():
        raise BankruptcySourcePacketError(f"source packet does not exist: {_display_path(packet_path)}")
    if not packet_path.is_file():
        raise BankruptcySourcePacketError(f"source packet must be a file: {_display_path(packet_path)}")
    try:
        packet_path.resolve().parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise BankruptcySourcePacketError("source packet must stay under state/us_short/") from exc
    if packet_path.suffix != ".json":
        raise BankruptcySourcePacketError("source packet must be a .json file")
    if not _git_ignored(packet_path):
        raise BankruptcySourcePacketError("source packet must be gitignored")


def _validate_repo_relative_text(value: Any, *, field: str) -> Path:
    if type(value) is not str or not value.strip():
        raise BankruptcySourcePacketError(f"{field} must be a non-empty repo-relative path")
    rel = Path(value)
    if rel.is_absolute() or rel.anchor or any(part == ".." for part in rel.parts):
        raise BankruptcySourcePacketError(f"{field} must be repo-relative and non-traversing")
    resolved = (ROOT / rel).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise BankruptcySourcePacketError(f"{field} escaped the repository root") from exc
    return resolved


def _validate_output_screen_path(value: Any) -> Path:
    path = _validate_repo_relative_text(value, field="paths.bankruptcy_screen_output_path")
    try:
        path.resolve().parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise BankruptcySourcePacketError("paths.bankruptcy_screen_output_path must stay under state/us_short/") from exc
    if path.suffix != ".json":
        raise BankruptcySourcePacketError("paths.bankruptcy_screen_output_path must be a .json file")
    if not _git_ignored(path):
        raise BankruptcySourcePacketError("paths.bankruptcy_screen_output_path must be gitignored")
    return path


def _validate_summary_path(summary_path: Path) -> None:
    if summary_path.suffix != ".json":
        raise BankruptcySourcePacketError("summary_path must be a .json file")
    try:
        summary_path.resolve().relative_to(ROOT.resolve())
    except ValueError as exc:
        raise BankruptcySourcePacketError("summary_path must stay under the repository root") from exc
    try:
        summary_path.resolve().parent.relative_to(DOCS_DIR.resolve())
    except ValueError as exc:
        raise BankruptcySourcePacketError("summary_path must stay under docs/ as a tracked summary") from exc
    if _git_ignored(summary_path):
        raise BankruptcySourcePacketError("summary_path must not be gitignored")


def _canonical_input_symbols(submissions_by_ticker: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in submissions_by_ticker:
        canonical = canonical_us_ticker(raw)
        if canonical is None:
            raise BankruptcySourcePacketError(f"invalid US ticker key in sec_submissions_by_ticker: {raw!r}")
        if canonical in seen:
            raise BankruptcySourcePacketError(f"duplicate canonical ticker key in sec_submissions_by_ticker: {canonical!r}")
        seen.add(canonical)
        out.append(canonical)
    return sorted(out)


def _load_and_validate_packet(packet_path: Path | str) -> tuple[dict[str, Any], Path, list[str]]:
    resolved_packet_path = _resolve_invocation_path(packet_path, field="packet_path")
    _validate_source_packet_path(resolved_packet_path)
    try:
        packet = _read_json(resolved_packet_path)
    except Exception as exc:
        raise BankruptcySourcePacketError(f"source packet JSON could not be read: {_display_path(resolved_packet_path)}") from exc
    _validate_schema(packet, SCHEMA_PATH, label="source packet")
    if type(packet) is not dict:
        raise BankruptcySourcePacketError("source packet root must be an object")
    scope = packet["scope"]
    for field in SCOPE_FALSE_FIELDS:
        if scope.get(field) is not False:
            raise BankruptcySourcePacketError(f"scope.{field} must be false")
    gates = packet["preflight_gates"]
    for field in PREFLIGHT_TRUE_FIELDS:
        if gates.get(field) is not True:
            raise BankruptcySourcePacketError(f"preflight_gates.{field} must be true")
    prohibited = packet["prohibited_claims"]
    for field in PROHIBITED_FALSE_FIELDS:
        if prohibited.get(field) is not False:
            raise BankruptcySourcePacketError(f"prohibited_claims.{field} must be false")
    output_path = _validate_output_screen_path(packet["paths"]["bankruptcy_screen_output_path"])
    input_symbols = _canonical_input_symbols(packet["sec_submissions_by_ticker"])
    return packet, output_path, input_symbols


def build_summary(
    *,
    packet_ref: str,
    screen_path: str,
    generated_at: str,
    status_as_of: str,
    source_observed_at: str,
    input_symbol_count: int,
    screen: dict[str, Any],
    tracked_summary_path: str | None = None,
    input_source: str = "reviewed_local_sec_submissions_source_packet",
    lookback_days: int = 90,
    input_symbols: list[str] | None = None,
) -> dict[str, Any]:
    by_ticker = screen.get("by_ticker") if isinstance(screen, dict) else {}
    if not isinstance(by_ticker, dict):
        raise BankruptcySourcePacketError("bankruptcy screen by_ticker must be a dict")
    positive_count = 0
    screened_no_filing_count = 0
    screen_symbols: list[str] = []
    for ticker, row in by_ticker.items():
        canonical = canonical_us_ticker(ticker)
        if canonical is None:
            raise BankruptcySourcePacketError(f"bankruptcy screen contains invalid ticker: {ticker!r}")
        screen_symbols.append(canonical)
        if not isinstance(row, dict):
            raise BankruptcySourcePacketError(f"bankruptcy screen row must be a dict for {ticker!r}")
        status = row.get("screen_status")
        if status == "bankrupt_8k_found":
            positive_count += 1
        elif status == "screened_no_filing":
            screened_no_filing_count += 1
        else:
            raise BankruptcySourcePacketError(f"unexpected bankruptcy screen_status in source summary: {status!r}")
    symbols = sorted(input_symbols or screen_symbols)
    summary_path = tracked_summary_path or DEFAULT_SUMMARY_PATH.relative_to(ROOT).as_posix()
    return {
        "schema_name": "us_short_batch5_bankruptcy_8k_source_packet_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_bankruptcy_8k_source_packet_summary.schema.json",
        "generated_at": generated_at,
        "source_packet_ref": packet_ref,
        "source_parser_ref": SOURCE_PARSER_REF,
        "status_as_of": status_as_of,
        "source_observed_at": source_observed_at,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "purpose": "local_sec_submissions_to_bankruptcy_8k_screen",
            "status": "bankruptcy_screen_written",
            "local_source_packet_consumed": True,
            "network_access_performed": False,
            "provider_calls_performed": False,
            "raw_payload_capture_performed": False,
            "bankruptcy_screen_written": True,
            "status_records_written": False,
            "run_fetch_invoked": False,
            "full_market_scan_performed": False,
            "candidate_artifact_written": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "source_contract": {
            "source_id": "sec_8k_item_103",
            "provider_id": "sec_edgar",
            "endpoint_family": "company_submissions_recent_filings",
            "input_source": input_source,
            "lookback_days": lookback_days,
        },
        "storage": {
            "source_packet_path": packet_ref,
            "source_packet_gitignored": True,
            "bankruptcy_screen_output_path": screen_path,
            "bankruptcy_screen_output_gitignored": True,
            "tracked_summary_path": summary_path,
            "tracked_summary_contains_raw_payload": False,
            "tracked_summary_contains_request_urls": False,
            "secrets_in_summary": False,
        },
        "source_packet": {
            "input_symbol_count": input_symbol_count,
            "input_symbols": symbols,
        },
        "aggregate_shape_metrics": {
            "input_symbol_count": input_symbol_count,
            "screen_symbol_count": len(by_ticker),
            "bankruptcy_8k_positive_count": positive_count,
            "screened_no_filing_count": screened_no_filing_count,
            "parser_error_count": 0,
        },
        "validation_decision": {
            "decision": "local_bankruptcy_8k_source_packet_screen_written_keep_sr_provider_001_open",
            "runner_consumption_form": "bankruptcy_screen_payload_for_build_live_status_records",
            "sr_provider_001_closed": False,
            "rationale": (
                "Local source-packet wiring exists; broader/full candidate-universe bankruptcy scan and provider "
                "gates remain open."
            ),
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
        "limitations": [
            (
                "This consumer summary covers only the local source-packet to bankruptcy-screen runner; upstream "
                "fetch evidence, when present, belongs in the producer summary."
            ),
            (
                "This consumer runner performed no SEC/FMP/Massive provider call, full-market scan, run_fetch "
                "invocation, DataHub, production, or ship-gate evidence claim."
            ),
        ],
    }


def _assert_summary_safe(summary: dict[str, Any]) -> None:
    text = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    lower = text.lower()
    for fragment in SUMMARY_FORBIDDEN_SUBSTRINGS:
        if fragment in lower:
            raise BankruptcySourcePacketError(f"tracked summary contains forbidden fragment: {fragment}")
    match = SUMMARY_FORBIDDEN_RAW_KEY_RE.search(text)
    if match:
        raise BankruptcySourcePacketError(f"tracked summary contains forbidden raw key: {match.group(0).rstrip(':')}")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_preflight(
    packet_path: Path | str = DEFAULT_PACKET_PATH,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    packet, output_path, input_symbols = _load_and_validate_packet(packet_path)
    return {
        "schema_name": "us_short_batch5_bankruptcy_8k_source_packet_preflight_result",
        "schema_version": "1.0.0",
        "generated_at": generated_at or iso_now(),
        "packet_ref": _repo_rel(_resolve_invocation_path(packet_path, field="packet_path")),
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "preflight_status": "offline_preflight_passed",
            "network_access_required": False,
            "provider_calls_performed": False,
            "bankruptcy_screen_written": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
        },
        "preflight_checks": {
            "packet_contract_validated": True,
            "source_packet_gitignored": True,
            "output_screen_path_gitignored": True,
            "no_provider_fetch": packet["preflight_gates"]["no_provider_fetch"],
            "no_datahub_or_production": packet["preflight_gates"]["no_datahub_or_production"],
        },
        "paths": {
            "bankruptcy_screen_output_path": _repo_rel(output_path),
            "input_symbol_count": len(input_symbols),
        },
    }


def run_packet(
    packet_path: Path | str = DEFAULT_PACKET_PATH,
    *,
    summary_path: Path | str = DEFAULT_SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    resolved_summary_path = _resolve_invocation_path(summary_path, field="summary_path")
    _validate_summary_path(resolved_summary_path)
    packet, output_path, input_symbols = _load_and_validate_packet(packet_path)
    packet_ref = _repo_rel(_resolve_invocation_path(packet_path, field="packet_path"))
    screen_rel = _repo_rel(output_path)
    generated_at = generated_at or iso_now()
    try:
        screen = build_bankruptcy_screen_from_sec_submissions(
            as_of=packet["decision_clock"]["status_as_of"],
            observed_at=packet["decision_clock"]["source_observed_at"],
            submissions_by_ticker=packet["sec_submissions_by_ticker"],
            lookback_days=packet["source_contract"]["lookback_days"],
        )
    except StatusSourceError as exc:
        raise BankruptcySourcePacketError(f"bankruptcy screen parser rejected source packet: {exc}") from exc

    summary = build_summary(
        packet_ref=packet_ref,
        screen_path=screen_rel,
        generated_at=generated_at,
        status_as_of=packet["decision_clock"]["status_as_of"],
        source_observed_at=packet["decision_clock"]["source_observed_at"],
        input_symbol_count=len(input_symbols),
        screen=screen,
        tracked_summary_path=_repo_rel(resolved_summary_path),
        input_source=packet["source_contract"]["input_source"],
        lookback_days=packet["source_contract"]["lookback_days"],
        input_symbols=input_symbols,
    )
    validate_summary(summary)
    _assert_summary_safe(summary)

    _write_json_atomic(output_path, screen)
    _write_json_atomic(resolved_summary_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline US-short Batch5 bankruptcy 8-K source-packet runner. "
            "Consumes a local SEC company-submissions source packet and writes a gitignored bankruptcy screen; "
            "it never fetches providers, invokes run_fetch, writes status_records, uses DataHub, or claims production evidence."
        )
    )
    parser.add_argument("--packet-path", type=Path, default=DEFAULT_PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.preflight_only:
        result = run_preflight(args.packet_path, generated_at=args.generated_at)
    else:
        result = run_packet(args.packet_path, summary_path=args.summary_path, generated_at=args.generated_at)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
