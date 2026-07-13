"""Pure offline assembly for the US-short manual corporate-action workflow.

The workflow binds already-produced private lifecycle, SEC-candidate, yfinance-alarm,
Massive-diagnostic, and manual-recorder artifacts to one security.  Only a validated
``confirmed_event`` from the existing manual recorder can make a private disposition ticket
eligible.  A strict SEC candidate is cross-checked when present but never promoted.  yfinance
and Massive remain advisory/diagnostic, and every §12.1 paper confirmation stays false.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from engine import us_short_corporate_action_disposition as disposition
from engine import us_short_corporate_action_event_recorder as recorder
from engine import us_short_security_identity as identity


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
OUTPUT_SCHEMA = SCHEMA_DIR / "us_short_corporate_action_workflow.schema.json"
SOURCE_SCHEMAS = {
    "lifecycle_observation": SCHEMA_DIR / "us_short_forward_lifecycle_observation.schema.json",
    "sec_parse_candidate": SCHEMA_DIR / "us_short_sec_corporate_action_parse_candidate.schema.json",
    "yfinance_daily_alarm": SCHEMA_DIR / "us_short_yfinance_corporate_action_alarm.schema.json",
    "massive_assessment": SCHEMA_DIR / "us_short_massive_corporate_action_assessment.schema.json",
}
_BLOCKING_ORDER = (
    "manual_event_missing",
    "manual_event_requires_review",
    "sec_candidate_confirmed_event_mismatch",
)
_FLAG_ORDER = (
    "lifecycle_trigger_present",
    "sec_candidate_terms_extracted",
    "sec_candidate_requires_manual_review",
    "yfinance_advisory_alarm",
    "yfinance_source_unavailable",
    "massive_unresolved_evidence",
    "massive_split_exact_diagnostic_only",
    "manual_event_confirmed",
)


class CorporateActionWorkflowError(ValueError):
    """One supplied workflow artifact is malformed, forged, or bound to another security."""


def _sha256_json(value: Any) -> str:
    try:
        encoded = json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise CorporateActionWorkflowError("workflow input is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def private_artifact_bytes(value: Any) -> bytes:
    """Return the canonical bytes used for private workflow and ticket persistence."""
    try:
        return (
            json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise CorporateActionWorkflowError("private workflow artifact is not canonical JSON") from exc


def _validator(path: Path):
    try:
        from jsonschema import Draft7Validator

        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        return Draft7Validator(schema)
    except (ImportError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CorporateActionWorkflowError("workflow schema dependency is unavailable") from exc


def _validate_schema(value: Any, *, path: Path, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CorporateActionWorkflowError(f"{label} must be an object")
    errors = sorted(_validator(path).iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "<root>"
        raise CorporateActionWorkflowError(f"{label} failed schema validation at {location}")
    return value


def _identity(record: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        validated = identity.validate_security_identity(record)
    except identity.SecurityIdentityError as exc:
        raise CorporateActionWorkflowError("security identity is invalid") from exc
    return validated, {
        "security_id": validated["security_id"],
        "issuer_cik": validated["issuer_cik"],
        "current_ticker": validated["current_ticker"],
        "identity_ref_sha256": _sha256_json(validated),
    }


def _evidence_ref(value: dict[str, Any], status: str) -> dict[str, str]:
    return {"artifact_ref_sha256": _sha256_json(value), "status": status}


def _validate_source_artifacts(
    *,
    security_binding: dict[str, Any],
    lifecycle_observation: Any | None,
    sec_parse_candidate: Any | None,
    yfinance_daily_alarm: Any | None,
    massive_assessment: Any | None,
    manual_event_record: Any | None,
) -> tuple[dict[str, Any], list[str]]:
    ticker = security_binding["current_ticker"]
    refs: dict[str, Any] = {
        "lifecycle_observation": None,
        "sec_parse_candidate": None,
        "yfinance_daily_alarm": None,
        "massive_assessment": None,
        "manual_event_record": None,
    }
    flags: list[str] = []

    if lifecycle_observation is not None:
        lifecycle = _validate_schema(
            lifecycle_observation,
            path=SOURCE_SCHEMAS["lifecycle_observation"],
            label="lifecycle_observation",
        )
        relevant = [event for event in lifecycle["events"] if event["symbol"] == ticker]
        if not relevant:
            raise CorporateActionWorkflowError("lifecycle observation has no event for the bound ticker")
        refs["lifecycle_observation"] = _evidence_ref(lifecycle, "trigger_present")
        flags.append("lifecycle_trigger_present")

    if sec_parse_candidate is not None:
        candidate = _validate_schema(
            sec_parse_candidate,
            path=SOURCE_SCHEMAS["sec_parse_candidate"],
            label="sec_parse_candidate",
        )
        if candidate["security_binding"] != {
            key: security_binding[key]
            for key in ("security_id", "current_ticker", "identity_ref_sha256")
        }:
            raise CorporateActionWorkflowError("SEC candidate is not identity-bound")
        refs["sec_parse_candidate"] = _evidence_ref(candidate, candidate["parse_status"])
        flags.append(
            "sec_candidate_terms_extracted"
            if candidate["parse_status"] == "candidate_terms_extracted"
            else "sec_candidate_requires_manual_review"
        )

    if yfinance_daily_alarm is not None:
        alarm = _validate_schema(
            yfinance_daily_alarm,
            path=SOURCE_SCHEMAS["yfinance_daily_alarm"],
            label="yfinance_daily_alarm",
        )
        if alarm["security_binding"] != {
            key: security_binding[key]
            for key in ("security_id", "current_ticker", "identity_ref_sha256")
        }:
            raise CorporateActionWorkflowError("yfinance alarm is not identity-bound")
        refs["yfinance_daily_alarm"] = _evidence_ref(alarm, alarm["alarm_status"])
        if alarm["alarm_status"] == "advisory_alarm":
            flags.append("yfinance_advisory_alarm")
        elif alarm["alarm_status"] == "source_unavailable":
            flags.append("yfinance_source_unavailable")

    if massive_assessment is not None:
        assessment = _validate_schema(
            massive_assessment,
            path=SOURCE_SCHEMAS["massive_assessment"],
            label="massive_assessment",
        )
        if assessment["evidence_binding"]["symbol"] != ticker:
            raise CorporateActionWorkflowError("Massive assessment is not ticker-bound")
        statuses = {row["status"] for row in assessment["event_assessments"]}
        status = "diagnostic_only" if statuses else "no_events"
        refs["massive_assessment"] = _evidence_ref(assessment, status)
        if "split_factor_exact_match" in statuses:
            flags.append("massive_split_exact_diagnostic_only")
        if statuses - {"split_factor_exact_match"}:
            flags.append("massive_unresolved_evidence")

    if manual_event_record is not None:
        try:
            manual = recorder.validate_manual_event_record(manual_event_record)
        except recorder.CorporateActionEventRecorderError as exc:
            raise CorporateActionWorkflowError("manual event record is invalid") from exc
        expected = {
            key: security_binding[key]
            for key in ("security_id", "issuer_cik", "current_ticker", "identity_ref_sha256")
        }
        if manual["security_binding"] != expected:
            raise CorporateActionWorkflowError("manual event record is not identity-bound")
        refs["manual_event_record"] = _evidence_ref(manual, manual["record_status"])
        if manual["record_status"] == "confirmed_event":
            flags.append("manual_event_confirmed")

    return refs, flags


def _sec_candidate_matches_confirmed(
    sec_parse_candidate: dict[str, Any] | None,
    manual_event_record: dict[str, Any] | None,
) -> bool:
    if sec_parse_candidate is None or manual_event_record is None:
        return True
    if manual_event_record["record_status"] != "confirmed_event":
        return True
    if sec_parse_candidate["source_binding"]["accession_number"] != manual_event_record["source_binding"]["sec_accession"]:
        return False
    if sec_parse_candidate["parse_status"] != "candidate_terms_extracted":
        return True
    candidate = sec_parse_candidate["event_candidate"]
    event = manual_event_record["confirmed_event"]
    return {
        "old_ticker": candidate["old_ticker"],
        "event_type": candidate["event_type"],
        "successor_ticker": candidate["successor_ticker"],
        "stock_ratio_numerator": candidate["exchange_ratio_numerator"],
        "stock_ratio_denominator": candidate["exchange_ratio_denominator"],
        "cash_per_old_share_cents": candidate["cash_per_share_cents"],
        "effective_date": candidate["effective_date"],
    } == {
        key: event[key]
        for key in (
            "old_ticker",
            "event_type",
            "successor_ticker",
            "stock_ratio_numerator",
            "stock_ratio_denominator",
            "cash_per_old_share_cents",
            "effective_date",
        )
    }


def validate_corporate_action_workflow(value: Any) -> dict[str, Any]:
    """Validate a workflow artifact before private persistence or later manual use."""
    return _validate_schema(value, path=OUTPUT_SCHEMA, label="corporate_action_workflow")


def build_corporate_action_workflow(
    *,
    identity_record: Any,
    lifecycle_observation: Any | None,
    sec_parse_candidate: Any | None,
    yfinance_daily_alarm: Any | None,
    massive_assessment: Any | None,
    manual_event_record: Any | None,
    disposition_ticket: Any | None,
) -> dict[str, Any]:
    """Assemble one source-bound manual workflow; never auto-confirm an event."""
    _, security_binding = _identity(identity_record)
    if all(
        value is None
        for value in (
            lifecycle_observation,
            sec_parse_candidate,
            yfinance_daily_alarm,
            massive_assessment,
            manual_event_record,
        )
    ):
        raise CorporateActionWorkflowError("at least one workflow input is required")
    refs, flags = _validate_source_artifacts(
        security_binding=security_binding,
        lifecycle_observation=lifecycle_observation,
        sec_parse_candidate=sec_parse_candidate,
        yfinance_daily_alarm=yfinance_daily_alarm,
        massive_assessment=massive_assessment,
        manual_event_record=manual_event_record,
    )
    blocking: list[str] = []
    if manual_event_record is None:
        blocking.append("manual_event_missing")
    elif manual_event_record["record_status"] != "confirmed_event":
        blocking.append("manual_event_requires_review")
    elif not _sec_candidate_matches_confirmed(sec_parse_candidate, manual_event_record):
        blocking.append("sec_candidate_confirmed_event_mismatch")

    eligible = not blocking
    ticket_ref = None
    if disposition_ticket is not None and not eligible:
        raise CorporateActionWorkflowError("blocked workflow cannot claim a private ticket")
    if disposition_ticket is not None:
        try:
            ticket = disposition.validate_manual_disposition(disposition_ticket)
        except disposition.CorporateActionDispositionError as exc:
            raise CorporateActionWorkflowError("private disposition ticket is invalid") from exc
        if ticket["event_binding"] != manual_event_record["confirmed_event"]:
            raise CorporateActionWorkflowError("private disposition ticket does not bind the confirmed event")
        ticket_ref = hashlib.sha256(private_artifact_bytes(ticket)).hexdigest()
    prepared = eligible and ticket_ref is not None
    status = (
        "manual_review_required"
        if blocking
        else "private_disposition_prepared"
        if prepared
        else "private_disposition_ready"
    )
    account_read = bool(
        manual_event_record is not None
        and manual_event_record["boundary"]["account_state_read"]
    )
    result = {
        "schema_name": "us_short_corporate_action_workflow",
        "schema_version": "1.0.0",
        "security_binding": security_binding,
        "input_evidence": refs,
        "workflow_status": status,
        "blocking_reasons": [reason for reason in _BLOCKING_ORDER if reason in blocking],
        "review_flags": [flag for flag in _FLAG_ORDER if flag in flags],
        "disposition": {
            "eligible": eligible,
            "private_ticket_prepared": prepared,
            "ticket_ref_sha256": ticket_ref,
        },
        "paper_confirmation_state": {
            "adjustment_mode_confirmed": False,
            "split_dividend_treatment_confirmed": False,
            "ex_date_price_consistency_confirmed": False,
            "paper_performance_evaluable": False,
            "paper_performance_blocked": True,
        },
        "boundary": {
            "provider_call_performed": False,
            "raw_payload_persisted": False,
            "corporate_action_semantics_auto_confirmed": False,
            "account_state_read": account_read,
            "account_state_mutated": False,
            "broker_order_placed": False,
            "return_calculation_performed": False,
            "selection_or_ranking_changed": False,
            "datahub_consumption_allowed": False,
            "paper_gate_confirmation_claimed": False,
            "ship_gate_evidence_claimed": False,
        },
    }
    return validate_corporate_action_workflow(result)
