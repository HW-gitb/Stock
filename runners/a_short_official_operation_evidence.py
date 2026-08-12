#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Freeze published A-short M6.7 operation recommendations as private facts.

This first slice is deliberately narrow.  It consumes only a complete official
``weekly_m67.json`` + matching receipt, validates the published M6.7 again,
and writes one immutable private capture.  It never recalculates an action,
reads a price/cache/provider, writes an outcome, changes M6.7, or executes an
order.  Outcome settlement belongs to the later, separately reviewed knife.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema
from engine.a_short_run_revision import (
    iter_private_week_roots, private_week_root, require_official_revision,
    validate_run_revision_id,
)


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROGRAM_ID = "a_short_official_operation_evidence"
SCHEMA_PATH = ROOT / "schemas" / "a_short_official_operation_evidence_private_capture.schema.json"
OUTCOME_SCHEMA_PATH = ROOT / "schemas" / "a_short_official_operation_evidence_private_outcome.schema.json"
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "a_short_official_operation_evidence_ledger.schema.json"
WEEKLY_SCHEMA_PATH = ROOT / "schemas" / "a_short_weekly_report.schema.json"
M67_SCHEMA_PATH = ROOT / "schemas" / "a_short_m67_report.schema.json"
PRIVATE_ROOT_SUFFIX = ("state", "a_short", "operation_evidence_private", "v1")
PRIVATE_ROOT_DEFAULT = ROOT.joinpath(*PRIVATE_ROOT_SUFFIX)
PUBLIC_SUMMARY_DEFAULT = ROOT / "research" / "results" / "a_short" / "official_operation_evidence_summary.json"
PUBLIC_MARKDOWN_DEFAULT = ROOT / "research" / "results" / "a_short" / "official_operation_evidence_summary.md"
EVALUATION_MODE = "live_normalized"
OFFICIAL_POLICY_VERSION = "official_m67_v1"
MIN_PUBLIC_COHORT_SIZE = 5


