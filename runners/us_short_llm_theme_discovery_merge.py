"""Knife-3/4c: deterministic web/X discovery merge and per-ticker evidence tier.

This is offline-only.  It consumes the two knife-3 source artifacts plus their
receipt manifests, verifies the artifact hashes, merges themes/members without
changing the knife-1 artifact contract, and emits a separate merge manifest
with ``discovery_sources`` and ``evidence_tier``.  It does not score, select,
confirm themes, or touch the weekly orchestrator.
"""
from __future__ import annotations

import hashlib
import json
import re
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from engine.us_short_schema_formats import FORMAT_CHECKER

ROOT = web.ROOT
SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery_merge.schema.json"


def default_discovery_path(expected_decision_date: str) -> Path:
    return web.STATE_DIR / f"us_short_llm_theme_discovery_web_x_{expected_decision_date}.json"


def default_manifest_path(expected_decision_date: str) -> Path:
    return web.STATE_DIR / f"us_short_llm_theme_discovery_web_x_{expected_decision_date}_merge.json"


class ThemeDiscoveryMergeError(ValueError):
    """The web/X merge would require an unsafe guess."""


def _sha(value: Any) -> str:
    return hashlib.sha256(web._canonical_json(value)).hexdigest()


def _instant(value: Any, field: str) -> datetime:
    try:
        return web._parse_dt(value, field=field)
    except web.WebThemeDiscoveryError as exc:
        raise ThemeDiscoveryMergeError(f"{field} is not timezone-aware RFC3339") from exc


def _corroboration(bound_refs: list[dict[str, str]]) -> tuple[str, str | None, list[str]]:
    """Independent-evidence verdict for one member (or the label for one theme).

    `both` — the 5-point tier — may only mean TWO INDEPENDENT DOCUMENTS.  Source IDs are
    ``<lane>:sha256(canonical_locator)`` and `_verify_receipt` now re-derives that binding, so the
    suffix is a content identity: the same suffix in both lanes is one document surfaced twice (a Grok
    citation to the news article Tavily also found), not corroboration.  A lane that contributes no
    document the other lane lacks is therefore REDUNDANT: its refs are reported and pruned from the
    member's evidence, because knife-2 re-derives the tier from ref TYPES alone — pruning is what makes
    this verdict reach the score instead of being silently upgraded back to `both` one layer down.

    This rule is sound only here, where IDs are provably `<lane>:sha256(locator)`; a knife-2-side latch
    would be unsound because a locally-authored discovery artifact's suffixes are not content hashes.
    """
    by_lane = {kind: {ref["source_id"].split(":", 1)[1] for ref in bound_refs if ref["source_type"] == kind}
               for kind in ("web", "x")}
    present = {kind for kind in ("web", "x") if by_lane[kind]}
    if not present:
        return "none", None, []
    if len(present) == 1:
        return next(iter(present)), "single", []
    web_only, x_only = by_lane["web"] - by_lane["x"], by_lane["x"] - by_lane["web"]
    if web_only and x_only:
        return "both", "both", []
    keep = "web" if web_only or not x_only else "x"
    redundant = sorted(ref["source_id"] for ref in bound_refs if ref["source_type"] != keep)
    return keep, "single", redundant


