"""Offline, versioned policy-decision routing for US-short discovery.

This layer keeps strategy identity separate from frozen input packets.  It only
records an explicit ``KEEP``/``REVIEW``/``BLOCKED`` disposition and never
derives a policy upgrade, calls a provider, or enables a discovery effect.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from engine import us_short_llm_theme_discovery_query_policy as query_policy
from engine.us_short_schema_formats import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery_policy_decision_result.schema.json"
RESULT_PREFIX = "us_short_llm_theme_discovery_policy_decision"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DECISION_DATE_RE = re.compile(r"^[0-9]{8}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")
POLICY_DISPOSITIONS = ("KEEP", "REVIEW", "BLOCKED")
UPSTREAM_IDENTITY_FIELDS = (
    "upstream_input_packet_id",
    "upstream_decision_result_id",
    "upstream_policy_version",
    "upstream_decision_date",
)


class PolicyDecisionError(ValueError):
    """A versioned offline policy decision is malformed or unsafe."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise PolicyDecisionError("policy decision is not canonically serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes, *, label: str) -> str:
    digest = hashlib.sha256(value).hexdigest()
    if not SHA256_RE.fullmatch(digest):  # pragma: no cover - hashlib contract guard
        raise PolicyDecisionError(f"{label} digest is malformed")
    return digest


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PolicyDecisionError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise PolicyDecisionError(f"{label} must be a JSON object")
    return value


