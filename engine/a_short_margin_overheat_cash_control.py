"""Knife 1 contract plus knife 2 predicate/shadow and knife 3 settlement seams.

It registers one independent comparison question, describes both measurement
stages, and prevents pre-freeze audit evidence from becoming a forward verdict.
Knife 2 adds the source-bound structured predicate producer and the one
comparison-only shadow allocation consumer.  Knife 3 adds source-bound weekly
capture, existing-cache settlement, private ledger/adjudication/reminder
rewrites, and a de-identified public projection; it does not freeze or alter
production behavior.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import numbers
import re
import random
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from engine import a_short_evidence_epoch_mode as epoch_mode
from engine.a_short_market_history import canonical_dates, percentile_rank
from engine import a_short_margin_overheat as production_margin


ROOT = Path(__file__).resolve().parents[1]
TRACK_ID = "a_short_margin_overheat_cash_control"
PROGRAM_ID = "margin_overheat_cash_control"
SCHEMA_VERSION = "1.0.0"
PRE_FREEZE = "pre_freeze_audit_only"
FROZEN = "frozen_enforced"
PROGRAM_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_program.schema.json"
STATE_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_state.schema.json"
PREDICATE_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_predicate.schema.json"
REPLAY_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_replay.schema.json"
CAPTURE_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_capture.schema.json"
RECEIPT_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_source_receipt.schema.json"
OUTCOME_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_outcome.schema.json"
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_ledger.schema.json"
ADJUDICATION_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_adjudication.schema.json"
REMINDER_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_reminder.schema.json"
STAGE_TRANSITION_RECEIPT_SCHEMA_PATH = (
    ROOT / "schemas" / "a_short_margin_overheat_cash_control_stage_transition_receipt.schema.json"
)
FREEZE_MANIFEST_SCHEMA_PATH = (
    ROOT / "schemas" / "a_short_margin_overheat_cash_control_freeze_manifest.schema.json"
)
PUBLIC_SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "a_short_margin_overheat_cash_control_public_summary.schema.json"
DAILY_CACHE_SCHEMA_PATH = ROOT / "schemas" / "a_short_factor_comparison_v2_daily_cache.schema.json"
GOVERNANCE_PATH = ROOT / "presets" / "a_short_margin_overheat_cash_control_governance_20260808.json"
STAGE_A = "stage_a"
STAGE_B = "stage_b"
EVIDENCE_STATUSES = ("insufficient_data", "accumulating", "review_due")
COMPARISON_VERDICTS = ("not_evaluated", "inconclusive", "supported", "not_supported")
PREDICATE_SCHEMA_NAME = "a_short_margin_overheat_cash_control_predicate"
REPLAY_SCHEMA_NAME = "a_short_margin_overheat_cash_control_replay"
PREDICATE_SCHEMA_VERSION = "1.0.0"
CAPTURE_SCHEMA_VERSION = "1.0.0"
HORIZONS = (5, 10, 20)
PUBLIC_STATUS_NOT_CONFIGURED = "not_configured"
PUBLIC_STATUS_CURRENT = "evidence_current"
PUBLIC_STATUS_UNAVAILABLE = "evidence_unavailable_or_inconclusive"
CAPTURE_REPLAY_DRIFT_MESSAGE = "margin-overheat capture replay input drifted"
QUESTION_ID = "margin_overheat_cash_control"
CHANGE_RATE_LOOKBACK_SESSIONS = 20
PREDICATE_SOURCE_REFERENCES = (
    "analysis_input.market_context.margin_overheat",
    "official_m67.selection_plan",
    "a_short_factor_comparison_v2.approved_daily_cache",
)
DEFINITION_SUMMARY = {
    "ratio": "required_exchange_rzye_total_divided_by_shanghai_float_mv",
    "change_rate_20d": "ratio_t_divided_by_ratio_t_minus_20_sessions_minus_one",
    "percentile": "fraction_of_same_window_values_at_or_below_current",
    "window": "rolling_three_calendar_years_exact_date_reconciliation",
    "warmup": "twenty_prior_sessions_from_the_same_source_series",
    "comparison_only": True,
}
REPLAY_ARM_SPECS = (
    ("change_rate_p90", "change_rate_20d_percentile_p90", "change_rate_percentile", 0.90),
    ("change_rate_p95", "change_rate_20d_percentile_p95", "change_rate_percentile", 0.95),
)
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
_FREEZE_SCHEMA_CONTRACTS = {
    "program": PROGRAM_SCHEMA_PATH,
    "state": STATE_SCHEMA_PATH,
    "predicate": PREDICATE_SCHEMA_PATH,
    "shadow": ROOT / "schemas" / "a_short_margin_overheat_cash_control_shadow.schema.json",
    "capture": CAPTURE_SCHEMA_PATH,
    "source_receipt": RECEIPT_SCHEMA_PATH,
    "outcome": OUTCOME_SCHEMA_PATH,
    "ledger": LEDGER_SCHEMA_PATH,
    "adjudication": ADJUDICATION_SCHEMA_PATH,
    "reminder": REMINDER_SCHEMA_PATH,
    "stage_transition_receipt": STAGE_TRANSITION_RECEIPT_SCHEMA_PATH,
    "freeze_manifest": FREEZE_MANIFEST_SCHEMA_PATH,
}
_SCHEMA_ANNOTATION_KEYS = frozenset({
    "title", "description", "$comment", "examples", "deprecated", "readOnly", "writeOnly",
})


class MarginOverheatCashControlError(ValueError):
    """Raised when the dedicated comparison contract cannot be proven."""


def _safe_exception_text(exc: BaseException) -> str:
    try:
        return str(exc)
    except Exception:
        return ""


def is_capture_replay_drift(exc: BaseException) -> bool:
    """Identify a direct or wrapped immutable same-week replay rejection."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ValueError):
            message = _safe_exception_text(current)
            if (message == CAPTURE_REPLAY_DRIFT_MESSAGE
                    or message.endswith(": " + CAPTURE_REPLAY_DRIFT_MESSAGE)):
                return True
        cause = current.__cause__
        current = cause if isinstance(cause, BaseException) else (
            None if getattr(current, "__suppress_context__", False) else current.__context__
        )
    return False


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


def _preliminary_calendar_effective_weeks() -> int:
    """Read the preliminary calendar gate from the governed adjudication contract."""
    contract = _adjudication_contract()
    try:
        threshold = contract["preliminary_calendar_effective_weeks"]
    except (KeyError, TypeError) as exc:
        raise MarginOverheatCashControlError(
            "governance is missing adjudication_contract.preliminary_calendar_effective_weeks"
        ) from exc
    return _strict_nonnegative_int(
        threshold, "adjudication_contract.preliminary_calendar_effective_weeks"
    )


def _production_constants_unchanged() -> None:
    if production_margin.MARGIN_OVERHEAT_PERCENTILE_THRESHOLD is not None or \
            production_margin.MARGIN_OVERHEAT_CASH_FACTOR is not None or \
            production_margin.MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED is not False:
        raise MarginOverheatCashControlError("production margin-overheat constants crossed the comparison boundary")


def _model_cash_cny() -> float:
    try:
        value = load_governance()["outcome_contract"]["model_cash_cny"]
    except (KeyError, TypeError) as exc:
        raise MarginOverheatCashControlError(
            "governance is missing the deidentified model cash"
        ) from exc
    if not _finite_number(value) or float(value) <= 0:
        raise MarginOverheatCashControlError(
            "governance deidentified model cash must be finite and positive"
        )
    return float(value)


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
    if epoch_mode._mode(TRACK_ID) not in (PRE_FREEZE, FROZEN):
        raise MarginOverheatCashControlError("margin-overheat shared epoch registry mode is invalid")
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
        "stage_b", "state_contract", "adjudication_contract", "capture_contract", "outcome_contract",
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


def _schema_validation_projection(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _schema_validation_projection(item)
            for key, item in value.items()
            if key not in _SCHEMA_ANNOTATION_KEYS
        }
    if isinstance(value, list):
        return [_schema_validation_projection(item) for item in value]
    return value


def _freeze_schema_contracts() -> dict[str, dict[str, str]]:
    contracts: dict[str, dict[str, str]] = {}
    for name, path in _FREEZE_SCHEMA_CONTRACTS.items():
        document = _load_json(path)
        if not isinstance(document, dict):
            raise MarginOverheatCashControlError(f"freeze schema contract {name} must be an object")
        contracts[name] = {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "projection": "json_schema_validation",
            "semantic_sha256": _digest(_schema_validation_projection(document)),
        }
    return contracts


def build_margin_overheat_freeze_manifest() -> dict[str, Any]:
    """Return the dedicated, comment-insensitive identity required before one-track freeze."""
    _production_constants_unchanged()
    from runners import a_short_weekly_pipeline as weekly_pipeline

    this_module = sys.modules[__name__]
    semantic_governance_sha256 = semantic_fingerprint()
    payload = {
        "semantic_governance_sha256": semantic_governance_sha256,
        "estimand_sha256": _digest({
            "track_id": TRACK_ID,
            "question_id": QUESTION_ID,
            "semantic_governance_sha256": semantic_governance_sha256,
        }),
        "schema_contracts": _freeze_schema_contracts(),
        "python_contracts": {
            "margin_overheat_track": epoch_mode.semantic_function_contract(
                this_module,
                (
                    "build_predicate_facts", "validate_predicate_facts", "_shadow_arm_spec",
                    "_shadow_trigger_percentile", "_governed_shadow_cash_factor",
                    "materialize_shadow_cash_control", "_arm_definitions", "_arm_capture_snapshot",
                    "_predicate_unavailable_reason",
                    "_validate_margin_capture", "_validate_stage_b_capture_admission",
                    "capture_margin_overheat_week", "_settlement_risk_evidence", "_settle_arm",
                    "_settle_capture", "_collect_source_bound_evidence", "_formal_decision",
                    "_risk_gate", "_cross_epoch_random_effects", "_simultaneous_winner",
                    "_adjudication_documents", "validate_stage_transition_receipt",
                    "build_stage_a_transition_receipt", "accept_stage_a_transition_receipt",
                    "register_stage_b_from_accepted_receipt", "_load_stage_b_admission",
                    "_stage_storage_root", "adjudicate_margin_overheat_cash_control",
                    "settle_margin_overheat_from_daily_cache",
                ),
            ),
            "weekly_cash_semantics": epoch_mode.semantic_function_contract(
                weekly_pipeline,
                (
                    "_normalise_margin_overheat_control", "_resolve_cash_factor_stack",
                    "_allocate_cash", "_allocate_cash_shadow",
                ),
            ),
        },
        "shared_track_id": TRACK_ID,
        "production_constants": {
            "percentile_threshold": production_margin.MARGIN_OVERHEAT_PERCENTILE_THRESHOLD,
            "cash_factor": production_margin.MARGIN_OVERHEAT_CASH_FACTOR,
            "production_effect_enabled": production_margin.MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED,
        },
        "boundary": {
            "comparison_only": True,
            "automatic_policy_switch": False,
            "direct_activation_requires_user_authorization": True,
        },
    }
    manifest = {
        "schema_name": "a_short_margin_overheat_cash_control_freeze_manifest",
        "schema_version": SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "payload": payload,
        "payload_sha256": _digest(payload),
        "production_unchanged": True,
    }
    _schema_validate(manifest, FREEZE_MANIFEST_SCHEMA_PATH)
    return manifest


