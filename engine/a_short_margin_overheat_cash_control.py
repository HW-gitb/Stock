"""Knife 1 contract plus knife 2 predicate/shadow seam for the margin-overheat track.

It registers one independent comparison question, describes both measurement
stages, and prevents pre-freeze audit evidence from becoming a forward verdict.
Knife 2 adds only the source-bound structured predicate producer and the one
comparison-only shadow allocation consumer.  Capture, settlement, ledger,
adjudication, reminder and freeze wiring remain later knives.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import numbers
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
GOVERNANCE_PATH = ROOT / "presets" / "a_short_margin_overheat_cash_control_governance_20260808.json"
STAGE_A = "stage_a"
STAGE_B = "stage_b"
EVIDENCE_STATUSES = ("insufficient_data", "accumulating", "review_due")
COMPARISON_VERDICTS = ("not_evaluated", "inconclusive", "supported", "not_supported")
PREDICATE_SCHEMA_NAME = "a_short_margin_overheat_cash_control_predicate"
REPLAY_SCHEMA_NAME = "a_short_margin_overheat_cash_control_replay"
PREDICATE_SCHEMA_VERSION = "1.0.0"
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