def _decision_date(value: Any) -> str:
    if not isinstance(value, str) or DECISION_DATE_RE.fullmatch(value) is None:
        raise PolicyDecisionError("decision_date must be YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise PolicyDecisionError("decision_date must be a real date") from exc
    return value


def _repo_relative_packet_ref(value: Any, *, root: Path) -> tuple[str, Path]:
    if not isinstance(value, str) or not value.startswith("docs/") or not value.endswith(".json"):
        raise PolicyDecisionError("input_packet_ref must be a repository-relative docs JSON path")
    root_path = Path(root).resolve()
    lexical_candidate = root_path / value
    if lexical_candidate.is_symlink():
        raise PolicyDecisionError("input packet may not be a symlink")
    candidate = lexical_candidate.resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise PolicyDecisionError("input_packet_ref must stay under the repository root") from exc
    try:
        candidate.read_bytes()
    except OSError as exc:
        raise PolicyDecisionError("input packet is unreadable") from exc
    return value, candidate


def _effect_boundary() -> dict[str, bool]:
    return {
        "scoring_eligible": False,
        "top15_effect_enabled": False,
        "operation_advice_effect_enabled": False,
        "dynamic_seats_enabled": False,
        "theme_probe_enabled": False,
        "lifecycle_actions_enabled": False,
        "theme_confirmation_enabled": False,
    }


def _validate_schema(payload: Mapping[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        errors = sorted(
            Draft7Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(payload),
            key=lambda error: list(error.absolute_path),
        )
    except (ImportError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PolicyDecisionError("policy decision schema is unavailable") from exc
    if errors:
        raise PolicyDecisionError(f"policy decision schema rejected: {errors[0].message}")


def _query_scope_sha256(policy: Mapping[str, Any]) -> str:
    return _digest(query_policy.render_stage1_queries(policy))


def build_policy_decision_result(
    *,
    input_packet_id: str,
    input_packet_ref: str,
    input_packet_sha256: str,
    decision_date: str,
    policy_version: str,
    policy_disposition: str,
    generated_at: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Build one deterministic decision identity for one packet/policy pair.

    ``policy_version`` and ``policy_disposition`` are explicit inputs.  There is
    intentionally no helper that infers a new version from a weak weekly result.
    """
    if not isinstance(input_packet_id, str) or IDENTIFIER_RE.fullmatch(input_packet_id) is None:
        raise PolicyDecisionError("input_packet_id is malformed")
    packet_ref, packet_path = _repo_relative_packet_ref(input_packet_ref, root=root)
    if not isinstance(input_packet_sha256, str) or SHA256_RE.fullmatch(input_packet_sha256) is None:
        raise PolicyDecisionError("input_packet_sha256 must be lowercase SHA256")
    actual_packet_sha256 = _sha256_bytes(packet_path.read_bytes(), label="input packet")
    if actual_packet_sha256 != input_packet_sha256:
        raise PolicyDecisionError("input packet digest does not match input_packet_sha256")
    decision_date = _decision_date(decision_date)
    if policy_disposition not in POLICY_DISPOSITIONS:
        raise PolicyDecisionError("policy_disposition must be KEEP, REVIEW, or BLOCKED")
    try:
        policy = query_policy.load_query_policy_for_version(policy_version, root=root)
    except query_policy.QueryPolicyError as exc:
        raise PolicyDecisionError("policy version is not a registered offline policy") from exc
    if not isinstance(generated_at, str):
        raise PolicyDecisionError("generated_at must be RFC3339 text")
    canonical_decision = {
        "input_packet_id": input_packet_id,
        "input_packet_ref": packet_ref,
        "input_packet_sha256": input_packet_sha256,
        "decision_date": decision_date,
        "policy_version": policy["policy_version"],
        "policy_content_sha256": policy["policy_content_sha256"],
        "query_scope_sha256": _query_scope_sha256(policy),
        "policy_disposition": policy_disposition,
        "provider_calls_performed": False,
        "network_access_performed": False,
    }
    payload = {
        "schema_name": "us_short_llm_theme_discovery_policy_decision_result",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_llm_theme_discovery_policy_decision_result.schema.json",
        "generated_at": generated_at,
        "decision_result_id": _digest(canonical_decision),
        "canonical_decision": canonical_decision,
        "effect_boundary": _effect_boundary(),
    }
    validate_policy_decision_result(payload, root=root)
    return payload


def validate_policy_decision_result(
    payload: Mapping[str, Any], *, root: Path = ROOT,
) -> bool:
    """Validate identity, policy binding, explicit disposition, and no-effect bounds."""
    _validate_schema(payload)
    canonical = payload["canonical_decision"]
    if payload["decision_result_id"] != _digest(canonical):
        raise PolicyDecisionError("decision_result_id does not match canonical_decision")
    packet_ref, packet_path = _repo_relative_packet_ref(canonical["input_packet_ref"], root=root)
    if packet_ref != canonical["input_packet_ref"]:
        raise PolicyDecisionError("input packet reference is not canonical")
    actual_packet_sha256 = _sha256_bytes(packet_path.read_bytes(), label="input packet")
    if actual_packet_sha256 != canonical["input_packet_sha256"]:
        raise PolicyDecisionError("input packet changed after decision construction")
    _decision_date(canonical["decision_date"])
    if canonical["policy_disposition"] not in POLICY_DISPOSITIONS:
        raise PolicyDecisionError("policy disposition is not registered")
    try:
        policy = query_policy.load_query_policy_for_version(canonical["policy_version"], root=root)
    except query_policy.QueryPolicyError as exc:
        raise PolicyDecisionError("decision references an unavailable policy version") from exc
    if canonical["policy_content_sha256"] != policy["policy_content_sha256"]:
        raise PolicyDecisionError("decision policy content digest does not match its policy version")
    if canonical["query_scope_sha256"] != _query_scope_sha256(policy):
        raise PolicyDecisionError("decision query scope does not match its policy version")
    if dict(payload["effect_boundary"]) != _effect_boundary():
        raise PolicyDecisionError("policy decision effect boundary must remain disabled")
    return True


def policy_decision_result_path(
    *, input_packet_id: str, decision_date: str, policy_version: str, root: Path = ROOT,
) -> Path:
    if not isinstance(input_packet_id, str) or IDENTIFIER_RE.fullmatch(input_packet_id) is None:
        raise PolicyDecisionError("input_packet_id is malformed")
    decision_date = _decision_date(decision_date)
    if not isinstance(policy_version, str) or IDENTIFIER_RE.fullmatch(policy_version) is None:
        raise PolicyDecisionError("policy_version is malformed")
    return Path(root).resolve() / "docs" / (
        f"{RESULT_PREFIX}_{input_packet_id}_{decision_date}_{policy_version}.json"
    )


def _upstream_identity_from_validated_result(payload: Mapping[str, Any]) -> dict[str, str]:
    canonical = payload["canonical_decision"]
    return {
        "upstream_input_packet_id": canonical["input_packet_id"],
        "upstream_decision_result_id": payload["decision_result_id"],
        "upstream_policy_version": canonical["policy_version"],
        "upstream_decision_date": canonical["decision_date"],
    }


def upstream_identity_for_policy_decision_result(
    payload: Mapping[str, Any], *, root: Path = ROOT,
) -> dict[str, str]:
    """Expose only the four fields permitted to connect a later Stage-1 consumer."""
    validate_policy_decision_result(payload, root=root)
    return _upstream_identity_from_validated_result(payload)


def locate_policy_decision_result(
    *,
    upstream_input_packet_id: str,
    upstream_decision_result_id: str,
    upstream_policy_version: str,
    upstream_decision_date: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Locate one result using the four-field upstream identity only.

    The locator never falls back to a latest result and never reads
    ``policy_disposition`` as a routing hint.
    """
    if not isinstance(upstream_decision_result_id, str) or SHA256_RE.fullmatch(upstream_decision_result_id) is None:
        raise PolicyDecisionError("upstream_decision_result_id must be lowercase SHA256")
    expected_identity = {
        "upstream_input_packet_id": upstream_input_packet_id,
        "upstream_decision_result_id": upstream_decision_result_id,
        "upstream_policy_version": upstream_policy_version,
        "upstream_decision_date": upstream_decision_date,
    }
    result_path = policy_decision_result_path(
        input_packet_id=upstream_input_packet_id,
        decision_date=upstream_decision_date,
        policy_version=upstream_policy_version,
        root=root,
    )
    if result_path.is_symlink() or not result_path.is_file():
        raise PolicyDecisionError("versioned policy decision result is unavailable")
    payload = _read_json_object(result_path, label="versioned policy decision result")
    validate_policy_decision_result(payload, root=root)
    if _upstream_identity_from_validated_result(payload) != expected_identity:
        raise PolicyDecisionError("upstream identity does not match the located decision result")
    return payload


__all__ = [
    "POLICY_DISPOSITIONS",
    "UPSTREAM_IDENTITY_FIELDS",
    "PolicyDecisionError",
    "SCHEMA_PATH",
    "build_policy_decision_result",
    "locate_policy_decision_result",
    "policy_decision_result_path",
    "upstream_identity_for_policy_decision_result",
    "validate_policy_decision_result",
]
