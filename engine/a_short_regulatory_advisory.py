"""Pure contracts for A-short official-regulatory advisory confirmation.

Official CNINFO rows are candidates for a human judgement, not an automatic
Rule6 or EGS decision.  A local confirmation document is bound to one EGS
candidate pool and exact event fingerprints before it can affect the
non-production M6.7 advisory layer.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


SCHEMA_NAME = "a_short_regulatory_advisory_confirmation"
SCHEMA_VERSION = "1.0.0"
HOLDING_SCHEMA_NAME = "a_short_regulatory_holding_confirmation"
HOLDING_SCHEMA_VERSION = "1.0.0"
DECISIONS = frozenset({"confirmed_material", "confirmed_not_material", "needs_more_information"})
EVENT_KEYS = ("source", "title", "category", "disclosure_date", "url_or_pdf", "risk_type", "severity")


class RegulatoryAdvisoryContractError(ValueError):
    """The manual confirmation input is stale, malformed, or mismatched."""


def event_fingerprint(ts_code: str, event: dict[str, Any]) -> str:
    """Hash the exact official event identity without retaining a raw response."""
    if not isinstance(event, dict):
        raise RegulatoryAdvisoryContractError("official event must be an object")
    missing = [key for key in EVENT_KEYS if key not in event]
    if missing:
        raise RegulatoryAdvisoryContractError(f"official event missing fields: {','.join(missing)}")
    identity = {"ts_code": str(ts_code), **{key: event[key] for key in EVENT_KEYS}}
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validated_confirmation_records(payload: dict[str, Any]) -> dict[tuple[str, str], dict[str, str]]:
    mapped: dict[tuple[str, str], dict[str, str]] = {}
    for index, item in enumerate(payload.get("confirmations") or []):
        if not isinstance(item, dict):
            raise RegulatoryAdvisoryContractError(f"confirmations[{index}] must be an object")
        code = str(item.get("ts_code") or "")
        fingerprint = str(item.get("event_fingerprint") or "")
        decision = str(item.get("decision") or "")
        reviewed_at = str(item.get("reviewed_at") or "")
        note = str(item.get("note") or "").strip()
        if decision not in DECISIONS:
            raise RegulatoryAdvisoryContractError(f"confirmations[{index}] has unsupported decision")
        try:
            reviewed_at_value = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RegulatoryAdvisoryContractError(f"confirmations[{index}] reviewed_at is not ISO-8601") from exc
        if "T" not in reviewed_at or reviewed_at_value.tzinfo is None:
            raise RegulatoryAdvisoryContractError(
                f"confirmations[{index}] reviewed_at must be a timezone-aware timestamp"
            )
        if not code or len(fingerprint) != 64 or any(ch not in "0123456789abcdef" for ch in fingerprint):
            raise RegulatoryAdvisoryContractError(f"confirmations[{index}] has invalid event identity")
        if not note:
            raise RegulatoryAdvisoryContractError(f"confirmations[{index}] note must be non-empty")
        key = (code, fingerprint)
        if key in mapped:
            raise RegulatoryAdvisoryContractError("duplicate confirmation for one official event")
        mapped[key] = {"decision": decision, "reviewed_at": reviewed_at, "note": note}
    return mapped


def validate_confirmation_document(payload: Any, as_of: str, candidate_digest: str) -> dict[tuple[str, str], dict[str, str]]:
    """Validate a candidate-pool confirmation document after JSON-Schema validation."""
    if not isinstance(payload, dict):
        raise RegulatoryAdvisoryContractError("confirmation document must be an object")
    if payload.get("schema_name") != SCHEMA_NAME or payload.get("schema_version") != SCHEMA_VERSION:
        raise RegulatoryAdvisoryContractError("unsupported confirmation schema identity")
    if str(payload.get("as_of")) != str(as_of):
        raise RegulatoryAdvisoryContractError("confirmation as_of does not match weekly as_of")
    if str(payload.get("candidate_digest")) != str(candidate_digest):
        raise RegulatoryAdvisoryContractError("confirmation candidate_digest does not match analysis_input")
    return _validated_confirmation_records(payload)


def holding_universe_digest(positions: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str:
    """Fingerprint the exact sorted account-position universe without copying account facts."""
    codes = [str(position.get("ts_code") or "") for position in positions if isinstance(position, dict)]
    if len(codes) != len(positions) or not all(codes) or len(set(codes)) != len(codes):
        raise RegulatoryAdvisoryContractError("holding universe must contain one non-empty ts_code per position")
    return hashlib.sha256(
        json.dumps(sorted(codes), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_holding_confirmation_document(
    payload: Any,
    as_of: str,
    account_snapshot_digest: str,
    expected_holding_universe_digest: str,
    holding_codes: set[str],
) -> dict[tuple[str, str], dict[str, str]]:
    """Validate a private holding confirmation bound to one account bundle and holding universe."""
    if not isinstance(payload, dict):
        raise RegulatoryAdvisoryContractError("holding confirmation document must be an object")
    if payload.get("schema_name") != HOLDING_SCHEMA_NAME or payload.get("schema_version") != HOLDING_SCHEMA_VERSION:
        raise RegulatoryAdvisoryContractError("unsupported holding confirmation schema identity")
    if str(payload.get("as_of")) != str(as_of):
        raise RegulatoryAdvisoryContractError("holding confirmation as_of does not match weekly as_of")
    if str(payload.get("account_snapshot_digest")) != str(account_snapshot_digest):
        raise RegulatoryAdvisoryContractError("holding confirmation account snapshot does not match --account")
    if str(payload.get("holding_universe_digest")) != str(expected_holding_universe_digest):
        raise RegulatoryAdvisoryContractError("holding confirmation universe does not match --account positions")
    mapped = _validated_confirmation_records(payload)
    outside = sorted({code for code, _ in mapped if code not in holding_codes})
    if outside:
        raise RegulatoryAdvisoryContractError("holding confirmation contains ts_code outside the bound holding universe")
    return mapped


def attach_confirmations(
    semantic: dict[str, Any] | None,
    ts_code: str,
    confirmations: dict[tuple[str, str], dict[str, str]],
) -> tuple[dict[str, Any] | None, set[tuple[str, str]]]:
    """Attach only exact current-event confirmations to one official semantic result."""
    if semantic is None:
        return None, set()
    if not isinstance(semantic, dict):
        raise RegulatoryAdvisoryContractError("official semantic result must be an object")
    out = dict(semantic)
    # This field is derived only from the validated confirmation document for
    # the current run.  Do not carry a provider-supplied decision across that
    # binding boundary.
    out.pop("regulatory_advisory", None)
    matched: set[tuple[str, str]] = set()
    decisions = []
    for event in out.get("events") or []:
        fingerprint = event_fingerprint(ts_code, event)
        key = (str(ts_code), fingerprint)
        record = confirmations.get(key)
        if record is None:
            continue
        matched.add(key)
        decisions.append({"event_fingerprint": fingerprint, "decision": record["decision"]})
    if decisions:
        out["regulatory_advisory"] = {"event_decisions": decisions}
    return out, matched


def resolve_regulatory_advisory(semantic: dict[str, Any] | None, ts_code: str) -> dict[str, Any]:
    """Derive advisory-only confirmation state from validated official semantic evidence."""
    events = list((semantic or {}).get("events") or [])
    raw = (semantic or {}).get("regulatory_advisory")
    if raw is None:
        decisions: dict[str, str] = {}
    else:
        if not isinstance(raw, dict) or set(raw) != {"event_decisions"}:
            raise RegulatoryAdvisoryContractError("regulatory_advisory must contain only event_decisions")
        rows = raw.get("event_decisions")
        if not isinstance(rows, list):
            raise RegulatoryAdvisoryContractError("regulatory_advisory.event_decisions must be a list")
        expected = {event_fingerprint(ts_code, event) for event in events}
        decisions = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or set(row) != {"event_fingerprint", "decision"}:
                raise RegulatoryAdvisoryContractError(f"event_decisions[{index}] has an invalid shape")
            fingerprint = str(row.get("event_fingerprint") or "")
            decision = str(row.get("decision") or "")
            if fingerprint not in expected or decision not in DECISIONS or fingerprint in decisions:
                raise RegulatoryAdvisoryContractError(f"event_decisions[{index}] is stale, duplicate, or invalid")
            decisions[fingerprint] = decision

    high_events = [event for event in events if event.get("severity") == "high"]
    high_full = [event for event in high_events if str(event.get("url_or_pdf") or "").strip()]
    high_material = []
    pending_high = []
    confirmed_not_material = 0
    needs_more_information = 0
    for event in high_events:
        fingerprint = event_fingerprint(ts_code, event)
        decision = decisions.get(fingerprint)
        if decision == "confirmed_not_material":
            confirmed_not_material += 1
        elif decision == "needs_more_information":
            needs_more_information += 1
            pending_high.append(event)
        elif decision == "confirmed_material" and event in high_full:
            high_material.append(event)
        else:
            pending_high.append(event)

    if high_material:
        status = "confirmed_material"
    elif pending_high:
        status = "pending_confirmation"
    elif high_events:
        status = "confirmed_not_material"
    else:
        status = "not_required"
    return {
        "status": status,
        "high_material": high_material,
        "pending_high": pending_high,
        "confirmed_not_material_count": confirmed_not_material,
        "needs_more_information_count": needs_more_information,
        "event_decision_count": len(decisions),
    }
