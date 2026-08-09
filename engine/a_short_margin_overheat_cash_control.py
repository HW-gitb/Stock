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
import subprocess
from datetime import datetime
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
    ("level_p95", "level_percentile_p95", "level_percentile", 0.95),
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


def _shadow_arm_spec(arm_id: str) -> tuple[str, str | None, str | None, float | None]:
    if arm_id == "baseline":
        return "no_margin_discount", None, None, None
    for candidate, criterion_id, field, threshold in REPLAY_ARM_SPECS:
        if candidate == arm_id:
            return criterion_id, field, field, threshold
    raise MarginOverheatCashControlError("unknown stage-A shadow arm")


def _shadow_trigger_percentile(facts: Mapping[str, Any], arm_id: str) -> float:
    if arm_id == "level_p95":
        value = facts["level"]["percentile"]
    elif arm_id in {"change_rate_p90", "change_rate_p95"}:
        value = facts["change_rate_20d"]["percentile"]
    else:
        raise MarginOverheatCashControlError("unknown stage-A shadow arm")
    if not _finite_number(value):
        raise MarginOverheatCashControlError(
            "available predicate facts lack the shadow arm percentile"
        )
    return float(value)


def _governed_shadow_cash_factor(arm_id: str, triggered: bool | None) -> float:
    """Read the Stage-A measurement factor from the governed arm contract."""
    governance = load_governance()
    try:
        stage_a = governance[STAGE_A]
        baseline_factor = stage_a["baseline"]["margin_cash_factor"]
        measurement_factor = stage_a["measurement_cash_factor"]
    except (KeyError, TypeError) as exc:
        raise MarginOverheatCashControlError(
            "governance is missing Stage-A shadow cash factors"
        ) from exc
    if (not _finite_number(baseline_factor) or not 0 < float(baseline_factor) <= 1
            or not _finite_number(measurement_factor)
            or not 0 < float(measurement_factor) <= 1):
        raise MarginOverheatCashControlError(
            "governance Stage-A shadow cash factors are invalid"
        )
    if triggered is not True:
        return float(baseline_factor)
    try:
        challengers = stage_a["challengers"]
        configured = next(
            arm["margin_cash_factor"] for arm in challengers
            if arm.get("arm_id") == arm_id
        )
    except (KeyError, StopIteration, TypeError) as exc:
        raise MarginOverheatCashControlError(
            "governance is missing the triggered Stage-A arm cash factor"
        ) from exc
    if (not _finite_number(configured) or not 0 < float(configured) <= 1
            or not math.isclose(float(configured), float(measurement_factor),
                                rel_tol=0.0, abs_tol=1e-12)):
        raise MarginOverheatCashControlError(
            "triggered Stage-A arm cash factor disagrees with measurement factor"
        )
    return float(configured)


