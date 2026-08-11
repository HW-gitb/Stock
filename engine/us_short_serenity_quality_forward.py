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

from engine import us_short_serenity_g1_blade6_preflight as g1_preflight
from engine import us_short_serenity_structural_theme_annotation as annotation_contract
from engine import us_short_serenity_shadow_consumers as shadow_consumer


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "presets" / "us_short_serenity_quality_forward_policy_v0.1.0.json"
POLICY_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_quality_forward_policy.schema.json"
REVIEW_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_quality_review.schema.json"
OBSERVATION_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_quality_forward_observation.schema.json"
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_quality_forward_ledger.schema.json"
GATE_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_quality_gate_result.schema.json"
G1_PREFLIGHT_SCHEMA_PATH = g1_preflight.SCHEMA_PATH

SCHEMA_NAME = "us_short_serenity_quality_forward_observation"
SCHEMA_VERSION = "1.0.0"
QUALITY_POLICY_VERSION = "serenity_quality_policy_v0.1.0"
REVIEW_SCHEMA_NAME = "us_short_serenity_quality_review"
REVIEW_SCHEMA_VERSION = "1.0.0"
CONSUMER_VERSION = shadow_consumer.CONSUMER_VERSION
PRODUCER_IDENTITY_VERSION = "serenity_annotation_producer_v0.1.0"
LEDGER_REJECTED_REASON_CODE = "SERENITY_QUALITY_LEDGER_REJECTED"
REVIEWER_IDENTITY_VERSION = "serenity_quality_reviewer_v0.1.0"
REVIEW_PROMPT_VERSION = "serenity_quality_reviewer_prompt_v0.1.0"
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
    "producer_identity_version",
    "annotation_prompt_version",
    "reviewer_identity_version",
    "review_prompt_version",
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
    if tuple(value["cohort_dimensions"]) != COHORT_DIMENSION_KEYS:
        raise SerenityQualityForwardError("quality policy cohort dimensions are not the frozen identity order")
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
            "annotation_author_kind": identity["annotation_author_kind"],
            "annotation_prompt_version": identity["prompt_or_protocol_id"],
            "producer_model_identity": identity["model_identity"],
        }
    except KeyError as exc:
        raise SerenityQualityForwardError("annotation identity is incomplete") from exc
    required_text = (
        "annotation_id",
        "schema_version",
        "rubric_version",
        "upstream_decision_result_id",
        "upstream_policy_version",
        "upstream_decision_date",
        "annotation_author_kind",
        "annotation_prompt_version",
    )
    if any(not isinstance(result[key], str) or not result[key] for key in required_text):
        raise SerenityQualityForwardError("annotation identity contains a blank value")
    if result["producer_model_identity"] is not None and not isinstance(result["producer_model_identity"], str):
        raise SerenityQualityForwardError("annotation producer model identity is malformed")
    _date(result["upstream_decision_date"], label="upstream_decision_date")
    return result


def _producer_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "identity_version": PRODUCER_IDENTITY_VERSION,
        "author_kind": identity["annotation_author_kind"],
        "prompt_version": identity["annotation_prompt_version"],
        "model_identity": identity["producer_model_identity"],
    }


def _reviewer_identity(review: Mapping[str, Any]) -> dict[str, Any]:
    value = review.get("reviewer_identity")
    if not isinstance(value, Mapping):
        raise SerenityQualityForwardError("quality review reviewer_identity is missing")
    try:
        result = {
            "identity_version": value["identity_version"],
            "reviewer_id": value["reviewer_id"],
            "model_identity": value["model_identity"],
            "prompt_version": value["prompt_version"],
        }
    except KeyError as exc:
        raise SerenityQualityForwardError("quality review reviewer_identity is incomplete") from exc
    if result["identity_version"] != REVIEWER_IDENTITY_VERSION:
        raise SerenityQualityForwardError("quality reviewer identity version drifted")
    if result["prompt_version"] != REVIEW_PROMPT_VERSION:
        raise SerenityQualityForwardError("quality reviewer prompt version drifted")
    if any(not isinstance(result[key], str) or not result[key].strip() for key in ("reviewer_id", "model_identity")):
        raise SerenityQualityForwardError("quality reviewer identity contains a blank value")
    return result


def _cohort_dimensions(
    identity: Mapping[str, Any],
    *,
    reviewer_identity: Mapping[str, Any],
) -> dict[str, str]:
    return {
        "annotation_schema_version": str(identity["schema_version"]),
        "rubric_version": str(identity["rubric_version"]),
        "consumer_version": CONSUMER_VERSION,
        "upstream_policy_version": str(identity["upstream_policy_version"]),
        "producer_identity_version": PRODUCER_IDENTITY_VERSION,
        "annotation_prompt_version": str(identity["annotation_prompt_version"]),
        "reviewer_identity_version": str(reviewer_identity["identity_version"]),
        "review_prompt_version": str(reviewer_identity["prompt_version"]),
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
        "pending_annotations": [],
        "closed_pending_annotations": [],
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
    producer_identity: Mapping[str, Any],
) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]]:
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
    reviewer_identity = _reviewer_identity(review)
    producer_model = producer_identity.get("model_identity")
    if isinstance(producer_model, str) and producer_model.strip() and reviewer_identity["model_identity"] == producer_model:
        raise SerenityQualityForwardError("quality review cannot be performed by the producer identity")
    rows = _metric_rows(review["metrics"], label="quality review")
    return review["reviewer_kind"], review["reviewed_at"], rows, reviewer_identity


