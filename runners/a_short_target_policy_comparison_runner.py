#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 target-policy shadow accumulator.

The runner owns one private ledger (the frozen per-week plans) and one
de-identified public progress summary.  It has no provider client: execution
prices, when they are later materialised, are passed in as an existing cache.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema

from engine import a_short_evidence_epoch_mode as _epoch_mode
from engine.a_short_artifact_set_transaction import commit_artifact_set

from engine.a_short_managed_exit import CONTRACT_VERSION as EXIT_CONTRACT_VERSION
from engine.a_short_managed_exit import evaluate_managed_exit
from runners import a_short_phase5_engine as phase5_engine
from engine.a_short_experiment_admission_registry import admission_snapshot, get_admission
from engine.a_short_target_policy_adjudication import adjudicate_target_exit
from engine.a_short_run_revision import (
    require_official_revision, resolve_official_revision, validate_run_revision_id,
)


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_LEDGER_DEFAULT = ROOT / "logs" / "a_short_target_policy_comparison.json"
PUBLIC_SUMMARY_DEFAULT = ROOT / "research" / "results" / "a_short" / "target_policy_comparison_summary.json"
PUBLIC_MARKDOWN_DEFAULT = ROOT / "research" / "results" / "a_short" / "target_policy_comparison_summary.md"
#: Gitignored (`state/*/artifact_set_journal/`); rollback journal + old-byte backups only.
DEFAULT_ARTIFACT_SET_JOURNAL_DIR = ROOT / "state" / "a_short" / "artifact_set_journal" / "target_policy_comparison"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "a_short_target_policy_comparison_summary.schema.json"
LEDGER_SCHEMA_NAME = "a_short_target_policy_comparison_ledger"
SCHEMA_VERSION = "1.0.0"
ADMISSION_IDS = ("p2_target_exit_policy", "p2_breakout_entry_policy")
TRACK_ADMISSIONS = {"target_exit": "p2_target_exit_policy", "breakout_entry": "p2_breakout_entry_policy"}
_PRE_8B_PUBLIC_SUMMARY_FIELDS = frozenset({
    "verdict", "progress", "fingerprint", "source_hash", "target_exit_adjudication",
    "breakout_entry_reports", "breakout_entry_verdict",
})


