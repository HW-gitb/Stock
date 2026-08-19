"""One-shot, diagnostic-only DeepSeek Stage-2 engineering smoke.

This runner is deliberately narrower than the formal Web CLI.  It accepts one tracked packet,
rebuilds the frozen source chunk through the production normalizer/chunker, reserves one private
Web Stage-2 budget, and then delegates the only paid call to ``PaidDispatchGateway``.  It never
builds or publishes a formal discovery artifact or receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
LIVE_ROOT = Path(r"D:\cnhea\Stock")
PACKET_ID = "us_short_web_regroup_engineering_smoke_20260815_chunk1_v3"
LEGACY_PACKET_ID = "us_short_web_regroup_engineering_smoke_20260815_chunk1_v2"
LEGACY_SCHEMA_NAME = "us_short_web_regroup_engineering_smoke_packet_v2"
LEGACY_SCHEMA_VERSION = "2.0.0"
EXPECTED_MODEL = "deepseek-v4-pro"
EXPECTED_SERVED_MODEL = "deepseek-v4-pro"
EXPECTED_TARGET_CHUNK_INDEX = 1
PACKET_PATH = ROOT / "docs" / "us_short_web_regroup_engineering_smoke_packet_20260815_v3.json"
SCHEMA_PATH = ROOT / "schemas" / "us_short_web_regroup_engineering_smoke_packet_v3.schema.json"
PRIVATE_ROOT = ROOT / "state" / "us_short" / "runs_private" / "soft_discovery_engineering_smoke_v3"
PARENT_PLAN_PATH = PRIVATE_ROOT / "us_short_web_regroup_engineering_smoke_20260815_chunk1_parent_plan.json"
RAW_ROOT = ROOT / "provider_samples" / "us_short_llm_theme_discovery_engineering_smoke_v3"
SUMMARY_PATH = PRIVATE_ROOT / "us_short_web_regroup_engineering_smoke_20260815_chunk1_summary.json"
EXPECTED_RENDERED_PROMPT_SHA256 = "97c7f93afc77310a193d585defc7b4afc596c87e27703c1ad9b053bcc3743a32"
EXPECTED_OUTPUT_BOUNDARY = {
    "diagnostic_root": "state/us_short/runs_private/soft_discovery_engineering_smoke_v3/",
    "parent_plan_ref": "state/us_short/runs_private/soft_discovery_engineering_smoke_v3/us_short_web_regroup_engineering_smoke_20260815_chunk1_parent_plan.json",
    "budget_ledger_ref": "state/us_short/runs_private/soft_discovery_engineering_smoke_v3/us_short_llm_theme_discovery_plan_web_20260815_budget.json",
    "raw_root": "provider_samples/us_short_llm_theme_discovery_engineering_smoke_v3/",
    "summary_ref": "state/us_short/runs_private/soft_discovery_engineering_smoke_v3/us_short_web_regroup_engineering_smoke_20260815_chunk1_summary.json",
}
LEGACY_OUTPUT_BOUNDARY = {
    "diagnostic_root": "state/us_short/runs_private/soft_discovery_engineering_smoke_v2/",
    "parent_plan_ref": "state/us_short/runs_private/soft_discovery_engineering_smoke_v2/us_short_web_regroup_engineering_smoke_20260815_chunk1_parent_plan.json",
    "budget_ledger_ref": "state/us_short/runs_private/soft_discovery_engineering_smoke_v2/us_short_llm_theme_discovery_plan_web_20260815_budget.json",
    "raw_root": "provider_samples/us_short_llm_theme_discovery_engineering_smoke_v2/",
    "summary_ref": "state/us_short/runs_private/soft_discovery_engineering_smoke_v2/us_short_web_regroup_engineering_smoke_20260815_chunk1_summary.json",
}

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_llm_theme_discovery_paid_gateway as paid_gateway  # noqa: E402
from engine import us_short_llm_theme_discovery_plan_budget as plan_budget  # noqa: E402
from engine import us_short_llm_theme_discovery_query_plan as query_plan  # noqa: E402
from engine import us_short_llm_theme_discovery_query_policy as query_policy  # noqa: E402
from engine.us_short_schema_formats import FORMAT_CHECKER  # noqa: E402
from runners import us_short_discovery_publish_policy as publish_policy  # noqa: E402
from runners import us_short_llm_theme_discovery_fetch_web as web  # noqa: E402


class EngineeringSmokeError(ValueError):
    """The one-shot diagnostic preflight or evidence chain cannot continue safely."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EngineeringSmokeError("required JSON artifact is unreadable") from exc


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise EngineeringSmokeError("required artifact digest cannot be read") from exc


