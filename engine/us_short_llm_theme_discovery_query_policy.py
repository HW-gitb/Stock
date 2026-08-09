"""Offline versioned policy container for US-short soft-discovery queries.

The tracked policy is the only source for the four shared Stage-1 template bytes and the
deterministic Stage-2 normalization/order/limit rules.  It is explicitly a
``candidate_offline`` artifact: loading or rendering it never calls a provider,
activates the weekly live path, changes scoring, or starts confirmation, seats,
probe, lifecycle, or operation effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import string
from typing import Any, Mapping

from engine.us_short_schema_formats import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "presets" / "us_short_llm_theme_discovery_query_policy_v0.2.0.json"
POLICY_SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery_query_policy.schema.json"
EXPECTED_SOURCE_PACKET_PATH = ROOT / "docs" / "us_short_soft_discovery_query_quality_probe_packet_20260730.json"
EXPECTED_POLICY_VERSION = "soft_discovery_query_policy_v0.2.0"
V0_3_POLICY_PATH = ROOT / "presets" / "us_short_llm_theme_discovery_query_policy_v0.3.0.json"
V0_3_POLICY_SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery_query_policy_v0.3.0.schema.json"
V0_3_POLICY_VERSION = "soft_discovery_query_policy_v0.3.0"
EXPECTED_STAGE1_TEMPLATE_IDS = (
    "stage1_new_cross_industry_demand",
    "stage1_capex_orders_capacity",
    "stage1_supply_regulation_bottleneck",
    "stage1_earnings_bookings_guidance",
)
EXPECTED_POLICY_CONTENT_SHA256 = "4b2d282155f34c70d881cda44bb5d6b267ce49cb8d46131d60831f1928c176cd"
EXPECTED_SOURCE_PACKET_SHA256 = "0c200961d178556e1e86d696e54bcaecd04e7f4cdae9426ee1fb5c1278dd949a"


@dataclass(frozen=True)
class PolicySpec:
    """Tracked policy authority and its execution boundary."""

    policy_version: str
    policy_path: Path
    policy_schema_path: Path
    expected_policy_content_sha256: str
    source_packet_required: bool
    provider_execution_allowed: bool


_POLICY_SPECS = {
    EXPECTED_POLICY_VERSION: PolicySpec(
        policy_version=EXPECTED_POLICY_VERSION,
        policy_path=POLICY_PATH,
        policy_schema_path=POLICY_SCHEMA_PATH,
        expected_policy_content_sha256=EXPECTED_POLICY_CONTENT_SHA256,
        source_packet_required=True,
        provider_execution_allowed=True,
    ),
    V0_3_POLICY_VERSION: PolicySpec(
        policy_version=V0_3_POLICY_VERSION,
        policy_path=V0_3_POLICY_PATH,
        policy_schema_path=V0_3_POLICY_SCHEMA_PATH,
        expected_policy_content_sha256="9e113e256ae507f46ca3939d3d471bb02d29041b7cecf41b2ce386b7c63c0ccc",
        source_packet_required=False,
        provider_execution_allowed=False,
    ),
}


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


def _validate_schema(policy: Mapping[str, Any], schema_path: Path) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - project dependency guard
        raise QueryPolicyError("jsonschema is required for the query policy contract") from exc
    errors = sorted(
        Draft7Validator(
            _read_json(schema_path),
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


def get_policy_spec(policy_version: str) -> PolicySpec:
    """Return the explicitly registered policy authority for one version."""
    try:
        return _POLICY_SPECS[policy_version]
    except (KeyError, TypeError) as exc:
        raise QueryPolicyError("query policy version is not registered") from exc


def validate_query_policy(
    policy: Mapping[str, Any], *, root: Path = ROOT, policy_path: Path | str | None = None,
) -> bool:
    """Validate one registered policy without binding it to a weekly input packet."""
    if not isinstance(policy, Mapping):
        raise QueryPolicyError("query policy must be an object")
    try:
        spec = get_policy_spec(policy["policy_version"])
    except (KeyError, QueryPolicyError) as exc:
        raise QueryPolicyError("query policy version is not a registered policy") from exc
    _validate_schema(policy, spec.policy_schema_path)
    if policy["activation_status"] != "candidate_offline" or policy["production_query_policy_activated"]:
        raise QueryPolicyError("query policy is not offline-only candidate state")
    core = policy["policy_core"]
    if any("{" in row["text"] or "}" in row["text"] for row in core["stage1_templates"]):
        raise QueryPolicyError("Stage-1 templates may not contain free-text placeholders")
    if policy["policy_content_sha256"] != _digest(core):
        raise QueryPolicyError("query policy content digest does not match policy_core")
    if policy["policy_content_sha256"] != spec.expected_policy_content_sha256:
        raise QueryPolicyError(f"query policy content is not the reviewed {spec.policy_version} content")
    template_ids = tuple(row["query_id"] for row in core["stage1_templates"])
    if template_ids != EXPECTED_STAGE1_TEMPLATE_IDS:
        raise QueryPolicyError("Stage-1 template ids/order drifted from the reviewed container")
    if len(set(core["stage2"]["term_type_rank"].values())) != 4:
        raise QueryPolicyError("Stage-2 term type ranks must be a permutation")
    if core["stage2"]["max_terms_total"] > sum(core["stage2"]["max_terms_by_type"].values()):
        raise QueryPolicyError("Stage-2 total limit cannot exceed its per-type capacity")
    _validate_query_template(core["stage2"]["query_text_template"])

    if spec.source_packet_required:
        root = Path(root).resolve()
        source_packet = policy.get("source_packet")
        if not isinstance(source_packet, Mapping):
            raise QueryPolicyError("reviewed v0.2.0 policy must declare its legacy source packet")
        source_path = Path(root) / source_packet["path"]
        if source_path.is_symlink():
            raise QueryPolicyError("query-policy source packet may not be a symlink")
        try:
            source_sha = _digest(_read_json(source_path))
        except QueryPolicyError as exc:
            raise QueryPolicyError("query-policy source packet is unreadable") from exc
        if source_sha != source_packet["sha256"] or source_sha != EXPECTED_SOURCE_PACKET_SHA256:
            raise QueryPolicyError("query-policy source packet digest is not the reviewed packet")
    return True


def load_query_policy(path: Path | str = POLICY_PATH, *, root: Path = ROOT) -> dict[str, Any]:
    """Load and validate one registered candidate-offline policy container."""
    policy_path = Path(path)
    payload = _read_json(policy_path)
    validate_query_policy(payload, root=root, policy_path=policy_path)
    return payload


def load_query_policy_for_version(
    policy_version: str, *, root: Path = ROOT,
) -> dict[str, Any]:
    """Load the immutable policy for an explicit version, never the latest by date."""
    spec = get_policy_spec(policy_version)
    return load_query_policy(spec.policy_path, root=root)


def render_stage1_queries(policy: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    """Render the four exact Stage-1 query bytes from the versioned container."""
    payload = load_query_policy() if policy is None else policy
    validate_query_policy(payload)
    return [
        {"query_id": row["query_id"], "query_text": row["text"]}
        for row in payload["policy_core"]["stage1_templates"]
    ]


def stage2_rule_sha256(policy: Mapping[str, Any]) -> str:
    """Return the reviewed policy's canonical Stage-2 rule fingerprint."""
    validate_query_policy(policy)
    return _digest(policy["policy_core"]["stage2"])


__all__ = [
    "EXPECTED_POLICY_CONTENT_SHA256",
    "EXPECTED_POLICY_VERSION",
    "EXPECTED_SOURCE_PACKET_SHA256",
    "PolicySpec",
    "POLICY_PATH",
    "POLICY_SCHEMA_PATH",
    "QueryPolicyError",
    "V0_3_POLICY_PATH",
    "V0_3_POLICY_SCHEMA_PATH",
    "V0_3_POLICY_VERSION",
    "get_policy_spec",
    "load_query_policy",
    "load_query_policy_for_version",
    "render_stage1_queries",
    "stage2_rule_sha256",
    "validate_query_policy",
]
