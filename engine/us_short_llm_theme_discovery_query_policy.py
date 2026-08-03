"""Offline versioned policy container for US-short soft-discovery queries.

The tracked policy is the only source for the four Stage-1 template bytes and the
deterministic Stage-2 normalization/order/limit rules.  It is explicitly a
``candidate_offline`` artifact: loading or rendering it never calls a provider,
activates the weekly live path, changes scoring, or starts confirmation, seats,
probe, lifecycle, or operation effects.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import string
from typing import Any, Mapping

from engine.us_short_schema_formats import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "presets" / "us_short_llm_theme_discovery_query_policy_v0.1.0.json"
POLICY_SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery_query_policy.schema.json"
EXPECTED_SOURCE_PACKET_PATH = ROOT / "docs" / "us_short_soft_discovery_query_quality_probe_packet_20260730.json"
EXPECTED_POLICY_VERSION = "soft_discovery_query_policy_v0.1.0"
EXPECTED_STAGE1_TEMPLATE_IDS = (
    "stage1_new_cross_industry_demand",
    "stage1_capex_orders_capacity",
    "stage1_supply_regulation_bottleneck",
    "stage1_earnings_bookings_guidance",
)
EXPECTED_POLICY_CONTENT_SHA256 = "f2a77b1d9fc19792ca5f090459fdf7586b3a81961563762b4c5d363dc17e565e"
EXPECTED_SOURCE_PACKET_SHA256 = "eda828bf27e3e948f71bd2b90766ff147eb999aa04d7bd3d0c62f1255a71af5f"


class QueryPolicyError(ValueError):
    """A malformed, drifted, or incorrectly activated query policy."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise QueryPolicyError("query policy core is not serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QueryPolicyError(f"query policy is unreadable: {path}") from exc
    if type(value) is not dict:
        raise QueryPolicyError("query policy root must be an object")
    return value


def _validate_schema(policy: Mapping[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - project dependency guard
        raise QueryPolicyError("jsonschema is required for the query policy contract") from exc
    errors = sorted(
        Draft7Validator(
            _read_json(POLICY_SCHEMA_PATH),
            format_checker=FORMAT_CHECKER,
        ).iter_errors(policy),
        key=lambda error: list(error.path),
    )
    if errors:
        raise QueryPolicyError(f"query policy schema rejected: {errors[0].message}")


def _validate_query_template(template: str) -> None:
    try:
        fields = [field_name for _, field_name, _, _ in string.Formatter().parse(template) if field_name]
    except ValueError as exc:
        raise QueryPolicyError("Stage-2 query template is not valid format text") from exc
    if set(fields) != {"term_type", "term"} or len(fields) != 2:
        raise QueryPolicyError("Stage-2 query template must contain exactly term_type and term placeholders")


def validate_query_policy(policy: Mapping[str, Any], *, root: Path = ROOT) -> bool:
    """Validate the versioned container and its pinned source/content fingerprints."""
    if not isinstance(policy, Mapping):
        raise QueryPolicyError("query policy must be an object")
    _validate_schema(policy)
    if policy["policy_version"] != EXPECTED_POLICY_VERSION:
        raise QueryPolicyError("query policy version is not the reviewed v0.1.0 policy")
    if policy["activation_status"] != "candidate_offline" or policy["production_query_policy_activated"]:
        raise QueryPolicyError("query policy is not offline-only candidate state")
    core = policy["policy_core"]
    if any("{" in row["text"] or "}" in row["text"] for row in core["stage1_templates"]):
        raise QueryPolicyError("Stage-1 templates may not contain free-text placeholders")
    if policy["policy_content_sha256"] != _digest(core):
        raise QueryPolicyError("query policy content digest does not match policy_core")
    if policy["policy_content_sha256"] != EXPECTED_POLICY_CONTENT_SHA256:
        raise QueryPolicyError("query policy content is not the reviewed v0.1.0 content")
    template_ids = tuple(row["query_id"] for row in core["stage1_templates"])
    if template_ids != EXPECTED_STAGE1_TEMPLATE_IDS:
        raise QueryPolicyError("Stage-1 template ids/order drifted from the reviewed container")
    if len(set(core["stage2"]["term_type_rank"].values())) != 4:
        raise QueryPolicyError("Stage-2 term type ranks must be a permutation")
    if core["stage2"]["max_terms_total"] > sum(core["stage2"]["max_terms_by_type"].values()):
        raise QueryPolicyError("Stage-2 total limit cannot exceed its per-type capacity")
    _validate_query_template(core["stage2"]["query_text_template"])

    root = Path(root).resolve()
    source_path = Path(root) / policy["source_packet"]["path"]
    if source_path.is_symlink():
        raise QueryPolicyError("query-policy source packet may not be a symlink")
    try:
        source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise QueryPolicyError("query-policy source packet is unreadable") from exc
    if source_sha != policy["source_packet"]["sha256"] or source_sha != EXPECTED_SOURCE_PACKET_SHA256:
        raise QueryPolicyError("query-policy source packet digest is not the reviewed packet")
    return True


def load_query_policy(path: Path | str = POLICY_PATH, *, root: Path = ROOT) -> dict[str, Any]:
    """Load and validate the tracked candidate-offline policy container."""
    payload = _read_json(Path(path))
    validate_query_policy(payload, root=root)
    return payload


def render_stage1_queries(policy: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    """Render the four exact Stage-1 query bytes from the versioned container."""
    payload = load_query_policy() if policy is None else policy
    validate_query_policy(payload)
    return [
        {"query_id": row["query_id"], "query_text": row["text"]}
        for row in payload["policy_core"]["stage1_templates"]
    ]


__all__ = [
    "EXPECTED_POLICY_CONTENT_SHA256",
    "EXPECTED_POLICY_VERSION",
    "EXPECTED_SOURCE_PACKET_SHA256",
    "POLICY_PATH",
    "POLICY_SCHEMA_PATH",
    "QueryPolicyError",
    "load_query_policy",
    "render_stage1_queries",
    "validate_query_policy",
]