def _assert_packet_contract(packet: Mapping[str, Any]) -> None:
    try:
        request = packet["paid_boundary"]["request"]
        call_counts = packet["paid_boundary"]["call_counts"]
        input_boundary = packet["input"]
        output_boundary = packet["output_boundary"]
    except (KeyError, TypeError) as exc:
        raise EngineeringSmokeError("engineering-smoke packet contract is malformed") from exc
    legacy_packet_path = LIVE_ROOT / "docs" / "us_short_web_regroup_engineering_smoke_packet_20260815_v2.json"
    is_legacy_test_packet = (
        packet.get("packet_id") == LEGACY_PACKET_ID
        and PACKET_PATH.resolve() != legacy_packet_path.resolve()
    )
    if packet.get("packet_id") == PACKET_ID:
        expected_schema_name = "us_short_web_regroup_engineering_smoke_packet_v3"
        expected_schema_version = "3.0.0"
        expected_packet_id = PACKET_ID
        expected_output_boundary = EXPECTED_OUTPUT_BOUNDARY
    elif is_legacy_test_packet:
        expected_schema_name = LEGACY_SCHEMA_NAME
        expected_schema_version = LEGACY_SCHEMA_VERSION
        expected_packet_id = LEGACY_PACKET_ID
        expected_output_boundary = LEGACY_OUTPUT_BOUNDARY
    else:
        raise EngineeringSmokeError("engineering-smoke packet identity is not runner-authorized")
    if (
        packet.get("schema_name") != expected_schema_name
        or packet.get("schema_version") != expected_schema_version
        or packet.get("packet_id") != expected_packet_id
        or packet.get("source_decision_date") != "20260815"
        or packet.get("formal_decision_date") is not None
        or packet.get("formal_decision_slots_occupied") is not False
        or packet.get("regrades_historical_decision") is not False
        or packet.get("provider_execution_authorized_by_packet_creation") is not False
    ):
        raise EngineeringSmokeError("engineering-smoke packet identity is not runner-authorized")
    if (
        input_boundary.get("target_chunk_index") != EXPECTED_TARGET_CHUNK_INDEX
        or input_boundary.get("target_source_count") != 10
        or input_boundary.get("rendered_prompt_sha256") != EXPECTED_RENDERED_PROMPT_SHA256
    ):
        raise EngineeringSmokeError("engineering-smoke packet target or prompt binding is not authorized")
    if (
        request.get("model") != EXPECTED_MODEL
        or request.get("expected_served_model") != EXPECTED_SERVED_MODEL
        or request.get("temperature") != 0
        or request.get("max_tokens") != paid_gateway.DEEPSEEK_REGROUP_MAX_TOKENS
        or request.get("response_format") != "json_object"
        or request.get("max_themes_per_chunk") != paid_gateway.DEEPSEEK_REGROUP_MAX_THEMES_PER_CHUNK
        or call_counts != {
            "tavily": 0, "deepseek": 1, "xai": 0, "retry": 0,
            "recovery": 0, "unknown_sibling": 0,
        }
    ):
        raise EngineeringSmokeError("engineering-smoke paid boundary is not runner-authorized")
    if (
        output_boundary.get("parent_plan_ref") != expected_output_boundary["parent_plan_ref"]
        or output_boundary.get("budget_ledger_ref") != expected_output_boundary["budget_ledger_ref"]
        or output_boundary.get("diagnostic_root") != expected_output_boundary["diagnostic_root"]
        or output_boundary.get("raw_root") != expected_output_boundary["raw_root"]
        or output_boundary.get("summary_ref") != expected_output_boundary["summary_ref"]
        or output_boundary.get("formal_outputs_forbidden") is not True
        or any(output_boundary.get("effects", {}).values())
    ):
        raise EngineeringSmokeError("engineering-smoke output boundary is not runner-authorized")
    expected_private_root = ROOT / expected_output_boundary["diagnostic_root"].rstrip("/")
    expected_parent_plan = ROOT / expected_output_boundary["parent_plan_ref"]
    expected_raw_root = ROOT / expected_output_boundary["raw_root"].rstrip("/")
    expected_summary = ROOT / expected_output_boundary["summary_ref"]
    if (
        PRIVATE_ROOT.resolve() != expected_private_root.resolve()
        or PARENT_PLAN_PATH.resolve() != expected_parent_plan.resolve()
        or RAW_ROOT.resolve() != expected_raw_root.resolve()
        or SUMMARY_PATH.resolve() != expected_summary.resolve()
    ):
        raise EngineeringSmokeError("engineering-smoke runtime output paths are not packet-authorized")