class TargetPolicyError(ValueError):
    """The P2 sidecar cannot prove an immutable, isolated evidence state."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _public_json_bytes(payload: Any) -> bytes:
    """The exact bytes `_atomic_write` would have written, without writing them."""
    return (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_public_json_bytes(payload))
    os.replace(temporary, path)


def _date(value: object) -> str:
    text = str(value or "")
    if len(text) != 8 or not text.isdigit():
        raise TargetPolicyError("invalid_date")
    return text


def _private_path(path: str | Path) -> Path:
    result = Path(path).resolve()
    try:
        relative = result.relative_to(ROOT)
    except ValueError:
        return result
    try:
        ignored = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", "--", str(relative)],
            capture_output=True, text=True, check=False,
        ).returncode == 0
    except OSError as exc:
        raise TargetPolicyError("cannot_prove_private_ledger_is_gitignored") from exc
    if not ignored:
        raise TargetPolicyError("private_ledger_is_not_gitignored")
    return result


def _semantic_function_contract(function: object) -> dict[str, Any]:
    """Bind one project function's executable semantics, not its prose.

    P2 was the last comparison track whose contract hashed raw
    ``inspect.getsource`` text, so a comment or reformat inside a bound
    function opened a new epoch and silently dropped every accumulated week.
    Routing every leg through the shared AST helper in
    ``engine/a_short_evidence_epoch_mode`` makes the contract read the
    checked-in file (a runtime monkeypatch cannot forge it), strip docstrings,
    and fail closed on a rename instead of quietly shrinking the bound set.
    """
    module = inspect.getmodule(function)
    name = getattr(function, "__name__", "")
    if module is None or getattr(function, "__qualname__", "") != name:
        raise TargetPolicyError("non_bindable_semantic_function")
    return _epoch_mode.semantic_function_contract(module, {name})


def _semantic_local_functions(*names: str) -> dict[str, Any]:
    """Bind named functions of THIS module straight from the checked-in file.

    The direct surface legs name their functions rather than passing the live
    object, so a runtime monkeypatch cannot move (or forge) the contract; that
    anti-forgery property is the reason the shared helper reads the file. A
    real implementation change edits the file and does move it, which
    `tests/test_a_short_evidence_epoch_mode.py` asserts per leg.
    """
    return _epoch_mode.semantic_function_contract(sys.modules[__name__], set(names))


def _semantic_dependency_closure(*roots: object) -> dict[str, Any]:
    """Recursively freeze project functions and their referenced globals.

    A one-hop `getsource` list misses helpers such as `ma`, `tick_up`, and
    policy constants reached through an otherwise shared function.  This
    closure follows the actual Python global references of each supplied
    runtime root, records project-function source, and includes finite
    serializable global values (the frozen policy/constants).  Non-project
    modules and runtime objects are intentionally excluded.
    """
    closure: dict[str, Any] = {}
    seen: set[tuple[str, str]] = set()

    def visit(function: object) -> None:
        if not inspect.isfunction(function):
            return
        module = inspect.getmodule(function)
        module_name = getattr(module, "__name__", "")
        if not (module_name.startswith("engine.") or module_name.startswith("runners.")):
            return
        key = (module_name, function.__qualname__)
        if key in seen:
            return
        seen.add(key)
        source_key = f"{module_name}.{function.__qualname__}"
        closure[source_key] = {"semantics": _semantic_function_contract(function), "globals": {}}
        variables = inspect.getclosurevars(function)
        for name, value in sorted(variables.globals.items()):
            if inspect.isfunction(value):
                visit(value)
            elif isinstance(value, set):
                closure[source_key]["globals"][name] = sorted(value)
            elif value is None or isinstance(value, (bool, int, float, str, tuple, list, dict)):
                closure[source_key]["globals"][name] = value

    for root in roots:
        visit(root)
    return closure


def _shared_contract_surface() -> dict[str, Any]:
    cache_builder = __import__("runners.a_short_factor_comparison_v2_cache_build", fromlist=["*"])
    return {
        "target_contract": "1.0.0",
        "managed_exit_contract": EXIT_CONTRACT_VERSION,
        "semantic_closure": _semantic_dependency_closure(
            evaluate_managed_exit, _freeze_plan, phase5_engine._p2_shadow_context, _load_execution_cache,
        ),
        # Dispatch is shared; the two settlement implementations are frozen
        # in their respective component surfaces below so a target-only
        # settlement change cannot reopen the breakout epoch (or vice versa).
        "settlement_dispatch_semantics": _semantic_local_functions("_settle_existing_records"),
        # `_freeze_plan` dereferences this through the imported phase5 module;
        # module objects are deliberately not serialized by the closure.
        "phase5_atr_multiplier": phase5_engine.ATR_MULT,
        "shared_cache_loader_semantics": _semantic_local_functions("_load_execution_cache"),
        "shared_cache_builder_closure": _semantic_dependency_closure(cache_builder.materialize_incremental_cache),
        "cost_and_priority": "t1_half_then_trailing;stop_before_t1;round_trip_cost_0.16pp",
    }


def _target_contract_surface() -> dict[str, Any]:
    return {
        "semantic_closure": _semantic_dependency_closure(
            _target_entry, phase5_engine.build_p2_target_ladder, _settle_target_records,
        ),
    }


def _breakout_contract_surface() -> dict[str, Any]:
    return {
        "semantic_closure": _semantic_dependency_closure(
            _breakout_entry, phase5_engine.build_p2_breakout_qualification, _settle_breakout_records,
        ),
    }


def _contract_fingerprint(track: str | None = None) -> str:
    """Pre-freeze returns a stable per-track constant; see ``engine/a_short_evidence_epoch_mode``."""
    if track is not None and track not in TRACK_ADMISSIONS:
        raise TargetPolicyError("unknown_p2_component")
    packet_identity = _epoch_mode.validated_frozen_packet_identity(
        "p2_target_policy"
    )
    if packet_identity is None:
        # Keep the two P2 components in separate epochs even while constant.
        return _epoch_mode.pre_freeze_fingerprint("p2_target_policy") if track is None else _digest(
            {"pre_freeze": _epoch_mode.pre_freeze_fingerprint("p2_target_policy"), "component_id": track})
    return _epoch_mode.bind_frozen_fingerprint(
        "p2_target_policy", _real_contract_fingerprint(track), packet_identity
    )


def _real_contract_fingerprint(track: str | None = None) -> str:
    contract = _shared_contract_surface()
    if track is None:
        return _digest({**contract, "admission_bindings": admission_snapshot(*ADMISSION_IDS)})
    if track not in TRACK_ADMISSIONS:
        raise TargetPolicyError("unknown_p2_component")
    component_surface = _target_contract_surface() if track == "target_exit" else _breakout_contract_surface()
    return _digest({**contract, "component_surface": component_surface, "component_id": track,
                    "admission_binding": admission_snapshot(TRACK_ADMISSIONS[track])})


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _without_outcomes(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_outcomes(item) for key, item in value.items() if key != "outcomes"}
    if isinstance(value, list):
        return [_without_outcomes(item) for item in value]
    return value


def _capture_digest(record: dict[str, Any]) -> str:
    return _digest(_without_outcomes({key: value for key, value in record.items() if key != "capture_sha256"}))


def _validate_current_record(record: dict[str, Any], epoch: dict[str, Any]) -> None:
    track = epoch["component_id"]
    entry_key, difference_key = ("target_entries", "target_difference") if track == "target_exit" else \
        ("breakout_entries", "breakout_difference")
    required = {"decision_date", "forward_eligible", "source_identity", "component_id", "admission_binding",
                "component_epoch_fingerprint", "capture_sha256", entry_key, difference_key}
    if not isinstance(record, dict) or not required.issubset(record) or set(record) - required != {"run_revision_id"} and set(record) - required or record["component_id"] != track or \
            record["admission_binding"] != epoch["admission_binding"] or \
            record["component_epoch_fingerprint"] != epoch["contract_fingerprint"] or \
            not isinstance(record["forward_eligible"], bool) or not isinstance(record[entry_key], list) or \
            not isinstance(record[difference_key], bool) or _date(record["decision_date"]) != record["decision_date"]:
        raise TargetPolicyError("private_current_record_binding_invalid")
    if record.get("run_revision_id") is not None:
        validate_run_revision_id(record["run_revision_id"])
    source = record["source_identity"]
    source_allowed = {"run_id", "candidate_digest", "official_m67_sha256", "price_data_through", "run_revision_id"}
    if not isinstance(source, dict) or not source_allowed.issuperset(source) or \
            set(source) - source_allowed - ({"run_revision_id"} if "run_revision_id" in source else set()) or \
            not isinstance(source["run_id"], str) or not source["run_id"] or \
            not _is_sha256(source["candidate_digest"]) or not _is_sha256(source["official_m67_sha256"]) or \
            _date(source["price_data_through"]) != source["price_data_through"] or \
            source.get("run_revision_id") != record.get("run_revision_id") or \
            record["capture_sha256"] != _capture_digest(record):
        raise TargetPolicyError("private_current_record_capture_integrity_invalid")


def _new_ledger() -> dict[str, Any]:
    return {
        "schema_name": LEDGER_SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "epochs": [],
        "review_status": {"target_exit": "not_reviewed", "breakout_entry": "not_reviewed"},
        "review_status_by_epoch": {"target_exit": {}, "breakout_entry": {}},
        "boundary": {"production": False, "automatic_policy_switch": False},
    }


def _validate_ledger(ledger: dict[str, Any]) -> None:
    if not isinstance(ledger, dict) or ledger.get("schema_name") != LEDGER_SCHEMA_NAME or \
            ledger.get("schema_version") != SCHEMA_VERSION or \
            ledger.get("boundary") != {"production": False, "automatic_policy_switch": False}:
        raise TargetPolicyError("private_ledger_contract_invalid")
    if not isinstance(ledger.get("epochs"), list) or not isinstance(ledger.get("review_status"), dict):
        raise TargetPolicyError("private_ledger_contract_invalid")
    if set(ledger["review_status"]) != {"target_exit", "breakout_entry"} or \
            any(value not in {"not_reviewed", "pass"} for value in ledger["review_status"].values()):
        raise TargetPolicyError("private_review_status_invalid")
    epoch_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for epoch in ledger["epochs"]:
        legacy_keys = {"epoch_id", "contract_fingerprint", "records"}
        current_keys = legacy_keys | {"component_id", "admission_binding"}
        if not isinstance(epoch, dict) or set(epoch) not in (legacy_keys, current_keys) or \
                not isinstance(epoch["records"], list) or epoch["epoch_id"] != epoch["contract_fingerprint"]:
            raise TargetPolicyError("private_epoch_invalid")
        if "component_id" in epoch and epoch["component_id"] not in TRACK_ADMISSIONS:
            raise TargetPolicyError("private_epoch_admission_binding_drifted")
        if "component_id" in epoch and _epoch_mode.enforcement_enabled("p2_target_policy") and \
                epoch["admission_binding"] != admission_snapshot(TRACK_ADMISSIONS[epoch["component_id"]]):
            raise TargetPolicyError("private_epoch_admission_binding_drifted")
        identities = [(record.get("decision_date"), record.get("run_revision_id"))
                      for record in epoch["records"] if isinstance(record, dict)]
        if len(identities) != len(epoch["records"]) or len(set(identities)) != len(identities):
            raise TargetPolicyError("private_record_identity_invalid")
        if "component_id" in epoch:
            for record in epoch["records"]:
                _validate_current_record(record, epoch)
        if "component_id" in epoch:
            epoch_by_key[(epoch["component_id"], epoch["epoch_id"])] = epoch
    epoch_status = ledger.get("review_status_by_epoch")
    if epoch_status is None:
        if any("component_id" in epoch for epoch in ledger["epochs"]):
            raise TargetPolicyError("private_current_epoch_review_state_missing")
        return
    if not isinstance(epoch_status, dict) or set(epoch_status) != set(TRACK_ADMISSIONS) or \
            any(not isinstance(values, dict) for values in epoch_status.values()):
        raise TargetPolicyError("private_epoch_review_status_invalid")
    for track, statuses in epoch_status.items():
        for epoch_id, status in statuses.items():
            epoch = epoch_by_key.get((track, epoch_id))
            if not isinstance(epoch, dict) or epoch.get("component_id") != track or \
                    status not in {"not_reviewed", "pass"}:
                raise TargetPolicyError("private_epoch_review_status_invalid")


def _load_or_initialize(path: str | Path) -> tuple[Path, dict[str, Any]]:
    private_path = _private_path(path)
    if not private_path.exists():
        return private_path, _new_ledger()
    try:
        ledger = json.loads(private_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TargetPolicyError("private_ledger_unreadable") from exc
    _validate_ledger(ledger)
    return private_path, ledger


def _active_epoch(ledger: dict[str, Any], *, create: bool, track: str = "target_exit") -> dict[str, Any] | None:
    if track not in TRACK_ADMISSIONS:
        raise TargetPolicyError("unknown_p2_component")
    fingerprint = _contract_fingerprint(track)
    for epoch in ledger["epochs"]:
        if epoch.get("component_id") == track and epoch["contract_fingerprint"] == fingerprint:
            return epoch
    if not create:
        return None
    epoch = {"epoch_id": fingerprint, "contract_fingerprint": fingerprint, "component_id": track,
             "admission_binding": admission_snapshot(TRACK_ADMISSIONS[track]), "records": []}
    ledger["epochs"].append(epoch)
    statuses = ledger.setdefault("review_status_by_epoch", {"target_exit": {}, "breakout_entry": {}})
    if not isinstance(statuses, dict) or set(statuses) != set(TRACK_ADMISSIONS):
        raise TargetPolicyError("private_epoch_review_status_invalid")
    statuses[track][epoch["epoch_id"]] = "not_reviewed"
    return epoch


def _current_review_status(ledger: dict[str, Any], track: str, epoch: dict[str, Any] | None) -> str:
    # Pre-freeze evidence is audit-only and can never reach a review point.
    if epoch is None or not _epoch_mode.evidence_counts_toward_clock("p2_target_policy"):
        return "not_reviewed"
    statuses = ledger.get("review_status_by_epoch") or {}
    return str((statuses.get(track) or {}).get(epoch["epoch_id"], "not_reviewed"))


def _empty_progress(review_status: str) -> dict[str, Any]:
    return {
        "forward_weeks": 0,
        "required_forward_weeks": 12,
        "decision_difference_weeks": 0,
        "required_decision_difference_weeks": 8,
        "evaluable_plans": 0,
        "required_evaluable_plans": 20,
        "review_state": "pass_pending_confirmation" if review_status == "pass" else "not_due",
    }


def _progress(records: list[dict[str, Any]], track: str, review_status: str) -> dict[str, Any]:
    progress = _empty_progress(review_status)
    forward = [record for record in records if record.get("forward_eligible") is True]
    progress["forward_weeks"] = len(forward)
    if track == "target_exit":
        different = [record for record in forward if record.get("target_difference") is True]
        settled = [item for record in forward for item in (record.get("target_entries") or [])
                   if item.get("changed") is True and
                   ((item.get("outcomes") or {}).get("status") == "settled")]
    else:
        different = [record for record in forward if record.get("breakout_difference") is True]
        settled = [item for record in forward for item in (record.get("breakout_entries") or [])
                   if item.get("changed") is True and
                   ((item.get("outcomes") or {}).get("status") == "settled")]
    progress["decision_difference_weeks"] = len(different)
    progress["evaluable_plans"] = len(settled)
    enough = progress["forward_weeks"] >= 12 and progress["decision_difference_weeks"] >= 8 and \
        progress["evaluable_plans"] >= 20
    if review_status == "pass":
        progress["review_state"] = "pass_pending_confirmation"
    elif enough and _epoch_mode.evidence_counts_toward_clock("p2_target_policy"):
        progress["review_state"] = "due"
    return progress


def _message(status: str, target: dict[str, Any], breakout: dict[str, Any]) -> str:
    if status == "not_configured":
        return "P2 目标策略：未配置；不读取或写入影子证据，正式 M6.7 不变。"
    if status == "evidence_unavailable_or_inconclusive":
        return "P2 目标策略：当前证据不可用或校验失败；不复用旧提醒，正式 M6.7 不变。"
    if status == "review_due":
        due = []
        if target["review_state"] == "due":
            due.append("P2 目标退出审查")
        if breakout["review_state"] == "due":
            due.append("独立突破入场审查")
        return "P2 目标策略：数据已够，请执行" + "、".join(due) + "；不自动切换生产。"
    if status == "review_pass_pending_confirmation":
        return "P2 目标策略：审查已 PASS，等待独立复审和用户确认；不自动切换生产。"
    return (
        "P2 目标策略：累计中；目标退出 "
        f"{target['forward_weeks']}/12 周、差异 {target['decision_difference_weeks']}/8 周、"
        f"计划 {target['evaluable_plans']}/20；突破轨 {breakout['forward_weeks']}/12 周、"
        f"差异 {breakout['decision_difference_weeks']}/8 周、受影响计划 {breakout['evaluable_plans']}/20。"
    )


def _summary_from_ledger(ledger: dict[str, Any], as_of: str,
                         official_revision_id: str | None = None,
                         official_project_root: str | Path | None = None) -> dict[str, Any]:
    target_epoch = _active_epoch(ledger, create=False, track="target_exit")
    breakout_epoch = _active_epoch(ledger, create=False, track="breakout_entry")
    target_records = list(target_epoch["records"]) if target_epoch else []
    breakout_records = list(breakout_epoch["records"]) if breakout_epoch else []
    if official_project_root is not None:
        target_records = [
            row for row in target_records
            if row.get("run_revision_id") not in (None, "") and
            (lambda selected: selected is not None and
             selected["selected_revision_id"] == row.get("run_revision_id"))(
                 resolve_official_revision(official_project_root, row["decision_date"], require=False)
             )
        ]
        breakout_records = [
            row for row in breakout_records
            if row.get("run_revision_id") not in (None, "") and
            (lambda selected: selected is not None and
             selected["selected_revision_id"] == row.get("run_revision_id"))(
                 resolve_official_revision(official_project_root, row["decision_date"], require=False)
             )
        ]
    elif official_revision_id is not None:
        target_records = [row for row in target_records if row.get("run_revision_id") == official_revision_id]
        breakout_records = [row for row in breakout_records if row.get("run_revision_id") == official_revision_id]
    target = _progress(target_records, "target_exit", _current_review_status(ledger, "target_exit", target_epoch))
    breakout = _progress(breakout_records, "breakout_entry", _current_review_status(ledger, "breakout_entry", breakout_epoch))
    if target["review_state"] == "pass_pending_confirmation" or breakout["review_state"] == "pass_pending_confirmation":
        status = "review_pass_pending_confirmation"
    elif target["review_state"] == "due" or breakout["review_state"] == "due":
        status = "review_due"
    else:
        status = "accumulating"
    records = [*target_records, *breakout_records]
    data_through = max((record["decision_date"] for record in records), default=None)
    execution_available = any(
        (item.get("outcomes") or {}).get("status") == "settled"
        for record in records
        for collection in (record.get("target_entries") or [], record.get("breakout_entries") or [])
        for item in collection
    )
    target_adjudication = adjudicate_target_exit(
        target_records,
        get_admission("p2_target_exit_policy")["statistical_contract"]["definition"],
        evidence_counts=_epoch_mode.evidence_counts_toward_clock("p2_target_policy"),
    )
    breakout_reports = {
        "new_old_entry_week_portfolios": [], "excluded_vs_csi1000": [],
        "missed_large_moves": [], "risk_outcomes": [],
    }
    source_hash = _digest([
        {"decision_date": row.get("decision_date"), "source_identity": row.get("source_identity"),
         "capture_sha256": row.get("capture_sha256")}
        for row in target_records
    ])
    summary = {
        "schema_name": "a_short_target_policy_comparison_summary",
        "schema_version": SCHEMA_VERSION,
        "summary_id": "a_short_target_policy_comparison",
        "as_of": as_of,
        "official_revision_id": official_revision_id,
        "data_through": data_through,
        "status": status,
        "target_exit": target,
        "breakout_entry": breakout,
        "execution_data_status": "available" if execution_available else "unavailable",
        "verdict": target_adjudication["verdict"],
        "progress": target_adjudication["progress"],
        "fingerprint": _digest({"admission": admission_snapshot("p2_target_exit_policy"),
                                 "records": [{"decision_date": row.get("decision_date"),
                                              "capture_sha256": row.get("capture_sha256")}
                                             for row in target_records]}),
        "source_hash": source_hash,
        "target_exit_adjudication": target_adjudication,
        "breakout_entry_reports": breakout_reports,
        "breakout_entry_verdict": "not_adjudicated",
        "admissions": admission_snapshot(*ADMISSION_IDS),
        "message": _message(status, target, breakout),
        "production_unchanged": True,
    }
    validate_public_summary(summary)
    return summary


def _unavailable_summary(as_of: str, *, configured: bool,
                         official_revision_id: str | None = None) -> dict[str, Any]:
    target = _empty_progress("not_reviewed")
    breakout = _empty_progress("not_reviewed")
    status = "evidence_unavailable_or_inconclusive" if configured else "not_configured"
    return {
        "schema_name": "a_short_target_policy_comparison_summary",
        "schema_version": SCHEMA_VERSION,
        "summary_id": "a_short_target_policy_comparison",
        "as_of": _date(as_of),
        "official_revision_id": official_revision_id,
        "data_through": None,
        "status": status,
        "target_exit": target,
        "breakout_entry": breakout,
        "execution_data_status": "unavailable",
        "verdict": "not_adjudicated",
        "progress": {"forward_weeks": 0, "difference_weeks": 0, "evaluable_plans": 0, "evaluable_weeks": 0},
        "fingerprint": _digest({"admission": admission_snapshot("p2_target_exit_policy"), "records": []}),
        "source_hash": _digest([]),
        "target_exit_adjudication": {"verdict": "not_adjudicated", "progress": {"forward_weeks": 0, "difference_weeks": 0, "evaluable_plans": 0, "evaluable_weeks": 0}, "metrics": {"mean_net_improvement_pp": None, "weekly_median_net_improvement_pp": None, "favorable_week_ratio": None, "max_drawdown_worsening_pp": None, "h5_mean_delta_pp": None, "h10_mean_delta_pp": None}, "reason": "evidence_unavailable", "comparison_only": True},
        "breakout_entry_reports": {"new_old_entry_week_portfolios": [], "excluded_vs_csi1000": [], "missed_large_moves": [], "risk_outcomes": []},
        "breakout_entry_verdict": "not_adjudicated",
        "admissions": admission_snapshot(*ADMISSION_IDS),
        "message": _message(status, target, breakout),
        "production_unchanged": True,
    }


def unavailable_public_summary(as_of: str) -> dict[str, Any]:
    """Return the current, non-stale P2 failure reminder for a weekly consumer."""
    return _unavailable_summary(as_of, configured=True)


def validate_public_summary(summary: dict[str, Any]) -> None:
    try:
        schema = json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(summary, schema)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise TargetPolicyError("public_summary_contract_invalid") from exc
    target, breakout = summary["target_exit"], summary["breakout_entry"]
    status = summary["status"]
    if summary["message"] != _message(status, target, breakout):
        raise TargetPolicyError("public_summary_message_drifted")
    if status != "review_due" and (target["review_state"] == "due" or breakout["review_state"] == "due"):
        raise TargetPolicyError("public_summary_review_state_drifted")
    if status == "review_due" and not (target["review_state"] == "due" or breakout["review_state"] == "due"):
        raise TargetPolicyError("public_summary_review_state_drifted")
    if summary.get("admissions") != admission_snapshot(*ADMISSION_IDS):
        raise TargetPolicyError("public_summary_admission_binding_drifted")
    adjudication = summary.get("target_exit_adjudication") or {}
    if adjudication.get("verdict") != summary.get("verdict") or adjudication.get("progress") != summary.get("progress"):
        raise TargetPolicyError("public_summary_adjudication_binding_drifted")


def _render_summary_markdown(summary: dict[str, Any]) -> str:
    target, breakout = summary["target_exit"], summary["breakout_entry"]
    return "\n".join([
        "# A-short P2 target-policy comparison",
        "",
        f"- as_of: {summary['as_of']}",
        f"- data_through: {summary['data_through'] or '无'}",
        f"- 状态: {summary['status']}",
        f"- {summary['message']}",
        "",
        "| 轨道 | forward 周 | 差异周 | 可评价计划 | 审查状态 |",
        "|---|---:|---:|---:|---|",
        f"| 目标退出 | {target['forward_weeks']}/12 | {target['decision_difference_weeks']}/8 | "
        f"{target['evaluable_plans']}/20 | {target['review_state']} |",
        f"| 突破入场 | {breakout['forward_weeks']}/12 | {breakout['decision_difference_weeks']}/8 | "
        f"{breakout['evaluable_plans']}/20 | {breakout['review_state']} |",
        "",
        "> 只显示脱敏进度；不读取逐股私有账本，不改变正式 M6.7。",
        "",
    ])


def _assert_public_summary_as_of_monotonic(summary: dict[str, Any], summary_path: Path) -> None:
    """Never replace a tracked public summary with an older point-in-time view."""
    if not summary_path.is_file():
        return
    try:
        existing = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            raise TargetPolicyError("existing_public_summary_unreadable")
        existing_as_of = _date(existing.get("as_of"))
        new_as_of = _date(summary.get("as_of"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, TargetPolicyError) as exc:
        raise TargetPolicyError("existing_public_summary_unreadable") from exc
    if existing_as_of > new_as_of:
        raise TargetPolicyError("public_summary_as_of_regressed")
    try:
        validate_public_summary(existing)
    except TargetPolicyError as exc:
        legacy_identity = {
            "schema_name": "a_short_target_policy_comparison_summary",
            "schema_version": SCHEMA_VERSION,
            "summary_id": "a_short_target_policy_comparison",
        }
        if (all(existing.get(key) == value for key, value in legacy_identity.items()) and
                all(key not in existing for key in _PRE_8B_PUBLIC_SUMMARY_FIELDS)):
            return
        raise TargetPolicyError("existing_public_summary_unreadable") from exc


def prepare_public_artifact_set(summary: dict[str, Any], *, summary_path: str | Path,
                                markdown_path: str | Path) -> dict[Path, bytes]:
    """Validate and render the whole public pair, writing nothing."""
    validate_public_summary(summary)
    target_path = Path(summary_path)
    _assert_public_summary_as_of_monotonic(summary, target_path)
    return {
        target_path: _public_json_bytes(summary),
        Path(markdown_path): _render_summary_markdown(summary).encode("utf-8"),
    }


def commit_public_artifact_set(files: dict[Path, bytes], *,
                               journal_dir: str | Path | None = None) -> None:
    """The one write entry point for the public pair: both files or neither."""
    commit_artifact_set(journal_dir or DEFAULT_ARTIFACT_SET_JOURNAL_DIR, files)


def write_public_summary(summary: dict[str, Any], *, summary_path: str | Path,
                         markdown_path: str | Path,
                         journal_dir: str | Path | None = None) -> None:
    """Compatibility facade for the standalone runner: prepare then commit."""
    commit_public_artifact_set(
        prepare_public_artifact_set(summary, summary_path=summary_path, markdown_path=markdown_path),
        journal_dir=journal_dir)


def settle_and_summarize(*, root: str | Path | None, as_of: str,
                          daily_cache_path: str | Path | None = None,
                          summary_path: str | Path | None = None,
                          markdown_path: str | Path | None = None,
                          write_public: bool = True,
                          run_revision_id: str | None = None,
                          official_project_root: str | Path | None = None) -> dict[str, Any]:
    """Settle only existing captures, then return the current de-identified P2 reminder.

    ``write_public=False`` is the weekly-pipeline path: it needs the summary for
    the in-report banner before the official bundle exists, and the published
    pair may only move after that bundle and the private capture have landed.
    """
    if root is None:
        return _unavailable_summary(as_of, configured=False)
    try:
        if run_revision_id is not None:
            run_revision_id = validate_run_revision_id(run_revision_id)
        official_revision_id = None
        if official_project_root is not None and run_revision_id is None:
            raise TargetPolicyError("official settlement requires run_revision_id")
        if official_project_root is not None and run_revision_id is not None:
            official_revision_id = require_official_revision(
                official_project_root, _date(as_of), run_revision_id
            )
        private_path, ledger = _load_or_initialize(root)
        if daily_cache_path is not None and Path(daily_cache_path).is_file():
            for track in TRACK_ADMISSIONS:
                epoch = _active_epoch(ledger, create=True, track=track)
                if official_project_root is not None:
                    selected_records = []
                    for record in epoch["records"]:
                        record_revision = record.get("run_revision_id")
                        if record_revision in (None, ""):
                            continue
                        selected = resolve_official_revision(
                            official_project_root, record["decision_date"], require=False,
                        )
                        if selected is not None and selected["selected_revision_id"] == record_revision:
                            selected_records.append(record)
                else:
                    selected_records = [record for record in epoch["records"]
                                        if run_revision_id is None or record.get("run_revision_id") == run_revision_id]
                _settle_existing_records(selected_records, Path(daily_cache_path), track=track)
        _validate_ledger(ledger)
        _atomic_write(private_path, ledger)
        summary = _summary_from_ledger(
            ledger, _date(as_of), official_revision_id=official_revision_id,
            official_project_root=official_project_root,
        )
        if (summary_path is None) != (markdown_path is None):
            raise TargetPolicyError("public_summary_paths_must_be_paired")
        if summary_path is not None and write_public:
            write_public_summary(summary, summary_path=summary_path, markdown_path=markdown_path)
        return summary
    except Exception:
        # The weekly seam must never repeat old review_due text if this sidecar
        # is corrupt or unavailable.  The caller keeps M6.7 authoritative, and
        # the published pair stays at its last checked state.
        return _unavailable_summary(as_of, configured=True)


def _freeze_plan(plan: dict[str, Any], series: list[dict], decision_date: str, regime: str,
                 *, t1: float | None, t2: float | None) -> dict[str, Any]:
    reference = series[-1]
    return {
        "decision_date": decision_date,
        "entry_low": plan["entry_low"],
        "entry_high": plan["entry_high"],
        "stop": plan["stop"],
        "t1": t1,
        "t2": t2,
        "atr_multiplier": phase5_engine.ATR_MULT.get(regime, 1.25),
        "price_basis": "qfq",
        "reference_trade_date": reference["trade_date"],
        "reference_close": reference["close"],
    }


def _target_entry(candidate: dict[str, Any], official_plan: dict | None, price_data_through: str,
                  decision_date: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
    """Execute only the target-exit policy component for this frozen candidate."""
    ladder = phase5_engine.build_p2_target_ladder(candidate, official_plan, price_data_through)
    if not isinstance(official_plan, dict):
        return None, None, ladder
    series = candidate.get("price_series") or []
    regime = str(candidate.get("market_regime") or "")
    baseline = _freeze_plan(official_plan, series, decision_date, regime,
                            t1=official_plan.get("t1"), t2=official_plan.get("t2"))
    if ladder["status"] not in {"available", "trailing_only"} or ladder.get("rr_eligible") is not True:
        return baseline, None, ladder
    t1 = ladder["t1"]["price"] if ladder.get("t1") else None
    t2 = ladder["t2"]["price"] if ladder.get("t2") else None
    challenger = _freeze_plan(official_plan, series, decision_date, regime, t1=t1, t2=t2)
    return baseline, challenger, ladder


def _breakout_entry(candidate: dict[str, Any], official_plan: dict | None, price_data_through: str,
                    decision_date: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Execute only the breakout-entry policy component for this frozen candidate."""
    qualification = phase5_engine.build_p2_breakout_qualification(candidate, price_data_through)
    if not isinstance(official_plan, dict):
        return None, qualification
    series = candidate.get("price_series") or []
    baseline = _freeze_plan(official_plan, series, decision_date, str(candidate.get("market_regime") or ""),
                            t1=official_plan.get("t1"), t2=official_plan.get("t2"))
    return baseline, qualification


