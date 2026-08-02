"""Pure deterministic Stage-2 planner for the US-short soft-discovery lane.

The planner consumes a validated, frozen Stage-1 payload and the versioned
candidate-offline policy.  It only projects structured values already present in
Stage-1: theme ``display_name`` becomes a source-bound ``concept`` term and each
member ``ticker`` becomes a source-bound ``ticker`` term.  It never guesses a
company/industry name from prose, consumes Stage-2 output, writes a file, calls a
provider, or changes selection/confirmation/seat/probe/lifecycle effects.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unicodedata
from typing import Any, Mapping

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_llm_theme_discovery_query_policy import (
    POLICY_PATH,
    QueryPolicyError,
    load_query_policy,
    validate_query_policy,
)
from engine.us_short_schema_formats import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[1]
STAGE1_SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery.schema.json"


class Stage2PlannerError(ValueError):
    """A malformed Stage-1 term or deterministic Stage-2 policy result."""


def _read_schema(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise Stage2PlannerError("Stage-1 schema is unreadable") from exc
    if type(value) is not dict:
        raise Stage2PlannerError("Stage-1 schema must be an object")
    return value


def _validate_stage1(stage1: Mapping[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - project dependency guard
        raise Stage2PlannerError("jsonschema is required for Stage-2 planning") from exc
    errors = sorted(
        Draft7Validator(_read_schema(STAGE1_SCHEMA_PATH), format_checker=FORMAT_CHECKER).iter_errors(stage1),
        key=lambda error: list(error.path),
    )
    if errors:
        raise Stage2PlannerError(f"frozen Stage-1 artifact rejected: {errors[0].message}")


def _canonical_discovery_term(value: Any, *, field: str) -> str:
    """Canonicalize a frozen structured Stage-1 term under the policy rules."""
    if type(value) is not str:
        raise Stage2PlannerError(f"{field} must be text")
    normalized = " ".join(unicodedata.normalize("NFC", value).strip().split()).casefold()
    if not normalized:
        raise Stage2PlannerError(f"{field} is empty after normalization")
    return normalized


def _normalize_ticker(value: Any, *, field: str) -> str:
    normalized = canonical_us_ticker(value)
    if normalized is None:
        raise Stage2PlannerError(f"{field} is not a canonical ticker")
    return normalized


def _source_ids(stage1: Mapping[str, Any]) -> set[str]:
    ids = [row["source_id"] for row in stage1["source_refs"]]
    if len(set(ids)) != len(ids):
        raise Stage2PlannerError("frozen Stage-1 source_ref ids must be unique")
    return set(ids)


def _source_bound_refs(value: Any, *, source_ids: set[str], field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise Stage2PlannerError(f"{field} must contain source refs")
    refs = tuple(sorted(set(value)))
    if any(type(ref) is not str or ref not in source_ids for ref in refs):
        raise Stage2PlannerError(f"{field} contains a source ref absent from frozen Stage-1 source_refs")
    return refs


def _term_digest(term_type: str, term: str) -> str:
    payload = json.dumps(
        {"term_type": term_type, "term": term},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def derive_stage2_plan_inputs(
    stage1_artifact: Mapping[str, Any],
    policy: Mapping[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return deterministic focus terms and Stage-2 queries from frozen Stage-1 only."""
    _validate_stage1(stage1_artifact)
    policy_payload = load_query_policy() if policy is None else policy
    try:
        validate_query_policy(policy_payload)
    except QueryPolicyError as exc:
        raise Stage2PlannerError("Stage-2 policy is not a validated candidate-offline policy") from exc

    stage2_policy = policy_payload["policy_core"]["stage2"]
    source_ids = _source_ids(stage1_artifact)
    terms: dict[tuple[str, str], set[str]] = {}
    for theme_index, theme in enumerate(stage1_artifact["themes"]):
        theme_refs = _source_bound_refs(
            theme["source_ref_ids"], source_ids=source_ids,
            field=f"themes[{theme_index}].source_ref_ids",
        )
        concept = _canonical_discovery_term(theme["display_name"], field=f"themes[{theme_index}].display_name")
        terms.setdefault(("concept", concept), set()).update(theme_refs)
        for member_index, member in enumerate(theme["members"]):
            member_refs = _source_bound_refs(
                member["source_ref_ids"], source_ids=source_ids,
                field=f"themes[{theme_index}].members[{member_index}].source_ref_ids",
            )
            ticker = _normalize_ticker(
                member["ticker"], field=f"themes[{theme_index}].members[{member_index}].ticker",
            )
            terms.setdefault(("ticker", ticker), set()).update(member_refs)

    type_rank = stage2_policy["term_type_rank"]
    ordered_keys = sorted(
        terms,
        key=lambda key: (type_rank[key[0]], key[1], tuple(sorted(terms[key]))),
    )
    counts = {term_type: 0 for term_type in stage2_policy["allowed_term_types"]}
    max_by_type = stage2_policy["max_terms_by_type"]
    if len(ordered_keys) > stage2_policy["max_terms_total"]:
        raise Stage2PlannerError("Stage-2 term count exceeds the policy total limit")

    focus_terms: list[dict[str, Any]] = []
    for term_type, term in ordered_keys:
        counts[term_type] += 1
        if counts[term_type] > max_by_type[term_type]:
            raise Stage2PlannerError(f"Stage-2 {term_type} term count exceeds its policy limit")
        refs = sorted(terms[(term_type, term)])
        focus_terms.append({"term": term, "term_type": term_type, "source_ref_ids": refs})

    query_template = stage2_policy["query_text_template"]
    stage2_queries = [
        {
            "query_id": f"stage2_{term_type}_{_term_digest(term_type, term)}",
            "query_text": query_template.format(term_type=term_type, term=term),
            "focus_term": term,
            "focus_term_type": term_type,
            "source_ref_ids": list(row["source_ref_ids"]),
        }
        for row in focus_terms
        for term_type, term in [(row["term_type"], row["term"])]
    ]
    return {"focus_terms": focus_terms, "stage2_queries": stage2_queries}


__all__ = ["POLICY_PATH", "Stage2PlannerError", "derive_stage2_plan_inputs"]
