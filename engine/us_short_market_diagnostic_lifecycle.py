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
from datetime import date
import json
import os
from pathlib import Path
import re
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
_DATE8 = re.compile(r"^[0-9]{8}$")


class MarketDiagnosticLifecycleError(RuntimeError):
    """Raised when a diagnostic weekly record or lifecycle register is unsafe to persist/use."""


def _date8(value: object, field: str) -> date:
    if not isinstance(value, str) or not value.isascii() or _DATE8.fullmatch(value) is None:
        raise MarketDiagnosticLifecycleError(f"{field} must be an ASCII YYYYMMDD date")
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError as exc:
        raise MarketDiagnosticLifecycleError(f"{field} is not a real calendar date") from exc


def _as_of(value: object) -> date:
    return _date8(value, "as_of_date")


def _not_future(value: date, field: str, as_of_date: date | None) -> None:
    if as_of_date is not None and value > as_of_date:
        raise MarketDiagnosticLifecycleError(f"{field} is after as_of_date")


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


def _validate_weekly_record_for_store(
    record: Mapping[str, Any], *, as_of_date: str | None = None
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise MarketDiagnosticLifecycleError("weekly record must be an object")
    _schema_validate(
        record,
        schema_path=WEEKLY_RECORD_SCHEMA_PATH,
        key="weekly_record",
        label="weekly record",
    )
    try:
        identity = validate_weekly_record(record, as_of_date=as_of_date)
    except MarketDiagnosticError as exc:
        raise MarketDiagnosticLifecycleError(f"weekly record calculation contract violation: {exc}") from exc
    return identity


def build_v1_1_reminder(
    evaluable_week_count: int,
    *,
    consecutive_paper_evaluable_week_count: int,
    active: bool | None = None,
    attribution_epoch: str | None = None,
) -> dict[str, Any]:
    """Return the weekly v1.1 state without requiring a human reminder."""

    if isinstance(evaluable_week_count, bool) or not isinstance(evaluable_week_count, int) or evaluable_week_count < 0:
        raise MarketDiagnosticLifecycleError("evaluable_week_count must be a non-negative integer")
    consecutive = consecutive_paper_evaluable_week_count
    if isinstance(consecutive, bool) or not isinstance(consecutive, int) or consecutive < 0:
        raise MarketDiagnosticLifecycleError(
            "consecutive_paper_evaluable_week_count must be a non-negative integer"
        )
    is_active = consecutive >= 4 if active is None else active
    if not isinstance(is_active, bool):
        raise MarketDiagnosticLifecycleError("active must be boolean")
    if attribution_epoch is not None and (not isinstance(attribution_epoch, str) or not attribution_epoch):
        raise MarketDiagnosticLifecycleError("attribution_epoch must be null or non-empty")
    status = "active" if is_active else "pending"
    if is_active:
        epoch_text = f"；attribution_epoch={attribution_epoch}" if attribution_epoch else ""
        text = (
            f"v1.1 归因：已自动启用{epoch_text}。"
            "作用：解释领先或落后主要来自仓位和现金，还是来自主动系统能力。"
            "缺少 VTI 总收益、PIT 现金收益或 g* 时只报 unavailable，不补零、不停用。"
        )
    else:
        text = (
            f"v1.1 归因：等待自动启用；当前连续 paper_evaluable=true 周={consecutive}/4。"
            "作用：解释领先或落后主要来自仓位和现金，还是来自主动系统能力。"
            "在启用前，任一 false/no_count/missing 周都会把连续计数清零。"
        )
    return {"status": status, "evaluable_week_count": evaluable_week_count, "text": text}


def _derive_v1_1_attribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    consecutive = 0
    trigger: dict[str, Any] | None = None
    for record in records:
        if record["strategy"]["paper_evaluable"]:
            consecutive += 1
        else:
            consecutive = 0
        if trigger is None and consecutive >= 4:
            trigger = {
                "diagnostic_epoch": record["diagnostic_epoch"],
                "calendar_week_index": record["calendar_week_index"],
                "decision_date": record["decision_date"],
                "strategy_ruleset_fingerprint": record["strategy_ruleset_fingerprint"],
            }
    if trigger is None:
        return {
            "status": "pending",
            "trigger_consecutive_weeks": 4,
            "current_consecutive_paper_evaluable_weeks": consecutive,
            "activation_trigger_week_index": None,
            "effective_from_week_index": None,
            "attribution_epoch": None,
            "sticky_after_activation": True,
        }
    return {
        "status": "active",
        "trigger_consecutive_weeks": 4,
        "current_consecutive_paper_evaluable_weeks": consecutive,
        "activation_trigger_week_index": trigger["calendar_week_index"],
        "effective_from_week_index": trigger["calendar_week_index"] + 1,
        "attribution_epoch": f"us-short-v1.1-{artifact_sha256(trigger)[:24]}",
        "sticky_after_activation": True,
    }


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
    consecutive = register.get("consecutive_paper_evaluable_week_count")
    if isinstance(consecutive, bool) or not isinstance(consecutive, int) or consecutive < 0:
        raise MarketDiagnosticLifecycleError(
            "lifecycle register consecutive_paper_evaluable_week_count is invalid"
        )
    attribution = register.get("v1_1_attribution")
    if not isinstance(attribution, Mapping):
        raise MarketDiagnosticLifecycleError("lifecycle register has no v1.1 attribution state")
    expected = build_v1_1_reminder(
        count,
        consecutive_paper_evaluable_week_count=consecutive,
        active=attribution.get("status") == "active",
        attribution_epoch=attribution.get("attribution_epoch"),
    )
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
        "consecutive_paper_evaluable_week_count": consecutive,
        "text": reminder["text"],
    }


