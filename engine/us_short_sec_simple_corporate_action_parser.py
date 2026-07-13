"""Strict, fail-closed parser for simple SEC 8-K corporate-action terms.

The parser consumes one already source-bound filing document and emits only an
*unconfirmed candidate*.  It never confirms legal meaning, emits a planner event, reads an
account, or changes selection.  Only narrow, explicit 8-K/8-K-A cash and/or stock terms are
eligible.  DEFM14A, CVR, election/proration, adjustment and fractional-share language are
manual-review outcomes by design.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from html.parser import HTMLParser
from typing import Any

from engine.us_short_security_identity import SecurityIdentityError, validate_security_identity


_ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CIK_RE = re.compile(r"^[0-9]{10}$")
_SUPPORTED_FORMS = frozenset(("8-K", "8-K/A"))
_COMPLEX_TERMS = (
    "contingent value right",
    "cvr",
    "subject to adjustment",
    "election",
    "proration",
    "cash in lieu",
    "fractional share",
)
_MONTHS = {
    name: index
    for index, name in enumerate(
        ("January", "February", "March", "April", "May", "June", "July", "August",
         "September", "October", "November", "December"),
        start=1,
    )
}
_EFFECTIVE_RE = re.compile(
    r"\b(?:became|was)\s+effective(?:\s+as\s+of|\s+on)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"([0-9]{1,2}),\s+([0-9]{4})\b",
    re.IGNORECASE,
)
_CASH_RE = re.compile(
    r"\b(?:each|one)\s+(?:outstanding\s+)?share\b[^.;]{0,240}?"
    r"(?:right\s+to\s+receive|receive)\s+\$([0-9]{1,9}\.[0-9]{2})\s+in\s+cash\b",
    re.IGNORECASE,
)
_STOCK_RE = re.compile(
    r"\b(?:each|one)\s+(?:outstanding\s+)?share\b[^.;]{0,240}?"
    r"(?:right\s+to\s+receive|receive)\s+([0-9]{1,9}(?:\.[0-9]{1,12})?)\s+shares?\s+of\b",
    re.IGNORECASE,
)
_FILING_KEYS = frozenset((
    "provider_id", "issuer_cik", "form_type", "accession_number", "filed_date",
    "accepted_at", "observed_at", "document_ref_sha256", "document_text",
    "network_access_performed",
))


class SecCorporateActionParserError(ValueError):
    """The identity, provenance, or raw filing envelope is malformed or unbound."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._suppressed_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._suppressed_depth:
            self._suppressed_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._suppressed_depth:
            self.parts.append(data)


def _identity_ref_sha256(record: dict[str, Any]) -> str:
    canonical = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _validate_identity(record: Any, *, label: str) -> dict[str, Any]:
    try:
        return validate_security_identity(record)
    except SecurityIdentityError as exc:
        raise SecCorporateActionParserError(f"{label} is invalid") from exc


