"""Default-offline yfinance alarm and SEC corporate-event interface skeletons.

These are intentionally not provider adapters.  The yfinance path does not import the package;
the SEC gateway rejects every fetch.  The parser entry returns only a no-raw-payload contract
marker.  A future call or raw parse requires its own source-bound authorization and scope review.
"""
from __future__ import annotations

import hashlib
import json

from engine.us_short_security_identity import SecurityIdentityError, validate_security_identity


class OfflineProviderBoundaryError(ValueError):
    """A caller tried to cross a default-offline provider boundary."""


def _identity_ref_sha256(record: object) -> str:
    try:
        record = validate_security_identity(record)
    except SecurityIdentityError as exc:
        raise OfflineProviderBoundaryError("security identity is invalid before provider handling") from exc
    canonical = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _security_binding(record: object) -> dict:
    identity_ref_sha256 = _identity_ref_sha256(record)
    return {
        "security_id": record["security_id"],
        "current_ticker": record["current_ticker"],
        "identity_ref_sha256": identity_ref_sha256,
    }


def build_offline_provider_boundary(record: object) -> dict:
    """Return the closed, no-network provider-boundary contract for one valid security."""
    return {
        "schema_name": "us_short_offline_provider_boundary",
        "schema_version": "1.0.0",
        "security_binding": _security_binding(record),
        "yfinance_smoke_alarm": {
            "status": "not_executed_offline",
            "package_import_attempted": False,
            "network_access_performed": False,
            "failure_disposition": "ticker_scoped_freeze",
            "selection_use_allowed": False,
        },
        "sec_corporate_event_interface": {
            "fetch_mode": "offline_default",
            "fetch_invoked": False,
            "raw_payload_read": False,
            "parser_entry_status": "awaits_separately_authorized_source_bound_payload",
            "corporate_event_semantics_confirmed": False,
        },
        "failure_isolation": {
            "global_run_blocked": False,
            "unrelated_symbols_frozen": False,
            "manual_review_required": True,
        },
        "boundary": {
            "provider_selected": False,
            "provider_call_performed": False,
            "account_state_read": False,
            "broker_order_placed": False,
            "return_calculation_performed": False,
            "selection_or_ranking_changed": False,
            "ship_gate_evidence_claimed": False,
        },
    }


def build_sec_corporate_event_fetch_request(record: object) -> dict:
    """Describe the identity-bound SEC request shape without forming a network request."""
    return {"fetch_mode": "offline_default", "security_binding": _security_binding(record)}


class OfflineSecCorporateEventGateway:
    """A hard no-network gate; this class intentionally has no HTTP client dependency."""

    def fetch(self, request: object) -> None:
        if not isinstance(request, dict) or request.get("fetch_mode") != "offline_default":
            raise OfflineProviderBoundaryError("SEC request must be an offline-default request")
        raise OfflineProviderBoundaryError(
            "SEC fetch is disabled by default; separately authorize a source-bound provider execution"
        )


def parse_sec_corporate_event_payload(record: object) -> dict:
    """Expose a no-raw parser entry marker, not a parser or a corporate-action interpretation."""
    return {
        "security_binding": _security_binding(record),
        "parser_entry_status": "awaits_separately_authorized_source_bound_payload",
        "raw_payload_read": False,
        "network_access_performed": False,
        "corporate_event_semantics_confirmed": False,
        "selection_use_allowed": False,
    }