def _record_for(
    *,
    decision_date: str,
    identity: Mapping[str, Any],
    dimensions: Mapping[str, str],
    reviewer_kind: str,
    producer_identity: Mapping[str, Any],
    reviewer_identity: Mapping[str, Any],
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
        "producer_identity": dict(producer_identity),
        "reviewer_identity": dict(reviewer_identity),
        "metrics": metrics,
        "eligible": True,
        "formal_count_eligible": (
            producer_identity.get("author_kind") == "llm"
            and isinstance(producer_identity.get("model_identity"), str)
            and bool(str(producer_identity["model_identity"]).strip())
            and isinstance(reviewer_identity.get("model_identity"), str)
            and bool(str(reviewer_identity["model_identity"]).strip())
            and producer_identity.get("model_identity") != reviewer_identity.get("model_identity")
        ),
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
    all_records = list(cohort["records"]) if cohort is not None else []
    records = [record for record in all_records if record.get("formal_count_eligible") is True]
    formal_blockers: list[str] = []
    if any(record.get("formal_count_eligible") is not True for record in all_records):
        formal_blockers.append("non_formal_record_excluded")
    if all_records and not records:
        formal_blockers.append("formal_identity_unavailable")
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
    if formal_blockers or len(records) < minimum_weeks or any(row["verdict"] == "not_ready" for row in metric_assessments):
        verdict = "continue_accumulating"
    elif any(row["verdict"] == "below_threshold" for row in metric_assessments):
        verdict = "quality_below_threshold"
    else:
        verdict = "quality_gate_pass"
    record_ids = [record["record_id"] for record in records]
    start_date = records[0]["decision_date"] if records else None
    end_date = records[-1]["decision_date"] if records else None
    result_id = None
    formal_count_ready = verdict == "quality_gate_pass" and not formal_blockers
    if formal_count_ready:
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
        "formal_count_ready": formal_count_ready,
        "formal_blockers": formal_blockers,
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
    producer_identity: Mapping[str, Any] | None = None,
    reviewer_identity: Mapping[str, Any] | None = None,
    formal_count_eligible: bool = False,
    settlement_status: str | None = None,
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
        "producer_identity": dict(producer_identity) if producer_identity is not None else None,
        "reviewer_identity": dict(reviewer_identity) if reviewer_identity is not None else None,
        "formal_count_eligible": formal_count_eligible,
        "settlement_status": settlement_status,
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
    g1_preflight: Mapping[str, Any] | None = None,
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
        "g1_blade6_preflight": dict(g1_preflight) if g1_preflight is not None else None,
        "shadow_consumption": dict(shadow),
        "artifacts": {key: str(path) for key, path in artifacts.items()},
        "error": error,
    }


def _default_g1_paths(gate_path: Path, decision_date: str) -> tuple[Path, Path]:
    base = Path(gate_path).parent
    return (
        base / "us_short_serenity_g1_decision.json",
        base / f"us_short_serenity_g1_blade6_preflight_{decision_date}.json",
    )


def _persist_gate_and_preflight(
    *,
    gate: Mapping[str, Any],
    gate_path: Path,
    g1_decision_path: Path,
    g1_preflight_path: Path,
    decision_date: str,
    observed_at: str,
) -> dict[str, Any]:
    _write_json(Path(gate_path), gate)
    return g1_preflight.run_g1_blade6_preflight(
        quality_gate_path=Path(gate_path),
        g1_decision_path=Path(g1_decision_path),
        output_path=Path(g1_preflight_path),
        decision_date=decision_date,
        generated_at=observed_at,
    )


