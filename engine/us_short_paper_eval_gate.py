# -*- coding: utf-8 -*-
"""US-short §12.1 复权/公司行动门 — batch-3 (#29): paper_performance evaluability fail-closed gate.

Design authority: docs/us_short_system_design.md §12.1 (复权/公司行动硬门: 未确认 adjustment_mode + split/dividend
处理 + 除权日价位一致 → paper_performance 一律 not_evaluable/data_degraded, 不进 ship-gate/alpha) / §18.0 P0
(复权/公司行动门, SR-PROVIDER-001) / §18.1 #29 / §12 (paper 仅设计迭代、绝不判满仓 ship-gate).

paper_performance is adjustment-evaluable for paper / reporting / shadow (design-iteration) use ONLY when all
three corporate-action confirmations are explicitly true: the price adjustment mode is confirmed, splits/dividends
are handled, and the ex-date price levels are consistent. CRUCIALLY this is a PAPER gate — even when fully
adjustment-confirmed, paper_performance is NEVER full-size ship-gate eligible (§12 / §27: model_paper_track is
design-iteration evidence; only ``live_normalized`` = manual_actual + reconciliation graduates). So the output
carries an explicit, always-False ship-gate invariant so corporate-action evaluability can never be read as a
ship-gate permission. The gate is FAIL-CLOSED: a confirmation that is not literally ``True`` (missing, False,
None, or a truthy non-bool like ``1`` / ``"yes"``) does NOT count as confirmed, so the default is
``not_evaluable`` — paper performance never silently becomes usable on an unverified / sloppily-truthy
corporate-action state (SR-PROVIDER-001: active price adjustment / corporate-action reconciliation is unproven,
current call count 0). Pure / offline: reads bool confirmations from a dict; no provider / live / DataHub /
network; no A-share crossing.
"""
from __future__ import annotations

import json
from pathlib import Path

# the three §12.1 corporate-action confirmations that gate paper_performance evaluability (design prose source)
_CONFIRMATIONS = ("adjustment_mode_confirmed", "split_dividend_handled", "ex_date_price_consistent")
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "us_short_paper_eval_adjustment_evidence.schema.json"
)
_OFFLINE_EVIDENCE_VALIDATOR = None

_OFFLINE_EVIDENCE_KEYS = frozenset(
    {
        "schema_name",
        "schema_version",
        "decision_date",
        "source_refs",
        "adjustment_mode",
        "split_handling",
        "dividend_handling",
        "ex_date_price_consistency",
        "scope",
    }
)
_SOURCE_REF_KEYS = frozenset({"id", "path", "sha256"})
_ADJUSTMENT_MODE_KEYS = frozenset({"status", "mode", "source_ref_ids"})
_HANDLING_KEYS = frozenset({"status", "source_ref_ids", "event_refs"})
_EVENT_REF_KEYS = frozenset({"event_id", "ticker", "ex_date", "source_ref_ids"})
_EX_DATE_KEYS = frozenset({"status", "source_ref_ids", "checked_event_ids"})
_SCOPE_KEYS = frozenset(
    {
        "offline_detection_only",
        "provider_call_performed",
        "corporate_action_reconciliation_claimed",
        "ship_gate_or_production_authorized",
    }
)
_ADJUSTMENT_STATUSES = frozenset({"confirmed", "missing", "ambiguous", "conflict"})
_ADJUSTMENT_MODES = frozenset(
    {
        "split_dividend_adjusted",
        "split_adjusted_price_return",
        "total_return_adjusted",
        "unadjusted_with_events_reconciled",
    }
)
_HANDLING_STATUSES = frozenset({"no_events", "events_reconciled", "missing", "ambiguous", "conflict"})
_EX_DATE_STATUSES = frozenset({"consistent", "not_applicable_no_events", "missing", "ambiguous", "conflict"})
_HEX = frozenset("0123456789abcdef")


class PaperEvalGateError(ValueError):
    """Raised when the corporate-action context is malformed (non-dict, or an unknown confirmation key)."""


