"""Pure/offline manual recorder for source-bound US-short corporate-action events.

This is the confirmed-event upstream of ``us_short_corporate_action_disposition``.  An
operator manually transcribes a reviewed SEC accession/URL, whose EDGAR CIK must bind to the
old security or an identity-bound successor, into exact stock fractions and integer cents, then
explicitly confirms it.  The module never fetches SEC, persists a URL, reads an account, or
applies a disposition.  Unsafe or unsupported input produces a
ticker-scoped manual-review freeze rather than an inferred event.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from engine import us_short_corporate_action_disposition as disposition
from engine import us_short_security_identity as identity
from engine.us_short_eligibility_gate import canonical_us_ticker


_INPUT_KEYS = frozenset((
    "security_identity", "position", "old_ticker", "event_type", "successor_ticker",
    "successor_security_identity", "stock_ratio_numerator", "stock_ratio_denominator", "cash_per_old_share_usd",
    "effective_date", "sec_accession", "sec_url", "unsupported_consideration",
))
_EVENT_TYPES = frozenset(("stock_conversion", "cash_consideration", "stock_and_cash_consideration", "forced_exit"))
_STOCK_TYPES = frozenset(("stock_conversion", "stock_and_cash_consideration"))
_CASH_TYPES = frozenset(("cash_consideration", "stock_and_cash_consideration"))
_ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
_SEC_ARCHIVES_URL_RE = re.compile(
    r"^https://www\.sec\.gov/Archives/edgar/data/([0-9]{1,10})/([0-9]{18})/[A-Za-z0-9._-]+$"
)
_CASH_USD_RE = re.compile(r"^(0|[1-9][0-9]*)\.[0-9]{2}$")
_SECURITY_ID_RE = re.compile(r"^US-CIK-[0-9]{10}-(COMMON|CLASS_[A-Z]{1,3}|ADR|PREFERRED)$")
_MANUAL_EVENT_ID_RE = re.compile(r"^manual-sec-[0-9a-f]{24}$")


class CorporateActionEventRecorderError(ValueError):
    """The manual recorder cannot bind an event to a trusted security identity."""


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def _strict_ticker(value: Any, *, field: str) -> str:
    ticker = canonical_us_ticker(value)
    if ticker is None or value != ticker:
        raise CorporateActionEventRecorderError(f"{field} must be a canonical US ticker")
    return ticker


def _strict_positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CorporateActionEventRecorderError(f"{field} must be a positive integer")
    return value


def _strict_effective_date(value: Any) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise CorporateActionEventRecorderError("effective_date must be YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise CorporateActionEventRecorderError("effective_date must be a real calendar date") from exc


def _source_binding(
    manual: dict[str, Any], *, allowed_issuer_ciks: frozenset[str] | None = None
) -> dict[str, Any]:
    """Validate source evidence locally and retain only an accession plus digest in output."""
    accession = manual.get("sec_accession")
    url = manual.get("sec_url")
    match = _SEC_ARCHIVES_URL_RE.fullmatch(url) if type(url) is str and url.isascii() else None
    if (
        type(accession) is not str
        or _ACCESSION_RE.fullmatch(accession) is None
        or match is None
        or match.group(2) != accession.replace("-", "")
    ):
        raise CorporateActionEventRecorderError("SEC accession/URL evidence is malformed or inconsistent")
    evidence_issuer_cik = match.group(1).zfill(10)
    if allowed_issuer_ciks is not None and evidence_issuer_cik not in allowed_issuer_ciks:
        raise CorporateActionEventRecorderError("SEC evidence CIK must bind to the old or successor security")
    canonical_evidence = {"sec_accession": accession, "sec_url": url}
    return {
        "source_kind": "sec_manual_read",
        "sec_accession": accession,
        "evidence_issuer_cik": evidence_issuer_cik,
        "source_evidence_ref_sha256": _sha256_json(canonical_evidence),
    }


def _safe_source_binding(manual: Any) -> dict[str, Any]:
    if isinstance(manual, dict):
        try:
            return _source_binding(manual)
        except CorporateActionEventRecorderError:
            pass
    return {
        "source_kind": "sec_manual_read",
        "sec_accession": None,
        "evidence_issuer_cik": None,
        "source_evidence_ref_sha256": None,
    }


def _security_binding(record: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        record = identity.validate_security_identity(record)
    except identity.SecurityIdentityError as exc:
        raise CorporateActionEventRecorderError("security_identity must be a valid offline identity record") from exc
    return record, {
        "security_id": record["security_id"],
        "issuer_cik": record["issuer_cik"],
        "current_ticker": record["current_ticker"],
        "identity_ref_sha256": _sha256_json(record),
    }


def _manual_review(
    *,
    security_identity: dict[str, Any],
    security_binding: dict[str, Any],
    source_binding: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    freeze = identity.build_ticker_scoped_source_freeze(
        security_identity,
        source_id="sec_manual_entry",
        failure_class="source_contract_violation",
    )
    record = {
        "schema_name": "us_short_corporate_action_manual_event_record",
        "schema_version": "1.0.0",
        "record_status": "manual_review",
        "security_binding": security_binding,
        "successor_security_binding": None,
        "source_binding": source_binding,
        "confirmed_event": None,
        "manual_review": {"reason": reason, "ticker_scoped_freeze": freeze},
        "boundary": _boundary(),
    }
    validate_manual_event_record(record)
    return record


def _boundary() -> dict[str, bool]:
    return {
        "provider_call_performed": False,
        "raw_payload_read": False,
        "account_state_read": False,
        "account_state_mutated": False,
        "broker_order_placed": False,
        "selection_or_ranking_changed": False,
        "ship_gate_evidence_claimed": False,
    }


def _cash_cents(value: Any) -> int:
    if type(value) is not str or _CASH_USD_RE.fullmatch(value) is None:
        raise CorporateActionEventRecorderError("cash_per_old_share_usd must be an exact non-negative USD string with two decimals")
    dollars, cents = value.split(".")
    result = int(dollars) * 100 + int(cents)
    if result <= 0:
        raise CorporateActionEventRecorderError("cash_per_old_share_usd must be positive")
    return result


def _confirmed_event(
    manual: dict[str, Any], *, security_identity: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    if set(manual) != _INPUT_KEYS:
        raise CorporateActionEventRecorderError("manual input must have the exact recorder fields")
    old_ticker = _strict_ticker(manual["old_ticker"], field="old_ticker")
    if old_ticker != security_identity["current_ticker"]:
        raise CorporateActionEventRecorderError("old_ticker must match security_identity.current_ticker")
    event_type = manual["event_type"]
    if event_type not in _EVENT_TYPES:
        raise CorporateActionEventRecorderError("event_type is unsupported")
    successor = manual["successor_ticker"]
    successor = None if successor is None else _strict_ticker(successor, field="successor_ticker")
    numerator = manual["stock_ratio_numerator"]
    denominator = manual["stock_ratio_denominator"]
    if event_type in _STOCK_TYPES:
        numerator = _strict_positive_int(numerator, field="stock_ratio_numerator")
        denominator = _strict_positive_int(denominator, field="stock_ratio_denominator")
        if successor is None:
            raise CorporateActionEventRecorderError("stock event requires successor_ticker")
        successor_identity, successor_binding = _security_binding(manual["successor_security_identity"])
        if successor_identity["current_ticker"] != successor:
            raise CorporateActionEventRecorderError("successor_ticker must match successor_security_identity.current_ticker")
    elif any(value is not None for value in (successor, numerator, denominator)):
        raise CorporateActionEventRecorderError("non-stock event cannot carry successor or stock ratio")
    else:
        numerator = denominator = None
        if manual["successor_security_identity"] is not None:
            raise CorporateActionEventRecorderError("non-stock event cannot carry successor_security_identity")
        successor_binding = None
    cash = manual["cash_per_old_share_usd"]
    if event_type in _CASH_TYPES:
        cash = _cash_cents(cash)
    elif cash is not None:
        raise CorporateActionEventRecorderError("non-cash event cannot carry cash consideration")
    else:
        cash = None
    unsupported = manual["unsupported_consideration"]
    if unsupported is not None:
        raise CorporateActionEventRecorderError("unsupported consideration must be routed to manual review first")
    allowed_evidence_ciks = frozenset(
        (security_identity["issuer_cik"],)
        if successor_binding is None
        else (security_identity["issuer_cik"], successor_binding["issuer_cik"])
    )
    source_binding = _source_binding(manual, allowed_issuer_ciks=allowed_evidence_ciks)
    event_seed = {
        "security_id": security_identity["security_id"], "event_type": event_type, "old_ticker": old_ticker,
        "effective_date": _strict_effective_date(manual["effective_date"]),
        "source_evidence_ref_sha256": source_binding["source_evidence_ref_sha256"],
        "successor_ticker": successor, "stock_ratio_numerator": numerator,
        "stock_ratio_denominator": denominator, "cash_per_old_share_cents": cash,
    }
    event = {
        "event_id": f"manual-sec-{_sha256_json(event_seed)[:24]}",
        "event_type": event_type,
        "old_ticker": old_ticker,
        "effective_date": event_seed["effective_date"],
        "source_evidence_ref_sha256": source_binding["source_evidence_ref_sha256"],
        "source_confirmation": "manually_confirmed_source_bound",
        "successor_ticker": successor,
        "stock_ratio_numerator": numerator,
        "stock_ratio_denominator": denominator,
        "cash_per_old_share_cents": cash,
    }
    # Reuse the downstream planner as the only event-semantics authority and prove the injected
    # position can produce a manual-only ticket.  The ticket is intentionally not persisted here.
    disposition.build_manual_disposition(manual["position"], event)
    return event, source_binding, successor_binding


def record_manual_corporate_action(manual: Any, *, confirm: bool) -> dict[str, Any]:
    """Record an event only after explicit manual confirmation; otherwise freeze one ticker."""
    if type(confirm) is not bool:
        raise CorporateActionEventRecorderError("confirm must be boolean")
    if not isinstance(manual, dict):
        raise CorporateActionEventRecorderError("manual input must be an object with security_identity")
    security_identity, security_binding = _security_binding(manual.get("security_identity"))
    source_binding = _safe_source_binding(manual)
    if manual.get("unsupported_consideration") == "cvr":
        return _manual_review(
            security_identity=security_identity, security_binding=security_binding,
            source_binding=source_binding, reason="unsupported_consideration_cvr",
        )
    if not confirm:
        return _manual_review(
            security_identity=security_identity, security_binding=security_binding,
            source_binding=source_binding, reason="manual_confirmation_missing",
        )
    try:
        event, source_binding, successor_binding = _confirmed_event(manual, security_identity=security_identity)
    except (CorporateActionEventRecorderError, disposition.CorporateActionDispositionError):
        return _manual_review(
            security_identity=security_identity, security_binding=security_binding,
            source_binding=source_binding, reason="confirmed_event_input_invalid",
        )
    record = {
        "schema_name": "us_short_corporate_action_manual_event_record",
        "schema_version": "1.0.0",
        "record_status": "confirmed_event",
        "security_binding": security_binding,
        "successor_security_binding": successor_binding,
        "source_binding": source_binding,
        "confirmed_event": event,
        "manual_review": {"reason": None, "ticker_scoped_freeze": None},
        "boundary": _boundary(),
    }
    validate_manual_event_record(record)
    return record


def validate_manual_event_record(record: Any) -> dict[str, Any]:
    """Fail closed on a forged recorder output before it can be sent to the planner."""
    required = {"schema_name", "schema_version", "record_status", "security_binding", "successor_security_binding", "source_binding", "confirmed_event", "manual_review", "boundary"}
    if not isinstance(record, dict) or set(record) != required:
        raise CorporateActionEventRecorderError("manual event record has an unexpected top-level shape")
    if record["schema_name"] != "us_short_corporate_action_manual_event_record" or record["schema_version"] != "1.0.0":
        raise CorporateActionEventRecorderError("manual event record identity is invalid")
    binding = record["security_binding"]
    if not isinstance(binding, dict) or set(binding) != {"security_id", "issuer_cik", "current_ticker", "identity_ref_sha256"}:
        raise CorporateActionEventRecorderError("security binding is invalid")
    if type(binding["security_id"]) is not str or _SECURITY_ID_RE.fullmatch(binding["security_id"]) is None:
        raise CorporateActionEventRecorderError("security binding identifier is invalid")
    if type(binding["issuer_cik"]) is not str or not re.fullmatch(r"[0-9]{10}", binding["issuer_cik"]) or binding["security_id"].split("-", 3)[2] != binding["issuer_cik"]:
        raise CorporateActionEventRecorderError("security binding CIK is invalid")
    if not isinstance(binding["identity_ref_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", binding["identity_ref_sha256"]) is None:
        raise CorporateActionEventRecorderError("identity binding digest is invalid")
    _strict_ticker(binding["current_ticker"], field="security_binding.current_ticker")
    source = record["source_binding"]
    if not isinstance(source, dict) or set(source) != {"source_kind", "sec_accession", "evidence_issuer_cik", "source_evidence_ref_sha256"} or source["source_kind"] != "sec_manual_read":
        raise CorporateActionEventRecorderError("source binding is invalid")
    review = record["manual_review"]
    if not isinstance(review, dict) or set(review) != {"reason", "ticker_scoped_freeze"}:
        raise CorporateActionEventRecorderError("manual review shape is invalid")
    if record["boundary"] != _boundary():
        raise CorporateActionEventRecorderError("recorder boundary is invalid")
    if record["record_status"] == "confirmed_event":
        if review != {"reason": None, "ticker_scoped_freeze": None}:
            raise CorporateActionEventRecorderError("confirmed event cannot carry a manual-review disposition")
        if not (isinstance(source["sec_accession"], str) and _ACCESSION_RE.fullmatch(source["sec_accession"]) and isinstance(source["evidence_issuer_cik"], str) and re.fullmatch(r"[0-9]{10}", source["evidence_issuer_cik"]) and isinstance(source["source_evidence_ref_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", source["source_evidence_ref_sha256"])):
            raise CorporateActionEventRecorderError("confirmed event source binding is incomplete")
        event = record["confirmed_event"]
        if not isinstance(event, dict) or event.get("old_ticker") != binding["current_ticker"] or event.get("source_evidence_ref_sha256") != source["source_evidence_ref_sha256"]:
            raise CorporateActionEventRecorderError("confirmed event does not bind to recorder identity/source")
        if type(event.get("event_id")) is not str or _MANUAL_EVENT_ID_RE.fullmatch(event["event_id"]) is None:
            raise CorporateActionEventRecorderError("confirmed event identifier is invalid")
        successor_binding = record["successor_security_binding"]
        if event.get("event_type") in _STOCK_TYPES:
            if not isinstance(successor_binding, dict) or set(successor_binding) != set(binding):
                raise CorporateActionEventRecorderError("stock event successor binding is invalid")
            if type(successor_binding["security_id"]) is not str or _SECURITY_ID_RE.fullmatch(successor_binding["security_id"]) is None or type(successor_binding["issuer_cik"]) is not str or not re.fullmatch(r"[0-9]{10}", successor_binding["issuer_cik"]) or successor_binding["security_id"].split("-", 3)[2] != successor_binding["issuer_cik"] or type(successor_binding["identity_ref_sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", successor_binding["identity_ref_sha256"]) is None:
                raise CorporateActionEventRecorderError("stock event successor identity is invalid")
            _strict_ticker(successor_binding["current_ticker"], field="successor_security_binding.current_ticker")
            if event.get("successor_ticker") != successor_binding["current_ticker"]:
                raise CorporateActionEventRecorderError("stock event successor ticker is not identity-bound")
            allowed_evidence_ciks = {binding["issuer_cik"], successor_binding["issuer_cik"]}
        elif successor_binding is not None:
            raise CorporateActionEventRecorderError("non-stock event cannot carry a successor binding")
        else:
            allowed_evidence_ciks = {binding["issuer_cik"]}
        if source["evidence_issuer_cik"] not in allowed_evidence_ciks:
            raise CorporateActionEventRecorderError("confirmed event evidence CIK is not identity-bound")
        disposition.build_manual_disposition({"ticker": binding["current_ticker"], "direction": "long", "shares": 1}, event)
    elif record["record_status"] == "manual_review":
        if record["confirmed_event"] is not None or record["successor_security_binding"] is not None or review["reason"] not in {"manual_confirmation_missing", "unsupported_consideration_cvr", "confirmed_event_input_invalid"}:
            raise CorporateActionEventRecorderError("manual-review record is invalid")
        freeze = review["ticker_scoped_freeze"]
        if not isinstance(freeze, dict) or freeze.get("frozen_security_id") != binding["security_id"] or freeze.get("frozen_tickers") != [binding["current_ticker"]] or freeze.get("global_run_blocked") is not False:
            raise CorporateActionEventRecorderError("manual-review freeze is not safely bound")
    else:
        raise CorporateActionEventRecorderError("record_status is unsupported")
    return record
