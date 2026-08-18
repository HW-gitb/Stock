"""Replay the one frozen Web regroup response for the zero-cost 5b diagnostic.

This runner reads only the fifth-knife packet, transport summary, raw response, frozen
sources, and the one frozen SIC snapshot.  It reuses the production parser, member
binding producer, discovery normalizer, and provisional validator.  It has no provider,
budget, retry, formal-publisher, merge, boost, or score path.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
PACKET_PATH = ROOT / "docs" / "us_short_web_regroup_engineering_smoke_packet_20260815_v2.json"
PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_web_regroup_engineering_smoke_packet_v2.schema.json"
TRANSPORT_SUMMARY_PATH = (
    ROOT / "state" / "us_short" / "runs_private" / "soft_discovery_engineering_smoke_v2"
    / "us_short_web_regroup_engineering_smoke_20260815_chunk1_summary.json"
)
TRANSPORT_RAW_ROOT = ROOT / "provider_samples" / "us_short_llm_theme_discovery_engineering_smoke_v2"
REPLAY_SUMMARY_PATH = (
    ROOT / "state" / "us_short" / "runs_private" / "soft_discovery_engineering_smoke_v2"
    / "us_short_web_regroup_replay_20260815_chunk1_summary.json"
)
SIC_SNAPSHOT_PATH = (
    ROOT / "state" / "us_short" / "sec_sic_classification_snapshots"
    / "sec_sic_snapshot_20260810T043853Z_d754ea63c8e39555.json"
)
SIC_SNAPSHOT_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_sec_sic_classification_snapshot.schema.json"
EXPECTED_DECISION_DATE = "20260815"
EXPECTED_SIC_SOURCE_AS_OF = "2026-08-10"
EXPECTED_SIC_SNAPSHOT_ID = "d754ea63c8e39555fc28cd58e121aef975145ff7e34e7995483a28f6d6860d71"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker  # noqa: E402
from engine.us_short_schema_formats import FORMAT_CHECKER  # noqa: E402
from runners import us_short_batch5_full_universe_sec_sic_classification_fetch as sic_fetch  # noqa: E402
from runners import us_short_discovery_publish_policy as publish_policy  # noqa: E402
from runners import us_short_llm_theme_discovery_fetch_web as web  # noqa: E402
from runners import us_short_provisional_theme_validate as provisional_validate  # noqa: E402


class WebRegroupReplayError(ValueError):
    """The fifth-knife evidence is missing, changed, or cannot be replayed safely."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebRegroupReplayError("required 5b JSON evidence is unreadable") from exc


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise WebRegroupReplayError("required 5b evidence digest cannot be read") from exc


def _safe_repo_file(root: Path, relative_ref: Any, *, prefix: str) -> Path:
    if (
        not isinstance(relative_ref, str)
        or not relative_ref.startswith(prefix)
        or any(part in {"", ".", ".."} for part in Path(relative_ref).parts)
    ):
        raise WebRegroupReplayError("5b evidence reference is outside its frozen namespace")
    path = (root / relative_ref).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise WebRegroupReplayError("5b evidence reference escapes the repository") from exc
    if path.is_symlink() or not path.is_file():
        raise WebRegroupReplayError("a required fifth-knife evidence file is missing")
    return path


