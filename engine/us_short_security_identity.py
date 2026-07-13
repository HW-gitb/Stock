"""Pure/offline US-short security identity and ticker-scoped source-failure containment.

An identity is anchored to SEC CIK plus a security class, not to a ticker.  A ticker is
only the current label, so a rename cannot create a second security identity.  This module
does not load a security master, call a provider, read raw payloads, access accounts, or
change selection/ranking.  A provider failure therefore produces a manual-review freeze for
only the bound security/ticker; it never blocks the whole run or freezes unrelated symbols.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from engine.us_short_eligibility_gate import canonical_us_ticker


_CIK_RE = re.compile(r"^[0-9]{10}$")
_SECURITY_CLASS_RE = re.compile(r"^(COMMON|CLASS_[A-Z]{1,3}|ADR|PREFERRED)$")
_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXCHANGES = frozenset(("NYSE", "NASDAQ"))
_REQUIRED_RECORD_KEYS = frozenset((
    "schema_name", "schema_version", "security_id", "issuer_cik", "security_class",
    "current_ticker", "issuer_name", "primary_exchange", "observed_as_of",
    "source_binding", "boundary",
))
_REQUIRED_BOUNDARY_KEYS = frozenset((
    "provider_call_performed", "raw_payload_read", "security_master_completeness_claimed",
    "selection_or_ranking_changed", "account_state_read", "broker_or_order_automation_allowed",
))
_SOURCE_FAILURE_CLASSES = frozenset((
    "unavailable_or_malformed_response", "source_contract_violation", "source_stale_or_unavailable",
))


class SecurityIdentityError(ValueError):
    """The offline identity record or its ticker-scoped freeze request is malformed."""


class _SecurityIdentityRecord(dict):
    """Dict-compatible in-memory record retaining a local mutation guard until serialization."""

    __slots__ = ("_integrity_sha256",)


def _require_canonical_ticker(value: object) -> str:
    if not isinstance(value, str) or value != canonical_us_ticker(value):
        raise SecurityIdentityError("current_ticker must be an already canonical US ticker")
    return value


def _normalize_cik(value: object) -> str:
    if isinstance(value, bool):
        raise SecurityIdentityError("issuer_cik must not be boolean")
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) > 10:
        raise SecurityIdentityError("issuer_cik must be at most ten ASCII digits")
    return value.zfill(10)


def _require_security_class(value: object) -> str:
    if not isinstance(value, str) or not value.isascii() or not _SECURITY_CLASS_RE.fullmatch(value):
        raise SecurityIdentityError("security_class must be an uppercase canonical class")
    return value


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise SecurityIdentityError(f"{field} must be a lowercase SHA-256 hex digest")
    return value


def _require_source_id(value: object) -> str:
    if not isinstance(value, str) or not _SOURCE_ID_RE.fullmatch(value):
        raise SecurityIdentityError("source_id must be a canonical local identifier")
    return value


def _require_date(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise SecurityIdentityError("observed_as_of must be YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise SecurityIdentityError("observed_as_of must be a real calendar date") from exc
    return value


def _security_id(issuer_cik: str, security_class: str) -> str:
    return f"US-CIK-{issuer_cik}-{security_class}"


def _record_fingerprint(record: dict) -> str:
    canonical = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def record_security_identity(
    *,
    issuer_cik: object,
    security_class: object,
    current_ticker: object,
    issuer_name: object,
    primary_exchange: object,
    observed_as_of: object,
    source_id: object,
    source_ref_sha256: object,
) -> dict:
    """Create one source-bound identity record from manually supplied, already-authorized data.

    The function is deliberately data-source agnostic and pure.  It is not a security-master
    fetcher and makes no completeness claim; a later, separately authorized source update may
    change only ``current_ticker`` while preserving the CIK/class ``security_id``.
    """
    cik = _normalize_cik(issuer_cik)
    security_class = _require_security_class(security_class)
    ticker = _require_canonical_ticker(current_ticker)
    if not isinstance(issuer_name, str) or not issuer_name.strip():
        raise SecurityIdentityError("issuer_name must be a non-empty string")
    if primary_exchange not in _EXCHANGES:
        raise SecurityIdentityError("primary_exchange must be an allowed US exchange")
    record = _SecurityIdentityRecord({
        "schema_name": "us_short_security_identity_record",
        "schema_version": "1.0.0",
        "security_id": _security_id(cik, security_class),
        "issuer_cik": cik,
        "security_class": security_class,
        "current_ticker": ticker,
        "issuer_name": issuer_name,
        "primary_exchange": primary_exchange,
        "observed_as_of": _require_date(observed_as_of),
        "source_binding": {
            "source_id": _require_source_id(source_id),
            "source_ref_sha256": _require_sha256(source_ref_sha256, field="source_ref_sha256"),
        },
        "boundary": {
            "provider_call_performed": False,
            "raw_payload_read": False,
            "security_master_completeness_claimed": False,
            "selection_or_ranking_changed": False,
            "account_state_read": False,
            "broker_or_order_automation_allowed": False,
        },
    })
    record._integrity_sha256 = _record_fingerprint(record)
    return record


def validate_security_identity(record: object) -> dict:
    """Fail closed on drift/tampering and return the validated identity record."""
    if isinstance(record, _SecurityIdentityRecord):
        if record._integrity_sha256 != _record_fingerprint(record):
            raise SecurityIdentityError("in-memory identity record was modified after issuance")
    if not isinstance(record, dict) or set(record) != _REQUIRED_RECORD_KEYS:
        raise SecurityIdentityError("identity record must have the exact contract keys")
    if record["schema_name"] != "us_short_security_identity_record" or record["schema_version"] != "1.0.0":
        raise SecurityIdentityError("unsupported identity record schema")
    cik = _normalize_cik(record["issuer_cik"])
    if record["issuer_cik"] != cik:
        raise SecurityIdentityError("issuer_cik must be zero-padded canonical form")
    security_class = _require_security_class(record["security_class"])
    if record["security_id"] != _security_id(cik, security_class):
        raise SecurityIdentityError("security_id must derive exactly from issuer_cik and security_class")
    _require_canonical_ticker(record["current_ticker"])
    if not isinstance(record["issuer_name"], str) or not record["issuer_name"].strip():
        raise SecurityIdentityError("issuer_name must be a non-empty string")
    if record["primary_exchange"] not in _EXCHANGES:
        raise SecurityIdentityError("primary_exchange is not allowed")
    _require_date(record["observed_as_of"])
    binding = record["source_binding"]
    if not isinstance(binding, dict) or set(binding) != {"source_id", "source_ref_sha256"}:
        raise SecurityIdentityError("source_binding must have exact contract keys")
    _require_source_id(binding["source_id"])
    _require_sha256(binding["source_ref_sha256"], field="source_ref_sha256")
    boundary = record["boundary"]
    if not isinstance(boundary, dict) or set(boundary) != _REQUIRED_BOUNDARY_KEYS:
        raise SecurityIdentityError("identity boundary must have exact contract keys")
    if any(value is not False for value in boundary.values()):
        raise SecurityIdentityError("identity boundary claims must remain false")
    return record


def build_ticker_scoped_source_freeze(
    record: object,
    *,
    source_id: object,
    failure_class: object,
) -> dict:
    """Create a manual-review freeze for precisely one identity after a source failure.

    This records only the safe bypass policy.  It neither retries a provider nor infers that a
    source outage proves any corporate-action semantics or global-run failure.
    """
    record = validate_security_identity(record)
    source_id = _require_source_id(source_id)
    if failure_class not in _SOURCE_FAILURE_CLASSES:
        raise SecurityIdentityError("failure_class is not an allowed source-failure disposition")
    return {
        "schema_name": "us_short_ticker_scoped_source_freeze",
        "schema_version": "1.0.0",
        "frozen_security_id": record["security_id"],
        "frozen_tickers": [record["current_ticker"]],
        "source_id": source_id,
        "failure_class": failure_class,
        "manual_review_required": True,
        "global_run_blocked": False,
        "boundary": {
            "provider_retry_performed": False,
            "unrelated_symbols_frozen": False,
            "selection_or_ranking_changed": False,
            "account_state_read": False,
            "broker_or_order_automation_allowed": False,
        },
    }
