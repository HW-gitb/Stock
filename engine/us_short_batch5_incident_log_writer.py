from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))

RECORD_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_incident_log_record.schema.json"
STORAGE_CONTRACT_PATH = ROOT / "docs" / "us_short_batch5_incident_log_storage_contract_20260625.json"
PRIVATE_INCIDENT_ROOT = ROOT / "state" / "us_short" / "runs_private" / "provider_incidents"

FORBIDDEN_FIELD_NAMES = {
    "request_url",
    "url",
    "payload",
    "raw_payload",
    "provider_response_body",
    "api_key",
    "apikey",
    "authorization",
    "headers",
}
FORBIDDEN_VALUE_FRAGMENTS = [
    "http://",
    "https://",
    "apikey=",
    "api_key=",
    "financialmodelingprep.com",
    "data.sec.gov",
    "www.sec.gov",
    "bearer ",
    "fmp_api_key",
    "sec_user_agent",
    "\"payload\"",
    "\"raw_payload\"",
    "\"request_url\"",
    "\"provider_response_body\"",
]


class IncidentLogWriterError(Exception):
    """Incident record or private write destination violates the batch5 offline boundary."""


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _git_check_ignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _validate_private_incident_root(path: Path) -> None:
    root = path.resolve()
    allowed_root = PRIVATE_INCIDENT_ROOT.resolve()
    try:
        root.relative_to(allowed_root)
    except ValueError as exc:
        raise IncidentLogWriterError(
            "incident_root must stay under the US-short batch5 private incident root"
        ) from exc
    probe_path = root / "20260625" / "incident_log.jsonl"
    if not _git_check_ignored(probe_path):
        raise IncidentLogWriterError("incident_root must be gitignored before any private write")


def _validate_decision_date(decision_date: str) -> None:
    if not (isinstance(decision_date, str) and len(decision_date) == 8 and decision_date.isdigit()):
        raise IncidentLogWriterError("decision_date must be YYYYMMDD")