def _schema_validate(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - project dependency guard
        raise WebRegroupReplayError("jsonschema is required for 5b") from exc
    errors = sorted(
        Draft7Validator(
            _read_json(schema_path), format_checker=FORMAT_CHECKER,
        ).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        raise WebRegroupReplayError(f"{label} schema rejected the frozen input")


def _validate_packet() -> dict[str, Any]:
    packet = _read_json(PACKET_PATH)
    _schema_validate(packet, PACKET_SCHEMA_PATH, label="fifth-knife packet")
    receipt_path = _safe_repo_file(
        ROOT, packet["input"]["receipt_ref"], prefix="state/us_short/",
    )
    if _sha256_file(receipt_path) != packet["input"]["receipt_sha256"]:
        raise WebRegroupReplayError("fifth-knife receipt digest does not match the packet")
    return packet


def _validate_transport_summary(packet: Mapping[str, Any]) -> dict[str, Any]:
    summary = _read_json(TRANSPORT_SUMMARY_PATH)
    if type(summary) is not dict:
        raise WebRegroupReplayError("fifth-knife transport summary is not an object")
    request = packet.get("paid_boundary", {}).get("request", {})
    if (
        summary.get("packet_id") != packet["packet_id"]
        or summary.get("source_decision_date") != EXPECTED_DECISION_DATE
        or summary.get("transport_verdict") != "PASS"
        or summary.get("status") != "live_authorized_engineering_smoke_response_captured"
        or summary.get("original_chunk_index") != packet["input"]["target_chunk_index"]
        or summary.get("requested_model") != request.get("model")
        or summary.get("expected_served_model") != request.get("expected_served_model")
        or summary.get("model_identity_match") is not True
        or summary.get("budget_ledger_ref") != packet["output_boundary"]["budget_ledger_ref"]
    ):
        raise WebRegroupReplayError("fifth-knife transport summary is not a PASS for this packet")
    if (
        summary.get("provider_call_count") != 1
        or summary.get("deepseek_call_count") != 1
        or summary.get("tavily_call_count") != 0
        or summary.get("xai_call_count") != 0
        or summary.get("retry_count") != 0
        or summary.get("recovery_count") != 0
        or summary.get("unknown_sibling_count") != 0
        or summary.get("raw_persisted_before_parse") is not True
        or summary.get("raw_hash_reread") is not True
        or summary.get("strict_parse_status") != "passed"
        or summary.get("formal_decision_slots_occupied") is not False
    ):
        raise WebRegroupReplayError("fifth-knife transport summary has an unsafe execution shape")
    return summary


def _load_target_inputs(packet: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime]:
    """Rebuild the target chunk through the production normalizer and chunker."""
    receipt_path = ROOT / packet["input"]["receipt_ref"]
    receipt = _read_json(receipt_path)
    receipt_refs = receipt.get("source_refs") if isinstance(receipt, dict) else None
    if (
        type(receipt) is not dict
        or receipt.get("decision_clock", {}).get("expected_decision_date") != EXPECTED_DECISION_DATE
        or not isinstance(receipt_refs, list)
        or len(receipt_refs) != packet["input"]["accepted_source_count"]
    ):
        raise WebRegroupReplayError("frozen Web receipt source set is malformed")
    rows: list[dict[str, Any]] = []
    for ref in receipt_refs:
        if type(ref) is not dict:
            raise WebRegroupReplayError("frozen Web receipt contains a malformed source ref")
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
            raise WebRegroupReplayError("frozen Web raw source does not match its receipt ref")
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
        expected_decision_date=EXPECTED_DECISION_DATE,
        fetched_at=fetched_at,
        raw_root=None,
        persist_raw=False,
    )
    if drops or len(normalized_refs) != 34 or len(prompt_rows) != 34:
        raise WebRegroupReplayError("production Web normalization did not conserve the frozen sources")
    normalized_by_id = {ref["source_id"]: ref for ref in normalized_refs}
    if any(
        normalized_by_id.get(ref.get("source_id"), {}).get("content_sha256")
        != ref.get("content_sha256")
        for ref in receipt_refs
    ):
        raise WebRegroupReplayError("frozen Web source digest changed during replay")
    chunks = web._chunk_regroup_rows(prompt_rows)
    if [len(chunk) for chunk in chunks] != [10, 10, 10, 4]:
        raise WebRegroupReplayError("production Web chunking did not produce the frozen four chunks")
    all_ids = [row["source_id"] for chunk in chunks for row in chunk]
    receipt_ids = [ref["source_id"] for ref in receipt_refs]
    if len(all_ids) != len(set(all_ids)) or set(all_ids) != set(receipt_ids):
        raise WebRegroupReplayError("production Web chunking did not conserve the receipt source set")
    target_index = packet["input"]["target_chunk_index"]
    target = chunks[target_index]
    target_ids = [row["source_id"] for row in target]
    if target_ids != packet["input"]["target_source_ids"]:
        raise WebRegroupReplayError("frozen target chunk order does not match production derivation")
    receipt_by_id = {ref["source_id"]: ref for ref in receipt_refs}
    target_refs = [receipt_by_id[source_id] for source_id in target_ids]
    if target_refs != packet["input"]["target_source_refs"]:
        raise WebRegroupReplayError("packet target source refs differ from the frozen receipt")
    return [dict(row) for row in target], [dict(ref) for ref in target_refs], fetched_at


def _load_transport_response(summary: Mapping[str, Any]) -> tuple[dict[str, Any], datetime]:
    raw_prefix = TRANSPORT_RAW_ROOT.resolve().relative_to(ROOT.resolve()).as_posix() + "/"
    raw_path = _safe_repo_file(
        ROOT,
        summary.get("raw_provider_response_ref"),
        prefix=raw_prefix,
    )
    raw = _read_json(raw_path)
    if type(raw) is not dict or raw.get("provider") != "deepseek" or type(raw.get("response")) is not dict:
        raise WebRegroupReplayError("fifth-knife raw response envelope is malformed")
    try:
        fetched_at = web._parse_dt(raw["fetched_at"], field="raw_response.fetched_at")
    except (KeyError, WebRegroupReplayError) as exc:
        raise WebRegroupReplayError("fifth-knife raw response clock is malformed") from exc
    response_sha256 = web._sha256_bytes(web._canonical_json(raw["response"]))
    if response_sha256 != summary.get("raw_provider_response_sha256"):
        raise WebRegroupReplayError("fifth-knife raw response digest does not match its summary")
    if not web._gitignored(raw_path):
        raise WebRegroupReplayError("fifth-knife raw response is not in a private ignored root")
    return raw["response"], fetched_at


def _load_frozen_sic() -> tuple[dict[str, Any], dict[str, str]]:
    snapshot = _read_json(SIC_SNAPSHOT_PATH)
    _schema_validate(snapshot, SIC_SNAPSHOT_SCHEMA_PATH, label="frozen SIC snapshot")
    if (
        snapshot.get("source_as_of") != EXPECTED_SIC_SOURCE_AS_OF
        or snapshot.get("snapshot_id") != EXPECTED_SIC_SNAPSHOT_ID
        or snapshot.get("snapshot_id") != sic_fetch._snapshot_digest(snapshot)
    ):
        raise WebRegroupReplayError("frozen SIC snapshot identity is invalid")
    sectors: dict[str, str] = {}
    for entry in snapshot["entries"].values():
        for raw_ticker in entry["tickers"]:
            ticker = canonical_us_ticker(raw_ticker)
            if ticker is None or (ticker in sectors and sectors[ticker] != entry["sector"]):
                raise WebRegroupReplayError("frozen SIC snapshot has conflicting ticker identity")
            sectors[ticker] = entry["sector"]
    return snapshot, sectors


def _semantic_results(
    parsed_themes: list[Any], discovery: Mapping[str, Any],
    validated_themes: list[dict[str, Any]], drops: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    accepted_ids = {theme["theme_id"] for theme in validated_themes}
    by_theme: dict[str, set[str]] = {}
    for drop in drops:
        theme_id = drop.get("theme_id")
        reason = drop.get("reason")
        if isinstance(theme_id, str) and isinstance(reason, str):
            by_theme.setdefault(theme_id, set()).add(reason)
    discovered_ids = {theme["theme_id"] for theme in discovery["themes"]}
    return [
        {
            "theme_id": theme.get("theme_id") if isinstance(theme, dict) else "<malformed>",
            "machine_result": (
                "accepted" if (theme.get("theme_id") if isinstance(theme, dict) else None) in accepted_ids
                else "rejected" if (theme.get("theme_id") if isinstance(theme, dict) else None) in discovered_ids
                else "not_reached_semantic_gate"
            ),
            "drop_reasons": sorted(
                by_theme.get(theme.get("theme_id") if isinstance(theme, dict) else "", set())
                | {
                    row["binding_reason"]
                    for row in ledger
                    if row.get("theme_id") == (theme.get("theme_id") if isinstance(theme, dict) else None)
                    and row.get("binding_status") == "rejected"
                }
                | {
                    row["parent_theme_reason"]
                    for row in ledger
                    if row.get("theme_id") == (theme.get("theme_id") if isinstance(theme, dict) else None)
                    and isinstance(row.get("parent_theme_reason"), str)
                }
            ),
        }
        for theme in parsed_themes
    ]


def _write_replay_summary(summary: dict[str, Any]) -> None:
    try:
        publish_policy._write_mutable_private_json(
            summary, REPLAY_SUMMARY_PATH,
            root=ROOT, state_dir=ROOT / "state" / "us_short",
            gitignored=web._gitignored,
        )
    except publish_policy.DiscoveryPublishPolicyError as exc:
        raise WebRegroupReplayError("5b replay summary could not be written") from exc


def run_replay() -> dict[str, Any]:
    packet = _validate_packet()
    transport_summary = _validate_transport_summary(packet)
    target_rows, target_refs, _source_fetched_at = _load_target_inputs(packet)
    response, response_fetched_at = _load_transport_response(transport_summary)
    served_model, _fingerprint, themes = web._consume_regroup_response(
        response,
        expected_served_model=None,
        chunk_index=packet["input"]["target_chunk_index"],
    )
    target_ids = {row["source_id"] for row in target_rows}
    source_rows = {row["source_id"]: row for row in target_rows}
    binding_drops: list[dict[str, str]] = []
    bound = web._llm_to_discovery_input(
        {"themes": themes}, target_refs,
        drop_ledger=binding_drops,
        generated_at=response_fetched_at,
        chunk_index=packet["input"]["target_chunk_index"],
        chunk_source_ids=target_ids,
        source_rows=source_rows,
    )
    discovery, normalization_drops = web._normalize_discovery_with_binding_ledger(
        bound, bound["_theme_ledger_groups"], bound["member_binding_ledger"],
        expected_decision_date=EXPECTED_DECISION_DATE, generated=response_fetched_at,
    )
    ledger = bound["member_binding_ledger"]
    ledger_summary = web._member_binding_summary(
        ledger,
        parsed_chunk_indexes=[packet["input"]["target_chunk_index"]],
        unparsed_chunk_indexes=[],
    )
    snapshot, sectors = _load_frozen_sic()
    accepted_tickers = {
        row["canonical_ticker"] for row in ledger
        if row["binding_status"] == "accepted" and row["canonical_ticker"] is not None
    }
    validated_themes, validation_drops = provisional_validate.validate_provisional_themes(
        discovery,
        eligible_tickers=accepted_tickers,
        candidate_tickers=accepted_tickers,
        sectors_by_ticker={ticker: sectors[ticker] for ticker in accepted_tickers if ticker in sectors},
    )
    machine_summary = {
        "schema_name": "us_short_web_regroup_replay_summary",
        "schema_version": "1.0.0",
        "status": "offline_replay_completed",
        "packet_id": packet["packet_id"],
        "transport_verdict": transport_summary["transport_verdict"],
        "source_decision_date": EXPECTED_DECISION_DATE,
        "original_chunk_index": packet["input"]["target_chunk_index"],
        "target_source_ids": packet["input"]["target_source_ids"],
        "raw_provider_response_ref": transport_summary["raw_provider_response_ref"],
        "raw_provider_response_sha256": transport_summary["raw_provider_response_sha256"],
        "requested_model": transport_summary["requested_model"],
        "served_model": served_model,
        "parsed_theme_count": len(themes),
        "member_binding_ledger": ledger,
        "member_ledger_summary": ledger_summary,
        "binding_drop_reason_counts": {
            reason: sum(1 for row in binding_drops if row.get("reason") == reason)
            for reason in sorted({row.get("reason") for row in binding_drops if row.get("reason")})
        },
        "normalization_drop_reason_counts": {
            reason: sum(1 for row in normalization_drops if row.get("reason") == reason)
            for reason in sorted({row.get("reason") for row in normalization_drops if row.get("reason")})
        },
        "semantic_results": _semantic_results(
            themes, discovery, validated_themes, validation_drops, ledger,
        ),
        "sic_snapshot": {
            "relative_path": SIC_SNAPSHOT_PATH.relative_to(ROOT).as_posix(),
            "source_as_of": snapshot["source_as_of"],
            "snapshot_id": snapshot["snapshot_id"],
            "calibration_only": True,
            "evaluable_accepted_ticker_count": sum(ticker in sectors for ticker in accepted_tickers),
            "missing_accepted_ticker_count": sum(ticker not in sectors for ticker in accepted_tickers),
        },
        "provider_call_count": 0,
        "network_call_count": 0,
        "retry_count": 0,
        "formal_decision_slots_occupied": False,
        "discovery_published": False,
        "receipt_published": False,
        "merge_published": False,
        "validation_published": False,
        "boost_published": False,
        "score_effect": False,
        "readiness": None,
    }
    _write_replay_summary(machine_summary)
    return machine_summary


def main() -> int:
    if len(sys.argv) != 1:
        print(json.dumps({"status": "STOP_INPUT_INVALID", "reason": "5b accepts no free input arguments"}, ensure_ascii=False))
        return 2
    try:
        summary = run_replay()
    except WebRegroupReplayError as exc:
        print(json.dumps({"status": "STOP_INPUT_INVALID", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