def _validate_packet(packet_path: Path = PACKET_PATH) -> dict[str, Any]:
    if Path(packet_path).resolve() != PACKET_PATH.resolve():
        raise EngineeringSmokeError("only the tracked engineering-smoke packet is accepted")
    packet = _read_json(PACKET_PATH)
    try:
        from jsonschema import Draft7Validator

        errors = sorted(
            Draft7Validator(_read_json(SCHEMA_PATH), format_checker=FORMAT_CHECKER).iter_errors(packet),
            key=lambda error: list(error.path),
        )
    except ImportError as exc:  # pragma: no cover - project dependency guard
        raise EngineeringSmokeError("jsonschema is required for the smoke packet") from exc
    if errors:
        raise EngineeringSmokeError("engineering-smoke packet is invalid")
    if packet["input"]["receipt_sha256"] != _sha256_file(
        ROOT / packet["input"]["receipt_ref"]
    ):
        raise EngineeringSmokeError("frozen Web receipt digest does not match the packet")
    _assert_packet_contract(packet)
    return packet


def _safe_repo_file(root: Path, relative_ref: str, *, prefix: str) -> Path:
    if (
        not isinstance(relative_ref, str)
        or not relative_ref.startswith(prefix)
        or any(part in {"", ".", ".."} for part in Path(relative_ref).parts)
    ):
        raise EngineeringSmokeError("frozen raw reference is outside the registered namespace")
    path = (root / relative_ref).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise EngineeringSmokeError("frozen raw reference escapes the repository") from exc
    if path.is_symlink() or not path.is_file():
        raise EngineeringSmokeError("a frozen Web raw receipt is missing")
    return path


