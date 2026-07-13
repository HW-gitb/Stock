"""Private forward-universe lifecycle capture from already stored status-sourced candidates.

This runner never calls a provider.  It freezes a forward start from an existing,
Git-ignored candidate artifact and later compares that frozen universe to another
such artifact.  It records conservative manual-review blocks for delisting/ticker
ambiguity, halts, bankruptcy, OTC migration, missing current rows, and critical
status unknowns.  It never confirms a merger or ticker change and never converts
shares, values cash consideration, changes selection, or touches account files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if _PYTHON_LIBS.exists() and str(_PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(_PYTHON_LIBS))

from engine import us_short_status_source as status_source  # noqa: E402
from engine.us_short_eligibility_gate import _V1_EXCHANGE_WHITELIST, canonical_us_ticker  # noqa: E402
from runners import us_short_forward_universe_snapshot as forward_snapshot  # noqa: E402


STATE_DIR = ROOT / "state" / "us_short"
OBSERVATION_SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_lifecycle_observation.schema.json"
_DISQUALIFYING_FLAGS = ("delisted", "halted", "bankruptcy", "otc")
_EVENT_BY_FLAG = {
    "delisted": "inactive_or_ticker_change_unresolved",
    "halted": "halted",
    "bankruptcy": "bankruptcy",
    "otc": "otc_or_exchange_migration",
}


class ForwardLifecycleCaptureError(RuntimeError):
    """A private forward-lifecycle observation cannot be safely frozen or captured."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ForwardLifecycleCaptureError("private lifecycle input is missing or unreadable") from exc


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ForwardLifecycleCaptureError("private lifecycle input cannot be hashed") from exc


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ForwardLifecycleCaptureError("private lifecycle path escapes the repository") from exc


def _require_private_state_json(path: Path, *, must_exist: bool) -> Path:
    path = path.resolve()
    try:
        path.relative_to(STATE_DIR.resolve())
    except ValueError as exc:
        raise ForwardLifecycleCaptureError("lifecycle paths must stay under state/us_short/") from exc
    if path.suffix != ".json":
        raise ForwardLifecycleCaptureError("lifecycle paths must be JSON files")
    if must_exist and (not path.exists() or not path.is_file()):
        raise ForwardLifecycleCaptureError("required private lifecycle file is missing")
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", str(path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ForwardLifecycleCaptureError("cannot confirm private lifecycle path is Git-ignored") from exc
    if result.returncode != 0:
        raise ForwardLifecycleCaptureError("lifecycle paths must be confirmed Git-ignored")
    return path


