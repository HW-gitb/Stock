"""Blade4 offline Serenity shadow consumers for US-short.

The consumer validates one Blade3 annotation and projects it into three
advisory-only surfaces: ``structural_constraint_cluster_shadow``,
``us_short_relevance_hint`` and ``us_long_research_candidate``.  The report
surface is a pure overlay on an already-rendered weekly report.  It inserts a
registered section-12 block and a line in the existing honest-banner section;
it never creates a free-text H2 and never opens or writes a report file.

Malformed or version-incompatible optional input is returned as a local
``invalid_annotation`` result.  The caller can keep the ordinary weekly task
running, while the failure remains visible in the trace.  No provider, network,
scoring, selection, seat, action, position, ``macro_cluster`` or ``us_long``
consumer is used here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engine import us_short_serenity_structural_theme_annotation as annotation_contract


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_shadow_consumption.schema.json"
CONSUMER_SCHEMA_NAME = "us_short_serenity_shadow_consumption"
CONSUMER_SCHEMA_VERSION = "1.0.0"
CONSUMER_VERSION = "serenity_shadow_consumer_v0.1.0"
REPORT_REGISTRY_KEY = "us_short_serenity_structural_annotation_shadow"
REPORT_SECTION_NUMBER = 12
REPORT_SECTION_HEADER_PREFIX = f"## {REPORT_SECTION_NUMBER}. "
REPORT_BANNER_HEADER = "## 诚实横幅"
EFFECT_BOUNDARY = {
    "scoring_eligible": False,
    "top15_effect_enabled": False,
    "operation_advice_effect_enabled": False,
}
_LONG_HORIZONS = frozenset({"3_to_12_months", "long_term"})


class SerenityShadowConsumerError(ValueError):
    """The optional Serenity shadow surface cannot be rendered safely."""


def _single_line(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SerenityShadowConsumerError(f"{label} must be a non-blank string")
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def _identity_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    identity = payload.get("identity_envelope")
    if not isinstance(identity, Mapping):
        raise SerenityShadowConsumerError("annotation identity_envelope is missing")
    return {
        "annotation_id": payload["annotation_id"],
        "schema_version": payload["schema_version"],
        "rubric_version": identity["rubric_version"],
        "upstream_decision_result_id": identity["upstream_decision_result_id"],
        "upstream_policy_version": identity["upstream_policy_version"],
        "upstream_decision_date": identity["upstream_decision_date"],
    }


def _surface_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the exact Blade3 identity into every advisory output surface."""
    return {key: identity[key] for key in (
        "annotation_id",
        "schema_version",
        "rubric_version",
        "upstream_decision_result_id",
        "upstream_policy_version",
        "upstream_decision_date",
    )}


def _source_ref_ids(canonical: Mapping[str, Any]) -> list[str]:
    refs: set[str] = set(canonical["horizon_basis_source_ref_ids"])
    for claim in canonical["claims"]:
        refs.update(claim["source_ref_ids"])
    for role in canonical["chain_role_by_ticker"].values():
        refs.update(role["source_ref_ids"])
    for falsifier in canonical["falsifiers"]:
        refs.update(falsifier["source_ref_ids"])
    return sorted(refs)


def _role_rows(canonical: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "ticker": ticker,
            "role": canonical["chain_role_by_ticker"][ticker]["role"],
            "source_ref_ids": list(canonical["chain_role_by_ticker"][ticker]["source_ref_ids"]),
        }
        for ticker in sorted(canonical["chain_role_by_ticker"])
    ]