def _verify_published_bundle(out_path: str | Path, receipt_path: str | Path, decision_date: str,
                             source_identity: dict[str, Any]):
    try:
        from runners.a_short_weekly_pipeline import validate_published_weekly_bundle
        bundle = validate_published_weekly_bundle(out_path, receipt_path)
    except (OSError, ValueError) as exc:
        raise TargetPolicyError("published_bundle_unreadable") from exc
    weekly, receipt = bundle.weekly, bundle.receipt
    lineage = weekly.get("run_lineage") or {}
    if str(weekly.get("as_of")) != str(decision_date) or lineage.get("run_id") != source_identity.get("run_id") or \
            receipt.get("run_id") != lineage.get("run_id") or receipt.get("candidate_digest") != lineage.get("candidate_digest") or \
            receipt.get("candidate_digest") != source_identity.get("candidate_digest"):
        raise TargetPolicyError("published_bundle_binding_invalid")
    return bundle


def capture_after_published_weekly(*, root: str | Path, decision_date: str, candidates: list[dict],
                                   source_identity: dict[str, Any], out_path: str | Path, receipt_path: str | Path,
                                   forward_eligible: bool,
                                   summary_path: str | Path | None = None,
                                   markdown_path: str | Path | None = None,
                                   run_revision_id: str | None = None) -> dict[str, Any]:
    """Freeze P2 target/breakout deltas only after the official bundle exists."""
    decision_date = _date(decision_date)
    if run_revision_id is not None:
        run_revision_id = validate_run_revision_id(run_revision_id)
    private_path, ledger = _load_or_initialize(root)
    weekly_bundle = _verify_published_bundle(
        out_path, receipt_path, decision_date, source_identity
    )
    weekly = weekly_bundle.weekly
    price_data_through = str(((weekly.get("run_lineage") or {}).get("price_freshness") or {}).get("price_data_through") or "")
    _date(price_data_through)
    if forward_eligible:
        freshness = (weekly.get("run_lineage") or {}).get("price_freshness") or {}
        if freshness.get("mode") != "intraday_prior_settled" or not freshness.get("run_date"):
            raise TargetPolicyError("forward_capture_requires_live_price_freshness")
    reports = {str(row.get("ts_code")): row for row in (weekly.get("reports") or []) if isinstance(row, dict)}
    entries, breakout_entries = [], []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not candidate.get("ts_code"):
            continue
        code = str(candidate["ts_code"])
        try:
            report = reports.get(code)
            official_plan = (((report or {}).get("machine") or {}).get("entry_exit_size_star") or {}).get("plan")
            baseline, challenger, ladder = _target_entry(candidate, official_plan, price_data_through, decision_date)
            breakout_baseline, qualification = _breakout_entry(candidate, official_plan, price_data_through,
                                                                decision_date)
        except Exception:
            # A malformed shadow-only candidate must become its own no-count
            # row.  It cannot discard all other same-week P2 evidence or
            # affect the already-published M6.7 bundle.
            official_plan = None
            baseline, challenger = None, None
            breakout_baseline = None
            ladder = {
                "status": "unavailable",
                "reason": "candidate_input_invalid",
            }
            qualification = {"momentum_confirmed": False, "true_breakout": False}
        changed = bool(baseline is not None and challenger is not None and baseline["t1"] != challenger["t1"])
        entries.append({
            "ts_code": code,
            "target_status": ladder["status"],
            "target_reason": ladder.get("reason"),
            "baseline_t1_basis": (
                str(official_plan.get("t1_basis"))
                if isinstance(official_plan, dict) and official_plan.get("t1_basis") in
                {"structural_resistance", "rr_floor_fallback"}
                else "unspecified_legacy"
            ),
            "baseline": baseline,
            "challenger": challenger,
            "changed": changed,
            "ladder": ladder,
            "outcomes": None,
        })
        old_momentum = bool(qualification["momentum_confirmed"])
        new_true_breakout = bool(qualification["true_breakout"])
        breakout_entries.append({"ts_code": code, "old_momentum_confirmed": old_momentum,
                                 "true_breakout": new_true_breakout,
                                 "changed": old_momentum != new_true_breakout,
                                 # Breakout evidence isolates the entry qualification:
                                 # whichever side is ineligible is cash at 0% through H20;
                                 # the eligible side uses the same frozen official exit plan.
                                 # It must not depend on whether the target challenger differs.
                                 "entry_plan": breakout_baseline,
                                 "outcomes": None})
    record_base = {
        "decision_date": decision_date,
        "run_revision_id": run_revision_id,
        "forward_eligible": bool(forward_eligible),
        "source_identity": {"run_id": str(source_identity["run_id"]),
                            "candidate_digest": str(source_identity["candidate_digest"]),
                            "official_m67_sha256": weekly_bundle.weekly_sha256,
                            "price_data_through": price_data_through,
                            "run_revision_id": run_revision_id},
    }
    records: dict[str, dict[str, Any]] = {}
    idempotent = True
    for track, admission_id in TRACK_ADMISSIONS.items():
        record = json.loads(json.dumps(record_base))
        if track == "target_exit":
            record["target_entries"] = entries
            record["target_difference"] = any(entry["changed"] for entry in entries)
        else:
            record["breakout_entries"] = breakout_entries
            record["breakout_difference"] = any(entry["changed"] for entry in breakout_entries)
        record["component_id"] = track
        record["admission_binding"] = admission_snapshot(admission_id)
        record["component_epoch_fingerprint"] = _contract_fingerprint(track)
        record["capture_sha256"] = _capture_digest(record)
        epoch = _active_epoch(ledger, create=True, track=track)
        existing = next((item for item in epoch["records"]
                         if item["decision_date"] == decision_date and
                         item.get("run_revision_id") == run_revision_id), None)
        if existing is not None:
            if existing.get("capture_sha256") != record["capture_sha256"]:
                if run_revision_id is not None:
                    _atomic_write(
                        private_path.parent / "weeks" / decision_date / "revisions" / run_revision_id / "conflict.json",
                        {"schema_name": "a_short_target_policy_comparison_conflict",
                         "decision_date": decision_date, "run_revision_id": run_revision_id,
                         "reason": "p2_capture_replay_input_drifted"},
                    )
                raise TargetPolicyError("p2_capture_replay_input_drifted")
            records[track] = existing
            continue
        idempotent = False
        epoch["records"].append(record)
        epoch["records"].sort(key=lambda item: (item["decision_date"], item.get("run_revision_id") or "legacy_revision_0"))
        records[track] = record
    _validate_ledger(ledger)
    if not idempotent:
        _atomic_write(private_path, ledger)
        if run_revision_id is not None:
            revision_root = (private_path.parent / "weeks" / decision_date / "revisions" / run_revision_id)
            revision_root.mkdir(parents=True, exist_ok=True)
            for track, record in records.items():
                _atomic_write(revision_root / f"{track}.json", record)
        summary = _summary_from_ledger(ledger, decision_date)
        if (summary_path is None) != (markdown_path is None):
            raise TargetPolicyError("public_summary_paths_must_be_paired")
        if summary_path is not None:
            write_public_summary(summary, summary_path=summary_path, markdown_path=markdown_path)
    return {"status": "idempotent" if idempotent else "captured", "record": records["target_exit"]}


