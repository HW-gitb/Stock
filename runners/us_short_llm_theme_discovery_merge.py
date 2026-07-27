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
from pathlib import Path, PurePosixPath
from typing import Any

from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery as ingest
from engine.us_short_schema_formats import FORMAT_CHECKER

ROOT = web.ROOT
SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery_merge.schema.json"
PROVIDER_SAMPLES_ROOT = ROOT / "provider_samples"


def default_discovery_path(expected_decision_date: str) -> Path:
    return web.STATE_DIR / f"us_short_llm_theme_discovery_web_x_{expected_decision_date}.json"


def default_manifest_path(expected_decision_date: str) -> Path:
    return web.STATE_DIR / f"us_short_llm_theme_discovery_web_x_{expected_decision_date}_merge.json"


class ThemeDiscoveryMergeError(ValueError):
    """The web/X merge would require an unsafe guess."""


CONFORMANCE_GUARDS = (
    "_instant",
    "_validate_discovery",
    "_schema_validate",
    "_verify_receipt",
    "_guard_generated_clock",
    "_guard_source_identity",
    "_guard_source_pit",
    "_guard_raw_content_digest",
    "_guard_member_evidence_tier",
    "_guard_summary_counts",
    "_guard_unique_manifest_rows",
    "_guard_merge_producer_clock",
    "_guard_merge_consumer_clock",
    "_guard_input_artifact_hashes",
    "_guard_upstream_generated_clocks",
    "_raw_receipt_path",
)


def _sha(value: Any) -> str:
    return hashlib.sha256(web._canonical_json(value)).hexdigest()


def _instant(value: Any, field: str) -> datetime:
    try:
        return web._parse_dt(value, field=field)
    except web.WebThemeDiscoveryError as exc:
        raise ThemeDiscoveryMergeError(f"{field} is not timezone-aware RFC3339") from exc


def _guard_generated_clock(value: Any, *, cutoff: datetime, field: str) -> datetime:
    instant = _instant(value, field)
    if instant >= cutoff:
        raise ThemeDiscoveryMergeError(f"{field} is not before the decision open")
    return instant


def _guard_merge_producer_clock(value: Any, *, cutoff: datetime) -> datetime:
    return _guard_generated_clock(value, cutoff=cutoff, field="generated_at")


def _guard_merge_consumer_clock(
    artifact_value: Any, manifest_value: Any, *, cutoff: datetime,
) -> None:
    artifact_generated = _guard_generated_clock(
        artifact_value, cutoff=cutoff, field="merged artifact generated_at",
    )
    manifest_generated = _guard_generated_clock(
        manifest_value, cutoff=cutoff, field="merge manifest generated_at",
    )
    if artifact_generated != manifest_generated:
        raise ThemeDiscoveryMergeError("merge artifact and manifest generated_at clocks do not match")


def _guard_input_artifact_hashes(
    actual: dict[str, Any], expected: dict[str, str],
) -> None:
    if actual != expected:
        raise ThemeDiscoveryMergeError("merge input artifact digests do not match document anchors")


def _guard_upstream_generated_clocks(
    artifact_value: Any,
    receipt_value: Any,
    *,
    cutoff: datetime,
    source_type: str,
) -> None:
    artifact_generated = _guard_generated_clock(
        artifact_value, cutoff=cutoff, field=f"{source_type} artifact generated_at",
    )
    receipt_generated = _guard_generated_clock(
        receipt_value, cutoff=cutoff, field=f"{source_type} receipt generated_at",
    )
    if artifact_generated != receipt_generated:
        raise ThemeDiscoveryMergeError(
            f"{source_type} artifact and receipt generated_at clocks do not match"
        )


def _guard_source_identity(*, source_id: str, source_type: str, locator: str) -> None:
    expected_id = web._source_id(locator) if source_type == "web" else xfetch._source_id(locator)
    if source_id != expected_id:
        raise ThemeDiscoveryMergeError("merge manifest source identity is not locator-derived")


def _guard_source_pit(*, observed: datetime, fetched: datetime, cutoff: datetime) -> None:
    if observed >= cutoff or fetched >= cutoff:
        raise ThemeDiscoveryMergeError("merge manifest source clock is not PIT-safe")


def _guard_raw_content_digest(*, raw_payload: dict[str, Any], expected_sha256: str) -> None:
    if _sha(raw_payload) != expected_sha256:
        raise ThemeDiscoveryMergeError("merge manifest raw content digest does not match")