def _safe_pending_name(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value or value in {".", ".."}:
        raise SerenityQualityForwardError(f"pending {label} is not a local file name")
    return value


def _pending_path(state_dir: Path, file_name: Any, *, label: str) -> Path:
    return Path(state_dir) / _safe_pending_name(file_name, label=label)


def _pending_for(
    *,
    decision_date: str,
    annotation_path: Path,
    review_path: Path,
    identity: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    return {
        "decision_date": decision_date,
        "annotation_file_name": _safe_pending_name(Path(annotation_path).name, label="annotation_file_name"),
        "review_file_name": _safe_pending_name(Path(review_path).name, label="review_file_name"),
        "annotation_identity": dict(identity),
        "producer_identity": _producer_identity(identity),
        "created_at": created_at,
        "status": "awaiting_review",
    }


def _pending_key(value: Mapping[str, Any]) -> tuple[str, str]:
    identity = value.get("annotation_identity")
    return str(value.get("decision_date")), str(identity.get("annotation_id")) if isinstance(identity, Mapping) else ""


def _merge_pending(ledger: dict[str, Any], pending: Mapping[str, Any]) -> str:
    key = _pending_key(pending)
    if any(_pending_key(item) == key for item in ledger["closed_pending_annotations"]):
        raise SerenityQualityForwardError("pending annotation was already closed and cannot be backfilled")
    same = [item for item in ledger["pending_annotations"] if _pending_key(item) == key]
    if same:
        if len(same) == 1 and dict(same[0]) == dict(pending):
            return "idempotent"
        raise SerenityQualityForwardError("same pending annotation identity already has a different target")
    if ledger["pending_annotations"]:
        raise SerenityQualityForwardError("multiple pending annotations would be created")
    ledger["pending_annotations"].append(dict(pending))
    return "added"


def _close_pending(
    ledger: dict[str, Any],
    pending: Mapping[str, Any],
    *,
    settlement_status: str,
    settled_at: str,
    reason_code: str,
    reviewer_identity: Mapping[str, Any] | None,
) -> None:
    key = _pending_key(pending)
    matches = [item for item in ledger["pending_annotations"] if _pending_key(item) == key]
    if len(matches) != 1:
        raise SerenityQualityForwardError("pending annotation settlement target is not unique")
    ledger["pending_annotations"] = [item for item in ledger["pending_annotations"] if _pending_key(item) != key]
    ledger["closed_pending_annotations"].append({
        "decision_date": pending["decision_date"],
        "annotation_identity": dict(pending["annotation_identity"]),
        "producer_identity": dict(pending["producer_identity"]),
        "settlement_status": settlement_status,
        "settled_at": settled_at,
        "reason_code": reason_code,
        "reviewer_identity": dict(reviewer_identity) if reviewer_identity is not None else None,
    })


def produce_annotation_for_week(
    *,
    annotation_path: Path,
    decision_date: str,
    soft_discovery_result: Mapping[str, Any] | None = None,
    annotation_payload: Mapping[str, Any] | None = None,
    root: Path = ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate or atomically publish one caller-supplied Blade3 annotation.

    The producer deliberately does not synthesize semantic content or call a
    model/provider.  A missing upstream receipt or payload leaves the week in
    a recoverable, zero-effect checkpoint state.
    """
    decision_date = _date(decision_date, label="decision_date")
    path = Path(annotation_path)
    effects = dict(EFFECT_BOUNDARY)
    upstream_identity = None
    if isinstance(soft_discovery_result, Mapping):
        for key in ("upstream_identity", "identity_envelope", "upstream"):
            candidate = soft_discovery_result.get(key)
            if isinstance(candidate, Mapping):
                upstream_identity = {
                    name: candidate.get(name)
                    for name in (
                        "upstream_input_packet_id", "upstream_decision_result_id",
                        "upstream_policy_version", "upstream_decision_date",
                    )
                }
                break
        if soft_discovery_result.get("decision_date") not in {None, decision_date}:
            return {
                "stage": "serenity_annotation_producer", "status": "invalid_evidence",
                "decision_date": decision_date, "checkpoint_status": "annotation_rejected",
                "reason_code": "SOFT_DISCOVERY_DECISION_DATE_MISMATCH", "annotation_identity": None,
                "producer_identity": None, "upstream_identity": upstream_identity, "effects": effects,
            }
    existing = _read_object(path, label="structural annotation")
    payload: Mapping[str, Any] | None = annotation_payload
    status = "produced"
    if soft_discovery_result is None or soft_discovery_result.get("status") not in {"valid_nonempty", "valid_empty"}:
        return {
            "stage": "serenity_annotation_producer", "status": "pending", "decision_date": decision_date,
            "checkpoint_status": "awaiting_annotation", "reason_code": "UPSTREAM_SOFT_DISCOVERY_NOT_VALID",
            "annotation_identity": None, "producer_identity": None, "upstream_identity": upstream_identity,
            "effects": effects,
        }
    if existing is not _MISSING:
        payload = existing
        status = "reused"
    if payload is None:
        return {
            "stage": "serenity_annotation_producer",
            "status": "pending",
            "decision_date": decision_date,
            "checkpoint_status": "awaiting_annotation",
            "reason_code": "ANNOTATION_PAYLOAD_UNAVAILABLE",
            "annotation_identity": None,
            "producer_identity": None,
            "effects": effects,
        }
    try:
        annotation_contract.validate_annotation(payload, root=Path(root), now=now)
        identity = _identity_from_annotation(payload)
        if identity["upstream_decision_date"] != decision_date:
            raise SerenityQualityForwardError("annotation upstream decision_date does not match this weekly task")
        if upstream_identity is not None:
            required_upstream = (
                "upstream_input_packet_id", "upstream_decision_result_id",
                "upstream_policy_version", "upstream_decision_date",
            )
            if any(not isinstance(upstream_identity.get(name), str) or not upstream_identity[name] for name in required_upstream):
                raise SerenityQualityForwardError("soft-discovery upstream identity is incomplete")
            annotation_upstream = {
                "upstream_input_packet_id": payload["identity_envelope"]["upstream_input_packet_id"],
                "upstream_decision_result_id": identity["upstream_decision_result_id"],
                "upstream_policy_version": identity["upstream_policy_version"],
                "upstream_decision_date": identity["upstream_decision_date"],
            }
            if annotation_upstream != upstream_identity:
                raise SerenityQualityForwardError("annotation does not bind the exact soft-discovery upstream identity")
        if existing is _MISSING:
            _write_json(path, payload)
        return {
            "stage": "serenity_annotation_producer",
            "status": status,
            "decision_date": decision_date,
            "checkpoint_status": "annotation_ready",
            "reason_code": None,
            "annotation_identity": identity,
            "producer_identity": _producer_identity(identity),
            "upstream_identity": upstream_identity or {
                "upstream_input_packet_id": payload["identity_envelope"]["upstream_input_packet_id"],
                "upstream_decision_result_id": identity["upstream_decision_result_id"],
                "upstream_policy_version": identity["upstream_policy_version"],
                "upstream_decision_date": identity["upstream_decision_date"],
            },
            "effects": effects,
        }
    except (KeyError, TypeError, ValueError, SerenityQualityForwardError) as exc:
        return {
            "stage": "serenity_annotation_producer",
            "status": "invalid_evidence",
            "decision_date": decision_date,
            "checkpoint_status": "annotation_rejected",
            "reason_code": "ANNOTATION_PRODUCER_REJECTED",
            "annotation_identity": None,
            "producer_identity": None,
            "upstream_identity": upstream_identity,
            "effects": effects,
            "error": _safe_error("ANNOTATION_PRODUCER_REJECTED", exc),
        }


def load_pending_review_target(
    *,
    ledger_path: Path,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    """Return the sole pending annotation and its exact local review target."""
    policy = load_quality_policy()
    ledger = _load_ledger(Path(ledger_path), policy)
    pending = ledger["pending_annotations"]
    if len(pending) != 1:
        raise SerenityQualityForwardError(
            f"pending review target requires exactly one pending annotation; found {len(pending)}"
        )
    item = dict(pending[0])
    root = Path(state_dir) if state_dir is not None else Path(ledger_path).parent
    annotation_path = _pending_path(root, item["annotation_file_name"], label="annotation_file_name")
    review_path = _pending_path(root, item["review_file_name"], label="review_file_name")
    annotation = _read_object(annotation_path, label="pending annotation")
    if annotation is _MISSING:
        raise SerenityQualityForwardError("pending annotation source is unavailable")
    assert isinstance(annotation, dict)
    identity = _identity_from_annotation(annotation)
    if dict(identity) != dict(item["annotation_identity"]):
        raise SerenityQualityForwardError("pending annotation identity does not match the frozen target")
    return {
        "pending": item,
        "annotation": annotation,
        "annotation_path": annotation_path,
        "review_path": review_path,
    }


def write_independent_quality_review(
    *,
    ledger_path: Path,
    review: Mapping[str, Any],
    review_path: Path | None = None,
    state_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and atomically write the reviewer packet for the sole pending target."""
    target = load_pending_review_target(ledger_path=ledger_path, state_dir=state_dir)
    expected_path = Path(target["review_path"])
    if review_path is not None and Path(review_path).resolve() != expected_path.resolve():
        raise SerenityQualityForwardError("review path does not match the sole pending target")
    identity = _identity_from_annotation(target["annotation"])
    producer = _producer_identity(identity)
    policy = load_quality_policy()
    reviewer_kind, reviewed_at, _metrics, reviewer_identity = _validate_review(
        review,
        identity=identity,
        decision_date=target["pending"]["decision_date"],
        policy=policy,
        producer_identity=producer,
    )
    del reviewer_kind, _metrics
    if now is not None and _parse_datetime(reviewed_at, label="reviewed_at") > now.astimezone(timezone.utc):
        raise SerenityQualityForwardError("quality review is dated after the current review action")
    existing = _read_object(expected_path, label="quality review")
    if existing is not _MISSING:
        if dict(existing) != dict(review):
            raise SerenityQualityForwardError("different review content cannot overwrite the frozen review packet")
        return {"status": "idempotent", "review_path": str(expected_path), "reviewer_identity": reviewer_identity}
    _write_json(expected_path, review)
    return {"status": "written", "review_path": str(expected_path), "reviewer_identity": reviewer_identity}


def ledger_rejected_settlement(exc: Exception) -> dict[str, Any]:
    """The single settlement shape for a ledger the current contract cannot read.

    Both this engine and the weekly runner's pre-stage seam return it, so the two
    callers cannot drift apart and the runner needs no private helper of ours.
    """
    return {
        "stage": "serenity_quality_settlement",
        "status": "no_count",
        "evidence_status": "invalid_evidence",
        "pending_count": 0,
        "reason_code": LEDGER_REJECTED_REASON_CODE,
        "error": _safe_error(LEDGER_REJECTED_REASON_CODE, exc),
        "main_task_should_abort": False,
        "effects": dict(EFFECT_BOUNDARY),
    }


def settle_pending_review(
    *,
    ledger_path: Path,
    current_decision_date: str,
    observed_at: str,
    state_dir: Path | None = None,
    root: Path = ROOT,
    now: datetime | None = None,
    policy_path: Path = POLICY_PATH,
    g1_decision_path: Path | None = None,
    g1_preflight_path: Path | None = None,
) -> dict[str, Any]:
    """Settle the prior week's sole pending review before a new weekly task.

    A missing, malformed, late, or identity-drifting review is closed as
    ``no_count``.  The closed row prevents any later historical backfill.
    """
    current_decision_date = _date(current_decision_date, label="current_decision_date")
    _parse_datetime(observed_at, label="observed_at")
    policy = load_quality_policy(policy_path)
    ledger_file = Path(ledger_path)
    if not ledger_file.is_file():
        return {"stage": "serenity_quality_settlement", "status": "no_pending", "pending_count": 0, "effects": dict(EFFECT_BOUNDARY)}
    try:
        ledger = _load_ledger(ledger_file, policy)
    except SerenityQualityForwardError as exc:
        # A pre-Blade5 ledger is not evidence for the current producer/reviewer contract.  Keep the old
        # bytes untouched, make the settlement a local no-count, and let the ordinary weekly task continue.
        return ledger_rejected_settlement(exc)
    pending_rows = ledger["pending_annotations"]
    if not pending_rows:
        return {"stage": "serenity_quality_settlement", "status": "no_pending", "pending_count": 0, "effects": dict(EFFECT_BOUNDARY)}
    if len(pending_rows) != 1:
        return {
            "stage": "serenity_quality_settlement", "status": "blocked_multiple_pending",
            "pending_count": len(pending_rows), "effects": dict(EFFECT_BOUNDARY),
        }
    pending = dict(pending_rows[0])
    if current_decision_date <= pending["decision_date"]:
        return {
            "stage": "serenity_quality_settlement", "status": "not_due",
            "pending_count": 1, "pending_decision_date": pending["decision_date"],
            "effects": dict(EFFECT_BOUNDARY),
        }
    state_root = Path(state_dir) if state_dir is not None else ledger_file.parent
    annotation_path = _pending_path(state_root, pending["annotation_file_name"], label="annotation_file_name")
    review_path = _pending_path(state_root, pending["review_file_name"], label="review_file_name")
    observation_path = state_root / f"us_short_serenity_quality_observation_{pending['decision_date']}.json"
    gate_path = state_root / f"us_short_serenity_quality_gate_{pending['decision_date']}.json"
    default_g1_decision_path, default_g1_preflight_path = _default_g1_paths(gate_path, pending["decision_date"])
    g1_decision_path = Path(g1_decision_path) if g1_decision_path is not None else default_g1_decision_path
    g1_preflight_path = Path(g1_preflight_path) if g1_preflight_path is not None else default_g1_preflight_path

    identity: dict[str, Any] | None = None
    producer: dict[str, Any] | None = None
    shadow: Mapping[str, Any] = {"status": "sleeping"}
    reviewer: dict[str, Any] | None = None
    reason_code = "REVIEW_MISSING_OR_INVALID"
    settlement_error: dict[str, str] | None = None
    valid_review = False
    try:
        annotation_value = _read_object(annotation_path, label="pending annotation")
        if annotation_value is _MISSING:
            raise SerenityQualityForwardError("pending annotation source is unavailable")
        assert isinstance(annotation_value, dict)
        identity = _identity_from_annotation(annotation_value)
        if dict(identity) != dict(pending["annotation_identity"]):
            raise SerenityQualityForwardError("pending annotation identity drifted")
        producer = _producer_identity(identity)
        shadow = shadow_consumer.consume_serenity_annotation(annotation_value, root=Path(root), now=now)
        if shadow.get("status") != "active":
            raise SerenityQualityForwardError("pending annotation no longer passes the Blade4 shadow boundary")
        review_value = _read_object(review_path, label="quality review")
        if review_value is _MISSING:
            reason_code = "REVIEW_MISSING"
            raise SerenityQualityForwardError("quality review was not supplied before the next weekly task")
        assert isinstance(review_value, dict)
        _reviewer_kind, reviewed_at, _metrics, reviewer = _validate_review(
            review_value, identity=identity, decision_date=pending["decision_date"],
            policy=policy, producer_identity=producer,
        )
        if _parse_datetime(reviewed_at, label="reviewed_at") >= _parse_datetime(observed_at, label="observed_at"):
            reason_code = "REVIEW_LATE"
            raise SerenityQualityForwardError("quality review was not completed before the next weekly task")
        valid_review = True
    except (KeyError, TypeError, ValueError, SerenityQualityForwardError) as exc:
        settlement_error = _safe_error("SERENITY_PENDING_REVIEW_NO_COUNT", exc)

    if valid_review:
        return {
            "stage": "serenity_quality_settlement",
            "status": "settled",
            "pending_decision_date": pending["decision_date"],
            "quality_result": run_quality_forward(
                annotation_path=annotation_path, review_path=review_path,
                observation_path=observation_path, ledger_path=ledger_file, gate_path=gate_path,
                decision_date=pending["decision_date"], observed_at=observed_at, root=root, now=now,
                policy_path=policy_path, g1_decision_path=g1_decision_path,
                g1_preflight_path=g1_preflight_path, pending_settlement=pending,
            ),
            "effects": dict(EFFECT_BOUNDARY),
        }

    _close_pending(
        ledger, pending, settlement_status="no_count", settled_at=observed_at,
        reason_code=reason_code, reviewer_identity=reviewer,
    )
    _validate_payload(ledger, LEDGER_SCHEMA_PATH, label="quality ledger")
    _write_json(ledger_file, ledger)
    observation = _observation(
        decision_date=pending["decision_date"], observed_at=observed_at,
        status="invalid_evidence" if identity is None else "not_evaluable", identity=identity,
        producer_identity=producer, reviewer_identity=reviewer, formal_count_eligible=False,
        settlement_status="no_count", metrics=_empty_metric_rows(reason="pending review closed without a valid on-time review"),
        annotation_present=identity is not None, review_present=review_path.is_file(),
        shadow_status=str(shadow.get("status", "sleeping")), error=settlement_error,
    )
    gate = _gate_for(ledger, cohort_id=None, observed_at=observed_at, policy=policy)
    _write_json(observation_path, observation)
    preflight = _persist_gate_and_preflight(
        gate=gate, gate_path=gate_path, g1_decision_path=g1_decision_path,
        g1_preflight_path=g1_preflight_path, decision_date=pending["decision_date"], observed_at=observed_at,
    )
    return {
        "stage": "serenity_quality_settlement", "status": "no_count",
        "pending_decision_date": pending["decision_date"], "reason_code": reason_code,
        "quality_gate": gate, "g1_blade6_preflight": preflight,
        "effects": dict(EFFECT_BOUNDARY),
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
    g1_decision_path: Path | None = None,
    g1_preflight_path: Path | None = None,
    pending_settlement: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one offline weekly observation and persist the Blade5/G1 state artifacts."""
    decision_date = _date(decision_date, label="decision_date")
    _parse_datetime(observed_at, label="observed_at")
    default_g1_decision_path, default_g1_preflight_path = _default_g1_paths(Path(gate_path), decision_date)
    g1_decision_path = Path(g1_decision_path) if g1_decision_path is not None else default_g1_decision_path
    g1_preflight_path = Path(g1_preflight_path) if g1_preflight_path is not None else default_g1_preflight_path
    artifacts = {
        "observation": Path(observation_path),
        "ledger": Path(ledger_path),
        "quality_gate": Path(gate_path),
        "g1_blade6_preflight": g1_preflight_path,
    }
    policy = load_quality_policy(policy_path)
    try:
        existing_ledger = _load_ledger(Path(ledger_path), policy)
    except SerenityQualityForwardError as exc:
        # Do not let a legacy/corrupt ledger abort the weekly task.  The invalid ledger remains on disk for
        # diagnosis; this run uses an empty in-memory ledger, so no legacy row can enter the current formal gate.
        error = _safe_error(LEDGER_REJECTED_REASON_CODE, exc)
        existing_ledger = _empty_ledger()
        shadow = shadow_consumer.consume_serenity_annotation(None)
        observation = _observation(
            decision_date=decision_date,
            observed_at=observed_at,
            status="invalid_evidence",
            identity=None,
            metrics=_empty_metric_rows(reason="quality ledger was unreadable or not in the current format"),
            annotation_present=Path(annotation_path).is_file(),
            review_present=Path(review_path).is_file(),
            shadow_status="sleeping",
            error=error,
        )
        gate = _gate_for(existing_ledger, cohort_id=None, observed_at=observed_at, policy=policy)
        _write_json(Path(observation_path), observation)
        # Keep the rejected ledger untouched; only the diagnostic observation and fail-closed preflight are new.
        preflight = _persist_gate_and_preflight(
            gate=gate, gate_path=Path(gate_path), g1_decision_path=g1_decision_path,
            g1_preflight_path=g1_preflight_path, decision_date=decision_date, observed_at=observed_at,
        )
        return _result(
            decision_date=decision_date,
            observed_at=observed_at,
            status="invalid_evidence",
            observation=observation,
            ledger=existing_ledger,
            gate=gate,
            shadow=shadow,
            artifacts=artifacts,
            g1_preflight=preflight,
            error=error,
        )
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
        preflight = _persist_gate_and_preflight(
            gate=gate, gate_path=Path(gate_path), g1_decision_path=g1_decision_path,
            g1_preflight_path=g1_preflight_path, decision_date=decision_date, observed_at=observed_at,
        )
        return _result(
            decision_date=decision_date,
            observed_at=observed_at,
            status="invalid_evidence",
            observation=observation,
            ledger=existing_ledger,
            gate=gate,
            shadow=shadow,
            artifacts=artifacts,
            g1_preflight=preflight,
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
        preflight = _persist_gate_and_preflight(
            gate=gate, gate_path=Path(gate_path), g1_decision_path=g1_decision_path,
            g1_preflight_path=g1_preflight_path, decision_date=decision_date, observed_at=observed_at,
        )
        return _result(
            decision_date=decision_date,
            observed_at=observed_at,
            status="sleeping",
            observation=observation,
            ledger=existing_ledger,
            gate=gate,
            shadow=shadow,
            artifacts=artifacts,
            g1_preflight=preflight,
        )
    assert isinstance(annotation_value, dict)
    annotation = annotation_value
    identity: dict[str, Any] | None = None
    producer_identity: dict[str, Any] | None = None
    shadow: Mapping[str, Any]
    try:
        identity = _identity_from_annotation(annotation)
        producer_identity = _producer_identity(identity)
        shadow = shadow_consumer.consume_serenity_annotation(annotation, root=Path(root), now=now)
        if shadow.get("status") != "active":
            raise SerenityQualityForwardError("annotation did not pass the Blade4 active shadow boundary")
    except (KeyError, TypeError, ValueError, SerenityQualityForwardError) as exc:
        shadow = shadow_consumer.consume_serenity_annotation(annotation if isinstance(annotation, Mapping) else {})
        error = _safe_error("SERENITY_ANNOTATION_REJECTED", exc)
        observation = _observation(
            decision_date=decision_date, observed_at=observed_at, status="invalid_evidence",
            identity=None, metrics=_empty_metric_rows(reason="annotation failed the frozen identity or shadow contract"),
            annotation_present=True, review_present=review_value is not _MISSING,
            shadow_status=str(shadow.get("status", "invalid_annotation")), error=error,
        )
        gate = _gate_for(existing_ledger, cohort_id=None, observed_at=observed_at, policy=policy)
        _write_json(Path(observation_path), observation)
        if not Path(ledger_path).is_file():
            _write_json(Path(ledger_path), existing_ledger)
        preflight = _persist_gate_and_preflight(
            gate=gate, gate_path=Path(gate_path), g1_decision_path=g1_decision_path,
            g1_preflight_path=g1_preflight_path, decision_date=decision_date, observed_at=observed_at,
        )
        return _result(
            decision_date=decision_date, observed_at=observed_at, status="invalid_evidence",
            observation=observation, ledger=existing_ledger, gate=gate, shadow=shadow,
            artifacts=artifacts, g1_preflight=preflight, error=error,
        )

    assert identity is not None and producer_identity is not None
    if review_value is _MISSING:
        pending = _pending_for(
            decision_date=decision_date, annotation_path=Path(annotation_path), review_path=Path(review_path),
            identity=identity, created_at=observed_at,
        )
        try:
            _merge_pending(existing_ledger, pending)
            _validate_payload(existing_ledger, LEDGER_SCHEMA_PATH, label="quality ledger")
            _write_json(Path(ledger_path), existing_ledger)
        except (KeyError, TypeError, ValueError, SerenityQualityForwardError) as exc:
            error = _safe_error("SERENITY_PENDING_REVIEW_REJECTED", exc)
            observation = _observation(
                decision_date=decision_date, observed_at=observed_at, status="invalid_evidence",
                identity=identity, producer_identity=producer_identity,
                metrics=_empty_metric_rows(reason="pending review target could not be frozen"),
                annotation_present=True, review_present=False, shadow_status="active", error=error,
            )
            gate = _gate_for(existing_ledger, cohort_id=None, observed_at=observed_at, policy=policy)
            _write_json(Path(observation_path), observation)
            preflight = _persist_gate_and_preflight(
                gate=gate, gate_path=Path(gate_path), g1_decision_path=g1_decision_path,
                g1_preflight_path=g1_preflight_path, decision_date=decision_date, observed_at=observed_at,
            )
            return _result(
                decision_date=decision_date, observed_at=observed_at, status="invalid_evidence",
                observation=observation, ledger=existing_ledger, gate=gate, shadow=shadow,
                artifacts=artifacts, g1_preflight=preflight, error=error,
            )
        observation = _observation(
            decision_date=decision_date, observed_at=observed_at, status="not_evaluable",
            identity=identity, producer_identity=producer_identity, formal_count_eligible=False,
            settlement_status="pending_review", metrics=_empty_metric_rows(reason="quality review was not supplied for this week"),
            annotation_present=True, review_present=False, shadow_status="active", error=None,
        )
        gate = _gate_for(existing_ledger, cohort_id=None, observed_at=observed_at, policy=policy)
        _write_json(Path(observation_path), observation)
        preflight = _persist_gate_and_preflight(
            gate=gate, gate_path=Path(gate_path), g1_decision_path=g1_decision_path,
            g1_preflight_path=g1_preflight_path, decision_date=decision_date, observed_at=observed_at,
        )
        return _result(
            decision_date=decision_date, observed_at=observed_at, status="not_evaluable",
            observation=observation, ledger=existing_ledger, gate=gate, shadow=shadow,
            artifacts=artifacts, g1_preflight=preflight,
        )

    assert isinstance(review_value, dict)
    reviewer_identity: dict[str, Any] | None = None
    dimensions: dict[str, str] | None = None
    cohort_id: str | None = None
    try:
        pending_key = (decision_date, str(identity["annotation_id"]))
        if pending_settlement is None and any(
            _pending_key(item) == pending_key for item in existing_ledger["pending_annotations"]
        ):
            raise SerenityQualityForwardError("current-week review must be settled on the next weekly task")
        if pending_settlement is not None and _pending_key(pending_settlement) != pending_key:
            raise SerenityQualityForwardError("pending settlement identity does not match the review")
        if any(_pending_key(item) == pending_key for item in existing_ledger["closed_pending_annotations"]):
            raise SerenityQualityForwardError("closed pending review cannot be backfilled")
        reviewer_kind, reviewed_at, metrics, reviewer_identity = _validate_review(
            review_value, identity=identity, decision_date=decision_date, policy=policy,
            producer_identity=producer_identity,
        )
        dimensions = _cohort_dimensions(identity, reviewer_identity=reviewer_identity)
        cohort_id = _cohort_id(dimensions)
        if pending_settlement is not None:
            _close_pending(
                existing_ledger, pending_settlement, settlement_status="eligible", settled_at=observed_at,
                reason_code="REVIEW_SETTLED", reviewer_identity=reviewer_identity,
            )
        record = _record_for(
            decision_date=decision_date, identity=identity, dimensions=dimensions, reviewer_kind=reviewer_kind,
            producer_identity=producer_identity, reviewer_identity=reviewer_identity,
            reviewed_at=reviewed_at, metrics=metrics, cohort=cohort_id,
        )
        merge_status = _merge_record(existing_ledger, record, cohort_id, dimensions)
    except (KeyError, TypeError, ValueError, SerenityQualityForwardError) as exc:
        error = _safe_error("SERENITY_QUALITY_REVIEW_REJECTED", exc)
        observation = _observation(
            decision_date=decision_date, observed_at=observed_at, status="invalid_evidence", identity=identity,
            producer_identity=producer_identity, reviewer_identity=reviewer_identity,
            metrics=_empty_metric_rows(reason="quality review failed the frozen identity or metric contract"),
            annotation_present=True, review_present=True, shadow_status="active", error=error,
        )
        gate = _gate_for(existing_ledger, cohort_id=cohort_id, observed_at=observed_at, policy=policy)
        _write_json(Path(observation_path), observation)
        if not Path(ledger_path).is_file():
            _write_json(Path(ledger_path), existing_ledger)
        preflight = _persist_gate_and_preflight(
            gate=gate, gate_path=Path(gate_path), g1_decision_path=g1_decision_path,
            g1_preflight_path=g1_preflight_path, decision_date=decision_date, observed_at=observed_at,
        )
        return _result(
            decision_date=decision_date, observed_at=observed_at, status="invalid_evidence", observation=observation,
            ledger=existing_ledger, gate=gate, shadow=shadow, artifacts=artifacts,
            g1_preflight=preflight, error=error,
        )

    formal_count_eligible = bool(record["formal_count_eligible"])
    observation = _observation(
        decision_date=decision_date, observed_at=observed_at, status="eligible", identity=identity,
        producer_identity=producer_identity, reviewer_identity=reviewer_identity,
        formal_count_eligible=formal_count_eligible,
        settlement_status="eligible" if pending_settlement is not None else "eligible",
        metrics=metrics, annotation_present=True, review_present=True, shadow_status="active", error=None,
    )
    if merge_status == "added" or pending_settlement is not None:
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
    preflight = _persist_gate_and_preflight(
        gate=gate, gate_path=Path(gate_path), g1_decision_path=g1_decision_path,
        g1_preflight_path=g1_preflight_path, decision_date=decision_date, observed_at=observed_at,
    )
    return _result(
        decision_date=decision_date, observed_at=observed_at, status="eligible", observation=observation,
        ledger=existing_ledger, gate=gate, shadow=shadow, artifacts=artifacts, g1_preflight=preflight,
    )


__all__ = [
    "CONSUMER_VERSION",
    "EFFECT_BOUNDARY",
    "GATE_SCHEMA_PATH",
    "G1_PREFLIGHT_SCHEMA_PATH",
    "LEDGER_REJECTED_REASON_CODE",
    "LEDGER_SCHEMA_PATH",
    "METRIC_IDS",
    "OBSERVATION_SCHEMA_PATH",
    "POLICY_PATH",
    "POLICY_SCHEMA_PATH",
    "PRODUCER_IDENTITY_VERSION",
    "QUALITY_POLICY_VERSION",
    "REVIEW_SCHEMA_PATH",
    "REVIEWER_IDENTITY_VERSION",
    "REVIEW_PROMPT_VERSION",
    "SerenityQualityForwardError",
    "ledger_rejected_settlement",
    "load_quality_policy",
    "load_pending_review_target",
    "produce_annotation_for_week",
    "run_quality_forward",
    "settle_pending_review",
    "write_independent_quality_review",
]
