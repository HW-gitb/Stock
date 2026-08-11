"""Offline Blade3 structural-theme annotation contract for US-short Serenity.

This module validates and canonicalizes a schema-only annotation.  It binds the
annotation to one explicitly named Blade2 policy decision and its frozen input
packet, but never reads ``policy_disposition`` and never enables scoring,
selection, seats, action, position, or provider execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from engine import us_short_llm_theme_discovery_policy_decision as policy_decision
from engine.us_short_schema_formats import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[1]
RUBRIC_PATH = ROOT / "presets" / "us_short_serenity_annotation_rubric_v0.1.0.json"
RUBRIC_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_annotation_rubric.schema.json"
SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_structural_theme_annotation.schema.json"
RUBRIC_VERSION = "serenity_annotation_rubric_v0.1.0"
ANNOTATION_VERSION = "structural_theme_annotation_v0.1.0"
SCHEMA_VERSION = "1.0.0"
ACCEPTED_UPSTREAM_POLICY_VERSIONS = (
    "soft_discovery_query_policy_v0.2.0",
    "soft_discovery_query_policy_v0.3.0",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")
DECISION_DATE_RE = re.compile(r"^[0-9]{8}$")
EFFECT_BOUNDARY = {
    "scoring_eligible": False,
    "top15_effect_enabled": False,
    "operation_advice_effect_enabled": False,
}


class StructuralAnnotationError(ValueError):
    """A structural annotation is malformed, stale, or not identity-bound."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise StructuralAnnotationError("annotation is not canonically serializable") from exc


def _digest(value: Any) -> str:
    digest = hashlib.sha256(_canonical_bytes(value)).hexdigest()
    if SHA256_RE.fullmatch(digest) is None:  # pragma: no cover - hashlib contract guard
        raise StructuralAnnotationError("annotation digest is malformed")
    return digest


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StructuralAnnotationError(f"{label} is unreadable") from exc
    if type(value) is not dict:
        raise StructuralAnnotationError(f"{label} must be a JSON object")
    return value


