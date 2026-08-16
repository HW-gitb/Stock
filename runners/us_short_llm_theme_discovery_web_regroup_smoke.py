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
PACKET_PATH = ROOT / "docs" / "us_short_web_regroup_engineering_smoke_packet_20260815.json"
SCHEMA_PATH = ROOT / "schemas" / "us_short_web_regroup_engineering_smoke_packet.schema.json"
PRIVATE_ROOT = ROOT / "state" / "us_short" / "runs_private" / "soft_discovery_engineering_smoke"
PARENT_PLAN_PATH = PRIVATE_ROOT / "us_short_web_regroup_engineering_smoke_20260815_parent_plan.json"
RAW_ROOT = ROOT / "provider_samples" / "us_short_llm_theme_discovery_engineering_smoke"
SUMMARY_PATH = PRIVATE_ROOT / "us_short_web_regroup_engineering_smoke_20260815_summary.json"

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


def _summary(
    packet: Mapping[str, Any], *, status: str, provider_ref: Mapping[str, Any] | None,
    parse_status: str, parse_error_type: str | None, parsed_theme_count: int | None,
    raw_hash_reread: bool, terminal_error_type: str | None = None,
) -> dict[str, Any]:
    served_model = provider_ref.get("served_model") if provider_ref is not None else None
    usage = provider_ref.get("usage") if provider_ref is not None else None
    finish_reason = provider_ref.get("finish_reason") if provider_ref is not None else None
    model_match = served_model == packet["paid_boundary"]["request"]["model"]
    theme_contract = (
        parsed_theme_count is not None
        and parsed_theme_count <= packet["paid_boundary"]["request"]["max_themes_per_chunk"]
    )
    raw_ref = provider_ref.get("raw_receipt_ref") if provider_ref is not None else None
    raw_sha = provider_ref.get("response_sha256") if provider_ref is not None else None
    raw_before_parse = provider_ref is not None
    passed = (
        status == "live_authorized_engineering_smoke_response_captured"
        and raw_before_parse
        and raw_hash_reread
        and model_match
        and isinstance(usage, dict)
        and all(type(usage.get(key)) is int and usage[key] >= 0 for key in (
            "prompt_tokens", "completion_tokens", "total_tokens",
        ))
        and finish_reason == "stop"
        and parse_status == "passed"
        and theme_contract
        and terminal_error_type is None
    )
    return {
        "schema_name": "us_short_web_regroup_engineering_smoke_summary",
        "schema_version": "1.0.0",
        "status": status,
        "transport_verdict": "PASS" if passed else "FAIL",
        "packet_id": packet["packet_id"],
        "source_decision_date": packet["source_decision_date"],
        "original_chunk_index": packet["input"]["target_chunk_index"],
        "provider_call_count": 1,
        "deepseek_call_count": 1,
        "tavily_call_count": 0,
        "xai_call_count": 0,
        "retry_count": 0,
        "requested_model": packet["paid_boundary"]["request"]["model"],
        "served_model": served_model,
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
        "parsed_theme_count": parsed_theme_count,
        "max_four_themes_status": "passed" if theme_contract else "failed",
        "model_identity_match": model_match,
        "formal_decision_slots_occupied": False,
        "discovery_published": False,
        "receipt_published": False,
        "merge_published": False,
        "validation_published": False,
        "boost_published": False,
        "score_effect": False,
        "replay_permitted": False,
        "terminal_error_type": terminal_error_type,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }


def _reread_raw_hash(provider_ref: Mapping[str, Any]) -> bool:
    raw_path = _safe_repo_file(
        ROOT,
        provider_ref["raw_receipt_ref"],
        prefix="provider_samples/us_short_llm_theme_discovery_engineering_smoke/",
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
    if ROOT.resolve() != LIVE_ROOT.resolve():
        raise EngineeringSmokeError("paid smoke execution is allowed only from the fixed main tree")
    _assert_one_shot_roots_empty()
    rows = _frozen_target_rows(packet)
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
            expected_served_model=packet["paid_boundary"]["request"]["model"],
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
            raw_hash_reread=False,
            terminal_error_type=type(item.outcome.call_error).__name__,
        )
        web.publish_engineering_smoke_diagnostic(summary)
        return summary
    raw_hash_reread = _reread_raw_hash(provider_ref)
    parse_status = "passed"
    parse_error_type = None
    parsed_theme_count: int | None = None
    if item.item_error is not None:
        parse_status = "failed"
        parse_error_type = type(item.item_error).__name__
    elif isinstance(item.value, tuple) and len(item.value) == 3:
        parsed_theme_count = len(item.value[2])
    else:
        parse_status = "failed"
        parse_error_type = "unexpected_parser_value"
    summary = _summary(
        packet,
        status="live_authorized_engineering_smoke_response_captured",
        provider_ref=provider_ref,
        parse_status=parse_status,
        parse_error_type=parse_error_type,
        parsed_theme_count=parsed_theme_count,
        raw_hash_reread=raw_hash_reread,
        terminal_error_type=(type(batch.stop_error).__name__ if batch.stop_error is not None else None),
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