def _guard_member_evidence_tier(
    *, residual: list[str], actual_sources: str, expected_sources: str,
    actual_tier: str | None, expected_tier: str | None,
) -> None:
    if residual or actual_sources != expected_sources or actual_tier != expected_tier:
        raise ThemeDiscoveryMergeError("merge manifest member evidence tier does not match its refs")


def _guard_summary_counts(*, summary: dict[str, Any], expected_counts: dict[str, int]) -> None:
    if any(summary[key] != value for key, value in expected_counts.items()):
        raise ThemeDiscoveryMergeError("merge manifest summary does not match its bound rows")


def _guard_unique_manifest_rows(rows: list[dict[str, Any]], *, key: str, label: str) -> dict[str, dict[str, Any]]:
    indexed = {row[key]: row for row in rows}
    if len(indexed) != len(rows):
        raise ThemeDiscoveryMergeError(f"merge manifest contains duplicate {label}")
    return indexed


def _raw_receipt_path(raw_ref: Any) -> Path:
    if not isinstance(raw_ref, str):
        raise ThemeDiscoveryMergeError("merge manifest raw receipt path is malformed")
    lexical = PurePosixPath(raw_ref)
    if (
        lexical.is_absolute()
        or not lexical.parts
        or lexical.parts[0] != "provider_samples"
        or ".." in lexical.parts
        or lexical.as_posix() != raw_ref
    ):
        raise ThemeDiscoveryMergeError("merge manifest raw receipt must stay under provider_samples")
    raw_path = (ROOT / raw_ref).resolve()
    if not raw_path.is_relative_to(PROVIDER_SAMPLES_ROOT.resolve()):
        raise ThemeDiscoveryMergeError("merge manifest raw receipt must stay under provider_samples")
    return raw_path


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
    _guard_upstream_generated_clocks(
        artifact.get("generated_at"),
        receipt.get("generated_at"),
        cutoff=cutoff,
        source_type=source_type,
    )
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
        fetched = _instant(ref.get("fetched_at"), f"{source_type} receipt fetched_at ({source_id})")
        _guard_source_pit(observed=observed, fetched=fetched, cutoff=cutoff)
        if _instant(artifact_refs[source_id].get("observed_at"), f"{source_type} artifact observed_at ({source_id})") != observed:
            raise ThemeDiscoveryMergeError(f"{source_type} artifact observation does not match the receipt: {source_id}")
        if mode == "live_authorized":
            raw_ref = ref.get("raw_receipt_ref")
            if not isinstance(raw_ref, str) or not ref.get("raw_receipt_gitignored"):
                raise ThemeDiscoveryMergeError(f"live {source_type} receipt is missing a gitignored raw receipt")
            raw_path = _raw_receipt_path(raw_ref)
            if not raw_path.is_file() or not web._gitignored(raw_path):
                raise ThemeDiscoveryMergeError(f"live {source_type} raw receipt is not gitignored")
            if raw_path.name != f"{source_id.split(':', 1)[1]}.json" or raw_path.parent.name != expected_decision_date:
                raise ThemeDiscoveryMergeError(f"live {source_type} raw receipt path is not bound to its source ID and decision date: {source_id}")
            try:
                raw_payload = web._read_json(raw_path)
            except web.WebThemeDiscoveryError as exc:
                raise ThemeDiscoveryMergeError(f"live {source_type} raw receipt is unreadable") from exc
            _guard_raw_content_digest(
                raw_payload=raw_payload, expected_sha256=ref.get("content_sha256"),
            )
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
    generated_at = _guard_merge_producer_clock(
        generated_at, cutoff=web._cutoff(expected_decision_date),
    ).isoformat()
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


def _ingest_input(artifact: dict[str, Any]) -> dict[str, Any]:
    """Project a frozen merge artifact back to Knife1's inert input surface."""
    return {
        "source_refs": [
            {
                "source_id": ref["source_id"],
                "source_type": ref["source_type"],
                "observed_at": ref["observed_at"],
            }
            for ref in artifact["source_refs"]
        ],
        "themes": [
            {
                "theme_id": theme["theme_id"],
                "display_name": theme["display_name"],
                "summary": theme["summary"],
                "status": theme["status"],
                "observed_at": theme["observed_at"],
                "source_ref_ids": list(theme["source_ref_ids"]),
                "members": [
                    {
                        "ticker": member["ticker"],
                        "membership_status": member["membership_status"],
                        "source_ref_ids": list(member["source_ref_ids"]),
                    }
                    for member in theme["members"]
                ],
                "cross_industry_validation_status": theme["cross_industry_validation_status"],
                "market_confirmation_status": theme["market_confirmation_status"],
            }
            for theme in artifact["themes"]
        ],
    }