def validate_margin_overheat_freeze_manifest(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise MarginOverheatCashControlError("margin-overheat freeze manifest must be an object")
    _schema_validate(dict(manifest), FREEZE_MANIFEST_SCHEMA_PATH)
    if _digest(manifest.get("payload")) != manifest.get("payload_sha256"):
        raise MarginOverheatCashControlError("margin-overheat freeze manifest payload digest does not match")
    _production_constants_unchanged()


def _freeze_component_fingerprint() -> str:
    return str(build_margin_overheat_freeze_manifest()["payload_sha256"])


def current_epoch_id() -> str:
    """Return a stable audit identity pre-freeze and a bound semantic identity after freeze."""
    return "epoch-" + epoch_mode.fingerprint_or_pre_freeze(
        TRACK_ID, _freeze_component_fingerprint
    )[:12]


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
    manifest = build_margin_overheat_freeze_manifest()
    validate_margin_overheat_freeze_manifest(manifest)
    return {
        "track_id": TRACK_ID,
        "requested_mode": FROZEN,
        "new_epoch_required": True,
        "clock_starts_only_after_durable_user_approval": True,
        "freeze_packet_identity": dict(freeze_packet_identity),
        "margin_overheat_freeze_manifest": manifest,
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
        preliminary_calendar_effective_weeks = _preliminary_calendar_effective_weeks()
        if trigger_effective_weeks < minimum_trigger_effective_weeks:
            evidence_status, clock_status = "insufficient_data", "running"
        elif calendar_effective_weeks < preliminary_calendar_effective_weeks:
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


def _build_adjudicated_state(*, calendar_effective_weeks: int, trigger_effective_weeks: int,
                             stage: str, comparison_verdict: str, reason: str) -> dict[str, Any]:
    """Knife4's only verdict-bearing state writer; Knife1's general entrypoint stays closed."""
    if comparison_verdict not in COMPARISON_VERDICTS or comparison_verdict == "not_evaluated":
        raise MarginOverheatCashControlError("adjudicated state requires a formal comparison verdict")
    if current_mode() != FROZEN:
        raise MarginOverheatCashControlError("adjudicated state requires the shared frozen epoch mode")
    _require_shared_clock_gate()
    if calendar_effective_weeks < 24:
        raise MarginOverheatCashControlError("adjudicated state requires a formal calendar checkpoint")
    base = build_state(
        calendar_effective_weeks=calendar_effective_weeks,
        trigger_effective_weeks=trigger_effective_weeks,
        stage=stage,
        mode=FROZEN,
    )
    if base["evidence_status"] == "insufficient_data":
        raise MarginOverheatCashControlError("adjudicated state requires the trigger opportunity floor")
    state = dict(base)
    state["comparison_verdict"] = comparison_verdict
    state["reason"] = reason
    _schema_validate(state, STATE_SCHEMA_PATH)
    return state


def _validate_adjudicated_state(state: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    if not isinstance(state, dict):
        raise MarginOverheatCashControlError("adjudicated state must be an object")
    _schema_validate(dict(state), STATE_SCHEMA_PATH)
    _production_constants_unchanged()
    if state.get("mode") != FROZEN or current_mode() != FROZEN:
        raise MarginOverheatCashControlError("adjudicated state requires the shared frozen epoch mode")
    _require_shared_clock_gate()
    if state.get("stage") != payload.get("stage") or \
            state.get("calendar_effective_weeks") != payload.get("calendar_effective_weeks") or \
            state.get("trigger_effective_weeks") != payload.get("trigger_effective_weeks"):
        raise MarginOverheatCashControlError("adjudicated state does not match source-bound evidence counts")
    if state.get("calendar_effective_weeks", 0) < 24 or \
            state.get("trigger_effective_weeks", 0) < _minimum_trigger_effective_weeks():
        raise MarginOverheatCashControlError("adjudicated state bypassed the formal calendar or trigger gate")
    if state.get("comparison_verdict") != payload.get("formal_verdict") or \
            state.get("comparison_verdict") == "not_evaluated":
        raise MarginOverheatCashControlError("adjudicated state comparison_verdict is not source-bound")


def stage_arm_ids(stage: str, governance: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    document = dict(governance or load_governance())
    validate_governance(document)
    if stage not in (STAGE_A, STAGE_B):
        raise MarginOverheatCashControlError("unknown comparison stage")
    section = document[stage]
    return (section["baseline"]["arm_id"],) + tuple(row["arm_id"] for row in section["challengers"])


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, numbers.Real)
        and math.isfinite(float(value))
    )


def _valid_date8(value: Any) -> bool:
    try:
        return bool(canonical_dates([value]))
    except (TypeError, ValueError):
        return False


def _predicate_source_digest(
    source_as_of: str,
    requested_dates: Sequence[str],
    ratios: Mapping[str, Any] | None,
) -> str:
    return _digest({
        "kind": "sequence19_exact_date_ratio_series",
        "source_as_of": str(source_as_of),
        "requested_dates": list(requested_dates),
        "ratios": None if ratios is None else [
            [date, ratios[date]] for date in requested_dates if date in ratios
        ],
    })


def _source_ratio_series(
    requested_dates: Sequence[str],
    ratios: Mapping[str, Any] | None,
) -> list[dict[str, Any]] | None:
    """Expose the digest-covered ratio series for read-side derivation checks."""
    if ratios is None:
        return None
    entries: list[dict[str, Any]] = []
    for date in requested_dates:
        if date not in ratios:
            continue
        value = ratios[date]
        if not _finite_number(value) or float(value) <= 0:
            return None
        entries.append({"date": str(date), "ratio": float(value)})
    return entries


def _source_receipt(source_as_of: str, source_digest: str) -> dict[str, str]:
    return {
        "kind": "sequence19_exact_date_ratio_series",
        "source_as_of": str(source_as_of),
        "source_digest": source_digest,
    }


def _predicate_artifact(
    *,
    source_as_of: str,
    requested_dates: Sequence[str],
    observed_session_count: int,
    coverage_complete: bool,
    unavailable_reason: str | None,
    ratios: Mapping[str, Any] | None = None,
    level_ratio: float | None = None,
    level_percentile: float | None = None,
    balance_yuan: float | None = None,
    denominator_float_mv_yuan: float | None = None,
    change_value: float | None = None,
    change_percentile: float | None = None,
    change_sample_count: int = 0,
) -> dict[str, Any]:
    requested = tuple(requested_dates)
    digest = _predicate_source_digest(source_as_of, requested, ratios)
    return {
        "schema_name": PREDICATE_SCHEMA_NAME,
        "schema_version": PREDICATE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "source_as_of": str(source_as_of),
        "window_start": requested[-1] if requested else None,
        "window_end": requested[0] if requested else None,
        "requested_session_count": len(requested),
        "observed_session_count": int(observed_session_count),
        "coverage_complete": bool(coverage_complete),
        "warmup_session_count": CHANGE_RATE_LOOKBACK_SESSIONS,
        "level": {
            "ratio": level_ratio,
            "percentile": level_percentile,
            "balance_yuan": balance_yuan,
            "denominator_float_mv_yuan": denominator_float_mv_yuan,
        },
        "change_rate_20d": {
            "lookback_sessions": CHANGE_RATE_LOOKBACK_SESSIONS,
            "value": change_value,
            "percentile": change_percentile,
            "sample_count": int(change_sample_count),
        },
        "definition_summary": copy.deepcopy(DEFINITION_SUMMARY),
        "source_references": list(PREDICATE_SOURCE_REFERENCES),
        "source_ratio_series": _source_ratio_series(requested, ratios),
        "source_digest": digest,
        "source_receipt": _source_receipt(source_as_of, digest),
        "status": "available" if coverage_complete else "unavailable",
        "unavailable_reason": unavailable_reason,
    }


def _validate_source_receipt(
    receipt: Mapping[str, Any] | None,
    *,
    source_as_of: str,
    source_digest: str,
) -> None:
    if not isinstance(receipt, Mapping):
        raise MarginOverheatCashControlError("source receipt is required for shadow admission")
    if receipt.get("kind") != "sequence19_exact_date_ratio_series":
        raise MarginOverheatCashControlError("source receipt kind is not sequence19 exact-date ratio")
    if receipt.get("source_as_of") != source_as_of:
        raise MarginOverheatCashControlError("source receipt is not bound to source_as_of")
    if receipt.get("source_digest") != source_digest:
        raise MarginOverheatCashControlError("source receipt digest does not match predicate facts")


def validate_predicate_facts(
    facts: Mapping[str, Any],
    *,
    expected_source_digest: str | None = None,
) -> None:
    """Validate the structured producer output before any shadow allocation."""
    if not isinstance(facts, dict):
        raise MarginOverheatCashControlError("margin-overheat predicate facts must be an object")
    _schema_validate(facts, PREDICATE_SCHEMA_PATH)
    if tuple(facts["source_references"]) != PREDICATE_SOURCE_REFERENCES:
        raise MarginOverheatCashControlError("predicate source references are outside the dedicated contract")
    _validate_source_receipt(
        facts["source_receipt"],
        source_as_of=facts["source_as_of"],
        source_digest=facts["source_digest"],
    )
    if expected_source_digest is not None and facts["source_digest"] != expected_source_digest:
        raise MarginOverheatCashControlError("predicate source digest does not match source receipt")
    requested = facts["requested_session_count"]
    observed = facts["observed_session_count"]
    if observed > requested:
        raise MarginOverheatCashControlError("predicate observed sessions exceed requested sessions")
    if (facts["window_end"] != facts["source_as_of"]
            and facts.get("unavailable_reason") != "source_clock_mismatch"):
        raise MarginOverheatCashControlError(
            "predicate window end is not bound to source_as_of"
        )
    if (facts["window_start"] is not None and facts["window_end"] is not None
            and facts["window_start"] > facts["window_end"]):
        raise MarginOverheatCashControlError("predicate window dates are reversed")
    level = facts["level"]
    change = facts["change_rate_20d"]
    numeric_values = (
        ("level.ratio", level["ratio"]),
        ("level.percentile", level["percentile"]),
        ("level.balance_yuan", level["balance_yuan"]),
        ("level.denominator_float_mv_yuan", level["denominator_float_mv_yuan"]),
        ("change_rate_20d.value", change["value"]),
        ("change_rate_20d.percentile", change["percentile"]),
    )
    for path, value in numeric_values:
        if value is not None and not _finite_number(value):
            raise MarginOverheatCashControlError(
                f"predicate {path} must be finite"
            )
    source_ratio_series = facts["source_ratio_series"]
    if source_ratio_series is not None:
        source_dates: list[str] = []
        source_ratios: dict[str, float] = {}
        for entry in source_ratio_series:
            date = str(entry["date"])
            if date in source_ratios:
                raise MarginOverheatCashControlError(
                    "predicate source ratio series contains duplicate dates"
                )
            source_dates.append(date)
            source_ratios[date] = float(entry["ratio"])
        if _predicate_source_digest(facts["source_as_of"], source_dates, source_ratios) != facts["source_digest"]:
            raise MarginOverheatCashControlError(
                "predicate source digest does not match source ratio series"
            )
    else:
        source_dates = []
        source_ratios = {}
    if facts["coverage_complete"]:
        if observed != requested:
            raise MarginOverheatCashControlError(
                "available predicate facts do not cover every requested session"
            )
        if facts["status"] != "available" or facts["unavailable_reason"] is not None:
            raise MarginOverheatCashControlError("available predicate facts carry an unavailable status")
        if any(level[key] is None for key in (
                "ratio", "percentile", "balance_yuan", "denominator_float_mv_yuan")):
            raise MarginOverheatCashControlError("available predicate facts are incomplete")
        if change["value"] is None or change["percentile"] is None:
            raise MarginOverheatCashControlError("available change-rate predicate facts are incomplete")
        if change["sample_count"] != requested - CHANGE_RATE_LOOKBACK_SESSIONS:
            raise MarginOverheatCashControlError("change-rate sample count is not bound to the warm-up window")
        if abs(level["ratio"] * level["denominator_float_mv_yuan"] - level["balance_yuan"]) > (
                1e-6 * level["balance_yuan"]):
            raise MarginOverheatCashControlError("predicate ratio does not equal balance over denominator")
        if (source_ratio_series is None
                or len(source_dates) != requested
                or source_dates[0] != facts["window_end"]
                or source_dates[-1] != facts["window_start"]):
            raise MarginOverheatCashControlError(
                "available predicate facts lack the complete source ratio series"
            )
        if facts["source_as_of"] not in source_ratios:
            raise MarginOverheatCashControlError(
                "available predicate facts lack the source_as_of ratio"
            )
        source_level = source_ratios[facts["source_as_of"]]
        if not math.isclose(level["ratio"], source_level, rel_tol=0.0, abs_tol=1e-12):
            raise MarginOverheatCashControlError(
                "predicate level.ratio is not derived from source ratios"
            )
        source_changes = _change_rate_series(source_dates, source_ratios)
        if not source_changes or facts["source_as_of"] not in source_changes:
            raise MarginOverheatCashControlError(
                "available predicate facts lack the source change-rate series"
            )
        source_change = source_changes[facts["source_as_of"]]
        if not math.isclose(change["value"], source_change, rel_tol=0.0, abs_tol=1e-12):
            raise MarginOverheatCashControlError(
                "predicate change_rate_20d.value is not derived from source ratios"
            )
        expected_level_percentile = percentile_rank(source_ratios.values(), source_level)
        expected_change_percentile = percentile_rank(source_changes.values(), source_change)
        if (expected_level_percentile is None
                or not math.isclose(level["percentile"], expected_level_percentile,
                                    rel_tol=0.0, abs_tol=1e-12)):
            raise MarginOverheatCashControlError(
                "predicate level.percentile is not derived from source ratios"
            )
        if (expected_change_percentile is None
                or not math.isclose(change["percentile"], expected_change_percentile,
                                    rel_tol=0.0, abs_tol=1e-12)):
            raise MarginOverheatCashControlError(
                "predicate change_rate_20d.percentile is not derived from source ratios"
            )
    else:
        if facts["status"] != "unavailable" or facts["unavailable_reason"] is None:
            raise MarginOverheatCashControlError("unavailable predicate facts lack a fail-closed reason")
        if any(level[key] is not None for key in (
                "ratio", "percentile", "balance_yuan", "denominator_float_mv_yuan")):
            raise MarginOverheatCashControlError("unavailable predicate facts carry level values")
        if change["value"] is not None or change["percentile"] is not None or change["sample_count"]:
            raise MarginOverheatCashControlError("unavailable predicate facts carry change-rate values")


def _change_rate_series(
    requested_dates: Sequence[str],
    ratios: Mapping[str, Any],
) -> dict[str, float] | None:
    if len(requested_dates) <= CHANGE_RATE_LOOKBACK_SESSIONS:
        return None
    values: dict[str, float] = {}
    for index, date in enumerate(requested_dates[:-CHANGE_RATE_LOOKBACK_SESSIONS]):
        older_date = requested_dates[index + CHANGE_RATE_LOOKBACK_SESSIONS]
        current = ratios.get(date)
        older = ratios.get(older_date)
        if (not _finite_number(current) or not _finite_number(older)
                or float(current) <= 0 or float(older) <= 0):
            return None
        values[date] = float(current) / float(older) - 1.0
    return values


def build_predicate_facts(
    margin_rows: Any,
    denominator_rows: Any,
    *,
    requested_dates: Iterable[Any],
    source_as_of: str | None = None,
) -> dict[str, Any]:
    """Build the knife-2 structured level/change-rate producer output.

    The two rows are the existing sequence-19 ``pro.margin`` and
    ``index_dailybasic.float_mv`` legs.  No endpoint, fetcher, or production
    output is introduced here; an exact-date failure returns an unavailable
    artifact and never a partial predicate.
    """
    try:
        requested = canonical_dates(requested_dates)
    except (TypeError, ValueError) as exc:
        raise MarginOverheatCashControlError("predicate requested dates are not canonical") from exc
    if not requested:
        raise MarginOverheatCashControlError("predicate requested dates cannot be empty")
    source_as_of = str(source_as_of or requested[0])
    if not _valid_date8(source_as_of):
        raise MarginOverheatCashControlError("predicate source_as_of is not a canonical date")
    if source_as_of != requested[0]:
        facts = _predicate_artifact(
            source_as_of=source_as_of,
            requested_dates=requested,
            observed_session_count=0,
            coverage_complete=False,
            unavailable_reason="source_clock_mismatch",
        )
        validate_predicate_facts(facts)
        return facts
    if len(requested) < production_margin.MARGIN_OVERHEAT_MIN_WINDOW_SESSIONS:
        facts = _predicate_artifact(
            source_as_of=source_as_of,
            requested_dates=requested,
            observed_session_count=0,
            coverage_complete=False,
            unavailable_reason="rolling_window_below_floor",
        )
        validate_predicate_facts(facts)
        return facts

    series = production_margin.margin_ratio_series(
        margin_rows,
        denominator_rows,
        requested_dates=requested,
    )
    observed = int((series.get("numerator") or {}).get("observed_count") or 0)
    if not series.get("coverage_complete"):
        facts = _predicate_artifact(
            source_as_of=source_as_of,
            requested_dates=requested,
            observed_session_count=observed,
            coverage_complete=False,
            unavailable_reason="coverage_incomplete",
        )
        validate_predicate_facts(facts)
        return facts

    ratios = {str(date): float(value) for date, value in series["ratios"].items()}
    if any(not _finite_number(value) or value <= 0 for value in ratios.values()):
        facts = _predicate_artifact(
            source_as_of=source_as_of,
            requested_dates=requested,
            observed_session_count=observed,
            coverage_complete=False,
            unavailable_reason="non_finite_or_non_positive_ratio",
            ratios=ratios,
        )
        validate_predicate_facts(facts)
        return facts
    changes = _change_rate_series(requested, ratios)
    if not changes or requested[0] not in changes:
        facts = _predicate_artifact(
            source_as_of=source_as_of,
            requested_dates=requested,
            observed_session_count=observed,
            coverage_complete=False,
            unavailable_reason="twenty_session_warmup_unavailable",
            ratios=ratios,
        )
        validate_predicate_facts(facts)
        return facts

    current_ratio = ratios[requested[0]]
    current_change = changes[requested[0]]
    level_percentile = percentile_rank(ratios.values(), current_ratio)
    change_percentile = percentile_rank(changes.values(), current_change)
    if level_percentile is None or change_percentile is None:
        facts = _predicate_artifact(
            source_as_of=source_as_of,
            requested_dates=requested,
            observed_session_count=observed,
            coverage_complete=False,
            unavailable_reason="percentile_unavailable",
            ratios=ratios,
        )
        validate_predicate_facts(facts)
        return facts

    numerator = series["numerator"]["totals"]
    denominator = series["float_mv"]
    facts = _predicate_artifact(
        source_as_of=source_as_of,
        requested_dates=requested,
        observed_session_count=observed,
        coverage_complete=True,
        unavailable_reason=None,
        ratios=ratios,
        level_ratio=current_ratio,
        level_percentile=float(level_percentile),
        balance_yuan=float(numerator[requested[0]]),
        denominator_float_mv_yuan=float(denominator[requested[0]]),
        change_value=float(current_change),
        change_percentile=float(change_percentile),
        change_sample_count=len(changes),
    )
    validate_predicate_facts(facts)
    return facts


def _week_endpoints(requested_dates: Sequence[str]) -> tuple[str, ...]:
    by_week: dict[tuple[int, int], str] = {}
    for date in requested_dates:
        parsed = datetime.strptime(date, "%Y%m%d")
        key = (parsed.isocalendar().year, parsed.isocalendar().week)
        by_week[key] = max(by_week.get(key, date), date)
    return tuple(sorted(by_week.values()))


def _rolling_window_start(date: str) -> str:
    parsed = datetime.strptime(date, "%Y%m%d")
    try:
        return parsed.replace(year=parsed.year - production_margin.MARGIN_OVERHEAT_WINDOW_YEARS).strftime("%Y%m%d")
    except ValueError:
        return parsed.replace(
            year=parsed.year - production_margin.MARGIN_OVERHEAT_WINDOW_YEARS,
            day=28,
        ).strftime("%Y%m%d")


def _longest_trigger_streak(rows: Sequence[Mapping[str, Any]], field: str, threshold: float) -> int:
    longest = current = 0
    previous: datetime | None = None
    for row in rows:
        if row.get("status") != "evaluable":
            current = 0
            previous = None
            continue
        parsed = datetime.strptime(row["week_end"], "%Y%m%d")
        adjacent = previous is not None and (parsed - previous).days == 7
        if float(row[field]) >= threshold:
            current = current + 1 if current and adjacent else 1
            longest = max(longest, current)
        else:
            current = 0
        previous = parsed
    return longest


def _replay_arm_summary(
    arm_id: str,
    criterion_id: str,
    field: str,
    threshold: float,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_year: dict[str, int] = {}
    count = 0
    for row in rows:
        if row.get("status") != "evaluable" or float(row[field]) < threshold:
            continue
        count += 1
        year = str(datetime.strptime(row["week_end"], "%Y%m%d").isocalendar().year)
        by_year[year] = by_year.get(year, 0) + 1
    return {
        "arm_id": arm_id,
        "criterion_id": criterion_id,
        "threshold": threshold,
        "trigger_week_count": count,
        "longest_consecutive_trigger_weeks": _longest_trigger_streak(rows, field, threshold),
        "trigger_weeks_by_year": dict(sorted(by_year.items())),
    }


def build_replay_frequency(
    margin_rows: Any,
    denominator_rows: Any,
    *,
    requested_dates: Iterable[Any],
    source_as_of: str | None = None,
    source_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish the provisional, non-forward replay frequency for all stage-A arms."""
    try:
        requested = canonical_dates(requested_dates)
    except (TypeError, ValueError) as exc:
        raise MarginOverheatCashControlError("replay requested dates are not canonical") from exc
    if not requested:
        raise MarginOverheatCashControlError("replay requested dates cannot be empty")
    source_as_of = str(source_as_of or requested[0])
    if not _valid_date8(source_as_of):
        raise MarginOverheatCashControlError("replay source_as_of is not a canonical date")
    series = production_margin.margin_ratio_series(
        margin_rows,
        denominator_rows,
        requested_dates=requested,
    )
    ratios = None
    observed = int((series.get("numerator") or {}).get("observed_count") or 0)
    if series.get("coverage_complete"):
        ratios = {str(date): float(value) for date, value in series["ratios"].items()}
    digest = _predicate_source_digest(source_as_of, requested, ratios)
    if source_receipt is not None:
        _validate_source_receipt(source_receipt, source_as_of=source_as_of, source_digest=digest)
    arm_zeros = [
        _replay_arm_summary(arm_id, criterion_id, field, threshold, [])
        for arm_id, criterion_id, field, threshold in REPLAY_ARM_SPECS
    ]
    base = {
        "schema_name": REPLAY_SCHEMA_NAME,
        "schema_version": PREDICATE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "source_as_of": source_as_of,
        "window_start": requested[-1],
        "window_end": requested[0],
        "source_digest": digest,
        "source_receipt": None if source_receipt is None else dict(source_receipt),
        "comparison_only": True,
        "exploratory": True,
        "forward_eligible": False,
        "week_count": 0,
        "evaluable_week_count": 0,
        "unavailable_week_count": 0,
        "unavailable_breakdown": {"warm_up": 0, "source_gap": 0},
        "by_arm": arm_zeros,
        "status": "NOT_VERIFIED",
        "not_verified": [],
    }
    if source_as_of != requested[0]:
        base["not_verified"].append("source_as_of is not bound to the newest requested session")
    if source_receipt is None:
        base["not_verified"].append("no source receipt was supplied; replay is not forward evidence")
    if ratios is None:
        base["not_verified"].append("margin or denominator series did not reconcile exactly")
        _schema_validate(base, REPLAY_SCHEMA_PATH)
        return base
    if any(not _finite_number(value) or value <= 0 for value in ratios.values()):
        base["not_verified"].append("ratio series contains a non-finite or non-positive value")
        _schema_validate(base, REPLAY_SCHEMA_PATH)
        return base
    changes = _change_rate_series(requested, ratios)
    if not changes:
        base["not_verified"].append("the requested source series lacks the twenty-session warm-up")
        _schema_validate(base, REPLAY_SCHEMA_PATH)
        return base

    week_rows: list[dict[str, Any]] = []
    for week_end in _week_endpoints(requested):
        start = _rolling_window_start(week_end)
        trailing = [date for date in requested if start <= date <= week_end]
        row: dict[str, Any] = {"week_end": week_end, "status": "unavailable"}
        if len(trailing) < production_margin.MARGIN_OVERHEAT_MIN_WINDOW_SESSIONS:
            row["reason"] = "warm_up"
        elif any(date not in changes for date in trailing):
            row["reason"] = "source_gap"
        else:
            level = percentile_rank(
                (ratios[date] for date in trailing), ratios[week_end]
            )
            change = percentile_rank(
                (changes[date] for date in trailing), changes[week_end]
            )
            if level is None or change is None:
                row["reason"] = "source_gap"
            else:
                row.update({
                    "status": "evaluable",
                    "level_percentile": float(level),
                    "change_rate_percentile": float(change),
                })
        week_rows.append(row)

    valid_rows = [row for row in week_rows if row["status"] == "evaluable"]
    base["week_count"] = len(week_rows)
    base["evaluable_week_count"] = len(valid_rows)
    base["unavailable_week_count"] = len(week_rows) - len(valid_rows)
    base["unavailable_breakdown"] = {
        "warm_up": sum(row.get("reason") == "warm_up" for row in week_rows),
        "source_gap": sum(row.get("reason") == "source_gap" for row in week_rows),
    }
    base["by_arm"] = [
        _replay_arm_summary(arm_id, criterion_id, field, threshold, week_rows)
        for arm_id, criterion_id, field, threshold in REPLAY_ARM_SPECS
    ]
    if not valid_rows:
        base["not_verified"].append("no week carried a complete rolling three-year predicate window")
    if base["unavailable_week_count"]:
        base["not_verified"].append("warm-up or source-gap weeks were excluded rather than shortened")
    if base["not_verified"]:
        base["status"] = "NOT_VERIFIED" if source_receipt is None else "PARTIAL"
    else:
        base["status"] = "COMPLETE"
    _schema_validate(base, REPLAY_SCHEMA_PATH)
    return base


def _shadow_arm_spec(
        arm_id: str, *, stage: str = STAGE_A,
        stage_b_supported_arm_id: str | None = None,
) -> tuple[str, str | None, str | None, float | None]:
    """Return the governed trigger specification for one staged shadow arm."""
    if stage == STAGE_A:
        if arm_id == "baseline":
            return "no_margin_discount", None, None, None
        for candidate, criterion_id, field, threshold in REPLAY_ARM_SPECS:
            if candidate == arm_id:
                return criterion_id, field, field, threshold
        raise MarginOverheatCashControlError("unknown stage-A shadow arm")
    if stage != STAGE_B:
        raise MarginOverheatCashControlError("unknown shadow comparison stage")
    if arm_id not in stage_arm_ids(STAGE_B):
        raise MarginOverheatCashControlError("unknown stage-B shadow arm")
    if arm_id == "baseline":
        return "stage_a_supported_criterion", None, None, None
    if stage_b_supported_arm_id not in stage_arm_ids(STAGE_A)[1:]:
        raise MarginOverheatCashControlError(
            "stage-B shadow arm lacks its accepted Stage-A criterion"
        )
    _criterion_id, field, _unused, threshold = _shadow_arm_spec(
        stage_b_supported_arm_id, stage=STAGE_A
    )
    return "stage_a_supported_criterion", field, field, threshold


def _shadow_trigger_percentile(
        facts: Mapping[str, Any], arm_id: str, *, stage: str = STAGE_A,
        stage_b_supported_arm_id: str | None = None,
) -> float:
    if stage == STAGE_B:
        if arm_id not in stage_arm_ids(STAGE_B)[1:]:
            raise MarginOverheatCashControlError("unknown stage-B shadow arm")
        if stage_b_supported_arm_id not in stage_arm_ids(STAGE_A)[1:]:
            raise MarginOverheatCashControlError(
                "stage-B shadow arm lacks its accepted Stage-A criterion"
            )
        return _shadow_trigger_percentile(
            facts, stage_b_supported_arm_id, stage=STAGE_A
        )
    if stage != STAGE_A:
        raise MarginOverheatCashControlError("unknown shadow comparison stage")
    if arm_id in {"change_rate_p90", "change_rate_p95"}:
        value = facts["change_rate_20d"]["percentile"]
    else:
        raise MarginOverheatCashControlError("unknown stage-A shadow arm")
    if not _finite_number(value):
        raise MarginOverheatCashControlError(
            "available predicate facts lack the shadow arm percentile"
        )
    return float(value)


def _governed_shadow_cash_factor(
        arm_id: str, triggered: bool | None, *, stage: str = STAGE_A,
) -> float:
    """Read one staged, comparison-only factor from the governed arm contract."""
    governance = load_governance()
    try:
        section = governance[stage]
        baseline_factor = section["baseline"]["margin_cash_factor"]
    except (KeyError, TypeError) as exc:
        raise MarginOverheatCashControlError(
            "governance is missing staged shadow cash factors"
        ) from exc
    if not _finite_number(baseline_factor) or not 0 < float(baseline_factor) <= 1:
        raise MarginOverheatCashControlError(
            "governance staged baseline shadow cash factor is invalid"
        )
    if stage == STAGE_A:
        try:
            measurement_factor = section["measurement_cash_factor"]
        except (KeyError, TypeError) as exc:
            raise MarginOverheatCashControlError(
                "governance is missing the Stage-A measurement factor"
            ) from exc
        if not _finite_number(measurement_factor) or not 0 < float(measurement_factor) <= 1:
            raise MarginOverheatCashControlError(
                "governance Stage-A measurement factor is invalid"
            )
    elif stage != STAGE_B:
        raise MarginOverheatCashControlError("unknown shadow comparison stage")
    if triggered is not True:
        return float(baseline_factor)
    try:
        challengers = section["challengers"]
        configured = next(
            arm["margin_cash_factor"] for arm in challengers
            if arm.get("arm_id") == arm_id
        )
    except (KeyError, StopIteration, TypeError) as exc:
        raise MarginOverheatCashControlError(
            "governance is missing the triggered staged arm cash factor"
        ) from exc
    if not _finite_number(configured) or not 0 < float(configured) <= 1:
        raise MarginOverheatCashControlError(
            "governance triggered staged arm cash factor is invalid"
        )
    if stage == STAGE_A and not math.isclose(
            float(configured), float(measurement_factor), rel_tol=0.0, abs_tol=1e-12
    ):
        raise MarginOverheatCashControlError(
            "triggered Stage-A arm cash factor disagrees with measurement factor"
        )
    return float(configured)


def materialize_shadow_cash_control(
    predicate_facts: Mapping[str, Any],
    *,
    arm_id: str,
    stage: str = STAGE_A,
    stage_b_supported_arm_id: str | None = None,
    reports: list,
    available_cash: Any,
    pre_holiday_control: Mapping[str, Any] | None = None,
    new_exposure_capacity: Any | None = None,
    as_of: str,
    source_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply one staged arm to a copied pre-margin allocation seam.

    This is the only knife-2 consumer.  It calls the production cash stack and
    allocator, carries no account context, and returns an in-memory shadow
    result; persistence and settlement belong to knife 3.
    """
    if not isinstance(source_receipt, Mapping):
        raise MarginOverheatCashControlError(
            "shadow consumer requires an explicit source receipt"
        )
    if stage not in (STAGE_A, STAGE_B):
        raise MarginOverheatCashControlError("shadow consumer comparison stage is invalid")
    if arm_id not in stage_arm_ids(stage):
        if stage == STAGE_A:
            raise MarginOverheatCashControlError("unknown stage-A shadow arm")
        raise MarginOverheatCashControlError("shadow consumer arm is not governed for its stage")
    if stage == STAGE_B and stage_b_supported_arm_id not in stage_arm_ids(STAGE_A)[1:]:
        raise MarginOverheatCashControlError(
            "stage-B shadow consumer lacks its accepted Stage-A criterion"
        )
    facts = dict(predicate_facts)
    validate_predicate_facts(
        facts,
        expected_source_digest=(
            source_receipt.get("source_digest")
            if isinstance(source_receipt, Mapping) else None
        ),
    )
    if str(as_of) != facts["source_as_of"]:
        raise MarginOverheatCashControlError("shadow consumer as_of is not bound to predicate source_as_of")
    model_cash_cny = _model_cash_cny()
    if (not _finite_number(available_cash)
            or abs(float(available_cash) - model_cash_cny) > 1e-9):
        raise MarginOverheatCashControlError(
            "shadow consumer available_cash must equal governance model cash"
        )
    receipt = dict(source_receipt)
    _validate_source_receipt(
        receipt,
        source_as_of=facts["source_as_of"],
        source_digest=facts["source_digest"],
    )
    validate_source_references(facts["source_references"])
    criterion_id, _field, _unused, threshold = _shadow_arm_spec(
        arm_id, stage=stage, stage_b_supported_arm_id=stage_b_supported_arm_id
    )
    triggered: bool | None
    if arm_id == "baseline":
        triggered = False
    elif facts["status"] != "available":
        triggered = None
    else:
        triggered = _shadow_trigger_percentile(
            facts, arm_id, stage=stage, stage_b_supported_arm_id=stage_b_supported_arm_id
        ) >= float(threshold)
    shadow_factor = _governed_shadow_cash_factor(arm_id, triggered, stage=stage)
    margin_control = {
        "source_as_of": facts["source_as_of"],
        "source_path": PREDICATE_SOURCE_REFERENCES[0],
        "percentile": facts["level"]["percentile"],
        "ratio": facts["level"]["ratio"],
        "balance_yuan": facts["level"]["balance_yuan"],
        "denominator_float_mv_yuan": facts["level"]["denominator_float_mv_yuan"],
        "window_start": facts["window_start"],
        "window_end": facts["window_end"],
        "requested_session_count": facts["requested_session_count"],
        "observed_session_count": facts["observed_session_count"],
        "coverage_complete": facts["coverage_complete"],
        "production_effect_enabled": False,
        "predicate_triggered": bool(triggered) if triggered is not None else False,
        "cash_factor": shadow_factor,
        "reason": (
            "baseline"
            if arm_id == "baseline"
            else "no_count"
            if triggered is None
            else "comparison_margin_overheat_triggered"
            if triggered
            else "comparison_margin_overheat_not_triggered"
        ),
    }
    core_control = dict(margin_control)
    # Let the production normalizer derive its own (currently disabled) reason
    # and predicate fields.  The comparison trigger/factor is applied only by
    # the private shadow seam after that production validation succeeds.
    core_control.pop("cash_factor")
    core_control.pop("predicate_triggered")
    core_control.pop("reason")
    shadow_reports = copy.deepcopy(reports)
    from runners import a_short_weekly_pipeline as weekly_pipeline

    allocation_summary = weekly_pipeline._allocate_cash_shadow(
        shadow_reports,
        available_cash,
        new_exposure_capacity,
        pre_holiday_control=(
            None if pre_holiday_control is None else dict(pre_holiday_control)
        ),
        margin_overheat_control=core_control,
        shadow_cash_factor=shadow_factor,
        as_of=str(as_of),
    )
    if not isinstance(allocation_summary, dict) or not isinstance(
            allocation_summary.get("cash_factor_stack"), dict):
        raise MarginOverheatCashControlError("shadow consumer did not use the shared allocation core")
    cash_factor_stack = copy.deepcopy(allocation_summary["cash_factor_stack"])
    comparison_margin_overheat_control = {
        "arm_id": arm_id,
        "criterion_id": criterion_id,
        "predicate_triggered": triggered,
        "cash_factor": shadow_factor,
        "reason": margin_control["reason"],
    }
    result = {
        "schema_name": "a_short_margin_overheat_cash_control_shadow",
        "schema_version": PREDICATE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "arm_id": arm_id,
        "criterion_id": criterion_id,
        "status": "evaluable" if triggered is not None else "no_count",
        "predicate_triggered": triggered,
        "shadow_cash_factor": shadow_factor,
        "source_digest": facts["source_digest"],
        "source_receipt": receipt,
        "cash_factor_stack": cash_factor_stack,
        "allocation_summary": allocation_summary,
        "comparison_margin_overheat_control": comparison_margin_overheat_control,
        "shadow_reports": shadow_reports,
    }
    _schema_validate(result, ROOT / "schemas" / "a_short_margin_overheat_cash_control_shadow.schema.json")
    return result


# ---------------------------------------------------------------------------
# Knife 3: weekly capture, settlement, and the private-to-public seam.
#
# The functions below deliberately keep all ticker/arm/NAV material in the
# dedicated private root.  The weekly runner supplies an already validated
# PublishedWeeklyBundle; this module therefore never turns an arbitrary path
# into an official M6.7 source.  Settlement accepts only an existing JSON
# daily cache and has no provider fallback.


def _knife3_boundary(governance: Mapping[str, Any] | None = None) -> dict[str, Any]:
    document = dict(governance or load_governance())
    validate_governance(document)
    return copy.deepcopy(document["boundary"])


def _private_root(root: str | Path) -> Path:
    if root is None:
        raise MarginOverheatCashControlError("margin-overheat private root is required")
    path = Path(root).resolve()
    if path == ROOT or any(part.lower() in {"result", "research"} for part in path.parts):
        raise MarginOverheatCashControlError(
            "margin-overheat private root may not be a published result or research path"
        )
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return path
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", "--", str(relative)],
            capture_output=True, check=False,
        )
    except OSError as exc:
        raise MarginOverheatCashControlError(
            "cannot prove margin-overheat private root is gitignored"
        ) from exc
    if result.returncode != 0:
        raise MarginOverheatCashControlError(
            "margin-overheat private root is not a provably private path"
        )
    return path


def _private_journal_dir(root: Path) -> Path:
    return root / ".artifact_set_journal"


def _recover_private_artifact_set(root: Path) -> None:
    from engine.a_short_artifact_set_transaction import recover

    try:
        recover(_private_journal_dir(root))
    except Exception as exc:
        raise MarginOverheatCashControlError(
            "margin-overheat private artifact set recovery failed"
        ) from exc


def _json_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                           indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MarginOverheatCashControlError(
            "margin-overheat private artifact contains non-JSON data"
        ) from exc


def _load_private_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarginOverheatCashControlError(
            f"margin-overheat {label} is unreadable"
        ) from exc


def _sha256(value: Any) -> str:
    return _digest(value)


def _require_sha(value: Any, label: str) -> str:
    text = str(value or "")
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise MarginOverheatCashControlError(f"margin-overheat {label} must be a lowercase sha256")
    return text


def _require_date8(value: Any, label: str) -> str:
    text = str(value or "")
    if not _valid_date8(text):
        raise MarginOverheatCashControlError(f"margin-overheat {label} must be a canonical date")
    return text


def _assert_finite_json(value: Any, path: str = "artifact") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise MarginOverheatCashControlError(f"{path} contains a non-finite number")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_finite_json(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_finite_json(child, f"{path}[{index}]")


def _cache_document(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MarginOverheatCashControlError("approved daily cache must be an object")
    document = copy.deepcopy(dict(value))
    _assert_finite_json(document, "daily_cache")
    _schema_validate(document, DAILY_CACHE_SCHEMA_PATH)
    return document


def load_margin_overheat_daily_cache(path: str | Path) -> dict[str, Any]:
    """Read the already approved daily cache; this function never calls a provider."""
    cache_path = Path(path).resolve()
    if not cache_path.is_file():
        raise MarginOverheatCashControlError("approved daily cache is unavailable")
    try:
        document = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarginOverheatCashControlError("approved daily cache is unreadable") from exc
    return _cache_document(document)


def _cache_rows(document: Mapping[str, Any]) -> tuple[list[str], dict[tuple[str, str], dict[str, Any]]]:
    rows = document.get("stocks")
    if not isinstance(rows, list):
        raise MarginOverheatCashControlError("approved daily cache stocks are malformed")
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise MarginOverheatCashControlError("approved daily cache contains a non-object stock row")
        code = str(raw.get("ts_code") or "")
        date = _require_date8(raw.get("trade_date"), "daily cache trade_date")
        if not code:
            raise MarginOverheatCashControlError("approved daily cache stock row lacks ts_code")
        clean = {
            "open": raw.get("open"),
            "close": raw.get("close"),
            "adj_factor": raw.get("adj_factor"),
            "adj_factor_observed": raw.get("adj_factor_observed"),
            "adj_factor_source": raw.get("adj_factor_source"),
            "corporate_action_verified": raw.get("corporate_action_verified"),
        }
        key = (code, date)
        if key in lookup and lookup[key] != clean:
            raise MarginOverheatCashControlError(
                "approved daily cache has conflicting duplicate stock rows"
            )
        lookup[key] = clean
    return sorted({date for _code, date in lookup}), lookup


def _valid_qfq_row(row: Mapping[str, Any] | None) -> bool:
    if not isinstance(row, Mapping):
        return False
    if any(not _finite_number(row.get(key)) or float(row[key]) <= 0
           for key in ("open", "close", "adj_factor")):
        return False
    if row.get("adj_factor_observed") is not True:
        return False
    if not str(row.get("adj_factor_source") or ""):
        return False
    return True


def _candidate_snapshots(candidates: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise MarginOverheatCashControlError("margin-overheat candidates must be a list")
    snapshots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise MarginOverheatCashControlError("margin-overheat candidate is not an object")
        code = str(candidate.get("ts_code") or "")
        if not code or code in seen:
            raise MarginOverheatCashControlError("margin-overheat candidate set has a duplicate or empty ts_code")
        if not _finite_number(candidate.get("close")) or float(candidate["close"]) <= 0:
            raise MarginOverheatCashControlError("margin-overheat candidate close must be finite and positive")
        seen.add(code)
        snapshots.append({
            "ts_code": code,
            "name": str(candidate.get("name") or ""),
            "close": float(candidate["close"]),
        })
    snapshots.sort(key=lambda row: row["ts_code"])
    return snapshots, _digest(snapshots)


def _selection_plan_snapshot(reports: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(reports, Sequence) or isinstance(reports, (str, bytes)):
        raise MarginOverheatCashControlError("official M6.7 reports must be a list")
    result = []
    seen: set[str] = set()
    for report in reports:
        if not isinstance(report, Mapping):
            raise MarginOverheatCashControlError("official M6.7 report is not an object")
        code = str(report.get("ts_code") or "")
        if not code or code in seen:
            raise MarginOverheatCashControlError("official M6.7 selection plan has a duplicate or empty ts_code")
        seen.add(code)
        table = report.get("m67", {}).get("table", {}) if isinstance(report.get("m67"), Mapping) else {}
        plan = (((report.get("machine") or {}).get("entry_exit_size_star") or {}).get("plan")
                if isinstance(report.get("machine"), Mapping) else None)
        result.append({
            "ts_code": code,
            "operation": str(table.get("操作") or table.get("operation") or ""),
            "shares": (plan or {}).get("shares", table.get("股数")),
            "cash_budget_used": (plan or {}).get("cash_budget_used"),
        })
    return result


def _frozen_positions_from_reports(reports: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for report in reports:
        if not isinstance(report, Mapping):
            continue
        code = str(report.get("ts_code") or "")
        table = report.get("m67", {}).get("table", {}) if isinstance(report.get("m67"), Mapping) else {}
        operation = str(table.get("操作") or table.get("operation") or "")
        plan = (((report.get("machine") or {}).get("entry_exit_size_star") or {}).get("plan")
                if isinstance(report.get("machine"), Mapping) else None)
        if operation not in {"建仓", "build", "open", "entry"} or not isinstance(plan, Mapping):
            continue
        if code in seen:
            raise MarginOverheatCashControlError("official M6.7 selection plan repeats a build symbol")
        shares = plan.get("allocated_shares", plan.get("shares", table.get("股数")))
        capital = plan.get("cash_budget_used")
        entry_high = plan.get("entry_high")
        if (isinstance(shares, bool) or not isinstance(shares, int) or shares <= 0
                or not _finite_number(capital) or float(capital) <= 0):
            if _finite_number(entry_high) and isinstance(shares, int) and shares > 0:
                capital = float(shares) * float(entry_high)
            else:
                raise MarginOverheatCashControlError(
                    "official M6.7 build lacks frozen shares and capital"
                )
        seen.add(code)
        positions.append({
            "ts_code": code,
            "shares": int(shares),
            "capital_used": round(float(capital), 8),
        })
    positions.sort(key=lambda row: row["ts_code"])
    return positions


def _arm_definitions(stage: str = STAGE_A) -> list[dict[str, Any]]:
    governance = load_governance()
    section = governance[stage]
    rows = [section["baseline"], *section["challengers"]]
    return [copy.deepcopy(row) for row in rows]


def _official_bundle_parts(official_bundle: Any, *, decision_date: str,
                           source_identity: Mapping[str, Any]) -> tuple[dict, dict, str]:
    if official_bundle is None:
        raise MarginOverheatCashControlError(
            "margin-overheat capture requires a validated official M6.7 bundle"
        )
    weekly = getattr(official_bundle, "weekly", None)
    receipt = getattr(official_bundle, "receipt", None)
    weekly_bytes = getattr(official_bundle, "weekly_bytes", None)
    if isinstance(official_bundle, Mapping):
        weekly = official_bundle.get("weekly", weekly)
        receipt = official_bundle.get("receipt", receipt)
        weekly_bytes = official_bundle.get("weekly_bytes", weekly_bytes)
    if not isinstance(weekly, dict) or not isinstance(receipt, dict):
        raise MarginOverheatCashControlError("official M6.7 bundle snapshot is incomplete")
    lineage = weekly.get("run_lineage")
    if not isinstance(lineage, Mapping) or str(weekly.get("as_of")) != str(decision_date):
        raise MarginOverheatCashControlError("official M6.7 bundle is not bound to decision_date")
    run_id = str(source_identity.get("run_id") or "")
    candidate_digest = str(source_identity.get("candidate_digest") or "")
    if lineage.get("run_id") != run_id or lineage.get("candidate_digest") != candidate_digest:
        raise MarginOverheatCashControlError("official M6.7 bundle receipt does not match source identity")
    if receipt.get("run_id") != lineage.get("run_id") or \
            receipt.get("candidate_digest") != lineage.get("candidate_digest"):
        raise MarginOverheatCashControlError("official M6.7 receipt identity drifted")
    if not isinstance(weekly_bytes, (bytes, bytearray)):
        raise MarginOverheatCashControlError(
            "validated official M6.7 bundle lacks the JSON byte binding"
        )
    return weekly, receipt, hashlib.sha256(bytes(weekly_bytes)).hexdigest()


def _margin_capture_program(governance: Mapping[str, Any], *, comparison_stage: str = STAGE_A,
                            experiment_batch_id: str | None = None,
                            stage_b_admission_sha256: str | None = None) -> dict[str, Any]:
    if comparison_stage not in (STAGE_A, STAGE_B):
        raise MarginOverheatCashControlError("margin-overheat program comparison stage is unknown")
    batch_id = experiment_batch_id or governance["namespace"]["experiment_batch_id"]
    return {
        "schema_name": "a_short_margin_overheat_cash_control_program_manifest",
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "track_id": TRACK_ID,
        "stage": "knife_3_weekly_capture_settlement",
        "comparison_stage": comparison_stage,
        "experiment_batch_id": batch_id,
        "stage_b_admission_sha256": stage_b_admission_sha256,
        "private_root_layout": governance["capture_contract"]["write_namespace"],
        "governance_sha256": _digest(governance),
        "schema_sha256": {
            "capture": hashlib.sha256(CAPTURE_SCHEMA_PATH.read_bytes()).hexdigest(),
            "source_receipt": hashlib.sha256(RECEIPT_SCHEMA_PATH.read_bytes()).hexdigest(),
            "outcome": hashlib.sha256(OUTCOME_SCHEMA_PATH.read_bytes()).hexdigest(),
            "ledger": hashlib.sha256(LEDGER_SCHEMA_PATH.read_bytes()).hexdigest(),
            "adjudication": hashlib.sha256(ADJUDICATION_SCHEMA_PATH.read_bytes()).hexdigest(),
            "reminder": hashlib.sha256(REMINDER_SCHEMA_PATH.read_bytes()).hexdigest(),
            "stage_transition_receipt": hashlib.sha256(
                STAGE_TRANSITION_RECEIPT_SCHEMA_PATH.read_bytes()).hexdigest(),
            "freeze_manifest": hashlib.sha256(FREEZE_MANIFEST_SCHEMA_PATH.read_bytes()).hexdigest(),
        },
        "boundary": _knife3_boundary(governance),
    }


def _empty_margin_ledger(governance: Mapping[str, Any], *, comparison_stage: str = STAGE_A,
                         experiment_batch_id: str | None = None) -> dict[str, Any]:
    if comparison_stage not in (STAGE_A, STAGE_B):
        raise MarginOverheatCashControlError("margin-overheat ledger comparison stage is unknown")
    return {
        "schema_name": "a_short_margin_overheat_cash_control_ledger",
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "program_id": PROGRAM_ID,
        "question_id": QUESTION_ID,
        "experiment_batch_id": experiment_batch_id or governance["namespace"]["experiment_batch_id"],
        "epoch_id": current_epoch_id(),
        "stage": comparison_stage,
        "entries": [],
        "boundary": _knife3_boundary(governance),
    }


def validate_margin_source_receipt(receipt: Mapping[str, Any], capture: Mapping[str, Any],
                                   *, require_current_epoch: bool = True) -> None:
    if not isinstance(receipt, dict) or not isinstance(capture, dict):
        raise MarginOverheatCashControlError("margin-overheat source receipt and capture must be objects")
    _schema_validate(dict(receipt), RECEIPT_SCHEMA_PATH)
    _validate_margin_capture(dict(capture), require_current_epoch=require_current_epoch)
    payload = receipt.get("payload")
    capture_payload = capture.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(capture_payload, Mapping):
        raise MarginOverheatCashControlError("margin-overheat source receipt payload is malformed")
    for key in ("decision_date", "run_date", "price_data_through", "official_m67_digest",
                "margin_fact_digest", "daily_cache_digest", "candidate_digest",
                "experiment_batch_id", "epoch_id"):
        if payload.get(key) != capture_payload.get(key):
            raise MarginOverheatCashControlError(
                f"margin-overheat source receipt {key} does not match capture"
            )
    if payload.get("capture_sha256") != capture.get("payload_sha256"):
        raise MarginOverheatCashControlError(
            "margin-overheat source receipt capture_sha256 does not match capture"
        )


def _validate_margin_capture(capture: Mapping[str, Any], *, require_current_epoch: bool = True) -> None:
    if not isinstance(capture, dict):
        raise MarginOverheatCashControlError("margin-overheat capture must be an object")
    _schema_validate(dict(capture), CAPTURE_SCHEMA_PATH)
    payload = capture.get("payload")
    if _digest(payload) != capture.get("payload_sha256"):
        raise MarginOverheatCashControlError("margin-overheat capture payload digest does not match")
    governance = load_governance()
    if capture.get("track_id") != TRACK_ID or capture.get("comparison_only") is not True:
        raise MarginOverheatCashControlError("margin-overheat capture crossed the comparison boundary")
    for key in ("decision_date", "run_date", "price_data_through"):
        _require_date8(payload.get(key), key)
    if payload["price_data_through"] > payload["decision_date"] or \
            payload["price_data_through"] > payload["run_date"]:
        raise MarginOverheatCashControlError("margin-overheat capture price clock is after its source dates")
    for key in ("official_m67_digest", "margin_fact_digest", "daily_cache_digest",
                "candidate_digest", "candidate_snapshot_digest", "experiment_batch_id", "epoch_id"):
        if key in {"experiment_batch_id", "epoch_id"}:
            if not str(payload.get(key) or ""):
                raise MarginOverheatCashControlError(f"margin-overheat capture {key} is empty")
        else:
            _require_sha(payload.get(key), key)
    stage = payload.get("stage")
    if stage not in (STAGE_A, STAGE_B):
        raise MarginOverheatCashControlError("margin-overheat capture comparison stage is invalid")
    if stage == STAGE_A:
        if payload["experiment_batch_id"] != governance["namespace"]["experiment_batch_id"]:
            raise MarginOverheatCashControlError("margin-overheat capture crosses experiment batch")
        if payload.get("stage_b_admission_sha256") is not None or \
                payload.get("stage_b_supported_arm_id") is not None:
            raise MarginOverheatCashControlError("stage-A capture carries a stage-B admission")
    else:
        _require_sha(payload.get("stage_b_admission_sha256"), "stage_b_admission_sha256")
        if payload.get("stage_b_supported_arm_id") not in stage_arm_ids(STAGE_A)[1:]:
            raise MarginOverheatCashControlError("stage-B capture lacks a supported Stage-A arm")
        if payload["experiment_batch_id"] == governance["namespace"]["experiment_batch_id"]:
            raise MarginOverheatCashControlError("stage-B capture did not open a new experiment batch")
    manifest_sha = payload.get("freeze_manifest_sha256")
    manifest = payload.get("freeze_manifest")
    if manifest_sha is not None:
        _require_sha(manifest_sha, "freeze_manifest_sha256")
        if not isinstance(manifest, Mapping):
            raise MarginOverheatCashControlError(
                "frozen capture lacks its dedicated freeze manifest"
            )
        validate_margin_overheat_freeze_manifest(manifest)
        if manifest.get("payload_sha256") != manifest_sha:
            raise MarginOverheatCashControlError(
                "frozen capture freeze manifest digest does not match payload"
            )
    elif manifest is not None:
        raise MarginOverheatCashControlError(
            "pre-freeze capture carries an unbound freeze manifest"
        )
    if require_current_epoch and current_mode() == FROZEN:
        current_manifest = build_margin_overheat_freeze_manifest()
        if manifest_sha != current_manifest["payload_sha256"] or manifest != current_manifest:
            raise MarginOverheatCashControlError("frozen capture freeze manifest does not match current semantic identity")
    if require_current_epoch and payload["epoch_id"] != current_epoch_id():
        raise MarginOverheatCashControlError("margin-overheat capture crosses independent epoch")
    snapshots = payload.get("candidate_universe")
    if not isinstance(snapshots, list) or _digest(snapshots) != payload["candidate_snapshot_digest"]:
        raise MarginOverheatCashControlError("margin-overheat capture candidate snapshot digest does not match")
    _assert_finite_json(payload, "capture.payload")
    if tuple(row.get("arm_id") for row in payload.get("arm_definitions") or []) != stage_arm_ids(stage):
        raise MarginOverheatCashControlError("margin-overheat capture arm definitions drifted")
    arms = payload.get("arms")
    if not isinstance(arms, list) or tuple(row.get("arm_id") for row in arms) != stage_arm_ids(stage):
        raise MarginOverheatCashControlError("margin-overheat capture arm snapshots drifted")
    predicate = payload.get("predicate_facts")
    if predicate is not None:
        validate_predicate_facts(predicate)
        if predicate.get("source_as_of") != payload["decision_date"]:
            raise MarginOverheatCashControlError("margin-overheat capture predicate source clock drifted")
    if payload.get("predicate_unavailable_reason") != _predicate_unavailable_reason(predicate):
        raise MarginOverheatCashControlError(
            "margin-overheat capture predicate unavailable reason drifted"
        )
    if payload.get("margin_facts_digest") != payload["margin_fact_digest"]:
        raise MarginOverheatCashControlError("margin-overheat capture margin fact digest alias drifted")
    if tuple(payload.get("source_references") or []) != PREDICATE_SOURCE_REFERENCES:
        raise MarginOverheatCashControlError(
            "margin-overheat capture source references are outside the dedicated contract"
        )


def validate_margin_outcome(outcome: Mapping[str, Any]) -> None:
    if not isinstance(outcome, dict):
        raise MarginOverheatCashControlError("margin-overheat outcome must be an object")
    _schema_validate(dict(outcome), OUTCOME_SCHEMA_PATH)
    payload = outcome.get("payload")
    if _digest(payload) != outcome.get("payload_sha256"):
        raise MarginOverheatCashControlError("margin-overheat outcome payload digest does not match")
    if outcome.get("track_id") != TRACK_ID or outcome.get("comparison_only") is not True:
        raise MarginOverheatCashControlError("margin-overheat outcome crossed the comparison boundary")


def validate_margin_ledger(ledger: Mapping[str, Any]) -> None:
    if not isinstance(ledger, dict):
        raise MarginOverheatCashControlError("margin-overheat ledger must be an object")
    _schema_validate(dict(ledger), LEDGER_SCHEMA_PATH)
    if ledger.get("track_id") != TRACK_ID or ledger.get("question_id") != QUESTION_ID:
        raise MarginOverheatCashControlError("margin-overheat ledger namespace drifted")
    keys = [(row["decision_date"], row["question_id"]) for row in ledger.get("entries", [])]
    if len(keys) != len(set(keys)):
        raise MarginOverheatCashControlError("margin-overheat ledger has duplicate decision-date entries")
    batch = ledger.get("experiment_batch_id")
    stage = ledger.get("stage")
    if stage not in (STAGE_A, STAGE_B):
        raise MarginOverheatCashControlError("margin-overheat ledger comparison stage is invalid")
    if any(row["experiment_batch_id"] != batch or row.get("stage") != stage
           for row in ledger.get("entries", [])):
        raise MarginOverheatCashControlError("margin-overheat ledger entry crosses batch or stage")


def validate_margin_adjudication(adjudication: Mapping[str, Any]) -> None:
    if not isinstance(adjudication, dict):
        raise MarginOverheatCashControlError("margin-overheat adjudication must be an object")
    _schema_validate(dict(adjudication), ADJUDICATION_SCHEMA_PATH)
    payload = adjudication.get("payload")
    if _digest(payload) != adjudication.get("payload_sha256"):
        raise MarginOverheatCashControlError("margin-overheat adjudication payload digest does not match")
    state = adjudication.get("state")
    if not isinstance(payload, Mapping) or not isinstance(state, Mapping):
        raise MarginOverheatCashControlError("margin-overheat adjudication payload or state is malformed")
    if state.get("comparison_verdict") != payload.get("formal_verdict"):
        raise MarginOverheatCashControlError("margin-overheat adjudication state verdict is not payload-bound")
    if state.get("comparison_verdict") == "not_evaluated":
        validate_state(state)
    else:
        _validate_adjudicated_state(state, payload)


def validate_stage_transition_receipt(receipt: Mapping[str, Any]) -> None:
    if not isinstance(receipt, dict):
        raise MarginOverheatCashControlError("stage-transition receipt must be an object")
    _schema_validate(dict(receipt), STAGE_TRANSITION_RECEIPT_SCHEMA_PATH)
    payload = receipt.get("payload")
    if _digest(payload) != receipt.get("payload_sha256"):
        raise MarginOverheatCashControlError("stage-transition receipt payload digest does not match")
    if receipt.get("track_id") != TRACK_ID or receipt.get("production_unchanged") is not True:
        raise MarginOverheatCashControlError("stage-transition receipt crossed the production boundary")
    issued_on = _require_date8(payload.get("issued_on"), "stage-transition issued_on")
    expires_on = _require_date8(payload.get("expires_on"), "stage-transition expires_on")
    if expires_on < issued_on:
        raise MarginOverheatCashControlError("stage-transition receipt expires before it is issued")
    accepted_on = payload.get("accepted_on")
    if payload.get("status") == "awaiting_user_acceptance":
        if accepted_on is not None:
            raise MarginOverheatCashControlError("unaccepted stage-transition receipt carries accepted_on")
    elif payload.get("status") == "accepted":
        accepted_date = _require_date8(accepted_on, "stage-transition accepted_on")
        if accepted_date > expires_on:
            raise MarginOverheatCashControlError("stage-transition receipt was accepted after expiry")
    else:  # schema is closed; retained as a point-name fail-closed boundary.
        raise MarginOverheatCashControlError("stage-transition receipt status is invalid")
    if payload.get("next_experiment_batch_id") == payload.get("source_experiment_batch_id"):
        raise MarginOverheatCashControlError("stage-transition receipt did not create a new forward batch")


def build_stage_a_transition_receipt(*, adjudication: Mapping[str, Any], issued_on: str,
                                    expires_on: str) -> dict[str, Any]:
    """Create a source-bound proposal; only a later explicit user acceptance can open stage B."""
    validate_margin_adjudication(adjudication)
    payload = adjudication["payload"]
    state = adjudication["state"]
    issued_on = _require_date8(issued_on, "stage-transition issued_on")
    expires_on = _require_date8(expires_on, "stage-transition expires_on")
    if expires_on < issued_on:
        raise MarginOverheatCashControlError("stage-transition receipt expires before it is issued")
    if state.get("stage") != STAGE_A or state.get("comparison_verdict") != "supported" or \
            payload.get("winning_arm_id") not in stage_arm_ids(STAGE_A)[1:]:
        raise MarginOverheatCashControlError("only a supported Stage-A adjudication can request Stage B")
    next_batch = "batch_stage_b_" + _digest({
        "source_adjudication_sha256": adjudication["payload_sha256"],
        "supported_arm_id": payload["winning_arm_id"],
        "source_epoch_id": payload["epoch_id"],
    })[:20]
    receipt_payload = {
        "status": "awaiting_user_acceptance",
        "source_stage": STAGE_A,
        "next_stage": STAGE_B,
        "source_adjudication_sha256": adjudication["payload_sha256"],
        "source_evidence_sha256": payload["evidence_sha256"],
        "source_experiment_batch_id": payload["experiment_batch_id"],
        "source_epoch_id": payload["epoch_id"],
        "supported_arm_id": payload["winning_arm_id"],
        "issued_on": issued_on,
        "accepted_on": None,
        "expires_on": expires_on,
        "next_experiment_batch_id": next_batch,
    }
    receipt = {
        "schema_name": "a_short_margin_overheat_cash_control_stage_transition_receipt",
        "schema_version": SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "record_type": "stage_transition_receipt",
        "payload": receipt_payload,
        "payload_sha256": _digest(receipt_payload),
        "production_unchanged": True,
        "boundary": _knife3_boundary(),
    }
    validate_stage_transition_receipt(receipt)
    return receipt


def accept_stage_a_transition_receipt(receipt: Mapping[str, Any], *, accepted_on: str) -> dict[str, Any]:
    """Record the user's explicit acceptance without changing production or the shared registry."""
    validate_stage_transition_receipt(receipt)
    proposed = copy.deepcopy(dict(receipt))
    if proposed["payload"]["status"] != "awaiting_user_acceptance":
        raise MarginOverheatCashControlError("stage-transition receipt is not awaiting user acceptance")
    accepted_on = _require_date8(accepted_on, "stage-transition accepted_on")
    if accepted_on > proposed["payload"]["expires_on"]:
        raise MarginOverheatCashControlError("stage-transition receipt is expired")
    proposed["payload"]["status"] = "accepted"
    proposed["payload"]["accepted_on"] = accepted_on
    proposed["payload_sha256"] = _digest(proposed["payload"])
    validate_stage_transition_receipt(proposed)
    return proposed


def register_stage_b_from_accepted_receipt(*, root: str | Path, receipt: Mapping[str, Any],
                                           as_of: str) -> dict[str, Any]:
    """Atomically register a new Stage-B private batch after a current accepted receipt."""
    validate_stage_transition_receipt(receipt)
    if receipt["payload"]["status"] != "accepted":
        raise MarginOverheatCashControlError("stage-B registration requires an accepted user receipt")
    as_of = _require_date8(as_of, "stage-B registration as_of")
    if as_of > receipt["payload"]["expires_on"]:
        raise MarginOverheatCashControlError("stage-B registration receipt is expired")
    if current_mode() != FROZEN:
        raise MarginOverheatCashControlError("stage-B registration requires the shared frozen epoch mode")
    _require_shared_clock_gate()
    private_root = _private_root(root)
    _recover_private_artifact_set(private_root)
    adjudication_path = private_root / "adjudication.json"
    if not adjudication_path.is_file():
        raise MarginOverheatCashControlError("stage-B registration requires the current Stage-A adjudication")
    adjudication = _load_private_json(adjudication_path, "Stage-A adjudication")
    validate_margin_adjudication(adjudication)
    source = receipt["payload"]
    payload = adjudication["payload"]
    if adjudication["state"].get("stage") != STAGE_A or \
            adjudication["state"].get("comparison_verdict") != "supported" or \
            any(source[key] != payload[value] for key, value in (
                ("source_evidence_sha256", "evidence_sha256"),
                ("source_experiment_batch_id", "experiment_batch_id"),
                ("source_epoch_id", "epoch_id"),
                ("supported_arm_id", "winning_arm_id"),
            )) or source["source_adjudication_sha256"] != adjudication["payload_sha256"]:
        raise MarginOverheatCashControlError("stage-B receipt is not bound to the current supported Stage-A evidence")
    governance = load_governance()
    batch_id = source["next_experiment_batch_id"]
    stage_root = private_root / "stage_b" / batch_id
    admission_path = private_root / "stage_b_admission.json"
    if admission_path.exists():
        existing = _load_private_json(admission_path, "stage-B admission")
        validate_stage_transition_receipt(existing)
        if existing != receipt:
            raise MarginOverheatCashControlError("stage-B admission replay drifted")
    elif stage_root.exists() and any(stage_root.iterdir()):
        raise MarginOverheatCashControlError("stage-B batch directory exists without its admission receipt")
    program = _margin_capture_program(
        governance, comparison_stage=STAGE_B, experiment_batch_id=batch_id,
        stage_b_admission_sha256=receipt["payload_sha256"],
    )
    ledger = _empty_margin_ledger(
        governance, comparison_stage=STAGE_B, experiment_batch_id=batch_id,
    )
    validate_margin_ledger(ledger)
    from engine.a_short_artifact_set_transaction import commit_artifact_set
    commit_artifact_set(_private_journal_dir(private_root), {
        admission_path: _json_bytes(dict(receipt)),
        stage_root / "program.json": _json_bytes(program),
        stage_root / "ledger.json": _json_bytes(ledger),
    })
    return {"status": "stage_b_registered", "experiment_batch_id": batch_id,
            "stage": STAGE_B, "production_unchanged": True}


def _stage_admission_as_of(as_of: str | None) -> str:
    """Use an explicit operation date, or today's date for an unqualified private read."""
    return _require_date8(
        as_of or datetime.now().strftime("%Y%m%d"),
        "stage-B admission as_of",
    )


def _load_stage_b_admission(private_root: Path, *, as_of: str | None = None) -> dict[str, Any]:
    """Load and re-authorize the accepted receipt on every Stage-B private operation."""
    admission_path = private_root / "stage_b_admission.json"
    if not admission_path.is_file():
        raise MarginOverheatCashControlError(
            "stage-B capture requires an accepted registered Stage-A receipt"
        )
    receipt = _load_private_json(admission_path, "stage-B admission")
    validate_stage_transition_receipt(receipt)
    payload = receipt["payload"]
    operation_as_of = _stage_admission_as_of(as_of)
    if operation_as_of > payload["expires_on"]:
        raise MarginOverheatCashControlError("stage-B admission receipt is expired")
    if payload["status"] != "accepted" or payload["source_stage"] != STAGE_A or \
            payload["next_stage"] != STAGE_B or \
            payload["supported_arm_id"] not in stage_arm_ids(STAGE_A)[1:]:
        raise MarginOverheatCashControlError(
            "stage-B admission is not an accepted supported Stage-A receipt"
        )
    if current_mode() != FROZEN:
        raise MarginOverheatCashControlError(
            "stage-B admission requires the shared frozen epoch mode"
        )
    _require_shared_clock_gate()
    stage_a_adjudication_path = private_root / "adjudication.json"
    if not stage_a_adjudication_path.is_file():
        raise MarginOverheatCashControlError(
            "stage-B admission requires a current supported Stage-A adjudication"
        )
    stage_a_adjudication = _load_private_json(
        stage_a_adjudication_path, "current Stage-A adjudication"
    )
    validate_margin_adjudication(stage_a_adjudication)
    if stage_a_adjudication["payload_sha256"] != payload["source_adjudication_sha256"] or \
            stage_a_adjudication["state"].get("stage") != STAGE_A or \
            stage_a_adjudication["state"].get("comparison_verdict") != "supported" or \
            stage_a_adjudication["payload"].get("formal_verdict") != "supported":
        raise MarginOverheatCashControlError(
            "stage-B admission requires a current supported Stage-A adjudication"
        )
    return receipt


def _stage_storage_root(private_root: Path, *, stage: str, as_of: str | None = None
                        ) -> tuple[Path, dict[str, Any] | None]:
    """Resolve the isolated private artifact root for one currently governed stage."""
    if stage == STAGE_A:
        return private_root, None
    if stage != STAGE_B:
        raise MarginOverheatCashControlError("margin-overheat comparison stage is invalid")
    receipt = _load_stage_b_admission(private_root, as_of=as_of)
    stage_root = private_root / "stage_b" / receipt["payload"]["next_experiment_batch_id"]
    if not stage_root.is_dir():
        raise MarginOverheatCashControlError(
            "stage-B admission has no registered private batch root"
        )
    return stage_root, receipt


def _validate_stage_b_capture_admission(
        capture: Mapping[str, Any], admission: Mapping[str, Any] | None,
) -> None:
    """Bind each Stage-B capture to the one accepted receipt that opened its batch."""
    payload = capture.get("payload") if isinstance(capture, Mapping) else None
    if not isinstance(payload, Mapping) or payload.get("stage") != STAGE_B:
        raise MarginOverheatCashControlError("stage-B admission received a non-Stage-B capture")
    if not isinstance(admission, Mapping):
        raise MarginOverheatCashControlError("stage-B capture lacks its accepted admission receipt")
    validate_stage_transition_receipt(admission)
    source = admission["payload"]
    if source["status"] != "accepted" or \
            payload.get("experiment_batch_id") != source["next_experiment_batch_id"] or \
            payload.get("stage_b_admission_sha256") != admission.get("payload_sha256") or \
            payload.get("stage_b_supported_arm_id") != source["supported_arm_id"]:
        raise MarginOverheatCashControlError(
            "stage-B capture is not source-bound to its accepted admission receipt"
        )


def validate_margin_public_summary(summary: Mapping[str, Any]) -> None:
    if not isinstance(summary, dict):
        raise MarginOverheatCashControlError("margin-overheat public summary must be an object")
    _schema_validate(dict(summary), PUBLIC_SUMMARY_SCHEMA_PATH)
    if summary.get("track_id") != TRACK_ID or summary.get("production_unchanged") is not True:
        raise MarginOverheatCashControlError("margin-overheat public summary crossed the production boundary")
    if summary.get("status") != PUBLIC_STATUS_CURRENT and summary.get("pending_user_receipt_count") != 0:
        raise MarginOverheatCashControlError("unavailable margin-overheat summary carries stale reminders")


def _public_margin_summary_payload(status: str, *, as_of: str, evidence_status: str = "insufficient_data",
                                   stage: str = STAGE_A, pending_user_receipt_count: int = 0) -> dict[str, Any]:
    """Build the fixed de-identified shape without touching the schema filesystem."""
    if status not in {PUBLIC_STATUS_NOT_CONFIGURED, PUBLIC_STATUS_CURRENT, PUBLIC_STATUS_UNAVAILABLE}:
        raise MarginOverheatCashControlError("margin-overheat public summary status is unknown")
    count = _strict_nonnegative_int(pending_user_receipt_count, "pending_user_receipt_count")
    return {
        "schema_name": "a_short_margin_overheat_cash_control_public_summary",
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "status": status,
        "evidence_status": evidence_status,
        "current_stage": stage,
        "pending_user_receipt_count": count if status == PUBLIC_STATUS_CURRENT else 0,
        "message": (
            "Margin-overheat comparison is not configured; official M6.7 is unchanged."
            if status == PUBLIC_STATUS_NOT_CONFIGURED else
            f"Margin-overheat comparison evidence is current; pending user receipts={count}; official M6.7 is unchanged."
            if status == PUBLIC_STATUS_CURRENT else
            "Margin-overheat comparison evidence is unavailable; stale reminders are suppressed and official M6.7 is unchanged."
        ),
        "production_unchanged": True,
    }


def _public_margin_summary(status: str, *, as_of: str, evidence_status: str = "insufficient_data",
                           stage: str = STAGE_A, pending_user_receipt_count: int = 0) -> dict[str, Any]:
    summary = _public_margin_summary_payload(
        status, as_of=as_of, evidence_status=evidence_status, stage=stage,
        pending_user_receipt_count=pending_user_receipt_count,
    )
    _schema_validate(summary, PUBLIC_SUMMARY_SCHEMA_PATH)
    return summary


def unavailable_margin_public_summary(*, as_of: str) -> dict[str, Any]:
    """Return the schema-shaped fail-soft banner without external contract I/O."""
    return _public_margin_summary_payload(PUBLIC_STATUS_UNAVAILABLE, as_of=as_of)


def _capture_source_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    receipt = {
        "schema_name": "a_short_margin_overheat_cash_control_source_receipt",
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "record_type": "source_receipt",
        "decision_date": payload["decision_date"],
        "payload": {
            "capture_sha256": _digest(payload),
            **{key: payload[key] for key in (
                "decision_date", "run_date", "price_data_through", "official_m67_digest",
                "margin_fact_digest", "daily_cache_digest", "candidate_digest",
                "experiment_batch_id", "epoch_id")},
            "settlement": None,
        },
        "boundary": _knife3_boundary(),
    }
    _schema_validate(receipt, RECEIPT_SCHEMA_PATH)
    return receipt


def _arm_capture_snapshot(*, facts: Mapping[str, Any] | None, arm_id: str,
                          reports: Sequence[Mapping[str, Any]], decision_date: str,
                          source_receipt: Mapping[str, Any] | None,
                          stage: str = STAGE_A,
                          stage_b_supported_arm_id: str | None = None) -> dict[str, Any]:
    criterion_id = next(row["criterion_id"] for row in _arm_definitions(stage)
                        if row["arm_id"] == arm_id)
    if isinstance(facts, Mapping) and facts.get("status") == "available":
        shadow = materialize_shadow_cash_control(
            facts, arm_id=arm_id, reports=list(reports), available_cash=_model_cash_cny(),
            new_exposure_capacity=_model_cash_cny(), as_of=decision_date,
            source_receipt=source_receipt, stage=stage,
            stage_b_supported_arm_id=stage_b_supported_arm_id,
        )
        positions = _frozen_positions_from_reports(shadow["shadow_reports"])
        return {
            "arm_id": arm_id,
            "criterion_id": criterion_id,
            "status": shadow["status"],
            "predicate_triggered": shadow["predicate_triggered"],
            "shadow_cash_factor": shadow["shadow_cash_factor"],
            "allocation_summary": copy.deepcopy(shadow["allocation_summary"]),
            "positions": positions,
        }
    baseline_positions = _frozen_positions_from_reports(reports)
    allocated = sum(float(row["capital_used"]) for row in baseline_positions)
    remaining = round(max(0.0, _model_cash_cny() - allocated), 8)
    return {
        "arm_id": arm_id,
        "criterion_id": criterion_id,
        "status": "no_count",
        "predicate_triggered": None,
        "shadow_cash_factor": 1.0,
        "allocation_summary": {
            "available_cash_start": _model_cash_cny(),
            "allocated_cash_total": round(allocated, 8),
            "remaining_cash": remaining,
            "new_exposure_capacity_start": _model_cash_cny(),
            "remaining_new_exposure_capacity": round(max(0.0, _model_cash_cny() - allocated), 8),
        },
        "positions": baseline_positions,
    }


def _predicate_unavailable_reason(facts: Mapping[str, Any] | None) -> str | None:
    """Return the source-bound no-count reason carried by a weekly capture."""
    if not isinstance(facts, Mapping):
        return "predicate_facts_missing"
    if facts.get("status") == "available":
        return None
    reason = facts.get("unavailable_reason")
    if not isinstance(reason, str) or not reason:
        raise MarginOverheatCashControlError(
            "unavailable predicate facts lack a capture reason"
        )
    return reason


def capture_margin_overheat_week(
    *, root: str | Path, decision_date: str, run_identity: Mapping[str, Any],
    official_bundle: Any, margin_facts: Mapping[str, Any],
    daily_cache_document: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]],
    reports: Sequence[Mapping[str, Any]], predicate_facts: Mapping[str, Any] | None = None,
    forward_eligible: bool = False,
    stage: str = STAGE_A,
) -> dict[str, Any]:
    """Capture one canonical week after the caller proves the official bundle exists."""
    private_root = _private_root(root)
    _recover_private_artifact_set(private_root)
    decision_date = _require_date8(decision_date, "decision_date")
    if stage not in (STAGE_A, STAGE_B):
        raise MarginOverheatCashControlError("margin-overheat capture comparison stage is invalid")
    stage_root, stage_b_admission = _stage_storage_root(
        private_root, stage=stage, as_of=decision_date,
    )
    if stage == STAGE_B:
        accepted_on = str(stage_b_admission["payload"]["accepted_on"])
        if decision_date < accepted_on:
            raise MarginOverheatCashControlError(
                "stage-B capture cannot backfill before its user acceptance"
            )
    _recover_private_artifact_set(stage_root)
    if not isinstance(run_identity, Mapping):
        raise MarginOverheatCashControlError("margin-overheat source identity is required")
    weekly, _receipt, official_digest = _official_bundle_parts(
        official_bundle, decision_date=decision_date, source_identity=run_identity)
    lineage = weekly.get("run_lineage") or {}
    freshness = lineage.get("price_freshness") or {}
    run_date = _require_date8(freshness.get("run_date") or lineage.get("run_date") or
                              run_identity.get("run_date"), "run_date")
    price_data_through = _require_date8(
        freshness.get("price_data_through") or lineage.get("price_data_through") or
        weekly.get("price_data_through") or run_identity.get("price_data_through"),
        "price_data_through",
    )
    if price_data_through > decision_date or price_data_through > run_date:
        raise MarginOverheatCashControlError("margin-overheat capture price_data_through is in the future")
    document = _cache_document(daily_cache_document)
    candidates_snapshot, candidate_snapshot_digest = _candidate_snapshots(candidates)
    if not isinstance(margin_facts, Mapping):
        raise MarginOverheatCashControlError("margin-overheat margin facts are required")
    facts_snapshot = copy.deepcopy(dict(margin_facts))
    _assert_finite_json(facts_snapshot, "margin_facts")
    facts = None if predicate_facts is None else copy.deepcopy(dict(predicate_facts))
    if facts is not None:
        validate_predicate_facts(facts)
        if facts.get("source_as_of") != decision_date:
            raise MarginOverheatCashControlError("margin-overheat predicate source_as_of is not decision_date")
    predicate_unavailable_reason = _predicate_unavailable_reason(facts)
    governance = load_governance()
    selection_plan = _selection_plan_snapshot(reports)
    source_receipt = facts.get("source_receipt") if isinstance(facts, Mapping) else None
    experiment_batch_id = (
        governance["namespace"]["experiment_batch_id"] if stage == STAGE_A
        else str(stage_b_admission["payload"]["next_experiment_batch_id"])
    )
    stage_b_admission_sha256 = (
        None if stage == STAGE_A else str(stage_b_admission["payload_sha256"])
    )
    stage_b_supported_arm_id = (
        None if stage == STAGE_A else str(stage_b_admission["payload"]["supported_arm_id"])
    )
    freeze_manifest = (
        build_margin_overheat_freeze_manifest() if current_mode() == FROZEN else None
    )
    arms = [_arm_capture_snapshot(facts=facts, arm_id=arm["arm_id"], reports=reports,
                                  decision_date=decision_date, source_receipt=source_receipt,
                                  stage=stage,
                                  stage_b_supported_arm_id=stage_b_supported_arm_id)
            for arm in _arm_definitions(stage)]
    payload = {
        "decision_date": decision_date,
        "run_date": run_date,
        "price_data_through": price_data_through,
        "official_m67_digest": official_digest,
        "margin_fact_digest": _digest(facts_snapshot),
        "margin_facts_digest": _digest(facts_snapshot),
        "daily_cache_digest": _digest(document),
        "candidate_digest": _require_sha(run_identity.get("candidate_digest"), "candidate_digest"),
        "candidate_snapshot_digest": candidate_snapshot_digest,
        "experiment_batch_id": experiment_batch_id,
        "epoch_id": current_epoch_id(),
        "stage": stage,
        "stage_b_admission_sha256": stage_b_admission_sha256,
        "stage_b_supported_arm_id": stage_b_supported_arm_id,
        "freeze_manifest_sha256": (
            freeze_manifest["payload_sha256"] if freeze_manifest is not None else None
        ),
        "freeze_manifest": freeze_manifest,
        "forward_eligible": bool(forward_eligible),
        "predicate_facts": facts,
        "predicate_unavailable_reason": predicate_unavailable_reason,
        "candidate_universe": candidates_snapshot,
        "official_selection_plan": selection_plan,
        "arm_definitions": _arm_definitions(stage),
        "arms": arms,
        "source_references": list(PREDICATE_SOURCE_REFERENCES),
    }
    capture = {
        "schema_name": "a_short_margin_overheat_cash_control_capture",
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "comparison_only": True,
        "payload": payload,
        "payload_sha256": _digest(payload),
        "boundary": _knife3_boundary(governance),
    }
    _validate_margin_capture(capture)
    receipt = _capture_source_receipt(payload)
    validate_margin_source_receipt(receipt, capture)
    week_dir = stage_root / "weeks" / decision_date
    capture_path, receipt_path = week_dir / "capture.json", week_dir / "source_receipt.json"
    if capture_path.exists() or receipt_path.exists():
        if not capture_path.is_file() or not receipt_path.is_file():
            raise MarginOverheatCashControlError(
                f"{decision_date}: partial margin-overheat capture artifact set"
            )
        existing_capture = _load_private_json(capture_path, "capture")
        existing_receipt = _load_private_json(receipt_path, "source receipt")
        validate_margin_source_receipt(existing_receipt, existing_capture)
        if existing_capture != capture:
            raise MarginOverheatCashControlError(CAPTURE_REPLAY_DRIFT_MESSAGE)
        return {"status": "already_captured", "decision_date": decision_date,
                "capture": existing_capture}
    if week_dir.exists() and any(week_dir.iterdir()):
        raise MarginOverheatCashControlError(
            f"{decision_date}: partial margin-overheat capture directory"
        )
    ledger_path = stage_root / "ledger.json"
    program_path = stage_root / "program.json"
    expected_program = _margin_capture_program(
        governance, comparison_stage=stage, experiment_batch_id=experiment_batch_id,
        stage_b_admission_sha256=stage_b_admission_sha256,
    )
    if program_path.exists():
        program = _load_private_json(program_path, "program manifest")
        if program != expected_program:
            raise MarginOverheatCashControlError("margin-overheat program manifest drifted")
    else:
        program = expected_program
    if ledger_path.exists():
        ledger = _load_private_json(ledger_path, "ledger")
        validate_margin_ledger(ledger)
    else:
        ledger = _empty_margin_ledger(
            governance, comparison_stage=stage, experiment_batch_id=experiment_batch_id,
        )
        validate_margin_ledger(ledger)
    from engine.a_short_artifact_set_transaction import commit_artifact_set
    commit_artifact_set(_private_journal_dir(stage_root), {
        program_path: _json_bytes(program),
        ledger_path: _json_bytes(ledger),
        capture_path: _json_bytes(capture),
        receipt_path: _json_bytes(receipt),
    })
    return {"status": "captured", "decision_date": decision_date, "capture": capture}


def _unavailable_risk_evidence() -> dict[str, Any]:
    return {
        "max_drawdown_pct": None,
        "bad_name_rate": None,
        "tail_loss_pct": None,
        "loss_distribution_count": None,
        "cash_drag_pct": None,
        "unfilled_rate": None,
        "fill_rate": None,
        "turnover_pct": None,
        "total_cost_pct": None,
        "max_name_weight_pct": None,
        "adjustment_coverage_pct": None,
        "loss_distribution_basis": None,
    }


def _settlement_risk_evidence(*, model_cash: float, retained_cash: float, remaining_cash: float,
                              horizon_rows: Sequence[Mapping[str, Any]],
                              h10_position_returns: Sequence[float],
                              capital_used: Sequence[float]) -> dict[str, Any]:
    navs = [model_cash] + [float(row["nav"]) for row in horizon_rows]
    peak = model_cash
    max_drawdown = 0.0
    for nav in navs:
        peak = max(peak, nav)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - nav) / peak * 100.0)
    h10_cost = next((float(row["cost"]) for row in horizon_rows if row["horizon"] == 10), None)
    position_count = len(h10_position_returns)
    total_capital = sum(capital_used)
    return {
        "max_drawdown_pct": round(max_drawdown, 8),
        "bad_name_rate": round(
            sum(value < 0.0 for value in h10_position_returns) / position_count
            if position_count else 0.0,
            8,
        ),
        "tail_loss_pct": round(min(h10_position_returns), 8) if position_count else 0.0,
        "loss_distribution_count": position_count,
        "cash_drag_pct": round((retained_cash + remaining_cash) / model_cash * 100.0, 8),
        "unfilled_rate": 0.0,
        "fill_rate": 1.0,
        "turnover_pct": round(total_capital / model_cash * 100.0, 8),
        "total_cost_pct": round((h10_cost or 0.0) / model_cash * 100.0, 8),
        "max_name_weight_pct": round(max(capital_used) / model_cash * 100.0, 8) if capital_used else 0.0,
        "adjustment_coverage_pct": 100.0,
        "loss_distribution_basis": "filled_positions_only",
    }


def _settle_arm(*, arm: Mapping[str, Any], candidate_by_code: Mapping[str, Mapping[str, Any]],
                decision_date: str, price_data_through: str, dates: Sequence[str],
                lookup: Mapping[tuple[str, str], Mapping[str, Any]]) -> tuple[dict[str, Any], str | None]:
    positions = arm.get("positions")
    if not isinstance(positions, list):
        return {"arm_id": arm.get("arm_id"), "status": "no_count", "reason": "positions_missing",
                "horizons": [], "risk_evidence": _unavailable_risk_evidence()}, "positions_missing"
    if decision_date not in dates:
        return {"arm_id": arm.get("arm_id"), "status": "pending", "reason": "decision_date_not_matured",
                "horizons": [], "risk_evidence": _unavailable_risk_evidence()}, None
    base_index = list(dates).index(decision_date)
    if base_index + max(HORIZONS) >= len(dates):
        return {"arm_id": arm.get("arm_id"), "status": "pending", "reason": "h20_not_mature",
                "horizons": [], "risk_evidence": _unavailable_risk_evidence()}, None
    selected = [str(row.get("ts_code") or "") for row in positions]
    for code in selected:
        if code not in candidate_by_code:
            return {"arm_id": arm.get("arm_id"), "status": "no_count",
                    "reason": "candidate_snapshot_missing", "horizons": [],
                    "risk_evidence": _unavailable_risk_evidence()}, "candidate_snapshot_missing"
        base = lookup.get((code, price_data_through))
        if not _valid_qfq_row(base):
            return {"arm_id": arm.get("arm_id"), "status": "no_count",
                    "reason": "price_data_through_unavailable", "horizons": [],
                    "risk_evidence": _unavailable_risk_evidence()}, "price_data_through_unavailable"
        if not math.isclose(float(base["close"]), float(candidate_by_code[code]["close"]),
                            rel_tol=0.0, abs_tol=1e-8):
            return {"arm_id": arm.get("arm_id"), "status": "no_count",
                    "reason": "candidate_close_drift", "horizons": [],
                    "risk_evidence": _unavailable_risk_evidence()}, "candidate_close_drift"
    horizon_rows: list[dict[str, Any]] = []
    cost_pct = float(load_governance()["outcome_contract"]["cost_pct"])
    h10_position_returns: list[float] = []
    capital_used: list[float] = []
    retained_cash = 0.0
    remaining_cash = 0.0
    for horizon in HORIZONS:
        entry_date, exit_date = dates[base_index + 1], dates[base_index + horizon]
        nav_positions = 0.0
        total_cost = 0.0
        for position in positions:
            code = str(position.get("ts_code") or "")
            if (isinstance(position.get("shares"), bool)
                    or not isinstance(position.get("shares"), int)
                    or position["shares"] <= 0
                    or not _finite_number(position.get("capital_used"))
                    or float(position["capital_used"]) <= 0):
                return {"arm_id": arm.get("arm_id"), "status": "no_count",
                        "reason": "frozen_position_invalid", "horizons": [],
                        "risk_evidence": _unavailable_risk_evidence()}, "frozen_position_invalid"
            entry, exit_row = lookup.get((code, entry_date)), lookup.get((code, exit_date))
            if not _valid_qfq_row(entry) or not _valid_qfq_row(exit_row):
                return {"arm_id": arm.get("arm_id"), "status": "no_count",
                        "reason": "price_or_adjustment_evidence_missing", "horizons": [],
                        "risk_evidence": _unavailable_risk_evidence()}, \
                    "price_or_adjustment_evidence_missing"
            entry_adj = float(entry["open"]) * float(entry["adj_factor"])
            exit_adj = float(exit_row["close"]) * float(exit_row["adj_factor"])
            nav_positions += int(position["shares"]) * exit_adj
            position_cost = float(position["capital_used"]) * cost_pct / 100.0
            total_cost += position_cost
            if horizon == 10:
                capital = float(position["capital_used"])
                capital_used.append(capital)
                h10_position_returns.append(
                    ((int(position["shares"]) * exit_adj - capital - position_cost) / capital) * 100.0
                )
        allocation = arm.get("allocation_summary") or {}
        available_start = allocation.get("available_cash_start", _model_cash_cny())
        remaining_cash = allocation.get("remaining_cash", _model_cash_cny())
        if not _finite_number(available_start) or not _finite_number(remaining_cash):
            return {"arm_id": arm.get("arm_id"), "status": "no_count",
                    "reason": "frozen_cash_invalid", "horizons": [],
                    "risk_evidence": _unavailable_risk_evidence()}, "frozen_cash_invalid"
        retained_cash = _model_cash_cny() - float(available_start)
        nav = retained_cash + float(remaining_cash) + nav_positions - total_cost
        horizon_rows.append({
            "horizon": horizon,
            "entry_date": entry_date,
            "exit_date": exit_date,
            "nav": round(nav, 8),
            "return_pct": round((nav / _model_cash_cny() - 1.0) * 100.0, 8),
            "cost": round(total_cost, 8),
        })
    return {
        "arm_id": arm.get("arm_id"),
        "status": "settled",
        "reason": None,
        "horizons": horizon_rows,
        "position_count": len(positions),
        "risk_evidence": _settlement_risk_evidence(
            model_cash=_model_cash_cny(), retained_cash=retained_cash,
            remaining_cash=float(remaining_cash), horizon_rows=horizon_rows,
            h10_position_returns=h10_position_returns, capital_used=capital_used,
        ),
    }, None


def _settle_capture(capture: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
    payload = capture["payload"]
    if payload["daily_cache_digest"] != _digest(document):
        raise MarginOverheatCashControlError("margin-overheat daily cache digest does not match capture")
    dates, lookup = _cache_rows(document)
    candidate_by_code = {str(row["ts_code"]): row for row in payload["candidate_universe"]}
    facts = payload.get("predicate_facts")
    if not isinstance(facts, Mapping) or facts.get("status") != "available":
        unavailable_reason = payload["predicate_unavailable_reason"]
        arms = [{"arm_id": row["arm_id"], "status": "no_count",
                 "predicate_triggered": row.get("predicate_triggered"),
                 "reason": unavailable_reason, "horizons": [],
                 "risk_evidence": _unavailable_risk_evidence()}
                for row in payload["arms"]]
        result_payload = {
            "question_id": QUESTION_ID, "decision_date": payload["decision_date"],
            "run_date": payload["run_date"], "price_data_through": payload["price_data_through"],
            "daily_cache_digest": payload["daily_cache_digest"], "status": "no_count",
            "reason": unavailable_reason, "arms": arms,
        }
    else:
        arm_results = []
        reasons: list[str] = []
        for arm in payload["arms"]:
            outcome, reason = _settle_arm(
                arm=arm, candidate_by_code=candidate_by_code,
                decision_date=payload["decision_date"],
                price_data_through=payload["price_data_through"], dates=dates, lookup=lookup,
            )
            outcome["predicate_triggered"] = arm.get("predicate_triggered")
            arm_results.append(outcome)
            if reason:
                reasons.append(reason)
        status = "no_count" if any(row["status"] == "no_count" for row in arm_results) else \
            "pending" if any(row["status"] == "pending" for row in arm_results) else "settled"
        result_payload = {
            "question_id": QUESTION_ID, "decision_date": payload["decision_date"],
            "run_date": payload["run_date"], "price_data_through": payload["price_data_through"],
            "daily_cache_digest": payload["daily_cache_digest"], "status": status,
            "reason": sorted(set(reasons))[0] if reasons else None, "arms": arm_results,
        }
    outcome = {
        "schema_name": "a_short_margin_overheat_cash_control_outcome",
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "comparison_only": True,
        "capture_sha256": capture["payload_sha256"],
        "payload": result_payload,
        "payload_sha256": _digest(result_payload),
        "boundary": _knife3_boundary(),
    }
    validate_margin_outcome(outcome)
    return outcome


def _adjudication_contract() -> dict[str, Any]:
    governance = load_governance()
    contract = copy.deepcopy(governance["adjudication_contract"])
    if contract["min_trigger_effective_weeks"] != _minimum_trigger_effective_weeks():
        raise MarginOverheatCashControlError(
            "adjudication and state trigger floors disagree"
        )
    return contract


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sample_variance(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = _mean(values)
    assert mean is not None
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _paired_bootstrap_mean_ci(values: Sequence[float], *, draws: int, confidence: float,
                              label: str) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    seed = int(_digest({"kind": "margin_overheat_bootstrap", "label": label,
                        "values": list(values), "draws": draws, "confidence": confidence})[:16], 16)
    rng = random.Random(seed)
    count = len(values)
    samples = sorted(
        sum(values[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(draws)
    )
    tail = (1.0 - confidence) / 2.0
    lower_index = max(0, min(len(samples) - 1, math.floor(tail * len(samples))))
    upper_index = max(0, min(len(samples) - 1, math.ceil((1.0 - tail) * len(samples)) - 1))
    return samples[lower_index], samples[upper_index]


def _paired_sign_flip_two_sided_pvalue(values: Sequence[float], *, draws: int) -> float | None:
    if not values:
        return None
    observed = abs(sum(values) / len(values))
    if observed <= 1e-12:
        return 1.0
    count = len(values)
    if count <= 16:
        total, extreme = 1 << count, 0
        for mask in range(total):
            signed = sum(
                value if (mask >> index) & 1 else -value
                for index, value in enumerate(values)
            ) / count
            if abs(signed) >= observed - 1e-12:
                extreme += 1
        return extreme / total
    seed = int(_digest({"kind": "margin_overheat_sign_flip", "values": list(values),
                        "draws": draws})[:16], 16)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(draws):
        signed = sum(value if rng.getrandbits(1) else -value for value in values) / count
        if abs(signed) >= observed - 1e-12:
            extreme += 1
    return (extreme + 1) / (draws + 1)


def _holm_bonferroni(pvalues: Mapping[str, float | None]) -> dict[str, float | None]:
    ordered = sorted((1.0 if value is None else float(value), arm_id)
                     for arm_id, value in pvalues.items())
    adjusted = {arm_id: None for arm_id in pvalues}
    running = 0.0
    for index, (pvalue, arm_id) in enumerate(ordered):
        current = min(1.0, pvalue * (len(ordered) - index))
        running = max(running, current)
        if pvalues[arm_id] is not None:
            adjusted[arm_id] = running
    return adjusted


def _nonoverlap_h10_blocks(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    prior_exit: str | None = None
    for row in sorted(rows, key=lambda item: str(item["decision_date"])):
        exit_date = row.get("evaluation_exit_date")
        if not isinstance(exit_date, str) or not exit_date:
            continue
        if prior_exit is None or str(row["decision_date"]) > prior_exit:
            chosen.append(dict(row))
            prior_exit = exit_date
    return chosen


def _t_critical_975(degrees_of_freedom: int) -> float:
    table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
             7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
             13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
             19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042}
    if degrees_of_freedom <= 1:
        return table[1]
    if degrees_of_freedom in table:
        return table[degrees_of_freedom]
    if degrees_of_freedom < 25:
        return table[20]
    if degrees_of_freedom < 30:
        return table[25]
    return table[30]


def _reml_tau_squared(means: Sequence[float], variances: Sequence[float]) -> float:
    if len(means) < 2:
        return 0.0
    upper = max(1e-12, max(variances) + max((left - right) ** 2
                                             for left in means for right in means))

    def objective(tau_squared: float) -> float:
        weights = [1.0 / max(1e-12, variance + tau_squared) for variance in variances]
        weighted_mean = sum(weight * value for weight, value in zip(weights, means)) / sum(weights)
        return 0.5 * (
            sum(math.log(variance + tau_squared) for variance in variances)
            + math.log(sum(weights))
            + sum(weight * (value - weighted_mean) ** 2 for weight, value in zip(weights, means))
        )

    left, right = 0.0, upper
    for _ in range(72):
        one = left + (right - left) / 3.0
        two = right - (right - left) / 3.0
        if objective(one) <= objective(two):
            right = two
        else:
            left = one
    return max(0.0, (left + right) / 2.0)


def _cross_epoch_random_effects(blocks: Sequence[Mapping[str, Any]], *, current_epoch_id: str,
                                contract: Mapping[str, Any]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for block in blocks:
        grouped.setdefault(str(block["epoch_id"]), []).append(dict(block))
    summaries: dict[str, dict[str, Any]] = {}
    for epoch_id, epoch_blocks in sorted(grouped.items()):
        values = [float(row["effect_pct"]) for row in epoch_blocks]
        variance = _sample_variance(values)
        summaries[epoch_id] = {
            "block_count": len(values),
            "mean_effect_pct": _mean(values),
            "sampling_variance": variance / len(values) if variance is not None and values else None,
            "qualified_for_cross_epoch": len(values) >= int(contract["min_epoch_blocks"]),
        }
    eligible = [(epoch_id, summary) for epoch_id, summary in summaries.items()
                if summary["qualified_for_cross_epoch"]]
    current = summaries.get(current_epoch_id)
    current_qualified = bool(current and current["qualified_for_cross_epoch"])
    current_mean = current.get("mean_effect_pct") if current else None
    current_harm = bool(current_qualified and current_mean is not None and
                        current_mean < -float(contract["min_economic_advantage_pct"]))
    current_positive = bool(current_qualified and current_mean is not None and current_mean > 0.0)
    if not eligible:
        return {"method": "insufficient_epoch_blocks", "epochs": summaries,
                "mean_effect_pct": None, "ci_lower_pct": None, "ci_upper_pct": None,
                "tau_squared": None, "heterogeneity_i2_pct": None, "direction_conflict": False,
                "current_epoch_qualified": current_qualified,
                "current_epoch_direction_consistent": current_positive,
                "current_epoch_harm": current_harm}
    if len(eligible) == 1:
        epoch_id, summary = eligible[0]
        values = [float(row["effect_pct"]) for row in grouped[epoch_id]]
        lower, upper = _paired_bootstrap_mean_ci(
            values, draws=int(contract["bootstrap_draws"]),
            confidence=float(contract["confidence_level"]), label=f"epoch:{epoch_id}")
        return {"method": "single_epoch_blocks", "epochs": summaries,
                "mean_effect_pct": summary["mean_effect_pct"], "ci_lower_pct": lower,
                "ci_upper_pct": upper, "tau_squared": 0.0, "heterogeneity_i2_pct": 0.0,
                "direction_conflict": False, "current_epoch_qualified": current_qualified,
                "current_epoch_direction_consistent": current_positive,
                "current_epoch_harm": current_harm}
    means = [float(summary["mean_effect_pct"]) for _, summary in eligible]
    variances = [max(1e-12, float(summary["sampling_variance"] or 0.0))
                 for _, summary in eligible]
    tau_squared = _reml_tau_squared(means, variances)
    weights = [1.0 / (variance + tau_squared) for variance in variances]
    pooled = sum(weight * mean for weight, mean in zip(weights, means)) / sum(weights)
    degrees = len(eligible) - 1
    q = sum(weight * (mean - pooled) ** 2 for weight, mean in zip(weights, means))
    standard_error = math.sqrt(max(0.0, (q / degrees if degrees else 1.0) / sum(weights)))
    directions = {1 if mean > 1e-12 else -1 if mean < -1e-12 else 0 for mean in means}
    return {"method": "random_effects_reml_hartung_knapp", "epochs": summaries,
            "mean_effect_pct": pooled,
            "ci_lower_pct": pooled - _t_critical_975(degrees) * standard_error,
            "ci_upper_pct": pooled + _t_critical_975(degrees) * standard_error,
            "tau_squared": tau_squared,
            "heterogeneity_i2_pct": max(0.0, (q - degrees) / q * 100.0) if q > 0 else 0.0,
            "direction_conflict": 1 in directions and -1 in directions,
            "current_epoch_qualified": current_qualified,
            "current_epoch_direction_consistent": current_positive,
            "current_epoch_harm": current_harm}


def _risk_gate(rows: Sequence[Mapping[str, Any]], *, no_count_rate: float | None,
               contract: Mapping[str, Any]) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    for field, limit in contract["risk_limits"].items():
        values = [no_count_rate] if field == "no_count_rate" and no_count_rate is not None else \
            [row["risk_evidence"].get(field) for row in rows]
        if not values or any(not _finite_number(value) for value in values):
            results[field] = {"value": None, "limit": limit, "passed": False}
            continue
        value = max(float(item) for item in values) if "maximum" in limit else min(float(item) for item in values)
        results[field] = {
            "value": value,
            "limit": limit,
            "passed": value <= float(limit["maximum"]) if "maximum" in limit
            else value >= float(limit["minimum"]),
        }
    basis_ok = all(row["risk_evidence"].get("loss_distribution_basis") == "filled_positions_only"
                   for row in rows)
    results["loss_distribution_basis"] = {
        "value": "filled_positions_only" if basis_ok else None, "passed": basis_ok,
    }
    return {"passed": all(item["passed"] for item in results.values()), "metrics": results}


def _risk_worsened(rows: Sequence[Mapping[str, Any]], *, contract: Mapping[str, Any]) -> bool:
    for field, limit in contract["risk_limits"].items():
        if field == "no_count_rate":
            continue
        candidate = [row["risk_evidence"].get(field) for row in rows]
        baseline = [row["baseline_risk_evidence"].get(field) for row in rows]
        if not candidate or any(not _finite_number(value) for value in candidate + baseline):
            return True
        if "maximum" in limit and max(candidate) > max(baseline) + 1e-12:
            return True
        if "minimum" in limit and min(candidate) < min(baseline) - 1e-12:
            return True
    return False


def _arm_statistics(rows: Sequence[Mapping[str, Any]], *, checkpoint: int,
                    current_epoch_id: str, contract: Mapping[str, Any],
                    adjusted_pvalue: float | None, no_count_rate: float | None) -> dict[str, Any]:
    analysis_rows = [dict(row) for row in sorted(rows, key=lambda row: str(row["decision_date"]))[:checkpoint]]
    blocks = _nonoverlap_h10_blocks(analysis_rows)
    block_values = [float(row["effect_pct"]) for row in blocks]
    state_counts: dict[str, int] = {}
    state_effects: dict[str, list[float]] = {}
    for row in analysis_rows:
        state = str(row["state"])
        state_counts[state] = state_counts.get(state, 0) + 1
        state_effects.setdefault(state, []).append(float(row["effect_pct"]))
    state_means = {state: _mean(values) for state, values in state_effects.items()}
    state_conflict = any(float(value or 0.0) > 1e-12 for value in state_means.values()) and \
        any(float(value or 0.0) < -1e-12 for value in state_means.values())
    half = len(block_values) // 2
    first_half = _mean(block_values[:half]) if half else None
    second_half = _mean(block_values[half:]) if half else None
    temporal_conflict = bool(first_half is not None and second_half is not None and first_half * second_half < 0.0)
    lower, upper = _paired_bootstrap_mean_ci(
        block_values, draws=int(contract["bootstrap_draws"]),
        confidence=float(contract["confidence_level"]), label="margin_overheat_arm")
    cross_epoch = _cross_epoch_random_effects(blocks, current_epoch_id=current_epoch_id, contract=contract)
    risk = _risk_gate(analysis_rows, no_count_rate=no_count_rate, contract=contract)
    state_coverage = len([state for state, count in state_counts.items()
                          if count >= int(contract["min_state_effective_weeks"])]) >= \
        int(contract["min_distinct_states"])
    block_mean = _mean(block_values)
    statistical_pass = (
        len(analysis_rows) >= checkpoint
        and len(block_values) >= int(contract["min_nonoverlap_blocks"])
        and block_mean is not None
        and block_mean >= float(contract["min_economic_advantage_pct"])
        and sum(value > 0.0 for value in block_values) / len(block_values) >= float(contract["min_block_win_rate"])
        and lower is not None and lower >= float(contract["min_economic_advantage_pct"])
        and adjusted_pvalue is not None and adjusted_pvalue <= float(contract["alpha_spending"][str(checkpoint)])
        and cross_epoch["mean_effect_pct"] is not None and cross_epoch["ci_lower_pct"] is not None
        and float(cross_epoch["ci_lower_pct"]) > 0.0
        and float(cross_epoch["heterogeneity_i2_pct"] or 0.0) <= float(contract["max_heterogeneity_i2_pct"])
        and not cross_epoch["direction_conflict"] and cross_epoch["current_epoch_qualified"]
        and cross_epoch["current_epoch_direction_consistent"] and not cross_epoch["current_epoch_harm"]
        and state_coverage and not state_conflict and not temporal_conflict and risk["passed"]
    )
    reliable_harm = (
        checkpoint >= 36 and len(block_values) >= int(contract["min_nonoverlap_blocks"])
        and block_mean is not None and block_mean <= -float(contract["min_economic_advantage_pct"])
        and upper is not None and upper < 0.0
        and adjusted_pvalue is not None and adjusted_pvalue <= float(contract["alpha_spending"][str(checkpoint)])
        and risk["passed"] and not temporal_conflict and not state_conflict
    )
    return {
        "effective_difference_weeks": len(rows),
        "analysis_effective_weeks": len(analysis_rows),
        "nonoverlap_blocks": len(block_values),
        "mean_paired_net_excess_pct": _mean([float(row["effect_pct"]) for row in analysis_rows]),
        "nonoverlap_mean_paired_net_excess_pct": block_mean,
        "nonoverlap_block_win_rate": (
            sum(value > 0.0 for value in block_values) / len(block_values) if block_values else None
        ),
        "paired_bootstrap_ci": {"confidence_level": contract["confidence_level"],
                                  "lower_pct": lower, "upper_pct": upper},
        "paired_sign_flip_two_sided_pvalue": _paired_sign_flip_two_sided_pvalue(
            block_values, draws=int(contract["permutation_draws"])),
        "holm_bonferroni_adjusted_pvalue": adjusted_pvalue,
        "state_effective_weeks": state_counts,
        "state_mean_effect_pct": state_means,
        "state_coverage_passed": state_coverage,
        "temporal_direction_conflict": temporal_conflict,
        "state_direction_conflict": state_conflict,
        "cross_epoch": cross_epoch,
        "risk_gate": risk,
        "eligible_for_adopt": statistical_pass,
        "reliable_harm": reliable_harm,
        "blocks": blocks,
    }


def _simultaneous_winner(eligible: Sequence[str], rows_by_arm: Mapping[str, Sequence[Mapping[str, Any]]],
                         *, checkpoint: int, contract: Mapping[str, Any]) -> tuple[str | None, dict[str, Any]]:
    if len(eligible) <= 1:
        return (eligible[0] if eligible else None), {}
    confidence = 1.0 - (1.0 - float(contract["simultaneous_confidence_level"])) / (len(eligible) - 1)
    details: dict[str, Any] = {}
    winners: list[str] = []
    for contender in eligible:
        contender_rows = {row["decision_date"]: row for row in rows_by_arm[contender][:checkpoint]}
        passes = True
        comparisons: dict[str, Any] = {}
        for opponent in eligible:
            if opponent == contender:
                continue
            opponent_rows = {row["decision_date"]: row for row in rows_by_arm[opponent][:checkpoint]}
            common = [
                {"decision_date": date,
                 "evaluation_exit_date": max(str(contender_rows[date]["evaluation_exit_date"]),
                                             str(opponent_rows[date]["evaluation_exit_date"])),
                 "effect_pct": float(contender_rows[date]["effect_pct"]) -
                               float(opponent_rows[date]["effect_pct"])}
                for date in sorted(set(contender_rows) & set(opponent_rows))
            ]
            values = [float(row["effect_pct"]) for row in _nonoverlap_h10_blocks(common)]
            lower, upper = _paired_bootstrap_mean_ci(
                values, draws=int(contract["bootstrap_draws"]), confidence=confidence,
                label=f"margin_finalist:{contender}:{opponent}")
            passed = len(values) >= int(contract["min_nonoverlap_blocks"]) and \
                lower is not None and lower >= float(contract["min_economic_advantage_pct"])
            comparisons[opponent] = {
                "common_nonoverlap_blocks": len(values), "mean_difference_pct": _mean(values),
                "simultaneous_confidence_level": confidence, "lower_pct": lower,
                "upper_pct": upper, "passed": passed,
            }
            passes = passes and passed
        details[contender] = comparisons
        if passes:
            winners.append(contender)
    return (winners[0] if len(winners) == 1 else None), details


def _horizon_for_arm(arm: Mapping[str, Any], horizon: int) -> Mapping[str, Any]:
    matches = [row for row in arm.get("horizons") or [] if row.get("horizon") == horizon]
    if len(matches) != 1:
        raise MarginOverheatCashControlError(f"settled arm lacks exactly one H{horizon} outcome")
    return matches[0]


def _validate_settlement_binding(receipt: Mapping[str, Any], capture: Mapping[str, Any],
                                 outcome: Mapping[str, Any]) -> None:
    validate_margin_source_receipt(receipt, capture, require_current_epoch=False)
    if outcome.get("capture_sha256") != capture.get("payload_sha256"):
        raise MarginOverheatCashControlError(
            "margin-overheat outcome is not bound to its capture"
        )
    settlement = receipt.get("payload", {}).get("settlement")
    if not isinstance(settlement, Mapping) or settlement.get("outcome_sha256") != outcome.get("payload_sha256") or \
            settlement.get("status") != outcome.get("payload", {}).get("status") or \
            settlement.get("daily_cache_digest") != capture.get("payload", {}).get("daily_cache_digest"):
        raise MarginOverheatCashControlError("margin-overheat settlement receipt does not bind outcome and cache")


def _collect_source_bound_evidence(ledger: Mapping[str, Any], captures: Mapping[str, Mapping[str, Any]],
                                   outcomes: Mapping[str, Mapping[str, Any]],
                                   receipts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    validate_margin_ledger(ledger)
    stage = ledger["stage"]
    arm_ids = stage_arm_ids(stage)
    challengers = arm_ids[1:]
    rows_by_arm: dict[str, list[dict[str, Any]]] = {arm_id: [] for arm_id in challengers}
    by_arm = {arm_id: {"settled_week_count": 0, "pending_week_count": 0,
                       "no_count_week_count": 0, "trigger_effective_week_count": 0,
                       "source_bound_effective_week_count": 0}
              for arm_id in arm_ids}
    statuses: list[str] = []
    source_rows: list[dict[str, Any]] = []
    current_epoch = current_epoch_id()
    frozen = current_mode() == FROZEN and evidence_counts_toward_clock()
    current_manifest = build_margin_overheat_freeze_manifest() if frozen else None
    current_manifest_sha = current_manifest["payload_sha256"] if current_manifest else None
    current_estimand_sha = (
        current_manifest["payload"]["estimand_sha256"] if current_manifest else None
    )
    for entry in sorted(ledger["entries"], key=lambda row: row["decision_date"]):
        date = entry["decision_date"]
        try:
            capture, outcome, receipt = captures[date], outcomes[date], receipts[date]
        except KeyError as exc:
            raise MarginOverheatCashControlError(
                f"{date}: ledger points to incomplete margin-overheat evidence"
            ) from exc
        _validate_margin_capture(capture, require_current_epoch=False)
        validate_margin_outcome(outcome)
        _validate_settlement_binding(receipt, capture, outcome)
        payload = capture["payload"]
        outcome_payload = outcome["payload"]
        if entry["capture_sha256"] != capture["payload_sha256"] or \
                entry["outcome_sha256"] != outcome["payload_sha256"] or \
                entry["source_receipt_sha256"] != _digest(receipt):
            raise MarginOverheatCashControlError(f"{date}: ledger source hash drift")
        if any(entry[key] != payload[key] for key in ("experiment_batch_id", "epoch_id", "stage")):
            raise MarginOverheatCashControlError(f"{date}: ledger does not match capture batch, epoch or stage")
        if entry["status"] != outcome_payload["status"]:
            raise MarginOverheatCashControlError(f"{date}: ledger status does not match outcome")
        capture_arms = {row["arm_id"]: row for row in payload["arms"]}
        outcome_arms = {row["arm_id"]: row for row in outcome_payload["arms"]}
        if tuple(capture_arms) != arm_ids or tuple(outcome_arms) != arm_ids:
            raise MarginOverheatCashControlError(f"{date}: source-bound arm identity drifted")
        # These are descriptive private-ledger counts, retained for outage
        # diagnosis.  Formal statistics below use only the eligible by_arm
        # counters populated after all forward/frozen/source gates.
        statuses.append(str(outcome_payload["status"]))
        if not entry["forward_eligible"]:
            continue
        if payload["forward_eligible"] is not True:
            raise MarginOverheatCashControlError(f"{date}: ledger forward eligibility is not capture-bound")
        if not frozen:
            continue
        capture_manifest = payload.get("freeze_manifest")
        if capture_manifest is None:
            # A valid pre-freeze record is audit-only forever.  It is retained
            # for source integrity but cannot enter any formal-risk denominator.
            continue
        if not isinstance(capture_manifest, Mapping):
            raise MarginOverheatCashControlError(f"{date}: frozen capture lacks its manifest")
        if payload["epoch_id"] == current_epoch:
            if payload.get("freeze_manifest_sha256") != current_manifest_sha or \
                    capture_manifest != current_manifest:
                raise MarginOverheatCashControlError(
                    f"{date}: frozen capture manifest identity drifted"
                )
        elif capture_manifest["payload"].get("estimand_sha256") != current_estimand_sha:
            raise MarginOverheatCashControlError(
                f"{date}: frozen epoch estimand changed and requires a new experiment batch"
            )
        for arm_id in arm_ids:
            arm_status = outcome_arms[arm_id]["status"]
            if arm_status == "settled":
                by_arm[arm_id]["settled_week_count"] += 1
            elif arm_status == "pending":
                by_arm[arm_id]["pending_week_count"] += 1
            else:
                by_arm[arm_id]["no_count_week_count"] += 1
        if outcome_payload["status"] != "settled" or any(
                outcome_arms[arm_id]["status"] != "settled" for arm_id in arm_ids):
            continue
        baseline_h10 = _horizon_for_arm(outcome_arms["baseline"], 10)
        source_row = {
            "decision_date": date,
            "epoch_id": entry["epoch_id"],
            "capture_sha256": entry["capture_sha256"],
            "outcome_sha256": entry["outcome_sha256"],
            "source_receipt_sha256": entry["source_receipt_sha256"],
            "arms": {},
        }
        for arm_id in challengers:
            arm = outcome_arms[arm_id]
            h10 = _horizon_for_arm(arm, 10)
            triggered = capture_arms[arm_id].get("predicate_triggered")
            if not isinstance(triggered, bool):
                raise MarginOverheatCashControlError(f"{date}: settled challenger lacks predicate trigger state")
            effect = float(h10["return_pct"]) - float(baseline_h10["return_pct"])
            if not triggered and not math.isclose(effect, 0.0, rel_tol=0.0, abs_tol=1e-12):
                raise MarginOverheatCashControlError(f"{date}: non-trigger challenger is not zero-delta paired")
            row = {
                "decision_date": date,
                "evaluation_exit_date": max(str(h10["exit_date"]), str(baseline_h10["exit_date"])),
                "epoch_id": entry["epoch_id"],
                "state": "triggered" if triggered else "non_triggered",
                "effect_pct": effect,
                "risk_evidence": copy.deepcopy(arm["risk_evidence"]),
                "baseline_risk_evidence": copy.deepcopy(outcome_arms["baseline"]["risk_evidence"]),
            }
            rows_by_arm[arm_id].append(row)
            by_arm[arm_id]["source_bound_effective_week_count"] += 1
            if triggered:
                by_arm[arm_id]["trigger_effective_week_count"] += 1
            source_row["arms"][arm_id] = {
                "triggered": triggered, "h10_return_pct": h10["return_pct"],
                "baseline_h10_return_pct": baseline_h10["return_pct"],
                "risk_evidence": arm["risk_evidence"],
            }
        by_arm["baseline"]["source_bound_effective_week_count"] += 1
        source_rows.append(source_row)
    no_count_rates = {
        arm_id: (
            by_arm[arm_id]["no_count_week_count"] /
            (by_arm[arm_id]["settled_week_count"] + by_arm[arm_id]["no_count_week_count"])
            if by_arm[arm_id]["settled_week_count"] + by_arm[arm_id]["no_count_week_count"] else None
        )
        for arm_id in challengers
    }
    return {
        "stage": stage,
        "capture_count": len(ledger["entries"]),
        "settled_week_count": statuses.count("settled"),
        "pending_week_count": statuses.count("pending"),
        "no_count_week_count": statuses.count("no_count"),
        "rows_by_arm": rows_by_arm,
        "by_arm": by_arm,
        "no_count_rates": no_count_rates,
        "source_rows": source_rows,
        "calendar_effective_weeks": len(source_rows),
        "trigger_effective_weeks": max(
            (by_arm[arm_id]["trigger_effective_week_count"] for arm_id in challengers), default=0
        ),
        "current_epoch_id": current_epoch,
    }


def _formal_checkpoint(calendar_effective_weeks: int, contract: Mapping[str, Any]) -> int | None:
    checkpoints = [int(value) for value in contract["formal_calendar_checkpoints"]]
    return max((checkpoint for checkpoint in checkpoints if calendar_effective_weeks >= checkpoint), default=None)


def _formal_decision(evidence: Mapping[str, Any]) -> dict[str, Any]:
    contract = _adjudication_contract()
    calendar_weeks = int(evidence["calendar_effective_weeks"])
    trigger_weeks = int(evidence["trigger_effective_weeks"])
    if not (current_mode() == FROZEN and evidence_counts_toward_clock()):
        return {"status": "pre_freeze_audit_only", "checkpoint": None,
                "verdict": "not_evaluated", "winner": None, "arm_statistics": [],
                "finalist_comparisons": {}}
    if calendar_weeks < int(contract["preliminary_calendar_effective_weeks"]):
        return {"status": "accumulating", "checkpoint": None,
                "verdict": "not_evaluated", "winner": None, "arm_statistics": [],
                "finalist_comparisons": {}}
    checkpoint = _formal_checkpoint(calendar_weeks, contract)
    if checkpoint is None:
        return {"status": "preliminary_review_due", "checkpoint": None,
                "verdict": "not_evaluated", "winner": None, "arm_statistics": [],
                "finalist_comparisons": {}}
    if trigger_weeks < int(contract["min_trigger_effective_weeks"]):
        return {"status": "insufficient_trigger_weeks", "checkpoint": checkpoint,
                "verdict": "not_evaluated", "winner": None, "arm_statistics": [],
                "finalist_comparisons": {}}
    rows_by_arm = {
        arm_id: sorted(rows, key=lambda row: str(row["decision_date"]))
        for arm_id, rows in evidence["rows_by_arm"].items()
    }
    raw_pvalues = {
        arm_id: _paired_sign_flip_two_sided_pvalue(
            [float(row["effect_pct"]) for row in _nonoverlap_h10_blocks(rows[:checkpoint])],
            draws=int(contract["permutation_draws"]),
        )
        for arm_id, rows in rows_by_arm.items()
    }
    adjusted = _holm_bonferroni(raw_pvalues)
    arm_statistics: list[dict[str, Any]] = []
    minimum_trigger = int(contract["min_trigger_effective_weeks"])
    for arm_id, rows in rows_by_arm.items():
        stats = _arm_statistics(
            rows, checkpoint=checkpoint, current_epoch_id=str(evidence["current_epoch_id"]),
            contract=contract, adjusted_pvalue=adjusted[arm_id],
            no_count_rate=evidence["no_count_rates"][arm_id],
        )
        stats["arm_id"] = arm_id
        stats["trigger_effective_weeks"] = evidence["by_arm"][arm_id]["trigger_effective_week_count"]
        stats["trigger_floor_passed"] = stats["trigger_effective_weeks"] >= minimum_trigger
        stats["eligible_for_adopt"] = bool(stats["eligible_for_adopt"] and stats["trigger_floor_passed"])
        stats["reliable_harm"] = bool(stats["reliable_harm"] and stats["trigger_floor_passed"])
        arm_statistics.append(stats)
    eligible = [row["arm_id"] for row in arm_statistics if row["eligible_for_adopt"]]
    winner, finalists = _simultaneous_winner(eligible, rows_by_arm, checkpoint=checkpoint, contract=contract)
    conflicts = any(
        row["temporal_direction_conflict"] or row["state_direction_conflict"] or
        row["cross_epoch"]["direction_conflict"] or
        (row["cross_epoch"]["heterogeneity_i2_pct"] is not None and
         row["cross_epoch"]["heterogeneity_i2_pct"] > float(contract["max_heterogeneity_i2_pct"]))
        for row in arm_statistics
    )
    mature = [row for row in arm_statistics if row["trigger_floor_passed"]]
    all_arms_mature = bool(arm_statistics) and len(mature) == len(arm_statistics)
    if winner:
        status, verdict = "formal_supported", "supported"
    elif checkpoint >= 36 and all_arms_mature and all(row["reliable_harm"] for row in arm_statistics):
        status, verdict = "formal_not_supported", "not_supported"
    else:
        status, verdict = "formal_inconclusive", "inconclusive"
    if conflicts and verdict != "not_evaluated":
        status, verdict, winner = "formal_inconclusive", "inconclusive", None
    return {"status": status, "checkpoint": checkpoint, "verdict": verdict,
            "winner": winner, "arm_statistics": arm_statistics,
            "finalist_comparisons": finalists}


def _adjudication_documents(ledger: Mapping[str, Any], outcomes: Mapping[str, Mapping[str, Any]],
                            captures: Mapping[str, Mapping[str, Any]],
                            receipts: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = _collect_source_bound_evidence(ledger, captures, outcomes, receipts)
    formal = _formal_decision(evidence)
    calendar_weeks = int(evidence["calendar_effective_weeks"])
    trigger_weeks = int(evidence["trigger_effective_weeks"])
    if formal["verdict"] == "not_evaluated":
        state = build_state(
            calendar_effective_weeks=calendar_weeks,
            trigger_effective_weeks=trigger_weeks,
            stage=evidence["stage"],
        )
    else:
        state = _build_adjudicated_state(
            calendar_effective_weeks=calendar_weeks,
            trigger_effective_weeks=trigger_weeks,
            stage=evidence["stage"], comparison_verdict=formal["verdict"],
            reason=formal["status"],
        )
    payload = {
        "question_id": QUESTION_ID,
        "experiment_batch_id": ledger["experiment_batch_id"],
        "epoch_id": evidence["current_epoch_id"],
        "stage": evidence["stage"],
        "capture_count": evidence["capture_count"],
        "settled_week_count": evidence["settled_week_count"],
        "pending_week_count": evidence["pending_week_count"],
        "no_count_week_count": evidence["no_count_week_count"],
        "calendar_effective_weeks": calendar_weeks,
        "trigger_effective_weeks": trigger_weeks,
        "current_epoch_id": evidence["current_epoch_id"],
        "source_bound_record_count": len(evidence["source_rows"]),
        "evidence_sha256": _digest(evidence["source_rows"]),
        "formal_checkpoint": formal["checkpoint"],
        "formal_status": formal["status"],
        "formal_verdict": formal["verdict"],
        "winning_arm_id": formal["winner"],
        "by_arm": evidence["by_arm"],
        "arm_statistics": [
            {key: value for key, value in row.items() if key != "blocks"}
            for row in formal["arm_statistics"]
        ],
        "finalist_comparisons": formal["finalist_comparisons"],
    }
    reminders: list[dict[str, Any]] = []
    if state["stage"] == STAGE_A and state["comparison_verdict"] == "supported":
        source_dates = [row["decision_date"] for row in evidence["source_rows"]]
        reminders.append({
            "question_id": QUESTION_ID,
            "decision_date": max(source_dates),
            "status": "supported",
            "reason": "stage_a_supported_receipt_required",
            "receipt_required": True,
            "stage": STAGE_A,
        })
    adjudication = {
        "schema_name": "a_short_margin_overheat_cash_control_adjudication",
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "comparison_only": True,
        "payload": payload,
        "payload_sha256": _digest(payload),
        "state": state,
        "reminder_count": len(reminders),
        "boundary": _knife3_boundary(),
    }
    validate_margin_adjudication(adjudication)
    reminder = {
        "schema_name": "a_short_margin_overheat_cash_control_reminder",
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "question_id": QUESTION_ID,
        "experiment_batch_id": ledger["experiment_batch_id"],
        "epoch_id": evidence["current_epoch_id"],
        "reminders": reminders,
        "production_unchanged": True,
        "boundary": _knife3_boundary(),
    }
    _schema_validate(reminder, REMINDER_SCHEMA_PATH)
    return adjudication, reminder


def validate_margin_reminder(reminder: Mapping[str, Any]) -> None:
    if not isinstance(reminder, dict):
        raise MarginOverheatCashControlError("margin-overheat reminder must be an object")
    _schema_validate(dict(reminder), REMINDER_SCHEMA_PATH)
    if reminder.get("track_id") != TRACK_ID or reminder.get("production_unchanged") is not True:
        raise MarginOverheatCashControlError("margin-overheat reminder crossed the production boundary")


def _clear_private_margin_reminder(private_root: Path) -> None:
    """Clear stale private reminders after any settlement/read fault."""
    if not private_root.exists():
        return
    reminder = {
        "schema_name": "a_short_margin_overheat_cash_control_reminder",
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "question_id": QUESTION_ID,
        "experiment_batch_id": load_governance()["namespace"]["experiment_batch_id"],
        "epoch_id": current_epoch_id(),
        "reminders": [],
        "production_unchanged": True,
        "boundary": _knife3_boundary(),
    }
    validate_margin_reminder(reminder)
    from engine.a_short_artifact_set_transaction import commit_artifact_set
    commit_artifact_set(_private_journal_dir(private_root), {
        private_root / "reminder.json": _json_bytes(reminder),
    })


def adjudicate_margin_overheat_cash_control(
        *, root: str | Path, stage: str = STAGE_A, as_of: str | None = None,
) -> dict[str, Any]:
    private_root = _private_root(root)
    _recover_private_artifact_set(private_root)
    operation_as_of = _stage_admission_as_of(as_of)
    stage_root, stage_b_admission = _stage_storage_root(
        private_root, stage=stage, as_of=operation_as_of,
    )
    _recover_private_artifact_set(stage_root)
    ledger = _load_private_json(stage_root / "ledger.json", "ledger")
    validate_margin_ledger(ledger)
    if ledger["stage"] != stage:
        raise MarginOverheatCashControlError("margin-overheat adjudication stage root drifted")
    if stage_b_admission is not None and ledger["experiment_batch_id"] != \
            stage_b_admission["payload"]["next_experiment_batch_id"]:
        raise MarginOverheatCashControlError("stage-B adjudication batch is not admission-bound")
    captures: dict[str, dict] = {}
    outcomes: dict[str, dict] = {}
    receipts: dict[str, dict] = {}
    for entry in ledger["entries"]:
        week_root = stage_root / "weeks" / entry["decision_date"]
        capture_path, outcome_path, receipt_path = (
            week_root / "capture.json", week_root / "outcome.json", week_root / "source_receipt.json"
        )
        if not capture_path.is_file() or not outcome_path.is_file() or not receipt_path.is_file():
            raise MarginOverheatCashControlError("margin-overheat ledger points to incomplete source-bound evidence")
        capture = _load_private_json(capture_path, "capture")
        outcome = _load_private_json(outcome_path, "outcome")
        receipt = _load_private_json(receipt_path, "source receipt")
        _validate_margin_capture(capture, require_current_epoch=False)
        if stage == STAGE_B:
            _validate_stage_b_capture_admission(capture, stage_b_admission)
        validate_margin_outcome(outcome)
        _validate_settlement_binding(receipt, capture, outcome)
        if outcome["capture_sha256"] != entry["capture_sha256"] or \
                outcome["payload_sha256"] != entry["outcome_sha256"] or \
                _digest(receipt) != entry["source_receipt_sha256"]:
            raise MarginOverheatCashControlError("margin-overheat ledger outcome digest does not match")
        captures[entry["decision_date"]] = capture
        outcomes[entry["decision_date"]] = outcome
        receipts[entry["decision_date"]] = receipt
    adjudication, reminder = _adjudication_documents(ledger, outcomes, captures, receipts)
    from engine.a_short_artifact_set_transaction import commit_artifact_set
    commit_artifact_set(_private_journal_dir(stage_root), {
        stage_root / "adjudication.json": _json_bytes(adjudication),
        stage_root / "reminder.json": _json_bytes(reminder),
    })
    return {"status": "adjudicated_margin_overheat_cash_control",
            "adjudication": adjudication, "reminder": reminder}


def settle_margin_overheat_from_daily_cache(
        *, root: str | Path, daily_cache_document: Mapping[str, Any],
        stage: str = STAGE_A, as_of: str | None = None,
) -> dict[str, Any]:
    """Recompute all private captures from one existing cache, then commit one artifact set."""
    private_root = _private_root(root)
    _recover_private_artifact_set(private_root)
    operation_as_of = _stage_admission_as_of(as_of)
    stage_root, stage_b_admission = _stage_storage_root(
        private_root, stage=stage, as_of=operation_as_of,
    )
    _recover_private_artifact_set(stage_root)
    document = _cache_document(daily_cache_document)
    governance = load_governance()
    expected_program = _margin_capture_program(
        governance, comparison_stage=stage,
        experiment_batch_id=(governance["namespace"]["experiment_batch_id"]
                             if stage == STAGE_A
                             else stage_b_admission["payload"]["next_experiment_batch_id"]),
        stage_b_admission_sha256=(None if stage == STAGE_A
                                  else stage_b_admission["payload_sha256"]),
    )
    program = _load_private_json(stage_root / "program.json", "program manifest")
    if program != expected_program:
        raise MarginOverheatCashControlError("margin-overheat program manifest drifted")
    ledger = _load_private_json(stage_root / "ledger.json", "ledger")
    validate_margin_ledger(ledger)
    if ledger["stage"] != stage:
        raise MarginOverheatCashControlError("margin-overheat settlement stage root drifted")
    weeks_root = stage_root / "weeks"
    capture_files = [] if not weeks_root.exists() else sorted(
        path for path in weeks_root.iterdir() if path.is_dir()
    )
    captures: dict[str, dict] = {}
    outcomes: dict[str, dict] = {}
    receipts: dict[str, dict] = {}
    for week_dir in capture_files:
        capture_path, receipt_path = week_dir / "capture.json", week_dir / "source_receipt.json"
        if not capture_path.is_file() or not receipt_path.is_file():
            raise MarginOverheatCashControlError(
                f"{week_dir.name}: partial margin-overheat capture artifact set"
            )
        capture = _load_private_json(capture_path, "capture")
        receipt = _load_private_json(receipt_path, "source receipt")
        _validate_margin_capture(capture, require_current_epoch=False)
        if stage == STAGE_B:
            _validate_stage_b_capture_admission(capture, stage_b_admission)
        validate_margin_source_receipt(receipt, capture, require_current_epoch=False)
        if capture["payload"]["daily_cache_digest"] != _digest(document):
            raise MarginOverheatCashControlError(
                "margin-overheat daily cache digest does not match capture"
            )
        captures[week_dir.name] = capture
        receipts[week_dir.name] = receipt
        outcome = _settle_capture(capture, document)
        outcomes[week_dir.name] = outcome
    settled_receipts: dict[str, dict] = {}
    for date, outcome in outcomes.items():
        receipt = copy.deepcopy(receipts[date])
        receipt["payload"]["settlement"] = {
            "outcome_sha256": outcome["payload_sha256"],
            "status": outcome["payload"]["status"],
            "daily_cache_digest": _digest(document),
        }
        _schema_validate(receipt, RECEIPT_SCHEMA_PATH)
        settled_receipts[date] = receipt
    new_entries = []
    for date in sorted(captures):
        capture = captures[date]
        outcome = outcomes[date]
        new_entries.append({
            "decision_date": date,
            "run_date": capture["payload"]["run_date"],
            "price_data_through": capture["payload"]["price_data_through"],
            "question_id": QUESTION_ID,
            "experiment_batch_id": capture["payload"]["experiment_batch_id"],
            "epoch_id": capture["payload"]["epoch_id"],
            "stage": capture["payload"]["stage"],
            "capture_sha256": capture["payload_sha256"],
            "outcome_sha256": outcome["payload_sha256"],
            "source_receipt_sha256": _digest(settled_receipts[date]),
            "status": outcome["payload"]["status"],
            "forward_eligible": bool(capture["payload"]["forward_eligible"]),
        })
    new_ledger = dict(ledger)
    new_ledger["entries"] = new_entries
    validate_margin_ledger(new_ledger)
    adjudication, reminder = _adjudication_documents(
        new_ledger, outcomes, captures, settled_receipts
    )
    writes: dict[Path, bytes] = {
        stage_root / "ledger.json": _json_bytes(new_ledger),
        stage_root / "adjudication.json": _json_bytes(adjudication),
        stage_root / "reminder.json": _json_bytes(reminder),
    }
    for date, outcome in outcomes.items():
        receipt = settled_receipts[date]
        writes[stage_root / "weeks" / date / "outcome.json"] = _json_bytes(outcome)
        writes[stage_root / "weeks" / date / "source_receipt.json"] = _json_bytes(receipt)
    from engine.a_short_artifact_set_transaction import commit_artifact_set
    commit_artifact_set(_private_journal_dir(stage_root), writes)
    return {"status": "settled_from_existing_cache", "ledger": new_ledger,
            "adjudication": adjudication, "reminder": reminder}


def settle_and_summarize_margin_overheat_weekly(*, root: str | Path | None,
                                                daily_cache_path: str | Path | None,
                                                as_of: str) -> dict[str, Any]:
    """Settle/adjudicate before M6.7 and suppress stale reminders on any fault."""
    private_root = None
    try:
        if root is None:
            return _public_margin_summary(PUBLIC_STATUS_NOT_CONFIGURED, as_of=as_of)
        private_root = _private_root(root)
        if not private_root.exists():
            return _public_margin_summary(PUBLIC_STATUS_UNAVAILABLE, as_of=as_of)
        if daily_cache_path is None:
            _clear_private_margin_reminder(private_root)
            return _public_margin_summary(PUBLIC_STATUS_UNAVAILABLE, as_of=as_of)
        document = load_margin_overheat_daily_cache(daily_cache_path)
        result = settle_margin_overheat_from_daily_cache(
            root=private_root, daily_cache_document=document, as_of=as_of,
        )
        reminder = result["reminder"]
        validate_margin_reminder(reminder)
        adjudication = result["adjudication"]
        validate_margin_adjudication(adjudication)
        state = adjudication["state"]
        summary = _public_margin_summary(
            PUBLIC_STATUS_CURRENT, as_of=as_of,
            evidence_status=state["evidence_status"],
            stage=state["stage"],
            pending_user_receipt_count=len(reminder["reminders"]),
        )
        validate_margin_public_summary(summary)
        return summary
    except Exception:
        if private_root is not None:
            try:
                _clear_private_margin_reminder(private_root)
            except Exception:
                pass
        return unavailable_margin_public_summary(as_of=as_of)


def capture_margin_overheat_after_published_weekly(
    *, root: str | Path, decision_date: str, candidates: Sequence[Mapping[str, Any]],
    reports: Sequence[Mapping[str, Any]], source_identity: Mapping[str, Any],
    official_bundle: Any, daily_cache_path: str | Path | None,
    margin_facts: Mapping[str, Any], predicate_facts: Mapping[str, Any] | None = None,
    forward_eligible: bool = False,
) -> dict[str, Any]:
    """Capture only after the weekly runner has validated JSON/Markdown/receipt."""
    if daily_cache_path is None:
        raise MarginOverheatCashControlError("margin-overheat capture requires an approved daily cache path")
    document = load_margin_overheat_daily_cache(daily_cache_path)
    return capture_margin_overheat_week(
        root=root, decision_date=decision_date, run_identity=source_identity,
        official_bundle=official_bundle, margin_facts=margin_facts,
        daily_cache_document=document, candidates=candidates, reports=reports,
        predicate_facts=predicate_facts, forward_eligible=forward_eligible,
    )