class OfficialOperationEvidenceError(ValueError):
    """A formal recommendation capture cannot be proved from its official source."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialOperationEvidenceError("official_operation_capture_source_unreadable") from exc


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _calendar_date(value: object, label: str) -> str:
    text = str(value or "")
    if len(text) != 8 or not text.isascii() or not text.isdigit():
        raise OfficialOperationEvidenceError(f"official_operation_capture_{label}_invalid")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise OfficialOperationEvidenceError(f"official_operation_capture_{label}_invalid") from exc
    return text


def _private_root(root: str | Path) -> Path:
    path = Path(root).resolve()
    if tuple(part.lower() for part in path.parts[-4:]) != PRIVATE_ROOT_SUFFIX:
        raise OfficialOperationEvidenceError(
            "official operation private root must end state/a_short/operation_evidence_private/v1"
        )
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return path
    try:
        checked = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", "--", str(relative)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise OfficialOperationEvidenceError("cannot prove official operation private root is gitignored") from exc
    if checked.returncode != 0:
        raise OfficialOperationEvidenceError("official operation private root is not provably gitignored")
    return path


def _boundary() -> dict:
    return {
        "fact_capture_only": True,
        "outcome_settlement_implemented": False,
        "modifies_m67": False,
        "modifies_selection_or_ranking": False,
        "automatic_order_execution": False,
        "shared_business_ledger": False,
    }


def _load_schema(path: Path) -> dict:
    source = _load_json(path)
    if not isinstance(source, dict):
        raise OfficialOperationEvidenceError("official_operation_capture_schema_unreadable")
    return source


def _validate_private_capture(record: dict) -> None:
    try:
        jsonschema.validate(record, _load_schema(SCHEMA_PATH))
    except jsonschema.ValidationError as exc:
        raise OfficialOperationEvidenceError("official_operation_capture_private_schema_invalid") from exc
    if record.get("program_id") != PROGRAM_ID or record.get("boundary") != _boundary():
        raise OfficialOperationEvidenceError("official_operation_capture_boundary_drift")
    expected = _digest({key: value for key, value in record.items() if key != "capture_sha256"})
    if record.get("capture_sha256") != expected:
        raise OfficialOperationEvidenceError("official_operation_capture_digest_invalid")
    ids = [row.get("decision_id") for row in record.get("decisions") or []]
    if len(ids) != len(set(ids)):
        raise OfficialOperationEvidenceError("official_operation_capture_duplicate_decision_id")


def _load_official_bundle(*, out_path: str | Path, receipt_path: str | Path):
    """Accept an official bundle only when the receipt binds the exact JSON file."""
    from runners.a_short_weekly_pipeline import validate_published_weekly_bundle
    from runners.a_short_phase5_engine import validate_m67_consistency

    output = Path(out_path).resolve()
    receipt_file = Path(receipt_path).resolve()
    expected_receipt = output.with_suffix("").with_suffix(".receipt.json")
    if receipt_file != expected_receipt:
        raise OfficialOperationEvidenceError("official_operation_capture_receipt_path_mismatch")
    try:
        bundle = validate_published_weekly_bundle(output, receipt_file)
    except Exception as exc:
        raise OfficialOperationEvidenceError("official_operation_capture_receipt_not_publish_bound") from exc
    weekly, receipt = bundle.weekly, bundle.receipt
    if not isinstance(weekly, dict) or not isinstance(receipt, dict):
        raise OfficialOperationEvidenceError("official_operation_capture_source_shape_invalid")
    try:
        weekly_schema = _load_schema(WEEKLY_SCHEMA_PATH)
        from engine.a_short_effect_contract import load_legacy_effect_contract
        ledger = weekly.get("effect_contract_ledger") or {}
        # A registered effect-contract fingerprint alone is not enough to
        # bypass the M0.5 shape guard: the weekly bundle must explicitly carry
        # the pre-M0.5 schema version.  Once M0.5 fields are present, all
        # semantic/safety validation remains enabled even on a historical
        # contract.
        legacy_m05 = (
            str(weekly.get("schema_version") or "") == "1.0.0"
            and bool(load_legacy_effect_contract(ledger.get("contract_fingerprint")))
        )
        try:
            jsonschema.validate(weekly, weekly_schema)
        except jsonschema.ValidationError as exc:
            # Published 1.0.0 bundles from before the data-quality shadow and
            # effect-ledger trend guard became required remain readable only
            # through an explicit historical-contract migration entry.  Do
            # not weaken the current schema globally and do not let an
            # unknown fingerprint take this compatibility path.
            legacy_schema = None
            if str(weekly.get("schema_version")) == "1.0.0":
                from engine.a_short_effect_contract import load_legacy_effect_contract
                ledger = weekly.get("effect_contract_ledger") or {}
                if load_legacy_effect_contract(ledger.get("contract_fingerprint")):
                    legacy_schema = copy.deepcopy(weekly_schema)
                    legacy_schema["required"] = [
                        key for key in legacy_schema.get("required", [])
                        if key not in {"data_quality_shadow", "northbound_control"}
                    ]
                    # validate_published_weekly_bundle has already performed
                    # the exact old-ledger reconstruction; this envelope pass
                    # only needs to avoid applying the current ledger shape.
                    legacy_schema["properties"]["effect_contract_ledger"] = {"type": "object"}
            if legacy_schema is None:
                raise
            # The weekly publish reader deliberately grandfathered immutable
            # pre-14A complete bundles whose IV status was represented by the
            # aligned freshness block rather than an explicit status field.
            # Apply that same in-memory compatibility view here; never rewrite
            # the historical bytes and never infer a degraded/partial state.
            schema_weekly = weekly
            lineage = weekly.get("run_lineage") or {}
            freshness = lineage.get("iv_freshness") or {}
            if (
                "iv_feed_status" not in lineage
                and str(weekly.get("schema_version") or "") == "1.0.0"
                and lineage.get("stage_status") == "complete"
                and isinstance(lineage.get("iv_feed"), str)
                and bool(lineage.get("iv_feed"))
                and freshness.get("status") == "aligned"
                and isinstance(freshness.get("iv_data_through"), str)
                and bool(freshness.get("iv_data_through"))
            ):
                schema_weekly = copy.deepcopy(weekly)
                schema_weekly["run_lineage"]["iv_feed_status"] = "ready"
            jsonschema.validate(schema_weekly, legacy_schema)
        m67_schema = _load_schema(M67_SCHEMA_PATH)
        for report in weekly["reports"]:
            jsonschema.validate(report, m67_schema)
            validate_m67_consistency(report, allow_legacy_m05=legacy_m05)
    except (KeyError, jsonschema.ValidationError, ValueError) as exc:
        raise OfficialOperationEvidenceError("official_operation_capture_m67_consistency_invalid") from exc
    lineage = weekly.get("run_lineage") or {}
    if receipt.get("account_snapshot") != lineage.get("account_snapshot"):
        raise OfficialOperationEvidenceError("official_operation_capture_account_snapshot_mismatch")
    return bundle


def _source_identity(
    weekly: dict,
    output: Path,
    receipt_file: Path,
    *,
    validated_bundle=None,
) -> dict:
    lineage = weekly["run_lineage"]
    as_of = _calendar_date(weekly.get("as_of"), "as_of")
    account_snapshot = lineage.get("account_snapshot")
    account_digest = account_snapshot.get("snapshot_digest") if isinstance(account_snapshot, dict) else None
    price_freshness = lineage.get("price_freshness")
    if not isinstance(price_freshness, dict):
        raise OfficialOperationEvidenceError("official_operation_capture_price_freshness_unbound")
    price_data_through = _calendar_date(price_freshness.get("price_data_through"), "price_data_through")
    if price_data_through > as_of:
        raise OfficialOperationEvidenceError("official_operation_capture_price_data_through_after_as_of")
    runtime_configuration = copy.deepcopy(lineage.get("runtime_configuration") or {})
    if not isinstance(runtime_configuration, dict) or not all(
            isinstance(runtime_configuration.get(field), str) and runtime_configuration[field]
            for field in ("schema_name", "schema_version", "configuration_fingerprint")) or \
            not isinstance(runtime_configuration.get("policies"), list):
        raise OfficialOperationEvidenceError("official_operation_capture_runtime_configuration_unbound")
    if account_snapshot is not None and not isinstance(account_digest, str):
        raise OfficialOperationEvidenceError("official_operation_capture_account_snapshot_digest_unbound")
    if validated_bundle is None:
        from runners.a_short_weekly_pipeline import validate_published_weekly_bundle
        validated_bundle = validate_published_weekly_bundle(output, receipt_file)
    receipt = validated_bundle.receipt
    output_binding = (receipt.get("outputs_digest") or {}).get(output.name)
    if not isinstance(output_binding, dict) or \
            output_binding.get("sha256") != validated_bundle.weekly_sha256 or \
            output_binding.get("byte_length") != len(validated_bundle.weekly_bytes):
        raise OfficialOperationEvidenceError("official_operation_capture_receipt_digest_mismatch")
    return {
        "as_of": as_of,
        "price_data_through": price_data_through,
        "run_id": str(lineage["run_id"]),
        "candidate_digest": str(lineage["candidate_digest"]),
        "official_m67_sha256": str(output_binding["sha256"]),
        "official_receipt_sha256": validated_bundle.receipt_sha256,
        "account_snapshot_digest": account_digest,
        "weekly_schema_version": str(weekly["schema_version"]),
        "m67_schema_versions": sorted({str(report["schema_version"]) for report in weekly["reports"]}) or ["1.0.0"],
        "runtime_configuration": runtime_configuration,
        "rule_parameter_versions": {
            "runtime_configuration_schema_name": runtime_configuration.get("schema_name"),
            "runtime_configuration_schema_version": runtime_configuration.get("schema_version"),
            "runtime_configuration_fingerprint": runtime_configuration.get("configuration_fingerprint"),
            "policy_bindings": copy.deepcopy(runtime_configuration.get("policies") or {}),
        },
        "effect_contract_ledger_sha256": _digest(weekly["effect_contract_ledger"]),
    }


def _decision_id(source: dict, symbol: str | None, scope: str,
                 final_action: str | None, holding_disposition: str | None) -> str:
    return _digest({
        "program_id": PROGRAM_ID,
        "as_of": source["as_of"],
        "run_revision_id": source.get("run_revision_id"),
        "run_id": source["run_id"],
        "candidate_digest": source["candidate_digest"],
        "account_snapshot_digest": source["account_snapshot_digest"],
        "symbol": symbol,
        "scope": scope,
        "action_identity": {
            "final_action": final_action,
            "holding_disposition": holding_disposition,
        },
    })


def _portfolio_row(weekly: dict, symbol: str) -> dict | None:
    stock_results = ((weekly.get("portfolio_risk") or {}).get("stock_results") or [])
    matches = [row for row in stock_results if isinstance(row, dict) and str(row.get("ts_code")) == symbol]
    if len(matches) > 1:
        raise OfficialOperationEvidenceError("official_operation_capture_duplicate_portfolio_result")
    return copy.deepcopy(matches[0]) if matches else None


def _frozen_managed_exit_plan(weekly: dict, report: dict, plan: dict, *, scope: str,
                              final_action: str | None) -> tuple[dict | None, str | None]:
    """Freeze only a provable prospective M6.7 entry plan for later cache settlement.

    This is deliberately part of the immutable decision capture.  A later
    result never re-reads a current regime or recomputes prices.  Existing
    holdings are not silently normalized into a synthetic account position:
    without an independently frozen entry basis they remain no-count.
    """
    if scope != "new_candidate" or final_action != "建仓" or not isinstance(plan, dict):
        return None, None
    try:
        from runners.a_short_phase5_engine import ATR_MULT
        regime = ((weekly.get("run_lineage") or {}).get("market_regime") or {}).get("effective_regime")
        atr_multiplier = ATR_MULT[str(regime)]
        levels = {key: float(plan[key]) for key in ("entry_low", "entry_high", "stop", "t1")}
        reference_close = float(plan["entry"])
        price_freshness = (weekly.get("run_lineage") or {}).get("price_freshness") or {}
        reference_trade_date = _calendar_date(price_freshness.get("price_data_through"), "price_data_through")
        t2 = plan.get("t2")
        if t2 is not None:
            levels["t2"] = float(t2)
        if (atr_multiplier <= 0 or reference_close <= 0 or any(value <= 0 for value in levels.values()) or
                levels["stop"] >= levels["entry_high"] or levels["t1"] <= levels["entry_high"] or
                (levels.get("t2") is not None and levels["t2"] <= levels["t1"])):
            return None, "frozen_qfq_conversion_reference_unavailable"
    except (KeyError, TypeError, ValueError, OfficialOperationEvidenceError):
        return None, "frozen_qfq_conversion_reference_unavailable"
    return {
        "decision_date": _calendar_date(weekly.get("as_of"), "as_of"),
        "entry_low": levels["entry_low"],
        "entry_high": levels["entry_high"],
        "stop": levels["stop"],
        "t1": levels["t1"],
        "t2": levels.get("t2"),
        "atr_multiplier": float(atr_multiplier),
        # M6.7 displays QFQ plan levels. The cache uses raw * observed adj
        # execution values, so the captured plan must bind a contemporaneous
        # QFQ reference. The shared exit core derives the conversion and fails
        # closed if the cache cannot prove this exact reference row.
        "price_basis": "qfq",
        "reference_trade_date": reference_trade_date,
        "reference_close": reference_close,
        "policy_version": "official_m67_v1",
    }, None


def _decision_from_report(weekly: dict, source: dict, report: dict) -> dict:
    table = report["m67"]["table"]
    summary = report["m67"]["精简结论区"]
    machine = report["machine"]
    symbol = str(report["ts_code"])
    stateful = machine.get("stateful_risk") or {}
    scope = "existing_holding" if stateful.get("position_state") == "held" else "new_candidate"
    final_action = table["操作"]
    holding_disposition = table.get("持仓处置")
    impacts = [row for row in (machine.get("operation_impact") or []) if isinstance(row, dict)]
    portfolio_row = _portfolio_row(weekly, symbol)
    portfolio_status = ((weekly.get("portfolio_risk") or {}).get("summary") or {}).get("status")
    plan = (machine.get("entry_exit_size_star") or {}).get("plan") or {}
    frozen_plan, frozen_plan_unavailable_reason = _frozen_managed_exit_plan(
        weekly, report, plan, scope=scope, final_action=final_action
    )
    return {
        "decision_id": _decision_id(source, symbol, scope, final_action, holding_disposition),
        "symbol": symbol,
        "scope": scope,
        "final_action": final_action,
        "holding_disposition": holding_disposition,
        "display": {
            "name": report.get("name"),
            "row_source": report.get("row_source"),
            "coverage_status": report.get("coverage_status"),
            "summary": copy.deepcopy(summary),
            "table": copy.deepcopy(table),
        },
        "constraints": {
            "blocked_add": bool(table.get("禁止加仓") or machine.get("blocked_add_required")),
            "hard_veto": bool(final_action == "否决" or any(
                row.get("veto_class") == "production_hard_veto" for row in impacts
            )),
            "advisory_downgrade": bool(
                holding_disposition not in {None, "持有"} or any(
                    row.get("veto_class") == "m67_advisory_veto" for row in impacts
                )
            ),
            "account_or_portfolio_blockage": {
                "account_integrity_status": ((weekly.get("run_lineage") or {}).get("account_snapshot") or {}).get("integrity_status"),
                "portfolio_status": portfolio_status,
                "portfolio_row_action": (portfolio_row or {}).get("action"),
                "portfolio_row_reasons": (portfolio_row or {}).get("reasons"),
            },
            "operation_impact": copy.deepcopy(impacts),
        },
        "prices": {
            "entry_type": table.get("类型"),
            "entry_range": {"low": plan.get("entry_low"), "high": plan.get("entry_high"), "display": table.get("入")},
            "take_profit_1": table.get("盈一"),
            "take_profit_2": table.get("盈二"),
            "stop": table.get("损"),
            "trigger": table.get("触发条件"),
            "holding_reduce_price": table.get("减仓价"),
            "holding_clear_price": table.get("清仓价"),
            "holding_reduce_ratio": table.get("减仓比例"),
            "managed_exit_plan": frozen_plan,
            "managed_exit_plan_unavailable_reason": frozen_plan_unavailable_reason,
            "validity": {
                "as_of": report.get("as_of"),
                "price_freshness": copy.deepcopy(((weekly.get("run_lineage") or {}).get("price_freshness"))),
            },
        },
        "sizing": {
            "suggested_shares": table.get("股数"),
            "expected_cash_usage": plan.get("cash_budget_used"),
            "cash_allocation": copy.deepcopy(weekly.get("cash_allocation")),
            "portfolio_stock_result": portfolio_row,
            "portfolio_summary": copy.deepcopy((weekly.get("portfolio_risk") or {}).get("summary")),
        },
        "portfolio": {
            "portfolio_risk": copy.deepcopy(weekly.get("portfolio_risk")),
        },
        "environment": {
            "production_regime": copy.deepcopy((weekly.get("run_lineage") or {}).get("market_regime")),
            "v14_3_comparison": copy.deepcopy(weekly.get("v14_3_comparison")),
            "risk_families": copy.deepcopy(machine.get("risk_families")),
            "coverage": {
                "coverage_status": report.get("coverage_status"),
                "row_source": report.get("row_source"),
            },
            "stateful_risk": copy.deepcopy(stateful),
            "ratchet": copy.deepcopy(machine.get("ratchet")),
        },
        "evidence_modes": {
            "live_normalized": {"status": "capture_pending"},
            "manual_actual": {"status": "not_recorded", "event_ref": None},
        },
    }


def _portfolio_only_decision(weekly: dict, source: dict) -> dict | None:
    summary = ((weekly.get("portfolio_risk") or {}).get("summary") or {})
    status = summary.get("status")
    if status in {None, "not_applicable", "clear"}:
        return None
    return {
        "decision_id": _decision_id(source, None, "portfolio_only", None, None),
        "symbol": None,
        "scope": "portfolio_only",
        "final_action": None,
        "holding_disposition": None,
        "display": {"portfolio_risk": copy.deepcopy(weekly.get("portfolio_risk"))},
        "constraints": {
            "blocked_add": False,
            "hard_veto": False,
            "advisory_downgrade": False,
            "account_or_portfolio_blockage": {"portfolio_status": status, "portfolio_summary": copy.deepcopy(summary)},
            "operation_impact": [],
        },
        "prices": {
            "entry_type": None, "entry_range": {"low": None, "high": None, "display": None},
            "take_profit_1": None, "take_profit_2": None, "stop": None, "trigger": None,
            "holding_reduce_price": None, "holding_clear_price": None, "holding_reduce_ratio": None,
            "validity": {"as_of": weekly.get("as_of"), "price_freshness": None},
        },
        "sizing": {
            "suggested_shares": None, "expected_cash_usage": None, "cash_allocation": None,
            "portfolio_stock_result": None, "portfolio_summary": copy.deepcopy(summary),
        },
        "portfolio": {"portfolio_risk": copy.deepcopy(weekly.get("portfolio_risk"))},
        "environment": {
            "production_regime": copy.deepcopy((weekly.get("run_lineage") or {}).get("market_regime")),
            "v14_3_comparison": copy.deepcopy(weekly.get("v14_3_comparison")),
            "risk_families": None, "coverage": {"coverage_status": None, "row_source": None},
            "stateful_risk": None, "ratchet": None,
        },
        "evidence_modes": {
            "live_normalized": {"status": "capture_pending"},
            "manual_actual": {"status": "not_recorded", "event_ref": None},
        },
    }


def _capture_record(
    weekly: dict,
    output: Path,
    receipt_file: Path,
    *,
    validated_bundle=None,
    run_revision_id: str | None = None,
) -> dict:
    as_of = _calendar_date(weekly.get("as_of"), "as_of")
    source = _source_identity(
        weekly, output, receipt_file, validated_bundle=validated_bundle
    )
    if run_revision_id is not None:
        run_revision_id = validate_run_revision_id(run_revision_id)
        source["run_revision_id"] = run_revision_id
    decisions = [_decision_from_report(weekly, source, report) for report in weekly["reports"]]
    if not decisions:
        portfolio_only = _portfolio_only_decision(weekly, source)
        if portfolio_only is not None:
            decisions.append(portfolio_only)
    record = {
        "schema_name": "a_short_official_operation_evidence_private_capture",
        "schema_version": "1.1.0",
        "record_type": "decision_capture",
        "program_id": PROGRAM_ID,
        "as_of": as_of,
        "run_revision_id": run_revision_id,
        "source_identity": source,
        "decisions": decisions,
        "boundary": _boundary(),
    }
    record["capture_sha256"] = _digest(record)
    _validate_private_capture(record)
    return record


def _capture_path(root: Path, as_of: str, run_revision_id: str | None = None) -> Path:
    return private_week_root(root, as_of, run_revision_id) / "capture.json"


def _write_conflict(root: Path, as_of: str, existing: dict, incoming: dict,
                    run_revision_id: str | None = None) -> None:
    """Record only hashes so a replay conflict never overwrites the original evidence."""
    conflict = {
        "schema_name": "a_short_official_operation_evidence_conflict",
        "schema_version": "1.0.0",
        "program_id": PROGRAM_ID,
        "as_of": as_of,
        "reason": "immutable_capture_content_conflict",
        "existing_capture_sha256": existing.get("capture_sha256"),
        "incoming_capture_sha256": incoming.get("capture_sha256"),
    }
    _atomic_write(private_week_root(root, as_of, run_revision_id) / "conflicts" / f"{as_of}.json", conflict)


def capture_after_published_weekly(*, root: str | Path, out_path: str | Path, receipt_path: str | Path,
                                   run_revision_id: str | None = None) -> dict:
    """Create one immutable capture from the published source; conflict never overwrites it."""
    private_root = _private_root(root)
    bundle = _load_official_bundle(
        out_path=out_path, receipt_path=receipt_path
    )
    record = _capture_record(
        bundle.weekly,
        bundle.weekly_path,
        bundle.receipt_path,
        validated_bundle=bundle,
        run_revision_id=run_revision_id,
    )
    revision = record.get("run_revision_id")
    path = _capture_path(private_root, record["as_of"], revision)
    if path.exists():
        existing = _load_json(path)
        _validate_private_capture(existing)
        if existing == record:
            _refresh_private_ledger(private_root)
            return {"status": "idempotent_existing_capture", "decision_count": len(record["decisions"]),
                    "production_unchanged": True}
        _write_conflict(private_root, record["as_of"], existing, record, revision)
        raise OfficialOperationEvidenceError("official_operation_capture_source_conflict")
    _atomic_write(path, record)
    _refresh_private_ledger(private_root)
    return {"status": "captured", "decision_count": len(record["decisions"]), "production_unchanged": True}


def _outcome_path(root: Path, as_of: str, decision_id: str,
                  run_revision_id: str | None = None) -> Path:
    if run_revision_id is None:
        return root / "outcomes" / f"{decision_id}.json"
    return private_week_root(root, as_of, run_revision_id) / "outcomes" / f"{decision_id}.json"


def _load_capture_records(root: Path) -> list[dict]:
    records: list[dict] = []
    weeks = root / "weeks"
    if not weeks.exists():
        return records
    for as_of, revision, directory in iter_private_week_roots(root):
        capture_path = directory / "capture.json"
        if not capture_path.is_file():
            continue
        capture = _load_json(capture_path)
        _validate_private_capture(capture)
        if capture.get("as_of") != as_of or capture.get("run_revision_id") != revision:
            raise OfficialOperationEvidenceError("official_operation_capture_directory_identity_drift")
        records.append(capture)
    return records


def _validate_private_outcome(record: dict) -> None:
    try:
        jsonschema.validate(record, _load_schema(OUTCOME_SCHEMA_PATH))
    except jsonschema.ValidationError as exc:
        raise OfficialOperationEvidenceError("official_operation_outcome_private_schema_invalid") from exc
    expected = _digest({key: value for key, value in record.items() if key != "outcome_sha256"})
    if record.get("outcome_sha256") != expected:
        raise OfficialOperationEvidenceError("official_operation_outcome_digest_invalid")


def _load_outcome(path: Path) -> dict:
    outcome = _load_json(path)
    _validate_private_outcome(outcome)
    return outcome


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _outcome_terminal(status: str) -> bool:
    return status in {"settled", "no_count"}


def cache_consumer_windows(*, root: str | Path, run_date: str) -> list[dict]:
    """Expose only frozen official plans to P5a's one shared cache writer."""
    private_root = _private_root(root)
    run_date = _calendar_date(run_date, "run_date")
    windows: list[dict] = []
    for capture in _load_capture_records(private_root):
        if capture["as_of"] > run_date or (private_week_root(private_root, capture["as_of"], capture.get("run_revision_id")) /
                                           "conflicts" / f"{capture['as_of']}.json").exists():
            continue
        symbols: list[str] = []
        for decision in capture["decisions"]:
            decision_id = str(decision.get("decision_id") or "")
            existing_path = _outcome_path(private_root, capture["as_of"], decision_id,
                                          capture.get("run_revision_id"))
            if existing_path.is_file() and _outcome_terminal(str(_load_outcome(existing_path).get("status"))):
                continue
            plan = ((decision.get("prices") or {}).get("managed_exit_plan"))
            if (isinstance(plan, dict) and plan.get("policy_version") == OFFICIAL_POLICY_VERSION and
                    isinstance(decision.get("symbol"), str) and decision["symbol"]):
                symbols.append(decision["symbol"])
        if symbols:
            windows.append({
                "consumer": "official_operation_evidence",
                "decision_date": capture["as_of"],
                "price_data_through": capture["source_identity"]["price_data_through"],
                "window_mode": "managed_exit",
                "pre_history_days": 20,
                "horizon_days": 20,
                "symbols": sorted(set(symbols)),
            })
    return windows


