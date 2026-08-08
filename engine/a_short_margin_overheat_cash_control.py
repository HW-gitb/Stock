"""Knife 1 contract and pre-freeze state machine for the margin-overheat track.

This module deliberately stops at schema/governance-first.  It registers one
independent comparison question, describes both measurement stages, and
prevents pre-freeze audit evidence from becoming a forward verdict.  Producer,
shadow allocation consumer, capture, settlement, ledger, adjudication and
reminder wiring belong to knives 2--4 and are not hidden here.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from engine import a_short_evidence_epoch_mode as epoch_mode
from engine import a_short_margin_overheat as production_margin


ROOT = Path(__file__).resolve().parents[1]
TRACK_ID = "a_short_margin_overheat_cash_control"
PROGRAM_ID = "margin_overheat_cash_control"
SCHEMA_VERSION = "1.0.0"
PRE_FREEZE = "pre_freeze_audit_only"
FROZEN = "frozen_enforced"
PROGRAM_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_program.schema.json"
STATE_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_state.schema.json"
GOVERNANCE_PATH = ROOT / "presets" / "a_short_margin_overheat_cash_control_governance_20260808.json"
STAGE_A = "stage_a"
STAGE_B = "stage_b"
EVIDENCE_STATUSES = ("insufficient_data", "accumulating", "review_due")
COMPARISON_VERDICTS = ("not_evaluated", "inconclusive", "supported", "not_supported")
FREEZE_PREREQUISITES = (
    "knife_1_independent_review_pass",
    "knife_2_replay_gate_pass",
    "knife_3_independent_review_pass",
    "knife_4_independent_review_pass",
    "semantic_freeze_manifest_complete",
    "source_hash_complete",
    "negative_controls_complete",
    "user_approved_design_final_before_freeze",
)


class MarginOverheatCashControlError(ValueError):
    """Raised when the dedicated comparison contract cannot be proven."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise MarginOverheatCashControlError(f"cannot read contract: {path}") from exc


def _schema_validate(value: dict, path: Path) -> None:
    import jsonschema

    try:
        jsonschema.validate(value, _load_json(path))
    except jsonschema.ValidationError as exc:
        raise MarginOverheatCashControlError(f"invalid margin-overheat contract: {exc.message}") from exc


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _strict_nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MarginOverheatCashControlError(f"{label} must be a non-negative integer")
    return value


def _assert_numeric_types_match(value: Any, expected: Any, path: str) -> None:
    """Reject JSON numbers whose Python numeric type differs from a schema const."""
    if isinstance(expected, bool):
        return
    if isinstance(expected, int):
        if type(value) is not int:
            raise MarginOverheatCashControlError(
                f"governance numeric type mismatch at {path}: expected int"
            )
        return
    if isinstance(expected, float):
        if type(value) is not float:
            raise MarginOverheatCashControlError(
                f"governance numeric type mismatch at {path}: expected float"
            )
        return
    if isinstance(expected, dict):
        if not isinstance(value, dict):
            return
        for key, child in expected.items():
            if key in value:
                _assert_numeric_types_match(value[key], child, f"{path}.{key}")
        return
    if isinstance(expected, list):
        if not isinstance(value, list):
            return
        for index, child in enumerate(expected):
            if index < len(value):
                _assert_numeric_types_match(value[index], child, f"{path}[{index}]")


def _validate_governance_numeric_types(governance: Mapping[str, Any]) -> None:
    schema = _load_json(PROGRAM_SCHEMA_PATH)
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    for key, property_schema in properties.items():
        if key in governance and isinstance(property_schema, dict) and "const" in property_schema:
            _assert_numeric_types_match(governance[key], property_schema["const"], key)


def _minimum_trigger_effective_weeks() -> int:
    """Read the trigger floor from the governed state contract, not a code literal."""
    governance = _load_json(GOVERNANCE_PATH)
    if not isinstance(governance, dict):
        raise MarginOverheatCashControlError("margin-overheat governance must be an object")
    _schema_validate(governance, PROGRAM_SCHEMA_PATH)
    _validate_governance_numeric_types(governance)
    try:
        floor = governance["state_contract"]["min_trigger_effective_weeks"]
    except (KeyError, TypeError) as exc:
        raise MarginOverheatCashControlError(
            "governance is missing state_contract.min_trigger_effective_weeks"
        ) from exc
    return _strict_nonnegative_int(floor, "state_contract.min_trigger_effective_weeks")