def _report_block(canonical: Mapping[str, Any], identity: Mapping[str, Any]) -> dict[str, Any]:
    common_constraint_id = canonical["common_constraint_id"] or "none"
    horizon = canonical["horizon_alignment"]
    candidate_status = "candidate" if horizon in _LONG_HORIZONS else "not_candidate"
    banner_line = (
        f"- [{REPORT_REGISTRY_KEY}] structural_constraint_cluster_shadow: "
        f"common_constraint_id={_single_line(str(common_constraint_id), label='common_constraint_id')}; "
        "advisory-only；不改变选股/操作建议/仓位"
    )
    appendix = [
        "- " + "; ".join(
            f"{key}={value}" for key, value in _surface_identity(identity).items()
        ),
        (
            "- structural_constraint_cluster_shadow: "
            f"system_change_id={_single_line(canonical['system_change_id'], label='system_change_id')}; "
            f"scarce_layer={canonical['scarce_layer']}; "
            f"constraint_mechanism={canonical['constraint_mechanism']}; "
            f"source_ref_ids={','.join(_source_ref_ids(canonical))}"
        ),
        (
            "- us_short_relevance_hint: "
            f"horizon_alignment={horizon}; "
            f"near_term_observable={_single_line(canonical['near_term_observable'], label='near_term_observable')}; "
            "不删除/不降级/不迁移主题"
        ),
        (
            "- us_long_research_candidate: "
            f"status={candidate_status}; horizon_alignment={horizon}; "
            "research-only；不自动写 us_long"
        ),
    ]
    for role in _role_rows(canonical):
        appendix.append(
            "- chain_role_by_ticker: "
            f"ticker={role['ticker']}; role={role['role']}; "
            f"source_ref_ids={','.join(role['source_ref_ids'])}"
        )
    for falsifier in canonical["falsifiers"]:
        appendix.append(
            "- falsifier: "
            f"type={falsifier['type']}; status={falsifier['status']}; "
            f"observable_metric={_single_line(falsifier['observable_metric'], label='observable_metric')}; "
            f"expected_window={falsifier['expected_window']}; "
            f"statement={_single_line(falsifier['statement'], label='falsifier.statement')}; "
            f"source_ref_ids={','.join(falsifier['source_ref_ids'])}"
        )
    appendix.append(
        "- effect_boundary: scoring_eligible=false; top15_effect_enabled=false; "
        "operation_advice_effect_enabled=false; main_task_should_abort=false"
    )
    if not all(line.startswith("- ") and "\n" not in line and "\r" not in line for line in appendix):
        raise SerenityShadowConsumerError("registered advisory appendix contains an unsafe line")
    return {
        **_surface_identity(identity),
        "surface": "registered_report_block",
        "registry_key": REPORT_REGISTRY_KEY,
        "section_number": REPORT_SECTION_NUMBER,
        "free_text_h2": False,
        "banner_line": banner_line,
        "advisory_appendix_lines": appendix,
        "source_ref_ids": _source_ref_ids(canonical),
        "changes_selection_or_action": False,
        "opens_report_file": False,
    }


def _active_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    identity = _identity_projection(payload)
    canonical = payload["canonical_annotation"]
    role_rows = _role_rows(canonical)
    source_refs = _source_ref_ids(canonical)
    horizon = canonical["horizon_alignment"]
    short_hint = {
        **_surface_identity(identity),
        "surface": "us_short_relevance_hint",
        "status": "advisory",
        "horizon_alignment": horizon,
        "near_term_observable": _single_line(canonical["near_term_observable"], label="near_term_observable"),
        "horizon_basis_source_ref_ids": list(canonical["horizon_basis_source_ref_ids"]),
        "theme_removed": False,
        "theme_downgraded": False,
        "theme_migrated": False,
        "changes_selection_or_action": False,
    }
    long_candidate = {
        **_surface_identity(identity),
        "surface": "us_long_research_candidate",
        "status": "candidate" if horizon in _LONG_HORIZONS else "not_candidate",
        "horizon_alignment": horizon,
        "system_change_id": canonical["system_change_id"],
        "source_ref_ids": source_refs,
        "research_only": True,
        "automatic_write": False,
        "us_long_write_performed": False,
        "changes_selection_or_action": False,
    }
    cluster = {
        **_surface_identity(identity),
        "surface": "structural_constraint_cluster_shadow",
        "status": "advisory_only",
        "common_constraint_id": canonical["common_constraint_id"],
        "system_change_id": canonical["system_change_id"],
        "scarce_layer": canonical["scarce_layer"],
        "constraint_mechanism": canonical["constraint_mechanism"],
        "member_roles": role_rows,
        "source_ref_ids": source_refs,
        "changes_selection_or_action": False,
    }
    report_block = _report_block(canonical, identity)
    trace = {
        **_surface_identity(identity),
        "surface": "decision_trace",
        "consumer_version": CONSUMER_VERSION,
        "landed_surfaces": [
            "structural_constraint_cluster_shadow",
            "us_short_relevance_hint",
            "us_long_research_candidate",
        ],
        "report_registry_key": REPORT_REGISTRY_KEY,
        "report_section_number": REPORT_SECTION_NUMBER,
        "report_block_registered": True,
        "chain_role_ticker_count": len(role_rows),
        "falsifier_count": len(canonical["falsifiers"]),
        "upstream_disposition_consumed": False,
        "theme_removed": False,
        "theme_downgraded": False,
        "theme_migrated": False,
        "action_confidence_changed": False,
        "seat_changed": False,
        "position_size_changed": False,
        "us_long_write_performed": False,
        "main_task_should_abort": False,
    }
    result = {
        "schema_name": CONSUMER_SCHEMA_NAME,
        "schema_version": CONSUMER_SCHEMA_VERSION,
        "consumer_version": CONSUMER_VERSION,
        "status": "active",
        "advisory_only": True,
        "main_task_should_abort": False,
        "annotation_identity": identity,
        "structural_constraint_cluster_shadow": cluster,
        "us_short_relevance_hint": short_hint,
        "us_long_research_candidate": long_candidate,
        "registered_report_block": report_block,
        "decision_trace": trace,
        "effect_boundary": dict(EFFECT_BOUNDARY),
        "error": None,
    }
    return result


