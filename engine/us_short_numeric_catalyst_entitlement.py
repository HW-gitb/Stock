from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from engine.us_short_catalyst_source import CatalystSourceError, resolve_catalyst_signals
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_seam_catalyst import project_catalyst_block


ENDPOINT_EARNINGS_SURPRISES = "earnings_surprises"
ENDPOINT_ANALYST_ESTIMATE_REVISIONS = "analyst_estimate_revisions"
SUPPORTED_ENDPOINTS = (ENDPOINT_EARNINGS_SURPRISES, ENDPOINT_ANALYST_ESTIMATE_REVISIONS)
NOT_ENTITLED_HTTP_STATUSES = frozenset({400, 402, 403, 404})
EMPTY_SOURCE_RESULT = {"signals": {}, "provenance": {}, "excluded": {}}


class NumericCatalystEntitlementError(ValueError):
    """Malformed entitlement probe packet before provider/network execution is allowed."""


def _valid_yyyymmdd(value: Any) -> bool:
    if not (type(value) is str and len(value) == 8 and value.isascii() and value.isdigit()):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _valid_observed_at(value: Any) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _require_exact_dict(value: Any, *, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise NumericCatalystEntitlementError(f"{field} must be an exact dict")
    if not all(type(key) is str for key in value):
        raise NumericCatalystEntitlementError(f"{field} keys must be exact strings")
    return value


def _require_packet(packet: Any, *, endpoint: str) -> dict[str, Any]:
    packet = _require_exact_dict(packet, field=f"endpoint_packets[{endpoint}]")
    expected = {"http_status", "source_as_of", "rows"}
    if set(packet) != expected:
        raise NumericCatalystEntitlementError(f"endpoint_packets[{endpoint}] keys must be {sorted(expected)}")
    if type(packet["http_status"]) is not int:
        raise NumericCatalystEntitlementError(f"endpoint_packets[{endpoint}].http_status must be an exact int")
    if not _valid_yyyymmdd(packet["source_as_of"]):
        raise NumericCatalystEntitlementError(f"endpoint_packets[{endpoint}].source_as_of must be real YYYYMMDD")
    return packet


def _canonical_ticker(raw: Any, *, field: str) -> str:
    if type(raw) is not str:
        raise ValueError(f"{field} must be exact str")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        raise ValueError(f"{field} must be a canonicalizable US ticker")
    return ticker


def _record_id(raw: Any, *, field: str) -> str:
    if type(raw) is not str or not raw or not raw.isascii():
        raise ValueError(f"{field} must be a non-empty ASCII str")
    if any(ch.isspace() for ch in raw) or ":" in raw or "#" in raw:
        raise ValueError(f"{field} must be lineage-safe")
    return raw


def _finite_number(raw: Any, *, field: str) -> float:
    if not (isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw)):
        raise ValueError(f"{field} must be a finite number")
    return float(raw)


def _strict_int(raw: Any, *, field: str) -> int:
    if type(raw) is not int:
        raise ValueError(f"{field} must be an exact int")
    return raw


def _provenance(
    *,
    endpoint: str,
    source_as_of: str,
    observed_at: str,
    record_id: str,
) -> dict[str, str]:
    return {
        "provider_id": "fmp",
        "endpoint_or_filing_type": endpoint,
        "source_as_of": source_as_of,
        "observed_at": observed_at,
        "coverage_status": "full",
        "parser_status": "ok",
        "lineage_ref": f"fmp:{endpoint}:{source_as_of}#{record_id}",
    }


def _parse_rows(
    *,
    endpoint: str,
    rows: Any,
    source_as_of: str,
    observed_at: str,
) -> dict[str, dict[str, Any]]:
    if type(rows) is not list:
        raise ValueError("rows must be an exact list")
    out: dict[str, dict[str, Any]] = {}
    if endpoint == ENDPOINT_EARNINGS_SURPRISES:
        expected = {"ticker", "earnings_surprise_pct", "earnings_report_date", "record_id"}
        value_key = "earnings_surprise_pct"
        date_key = "earnings_report_date"
    elif endpoint == ENDPOINT_ANALYST_ESTIMATE_REVISIONS:
        expected = {"ticker", "analyst_revision_net", "analyst_revision_date", "record_id"}
        value_key = "analyst_revision_net"
        date_key = "analyst_revision_date"
    else:
        raise ValueError("unsupported endpoint")
    for idx, row in enumerate(rows):
        if type(row) is not dict or not all(type(key) is str for key in row):
            raise ValueError("row must be an exact dict with exact string keys")
        if set(row) != expected:
            raise ValueError("row keys drifted from normalized endpoint contract")
        ticker = _canonical_ticker(row["ticker"], field=f"rows[{idx}].ticker")
        if ticker in out:
            raise ValueError("duplicate normalized ticker")
        event_date = row[date_key]
        if not _valid_yyyymmdd(event_date):
            raise ValueError(f"rows[{idx}].{date_key} must be real YYYYMMDD")
        record_id = _record_id(row["record_id"], field=f"rows[{idx}].record_id")
        if endpoint == ENDPOINT_EARNINGS_SURPRISES:
            value = _finite_number(row[value_key], field=f"rows[{idx}].{value_key}")
        else:
            value = _strict_int(row[value_key], field=f"rows[{idx}].{value_key}")
        out[ticker] = {
            value_key: value,
            date_key: event_date,
            "provenance": _provenance(
                endpoint=endpoint,
                source_as_of=source_as_of,
                observed_at=observed_at,
                record_id=record_id,
            ),
        }
    return out


