"""Pure contracts for A-short experiment identity and manual baseline activation.

This module deliberately owns no research ledger and never opens or writes a
production configuration.  An automatic adjudicator can only construct an
advisory suggestion; a separately signed user receipt can only be turned into
an in-memory activation plan for a single already-admitted component.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADMISSION_SCHEMA_PATH = ROOT / "schemas" / "a_short_experiment_admission.schema.json"
RECEIPT_SCHEMA_PATH = ROOT / "schemas" / "a_short_experiment_decision_receipt.schema.json"


class ExperimentGovernanceError(ValueError):
    """Raised when an identity, receipt, or derived activation plan drifts."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_schema(value: dict, path: Path, label: str) -> None:
    try:
        import jsonschema

        jsonschema.validate(value, _schema(path))
    except Exception as exc:  # jsonschema's concrete exception types are optional at import time.
        raise ExperimentGovernanceError(f"{label} schema validation failed: {exc}") from exc


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ExperimentGovernanceError(f"{label} must be a lowercase sha256")
    return value


def _canonical_week(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ExperimentGovernanceError(f"{label} must be YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ExperimentGovernanceError(f"{label} must be a real calendar date") from exc
    return value


def _definition_digest(definition: object) -> str:
    if not isinstance(definition, dict):
        raise ExperimentGovernanceError("definition must be an object")
    return _digest(definition)


def _one_change_proof_payload(admission: dict) -> dict:
    return {
        "component_id": admission["component_id"],
        "effect_surface": admission["effect_surface"],
        "changed_component_ids": admission["one_change_only"]["changed_component_ids"],
        "unchanged_contract_sha256": admission["one_change_only"]["unchanged_contract_sha256"],
        "frozen_baseline_definition_sha256": admission["one_change_only"].get("frozen_baseline_definition_sha256"),
        "frozen_candidate_definition_sha256": admission["one_change_only"].get("frozen_candidate_definition_sha256"),
        "baseline_definition_sha256": admission["baseline"]["definition_sha256"],
        "candidate_definition_sha256": admission["candidate"]["definition_sha256"],
        "pit_forward_contract_sha256": admission["pit_forward_contract"]["contract_sha256"],
        "statistical_contract_sha256": admission["statistical_contract"]["definition_sha256"],
        "dependency_components": admission["dependency_components"],
    }


def _identity_payload(admission: dict) -> dict:
    payload = copy.deepcopy(admission)
    payload.pop("identity_sha256", None)
    return payload


def _receipt_payload(receipt: dict) -> dict:
    payload = copy.deepcopy(receipt)
    payload.pop("receipt_sha256", None)
    return payload


def _validate_trusted_arm_inventory(admission: dict) -> None:
    """Bind active admissions to their reviewed source inventory, not caller input.

    Generic draft fixtures intentionally have no registry entry.  Every active
    P0/P1/P2/P3/P5 experiment does: its two arm digests must match the
    separately reviewed registry inventory before it can be sealed or used.
    This prevents a caller from changing both an arm and its in-payload
    ``frozen_*`` anchor, then laundering the change by resealing.
    """
    try:
        from engine.a_short_experiment_admission_registry import trusted_arm_inventory
    except ImportError as exc:
        raise ExperimentGovernanceError("trusted admission inventory is unavailable") from exc
    expected = trusted_arm_inventory(admission.get("experiment_id"))
    if expected is None:
        return
    baseline_expected, candidate_expected = expected
    if (admission["baseline"]["definition_sha256"], admission["candidate"]["definition_sha256"]) != expected:
        raise ExperimentGovernanceError("one-change-only reviewed arm inventory drifted")
    anchors = admission["one_change_only"]
    if (anchors["frozen_baseline_definition_sha256"], anchors["frozen_candidate_definition_sha256"]) != (
            baseline_expected, candidate_expected):
        raise ExperimentGovernanceError("one-change-only reviewed inventory anchors drifted")


def seal_experiment_admission(admission: dict) -> dict:
    """Return a signed copy for fixtures and pre-admission construction only."""
    sealed = copy.deepcopy(admission)
    sealed["baseline"]["definition_sha256"] = _definition_digest(sealed["baseline"]["definition"])
    sealed["candidate"]["definition_sha256"] = _definition_digest(sealed["candidate"]["definition"])
    one_change = sealed["one_change_only"]
    # The arm inventory is set in the reviewed source admission, never by the
    # public resealing helper.  Otherwise an edited admission could delete the
    # anchors, reseal itself, and launder a second component change as a fresh
    # one-change contract.
    try:
        _require_sha256(one_change["frozen_baseline_definition_sha256"],
                        "one-change-only frozen baseline inventory")
        _require_sha256(one_change["frozen_candidate_definition_sha256"],
                        "one-change-only frozen candidate inventory")
    except (KeyError, TypeError) as exc:
        raise ExperimentGovernanceError("one-change-only pre-frozen arm inventory is required before sealing") from exc
    _validate_trusted_arm_inventory(sealed)
    sealed["statistical_contract"]["definition_sha256"] = _definition_digest(
        sealed["statistical_contract"]["definition"]
    )
    sealed["one_change_only"]["proof_sha256"] = _digest(_one_change_proof_payload(sealed))
    sealed["identity_sha256"] = _digest(_identity_payload(sealed))
    return sealed


def seal_user_decision_receipt(receipt: dict) -> dict:
    """Return a signed copy of a user-decision receipt without applying it."""
    sealed = copy.deepcopy(receipt)
    sealed["receipt_sha256"] = _digest(_receipt_payload(sealed))
    return sealed


def validate_experiment_admission(admission: dict) -> None:
    _validate_schema(admission, ADMISSION_SCHEMA_PATH, "experiment admission")
    for name in ("baseline", "candidate"):
        arm = admission[name]
        expected = _definition_digest(arm["definition"])
        if arm["definition_sha256"] != expected:
            raise ExperimentGovernanceError(f"{name} definition sha256 does not bind its definition")
    if admission["baseline"]["arm_id"] == admission["candidate"]["arm_id"]:
        raise ExperimentGovernanceError("baseline and candidate arm_id must differ")
    statistical_expected = _definition_digest(admission["statistical_contract"]["definition"])
    if admission["statistical_contract"]["definition_sha256"] != statistical_expected:
        raise ExperimentGovernanceError("statistical contract definition sha256 does not bind its definition")
    changed_components = admission["one_change_only"]["changed_component_ids"]
    if changed_components != [admission["component_id"]]:
        raise ExperimentGovernanceError("one-change-only proof must name exactly one component")
    frozen_baseline = admission["one_change_only"]["frozen_baseline_definition_sha256"]
    frozen_candidate = admission["one_change_only"]["frozen_candidate_definition_sha256"]
    if frozen_baseline != admission["baseline"]["definition_sha256"]:
        raise ExperimentGovernanceError("one-change-only baseline inventory drifted")
    if frozen_candidate != admission["candidate"]["definition_sha256"]:
        raise ExperimentGovernanceError("one-change-only candidate inventory drifted")
    _validate_trusted_arm_inventory(admission)
    expected_proof = _digest(_one_change_proof_payload(admission))
    if admission["one_change_only"]["proof_sha256"] != expected_proof:
        raise ExperimentGovernanceError("one-change-only proof sha256 drifted")
    dependency_ids = [row["component_id"] for row in admission["dependency_components"]]
    if len(dependency_ids) != len(set(dependency_ids)):
        raise ExperimentGovernanceError("dependency component ids must be unique")
    if admission["component_id"] in dependency_ids:
        raise ExperimentGovernanceError("a component cannot be its own dependency")
    if admission["experiment_id"] in admission["dependent_experiment_ids"]:
        raise ExperimentGovernanceError("a dependent experiment cannot self-reference the admitted experiment")
    expected_identity = _digest(_identity_payload(admission))
    if admission["identity_sha256"] != expected_identity:
        raise ExperimentGovernanceError("experiment identity sha256 drifted")


def _expected_receipt_binding(admission: dict, decision_kind: str) -> tuple[dict, dict]:
    if decision_kind == "promote":
        return admission["baseline"], admission["candidate"]
    if decision_kind == "rollback":
        return admission["candidate"], admission["baseline"]
    raise ExperimentGovernanceError("accepted receipt must be a promote or rollback")


def validate_user_decision_receipt(receipt: dict, *, admission: dict) -> None:
    validate_experiment_admission(admission)
    _validate_schema(receipt, RECEIPT_SCHEMA_PATH, "user decision receipt")
    if receipt["receipt_sha256"] != _digest(_receipt_payload(receipt)):
        raise ExperimentGovernanceError("user decision receipt sha256 drifted")
    if receipt["admission_identity_sha256"] != admission["identity_sha256"]:
        raise ExperimentGovernanceError("receipt admission identity sha256 does not bind the admitted contract")
    for field in ("experiment_id", "component_id", "allowed_configuration_path"):
        if receipt[field] != admission[field]:
            raise ExperimentGovernanceError(f"receipt {field} does not bind the admitted experiment")
    _require_sha256(receipt["adjudication_sha256"], "adjudication_sha256")
    decision_week = _canonical_week(receipt["decision_canonical_week"], "decision_canonical_week")
    if receipt["decision"] != "accepted":
        if receipt["candidate_arm_id"] != admission["candidate"]["arm_id"] or \
                receipt["old_baseline_definition_sha256"] != admission["baseline"]["definition_sha256"] or \
                receipt["new_baseline_definition_sha256"] != admission["candidate"]["definition_sha256"]:
            raise ExperimentGovernanceError("non-accepted receipt must still bind the admitted candidate and baselines")
        return
    effective_week = _canonical_week(receipt["effective_from_canonical_week"], "effective_from_canonical_week")
    if effective_week <= decision_week:
        raise ExperimentGovernanceError("effective_from_canonical_week must be after decision_canonical_week")
    old_arm, new_arm = _expected_receipt_binding(admission, receipt["decision_kind"])
    if receipt["candidate_arm_id"] != new_arm["arm_id"]:
        raise ExperimentGovernanceError("receipt candidate arm does not bind the accepted component arm")
    if receipt["old_baseline_definition_sha256"] != old_arm["definition_sha256"] or \
            receipt["new_baseline_definition_sha256"] != new_arm["definition_sha256"]:
        raise ExperimentGovernanceError("receipt old/new baseline digests do not bind the accepted change")
    if receipt["decision_kind"] == "promote" and receipt["supersedes_receipt_id"] is not None:
        raise ExperimentGovernanceError("a first promotion cannot supersede a prior receipt")
    if receipt["decision_kind"] == "rollback" and not receipt["supersedes_receipt_id"]:
        raise ExperimentGovernanceError("a rollback requires a distinct prior user receipt")


def validate_receipt_collection(receipts: list[dict], *, admission: dict) -> None:
    if not isinstance(receipts, list):
        raise ExperimentGovernanceError("receipt collection must be a list")
    ids: set[str] = set()
    accepted_effective_weeks: set[tuple[str, str]] = set()
    receipt_by_id: dict[str, dict] = {}
    for receipt in receipts:
        validate_user_decision_receipt(receipt, admission=admission)
        receipt_id = receipt["receipt_id"]
        if receipt_id in ids:
            raise ExperimentGovernanceError("duplicate receipt_id is not allowed")
        ids.add(receipt_id)
        receipt_by_id[receipt_id] = receipt
        if receipt["decision"] == "accepted":
            key = (receipt["component_id"], str(receipt["effective_from_canonical_week"]))
            if key in accepted_effective_weeks:
                raise ExperimentGovernanceError("duplicate accepted component receipt for an effective week")
            accepted_effective_weeks.add(key)
    for receipt in receipts:
        if receipt["decision_kind"] == "rollback":
            predecessor = receipt_by_id.get(str(receipt["supersedes_receipt_id"]))
            if predecessor is None or predecessor["decision"] != "accepted":
                raise ExperimentGovernanceError("rollback must supersede an accepted prior user receipt")


def build_adjudication_suggestion(admission: dict, *, adjudication_sha256: str) -> dict:
    """Create advisory-only output; it has no configuration path or write operation."""
    validate_experiment_admission(admission)
    _require_sha256(adjudication_sha256, "adjudication_sha256")
    return {
        "experiment_id": admission["experiment_id"],
        "component_id": admission["component_id"],
        "candidate_arm_id": admission["candidate"]["arm_id"],
        "adjudication_sha256": adjudication_sha256,
        "recommendation": (
            "user_decision_required"
            if admission["track_mode"] == "switchable"
            else "diagnostic_only_no_baseline_change"
        ),
        "advisory_only": True,
        "automatic_production_config_write": False,
    }


def _arm_baseline(arm: dict) -> dict:
    return {"arm_id": arm["arm_id"], "definition_sha256": arm["definition_sha256"]}


def build_baseline_activation_plan(admission: dict, receipt: dict, *, current_baselines: dict,
                                   prior_receipts: list[dict]) -> dict:
    """Derive a single-component, forward-only plan without changing any configuration."""
    validate_user_decision_receipt(receipt, admission=admission)
    if admission["track_mode"] != "switchable":
        raise ExperimentGovernanceError("diagnostic-only admission cannot create a baseline activation plan")
    validate_receipt_collection([*prior_receipts, receipt], admission=admission)
    if receipt["decision"] != "accepted":
        raise ExperimentGovernanceError("only an accepted user receipt may create an activation plan")
    component_id = admission["component_id"]
    current = current_baselines.get(component_id)
    if not isinstance(current, dict) or set(current) != {"arm_id", "definition_sha256"}:
        raise ExperimentGovernanceError("current baseline is unavailable or malformed")
    expected_old, expected_new = _expected_receipt_binding(admission, receipt["decision_kind"])
    if current != _arm_baseline(expected_old):
        raise ExperimentGovernanceError("current component baseline does not match the user receipt old baseline")
    unchanged = {key: copy.deepcopy(value) for key, value in current_baselines.items() if key != component_id}
    return {
        "schema_name": "a_short_experiment_baseline_activation_plan",
        "schema_version": "1.0.0",
        "experiment_id": admission["experiment_id"],
        "receipt_id": receipt["receipt_id"],
        "effective_from_canonical_week": receipt["effective_from_canonical_week"],
        "component_replacement": {
            "component_id": component_id,
            "old_baseline": _arm_baseline(expected_old),
            "new_baseline": _arm_baseline(expected_new),
        },
        "shadow_baseline": _arm_baseline(expected_old),
        "unchanged_component_baselines": unchanged,
        "epoch_restarts": [
            {"experiment_id": experiment_id, "reason": "upstream_component_baseline_changed"}
            for experiment_id in admission["dependent_experiment_ids"]
        ],
        "configuration_change": {
            "allowed_configuration_path": admission["allowed_configuration_path"],
            "manual_user_decision_receipt_id": receipt["receipt_id"],
            "automatic_write": False,
        },
        "historical_evidence_rewrite": False,
        "boundary": {
            "automatic_adjudication_recommendation_only": True,
            "automatic_production_config_write": False,
        },
    }


def validate_baseline_activation_plan(plan: dict, *, admission: dict, receipt: dict) -> None:
    validate_user_decision_receipt(receipt, admission=admission)
    if admission["track_mode"] != "switchable":
        raise ExperimentGovernanceError("diagnostic-only admission cannot validate a baseline activation plan")
    expected_keys = {
        "schema_name", "schema_version", "experiment_id", "receipt_id", "effective_from_canonical_week",
        "component_replacement", "shadow_baseline", "unchanged_component_baselines", "epoch_restarts",
        "configuration_change", "historical_evidence_rewrite", "boundary",
    }
    if not isinstance(plan, dict) or set(plan) != expected_keys:
        raise ExperimentGovernanceError("activation plan keys drifted")
    if plan["schema_name"] != "a_short_experiment_baseline_activation_plan" or plan["schema_version"] != "1.0.0":
        raise ExperimentGovernanceError("activation plan identity drifted")
    if plan["experiment_id"] != admission["experiment_id"] or plan["receipt_id"] != receipt["receipt_id"]:
        raise ExperimentGovernanceError("activation plan receipt binding drifted")
    if plan["effective_from_canonical_week"] != receipt["effective_from_canonical_week"]:
        raise ExperimentGovernanceError("activation plan effective week drifted")
    expected_old, expected_new = _expected_receipt_binding(admission, receipt["decision_kind"])
    replacement = plan["component_replacement"]
    if not isinstance(replacement, dict) or set(replacement) != {"component_id", "old_baseline", "new_baseline"} or \
            replacement["component_id"] != admission["component_id"] or \
            replacement["old_baseline"] != _arm_baseline(expected_old) or \
            replacement["new_baseline"] != _arm_baseline(expected_new):
        raise ExperimentGovernanceError("activation plan may replace only the admitted component")
    if plan["shadow_baseline"] != _arm_baseline(expected_old):
        raise ExperimentGovernanceError("activation plan must retain the old baseline as shadow")
    if admission["component_id"] in plan["unchanged_component_baselines"]:
        raise ExperimentGovernanceError("activation plan cannot duplicate the replaced component as unchanged")
    expected_restarts = [
        {"experiment_id": experiment_id, "reason": "upstream_component_baseline_changed"}
        for experiment_id in admission["dependent_experiment_ids"]
    ]
    if plan["epoch_restarts"] != expected_restarts:
        raise ExperimentGovernanceError("activation plan must restart every dependent experiment epoch restarts")
    if plan["configuration_change"] != {
        "allowed_configuration_path": admission["allowed_configuration_path"],
        "manual_user_decision_receipt_id": receipt["receipt_id"],
        "automatic_write": False,
    }:
        raise ExperimentGovernanceError("activation plan configuration boundary drifted")
    if plan["historical_evidence_rewrite"] is not False or plan["boundary"] != {
        "automatic_adjudication_recommendation_only": True,
        "automatic_production_config_write": False,
    }:
        raise ExperimentGovernanceError("activation plan boundary drifted")


def baseline_for_canonical_week(plan: dict, canonical_week: str) -> dict:
    """Select a baseline for one week without mutating historical evidence or config."""
    week = _canonical_week(canonical_week, "canonical_week")
    effective_week = _canonical_week(plan.get("effective_from_canonical_week"), "effective_from_canonical_week")
    replacement = plan.get("component_replacement")
    if not isinstance(replacement, dict) or "old_baseline" not in replacement or "new_baseline" not in replacement:
        raise ExperimentGovernanceError("activation plan replacement is malformed")
    return copy.deepcopy(replacement["new_baseline"] if week >= effective_week else replacement["old_baseline"])