def _execution_rows_by_symbol(daily_payload: dict | None) -> dict[str, list[dict]] | None:
    if not isinstance(daily_payload, dict) or not isinstance(daily_payload.get("rows"), list):
        return None
    result: dict[str, list[dict]] = {}
    for raw in daily_payload["rows"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("ts_code"), str) or not raw["ts_code"]:
            return None
        row = {key: value for key, value in raw.items() if key != "ts_code"}
        result.setdefault(raw["ts_code"], []).append(row)
    for rows in result.values():
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))
    return result


def _pending_result(reason: str) -> dict:
    return {"status": "pending", "reason": reason, "metrics": None, "path": None}


def _no_count_result(reason: str) -> dict:
    return {"status": "no_count", "reason": reason, "metrics": None, "path": None}


def _normalized_result(decision: dict, rows: dict[str, list[dict]] | None) -> dict:
    """Classify one frozen recommendation without an account, position, or second evaluator."""
    plan = ((decision.get("prices") or {}).get("managed_exit_plan"))
    if not isinstance(plan, dict):
        scope = str(decision.get("scope") or "")
        unavailable_reason = (decision.get("prices") or {}).get("managed_exit_plan_unavailable_reason")
        return _no_count_result("existing_holding_entry_basis_unavailable" if scope == "existing_holding"
                                else str(unavailable_reason or "frozen_managed_exit_plan_unavailable"))
    if rows is None:
        return _pending_result("shared_execution_cache_unavailable")
    symbol = str(decision.get("symbol") or "")
    execution_rows = rows.get(symbol)
    if not execution_rows:
        return _pending_result("shared_execution_rows_pending")
    from engine.a_short_managed_exit import evaluate_official_managed_exit, managed_exit_evidence_window
    managed = evaluate_official_managed_exit(plan, execution_rows)
    try:
        evidence_window_sha256 = _digest(managed_exit_evidence_window(plan, execution_rows))
    except Exception:
        evidence_window_sha256 = None
    if managed.get("status") == "settled":
        path = managed.get("official_path") or {}
        gross = _finite_number(managed.get("gross_return_pct"))
        net = _finite_number(managed.get("net_return_pct"))
        cost = _finite_number(managed.get("round_trip_cost_pct"))
        if gross is None or net is None or cost is None:
            return _no_count_result("managed_exit_metric_invalid")
        return {
            "status": "settled",
            "reason": None,
            "metrics": {
                "gross_return_pct": gross,
                "cost_total_pct": cost,
                "net_return_pct": net,
                "normalized_capital_employed_fraction": 1.0,
                "mfe_pct": _finite_number(path.get("mfe_pct")),
                "mae_pct": _finite_number(path.get("mae_pct")),
                "filled": True,
                "same_bar_both_triggered": bool(path.get("same_bar_both_triggered")),
                "execution_path_ambiguous": bool(path.get("execution_path_ambiguous")),
            },
            "path": managed,
            "evaluation_window_sha256": evidence_window_sha256,
        }
    reason = str(managed.get("reason") or "managed_exit_unavailable")
    if reason in {"h20_not_available", "execution_prices_unavailable"}:
        return _pending_result(reason)
    result = _no_count_result(reason)
    result["evaluation_window_sha256"] = evidence_window_sha256
    return result