def _schema_validate(path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise ThemeDiscoveryMergeError("jsonschema is required; refusing schema bypass") from exc
    schema = web._read_json(path)
    errors = sorted(
        Draft7Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ThemeDiscoveryMergeError(f"schema rejected: {errors[0].message}")


def _validate_discovery(artifact: dict[str, Any]) -> None:
    schema = web._read_json(ROOT / "schemas" / "us_short_llm_theme_discovery.schema.json")
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise ThemeDiscoveryMergeError("jsonschema is required; refusing schema bypass") from exc
    errors = sorted(
        Draft7Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(artifact),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ThemeDiscoveryMergeError(f"discovery artifact rejected: {errors[0].message}")


def _verify_receipt(
    artifact: dict[str, Any], receipt: dict[str, Any], source_type: str,
    expected_decision_date: str,
) -> dict[str, str]:
    try:
        if source_type == "web":
            web._validate_schema(receipt)
        else:
            xfetch._validate_schema(receipt)
    except Exception as exc:
        raise ThemeDiscoveryMergeError(f"{source_type} receipt schema is invalid") from exc
    if receipt.get("decision_clock", {}).get("expected_decision_date") != expected_decision_date:
        raise ThemeDiscoveryMergeError(f"{source_type} receipt decision date does not match merge clock")
    if artifact.get("decision_clock", {}).get("expected_decision_date") != expected_decision_date:
        raise ThemeDiscoveryMergeError(f"{source_type} artifact decision date does not match merge clock")
    contract = receipt.get("fetch_contract", {})
    mode = contract.get("execution_mode")
    expected_live = mode == "live_authorized"
    if contract.get("network_access_performed") is not expected_live or contract.get("provider_calls_performed") is not expected_live:
        raise ThemeDiscoveryMergeError(f"{source_type} receipt execution evidence is inconsistent with execution_mode")
    network_calls = contract.get("network_call_count")
    provider_calls = contract.get("provider_call_count")
    if not isinstance(network_calls, int) or not isinstance(provider_calls, int) or network_calls < 0 or provider_calls < 0:
        raise ThemeDiscoveryMergeError(f"{source_type} receipt call counts are malformed")
    if expected_live and (network_calls <= 0 or provider_calls <= 0):
        raise ThemeDiscoveryMergeError(f"{source_type} live receipt has no observed provider/network calls")
    if not expected_live and (network_calls or provider_calls):
        raise ThemeDiscoveryMergeError(f"{source_type} offline receipt claims provider/network calls")
    expected = web._discovery_evidence_hash(artifact)
    if receipt.get("discovery_artifact_sha256") != expected:
        raise ThemeDiscoveryMergeError(f"{source_type} discovery artifact digest does not match receipt")
    actual_types: dict[str, str] = {}
    artifact_refs = {ref.get("source_id"): ref for ref in artifact.get("source_refs", []) if isinstance(ref, dict)}
    artifact_types = {source_id: ref.get("source_type") for source_id, ref in artifact_refs.items()}
    cutoff = web._cutoff(expected_decision_date)
    for ref in receipt.get("source_refs", []):
        if ref.get("source_type") != source_type:
            raise ThemeDiscoveryMergeError(f"receipt source type mismatch: {ref.get('source_id')}")
        source_id = ref.get("source_id")
        if not isinstance(source_id, str) or source_id in actual_types:
            raise ThemeDiscoveryMergeError("receipt source IDs are malformed or duplicated")
        if artifact_types.get(source_id) != source_type:
            raise ThemeDiscoveryMergeError(f"artifact source type mismatch: {source_id}")
        # Identity must be RE-DERIVED from content, not merely repeated consistently across the three
        # copies: a self-consistent raw/receipt/artifact triad carrying an unbound ID is not provenance.
        locator = ref.get("canonical_locator")
        if not isinstance(locator, str) or not locator:
            raise ThemeDiscoveryMergeError(f"{source_type} receipt source has no canonical locator: {source_id}")
        # Re-deriving the ID from the receipt's own string only proves self-consistency; the dedup below
        # treats the hash as a DOCUMENT identity, so the string must already be canonical — otherwise a
        # host-case or trailing-slash variant of one URL mints a second identity and reads as `both`.
        if web._canonical_locator(locator) != locator:
            raise ThemeDiscoveryMergeError(f"{source_type} receipt locator is not canonical: {source_id}")
        expected_id = web._source_id(locator) if source_type == "web" else xfetch._source_id(locator)
        if source_id != expected_id:
            raise ThemeDiscoveryMergeError(f"{source_type} source ID is not derived from its canonical locator: {source_id}")
        # The observation instant is the PIT-bearing field, so bind it across receipt and artifact and
        # keep the pre-open check here too (a hash only proves the receipt is self-consistent).
        observed = _instant(ref.get("observed_at"), f"{source_type} receipt observed_at ({source_id})")
        if observed >= cutoff:
            raise ThemeDiscoveryMergeError(f"{source_type} receipt source was observed after the decision open: {source_id}")
        if _instant(artifact_refs[source_id].get("observed_at"), f"{source_type} artifact observed_at ({source_id})") != observed:
            raise ThemeDiscoveryMergeError(f"{source_type} artifact observation does not match the receipt: {source_id}")
        if mode == "live_authorized":
            raw_ref = ref.get("raw_receipt_ref")
            if not isinstance(raw_ref, str) or not ref.get("raw_receipt_gitignored"):
                raise ThemeDiscoveryMergeError(f"live {source_type} receipt is missing a gitignored raw receipt")
            raw_path = (ROOT / raw_ref).resolve()
            if not raw_path.is_relative_to(ROOT.resolve()) or not raw_path.is_file() or not web._gitignored(raw_path):
                raise ThemeDiscoveryMergeError(f"live {source_type} raw receipt is not gitignored")
            if raw_path.name != f"{source_id.split(':', 1)[1]}.json" or raw_path.parent.name != expected_decision_date:
                raise ThemeDiscoveryMergeError(f"live {source_type} raw receipt path is not bound to its source ID and decision date: {source_id}")
            try:
                raw_payload = web._read_json(raw_path)
            except web.WebThemeDiscoveryError as exc:
                raise ThemeDiscoveryMergeError(f"live {source_type} raw receipt is unreadable") from exc
            if _sha(raw_payload) != ref.get("content_sha256"):
                raise ThemeDiscoveryMergeError(f"live {source_type} raw receipt content hash does not match")
            for key in ("source_id", "source_type", "canonical_locator"):
                if raw_payload.get(key) != ref.get(key):
                    raise ThemeDiscoveryMergeError(f"live {source_type} raw receipt binding mismatch: {key}")
            # A re-hashed raw payload is self-consistent, so the raw observation time must be bound to
            # the receipt's PIT field as well; otherwise after-open evidence rides in behind a good hash.
            raw_time_key = "published_at" if source_type == "web" else "created_at"
            if _instant(raw_payload.get(raw_time_key), f"live {source_type} raw {raw_time_key} ({source_id})") != observed:
                raise ThemeDiscoveryMergeError(f"live {source_type} raw observation time does not match the receipt: {source_id}")
        actual_types[source_id] = source_type
    artifact_ids = {ref.get("source_id") for ref in artifact.get("source_refs", [])}
    if artifact_ids != set(actual_types):
        raise ThemeDiscoveryMergeError(f"{source_type} receipt source IDs do not cover artifact refs")
    return actual_types


def _theme_key(theme: dict[str, Any]) -> str:
    theme_id = theme.get("theme_id")
    if isinstance(theme_id, str) and theme_id:
        return "id:" + theme_id.lower()
    return "name:" + re.sub(r"[^a-z0-9]+", "_", str(theme.get("display_name", "")).lower()).strip("_")


def merge_web_x_discovery(
    *, web_artifact: dict[str, Any], web_receipt: dict[str, Any],
    x_artifact: dict[str, Any], x_receipt: dict[str, Any],
    expected_decision_date: str, generated_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    web._decision_date(expected_decision_date)
    # Normalize the operator-supplied clock exactly as the ingest does: the manifest is
    # schema-checked for RFC 3339, so a loose-but-parseable spelling must not reach it.
    generated_at = _instant(generated_at, "generated_at").isoformat()
    _validate_discovery(web_artifact)
    _validate_discovery(x_artifact)
    web_types = _verify_receipt(web_artifact, web_receipt, "web", expected_decision_date)
    x_types = _verify_receipt(x_artifact, x_receipt, "x", expected_decision_date)
    refs_by_id: dict[str, dict[str, str]] = {}
    receipt_refs_by_id: dict[str, dict[str, Any]] = {}
    for receipt in (web_receipt, x_receipt):
        for ref in receipt.get("source_refs", []):
            receipt_refs_by_id[ref["source_id"]] = dict(ref)
    for artifact, source_type in ((web_artifact, "web"), (x_artifact, "x")):
        for ref in artifact["source_refs"]:
            source_id = ref["source_id"]
            prior = refs_by_id.get(source_id)
            candidate = {"source_id": source_id, "source_type": source_type, "observed_at": ref["observed_at"]}
            if prior is not None and prior != candidate:
                raise ThemeDiscoveryMergeError(f"source ID has conflicting definitions: {source_id}")
            refs_by_id[source_id] = candidate
    if set(web_types) & set(x_types):
        raise ThemeDiscoveryMergeError("web and x source IDs unexpectedly overlap")
    merged: dict[str, dict[str, Any]] = {}
    for artifact in (web_artifact, x_artifact):
        for theme in artifact["themes"]:
            key = _theme_key(theme)
            if key not in merged:
                merged[key] = {
                    "theme_id": theme["theme_id"], "display_name": theme["display_name"], "summary": theme["summary"],
                    "status": "provisional_discovered", "observed_at": theme["observed_at"],
                    "source_ref_ids": [], "members": {}, "cross_industry_validation_status": "not_run", "market_confirmation_status": "not_run",
                }
            target = merged[key]
            target["source_ref_ids"] = sorted(set(target["source_ref_ids"]) | set(theme["source_ref_ids"]))
            # Compare INSTANTS, not strings: a lexical max over mixed UTC offsets picks the earlier
            # real instant, which then predates a cited source and kills the week.
            target["observed_at"] = max(
                target["observed_at"], theme["observed_at"],
                key=lambda value: web._parse_dt(value, field="theme.observed_at"),
            )
            for member in theme["members"]:
                ticker = member["ticker"]
                row = target["members"].setdefault(ticker, {"ticker": ticker, "membership_status": "provisional_unvalidated", "source_ref_ids": []})
                row["source_ref_ids"] = sorted(set(row["source_ref_ids"]) | set(member["source_ref_ids"]))
    # Prune each member's non-independent lane BEFORE the ingest freezes the artifact: knife-2 rebuilds
    # `evidence_tier` from ref types only, so a redundant lane left in place is re-promoted to `both`
    # (5.0) no matter what this manifest says.  What was pruned is kept per member in the manifest.
    from engine.us_short_eligibility_gate import canonical_us_ticker
    redundant_by_member: dict[tuple[str, str], list[str]] = {}
    for theme in merged.values():
        for ticker, row in theme["members"].items():
            bound = [refs_by_id[ref_id] for ref_id in row["source_ref_ids"] if ref_id in refs_by_id]
            redundant = _corroboration(bound)[2]
            if redundant:
                row["source_ref_ids"] = sorted(set(row["source_ref_ids"]) - set(redundant))
                redundant_by_member[(theme["theme_id"], canonical_us_ticker(ticker) or ticker)] = redundant
    discovery_input = {"source_refs": list(refs_by_id.values()), "themes": []}
    for theme in merged.values():
        theme = dict(theme)
        theme["members"] = list(theme["members"].values())
        discovery_input["themes"].append(theme)
    from runners.us_short_llm_theme_discovery import normalize_discovery_payload
    # §五 red-line #4 extends past the fetch layer: one theme the ingest cannot normalize must be
    # dropped with a ledger row, not allowed to abort the whole week's merge.
    merge_drops: list[dict[str, Any]] = []
    keepable: list[dict[str, Any]] = []
    for theme in discovery_input["themes"]:
        try:
            normalize_discovery_payload(
                {"source_refs": discovery_input["source_refs"], "themes": [theme]},
                expected_decision_date=expected_decision_date, generated_at=generated_at,
            )
        except Exception as exc:
            merge_drops.append({
                "stage": "theme", "theme_id": str(theme.get("theme_id", "unknown")),
                "reason": "theme_rejected_by_ingest", "detail": type(exc).__name__,
            })
            continue
        keepable.append(theme)
    discovery_input["themes"] = keepable
    merged_artifact = normalize_discovery_payload(discovery_input, expected_decision_date=expected_decision_date, generated_at=generated_at)
    member_rows: list[dict[str, Any]] = []
    theme_rows: list[dict[str, Any]] = []
    for theme in merged_artifact["themes"]:
        # Theme refs stay whole (members bind to them), but the LABEL must use the same
        # independent-document rule, or a theme whose only X ref repeats a web document reads as `both`.
        theme_sources = _corroboration(
            [refs_by_id[ref_id] for ref_id in theme["source_ref_ids"] if ref_id in refs_by_id]
        )[0]
        theme_member_rows = []
        for member in theme["members"]:
            bound = [refs_by_id[ref_id] for ref_id in member["source_ref_ids"] if ref_id in refs_by_id]
            sources, tier, residual = _corroboration(bound)
            if residual:
                raise ThemeDiscoveryMergeError(f"member evidence pruning failed for {member['ticker']}")
            row = {"ticker": member["ticker"], "discovery_sources": sources, "evidence_tier": tier,
                   "source_ref_ids": member["source_ref_ids"],
                   "redundant_source_ref_ids": redundant_by_member.get((theme["theme_id"], member["ticker"]), [])}
            member_rows.append({"theme_id": theme["theme_id"], **row})
            theme_member_rows.append(row)
        theme_rows.append({"theme_id": theme["theme_id"], "discovery_sources": theme_sources, "members": theme_member_rows})
    manifest = {
        "schema_name": "us_short_llm_theme_discovery_merge", "schema_version": "1.0.0", "generated_at": generated_at,
        "decision_clock": {"expected_decision_date": expected_decision_date, "cutoff_policy": "before_decision_open_et", "pit_enforced": True},
        "merge_contract": {"producer_kind": "web_x_discovery_merge", "execution_mode": "offline_local_receipts", "scoring_eligible": False, "top15_effect_enabled": False, "operation_advice_effect_enabled": False, "dynamic_seats_enabled": False, "theme_probe_enabled": False, "lifecycle_actions_enabled": False},
        "input_artifact_sha256": {"web": web._discovery_evidence_hash(web_artifact), "x": web._discovery_evidence_hash(x_artifact)}, "source_refs": [receipt_refs_by_id[source_id] for source_id in sorted(receipt_refs_by_id)], "themes": theme_rows,
        "drop_ledger": sorted(merge_drops, key=lambda row: (row["theme_id"], row["reason"])),
        "summary": {"web_theme_count": len(web_artifact["themes"]), "x_theme_count": len(x_artifact["themes"]), "merged_theme_count": len(theme_rows), "dropped_theme_count": len(merge_drops), "both_member_count": sum(row["evidence_tier"] == "both" for row in member_rows), "single_member_count": sum(row["evidence_tier"] == "single" for row in member_rows), "zero_member_count": sum(row["evidence_tier"] is None for row in member_rows), "redundant_member_count": sum(bool(row["redundant_source_ref_ids"]) for row in member_rows)},
    }
    _schema_validate(SCHEMA_PATH, manifest)
    return merged_artifact, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge offline knife-3 web and X discovery packets.")
    parser.add_argument("--web-discovery", type=Path, required=True)
    parser.add_argument("--web-receipt", type=Path, required=True)
    parser.add_argument("--x-discovery", type=Path, required=True)
    parser.add_argument("--x-receipt", type=Path, required=True)
    parser.add_argument("--expected-decision-date", required=True)
    parser.add_argument("--generated-at", required=True)
    # Per-decision-date defaults: an undated slot plus the immutability raise is a one-shot lane.
    parser.add_argument("--discovery-output", type=Path, default=None)
    parser.add_argument("--manifest-output", type=Path, default=None)
    args = parser.parse_args(argv)
    web._decision_date(args.expected_decision_date)
    discovery_output, manifest_output = web._decision_publish_paths(
        args.discovery_output or default_discovery_path(args.expected_decision_date),
        default_discovery_path(args.expected_decision_date),
        args.manifest_output or default_manifest_path(args.expected_decision_date),
        default_manifest_path(args.expected_decision_date),
    )
    merged, manifest = merge_web_x_discovery(
        web_artifact=web._read_json(args.web_discovery), web_receipt=web._read_json(args.web_receipt),
        x_artifact=web._read_json(args.x_discovery), x_receipt=web._read_json(args.x_receipt),
        expected_decision_date=args.expected_decision_date, generated_at=args.generated_at,
    )
    web.publish_decision_pair(
        merged, discovery_output, default_discovery_path(args.expected_decision_date),
        manifest, manifest_output, default_manifest_path(args.expected_decision_date),
    )
    print(json.dumps(manifest["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    main()
