"""Small, source-bound feasibility probe for three A-short effect chains.

This is intentionally not a generic data-flow analyzer.  It proves only that
three selected leaves have the expected local AST consumers and records the
source hashes used for that probe.  A missing step fails closed; the remaining
371-leaf inventory still requires the 12B classification and later repairs.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from jsonschema import validate


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "a_short_effect_consumer_probe.schema.json"
SCHEMA_NAME = "a_short_effect_consumer_probe"
SCHEMA_VERSION = "1.0.0"

_WEEKLY = "runners/a_short_weekly_pipeline.py"
_PHASE5 = "runners/a_short_phase5_engine.py"
_SHADOW = "engine/a_short_data_quality_shadow.py"


class ConsumerProbeError(ValueError):
    """Raised when a selected leaf-to-consumer proof is incomplete."""


_SPECS = (
    {
        "id": "crash_veto_to_negative_event",
        "leaf": "candidates[].derived_flags.has_crash_veto",
        "terminal_kind": "main_decision",
        "terminal_surface": "reports[].machine.risk_families.negative_event",
        "files": (_WEEKLY, _PHASE5),
    },
    {
        "id": "industry_trend_to_star",
        "leaf": "candidates[].industry.industry_trend",
        "terminal_kind": "main_decision",
        "terminal_surface": "reports[].machine.entry_exit_size_star.star",
        "files": (_WEEKLY, _PHASE5),
    },
    {
        "id": "data_quality_to_shadow_verdict",
        "leaf": "candidates[].data_quality.completeness_score",
        "terminal_kind": "comparison_verdict",
        "terminal_surface": "weekly.data_quality_shadow.verdict.observed_outcome",
        "files": (_WEEKLY, _SHADOW),
    },
)


def _hash_source(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _function(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    return next((node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name), None)


def _has_get(function: ast.AST, root: str, key: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == root
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == key
        for node in ast.walk(function)
    )


def _has_subscript(function: ast.AST, root: str, key: str) -> bool:
    return any(
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == root
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == key
        for node in ast.walk(function)
    )


def _has_call(function: ast.AST, name: str) -> bool:
    return any(isinstance(node, ast.Call)
               and isinstance(node.func, ast.Name)
               and node.func.id == name
               for node in ast.walk(function))


def _has_constant(function: ast.AST, value: str) -> bool:
    return any(isinstance(node, ast.Constant) and node.value == value
               for node in ast.walk(function))


def _check_crash_veto_weekly(tree: ast.AST) -> str | None:
    function = _function(tree, "normalize_candidate")
    if function is None:
        return None
    if not _has_get(function, "cand", "derived_flags"):
        return None
    if not _has_get(function, "d", "has_crash_veto"):
        return None
    return 'normalize_candidate reads cand.get("derived_flags") then d.get("has_crash_veto")'


def _check_crash_veto_phase5(tree: ast.AST) -> str | None:
    function = _function(tree, "classify_risk_families")
    if function is None or not _has_get(function, "d", "crash_veto"):
        return None
    if not _has_subscript(function, "fam", "negative_event"):
        return None
    return 'classify_risk_families reads d.get("crash_veto") into negative_event'


def _check_industry_weekly(tree: ast.AST) -> str | None:
    normalize = _function(tree, "normalize_candidate")
    if normalize is None or not _has_call(normalize, "_industry_trend_for_candidate"):
        return None
    trend = _function(tree, "_industry_trend_for_candidate")
    if trend is None or not _has_constant(trend, "industry_trend"):
        return None
    return "normalize_candidate calls _industry_trend_for_candidate and binds industry_trend"


def _check_industry_phase5(tree: ast.AST) -> str | None:
    function = _function(tree, "compute_star")
    if function is None or not _has_get(function, "inp", "industry_trend"):
        return None
    if not _has_constant(function, "headwind"):
        return None
    return 'compute_star consumes inp.get("industry_trend") and applies the headwind branch'


def _check_data_quality_weekly(tree: ast.AST) -> str | None:
    normalize = _function(tree, "normalize_candidate")
    build = _function(tree, "build_weekly_report")
    if normalize is None or build is None:
        return None
    if not _has_constant(normalize, "data_quality") or not _has_call(build, "build_data_quality_shadow"):
        return None
    return "normalize_candidate preserves data_quality and build_weekly_report creates the shadow"


def _check_data_quality_shadow(tree: ast.AST) -> str | None:
    function = _function(tree, "build_data_quality_shadow")
    if function is None or not _has_constant(function, "comparison_only"):
        return None
    if not _has_constant(function, "production_effect_enabled"):
        return None
    return "build_data_quality_shadow emits comparison_only=true and production_effect_enabled=false"


_CHECKS = {
    (_SPECS[0]["id"], _WEEKLY): _check_crash_veto_weekly,
    (_SPECS[0]["id"], _PHASE5): _check_crash_veto_phase5,
    (_SPECS[1]["id"], _WEEKLY): _check_industry_weekly,
    (_SPECS[1]["id"], _PHASE5): _check_industry_phase5,
    (_SPECS[2]["id"], _WEEKLY): _check_data_quality_weekly,
    (_SPECS[2]["id"], _SHADOW): _check_data_quality_shadow,
}


def _load_sources(source_overrides: dict[str, str] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    source_overrides = source_overrides or {}
    paths = sorted({path for spec in _SPECS for path in spec["files"]})
    sources = {path: source_overrides.get(path, (ROOT / path).read_text(encoding="utf-8")) for path in paths}
    trees = {path: ast.parse(source, filename=path) for path, source in sources.items()}
    return sources, trees


def validate_consumer_probe(payload: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validate(payload, schema)
    if payload.get("probe_status") != "feasible_probe_pass":
        raise ConsumerProbeError("consumer probe is not a feasible-probe pass")
    source_hashes = {row["path"]: row["sha256"] for row in payload["source_files"]}
    expected_ids = {spec["id"] for spec in _SPECS}
    actual_ids = {row["id"] for row in payload["probes"]}
    if actual_ids != expected_ids:
        raise ConsumerProbeError("consumer probe leaf set changed")
    for row in payload["probes"]:
        for source_ref in row["source_refs"]:
            if source_hashes.get(source_ref["path"]) != source_ref["sha256"]:
                raise ConsumerProbeError(f"consumer probe source binding mismatch: {source_ref['path']}")


def build_consumer_probe(source_overrides: dict[str, str] | None = None) -> dict:
    sources, trees = _load_sources(source_overrides)
    source_files = [{"path": path, "sha256": _hash_source(sources[path])} for path in sorted(sources)]
    probes = []
    for spec in _SPECS:
        source_refs = []
        evidence = []
        for path in spec["files"]:
            check = _CHECKS[(spec["id"], path)]
            result = check(trees[path])
            if result is None:
                raise ConsumerProbeError(f"consumer proof missing: {spec['id']}::{path}")
            source_refs.append({"path": path, "sha256": _hash_source(sources[path])})
            evidence.append(result)
        probes.append({
            "id": spec["id"],
            "leaf": spec["leaf"],
            "terminal_kind": spec["terminal_kind"],
            "terminal_surface": spec["terminal_surface"],
            "proof_status": "static_ast_presence",
            "consumer_refs": list(spec["files"]),
            "evidence": evidence,
            "source_refs": source_refs,
        })
    payload = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "probe_status": "feasible_probe_pass",
        "proof_scope": "three selected leaf-to-consumer chains only; not a generic data-flow proof",
        "production_effect_enabled": False,
        "source_files": source_files,
        "probes": probes,
    }
    validate_consumer_probe(payload)
    return payload