def _outcome_from_decision(*, capture: dict, decision: dict, as_of: str,
                           daily_payload: dict | None, rows: dict[str, list[dict]] | None) -> dict:
    result = _normalized_result(decision, rows)
    record = {
        "schema_name": "a_short_official_operation_evidence_private_outcome",
        "schema_version": "1.1.0",
        "program_id": PROGRAM_ID,
        "decision_id": decision["decision_id"],
        "run_revision_id": capture.get("run_revision_id"),
        "evaluation_mode": EVALUATION_MODE,
        "policy_version": OFFICIAL_POLICY_VERSION,
        "capture_sha256": capture["capture_sha256"],
        "source_as_of": capture["as_of"],
        "settled_through": as_of,
        "cache_sha256": _digest(daily_payload) if daily_payload is not None else None,
        "evaluation_window_sha256": result.get("evaluation_window_sha256"),
        "status": result["status"],
        "reason": result["reason"],
        "metrics": result["metrics"],
        "path": result["path"],
        "boundary": {
            "program_progress_ledger_only": True,
            "portfolio_state_created": False,
            "cash_or_positions_created": False,
            "nav_or_head_manifest_created": False,
            "automatic_order_execution": False,
            "manual_actual_inferred": False,
        },
    }
    record["outcome_sha256"] = _digest(record)
    _validate_private_outcome(record)
    return record