def _offline_evidence_validator():
    global _OFFLINE_EVIDENCE_VALIDATOR
    if _OFFLINE_EVIDENCE_VALIDATOR is not None:
        return _OFFLINE_EVIDENCE_VALIDATOR
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - environment guard
        raise PaperEvalGateError("jsonschema is required for offline adjustment evidence validation") from exc
    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperEvalGateError("offline adjustment evidence schema cannot be loaded") from exc
    Draft7Validator.check_schema(schema)
    _OFFLINE_EVIDENCE_VALIDATOR = Draft7Validator(schema)
    return _OFFLINE_EVIDENCE_VALIDATOR


def _format_schema_error(error) -> str:
    path = ".".join(str(part) for part in error.path) or "<root>"
    return "%s: %s" % (path, error.message)


def _validate_offline_evidence_schema(evidence: dict) -> None:
    validator = _offline_evidence_validator()
    errors = sorted(validator.iter_errors(evidence), key=lambda err: list(err.path))
    if errors:
        joined = "; ".join(_format_schema_error(error) for error in errors[:3])
        if len(errors) > 3:
            joined += "; ... (%d total errors)" % len(errors)
        raise PaperEvalGateError("offline adjustment evidence schema validation failed: %s" % joined)


def _reject_unknown_keys(obj: dict, allowed: frozenset[str], label: str) -> None:
    unknown = [k for k in obj if k not in allowed]
    if unknown:
        raise PaperEvalGateError(
            "unknown %s key(s) %s - closed-world corporate-action gate input" % (label, sorted(map(str, unknown)))
        )


def _optional_dict(parent: dict, key: str, allowed: frozenset[str]) -> dict:
    value = parent.get(key)
    if value is None:
        return {}
    if type(value) is not dict:
        raise PaperEvalGateError("%s must be a dict when present" % key)
    _reject_unknown_keys(value, allowed, key)
    return value


def _source_ref_ids(evidence: dict) -> set[str]:
    refs = evidence.get("source_refs", [])
    if refs is None:
        refs = []
    if type(refs) is not list:
        raise PaperEvalGateError("source_refs must be a list")
    out: set[str] = set()
    for idx, ref in enumerate(refs):
        if type(ref) is not dict:
            raise PaperEvalGateError("source_refs[%d] must be a dict" % idx)
        _reject_unknown_keys(ref, _SOURCE_REF_KEYS, "source_ref")
        ref_id = ref.get("id")
        if type(ref_id) is not str or not ref_id:
            raise PaperEvalGateError("source_refs[%d].id must be a non-empty string" % idx)
        path = ref.get("path")
        if not _valid_source_path(path):
            raise PaperEvalGateError("source_refs[%d].path must be a safe repo-relative json path" % idx)
        sha256 = ref.get("sha256")
        if type(sha256) is not str or len(sha256) != 64 or any(ch not in _HEX for ch in sha256):
            raise PaperEvalGateError("source_refs[%d].sha256 must be a lowercase 64-character hex digest" % idx)
        if ref_id in out:
            raise PaperEvalGateError("duplicate source_ref id %r" % ref_id)
        out.add(ref_id)
    return out


def _valid_source_path(path) -> bool:
    if type(path) is not str or not path.endswith(".json"):
        return False
    if "://" in path or "\\" in path or path.startswith("/") or path.startswith("."):
        return False
    if len(path) >= 2 and path[1] == ":":
        return False
    parts = path.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _has_valid_source_ref_ids(obj: dict, valid_ids: set[str]) -> bool:
    ids = obj.get("source_ref_ids")
    if type(ids) is not list or not ids:
        return False
    return all(type(ref_id) is str and ref_id in valid_ids for ref_id in ids)