def render_weekly_report_reminder(register: Mapping[str, Any]) -> str:
    """Render the registered reminder as one safe section-12 line."""

    block = build_weekly_report_reminder(register)
    return (
        f"- [{block['registry_key']}] 状态={block['status']}；"
        f"日历周={block['calendar_week_count']}；累计可评估周={block['evaluable_week_count']}；"
        f"连续可评估周={block['consecutive_paper_evaluable_week_count']}；"
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


def _register_from_records(
    records: list[dict[str, Any]], *, as_of_date: str | None = None
) -> dict[str, Any]:
    if not records:
        raise MarketDiagnosticLifecycleError("cannot build an empty diagnostic lifecycle register")
    first = records[0]
    epoch = first["diagnostic_epoch"]
    refs: list[dict[str, Any]] = []
    evaluable_week_count = 0
    previous_decision: str | None = None
    previous_valuation: str | None = None
    for expected_week, record in enumerate(records, start=1):
        record_date = _date8(record["decision_date"], "weekly_record.decision_date")
        record_valuation = _date8(record["valuation_date"], "weekly_record.valuation_date")
        as_of = _as_of(as_of_date) if as_of_date is not None else None
        _not_future(record_date, "weekly_record.decision_date", as_of)
        _not_future(record_valuation, "weekly_record.valuation_date", as_of)
        identity = _validate_weekly_record_for_store(record, as_of_date=as_of_date)
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
    attribution = _derive_v1_1_attribution(records)
    return {
        "schema_name": "us_short_market_diagnostic_lifecycle_register",
        "schema_version": "1.1.0",
        "diagnostic_epoch": epoch,
        "calendar_week_count": len(records),
        "evaluable_week_count": evaluable_week_count,
        "non_evaluable_week_count": len(records) - evaluable_week_count,
        "consecutive_paper_evaluable_week_count": attribution[
            "current_consecutive_paper_evaluable_weeks"
        ],
        "last_calendar_week_index": last["calendar_week_index"],
        "last_decision_date": last["decision_date"],
        "last_valuation_date": last["valuation_date"],
        "current_window_id": current_window["window_id"],
        "current_window_week_count": last["calendar_week_index"] - current_window["window_start_week"] + 1,
        "record_refs": refs,
        "v1_1_reminder": build_v1_1_reminder(
            evaluable_week_count,
            consecutive_paper_evaluable_week_count=attribution[
                "current_consecutive_paper_evaluable_weeks"
            ],
            active=attribution["status"] == "active",
            attribution_epoch=attribution["attribution_epoch"],
        ),
        "v1_1_attribution": attribution,
        "boundary": dict(STORE_BOUNDARY),
    }


def _load_records_for_register(
    root: Path, register: Mapping[str, Any], *, as_of_date: str | None = None
) -> list[dict[str, Any]]:
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
        identity = _validate_weekly_record_for_store(record, as_of_date=as_of_date)
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


def load_lifecycle_register(
    root: str | Path = DEFAULT_ROOT, *, as_of_date: str | None = None
) -> dict[str, Any]:
    """Load the private register and re-derive every count/ref before returning it."""

    store_root = _private_root(root)
    if as_of_date is not None:
        _as_of(as_of_date)
    path = _private_path(store_root, REGISTER_FILENAME)
    if not path.is_file():
        raise MarketDiagnosticLifecycleError("diagnostic lifecycle register is not initialized")
    register, _digest = _read_canonical_json(path)
    records = _load_records_for_register(store_root, register, as_of_date=as_of_date)
    expected = _register_from_records(records, as_of_date=as_of_date)
    if expected != register:
        raise MarketDiagnosticLifecycleError("diagnostic lifecycle register is not derived from weekly records")
    return register


def load_settled_weekly_records(
    root: str | Path = DEFAULT_ROOT, *, as_of_date: str | None = None
) -> list[dict[str, Any]]:
    """Load every settled diagnostic week after revalidating the private register and records."""

    store_root = _private_root(root)
    register = load_lifecycle_register(store_root, as_of_date=as_of_date)
    return _load_records_for_register(store_root, register, as_of_date=as_of_date)


def _load_existing_records(
    store_root: Path, *, as_of_date: str | None = None
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    register_path = _private_path(store_root, REGISTER_FILENAME)
    if register_path.is_file():
        register = load_lifecycle_register(store_root, as_of_date=as_of_date)
        records = _load_records_for_register(store_root, register, as_of_date=as_of_date)
        return register, records
    record_paths = _record_files(store_root)
    if record_paths:
        if len(record_paths) != 1:
            raise MarketDiagnosticLifecycleError(
                "diagnostic weekly records exist without a lifecycle register; refuse silent reconstruction"
            )
        relative = next(iter(record_paths))
        record, _digest = _read_canonical_json(_private_path(store_root, relative))
        identity = _validate_weekly_record_for_store(record, as_of_date=as_of_date)
        if identity["calendar_week_index"] != 1 or relative != _record_relative_path(record):
            raise MarketDiagnosticLifecycleError("orphan diagnostic record is not a valid week-1 recovery candidate")
        return None, [record]
    return None, []


def persist_settled_weekly_record(
    weekly_record: Mapping[str, Any],
    *,
    root: str | Path = DEFAULT_ROOT,
    as_of_date: str | None = None,
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
    if as_of_date is not None:
        _as_of(as_of_date)
    store_root = _private_root(root)
    incoming = deepcopy(dict(weekly_record))
    incoming_identity = _validate_weekly_record_for_store(incoming, as_of_date=as_of_date)
    register, records = _load_existing_records(store_root, as_of_date=as_of_date)
    incoming_week = incoming_identity["calendar_week_index"]
    incoming_path_relative = _record_relative_path(incoming)
    incoming_path = _private_path(store_root, incoming_path_relative)

    if register is None and records:
        orphan = records[0]
        orphan_state = _derive_v1_1_attribution(records)
        incoming["v1_1_reminder"] = build_v1_1_reminder(
            int(orphan["strategy"]["strategy_evaluable"]),
            consecutive_paper_evaluable_week_count=orphan_state[
                "current_consecutive_paper_evaluable_weeks"
            ],
            active=orphan_state["status"] == "active",
            attribution_epoch=orphan_state["attribution_epoch"],
        )
        _validate_weekly_record_for_store(incoming, as_of_date=as_of_date)
        if _record_relative_path(orphan) != incoming_path_relative or artifact_sha256(orphan) != artifact_sha256(incoming):
            raise MarketDiagnosticLifecycleError("orphan diagnostic weekly record conflicts with the retry input")
        recovered_register = _register_from_records(records, as_of_date=as_of_date)
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
            _validate_weekly_record_for_store(incoming, as_of_date=as_of_date)
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
    else:
        if incoming_week != 1:
            raise MarketDiagnosticLifecycleError("the first diagnostic weekly record must be calendar week 1")

    next_records = [*records, incoming]
    next_state = _derive_v1_1_attribution(next_records)
    expected_evaluable_count = sum(int(record["strategy"]["strategy_evaluable"]) for record in next_records)
    incoming["v1_1_reminder"] = build_v1_1_reminder(
        expected_evaluable_count,
        consecutive_paper_evaluable_week_count=next_state[
            "current_consecutive_paper_evaluable_weeks"
        ],
        active=next_state["status"] == "active",
        attribution_epoch=next_state["attribution_epoch"],
    )
    _validate_weekly_record_for_store(incoming, as_of_date=as_of_date)
    if incoming_path.is_file():
        existing, existing_digest = _read_canonical_json(incoming_path)
        if existing_digest != artifact_sha256(incoming):
            raise MarketDiagnosticLifecycleError("immutable diagnostic weekly record conflict")
        if existing != incoming:
            raise MarketDiagnosticLifecycleError("immutable diagnostic weekly record bytes do not match")
    else:
        _atomic_write(incoming_path, incoming)

    next_register = _register_from_records(next_records, as_of_date=as_of_date)
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
    "load_settled_weekly_records",
    "persist_settled_weekly_record",
    "render_weekly_report_reminder",
]
