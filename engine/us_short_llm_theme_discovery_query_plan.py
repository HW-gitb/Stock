"""Offline, source-bound query-plan artifacts for US-short soft discovery.

This module deliberately stops at the A1 contract boundary.  It does not fetch, call a
provider, activate the production query policy, or implement the deterministic Stage-2
planner.  It builds and validates the three time-separated state shapes required before
those later slices can be implemented:

* an immutable parent plan frozen before any paid dispatch;
* an immutable Stage-2 plan bound to a frozen Stage-1 artifact; and
* a mutable dispatch/event ledger plus an immutable final execution receipt.

All filesystem writes go through ``runners.us_short_discovery_publish_policy``.  The
canonical plan identities intentionally exclude clocks, output paths, and execution
results so a retry cannot change the identity of the work it claims to execute.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from engine.us_short_schema_formats import FORMAT_CHECKER
from runners.us_short_discovery_publish_policy import (
    DiscoveryPublishPolicyError,
    mutable_ledger_lock,
    validate_exact_decision_slot,
    write_immutable_json,
    write_mutable_ledger,
)


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state" / "us_short"
PARENT_SCHEMA = ROOT / "schemas" / "us_short_llm_theme_discovery_parent_plan.schema.json"
STAGE2_SCHEMA = ROOT / "schemas" / "us_short_llm_theme_discovery_stage2_plan.schema.json"
LEDGER_SCHEMA = ROOT / "schemas" / "us_short_llm_theme_discovery_consumption_ledger.schema.json"
RECEIPT_SCHEMA = ROOT / "schemas" / "us_short_llm_theme_discovery_execution_receipt.schema.json"
STAGE1_SCHEMA = ROOT / "schemas" / "us_short_llm_theme_discovery.schema.json"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DECISION_DATE_RE = re.compile(r"^[0-9]{8}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{1,127}$")
PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
PATH_PROBE_IDENTITY = "0" * 64


class QueryPlanError(ValueError):
    """An A1 query-plan contract or immutable/mutable slot was malformed."""


def _read_schema(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QueryPlanError(f"cannot load query-plan schema: {path.name}") from exc
    if type(value) is not dict:
        raise QueryPlanError(f"query-plan schema is not an object: {path.name}")
    return value


def _validate(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - project test/runtime dependency
        raise QueryPlanError("jsonschema is required for the query-plan contract") from exc
    errors = sorted(
        Draft7Validator(_read_schema(schema_path), format_checker=FORMAT_CHECKER).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        raise QueryPlanError(f"{label} schema rejected: {errors[0].message}")


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise QueryPlanError("query-plan canonical core is not serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _ensure_digest(value: Any, *, field: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise QueryPlanError(f"{field} must be a lowercase SHA-256")
    return value


def _ensure_decision_date(value: Any) -> str:
    if type(value) is not str or DECISION_DATE_RE.fullmatch(value) is None:
        raise QueryPlanError("decision_date must be a real YYYYMMDD date")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise QueryPlanError("decision_date must be a real YYYYMMDD date") from exc
    return value


def _ensure_identifier(value: Any, *, field: str) -> str:
    if type(value) is not str or IDENTIFIER_RE.fullmatch(value) is None:
        raise QueryPlanError(f"{field} is malformed")
    return value


def _repo_relative(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise QueryPlanError("query-plan artifact path must stay under the repository root") from exc


def _read_artifact(path: Path, *, root: Path) -> tuple[dict[str, Any], str, str]:
    candidate = Path(path)
    if candidate.is_symlink():
        raise QueryPlanError("query-plan artifact path may not be a symlink")
    _repo_relative(candidate, root=root)
    resolved = candidate.resolve()
    try:
        raw = resolved.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QueryPlanError(f"query-plan artifact is unreadable: {resolved}") from exc
    if type(value) is not dict:
        raise QueryPlanError("query-plan artifact root must be an object")
    return value, hashlib.sha256(raw).hexdigest(), _repo_relative(resolved, root=root)


def _artifact_ref(path: Path, digest: str, *, root: Path) -> dict[str, str]:
    return {"path": _repo_relative(path, root=root), "sha256": _ensure_digest(digest, field="artifact sha256")}


def _nullable_artifact_ref() -> dict[str, None]:
    """Keep an absent later-stage binding closed without using an untyped null object."""
    return {"path": None, "sha256": None}


def _normalize_stage1_queries(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, (list, tuple)) or not value:
        raise QueryPlanError("stage1_queries must be a non-empty ordered list")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) != {"query_id", "query_text"}:
            raise QueryPlanError("each stage1 query must contain exactly query_id and query_text")
        query_id = _ensure_identifier(item["query_id"], field=f"stage1_queries[{index}].query_id")
        query_text = item["query_text"]
        if type(query_text) is not str or not query_text.strip():
            raise QueryPlanError(f"stage1_queries[{index}].query_text must be non-empty text")
        if query_id in seen:
            raise QueryPlanError("stage1 query ids must be unique")
        seen.add(query_id)
        result.append({"query_id": query_id, "query_text": query_text})
    return result


def _normalize_provider_envelopes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or not value:
        raise QueryPlanError("provider_envelopes must be a non-empty ordered list")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise QueryPlanError(f"provider_envelopes[{index}] must be an object")
        expected = {
            "provider", "stage1_max_dispatch_count", "stage2_max_dispatch_count",
            "retry_max_dispatch_count", "max_dispatch_count",
        }
        if set(item) != expected:
            raise QueryPlanError(f"provider_envelopes[{index}] has unexpected fields")
        provider = item["provider"]
        if type(provider) is not str or PROVIDER_RE.fullmatch(provider) is None:
            raise QueryPlanError(f"provider_envelopes[{index}].provider is malformed")
        if provider in seen:
            raise QueryPlanError("provider envelopes must have unique providers")
        seen.add(provider)
        counts = {key: item[key] for key in expected if key != "provider"}
        if any(type(count) is not int or count < 0 for count in counts.values()):
            raise QueryPlanError(f"provider_envelopes[{index}] counts must be non-negative integers")
        expected_max = (
            counts["stage1_max_dispatch_count"]
            + counts["stage2_max_dispatch_count"]
            + counts["retry_max_dispatch_count"]
        )
        if counts["max_dispatch_count"] != expected_max:
            raise QueryPlanError(f"provider_envelopes[{index}] max_dispatch_count is not the sum of its stages")
        result.append({"provider": provider, **counts})
    return sorted(result, key=lambda row: row["provider"])


def _parent_core(
    *, decision_date: str, policy_version: str, policy_template_content_sha256: str,
    stage1_queries: Any, stage2_rule_sha256: str, provider_envelopes: Any,
) -> dict[str, Any]:
    return {
        "decision_date": _ensure_decision_date(decision_date),
        "policy_version": _ensure_identifier(policy_version, field="policy_version"),
        "policy_template_content_sha256": _ensure_digest(
            policy_template_content_sha256, field="policy_template_content_sha256"
        ),
        "stage1_queries": _normalize_stage1_queries(stage1_queries),
        "stage2_rule_sha256": _ensure_digest(stage2_rule_sha256, field="stage2_rule_sha256"),
        "provider_envelopes": _normalize_provider_envelopes(provider_envelopes),
    }


def _effect_boundary() -> dict[str, bool]:
    return {
        "scoring_eligible": False,
        "top15_effect_enabled": False,
        "operation_advice_effect_enabled": False,
        "dynamic_seats_enabled": False,
        "theme_probe_enabled": False,
        "lifecycle_actions_enabled": False,
    }


def build_parent_plan(
    *, decision_date: str, policy_version: str, policy_template_content_sha256: str,
    stage1_queries: Any, stage2_rule_sha256: str, provider_envelopes: Any,
    generated_at: str, activation_status: str = "candidate_offline",
) -> dict[str, Any]:
    """Build the immutable pre-dispatch parent plan and its canonical identity."""
    core = _parent_core(
        decision_date=decision_date, policy_version=policy_version,
        policy_template_content_sha256=policy_template_content_sha256,
        stage1_queries=stage1_queries, stage2_rule_sha256=stage2_rule_sha256,
        provider_envelopes=provider_envelopes,
    )
    payload = {
        "schema_name": "us_short_llm_theme_discovery_parent_plan",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "plan_identity": _digest(core),
        "canonical_plan_core": core,
        "activation_status": activation_status,
        "effect_boundary": _effect_boundary(),
    }
    validate_parent_plan(payload)
    return payload


def validate_parent_plan(payload: dict[str, Any]) -> bool:
    _validate(payload, PARENT_SCHEMA, label="parent query plan")
    core = payload["canonical_plan_core"]
    if payload["plan_identity"] != _digest(core):
        raise QueryPlanError("parent plan_identity does not match its canonical plan core")
    _parent_core(
        decision_date=core["decision_date"], policy_version=core["policy_version"],
        policy_template_content_sha256=core["policy_template_content_sha256"],
        stage1_queries=core["stage1_queries"], stage2_rule_sha256=core["stage2_rule_sha256"],
        provider_envelopes=core["provider_envelopes"],
    )
    return True


def default_parent_plan_path(
    decision_date: str, plan_identity: str | None = None, *, state_dir: Path = STATE_DIR,
) -> Path:
    _ensure_decision_date(decision_date)
    plan_identity = PATH_PROBE_IDENTITY if plan_identity is None else plan_identity
    _ensure_digest(plan_identity, field="plan_identity")
    return Path(state_dir) / f"us_short_llm_theme_discovery_query_plan_parent_{decision_date}_{plan_identity}.json"


def _normalize_artifact_path(path: Path | str, *, root: Path) -> Path:
    candidate = Path(path)
    candidate = candidate if candidate.is_absolute() else Path(root) / candidate
    if candidate.is_symlink():
        raise QueryPlanError("query-plan artifact path may not be a symlink")
    _repo_relative(candidate, root=root)
    return candidate.absolute()


def _stage1_source_ids(stage1: dict[str, Any]) -> set[str]:
    return {row["source_id"] for row in stage1.get("source_refs", [])}


def _normalize_focus_terms(value: Any, *, source_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or not value:
        raise QueryPlanError("focus_terms must be a non-empty ordered list")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) != {"term", "term_type", "source_ref_ids"}:
            raise QueryPlanError("each focus term must contain term, term_type, source_ref_ids")
        term = item["term"]
        term_type = item["term_type"]
        refs = item["source_ref_ids"]
        if type(term) is not str or not term.strip():
            raise QueryPlanError(f"focus_terms[{index}].term must be non-empty text")
        if term_type not in {"company", "ticker", "industry", "concept"}:
            raise QueryPlanError(f"focus_terms[{index}].term_type is unsupported")
        if not isinstance(refs, (list, tuple)) or not refs:
            raise QueryPlanError(f"focus_terms[{index}].source_ref_ids must be non-empty")
        normalized_refs = [
            _ensure_identifier(ref, field=f"focus_terms[{index}].source_ref_ids") for ref in refs
        ]
        if len(set(normalized_refs)) != len(normalized_refs) or not set(normalized_refs) <= source_ids:
            raise QueryPlanError("focus term source refs must be unique and present in Stage-1")
        key = (term_type, term)
        if key in seen:
            raise QueryPlanError("focus terms must be unique by type and term")
        seen.add(key)
        result.append({"term": term, "term_type": term_type, "source_ref_ids": normalized_refs})
    return result


def _normalize_stage2_queries(value: Any, *, focus_terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or not value:
        raise QueryPlanError("stage2_queries must be a non-empty ordered list")
    focus_lookup = {(row["term_type"], row["term"]): row for row in focus_terms}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        expected = {"query_id", "query_text", "focus_term", "focus_term_type", "source_ref_ids"}
        if not isinstance(item, Mapping) or set(item) != expected:
            raise QueryPlanError("each Stage-2 query has an incomplete or unexpected field set")
        query_id = _ensure_identifier(item["query_id"], field=f"stage2_queries[{index}].query_id")
        query_text = item["query_text"]
        term = item["focus_term"]
        term_type = item["focus_term_type"]
        refs = item["source_ref_ids"]
        if type(query_text) is not str or not query_text.strip():
            raise QueryPlanError(f"stage2_queries[{index}].query_text must be non-empty text")
        if query_id in seen:
            raise QueryPlanError("Stage-2 query ids must be unique")
        focus = focus_lookup.get((term_type, term))
        if focus is None:
            raise QueryPlanError("Stage-2 query focus term is not in the frozen focus-term set")
        if not isinstance(refs, (list, tuple)) or not refs:
            raise QueryPlanError("Stage-2 query source refs must be non-empty")
        normalized_refs = [
            _ensure_identifier(ref, field=f"stage2_queries[{index}].source_ref_ids") for ref in refs
        ]
        if len(set(normalized_refs)) != len(normalized_refs) or not set(normalized_refs) <= set(focus["source_ref_ids"]):
            raise QueryPlanError("Stage-2 query source refs must be a subset of its Stage-1 focus refs")
        seen.add(query_id)
        result.append({
            "query_id": query_id, "query_text": query_text, "focus_term": term,
            "focus_term_type": term_type, "source_ref_ids": normalized_refs,
        })
    return result


def default_stage2_plan_path(
    decision_date: str, plan_identity: str | None = None, *, state_dir: Path = STATE_DIR,
) -> Path:
    _ensure_decision_date(decision_date)
    plan_identity = PATH_PROBE_IDENTITY if plan_identity is None else plan_identity
    _ensure_digest(plan_identity, field="plan_identity")
    return Path(state_dir) / f"us_short_llm_theme_discovery_query_plan_stage2_{decision_date}_{plan_identity}.json"


def build_stage2_plan(
    *, parent_plan: dict[str, Any], parent_plan_path: Path | str, stage1_artifact_path: Path | str,
    focus_terms: Any, stage2_queries: Any, generated_at: str, root: Path = ROOT,
    activation_status: str = "candidate_offline",
) -> dict[str, Any]:
    """Build a separate Stage-2 frozen artifact from one already-frozen Stage-1 artifact."""
    validate_parent_plan(parent_plan)
    root = Path(root).resolve()
    parent_path = _normalize_artifact_path(parent_plan_path, root=root)
    loaded_parent, parent_sha, _parent_rel = _read_artifact(parent_path, root=root)
    validate_parent_plan(loaded_parent)
    if loaded_parent != parent_plan:
        raise QueryPlanError("parent plan bytes do not match the supplied parent plan")
    if loaded_parent["plan_identity"] != parent_plan["plan_identity"]:
        raise QueryPlanError("parent plan identity changed before Stage-2 planning")

    stage1_path = _normalize_artifact_path(stage1_artifact_path, root=root)
    stage1, stage1_sha, _stage1_rel = _read_artifact(stage1_path, root=root)
    _validate(stage1, STAGE1_SCHEMA, label="frozen Stage-1 discovery artifact")
    decision_date = parent_plan["canonical_plan_core"]["decision_date"]
    if stage1["decision_clock"]["expected_decision_date"] != decision_date:
        raise QueryPlanError("Stage-1 decision date does not match parent plan")
    source_ids = _stage1_source_ids(stage1)
    normalized_focus = _normalize_focus_terms(focus_terms, source_ids=source_ids)
    normalized_queries = _normalize_stage2_queries(stage2_queries, focus_terms=normalized_focus)
    provider_binding = _digest(parent_plan["canonical_plan_core"]["provider_envelopes"])
    core = {
        "decision_date": decision_date,
        "parent_plan_identity": parent_plan["plan_identity"],
        "parent_plan_artifact": _artifact_ref(parent_path, parent_sha, root=root),
        "stage1_artifact": _artifact_ref(stage1_path, stage1_sha, root=root),
        "stage2_rule_sha256": parent_plan["canonical_plan_core"]["stage2_rule_sha256"],
        "provider_envelope_binding_sha256": provider_binding,
        "focus_terms": normalized_focus,
        "stage2_queries": normalized_queries,
    }
    payload = {
        "schema_name": "us_short_llm_theme_discovery_stage2_plan",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "plan_identity": _digest(core),
        "canonical_stage2_core": core,
        "activation_status": activation_status,
        "effect_boundary": _effect_boundary(),
    }
    validate_stage2_plan(payload)
    return payload


def validate_stage2_plan(payload: dict[str, Any]) -> bool:
    _validate(payload, STAGE2_SCHEMA, label="Stage-2 query plan")
    core = payload["canonical_stage2_core"]
    if payload["plan_identity"] != _digest(core):
        raise QueryPlanError("Stage-2 plan_identity does not match its canonical core")
    if len({row["query_id"] for row in core["stage2_queries"]}) != len(core["stage2_queries"]):
        raise QueryPlanError("Stage-2 query ids must be unique")
    focus_lookup = {(row["term_type"], row["term"]): row for row in core["focus_terms"]}
    for row in core["stage2_queries"]:
        focus = focus_lookup.get((row["focus_term_type"], row["focus_term"]))
        if focus is None or not set(row["source_ref_ids"]) <= set(focus["source_ref_ids"]):
            raise QueryPlanError("Stage-2 query lineage is not source-bound to its focus term")
    return True


def _parent_and_stage2_refs(
    *, parent_plan: dict[str, Any], parent_plan_path: Path | str,
    stage2_plan: dict[str, Any] | None, stage2_plan_path: Path | str | None,
    root: Path,
) -> tuple[dict[str, str], dict[str, str | None]]:
    validate_parent_plan(parent_plan)
    parent_path = _normalize_artifact_path(parent_plan_path, root=root)
    loaded_parent, parent_sha, _ = _read_artifact(parent_path, root=root)
    validate_parent_plan(loaded_parent)
    if loaded_parent != parent_plan:
        raise QueryPlanError("parent plan bytes changed before ledger/receipt construction")
    parent_ref = _artifact_ref(parent_path, parent_sha, root=root)
    if stage2_plan is None:
        if stage2_plan_path is not None:
            raise QueryPlanError("stage2_plan_path requires a Stage-2 plan")
        return parent_ref, _nullable_artifact_ref()
    if stage2_plan_path is None:
        raise QueryPlanError("Stage-2 plan requires stage2_plan_path")
    validate_stage2_plan(stage2_plan)
    stage2_path = _normalize_artifact_path(stage2_plan_path, root=root)
    loaded_stage2, stage2_sha, _ = _read_artifact(stage2_path, root=root)
    validate_stage2_plan(loaded_stage2)
    if loaded_stage2 != stage2_plan:
        raise QueryPlanError("Stage-2 plan bytes changed before ledger/receipt construction")
    if loaded_stage2["canonical_stage2_core"]["parent_plan_identity"] != parent_plan["plan_identity"]:
        raise QueryPlanError("Stage-2 plan is bound to a different parent identity")
    return parent_ref, _artifact_ref(stage2_path, stage2_sha, root=root)


def default_consumption_ledger_path(
    decision_date: str, parent_plan_identity: str | None = None, *, state_dir: Path = STATE_DIR,
) -> Path:
    _ensure_decision_date(decision_date)
    parent_plan_identity = PATH_PROBE_IDENTITY if parent_plan_identity is None else parent_plan_identity
    _ensure_digest(parent_plan_identity, field="parent_plan_identity")
    return Path(state_dir) / (
        f"us_short_llm_theme_discovery_query_plan_{decision_date}_{parent_plan_identity}_consumption.json"
    )


def _normalize_events(events: Any, *, provider_limits: dict[str, int], has_stage2: bool) -> list[dict[str, Any]]:
    if not isinstance(events, (list, tuple)):
        raise QueryPlanError("consumption events must be a list")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_attempts: set[tuple[str, str, str, int]] = set()
    terminal_types = {"completion", "failure", "unknown"}
    for index, item in enumerate(events):
        expected = {"sequence", "event_id", "stage", "provider", "query_id", "event_type", "attempt", "occurred_at"}
        if not isinstance(item, Mapping) or set(item) != expected:
            raise QueryPlanError("each consumption event has an incomplete or unexpected field set")
        if item["sequence"] != index + 1 or type(item["sequence"]) is not int:
            raise QueryPlanError("consumption event sequence must be contiguous")
        event_id = _ensure_identifier(item["event_id"], field="consumption event_id")
        stage = item["stage"]
        provider = item["provider"]
        query_id = _ensure_identifier(item["query_id"], field="consumption query_id")
        event_type = item["event_type"]
        attempt = item["attempt"]
        if event_id in seen_ids:
            raise QueryPlanError("consumption event ids must be unique")
        if stage not in {"stage1", "stage2"} or (stage == "stage2" and not has_stage2):
            raise QueryPlanError("consumption event stage is not bound to the supplied plans")
        if type(provider) is not str or provider not in provider_limits:
            raise QueryPlanError("consumption event provider is outside the parent envelope")
        if event_type not in {"dispatch", "completion", "failure", "unknown"}:
            raise QueryPlanError("unsupported consumption event type")
        if type(attempt) is not int or attempt < 1:
            raise QueryPlanError("consumption event attempt must be a positive integer")
        key = (stage, provider, query_id, attempt)
        if event_type == "dispatch" and key in seen_attempts:
            raise QueryPlanError("a dispatch attempt may be recorded only once")
        if event_type == "dispatch":
            seen_attempts.add(key)
        elif event_type in terminal_types and key not in seen_attempts:
            raise QueryPlanError("a terminal consumption event must follow its dispatch")
        seen_ids.add(event_id)
        normalized.append(dict(item))
    return normalized


def _dispatch_bucket(stage: str, attempt: int) -> str:
    if attempt > 1:
        return "retry"
    return stage


def _provider_totals(events: list[dict[str, Any]], envelopes: list[dict[str, Any]]) -> list[dict[str, int | str]]:
    totals: dict[str, dict[str, int | str]] = {
        row["provider"]: {
            "provider": row["provider"],
            "stage1_max_dispatch_count": row["stage1_max_dispatch_count"],
            "stage2_max_dispatch_count": row["stage2_max_dispatch_count"],
            "retry_max_dispatch_count": row["retry_max_dispatch_count"],
            "max_dispatch_count": row["max_dispatch_count"],
            "stage1_dispatch_count": 0,
            "stage2_dispatch_count": 0,
            "retry_dispatch_count": 0,
            "dispatch_count": 0,
            "completion_count": 0,
            "failure_count": 0,
            "unknown_count": 0,
        }
        for row in envelopes
    }
    for event in events:
        if event["event_type"] == "dispatch":
            bucket = _dispatch_bucket(event["stage"], event["attempt"])
            totals[event["provider"]][f"{bucket}_dispatch_count"] += 1
        elif event["event_type"] == "completion":
            totals[event["provider"]]["completion_count"] += 1
        elif event["event_type"] == "failure":
            totals[event["provider"]]["failure_count"] += 1
        else:
            totals[event["provider"]]["unknown_count"] += 1
    result = []
    for row in totals.values():
        row["dispatch_count"] = sum(
            row[field] for field in ("stage1_dispatch_count", "stage2_dispatch_count", "retry_dispatch_count")
        )
        for count_field, max_field in (
            ("stage1_dispatch_count", "stage1_max_dispatch_count"),
            ("stage2_dispatch_count", "stage2_max_dispatch_count"),
            ("retry_dispatch_count", "retry_max_dispatch_count"),
        ):
            if row[count_field] > row[max_field]:
                raise QueryPlanError(f"provider {row['provider']} {count_field} exceeds its envelope")
        if row["dispatch_count"] > row["max_dispatch_count"]:
            raise QueryPlanError(f"provider {row['provider']} dispatches exceed the parent envelope")
        row["remaining_dispatch_count"] = row["max_dispatch_count"] - row["dispatch_count"]
        result.append(row)
    return result


def build_consumption_ledger(
    *, parent_plan: dict[str, Any], parent_plan_path: Path | str,
    stage2_plan: dict[str, Any] | None = None, stage2_plan_path: Path | str | None = None,
    events: Any = (), generated_at: str, status: str = "not_started", root: Path = ROOT,
) -> dict[str, Any]:
    """Build the mutable event ledger without changing either frozen plan."""
    root = Path(root).resolve()
    parent_ref, stage2_ref = _parent_and_stage2_refs(
        parent_plan=parent_plan, parent_plan_path=parent_plan_path,
        stage2_plan=stage2_plan, stage2_plan_path=stage2_plan_path, root=root,
    )
    core = parent_plan["canonical_plan_core"]
    limits = {row["provider"]: row["max_dispatch_count"] for row in core["provider_envelopes"]}
    normalized_events = _normalize_events(events, provider_limits=limits, has_stage2=stage2_plan is not None)
    totals = _provider_totals(normalized_events, core["provider_envelopes"])
    payload = {
        "schema_name": "us_short_llm_theme_discovery_consumption_ledger",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "decision_date": core["decision_date"],
        "parent_plan_identity": parent_plan["plan_identity"],
        "parent_plan_artifact": parent_ref,
        "stage2_plan_identity": stage2_plan["plan_identity"] if stage2_plan is not None else None,
        "stage2_plan_artifact": stage2_ref,
        "provider_envelope_binding_sha256": _digest(core["provider_envelopes"]),
        "events": normalized_events,
        "provider_totals": totals,
        "status": status,
        "mutable": True,
        "effect_boundary": _effect_boundary(),
    }
    validate_consumption_ledger(payload)
    return payload


def validate_consumption_ledger(payload: dict[str, Any]) -> bool:
    _validate(payload, LEDGER_SCHEMA, label="query-plan consumption ledger")
    events = payload["events"]
    dispatch_keys = {
        (event["stage"], event["provider"], event["query_id"], event["attempt"])
        for event in events if event["event_type"] == "dispatch"
    }
    terminal_keys: set[tuple[str, str, str, int]] = set()
    observed: dict[str, dict[str, int]] = {}
    for event in events:
        key = (event["stage"], event["provider"], event["query_id"], event["attempt"])
        row = observed.setdefault(event["provider"], {
            "stage1_dispatch_count": 0, "stage2_dispatch_count": 0, "retry_dispatch_count": 0,
            "dispatch_count": 0, "completion_count": 0, "failure_count": 0, "unknown_count": 0,
        })
        if event["event_type"] == "dispatch":
            row[f"{_dispatch_bucket(event['stage'], event['attempt'])}_dispatch_count"] += 1
            row["dispatch_count"] += 1
        else:
            if key not in dispatch_keys:
                raise QueryPlanError("terminal consumption event has no dispatch")
            if key in terminal_keys:
                raise QueryPlanError("a dispatch attempt may have only one terminal event")
            terminal_keys.add(key)
            row[f"{event['event_type']}_count"] += 1
    declared = {row["provider"]: row for row in payload["provider_totals"]}
    if len(declared) != len(payload["provider_totals"]):
        raise QueryPlanError("provider totals must have unique providers")
    for provider, row in declared.items():
        counts = observed.get(provider, {
            "stage1_dispatch_count": 0, "stage2_dispatch_count": 0, "retry_dispatch_count": 0,
            "dispatch_count": 0, "completion_count": 0, "failure_count": 0, "unknown_count": 0,
        })
        for field, expected in counts.items():
            if row[field] != expected:
                raise QueryPlanError(f"provider total {provider}.{field} does not match its events")
        if row["dispatch_count"] != sum(
            row[field] for field in ("stage1_dispatch_count", "stage2_dispatch_count", "retry_dispatch_count")
        ):
            raise QueryPlanError(f"provider total {provider}.dispatch_count is inconsistent with stage buckets")
        for count_field, max_field in (
            ("stage1_dispatch_count", "stage1_max_dispatch_count"),
            ("stage2_dispatch_count", "stage2_max_dispatch_count"),
            ("retry_dispatch_count", "retry_max_dispatch_count"),
        ):
            if row[count_field] > row[max_field]:
                raise QueryPlanError(f"provider total {provider}.{count_field} exceeds its envelope")
        if row["max_dispatch_count"] != sum(
            row[field] for field in (
                "stage1_max_dispatch_count", "stage2_max_dispatch_count", "retry_max_dispatch_count",
            )
        ):
            raise QueryPlanError(f"provider total {provider}.max_dispatch_count is not the sum of its stages")
        if row["dispatch_count"] > row["max_dispatch_count"]:
            raise QueryPlanError("consumption ledger exceeds a provider envelope")
        if row["remaining_dispatch_count"] != row["max_dispatch_count"] - row["dispatch_count"]:
            raise QueryPlanError(f"provider total {provider}.remaining_dispatch_count is inconsistent")
    if set(observed) - set(declared):
        raise QueryPlanError("consumption event provider is missing from provider totals")
    if any(event["stage"] == "stage2" for event in events) and payload["stage2_plan_identity"] is None:
        raise QueryPlanError("Stage-2 consumption requires a bound Stage-2 plan identity")
    if sum(row["unknown_count"] for row in payload["provider_totals"]) > 0 and payload["status"] not in {"in_flight", "inconclusive"}:
        raise QueryPlanError("unknown consumption must remain in-flight or inconclusive")
    return True


def write_parent_plan(
    payload: dict[str, Any], path: Path | str, *, state_dir: Path = STATE_DIR,
    root: Path = ROOT, gitignored: Callable[[Path], bool] | None = None,
) -> None:
    validate_parent_plan(payload)
    expected = default_parent_plan_path(
        payload["canonical_plan_core"]["decision_date"], payload["plan_identity"], state_dir=state_dir,
    )
    try:
        resolved = validate_exact_decision_slot(Path(path), expected, root=root, state_dir=Path(state_dir), gitignored=gitignored)
        write_immutable_json(payload, resolved, verify=validate_parent_plan)
    except DiscoveryPublishPolicyError as exc:
        raise QueryPlanError("cannot publish immutable parent query plan") from exc


def write_stage2_plan(
    payload: dict[str, Any], path: Path | str, *, state_dir: Path = STATE_DIR,
    root: Path = ROOT, gitignored: Callable[[Path], bool] | None = None,
) -> None:
    validate_stage2_plan(payload)
    decision_date = payload["canonical_stage2_core"]["decision_date"]
    expected = default_stage2_plan_path(decision_date, payload["plan_identity"], state_dir=state_dir)
    try:
        resolved = validate_exact_decision_slot(Path(path), expected, root=root, state_dir=Path(state_dir), gitignored=gitignored)
        write_immutable_json(payload, resolved, verify=validate_stage2_plan)
    except DiscoveryPublishPolicyError as exc:
        raise QueryPlanError("cannot publish immutable Stage-2 query plan") from exc


def write_consumption_ledger(
    payload: dict[str, Any], path: Path | str, *, state_dir: Path = STATE_DIR,
    root: Path = ROOT, gitignored: Callable[[Path], bool] | None = None,
) -> None:
    validate_consumption_ledger(payload)
    expected = default_consumption_ledger_path(
        payload["decision_date"], payload["parent_plan_identity"], state_dir=state_dir,
    )
    try:
        resolved = validate_exact_decision_slot(Path(path), expected, root=root, state_dir=Path(state_dir), gitignored=gitignored)
        with mutable_ledger_lock(resolved):
            write_mutable_ledger(
                payload, resolved, root=Path(root), state_dir=Path(state_dir),
                gitignored=gitignored, ledger_kind="query_plan_consumption",
            )
    except DiscoveryPublishPolicyError as exc:
        raise QueryPlanError("cannot update query-plan consumption ledger") from exc


def default_execution_receipt_path(
    decision_date: str, parent_plan_identity: str | None = None, *, state_dir: Path = STATE_DIR,
) -> Path:
    _ensure_decision_date(decision_date)
    parent_plan_identity = PATH_PROBE_IDENTITY if parent_plan_identity is None else parent_plan_identity
    _ensure_digest(parent_plan_identity, field="parent_plan_identity")
    return Path(state_dir) / (
        f"us_short_llm_theme_discovery_query_plan_{decision_date}_{parent_plan_identity}_execution_receipt.json"
    )


def build_execution_receipt(
    *, ledger: dict[str, Any], ledger_path: Path | str, status: str,
    provider_calls_performed: bool, generated_at: str, root: Path = ROOT,
    execution_mode: str = "offline_test",
) -> dict[str, Any]:
    """Freeze a final receipt bound to the exact mutable-ledger bytes observed at closeout."""
    validate_consumption_ledger(ledger)
    root = Path(root).resolve()
    ledger_resolved = _normalize_artifact_path(ledger_path, root=root)
    loaded_ledger, ledger_sha, _ = _read_artifact(ledger_resolved, root=root)
    validate_consumption_ledger(loaded_ledger)
    if loaded_ledger != ledger:
        raise QueryPlanError("consumption ledger bytes changed before receipt construction")
    events = ledger["events"]
    stages = []
    for event in events:
        if event["stage"] not in stages:
            stages.append(event["stage"])
    if not stages:
        stages = ["stage1"]
    unknown_count = sum(row["unknown_count"] for row in ledger["provider_totals"])
    payload = {
        "schema_name": "us_short_llm_theme_discovery_execution_receipt",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "decision_date": ledger["decision_date"],
        "parent_plan_identity": ledger["parent_plan_identity"],
        "stage2_plan_identity": ledger["stage2_plan_identity"],
        "parent_plan_artifact": ledger["parent_plan_artifact"],
        "stage2_plan_artifact": ledger["stage2_plan_artifact"],
        "consumption_ledger_artifact": _artifact_ref(ledger_resolved, ledger_sha, root=root),
        "status": status,
        "stage_sequence": stages,
        "provider_totals": ledger["provider_totals"],
        "unknown_dispatch_count": unknown_count,
        "replay_policy": "unknown_dispatches_are_consumed_no_auto_replay",
        "provider_calls_performed": provider_calls_performed,
        "execution_mode": execution_mode,
        "effect_boundary": _effect_boundary(),
    }
    validate_execution_receipt(payload)
    return payload


def validate_execution_receipt(payload: dict[str, Any]) -> bool:
    _validate(payload, RECEIPT_SCHEMA, label="query-plan execution receipt")
    observed_unknown = sum(row["unknown_count"] for row in payload["provider_totals"])
    if payload["unknown_dispatch_count"] != observed_unknown:
        raise QueryPlanError("receipt unknown_dispatch_count does not match provider totals")
    if payload["unknown_dispatch_count"] > 0 and payload["status"] not in {"inconclusive", "unknown_in_flight"}:
        raise QueryPlanError("receipt with unknown dispatches must remain inconclusive")
    if payload["execution_mode"] == "offline_test" and payload["provider_calls_performed"]:
        raise QueryPlanError("offline_test receipt cannot claim provider calls")
    return True


def write_execution_receipt(
    payload: dict[str, Any], path: Path | str, *, state_dir: Path = STATE_DIR,
    root: Path = ROOT, gitignored: Callable[[Path], bool] | None = None,
) -> None:
    validate_execution_receipt(payload)
    expected = default_execution_receipt_path(
        payload["decision_date"], payload["parent_plan_identity"], state_dir=state_dir,
    )
    try:
        resolved = validate_exact_decision_slot(Path(path), expected, root=root, state_dir=Path(state_dir), gitignored=gitignored)
        write_immutable_json(payload, resolved, verify=validate_execution_receipt)
    except DiscoveryPublishPolicyError as exc:
        raise QueryPlanError("cannot publish immutable query-plan execution receipt") from exc


__all__ = [
    "QueryPlanError", "build_parent_plan", "validate_parent_plan", "write_parent_plan",
    "default_parent_plan_path", "build_stage2_plan", "validate_stage2_plan", "write_stage2_plan",
    "default_stage2_plan_path", "build_consumption_ledger", "validate_consumption_ledger",
    "write_consumption_ledger", "default_consumption_ledger_path", "build_execution_receipt",
    "validate_execution_receipt", "write_execution_receipt", "default_execution_receipt_path",
]