def validate_merged_packet(
    artifact: dict[str, Any],
    manifest: dict[str, Any],
    *,
    expected_decision_date: str,
    upstream_pairs: dict[str, tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    """Revalidate a frozen Knife3 pair against both exact upstream artifact/receipt pairs."""
    web._decision_date(expected_decision_date)
    _validate_discovery(artifact)
    _schema_validate(SCHEMA_PATH, manifest)
    if artifact["decision_clock"]["expected_decision_date"] != expected_decision_date:
        raise ThemeDiscoveryMergeError("merged artifact decision date does not match capstone clock")
    if manifest["decision_clock"]["expected_decision_date"] != expected_decision_date:
        raise ThemeDiscoveryMergeError("merge manifest decision date does not match capstone clock")

    cutoff = web._cutoff(expected_decision_date)
    _guard_merge_consumer_clock(
        artifact["generated_at"], manifest["generated_at"], cutoff=cutoff,
    )

    ingest_input = _ingest_input(artifact)
    normalized = ingest.normalize_discovery_payload(
        ingest_input,
        expected_decision_date=expected_decision_date,
        generated_at=artifact["generated_at"],
    )
    if normalized != artifact:
        raise ThemeDiscoveryMergeError("merged artifact identity/digest does not match its normalized evidence")

    manifest_refs: dict[str, dict[str, Any]] = {}
    for ref in manifest["source_refs"]:
        source_id = ref["source_id"]
        if source_id in manifest_refs:
            raise ThemeDiscoveryMergeError("merge manifest contains duplicate source identity")
        source_type = ref["source_type"]
        locator = ref["canonical_locator"]
        if web._canonical_locator(locator) != locator:
            raise ThemeDiscoveryMergeError("merge manifest source locator is not canonical")
        _guard_source_identity(source_id=source_id, source_type=source_type, locator=locator)
        observed = _instant(ref["observed_at"], f"manifest source observed_at ({source_id})")
        fetched = _instant(ref["fetched_at"], f"manifest source fetched_at ({source_id})")
        _guard_source_pit(observed=observed, fetched=fetched, cutoff=cutoff)
        raw_ref = ref["raw_receipt_ref"]
        raw_gitignored = ref["raw_receipt_gitignored"]
        if (raw_ref is None) != (raw_gitignored is False):
            raise ThemeDiscoveryMergeError("merge manifest raw receipt binding is inconsistent")
        if raw_ref is not None:
            raw_path = _raw_receipt_path(raw_ref)
            if (
                not raw_path.is_file()
                or not web._gitignored(raw_path)
            ):
                raise ThemeDiscoveryMergeError("merge manifest raw receipt is missing or not gitignored")
            if (
                raw_path.name != f"{source_id.split(':', 1)[1]}.json"
                or raw_path.parent.name != expected_decision_date
            ):
                raise ThemeDiscoveryMergeError(
                    "merge manifest raw receipt path is not bound to its source identity and decision date"
                )
            raw_payload = web._read_json(raw_path)
            _guard_raw_content_digest(
                raw_payload=raw_payload, expected_sha256=ref["content_sha256"],
            )
            for field in ("source_id", "source_type", "canonical_locator"):
                if raw_payload.get(field) != ref[field]:
                    raise ThemeDiscoveryMergeError(f"merge manifest raw source binding mismatch: {field}")
            raw_time_key = "published_at" if source_type == "web" else "created_at"
            if _instant(raw_payload.get(raw_time_key), f"raw {raw_time_key} ({source_id})") != observed:
                raise ThemeDiscoveryMergeError("merge manifest raw observation clock does not match")
        manifest_refs[source_id] = ref

    artifact_refs = {
        ref["source_id"]: {
            "source_id": ref["source_id"],
            "source_type": ref["source_type"],
            "observed_at": ref["observed_at"],
        }
        for ref in artifact["source_refs"]
    }
    manifest_projection = {
        source_id: {
            "source_id": source_id,
            "source_type": ref["source_type"],
            "observed_at": ref["observed_at"],
        }
        for source_id, ref in manifest_refs.items()
    }
    if artifact_refs != manifest_projection:
        raise ThemeDiscoveryMergeError("merge manifest sources do not bind the merged artifact")

    artifact_themes = _guard_unique_manifest_rows(
        artifact["themes"], key="theme_id", label="artifact theme identity",
    )
    manifest_themes = _guard_unique_manifest_rows(
        manifest["themes"], key="theme_id", label="theme identity",
    )
    if set(artifact_themes) != set(manifest_themes):
        raise ThemeDiscoveryMergeError("merge manifest themes do not cover the merged artifact")
    for theme_id, manifest_theme in manifest_themes.items():
        artifact_theme = artifact_themes[theme_id]
        theme_refs = [manifest_refs[ref_id] for ref_id in artifact_theme["source_ref_ids"]]
        if manifest_theme["discovery_sources"] != _corroboration(theme_refs)[0]:
            raise ThemeDiscoveryMergeError("merge manifest theme source tier does not match its evidence")
        artifact_members = _guard_unique_manifest_rows(
            artifact_theme["members"], key="ticker", label="artifact member identity",
        )
        manifest_members = _guard_unique_manifest_rows(
            manifest_theme["members"], key="ticker", label="member identity",
        )
        if set(artifact_members) != set(manifest_members):
            raise ThemeDiscoveryMergeError("merge manifest members do not cover the merged artifact")
        for ticker, manifest_member in manifest_members.items():
            artifact_member = artifact_members[ticker]
            if manifest_member["source_ref_ids"] != artifact_member["source_ref_ids"]:
                raise ThemeDiscoveryMergeError("merge manifest member refs do not bind the merged artifact")
            if set(manifest_member["redundant_source_ref_ids"]) & set(manifest_member["source_ref_ids"]):
                raise ThemeDiscoveryMergeError("merge manifest retained and redundant member refs overlap")
            if not set(manifest_member["redundant_source_ref_ids"]).issubset(manifest_refs):
                raise ThemeDiscoveryMergeError("merge manifest redundant member ref is unknown")
            member_refs = [manifest_refs[ref_id] for ref_id in artifact_member["source_ref_ids"]]
            sources, tier, residual = _corroboration(member_refs)
            _guard_member_evidence_tier(
                residual=residual,
                actual_sources=manifest_member["discovery_sources"],
                expected_sources=sources,
                actual_tier=manifest_member["evidence_tier"],
                expected_tier=tier,
            )

    summary = manifest["summary"]
    members = [member for theme in manifest["themes"] for member in theme["members"]]
    expected_counts = {
        "merged_theme_count": len(manifest["themes"]),
        "dropped_theme_count": len(manifest["drop_ledger"]),
        "both_member_count": sum(member["evidence_tier"] == "both" for member in members),
        "single_member_count": sum(member["evidence_tier"] == "single" for member in members),
        "zero_member_count": sum(member["evidence_tier"] is None for member in members),
        "redundant_member_count": sum(bool(member["redundant_source_ref_ids"]) for member in members),
    }
    _guard_summary_counts(summary=summary, expected_counts=expected_counts)

    if set(upstream_pairs) != {"web", "x"}:
        raise ThemeDiscoveryMergeError("merge upstream anchors must contain exactly web and x pairs")
    web_artifact, web_receipt = upstream_pairs["web"]
    x_artifact, x_receipt = upstream_pairs["x"]
    _verify_receipt(web_artifact, web_receipt, "web", expected_decision_date)
    _verify_receipt(x_artifact, x_receipt, "x", expected_decision_date)
    expected_input_hashes = {
        "web": web._discovery_evidence_hash(web_artifact),
        "x": web._discovery_evidence_hash(x_artifact),
    }
    _guard_input_artifact_hashes(
        manifest["input_artifact_sha256"], expected_input_hashes,
    )
    replayed_artifact, replayed_manifest = merge_web_x_discovery(
        web_artifact=web_artifact,
        web_receipt=web_receipt,
        x_artifact=x_artifact,
        x_receipt=x_receipt,
        expected_decision_date=expected_decision_date,
        generated_at=artifact["generated_at"],
    )
    if replayed_artifact != artifact or replayed_manifest != manifest:
        raise ThemeDiscoveryMergeError("merge packet is not the deterministic projection of its upstream pairs")
    return ingest_input


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
