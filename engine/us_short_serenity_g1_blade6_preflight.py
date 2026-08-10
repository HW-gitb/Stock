"""Offline G1/Blade6 readiness preflight for the Serenity quality gate.

This is only a downstream identity check.  It never creates a Blade6
preregistration, enables an effect flag, calls a provider/model, or changes a
selection/action consumer.  A real quality gate and an explicitly stored G1
decision are both required before the result can say that Blade6 may start.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_g1_blade6_preflight.schema.json"
GATE_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_quality_gate_result.schema.json"
SCHEMA_NAME = "us_short_serenity_g1_blade6_preflight"
SCHEMA_VERSION = "1.0.0"
ROUTE = "theme_fit_score_to_selected_tickers"
EFFECT_BOUNDARY = {
    "scoring_eligible": False,
    "top15_effect_enabled": False,
    "operation_advice_effect_enabled": False,
    "provider_calls_performed": False,
    "network_access_performed": False,
    "preregistration_created": False,
    "blade6_entered": False,
}


class SerenityG1Blade6PreflightError(ValueError):
    """The downstream quality-gate/G1 identity is incomplete or inconsistent."""


def _read_object(path: Path, *, label: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SerenityG1Blade6PreflightError(f"{label} is unreadable") from exc
    if type(value) is not dict:
        raise SerenityG1Blade6PreflightError(f"{label} must be a JSON object")
    return value


def _validate(value: Mapping[str, Any], schema_path: Path, *, label: str) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SerenityG1Blade6PreflightError(f"{label} schema is unavailable") from exc
    errors = sorted(Draft7Validator(schema).iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        raise SerenityG1Blade6PreflightError(f"{label} schema rejected: {errors[0].message}")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _blocking_preflight(
    *,
    decision_date: str,
    generated_at: str,
    quality_gate_result_id: str | None,
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision_date": decision_date,
        "status": "blocked",
        "quality_gate_result_id": quality_gate_result_id,
        "g1_decision_id": None,
        "selected_route": None,
        "blocking_reasons": reasons,
        "effects": dict(EFFECT_BOUNDARY),
    }


def run_g1_blade6_preflight(
    *,
    quality_gate_path: Path,
    g1_decision_path: Path,
    output_path: Path,
    decision_date: str,
    generated_at: str,
) -> dict[str, Any]:
    """Validate the exact quality gate and optional G1 decision for future use."""
    gate = _read_object(Path(quality_gate_path), label="quality gate result")
    reasons: list[str] = []
    gate_id: str | None = None
    if gate is None:
        reasons.append("quality_gate_result_unavailable")
    else:
        try:
            _validate(gate, GATE_SCHEMA_PATH, label="quality gate result")
        except SerenityG1Blade6PreflightError as exc:
            reasons.append("quality_gate_result_invalid")
        else:
            gate_id = gate.get("quality_gate_result_id")
            if gate.get("cohort_id") is None:
                reasons.append("quality_gate_cohort_unavailable")
            if gate.get("verdict") != "quality_gate_pass" or not isinstance(gate_id, str):
                reasons.append("quality_gate_not_passed")

    g1 = _read_object(Path(g1_decision_path), label="G1 decision")
    if g1 is None:
        reasons.append("g1_decision_unavailable")
    else:
        expected = {
            "schema_name": "us_short_serenity_g1_decision",
            "schema_version": "1.0.0",
            "decision_date": decision_date,
            "decision": "open_effect_experiment",
            "selected_route": ROUTE,
            "effect_experiment_enabled": True,
            "operation_advice_effect_enabled": False,
        }
        for key, expected_value in expected.items():
            if g1.get(key) != expected_value:
                reasons.append(f"g1_{key}_mismatch")
        g1_id = g1.get("g1_decision_id")
        if not isinstance(g1_id, str) or not g1_id.startswith("serenity_g1_decision:"):
            reasons.append("g1_decision_id_invalid")
        if gate_id is None or g1.get("quality_gate_result_id") != gate_id:
            reasons.append("g1_quality_gate_binding_mismatch")

    if reasons:
        result = _blocking_preflight(
            decision_date=decision_date,
            generated_at=generated_at,
            quality_gate_result_id=gate_id,
            reasons=sorted(set(reasons)),
        )
    else:
        result = {
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "decision_date": decision_date,
            "status": "ready_for_blade6_preregistration",
            "quality_gate_result_id": gate_id,
            "g1_decision_id": g1["g1_decision_id"],
            "selected_route": ROUTE,
            "blocking_reasons": [],
            "effects": dict(EFFECT_BOUNDARY),
        }
    _validate(result, SCHEMA_PATH, label="G1/Blade6 preflight")
    _write_json(Path(output_path), result)
    return result


__all__ = [
    "EFFECT_BOUNDARY",
    "ROUTE",
    "SCHEMA_PATH",
    "SerenityG1Blade6PreflightError",
    "run_g1_blade6_preflight",
]