def _frozen_target_rows(packet: Mapping[str, Any]) -> list[dict[str, str]]:
    """Read main-tree raw sources and let the production normalizer choose the chunk."""
    receipt_path = ROOT / packet["input"]["receipt_ref"]
    receipt = _read_json(receipt_path)
    if (
        type(receipt) is not dict
        or receipt.get("decision_clock", {}).get("expected_decision_date") != "20260815"
        or type(receipt.get("source_refs")) is not list
        or len(receipt["source_refs"]) != packet["input"]["accepted_source_count"]
    ):
        raise EngineeringSmokeError("frozen Web receipt source set is malformed")
    receipt_refs = receipt["source_refs"]
    rows: list[dict[str, Any]] = []
    for ref in receipt_refs:
        if type(ref) is not dict:
            raise EngineeringSmokeError("frozen Web receipt contains a malformed source ref")
        raw_path = _safe_repo_file(
            ROOT,
            ref.get("raw_receipt_ref"),
            prefix="provider_samples/us_short_llm_theme_discovery_fetch_web/raw/20260815/",
        )
        raw = _read_json(raw_path)
        if (
            type(raw) is not dict
            or raw.get("source_id") != ref.get("source_id")
            or raw.get("canonical_locator") != ref.get("canonical_locator")
            or not isinstance(raw.get("title"), str)
            or not isinstance(raw.get("content"), str)
            or not isinstance(raw.get("published_at"), str)
        ):
            raise EngineeringSmokeError("frozen Web raw receipt does not match its source ref")
        rows.append({
            "url": raw["canonical_locator"],
            "title": raw["title"],
            "content": raw["content"],
            "published_date": raw["published_at"],
        })
    fetched_at = max(
        web._parse_dt(ref["fetched_at"], field="source_ref.fetched_at")
        for ref in receipt_refs
    )
    normalized_refs, prompt_rows, drops = web._normalize_search_results(
        rows,
        expected_decision_date="20260815",
        fetched_at=fetched_at,
        raw_root=None,
        persist_raw=False,
    )
    if drops or len(normalized_refs) != 34 or len(prompt_rows) != 34:
        raise EngineeringSmokeError("production Web normalization did not conserve the 34 sources")
    recorded_digests: dict[str, str] = {}
    for ref, row in zip(receipt_refs, rows):
        single_refs, _single_rows, single_drops = web._normalize_search_results(
            [row],
            expected_decision_date="20260815",
            fetched_at=web._parse_dt(ref["fetched_at"], field="source_ref.fetched_at"),
            raw_root=None,
            persist_raw=False,
        )
        if single_drops or len(single_refs) != 1:
            raise EngineeringSmokeError("a frozen source cannot be reproduced through the production normalizer")
        recorded_digests[ref["source_id"]] = single_refs[0]["content_sha256"]
    if any(
        recorded_digests.get(ref["source_id"]) != ref.get("content_sha256")
        for ref in receipt_refs
    ):
        raise EngineeringSmokeError("frozen Web raw digests do not match the receipt")
    chunks = web._chunk_regroup_rows(prompt_rows)
    if [len(chunk) for chunk in chunks] != [10, 10, 10, 4]:
        raise EngineeringSmokeError("production Web chunking did not produce the frozen four chunks")
    all_ids = [row["source_id"] for chunk in chunks for row in chunk]
    if len(all_ids) != len(set(all_ids)) or set(all_ids) != {ref["source_id"] for ref in receipt_refs}:
        raise EngineeringSmokeError("production Web chunking did not conserve the receipt source set")
    target = chunks[packet["input"]["target_chunk_index"]]
    target_ids = [row["source_id"] for row in target]
    if target_ids != packet["input"]["target_source_ids"]:
        raise EngineeringSmokeError("frozen target chunk order does not match production derivation")
    packet_refs = packet["input"]["target_source_refs"]
    receipt_by_id = {ref["source_id"]: ref for ref in receipt_refs}
    for row, packet_ref in zip(target, packet_refs):
        receipt_ref = receipt_by_id.get(row["source_id"])
        if receipt_ref is None:
            raise EngineeringSmokeError("target chunk source is absent from the receipt")
        for key in (
            "source_id", "source_type", "canonical_locator", "observed_at", "fetched_at",
            "content_sha256", "raw_receipt_ref", "raw_receipt_gitignored",
        ):
            if packet_ref.get(key) != receipt_ref.get(key):
                raise EngineeringSmokeError("packet target source binding differs from the receipt")
        if recorded_digests.get(row["source_id"]) != packet_ref["content_sha256"]:
            raise EngineeringSmokeError("target source digest differs after production normalization")
    return [dict(row) for row in target]