def _production_constants_unchanged() -> None:
    if production_margin.MARGIN_OVERHEAT_PERCENTILE_THRESHOLD is not None or \
            production_margin.MARGIN_OVERHEAT_CASH_FACTOR is not None or \
            production_margin.MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED is not False:
        raise MarginOverheatCashControlError("production margin-overheat constants crossed the comparison boundary")


def _require_shared_clock_gate() -> None:
    try:
        allowed = epoch_mode.evidence_counts_toward_clock(TRACK_ID)
    except Exception as exc:
        raise MarginOverheatCashControlError(
            "evidence_counts_toward_clock shared epoch gate rejected frozen counting state"
        ) from exc
    if allowed is not True:
        raise MarginOverheatCashControlError(
            "evidence_counts_toward_clock shared epoch gate rejected frozen counting state"
        )


def load_governance(path: str | Path = GOVERNANCE_PATH) -> dict:
    governance = _load_json(Path(path))
    validate_governance(governance)
    return copy.deepcopy(governance)


def validate_governance(governance: Mapping[str, Any]) -> None:
    if not isinstance(governance, dict):
        raise MarginOverheatCashControlError("margin-overheat governance must be an object")
    _schema_validate(governance, PROGRAM_SCHEMA_PATH)
    _validate_governance_numeric_types(governance)
    if TRACK_ID not in epoch_mode.TRACKS:
        raise MarginOverheatCashControlError("margin-overheat track is not registered in shared epoch mode")
    if epoch_mode._mode(TRACK_ID) != PRE_FREEZE:
        raise MarginOverheatCashControlError("margin-overheat knife 1 must remain pre-freeze")
    _production_constants_unchanged()


def semantic_projection(governance: Mapping[str, Any] | None = None) -> dict:
    """Return only fields allowed to change a future comparison verdict.

    The default document is fully admission-validated.  An explicit mapping
    is treated as a candidate for hash comparison before admission validation;
    callers that would persist or admit it must still call
    :func:`validate_governance`.
    """
    if governance is None:
        document = load_governance()
    elif isinstance(governance, Mapping):
        document = copy.deepcopy(dict(governance))
    else:
        raise MarginOverheatCashControlError("margin-overheat governance must be an object")
    keys = (
        "schema_name", "schema_version", "program_id", "track_id", "lane",
        "comparison_only", "mode", "namespace", "source_binding", "stage_a",
        "stage_b", "state_contract", "capture_contract", "outcome_contract",
        "boundary",
    )
    try:
        return {key: document[key] for key in keys}
    except KeyError as exc:
        raise MarginOverheatCashControlError("semantic candidate is missing a contract field") from exc


def semantic_fingerprint(governance: Mapping[str, Any] | None = None) -> str:
    return _digest(semantic_projection(governance))


def current_mode() -> str:
    """Read the shared registry; it is the sole mode authority."""
    return epoch_mode._mode(TRACK_ID)


def current_epoch_id() -> str:
    """Return the dedicated epoch identity without starting a clock."""
    return "epoch-" + semantic_fingerprint()[:12]


def evidence_counts_toward_clock() -> bool:
    return epoch_mode.evidence_counts_toward_clock(TRACK_ID)


def validate_source_references(references: Sequence[str], governance: Mapping[str, Any] | None = None) -> None:
    """Reject prose, other market-context leaves, and other comparison ledgers."""
    document = dict(governance or load_governance())
    validate_governance(document)
    if isinstance(references, (str, bytes)) or not isinstance(references, Sequence):
        raise MarginOverheatCashControlError("source references must be an ordered list")
    refs = list(references)
    if any(not isinstance(ref, str) or not ref for ref in refs) or len(refs) != len(set(refs)):
        raise MarginOverheatCashControlError("source references must be unique non-empty strings")
    allowed = set(document["source_binding"]["allowed_structured_sources"])
    if set(refs) != allowed:
        raise MarginOverheatCashControlError("source references are outside the dedicated structured contract")


def validate_freeze_admission(prerequisites: Mapping[str, object]) -> dict[str, object]:
    """Validate, but never write, the separate user-gated frozen transition."""
    load_governance()
    if set(prerequisites) != set(FREEZE_PREREQUISITES) or \
            any(prerequisites[key] is not True for key in FREEZE_PREREQUISITES):
        raise MarginOverheatCashControlError(
            "frozen transition requires all four knife reviews, replay, freeze, source, negative-control and user gates"
        )
    try:
        freeze_packet_identity = epoch_mode.validate_frozen_transition(TRACK_ID)
    except Exception as exc:
        raise MarginOverheatCashControlError(
            "validate_frozen_transition shared freeze gate rejected admission"
        ) from exc
    return {
        "track_id": TRACK_ID,
        "requested_mode": FROZEN,
        "new_epoch_required": True,
        "clock_starts_only_after_durable_user_approval": True,
        "freeze_packet_identity": dict(freeze_packet_identity),
        "write_performed": False,
    }


