# -*- coding: utf-8 -*-
"""Pure fail-closed zero-event evidence for the US-short A1 forward comparison.

This module never calls a provider.  It derives an exact common-pool H20 window from a validated
private source capture plus the current maturity OHLCV packet, validates a private market-wide
split/dividend coverage packet, and emits the existing adjustment-evidence shape.  Only complete,
exhausted, zero-event coverage can be evaluable; eventful or incomplete coverage remains no-count.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

from engine.us_short_forward_policy_source_capture import (
    ForwardPolicySourceCaptureError,
    validate_forward_policy_source_capture,
)
from engine.us_short_paper_eval_gate import (
    PaperEvalGateError,
    paper_performance_evaluability_from_offline_evidence,
)


ROOT = Path(__file__).resolve().parent.parent
_COVERAGE_SCHEMA = ROOT / "schemas" / "us_short_forward_policy_corporate_action_coverage.schema.json"
_OHLCV_SCHEMA = ROOT / "schemas" / "us_short_batch5_full_universe_ohlcv_series_packet.schema.json"
FIRST_ELIGIBLE_DECISION_DATE = "20260720"
_PAPER_MODE_BY_OHLCV_MODE = {
    "split_adjusted": "split_adjusted_price_return",
    "split_dividend_adjusted": "split_dividend_adjusted",
}
MATURITY_SOURCE_REF = {
    "id": "maturity_ohlcv_packet",
    "path": "state/us_short/shadow_compare_private/forward_policy_maturity_source.json",
}


class ForwardPolicyCorporateActionEvidenceError(ValueError):
    """The zero-event certificate inputs are incomplete, drifted, or unsafe."""


def canonical_sha256(value: object) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ForwardPolicyCorporateActionEvidenceError("value is not finite canonical JSON") from exc
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyCorporateActionEvidenceError("required schema cannot be loaded") from exc
    if not isinstance(value, dict):
        raise ForwardPolicyCorporateActionEvidenceError("required schema root must be an object")
    return value


def _validate_schema(value: object, path: Path, label: str) -> None:
    try:
        jsonschema.validate(value, _load_schema(path))
    except jsonschema.ValidationError as exc:
        raise ForwardPolicyCorporateActionEvidenceError(f"{label} schema rejected: {exc.message}") from exc


def _strict_date(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 8 or not value.isascii() or not value.isdigit():
        return False
    try:
        datetime.datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _strict_iso_date(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def derive_mature_h20_window(
    *, source_capture: object, maturity_ohlcv_packet: object, maturity_ohlcv_sha256: str, maturity_as_of: str,
) -> dict[str, Any] | None:
    """Return the exact common H20 window, or ``None`` when fewer than 20 sessions exist."""
    if not (_strict_date(maturity_as_of) and _sha(maturity_ohlcv_sha256)):
        raise ForwardPolicyCorporateActionEvidenceError("maturity clock and source digest must be exact")
    try:
        frozen = validate_forward_policy_source_capture(source_capture)
    except ForwardPolicySourceCaptureError as exc:
        raise ForwardPolicyCorporateActionEvidenceError("source capture is invalid") from exc
    capture = frozen["capture"]
    decision_date = capture["decision_date"]
    if decision_date < FIRST_ELIGIBLE_DECISION_DATE or decision_date >= maturity_as_of:
        return None
    _validate_schema(maturity_ohlcv_packet, _OHLCV_SCHEMA, "maturity OHLCV packet")
    if not isinstance(maturity_ohlcv_packet, dict) \
            or maturity_ohlcv_packet["decision_clock"].get("expected_decision_date") != maturity_as_of:
        raise ForwardPolicyCorporateActionEvidenceError("maturity OHLCV packet clock drifted")
    ohlcv_mode = maturity_ohlcv_packet["series_contract"].get("adjustment_mode")
    if ohlcv_mode not in _PAPER_MODE_BY_OHLCV_MODE:
        raise ForwardPolicyCorporateActionEvidenceError("maturity OHLCV adjustment mode is not confirmed")
    entry_iso = f"{decision_date[:4]}-{decision_date[4:6]}-{decision_date[6:]}"
    maturity_iso = f"{maturity_as_of[:4]}-{maturity_as_of[4:6]}-{maturity_as_of[6:]}"
    series_by_ticker = maturity_ohlcv_packet["series_by_ticker"]
    reference_dates: list[str] | None = None
    for ticker in capture["common_selection_pool"]:
        series = series_by_ticker.get(ticker)
        if not isinstance(series, dict) or series.get("adjustment_mode") != ohlcv_mode:
            raise ForwardPolicyCorporateActionEvidenceError("common-pool ticker lacks confirmed maturity OHLCV")
        points = series.get("points")
        if not isinstance(points, list):
            raise ForwardPolicyCorporateActionEvidenceError("common-pool maturity OHLCV points are missing")
        dates: list[str] = []
        prior = None
        for point in points:
            point_date = point.get("date") if isinstance(point, dict) else None
            if not _strict_iso_date(point_date) or (prior is not None and point_date <= prior):
                raise ForwardPolicyCorporateActionEvidenceError("maturity OHLCV dates are malformed or unordered")
            prior = point_date
            if entry_iso <= point_date <= maturity_iso and len(dates) < 20:
                dates.append(point_date)
        if len(dates) < 20:
            return None
        if reference_dates is None:
            reference_dates = dates
        elif dates != reference_dates:
            raise ForwardPolicyCorporateActionEvidenceError("common-pool H20 session dates do not match")
    if not reference_dates:
        raise ForwardPolicyCorporateActionEvidenceError("common-pool H20 window is empty")
    return {
        "decision_date": decision_date,
        "common_selection_pool": list(capture["common_selection_pool"]),
        "common_selection_pool_sha256": capture["common_selection_pool_sha256"],
        "window_start": reference_dates[0],
        "h20_session_date": reference_dates[-1],
        "maturity_as_of": maturity_as_of,
        "maturity_ohlcv_sha256": maturity_ohlcv_sha256,
        "paper_adjustment_mode": _PAPER_MODE_BY_OHLCV_MODE[ohlcv_mode],
    }


def validate_coverage_packet(packet: object) -> dict[str, Any]:
    _validate_schema(packet, _COVERAGE_SCHEMA, "corporate-action coverage packet")
    if not isinstance(packet, dict):
        raise ForwardPolicyCorporateActionEvidenceError("coverage packet must be an object")
    window = packet["query_window"]
    if not (_strict_iso_date(window["from"]) and _strict_iso_date(window["to"]) and window["from"] <= window["to"]):
        raise ForwardPolicyCorporateActionEvidenceError("coverage query window is invalid")
    decisions: set[str] = set()
    for binding in packet["capture_bindings"]:
        if binding["decision_date"] in decisions or not (
            window["from"] <= binding["window_start"] <= binding["h20_session_date"] <= window["to"]
        ):
            raise ForwardPolicyCorporateActionEvidenceError("coverage capture binding is duplicated or out of range")
        decisions.add(binding["decision_date"])
    all_ids: set[str] = set()
    for family in packet["families"].values():
        if family["result_count"] != len(family["events"]) \
                or family["result_sha256"] != canonical_sha256(family["events"]) \
                or len(family["raw_page_sha256"]) != family["pages_fetched"]:
            raise ForwardPolicyCorporateActionEvidenceError("coverage family count/digest/page binding drifted")
        if family["status"] == "complete" and (
            family["pagination_exhausted"] is not True or family["failure_reason"] is not None
        ):
            raise ForwardPolicyCorporateActionEvidenceError("complete coverage must be exhausted and failure-free")
        for event in family["events"]:
            if event["event_id"] in all_ids or not window["from"] <= event["event_date"] <= window["to"]:
                raise ForwardPolicyCorporateActionEvidenceError("coverage event is duplicated or outside query bounds")
            all_ids.add(event["event_id"])
    return packet


def build_adjustment_evidence(
    *, window: dict[str, Any], coverage_packet: object, coverage_packet_sha256: str,
) -> dict[str, Any]:
    """Emit the existing adjustment-evidence shape for one exact H20 capture."""
    if not _sha(coverage_packet_sha256):
        raise ForwardPolicyCorporateActionEvidenceError("coverage packet digest must be lowercase SHA256")
    coverage = validate_coverage_packet(coverage_packet)
    if coverage_packet_sha256 != canonical_sha256(coverage):
        raise ForwardPolicyCorporateActionEvidenceError("coverage packet digest does not match its canonical content")
    if coverage["maturity_as_of"] != window.get("maturity_as_of") \
            or coverage["maturity_ohlcv_sha256"] != window.get("maturity_ohlcv_sha256"):
        raise ForwardPolicyCorporateActionEvidenceError("coverage maturity source binding drifted")
    binding = next((item for item in coverage["capture_bindings"] if item["decision_date"] == window.get("decision_date")), None)
    expected_binding = {
        "decision_date": window.get("decision_date"),
        "common_selection_pool_sha256": window.get("common_selection_pool_sha256"),
        "window_start": window.get("window_start"),
        "h20_session_date": window.get("h20_session_date"),
    }
    if binding != expected_binding:
        raise ForwardPolicyCorporateActionEvidenceError("coverage common-pool/H20 binding drifted")
    pool = set(window.get("common_selection_pool", []))
    if not pool:
        raise ForwardPolicyCorporateActionEvidenceError("certificate common pool is empty")
    paper_adjustment_mode = window.get("paper_adjustment_mode")
    if paper_adjustment_mode not in _PAPER_MODE_BY_OHLCV_MODE.values():
        raise ForwardPolicyCorporateActionEvidenceError("certificate adjustment mode is not source-derived")
    refs = [
        {**MATURITY_SOURCE_REF, "sha256": window["maturity_ohlcv_sha256"]},
        {
            "id": "corporate_action_coverage_packet",
            "path": f"state/us_short/shadow_compare_private/forward_policy_corporate_action_coverage_{coverage['maturity_as_of']}.json",
            "sha256": coverage_packet_sha256,
        },
    ]
    ref_ids = [item["id"] for item in refs]
    events_by_family: dict[str, list[dict[str, Any]]] = {}
    for family_name, family in coverage["families"].items():
        events_by_family[family_name] = [event for event in family["events"] if (
            event["ticker"] in pool and window["window_start"] <= event["event_date"] <= window["h20_session_date"]
        )]
    complete = all(
        family["status"] == "complete" and family["pagination_exhausted"] is True
        for family in coverage["families"].values()
    )
    eventful = any(events_by_family.values())
    if complete and not eventful:
        adjustment = {"status": "confirmed", "mode": paper_adjustment_mode, "source_ref_ids": ref_ids}
        split = {"status": "no_events", "source_ref_ids": ref_ids, "event_refs": []}
        dividend = {"status": "no_events", "source_ref_ids": ref_ids, "event_refs": []}
        ex_date = {"status": "not_applicable_no_events", "source_ref_ids": ref_ids, "checked_event_ids": []}
    else:
        adjustment = {"status": "ambiguous", "mode": "unknown", "source_ref_ids": ref_ids}
        sections: dict[str, dict[str, Any]] = {}
        for family_name in ("splits", "dividends"):
            event_refs = [{
                "event_id": event["event_id"], "ticker": event["ticker"], "ex_date": event["event_date"],
                "source_ref_ids": ref_ids,
            } for event in events_by_family[family_name]]
            sections[family_name] = {
                "status": "ambiguous" if event_refs else "missing",
                "source_ref_ids": ref_ids,
                "event_refs": event_refs,
            }
        split, dividend = sections["splits"], sections["dividends"]
        ex_date = {"status": "ambiguous" if eventful else "missing", "source_ref_ids": ref_ids, "checked_event_ids": []}
    evidence = {
        "schema_name": "us_short_paper_eval_adjustment_evidence",
        "schema_version": "1.0.0",
        "decision_date": window["decision_date"],
        "source_refs": refs,
        "adjustment_mode": adjustment,
        "split_handling": split,
        "dividend_handling": dividend,
        "ex_date_price_consistency": ex_date,
        "scope": {
            "offline_detection_only": True,
            "provider_call_performed": False,
            "corporate_action_reconciliation_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
    }
    try:
        paper_performance_evaluability_from_offline_evidence(evidence)
    except PaperEvalGateError as exc:
        raise ForwardPolicyCorporateActionEvidenceError("emitted adjustment evidence is invalid") from exc
    return evidence
