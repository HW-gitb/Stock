"""US-short 26-week market-diagnostic Knife 3 lifecycle persistence.

This module is the post-settlement seam for the diagnostic track.  The local
adapter builds one schema-shaped weekly record from an already-settled
model-paper week; this module then:

* derives and writes the v1.1 reminder from the persisted count;
* publishes the weekly record once, byte-immutably, under the private
  ``market_diagnostic_private`` root; and
* rebuilds the lifecycle register from every weekly record before accepting
  another week.

The register is deliberately separate from the existing §13 calibration
register.  It contains no ticker, holding, order, or account-value detail.
It never calls a provider, writes the model-paper account, advances a head,
changes selection/action/sizing/NAV, or qualifies for Ship gate.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import uuid
from typing import Any, Mapping

import jsonschema

from engine.us_short_market_diagnostic import (
    BOUNDARY,
    MarketDiagnosticError,
    validate_weekly_record,
    window_containing_week,
)
from engine.us_short_model_paper_portfolio import artifact_sha256, canonical_json_bytes
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = ROOT / "state" / "us_short" / "market_diagnostic_private"
REGISTER_FILENAME = "lifecycle_register.json"
WEEKLY_RECORD_FILENAME = "weekly_record.json"
REGISTER_SCHEMA_PATH = ROOT / "schemas" / "us_short_market_diagnostic_lifecycle_register.schema.json"
WEEKLY_RECORD_SCHEMA_PATH = ROOT / "schemas" / "us_short_market_diagnostic_weekly_record.schema.json"
REPORT_REMINDER_KEY = "us_short_market_diagnostic_v1_1"
REPORT_REMINDER_SECTION = 12

STORE_BOUNDARY = {
    **BOUNDARY,
    "provider_fetch": False,
    "account_write": False,
    "diagnostic_store_write": True,
    "private_store_only": True,
}

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


class MarketDiagnosticLifecycleError(RuntimeError):
    """Raised when a diagnostic weekly record or lifecycle register is unsafe to persist/use."""


def _load_schema(path: Path, key: str) -> dict[str, Any]:
    if key not in _SCHEMA_CACHE:
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            jsonschema.Draft7Validator.check_schema(schema)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, jsonschema.exceptions.SchemaError) as exc:
            raise MarketDiagnosticLifecycleError(f"cannot load diagnostic schema: {path}") from exc
        _SCHEMA_CACHE[key] = schema
    return _SCHEMA_CACHE[key]


def _schema_validate(value: Mapping[str, Any], *, schema_path: Path, key: str, label: str) -> None:
    errors = sorted(
        jsonschema.Draft7Validator(_load_schema(schema_path, key)).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise MarketDiagnosticLifecycleError(f"{label} schema violation at {location}: {error.message}")


def _private_root(root: str | Path) -> Path:
    path = Path(root)
    if not path.is_absolute():
        raise MarketDiagnosticLifecycleError("diagnostic private root must be absolute")
    path = path.resolve()
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise MarketDiagnosticLifecycleError(f"diagnostic private root is not private: {path}") from exc
    return path


def _private_path(root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path or Path(relative_path).is_absolute():
        raise MarketDiagnosticLifecycleError("diagnostic relative path must be non-empty and relative")
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise MarketDiagnosticLifecycleError("diagnostic artifact escapes its private root") from exc
    try:
        reject_nonprivate_output_path(candidate)
    except PrivatePathError as exc:
        raise MarketDiagnosticLifecycleError(f"diagnostic artifact is not private: {candidate}") from exc
    return candidate


def _read_canonical_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise MarketDiagnosticLifecycleError(f"cannot read diagnostic artifact: {path}") from exc
    try:
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        if canonical_json_bytes(value) != payload:
            raise ValueError("bytes are not canonical")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise MarketDiagnosticLifecycleError(f"diagnostic artifact is not canonical UTF-8 JSON: {path}") from exc
    return value, artifact_sha256(value)


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    """Write one canonical JSON object with a same-directory replace."""

    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise MarketDiagnosticLifecycleError(f"diagnostic artifact is not private: {path}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        reject_nonprivate_output_path(temporary)
    except PrivatePathError as exc:
        raise MarketDiagnosticLifecycleError(f"diagnostic temporary artifact is not private: {temporary}") from exc
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise MarketDiagnosticLifecycleError(f"cannot atomically write diagnostic artifact: {path}") from exc
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _validate_weekly_record_for_store(record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise MarketDiagnosticLifecycleError("weekly record must be an object")
    _schema_validate(
        record,
        schema_path=WEEKLY_RECORD_SCHEMA_PATH,
        key="weekly_record",
        label="weekly record",
    )
    try:
        identity = validate_weekly_record(record)
    except MarketDiagnosticError as exc:
        raise MarketDiagnosticLifecycleError(f"weekly record calculation contract violation: {exc}") from exc
    return identity


def _reminder_status(evaluable_week_count: int) -> str:
    if evaluable_week_count < 4:
        return "pending"
    if evaluable_week_count < 8:
        return "ready_for_v1_1_implementation"
    return "overdue"


def build_v1_1_reminder(evaluable_week_count: int) -> dict[str, Any]:
    """Return the plain-language v1.1 reminder for a derived count.

    Knife 3 never emits ``active``.  That state belongs to a later, separately
    reviewed v1.1 attribution implementation; until then the reminder remains
    visible every week, including after the eighth evaluable week.
    """

    if isinstance(evaluable_week_count, bool) or not isinstance(evaluable_week_count, int) or evaluable_week_count < 0:
        raise MarketDiagnosticLifecycleError("evaluable_week_count must be a non-negative integer")
    status = _reminder_status(evaluable_week_count)
    text = (
        f"v1.1归因：待做。当前已积累 {evaluable_week_count} 个可评估周，计划在4—8个可评估周后实施。"
        "作用：解释领先或落后主要来自仓位/现金，还是来自主动系统能力。"
        "当前v1只能告诉总成绩，暂时不能完整解释原因。"
    )
    if status == "ready_for_v1_1_implementation":
        text += "现在已进入 v1.1 实施窗口。"
    elif status == "overdue":
        text += "已经超过第8个可评估周，v1.1 仍未启用，请安排实施。"
    return {"status": status, "evaluable_week_count": evaluable_week_count, "text": text}


def build_weekly_report_reminder(register: Mapping[str, Any]) -> dict[str, Any]:
    """Build the registered, de-identified §13 weekly-report reminder block."""

    if not isinstance(register, Mapping):
        raise MarketDiagnosticLifecycleError("lifecycle register must be an object")
    reminder = register.get("v1_1_reminder")
    if not isinstance(reminder, Mapping):
        raise MarketDiagnosticLifecycleError("lifecycle register has no v1.1 reminder")
    count = register.get("evaluable_week_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise MarketDiagnosticLifecycleError("lifecycle register evaluable_week_count is invalid")
    expected = build_v1_1_reminder(count)
    if dict(reminder) != expected:
        raise MarketDiagnosticLifecycleError("lifecycle register reminder is not derived from its count")
    calendar_count = register.get("calendar_week_count")
    if isinstance(calendar_count, bool) or not isinstance(calendar_count, int) or calendar_count < 1:
        raise MarketDiagnosticLifecycleError("lifecycle register calendar_week_count is invalid")
    return {
        "registry_key": REPORT_REMINDER_KEY,
        "section_number": REPORT_REMINDER_SECTION,
        "status": reminder["status"],
        "calendar_week_count": calendar_count,
        "evaluable_week_count": count,
        "text": reminder["text"],
    }


def render_weekly_report_reminder(register: Mapping[str, Any]) -> str:
    """Render the registered reminder as one safe section-12 line."""

    block = build_weekly_report_reminder(register)
    return (
        f"- [{block['registry_key']}] 状态={block['status']}；"
        f"日历周={block['calendar_week_count']}；可评估周={block['evaluable_week_count']}；"
        f"{block['text']}"
    )


def _record_relative_path(record: Mapping[str, Any]) -> str:
    return f"weeks/{record['decision_date']}/{WEEKLY_RECORD_FILENAME}"


def _record_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    result: set[str] = set()
    for path in root.rglob(WEEKLY_RECORD_FILENAME):
        if not path.is_file():
            continue
        try:
            relative = path.resolve().relative_to(root).as_posix()
        except ValueError as exc:
            raise MarketDiagnosticLifecycleError("diagnostic weekly record escaped its private root") from exc
        result.add(relative)
    return result


def _register_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        raise MarketDiagnosticLifecycleError("cannot build an empty diagnostic lifecycle register")
    first = records[0]
    epoch = first["diagnostic_epoch"]
    refs: list[dict[str, Any]] = []
    evaluable_week_count = 0
    previous_decision: str | None = None
    previous_valuation: str | None = None
    for expected_week, record in enumerate(records, start=1):
        identity = _validate_weekly_record_for_store(record)
        if identity["calendar_week_index"] != expected_week:
            raise MarketDiagnosticLifecycleError("diagnostic calendar weeks must start at 1 and be consecutive")
        if record["diagnostic_epoch"] != epoch:
            raise MarketDiagnosticLifecycleError("diagnostic_epoch cannot be silently mixed in one lifecycle register")
        if previous_decision is not None and record["decision_date"] <= previous_decision:
            raise MarketDiagnosticLifecycleError("diagnostic decision dates must be strictly increasing")
        if previous_valuation is not None and record["valuation_date"] <= previous_valuation:
            raise MarketDiagnosticLifecycleError("diagnostic valuation dates must be strictly increasing")
        previous_decision = record["decision_date"]
        previous_valuation = record["valuation_date"]
        strategy_evaluable = record["strategy"]["strategy_evaluable"]
        evaluable_week_count += int(strategy_evaluable)
        refs.append(
            {
                "calendar_week_index": expected_week,
                "decision_date": record["decision_date"],
                "valuation_date": record["valuation_date"],
                "weekly_record_relative_path": _record_relative_path(record),
                "weekly_record_sha256": artifact_sha256(record),
                "strategy_evaluable": strategy_evaluable,
            }
        )

    last = records[-1]
    current_window = window_containing_week(last["calendar_week_index"])
    return {
        "schema_name": "us_short_market_diagnostic_lifecycle_register",
        "schema_version": "1.0.0",
        "diagnostic_epoch": epoch,
        "calendar_week_count": len(records),
        "evaluable_week_count": evaluable_week_count,
        "non_evaluable_week_count": len(records) - evaluable_week_count,
        "last_calendar_week_index": last["calendar_week_index"],
        "last_decision_date": last["decision_date"],
        "last_valuation_date": last["valuation_date"],
        "current_window_id": current_window["window_id"],
        "current_window_week_count": last["calendar_week_index"] - current_window["window_start_week"] + 1,
        "record_refs": refs,
        "v1_1_reminder": build_v1_1_reminder(evaluable_week_count),
        "boundary": dict(STORE_BOUNDARY),
    }


def _load_records_for_register(root: Path, register: Mapping[str, Any]) -> list[dict[str, Any]]:
    _schema_validate(
        register,
        schema_path=REGISTER_SCHEMA_PATH,
        key="lifecycle_register",
        label="lifecycle register",
    )
    refs = register["record_refs"]
    records: list[dict[str, Any]] = []
    expected_paths: set[str] = set()
    previous_decision: str | None = None
    previous_valuation: str | None = None
    for expected_week, ref in enumerate(refs, start=1):
        if ref["calendar_week_index"] != expected_week:
            raise MarketDiagnosticLifecycleError("lifecycle register record refs are not consecutive")
        relative = ref["weekly_record_relative_path"]
        expected_paths.add(relative)
        path = _private_path(root, relative)
        record, digest = _read_canonical_json(path)
        if digest != ref["weekly_record_sha256"]:
            raise MarketDiagnosticLifecycleError(f"weekly record digest mismatch: {relative}")
        identity = _validate_weekly_record_for_store(record)
        if (
            identity["calendar_week_index"] != ref["calendar_week_index"]
            or record["decision_date"] != ref["decision_date"]
            or record["valuation_date"] != ref["valuation_date"]
            or record["strategy"]["strategy_evaluable"] != ref["strategy_evaluable"]
            or _record_relative_path(record) != relative
        ):
            raise MarketDiagnosticLifecycleError(f"lifecycle register ref does not bind weekly record: {relative}")
        if previous_decision is not None and record["decision_date"] <= previous_decision:
            raise MarketDiagnosticLifecycleError("diagnostic decision dates must be strictly increasing")
        if previous_valuation is not None and record["valuation_date"] <= previous_valuation:
            raise MarketDiagnosticLifecycleError("diagnostic valuation dates must be strictly increasing")
        previous_decision = record["decision_date"]
        previous_valuation = record["valuation_date"]
        records.append(record)

    extra_paths = _record_files(root) - expected_paths
    if extra_paths:
        raise MarketDiagnosticLifecycleError(
            "unreferenced immutable diagnostic weekly records exist: " + ", ".join(sorted(extra_paths))
        )
    return records


def load_lifecycle_register(root: str | Path = DEFAULT_ROOT) -> dict[str, Any]:
    """Load the private register and re-derive every count/ref before returning it."""

    store_root = _private_root(root)
    path = _private_path(store_root, REGISTER_FILENAME)
    if not path.is_file():
        raise MarketDiagnosticLifecycleError("diagnostic lifecycle register is not initialized")
    register, _digest = _read_canonical_json(path)
    records = _load_records_for_register(store_root, register)
    expected = _register_from_records(records)
    if expected != register:
        raise MarketDiagnosticLifecycleError("diagnostic lifecycle register is not derived from weekly records")
    return register


def _load_existing_records(store_root: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    register_path = _private_path(store_root, REGISTER_FILENAME)
    if register_path.is_file():
        register = load_lifecycle_register(store_root)
        records = _load_records_for_register(store_root, register)
        return register, records
    record_paths = _record_files(store_root)
    if record_paths:
        if len(record_paths) != 1:
            raise MarketDiagnosticLifecycleError(
                "diagnostic weekly records exist without a lifecycle register; refuse silent reconstruction"
            )
        relative = next(iter(record_paths))
        record, _digest = _read_canonical_json(_private_path(store_root, relative))
        identity = _validate_weekly_record_for_store(record)
        if identity["calendar_week_index"] != 1 or relative != _record_relative_path(record):
            raise MarketDiagnosticLifecycleError("orphan diagnostic record is not a valid week-1 recovery candidate")
        return None, [record]
    return None, []


def persist_settled_weekly_record(
    weekly_record: Mapping[str, Any],
    *,
    root: str | Path = DEFAULT_ROOT,
) -> dict[str, Any]:
    """Publish one already-built settled weekly record and update the counter.

    Repeating an identical week is idempotent.  A gap, date/order drift,
    epoch change, digest conflict, orphan record, or stale register fails
    closed.  The weekly record is published before the mutable register; a
    retry can only recover a matching week-1 orphan, never adopt an unknown
    file.
    """

    if not isinstance(weekly_record, Mapping):
        raise MarketDiagnosticLifecycleError("weekly_record must be an object")
    store_root = _private_root(root)
    incoming = deepcopy(dict(weekly_record))
    incoming_identity = _validate_weekly_record_for_store(incoming)
    register, records = _load_existing_records(store_root)
    incoming_week = incoming_identity["calendar_week_index"]
    incoming_path_relative = _record_relative_path(incoming)
    incoming_path = _private_path(store_root, incoming_path_relative)

    if register is None and records:
        orphan = records[0]
        incoming["v1_1_reminder"] = build_v1_1_reminder(int(orphan["strategy"]["strategy_evaluable"]))
        _validate_weekly_record_for_store(incoming)
        if _record_relative_path(orphan) != incoming_path_relative or artifact_sha256(orphan) != artifact_sha256(incoming):
            raise MarketDiagnosticLifecycleError("orphan diagnostic weekly record conflicts with the retry input")
        recovered_register = _register_from_records(records)
        _atomic_write(_private_path(store_root, REGISTER_FILENAME), recovered_register)
        return {
            "status": "recovered",
            "calendar_week_index": 1,
            "weekly_record_sha256": artifact_sha256(orphan),
            "calendar_week_count": recovered_register["calendar_week_count"],
            "evaluable_week_count": recovered_register["evaluable_week_count"],
            "v1_1_reminder": dict(recovered_register["v1_1_reminder"]),
            "weekly_report_reminder": build_weekly_report_reminder(recovered_register),
        }

    if register is not None:
        if incoming_week <= register["last_calendar_week_index"]:
            if incoming_week > len(records):
                raise MarketDiagnosticLifecycleError("diagnostic record is behind a register with a missing week")
            existing = records[incoming_week - 1]
            if _record_relative_path(existing) != incoming_path_relative:
                raise MarketDiagnosticLifecycleError("immutable week identity conflicts with its existing record")
            incoming["v1_1_reminder"] = dict(existing["v1_1_reminder"])
            _validate_weekly_record_for_store(incoming)
            if artifact_sha256(existing) != artifact_sha256(incoming):
                raise MarketDiagnosticLifecycleError("immutable diagnostic weekly record conflict")
            return {
                "status": "idempotent",
                "calendar_week_index": incoming_week,
                "weekly_record_sha256": artifact_sha256(existing),
                "calendar_week_count": register["calendar_week_count"],
                "evaluable_week_count": register["evaluable_week_count"],
                "v1_1_reminder": dict(register["v1_1_reminder"]),
                "weekly_report_reminder": build_weekly_report_reminder(register),
            }
        expected_week = register["last_calendar_week_index"] + 1
        if incoming_week != expected_week:
            raise MarketDiagnosticLifecycleError(
                f"diagnostic calendar week must append {expected_week}, got {incoming_week}"
            )
        if incoming["diagnostic_epoch"] != register["diagnostic_epoch"]:
            raise MarketDiagnosticLifecycleError("diagnostic_epoch changed; start a new diagnostic epoch explicitly")
        expected_evaluable_count = register["evaluable_week_count"] + int(
            incoming["strategy"]["strategy_evaluable"]
        )
    else:
        if incoming_week != 1:
            raise MarketDiagnosticLifecycleError("the first diagnostic weekly record must be calendar week 1")
        expected_evaluable_count = int(incoming["strategy"]["strategy_evaluable"])

    incoming["v1_1_reminder"] = build_v1_1_reminder(expected_evaluable_count)
    _validate_weekly_record_for_store(incoming)
    if incoming_path.is_file():
        existing, existing_digest = _read_canonical_json(incoming_path)
        if existing_digest != artifact_sha256(incoming):
            raise MarketDiagnosticLifecycleError("immutable diagnostic weekly record conflict")
        if existing != incoming:
            raise MarketDiagnosticLifecycleError("immutable diagnostic weekly record bytes do not match")
    else:
        _atomic_write(incoming_path, incoming)

    next_records = [*records, incoming]
    next_register = _register_from_records(next_records)
    register_path = _private_path(store_root, REGISTER_FILENAME)
    _atomic_write(register_path, next_register)
    return {
        "status": "published",
        "calendar_week_index": incoming_week,
        "weekly_record_sha256": artifact_sha256(incoming),
        "calendar_week_count": next_register["calendar_week_count"],
        "evaluable_week_count": next_register["evaluable_week_count"],
        "v1_1_reminder": dict(next_register["v1_1_reminder"]),
        "weekly_report_reminder": build_weekly_report_reminder(next_register),
    }


append_weekly_record = persist_settled_weekly_record


__all__ = [
    "DEFAULT_ROOT",
    "MarketDiagnosticLifecycleError",
    "REPORT_REMINDER_KEY",
    "REPORT_REMINDER_SECTION",
    "STORE_BOUNDARY",
    "append_weekly_record",
    "build_v1_1_reminder",
    "build_weekly_report_reminder",
    "load_lifecycle_register",
    "persist_settled_weekly_record",
    "render_weekly_report_reminder",
]
