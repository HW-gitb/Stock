"""Build the reviewed, policy-bound parent plan for the 20260808 probe.

This runner is deliberately offline and has no free-text query input.  It renders
Stage-1 only from the reviewed v0.2.0 policy, compares those bytes with the
independent 20260808 probe packet, freezes the provider envelope, and publishes
the canonical parent-plan slot consumed by both live runners.  It never reserves
a budget, creates a provider client, or performs a network call.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state" / "us_short"
DEFAULT_POLICY_PATH = ROOT / "presets" / "us_short_llm_theme_discovery_query_policy_v0.2.0.json"
DEFAULT_PROBE_PACKET_PATH = ROOT / "docs" / "us_short_soft_discovery_query_quality_probe_packet_20260808.json"
PROBE_PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_soft_discovery_query_quality_probe_packet_20260808.schema.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_llm_theme_discovery_plan_budget as plan_budget  # noqa: E402
from engine import us_short_llm_theme_discovery_query_plan as query_plan  # noqa: E402
from engine import us_short_llm_theme_discovery_query_policy as query_policy  # noqa: E402
from engine.us_short_schema_formats import FORMAT_CHECKER  # noqa: E402


class ParentPlanBuilderError(ValueError):
    """The reviewed policy cannot produce a safe plan-bound parent artifact."""


def _ensure_reviewed_policy_path(path: Path | str) -> Path:
    candidate = Path(path)
    candidate = candidate if candidate.is_absolute() else ROOT / candidate
    candidate = candidate.resolve()
    if candidate != DEFAULT_POLICY_PATH.resolve():
        raise ParentPlanBuilderError("parent-plan builder accepts only the tracked reviewed v0.2.0 policy")
    return candidate


def _load_probe_packet(
    path: Path | None = None,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    path = DEFAULT_PROBE_PACKET_PATH if path is None else path
    schema_path = PROBE_PACKET_SCHEMA_PATH if schema_path is None else schema_path
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ParentPlanBuilderError("20260808 probe packet or schema is unreadable") from exc
    if type(packet) is not dict or type(schema) is not dict:
        raise ParentPlanBuilderError("20260808 probe packet and schema must be objects")
    try:
        from jsonschema import Draft7Validator
        errors = sorted(
            Draft7Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(packet),
            key=lambda error: list(error.path),
        )
    except ImportError as exc:  # pragma: no cover - project dependency guard
        raise ParentPlanBuilderError("jsonschema is required for the 20260808 probe packet") from exc
    if errors:
        raise ParentPlanBuilderError(f"20260808 probe packet schema rejected: {errors[0].message}")
    return packet


def _rendered_stage1_queries(
    policy: Mapping[str, Any], probe_packet: Mapping[str, Any],
) -> list[dict[str, str]]:
    rendered = query_policy.render_stage1_queries(policy)
    expected = [
        {"query_id": row["query_id"], "query_text": row["text"]}
        for row in probe_packet["query_templates"]
    ]
    if rendered != expected:
        raise ParentPlanBuilderError(
            "rendered Stage-1 queries do not exactly match the independent probe packet"
        )
    if len(rendered) != 4 or len({row["query_id"] for row in rendered}) != 4:
        raise ParentPlanBuilderError("reviewed policy must render exactly four unique Stage-1 queries")
    return rendered


def _default_provider_envelopes(query_count: int) -> list[dict[str, int | str]]:
    hard = plan_budget.derive_hard_provider_call_budget()
    envelopes: list[dict[str, int | str]] = [
        {
            "provider": "web",
            "stage1_max_dispatch_count": query_count,
            "stage2_max_dispatch_count": query_count,
            "retry_max_dispatch_count": 0,
            "max_dispatch_count": query_count * 2,
        },
        {
            "provider": "xai",
            "stage1_max_dispatch_count": query_count,
            "stage2_max_dispatch_count": 0,
            "retry_max_dispatch_count": 0,
            "max_dispatch_count": query_count,
        },
    ]
    for envelope in envelopes:
        try:
            plan_budget._validate_hard_provider_envelope(  # type: ignore[attr-defined]
                str(envelope["provider"]), envelope,
            )
        except plan_budget.PlanBudgetError as exc:
            raise ParentPlanBuilderError("default provider envelope exceeds the shared hard budget") from exc
    return envelopes


def _normalize_provider_envelopes(
    value: Any,
    *,
    query_count: int,
) -> list[dict[str, int | str]]:
    if not isinstance(value, (list, tuple)):
        raise ParentPlanBuilderError("provider envelope input must be a JSON array")
    expected_fields = {
        "provider", "stage1_max_dispatch_count", "stage2_max_dispatch_count",
        "retry_max_dispatch_count", "max_dispatch_count",
    }
    rows = [dict(row) for row in value if isinstance(row, Mapping)]
    if len(rows) != len(value) or len(rows) != 2:
        raise ParentPlanBuilderError("provider envelope input must contain exactly web and xai")
    if {row.get("provider") for row in rows} != {"web", "xai"}:
        raise ParentPlanBuilderError("provider envelope input must contain exactly web and xai")
    normalized: list[dict[str, int | str]] = []
    for row in sorted(rows, key=lambda item: str(item.get("provider"))):
        if set(row) != expected_fields:
            raise ParentPlanBuilderError("provider envelope fields are not exact")
        provider = row["provider"]
        expected = (
            (query_count, query_count, 0, query_count * 2)
            if provider == "web"
            else (query_count, 0, 0, query_count)
        )
        actual = tuple(row[field] for field in (
            "stage1_max_dispatch_count", "stage2_max_dispatch_count",
            "retry_max_dispatch_count", "max_dispatch_count",
        ))
        if actual != expected:
            raise ParentPlanBuilderError(
                f"{provider} envelope must freeze the four-query stage-1/no-retry shape"
            )
        if any(type(item) is not int for item in actual):
            raise ParentPlanBuilderError(f"{provider} provider envelope counts must be integers")
        normalized.append({key: row[key] for key in expected_fields})
    return normalized


def build_parent_plan_from_reviewed_policy(
    *,
    decision_date: str,
    generated_at: str,
    policy_path: Path | str = DEFAULT_POLICY_PATH,
    provider_envelopes: Any | None = None,
) -> dict[str, Any]:
    """Render the reviewed policy into a schema-validated, no-free-text plan."""
    reviewed_path = _ensure_reviewed_policy_path(policy_path)
    probe_packet = _load_probe_packet()
    boundary = probe_packet["probe_boundary"]
    expected_date = boundary["expected_decision_date"]
    forbidden_dates = set(boundary["forbidden_reused_decision_dates"])
    if decision_date != expected_date or decision_date in forbidden_dates:
        raise ParentPlanBuilderError(
            "decision date is not the independent 20260808 probe packet slot"
        )
    try:
        policy = query_policy.load_query_policy(reviewed_path, root=ROOT)
    except query_policy.QueryPolicyError as exc:
        raise ParentPlanBuilderError("reviewed policy failed its own validation") from exc
    queries = _rendered_stage1_queries(policy, probe_packet)
    envelopes = _default_provider_envelopes(len(queries)) if provider_envelopes is None else _normalize_provider_envelopes(
        provider_envelopes, query_count=len(queries),
    )
    return query_plan.build_parent_plan(
        decision_date=decision_date,
        policy_version=policy["policy_version"],
        policy_template_content_sha256=policy["policy_content_sha256"],
        stage1_queries=queries,
        stage2_rule_sha256=query_policy.stage2_rule_sha256(policy),
        provider_envelopes=envelopes,
        generated_at=generated_at,
    )


def publish_parent_plan(
    payload: dict[str, Any], *, root: Path = ROOT, state_dir: Path = STATE_DIR,
) -> Path:
    """Publish one canonical decision-date/identity slot through the shared write door."""
    path = query_plan.default_parent_plan_path(
        payload["canonical_plan_core"]["decision_date"],
        payload["plan_identity"],
        state_dir=state_dir,
    )
    try:
        query_plan.write_parent_plan(payload, path, state_dir=state_dir, root=root)
    except query_plan.QueryPlanError as exc:
        raise ParentPlanBuilderError("cannot publish the canonical parent-plan slot") from exc
    return path.resolve()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the offline, policy-bound US-short 20260808 parent plan."
    )
    parser.add_argument("--policy-path", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--decision-date", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--provider-envelope-json", action="append", default=None,
        help="optional structured provider-envelope object; never accepts query text",
    )
    parser.add_argument(
        "--state-dir", type=Path, default=STATE_DIR,
        help="offline artifact directory; live consumers use the canonical state/us_short directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    provider_envelopes = None
    if args.provider_envelope_json is not None:
        try:
            provider_envelopes = [json.loads(value) for value in args.provider_envelope_json]
        except (TypeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"provider envelope JSON is invalid: {exc}") from exc
    try:
        payload = build_parent_plan_from_reviewed_policy(
            decision_date=args.decision_date,
            generated_at=args.generated_at,
            policy_path=args.policy_path,
            provider_envelopes=provider_envelopes,
        )
        state_dir = args.state_dir if args.state_dir.is_absolute() else ROOT / args.state_dir
        path = publish_parent_plan(payload, state_dir=state_dir.resolve())
    except (ParentPlanBuilderError, query_plan.QueryPlanError) as exc:
        raise SystemExit(f"parent plan build failed: {exc}") from exc
    print(json.dumps({
        "status": "parent_plan_written_offline",
        "artifact_path": path.relative_to(ROOT).as_posix(),
        "plan_identity": payload["plan_identity"],
        "decision_date": payload["canonical_plan_core"]["decision_date"],
        "query_count": len(payload["canonical_plan_core"]["stage1_queries"]),
        "provider_calls_performed": False,
        "network_access_performed": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