def _write_outcome_conflict(root: Path, decision_id: str, existing: dict, incoming: dict,
                            run_revision_id: str | None = None, source_as_of: str | None = None) -> None:
    conflict_root = (private_week_root(root, source_as_of, run_revision_id)
                     if run_revision_id is not None and source_as_of else root)
    _atomic_write(conflict_root / "conflicts" / f"outcome_{decision_id}.json", {
        "schema_name": "a_short_official_operation_evidence_conflict",
        "schema_version": "1.0.0",
        "program_id": PROGRAM_ID,
        "decision_id": decision_id,
        "reason": "immutable_outcome_content_conflict",
        "existing_outcome_sha256": existing.get("outcome_sha256"),
        "incoming_outcome_sha256": incoming.get("outcome_sha256"),
    })


def _terminal_evidence(record: dict) -> dict:
    """The immutable decision result, excluding a growing cache/progress clock."""
    return {
        key: record.get(key)
        for key in (
            "schema_name", "schema_version", "program_id", "decision_id", "evaluation_mode",
            "policy_version", "capture_sha256", "source_as_of", "status", "reason", "metrics",
            "path", "evaluation_window_sha256", "boundary",
        )
    }


def _write_or_advance_outcome(root: Path, incoming: dict) -> bool:
    path = _outcome_path(root, incoming["source_as_of"], incoming["decision_id"],
                         incoming.get("run_revision_id"))
    if not path.exists():
        _atomic_write(path, incoming)
        return True
    existing = _load_outcome(path)
    if (existing.get("decision_id"), existing.get("evaluation_mode"), existing.get("policy_version"),
            existing.get("capture_sha256")) != (incoming["decision_id"], incoming["evaluation_mode"],
                                                  incoming["policy_version"], incoming["capture_sha256"]):
        _write_outcome_conflict(root, incoming["decision_id"], existing, incoming,
                                incoming.get("run_revision_id"), incoming.get("source_as_of"))
        raise OfficialOperationEvidenceError("official_operation_outcome_identity_conflict")
    if _outcome_terminal(str(existing.get("status"))):
        # A later weekly run naturally has a later progress date and a larger
        # whole-cache digest. Neither changes this decision's frozen H20 input
        # window. Cache absence is likewise not a source conflict after a
        # terminal result has already been proved.
        if not _outcome_terminal(str(incoming.get("status"))) or \
                _terminal_evidence(existing) == _terminal_evidence(incoming):
            return False
        _write_outcome_conflict(root, incoming["decision_id"], existing, incoming,
                                incoming.get("run_revision_id"), incoming.get("source_as_of"))
        raise OfficialOperationEvidenceError("official_operation_outcome_terminal_conflict")
    if existing == incoming:
        return False
    _atomic_write(path, incoming)
    return True