def _inactive_payload(status: str, *, error: dict[str, str] | None = None) -> dict[str, Any]:
    trace = {
        "annotation_id": None,
        "schema_version": None,
        "rubric_version": None,
        "upstream_decision_result_id": None,
        "upstream_policy_version": None,
        "upstream_decision_date": None,
        "surface": "decision_trace",
        "consumer_version": CONSUMER_VERSION,
        "landed_surfaces": [],
        "report_registry_key": REPORT_REGISTRY_KEY,
        "report_section_number": REPORT_SECTION_NUMBER,
        "report_block_registered": False,
        "chain_role_ticker_count": 0,
        "falsifier_count": 0,
        "upstream_disposition_consumed": False,
        "theme_removed": False,
        "theme_downgraded": False,
        "theme_migrated": False,
        "action_confidence_changed": False,
        "seat_changed": False,
        "position_size_changed": False,
        "us_long_write_performed": False,
        "main_task_should_abort": False,
    }
    return {
        "schema_name": CONSUMER_SCHEMA_NAME,
        "schema_version": CONSUMER_SCHEMA_VERSION,
        "consumer_version": CONSUMER_VERSION,
        "status": status,
        "advisory_only": True,
        "main_task_should_abort": False,
        "annotation_identity": None,
        "structural_constraint_cluster_shadow": None,
        "us_short_relevance_hint": None,
        "us_long_research_candidate": None,
        "registered_report_block": None,
        "decision_trace": trace,
        "effect_boundary": dict(EFFECT_BOUNDARY),
        "error": error,
    }


def _validate_shadow_payload(payload: Mapping[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.absolute_path))
    except (ImportError, OSError, UnicodeDecodeError, ValueError) as exc:
        raise SerenityShadowConsumerError("shadow consumer schema is unavailable") from exc
    if errors:
        raise SerenityShadowConsumerError(f"shadow consumer schema rejected: {errors[0].message}")


def consume_serenity_annotation(
    payload: Mapping[str, Any] | None,
    *,
    root: Path = ROOT,
    now=None,
) -> dict[str, Any]:
    """Consume one optional Blade3 annotation without giving it behavioral authority.

    ``None`` is the dormant week and returns without asking the annotation
    validator to read anything.  A malformed or incompatible annotation is
    represented as ``invalid_annotation`` and never raises into the main task.
    """
    if payload is None:
        result = _inactive_payload("sleeping")
        _validate_shadow_payload(result)
        return result
    try:
        annotation_contract.validate_annotation(payload, root=Path(root), now=now)
        if payload.get("schema_version") != annotation_contract.SCHEMA_VERSION:
            raise annotation_contract.StructuralAnnotationError("annotation schema version is not declared")
        result = _active_payload(payload)
        if payload.get("effect_boundary") != EFFECT_BOUNDARY:
            raise annotation_contract.StructuralAnnotationError("annotation effect boundary is not disabled")
    except (annotation_contract.StructuralAnnotationError, KeyError, TypeError, ValueError) as exc:
        result = _inactive_payload(
            "invalid_annotation",
            error={
                "code": "SERENITY_ANNOTATION_REJECTED",
                "message": " ".join(str(exc).replace("\r", " ").replace("\n", " ").split())[:300],
            },
        )
    _validate_shadow_payload(result)
    return result


