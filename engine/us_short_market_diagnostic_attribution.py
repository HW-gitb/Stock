"""Pure, source-bound attribution for the US-short diagnostic track.

Knife 6 explains a completed v1 comparison; it does not change the v1
weekly record, selection, action advice, NAV, or any account state.  Callers
must provide the point-in-time inputs.  In particular, this module never
fetches VTI, a T-bill series, provider data, or account data, and it never
turns an unavailable input into zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from engine.us_short_market_diagnostic import (
    BOUNDARY as V1_BOUNDARY,
    MarketDiagnosticError,
    compound_wealth,
    validate_weekly_record,
    window_containing_week,
)
from engine.us_short_model_paper_portfolio import ModelPaperPortfolioError, canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
INPUT_SCHEMA = "us_short_market_diagnostic_attribution_input.schema.json"
REPORT_SCHEMA = "us_short_market_diagnostic_attribution_report.schema.json"
# Both schemas pin every one of these ten flags with `const` and close the
# object, so a boundary that parses is already exactly this dict. A second
# comparison in code could never fire (verified by plant: making it a no-op
# reddens nothing), and CLAUDE.md section 5 asks us not to block the same
# impossible input at every layer. What DOES need guarding is the two sources
# agreeing, and that is a test, not a runtime check.
ATTRIBUTION_BOUNDARY = {
    **V1_BOUNDARY,
    "v1_record_mutated": False,
    "historical_backfill_performed": False,
    "provider_fetch_performed": False,
    "account_write_performed": False,
}
_SHA256 = set("0123456789abcdef")
_TOLERANCE = 1e-12
# How long a cash observation's declared period may be. This bounds the LABEL, and
# a label bound is nearly worthless on its own: a 10-day cap was passed trivially
# by declaring a legal 7-day period and putting a month's accrual in
# `weekly_return`, which flipped the published exposure effect's sign. Worse, 10
# rejected honest weeks -- `valuation_date` has no cadence rule of its own (only
# `decision_date` is pinned to exactly seven days), so ordinary settlement-lag
# drift makes a real gap of 11+. The real work is done by the magnitude band
# below; this stays only wide enough that no honest week is refused.
_MAX_CASH_EFFECTIVE_DAYS = 21
# What the NUMBER has to look like. A 3M T-bill's weekly return, annualised over
# its own declared period, must land in a plausible band. This catches the two
# realistic producer errors no date check can see: an annualised rate written into
# a weekly slot (annualises to ~235%), and a month's accrual written into a week's
# (~16%). Note what that second number means -- a month of accrual is
# indistinguishable BY MAGNITUDE from a genuine 1981-style 16% bill, so this bound
# is a units-error catcher, not a market-plausibility oracle. 10% is comfortably
# above anything since 1990 and below the month-in-a-week error. If a real 3M bill
# ever exceeds it, widen this deliberately and say so; do not widen it to make a
# failing producer pass.
# The canonical diagnostic week. The lifecycle pins the decision cadence to
# exactly this (`_require_weekly_cadence`), the report compounds exactly one row
# per week, and the band below annualises over exactly this. One constant, so the
# three cannot drift. Two earlier attempts hung the band on a length the PRODUCER
# chose -- first the declared effective span, then the valuation gap -- and each
# time the same dishonest number got through by widening the lever. A quantity
# that calibrates a check must not be one the checked party controls.
_WEEK_DAYS = 7
_DAYS_PER_YEAR = 365.0
_MIN_CASH_ANNUALISED = -0.01
_MAX_CASH_ANNUALISED = 0.10
_VALIDATORS: dict[str, Draft7Validator] = {}


class AttributionError(ValueError):
    """Raised when attribution inputs are ambiguous or violate the boundary."""


def _fail(message: str) -> None:
    raise AttributionError(message)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{field} must be an object")
    return value


def _finite(value: object, field: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{field} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise AttributionError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        _fail(f"{field} must be a finite number")
    return result


def _return(value: object, field: str, *, allow_none: bool = False) -> float | None:
    result = _finite(value, field, allow_none=allow_none)
    if result is not None and result <= -1.0:
        _fail(f"{field} must be greater than -1")
    return result


def _date8(value: object, field: str) -> date:
    if not isinstance(value, str) or len(value) != 8 or not value.isascii() or not value.isdigit():
        _fail(f"{field} must be an eight-digit date")
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError as exc:
        raise AttributionError(f"{field} is not a real calendar date") from exc


def _available_date(value: object, field: str) -> date:
    if not isinstance(value, str) or not value:
        _fail(f"{field} must be a non-empty RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AttributionError(f"{field} must be a parseable RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        _fail(f"{field} must include a timezone")
    return parsed.date()


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _SHA256 for char in value):
        _fail(f"{field} must be a lowercase sha256")
    return value


def _reasons(value: object, field: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        _fail(f"{field} must be an array of reasons")
    result: list[str] = []
    for index, reason in enumerate(value):
        if not isinstance(reason, str) or not reason:
            _fail(f"{field}[{index}] must be a non-empty string")
        if reason not in result:
            result.append(reason)
    if required and not result:
        _fail(f"{field} must explain why the input is unavailable")
    return result


def _refs(value: object, field: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        _fail(f"{field} must be an array of source digests")
    result: list[str] = []
    for index, source_ref in enumerate(value):
        digest = _sha(source_ref, f"{field}[{index}]")
        if digest not in result:
            result.append(digest)
    if required and not result:
        _fail(f"{field} must contain at least one source digest")
    if len(result) > 256:
        _fail(f"{field} contains too many source digests")
    return result


def _union(*groups: Iterable[str]) -> list[str]:
    result: list[str] = []
    for group in groups:
        for value in group:
            if value not in result:
                result.append(value)
    if len(result) > 256:
        _fail("attribution source_refs contains too many source digests")
    return result


def _validator(schema_name: str) -> Draft7Validator:
    validator = _VALIDATORS.get(schema_name)
    if validator is None:
        schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        validator = Draft7Validator(schema)
        _VALIDATORS[schema_name] = validator
    return validator


def _schema_validate(value: Any, schema_name: str, label: str) -> None:
    errors = sorted(_validator(schema_name).iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise AttributionError(f"{label} schema violation at {path}: {first.message}")


def _status_reasons(value: object, field: str, status: str) -> list[str]:
    return _reasons(value, field, required=status == "unavailable")


def _validate_strategy(strategy: Mapping[str, Any], field: str) -> list[str]:
    paper_evaluable = strategy.get("paper_evaluable")
    strategy_evaluable = strategy.get("strategy_evaluable")
    if not isinstance(paper_evaluable, bool) or not isinstance(strategy_evaluable, bool):
        _fail(f"{field} evaluability flags must be boolean")
    weekly_return = _return(strategy.get("weekly_return"), f"{field}.weekly_return", allow_none=True)
    weekly_record_sha = strategy.get("weekly_record_sha256")
    if weekly_record_sha is not None:
        _sha(weekly_record_sha, f"{field}.weekly_record_sha256")
    reasons = _reasons(strategy.get("data_quality_reasons"), f"{field}.data_quality_reasons")
    if strategy_evaluable:
        if not paper_evaluable:
            _fail(f"{field}.strategy_evaluable requires paper_evaluable")
        if weekly_return is None or weekly_record_sha is None or reasons:
            _fail(f"{field}.strategy_evaluable requires a complete source-bound return")
    elif weekly_return is not None:
        _fail(f"{field}.weekly_return must be null when strategy is unavailable")
    if not strategy_evaluable and not reasons:
        _fail(f"{field}.data_quality_reasons must explain the unavailable strategy")
    return reasons


def _validate_vti(vti: Mapping[str, Any], field: str) -> list[str]:
    status = vti.get("status")
    quality = vti.get("return_quality")
    if status not in {"evaluable", "unavailable"}:
        _fail(f"{field}.status is unknown")
    if quality not in {"total_return_evaluable", "unavailable"}:
        _fail(f"{field}.return_quality is unknown")
    weekly_return = _return(vti.get("weekly_return"), f"{field}.weekly_return", allow_none=True)
    sidecar = vti.get("sidecar_observation_sha256")
    if sidecar is not None:
        _sha(sidecar, f"{field}.sidecar_observation_sha256")
    source_refs = _refs(vti.get("source_refs"), f"{field}.source_refs")
    reasons = _status_reasons(vti.get("data_quality_reasons"), f"{field}.data_quality_reasons", status)
    if status == "evaluable":
        if quality != "total_return_evaluable" or weekly_return is None or sidecar is None:
            _fail(f"{field} evaluable status requires the VTI total-return sidecar")
        if sidecar not in source_refs:
            # Same rule the cash leg carries: the document an observation names has
            # to be inside the walk it claims to belong to, or section 16's
            # layer-by-layer traceability stops at this leg.
            _fail(f"{field}.sidecar_observation_sha256 must appear in {field}.source_refs")
        if reasons or not source_refs:
            _fail(f"{field} evaluable status cannot carry degraded or empty provenance")
    else:
        if quality != "unavailable" or weekly_return is not None or sidecar is not None:
            _fail(f"{field} unavailable status must not carry a VTI return")
        if source_refs:
            _fail(f"{field} unavailable status must not carry VTI observation provenance")
    return source_refs


def _validate_cash(
    cash: Mapping[str, Any],
    field: str,
    *,
    valuation_date: date,
    decision_date: date,
) -> list[str]:
    status = cash.get("status")
    if status not in {"evaluable", "unavailable"}:
        _fail(f"{field}.status is unknown")
    if cash.get("instrument") != "pit_3m_tbill":
        _fail(f"{field}.instrument must be pit_3m_tbill")
    weekly_return = _return(cash.get("weekly_return"), f"{field}.weekly_return", allow_none=True)
    source_sha = cash.get("source_sha256")
    if source_sha is not None:
        _sha(source_sha, f"{field}.source_sha256")
    source_refs = _refs(cash.get("source_refs"), f"{field}.source_refs")
    if source_sha is not None and source_sha not in source_refs:
        # The sibling v1 module binds each benchmark's price and dividend digests
        # into source_refs; the cash leg did not inherit that, so the document an
        # observation named sat outside the root -> week -> observation walk that
        # section 16 acceptance 1 asks for.
        _fail(f"{field}.source_sha256 must appear in {field}.source_refs")
    reasons = _status_reasons(cash.get("data_quality_reasons"), f"{field}.data_quality_reasons", status)
    date_fields = ("effective_start_date", "effective_end_date", "as_of_date")
    parsed_dates: dict[str, date | None] = {}
    for date_field in date_fields:
        value = cash.get(date_field)
        parsed_dates[date_field] = None if value is None else _date8(value, f"{field}.{date_field}")
    available_at = cash.get("available_at")
    available_day = None if available_at is None else _available_date(available_at, f"{field}.available_at")
    if status == "evaluable":
        if (
            weekly_return is None
            or source_sha is None
            or not source_refs
            or reasons
            or any(parsed_dates[name] is None for name in date_fields)
            or available_day is None
        ):
            _fail(f"{field} evaluable status requires complete PIT provenance")
        start = parsed_dates["effective_start_date"]
        end = parsed_dates["effective_end_date"]
        cash_as_of = parsed_dates["as_of_date"]
        assert start is not None and end is not None and available_day is not None
        if start >= end:
            _fail(f"{field} effective date range must be ordered")
        if end > valuation_date or cash_as_of > valuation_date:
            _fail(f"{field} contains cash data after the valuation date")
        # Everything above asks "is this in the past?"; nothing asked "is this
        # THIS week's rate?". Without the two checks below, one December row keyed
        # to twenty-six different weeks was accepted and became the whole cash leg
        # of the exposure-matched benchmark — the fixed cash rate design section
        # 12.7 forbids, wearing PIT clothes. Section 16 asks for effective-period,
        # as-of AND decision-time ordering; only decision-time was enforced.
        # Note the conjunction: `end > valuation_date` above and `valuation_date
        # <= end` here together force end == valuation_date exactly, so the
        # `start <= valuation_date` half can never fire. Kept as one readable
        # containment statement, and it buys a property worth naming: two weeks
        # can never share one cash observation.
        if not (start <= valuation_date <= end):
            _fail(
                f"{field} effective period does not cover this week's valuation date; "
                "a cash observation must price the week it is attached to"
            )
        span_days = (end - start).days
        if span_days > _MAX_CASH_EFFECTIVE_DAYS:
            _fail(
                f"{field} effective period spans more than {_MAX_CASH_EFFECTIVE_DAYS} days, so "
                "covering this week proves nothing about it"
            )
        # Annualised over the canonical week, which is the interval the report
        # compounds this number for and the one the lifecycle pins. Deliberately
        # NOT the declared span and NOT the valuation gap: both are chosen by the
        # same producer supplying the number, and each was in turn used to widen
        # the band until a month of accrual fitted through it.
        annualised = float(weekly_return) * _DAYS_PER_YEAR / _WEEK_DAYS
        if not (_MIN_CASH_ANNUALISED <= annualised <= _MAX_CASH_ANNUALISED):
            _fail(
                f"{field}.weekly_return annualises to {annualised:.4f} over the canonical "
                f"{_WEEK_DAYS}-day week the report compounds it for, which is not a 3M T-bill "
                "yield; a weekly slot cannot hold an annual rate or a month of accrual"
            )
        # `available <= decision` here plus `decision <= as_of` in the only caller
        # makes `available <= as_of` unconditional, so an as-of check on this field
        # was unreachable. Blocking the same impossible input at a second layer is
        # what CLAUDE.md section 5 asks us not to do.
        if available_day > decision_date:
            _fail(f"{field}.available_at is after the decision date")
    else:
        if (
            weekly_return is not None
            or source_sha is not None
            or source_refs
            or any(parsed_dates.values())
            or available_at is not None
        ):
            _fail(f"{field} unavailable status must not carry a cash observation")
    return source_refs


def _validate_target(
    target: Mapping[str, Any], field: str, *, decision_date: date | None = None
) -> list[str]:
    """Validate one target-exposure observation and bind it to the week it describes.

    ``decision_date`` is required in practice. The observation used to carry no
    date at all, so the ONLY thing tying it to week t was the caller's dictionary
    key — the same defect the cash leg had, one step further along: the cash row
    at least carried dates nobody compared, this one had none to compare. A target
    exposure IS the decision, so it must be as-of the decision date.
    """

    status = target.get("status")
    if status not in {"evaluable", "unavailable"}:
        _fail(f"{field}.status is unknown")
    source_refs = _refs(target.get("source_refs"), f"{field}.source_refs")
    observed = target.get("as_of_date")
    if status == "evaluable":
        if observed is None:
            _fail(f"{field}.as_of_date is required so the observation names the week it decides")
        observed_day = _date8(observed, f"{field}.as_of_date")
        if decision_date is not None and observed_day != decision_date:
            _fail(
                f"{field}.as_of_date does not match this week's decision date; a target exposure "
                "belongs to the decision it was taken at"
            )
    elif observed is not None:
        _fail(f"{field} unavailable status must not carry target-exposure inputs")
    reasons = _status_reasons(target.get("data_quality_reasons"), f"{field}.data_quality_reasons", status)
    component_names = (
        "carried_holdings_exposure",
        "new_order_exposure",
        "cash_capacity_exposure",
        "environment_position_cap",
        "long_only_cap",
    )
    values: dict[str, float | None] = {}
    for name in component_names:
        values[name] = _finite(target.get(name), f"{field}.{name}", allow_none=True)
    if status == "evaluable":
        if reasons or not source_refs or any(value is None or value < 0 or value > 1 for value in values.values()):
            _fail(f"{field} evaluable status requires bounded target-exposure inputs")
        if abs(values["long_only_cap"] - 1.0) > _TOLERANCE:
            _fail(f"{field}.long_only_cap must equal the long-only ceiling of 1")
    elif any(value is not None for value in values.values()) or source_refs:
        _fail(f"{field} unavailable status must not carry target-exposure inputs")
    return source_refs


def validate_attribution_input(
    packet: Mapping[str, Any], *, as_of_date: str | None = None
) -> dict[str, Any]:
    """Validate source binding, PIT ordering, and the Knife6 boundary."""

    value = dict(_mapping(packet, "attribution_input"))
    as_of = None if as_of_date is None else _date8(as_of_date, "as_of_date")
    _schema_validate(value, INPUT_SCHEMA, "attribution_input")
    root_refs = _refs(value["source_refs"], "attribution_input.source_refs", required=True)
    weeks = value["weeks"]
    if not weeks:
        _fail("attribution_input.weeks must not be empty")
    previous_week: int | None = None
    previous_decision: date | None = None
    previous_valuation: date | None = None
    week_pointers: list[str] = []
    seen_sidecars: set[str] = set()
    for index, raw_week in enumerate(weeks):
        week = _mapping(raw_week, f"weeks[{index}]")
        week_index = week["calendar_week_index"]
        try:
            expected = window_containing_week(week_index)
        except MarketDiagnosticError as exc:
            raise AttributionError(f"weeks[{index}].calendar_week_index is invalid") from exc
        if value["window_id"] != expected["window_id"]:
            _fail(f"weeks[{index}].calendar_week_index does not belong to window_id")
        if previous_week is not None and week_index != previous_week + 1:
            _fail("attribution weeks must be consecutive and ordered")
        decision = _date8(week["decision_date"], f"weeks[{index}].decision_date")
        valuation = _date8(week["valuation_date"], f"weeks[{index}].valuation_date")
        if valuation > decision:
            _fail(f"weeks[{index}] valuation_date cannot be after decision_date")
        if as_of is not None and (decision > as_of or valuation > as_of):
            _fail(f"weeks[{index}] contains future diagnostic data")
        # Ordering is not checked separately: a step of zero or a step backwards
        # is a step that is not seven days, which the rule below refuses with a
        # message that says more.
        # The same seven-day rule the lifecycle store enforces on every write
        # (`_require_weekly_cadence`). Named by rule rather than by module: the
        # authorization-conformance surface is selected by which modules NAME
        # the private store, and one such name in a comment pulled all thirty
        # functions of this pure calculator into it.
        # Stored records already satisfy it; a hand-built packet did not have to,
        # and the cash band annualises over exactly this interval, so a packet
        # that skipped or doubled a week would have been priced as if it had not.
        if previous_decision is not None and (decision - previous_decision).days != _WEEK_DAYS:
            _fail(
                f"attribution decision dates must advance exactly {_WEEK_DAYS} days; "
                "a calendar week is the canonical decision cadence"
            )
        if previous_valuation is not None and valuation <= previous_valuation:
            _fail("attribution valuation dates must be strictly increasing")

        week_refs = _refs(week["source_refs"], f"weeks[{index}].source_refs", required=True)
        # The layered binding: the root names this week, and this week carries its
        # own complete provenance. Requiring the root to CONTAIN every week's refs
        # is what forced the flat rollup that made 26 weeks unreachable.
        week_record_digest = _mapping(
            week["strategy"], f"weeks[{index}].strategy"
        ).get("weekly_record_sha256")
        if week_record_digest is None:
            _fail(f"weeks[{index}].strategy.weekly_record_sha256 is required to bind the week")
        if week_record_digest not in week_refs:
            _fail(f"weeks[{index}].source_refs must contain its own weekly_record_sha256")
        if week_record_digest not in root_refs:
            _fail(
                f"weeks[{index}] is not named by attribution_input.source_refs; the root must "
                "point at every week it claims to summarise"
            )
        week_pointers.append(week_record_digest)
        strategy = _mapping(week["strategy"], f"weeks[{index}].strategy")
        strategy_refs = []
        _validate_strategy(strategy, f"weeks[{index}].strategy")
        if strategy.get("weekly_record_sha256") is not None:
            strategy_refs.append(strategy["weekly_record_sha256"])
        vti_block = _mapping(week["vti"], f"weeks[{index}].vti")
        vti_refs = _validate_vti(vti_block, f"weeks[{index}].vti")
        vti_sidecar = vti_block.get("sidecar_observation_sha256")
        # The same class as the cash leg: one observation cannot price two weeks.
        # Copying week 1's VTI block into every week left one distinct return and
        # one distinct sidecar digest across the whole window, and validated.
        if vti_sidecar is not None:
            if vti_sidecar in seen_sidecars:
                _fail(
                    f"weeks[{index}].vti reuses a dividend-sidecar observation already used for "
                    "another week; one observation cannot price two weeks"
                )
            seen_sidecars.add(vti_sidecar)
        cash_refs = _validate_cash(
            _mapping(week["cash_return"], f"weeks[{index}].cash_return"),
            f"weeks[{index}].cash_return",
            valuation_date=valuation,
            decision_date=decision,
        )
        target_refs = _validate_target(
            _mapping(week["target_exposure"], f"weeks[{index}].target_exposure"),
            f"weeks[{index}].target_exposure",
            decision_date=decision,
        )
        nested_refs = _union(strategy_refs, vti_refs, cash_refs, target_refs)
        if not set(nested_refs).issubset(week_refs):
            _fail(f"weeks[{index}] source_refs do not cover all nested observations")
        previous_week = week_index
        previous_decision = decision
        previous_valuation = valuation
    # "One pointer per week" was asserted in the schema description and enforced
    # nowhere: the root could name weeks that had been dropped from `weeks`, two
    # weeks could share one pointer, and a 2-week packet could carry 24 unrelated
    # digests. Equality both ways is the whole invariant.
    if len(set(week_pointers)) != len(week_pointers):
        _fail("attribution_input weeks share a weekly_record_sha256; each week must be distinct")
    if sorted(root_refs) != sorted(week_pointers):
        _fail(
            "attribution_input.source_refs is not exactly one pointer per week; the root must "
            "name every week it summarises and nothing else"
        )
    return value


def calculate_target_exposure(target: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate rule-implied ``g*`` from supplied constraints only."""

    target_map = _mapping(target, "target_exposure")
    refs = _validate_target(target_map, "target_exposure")
    if target_map.get("status") != "evaluable":
        _fail("target_exposure is unavailable")
    carried = float(target_map["carried_holdings_exposure"])
    new_orders = float(target_map["new_order_exposure"])
    requested = carried + new_orders
    limits = {
        "cash_capacity_exposure": float(target_map["cash_capacity_exposure"]),
        "environment_position_cap": float(target_map["environment_position_cap"]),
        "long_only_cap": float(target_map["long_only_cap"]),
    }
    g_star = min([requested, *limits.values()])
    binding: list[str] = []
    if abs(requested - g_star) <= _TOLERANCE:
        binding.append("requested_exposure")
    binding.extend(name for name, limit in limits.items() if abs(limit - g_star) <= _TOLERANCE)
    return {
        "g_star": g_star,
        "requested_exposure": requested,
        "constraint_exposures": {
            "requested_exposure": requested,
            # Carried below so the published report can re-derive requested_exposure
            # instead of believing it. Without these two the validator re-derived
            # g* correctly and still accepted a filled position written in as a
            # rule target, because requested_exposure had no inputs to check.
            "carried_holdings_exposure": carried,
            "new_order_exposure": new_orders,
            **limits,
        },
        "binding_constraints": binding,
        "source_refs": refs,
    }