def materialize_shadow_cash_control(
    predicate_facts: Mapping[str, Any],
    *,
    arm_id: str,
    reports: list,
    available_cash: Any,
    pre_holiday_control: Mapping[str, Any] | None = None,
    new_exposure_capacity: Any | None = None,
    as_of: str,
    source_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply one stage-A arm to a copied pre-margin allocation seam.

    This is the only knife-2 consumer.  It calls the production cash stack and
    allocator, carries no account context, and returns an in-memory shadow
    result; persistence and settlement belong to knife 3.
    """
    if not isinstance(source_receipt, Mapping):
        raise MarginOverheatCashControlError(
            "shadow consumer requires an explicit source receipt"
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
    criterion_id, _field, _unused, threshold = _shadow_arm_spec(arm_id)
    triggered: bool | None
    if arm_id == "baseline":
        triggered = False
    elif facts["status"] != "available":
        triggered = None
    else:
        triggered = _shadow_trigger_percentile(facts, arm_id) >= float(threshold)
    shadow_factor = _governed_shadow_cash_factor(arm_id, triggered)
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


def _margin_capture_program(governance: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_name": "a_short_margin_overheat_cash_control_program_manifest",
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "track_id": TRACK_ID,
        "stage": "knife_3_weekly_capture_settlement",
        "private_root_layout": governance["capture_contract"]["write_namespace"],
        "governance_sha256": _digest(governance),
        "schema_sha256": {
            "capture": hashlib.sha256(CAPTURE_SCHEMA_PATH.read_bytes()).hexdigest(),
            "source_receipt": hashlib.sha256(RECEIPT_SCHEMA_PATH.read_bytes()).hexdigest(),
            "outcome": hashlib.sha256(OUTCOME_SCHEMA_PATH.read_bytes()).hexdigest(),
            "ledger": hashlib.sha256(LEDGER_SCHEMA_PATH.read_bytes()).hexdigest(),
            "adjudication": hashlib.sha256(ADJUDICATION_SCHEMA_PATH.read_bytes()).hexdigest(),
            "reminder": hashlib.sha256(REMINDER_SCHEMA_PATH.read_bytes()).hexdigest(),
        },
        "boundary": _knife3_boundary(governance),
    }


def _empty_margin_ledger(governance: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_name": "a_short_margin_overheat_cash_control_ledger",
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "track_id": TRACK_ID,
        "program_id": PROGRAM_ID,
        "question_id": QUESTION_ID,
        "experiment_batch_id": governance["namespace"]["experiment_batch_id"],
        "epoch_id": current_epoch_id(),
        "entries": [],
        "boundary": _knife3_boundary(governance),
    }


def validate_margin_source_receipt(receipt: Mapping[str, Any], capture: Mapping[str, Any]) -> None:
    if not isinstance(receipt, dict) or not isinstance(capture, dict):
        raise MarginOverheatCashControlError("margin-overheat source receipt and capture must be objects")
    _schema_validate(dict(receipt), RECEIPT_SCHEMA_PATH)
    _validate_margin_capture(dict(capture))
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


def _validate_margin_capture(capture: Mapping[str, Any]) -> None:
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
    if payload["experiment_batch_id"] != governance["namespace"]["experiment_batch_id"]:
        raise MarginOverheatCashControlError("margin-overheat capture crosses experiment batch")
    if payload["epoch_id"] != current_epoch_id():
        raise MarginOverheatCashControlError("margin-overheat capture crosses independent epoch")
    snapshots = payload.get("candidate_universe")
    if not isinstance(snapshots, list) or _digest(snapshots) != payload["candidate_snapshot_digest"]:
        raise MarginOverheatCashControlError("margin-overheat capture candidate snapshot digest does not match")
    _assert_finite_json(payload, "capture.payload")
    if tuple(row.get("arm_id") for row in payload.get("arm_definitions") or []) != stage_arm_ids(STAGE_A):
        raise MarginOverheatCashControlError("margin-overheat capture arm definitions drifted")
    arms = payload.get("arms")
    if not isinstance(arms, list) or tuple(row.get("arm_id") for row in arms) != stage_arm_ids(STAGE_A):
        raise MarginOverheatCashControlError("margin-overheat capture arm snapshots drifted")
    predicate = payload.get("predicate_facts")
    if predicate is not None:
        validate_predicate_facts(predicate)
        if predicate.get("source_as_of") != payload["decision_date"]:
            raise MarginOverheatCashControlError("margin-overheat capture predicate source clock drifted")
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
    epoch = ledger.get("epoch_id")
    if any(row["experiment_batch_id"] != batch or row["epoch_id"] != epoch
           for row in ledger.get("entries", [])):
        raise MarginOverheatCashControlError("margin-overheat ledger entry crosses batch or epoch")


def validate_margin_adjudication(adjudication: Mapping[str, Any]) -> None:
    if not isinstance(adjudication, dict):
        raise MarginOverheatCashControlError("margin-overheat adjudication must be an object")
    _schema_validate(dict(adjudication), ADJUDICATION_SCHEMA_PATH)
    if _digest(adjudication.get("payload")) != adjudication.get("payload_sha256"):
        raise MarginOverheatCashControlError("margin-overheat adjudication payload digest does not match")
    if adjudication.get("state", {}).get("comparison_verdict") != "not_evaluated":
        raise MarginOverheatCashControlError("margin-overheat adjudication emitted a verdict")


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
                          source_receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    criterion_id = next(row["criterion_id"] for row in _arm_definitions()
                        if row["arm_id"] == arm_id)
    if isinstance(facts, Mapping) and facts.get("status") == "available":
        shadow = materialize_shadow_cash_control(
            facts, arm_id=arm_id, reports=list(reports), available_cash=_model_cash_cny(),
            new_exposure_capacity=_model_cash_cny(), as_of=decision_date,
            source_receipt=source_receipt,
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


def capture_margin_overheat_week(
    *, root: str | Path, decision_date: str, run_identity: Mapping[str, Any],
    official_bundle: Any, margin_facts: Mapping[str, Any],
    daily_cache_document: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]],
    reports: Sequence[Mapping[str, Any]], predicate_facts: Mapping[str, Any] | None = None,
    forward_eligible: bool = False,
) -> dict[str, Any]:
    """Capture one canonical week after the caller proves the official bundle exists."""
    private_root = _private_root(root)
    _recover_private_artifact_set(private_root)
    decision_date = _require_date8(decision_date, "decision_date")
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
    governance = load_governance()
    selection_plan = _selection_plan_snapshot(reports)
    source_receipt = facts.get("source_receipt") if isinstance(facts, Mapping) else None
    arms = [_arm_capture_snapshot(facts=facts, arm_id=arm["arm_id"], reports=reports,
                                  decision_date=decision_date, source_receipt=source_receipt)
            for arm in _arm_definitions()]
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
        "experiment_batch_id": governance["namespace"]["experiment_batch_id"],
        "epoch_id": current_epoch_id(),
        "forward_eligible": bool(forward_eligible),
        "predicate_facts": facts,
        "candidate_universe": candidates_snapshot,
        "official_selection_plan": selection_plan,
        "arm_definitions": _arm_definitions(),
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
    week_dir = private_root / "weeks" / decision_date
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
    ledger_path = private_root / "ledger.json"
    program_path = private_root / "program.json"
    if program_path.exists():
        program = _load_private_json(program_path, "program manifest")
        if program != _margin_capture_program(governance):
            raise MarginOverheatCashControlError("margin-overheat program manifest drifted")
    else:
        program = _margin_capture_program(governance)
    if ledger_path.exists():
        ledger = _load_private_json(ledger_path, "ledger")
        validate_margin_ledger(ledger)
    else:
        ledger = _empty_margin_ledger(governance)
        validate_margin_ledger(ledger)
    from engine.a_short_artifact_set_transaction import commit_artifact_set
    commit_artifact_set(_private_journal_dir(private_root), {
        program_path: _json_bytes(program),
        ledger_path: _json_bytes(ledger),
        capture_path: _json_bytes(capture),
        receipt_path: _json_bytes(receipt),
    })
    return {"status": "captured", "decision_date": decision_date, "capture": capture}


def _settle_arm(*, arm: Mapping[str, Any], candidate_by_code: Mapping[str, Mapping[str, Any]],
                decision_date: str, price_data_through: str, dates: Sequence[str],
                lookup: Mapping[tuple[str, str], Mapping[str, Any]]) -> tuple[dict[str, Any], str | None]:
    positions = arm.get("positions")
    if not isinstance(positions, list):
        return {"arm_id": arm.get("arm_id"), "status": "no_count", "reason": "positions_missing",
                "horizons": []}, "positions_missing"
    if decision_date not in dates:
        return {"arm_id": arm.get("arm_id"), "status": "pending", "reason": "decision_date_not_matured",
                "horizons": []}, None
    base_index = list(dates).index(decision_date)
    if base_index + max(HORIZONS) >= len(dates):
        return {"arm_id": arm.get("arm_id"), "status": "pending", "reason": "h20_not_mature",
                "horizons": []}, None
    selected = [str(row.get("ts_code") or "") for row in positions]
    for code in selected:
        if code not in candidate_by_code:
            return {"arm_id": arm.get("arm_id"), "status": "no_count",
                    "reason": "candidate_snapshot_missing", "horizons": []}, "candidate_snapshot_missing"
        base = lookup.get((code, price_data_through))
        if not _valid_qfq_row(base):
            return {"arm_id": arm.get("arm_id"), "status": "no_count",
                    "reason": "price_data_through_unavailable", "horizons": []}, "price_data_through_unavailable"
        if not math.isclose(float(base["close"]), float(candidate_by_code[code]["close"]),
                            rel_tol=0.0, abs_tol=1e-8):
            return {"arm_id": arm.get("arm_id"), "status": "no_count",
                    "reason": "candidate_close_drift", "horizons": []}, "candidate_close_drift"
    horizon_rows: list[dict[str, Any]] = []
    cost_pct = float(load_governance()["outcome_contract"]["cost_pct"])
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
                        "reason": "frozen_position_invalid", "horizons": []}, "frozen_position_invalid"
            entry, exit_row = lookup.get((code, entry_date)), lookup.get((code, exit_date))
            if not _valid_qfq_row(entry) or not _valid_qfq_row(exit_row):
                return {"arm_id": arm.get("arm_id"), "status": "no_count",
                        "reason": "price_or_adjustment_evidence_missing", "horizons": []}, \
                    "price_or_adjustment_evidence_missing"
            entry_adj = float(entry["open"]) * float(entry["adj_factor"])
            exit_adj = float(exit_row["close"]) * float(exit_row["adj_factor"])
            nav_positions += int(position["shares"]) * exit_adj
            total_cost += float(position["capital_used"]) * cost_pct / 100.0
        allocation = arm.get("allocation_summary") or {}
        available_start = allocation.get("available_cash_start", _model_cash_cny())
        remaining_cash = allocation.get("remaining_cash", _model_cash_cny())
        if not _finite_number(available_start) or not _finite_number(remaining_cash):
            return {"arm_id": arm.get("arm_id"), "status": "no_count",
                    "reason": "frozen_cash_invalid", "horizons": []}, "frozen_cash_invalid"
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
    return {"arm_id": arm.get("arm_id"), "status": "settled", "reason": None,
            "horizons": horizon_rows, "position_count": len(positions)}, None


def _settle_capture(capture: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
    payload = capture["payload"]
    if payload["daily_cache_digest"] != _digest(document):
        raise MarginOverheatCashControlError("margin-overheat daily cache digest does not match capture")
    dates, lookup = _cache_rows(document)
    candidate_by_code = {str(row["ts_code"]): row for row in payload["candidate_universe"]}
    facts = payload.get("predicate_facts")
    if not isinstance(facts, Mapping) or facts.get("status") != "available":
        arms = [{"arm_id": row["arm_id"], "status": "no_count",
                 "predicate_triggered": row.get("predicate_triggered"),
                 "reason": "margin_predicate_unavailable", "horizons": []}
                for row in payload["arms"]]
        result_payload = {
            "question_id": QUESTION_ID, "decision_date": payload["decision_date"],
            "run_date": payload["run_date"], "price_data_through": payload["price_data_through"],
            "daily_cache_digest": payload["daily_cache_digest"], "status": "no_count",
            "reason": "margin_predicate_unavailable", "arms": arms,
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


def _adjudication_documents(ledger: Mapping[str, Any], outcomes: Mapping[str, Mapping[str, Any]]) -> tuple[dict, dict]:
    entries = list(ledger.get("entries") or [])
    statuses = [str(outcomes[row["decision_date"]]["payload"]["status"]) for row in entries]
    reminders = [
        {"question_id": QUESTION_ID, "decision_date": row["decision_date"],
         "status": outcomes[row["decision_date"]]["payload"]["status"],
         "reason": outcomes[row["decision_date"]]["payload"].get("reason"),
         "receipt_required": True}
        for row in entries if outcomes[row["decision_date"]]["payload"]["status"] in {"pending", "no_count"}
    ]
    state = build_state(calendar_effective_weeks=0, trigger_effective_weeks=0, stage=STAGE_A)
    by_arm = {arm_id: {"settled_week_count": 0, "pending_week_count": 0,
                       "no_count_week_count": 0, "trigger_effective_week_count": 0}
              for arm_id in stage_arm_ids(STAGE_A)}
    for row in entries:
        outcome = outcomes[row["decision_date"]]["payload"]
        for arm in outcome.get("arms") or []:
            counts = by_arm[arm["arm_id"]]
            if arm["status"] == "settled":
                counts["settled_week_count"] += 1
            elif arm["status"] == "pending":
                counts["pending_week_count"] += 1
            else:
                counts["no_count_week_count"] += 1
            if arm.get("predicate_triggered") is True and arm["status"] == "settled":
                counts["trigger_effective_week_count"] += 1
    payload = {
        "question_id": QUESTION_ID,
        "experiment_batch_id": ledger["experiment_batch_id"],
        "epoch_id": ledger["epoch_id"],
        "capture_count": len(entries),
        "settled_week_count": statuses.count("settled"),
        "pending_week_count": statuses.count("pending"),
        "no_count_week_count": statuses.count("no_count"),
        "by_arm": by_arm,
    }
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
        "epoch_id": ledger["epoch_id"],
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


def adjudicate_margin_overheat_cash_control(*, root: str | Path) -> dict[str, Any]:
    private_root = _private_root(root)
    _recover_private_artifact_set(private_root)
    ledger = _load_private_json(private_root / "ledger.json", "ledger")
    validate_margin_ledger(ledger)
    outcomes: dict[str, dict] = {}
    for entry in ledger["entries"]:
        path = private_root / "weeks" / entry["decision_date"] / "outcome.json"
        if not path.is_file():
            raise MarginOverheatCashControlError("margin-overheat ledger points to a missing outcome")
        outcome = _load_private_json(path, "outcome")
        validate_margin_outcome(outcome)
        if outcome["capture_sha256"] != entry["capture_sha256"] or \
                outcome["payload_sha256"] != entry["outcome_sha256"]:
            raise MarginOverheatCashControlError("margin-overheat ledger outcome digest does not match")
        outcomes[entry["decision_date"]] = outcome
    adjudication, reminder = _adjudication_documents(ledger, outcomes)
    from engine.a_short_artifact_set_transaction import commit_artifact_set
    commit_artifact_set(_private_journal_dir(private_root), {
        private_root / "adjudication.json": _json_bytes(adjudication),
        private_root / "reminder.json": _json_bytes(reminder),
    })
    return {"status": "adjudicated_margin_overheat_cash_control",
            "adjudication": adjudication, "reminder": reminder}


def settle_margin_overheat_from_daily_cache(*, root: str | Path,
                                            daily_cache_document: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute all private captures from one existing cache, then commit one artifact set."""
    private_root = _private_root(root)
    _recover_private_artifact_set(private_root)
    document = _cache_document(daily_cache_document)
    program = _load_private_json(private_root / "program.json", "program manifest")
    if program != _margin_capture_program(load_governance()):
        raise MarginOverheatCashControlError("margin-overheat program manifest drifted")
    ledger = _load_private_json(private_root / "ledger.json", "ledger")
    validate_margin_ledger(ledger)
    weeks_root = private_root / "weeks"
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
        _validate_margin_capture(capture)
        validate_margin_source_receipt(receipt, capture)
        if capture["payload"]["daily_cache_digest"] != _digest(document):
            raise MarginOverheatCashControlError(
                "margin-overheat daily cache digest does not match capture"
            )
        captures[week_dir.name] = capture
        receipts[week_dir.name] = receipt
        outcome = _settle_capture(capture, document)
        outcomes[week_dir.name] = outcome
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
            "capture_sha256": capture["payload_sha256"],
            "outcome_sha256": outcome["payload_sha256"],
            "status": outcome["payload"]["status"],
            "forward_eligible": bool(capture["payload"]["forward_eligible"]),
        })
    new_ledger = dict(ledger)
    new_ledger["entries"] = new_entries
    validate_margin_ledger(new_ledger)
    adjudication, reminder = _adjudication_documents(new_ledger, outcomes)
    writes: dict[Path, bytes] = {
        private_root / "ledger.json": _json_bytes(new_ledger),
        private_root / "adjudication.json": _json_bytes(adjudication),
        private_root / "reminder.json": _json_bytes(reminder),
    }
    for date, outcome in outcomes.items():
        receipt = copy.deepcopy(receipts[date])
        receipt["payload"]["settlement"] = {
            "outcome_sha256": outcome["payload_sha256"],
            "status": outcome["payload"]["status"],
            "daily_cache_digest": _digest(document),
        }
        _schema_validate(receipt, RECEIPT_SCHEMA_PATH)
        writes[private_root / "weeks" / date / "outcome.json"] = _json_bytes(outcome)
        writes[private_root / "weeks" / date / "source_receipt.json"] = _json_bytes(receipt)
    from engine.a_short_artifact_set_transaction import commit_artifact_set
    commit_artifact_set(_private_journal_dir(private_root), writes)
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
            root=private_root, daily_cache_document=document
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