def _insert_before_section_end(body: list[str], start: int, lines: list[str]) -> None:
    end = next((index for index in range(start + 1, len(body)) if body[index].startswith("## ")), len(body))
    while end > start + 1 and not body[end - 1].strip():
        end -= 1
    body[end:end] = lines


def render_registered_report_overlay(report_text: str, shadow: Mapping[str, Any]) -> str:
    """Insert the active shadow into existing registered report sections.

    This is intentionally pure: it receives and returns Markdown text.  It
    does not open a report path, create a file, or invent an H2.  The existing
    ``## 诚实横幅`` and registered ``## 12. ...`` sections must each occur once.
    """
    if not isinstance(report_text, str):
        raise SerenityShadowConsumerError("report_text must be a string")
    if shadow.get("status") != "active":
        return report_text
    _validate_shadow_payload(shadow)
    block = shadow["registered_report_block"]
    body = report_text.splitlines()
    banner_headers = [index for index, line in enumerate(body) if line == REPORT_BANNER_HEADER]
    section_headers = [index for index, line in enumerate(body) if line.startswith(REPORT_SECTION_HEADER_PREFIX)]
    if len(banner_headers) != 1:
        raise SerenityShadowConsumerError("weekly report has no unique registered honest-banner section")
    if len(section_headers) != 1:
        raise SerenityShadowConsumerError("weekly report has no unique registered Serenity section")
    marker = f"- [{REPORT_REGISTRY_KEY}]"
    if any(line.startswith(marker) for line in body):
        raise SerenityShadowConsumerError("registered Serenity block is already present")
    _insert_before_section_end(body, banner_headers[0], [block["banner_line"]])
    section_headers = [index for index, line in enumerate(body) if line.startswith(REPORT_SECTION_HEADER_PREFIX)]
    _insert_before_section_end(body, section_headers[0], list(block["advisory_appendix_lines"]))
    inserted = [block["banner_line"], *block["advisory_appendix_lines"]]
    if any(line.lstrip().startswith("## ") for line in inserted):
        raise SerenityShadowConsumerError("registered Serenity overlay attempted to create a free-text H2")
    return "\n".join(body) + ("\n" if report_text.endswith("\n") else "")


def deliver_serenity_shadow_to_report(report_text: str, shadow: Mapping[str, Any]) -> dict[str, Any]:
    """Best-effort optional report delivery; a malformed overlay never aborts the week."""
    if shadow.get("status") != "active":
        return {
            "report_text": report_text,
            "report_block_delivered": False,
            "report_block_problem": shadow.get("error"),
            "main_task_should_abort": False,
        }
    try:
        rendered = render_registered_report_overlay(report_text, shadow)
    except SerenityShadowConsumerError as exc:
        return {
            "report_text": report_text,
            "report_block_delivered": False,
            "report_block_problem": f"{type(exc).__name__}: {exc}",
            "main_task_should_abort": False,
        }
    return {
        "report_text": rendered,
        "report_block_delivered": True,
        "report_block_problem": None,
        "main_task_should_abort": False,
    }


__all__ = [
    "CONSUMER_SCHEMA_NAME",
    "CONSUMER_SCHEMA_VERSION",
    "CONSUMER_VERSION",
    "EFFECT_BOUNDARY",
    "REPORT_REGISTRY_KEY",
    "REPORT_SECTION_NUMBER",
    "SCHEMA_PATH",
    "SerenityShadowConsumerError",
    "consume_serenity_annotation",
    "deliver_serenity_shadow_to_report",
    "render_registered_report_overlay",
]
