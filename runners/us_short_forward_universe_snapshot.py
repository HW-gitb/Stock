from __future__ import annotations

import argparse
import hashlib
import json
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

from engine.us_short_eligibility_gate import (  # noqa: E402
    _V1_EXCHANGE_WHITELIST,
    canonical_us_ticker,
)


SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_universe_snapshot.schema.json"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
SCOPE_FALSE_FIELDS = (
    "network_access_performed",
    "provider_calls_performed",
    "raw_payload_capture_performed",
    "datahub_consumption_allowed",
    "production_storage_allowed",
    "ship_gate_evidence_claimed",
    "broker_or_order_automation_allowed",
    "a_share_crossing_allowed",
)
PROHIBITED_FALSE_FIELDS = (
    "provider_selection_complete",
    "live_normalized_evidence",
    "production_ready",
    "ship_gate_evidence",
    "datahub_consumed",
)
EXCHANGE_WHITELIST = frozenset(_V1_EXCHANGE_WHITELIST)


class ForwardUniverseSnapshotError(ValueError):
    """The local forward-universe snapshot cannot be built or written safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _display_path(path: Path) -> str:
    try:
        return _repo_rel(path)
    except ValueError:
        return str(path)


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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(raw)


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _valid_yyyymmdd(value: Any) -> bool:
    if not (type(value) is str and len(value) == 8 and value.isascii() and value.isdigit()):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _valid_yyyy_mm_dd(value: Any) -> bool:
    if not (type(value) is str and len(value) == 10 and value.isascii()):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _valid_generated_at(value: Any) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _resolve_repo_relative_path(value: Any, *, field: str) -> Path:
    if type(value) is not str or not value.strip():
        raise ForwardUniverseSnapshotError(f"{field} must be a non-empty repo-relative path")
    if "://" in value or "\\" in value or ":" in value:
        raise ForwardUniverseSnapshotError(f"{field} must not be a URL, Windows path, or drive path")
    rel = Path(value)
    if rel.is_absolute() or rel.anchor or any(part == ".." for part in rel.parts):
        raise ForwardUniverseSnapshotError(f"{field} must be repo-relative and non-traversing")
    resolved = (ROOT / rel).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ForwardUniverseSnapshotError(f"{field} escaped the repository root") from exc
    return resolved


def _validate_gitignored_state_json(path: Path, *, field: str, must_exist: bool) -> Path:
    try:
        path.resolve().parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise ForwardUniverseSnapshotError(f"{field} must stay under state/us_short/") from exc
    if path.suffix != ".json":
        raise ForwardUniverseSnapshotError(f"{field} must be a .json file")
    if must_exist:
        if not path.exists():
            raise ForwardUniverseSnapshotError(f"{field} does not exist: {_display_path(path)}")
        if not path.is_file():
            raise ForwardUniverseSnapshotError(f"{field} must be a file: {_display_path(path)}")
    if not _git_ignored(path):
        raise ForwardUniverseSnapshotError(f"{field} must be gitignored")
    return path


def _normalize_source_refs(source_refs: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not isinstance(source_refs, list) or not source_refs:
        raise ForwardUniverseSnapshotError("source_refs must be a non-empty list")
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for idx, ref in enumerate(source_refs):
        if not isinstance(ref, dict):
            raise ForwardUniverseSnapshotError(f"source_refs[{idx}] must be an object")
        role = ref.get("role")
        if type(role) is not str or not role.strip():
            raise ForwardUniverseSnapshotError(f"source_refs[{idx}].role must be a non-empty string")
        path = _resolve_repo_relative_path(ref.get("path"), field=f"source_refs[{idx}].path")
        _validate_gitignored_state_json(path, field=f"source_refs[{idx}].path", must_exist=True)
        rel = _repo_rel(path)
        key = (role.strip(), rel)
        if key in seen:
            raise ForwardUniverseSnapshotError(f"duplicate source_ref: {role!r} {rel!r}")
        seen.add(key)
        item = {"role": role.strip(), "path": rel, "sha256": _sha256_file(path)}
        out.append(item)
    return out


def _normalize_cik(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ForwardUniverseSnapshotError("cik must be string/integer, not bool")
    if isinstance(value, int):
        if value < 0 or value > 9999999999:
            raise ForwardUniverseSnapshotError("cik integer out of range")
        return f"{value:010d}"
    if type(value) is str and value.isascii() and value.isdigit() and len(value) <= 10:
        return value.zfill(10)
    raise ForwardUniverseSnapshotError(f"invalid cik: {value!r}")


def _normalize_active_row(row: Any, *, provider_as_of: str, idx: int) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ForwardUniverseSnapshotError(f"rows[{idx}] must be an object")
    ticker = canonical_us_ticker(row.get("ticker", row.get("symbol")))
    if ticker is None:
        raise ForwardUniverseSnapshotError(f"rows[{idx}] has invalid US ticker")
    if row.get("listing_status") != "active":
        raise ForwardUniverseSnapshotError(f"rows[{idx}] listing_status must be active")
    exchange = row.get("primary_exchange", row.get("exchange"))
    if type(exchange) is not str or exchange not in EXCHANGE_WHITELIST:
        raise ForwardUniverseSnapshotError(
            f"rows[{idx}] primary_exchange must be one of {sorted(EXCHANGE_WHITELIST)}"
        )
    row_as_of = row.get("status_as_of", row.get("provider_as_of", provider_as_of))
    if not _valid_yyyy_mm_dd(row_as_of):
        raise ForwardUniverseSnapshotError(f"rows[{idx}] provider/status as_of must be YYYY-MM-DD")
    normalized = {
        "ticker": ticker,
        "listing_status": "active",
        "primary_exchange": exchange,
        "provider_as_of": row_as_of,
    }
    cik = _normalize_cik(row.get("cik"))
    if cik is not None:
        normalized["cik"] = cik
    return normalized


def _snapshot_path_for(forward_start_date: str) -> Path:
    return STATE_US_SHORT_DIR / f"forward_universe_snapshot_{forward_start_date}.json"


def _validate_output_path(path: Path | str, *, forward_start_date: str) -> Path:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ForwardUniverseSnapshotError("output_path must stay under the repository root") from exc
    canonical = _snapshot_path_for(forward_start_date).resolve()
    if resolved != canonical:
        raise ForwardUniverseSnapshotError(
            f"output_path must be state/us_short/forward_universe_snapshot_{forward_start_date}.json"
        )
    return _validate_gitignored_state_json(resolved, field="output_path", must_exist=False)


def build_forward_universe_snapshot(
    *,
    forward_start_date: str,
    provider_as_of: str,
    provider_label: str,
    source_refs: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    if not _valid_yyyymmdd(forward_start_date):
        raise ForwardUniverseSnapshotError("forward_start_date must be ASCII YYYYMMDD")
    if not _valid_yyyy_mm_dd(provider_as_of):
        raise ForwardUniverseSnapshotError("provider_as_of must be ASCII YYYY-MM-DD")
    if type(provider_label) is not str or not provider_label.strip():
        raise ForwardUniverseSnapshotError("provider_label must be a non-empty string")
    generated_at = generated_at or iso_now()
    if not _valid_generated_at(generated_at):
        raise ForwardUniverseSnapshotError("generated_at must be timezone-aware ISO-8601")
    if not isinstance(rows, list):
        raise ForwardUniverseSnapshotError("rows must be a list")

    active_universe = [
        _normalize_active_row(row, provider_as_of=provider_as_of, idx=idx)
        for idx, row in enumerate(rows)
    ]
    active_universe.sort(key=lambda row: row["ticker"])
    symbols = [row["ticker"] for row in active_universe]
    if len(symbols) != len(set(symbols)):
        raise ForwardUniverseSnapshotError("rows contain duplicate canonical tickers")

    snapshot = {
        "schema_name": "us_short_forward_universe_snapshot",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "forward_start_date": forward_start_date,
        "provider_as_of": provider_as_of,
        "provider_label": provider_label.strip(),
        "source_refs": _normalize_source_refs(source_refs),
        "scope": {
            "market": "US",
            "lane": "us_short",
            "artifact_status": "forward_universe_snapshot_frozen_offline",
            "network_access_performed": False,
            "provider_calls_performed": False,
            "raw_payload_capture_performed": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "row_count": len(active_universe),
        "active_symbols": symbols,
        "active_universe": active_universe,
        "hashes": {
            "algorithm": "sha256",
            "active_symbols_sha256": _sha256_json(symbols),
            "active_universe_rows_sha256": _sha256_json(active_universe),
        },
        "retention_policy": {
            "delist_events_retained": True,
            "halt_events_retained": True,
            "merger_events_retained": True,
            "bankruptcy_events_retained": True,
            "no_trade_events_retained": True,
            "post_forward_start_deletion_allowed": False,
        },
        "prohibited_claims": {
            "provider_selection_complete": False,
            "live_normalized_evidence": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "datahub_consumed": False,
        },
    }
    validate_forward_universe_snapshot(snapshot)
    return snapshot


def validate_forward_universe_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise ForwardUniverseSnapshotError("jsonschema is required for forward-universe snapshot validation") from exc
    schema = _read_json(SCHEMA_PATH)
    errors = sorted(Draft7Validator(schema).iter_errors(snapshot), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise ForwardUniverseSnapshotError(f"snapshot schema rejected {len(errors)} field(s): {joined}")

    active_universe = snapshot["active_universe"]
    symbols = [row["ticker"] for row in active_universe]
    if snapshot["row_count"] != len(active_universe):
        raise ForwardUniverseSnapshotError("row_count must equal active_universe length")
    if symbols != sorted(symbols) or len(symbols) != len(set(symbols)):
        raise ForwardUniverseSnapshotError("active_universe must be sorted by unique ticker")
    if snapshot["active_symbols"] != symbols:
        raise ForwardUniverseSnapshotError("active_symbols must equal active_universe tickers")
    hashes = snapshot["hashes"]
    if hashes["active_symbols_sha256"] != _sha256_json(symbols):
        raise ForwardUniverseSnapshotError("active_symbols_sha256 does not match active_symbols")
    if hashes["active_universe_rows_sha256"] != _sha256_json(active_universe):
        raise ForwardUniverseSnapshotError("active_universe_rows_sha256 does not match active_universe")
    for field in SCOPE_FALSE_FIELDS:
        if snapshot["scope"][field] is not False:
            raise ForwardUniverseSnapshotError(f"scope.{field} must be false")
    for field in PROHIBITED_FALSE_FIELDS:
        if snapshot["prohibited_claims"][field] is not False:
            raise ForwardUniverseSnapshotError(f"prohibited_claims.{field} must be false")
    return snapshot


def write_forward_universe_snapshot(
    *,
    forward_start_date: str,
    provider_as_of: str,
    provider_label: str,
    source_refs: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    output_path: Path | str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    output = _validate_output_path(output_path or _snapshot_path_for(forward_start_date),
                                   forward_start_date=forward_start_date)
    snapshot = build_forward_universe_snapshot(
        forward_start_date=forward_start_date,
        provider_as_of=provider_as_of,
        provider_label=provider_label,
        source_refs=source_refs,
        rows=rows,
        generated_at=generated_at,
    )
    _write_json_atomic(snapshot, output)
    return snapshot


def _resolve_input_path(path: Path | str) -> Path:
    resolved = _resolve_repo_relative_path(str(path), field="input").resolve()
    return _validate_gitignored_state_json(resolved, field="input", must_exist=True)


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("rows", "active_universe", "candidate_universe"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return rows
    raise ForwardUniverseSnapshotError("input JSON must be a list or object with rows/active_universe")


def run_from_local_input(
    *,
    input_path: Path | str,
    forward_start_date: str,
    provider_as_of: str,
    provider_label: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    input_file = _resolve_input_path(input_path)
    rows = _extract_rows(_read_json(input_file))
    snapshot = write_forward_universe_snapshot(
        forward_start_date=forward_start_date,
        provider_as_of=provider_as_of,
        provider_label=provider_label,
        source_refs=[{"role": "active_listing_input", "path": _repo_rel(input_file)}],
        rows=rows,
        generated_at=generated_at,
    )
    return {
        "schema_name": "us_short_forward_universe_snapshot_run_summary",
        "schema_version": "1.0.0",
        "generated_at": snapshot["generated_at"],
        "snapshot_path": _repo_rel(_snapshot_path_for(forward_start_date)),
        "row_count": snapshot["row_count"],
        "hashes": snapshot["hashes"],
        "scope": snapshot["scope"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze a US-short forward active-universe snapshot from a local gitignored JSON input."
    )
    parser.add_argument("--input", required=True, help="gitignored state/us_short/*.json local active-listing input")
    parser.add_argument("--forward-start-date", required=True, help="forward start date as YYYYMMDD")
    parser.add_argument("--provider-as-of", required=True, help="provider/listing status as-of date as YYYY-MM-DD")
    parser.add_argument("--provider-label", required=True, help="label for the reviewed local input source")
    parser.add_argument("--generated-at", default=None, help="timezone-aware ISO-8601 generation time")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_from_local_input(
            input_path=args.input,
            forward_start_date=args.forward_start_date,
            provider_as_of=args.provider_as_of,
            provider_label=args.provider_label,
            generated_at=args.generated_at,
        )
    except ForwardUniverseSnapshotError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