def _cohort_key(capture: dict, decision: dict, outcome: dict) -> dict:
    environment = decision.get("environment") or {}
    constraints = decision.get("constraints") or {}
    prices = decision.get("prices") or {}
    risk_families = environment.get("risk_families") or {}
    active_risk_families = sorted(
        str(name) for name, value in risk_families.items()
        if isinstance(value, dict) and value.get("hit") is True
    ) if isinstance(risk_families, dict) else []
    metrics = outcome.get("metrics") or {}
    fill_status = ("filled" if metrics.get("filled") is True else
                   "unfilled" if outcome.get("reason") in {"entry_unfillable", "entry_outside_frozen_range"}
                   else "not_evaluable")
    return {
        "scope": decision.get("scope"),
        "final_action": decision.get("final_action"),
        "holding_disposition": decision.get("holding_disposition"),
        "entry_type": prices.get("entry_type"),
        "production_regime": (environment.get("production_regime") or {}).get("effective_regime"),
        "v14_3_comparison_label": (environment.get("v14_3_comparison") or {}).get("status"),
        "risk_families": active_risk_families,
        "coverage": (environment.get("coverage") or {}).get("coverage_status"),
        "account_or_portfolio_blocked": bool((constraints.get("account_or_portfolio_blockage") or {}).get("portfolio_status")
                                              not in {None, "clear", "not_applicable"}),
        "outcome_status": outcome.get("status"),
        "fill_status": fill_status,
        "same_bar_ambiguity": bool(((outcome.get("metrics") or {}).get("same_bar_both_triggered"))),
    }