def _unavailable_cash(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "instrument": "pit_3m_tbill",
        "weekly_return": None,
        "effective_start_date": None,
        "effective_end_date": None,
        "as_of_date": None,
        "available_at": None,
        "source_sha256": None,
        "source_refs": [],
        "data_quality_reasons": [reason],
    }


def _unavailable_target(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "as_of_date": None,
        "carried_holdings_exposure": None,
        "new_order_exposure": None,
        "cash_capacity_exposure": None,
        "environment_position_cap": None,
        "long_only_cap": None,
        "source_refs": [],
        "data_quality_reasons": [reason],
    }


def _lookup_by_week(
    values: Mapping[int, Mapping[str, Any]] | None,
    week_index: int,
    field: str,
) -> Mapping[str, Any] | None:
    if values is None:
        return None
    # No type check: every caller runs `_reject_unknown_week_keys` first, which
    # refuses a non-mapping before any week is looked up. Keeping a second copy
    # here meant a plant against the real guard was absorbed by this one.
    if week_index in values:
        result = values[week_index]
    else:
        result = values.get(str(week_index))  # type: ignore[arg-type]
    if result is not None and not isinstance(result, Mapping):
        _fail(f"{field}[{week_index}] must be an object")
    return result


def _reject_unknown_week_keys(
    values: Mapping[int, Mapping[str, Any]] | None, known: set[int], field: str
) -> None:
    """A side-table key that matches no week is a mistake, not an empty result.

    Mistyping a key produced exactly the same packet as having no data at all —
    every week ``unavailable`` with reason ``..._not_available`` — so a typo was
    indistinguishable from an honest gap, which is the confusion this whole track
    keeps finding in itself.
    """

    if values is None:
        return
    # Before iterating. This guard runs ahead of the per-week lookups, so a
    # non-mapping reached `for key in values` and escaped as a bare TypeError or
    # IndexError from a public entry -- the untyped-exception defect the register
    # already recorded as resolved once.
    if not isinstance(values, Mapping):
        _fail(f"{field} must be an object keyed by calendar week")
    unknown = []
    for key in values:
        # Accepting anything `int()` swallows was the bug in the guard itself:
        # `"01"`, `" 1"` and `1.5` all resolved to a known week here and were then
        # silently dropped by the lookup, which only tries `week_index` and
        # `str(week_index)`. The guard must accept exactly the two shapes the
        # lookup understands, or it certifies keys the lookup will discard.
        if isinstance(key, bool):
            unknown.append(repr(key))
            continue
        if isinstance(key, int):
            index = key
        elif isinstance(key, str) and key.isascii() and key.isdigit() and str(int(key)) == key:
            index = int(key)
        else:
            unknown.append(repr(key))
            continue
        if index not in known:
            unknown.append(repr(key))
    # `{1: a, "1": b}` passes every per-key test above and then loses one row
    # silently, because the lookup only ever reads the int form. Two spellings of
    # one week is a merge accident, not a choice to resolve quietly.
    seen: dict[int, object] = {}
    for key in values:
        if isinstance(key, bool):
            continue
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if index in seen and seen[index] != key:
            unknown.append(f"{seen[index]!r} and {key!r} both name week {index}")
        seen[index] = key
    if unknown:
        _fail(
            f"{field} is keyed to weeks this packet does not contain: {', '.join(sorted(unknown))}"
        )