def _neutral_projection(*, governance: dict[str, Any], as_of: str, target_tickers: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return project_catalyst_block(
        catalyst_source_result=dict(EMPTY_SOURCE_RESULT),
        governance=governance,
        as_of=as_of,
        target_tickers=target_tickers,
    )


def resolve_numeric_catalyst_with_entitlement(
    *,
    as_of: str,
    observed_at: str,
    endpoint_packets: Any,
    target_tickers: list[str] | tuple[str, ...],
    governance: dict[str, Any],
) -> dict[str, Any]:
    if not _valid_yyyymmdd(as_of):
        raise NumericCatalystEntitlementError("as_of must be real YYYYMMDD")
    if not _valid_observed_at(observed_at):
        raise NumericCatalystEntitlementError("observed_at must be timezone-aware RFC3339")
    packets = _require_exact_dict(endpoint_packets, field="endpoint_packets")
    if set(packets) - set(SUPPORTED_ENDPOINTS):
        raise NumericCatalystEntitlementError("endpoint_packets contains unsupported endpoint")

    entitlement: dict[str, dict[str, Any]] = {}
    earnings: dict[str, dict[str, Any]] = {}
    analyst: dict[str, dict[str, Any]] = {}
    for endpoint in SUPPORTED_ENDPOINTS:
        packet = _require_packet(packets.get(endpoint, {
            "http_status": 404,
            "source_as_of": as_of,
            "rows": [],
        }), endpoint=endpoint)
        status_code = packet["http_status"]
        parsed_rows: dict[str, dict[str, Any]] = {}
        row_count = 0
        if status_code in NOT_ENTITLED_HTTP_STATUSES:
            status = "not_entitled"
            per_symbol_allowed = False
        elif status_code != 200:
            status = "failed_status_neutral_fallback"
            per_symbol_allowed = False
        else:
            try:
                parsed_rows = _parse_rows(
                    endpoint=endpoint,
                    rows=packet["rows"],
                    source_as_of=packet["source_as_of"],
                    observed_at=observed_at,
                )
            except ValueError:
                status = "malformed_200_neutral_fallback"
                per_symbol_allowed = False
            else:
                status = "entitled"
                per_symbol_allowed = True
                row_count = len(parsed_rows)
        entitlement[endpoint] = {
            "http_status": status_code,
            "status": status,
            "per_symbol_fetch_allowed": per_symbol_allowed,
            "skipped_per_symbol_fetch": not per_symbol_allowed,
            "normalized_row_count": row_count,
        }
        if status == "entitled":
            if endpoint == ENDPOINT_EARNINGS_SURPRISES:
                earnings = parsed_rows
            else:
                analyst = parsed_rows

    try:
        source_result = resolve_catalyst_signals(as_of=as_of, earnings=earnings, analyst=analyst)
    except CatalystSourceError:
        source_result = dict(EMPTY_SOURCE_RESULT)
        for endpoint, row in entitlement.items():
            if row["status"] == "entitled":
                row["status"] = "resolver_rejected_neutral_fallback"
                row["per_symbol_fetch_allowed"] = False
                row["skipped_per_symbol_fetch"] = True
                row["normalized_row_count"] = 0

    projection = project_catalyst_block(
        catalyst_source_result=source_result,
        governance=governance,
        as_of=as_of,
        target_tickers=target_tickers,
    )
    return {
        "entitlement": entitlement,
        "source_result": source_result,
        "projection": projection,
        "network_access_performed": False,
        "provider_calls_performed": False,
        "live_fetch_authorized": False,
    }