def _strict_yyyymmdd(value: Any) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise ForwardLifecycleCaptureError("decision date must be ASCII YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ForwardLifecycleCaptureError("decision date must be a real calendar date") from exc
    return value


def _iso_from_yyyymmdd(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def _valid_observed_at(value: Any) -> str:
    if type(value) is not str or "T" not in value:
        raise ForwardLifecycleCaptureError("candidate observed_at must be timezone-aware ISO-8601")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ForwardLifecycleCaptureError("candidate observed_at must be timezone-aware ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ForwardLifecycleCaptureError("candidate observed_at must be timezone-aware ISO-8601")
    return value


def _row_from_candidate(row: Any, *, candidate_as_of: str) -> tuple[str, dict[str, Any]]:
    if not isinstance(row, dict):
        raise ForwardLifecycleCaptureError("candidate rows must be objects")
    ticker = canonical_us_ticker(row.get("ticker"))
    if ticker is None or row.get("ticker") != ticker:
        raise ForwardLifecycleCaptureError("candidate ticker must be canonical US ticker")
    if row.get("status_flags_sourced") is not True:
        raise ForwardLifecycleCaptureError("candidate rows must carry sourced status provenance")
    record = row.get("status_provenance")
    if not isinstance(record, dict) or record.get("ticker") != ticker or not status_source.validate_status_record(record):
        raise ForwardLifecycleCaptureError("candidate status provenance is invalid")
    if record.get("as_of") != candidate_as_of:
        raise ForwardLifecycleCaptureError("candidate status provenance as_of must match candidate decision date")
    row_flags, _ = status_source.status_flags_for_row(record, row_ticker=ticker)
    for flag in _DISQUALIFYING_FLAGS:
        expected = row_flags[flag] if flag in row_flags else None
        if row.get(flag) is not expected:
            raise ForwardLifecycleCaptureError("candidate status flags disagree with status provenance")
    return ticker, record


def _load_candidate(candidate_path: Path) -> tuple[dict[str, Any], str, dict[str, dict[str, Any]], str, str]:
    candidate_path = _require_private_state_json(candidate_path, must_exist=True)
    payload = _read_json(candidate_path)
    if not isinstance(payload, dict):
        raise ForwardLifecycleCaptureError("candidate artifact root must be an object")
    if payload.get("schema_name") != "us_short_universe_candidate_artifact" or payload.get("schema_version") != "1.1.0":
        raise ForwardLifecycleCaptureError("candidate artifact identity is unsupported")
    decision_date = _strict_yyyymmdd(payload.get("decision_date"))
    observed_at = _valid_observed_at(payload.get("generated_at"))
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("row_count") != len(rows):
        raise ForwardLifecycleCaptureError("candidate rows and row_count are invalid")
    by_ticker: dict[str, dict[str, Any]] = {}
    candidate_as_of = _iso_from_yyyymmdd(decision_date)
    for row in rows:
        ticker, record = _row_from_candidate(row, candidate_as_of=candidate_as_of)
        if ticker in by_ticker:
            raise ForwardLifecycleCaptureError("candidate rows contain duplicate canonical tickers")
        by_ticker[ticker] = {"row": row, "record": record}
    return payload, decision_date, by_ticker, observed_at, _sha256_file(candidate_path)


def _snapshot_output_path(forward_start_date: str) -> Path:
    return STATE_DIR / f"forward_universe_snapshot_{forward_start_date}.json"


def _observation_output_path(forward_start_date: str, decision_date: str) -> Path:
    return STATE_DIR / f"forward_lifecycle_observation_{forward_start_date}_{decision_date}.json"


def _validate_observation(observation: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ForwardLifecycleCaptureError("jsonschema is required to validate lifecycle observations") from exc
    schema = _read_json(OBSERVATION_SCHEMA_PATH)
    errors = sorted(Draft7Validator(schema).iter_errors(observation), key=lambda error: list(error.path))
    if errors:
        path = ".".join(str(item) for item in errors[0].path) or "<root>"
        raise ForwardLifecycleCaptureError(f"lifecycle observation failed schema validation at {path}")


def _write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ForwardLifecycleCaptureError("private lifecycle output cannot be written") from exc


def freeze_forward_snapshot(*, confirm_user_authorization: bool, candidate_path: Path) -> dict[str, Any]:
    """Freeze active listing membership from a local status-sourced candidate artifact only."""
    if not confirm_user_authorization:
        raise ForwardLifecycleCaptureError("forward snapshot freeze requires explicit user authorization")
    candidate_path = _require_private_state_json(candidate_path, must_exist=True)
    _, forward_start_date, by_ticker, _, _ = _load_candidate(candidate_path)
    output_path = _snapshot_output_path(forward_start_date)
    _require_private_state_json(output_path, must_exist=False)
    if output_path.exists():
        raise ForwardLifecycleCaptureError("forward snapshot already exists; refusing to overwrite the frozen start")

    active_rows: list[dict[str, Any]] = []
    for ticker, item in by_ticker.items():
        record = item["record"]
        flags = record["flags"]
        exchange = item["row"].get("exchange")
        if flags["delisted"]["value"] is False and flags["otc"]["value"] is False:
            if exchange not in _V1_EXCHANGE_WHITELIST:
                raise ForwardLifecycleCaptureError("active candidate exchange is outside the US-short whitelist")
            active_rows.append(
                {
                    "ticker": ticker,
                    "listing_status": "active",
                    "primary_exchange": exchange,
                    "status_as_of": _iso_from_yyyymmdd(forward_start_date),
                }
            )
    if not active_rows:
        raise ForwardLifecycleCaptureError("cannot freeze an empty active forward universe")
    snapshot = forward_snapshot.write_forward_universe_snapshot(
        forward_start_date=forward_start_date,
        provider_as_of=_iso_from_yyyymmdd(forward_start_date),
        provider_label="status_sourced_candidate_universe",
        source_refs=[{"role": "status_sourced_candidate_artifact", "path": _repo_relative(candidate_path)}],
        rows=active_rows,
        output_path=output_path,
    )
    return {
        "snapshot_path": _repo_relative(output_path),
        "forward_start_date": snapshot["forward_start_date"],
        "frozen_symbol_count": snapshot["row_count"],
    }


def _event(symbol: str, event_type: str, *, decision_date: str, observed_at: str, source_hash: str) -> dict[str, Any]:
    digest = hashlib.sha256(f"{symbol}|{event_type}|{decision_date}|{source_hash}".encode("utf-8")).hexdigest()
    return {
        "event_id": f"{symbol}-{event_type}-{decision_date}-{digest[:12]}",
        "symbol": symbol,
        "event_type": event_type,
        "decision_date": decision_date,
        "observed_at": observed_at,
        "manual_review_required": True,
        "new_entry_blocked": True,
        "automatic_conversion_or_cash_valuation_performed": False,
    }


def _build_observation(
    *,
    snapshot: dict[str, Any],
    snapshot_path: Path,
    snapshot_hash: str,
    decision_date: str,
    observed_at: str,
    candidate_path: Path,
    candidate_hash: str,
    candidate_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    frozen_symbols = snapshot["active_symbols"]
    events: list[dict[str, Any]] = []
    known_clear = 0
    missing = 0
    unknown_symbols = 0
    for symbol in frozen_symbols:
        item = candidate_by_ticker.get(symbol)
        if item is None:
            missing += 1
            events.append(_event(symbol, "missing_from_current_universe_requires_manual_review", decision_date=decision_date, observed_at=observed_at, source_hash=candidate_hash))
            continue
        flags = item["record"]["flags"]
        symbol_events = []
        for flag in _DISQUALIFYING_FLAGS:
            if flags[flag]["value"] is True:
                symbol_events.append(_EVENT_BY_FLAG[flag])
        if any(flags[flag]["value"] is None for flag in _DISQUALIFYING_FLAGS):
            unknown_symbols += 1
            symbol_events.append("critical_status_unknown_requires_manual_review")
        if not symbol_events:
            known_clear += 1
            continue
        events.extend(_event(symbol, event_type, decision_date=decision_date, observed_at=observed_at, source_hash=candidate_hash) for event_type in symbol_events)
    events.sort(key=lambda event: (event["symbol"], event["event_type"]))
    blocked_symbols = {event["symbol"] for event in events}
    observation = {
        "schema_name": "us_short_forward_lifecycle_observation",
        "schema_version": "1.0.0",
        "forward_start_date": snapshot["forward_start_date"],
        "decision_date": decision_date,
        "observed_at": observed_at,
        "snapshot_ref": {"path": _repo_relative(snapshot_path), "sha256": snapshot_hash},
        "candidate_ref": {"path": _repo_relative(candidate_path), "sha256": candidate_hash},
        "events": events,
        "coverage": {
            "frozen_symbol_count": len(frozen_symbols),
            "current_candidate_row_count": len(candidate_by_ticker),
            "matched_frozen_symbol_count": len(frozen_symbols) - missing,
            "missing_frozen_symbol_count": missing,
            "known_clear_symbol_count": known_clear,
            "blocked_symbol_count": len(blocked_symbols),
            "critical_status_unknown_symbol_count": unknown_symbols,
        },
        "retention_policy": {
            "forward_snapshot_symbols_deleted": False,
            "lifecycle_events_retained": True,
        },
        "boundary": {
            "network_access_performed": False,
            "provider_calls_performed": False,
            "raw_payload_capture_performed": False,
            "merger_or_ticker_change_semantics_confirmed": False,
            "automatic_corporate_action_processing_performed": False,
            "return_calculation_performed": False,
            "selection_or_ranking_changed": False,
            "datahub_consumption_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
        },
    }
    _validate_observation(observation)
    return observation


def capture_forward_lifecycle_observation(
    *,
    confirm_user_authorization: bool,
    snapshot_path: Path,
    candidate_path: Path,
) -> dict[str, int]:
    """Record private fail-closed lifecycle observations; never perform a provider call."""
    if not confirm_user_authorization:
        raise ForwardLifecycleCaptureError("forward lifecycle capture requires explicit user authorization")
    snapshot_path = _require_private_state_json(snapshot_path, must_exist=True)
    snapshot_payload = _read_json(snapshot_path)
    try:
        snapshot = forward_snapshot.validate_forward_universe_snapshot(snapshot_payload)
    except Exception as exc:
        raise ForwardLifecycleCaptureError("forward snapshot is invalid") from exc
    _, decision_date, candidate_by_ticker, observed_at, candidate_hash = _load_candidate(candidate_path)
    if decision_date < snapshot["forward_start_date"]:
        raise ForwardLifecycleCaptureError("lifecycle observation predates the frozen forward start")
    output_path = _observation_output_path(snapshot["forward_start_date"], decision_date)
    _require_private_state_json(output_path, must_exist=False)
    if output_path.exists():
        raise ForwardLifecycleCaptureError("lifecycle observation already exists; refusing to overwrite it")
    candidate_path = _require_private_state_json(candidate_path, must_exist=True)
    observation = _build_observation(
        snapshot=snapshot,
        snapshot_path=snapshot_path,
        snapshot_hash=_sha256_file(snapshot_path),
        decision_date=decision_date,
        observed_at=observed_at,
        candidate_path=candidate_path,
        candidate_hash=candidate_hash,
        candidate_by_ticker=candidate_by_ticker,
    )
    _write_json_atomic(observation, output_path)
    return {
        "event_count": len(observation["events"]),
        "blocked_symbol_count": observation["coverage"]["blocked_symbol_count"],
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze or observe private US-short forward lifecycle state")
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--candidate", type=Path, required=True)
    freeze.add_argument("--confirm-user-authorization", action="store_true")
    observe = subparsers.add_parser("observe")
    observe.add_argument("--snapshot", type=Path, required=True)
    observe.add_argument("--candidate", type=Path, required=True)
    observe.add_argument("--confirm-user-authorization", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "freeze":
            result = freeze_forward_snapshot(
                confirm_user_authorization=args.confirm_user_authorization,
                candidate_path=args.candidate,
            )
        else:
            result = capture_forward_lifecycle_observation(
                confirm_user_authorization=args.confirm_user_authorization,
                snapshot_path=args.snapshot,
                candidate_path=args.candidate,
            )
    except ForwardLifecycleCaptureError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
