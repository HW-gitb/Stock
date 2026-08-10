"""Offline Blade5 quality-forward ledger for the US-short Serenity shadow.

This module observes one frozen Blade3 annotation and an explicitly supplied
local review packet.  It records only judgment-shaped quality observations and
keeps cohorts separate when any identity-affecting version changes.  The
existing Blade4 consumer is used for the advisory shadow/report surface, but
no quality result is allowed to reach scoring, selection, action, sizing, or
provider execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft7Validator

from engine import us_short_serenity_shadow_consumers as shadow_consumer


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "presets" / "us_short_serenity_quality_forward_policy_v0.1.0.json"
POLICY_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_quality_forward_policy.schema.json"
REVIEW_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_quality_review.schema.json"
OBSERVATION_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_quality_forward_observation.schema.json"
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_quality_forward_ledger.schema.json"
GATE_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_quality_gate_result.schema.json"

SCHEMA_NAME = "us_short_serenity_quality_forward_observation"
SCHEMA_VERSION = "1.0.0"
QUALITY_POLICY_VERSION = "serenity_quality_policy_v0.1.0"
REVIEW_SCHEMA_NAME = "us_short_serenity_quality_review"
REVIEW_SCHEMA_VERSION = "1.0.0"
CONSUMER_VERSION = shadow_consumer.CONSUMER_VERSION
METRIC_IDS = (
    "claim_binding_integrity",
    "review_consistency",
    "falsifier_observability",
    "horizon_judgment",
    "weak_or_contradicted_discrimination",
)
IDENTITY_KEYS = (
    "annotation_id",
    "schema_version",
    "rubric_version",
    "upstream_decision_result_id",
    "upstream_policy_version",
    "upstream_decision_date",
)
COHORT_DIMENSION_KEYS = (
    "annotation_schema_version",
    "rubric_version",
    "consumer_version",
    "upstream_policy_version",
)
EFFECT_BOUNDARY = {
    "scoring_eligible": False,
    "top15_effect_enabled": False,
    "operation_advice_effect_enabled": False,
    "provider_calls_performed": False,
    "network_access_performed": False,
    "main_task_should_abort": False,
}
_MISSING = object()


class SerenityQualityForwardError(ValueError):
    """A local quality-forward artifact is malformed or conflicts with a frozen record."""


def _read_object(path: Path, *, label: str) -> dict[str, Any] | object:
    if not path.is_file():
        return _MISSING
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SerenityQualityForwardError(f"{label} is unreadable") from exc
    if type(value) is not dict:
        raise SerenityQualityForwardError(f"{label} must be a JSON object")
    return value


def _read_schema(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SerenityQualityForwardError(f"{label} schema is unavailable") from exc
    if type(value) is not dict:
        raise SerenityQualityForwardError(f"{label} schema must be an object")
    return value


def _validate_payload(payload: Mapping[str, Any], schema_path: Path, *, label: str) -> None:
    schema = _read_schema(schema_path, label=label)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.absolute_path))
    if errors:
        raise SerenityQualityForwardError(f"{label} schema rejected: {errors[0].message}")


def load_quality_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    """Load the one frozen policy; callers cannot select a different version silently."""
    value = _read_object(Path(path), label="quality policy")
    if value is _MISSING:
        raise SerenityQualityForwardError("quality policy is missing")
    assert isinstance(value, dict)
    _validate_payload(value, POLICY_SCHEMA_PATH, label="quality policy")
    if tuple(item["metric_id"] for item in value["metrics"]) != METRIC_IDS:
        raise SerenityQualityForwardError("quality policy metric order is not the frozen order")
    return value


def _parse_datetime(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise SerenityQualityForwardError(f"{label} must be RFC3339 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SerenityQualityForwardError(f"{label} must be RFC3339 text") from exc
    if parsed.tzinfo is None:
        raise SerenityQualityForwardError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _date(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise SerenityQualityForwardError(f"{label} must be YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise SerenityQualityForwardError(f"{label} must be a real date") from exc
    return value


def _safe_error(code: str, exc: Exception) -> dict[str, str]:
    message = " ".join(str(exc).replace("\r", " ").replace("\n", " ").split())[:300]
    return {"code": code, "message": message or type(exc).__name__}


def _identity_from_annotation(annotation: Mapping[str, Any]) -> dict[str, Any]:
    identity = annotation.get("identity_envelope")
    if not isinstance(identity, Mapping):
        raise SerenityQualityForwardError("annotation identity_envelope is missing")
    try:
        result = {
            "annotation_id": annotation["annotation_id"],
            "schema_version": annotation["schema_version"],
            "rubric_version": identity["rubric_version"],
            "upstream_decision_result_id": identity["upstream_decision_result_id"],
            "upstream_policy_version": identity["upstream_policy_version"],
            "upstream_decision_date": identity["upstream_decision_date"],
        }
    except KeyError as exc:
        raise SerenityQualityForwardError("annotation identity is incomplete") from exc
    if any(not isinstance(value, str) or not value for value in result.values()):
        raise SerenityQualityForwardError("annotation identity contains a blank value")
    _date(result["upstream_decision_date"], label="upstream_decision_date")
    return result


def _cohort_dimensions(identity: Mapping[str, Any]) -> dict[str, str]:
    return {
        "annotation_schema_version": str(identity["schema_version"]),
        "rubric_version": str(identity["rubric_version"]),
        "consumer_version": CONSUMER_VERSION,
        "upstream_policy_version": str(identity["upstream_policy_version"]),
    }


def _cohort_id(dimensions: Mapping[str, str]) -> str:
    return "serenity_quality_cohort:" + ":".join(dimensions[key] for key in COHORT_DIMENSION_KEYS)


def _empty_metric_rows(*, reason: str) -> list[dict[str, Any]]:
    return [
        {
            "metric_id": metric_id,
            "verdict": "not_evaluable",
            "rationale": reason,
            "evidence_ref_ids": ["quality:observation_not_evaluable"],
        }
        for metric_id in METRIC_IDS
    ]


def _metric_rows(value: Any, *, label: str) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) != len(METRIC_IDS):
        raise SerenityQualityForwardError(f"{label} must contain the five frozen metrics")
    rows = [dict(item) for item in value if isinstance(item, Mapping)]
    if len(rows) != len(METRIC_IDS) or tuple(row.get("metric_id") for row in rows) != METRIC_IDS:
        raise SerenityQualityForwardError(f"{label} metric order or identity drifted")
    for row in rows:
        if row.get("verdict") not in {"pass", "fail", "not_evaluable"}:
            raise SerenityQualityForwardError(f"{label} contains an unknown verdict")
        if not isinstance(row.get("rationale"), str) or not row["rationale"].strip():
            raise SerenityQualityForwardError(f"{label} contains a blank rationale")
        refs = row.get("evidence_ref_ids")
        if type(refs) is not list or not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            raise SerenityQualityForwardError(f"{label} contains no usable evidence reference")
    return rows


def _empty_ledger() -> dict[str, Any]:
    return {
        "schema_name": "us_short_serenity_quality_forward_ledger",
        "schema_version": SCHEMA_VERSION,
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "cross_cohort_aggregation_allowed": False,
        "cohorts": [],
        "effects": dict(EFFECT_BOUNDARY),
    }


def _load_ledger(path: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    value = _read_object(path, label="quality ledger")
    if value is _MISSING:
        return _empty_ledger()
    assert isinstance(value, dict)
    _validate_payload(value, LEDGER_SCHEMA_PATH, label="quality ledger")
    if value["quality_policy_version"] != policy["quality_policy_version"]:
        raise SerenityQualityForwardError("quality ledger policy version is not the frozen policy")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _validate_review(
    review: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    decision_date: str,
    policy: Mapping[str, Any],
) -> tuple[str, str, list[dict[str, Any]]]:
    _validate_payload(review, REVIEW_SCHEMA_PATH, label="quality review")
    if review["decision_date"] != decision_date:
        raise SerenityQualityForwardError("quality review decision_date does not match the weekly observation")
    if review["quality_policy_version"] != policy["quality_policy_version"]:
        raise SerenityQualityForwardError("quality review policy version is not the frozen policy")
    if review["consumer_version"] != CONSUMER_VERSION:
        raise SerenityQualityForwardError("quality review consumer version is not the frozen consumer")
    if dict(review["annotation_identity"]) != dict(identity):
        raise SerenityQualityForwardError("quality review annotation identity does not match the annotation")
    _parse_datetime(review["reviewed_at"], label="reviewed_at")
    rows = _metric_rows(review["metrics"], label="quality review")
    return review["reviewer_kind"], review["reviewed_at"], rows


def _record_for(
    *,
    decision_date: str,
    identity: Mapping[str, Any],
    dimensions: Mapping[str, str],
    reviewer_kind: str,
    reviewed_at: str,
    metrics: list[dict[str, Any]],
    cohort: str,
) -> dict[str, Any]:
    return {
        "record_id": f"serenity_quality_record:{cohort}:{decision_date}",
        "decision_date": decision_date,
        "annotation_identity": dict(identity),
        "consumer_version": CONSUMER_VERSION,
        "dimensions": dict(dimensions),
        "reviewer_kind": reviewer_kind,
        "reviewed_at": reviewed_at,
        "metrics": metrics,
        "eligible": True,
    }


def _merge_record(ledger: dict[str, Any], record: dict[str, Any], cohort_id: str, dimensions: Mapping[str, str]) -> str:
    cohort = next((item for item in ledger["cohorts"] if item["cohort_id"] == cohort_id), None)
    if cohort is None:
        cohort = {
            "cohort_id": cohort_id,
            "dimensions": dict(dimensions),
            "records": [],
            "quality_gate_result_id": None,
        }
        ledger["cohorts"].append(cohort)
    elif cohort["dimensions"] != dict(dimensions):
        raise SerenityQualityForwardError("quality cohort dimensions conflict with its frozen cohort id")
    same_date = [item for item in cohort["records"] if item["decision_date"] == record["decision_date"]]
    if same_date:
        if len(same_date) == 1 and same_date[0] == record:
            return "idempotent"
        raise SerenityQualityForwardError("same decision_date already has a different quality record")
    cohort["records"].append(record)
    cohort["records"].sort(key=lambda item: item["decision_date"])
    return "added"


def _gate_for(
    ledger: Mapping[str, Any],
    *,
    cohort_id: str | None,
    observed_at: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    cohort = next((item for item in ledger["cohorts"] if item["cohort_id"] == cohort_id), None) if cohort_id else None
    records = list(cohort["records"]) if cohort is not None else []
    minimum_weeks = int(policy["frozen_window"]["minimum_eligible_weeks"])
    minimum_evaluable_rate = float(policy["frozen_window"]["minimum_evaluable_rate"])
    minimum_pass_rate = float(policy["frozen_window"]["minimum_pass_rate"])
    metric_assessments: list[dict[str, Any]] = []
    for metric_id in METRIC_IDS:
        rows = [next(row for row in record["metrics"] if row["metric_id"] == metric_id) for record in records]
        evaluable = [row for row in rows if row["verdict"] in {"pass", "fail"}]
        passed = sum(row["verdict"] == "pass" for row in evaluable)
        evaluable_rate = len(evaluable) / len(records) if records else 0.0
        pass_rate = passed / len(evaluable) if evaluable else 0.0
        if len(records) < minimum_weeks or evaluable_rate < minimum_evaluable_rate:
            verdict = "not_ready"
        elif pass_rate < minimum_pass_rate:
            verdict = "below_threshold"
        else:
            verdict = "pass"
        metric_assessments.append({
            "metric_id": metric_id,
            "evaluable_count": len(evaluable),
            "evaluable_rate": evaluable_rate,
            "pass_count": passed,
            "pass_rate": pass_rate,
            "verdict": verdict,
        })
    if len(records) < minimum_weeks or any(row["verdict"] == "not_ready" for row in metric_assessments):
        verdict = "continue_accumulating"
    elif any(row["verdict"] == "below_threshold" for row in metric_assessments):
        verdict = "quality_below_threshold"
    else:
        verdict = "quality_gate_pass"
    record_ids = [record["record_id"] for record in records]
    start_date = records[0]["decision_date"] if records else None
    end_date = records[-1]["decision_date"] if records else None
    result_id = None
    if verdict == "quality_gate_pass":
        result_id = f"serenity_quality_gate:{policy['quality_policy_version']}:{cohort_id}:{start_date}:{end_date}:{len(records)}"
    dimensions = dict(cohort["dimensions"]) if cohort is not None else None
    gate = {
        "schema_name": "us_short_serenity_quality_gate_result",
        "schema_version": SCHEMA_VERSION,
        "generated_at": observed_at,
        "quality_policy_version": policy["quality_policy_version"],
        "cohort_id": cohort_id,
        "cohort_dimensions": dimensions,
        "verdict": verdict,
        "quality_gate_result_id": result_id,
        "window": {
            "start_decision_date": start_date,
            "end_decision_date": end_date,
            "eligible_week_count": len(records),
            "record_ids": record_ids,
        },
        "metric_assessments": metric_assessments,
        "thresholds": dict(policy["frozen_window"]),
        "effects": dict(EFFECT_BOUNDARY),
    }
    _validate_payload(gate, GATE_SCHEMA_PATH, label="quality gate result")
    return gate


def _observation(
    *,
    decision_date: str,
    observed_at: str,
    status: str,
    identity: Mapping[str, Any] | None,
    metrics: list[dict[str, Any]],
    annotation_present: bool,
    review_present: bool,
    shadow_status: str,
    error: dict[str, str] | None,
    report_block_delivered: bool | None = None,
    report_block_problem: str | None = None,
) -> dict[str, Any]:
    value = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "decision_date": decision_date,
        "observed_at": observed_at,
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "consumer_version": CONSUMER_VERSION,
        "status": status,
        "annotation_identity": dict(identity) if identity is not None else None,
        "metrics": metrics,
        "annotation_present": annotation_present,
        "review_present": review_present,
        "eligible": status == "eligible",
        "shadow_consumption_status": shadow_status,
        "report_overlay_available": shadow_status == "active",
        "report_block_delivered": report_block_delivered,
        "report_block_problem": report_block_problem,
        "effects": dict(EFFECT_BOUNDARY),
        "error": error,
    }
    _validate_payload(value, OBSERVATION_SCHEMA_PATH, label="quality observation")
    return value


def _result(
    *,
    decision_date: str,
    observed_at: str,
    status: str,
    observation: Mapping[str, Any],
    ledger: Mapping[str, Any],
    gate: Mapping[str, Any],
    shadow: Mapping[str, Any],
    artifacts: Mapping[str, Path],
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "stage": "serenity_quality_forward",
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": observed_at,
        "observed_at": observed_at,
        "decision_date": decision_date,
        "status": status,
        "main_task_should_abort": False,
        "validated_theme_count": 0,
        "boostable_ticker_count": 0,
        "effects": dict(EFFECT_BOUNDARY),
        "annotation_identity": observation.get("annotation_identity"),
        "observation": dict(observation),
        "ledger": dict(ledger),
        "quality_gate": dict(gate),
        "quality_gate_result_id": gate.get("quality_gate_result_id"),
        "shadow_consumption": dict(shadow),
        "artifacts": {key: str(path) for key, path in artifacts.items()},
        "error": error,
    }


def run_quality_forward(
    *,
    annotation_path: Path,
    review_path: Path,
    observation_path: Path,
    ledger_path: Path,
    gate_path: Path,
    decision_date: str,
    observed_at: str,
    root: Path = ROOT,
    now: datetime | None = None,
    policy_path: Path = POLICY_PATH,
) -> dict[str, Any]:
    """Run one offline weekly observation and persist its three state artifacts."""
    decision_date = _date(decision_date, label="decision_date")
    _parse_datetime(observed_at, label="observed_at")
    artifacts = {
        "observation": Path(observation_path),
        "ledger": Path(ledger_path),
        "quality_gate": Path(gate_path),
    }
    policy = load_quality_policy(policy_path)
    existing_ledger = _load_ledger(Path(ledger_path), policy)
    try:
        annotation_value = _read_object(Path(annotation_path), label="annotation")
        review_value = _read_object(Path(review_path), label="quality review")
    except SerenityQualityForwardError as exc:
        error = _safe_error("SERENITY_QUALITY_INPUT_REJECTED", exc)
        shadow = shadow_consumer.consume_serenity_annotation(None)
        observation = _observation(
            decision_date=decision_date,
            observed_at=observed_at,
            status="invalid_evidence",
            identity=None,
            metrics=_empty_metric_rows(reason="quality-forward input was unreadable"),
            annotation_present=Path(annotation_path).is_file(),
            review_present=Path(review_path).is_file(),
            shadow_status="sleeping",
            error=error,
        )
        gate = _gate_for(existing_ledger, cohort_id=None, observed_at=observed_at, policy=policy)
        _write_json(Path(observation_path), observation)
        if not Path(ledger_path).is_file():
            _write_json(Path(ledger_path), existing_ledger)
        _write_json(Path(gate_path), gate)
        return _result(
            decision_date=decision_date,
            observed_at=observed_at,
            status="invalid_evidence",
            observation=observation,
            ledger=existing_ledger,
            gate=gate,
            shadow=shadow,
            artifacts=artifacts,
            error=error,
        )
    if annotation_value is _MISSING:
        shadow = shadow_consumer.consume_serenity_annotation(None)
        gate = _gate_for(existing_ledger, cohort_id=None, observed_at=observed_at, policy=policy)
        observation = _observation(
            decision_date=decision_date,
            observed_at=observed_at,
            status="sleeping",
            identity=None,
            metrics=_empty_metric_rows(reason="annotation was not supplied for this week"),
            annotation_present=False,
            review_present=False,
            shadow_status="sleeping",
            error=None,
        )
        _write_json(Path(observation_path), observation)
        _write_json(Path(ledger_path), existing_ledger)
        _write_json(Path(gate_path), gate)
        return _result(
            decision_date=decision_date,
            observed_at=observed_at,
            status="sleeping",
            observation=observation,
            ledger=existing_ledger,
            gate=gate,
            shadow=shadow,
            artifacts=artifacts,
        )
    assert isinstance(annotation_value, dict)
    annotation = annotation_value
    try:
        identity = _identity_from_annotation(annotation)
        shadow = shadow_consumer.consume_serenity_annotation(annotation, root=Path(root), now=now)
        if shadow.get("status") != "active":
            raise SerenityQualityForwardError("annotation did not pass the Blade4 active shadow boundary")
        dimensions = _cohort_dimensions(identity)
        cohort_id = _cohort_id(dimensions)
    except (KeyError, TypeError, ValueError, SerenityQualityForwardError) as exc:
        shadow = shadow_consumer.consume_serenity_annotation(annotation if isinstance(annotation, Mapping) else {})
        error = _safe_error("SERENITY_ANNOTATION_REJECTED", exc)
        observation = _observation(
            decision_date=decision_date,
            observed_at=observed_at,
            status="invalid_evidence",
            identity=None,
            metrics=_empty_metric_rows(reason="annotation failed the frozen identity or shadow contract"),
            annotation_present=True,
            review_present=review_value is not _MISSING,
            shadow_status=str(shadow.get("status", "invalid_annotation")),
            error=error,
        )
        gate = _gate_for(existing_ledger, cohort_id=None, observed_at=observed_at, policy=policy)
        _write_json(Path(observation_path), observation)
        if not Path(ledger_path).is_file():
            _write_json(Path(ledger_path), existing_ledger)
        _write_json(Path(gate_path), gate)
        return _result(
            decision_date=decision_date,
            observed_at=observed_at,
            status="invalid_evidence",
            observation=observation,
            ledger=existing_ledger,
            gate=gate,
            shadow=shadow,
            artifacts=artifacts,
            error=error,
        )

    if review_value is _MISSING:
        observation = _observation(
            decision_date=decision_date,
            observed_at=observed_at,
            status="not_evaluable",
            identity=identity,
            metrics=_empty_metric_rows(reason="quality review was not supplied for this week"),
            annotation_present=True,
            review_present=False,
            shadow_status="active",
            error=None,
        )
        gate = _gate_for(existing_ledger, cohort_id=cohort_id, observed_at=observed_at, policy=policy)
        _write_json(Path(observation_path), observation)
        _write_json(Path(ledger_path), existing_ledger)
        _write_json(Path(gate_path), gate)
        return _result(
            decision_date=decision_date,
            observed_at=observed_at,
            status="not_evaluable",
            observation=observation,
            ledger=existing_ledger,
            gate=gate,
            shadow=shadow,
            artifacts=artifacts,
        )

    assert isinstance(review_value, dict)
    try:
        reviewer_kind, reviewed_at, metrics = _validate_review(
            review_value,
            identity=identity,
            decision_date=decision_date,
            policy=policy,
        )
        record = _record_for(
            decision_date=decision_date,
            identity=identity,
            dimensions=dimensions,
            reviewer_kind=reviewer_kind,
            reviewed_at=reviewed_at,
            metrics=metrics,
            cohort=cohort_id,
        )
        merge_status = _merge_record(existing_ledger, record, cohort_id, dimensions)
    except (KeyError, TypeError, ValueError, SerenityQualityForwardError) as exc:
        error = _safe_error("SERENITY_QUALITY_REVIEW_REJECTED", exc)
        observation = _observation(
            decision_date=decision_date,
            observed_at=observed_at,
            status="invalid_evidence",
            identity=identity,
            metrics=_empty_metric_rows(reason="quality review failed the frozen identity or metric contract"),
            annotation_present=True,
            review_present=True,
            shadow_status="active",
            error=error,
        )
        gate = _gate_for(existing_ledger, cohort_id=cohort_id, observed_at=observed_at, policy=policy)
        _write_json(Path(observation_path), observation)
        if not Path(ledger_path).is_file():
            _write_json(Path(ledger_path), existing_ledger)
        _write_json(Path(gate_path), gate)
        return _result(
            decision_date=decision_date,
            observed_at=observed_at,
            status="invalid_evidence",
            observation=observation,
            ledger=existing_ledger,
            gate=gate,
            shadow=shadow,
            artifacts=artifacts,
            error=error,
        )

    observation = _observation(
        decision_date=decision_date,
        observed_at=observed_at,
        status="eligible",
        identity=identity,
        metrics=metrics,
        annotation_present=True,
        review_present=True,
        shadow_status="active",
        error=None,
    )
    if merge_status == "added":
        _validate_payload(existing_ledger, LEDGER_SCHEMA_PATH, label="quality ledger")
        _write_json(Path(ledger_path), existing_ledger)
    elif not Path(ledger_path).is_file():
        _write_json(Path(ledger_path), existing_ledger)
    gate = _gate_for(existing_ledger, cohort_id=cohort_id, observed_at=observed_at, policy=policy)
    cohort = next(item for item in existing_ledger["cohorts"] if item["cohort_id"] == cohort_id)
    if cohort["quality_gate_result_id"] != gate["quality_gate_result_id"]:
        cohort["quality_gate_result_id"] = gate["quality_gate_result_id"]
        _validate_payload(existing_ledger, LEDGER_SCHEMA_PATH, label="quality ledger")
        _write_json(Path(ledger_path), existing_ledger)
    _write_json(Path(observation_path), observation)
    _write_json(Path(gate_path), gate)
    return _result(
        decision_date=decision_date,
        observed_at=observed_at,
        status="eligible",
        observation=observation,
        ledger=existing_ledger,
        gate=gate,
        shadow=shadow,
        artifacts=artifacts,
    )


__all__ = [
    "CONSUMER_VERSION",
    "EFFECT_BOUNDARY",
    "GATE_SCHEMA_PATH",
    "LEDGER_SCHEMA_PATH",
    "METRIC_IDS",
    "OBSERVATION_SCHEMA_PATH",
    "POLICY_PATH",
    "POLICY_SCHEMA_PATH",
    "QUALITY_POLICY_VERSION",
    "REVIEW_SCHEMA_PATH",
    "SerenityQualityForwardError",
    "load_quality_policy",
    "run_quality_forward",
]
