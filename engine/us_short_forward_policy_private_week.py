# -*- coding: utf-8 -*-
"""Private persistence seam for one source-injected US-short comparison v2 forward week.

This is deliberately a caller-injected, offline materializer rather than a provider adapter or weekly-runner stage.
It binds the complete Cut-A capture to the third-blade all-candidate order snapshot, records the exact forward price
input bundle, recomputes the existing H5/H10/H20 outcome core, and atomically persists one ticker-bearing record on a
proven private path.  Thus a later accumulator can distinguish an order-snapshot no-count from an incomplete price
window and can re-derive that no policy got a selected-only order or a different price window.

It does not fetch data, add a provider call, scan a directory, schedule itself, alter the formal model-paper ledger,
make a factor recommendation, or change the primary system.  Forward inputs remain supplied by a future authorized
source layer; this module only fail-closes and preserves their exact injected form.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import jsonschema

from engine.us_short_forward_policy_order_snapshot import (
    ForwardPolicyOrderSnapshotError,
    validate_forward_policy_order_snapshot_packet,
)
from engine.us_short_forward_policy_outcome import (
    ForwardPolicyOutcomeError,
    produce_forward_policy_outcome,
    validate_forward_policy_outcome_packet,
)
from engine.us_short_forward_policy_shadow_stage import (
    ForwardPolicyShadowStageError,
    validate_forward_shadow_selection_record,
)
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_private_week.schema.json"
PRIVATE_ROOT = ROOT / "state" / "us_short" / "shadow_compare_private"
_RECORD_KEYS = frozenset({
    "schema_name", "schema_version", "materialization_status", "capture_binding", "capture",
    "capture_sha256", "order_snapshot", "order_snapshot_packet_sha256", "forward_inputs",
    "forward_input_snapshot_sha256", "outcome_packet", "outcome_packet_sha256", "degradation_reason", "boundary",
})
_FORWARD_INPUT_KEYS = frozenset({"daily_bars_by_ticker", "cost_prior", "adjustment_evidence"})
BOUNDARY = {
    "track": "comparison_non_production",
    "evidence_level": "forward_policy_private_week_persistence",
    "shadow_counts_ship_gate": False,
    "full_size_ship_gate_allowed": False,
    "changes_primary_selection": False,
    "provider_calls_added": False,
    "broker_or_order_automation_allowed": False,
    "writes_private_forward_packet": True,
    "writes_model_paper_ledger": False,
    "writes_formal_recommendation": False,
}


class ForwardPolicyPrivateWeekError(ValueError):
    """The common capture, order snapshot, forward input, or private record is unsafe to persist."""


def _canonical_sha256(value: object) -> str:
    try:
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ForwardPolicyPrivateWeekError("private forward-week value is not finite canonical JSON") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_schema() -> dict:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyPrivateWeekError("cannot load forward-policy private-week schema") from exc


def _validate_schema(record: object) -> None:
    try:
        jsonschema.validate(record, _load_schema())
    except jsonschema.ValidationError as exc:
        raise ForwardPolicyPrivateWeekError(f"forward-policy private-week schema rejected: {exc.message}") from exc


def _private_path_is_canonical(path: Path, *, decision_date: str) -> None:
    expected_name = f"forward_policy_outcome_{decision_date}.json"
    resolved = path.resolve()
    root = ROOT.resolve()
    try:
        in_repo = resolved.is_relative_to(root)
    except AttributeError:  # pragma: no cover - supported Python has is_relative_to
        in_repo = str(resolved).startswith(str(root))
    if in_repo and (resolved.parent != PRIVATE_ROOT.resolve() or resolved.name != expected_name):
        raise ForwardPolicyPrivateWeekError(
            "in-repo forward-policy private week must use the canonical shadow_compare_private decision bucket"
        )
    if not in_repo and resolved.name != expected_name:
        raise ForwardPolicyPrivateWeekError("external forward-policy private week must retain its decision-date filename")


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _validated_capture(capture: object) -> dict:
    try:
        return validate_forward_shadow_selection_record(capture)
    except ForwardPolicyShadowStageError as exc:
        raise ForwardPolicyPrivateWeekError(f"invalid v2 Cut-A capture: {exc}") from exc


def _validated_order_snapshot(order_snapshot: object) -> dict:
    try:
        return validate_forward_policy_order_snapshot_packet(order_snapshot)
    except ForwardPolicyOrderSnapshotError as exc:
        raise ForwardPolicyPrivateWeekError(f"invalid common-order snapshot: {exc}") from exc


def _capture_binding(capture: dict) -> dict:
    return {
        "decision_date": capture["decision_date"],
        "price_basis_date": capture["price_basis_date"],
        "source_context_sha256": capture["source_context_sha256"],
        "comparison_contract_sha256": capture["comparison_contract_sha256"],
        "common_selection_pool_sha256": capture["common_selection_pool_sha256"],
        "capture_sha256": _canonical_sha256(capture),
    }


def _validate_capture_snapshot_binding(capture: dict, order_snapshot: dict) -> None:
    if order_snapshot["capture_binding"] != _capture_binding(capture):
        raise ForwardPolicyPrivateWeekError(
            "Cut-A capture does not exactly match the common-order snapshot capture/date/contract/pool binding"
        )


def _forward_inputs(*, daily_bars_by_ticker: object, cost_prior: object, adjustment_evidence: object) -> dict:
    if daily_bars_by_ticker is None or cost_prior is None or adjustment_evidence is None:
        raise ForwardPolicyPrivateWeekError(
            "a ready common-order snapshot requires all caller-injected daily bars, cost prior, and adjustment evidence"
        )
    return {
        "daily_bars_by_ticker": daily_bars_by_ticker,
        "cost_prior": cost_prior,
        "adjustment_evidence": adjustment_evidence,
    }


def _base_record(*, capture: dict, order_snapshot: dict) -> dict:
    return {
        "schema_name": "us_short_forward_policy_private_week",
        "schema_version": "1.0.0",
        "capture_binding": _capture_binding(capture),
        "capture": capture,
        "capture_sha256": _canonical_sha256(capture),
        "order_snapshot": order_snapshot,
        "order_snapshot_packet_sha256": _canonical_sha256(order_snapshot),
        "boundary": dict(BOUNDARY),
    }


def _outcome_for(*, capture: dict, order_snapshot: dict, inputs: dict) -> dict:
    try:
        outcome = produce_forward_policy_outcome(
            capture=capture,
            orders_by_ticker=order_snapshot["orders_by_ticker"],
            daily_bars_by_ticker=inputs["daily_bars_by_ticker"],
            cost_prior=inputs["cost_prior"],
            adjustment_evidence=inputs["adjustment_evidence"],
        )
        validate_forward_policy_outcome_packet(outcome)
    except ForwardPolicyOutcomeError as exc:
        raise ForwardPolicyPrivateWeekError(f"forward outcome core rejected the injected private-week inputs: {exc}") from exc
    if outcome["capture_binding"] != order_snapshot["capture_binding"]:
        raise ForwardPolicyPrivateWeekError("outcome capture binding drifted from its common-order snapshot")
    if outcome["common_selection_pool"] != order_snapshot["common_selection_pool"]:
        raise ForwardPolicyPrivateWeekError("outcome common pool drifted from its common-order snapshot")
    if outcome["common_order_snapshot_sha256"] != order_snapshot["common_order_snapshot_sha256"]:
        raise ForwardPolicyPrivateWeekError("outcome order digest drifted from its common-order snapshot")
    return outcome


def materialize_forward_policy_private_week(
    *, capture: object, order_snapshot: object, daily_bars_by_ticker: object, cost_prior: object,
    adjustment_evidence: object, private_output_path: object,
) -> dict:
    """Atomically write one private, source-injected comparison week after all bindings revalidate.

    A third-blade ``data_degraded_whole_week_no_count`` order snapshot is itself durable evidence, but it must carry
    no forward inputs or fabricated outcome.  A ready snapshot always invokes the existing outcome core once; an
    incomplete H20 window or adjustment failure is persisted as a no-count packet with its exact supplied input bundle.
    """
    frozen_capture = _validated_capture(capture)
    frozen_snapshot = _validated_order_snapshot(order_snapshot)
    _validate_capture_snapshot_binding(frozen_capture, frozen_snapshot)
    decision_date = frozen_capture["decision_date"]
    path = Path(private_output_path)
    if not path.is_absolute():
        raise ForwardPolicyPrivateWeekError("private forward-week output path must be absolute")
    _private_path_is_canonical(path, decision_date=decision_date)
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise ForwardPolicyPrivateWeekError(str(exc)) from exc

    record = _base_record(capture=frozen_capture, order_snapshot=frozen_snapshot)
    if frozen_snapshot["order_snapshot_status"] == "data_degraded_whole_week_no_count":
        if any(value is not None for value in (daily_bars_by_ticker, cost_prior, adjustment_evidence)):
            raise ForwardPolicyPrivateWeekError("order-snapshot no-count must not carry unused forward inputs")
        record.update({
            "materialization_status": "data_degraded_whole_week_no_count",
            "forward_inputs": None,
            "forward_input_snapshot_sha256": None,
            "outcome_packet": None,
            "outcome_packet_sha256": None,
            "degradation_reason": f"order_snapshot:{frozen_snapshot['degradation_reason']}",
        })
    else:
        inputs = _forward_inputs(
            daily_bars_by_ticker=daily_bars_by_ticker, cost_prior=cost_prior, adjustment_evidence=adjustment_evidence,
        )
        outcome = _outcome_for(capture=frozen_capture, order_snapshot=frozen_snapshot, inputs=inputs)
        record.update({
            "materialization_status": (
                "ready_for_accumulation" if outcome["outcome_status"] == "ready_for_comparison"
                else "data_degraded_whole_week_no_count"
            ),
            "forward_inputs": inputs,
            "forward_input_snapshot_sha256": _canonical_sha256(inputs),
            "outcome_packet": outcome,
            "outcome_packet_sha256": _canonical_sha256(outcome),
            "degradation_reason": (
                None if outcome["outcome_status"] == "ready_for_comparison"
                else f"outcome:{outcome['degradation_reason']}"
            ),
        })
    validate_forward_policy_private_week_record(record)
    _atomic_json_write(path, record)
    return {
        "private_record_path": str(path),
        "materialization_status": record["materialization_status"],
        "decision_date": decision_date,
    }


def validate_forward_policy_private_week_record(record: object) -> dict:
    """Closed-world consumer gate for the private forward-week packet before any future accumulator reads it."""
    if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
        raise ForwardPolicyPrivateWeekError("private forward-week record must use its exact closed-world key set")
    _validate_schema(record)
    if record["boundary"] != BOUNDARY:
        raise ForwardPolicyPrivateWeekError("private forward-week boundary drifted from comparison-only policy")
    capture = _validated_capture(record["capture"])
    order_snapshot = _validated_order_snapshot(record["order_snapshot"])
    binding = _capture_binding(capture)
    if record["capture_binding"] != binding or order_snapshot["capture_binding"] != binding:
        raise ForwardPolicyPrivateWeekError("private forward-week capture binding does not match its frozen capture")
    if record["capture_sha256"] != _canonical_sha256(capture):
        raise ForwardPolicyPrivateWeekError("private forward-week capture digest is inconsistent")
    if record["order_snapshot_packet_sha256"] != _canonical_sha256(order_snapshot):
        raise ForwardPolicyPrivateWeekError("private forward-week order-snapshot packet digest is inconsistent")

    status = record["materialization_status"]
    inputs, outcome = record["forward_inputs"], record["outcome_packet"]
    if order_snapshot["order_snapshot_status"] == "data_degraded_whole_week_no_count":
        expected_reason = f"order_snapshot:{order_snapshot['degradation_reason']}"
        if status != "data_degraded_whole_week_no_count" or record["degradation_reason"] != expected_reason \
                or any(value is not None for value in (
                    inputs, record["forward_input_snapshot_sha256"], outcome, record["outcome_packet_sha256"],
                )):
            raise ForwardPolicyPrivateWeekError("order-snapshot no-count record must contain no forward input or outcome")
        return record

    if not isinstance(inputs, dict) or set(inputs) != _FORWARD_INPUT_KEYS:
        raise ForwardPolicyPrivateWeekError("ready order snapshot requires the exact forward-input bundle")
    if record["forward_input_snapshot_sha256"] != _canonical_sha256(inputs):
        raise ForwardPolicyPrivateWeekError("private forward-week input digest is inconsistent")
    if not isinstance(outcome, dict) or record["outcome_packet_sha256"] != _canonical_sha256(outcome):
        raise ForwardPolicyPrivateWeekError("private forward-week outcome packet digest is inconsistent")
    try:
        validate_forward_policy_outcome_packet(outcome)
    except ForwardPolicyOutcomeError as exc:
        raise ForwardPolicyPrivateWeekError(f"invalid persisted forward outcome: {exc}") from exc
    if outcome["capture_binding"] != binding \
            or outcome["common_selection_pool"] != order_snapshot["common_selection_pool"] \
            or outcome["common_order_snapshot_sha256"] != order_snapshot["common_order_snapshot_sha256"]:
        raise ForwardPolicyPrivateWeekError("persisted forward outcome is not bound to the frozen common-order snapshot")
    # A self-consistent input digest alone does not prove the stored outcome was calculated from those exact inputs:
    # an editor could replace valid bars/cost/evidence and update only the input digest.  Re-run the pure outcome core
    # and require the entire packet to match before an accumulator can treat this private record as a real week.
    recomputed_outcome = _outcome_for(capture=capture, order_snapshot=order_snapshot, inputs=inputs)
    if outcome != recomputed_outcome:
        raise ForwardPolicyPrivateWeekError("persisted forward outcome does not equal the exact rederived input outcome")
    if outcome["outcome_status"] == "ready_for_comparison":
        if status != "ready_for_accumulation" or record["degradation_reason"] is not None:
            raise ForwardPolicyPrivateWeekError("ready outcome must be the only accumulator-ready private-week status")
    else:
        expected_reason = f"outcome:{outcome['degradation_reason']}"
        if status != "data_degraded_whole_week_no_count" or record["degradation_reason"] != expected_reason:
            raise ForwardPolicyPrivateWeekError("degraded outcome must remain a whole-week no-count record")
    return record