def _event_ids(section: dict, valid_ids: set[str], label: str) -> tuple[bool, set[str]]:
    events = section.get("event_refs", [])
    if events is None:
        events = []
    if type(events) is not list:
        raise PaperEvalGateError("%s.event_refs must be a list" % label)
    out: set[str] = set()
    for idx, event in enumerate(events):
        if type(event) is not dict:
            raise PaperEvalGateError("%s.event_refs[%d] must be a dict" % (label, idx))
        _reject_unknown_keys(event, _EVENT_REF_KEYS, "%s.event_ref" % label)
        event_id = event.get("event_id")
        ticker = event.get("ticker")
        ex_date = event.get("ex_date")
        if type(event_id) is not str or not event_id:
            return False, set()
        if type(ticker) is not str or not ticker:
            return False, set()
        if type(ex_date) is not str or not ex_date:
            return False, set()
        if not _has_valid_source_ref_ids(event, valid_ids):
            return False, set()
        if event_id in out:
            raise PaperEvalGateError("duplicate corporate-action event_id %r" % event_id)
        out.add(event_id)
    return True, out


def _adjustment_mode_confirmed(evidence: dict, valid_ids: set[str]) -> bool:
    section = _optional_dict(evidence, "adjustment_mode", _ADJUSTMENT_MODE_KEYS)
    if not section:
        return False
    status = section.get("status")
    if status not in _ADJUSTMENT_STATUSES:
        raise PaperEvalGateError("adjustment_mode.status is invalid: %r" % (status,))
    return (
        status == "confirmed"
        and section.get("mode") in _ADJUSTMENT_MODES
        and _has_valid_source_ref_ids(section, valid_ids)
    )


def _handling_confirmed(evidence: dict, key: str, valid_ids: set[str]) -> tuple[bool, set[str]]:
    section = _optional_dict(evidence, key, _HANDLING_KEYS)
    if not section:
        return False, set()
    status = section.get("status")
    if status not in _HANDLING_STATUSES:
        raise PaperEvalGateError("%s.status is invalid: %r" % (key, status))
    if not _has_valid_source_ref_ids(section, valid_ids):
        return False, set()
    events_ok, events = _event_ids(section, valid_ids, key)
    if not events_ok:
        return False, set()
    if status == "no_events":
        return not events, set()
    if status == "events_reconciled":
        return bool(events), events
    return False, events


def _ex_date_consistent(evidence: dict, valid_ids: set[str], event_ids: set[str]) -> bool:
    section = _optional_dict(evidence, "ex_date_price_consistency", _EX_DATE_KEYS)
    if not section:
        return False
    status = section.get("status")
    if status not in _EX_DATE_STATUSES:
        raise PaperEvalGateError("ex_date_price_consistency.status is invalid: %r" % (status,))
    if not _has_valid_source_ref_ids(section, valid_ids):
        return False
    checked = section.get("checked_event_ids", [])
    if checked is None:
        checked = []
    if type(checked) is not list or not all(type(event_id) is str and event_id for event_id in checked):
        raise PaperEvalGateError("ex_date_price_consistency.checked_event_ids must be a list of strings")
    checked_ids = set(checked)
    if len(checked_ids) != len(checked):
        raise PaperEvalGateError("duplicate checked_event_ids in ex_date_price_consistency")
    if status == "consistent":
        return bool(event_ids) and checked_ids == event_ids
    if status == "not_applicable_no_events":
        return not event_ids and not checked_ids
    return False


def derive_adjustment_context_from_offline_evidence(evidence) -> dict:
    """Derive the three existing paper-evaluation confirmation booleans from a local schema-bound evidence packet.

    This is the offline half of the corporate-action / price-adjustment gate. It does not fetch provider data,
    parse raw payloads, calculate returns, claim reconciliation, or authorize ship-gate / production use.
    """
    if not isinstance(evidence, dict):
        raise PaperEvalGateError("offline adjustment evidence must be a dict")
    _validate_offline_evidence_schema(evidence)
    _reject_unknown_keys(evidence, _OFFLINE_EVIDENCE_KEYS, "offline evidence")
    scope = _optional_dict(evidence, "scope", _SCOPE_KEYS)
    if scope and (
        scope.get("offline_detection_only") is not True
        or scope.get("provider_call_performed") is not False
        or scope.get("corporate_action_reconciliation_claimed") is not False
        or scope.get("ship_gate_or_production_authorized") is not False
    ):
        raise PaperEvalGateError("offline adjustment evidence scope must not authorize provider/live/ship-gate use")
    valid_ids = _source_ref_ids(evidence)
    split_ok, split_events = _handling_confirmed(evidence, "split_handling", valid_ids)
    dividend_ok, dividend_events = _handling_confirmed(evidence, "dividend_handling", valid_ids)
    event_ids = split_events | dividend_events
    return {
        "adjustment_mode_confirmed": _adjustment_mode_confirmed(evidence, valid_ids),
        "split_dividend_handled": split_ok and dividend_ok,
        "ex_date_price_consistent": _ex_date_consistent(evidence, valid_ids, event_ids),
    }


