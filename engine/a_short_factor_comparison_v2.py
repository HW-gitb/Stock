"""A-short comparison-track v2: offline, source-bound weekly evidence only.

This module is intentionally separate from the live weekly pipeline and the v1
``a_short_factor_comparison`` track. Knife 1 builds private capture, epoch,
cache-only outcome, adjustment and risk evidence. Knife 2 consumes only those
frozen artifacts through a separate offline adjudicator; knife 3 alone may wire
the two into weekly execution. Neither module changes production or calls a
provider.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from engine import a_short_evidence_epoch_mode as _epoch_mode

from engine import a_short_factor_comparison as v1


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRIVATE_ROOT = ROOT / "state" / "a_short" / "factor_comparison_private" / "v2"
GOVERNANCE_PATH = ROOT / "presets" / "a_short_factor_comparison_v2_governance_20260718.json"
PROGRAM_SCHEMA_PATH = ROOT / "schemas" / "a_short_factor_comparison_v2_program.schema.json"
WEEKLY_SCHEMA_PATH = ROOT / "schemas" / "a_short_factor_comparison_v2_weekly.schema.json"
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "a_short_factor_comparison_v2_ledger.schema.json"
RECEIPT_SCHEMA_PATH = ROOT / "schemas" / "a_short_factor_comparison_v2_decision_receipt.schema.json"
PUBLIC_PROGRESS_SCHEMA_PATH = ROOT / "schemas" / "a_short_factor_comparison_v2_public_progress.schema.json"
BATCH_REGISTRY_PATH = "experiment_batches.json"

PROGRAM_ID = "a_short_factor_comparison_v2"
SCHEMA_VERSION = "2.0.0"
HORIZONS = (5, 10, 20)
COMMON_POOL_SEAM = "same_pit_candidate_universe_after_non_iv_immutable_hard_gates"
P0V2_SEMANTIC_MODULE_EXCLUSIONS = {
    "engine.a_short_factor_comparison_v2": (),
    "engine.a_short_factor_comparison": (),
    "engine.a_short_factor_comparison_v2_weekly": (),
    "engine.a_short_factor_comparison_v2_adjudication": (),
    "runners.a_short_factor_comparison_v2_cache_build": (),
    "runners.a_short_phase5_engine": (),
}


class ComparisonV2Error(ValueError):
    """Raised when a v2 private evidence invariant cannot be proven."""


def _price_close_matches(left: object, right: object) -> bool:
    """Compare the same frozen price without rejecting binary float representation drift."""
    return _finite(left) and _finite(right) and math.isclose(
        float(left), float(right), rel_tol=0.0, abs_tol=1e-8
    )


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return _digest(_load_json(path))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _date(value: object) -> str:
    return v1._date(value)


def _finite(value: object) -> bool:
    return v1._finite(value)


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _boundary(governance: dict) -> dict:
    return copy.deepcopy(governance["boundary"])


def _schema(path: Path) -> dict:
    return _load_json(path)


def _validate_with_schema(value: dict, path: Path) -> None:
    import jsonschema

    jsonschema.validate(value, _schema(path))


def _private_root(root: str | Path) -> Path:
    path = Path(root).resolve()
    suffix = ("state", "a_short", "factor_comparison_private", "v2")
    if tuple(part.lower() for part in path.parts[-4:]) != suffix:
        raise ComparisonV2Error("v2 comparison root must end state/a_short/factor_comparison_private/v2")
    try:
        path.relative_to(ROOT)
    except ValueError:
        return path
    try:
        relative = path.relative_to(ROOT)
        result = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", "--", str(relative)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ComparisonV2Error("cannot prove v2 private root is gitignored") from exc
    if result.returncode != 0:
        raise ComparisonV2Error("v2 comparison root is not a provably gitignored private path")
    return path


def load_v2_governance(path: str | Path = GOVERNANCE_PATH) -> dict:
    governance = _load_json(Path(path))
    validate_v2_governance(governance)
    return governance


def validate_v2_governance(governance: dict) -> None:
    _validate_with_schema(governance, PROGRAM_SCHEMA_PATH)
    questions = governance["questions"]
    if len({row["question_id"] for row in questions}) != len(questions):
        raise ComparisonV2Error("v2 question ids must be unique")
    all_v1 = {row["factor_id"] for row in v1.load_governance()["factor_registry"]}
    for question in questions:
        arms = question["arms"]
        ordered = question["ordered_arm_ids"]
        if [row["arm_id"] for row in arms] != ordered:
            raise ComparisonV2Error("ordered_arm_ids is the only v2 arm order authority")
        if len(set(ordered)) != len(ordered):
            raise ComparisonV2Error("v2 arm ids must be unique")
        baselines = [row for row in arms if row["kind"] == "baseline"]
        if len(baselines) != 1 or baselines[0]["arm_id"] != "baseline" or baselines[0]["factor_id"] is not None:
            raise ComparisonV2Error("every v2 question requires exactly one baseline arm")
        challengers = [row for row in arms if row["kind"] == "challenger"]
        if not challengers:
            raise ComparisonV2Error("every v2 question requires a challenger")
        components = question.get("component_factor_ids")
        is_combination = question["question_type"] == "combination_policy"
        if is_combination:
            if question["effect_surface"] != "combined_policy" or len(challengers) != 1 or \
                    not isinstance(components, list) or len(components) != 2 or set(components) - all_v1:
                raise ComparisonV2Error("v2 combination question must pre-register exactly two known component factors")
            categories = {next(row["category"] for row in v1.load_governance()["factor_registry"]
                               if row["factor_id"] == factor_id) for factor_id in components}
            if categories != {"entry_anchor", "iv_policy"}:
                raise ComparisonV2Error("v2 combination requires one entry and one IV component")
        elif components is not None:
            raise ComparisonV2Error("only a v2 combination question may declare component factors")
        for arm in challengers:
            if not is_combination and arm["factor_id"] not in all_v1:
                raise ComparisonV2Error(f"unknown v2 factor arm {arm['factor_id']!r}")
            if arm["effect_surface"] != question["effect_surface"]:
                raise ComparisonV2Error("challenger effect surface must equal its question effect surface")
            if arm["effect_surface"] not in {"entry_type", "iv_policy", "combined_policy"}:
                raise ComparisonV2Error("v2 D1/D3 supports only entry_type or iv_policy effect surfaces")
        if baselines[0]["effect_surface"] != "none":
            raise ComparisonV2Error("baseline arm must not declare an effect surface")
    if governance["outcome_contract"]["horizons_trading_days"] != list(HORIZONS):
        raise ComparisonV2Error("v2 horizons drifted")
    required_risk = {
        "max_drawdown_pct", "bad_name_rate", "tail_loss_pct", "cash_drag_pct", "unfilled_rate",
        "fill_rate", "turnover_pct", "total_cost_pct", "max_name_weight_pct", "adjustment_coverage_pct",
        "loss_distribution_basis", "loss_distribution_count",
    }
    if set(governance["risk_evidence"]) != required_risk:
        raise ComparisonV2Error("v2 risk evidence set drifted")


def validate_v2_weekly_record(record: dict) -> None:
    _validate_with_schema(record, WEEKLY_SCHEMA_PATH)
    if any(record["boundary"].values()):
        raise ComparisonV2Error("v2 weekly record crossed the comparison-only boundary")


def validate_v2_ledger(ledger: dict) -> None:
    _validate_with_schema(ledger, LEDGER_SCHEMA_PATH)
    if any(ledger["boundary"].values()):
        raise ComparisonV2Error("v2 ledger crossed the comparison-only boundary")
    keys = [(row["decision_date"], row["question_id"]) for row in ledger["entries"]]
    if len(keys) != len(set(keys)):
        raise ComparisonV2Error("v2 ledger may contain one entry per decision date/question only")


def validate_v2_decision_receipt(receipt: dict) -> None:
    _validate_with_schema(receipt, RECEIPT_SCHEMA_PATH)
    if any(receipt["boundary"].values()):
        raise ComparisonV2Error("v2 decision receipt crossed the comparison-only boundary")


def _canonical_contracts(governance: dict) -> dict:
    """Pre-freeze every contract leg is a stable constant; the admission binding
    stays real because it is a governance fact, not an implementation hash.
    See ``engine/a_short_evidence_epoch_mode``."""
    packet_identity = _epoch_mode.validated_frozen_packet_identity(
        "p0_factor_comparison_v2"
    )
    if packet_identity is None:
        constant = _epoch_mode.pre_freeze_fingerprint("p0_factor_comparison_v2")
        return {"decision_delta_contract": constant, "immutable_common_pool_contract": constant,
                "outcome_contract": constant, "runtime_wiring_contract": constant,
                "admission_bindings": _pre_freeze_admission_bindings(governance)}
    real = _real_canonical_contracts(governance)
    return {
        key: (
            _epoch_mode.bind_frozen_fingerprint(
                "p0_factor_comparison_v2", value, packet_identity
            )
            if key != "admission_bindings" else value
        )
        for key, value in real.items()
    }


def _pre_freeze_admission_bindings(governance: dict) -> dict:
    from engine.a_short_experiment_admission_registry import admission_snapshot, admissions
    registered = admissions()
    admission_ids = tuple(
        f"p0_{question['question_id']}_{arm['arm_id']}"
        for question in governance["questions"]
        for arm in question["arms"] if arm["kind"] == "challenger" and
        f"p0_{question['question_id']}_{arm['arm_id']}" in registered
    )
    return admission_snapshot(*admission_ids)


def _real_canonical_contracts(governance: dict) -> dict:
    from runners import a_short_phase5_engine as phase5
    weekly = __import__("engine.a_short_factor_comparison_v2_weekly", fromlist=["*"])
    adjudication = __import__("engine.a_short_factor_comparison_v2_adjudication", fromlist=["*"])
    cache_builder = __import__("runners.a_short_factor_comparison_v2_cache_build", fromlist=["*"])
    modules = {
        "engine.a_short_factor_comparison_v2": __import__(__name__, fromlist=["*"]),
        "engine.a_short_factor_comparison": v1,
        "engine.a_short_factor_comparison_v2_weekly": weekly,
        "engine.a_short_factor_comparison_v2_adjudication": adjudication,
        "runners.a_short_factor_comparison_v2_cache_build": cache_builder,
        "runners.a_short_phase5_engine": phase5,
    }
    semantic_modules = {
        name: _epoch_mode.semantic_module_contract(
            module,
            excluded_functions=P0V2_SEMANTIC_MODULE_EXCLUSIONS[name],
        )
        for name, module in modules.items()
    }
    semantic_runtime_contract = _digest(semantic_modules)

    factor_map = {row["factor_id"]: row for row in v1.load_governance()["factor_registry"]}
    question_arms = []
    for question in governance["questions"]:
        question_arms.append({
            "question_id": question["question_id"],
            "component_factor_ids": question.get("component_factor_ids"),
            "effect_surface": question["effect_surface"],
            "ordered_arm_ids": question["ordered_arm_ids"],
            "arms": [
                {"arm_id": arm["arm_id"], "factor_id": arm["factor_id"],
                 "effect_surface": arm["effect_surface"], "one_change_only": arm["one_change_only"],
                 "factor_definition": ([factor_map[factor_id] for factor_id in question["component_factor_ids"]]
                                       if question["question_type"] == "combination_policy" and
                                       arm["kind"] == "challenger" else factor_map.get(arm["factor_id"]))}
                for arm in question["arms"]
            ],
        })
    from engine.a_short_experiment_admission_registry import admission_snapshot, admissions
    registered = admissions()
    admission_ids = tuple(
        f"p0_{question['question_id']}_{arm['arm_id']}"
        for question in governance["questions"]
        for arm in question["arms"] if arm["kind"] == "challenger" and
        f"p0_{question['question_id']}_{arm['arm_id']}" in registered
    )
    return {
        "decision_delta_contract": _digest({
            "questions": question_arms,
            "semantic_runtime_contract": semantic_runtime_contract,
        }),
        "immutable_common_pool_contract": _digest({
            "seams": [row["common_pool_seam"] for row in governance["questions"]],
            "semantic_runtime_contract": semantic_runtime_contract,
        }),
        "outcome_contract": _digest({
            "outcome_contract": governance["outcome_contract"],
            "adjustment_contract": governance["adjustment_contract"],
            "semantic_runtime_contract": semantic_runtime_contract,
        }),
        # Capture, cache materialisation and settlement are one evidence
        # pipeline.  Any executable change to these local seams opens a new
        # epoch instead of allowing old forward rows to keep counting.
        "runtime_wiring_contract": _digest({
            "semantic_modules": semantic_modules,
            "weekly_schema": _schema(WEEKLY_SCHEMA_PATH),
            "daily_cache_schema": _schema(ROOT / "schemas" / "a_short_factor_comparison_v2_daily_cache.schema.json"),
        }),
        # This is intentionally part of the epoch signature.  A statistical,
        # PIT, arm, dependency or one-change admission drift opens a new v2
        # epoch; older captures are never rewritten or re-counted.
        "admission_bindings": admission_snapshot(*admission_ids),
    }


def _program_manifest(governance: dict) -> dict:
    return {
        "schema_name": "a_short_factor_comparison_v2_program_manifest",
        "schema_version": SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "lane": "a_short",
        "private_root_layout": "state/a_short/factor_comparison_private/v2",
        "governance_schema_sha256": _file_digest(PROGRAM_SCHEMA_PATH),
        "weekly_schema_sha256": _file_digest(WEEKLY_SCHEMA_PATH),
        "ledger_schema_sha256": _file_digest(LEDGER_SCHEMA_PATH),
        "decision_receipt_schema_sha256": _file_digest(RECEIPT_SCHEMA_PATH),
        "boundary": _boundary(governance),
        "legacy_v1": "read_only_not_imported",
        "stage": "knife_2_offline_adjudication_available",
    }


def _ensure_program(root: Path, governance: dict) -> None:
    manifest = _program_manifest(governance)
    path = root / "program_manifest.json"
    if path.exists():
        if _load_json(path) != manifest:
            raise ComparisonV2Error("v2 program manifest drifted")
    else:
        _atomic_write(path, manifest)
    ledger_path = root / "ledger.json"
    if not ledger_path.exists():
        ledger = {
            "schema_name": "a_short_factor_comparison_v2_ledger",
            "schema_version": SCHEMA_VERSION,
            "program_id": PROGRAM_ID,
            "stage": "capture_only",
            "entries": [],
            "boundary": _boundary(governance),
        }
        validate_v2_ledger(ledger)
        _atomic_write(ledger_path, ledger)
    epochs_path = root / "epochs.json"
    if not epochs_path.exists():
        _atomic_write(epochs_path, {"schema_name": "a_short_factor_comparison_v2_epochs", "schema_version": SCHEMA_VERSION,
                                     "program_id": PROGRAM_ID, "epochs": [], "boundary": _boundary(governance)})
    _load_experiment_batches(root, governance)


def _initial_experiment_batches(governance: dict) -> dict:
    return {
        "schema_name": "a_short_factor_comparison_v2_experiment_batches",
        "schema_version": SCHEMA_VERSION,
        "program_id": PROGRAM_ID,
        "questions": [{
            "question_id": question["question_id"],
            "active_experiment_batch_id": question["experiment_batch_id"],
            "activation_kind": "governance_initial",
            "prior_experiment_batch_ids": [],
            "new_forward_evidence_required": True,
        } for question in governance["questions"]],
        "combination_batches": [],
        "boundary": {"production": False, "automatic_policy_switch": False},
    }


def _validate_combination_receipts(root: Path, combination: dict) -> None:
    path = root / "decision_receipts.json"
    if not path.exists():
        raise ComparisonV2Error("v2 combination batch requires accepted private decision receipts")
    collection = _load_json(path)
    if set(collection) != {"schema_name", "schema_version", "program_id", "receipts", "boundary"} or \
            collection.get("schema_name") != "a_short_factor_comparison_v2_decision_receipts" or \
            collection.get("schema_version") != SCHEMA_VERSION or collection.get("program_id") != PROGRAM_ID or \
            collection.get("boundary") != {"production": False, "automatic_policy_switch": False}:
        raise ComparisonV2Error("v2 combination receipt collection drifted")
    receipts = {}
    for row in collection["receipts"]:
        if set(row) != {"receipt_sha256", "receipt"} or row.get("receipt_sha256") in receipts or \
                row["receipt_sha256"] != row["receipt"].get("verdict_sha256"):
            raise ComparisonV2Error("v2 combination receipt collection is malformed")
        validate_v2_decision_receipt(row["receipt"])
        receipts[row["receipt_sha256"]] = row["receipt"]
    components = combination["accepted_components"]
    if sorted(combination["accepted_receipt_sha256s"]) != sorted(component["receipt_sha256"] for component in components):
        raise ComparisonV2Error("v2 combination receipt index drifted")
    component_question_ids = combination["component_question_ids"]
    accepted_question_ids = [component["question_id"] for component in components]
    if len(set(component_question_ids)) != len(component_question_ids) or \
            len(set(accepted_question_ids)) != len(accepted_question_ids) or \
            set(accepted_question_ids) != set(component_question_ids):
        raise ComparisonV2Error("v2 combination requires one accepted receipt per component question")
    for component in components:
        receipt = receipts.get(component["receipt_sha256"])
        if receipt is None or receipt["status"] != "accepted" or receipt["decision"] != "accepted" or \
                receipt["question_id"] != component["question_id"] or receipt["arm_id"] != component["arm_id"]:
            raise ComparisonV2Error("v2 combination component is not bound to its accepted receipt")


def _load_experiment_batches(root: Path, governance: dict) -> dict:
    """Load the private batch registry that prevents dormant evidence from being reused."""
    path = root / BATCH_REGISTRY_PATH
    if not path.exists():
        payload = _initial_experiment_batches(governance)
        _atomic_write(path, payload)
        return payload
    payload = _load_json(path)
    required = {"schema_name", "schema_version", "program_id", "questions", "combination_batches", "boundary"}
    if set(payload) != required or payload.get("schema_name") != "a_short_factor_comparison_v2_experiment_batches" or \
            payload.get("schema_version") != SCHEMA_VERSION or payload.get("program_id") != PROGRAM_ID or \
            payload.get("boundary") != {"production": False, "automatic_policy_switch": False}:
        raise ComparisonV2Error("v2 experiment batch registry drifted")
    configured = [question["question_id"] for question in governance["questions"]]
    rows = payload.get("questions")
    if not isinstance(rows, list) or len({row.get("question_id") for row in rows}) != len(rows) or \
            any(row.get("question_id") not in configured for row in rows):
        raise ComparisonV2Error("v2 experiment batch registry question ordering drifted")
    by_question = {row["question_id"]: row for row in rows}
    changed = False
    for question in governance["questions"]:
        if question["question_id"] in by_question:
            continue
        combination = next((row for row in payload["combination_batches"]
                            if row.get("experiment_batch_id") == question["experiment_batch_id"]), None)
        if question["question_type"] != "combination_policy" or not isinstance(combination, dict) or \
                combination.get("pre_registered_combination_question_required") is not True:
            raise ComparisonV2Error("v2 new question must be a pre-registered combination batch")
        _validate_combination_receipts(root, combination)
        accepted_factor_ids = {row.get("arm_id") for row in combination.get("accepted_components", [])}
        if set(question.get("component_factor_ids") or []) != accepted_factor_ids:
            raise ComparisonV2Error("v2 combination question components do not match accepted batch receipts")
        by_question[question["question_id"]] = {
            "question_id": question["question_id"],
            "active_experiment_batch_id": question["experiment_batch_id"],
            "activation_kind": "combination_preregistered",
            "prior_experiment_batch_ids": [],
            "new_forward_evidence_required": True,
        }
        changed = True
    payload["questions"] = [by_question[question_id] for question_id in configured]
    rows = payload["questions"]
    for row in rows:
        if set(row) != {"question_id", "active_experiment_batch_id", "activation_kind", "prior_experiment_batch_ids",
                        "new_forward_evidence_required"} or not isinstance(row["active_experiment_batch_id"], str) or \
                not row["active_experiment_batch_id"] or not isinstance(row["prior_experiment_batch_ids"], list) or \
                row["new_forward_evidence_required"] is not True:
            raise ComparisonV2Error("v2 experiment batch registry entry is malformed")
    if not isinstance(payload["combination_batches"], list):
        raise ComparisonV2Error("v2 combination batch registry is malformed")
    for row in payload["combination_batches"]:
        required_combination = {"experiment_batch_id", "component_question_ids", "accepted_components", "accepted_receipt_sha256s",
                                "new_forward_evidence_required", "historical_backfill_forbidden",
                                "pre_registered_combination_question_required"}
        if set(row) != required_combination or not isinstance(row["experiment_batch_id"], str) or \
                not isinstance(row["component_question_ids"], list) or len(row["component_question_ids"]) < 2 or \
                not isinstance(row["accepted_components"], list) or len(row["accepted_components"]) != len(row["component_question_ids"]) or \
                not all(set(component) == {"question_id", "arm_id", "receipt_sha256"} for component in row["accepted_components"]) or \
                not isinstance(row["accepted_receipt_sha256s"], list) or \
                row["new_forward_evidence_required"] is not True or row["historical_backfill_forbidden"] is not True or \
                row["pre_registered_combination_question_required"] is not True:
            raise ComparisonV2Error("v2 combination batch registry entry is malformed")
        component_question_ids = row["component_question_ids"]
        accepted_question_ids = [component["question_id"] for component in row["accepted_components"]]
        if len(set(component_question_ids)) != len(component_question_ids) or \
                len(set(accepted_question_ids)) != len(accepted_question_ids) or \
                set(accepted_question_ids) != set(component_question_ids):
            raise ComparisonV2Error("v2 combination batch component question set drifted")
    if changed:
        _atomic_write(path, payload)
    return payload


def _active_experiment_batch_ids(root: Path, governance: dict) -> dict[str, str]:
    return {row["question_id"]: row["active_experiment_batch_id"]
            for row in _load_experiment_batches(root, governance)["questions"]}


def _clean_run_identity(run_identity: dict, decision_date: str) -> dict:
    if not isinstance(run_identity, dict):
        raise ComparisonV2Error("v2 run_identity must be an object")
    required = ("run_id", "run_date", "source_as_of", "price_data_through", "candidate_digest", "official_m67_digest")
    if set(run_identity) != set(required):
        raise ComparisonV2Error("v2 run_identity keys drifted")
    identity = {key: str(run_identity[key]) for key in required}
    if not identity["run_id"]:
        raise ComparisonV2Error("v2 run_identity requires run_id")
    run_date = _date(identity["run_date"])
    source_as_of = _date(identity["source_as_of"])
    price_data_through = _date(identity["price_data_through"])
    if source_as_of != decision_date:
        raise ComparisonV2Error("v2 capture requires decision_date to equal the PIT source_as_of")
    if price_data_through > decision_date or price_data_through > run_date:
        raise ComparisonV2Error("v2 price_data_through cannot be after decision_date or physical run_date")
    for key in ("candidate_digest", "official_m67_digest"):
        if len(identity[key]) != 64 or any(char not in "0123456789abcdef" for char in identity[key]):
            raise ComparisonV2Error(f"v2 {key} must be a lowercase sha256")
    return identity


def _immutable_common_pool(candidates: list[dict]) -> dict:
    """Freeze the pre-IV-policy PIT seam after non-IV immutable hard gates.

    D3's measured IV gate is deliberately deferred to each arm.  Candidates that
    fail only that gate remain in ``symbols`` and are explicitly labelled in
    ``iv_policy_deferred``; contraction, liquidity, event and all other
    independent hard gates remain exclusionary for every arm.
    """
    from runners.a_short_phase5_engine import classify_risk_families, compute_indicators

    included, iv_policy_deferred, rejected = [], {}, {}
    for candidate in candidates:
        if (candidate.get("stateful_risk") or {}).get("position_state") == "held":
            rejected[candidate["ts_code"]] = ["existing_holding_out_of_scope"]
            continue
        if str(candidate.get("market_regime") or "") == "收缩期":
            rejected[candidate["ts_code"]] = ["market_regime:contraction_no_new_entry"]
            continue
        families = classify_risk_families(candidate, compute_indicators(candidate["price_series"]))
        reasons, deferred_reasons = [], []
        for family, detail in families.items():
            if detail.get("action") != "hard_veto":
                continue
            for reason in detail.get("reasons") or []:
                text = str(reason)
                if family == "market_regime" and "IV分位" in text:
                    deferred_reasons.append(f"{family}:{text}")
                    continue
                reasons.append(f"{family}:{text}")
        if reasons:
            rejected[candidate["ts_code"]] = sorted(reasons)
        else:
            included.append(candidate["ts_code"])
            if deferred_reasons:
                iv_policy_deferred[candidate["ts_code"]] = sorted(deferred_reasons)
    return {
        "seam": COMMON_POOL_SEAM,
        "symbols": sorted(included),
        "iv_policy_deferred": iv_policy_deferred,
        "rejected": rejected,
        "digest": _digest({"symbols": sorted(included), "iv_policy_deferred": iv_policy_deferred,
                           "rejected": rejected}),
    }


def _arm_definition(arm: dict, v1_factors: dict, *, component_factor_ids: list[str] | None = None) -> dict:
    factor = v1_factors.get(arm["factor_id"])
    composite = [copy.deepcopy(v1_factors[factor_id]) for factor_id in component_factor_ids or []]
    return {
        "arm_id": arm["arm_id"],
        "kind": arm["kind"],
        "factor_id": arm["factor_id"],
        "effect_surface": arm["effect_surface"],
        "one_change_only": arm["one_change_only"],
        "factor_definition": composite if composite else copy.deepcopy(factor) if factor is not None else None,
        "component_factor_ids": copy.deepcopy(component_factor_ids) if composite else None,
        "allocation": "equal_slot_no_reallocation",
        "candidate_pool": COMMON_POOL_SEAM,
    }


def _combined_candidate_decision(candidate: dict, *, component_factor_ids: list[str], factor_map: dict,
                                 governance: dict, realized_regime: dict) -> dict:
    """Apply one pre-registered entry factor and one IV factor without changing production code."""
    from runners.a_short_phase5_engine import classify_risk_families, compute_indicators, exit_and_size

    if v1._is_existing_holding(candidate):
        return {"ts_code": candidate["ts_code"], "status": "out_of_scope_existing_holding", "selected": False,
                "score": candidate.get("egs_score"), "reason": "comparison_new_entries_only", "plan": None}
    entry_factor_id = next(factor_id for factor_id in component_factor_ids
                           if factor_map[factor_id]["category"] == "entry_anchor")
    iv_factor_id = next(factor_id for factor_id in component_factor_ids
                        if factor_map[factor_id]["category"] == "iv_policy")
    indicators = compute_indicators(candidate["price_series"])
    families = classify_risk_families(candidate, indicators)
    iv = v1._iv_policy(candidate, iv_factor_id, factor_map[iv_factor_id], realized_regime)
    hard = v1._hard_reasons(families, bool(iv["relax_iv_hard"]))
    if hard:
        return {"ts_code": candidate["ts_code"], "status": "hard_veto", "selected": False,
                "score": candidate.get("egs_score"), "reason": "|".join(hard), "plan": None}
    entry_type, entry_reason = v1._entry_for_factor(candidate, indicators, entry_factor_id, factor_map[entry_factor_id])
    if entry_type == "观察":
        return {"ts_code": candidate["ts_code"], "status": "observe", "selected": False,
                "score": candidate.get("egs_score"), "reason": entry_reason, "plan": None}
    virtual = copy.deepcopy(candidate)
    cash = float(governance["selection"]["virtual_account_available_cash"])
    virtual["account"] = {"available_cash": cash, "bucket_capital": cash, "new_exposure_capacity": cash}
    plan, rejected = exit_and_size(virtual, indicators, str(candidate.get("market_regime") or "震荡期"), entry_type,
                                   extra_halve=bool(iv["extra_halve"]), halve_reason=str(iv["reason"]),
                                   size_multiplier=float(iv["size_multiplier"]),
                                   size_multiplier_reason=str(iv["reason"]))
    if plan is None:
        return {"ts_code": candidate["ts_code"], "status": "observe", "selected": False,
                "score": candidate.get("egs_score"), "reason": str(rejected), "plan": None}
    return {"ts_code": candidate["ts_code"], "status": "eligible", "selected": False,
            "score": candidate.get("egs_score"), "reason": entry_reason, "plan": plan, "iv_policy": iv}


def _combined_policy_result(candidates: list[dict], *, component_factor_ids: list[str], factor_map: dict,
                            governance: dict, decision_date: str, forward_eligible: bool,
                            universe_digest: str, realized_regime: dict) -> dict:
    decisions = [_combined_candidate_decision(candidate, component_factor_ids=component_factor_ids,
                                              factor_map=factor_map, governance=governance,
                                              realized_regime=realized_regime) for candidate in candidates]
    eligible = sorted((row for row in decisions if row["status"] == "eligible"), key=v1._score_key)
    chosen = eligible[:int(governance["selection"]["slots"])]
    chosen_codes = {row["ts_code"] for row in chosen}
    for row in decisions:
        row["selected"] = row["ts_code"] in chosen_codes
    return {
        "selection": {"slots": int(governance["selection"]["slots"]),
                      "eligible_symbols": [row["ts_code"] for row in eligible],
                      "selected_symbols": [row["ts_code"] for row in chosen], "decisions": decisions},
    }


def _materialize_question(question: dict, candidates: list[dict], *, decision_date: str,
                          forward_eligible: bool, v1_governance: dict, common_pool: dict,
                          experiment_batch_id: str) -> dict:
    factor_map = {row["factor_id"]: row for row in v1_governance["factor_registry"]}
    universe_digest = _digest(candidates)
    pool_symbols = set(common_pool["symbols"])
    pool_candidates = [candidate for candidate in candidates if candidate["ts_code"] in pool_symbols]
    arms = []
    baseline_record = None
    component_factor_ids = question.get("component_factor_ids") if question["question_type"] == "combination_policy" else None
    for arm in question["arms"]:
        factor_id = "baseline" if arm["kind"] == "baseline" else str(arm["factor_id"])
        if component_factor_ids and arm["kind"] == "challenger":
            record = _combined_policy_result(
                pool_candidates, component_factor_ids=component_factor_ids, factor_map=factor_map,
                governance=v1_governance, decision_date=decision_date, forward_eligible=forward_eligible,
                universe_digest=universe_digest,
                realized_regime=v1.unavailable_realized_regime(v1_governance, "v2_capture_not_weekly_wired"),
            )
        else:
            record = v1._policy_result(
                pool_candidates, factor_id, None if factor_id == "baseline" else factor_map[factor_id],
                v1_governance, decision_date, forward_eligible, universe_digest,
                v1.unavailable_realized_regime(v1_governance, "v2_capture_not_weekly_wired"),
            )
        materialization = {
            "arm_definition": _arm_definition(arm, factor_map,
                                                component_factor_ids=component_factor_ids if arm["kind"] == "challenger" else None),
            "arm_definition_sha256": _digest(_arm_definition(arm, factor_map,
                                                               component_factor_ids=component_factor_ids if arm["kind"] == "challenger" else None)),
            "selected_symbols": record["selection"]["selected_symbols"],
            "eligible_symbols": record["selection"]["eligible_symbols"],
            "decisions": record["selection"]["decisions"],
            "slots": record["selection"]["slots"],
            "candidate_universe_digest": universe_digest,
        }
        if arm["kind"] == "baseline":
            baseline_record = materialization
        arms.append(materialization)
    if baseline_record is None:
        raise ComparisonV2Error("question materializer lost baseline")
    for arm in arms:
        definition = arm["arm_definition"]
        if definition["kind"] == "challenger":
            if definition["effect_surface"] != question["effect_surface"]:
                raise ComparisonV2Error("arm materializer attempted a hidden second effect surface")
            if definition["allocation"] != "equal_slot_no_reallocation" or \
                    definition["candidate_pool"] != common_pool["seam"]:
                raise ComparisonV2Error("arm materializer attempted a hidden pool or allocation redefinition")
    return {
        "question_id": question["question_id"],
        "experiment_batch_id": experiment_batch_id,
        "title": question["title"],
        "effect_surface": question["effect_surface"],
        "ordered_arm_ids": question["ordered_arm_ids"],
        "common_pool": common_pool,
        "baseline_parity": {
            "canonical_primitives": "a_short_phase5_engine_via_v1_policy_result",
            "baseline_selection_digest": _digest({
                "selected_symbols": baseline_record["selected_symbols"],
                "eligible_symbols": baseline_record["eligible_symbols"],
                "decisions": baseline_record["decisions"],
            }),
        },
        "arms": arms,
    }


def _resolve_epoch(root: Path, governance: dict, decision_date: str) -> dict:
    path = root / "epochs.json"
    payload = _load_json(path)
    if set(payload) != {"schema_name", "schema_version", "program_id", "epochs", "boundary"}:
        raise ComparisonV2Error("v2 epochs record keys drifted")
    if payload["program_id"] != PROGRAM_ID or any(payload["boundary"].values()):
        raise ComparisonV2Error("v2 epochs record is invalid")
    signature = _canonical_contracts(governance)
    epochs = payload["epochs"]
    if epochs and epochs[-1].get("orthogonality_signature") == signature:
        return copy.deepcopy(epochs[-1])
    epoch = {
        "epoch_id": "epoch-" + _digest({"decision_date": decision_date, "signature": signature})[:12],
        "starts_on": decision_date,
        "orthogonality_signature": signature,
        "orthogonality_checks": list(governance["epoch_policy"]["orthogonality_checks"]),
        "reason": "initial_v2_epoch" if not epochs else "nonorthogonal_contract_change",
    }
    epochs.append(epoch)
    _atomic_write(path, payload)
    return copy.deepcopy(epoch)


def _capture_payload_digest(payload: dict) -> str:
    return _digest({key: value for key, value in payload.items() if key != "capture_sha256"})


def _validate_capture_integrity(capture: dict) -> None:
    """Re-validate frozen capture hashes, source bindings and pool identity.

    Frozen arm selections and model-paper plans remain hash-bound capture payloads;
    this function deliberately does not re-run the historical selector.
    """
    validate_v2_weekly_record(capture)
    if capture["record_type"] != "capture":
        raise ComparisonV2Error("v2 capture record type drifted")
    payload = capture["payload"]
    required = {
        "capture_sha256", "forward_eligible", "run_identity", "candidate_universe",
        "candidate_universe_digest", "canonical_baseline", "governance_sha256",
        "v1_comparison_governance_sha256", "common_pool", "questions", "admission_bindings",
        "orthogonality_signature",
    }
    # Pre-admission captures remain readable only as diagnostic history; they
    # deliberately lack both bindings and cannot satisfy is_current...
    legacy_required = required - {"admission_bindings", "orthogonality_signature"}
    if set(payload) != required and set(payload) != legacy_required:
        raise ComparisonV2Error("v2 capture payload keys drifted")
    if payload["capture_sha256"] != _capture_payload_digest(payload):
        raise ComparisonV2Error("v2 capture content no longer matches its sha256")
    if "admission_bindings" in payload and not isinstance(payload["admission_bindings"], dict):
        raise ComparisonV2Error("v2 capture admission binding is malformed")
    if "orthogonality_signature" in payload and not isinstance(payload["orthogonality_signature"], dict):
        raise ComparisonV2Error("v2 capture epoch signature is malformed")
    identity = _clean_run_identity(payload["run_identity"], capture["decision_date"])
    candidates = payload["candidate_universe"]
    if not isinstance(candidates, list) or not candidates:
        raise ComparisonV2Error("v2 capture candidate snapshot is missing")
    candidate_digest = _digest(candidates)
    if candidate_digest != payload["candidate_universe_digest"] or candidate_digest != identity["candidate_digest"]:
        raise ComparisonV2Error("v2 capture candidate source digest is not bound to the actual snapshot")
    codes = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ComparisonV2Error("v2 capture candidate snapshot row is malformed")
        code = str(candidate.get("ts_code") or "")
        series = candidate.get("price_series")
        if not code or not isinstance(series, list) or not series:
            raise ComparisonV2Error("v2 capture candidate snapshot lacks PIT price history")
        bar_dates = [_date(row.get("trade_date")) for row in series if isinstance(row, dict) and row.get("trade_date")]
        if len(bar_dates) != len(series) or max(bar_dates) != identity["price_data_through"]:
            raise ComparisonV2Error("v2 capture candidate price history does not end at frozen price_data_through")
        if not _price_close_matches(candidate.get("close"), series[-1].get("close")):
            raise ComparisonV2Error("v2 capture candidate close is not bound to its frozen price_data_through history")
        codes.append(code)
    if len(codes) != len(set(codes)):
        raise ComparisonV2Error("v2 capture candidate snapshot has duplicate symbols")
    common_pool = _immutable_common_pool(candidates)
    if common_pool != payload["common_pool"]:
        raise ComparisonV2Error("v2 capture immutable common pool drifted")
    question_ids = set()
    for question in payload["questions"]:
        question_id = question.get("question_id")
        if not isinstance(question_id, str) or question_id in question_ids:
            raise ComparisonV2Error("v2 capture question identity drifted")
        batch_id = question.get("experiment_batch_id")
        if not isinstance(batch_id, str) or not batch_id:
            raise ComparisonV2Error("v2 capture question experiment batch identity drifted")
        question_ids.add(question_id)
        if question.get("common_pool") != common_pool:
            raise ComparisonV2Error("v2 capture question no longer uses the shared immutable common pool")
        arms = question.get("arms")
        ordered = question.get("ordered_arm_ids")
        if not isinstance(arms, list) or not isinstance(ordered, list) or \
                [arm.get("arm_definition", {}).get("arm_id") for arm in arms] != ordered:
            raise ComparisonV2Error("v2 capture arm order drifted from ordered_arm_ids")
        if sum(arm.get("arm_definition", {}).get("kind") == "baseline" for arm in arms) != 1:
            raise ComparisonV2Error("v2 capture question must retain exactly one baseline")
        for arm in arms:
            if arm.get("candidate_universe_digest") != candidate_digest:
                raise ComparisonV2Error("v2 arm is not bound to the capture candidate snapshot")
            definition = arm.get("arm_definition") or {}
            if arm.get("arm_definition_sha256") != _digest(definition):
                raise ComparisonV2Error("v2 arm definition sha256 drifted")


def is_current_governed_capture(capture: dict, *, governance: dict | None = None) -> bool:
    """Whether a capture belongs to the active admission epoch, not a legacy diagnostic epoch."""
    payload = capture.get("payload") if isinstance(capture, dict) else None
    signature = _canonical_contracts(governance or load_v2_governance())
    return isinstance(payload, dict) and payload.get("admission_bindings") == signature["admission_bindings"] and \
        payload.get("orthogonality_signature") == signature


def _validate_source_receipt(root: Path, capture: dict, receipt: dict) -> None:
    _validate_capture_integrity(capture)
    validate_v2_weekly_record(receipt)
    if receipt["record_type"] != "source_receipt" or receipt["decision_date"] != capture["decision_date"] or \
            receipt["epoch_id"] != capture["epoch_id"]:
        raise ComparisonV2Error("v2 source receipt identity does not match its capture")
    epochs = _load_json(root / "epochs.json")
    matches = [row for row in epochs.get("epochs", []) if row.get("epoch_id") == capture["epoch_id"]]
    if len(matches) != 1:
        raise ComparisonV2Error("v2 capture epoch identity is unavailable or ambiguous")
    signature = matches[0].get("orthogonality_signature")
    signature_admissions = signature.get("admission_bindings") if isinstance(signature, dict) else None
    capture_admissions = capture["payload"].get("admission_bindings")
    if signature_admissions is None:
        if capture_admissions is not None:
            raise ComparisonV2Error("legacy v2 epoch cannot carry a later admission binding")
    elif capture_admissions != signature_admissions:
        raise ComparisonV2Error("v2 capture admission identity/statistical/PIT/dependency binding drifted")
    expected = {
        "capture_sha256": capture["payload"]["capture_sha256"],
        "run_identity": capture["payload"]["run_identity"],
        "candidate_universe_digest": capture["payload"]["candidate_universe_digest"],
        "common_pool_digest": capture["payload"]["common_pool"]["digest"],
        "orthogonality_signature": signature,
        "outcome_contract_sha256": signature.get("outcome_contract") if isinstance(signature, dict) else None,
        "settlement": None,
    }
    actual = copy.deepcopy(receipt.get("payload"))
    if not isinstance(actual, dict):
        raise ComparisonV2Error("v2 source receipt payload is malformed")
    actual["settlement"] = None
    if actual != expected:
        raise ComparisonV2Error("v2 source receipt is not bound to capture, epoch and actual candidate source")


def capture_v2_week(*, root: str | Path, decision_date: str, candidates: list[dict], run_identity: dict,
                    forward_eligible: bool, governance: dict | None = None) -> dict:
    """Freeze v2 question/arm evidence.  No provider call or live weekly coupling occurs here."""
    root = _private_root(root)
    decision_date = _date(decision_date)
    governance = copy.deepcopy(governance or load_v2_governance())
    validate_v2_governance(governance)
    identity = _clean_run_identity(run_identity, decision_date)
    if not isinstance(forward_eligible, bool):
        raise ComparisonV2Error("forward_eligible must be boolean")
    if forward_eligible and _today() != identity["run_date"]:
        raise ComparisonV2Error("v2 forward_eligible capture requires the real local run date")
    if forward_eligible and decision_date < identity["run_date"]:
        raise ComparisonV2Error("v2 forward_eligible capture requires a live canonical decision_date")
    sanitized = [v1._safe_candidate(candidate) for candidate in candidates]
    if not sanitized:
        raise ComparisonV2Error("v2 candidate universe is empty")
    codes = [row["ts_code"] for row in sanitized]
    if len(codes) != len(set(codes)):
        raise ComparisonV2Error("v2 candidate universe contains duplicate ts_code")
    if len({str(row.get("market_regime") or "") for row in sanitized}) != 1:
        raise ComparisonV2Error("v2 candidates must share one effective production regime")
    candidate_digest = _digest(sanitized)
    if identity["candidate_digest"] != candidate_digest:
        raise ComparisonV2Error("v2 run_identity candidate_digest must equal the actual normalized candidate snapshot")
    for candidate in sanitized:
        for price_row in candidate["price_series"]:
            trade_date = price_row.get("trade_date")
            if trade_date is None or _date(trade_date) > identity["price_data_through"]:
                raise ComparisonV2Error("v2 capture candidate price series must be complete PIT data through price_data_through")
        if _date(candidate["price_series"][-1]["trade_date"]) != identity["price_data_through"]:
            raise ComparisonV2Error("v2 capture candidate snapshot last_date mismatch")
        if not _price_close_matches(candidate["price_series"][-1]["close"], candidate["close"]):
            raise ComparisonV2Error("v2 capture candidate snapshot last_close mismatch")
    _ensure_program(root, governance)
    active_batch_ids = _active_experiment_batch_ids(root, governance)
    epoch = _resolve_epoch(root, governance, decision_date)
    day = root / "weeks" / decision_date
    capture_path = day / "capture.json"
    receipt_path = day / "source_receipt.json"
    common_pool = _immutable_common_pool(sanitized)
    v1_governance = v1.load_governance()
    questions = [
        _materialize_question(question, sanitized, decision_date=decision_date,
                              forward_eligible=forward_eligible, v1_governance=v1_governance,
                              common_pool=common_pool,
                              experiment_batch_id=active_batch_ids[question["question_id"]])
        for question in governance["questions"]
    ]
    capture_payload = {
        "capture_sha256": None,
        "forward_eligible": forward_eligible,
        "run_identity": identity,
        "candidate_universe": sanitized,
        "candidate_universe_digest": candidate_digest,
        "canonical_baseline": governance["baseline"],
        "governance_sha256": _digest(governance),
        "v1_comparison_governance_sha256": _digest(v1_governance),
        "common_pool": common_pool,
        "questions": questions,
        "admission_bindings": epoch["orthogonality_signature"]["admission_bindings"],
        # A capture carries the whole epoch contract, not merely its admission
        # snapshot.  This keeps an old runtime/statistical source seam from
        # silently counting after a new governed epoch starts.
        "orthogonality_signature": epoch["orthogonality_signature"],
    }
    capture_payload["capture_sha256"] = _capture_payload_digest(capture_payload)
    capture = {
        "schema_name": "a_short_factor_comparison_v2_weekly",
        "schema_version": SCHEMA_VERSION,
        "record_type": "capture",
        "program_id": PROGRAM_ID,
        "decision_date": decision_date,
        "epoch_id": epoch["epoch_id"],
        "payload": capture_payload,
        "boundary": _boundary(governance),
    }
    validate_v2_weekly_record(capture)
    receipt = {
        "schema_name": "a_short_factor_comparison_v2_weekly",
        "schema_version": SCHEMA_VERSION,
        "record_type": "source_receipt",
        "program_id": PROGRAM_ID,
        "decision_date": decision_date,
        "epoch_id": epoch["epoch_id"],
        "payload": {
            "capture_sha256": capture_payload["capture_sha256"],
            "run_identity": identity,
            "candidate_universe_digest": candidate_digest,
            "common_pool_digest": common_pool["digest"],
            "orthogonality_signature": epoch["orthogonality_signature"],
            "outcome_contract_sha256": epoch["orthogonality_signature"]["outcome_contract"],
            "settlement": None,
        },
        "boundary": _boundary(governance),
    }
    validate_v2_weekly_record(receipt)
    if capture_path.exists() or receipt_path.exists():
        if not capture_path.exists() or not receipt_path.exists():
            raise ComparisonV2Error(f"{decision_date}: partial v2 capture directory exists")
        existing_capture = _load_json(capture_path)
        existing_receipt = _load_json(receipt_path)
        _validate_source_receipt(root, existing_capture, existing_receipt)
        expected_receipt_core = copy.deepcopy(receipt)
        existing_receipt_core = copy.deepcopy(existing_receipt)
        existing_receipt_core["payload"]["settlement"] = None
        if existing_capture != capture or existing_receipt_core != expected_receipt_core:
            raise ComparisonV2Error(f"{decision_date}: v2 capture replay input drifted")
        return {"status": "already_captured", "day": str(day), "epoch_id": epoch["epoch_id"], "capture": capture}
    if day.exists() and any(day.iterdir()):
        raise ComparisonV2Error(f"{decision_date}: v2 partial directory exists without complete capture")
    _atomic_write(capture_path, capture)
    _atomic_write(receipt_path, receipt)
    return {"status": "captured", "day": str(day), "epoch_id": epoch["epoch_id"], "capture": capture}


def _normalise_prices(daily_payload: dict) -> tuple[list[str], dict[tuple[str, str], dict], dict[tuple[str, str], float]]:
    stocks = daily_payload.get("stocks") if isinstance(daily_payload, dict) else None
    if not isinstance(stocks, pd.DataFrame):
        raise ComparisonV2Error("v2 settlement requires a pandas daily_payload.stocks frame")
    required = {"ts_code", "trade_date", "open", "close", "adj_factor"}
    if not required.issubset(stocks.columns):
        raise ComparisonV2Error(f"v2 settlement price cache missing {sorted(required - set(stocks.columns))}")
    lookup: dict[tuple[str, str], dict] = {}
    for row in stocks.to_dict("records"):
        code = str(row.get("ts_code") or "")
        trade_date = _date(row.get("trade_date"))
        key = (code, trade_date)
        clean = {
            "open": row.get("open"), "close": row.get("close"), "adj_factor": row.get("adj_factor"),
            "adj_factor_observed": row.get("adj_factor_observed"),
            "adj_factor_source": row.get("adj_factor_source"),
            "corporate_action_verified": row.get("corporate_action_verified"),
        }
        if key in lookup and lookup[key] != clean:
            raise ComparisonV2Error("v2 settlement cache has conflicting duplicate price rows")
        lookup[key] = clean
    limits_lookup: dict[tuple[str, str], float] = {}
    limits = daily_payload.get("limits")
    if isinstance(limits, pd.DataFrame) and not limits.empty:
        required_limits = {"ts_code", "trade_date", "up_limit"}
        if not required_limits.issubset(limits.columns):
            raise ComparisonV2Error("v2 settlement limit cache is malformed")
        for row in limits.to_dict("records"):
            value = row.get("up_limit")
            if _finite(value) and float(value) > 0:
                limits_lookup[(str(row["ts_code"]), _date(row["trade_date"]))] = float(value)
    dates = sorted({trade_date for _code, trade_date in lookup})
    return dates, lookup, limits_lookup


def _adjustment_quality(*, selected_union: list[str], dates: list[str], lookup: dict[tuple[str, str], dict],
                        governance: dict) -> tuple[dict, dict[str, str]]:
    contract = governance["adjustment_contract"]
    required = len(selected_union) * len(dates)
    observed = 0
    by_code: dict[str, str] = {}
    all_reasons: list[str] = []
    for code in selected_union:
        previous_qfq = None
        previous_adj = None
        for trade_date in dates:
            row = lookup.get((code, trade_date))
            reason = None
            if row is None or not (_finite(row.get("open")) and _finite(row.get("close"))):
                reason = "price_missing"
            elif not _finite(row.get("adj_factor")) or float(row["adj_factor"]) <= 0:
                reason = "adj_factor_missing"
            elif row.get("adj_factor_observed") is not True:
                reason = "adj_factor_not_observed"
            elif str(row.get("adj_factor_source") or "") != contract["required_source"]:
                reason = "adj_factor_source_unverified"
            else:
                observed += 1
                adjusted_close = float(row["close"]) * float(row["adj_factor"])
                if previous_adj is not None:
                    ratio = max(float(row["adj_factor"]) / previous_adj, previous_adj / float(row["adj_factor"]))
                    if ratio > float(contract["max_adj_factor_ratio_without_event"]) and \
                            row.get("corporate_action_verified") is not True:
                        reason = "adj_factor_jump_unverified"
                if reason is None and previous_qfq is not None:
                    qfq_gap = abs(adjusted_close / previous_qfq - 1.0) * 100.0 if previous_qfq else math.inf
                    if qfq_gap > float(contract["max_qfq_gap_pct_without_event"]) and \
                            row.get("corporate_action_verified") is not True:
                        reason = "qfq_price_gap_unverified"
                previous_qfq = adjusted_close
                previous_adj = float(row["adj_factor"])
            if reason is not None:
                by_code.setdefault(code, reason)
                all_reasons.append(reason)
    coverage_pct = (observed / required * 100.0) if required else 100.0
    reason = sorted(set(all_reasons))[0] if all_reasons else None
    return ({"required_points": required, "observed_points": observed, "coverage_pct": coverage_pct,
             "status": "valid" if reason is None else "invalid", "reason": reason}, by_code)


def _arm_no_count_reason(arm: dict, by_code: dict[str, str], question_reason: str | None) -> str | None:
    arm_reasons = sorted({by_code[code] for code in arm["selected_symbols"] if code in by_code})
    if arm_reasons:
        return arm_reasons[0]
    return f"question_union_invalid:{question_reason}" if question_reason else None


def _loss_distribution_metrics(filled_h10_returns: list[float]) -> dict:
    """Measure name-level loss only over filled positions; cash drag is separate."""
    if not filled_h10_returns:
        return {"bad_name_rate": None, "tail_loss_pct": None,
                "loss_distribution_basis": "filled_positions_only", "loss_distribution_count": 0}
    worst_count = max(1, math.ceil(len(filled_h10_returns) * 0.2))
    return {
        "bad_name_rate": sum(value <= -5.0 for value in filled_h10_returns) / len(filled_h10_returns),
        "tail_loss_pct": sum(sorted(filled_h10_returns)[:worst_count]) / worst_count,
        "loss_distribution_basis": "filled_positions_only",
        "loss_distribution_count": len(filled_h10_returns),
    }


def _position_outcomes(*, arm: dict, candidates: dict[str, dict], price_data_through: str, date_pos: dict[str, int], dates: list[str],
                       lookup: dict[tuple[str, str], dict], limits: dict[tuple[str, str], float], governance: dict) -> tuple[dict, dict]:
    as_of = arm["decision_date"]
    base_index = date_pos[as_of]
    slots = int(arm["slots"])
    decision_by_code = {row["ts_code"]: row for row in arm["decisions"] if row.get("selected")}
    positions = []
    for code in arm["selected_symbols"]:
        decision = decision_by_code.get(code)
        if not decision or not isinstance(decision.get("plan"), dict):
            raise ComparisonV2Error("v2 selected arm lacks a frozen model-paper plan")
        plan = decision["plan"]
        entry_date = dates[base_index + 1]
        base = lookup[(code, price_data_through)]
        entry = lookup[(code, entry_date)]
        frozen_candidate = candidates.get(code)
        frozen_close = frozen_candidate.get("close") if isinstance(frozen_candidate, dict) else None
        if not _finite(frozen_close) or not _finite(base.get("close")) or \
                not math.isclose(float(base["close"]), float(frozen_close), rel_tol=0.0, abs_tol=1e-8):
            raise ComparisonV2Error("v2 settlement price_data_through close drifts from frozen candidate snapshot")
        entry_model = None
        if _finite(plan.get("entry")) and float(frozen_close) > 0 and _finite(entry.get("open")):
            entry_model = float(plan["entry"]) * float(entry["open"]) / float(frozen_close)
        entry_low, entry_high = plan.get("entry_low"), plan.get("entry_high")
        if not _finite(entry_model) or not (_finite(entry_low) and _finite(entry_high)) or \
                float(entry_model) < float(entry_low) or float(entry_model) > float(entry_high):
            positions.append({"ts_code": code, "entry_status": "unfilled_entry_range", "entry_model_price": entry_model,
                              "horizons": {f"h{h}": {"status": "unfilled_entry_range", "net_return_pct": 0.0} for h in HORIZONS}})
            continue
        up_limit = limits.get((code, entry_date))
        limit_price = up_limit if up_limit is not None else float(frozen_close) * 1.10
        if float(entry["open"]) >= limit_price * 0.999:
            positions.append({"ts_code": code, "entry_status": "unfilled_limit_up", "entry_model_price": entry_model,
                              "horizons": {f"h{h}": {"status": "unfilled_limit_up", "net_return_pct": 0.0} for h in HORIZONS}})
            continue
        horizons = {}
        for horizon in HORIZONS:
            exit_date = dates[base_index + horizon]
            exit_row = lookup[(code, exit_date)]
            gross = (float(exit_row["close"]) * float(exit_row["adj_factor"])) / \
                    (float(entry["open"]) * float(entry["adj_factor"])) - 1.0
            horizons[f"h{horizon}"] = {
                "status": "settled", "entry_date": entry_date, "exit_date": exit_date,
                "net_return_pct": gross * 100.0 - float(governance["outcome_contract"]["cost_pct"]),
            }
        positions.append({"ts_code": code, "entry_status": "settled", "entry_model_price": entry_model,
                          "horizons": horizons})
    horizon_results = {}
    h10_cumulative_returns = []
    filled = [row for row in positions if row["entry_status"] == "settled"]
    cost_pct = float(governance["outcome_contract"]["cost_pct"])
    for horizon in HORIZONS:
        returns = [float(row["horizons"][f"h{horizon}"]["net_return_pct"]) for row in positions]
        horizon_results[f"h{horizon}"] = {
            "status": "settled", "net_return_pct": sum(returns) / slots if slots else 0.0,
            "evaluation_exit_date": dates[base_index + horizon],
        }
    for index in range(base_index + 1, base_index + 11):
        day = dates[index]
        marked = 0.0
        for row in filled:
            entry_date = row["horizons"]["h10"]["entry_date"]
            entry = lookup[(row["ts_code"], entry_date)]
            close = lookup[(row["ts_code"], day)]
            marked += ((float(close["close"]) * float(close["adj_factor"])) /
                       (float(entry["open"]) * float(entry["adj_factor"])) - 1.0) * 100.0 / slots
        marked -= cost_pct * len(filled) / slots if slots else 0.0
        h10_cumulative_returns.append(marked)
    filled_h10_returns = [float(row["horizons"]["h10"]["net_return_pct"]) for row in filled]
    filled_count = len(filled)
    selected_count = len(positions)
    risk = {
        "max_drawdown_pct": _maximum_drawdown(h10_cumulative_returns),
        "cash_drag_pct": (slots - filled_count) / slots * 100.0 if slots else 0.0,
        "unfilled_rate": (selected_count - filled_count) / selected_count if selected_count else 0.0,
        "fill_rate": filled_count / selected_count if selected_count else 1.0,
        "turnover_pct": selected_count / slots * 100.0 if slots else 0.0,
        "total_cost_pct": cost_pct * filled_count / slots if slots else 0.0,
        "max_name_weight_pct": 100.0 / slots if filled_count else 0.0,
    }
    risk.update(_loss_distribution_metrics(filled_h10_returns))
    return ({"selected_positions": positions, "horizons": horizon_results, "risk_evidence": risk},
            {"selected_count": selected_count, "filled_count": filled_count})


def _maximum_drawdown(cumulative_returns_pct: list[float]) -> float:
    """Return drawdown from cumulative portfolio returns, not period-return compounding."""
    nav = peak = 1.0
    maximum = 0.0
    for value in cumulative_returns_pct:
        if not _finite(value) or float(value) < -100.0:
            raise ComparisonV2Error("v2 cumulative NAV return is invalid")
        nav = 1.0 + float(value) / 100.0
        peak = max(peak, nav)
        maximum = max(maximum, (peak - nav) / peak * 100.0)
    return maximum


def _settle_question(question: dict, capture: dict, *, dates: list[str], lookup: dict[tuple[str, str], dict],
                     limits: dict[tuple[str, str], float], governance: dict) -> dict:
    decision_date = capture["decision_date"]
    date_pos = {date: index for index, date in enumerate(dates)}
    if decision_date not in date_pos or date_pos[decision_date] + max(HORIZONS) >= len(dates):
        return {"question_id": question["question_id"], "status": "pending", "reason": "h20_not_mature", "arms": []}
    key_dates = dates[date_pos[decision_date]:date_pos[decision_date] + max(HORIZONS) + 1]
    selected_union = sorted({code for arm in question["arms"] for code in arm["selected_symbols"]})
    coverage, by_code = _adjustment_quality(selected_union=selected_union, dates=key_dates, lookup=lookup,
                                            governance=governance)
    candidate_by_code = {row["ts_code"]: row for row in capture["payload"].get("candidate_universe", [])}
    if set(selected_union) - set(candidate_by_code):
        raise ComparisonV2Error("v2 selected union is missing its frozen candidate snapshot")
    if coverage["status"] != "valid":
        reason = str(coverage["reason"])
        return {
            "question_id": question["question_id"], "status": "no_count", "reason": reason,
            "adjustment_coverage": coverage,
            "arms": [
                {"arm_id": arm["arm_definition"]["arm_id"], "no_count_reason": _arm_no_count_reason(arm, by_code, reason),
                 "no_count_count": 1, "selected_symbols": arm["selected_symbols"]}
                for arm in question["arms"]
            ],
        }
    arms = []
    for arm in question["arms"]:
        arm_data = dict(arm)
        arm_data["decision_date"] = decision_date
        outcome, counts = _position_outcomes(arm=arm_data, candidates=candidate_by_code,
                                             price_data_through=capture["payload"]["run_identity"]["price_data_through"],
                                             date_pos=date_pos, dates=dates,
                                             lookup=lookup, limits=limits, governance=governance)
        outcome["risk_evidence"]["adjustment_coverage_pct"] = coverage["coverage_pct"]
        arms.append({"arm_id": arm["arm_definition"]["arm_id"], "selected_symbols": arm["selected_symbols"],
                     "outcome": outcome, "no_count_reason": None, "no_count_count": 0, **counts})
    return {"question_id": question["question_id"], "status": "settled", "reason": None,
            "adjustment_coverage": coverage, "arms": arms}


def _relevant_price_window_digest(capture: dict, *, dates: list[str], lookup: dict[tuple[str, str], dict],
                                  limits: dict[tuple[str, str], float]) -> str:
    """Digest only the selected-union rows and frozen outcome window, never unrelated cache growth."""
    decision_date = capture["decision_date"]
    date_pos = {date: index for index, date in enumerate(dates)}
    if decision_date not in date_pos:
        relevant_dates = []
    else:
        start = date_pos[decision_date]
        end = min(len(dates), start + max(HORIZONS) + 1)
        relevant_dates = dates[start:end]
    selected_union = sorted({
        code for question in capture["payload"]["questions"] for arm in question["arms"]
        for code in arm["selected_symbols"]
    })
    rows = {
        f"{code}|{trade_date}": lookup.get((code, trade_date))
        for code in selected_union for trade_date in relevant_dates
    }
    relevant_limits = {
        f"{code}|{trade_date}": limits[(code, trade_date)]
        for code in selected_union for trade_date in relevant_dates if (code, trade_date) in limits
    }
    return _digest({"selected_union": selected_union, "dates": relevant_dates, "rows": rows, "limits": relevant_limits})


def _outcome_payload(capture: dict, *, dates: list[str], lookup: dict[tuple[str, str], dict],
                     limits: dict[tuple[str, str], float], governance: dict) -> dict:
    questions = capture["payload"]["questions"]
    payload = {
        "capture_sha256": capture["payload"]["capture_sha256"],
        "forward_eligible": capture["payload"]["forward_eligible"],
        "price_window_digest": _relevant_price_window_digest(capture, dates=dates, lookup=lookup, limits=limits),
        "questions": [],
    }
    for question in questions:
        payload["questions"].append(_settle_question(question, capture, dates=dates, lookup=lookup,
                                                       limits=limits, governance=governance))
    payload["outcome_sha256"] = _digest({key: value for key, value in payload.items() if key != "outcome_sha256"})
    return payload


def _upsert_ledger(root: Path, capture: dict, outcome: dict, governance: dict) -> None:
    path = root / "ledger.json"
    ledger = _load_json(path)
    validate_v2_ledger(ledger)
    decision_date = capture["decision_date"]
    entries = [row for row in ledger["entries"] if row["decision_date"] != decision_date]
    for question in outcome["payload"]["questions"]:
        capture_question = next((row for row in capture["payload"]["questions"]
                                 if row["question_id"] == question["question_id"]), None)
        if not isinstance(capture_question, dict):
            raise ComparisonV2Error("v2 ledger cannot bind an outcome question to its capture batch")
        entries.append({
            "decision_date": decision_date,
            "question_id": question["question_id"],
            "experiment_batch_id": capture_question["experiment_batch_id"],
            "epoch_id": capture["epoch_id"],
            "forward_eligible": bool(capture["payload"]["forward_eligible"]),
            "outcome_status": question["status"],
            "capture_sha256": capture["payload"]["capture_sha256"],
            "outcome_sha256": outcome["payload"]["outcome_sha256"],
        })
    ledger["entries"] = sorted(entries, key=lambda row: (row["decision_date"], row["question_id"]))
    ledger["boundary"] = _boundary(governance)
    validate_v2_ledger(ledger)
    _atomic_write(path, ledger)


def settle_v2_from_daily_payload(*, root: str | Path, daily_payload: dict, governance: dict | None = None) -> dict:
    """Settle only frozen v2 captures from an existing cache payload; no fetch and no adjudication."""
    root = _private_root(root)
    governance = copy.deepcopy(governance or load_v2_governance())
    validate_v2_governance(governance)
    if not root.exists():
        return {"status": "no_v2_comparison_root", "updated_dates": []}
    _ensure_program(root, governance)
    dates, lookup, limits = _normalise_prices(daily_payload)
    updated = []
    weeks_root = root / "weeks"
    if not weeks_root.exists():
        return {"status": "no_v2_captures", "updated_dates": [], "production_unchanged": True}
    for day in sorted(path for path in weeks_root.iterdir() if path.is_dir() and path.name.isdigit()):
        capture_path = day / "capture.json"
        receipt_path = day / "source_receipt.json"
        if not capture_path.exists() or not receipt_path.exists():
            raise ComparisonV2Error(f"{day.name}: incomplete v2 capture cannot settle")
        capture = _load_json(capture_path)
        receipt = _load_json(receipt_path)
        _validate_source_receipt(root, capture, receipt)
        if not is_current_governed_capture(capture, governance=governance):
            continue
        outcome_payload = _outcome_payload(capture, dates=dates, lookup=lookup, limits=limits, governance=governance)
        outcome = {
            "schema_name": "a_short_factor_comparison_v2_weekly",
            "schema_version": SCHEMA_VERSION,
            "record_type": "outcome",
            "program_id": PROGRAM_ID,
            "decision_date": capture["decision_date"],
            "epoch_id": capture["epoch_id"],
            "payload": outcome_payload,
            "boundary": _boundary(governance),
        }
        validate_v2_weekly_record(outcome)
        outcome_path = day / "outcome.json"
        terminal = all(row["status"] in {"settled", "no_count"} for row in outcome_payload["questions"])
        if outcome_path.exists():
            existing = _load_json(outcome_path)
            validate_v2_weekly_record(existing)
            existing_terminal = all(row["status"] in {"settled", "no_count"}
                                    for row in existing["payload"].get("questions", []))
            if existing_terminal and existing != outcome:
                raise ComparisonV2Error(f"{day.name}: terminal v2 outcome source drifted")
            if existing_terminal:
                outcome = existing
            else:
                _atomic_write(outcome_path, outcome)
        else:
            _atomic_write(outcome_path, outcome)
        settlement = {
            "price_window_digest": outcome["payload"]["price_window_digest"],
            "outcome_sha256": outcome["payload"]["outcome_sha256"],
            "terminal": terminal,
        }
        receipt_payload = copy.deepcopy(receipt["payload"])
        old_settlement = receipt_payload.get("settlement")
        if old_settlement is not None and old_settlement != settlement and old_settlement.get("terminal"):
            raise ComparisonV2Error(f"{day.name}: terminal v2 source receipt drifted")
        receipt_payload["settlement"] = settlement
        updated_receipt = dict(receipt)
        updated_receipt["payload"] = receipt_payload
        validate_v2_weekly_record(updated_receipt)
        _atomic_write(receipt_path, updated_receipt)
        _upsert_ledger(root, capture, outcome, governance)
        updated.append(day.name)
    return {"status": "settled_from_existing_cache", "updated_dates": updated, "production_unchanged": True}


def build_v2_public_progress(*, root: str | Path | None, as_of: str,
                             governance: dict | None = None) -> dict:
    """Build P0's de-identified public progress; private symbols, prices and inputs never leave the ledger."""
    governance = copy.deepcopy(governance or load_v2_governance())
    validate_v2_governance(governance)
    as_of = _date(as_of)
    from engine.a_short_experiment_admission_registry import admission_snapshot, admissions
    registry = admissions()
    admission_questions = {
        f"p0_{question['question_id']}_{arm['arm_id']}": question["question_id"]
        for question in governance["questions"] for arm in question["arms"]
        if arm["kind"] == "challenger" and f"p0_{question['question_id']}_{arm['arm_id']}" in registry
    }
    admission_ids = tuple(admission_questions)
    signature = _canonical_contracts(governance)
    epoch_id, entries = None, []
    if root is not None:
        private_root = _private_root(root)
        ledger_path, epochs_path = private_root / "ledger.json", private_root / "epochs.json"
        if ledger_path.exists() and epochs_path.exists():
            ledger = _load_json(ledger_path)
            validate_v2_ledger(ledger)
            current = next((row for row in reversed(_load_json(epochs_path).get("epochs", []))
                            if row.get("orthogonality_signature") == signature), None)
            if current is not None:
                epoch_id = current["epoch_id"]
                entries = [row for row in ledger["entries"] if row["epoch_id"] == epoch_id and
                           row["forward_eligible"] and row["decision_date"] <= as_of]
    evidence = []
    for admission_id in admission_ids:
        admission = registry[admission_id]
        question_id = admission_questions[admission_id]
        rows = [row for row in entries if row["question_id"] == question_id]
        evidence.append({
            "admission_id": admission_id, "component_id": admission["component_id"],
            "baseline_arm_id": admission["baseline"]["arm_id"],
            "baseline_definition_sha256": admission["baseline"]["definition_sha256"],
            "candidate_arm_id": admission["candidate"]["arm_id"],
            "candidate_definition_sha256": admission["candidate"]["definition_sha256"],
            "forward_weeks": len({row["decision_date"] for row in rows}),
            "settled_weeks": len({row["decision_date"] for row in rows if row["outcome_status"] == "settled"}),
            "no_count_weeks": len({row["decision_date"] for row in rows if row["outcome_status"] == "no_count"}),
            "verdict": "not_adjudicated", "activation_permitted": False,
        })
    summary = {
        "schema_name": "a_short_factor_comparison_v2_public_progress", "schema_version": "1.0.0",
        "as_of": as_of, "current_epoch_id": epoch_id, "admissions": admission_snapshot(*admission_ids),
        "evidence": evidence,
        "source_hash": _digest([{key: row[key] for key in ("decision_date", "question_id", "epoch_id", "capture_sha256", "outcome_sha256")}
                                for row in entries]),
        "production_unchanged": True,
    }
    try:
        _validate_with_schema(summary, PUBLIC_PROGRESS_SCHEMA_PATH)
    except Exception as exc:
        raise ComparisonV2Error("v2 public progress schema invalid") from exc
    return summary