def _validate_json_schema(payload: Mapping[str, Any], schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator

        schema = _read_json_object(schema_path, label=f"{label} schema")
        errors = sorted(
            Draft7Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(payload),
            key=lambda error: list(error.absolute_path),
        )
    except (ImportError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise StructuralAnnotationError(f"{label} schema is unavailable") from exc
    if errors:
        raise StructuralAnnotationError(f"{label} schema rejected: {errors[0].message}")


def _parse_datetime(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise StructuralAnnotationError(f"{label} must be RFC3339 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StructuralAnnotationError(f"{label} must be RFC3339 text") from exc
    if parsed.tzinfo is None:
        raise StructuralAnnotationError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_decision_date(value: Any) -> str:
    if not isinstance(value, str) or DECISION_DATE_RE.fullmatch(value) is None:
        raise StructuralAnnotationError("upstream_decision_date must be YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise StructuralAnnotationError("upstream_decision_date must be a real date") from exc
    return value


def _annotation_id_basis(
    identity: Mapping[str, Any],
    canonical_annotation: Mapping[str, Any],
    effect_boundary: Mapping[str, Any],
) -> dict[str, Any]:
    identity_without_generation = {
        key: value
        for key, value in identity.items()
        if key not in {"generated_at", "annotation_sha256"}
    }
    return {
        "identity_envelope": identity_without_generation,
        "canonical_annotation": canonical_annotation,
        "effect_boundary": effect_boundary,
    }


def load_rubric() -> dict[str, Any]:
    """Load the explicit candidate-offline rubric version used by Blade3."""
    rubric = _read_json_object(RUBRIC_PATH, label="Serenity annotation rubric")
    _validate_json_schema(rubric, RUBRIC_SCHEMA_PATH, label="Serenity annotation rubric")
    if rubric["rubric_version"] != RUBRIC_VERSION:
        raise StructuralAnnotationError("rubric version is not the registered Blade3 version")
    if tuple(rubric["accepted_upstream_policy_versions"]) != ACCEPTED_UPSTREAM_POLICY_VERSIONS:
        raise StructuralAnnotationError("rubric upstream policy allowlist drifted")
    if rubric["effect_boundary"] != EFFECT_BOUNDARY:
        raise StructuralAnnotationError("rubric effect boundary must remain disabled")
    return rubric


def validate_annotation(
    payload: Mapping[str, Any],
    *,
    root: Path = ROOT,
    now: datetime | None = None,
) -> bool:
    """Validate schema, explicit upstream identity, freshness, and no-effect bounds."""
    if not isinstance(payload, Mapping):
        raise StructuralAnnotationError("structural annotation must be an object")
    _validate_json_schema(payload, SCHEMA_PATH, label="structural theme annotation")
    rubric = load_rubric()
    identity = payload["identity_envelope"]
    canonical = payload["canonical_annotation"]
    if identity["upstream_policy_version"] not in rubric["accepted_upstream_policy_versions"]:
        raise StructuralAnnotationError("upstream policy version is not explicitly accepted by the rubric")
    if identity["rubric_version"] != rubric["rubric_version"]:
        raise StructuralAnnotationError("annotation rubric version is not the reviewed candidate rubric")
    if payload["generated_at"] != identity["generated_at"]:
        raise StructuralAnnotationError("top-level and identity generated_at differ")
    if dict(payload["effect_boundary"]) != EFFECT_BOUNDARY:
        raise StructuralAnnotationError("annotation effect boundary must remain disabled")
    _validate_decision_date(identity["upstream_decision_date"])

    try:
        upstream = policy_decision.locate_policy_decision_result(
            upstream_input_packet_id=identity["upstream_input_packet_id"],
            upstream_decision_result_id=identity["upstream_decision_result_id"],
            upstream_policy_version=identity["upstream_policy_version"],
            upstream_decision_date=identity["upstream_decision_date"],
            root=Path(root),
        )
    except policy_decision.PolicyDecisionError as exc:
        raise StructuralAnnotationError("upstream policy decision identity is unavailable or mismatched") from exc
    upstream_canonical = upstream["canonical_decision"]
    if identity["input_artifact_sha256"] != upstream_canonical["input_packet_sha256"]:
        raise StructuralAnnotationError("annotation input artifact digest does not match the upstream packet")
    if identity["annotation_sha256"] != _digest(canonical):
        raise StructuralAnnotationError("annotation_sha256 does not match canonical_annotation")
    if payload["annotation_id"] != _digest(_annotation_id_basis(identity, canonical, payload["effect_boundary"])):
        raise StructuralAnnotationError("annotation_id does not match the identity envelope and canonical annotation")

    generated_at = _parse_datetime(identity["generated_at"], label="generated_at")
    source_cutoff_at = _parse_datetime(identity["source_cutoff_at"], label="source_cutoff_at")
    valid_through = _parse_datetime(identity["valid_through"], label="valid_through")
    if valid_through <= source_cutoff_at:
        raise StructuralAnnotationError("valid_through must be after source_cutoff_at")
    if valid_through <= generated_at:
        raise StructuralAnnotationError("valid_through must be after generated_at")
    comparison_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if valid_through <= comparison_now:
        raise StructuralAnnotationError("annotation valid_through has expired")
    return True


def canonicalize_annotation(
    payload: Mapping[str, Any],
    *,
    root: Path = ROOT,
    now: datetime | None = None,
) -> bytes:
    """Return stable canonical bytes for one fully validated annotation."""
    validate_annotation(payload, root=root, now=now)
    return _canonical_bytes(payload)


def canonical_annotation_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return stable bytes for the effect-free annotation content only."""
    if not isinstance(payload, Mapping) or "canonical_annotation" not in payload:
        raise StructuralAnnotationError("canonical_annotation is required")
    return _canonical_bytes(payload["canonical_annotation"])


def build_structural_theme_annotation(
    *,
    upstream_input_packet_id: str,
    upstream_decision_result_id: str,
    upstream_policy_version: str,
    upstream_decision_date: str,
    source_cutoff_at: str,
    annotation_author_kind: str,
    prompt_or_protocol_id: str,
    model_identity: str | None,
    generated_at: str,
    review_status: str,
    valid_through: str,
    canonical_annotation: Mapping[str, Any],
    root: Path = ROOT,
) -> dict[str, Any]:
    """Build one offline annotation after locating its exact upstream result."""
    load_rubric()
    upstream = policy_decision.locate_policy_decision_result(
        upstream_input_packet_id=upstream_input_packet_id,
        upstream_decision_result_id=upstream_decision_result_id,
        upstream_policy_version=upstream_policy_version,
        upstream_decision_date=upstream_decision_date,
        root=Path(root),
    )
    if not isinstance(canonical_annotation, Mapping):
        raise StructuralAnnotationError("canonical_annotation must be an object")
    canonical = dict(canonical_annotation)
    identity = {
        "upstream_input_packet_id": upstream_input_packet_id,
        "upstream_decision_result_id": upstream_decision_result_id,
        "upstream_policy_version": upstream_policy_version,
        "upstream_decision_date": upstream_decision_date,
        "input_artifact_sha256": upstream["canonical_decision"]["input_packet_sha256"],
        "source_cutoff_at": source_cutoff_at,
        "rubric_version": RUBRIC_VERSION,
        "annotation_author_kind": annotation_author_kind,
        "prompt_or_protocol_id": prompt_or_protocol_id,
        "model_identity": model_identity,
        "generated_at": generated_at,
        "review_status": review_status,
        "annotation_sha256": _digest(canonical),
        "valid_through": valid_through,
    }
    payload = {
        "schema_name": "us_short_serenity_structural_theme_annotation",
        "schema_version": SCHEMA_VERSION,
        "schema_ref": "schemas/us_short_serenity_structural_theme_annotation.schema.json",
        "annotation_id": _digest(_annotation_id_basis(identity, canonical, EFFECT_BOUNDARY)),
        "generated_at": generated_at,
        "identity_envelope": identity,
        "canonical_annotation": canonical,
        "effect_boundary": dict(EFFECT_BOUNDARY),
    }
    validate_annotation(payload, root=root)
    return payload


__all__ = [
    "ACCEPTED_UPSTREAM_POLICY_VERSIONS",
    "ANNOTATION_VERSION",
    "EFFECT_BOUNDARY",
    "RUBRIC_PATH",
    "RUBRIC_VERSION",
    "SCHEMA_PATH",
    "StructuralAnnotationError",
    "build_structural_theme_annotation",
    "canonical_annotation_bytes",
    "canonicalize_annotation",
    "load_rubric",
    "validate_annotation",
]