def _refresh_private_ledger(root: Path) -> dict:
    rows: list[dict] = []
    for capture in _load_capture_records(root):
        for decision in capture["decisions"]:
            path = _outcome_path(root, capture["as_of"], decision["decision_id"],
                                 capture.get("run_revision_id"))
            outcome = _load_outcome(path) if path.is_file() else None
            rows.append({
                "decision_id": decision["decision_id"], "capture_as_of": capture["as_of"],
                "run_revision_id": capture.get("run_revision_id"),
                "capture_sha256": capture["capture_sha256"], "evaluation_mode": EVALUATION_MODE,
                "policy_version": OFFICIAL_POLICY_VERSION,
                "status": outcome.get("status") if outcome else "capture_pending",
                "reason": outcome.get("reason") if outcome else None,
                "outcome_sha256": outcome.get("outcome_sha256") if outcome else None,
            })
    if len({(row["decision_id"], row.get("run_revision_id"), row["evaluation_mode"], row["policy_version"]) for row in rows}) != len(rows):
        raise OfficialOperationEvidenceError("official_operation_ledger_duplicate_decision")
    ledger = {
        "schema_name": "a_short_official_operation_evidence_ledger", "schema_version": "1.0.0",
        "program_id": PROGRAM_ID, "records": sorted(rows, key=lambda row: (row["capture_as_of"], row.get("run_revision_id") or "legacy_revision_0", row["decision_id"])),
        "boundary": {"program_progress_ledger_only": True, "portfolio_state_created": False,
                     "cash_or_positions_created": False, "nav_or_head_manifest_created": False,
                     "automatic_order_execution": False},
    }
    try:
        jsonschema.validate(ledger, _load_schema(LEDGER_SCHEMA_PATH))
    except jsonschema.ValidationError as exc:
        raise OfficialOperationEvidenceError("official_operation_progress_ledger_invalid") from exc
    _atomic_write(root / "ledger.json", ledger)
    return ledger


def build_public_summary(*, root: str | Path, as_of: str,
                         run_revision_id: str | None = None,
                         official_project_root: str | Path | None = None) -> dict:
    """Return a de-identified cohort report; small cohorts expose counts only."""
    private_root, as_of = _private_root(root), _calendar_date(as_of, "as_of")
    if run_revision_id is not None:
        run_revision_id = validate_run_revision_id(run_revision_id)
    official_revision_id = None
    if official_project_root is not None and run_revision_id is None:
        raise OfficialOperationEvidenceError("official summary requires run_revision_id")
    if official_project_root is not None and run_revision_id is not None:
        official_revision_id = require_official_revision(
            official_project_root, as_of, run_revision_id
        )
    grouped: dict[str, dict] = {}
    totals = {"capture_pending": 0, "pending": 0, "settled": 0, "no_count": 0, "ambiguous": 0, "unfilled": 0}
    for capture in _load_capture_records(private_root):
        if capture["as_of"] > as_of:
            continue
        if run_revision_id is not None and capture.get("run_revision_id") != run_revision_id:
            continue
        for decision in capture["decisions"]:
            path = _outcome_path(private_root, capture["as_of"], decision["decision_id"],
                                 capture.get("run_revision_id"))
            outcome = _load_outcome(path) if path.is_file() else {"status": "capture_pending", "metrics": None}
            status = str(outcome["status"])
            totals[status] = totals.get(status, 0) + 1
            metrics = outcome.get("metrics") or {}
            if metrics.get("same_bar_both_triggered"):
                totals["ambiguous"] += 1
            if status == "no_count" and outcome.get("reason") in {"entry_unfillable", "entry_outside_frozen_range"}:
                totals["unfilled"] += 1
            key = _canonical(_cohort_key(capture, decision, outcome))
            bucket = grouped.setdefault(key, {"cohort": _cohort_key(capture, decision, outcome), "records": []})
            bucket["records"].append(outcome)
    cohorts = []
    for bucket in grouped.values():
        records = bucket["records"]
        settled = [row for row in records if row.get("status") == "settled"]
        row = {"cohort": bucket["cohort"], "official_revision_id": official_revision_id,
               "record_count": len(records), "evaluable_count": len(settled),
               "no_count_count": sum(item.get("status") == "no_count" for item in records),
               "ambiguous_count": sum(bool((item.get("metrics") or {}).get("same_bar_both_triggered")) for item in records),
               "metrics_withheld_for_small_cohort": len(settled) < MIN_PUBLIC_COHORT_SIZE}
        if len(settled) >= MIN_PUBLIC_COHORT_SIZE:
            for name in ("gross_return_pct", "cost_total_pct", "net_return_pct", "mfe_pct", "mae_pct"):
                values = [float(item["metrics"][name]) for item in settled if item["metrics"].get(name) is not None]
                row[name + "_mean"] = round(sum(values) / len(values), 8) if values else None
        cohorts.append(row)
    return {
        "schema_name": "a_short_official_operation_evidence_summary", "schema_version": "1.0.0",
        "program_id": PROGRAM_ID, "as_of": as_of, "evaluation_mode": EVALUATION_MODE,
        "official_revision_id": official_revision_id,
        "minimum_metric_cohort_size": MIN_PUBLIC_COHORT_SIZE, "totals": totals,
        "cohorts": sorted(cohorts, key=lambda row: _canonical(row["cohort"])),
        "boundary": {"deidentified_aggregate_only": True, "contains_symbols": False,
                     "contains_account_balances": False, "automatic_policy_change": False},
    }