def _reproducible_flag(
    values: Mapping[int, bool] | None, week_index: int
) -> bool:
    """Whether this week's decision instant can be reproduced; absent means yes."""

    if values is None:
        return True
    # No type check here: `_reject_unknown_week_keys` already refused a
    # non-mapping for all three side tables before any week is looked up, and
    # blocking the same impossible input twice is what hid that guard from its
    # own reverse case.
    if week_index in values:
        flag = values[week_index]
    else:
        flag = values.get(str(week_index), True)  # type: ignore[arg-type]
    # No type check: the schema pins `decision_time_reproducible` to `boolean`, so
    # a non-bool is refused as a schema violation before this value is read back.
    # Blocking it here too is the duplicate-layer pattern this module has now
    # removed five times.
    return flag


def build_attribution_input(
    weekly_records: Sequence[Mapping[str, Any]],
    *,
    attribution_epoch: str,
    target_exposure_by_week: Mapping[int, Mapping[str, Any]] | None = None,
    cash_return_by_week: Mapping[int, Mapping[str, Any]] | None = None,
    decision_time_reproducible_by_week: Mapping[int, bool] | None = None,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Build a source-bound Knife6 packet from already-persisted weekly rows.

    Missing target or PIT cash observations intentionally become explicit
    unavailable rows.  The builder does not infer them from NAV or substitute
    a fixed rate.
    """

    if isinstance(weekly_records, (str, bytes)) or not isinstance(weekly_records, Sequence) or not weekly_records:
        _fail("weekly_records must be a non-empty sequence")
    if not isinstance(attribution_epoch, str) or not attribution_epoch:
        _fail("attribution_epoch must be non-empty")
    normalized_rows: list[Mapping[str, Any]] = []
    first_identity: dict[str, Any] | None = None
    for index, raw_row in enumerate(weekly_records):
        row = _mapping(raw_row, f"weekly_records[{index}]")
        try:
            identity = validate_weekly_record(row, as_of_date=as_of_date)
        except MarketDiagnosticError as exc:
            raise AttributionError(f"weekly_records[{index}] violates the v1 weekly contract") from exc
        if first_identity is None:
            first_identity = identity
        elif identity["diagnostic_epoch"] != first_identity["diagnostic_epoch"]:
            _fail("weekly_records cannot silently join diagnostic epochs")
        normalized_rows.append(row)
    assert first_identity is not None

    known_weeks = {
        validate_weekly_record(row)["calendar_week_index"] for row in normalized_rows
    }
    _reject_unknown_week_keys(cash_return_by_week, known_weeks, "cash_return_by_week")
    _reject_unknown_week_keys(target_exposure_by_week, known_weeks, "target_exposure_by_week")
    _reject_unknown_week_keys(
        decision_time_reproducible_by_week, known_weeks, "decision_time_reproducible_by_week"
    )

    weeks: list[dict[str, Any]] = []
    root_refs: list[str] = []
    for index, row in enumerate(normalized_rows):
        try:
            identity = validate_weekly_record(row, as_of_date=as_of_date)
        except MarketDiagnosticError as exc:
            raise AttributionError(f"weekly_records[{index}] violates the v1 weekly contract") from exc
        week_index = identity["calendar_week_index"]
        try:
            record_digest = hashlib.sha256(canonical_json_bytes(dict(row))).hexdigest()
        except (ModelPaperPortfolioError, OverflowError, TypeError, ValueError) as exc:
            raise AttributionError(f"weekly_records[{index}] cannot be source-bound") from exc
        strategy = _mapping(row["strategy"], f"weekly_records[{index}].strategy")
        strategy_evaluable = bool(strategy["strategy_evaluable"])
        strategy_reasons = list(strategy.get("degradation_reasons", []))
        if not strategy_evaluable and not strategy_reasons:
            strategy_reasons.append("strategy_not_evaluable")
        weekly_strategy = {
            "paper_evaluable": bool(strategy["paper_evaluable"]),
            "strategy_evaluable": strategy_evaluable,
            "weekly_return": strategy.get("weekly_return") if strategy_evaluable else None,
            "weekly_record_sha256": record_digest,
            "data_quality_reasons": strategy_reasons,
        }

        benchmark = _mapping(row["benchmarks"]["VTI"], f"weekly_records[{index}].benchmarks.VTI")
        sidecar_digest = benchmark.get("dividend_sidecar_sha256")
        # Section 16 acceptance 3: VTI enters attribution only when Knife 5 says
        # total return AND the sidecar digest is there. The first conjunct is NOT
        # redundant with the v1 contract -- an earlier comment here claimed it was
        # and that was wrong. A v1-LEGAL record may carry
        # `return_quality="price_return_diagnostic"` with `benchmark_evaluable`
        # true, a degradation reason, and a present sidecar digest; the v1 rule
        # only forbids a sidecar when the benchmark is NOT evaluable. Deleting
        # this conjunct admits exactly that record as total-return evaluable,
        # which is the prohibition acceptance 3 exists for. Each conjunct now has
        # its own reverse case.
        vti_evaluable = (
            benchmark.get("return_quality") == "total_return_evaluable"
            and benchmark.get("benchmark_evaluable") is True
            and benchmark.get("weekly_return") is not None
            and sidecar_digest is not None
        )
        vti_refs = [sidecar_digest] if vti_evaluable else []
        vti_reasons = list(benchmark.get("data_quality_reasons", []))
        if not vti_evaluable and "vti_total_return_not_available" not in vti_reasons:
            vti_reasons.append("vti_total_return_not_available")
        vti = {
            "status": "evaluable" if vti_evaluable else "unavailable",
            "return_quality": "total_return_evaluable" if vti_evaluable else "unavailable",
            "weekly_return": benchmark.get("weekly_return") if vti_evaluable else None,
            "sidecar_observation_sha256": sidecar_digest if vti_evaluable else None,
            "source_refs": vti_refs,
            "data_quality_reasons": [] if vti_evaluable else vti_reasons,
        }

        cash = _lookup_by_week(cash_return_by_week, week_index, "cash_return_by_week")
        cash_value = dict(cash) if cash is not None else _unavailable_cash("pit_3m_tbill_not_available")
        target = _lookup_by_week(target_exposure_by_week, week_index, "target_exposure_by_week")
        target_value = dict(target) if target is not None else _unavailable_target("target_exposure_not_available")
        row_refs = _union(
            _refs(row["source_refs"], f"weekly_records[{index}].source_refs", required=True),
            [record_digest],
            vti_refs,
            _refs(cash_value.get("source_refs", []), f"cash_return_by_week[{week_index}].source_refs"),
            _refs(target_value.get("source_refs", []), f"target_exposure_by_week[{week_index}].source_refs"),
        )
        # LAYERED, not rolled up. The root used to be the union of every week's
        # provenance, which meant 26 weeks of honest per-ETF dividend digests blew
        # the 256 ceiling around week 24 — the one window this module exists to
        # produce was unreachable with real data. The root now carries one pointer
        # per week and each week stays complete in itself, so an auditor walks
        # root -> week -> observation instead of reading one flat list that has to
        # hold everything at once.
        root_refs = _union(root_refs, [record_digest])
        weeks.append(
            {
                "calendar_week_index": week_index,
                "decision_date": row["decision_date"],
                "valuation_date": row["valuation_date"],
                # Was a hardcoded literal. De-const-ing the schema let a
                # hand-written packet report the honest answer while the only
                # producer in the repo still could not, so the design's
                # "irreproducible decision time -> unavailable week" branch
                # remained unreachable from anything that actually runs.
                "decision_time_reproducible": _reproducible_flag(
                    decision_time_reproducible_by_week, week_index
                ),
                "strategy": weekly_strategy,
                "vti": vti,
                "cash_return": cash_value,
                "target_exposure": target_value,
                "source_refs": row_refs,
            }
        )
    packet = {
        "schema_name": "us_short_market_diagnostic_attribution_input",
        "schema_version": "1.0.0",
        "attribution_epoch": attribution_epoch,
        "diagnostic_epoch": first_identity["diagnostic_epoch"],
        "window_id": first_identity["window_id"],
        "weeks": weeks,
        "source_refs": root_refs,
        "boundary": dict(ATTRIBUTION_BOUNDARY),
    }
    return validate_attribution_input(packet, as_of_date=as_of_date)


# The weekly identity raw_excess = exposure_effect + active_system_effect is an
# ALGEBRAIC TAUTOLOGY, not a cross-check: with S, V and M the three effects are
# (S-V), (M-V) and (S-M), whose residual is identically zero. Sampling 500k
# realistic magnitudes gives a maximum residual of 1.11e-16. Do not mistake the
# residual assertion for verification, and do not add machinery around it — the
# real gate is the validator recomputing every effect from the raw returns.
def _normalise_effect(value: float) -> float:
    return 0.0 if abs(value) <= _TOLERANCE else value


def _compound_return(values: Iterable[object], field: str) -> float:
    try:
        return compound_wealth(values) - 1.0
    except MarketDiagnosticError as exc:
        raise AttributionError(f"{field} cannot be compounded into finite wealth") from exc


def _week_unavailable_reasons(week: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    strategy = week["strategy"]
    vti = week["vti"]
    cash = week["cash_return"]
    target = week["target_exposure"]
    if not strategy["strategy_evaluable"]:
        reasons.extend(strategy["data_quality_reasons"] or ["strategy_not_evaluable"])
    if vti["status"] != "evaluable":
        reasons.extend(vti["data_quality_reasons"] or ["vti_total_return_not_available"])
    if cash["status"] != "evaluable":
        reasons.extend(cash["data_quality_reasons"] or ["pit_3m_tbill_not_available"])
    if target["status"] != "evaluable":
        reasons.extend(target["data_quality_reasons"] or ["target_exposure_not_available"])
    # Design 12.7 lists an irreproducible decision time alongside the other three
    # missing inputs, all of which degrade the week to unavailable. It used to
    # reject the whole packet instead, so one irreproducible week killed a
    # 26-week report rather than marking that week.
    if week["decision_time_reproducible"] is not True:
        reasons.append("decision_time_not_reproducible")
    return list(dict.fromkeys(reasons))


def build_attribution_report(
    packet: Mapping[str, Any], *, as_of_date: str | None = None
) -> dict[str, Any]:
    """Return a complete report only when every week has all four inputs."""

    value = validate_attribution_input(packet, as_of_date=as_of_date)
    output_weeks: list[dict[str, Any]] = []
    evaluable_rows: list[dict[str, Any]] = []
    root_refs = list(value["source_refs"])
    for week in value["weeks"]:
        strategy = week["strategy"]
        vti = week["vti"]
        cash = week["cash_return"]
        target = week["target_exposure"]
        refs = _union(
            week["source_refs"],
            [strategy["weekly_record_sha256"]] if strategy["weekly_record_sha256"] else [],
            vti["source_refs"],
            cash["source_refs"],
            target["source_refs"],
        )
        # Layered, as in the input: one pointer per week, each week self-contained.
        root_refs = _union(
            root_refs, [strategy["weekly_record_sha256"]] if strategy["weekly_record_sha256"] else []
        )
        reasons = _week_unavailable_reasons(week)
        if reasons:
            output_weeks.append(
                {
                    "calendar_week_index": week["calendar_week_index"],
                    "decision_date": week["decision_date"],
                    "valuation_date": week["valuation_date"],
                    "weekly_record_sha256": strategy["weekly_record_sha256"],
                    "target_exposure_source_refs": list(target["source_refs"]),
                    "status": "unavailable",
                    "strategy_weekly_return": None,
                    "vti_total_return": None,
                    "cash_weekly_return": None,
                    "g_star": None,
                    "requested_exposure": None,
                    "constraint_exposures": {
                        "requested_exposure": None,
                        "carried_holdings_exposure": None,
                        "new_order_exposure": None,
                        "cash_capacity_exposure": None,
                        "environment_position_cap": None,
                        "long_only_cap": None,
                    },
                    "matched_target_return": None,
                    "raw_excess": None,
                    "exposure_effect": None,
                    "active_system_effect": None,
                    "identity_residual": None,
                    "binding_constraints": [],
                    "source_refs": refs,
                    "unavailable_reasons": reasons,
                }
            )
            continue

        target_calc = calculate_target_exposure(target)
        strategy_return = float(strategy["weekly_return"])
        vti_return = float(vti["weekly_return"])
        cash_return = float(cash["weekly_return"])
        g_star = target_calc["g_star"]
        matched = g_star * vti_return + (1.0 - g_star) * cash_return
        raw_excess = strategy_return - vti_return
        exposure_effect = matched - vti_return
        active_effect = strategy_return - matched
        residual = _normalise_effect(raw_excess - exposure_effect - active_effect)
        row = {
            "calendar_week_index": week["calendar_week_index"],
            "decision_date": week["decision_date"],
            "valuation_date": week["valuation_date"],
            "weekly_record_sha256": strategy["weekly_record_sha256"],
            "target_exposure_source_refs": list(target["source_refs"]),
            "status": "evaluable",
            "strategy_weekly_return": strategy_return,
            "vti_total_return": vti_return,
            "cash_weekly_return": cash_return,
            "g_star": g_star,
            "requested_exposure": target_calc["requested_exposure"],
            "constraint_exposures": target_calc["constraint_exposures"],
            "matched_target_return": matched,
            "raw_excess": raw_excess,
            "exposure_effect": exposure_effect,
            "active_system_effect": active_effect,
            "identity_residual": residual,
            "binding_constraints": target_calc["binding_constraints"],
            "source_refs": refs,
            "unavailable_reasons": [],
        }
        output_weeks.append(row)
        evaluable_rows.append(row)

    evaluable_count = len(evaluable_rows)
    unavailable_count = len(output_weeks) - evaluable_count
    if unavailable_count:
        summary = {
            "calendar_weeks": len(output_weeks),
            "evaluable_weeks": evaluable_count,
            "unavailable_weeks": unavailable_count,
            "strategy_cumulative_return": None,
            "vti_cumulative_return": None,
            "matched_target_cumulative_return": None,
            "raw_excess": None,
            "exposure_effect": None,
            "active_system_effect": None,
            "identity_residual": None,
            "weekly_identity_max_abs_residual": None,
        }
        status = "unavailable"
    else:
        strategy_cumulative = _compound_return(
            (row["strategy_weekly_return"] for row in evaluable_rows),
            "strategy cumulative return",
        )
        vti_cumulative = _compound_return(
            (row["vti_total_return"] for row in evaluable_rows),
            "VTI cumulative return",
        )
        target_cumulative = _compound_return(
            (row["matched_target_return"] for row in evaluable_rows),
            "matched-target cumulative return",
        )
        raw_excess = strategy_cumulative - vti_cumulative
        exposure_effect = target_cumulative - vti_cumulative
        active_effect = strategy_cumulative - target_cumulative
        summary = {
            "calendar_weeks": len(output_weeks),
            "evaluable_weeks": evaluable_count,
            "unavailable_weeks": 0,
            "strategy_cumulative_return": strategy_cumulative,
            "vti_cumulative_return": vti_cumulative,
            "matched_target_cumulative_return": target_cumulative,
            "raw_excess": raw_excess,
            "exposure_effect": exposure_effect,
            "active_system_effect": active_effect,
            "identity_residual": _normalise_effect(raw_excess - exposure_effect - active_effect),
            "weekly_identity_max_abs_residual": max(
                abs(row["identity_residual"]) for row in evaluable_rows
            ),
        }
        status = "evaluable"
    report = {
        "schema_name": "us_short_market_diagnostic_attribution_report",
        "schema_version": "1.0.0",
        "attribution_epoch": value["attribution_epoch"],
        "diagnostic_epoch": value["diagnostic_epoch"],
        "window_id": value["window_id"],
        "status": status,
        "weeks": output_weeks,
        "summary": summary,
        "source_refs": root_refs,
        "boundary": dict(ATTRIBUTION_BOUNDARY),
    }
    return validate_attribution_report(report, as_of_date=as_of_date)


def validate_attribution_report(
    report: Mapping[str, Any], *, as_of_date: str | None = None
) -> dict[str, Any]:
    """Validate a report produced by :func:`build_attribution_report`."""

    value = dict(_mapping(report, "attribution_report"))
    as_of = None if as_of_date is None else _date8(as_of_date, "as_of_date")
    _schema_validate(value, REPORT_SCHEMA, "attribution_report")
    root_refs = _refs(value["source_refs"], "attribution_report.source_refs", required=True)
    max_residual = 0.0
    evaluable_count = 0
    unavailable_count = 0
    evaluable_rows: list[Mapping[str, Any]] = []
    previous_week: int | None = None
    previous_decision: date | None = None
    previous_valuation: date | None = None
    report_pointers: list[str] = []
    for index, week in enumerate(value["weeks"]):
        try:
            expected_window = window_containing_week(week["calendar_week_index"])
        except MarketDiagnosticError as exc:
            raise AttributionError(
                f"attribution_report.weeks[{index}].calendar_week_index is invalid"
            ) from exc
        if expected_window["window_id"] != value["window_id"]:
            _fail(f"attribution_report.weeks[{index}] does not belong to window_id")
        if previous_week is not None and week["calendar_week_index"] != previous_week + 1:
            _fail("attribution report weeks must be consecutive and ordered")
        decision = _date8(week["decision_date"], f"attribution_report.weeks[{index}].decision_date")
        valuation = _date8(week["valuation_date"], f"attribution_report.weeks[{index}].valuation_date")
        if valuation > decision:
            _fail(f"attribution_report.weeks[{index}] valuation_date cannot be after decision_date")
        if as_of is not None and (decision > as_of or valuation > as_of):
            _fail(f"attribution_report.weeks[{index}] contains future diagnostic data")
        # As on the input side, ordering needs no separate check: the cadence
        # rule below already refuses every step that is not exactly seven days.
        # The same cadence the input gate enforces. `validate_attribution_report`
        # is the only independent check a report gets once it has been persisted,
        # sent between processes, or hand-edited, so a rule that lives only on the
        # input side is absent exactly when it is needed. Without this, twenty-six
        # consecutive DAYS published as a twenty-six WEEK verdict, which a reader
        # of the scorecard cannot see.
        if previous_decision is not None and (decision - previous_decision).days != _WEEK_DAYS:
            _fail(
                f"attribution report decision dates must advance exactly {_WEEK_DAYS} days; "
                "a calendar week is the canonical decision cadence"
            )
        if previous_valuation is not None and valuation <= previous_valuation:
            _fail("attribution report valuation dates must be strictly increasing")
        previous_week = week["calendar_week_index"]
        previous_decision = decision
        previous_valuation = valuation
        refs = _refs(week["source_refs"], f"attribution_report.weeks[{index}].source_refs", required=True)
        # Layered, matching the input: the root names each week by ITS OWN record
        # digest and each week owns its complete provenance. "Shares any digest
        # with the root" was vacuous — every week could carry week 1's digest and
        # nothing else, losing all per-week provenance, and still validate.
        pointer = week.get("weekly_record_sha256")
        _sha(pointer, f"attribution_report.weeks[{index}].weekly_record_sha256")
        if pointer not in refs:
            _fail(
                f"attribution_report.weeks[{index}].source_refs must contain its own "
                "weekly_record_sha256"
            )
        # Published provenance that resolves to nothing is worse than none: it
        # invites a reader to check something they cannot. This field was carried
        # into the report and then never mentioned by the validator, so an
        # evaluable week could publish an empty list, an invented digest, or
        # another week's target refs and still validate.
        target_refs = _refs(
            week.get("target_exposure_source_refs"),
            f"attribution_report.weeks[{index}].target_exposure_source_refs",
        )
        if not set(target_refs).issubset(refs):
            _fail(
                f"attribution_report.weeks[{index}].target_exposure_source_refs names digests "
                "this week does not carry; published provenance must resolve inside the artifact"
            )
        if week["status"] == "evaluable" and not target_refs:
            _fail(
                f"attribution_report.weeks[{index}] is evaluable but publishes no target-exposure "
                "provenance, so its exposures cannot be traced at all"
            )
        # Deliberately no "unavailable => empty" rule: a week can be unavailable
        # because its CASH is missing while its target exposure is perfectly good,
        # and erasing that provenance would hide what the producer did supply.
        # Subsumed by the root/pointer equality after the loop; kept because it
        # names the offending week, which the aggregate comparison cannot.
        if pointer not in root_refs:
            _fail(
                f"attribution_report.weeks[{index}] is not named by the report root; the root must "
                "point at every week it claims to summarise"
            )
        report_pointers.append(pointer)
        if week["status"] == "evaluable":
            evaluable_count += 1
            for field in ("strategy_weekly_return", "vti_total_return", "cash_weekly_return"):
                # `_finite` alone lets a return of -1.5 through, and in a MIXED
                # report no cumulative metric is published to catch it -- one
                # evaluable row then reports an active-system effect of about
                # +75pp. The input gate has always applied this floor; the report
                # gate is the only check a persisted report gets.
                _return(week[field], f"attribution_report.weeks[{index}].{field}")
            for field in (
                "strategy_weekly_return",
                "vti_total_return",
                "cash_weekly_return",
                "g_star",
                "requested_exposure",
                "matched_target_return",
                "raw_excess",
                "exposure_effect",
                "active_system_effect",
                "identity_residual",
            ):
                _finite(week[field], f"attribution_report.weeks[{index}].{field}")
            if not 0.0 <= float(week["g_star"]) <= 1.0:
                _fail(f"attribution_report.weeks[{index}].g_star is outside [0, 1]")
            # Every sibling number in this block has a range gate; the cash leg had
            # none, so an annual rate written into the weekly slot -- refused on the
            # input side -- was accepted here and flipped the sign of BOTH published
            # headline effects. The builder's cash always came through the input
            # band, so this can only ever reject something that did not.
            cash_annualised = float(week["cash_weekly_return"]) * _DAYS_PER_YEAR / _WEEK_DAYS
            if not _MIN_CASH_ANNUALISED <= cash_annualised <= _MAX_CASH_ANNUALISED:
                _fail(
                    f"attribution_report.weeks[{index}].cash_weekly_return annualises to "
                    f"{cash_annualised:.4f} over the canonical {_WEEK_DAYS}-day week, which is "
                    "not a 3M T-bill yield"
                )
            requested_exposure = float(week["requested_exposure"])
            if requested_exposure < 0.0 or requested_exposure > 2.0:
                _fail(f"attribution_report.weeks[{index}].requested_exposure is outside [0, 2]")
            constraint_exposures = _mapping(
                week["constraint_exposures"],
                f"attribution_report.weeks[{index}].constraint_exposures",
            )
            constraint_values = {
                name: _finite(
                    constraint_exposures.get(name),
                    f"attribution_report.weeks[{index}].constraint_exposures.{name}",
                )
                for name in (
                    "requested_exposure",
                    "cash_capacity_exposure",
                    "environment_position_cap",
                    "long_only_cap",
                )
            }
            if abs(float(constraint_values["requested_exposure"]) - requested_exposure) > _TOLERANCE:
                _fail(f"attribution_report.weeks[{index}] requested exposure is inconsistent")
            # Arithmetic consistency, NOT verification, and the difference
            # matters. `requested_exposure` must equal its two declared components
            # — but those components are themselves producer-supplied numbers that
            # nothing here can check against a holding, an order or a NAV, and
            # design 12.7 forbids this module from reading fills to try. Splitting
            # a filled 0.9 into carried 0.5 + new 0.4 still passes and still
            # shrinks the published exposure effect fivefold. This raises the bar
            # from "write one number" to "write two that sum to it". The producer
            # that closes it is built: `us_short_market_diagnostic_weekly_fetch.
            # load_target_exposures` reads both components off the note the
            # decision took while it still had them, and carries that note's
            # digest. What survives is only that THIS module cannot tell that
            # path from a caller who typed the two numbers in, which is why the
            # schema keeps its producer-asserted disclosure.
            components = {
                name: _finite(
                    constraint_exposures.get(name),
                    f"attribution_report.weeks[{index}].constraint_exposures.{name}",
                )
                for name in ("carried_holdings_exposure", "new_order_exposure")
            }
            if any(float(value) < 0.0 or float(value) > 1.0 for value in components.values()):
                _fail(
                    f"attribution_report.weeks[{index}] carries an out-of-range requested-exposure component"
                )
            expected_requested = float(components["carried_holdings_exposure"]) + float(
                components["new_order_exposure"]
            )
            if abs(expected_requested - requested_exposure) > _TOLERANCE:
                _fail(
                    f"attribution_report.weeks[{index}].requested_exposure is not the sum of the "
                    "carried and newly ordered exposure it claims to come from"
                )
            if any(
                float(constraint_values[name]) < 0.0 or float(constraint_values[name]) > 1.0
                for name in (
                    "cash_capacity_exposure",
                    "environment_position_cap",
                    "long_only_cap",
                )
            ):
                _fail(f"attribution_report.weeks[{index}] carries an invalid exposure constraint")
            if abs(float(constraint_values["long_only_cap"]) - 1.0) > _TOLERANCE:
                _fail(f"attribution_report.weeks[{index}] long_only_cap must equal 1")
            expected_g_star = min(float(value) for value in constraint_values.values())
            if abs(float(week["g_star"]) - expected_g_star) > _TOLERANCE:
                _fail(f"attribution_report.weeks[{index}].g_star is not the rule-implied minimum")
            expected_binding = [
                name
                for name, constraint_value in constraint_values.items()
                if abs(float(constraint_value) - expected_g_star) <= _TOLERANCE
            ]
            if week["binding_constraints"] != expected_binding:
                _fail(f"attribution_report.weeks[{index}].binding_constraints are not reproducible")
            identity = float(week["raw_excess"]) - float(week["exposure_effect"]) - float(
                week["active_system_effect"]
            )
            if abs(identity) > _TOLERANCE:
                _fail(f"attribution_report.weeks[{index}] violates the attribution identity")
            matched = float(week["g_star"]) * float(week["vti_total_return"]) + (
                1.0 - float(week["g_star"])
            ) * float(week["cash_weekly_return"])
            if abs(matched - float(week["matched_target_return"])) > _TOLERANCE:
                _fail(f"attribution_report.weeks[{index}] has an invalid matched target return")
            raw_excess = float(week["strategy_weekly_return"]) - float(week["vti_total_return"])
            exposure_effect = float(week["matched_target_return"]) - float(week["vti_total_return"])
            active_effect = float(week["strategy_weekly_return"]) - float(week["matched_target_return"])
            if (
                abs(raw_excess - float(week["raw_excess"])) > _TOLERANCE
                or abs(exposure_effect - float(week["exposure_effect"])) > _TOLERANCE
                or abs(active_effect - float(week["active_system_effect"])) > _TOLERANCE
                or abs(identity - float(week["identity_residual"])) > _TOLERANCE
            ):
                _fail(f"attribution_report.weeks[{index}] carries an inconsistent attribution effect")
            if week["unavailable_reasons"]:
                _fail(f"attribution_report.weeks[{index}] evaluable row carries unavailable reasons")
            max_residual = max(max_residual, abs(float(week["identity_residual"])))
            evaluable_rows.append(week)
        else:
            unavailable_count += 1
            if any(
                week[field] is not None
                for field in (
                    "strategy_weekly_return",
                    "vti_total_return",
                    "cash_weekly_return",
                    "g_star",
                    "requested_exposure",
                    "matched_target_return",
                    "raw_excess",
                    "exposure_effect",
                    "active_system_effect",
                    "identity_residual",
                )
            ):
                _fail(f"attribution_report.weeks[{index}] unavailable row carries a metric")
            if any(value is not None for value in week["constraint_exposures"].values()):
                _fail(f"attribution_report.weeks[{index}] unavailable row carries exposure constraints")
            if week["binding_constraints"]:
                _fail(f"attribution_report.weeks[{index}] unavailable row carries binding constraints")
            _reasons(week["unavailable_reasons"], f"attribution_report.weeks[{index}].unavailable_reasons", required=True)
    # Same exact-equality invariant as the input side: the root is one pointer per
    # week and nothing else, so a dropped week cannot leave an orphan pointer and
    # two weeks cannot share one.
    # Also subsumed by the equality below (the root is deduped, so a shared
    # pointer shortens it); kept for the message, which says what is wrong.
    if len(set(report_pointers)) != len(report_pointers):
        _fail("attribution_report weeks share a weekly_record_sha256; each week must be distinct")
    # Both sides are already deduped (`_refs`) and distinct (checked above), so
    # this is set equality expressed as sorted equality; neither form is weaker.
    if sorted(root_refs) != sorted(report_pointers):
        _fail(
            "attribution_report.source_refs is not exactly one pointer per week; the root must "
            "name every week it summarises and nothing else"
        )

    summary = value["summary"]
    for field in (
        "strategy_cumulative_return",
        "vti_cumulative_return",
        "matched_target_cumulative_return",
        "raw_excess",
        "exposure_effect",
        "active_system_effect",
        "identity_residual",
        "weekly_identity_max_abs_residual",
    ):
        _finite(summary[field], f"attribution_report.summary.{field}", allow_none=True)
    if summary["evaluable_weeks"] != evaluable_count or summary["unavailable_weeks"] != unavailable_count:
        _fail("attribution summary counts do not match weekly statuses")
    if summary["calendar_weeks"] != len(value["weeks"]):
        _fail("attribution summary calendar_weeks does not match weekly rows")
    if value["status"] == "evaluable":
        if unavailable_count or summary["unavailable_weeks"] != 0:
            _fail("evaluable report cannot contain unavailable weeks")
        if any(
            summary[field] is None
            for field in (
                "strategy_cumulative_return",
                "vti_cumulative_return",
                "matched_target_cumulative_return",
                "raw_excess",
                "exposure_effect",
                "active_system_effect",
                "identity_residual",
                "weekly_identity_max_abs_residual",
            )
        ):
            _fail("evaluable report must carry all summary metrics")
        summary_identity = float(summary["raw_excess"]) - float(summary["exposure_effect"]) - float(
            summary["active_system_effect"]
        )
        if abs(summary_identity) > _TOLERANCE:
            _fail("attribution summary violates the attribution identity")
        expected_strategy = _compound_return(
            (row["strategy_weekly_return"] for row in evaluable_rows),
            "attribution report strategy cumulative return",
        )
        expected_vti = _compound_return(
            (row["vti_total_return"] for row in evaluable_rows),
            "attribution report VTI cumulative return",
        )
        expected_target = _compound_return(
            (row["matched_target_return"] for row in evaluable_rows),
            "attribution report matched-target cumulative return",
        )
        expected_summary = {
            "strategy_cumulative_return": expected_strategy,
            "vti_cumulative_return": expected_vti,
            "matched_target_cumulative_return": expected_target,
            "raw_excess": expected_strategy - expected_vti,
            "exposure_effect": expected_target - expected_vti,
            "active_system_effect": expected_strategy - expected_target,
            "identity_residual": 0.0,
            "weekly_identity_max_abs_residual": max_residual,
        }
        if any(
            abs(float(summary[field]) - expected_value) > _TOLERANCE
            for field, expected_value in expected_summary.items()
        ):
            _fail("attribution summary is not derived from weekly rows")
    else:
        if unavailable_count == 0 or summary["unavailable_weeks"] == 0:
            _fail("unavailable report must identify an unavailable week")
        if any(
            summary[field] is not None
            for field in (
                "strategy_cumulative_return",
                "vti_cumulative_return",
                "matched_target_cumulative_return",
                "raw_excess",
                "exposure_effect",
                "active_system_effect",
                "identity_residual",
                "weekly_identity_max_abs_residual",
            )
        ):
            _fail("unavailable report must not carry partial summary metrics")
    if max_residual > _TOLERANCE:
        _fail("attribution identity residual is too large")
    return value


__all__ = [
    "ATTRIBUTION_BOUNDARY",
    "AttributionError",
    "build_attribution_input",
    "build_attribution_report",
    "calculate_target_exposure",
    "validate_attribution_input",
    "validate_attribution_report",
]