def _scan_for_forbidden_content(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lower_key = str(key).lower()
            if lower_key in FORBIDDEN_FIELD_NAMES:
                raise IncidentLogWriterError(f"forbidden incident record field: {path}.{key}")
            _scan_for_forbidden_content(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _scan_for_forbidden_content(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        lower_value = value.lower()
        for fragment in FORBIDDEN_VALUE_FRAGMENTS:
            if fragment in lower_value:
                raise IncidentLogWriterError(f"forbidden incident record value at {path}: {fragment}")


def _load_incident_mappings() -> dict[str, dict[str, Any]]:
    contract = _read_json(STORAGE_CONTRACT_PATH)
    return {row["incident_type"]: row for row in contract["incident_type_mappings"]}


def _validate_schema(record: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise IncidentLogWriterError("jsonschema is required to validate incident records") from exc
    schema = _read_json(RECORD_SCHEMA_PATH)
    errors = sorted(Draft7Validator(schema).iter_errors(record), key=lambda err: list(err.path))
    if errors:
        messages = "; ".join(error.message for error in errors)
        raise IncidentLogWriterError(f"incident record schema validation failed: {messages}")


def _validate_mapping_traceback(record: dict[str, Any]) -> None:
    mappings = _load_incident_mappings()
    incident_type = record["incident_type"]
    mapping = mappings.get(incident_type)
    if mapping is None:
        raise IncidentLogWriterError(f"incident_type not in storage contract: {incident_type}")
    if record["severity"] != mapping["default_severity"]:
        raise IncidentLogWriterError(
            "severity must match storage-contract default for incident_type "
            f"{incident_type}: {mapping['default_severity']}"
        )
    if record["immediate_action"] not in mapping["required_actions"]:
        raise IncidentLogWriterError(
            "immediate_action must be one of storage-contract required_actions for "
            f"{incident_type}: {mapping['required_actions']}"
        )
    for field in [
        "authorizes_status_polling",
        "authorizes_data_fetch",
        "authorizes_fallback_execution",
        "authorizes_adapter_or_datahub",
        "authorizes_runner_consumption",
        "authorizes_ship_gate_or_live_normalized_evidence",
    ]:
        if mapping.get(field) is not False:
            raise IncidentLogWriterError(f"storage-contract mapping drift: {incident_type}.{field} must be false")


def validate_incident_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise IncidentLogWriterError("incident record must be a dict")
    _scan_for_forbidden_content(record)
    _validate_schema(record)
    _validate_mapping_traceback(record)
    return record


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    seen_incident_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IncidentLogWriterError(f"invalid existing incident_log.jsonl line {line_number}") from exc
        try:
            validated = validate_incident_record(row)
        except IncidentLogWriterError as exc:
            raise IncidentLogWriterError(f"invalid existing incident_log.jsonl line {line_number}: {exc}") from exc
        incident_id = validated["incident_id"]
        if incident_id in seen_incident_ids:
            raise IncidentLogWriterError(
                f"duplicate incident_id in existing incident_log.jsonl line {line_number}: {incident_id}"
            )
        seen_incident_ids.add(incident_id)
        rows.append(validated)
    return rows


def _ensure_unique_incident_id(existing_records: list[dict[str, Any]], incident_id: str) -> None:
    if any(record.get("incident_id") == incident_id for record in existing_records):
        raise IncidentLogWriterError(f"duplicate incident_id in incident_log.jsonl: {incident_id}")


def _build_summary(*, decision_date: str, log_path: Path, summary_path: Path, records: list[dict[str, Any]]) -> dict:
    counts = Counter(record["incident_type"] for record in records)
    latest = records[-1] if records else {}
    return {
        "schema_name": "us_short_batch5_incident_log_summary",
        "schema_version": "1.0.0",
        "decision_date": decision_date,
        "record_schema_ref": "schemas/us_short_batch5_incident_log_record.schema.json",
        "storage_contract_ref": "docs/us_short_batch5_incident_log_storage_contract_20260625.json",
        "incident_count": len(records),
        "incident_type_counts": dict(sorted(counts.items())),
        "latest_incident_id": latest.get("incident_id"),
        "latest_review_status": latest.get("review_status"),
        "storage": {
            "private_log_path": _repo_relative(log_path),
            "private_summary_path": _repo_relative(summary_path),
            "private_paths_gitignored": True,
            "tracked_files_written": False,
            "raw_payloads_written_by_writer": False,
            "request_urls_in_summary": False,
            "secrets_in_summary": False,
            "raw_rows_in_summary": False,
        },
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "writer_mode": "offline_private_incident_log_writer",
            "provider_calls_performed_by_writer": False,
            "network_access_required_by_writer": False,
            "provider_status_page_polled_by_writer": False,
            "status_page_polled_by_writer": False,
            "fallback_execution_performed_by_writer": False,
            "datahub_consumption_performed_by_writer": False,
            "runner_consumption_performed_by_writer": False,
            "production_storage_performed_by_writer": False,
            "live_normalized_evidence_claimed_by_writer": False,
            "ship_gate_evidence_claimed_by_writer": False,
        },
        "prohibited_claims": {
            "live_normalized_evidence_claimed": False,
            "ship_gate_evidence_claimed": False,
            "production_readiness_claimed": False,
            "provider_selected": False,
            "datahub_ready": False,
            "fallback_executed": False,
        },
    }


def _write_json_atomic(payload: dict[str, Any], path: Path) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _scan_for_forbidden_content(payload)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8", newline="\n")
    tmp_path.replace(path)


def write_incident_record(
    record: dict[str, Any],
    *,
    decision_date: str,
    incident_root: Path | str | None = None,
) -> dict[str, Any]:
    """Append one validated incident record to the gitignored batch5 private incident log.

    This writer is intentionally offline/local. It validates an already observed incident record, writes private
    JSONL plus a private no-secret summary, and never fetches provider data, polls status pages, executes fallback,
    writes tracked files, writes raw payloads, or claims live_normalized / ship-gate evidence.
    """
    _validate_decision_date(decision_date)
    root = Path(incident_root) if incident_root is not None else PRIVATE_INCIDENT_ROOT
    _validate_private_incident_root(root)
    validated = validate_incident_record(record)

    target_dir = root / decision_date
    log_path = target_dir / "incident_log.jsonl"
    summary_path = target_dir / "incident_summary.json"
    for path in [log_path, summary_path]:
        if not _git_check_ignored(path):
            raise IncidentLogWriterError(f"private output path must be gitignored before write: {path}")

    existing_records = _load_jsonl(log_path)
    _ensure_unique_incident_id(existing_records, validated["incident_id"])

    target_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(validated, ensure_ascii=False, sort_keys=True)
    _scan_for_forbidden_content(line)
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.write("\n")

    records = [*existing_records, validated]
    summary = _build_summary(
        decision_date=decision_date,
        log_path=log_path,
        summary_path=summary_path,
        records=records,
    )
    _write_json_atomic(summary, summary_path)
    return summary