def paper_performance_evaluability_from_offline_evidence(evidence) -> dict:
    """Run the existing paper-evaluation gate from a local schema-bound corporate-action evidence packet."""
    adjustment_context = derive_adjustment_context_from_offline_evidence(evidence)
    result = dict(paper_performance_evaluability(adjustment_context))
    result["adjustment_context"] = adjustment_context
    result["corporate_action_gate_source"] = "offline_adjustment_evidence"
    return result


def paper_performance_evaluability(adjustment_context) -> dict:
    """Decide whether paper_performance is adjustment-evaluable for paper / reporting / shadow use (§12.1 复权门,
    fail-closed) — NEVER a full-size ship-gate permission (§12 / §27; the output keeps that explicitly disallowed).

    ``adjustment_context`` is a dict over (a subset of) the three §12.1 corporate-action confirmations — each is
    counted as confirmed ONLY when its value is literally ``True`` (a missing key, ``False``, ``None``, or a
    truthy non-bool does NOT confirm). Returns ``{"status": "evaluable" | "not_evaluable", "unconfirmed":
    [<confirmations not literally True>], "blocks_paper_performance_due_to_corporate_action": bool,
    "full_size_ship_gate_allowed": False, "ship_gate_evidence_level": "paper_not_live_normalized"}`` — ``evaluable``
    (paper / reporting / shadow design-iteration use) ONLY when all three are confirmed, else ``not_evaluable``.
    ``full_size_ship_gate_allowed`` / ``ship_gate_evidence_level`` are FIXED (paper is never full-size ship-gate
    eligible, §12 / §27), so corporate-action evaluability can never be mistaken for ship-gate permission. Raises
    ``PaperEvalGateError`` on a non-dict context or an UNKNOWN confirmation key (closed-world — a typo'd key would
    otherwise silently leave a real confirmation unreported and could look confirmed)."""
    if not isinstance(adjustment_context, dict):
        raise PaperEvalGateError("adjustment_context must be a dict, got %r" % (type(adjustment_context).__name__,))
    unknown = [k for k in adjustment_context if k not in _CONFIRMATIONS]
    if unknown:
        raise PaperEvalGateError(
            "unknown corporate-action confirmation key(s) %s — not in %s (closed-world: a typo'd key must fail "
            "closed, never silently drop a confirmation)" % (sorted(map(str, unknown)), list(_CONFIRMATIONS))
        )
    unconfirmed = [k for k in _CONFIRMATIONS if adjustment_context.get(k) is not True]  # ONLY literal True confirms
    blocked = bool(unconfirmed)
    return {
        "status": "not_evaluable" if blocked else "evaluable",
        "unconfirmed": unconfirmed,
        # LOCAL corporate-action cause ONLY — True when an unconfirmed corporate-action keeps paper_performance
        # out of paper / reporting / shadow use. It is NOT a ship-gate permission signal.
        "blocks_paper_performance_due_to_corporate_action": blocked,
        # §12 / §27 HARD invariant — stays fixed regardless of corporate-action confirmation: this is a PAPER
        # gate; model_paper_track evidence is design-iteration only and is NEVER full-size ship-gate eligible
        # (only live_normalized = manual_actual + reconciliation graduates). So evaluability here can never be
        # read as ship-gate permission (R-USSHORT-BATCH3-PAPER-EVAL-GATE-SHIP-GATE-PERMISSION-GAP).
        "full_size_ship_gate_allowed": False,
        "ship_gate_evidence_level": "paper_not_live_normalized",
    }