def _build_diagnostic_parent_plan(packet: Mapping[str, Any]) -> dict[str, Any]:
    binding = packet["policy_binding"]
    policy = query_policy.load_query_policy_for_version(
        binding["policy_version"], root=ROOT,
    )
    if (
        policy["policy_content_sha256"] != binding["policy_content_sha256"]
        or query_policy.stage2_rule_sha256(policy) != binding["stage2_rule_sha256"]
    ):
        raise EngineeringSmokeError("reviewed policy binding does not match the packet")
    parent_plan = query_plan.build_parent_plan(
        decision_date=packet["source_decision_date"],
        policy_version=policy["policy_version"],
        policy_template_content_sha256=policy["policy_content_sha256"],
        stage1_queries=query_policy.render_stage1_queries(policy),
        stage2_rule_sha256=query_policy.stage2_rule_sha256(policy),
        provider_envelopes=[
            {
                "provider": "web",
                "stage1_max_dispatch_count": 0,
                "stage2_max_dispatch_count": 1,
                "retry_max_dispatch_count": 0,
                "max_dispatch_count": 1,
            },
            {
                "provider": "xai",
                "stage1_max_dispatch_count": 0,
                "stage2_max_dispatch_count": 0,
                "retry_max_dispatch_count": 0,
                "max_dispatch_count": 0,
            },
        ],
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    query_plan.validate_parent_plan_against_reviewed_policy(parent_plan)
    return parent_plan


def _private_gitignored(path: Path) -> bool:
    return publish_policy._gitignored(path, root=ROOT)


def _write_private_plan(parent_plan: dict[str, Any]) -> None:
    if not _private_gitignored(PARENT_PLAN_PATH):
        raise EngineeringSmokeError("diagnostic parent plan path must be gitignored")
    try:
        publish_policy.write_immutable_json(
            parent_plan, PARENT_PLAN_PATH, clock_keys=(), recursive=True,
        )
    except publish_policy.DiscoveryPublishPolicyError as exc:
        raise EngineeringSmokeError("diagnostic parent plan could not be written") from exc


def _assert_one_shot_roots_empty() -> None:
    for root in (PRIVATE_ROOT, RAW_ROOT):
        if root.exists() and any(root.rglob("*")):
            raise EngineeringSmokeError("this packet already has diagnostic evidence; replay is forbidden")


def _validate_rendered_prompt(packet: Mapping[str, Any], rows: list[dict[str, str]]) -> str:
    prompt = web._build_deepseek_prompt(packet["source_decision_date"], rows)
    rendered_sha256 = web._sha256_bytes(prompt.encode("utf-8"))
    if rendered_sha256 != packet["input"]["rendered_prompt_sha256"]:
        raise EngineeringSmokeError("rendered DeepSeek prompt digest does not match the packet")
    return prompt


def _read_budget_ledger(
    packet: Mapping[str, Any], budget: Any,
) -> tuple[Path, dict[str, Any]]:
    state_dir = getattr(budget, "state_dir", None)
    if state_dir is None:
        raise EngineeringSmokeError("diagnostic budget has no private state directory")
    path = plan_budget.default_plan_budget_path(
        "web", packet["source_decision_date"], state_dir=Path(state_dir),
    )
    try:
        ledger_ref = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise EngineeringSmokeError("diagnostic budget ledger escaped the private root") from exc
    if ledger_ref != packet["output_boundary"]["budget_ledger_ref"]:
        raise EngineeringSmokeError("diagnostic budget ledger path differs from the packet")
    ledger = _read_json(path)
    if type(ledger) is not dict:
        raise EngineeringSmokeError("diagnostic budget ledger is not an object")
    return path, ledger


def _ledger_metrics(ledger: Mapping[str, Any]) -> dict[str, int]:
    counts = ledger.get("dispatch_counts")
    vendors = ledger.get("vendor_dispatch_counts")
    recovery_events = ledger.get("recovery_events")
    if (
        type(counts) is not dict
        or type(vendors) is not dict
        or type(recovery_events) is not list
    ):
        raise EngineeringSmokeError("diagnostic budget ledger counts are missing")
    fields = {
        "reservation_count": ledger.get("reservation_attempt_count"),
        "query_reservation_count": len(ledger.get("query_reservations", [])),
        "provider_call_count": counts.get("dispatch_count"),
        "deepseek_call_count": vendors.get("deepseek"),
        "tavily_call_count": vendors.get("tavily"),
        "xai_call_count": vendors.get("xai"),
        "retry_count": counts.get("retry_dispatch_count"),
        "recovery_count": len(recovery_events),
        "unknown_sibling_count": counts.get("unknown_dispatch_count"),
    }
    if any(type(value) is not int or value < 0 for value in fields.values()):
        raise EngineeringSmokeError("diagnostic budget ledger counts are invalid")
    return fields


def _failure_reason(exc: BaseException | None) -> tuple[str | None, str | None]:
    if exc is None:
        return None, None
    reason = getattr(exc, "reason", None)
    detail = getattr(exc, "detail", None)
    reason_map = {
        "regroup_model_identity_changed": "served_model_mismatch",
        "regroup_model_identity_missing": "served_model_missing",
        "regroup_response_truncated": "finish_reason_not_stop",
        "regroup_theme_count_exceeded": "max_themes_exceeded",
        "regroup_response_invalid": "response_shape_invalid",
    }
    if isinstance(reason, str):
        return reason_map.get(reason, reason), detail if isinstance(detail, str) else None
    if isinstance(exc, plan_budget.PostPaymentDispatchError):
        return "completion_ledger_error", None
    if isinstance(exc, paid_gateway.PaidProviderError):
        # The cause's class name is enough to route (APITimeoutError vs AuthenticationError vs ...)
        # and carries no message, URL or key, so a spent shot stops recording only "it failed".
        cause = exc.__cause__
        return "provider_call_failed", type(cause).__name__ if cause is not None else None
    message = str(exc)
    message_map = {
        "DeepSeek response is not JSON": "response_not_json",
        "DeepSeek response must be text": "response_content_missing",
        "DeepSeek response shape is unsafe": "response_shape_invalid",
    }
    return message_map.get(message, "diagnostic_failure"), None


def _post_check_status(
    parsed_themes: list[Any] | None, *, failure_reason: str | None,
) -> tuple[str, str]:
    if parsed_themes is None:
        status = "failed" if failure_reason == "max_themes_exceeded" else "not_evaluated"
        return status, "not_evaluated"
    status = (
        "passed"
        if len(parsed_themes) <= paid_gateway.DEEPSEEK_REGROUP_MAX_THEMES_PER_CHUNK
        else "failed"
    )
    semantic_status = (
        "passed"
        if all(
            isinstance(theme, dict)
            and isinstance(theme.get("semantic_assertions"), list)
            for theme in parsed_themes
        )
        else "failed"
    )
    return status, semantic_status


def _summary(
    packet: Mapping[str, Any], *, status: str, provider_ref: Mapping[str, Any] | None,
    parse_status: str, parse_error_type: str | None, parsed_theme_count: int | None,
    parsed_themes: list[Any] | None, raw_hash_reread: bool, budget: Any,
    terminal_error: BaseException | None = None,
    parse_error: BaseException | None = None,
) -> dict[str, Any]:
    ledger_path, ledger = _read_budget_ledger(packet, budget)
    metrics = _ledger_metrics(ledger)
    served_model = provider_ref.get("served_model") if provider_ref is not None else None
    usage = provider_ref.get("usage") if provider_ref is not None else None
    finish_reason = provider_ref.get("finish_reason") if provider_ref is not None else None
    model_identity_complete = web._model_identity_is_complete(
        packet["paid_boundary"]["request"]["model"], served_model,
    )
    model_identity_match = (
        model_identity_complete
        and served_model == packet["paid_boundary"]["request"]["expected_served_model"]
    )
    parse_reason, parse_detail = _failure_reason(parse_error)
    terminal_reason, terminal_detail = _failure_reason(terminal_error)
    failure_reason = parse_reason or terminal_reason
    theme_status, semantic_status = _post_check_status(
        parsed_themes, failure_reason=failure_reason,
    )
    expected_counts = packet["paid_boundary"]["call_counts"]
    counts_match = (
        metrics["tavily_call_count"] == expected_counts["tavily"]
        and metrics["deepseek_call_count"] == expected_counts["deepseek"]
        and metrics["xai_call_count"] == expected_counts["xai"]
        and metrics["retry_count"] == expected_counts["retry"]
        and metrics["recovery_count"] == expected_counts["recovery"]
        and metrics["unknown_sibling_count"] == expected_counts["unknown_sibling"]
    )
    raw_ref = provider_ref.get("raw_receipt_ref") if provider_ref is not None else None
    raw_sha = provider_ref.get("response_sha256") if provider_ref is not None else None
    raw_before_parse = provider_ref is not None
    passed = (
        status == "live_authorized_engineering_smoke_response_captured"
        and raw_before_parse
        and raw_hash_reread
        and model_identity_match
        and isinstance(usage, dict)
        and all(type(usage.get(key)) is int and usage[key] >= 0 for key in (
            "prompt_tokens", "completion_tokens", "total_tokens",
        ))
        and finish_reason == "stop"
        and parse_status == "passed"
        and theme_status == "passed"
        and counts_match
        and metrics["provider_call_count"] == 1
        and metrics["reservation_count"] == 1
        and terminal_error is None
    )
    return {
        "schema_name": "us_short_web_regroup_engineering_smoke_summary",
        "schema_version": "2.0.0",
        "status": status,
        "transport_verdict": "PASS" if passed else "FAIL",
        "packet_id": packet["packet_id"],
        "source_decision_date": packet["source_decision_date"],
        "original_chunk_index": packet["input"]["target_chunk_index"],
        "provider_call_count": metrics["provider_call_count"],
        "deepseek_call_count": metrics["deepseek_call_count"],
        "tavily_call_count": metrics["tavily_call_count"],
        "xai_call_count": metrics["xai_call_count"],
        "retry_count": metrics["retry_count"],
        "recovery_count": metrics["recovery_count"],
        "unknown_sibling_count": metrics["unknown_sibling_count"],
        "budget_reservation_count": metrics["reservation_count"],
        "budget_query_reservation_count": metrics["query_reservation_count"],
        "budget_ledger_ref": ledger_path.resolve().relative_to(ROOT.resolve()).as_posix(),
        "requested_model": packet["paid_boundary"]["request"]["model"],
        "expected_served_model": packet["paid_boundary"]["request"]["expected_served_model"],
        "served_model": served_model,
        "system_fingerprint": provider_ref.get("system_fingerprint") if provider_ref is not None else None,
        "max_tokens_requested": packet["paid_boundary"]["request"]["max_tokens"],
        "strict_json_requested": True,
        "response_format": packet["paid_boundary"]["request"]["response_format"],
        "usage": usage,
        "finish_reason": finish_reason,
        "raw_provider_response_ref": raw_ref,
        "raw_provider_response_sha256": raw_sha,
        "raw_persisted_before_parse": raw_before_parse,
        "raw_hash_reread": raw_hash_reread,
        "strict_parse_status": parse_status,
        "strict_parse_error_type": parse_error_type,
        "strict_parse_error_reason": parse_reason,
        "strict_parse_error_detail": parse_detail,
        "parsed_theme_count": parsed_theme_count,
        "theme_count_status": theme_status,
        "max_four_themes_status": theme_status,
        "semantic_fields_status": semantic_status,
        "model_identity_complete": model_identity_complete,
        "model_identity_match": model_identity_match,
        "formal_decision_slots_occupied": False,
        "discovery_published": False,
        "receipt_published": False,
        "merge_published": False,
        "validation_published": False,
        "boost_published": False,
        "score_effect": False,
        "replay_permitted": False,
        "terminal_error_type": type(terminal_error).__name__ if terminal_error is not None else None,
        "terminal_error_reason": terminal_reason,
        "terminal_error_detail": terminal_detail,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }


def _reread_raw_hash(provider_ref: Mapping[str, Any]) -> bool:
    raw_prefix = RAW_ROOT.resolve().relative_to(ROOT.resolve()).as_posix() + "/"
    raw_path = _safe_repo_file(
        ROOT,
        provider_ref["raw_receipt_ref"],
        prefix=raw_prefix,
    )
    payload = _read_json(raw_path)
    if type(payload) is not dict or type(payload.get("response")) is not dict:
        raise EngineeringSmokeError("persisted DeepSeek raw response is malformed")
    return web._sha256_bytes(web._canonical_json(payload["response"])) == provider_ref["response_sha256"]


def run_one_shot(
    packet: Mapping[str, Any] | None = None, *, confirm_user_authorization: str,
    packet_path: Path | None = None,
) -> dict[str, Any]:
    if packet_path is None:
        packet_path = PACKET_PATH
    validated_packet = _validate_packet(packet_path)
    if packet is not None and packet != validated_packet:
        raise EngineeringSmokeError("packet argument does not match the validated tracked packet")
    packet = validated_packet
    if confirm_user_authorization != packet["packet_id"]:
        raise EngineeringSmokeError("exact packet authorization is required")
    _assert_packet_contract(packet)
    if ROOT.resolve() != LIVE_ROOT.resolve():
        raise EngineeringSmokeError("paid smoke execution is allowed only from the fixed main tree")
    _assert_one_shot_roots_empty()
    rows = _frozen_target_rows(packet)
    _validate_rendered_prompt(packet, rows)
    parent_plan = _build_diagnostic_parent_plan(packet)
    api_key = web._require_single_deepseek_api_key(os.environ.get("DEEPSEEK_API_KEY", ""))
    _write_private_plan(parent_plan)
    budget = plan_budget.reserve_plan_budget(
        parent_plan,
        lane=plan_budget.PLAN_LANE,
        state_dir=PRIVATE_ROOT,
        root=ROOT,
        gitignored=_private_gitignored,
        expected_decision_date=packet["source_decision_date"],
        providers=("web",),
        require_reviewed_policy=True,
    )
    transport = paid_gateway.new_transport("deepseek")
    deepseek = paid_gateway.DeepSeekClient(api_key, live_transport=transport)
    provider_ref: dict[str, Any] | None = None

    def persist_response(request: Any, response: Any) -> None:
        nonlocal provider_ref
        provider_ref = web._persist_live_web_regroup_response(
            request,
            response,
            raw_root=RAW_ROOT,
            expected_decision_date=packet["source_decision_date"],
            fetched_at=datetime.now(timezone.utc),
        )

    gateway = paid_gateway.PaidDispatchGateway(budget, parent_plan=parent_plan)
    batch = gateway.dispatch_web_regroup_all(
        deepseek,
        expected_decision_date=packet["source_decision_date"],
        chunks=[(packet["input"]["target_chunk_index"], rows)],
        prompt_builder=web._build_deepseek_prompt,
        transport=transport,
        capture_response=lambda _request, response: response,
        persist_response=persist_response,
        consume_response=lambda request, response: web._consume_regroup_response(
            response,
            expected_served_model=packet["paid_boundary"]["request"]["expected_served_model"],
            chunk_index=int(request.scope.split(":", 1)[1]),
        ),
    )
    if len(batch.items) != 1:
        raise EngineeringSmokeError("one-shot gateway returned an unexpected item count")
    item = batch.items[0]
    if provider_ref is None and item.outcome.call_error is None:
        raise EngineeringSmokeError("DeepSeek response was not persisted before parsing")
    if provider_ref is None:
        summary = _summary(
            packet,
            status="live_authorized_engineering_smoke_call_failed",
            provider_ref=None,
            parse_status="not_run",
            parse_error_type=None,
            parsed_theme_count=None,
            parsed_themes=None,
            raw_hash_reread=False,
            budget=budget,
            terminal_error=item.outcome.call_error,
        )
        web.publish_engineering_smoke_diagnostic(summary)
        return summary
    raw_hash_reread = _reread_raw_hash(provider_ref)
    parse_status = "passed"
    parse_error_type = None
    parse_error = None
    parsed_theme_count: int | None = None
    parsed_themes: list[Any] | None = None
    if item.item_error is not None:
        parse_status = "failed"
        parse_error_type = type(item.item_error).__name__
        parse_error = item.item_error
    elif isinstance(item.value, tuple) and len(item.value) == 3:
        parsed_themes = item.value[2] if isinstance(item.value[2], list) else None
        parsed_theme_count = len(parsed_themes) if parsed_themes is not None else None
    else:
        parse_status = "failed"
        parse_error_type = "unexpected_parser_value"
        parse_error = EngineeringSmokeError("unexpected parser value")
    summary = _summary(
        packet,
        status="live_authorized_engineering_smoke_response_captured",
        provider_ref=provider_ref,
        parse_status=parse_status,
        parse_error_type=parse_error_type,
        parsed_theme_count=parsed_theme_count,
        parsed_themes=parsed_themes,
        raw_hash_reread=raw_hash_reread,
        budget=budget,
        terminal_error=batch.stop_error,
        parse_error=parse_error,
    )
    web.publish_engineering_smoke_diagnostic(summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the one-shot US-short DeepSeek regroup smoke.")
    parser.add_argument("--packet", type=Path, default=PACKET_PATH)
    parser.add_argument("--confirm-user-authorization", required=True)
    args = parser.parse_args(argv)
    try:
        summary = run_one_shot(
            confirm_user_authorization=args.confirm_user_authorization,
            packet_path=args.packet,
        )
    except EngineeringSmokeError as exc:
        print(json.dumps({"status": "STOP", "reason": str(exc)}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "STOP", "reason": type(exc).__name__}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["transport_verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
