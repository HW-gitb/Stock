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
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROGRAM_ID = "a_short_official_operation_evidence"
SCHEMA_PATH = ROOT / "schemas" / "a_short_official_operation_evidence_private_capture.schema.json"
WEEKLY_SCHEMA_PATH = ROOT / "schemas" / "a_short_weekly_report.schema.json"
M67_SCHEMA_PATH = ROOT / "schemas" / "a_short_m67_report.schema.json"
PRIVATE_ROOT_SUFFIX = ("state", "a_short", "operation_evidence_private", "v1")
PRIVATE_ROOT_DEFAULT = ROOT.joinpath(*PRIVATE_ROOT_SUFFIX)


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
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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


def _load_official_bundle(*, out_path: str | Path, receipt_path: str | Path) -> tuple[dict, dict, Path, Path]:
    """Accept an official bundle only when the receipt binds the exact JSON file."""
    from runners.a_short_weekly_pipeline import load_published_weekly_bundle
    from runners.a_short_phase5_engine import validate_m67_consistency

    output = Path(out_path).resolve()
    receipt_file = Path(receipt_path).resolve()
    expected_receipt = output.with_suffix("").with_suffix(".receipt.json")
    if receipt_file != expected_receipt:
        raise OfficialOperationEvidenceError("official_operation_capture_receipt_path_mismatch")
    try:
        weekly = load_published_weekly_bundle(str(output))
    except Exception as exc:
        raise OfficialOperationEvidenceError("official_operation_capture_receipt_not_publish_bound") from exc
    receipt = _load_json(receipt_file)
    if not isinstance(weekly, dict) or not isinstance(receipt, dict):
        raise OfficialOperationEvidenceError("official_operation_capture_source_shape_invalid")
    try:
        jsonschema.validate(weekly, _load_schema(WEEKLY_SCHEMA_PATH))
        m67_schema = _load_schema(M67_SCHEMA_PATH)
        for report in weekly["reports"]:
            jsonschema.validate(report, m67_schema)
            validate_m67_consistency(report)
    except (KeyError, jsonschema.ValidationError, ValueError) as exc:
        raise OfficialOperationEvidenceError("official_operation_capture_m67_consistency_invalid") from exc
    lineage = weekly.get("run_lineage") or {}
    if receipt.get("account_snapshot") != lineage.get("account_snapshot"):
        raise OfficialOperationEvidenceError("official_operation_capture_account_snapshot_mismatch")
    return weekly, receipt, output, receipt_file


def _source_identity(weekly: dict, output: Path, receipt_file: Path) -> dict:
    lineage = weekly["run_lineage"]
    account_snapshot = lineage.get("account_snapshot")
    account_digest = account_snapshot.get("snapshot_digest") if isinstance(account_snapshot, dict) else None
    runtime_configuration = copy.deepcopy(lineage.get("runtime_configuration") or {})
    if not isinstance(runtime_configuration, dict) or not all(
            isinstance(runtime_configuration.get(field), str) and runtime_configuration[field]
            for field in ("schema_name", "schema_version", "configuration_fingerprint")) or \
            not isinstance(runtime_configuration.get("policies"), list):
        raise OfficialOperationEvidenceError("official_operation_capture_runtime_configuration_unbound")
    if account_snapshot is not None and not isinstance(account_digest, str):
        raise OfficialOperationEvidenceError("official_operation_capture_account_snapshot_digest_unbound")
    return {
        "as_of": str(weekly["as_of"]),
        "run_id": str(lineage["run_id"]),
        "candidate_digest": str(lineage["candidate_digest"]),
        "official_m67_sha256": _file_digest(output),
        "official_receipt_sha256": _file_digest(receipt_file),
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


def _capture_record(weekly: dict, output: Path, receipt_file: Path) -> dict:
    as_of = _calendar_date(weekly.get("as_of"), "as_of")
    source = _source_identity(weekly, output, receipt_file)
    decisions = [_decision_from_report(weekly, source, report) for report in weekly["reports"]]
    if not decisions:
        portfolio_only = _portfolio_only_decision(weekly, source)
        if portfolio_only is not None:
            decisions.append(portfolio_only)
    record = {
        "schema_name": "a_short_official_operation_evidence_private_capture",
        "schema_version": "1.0.0",
        "record_type": "decision_capture",
        "program_id": PROGRAM_ID,
        "as_of": as_of,
        "source_identity": source,
        "decisions": decisions,
        "boundary": _boundary(),
    }
    record["capture_sha256"] = _digest(record)
    _validate_private_capture(record)
    return record


def _capture_path(root: Path, as_of: str) -> Path:
    return root / "weeks" / as_of / "capture.json"


def _write_conflict(root: Path, as_of: str, existing: dict, incoming: dict) -> None:
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
    _atomic_write(root / "conflicts" / f"{as_of}.json", conflict)


def capture_after_published_weekly(*, root: str | Path, out_path: str | Path, receipt_path: str | Path) -> dict:
    """Create one immutable capture from the published source; conflict never overwrites it."""
    private_root = _private_root(root)
    weekly, _receipt, output, receipt_file = _load_official_bundle(out_path=out_path, receipt_path=receipt_path)
    record = _capture_record(weekly, output, receipt_file)
    path = _capture_path(private_root, record["as_of"])
    if path.exists():
        existing = _load_json(path)
        _validate_private_capture(existing)
        if existing == record:
            return {"status": "idempotent_existing_capture", "decision_count": len(record["decisions"]),
                    "production_unchanged": True}
        _write_conflict(private_root, record["as_of"], existing, record)
        raise OfficialOperationEvidenceError("official_operation_capture_source_conflict")
    _atomic_write(path, record)
    return {"status": "captured", "decision_count": len(record["decisions"]), "production_unchanged": True}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Capture an already-published A-short M6.7 bundle as private evidence")
    parser.add_argument("capture", nargs="?", choices=["capture"], default="capture")
    parser.add_argument("--root", default=str(PRIVATE_ROOT_DEFAULT),
                        help="private root ending state/a_short/operation_evidence_private/v1")
    parser.add_argument("--weekly", required=True, help="official published weekly_m67.json")
    parser.add_argument("--receipt", required=True, help="matching official weekly_m67.receipt.json")
    args = parser.parse_args(argv)
    result = capture_after_published_weekly(root=args.root, out_path=args.weekly, receipt_path=args.receipt)
    print(f"[official-operation-evidence] capture={result['status']} decisions={result['decision_count']} "
          "(M6.7 unchanged; no outcome settlement)")


if __name__ == "__main__":
    main()
