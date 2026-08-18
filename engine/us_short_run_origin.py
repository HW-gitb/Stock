# -*- coding: utf-8 -*-
"""US-short weekend-pipeline execution / data-origin fact — batch4 honesty provenance (single source).

Design authority: docs/us_short_system_design.md §11 (诚实) / §18.0 / §18.2 batch4. Closes
R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP: a batch4 weekend run carries an IMMUTABLE run-origin
fact — either `offline_test` (a caller-supplied fixture), `research_live` (fully provider-derived, pre-authoritative
research), or `mixed_source` (real provider facts plus a receipt-bound caller action template). Operational `live` stays
hard-gated upstream in the orchestrator. The official artifacts carry this fact so neither a synthetic fixture
nor a pre-authoritative research run can be mistaken for an operational, ship-gate-authoritative weekly artifact.

This module is the ONE immutable source of those facts + their validator + the always-visible disclosure text the
report renders and the private-write boundary reconciles. Provider-backed modes are CAPSTONE-INTERNAL and require the
run-specific source/provider execution receipt below (R-USSHORT-REVIEWQ-CAT1 Required A); no operational/ship-gate claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path

from engine.us_short_provider_health import (
    CRITICAL_SOURCES, REQUIRED_HEALTH_KEYS, RUN_STATES, parse_provider_health_detail_line,
    provider_health_non_clean_line,
)

# the immutable batch4 execution / data-origin fact. run_mode=offline_test (live gated → batch5);
# data_origin=caller_supplied_fixture (no provider call produced any market/provider fact);
# operational_use=not_authorized (the artifacts are NOT actionable weekly advice).
OFFLINE_TEST_RUN_ORIGIN = {
    "run_mode": "offline_test",
    "data_origin": "caller_supplied_fixture",
    "operational_use": "not_authorized",
}
_REQUIRED_KEYS = frozenset(OFFLINE_TEST_RUN_ORIGIN)

# the SECOND immutable batch4 honesty fact (2026-07-09, option a): a RESEARCH run over REAL provider data on a
# still-pre-authoritative calendar. data_origin=real_provider_pre_authoritative (真实 provider 调用，但日历/源未经
# 批5 SR-PROVIDER-001 权威核对); operational_use=not_authorized (仍非可执行运营建议). This lets the capstone emit an
# HONEST real-data research report WITHOUT the offline_test "fixture/unreal" lie AND without claiming operational
# authority (live stays hard-gated in the orchestrator → batch5). See project_us_short_live_mode_authoritative_upgrade.
RESEARCH_LIVE_RUN_ORIGIN = {
    "run_mode": "research_live",
    "data_origin": "real_provider_pre_authoritative",
    "operational_use": "not_authorized",
}

# A real provider fetch may still require caller-supplied Batch4 action inputs (market trend/breadth,
# prior regime, sizing, basket and cost).  That is neither a pure fixture nor a wholly provider-derived
# research report.  It must be disclosed as mixed source and receives the same capstone receipt gate as
# research_live, with the exact action-template identity bound into that receipt.
MIXED_SOURCE_RUN_ORIGIN = {
    "run_mode": "mixed_source",
    "data_origin": "real_provider_plus_caller_template",
    "operational_use": "not_authorized",
}
_VALID_RUN_ORIGINS = (OFFLINE_TEST_RUN_ORIGIN, RESEARCH_LIVE_RUN_ORIGIN, MIXED_SOURCE_RUN_ORIGIN)
_RECEIPT_REQUIRED_RUN_MODES = frozenset({"research_live", "mixed_source"})

# R-USSHORT-REVIEWQ-CAT1 Required A — provider-backed modes are CAPSTONE-INTERNAL run_origins, NOT public run_modes a generic
# Batch4/E2E caller can select. The batch4 / e2e entry points AND the run_weekend_pipeline orchestrator (the deepest
# PUBLISHED surface that mints the fact) gate research_live on a frozen receipt bound to the exact run, source digest,
# completed stage set, and provider-call evidence. The one-click capstone issues it after the gated live fetch.
# A GENERIC caller — the CLI (research_live is not an argparse
# choice) or a direct public-function caller — cannot select either mode: passing True / a look-alike object fails
# The receipt can honestly aggregate source-bound executed/reused stages across explicit checkpoint bundles;
# it never rewrites a stage clock to pretend that every stage ran in one process. In-process Python cannot be
# cryptographically sandboxed; deliberately calling the private
# receipt issuer remains outside the generic-caller threat model.
_RECEIPT_ISSUER = object()
_RECEIPT_SIGNING_KEY = os.urandom(32)
_REQUIRED_PRE_BRIDGE_STAGES = (
    "universe_fetch", "momentum_fetch", "overextension_producer", "momentum_producer", "sic_fetch", "theme_producer",
    "projection_inputs", "pass2_preflight", "yfinance_grades_fetch", "pass2_fetch", "vix_regime",
)
_REQUIRED_PROVIDER_STAGES = ("universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch")
_REQUIRED_PROVIDER_SUMMARY_STAGES = (*_REQUIRED_PROVIDER_STAGES, "yfinance_grades_fetch", "vix_regime")
_REQUIRED_PROVIDER_HEALTH_KEYS = REQUIRED_HEALTH_KEYS
_RECEIPT_V2_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "us_short_weekly_capstone_receipt_v2.schema.json"


@dataclass(frozen=True)
class _CapstoneResearchLiveReceipt:
    """Source-bound execution receipt carried through every research-live consumer boundary."""

    run_id: str
    decision_date: str
    generated_at: str
    completed_stages: tuple[str, ...]
    stage_executions: tuple[tuple[str, str, str, str | None, str], ...]
    source_packet_path: str
    source_packet_sha256: str
    source_artifact_manifest: tuple[tuple[str, str, str], ...]
    action_input_manifest: tuple[tuple[str, str, str], ...]
    provider_call_counts: tuple[tuple[str, int], ...]
    provider_summary_digests: tuple[tuple[str, str], ...]
    provider_health_facts: tuple[tuple[str, str], ...]
    provider_evidence_sha256: str
    _signature: str = field(repr=False, compare=False)
    _issuer: object = field(repr=False, compare=False)


def _is_sha256(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _valid_source_manifest(value) -> bool:
    if not isinstance(value, tuple) or not value:
        return False
    try:
        fields = [field for field, _, _ in value]
        return len(set(fields)) == len(fields) and all(
            isinstance(field, str) and bool(field) and Path(path).is_absolute() and _is_sha256(digest)
            for field, path, digest in value
        )
    except (TypeError, ValueError):
        return False


def _valid_action_input_manifest(value) -> bool:
    """A mixed-source run has one complete Batch4 action template, bound by identity and digest."""
    if value == ():
        return True
    try:
        return (
            isinstance(value, tuple)
            and tuple(role for role, _, _ in value) == ("batch4_action_template",)
            and all(Path(path).is_absolute() and _is_sha256(digest) for _, path, digest in value)
        )
    except (TypeError, ValueError):
        return False


def _valid_provider_summary_digests(value) -> bool:
    if not isinstance(value, tuple):
        return False
    try:
        return tuple(stage for stage, _ in value) == _REQUIRED_PROVIDER_SUMMARY_STAGES \
            and all(_is_sha256(digest) for _, digest in value)
    except (TypeError, ValueError):
        return False


def _valid_provider_calls(value) -> bool:
    if not isinstance(value, tuple):
        return False
    try:
        return (
            tuple(stage for stage, _ in value) == _REQUIRED_PROVIDER_STAGES
            and all(
                type(count) is int and count >= (0 if stage == "sic_fetch" else 1)
                for stage, count in value
            )
        )
    except (TypeError, ValueError):
        return False


def _valid_provider_health_facts(value) -> bool:
    if not isinstance(value, tuple):
        return False
    try:
        return tuple(key for key, _ in value) == _REQUIRED_PROVIDER_HEALTH_KEYS \
            and all(state in {"ok", "degraded", "down", "missing"} for _, state in value)
    except (TypeError, ValueError):
        return False


def _valid_stage_executions(value) -> bool:
    try:
        return (
            isinstance(value, tuple)
            and tuple(row[0] for row in value) == _REQUIRED_PRE_BRIDGE_STAGES
            and all(
                isinstance(row, tuple) and len(row) == 5
                and row[1] in {"executed", "reused", "refreshed_equivalent"}
                and isinstance(row[2], str) and bool(row[2])
                and (row[3] is None or isinstance(row[3], str) and bool(row[3]))
                and _is_sha256(row[4])
                for row in value
            )
        )
    except (TypeError, ValueError, IndexError):
        return False


def _validate_receipt_v2_payload(payload: dict) -> None:
    try:
        from jsonschema import Draft7Validator
        schema = json.loads(_RECEIPT_V2_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (ImportError, OSError, ValueError) as exc:
        raise RunOriginError("cannot load receipt v2 schema validator") from exc
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        raise RunOriginError("receipt v2 failed schema validation: " + "; ".join(e.message for e in errors[:5]))


def _receipt_signature_payload(
    *, run_id, decision_date, generated_at, completed_stages, stage_executions, source_packet_path, source_packet_sha256,
    source_artifact_manifest, action_input_manifest, provider_call_counts, provider_summary_digests, provider_health_facts,
    provider_evidence_sha256,
) -> bytes:
    return json.dumps(
        {
            "run_id": run_id,
            "decision_date": decision_date,
            "generated_at": generated_at,
            "completed_stages": list(completed_stages),
            "stage_executions": [list(row) for row in stage_executions],
            "source_packet_path": source_packet_path,
            "source_packet_sha256": source_packet_sha256,
            "source_artifact_manifest": [list(row) for row in source_artifact_manifest],
            "action_input_manifest": [list(row) for row in action_input_manifest],
            "provider_call_counts": [list(row) for row in provider_call_counts],
            "provider_summary_digests": [list(row) for row in provider_summary_digests],
            "provider_health_facts": [list(row) for row in provider_health_facts],
            "provider_evidence_sha256": provider_evidence_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _issue_capstone_research_live_receipt(
    *, run_id: str, decision_date: str, generated_at: str, completed_stages,
    source_packet_path, source_packet_sha256: str, source_artifact_manifest,
    provider_call_counts, provider_summary_digests, provider_health_facts, provider_evidence_sha256: str,
    action_input_manifest=(), stage_executions=None,
):
    """Issue an immutable receipt from a complete, source-bound capstone provider execution."""
    stages = tuple(completed_stages)
    calls = tuple((stage, count) for stage, count in provider_call_counts)
    source_manifest = tuple((field, path, digest) for field, path, digest in source_artifact_manifest)
    action_manifest = tuple((field, path, digest) for field, path, digest in action_input_manifest)
    summary_digests = tuple((stage, digest) for stage, digest in provider_summary_digests)
    health_facts = tuple((key, state) for key, state in provider_health_facts)
    if stage_executions is None:
        stage_executions = tuple(
            (stage, "executed", generated_at, generated_at, hashlib.sha256(
                f"{stage}|{generated_at}".encode("utf-8")
            ).hexdigest())
            for stage in stages
        )
    else:
        stage_executions = tuple(tuple(row) for row in stage_executions)
    if stages != _REQUIRED_PRE_BRIDGE_STAGES:
        raise RunOriginError("research_live receipt missing or reordering required pre-bridge stages")
    if tuple(stage for stage, _ in calls) != _REQUIRED_PROVIDER_STAGES:
        raise RunOriginError("research_live receipt provider-call evidence must cover the exact required stages")
    if any(type(count) is not int or count < 1 for _, count in calls):
        raise RunOriginError("research_live receipt requires positive provider-call evidence for every provider stage")
    if not _valid_source_manifest(source_manifest):
        raise RunOriginError("research_live receipt source-artifact manifest is malformed")
    if not _valid_action_input_manifest(action_manifest):
        raise RunOriginError("research_live receipt action-input manifest is malformed")
    if not _valid_provider_summary_digests(summary_digests):
        raise RunOriginError("research_live receipt requires exact provider-stage summary digests")
    if not _valid_provider_health_facts(health_facts):
        raise RunOriginError("research_live receipt requires exact provider-health facts")
    if not _valid_stage_executions(stage_executions):
        raise RunOriginError("research_live receipt requires exact per-stage execution provenance")
    if not (isinstance(run_id, str) and _is_sha256(run_id)):
        raise RunOriginError("research_live receipt run_id must be a sha256 identity")
    if not (isinstance(decision_date, str) and len(decision_date) == 8 and decision_date.isascii()
            and decision_date.isdigit()):
        raise RunOriginError("research_live receipt decision_date must be YYYYMMDD")
    if not (isinstance(generated_at, str) and generated_at):
        raise RunOriginError("research_live receipt generated_at is required")
    source_path = Path(source_packet_path)
    if not source_path.is_absolute():
        raise RunOriginError("research_live receipt source_packet_path must be absolute")
    if not _is_sha256(source_packet_sha256) or not _is_sha256(provider_evidence_sha256):
        raise RunOriginError("research_live receipt requires sha256 source and provider-evidence digests")
    resolved_source_path = str(source_path.resolve())
    receipt_payload = {
        "schema_name": "us_short_weekly_capstone_receipt",
        "schema_version": "2.0.0",
        "run_id": run_id,
        "decision_date": decision_date,
        "finalized_at": generated_at,
        "completed_stages": list(stages),
        "stage_executions": [
            {
                "name": name, "execution_mode": mode, "generated_at": stage_generated_at,
                "observed_at": observed_at, "result_sha256": result_sha256,
            }
            for name, mode, stage_generated_at, observed_at, result_sha256 in stage_executions
        ],
        "source_packet_path": resolved_source_path,
        "source_packet_sha256": source_packet_sha256,
        "source_artifact_manifest": [list(row) for row in source_manifest],
        "action_input_manifest": [list(row) for row in action_manifest],
        "provider_call_counts": [list(row) for row in calls],
        "provider_summary_digests": [list(row) for row in summary_digests],
        "provider_health_facts": [list(row) for row in health_facts],
        "provider_evidence_sha256": provider_evidence_sha256,
    }
    _validate_receipt_v2_payload(receipt_payload)
    signature = hmac.new(
        _RECEIPT_SIGNING_KEY,
        _receipt_signature_payload(
            run_id=run_id,
            decision_date=decision_date,
            generated_at=generated_at,
            completed_stages=stages,
            stage_executions=stage_executions,
            source_packet_path=resolved_source_path,
            source_packet_sha256=source_packet_sha256,
            source_artifact_manifest=source_manifest,
            action_input_manifest=action_manifest,
            provider_call_counts=calls,
            provider_summary_digests=summary_digests,
            provider_health_facts=health_facts,
            provider_evidence_sha256=provider_evidence_sha256,
        ),
        hashlib.sha256,
    ).hexdigest()
    return _CapstoneResearchLiveReceipt(
        run_id=run_id,
        decision_date=decision_date,
        generated_at=generated_at,
        completed_stages=stages,
        stage_executions=stage_executions,
        source_packet_path=resolved_source_path,
        source_packet_sha256=source_packet_sha256,
        source_artifact_manifest=source_manifest,
        action_input_manifest=action_manifest,
        provider_call_counts=calls,
        provider_summary_digests=summary_digests,
        provider_health_facts=health_facts,
        provider_evidence_sha256=provider_evidence_sha256,
        _signature=signature,
        _issuer=_RECEIPT_ISSUER,
    )


def is_capstone_research_live_capability(candidate) -> bool:
    """Return whether candidate is a complete receipt issued by this module, not a truthy caller flag."""
    structurally_valid = (
        isinstance(candidate, _CapstoneResearchLiveReceipt)
        and candidate._issuer is _RECEIPT_ISSUER
        and candidate.completed_stages == _REQUIRED_PRE_BRIDGE_STAGES
        and _valid_stage_executions(candidate.stage_executions)
        and _valid_provider_calls(candidate.provider_call_counts)
        and _is_sha256(candidate.run_id)
        and _is_sha256(candidate.source_packet_sha256)
        and _valid_source_manifest(candidate.source_artifact_manifest)
        and _valid_action_input_manifest(candidate.action_input_manifest)
        and _valid_provider_summary_digests(candidate.provider_summary_digests)
        and _valid_provider_health_facts(candidate.provider_health_facts)
        and _is_sha256(candidate.provider_evidence_sha256)
        and _is_sha256(candidate._signature)
    )
    if not structurally_valid:
        return False
    expected_signature = hmac.new(
        _RECEIPT_SIGNING_KEY,
        _receipt_signature_payload(
            run_id=candidate.run_id,
            decision_date=candidate.decision_date,
            generated_at=candidate.generated_at,
            completed_stages=candidate.completed_stages,
            stage_executions=candidate.stage_executions,
            source_packet_path=candidate.source_packet_path,
            source_packet_sha256=candidate.source_packet_sha256,
            source_artifact_manifest=candidate.source_artifact_manifest,
            action_input_manifest=candidate.action_input_manifest,
            provider_call_counts=candidate.provider_call_counts,
            provider_summary_digests=candidate.provider_summary_digests,
            provider_health_facts=candidate.provider_health_facts,
            provider_evidence_sha256=candidate.provider_evidence_sha256,
        ),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(candidate._signature, expected_signature)


def require_research_live_receipt_binding(
    capability, *, decision_date=None, generated_at=None, source_packet_path=None, source_packet_sha256=None,
    source_artifact_manifest=None, action_input_manifest=None,
):
    """Validate a receipt and any source/run identity known at the current boundary."""
    if not is_capstone_research_live_capability(capability):
        raise RunOriginError("research_live requires a valid source-bound capstone execution receipt")
    if decision_date is not None and capability.decision_date != decision_date:
        raise RunOriginError("research_live receipt decision_date does not match the consumed run")
    if generated_at is not None and capability.generated_at != generated_at:
        raise RunOriginError("research_live receipt generated_at does not match the consumed run")
    if source_packet_path is not None and capability.source_packet_path != str(Path(source_packet_path).resolve()):
        raise RunOriginError("research_live receipt source_packet_path does not match the consumed packet")
    if source_packet_sha256 is not None and capability.source_packet_sha256 != source_packet_sha256:
        raise RunOriginError("research_live receipt source packet digest mismatch")
    if source_artifact_manifest is not None and capability.source_artifact_manifest != tuple(source_artifact_manifest):
        raise RunOriginError("research_live receipt source artifact manifest mismatch")
    if action_input_manifest is not None and capability.action_input_manifest != tuple(action_input_manifest):
        raise RunOriginError("research_live receipt action-input manifest mismatch")
    return capability


def require_research_live_provider_summary(capability, stage: str, summary) -> None:
    """Bind a provider summary read at a later gate to the exact in-memory summary signed by the receipt."""
    require_research_live_receipt_binding(capability)
    expected = dict(capability.provider_summary_digests).get(stage)
    if expected is None:
        raise RunOriginError(f"research_live receipt does not bind provider stage {stage!r}")
    actual = hashlib.sha256(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise RunOriginError(f"research_live provider summary changed after receipt issuance: {stage}")


def require_research_live_provider_health(capability, provider_health) -> None:
    """Bind the provider-health file consumed by E2E to the facts derived when the receipt was issued."""
    require_research_live_receipt_binding(capability)
    expected = dict(capability.provider_health_facts)
    if not isinstance(provider_health, dict) or provider_health != expected:
        raise RunOriginError("research_live provider health does not match the receipt-bound provider outcome")


def require_research_live_provider_health_result(capability, provider_health_result) -> None:
    """Bind a classified provider-health result used by report/persistence consumers to the receipt facts."""
    from engine.us_short_provider_health import classify_provider_health

    require_research_live_receipt_binding(capability)
    expected = classify_provider_health(dict(capability.provider_health_facts))
    if provider_health_result != expected:
        raise RunOriginError("research_live classified provider health does not match the receipt-bound outcome")


def require_research_live_capability(run_origin, capability, *, decision_date=None):
    """CONSUMER-LAYER gate (R-USSHORT-REVIEWQ-CAT1 Required A, 4th surface): the run_origin fact is a dict of PUBLIC
    strings that `validate_run_origin` accepts by shape, so the four official-artifact producers
    (`assemble_machine_record` / `build_weekly_report` / `write_run_private` / `write_action_table`) could
    be driven DIRECTLY with a hand-built provider-backed origin, bypassing the entry-point gates. Every such producer
    calls this: turning a provider-backed fact into an official artifact requires the capstone receipt. A no-op for
    offline_test / any non-provider-backed origin (they need no capability). Raises RunOriginError otherwise."""
    if isinstance(run_origin, dict) and run_origin.get("run_mode") in _RECEIPT_REQUIRED_RUN_MODES:
        receipt = require_research_live_receipt_binding(capability, decision_date=decision_date)
        if run_origin["run_mode"] == "mixed_source" and not receipt.action_input_manifest:
            raise RunOriginError("mixed_source official artifacts require a receipt-bound action-input template")
        provider_health_facts = dict(receipt.provider_health_facts)
        if any(provider_health_facts.get(source) != "ok" for source in CRITICAL_SOURCES):
            raise RunOriginError(
    "provider-backed official artifacts require receipt-bound healthy critical providers"
            )

# the stable always-visible offline disclosure sentinel — rendered into the weekly report (§11.2) and
# reconciled at the §18.0 private-write boundary so an offline machine record can never be written beside a
# report that omits the disclosure (machine/report mode mismatch fails closed).
OFFLINE_DISCLOSURE_SENTINEL = "⚠ 离线工程运行（OFFLINE_TEST·调用方注入 fixture·非真实数据·不可执行）"
RESEARCH_DISCLOSURE_SENTINEL = "⚠ 研究运行（RESEARCH_LIVE·真实 provider 数据·非 ship-gate 权威·research-only·不可执行）"
MIXED_SOURCE_DISCLOSURE_SENTINEL = "⚠ 混合来源运行（MIXED_SOURCE·真实 provider 数据 + 调用方动作模板·不可执行）"

# the STRUCTURED offline report invariants the §18.0 private-write boundary enforces on report_data (NOT a
# markdown substring): §11 provider health must carry the offline disclaimer and must NOT restore the
# operationally-authoritative phrasing; §13 must NOT claim there is no unclean item. Single source so the
# report builder (which renders these) and the private-write consumer (which re-validates) cannot drift.
OFFLINE_PROVIDER_DISCLAIMER = "offline_test 不认定运营级权威 clean"   # §11 MUST contain this
PROVIDER_AUTHORITATIVE_CLEAN_MARK = "结构化、权威"                    # §11 MUST NOT contain this (operational-authority claim)
NO_UNCLEAN_CLAIM_MARK = "本周无不 clean 项"                          # §13 MUST NOT contain this
_HONESTY_KEYS = frozenset({
    "provider_health_state", "provider_operationally_authoritative",
    "operational_use_authorized", "coverage_non_full_count",
})
OFFLINE_LIMITATION_LINE = (
    "本周不 clean 项 ①: 离线工程运行（offline_test·调用方注入 fixture），所有 provider/市场事实非真实、"
    "不可作运营周报（operational_use=not_authorized）"
)
RESEARCH_PROVIDER_DISCLAIMER = "research_live 不认定运营级权威 clean"   # §11 MUST contain (research mode)
RESEARCH_LIMITATION_LINE = (
    "本周不 clean 项 ①: 研究运行（research_live·真实 provider 数据·预权威），"
    "未经 ship-gate 运营核准、不可作运营周报（operational_use=not_authorized）"
)
MIXED_SOURCE_PROVIDER_DISCLAIMER = "mixed_source 不认定运营级权威 clean"
MIXED_SOURCE_LIMITATION_LINE = (
    "本周不 clean 项 ①: 混合来源运行（mixed_source·真实 provider 数据 + 调用方动作模板），"
    "模板输入已收据绑定但非本轮 provider 来源，未经 ship-gate 运营核准、不可作运营周报（operational_use=not_authorized）"
)
# per-run_mode text so the SAME closed-world validators render/enforce every honesty track without duplicating the
# structure. The offline_test entries are byte-identical to the
# original inline strings (existing tests pin them).
_MODE_SENTINEL = {"offline_test": OFFLINE_DISCLOSURE_SENTINEL, "research_live": RESEARCH_DISCLOSURE_SENTINEL,
                  "mixed_source": MIXED_SOURCE_DISCLOSURE_SENTINEL}
_MODE_PROVIDER_DISCLAIMER = {"offline_test": OFFLINE_PROVIDER_DISCLAIMER, "research_live": RESEARCH_PROVIDER_DISCLAIMER,
                             "mixed_source": MIXED_SOURCE_PROVIDER_DISCLAIMER}
_MODE_LIMITATION_LINE = {"offline_test": OFFLINE_LIMITATION_LINE, "research_live": RESEARCH_LIMITATION_LINE,
                         "mixed_source": MIXED_SOURCE_LIMITATION_LINE}
_MODE_S11_TEMPLATE = {
    "offline_test": "数据源健康: provider_health=%s（离线 fixture 自报；%s，非真实 provider 调用）",
    "research_live": "数据源健康: provider_health=%s（真实 provider 调用；%s，research/预权威、未经 ship-gate 运营核准）",
    "mixed_source": "数据源健康: provider_health=%s（真实 provider 调用；%s，动作输入含 caller template）",
}
_MODE_DISCLOSURE_FACT = {
    "offline_test": ("本表所有市场/provider 事实均为调用方注入的 fixture（run_mode=%s, data_origin=%s, "
                     "operational_use=%s）；非真实数据、非真实 provider 调用，不构成可执行的周度选股/建议"),
    "research_live": ("本表所有市场/provider 事实来自真实 provider 调用（run_mode=%s, data_origin=%s, "
                      "operational_use=%s）；research/预权威、未经 ship-gate 运营核准，不构成可执行的周度选股/建议"),
    "mixed_source": ("本表 provider 事实来自真实 provider 调用，但市场/仓位/组合/成本动作输入含调用方模板（run_mode=%s, "
                     "data_origin=%s, operational_use=%s）；模板已收据绑定但并非本轮 provider 来源，不构成可执行的周度选股/建议"),
}

class RunOriginError(ValueError):
    """The execution/data-origin fact is missing or not one immutable permitted fact (fail-closed)."""


def build_offline_honesty(provider_health_state, coverage_non_full_count):
    """Build the typed, closed-world honesty facts from stage outputs."""
    if provider_health_state not in RUN_STATES:
        raise RunOriginError("provider_health_state 须来自 provider-health 冻结枚举")
    if (not isinstance(coverage_non_full_count, int) or isinstance(coverage_non_full_count, bool)
            or coverage_non_full_count < 0):
        raise RunOriginError("coverage_non_full_count 须为非负 int")
    return {
        "provider_health_state": provider_health_state,
        "provider_operationally_authoritative": False,
        "operational_use_authorized": False,
        "coverage_non_full_count": coverage_non_full_count,
    }


def canonical_offline_sections(honesty, origin):
    """Recompute the only permitted §11/§13 section bodies from typed honesty facts + the run_origin (the run_mode
    picks the matching disclosure text; the honesty booleans are identical — all modes remain
    NOT operationally authoritative, NOT authorized)."""
    mode = validate_run_origin(origin)["run_mode"]
    if not isinstance(honesty, dict) or set(honesty) != _HONESTY_KEYS:
        raise RunOriginError("offline_honesty 须为 closed-world typed object")
    expected = build_offline_honesty(
        honesty.get("provider_health_state"), honesty.get("coverage_non_full_count"))
    if honesty != expected:
        raise RunOriginError("offline_honesty 不得授权运营权威或运营使用")
    count = honesty["coverage_non_full_count"]
    s11 = [_MODE_S11_TEMPLATE[mode]
           % (honesty["provider_health_state"], _MODE_PROVIDER_DISCLAIMER[mode])]
    s13 = [_MODE_LIMITATION_LINE[mode]]
    if count:
        s13.append("② 本周 %d 行覆盖非 full（partial/restricted/blocked），明细见 §6 持仓覆盖诚实度节" % count)
    return s11, s13


# §1 is the SYSTEM-OWNED authoritative run-status section, part of the required provenance surface — it must be
# exactly the canonical offline disclosure lines + ONE validated run-status line (no extra/reordered prose can be
# slipped in after the sentinel). The dynamic counts/date are a closed-world typed object, recomputed independently
# at the consumer boundary so a “补充声明：…真实 provider…可直接执行” line cannot ride through byte equality.
_RUN_STATUS_KEYS = frozenset({
    "decision_date", "build_count", "observe_count", "holding_count",
    "candidate_count", "lifecycle_reminder_count",
})
_RUN_STATUS_COUNT_KEYS = ("build_count", "observe_count", "holding_count", "candidate_count", "lifecycle_reminder_count")


def _real_yyyymmdd(value):
    if not (isinstance(value, str) and len(value) == 8 and value.isascii() and value.isdigit()):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
        return True
    except ValueError:
        return False


def build_run_status(decision_date, build_count, observe_count, holding_count, candidate_count,
                     lifecycle_reminder_count):
    """Build the typed, closed-world §1 run-status facts from stage outputs (real YYYYMMDD + non-negative counts)."""
    if not _real_yyyymmdd(decision_date):
        raise RunOriginError("run_status.decision_date 须为真实 YYYYMMDD")
    status = {"decision_date": decision_date, "build_count": build_count, "observe_count": observe_count,
              "holding_count": holding_count, "candidate_count": candidate_count,
              "lifecycle_reminder_count": lifecycle_reminder_count}
    for k in _RUN_STATUS_COUNT_KEYS:
        v = status[k]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise RunOriginError(f"run_status.{k} 须为非负 int")
    return status


def canonical_section_1(origin, run_status):
    """Recompute the only permitted §1 body = the two offline disclosure lines + ONE run-status line, from the
    immutable run_origin + the typed run_status. Any extra/reordered §1 prose fails the consumer equality check."""
    if not isinstance(run_status, dict) or set(run_status) != _RUN_STATUS_KEYS:
        raise RunOriginError("run_status 须为 closed-world typed object")
    rs = build_run_status(run_status.get("decision_date"), run_status.get("build_count"),
                          run_status.get("observe_count"), run_status.get("holding_count"),
                          run_status.get("candidate_count"), run_status.get("lifecycle_reminder_count"))
    status_line = ("本周运行状态: decision_date=%s; 建仓 %d / 观察 %d / 持仓 %d / 候选 %d; lifecycle 提醒 %d 项"
                   % (rs["decision_date"], rs["build_count"], rs["observe_count"], rs["holding_count"],
                      rs["candidate_count"], rs["lifecycle_reminder_count"]))
    return offline_disclosure_lines(origin) + [status_line]


def assert_offline_report_invariants(report_data, origin):
    """Fail-closed STRUCTURED validation of a weekly report_data's offline provenance (the private-write
    consumer boundary, R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP round-1 FAIL): report_data must
    carry the matching run_origin, §1 must show the offline sentinel, §11 must carry the offline disclaimer and
    NOT the operational-authority phrasing, and §13 must NOT claim there is no unclean item — so a renderer-valid
    report that KEEPS the §1 sentinel but RESTORES a “provider 权威 clean” / “本周无不 clean” surface fails closed."""
    validate_run_origin(origin)
    if not isinstance(report_data, dict):
        raise RunOriginError("report_data 须为 dict")
    if report_data.get("run_origin") != origin:
        raise RunOriginError("report_data.run_origin 与本次 run_origin 不一致（offline 来源对账失败）")
    sections = report_data.get("sections")
    if not isinstance(sections, dict):
        raise RunOriginError("report_data.sections 须为 dict")
    # A section carrying BOTH its int and str key lets the validator (int-first getter) and the renderer (str-first
    # getter) read DIFFERENT bodies, so a forged body could ride the alternate key past the canonical §1/§11/§13
    # checks. Reject any int/str collision (a pre-existing latent gap hardened here in the honesty boundary; the wired
    # builder emits int-only keys, so this never fires on a real report — only a hand-crafted mixed-key one).
    for _k in [k for k in sections if isinstance(k, int)]:
        if str(_k) in sections:
            raise RunOriginError(
                f"§{_k} 同时携带 int 与 str 键（validator/renderer 键序不一致→读到不同体）；fail-closed")
    # §1 is system-owned: it must be EXACTLY the canonical disclosure lines + one typed run-status line, not merely
    # "contains the sentinel" — else an operational-authority line can be appended after the retained sentinel.
    expected_s1 = canonical_section_1(origin, report_data.get("run_status"))
    actual_s1 = sections.get(1, sections.get("1"))
    if actual_s1 != expected_s1:
        raise RunOriginError("§1 必须完全由 run_origin + typed run_status canonical 渲染（禁额外运营/权威声明行）")
    expected_s11, expected_s13 = canonical_offline_sections(report_data.get("offline_honesty"), origin)
    actual_s11 = sections.get(11, sections.get("11"))
    actual_s13 = sections.get(13, sections.get("13"))
    health_facts = parse_provider_health_detail_line(actual_s11[-1]) if isinstance(actual_s11, list) and actual_s11 else None
    if (not isinstance(actual_s11, list) or actual_s11[:len(expected_s11)] != expected_s11
            or len(actual_s11) != len(expected_s11) + 1 or health_facts is None):
        raise RunOriginError("§11 必须完全由 offline_honesty canonical 渲染（禁额外/同义权威声明）")
    expected_health_s13 = [
        provider_health_non_clean_line(key, health_facts[key])
        for key in REQUIRED_HEALTH_KEYS
        if health_facts[key] != "clean"
    ]
    if actual_s13 != [*expected_s13, *expected_health_s13]:
        raise RunOriginError("§13 必须完全由 offline_honesty canonical 渲染（禁同义运营 clean 声明）")
    return report_data


def validate_run_origin(origin):
    """Fail-closed: run_origin MUST equal one immutable permitted not-authorized fact (closed-world exact values)."""
    if not isinstance(origin, dict):
        raise RunOriginError("run_origin 须为 dict")
    if set(origin) != _REQUIRED_KEYS:
        raise RunOriginError(
            f"run_origin 顶层键须恰为 {sorted(_REQUIRED_KEYS)}（closed-world）: {sorted(origin)}")
    if origin not in _VALID_RUN_ORIGINS:
        raise RunOriginError(
            "run_origin 须为不可变 offline_test / research_live / mixed_source 事实 "
            f"{OFFLINE_TEST_RUN_ORIGIN} / {RESEARCH_LIVE_RUN_ORIGIN} / {MIXED_SOURCE_RUN_ORIGIN}"
            "（batch4·非运营权威·operational_use=not_authorized）")
    return origin


def run_origin_for_mode(run_mode):
    """The data-origin fact for a batch4 run. The official chain accepts offline_test, research_live, or mixed_source;
    operational live is hard-gated upstream. Provider-backed modes already passed the capstone receipt gate, so a
    generic caller cannot reach this with either provider-backed run_mode."""
    if run_mode == "offline_test":
        return dict(OFFLINE_TEST_RUN_ORIGIN)
    if run_mode == "research_live":
        return dict(RESEARCH_LIVE_RUN_ORIGIN)
    if run_mode == "mixed_source":
        return dict(MIXED_SOURCE_RUN_ORIGIN)
    raise RunOriginError(
        f"batch4 官方链只在 offline_test / research_live / mixed_source 产出 artifact（live 由 orchestrator 硬阻断）: run_mode={run_mode!r}")


def offline_disclosure_lines(origin):
    """The always-visible disclosure lines for the weekly report (§11.2), per permitted run_mode."""
    mode = validate_run_origin(origin)["run_mode"]
    return [
        _MODE_SENTINEL[mode],
        _MODE_DISCLOSURE_FACT[mode] % (
            origin["run_mode"], origin["data_origin"], origin["operational_use"]),
    ]
