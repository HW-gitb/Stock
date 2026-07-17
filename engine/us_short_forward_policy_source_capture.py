# -*- coding: utf-8 -*-
"""Private, source-bound capture and maturity helpers for US-short A1 comparison evidence.

The decision-time helper freezes one common-pool price-control map from the already fetched
full-universe OHLCV packet.  Every A1 selection head subsequently faces the identical model-paper
execution basis: pullback-only, one shared market regime, and one frozen cost prior.  The later
maturity helper consumes a subsequent already-fetched OHLCV packet, extracts only the first H20
sessions after that frozen decision, and writes the existing private forward-week record.

No function fetches a provider, relaxes the corporate-action gate, changes balanced selection,
or makes a production switch.  Missing verified adjustment evidence is represented as an explicit
whole-week no-count, never as a zero-return or a counted observation.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import jsonschema

from engine.us_short_forward_policy_comparison_ledger import build_same_run_source_receipt
from engine.us_short_forward_policy_order_snapshot import (
    ForwardPolicyOrderSnapshotError,
    produce_forward_policy_order_snapshot,
    validate_forward_policy_order_snapshot_packet,
)
from engine.us_short_forward_policy_private_week import (
    ForwardPolicyPrivateWeekError,
    materialize_forward_policy_private_week,
    validate_forward_policy_private_week_record,
)
from engine.us_short_forward_policy_shadow_stage import (
    ForwardPolicyShadowStageError,
    validate_forward_shadow_selection_record,
)
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path


ROOT = Path(__file__).resolve().parent.parent
PRIVATE_ROOT = ROOT / "state" / "us_short" / "shadow_compare_private"
_OHLCV_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_ohlcv_series_packet.schema.json"
_SOURCE_CAPTURE_SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_source_capture.schema.json"
_EXECUTION_SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_comparison_execution.schema.json"
_EXECUTION_PRESET_PATH = ROOT / "presets" / "us_short_forward_policy_comparison_execution_20260717.json"
_CAPTURE_KEYS = frozenset({
    "schema_name", "schema_version", "capture", "candidate_price_inputs_by_ticker",
    "market_axis_regimes", "prior_regime", "prior_upgrade_count", "order_snapshot",
    "cost_prior", "execution_contract_sha256", "source_binding", "boundary",
})
BOUNDARY = {
    "track": "comparison_non_production",
    "provider_calls_added": False,
    "shadow_counts_ship_gate": False,
    "changes_primary_selection": False,
    "automatic_production_switch": False,
    "broker_or_order_automation_allowed": False,
    "writes_private_source_capture": True,
}


class ForwardPolicySourceCaptureError(ValueError):
    """The private A1 source capture or its later H20 maturity input is unsafe."""


def _canonical_sha256(value: object) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ForwardPolicySourceCaptureError("source-capture value is not finite canonical JSON") from exc
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_json(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicySourceCaptureError(f"cannot load {label}") from exc
    if not isinstance(value, dict):
        raise ForwardPolicySourceCaptureError(f"{label} must be a JSON object")
    return value


def _validate_schema(value: object, path: Path, *, label: str) -> None:
    try:
        jsonschema.validate(value, _load_json(path, label=label))
    except jsonschema.ValidationError as exc:
        raise ForwardPolicySourceCaptureError(f"{label} schema rejected: {exc.message}") from exc


def _strict_date(value: object) -> bool:
    if not (type(value) is str and value.isascii() and len(value) == 8 and value.isdigit()):
        return False
    try:
        datetime.date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return False
    return True


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _finite_positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0.0


def _iso_date(compact: str) -> str:
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"


def _strict_iso_date(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _capture_output_path_is_valid(path: Path, *, decision_date: str) -> None:
    expected_name = f"forward_policy_source_capture_{decision_date}.json"
    if path.name != expected_name:
        raise ForwardPolicySourceCaptureError("source capture must keep its canonical decision-date filename")
    resolved = path.resolve()
    root = ROOT.resolve()
    try:
        in_repo = resolved.is_relative_to(root)
    except AttributeError:  # pragma: no cover
        in_repo = str(resolved).startswith(str(root))
    if in_repo and resolved.parent != PRIVATE_ROOT.resolve():
        raise ForwardPolicySourceCaptureError("in-repo source capture must stay in shadow_compare_private")


def load_forward_policy_comparison_execution_contract() -> dict:
    """Load the const-pinned shared execution/cost basis for all A1 selection-factor arms."""
    contract = _load_json(_EXECUTION_PRESET_PATH, label="comparison execution preset")
    _validate_schema(contract, _EXECUTION_SCHEMA_PATH, label="comparison execution preset")
    return contract


def forward_policy_comparison_execution_contract_sha256() -> str:
    return _canonical_sha256(load_forward_policy_comparison_execution_contract())


def _validated_capture(value: object) -> dict:
    try:
        return validate_forward_shadow_selection_record(value)
    except ForwardPolicyShadowStageError as exc:
        raise ForwardPolicySourceCaptureError(f"invalid Cut-A selection capture: {exc}") from exc


def _validated_ohlcv_packet(packet: object) -> dict:
    _validate_schema(packet, _OHLCV_SCHEMA_PATH, label="full-universe OHLCV packet")
    if not isinstance(packet, dict):
        raise ForwardPolicySourceCaptureError("full-universe OHLCV packet must be an object")
    return packet


def _candidate_price_inputs(
    *, capture: dict, ohlcv_packet: dict, overextension_by_ticker: object, contract: dict,
) -> dict[str, dict]:
    common_pool = capture["common_selection_pool"]
    if not isinstance(overextension_by_ticker, dict) or not set(common_pool).issubset(overextension_by_ticker):
        raise ForwardPolicySourceCaptureError("source-bound overextension map must cover every common-pool candidate")
    price_basis_iso = _iso_date(capture["price_basis_date"])
    packet_clock = ohlcv_packet["decision_clock"]
    if (
        packet_clock["expected_decision_date"] != capture["decision_date"]
        or packet_clock["candidate_price_basis_date"] != capture["price_basis_date"]
        or packet_clock["price_basis_date"] != price_basis_iso
    ):
        raise ForwardPolicySourceCaptureError("OHLCV packet clock does not match the frozen Cut-A capture")
    series_by_ticker = ohlcv_packet["series_by_ticker"]
    policy = contract["common_execution_policy"]
    rows: dict[str, dict] = {}
    for ticker in common_pool:
        series = series_by_ticker.get(ticker)
        if not isinstance(series, dict) or series.get("as_of") != price_basis_iso:
            raise ForwardPolicySourceCaptureError(f"{ticker} lacks an exact price-basis OHLCV series")
        points = series.get("points")
        if not isinstance(points, list) or not points:
            raise ForwardPolicySourceCaptureError(f"{ticker} OHLCV points are empty")
        normalized = []
        prior_date = None
        for point in points:
            point_date = point.get("date") if isinstance(point, dict) else None
            if not _strict_iso_date(point_date) or point_date > price_basis_iso \
                    or (prior_date is not None and point_date <= prior_date):
                raise ForwardPolicySourceCaptureError(f"{ticker} OHLCV point is malformed or after price basis")
            bar = {key: point.get(key) for key in ("high", "low", "close")}
            if not all(_finite_positive(value) for value in bar.values()) or not (bar["low"] <= bar["close"] <= bar["high"]):
                raise ForwardPolicySourceCaptureError(f"{ticker} OHLCV point has invalid high/low/close geometry")
            normalized.append(bar)
            prior_date = point_date
        if points[-1].get("date") != price_basis_iso:
            raise ForwardPolicySourceCaptureError(f"{ticker} OHLCV series does not terminate at the frozen price basis")
        rows[ticker] = {
            "ticker": ticker,
            "price_input": {"close": normalized[-1]["close"], "bars": normalized},
            "sub_mode": policy["sub_mode"],
            "defensive_breakout_probe_allowed": policy["defensive_breakout_probe_allowed"],
            "overextension": overextension_by_ticker[ticker],
        }
    return rows


def materialize_forward_policy_source_capture(
    *,
    capture: object,
    ohlcv_packet: object,
    ohlcv_packet_sha256: str,
    source_context_sha256: str,
    overextension_by_ticker: object,
    market_axis_regimes: object,
    prior_regime: object,
    prior_upgrade_count: object,
    private_output_path: object,
) -> dict:
    """Freeze decision-time common execution inputs/order geometry on a private canonical path.

    This is deliberately a local consumer of the capstone's already fetched OHLCV packet.  All
    common-pool names are assigned the same pullback-only comparison execution policy so selection
    factors, not policy-specific entry styles, are what later H10 evidence compares.
    """
    frozen_capture = _validated_capture(capture)
    if not (_sha(ohlcv_packet_sha256) and _sha(source_context_sha256)):
        raise ForwardPolicySourceCaptureError("source-capture digests must be lowercase SHA256 values")
    if source_context_sha256 != frozen_capture["source_context_sha256"]:
        raise ForwardPolicySourceCaptureError("source context digest does not match the Cut-A capture")
    frozen_packet = _validated_ohlcv_packet(ohlcv_packet)
    contract = load_forward_policy_comparison_execution_contract()
    inputs = _candidate_price_inputs(
        capture=frozen_capture,
        ohlcv_packet=frozen_packet,
        overextension_by_ticker=overextension_by_ticker,
        contract=contract,
    )
    try:
        snapshot = produce_forward_policy_order_snapshot(
            capture=frozen_capture,
            price_basis_date=frozen_capture["price_basis_date"],
            candidate_price_inputs_by_ticker=inputs,
            market_axis_regimes=market_axis_regimes,
            prior_regime=prior_regime,
            prior_upgrade_count=prior_upgrade_count,
        )
    except ForwardPolicyOrderSnapshotError as exc:
        raise ForwardPolicySourceCaptureError(f"common source capture could not form its order snapshot: {exc}") from exc
    path = Path(private_output_path)
    if not path.is_absolute():
        raise ForwardPolicySourceCaptureError("source capture output path must be absolute")
    _capture_output_path_is_valid(path, decision_date=frozen_capture["decision_date"])
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise ForwardPolicySourceCaptureError(str(exc)) from exc
    record = {
        "schema_name": "us_short_forward_policy_source_capture",
        "schema_version": "1.0.0",
        "capture": frozen_capture,
        "candidate_price_inputs_by_ticker": inputs,
        "market_axis_regimes": market_axis_regimes,
        "prior_regime": prior_regime,
        "prior_upgrade_count": prior_upgrade_count,
        "order_snapshot": snapshot,
        "cost_prior": contract["cost_prior"],
        "execution_contract_sha256": _canonical_sha256(contract),
        "source_binding": {
            "source_context_sha256": source_context_sha256,
            "ohlcv_packet_sha256": ohlcv_packet_sha256,
            "ohlcv_price_basis_date": frozen_capture["price_basis_date"],
        },
        "boundary": dict(BOUNDARY),
    }
    validate_forward_policy_source_capture(record)
    _atomic_json_write(path, record)
    return {
        "private_source_capture_path": str(path),
        "decision_date": frozen_capture["decision_date"],
        "order_snapshot_status": snapshot["order_snapshot_status"],
    }


def validate_forward_policy_source_capture(record: object) -> dict:
    """Re-derive the private order snapshot before a later maturity step can consume it."""
    if not isinstance(record, dict) or set(record) != _CAPTURE_KEYS:
        raise ForwardPolicySourceCaptureError("source capture must use its exact closed-world key set")
    _validate_schema(record, _SOURCE_CAPTURE_SCHEMA_PATH, label="source capture")
    if record["boundary"] != BOUNDARY:
        raise ForwardPolicySourceCaptureError("source capture comparison-only boundary drifted")
    capture = _validated_capture(record["capture"])
    if record["source_binding"]["source_context_sha256"] != capture["source_context_sha256"] \
            or record["source_binding"]["ohlcv_price_basis_date"] != capture["price_basis_date"]:
        raise ForwardPolicySourceCaptureError("source capture binding drifts from Cut-A capture identity")
    contract = load_forward_policy_comparison_execution_contract()
    if record["execution_contract_sha256"] != _canonical_sha256(contract) or record["cost_prior"] != contract["cost_prior"]:
        raise ForwardPolicySourceCaptureError("source capture execution/cost contract drifted")
    rows = record["candidate_price_inputs_by_ticker"]
    common_pool = capture["common_selection_pool"]
    if not isinstance(rows, dict) or set(rows) != set(common_pool):
        raise ForwardPolicySourceCaptureError("source capture price inputs must cover exactly the common pool")
    policy = contract["common_execution_policy"]
    for ticker in common_pool:
        row = rows[ticker]
        if not isinstance(row, dict) or row.get("ticker") != ticker \
                or row.get("sub_mode") != policy["sub_mode"] \
                or row.get("defensive_breakout_probe_allowed") is not policy["defensive_breakout_probe_allowed"]:
            raise ForwardPolicySourceCaptureError("source capture common execution policy drifted")
    try:
        rederived = produce_forward_policy_order_snapshot(
            capture=capture,
            price_basis_date=capture["price_basis_date"],
            candidate_price_inputs_by_ticker=rows,
            market_axis_regimes=record["market_axis_regimes"],
            prior_regime=record["prior_regime"],
            prior_upgrade_count=record["prior_upgrade_count"],
        )
        validate_forward_policy_order_snapshot_packet(record["order_snapshot"])
    except ForwardPolicyOrderSnapshotError as exc:
        raise ForwardPolicySourceCaptureError(f"source capture order snapshot is invalid: {exc}") from exc
    if record["order_snapshot"] != rederived:
        raise ForwardPolicySourceCaptureError("source capture order snapshot is not the exact rederived common result")
    return record


def unconfirmed_adjustment_evidence(*, decision_date: str, source_packet_sha256: str) -> dict:
    """Produce an honest, schema-valid no-count corporate-action gate when no reviewed evidence exists."""
    if not (_strict_date(decision_date) and _sha(source_packet_sha256)):
        raise ForwardPolicySourceCaptureError("unconfirmed adjustment evidence needs a strict date and packet digest")
    ref_id = "maturity_ohlcv_packet"
    return {
        "schema_name": "us_short_paper_eval_adjustment_evidence",
        "schema_version": "1.0.0",
        "decision_date": decision_date,
        "source_refs": [{
            "id": ref_id,
            "path": "state/us_short/shadow_compare_private/forward_policy_maturity_source.json",
            "sha256": source_packet_sha256,
        }],
        "adjustment_mode": {"status": "ambiguous", "mode": "unknown", "source_ref_ids": [ref_id]},
        "split_handling": {"status": "missing", "source_ref_ids": [ref_id], "event_refs": []},
        "dividend_handling": {"status": "missing", "source_ref_ids": [ref_id], "event_refs": []},
        "ex_date_price_consistency": {"status": "missing", "source_ref_ids": [ref_id], "checked_event_ids": []},
        "scope": {
            "offline_detection_only": True,
            "provider_call_performed": False,
            "corporate_action_reconciliation_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
    }


def _maturity_daily_bars(*, source_capture: dict, current_ohlcv_packet: dict) -> dict[str, list[dict]]:
    entry_iso = _iso_date(source_capture["capture"]["decision_date"])
    series_by_ticker = current_ohlcv_packet["series_by_ticker"]
    out: dict[str, list[dict]] = {}
    for ticker in source_capture["capture"]["common_selection_pool"]:
        series = series_by_ticker.get(ticker)
        if not isinstance(series, dict) or not isinstance(series.get("points"), list):
            continue
        prior_date = None
        for point in series["points"]:
            point_date = point.get("date") if isinstance(point, dict) else None
            if not _strict_iso_date(point_date) or (prior_date is not None and point_date <= prior_date):
                raise ForwardPolicySourceCaptureError(f"{ticker} maturity OHLCV dates are malformed or unordered")
            prior_date = point_date
        points = [point for point in series["points"] if point["date"] >= entry_iso][:20]
        bars = []
        for index, point in enumerate(points, start=1):
            values = {key: point.get(key) for key in ("open", "high", "low", "close")}
            if not all(_finite_positive(value) for value in values.values()) \
                    or not (values["low"] <= values["open"] <= values["high"]
                            and values["low"] <= values["close"] <= values["high"]):
                raise ForwardPolicySourceCaptureError(f"{ticker} maturity OHLCV geometry is invalid")
            bars.append({"session_index": index, "session_date": point["date"].replace("-", ""), **values})
        out[ticker] = bars
    return out


def _reusable_prior_no_count_inputs(*, source_capture: dict, prior_private_week_record: object) -> tuple[dict, dict, str] | None:
    """Return a complete previously frozen H20 input only for a later verified adjustment retry.

    The first mature run can have the full H20 window while corporate-action evidence is still unavailable.
    Retaining that exact private no-count input prevents a later evidence arrival from silently losing the
    original window once the rolling OHLCV packet has aged it out.  It deliberately accepts only this module's
    unconfirmed-evidence marker, exact capture/order identity, and a complete 20-session common-pool input.
    """
    try:
        prior = validate_forward_policy_private_week_record(prior_private_week_record)
    except ForwardPolicyPrivateWeekError as exc:
        raise ForwardPolicySourceCaptureError(f"prior private no-count record is invalid: {exc}") from exc
    if prior["materialization_status"] != "data_degraded_whole_week_no_count" \
            or prior["capture"] != source_capture["capture"] \
            or prior["order_snapshot"] != source_capture["order_snapshot"]:
        return None
    inputs = prior["forward_inputs"]
    if not isinstance(inputs, dict) or inputs.get("cost_prior") != source_capture["cost_prior"]:
        return None
    bars = inputs.get("daily_bars_by_ticker")
    pool = source_capture["capture"]["common_selection_pool"]
    if not isinstance(bars, dict) or set(bars) != set(pool) or any(
        not isinstance(bars[ticker], list) or len(bars[ticker]) != 20 for ticker in pool
    ):
        return None
    evidence = inputs.get("adjustment_evidence")
    if not isinstance(evidence, dict) or evidence.get("decision_date") != source_capture["capture"]["decision_date"]:
        return None
    refs = evidence.get("source_refs")
    if not isinstance(refs, list) or len(refs) != 1:
        return None
    ref = refs[0]
    if not isinstance(ref, dict) or ref.get("id") != "maturity_ohlcv_packet" \
            or ref.get("path") != "state/us_short/shadow_compare_private/forward_policy_maturity_source.json" \
            or not _sha(ref.get("sha256")):
        return None
    expected = unconfirmed_adjustment_evidence(
        decision_date=source_capture["capture"]["decision_date"], source_packet_sha256=ref["sha256"],
    )
    if evidence != expected:
        return None
    return bars, inputs["cost_prior"], ref["sha256"]


def materialize_forward_policy_source_maturity(
    *,
    source_capture: object,
    current_ohlcv_packet: object,
    current_ohlcv_packet_sha256: str,
    source_run_id: str,
    adjustment_evidence: object | None,
    private_outcome_path: object,
    prior_private_week_record: object | None = None,
) -> dict:
    """Materialize one frozen source capture from current H20 bars and emit a receipt only if evaluable.

    The current packet is an existing weekly grouped-daily output.  It supplies no extra provider call;
    missing corporate-action evidence remains an explicit no-count.  A caller may later supply reviewed
    adjustment evidence for this exact decision date, at which point the same pure materialization can
    produce a receipt-backed, countable week without changing the source capture or primary system.
    """
    frozen_source = validate_forward_policy_source_capture(source_capture)
    if not (_sha(current_ohlcv_packet_sha256) and isinstance(source_run_id, str) and source_run_id):
        raise ForwardPolicySourceCaptureError("maturity needs a current source digest and non-blank run id")
    packet = _validated_ohlcv_packet(current_ohlcv_packet)
    capture = frozen_source["capture"]
    path = Path(private_outcome_path)
    if not path.is_absolute():
        raise ForwardPolicySourceCaptureError("maturity private output path must be absolute")
    prior_inputs = None if prior_private_week_record is None else _reusable_prior_no_count_inputs(
        source_capture=frozen_source, prior_private_week_record=prior_private_week_record,
    )
    if frozen_source["order_snapshot"]["order_snapshot_status"] == "data_degraded_whole_week_no_count":
        daily_bars, cost_prior, evidence = None, None, None
        receipt_source_sha256 = current_ohlcv_packet_sha256
    elif prior_inputs is not None and adjustment_evidence is not None:
        daily_bars, cost_prior, receipt_source_sha256 = prior_inputs
        evidence = adjustment_evidence
    else:
        daily_bars = _maturity_daily_bars(source_capture=frozen_source, current_ohlcv_packet=packet)
        cost_prior = frozen_source["cost_prior"]
        evidence = adjustment_evidence if adjustment_evidence is not None else unconfirmed_adjustment_evidence(
            decision_date=capture["decision_date"],
            source_packet_sha256=current_ohlcv_packet_sha256,
        )
        receipt_source_sha256 = current_ohlcv_packet_sha256
    try:
        result = materialize_forward_policy_private_week(
            capture=capture,
            order_snapshot=frozen_source["order_snapshot"],
            daily_bars_by_ticker=daily_bars,
            cost_prior=cost_prior,
            adjustment_evidence=evidence,
            private_output_path=path,
        )
    except ForwardPolicyPrivateWeekError as exc:
        raise ForwardPolicySourceCaptureError(f"maturity private-week materialization failed: {exc}") from exc
    private_week = validate_forward_policy_private_week_record(
        json.loads(path.read_text(encoding="utf-8"))
    )
    receipt = None
    if private_week["materialization_status"] == "ready_for_accumulation":
        receipt = build_same_run_source_receipt(
            private_week,
            run_id=source_run_id,
            source_packet_sha256=receipt_source_sha256,
        )
    return {
        **result,
        "source_receipt": receipt,
        "counted_week_eligible": receipt is not None,
    }