def _aware_timestamp(value: Any, *, field: str) -> datetime:
    if type(value) is not str or "T" not in value:
        raise SecCorporateActionParserError(f"{field} must be an aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise SecCorporateActionParserError(f"{field} must be an aware ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise SecCorporateActionParserError(f"{field} must be timezone-aware")
    return parsed


def _filed_date(value: Any) -> datetime:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise SecCorporateActionParserError("filed_date must be YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise SecCorporateActionParserError("filed_date must be a real date") from exc


def _plain_text(raw: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(raw)
        extractor.close()
    except (ValueError, TypeError) as exc:
        raise SecCorporateActionParserError("document_text could not be normalized") from exc
    return " ".join(" ".join(extractor.parts).split())


def _source_binding(filing: dict[str, Any]) -> dict[str, Any]:
    return {key: filing[key] for key in (
        "provider_id", "issuer_cik", "form_type", "accession_number", "filed_date",
        "accepted_at", "observed_at", "document_ref_sha256",
    )}


def _candidate_digest(binding: dict[str, Any]) -> str:
    canonical = json.dumps(binding, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _result(
    *,
    identity_record: dict[str, Any],
    filing: dict[str, Any],
    status: str,
    reasons: list[str],
    event: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_name": "us_short_sec_corporate_action_parse_candidate",
        "schema_version": "1.0.0",
        "security_binding": {
            "security_id": identity_record["security_id"],
            "current_ticker": identity_record["current_ticker"],
            "identity_ref_sha256": _identity_ref_sha256(identity_record),
        },
        "source_binding": _source_binding(filing),
        "parse_status": status,
        "manual_review_reasons": reasons,
        "event_candidate": event,
        "human_confirmation_required": True,
        "ticker_scoped_freeze_required": status != "candidate_terms_extracted",
        "boundary": {
            "provider_call_performed": filing["network_access_performed"],
            "raw_document_read": True,
            "raw_document_persisted": False,
            "source_semantics_confirmed": False,
            "planner_event_emitted": False,
            "account_state_read": False,
            "selection_or_ranking_changed": False,
            "broker_order_placed": False,
            "ship_gate_evidence_claimed": False,
        },
    }


def _validate_filing(
    filing: Any,
    *,
    identity_record: dict[str, Any],
    successor_identity_record: dict[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    if not isinstance(filing, dict) or set(filing) != _FILING_KEYS:
        raise SecCorporateActionParserError("filing must have the exact source-bound keys")
    if filing["provider_id"] != "sec_edgar":
        raise SecCorporateActionParserError("provider_id must be sec_edgar")
    cik = filing["issuer_cik"]
    if type(cik) is not str or _CIK_RE.fullmatch(cik) is None:
        raise SecCorporateActionParserError("issuer_cik must be a zero-padded ten-digit CIK")
    allowed_ciks = {identity_record["issuer_cik"]}
    if successor_identity_record is not None:
        allowed_ciks.add(successor_identity_record["issuer_cik"])
    if cik not in allowed_ciks:
        raise SecCorporateActionParserError("SEC filing CIK is not bound to the old or successor identity")
    if type(filing["form_type"]) is not str or not filing["form_type"] or len(filing["form_type"]) > 32:
        raise SecCorporateActionParserError("form_type must be a bounded non-empty string")
    if type(filing["accession_number"]) is not str or _ACCESSION_RE.fullmatch(filing["accession_number"]) is None:
        raise SecCorporateActionParserError("accession_number is invalid")
    if type(filing["document_ref_sha256"]) is not str or _SHA256_RE.fullmatch(filing["document_ref_sha256"]) is None:
        raise SecCorporateActionParserError("document_ref_sha256 is invalid")
    if type(filing["network_access_performed"]) is not bool:
        raise SecCorporateActionParserError("network_access_performed must be boolean")
    accepted = _aware_timestamp(filing["accepted_at"], field="accepted_at")
    observed = _aware_timestamp(filing["observed_at"], field="observed_at")
    if accepted > observed:
        raise SecCorporateActionParserError("accepted_at cannot be after observed_at")
    filed = _filed_date(filing["filed_date"])
    if filed.date() > accepted.date():
        raise SecCorporateActionParserError("filed_date cannot be after accepted_at")
    raw = filing["document_text"]
    if type(raw) is not str or not raw.strip() or len(raw) > 2_000_000:
        raise SecCorporateActionParserError("document_text must be a non-empty bounded string")
    return filing, _plain_text(raw)


def _effective_dates(text: str) -> list[str]:
    out: list[str] = []
    for month, day, year in _EFFECTIVE_RE.findall(text):
        try:
            date = datetime(int(year), _MONTHS[month.title()], int(day))
        except (ValueError, KeyError):
            continue
        out.append(date.strftime("%Y%m%d"))
    return out


def _cash_values(text: str) -> list[int]:
    values: list[int] = []
    for raw in _CASH_RE.findall(text):
        try:
            amount = Decimal(raw)
        except InvalidOperation:
            continue
        cents = amount * 100
        if cents == cents.to_integral_value() and cents > 0:
            values.append(int(cents))
    return values


def _stock_values(text: str) -> list[Fraction]:
    values: list[Fraction] = []
    for raw in _STOCK_RE.findall(text):
        try:
            value = Fraction(Decimal(raw))
        except (InvalidOperation, ValueError, ZeroDivisionError):
            continue
        if value > 0:
            values.append(value)
    return values


def _successor_text_bound(text: str, ticker: str) -> bool:
    escaped = re.escape(ticker)
    patterns = (
        rf"\bticker\s+symbol\s+(?:is|will\s+be)\s+[\"']?{escaped}[\"']?\b",
        rf"\b(?:NASDAQ|NYSE)\s*:\s*{escaped}\b",
    )
    return any(re.search(pattern, text, re.IGNORECASE) is not None for pattern in patterns)


def parse_simple_sec_corporate_action(
    *,
    identity_record: Any,
    filing: Any,
    successor_identity_record: Any | None = None,
) -> dict[str, Any]:
    """Extract a narrow candidate from one source-bound filing; never auto-confirm it."""
    old = _validate_identity(identity_record, label="identity_record")
    successor = None
    if successor_identity_record is not None:
        successor = _validate_identity(successor_identity_record, label="successor_identity_record")
        if successor["security_id"] == old["security_id"]:
            raise SecCorporateActionParserError("successor identity must differ from the old security")
    filing, text = _validate_filing(filing, identity_record=old, successor_identity_record=successor)

    if filing["form_type"] not in _SUPPORTED_FORMS:
        return _result(identity_record=old, filing=filing, status="manual_review",
                       reasons=["unsupported_form"], event=None)
    lowered = text.lower()
    if any(term in lowered for term in _COMPLEX_TERMS):
        return _result(identity_record=old, filing=filing, status="manual_review",
                       reasons=["complex_terms_present"], event=None)

    effective = _effective_dates(text)
    cash = _cash_values(text)
    stock = _stock_values(text)
    reasons: list[str] = []
    if len(effective) != 1:
        reasons.append("missing_or_ambiguous_effective_date")
    if len(cash) > 1:
        reasons.append("ambiguous_cash_terms")
    if len(stock) > 1:
        reasons.append("ambiguous_stock_terms")
    if not cash and not stock:
        reasons.append("consideration_not_exactly_extractable")
    if stock:
        if successor is None:
            reasons.append("successor_identity_missing")
        elif not _successor_text_bound(text, successor["current_ticker"]):
            reasons.append("successor_not_text_bound")
    if reasons:
        return _result(identity_record=old, filing=filing, status="manual_review",
                       reasons=sorted(set(reasons)), event=None)

    if stock and cash:
        event_type = "stock_and_cash_consideration"
    elif stock:
        event_type = "stock_conversion"
    else:
        event_type = "cash_consideration"
    ratio = stock[0] if stock else None
    binding = _source_binding(filing)
    event = {
        "old_ticker": old["current_ticker"],
        "event_type": event_type,
        "successor_ticker": successor["current_ticker"] if ratio is not None else None,
        "exchange_ratio_numerator": ratio.numerator if ratio is not None else None,
        "exchange_ratio_denominator": ratio.denominator if ratio is not None else None,
        "cash_per_share_cents": cash[0] if cash else None,
        "effective_date": effective[0],
        "source_evidence_ref_sha256": _candidate_digest(binding),
    }
    return _result(identity_record=old, filing=filing, status="candidate_terms_extracted",
                   reasons=[], event=event)