def _load_execution_cache(path: Path) -> dict[str, list[dict[str, Any]]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TargetPolicyError("execution_cache_unreadable") from exc
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise TargetPolicyError("execution_cache_contract_invalid")
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("ts_code"):
            raise TargetPolicyError("execution_cache_contract_invalid")
        by_code.setdefault(str(row["ts_code"]), []).append({key: value for key, value in row.items() if key != "ts_code"})
    return by_code


def _settle_target_records(records: list[dict[str, Any]], by_code: dict[str, list[dict[str, Any]]]) -> None:
    for record in records:
        for entry in record.get("target_entries") or []:
            if entry.get("changed") is not True:
                continue
            baseline, challenger = entry.get("baseline"), entry.get("challenger")
            if not isinstance(baseline, dict) or not isinstance(challenger, dict):
                continue
            rows = by_code.get(str(entry.get("ts_code")))
            if not rows:
                continue
            old = evaluate_managed_exit(baseline, rows)
            new = evaluate_managed_exit(challenger, rows)
            if old["status"] == "settled" and new["status"] == "settled":
                entry["outcomes"] = {"status": "settled", "baseline": old, "challenger": new,
                                     "net_delta_pct": round(new["net_return_pct"] - old["net_return_pct"], 8)}
            elif old["reason"] == "price_basis_mismatch" or new["reason"] == "price_basis_mismatch":
                entry["outcomes"] = {"status": "no_count", "reason": "price_basis_mismatch"}
            else:
                entry["outcomes"] = {"status": "pending", "baseline_status": old["status"],
                                     "challenger_status": new["status"]}


def _settle_breakout_records(records: list[dict[str, Any]], by_code: dict[str, list[dict[str, Any]]]) -> None:
    for record in records:
        for breakout in record.get("breakout_entries") or []:
            if breakout.get("changed") is not True:
                continue
            plan = breakout.get("entry_plan")
            rows = by_code.get(str(breakout.get("ts_code")))
            if not isinstance(plan, dict) or not rows:
                continue
            managed = evaluate_managed_exit(plan, rows)
            if managed["status"] == "settled":
                managed_return = managed["net_return_pct"]
                old_eligible = bool(breakout.get("old_momentum_confirmed"))
                new_eligible = bool(breakout.get("true_breakout"))
                breakout["outcomes"] = {
                    "status": "settled",
                    "old_entry_eligible": old_eligible,
                    "new_entry_eligible": new_eligible,
                    "old_h20_net_return_pct": managed_return if old_eligible else 0.0,
                    "new_h20_net_return_pct": managed_return if new_eligible else 0.0,
                    "managed_exit": managed,
                }
            else:
                breakout["outcomes"] = {"status": "pending", "managed_status": managed["status"],
                                         "reason": managed.get("reason")}


def _settle_existing_records(records: list[dict[str, Any]], daily_cache_path: Path, *, track: str) -> None:
    by_code = _load_execution_cache(daily_cache_path)
    if track == "target_exit":
        _settle_target_records(records, by_code)
        return
    if track == "breakout_entry":
        _settle_breakout_records(records, by_code)
        return
    raise TargetPolicyError("unknown_p2_component")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A-short P2 target-policy shadow accumulator (no provider calls)")
    parser.add_argument("command", choices=["refresh", "settle"])
    parser.add_argument("--root", default=str(PRIVATE_LEDGER_DEFAULT))
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--daily-cache")
    parser.add_argument("--summary-out", default=str(PUBLIC_SUMMARY_DEFAULT))
    parser.add_argument("--markdown-out", default=str(PUBLIC_MARKDOWN_DEFAULT))
    args = parser.parse_args(argv)
    summary = settle_and_summarize(root=args.root, as_of=args.as_of, daily_cache_path=args.daily_cache,
                                   summary_path=args.summary_out, markdown_path=args.markdown_out)
    print(summary["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