def write_public_summary(summary: dict, *, json_path: str | Path, markdown_path: str | Path) -> None:
    encoded = _canonical(summary).lower()
    for prohibited in ("ts_code", "account_snapshot", "suggested_shares", "expected_cash_usage"):
        if prohibited in encoded:
            raise OfficialOperationEvidenceError("official_operation_public_summary_privacy_violation")
    _atomic_write(Path(json_path), summary)
    totals = summary["totals"]
    lines = ["# A-short 正式操作建议证据进度", "", "仅统计已冻结建议的规范化前向结果；不是模拟账户，不代表实际成交。", "",
             "| 已冻结 | 待成熟 | 已结算 | no-count | 同根歧义 | 未成交 |", "|---:|---:|---:|---:|---:|---:|",
             f"| {totals.get('capture_pending', 0)} | {totals.get('pending', 0)} | {totals.get('settled', 0)} | {totals.get('no_count', 0)} | {totals.get('ambiguous', 0)} | {totals.get('unfilled', 0)} |",
             "", "小于最小 cohort 的结果只显示计数；不输出股票、账户、持仓、成本或实际成交。"]
    path = Path(markdown_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def settle_and_summarize(*, root: str | Path, as_of: str, daily_cache_path: str | Path | None = None,
                          public_json_path: str | Path = PUBLIC_SUMMARY_DEFAULT,
                          public_markdown_path: str | Path = PUBLIC_MARKDOWN_DEFAULT,
                          run_revision_id: str | None = None,
                          official_project_root: str | Path | None = None) -> dict:
    """Advance only the private decision-progress ledger from the shared cache."""
    private_root, as_of = _private_root(root), _calendar_date(as_of, "as_of")
    if run_revision_id is not None:
        run_revision_id = validate_run_revision_id(run_revision_id)
    official_revision_id = None
    if official_project_root is not None and run_revision_id is None:
        raise OfficialOperationEvidenceError("official settlement requires run_revision_id")
    if official_project_root is not None and run_revision_id is not None:
        official_revision_id = require_official_revision(
            official_project_root, as_of, run_revision_id
        )
    daily_payload = None
    if daily_cache_path is not None and Path(daily_cache_path).is_file():
        daily_payload = _load_json(Path(daily_cache_path))
    rows = _execution_rows_by_symbol(daily_payload)
    if rows is not None:
        # A cache may retain later runs for other consumers. A decision-side
        # settlement can never consume a bar after its own canonical as-of.
        rows = {
            symbol: [row for row in execution_rows if str(row.get("trade_date") or "") <= as_of]
            for symbol, execution_rows in rows.items()
        }
    changed = 0
    for capture in _load_capture_records(private_root):
        if capture["as_of"] > as_of:
            continue
        if run_revision_id is not None and capture.get("run_revision_id") != run_revision_id:
            continue
        if official_project_root is not None:
            capture_revision = capture.get("run_revision_id")
            if capture_revision in (None, ""):
                raise OfficialOperationEvidenceError("official settlement capture missing run_revision_id")
            require_official_revision(
                official_project_root, capture["as_of"], capture_revision
            )
        if (private_week_root(private_root, capture["as_of"], capture.get("run_revision_id")) /
                "conflicts" / f"{capture['as_of']}.json").exists():
            continue
        for decision in capture["decisions"]:
            changed += int(_write_or_advance_outcome(
                private_root,
                _outcome_from_decision(capture=capture, decision=decision, as_of=as_of,
                                       daily_payload=daily_payload, rows=rows),
            ))
    ledger = _refresh_private_ledger(private_root)
    summary = build_public_summary(
        root=private_root, as_of=as_of, run_revision_id=run_revision_id,
        official_project_root=official_project_root,
    )
    write_public_summary(summary, json_path=public_json_path, markdown_path=public_markdown_path)
    return {"status": "settled_from_existing_shared_cache", "outcomes_updated": changed,
            "ledger_record_count": len(ledger["records"]), "summary": summary,
            "production_unchanged": True}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Capture an already-published A-short M6.7 bundle as private evidence")
    parser.add_argument("command", nargs="?", choices=["capture", "settle"], default="capture")
    parser.add_argument("--root", default=str(PRIVATE_ROOT_DEFAULT),
                        help="private root ending state/a_short/operation_evidence_private/v1")
    parser.add_argument("--weekly", help="official published weekly_m67.json (required for capture)")
    parser.add_argument("--receipt", help="matching official weekly_m67.receipt.json (required for capture)")
    parser.add_argument("--as-of", help="settlement date YYYYMMDD (required for settle)")
    parser.add_argument("--daily-cache", help="existing P5a shared daily_cache.json; never fetches")
    parser.add_argument("--summary-out", default=str(PUBLIC_SUMMARY_DEFAULT))
    parser.add_argument("--summary-markdown-out", default=str(PUBLIC_MARKDOWN_DEFAULT))
    args = parser.parse_args(argv)
    if args.command == "capture":
        if not args.weekly or not args.receipt:
            parser.error("capture requires --weekly and --receipt")
        result = capture_after_published_weekly(root=args.root, out_path=args.weekly, receipt_path=args.receipt)
        print(f"[official-operation-evidence] capture={result['status']} decisions={result['decision_count']} "
              "(M6.7 unchanged; no outcome settlement)")
        return
    if not args.as_of:
        parser.error("settle requires --as-of")
    result = settle_and_summarize(root=args.root, as_of=args.as_of, daily_cache_path=args.daily_cache,
                                  public_json_path=args.summary_out,
                                  public_markdown_path=args.summary_markdown_out)
    print(f"[official-operation-evidence] settlement={result['status']} "
          f"updated={result['outcomes_updated']} (no portfolio state)")


if __name__ == "__main__":
    main()