def build_state(*, calendar_effective_weeks: int, trigger_effective_weeks: int,
                stage: str = STAGE_A, mode: str | None = None,
                comparison_verdict: str = "not_evaluated") -> dict:
    """Build a state snapshot; pre-freeze input is deliberately not counted."""
    calendar_effective_weeks = _strict_nonnegative_int(calendar_effective_weeks, "calendar_effective_weeks")
    trigger_effective_weeks = _strict_nonnegative_int(trigger_effective_weeks, "trigger_effective_weeks")
    if trigger_effective_weeks > calendar_effective_weeks:
        raise MarginOverheatCashControlError("trigger weeks cannot exceed calendar weeks")
    if stage not in (STAGE_A, STAGE_B):
        raise MarginOverheatCashControlError("unknown comparison stage")
    registry_mode = current_mode()
    mode = registry_mode if mode is None else mode
    if mode != registry_mode:
        raise MarginOverheatCashControlError(
            "requested mode does not match the shared epoch registry"
        )
    if mode not in (PRE_FREEZE, FROZEN):
        raise MarginOverheatCashControlError("unknown comparison mode")
    _production_constants_unchanged()
    if comparison_verdict != "not_evaluated":
        raise MarginOverheatCashControlError("knife 1 cannot emit a comparison verdict")

    if mode == PRE_FREEZE:
        state = {
            "schema_name": "a_short_margin_overheat_cash_control_state",
            "schema_version": SCHEMA_VERSION,
            "track_id": TRACK_ID,
            "stage": stage,
            "mode": PRE_FREEZE,
            "clock_status": "not_started",
            "calendar_effective_weeks": 0,
            "trigger_effective_weeks": 0,
            "evidence_status": "insufficient_data",
            "comparison_verdict": "not_evaluated",
            "production_unchanged": True,
            "reason": "pre_freeze_audit_only",
        }
    else:
        _require_shared_clock_gate()
        minimum_trigger_effective_weeks = _minimum_trigger_effective_weeks()
        if trigger_effective_weeks < minimum_trigger_effective_weeks:
            evidence_status, clock_status = "insufficient_data", "running"
        elif calendar_effective_weeks < 12:
            evidence_status, clock_status = "accumulating", "running"
        else:
            evidence_status, clock_status = "review_due", "review_due"
        reason = (
            "insufficient_trigger_weeks"
            if trigger_effective_weeks < minimum_trigger_effective_weeks
            else evidence_status
        )
        state = {
            "schema_name": "a_short_margin_overheat_cash_control_state",
            "schema_version": SCHEMA_VERSION,
            "track_id": TRACK_ID,
            "stage": stage,
            "mode": FROZEN,
            "clock_status": clock_status,
            "calendar_effective_weeks": calendar_effective_weeks,
            "trigger_effective_weeks": trigger_effective_weeks,
            "evidence_status": evidence_status,
            "comparison_verdict": "not_evaluated",
            "production_unchanged": True,
            "reason": reason,
        }
    _schema_validate(state, STATE_SCHEMA_PATH)
    return state


def validate_state(state: Mapping[str, Any]) -> None:
    if not isinstance(state, dict):
        raise MarginOverheatCashControlError("state must be an object")
    _schema_validate(state, STATE_SCHEMA_PATH)
    if state["trigger_effective_weeks"] > state["calendar_effective_weeks"]:
        raise MarginOverheatCashControlError("state trigger weeks exceed calendar weeks")
    _production_constants_unchanged()
    if state["comparison_verdict"] != "not_evaluated":
        raise MarginOverheatCashControlError("knife 1 validate_state rejects comparison_verdict")
    if state["mode"] != current_mode():
        raise MarginOverheatCashControlError(
            "state mode does not match the shared epoch registry"
        )
    if state["mode"] == PRE_FREEZE and (state["calendar_effective_weeks"] != 0 or
                                         state["trigger_effective_weeks"] != 0):
        raise MarginOverheatCashControlError("pre-freeze state cannot count weeks or emit a verdict")
    if state["mode"] == FROZEN:
        _require_shared_clock_gate()


def stage_arm_ids(stage: str, governance: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    document = dict(governance or load_governance())
    validate_governance(document)
    if stage not in (STAGE_A, STAGE_B):
        raise MarginOverheatCashControlError("unknown comparison stage")
    section = document[stage]
    return (section["baseline"]["arm_id"],) + tuple(row["arm_id"] for row in section["challengers"])
