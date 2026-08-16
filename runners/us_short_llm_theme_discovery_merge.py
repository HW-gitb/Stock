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
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery as ingest
from engine.us_short_schema_formats import FORMAT_CHECKER

ROOT = web.ROOT
SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery_merge.schema.json"
PROVIDER_SAMPLES_ROOT = ROOT / "provider_samples"
_URL_TEXT_RE = re.compile(r"https?://[^\s<>()]+", re.I)
# User decision 2026-07-30 (K3-R105 a): only a GENUINE trailing boilerplate block may swallow the
# text after it.  `_safe_text` collapses every stored field to one line, so the old single pattern's
# `.*$` meant "from this word to the end of the field" for every marker — one mid-sentence
# `Read more:` hid every ticker behind it and cost real members their evidence.
# A legal notice really does terminate the content, so it still eats its tail — but only when it
# STARTS a segment.  `The disclaimer in the 10-K notes AAPL supply risk` is ordinary prose, not a
# trailing notice, and blanking the rest of that sentence would deny a legitimately named ticker.
_BOILERPLATE_NOTICE_TAIL_RE = re.compile(
    r"(?:^|(?<=[.!?;]))\s*(?:copyright|all rights reserved|disclaimer)\b.*$",
    re.I | re.M,
)
# A call-to-action or attribution label is a PHRASE, not a terminator: strip the label itself (plus
# its punctuation) and keep whatever the snippet actually says around it.  The trailing `\b` is
# load-bearing — without it `source` eats the head of `SOURCES` and leaves `S` standing as its own
# token, which then reads as a bare ticker the document never wrote.
_BOILERPLATE_LABEL_RE = re.compile(
    # `[^\S\n]` not `\s`: the label must never eat the newline that keeps the title and the content
    # separate fields, or a title-ending label would splice the two together.
    r"(?:^|[^\S\n])(?:subscribe|follow us|read more|source)\b[^\S\n]*[:：]?",
    re.I,
)


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
    "_verify_provider_response_ref",
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
) -> datetime:
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
    return artifact_generated


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


def _verify_provider_response_ref(
    ref: dict[str, Any], *, expected_decision_date: str, cutoff: datetime,
    upstream_generated_at: datetime,
) -> int:
    response_index = ref.get("response_index")
    response_sha256 = ref.get("response_sha256")
    if not isinstance(response_index, int) or response_index < 0 or not isinstance(response_sha256, str):
        raise ThemeDiscoveryMergeError("X provider response reference is malformed")
    raw_ref = ref.get("raw_receipt_ref")
    if not isinstance(raw_ref, str):
        raise ThemeDiscoveryMergeError("X provider raw response path is malformed")
    lexical = PurePosixPath(raw_ref)
    if (
        Path(raw_ref).is_absolute()
        or lexical.is_absolute()
        or ".." in lexical.parts
        or lexical.as_posix() != raw_ref
    ):
        raise ThemeDiscoveryMergeError("X provider raw response must stay under provider_samples")
    raw_path = (ROOT / raw_ref).resolve()
    if not raw_path.is_relative_to(PROVIDER_SAMPLES_ROOT.resolve()):
        raise ThemeDiscoveryMergeError("X provider raw response must stay under provider_samples")
    if not raw_path.is_file() or not web._gitignored(raw_path) or ref.get("raw_receipt_gitignored") is not True:
        raise ThemeDiscoveryMergeError("X provider raw response is missing or not gitignored")
    if (
        raw_path.name != f"xai_{response_sha256}.json"
        or raw_path.parent.name != expected_decision_date
        or raw_path.parent.parent.name != "provider_responses"
    ):
        raise ThemeDiscoveryMergeError("X provider raw response path is not digest/date bound")
    try:
        raw_payload = web._read_json(raw_path)
    except web.WebThemeDiscoveryError as exc:
        raise ThemeDiscoveryMergeError("X provider raw response is unreadable") from exc
    if not isinstance(raw_payload, dict):
        raise ThemeDiscoveryMergeError("X provider raw response shape is invalid")
    response = raw_payload.get("response")
    if raw_payload.get("provider") != "xai" or not isinstance(response, dict):
        raise ThemeDiscoveryMergeError("X provider raw response shape is invalid")
    if hashlib.sha256(web._canonical_json(response)).hexdigest() != response_sha256:
        raise ThemeDiscoveryMergeError("X provider raw response digest does not match")
    frozen_fetched = _instant(raw_payload.get("fetched_at"), "X provider raw fetched_at")
    receipt_fetched = _instant(ref.get("fetched_at"), "X provider response ref fetched_at")
    if (
        frozen_fetched != receipt_fetched
        or frozen_fetched < web._decision_week_start(expected_decision_date)
        or frozen_fetched > upstream_generated_at
        or frozen_fetched >= cutoff
    ):
        raise ThemeDiscoveryMergeError("X provider raw response clock is not bound or PIT-safe")
    return response_index


def _document_identity(ref: dict[str, str]) -> str:
    """Cross-lane identity of ONE document, for the independent-evidence verdict only.

    Falls back to the content-hash suffix; an X post locator instead yields the post identity, so
    the same tweet cited by both lanes in different spellings can never mint the `both` tier.
    """
    locator = ref.get("canonical_locator")
    if not isinstance(locator, str):
        # Unreachable defence: both call paths reject a missing or non-canonical `canonical_locator`
        # before corroboration runs.  It returns a shared constant rather than raising because a
        # raise on the merge path would be a new batch-kill vector; note that this constant does NOT
        # by itself prevent a `both` verdict (one unidentified document still differs from an
        # identified one), so it is a crash guard, not a security property.
        return "unidentified_document"
    status_id = xfetch._x_post_document_identity(locator)
    if status_id is not None:
        return f"x_status:{status_id}"
    return ref["source_id"].split(":", 1)[1]


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

    A raw hash suffix is not enough for X posts: the X lane deliberately persists the PROVIDER
    annotation spelling (`/i/status/<id>`), while a web sighting of the same post carries the handle
    spelling, so two spellings of ONE tweet hash differently and would read as corroboration.  The
    lane already owns a provable post identity for exactly this question (K3-R79/K3-R90/K3-R94), so
    it is reused here.  Only what is PROVABLY one document is collapsed.  For a NON-X document the
    open heuristic mirrors (`www.`/AMP, `http` vs `https`, tracking params) stay deliberately
    uncollapsed — that judgement is unchanged; the X post rule is not a heuristic, so it collapses
    those spellings for X locators only.
    """
    by_lane = {kind: {_document_identity(ref) for ref in bound_refs if ref["source_type"] == kind}
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
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    try:
        if source_type == "web":
            web._validate_schema(receipt)
        else:
            xfetch._validate_schema(receipt)
    except Exception as exc:
        raise ThemeDiscoveryMergeError(f"{source_type} receipt schema is invalid") from exc
    if source_type == "web" and receipt.get("schema_version") == "1.2.0":
        # Kept separate from the schema door: a ledger/consistency failure and a shape
        # failure need different diagnoses, and reporting both as "schema is invalid"
        # sent a reviewer down the wrong path once already.
        try:
            web._validate_member_binding_ledger(receipt, artifact)
        except Exception as exc:
            raise ThemeDiscoveryMergeError("web receipt member binding ledger is invalid") from exc
    if receipt.get("decision_clock", {}).get("expected_decision_date") != expected_decision_date:
        raise ThemeDiscoveryMergeError(f"{source_type} receipt decision date does not match merge clock")
    if artifact.get("decision_clock", {}).get("expected_decision_date") != expected_decision_date:
        raise ThemeDiscoveryMergeError(f"{source_type} artifact decision date does not match merge clock")
    contract = receipt.get("fetch_contract", {})
    mode = contract.get("execution_mode")
    if source_type == "web":
        regroup_chunk_counts = contract.get("regroup_chunk_counts")
        if (
            isinstance(regroup_chunk_counts, dict)
            and regroup_chunk_counts.get("failed", 0) > 0
        ):
            raise ThemeDiscoveryMergeError(
                "web receipt has incomplete regroup chunks"
            )
    expected_live = mode == "live_authorized"
    if contract.get("network_access_performed") is not expected_live or contract.get("provider_calls_performed") is not expected_live:
        raise ThemeDiscoveryMergeError(f"{source_type} receipt execution evidence is inconsistent with execution_mode")
    network_calls = contract.get("network_call_count")
    provider_calls = contract.get("provider_call_count")
    if not isinstance(network_calls, int) or not isinstance(provider_calls, int) or network_calls < 0 or provider_calls < 0:
        raise ThemeDiscoveryMergeError(f"{source_type} receipt call counts are malformed")
    expected_transport_providers = {"tavily", "deepseek"} if source_type == "web" else {"xai"}
    transport_counts = contract.get("transport_response_counts")
    if (
        not isinstance(transport_counts, dict)
        or set(transport_counts) != expected_transport_providers
        or not all(isinstance(count, int) and count >= 0 for count in transport_counts.values())
    ):
        raise ThemeDiscoveryMergeError(f"{source_type} receipt transport evidence is malformed")
    completed_transport_responses = sum(transport_counts.values())
    if network_calls != completed_transport_responses or provider_calls != completed_transport_responses:
        raise ThemeDiscoveryMergeError(f"{source_type} receipt call counts are not transport-derived")
    if expected_live and (network_calls <= 0 or provider_calls <= 0):
        raise ThemeDiscoveryMergeError(f"{source_type} live receipt has no observed provider/network calls")
    if not expected_live and (network_calls or provider_calls):
        raise ThemeDiscoveryMergeError(f"{source_type} offline receipt claims provider/network calls")
    expected = web._discovery_evidence_hash(artifact)
    if receipt.get("discovery_artifact_sha256") != expected:
        raise ThemeDiscoveryMergeError(f"{source_type} discovery artifact digest does not match receipt")
    actual_types: dict[str, str] = {}
    raw_payloads: dict[str, dict[str, Any]] = {}
    artifact_refs = {ref.get("source_id"): ref for ref in artifact.get("source_refs", []) if isinstance(ref, dict)}
    artifact_types = {source_id: ref.get("source_type") for source_id, ref in artifact_refs.items()}
    cutoff = web._cutoff(expected_decision_date)
    upstream_generated_at = _guard_upstream_generated_clocks(
        artifact.get("generated_at"),
        receipt.get("generated_at"),
        cutoff=cutoff,
        source_type=source_type,
    )
    has_provider_refs = "provider_response_refs" in receipt
    has_provider_annotations = "provider_annotation_urls" in receipt
    if source_type == "x" and has_provider_refs != has_provider_annotations:
        raise ThemeDiscoveryMergeError("X provider evidence fields must be present together")
    provider_response_refs = receipt.get("provider_response_refs")
    if source_type == "x" and has_provider_refs:
        verified_response_indexes = [
            _verify_provider_response_ref(
                ref, expected_decision_date=expected_decision_date, cutoff=cutoff,
                upstream_generated_at=upstream_generated_at,
            )
            for ref in provider_response_refs if isinstance(ref, dict)
        ]
        response_drop_indexes = [
            row.get("provider_response_index")
            for row in receipt.get("drop_ledger", [])
            if isinstance(row, dict) and row.get("reason") in xfetch.PROVIDER_RESPONSE_DROP_REASONS
        ]
        accounted_indexes = verified_response_indexes + response_drop_indexes
        if (
            len(verified_response_indexes) != len(provider_response_refs)
            or any(not isinstance(index, int) for index in accounted_indexes)
            or len(set(accounted_indexes)) != len(accounted_indexes)
            or set(accounted_indexes) != set(range(transport_counts["xai"]))
        ):
            raise ThemeDiscoveryMergeError("X provider responses are not completely accounted")
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
        raw_ref = ref.get("raw_receipt_ref")
        raw_available = isinstance(raw_ref, str) and bool(ref.get("raw_receipt_gitignored"))
        if mode == "live_authorized" and not raw_available:
            raise ThemeDiscoveryMergeError(f"live {source_type} receipt is missing a gitignored raw receipt")
        if raw_available:
            if not isinstance(raw_ref, str):
                raise ThemeDiscoveryMergeError(f"{source_type} raw receipt reference is malformed")
            raw_path = _raw_receipt_path(raw_ref)
            if not raw_path.is_file() or not web._gitignored(raw_path):
                raise ThemeDiscoveryMergeError(f"{source_type} raw receipt is not gitignored")
            if raw_path.name != f"{source_id.split(':', 1)[1]}.json" or raw_path.parent.name != expected_decision_date:
                raise ThemeDiscoveryMergeError(f"{source_type} raw receipt path is not bound to its source ID and decision date: {source_id}")
            try:
                raw_payload = web._read_json(raw_path)
            except web.WebThemeDiscoveryError as exc:
                raise ThemeDiscoveryMergeError(f"{source_type} raw receipt is unreadable") from exc
            _guard_raw_content_digest(
                raw_payload=raw_payload, expected_sha256=ref.get("content_sha256"),
            )
            for key in ("source_id", "source_type", "canonical_locator"):
                if raw_payload.get(key) != ref.get(key):
                    raise ThemeDiscoveryMergeError(f"{source_type} raw receipt binding mismatch: {key}")
            raw_time_key = "published_at" if source_type == "web" else "created_at"
            if _instant(raw_payload.get(raw_time_key), f"{source_type} raw {raw_time_key} ({source_id})") != observed:
                raise ThemeDiscoveryMergeError(f"{source_type} raw observation time does not match the receipt: {source_id}")
            raw_payloads[source_id] = raw_payload
        actual_types[source_id] = source_type
    artifact_ids = {ref.get("source_id") for ref in artifact.get("source_refs", [])}
    if artifact_ids != set(actual_types):
        raise ThemeDiscoveryMergeError(f"{source_type} receipt source IDs do not cover artifact refs")
    return actual_types, raw_payloads


def _raw_payload_mentions_ticker(raw_payload: dict[str, Any], ticker: str) -> bool:
    """Count only a standalone ticker/cashtag in frozen title/body evidence.

    URLs and boilerplate lines are deliberately removed before matching: their occurrence is not a
    provider assertion about the company.  Unknown payload shapes or non-canonical tickers never
    corroborate, so ambiguity always demotes rather than upgrades a member.
    """
    from engine.us_short_eligibility_gate import canonical_us_ticker

    canonical = canonical_us_ticker(ticker)
    if canonical is None:
        return False
    text_key = "content" if raw_payload.get("source_type") == "web" else "text"
    fields = [raw_payload.get("title"), raw_payload.get(text_key)]
    if not all(isinstance(value, str) for value in fields):
        return False
    evidence = "\n".join(fields)
    # A stripped URL ends the clause it sat in, so it counts as a segment break for the notice rule
    # below (scraped snippets routinely put the legal notice straight after a link).
    evidence = _URL_TEXT_RE.sub(" . ", evidence)
    evidence = _BOILERPLATE_NOTICE_TAIL_RE.sub("", evidence)
    evidence = _BOILERPLATE_LABEL_RE.sub(" ", evidence)
    return _evidence_mentions_canonical_ticker(evidence, canonical)


def _class_share_evidence_spellings(canonical: str) -> tuple[str, ...]:
    """Return safe textual aliases for an already-declared class-share ticker.

    This is deliberately one-way: a punctuated target such as ``BRK.B`` may match the
    equivalent evidence spellings ``BRK-B`` and ``BRKB``.  A compact target does not
    invent a punctuation split, because that would guess a class share for an otherwise
    valid independent ticker and widen the money-moving evidence gate.
    """
    match = re.fullmatch(r"([A-Z][A-Z0-9]{0,5})[.-]([A-Z]{1,3})", canonical)
    if match is None:
        return (canonical,)
    root, share_class = match.groups()
    return (f"{root}.{share_class}", f"{root}-{share_class}", f"{root}{share_class}")


def _evidence_mentions_canonical_ticker(evidence: str, canonical: str) -> bool:
    """A bare ticker is upper-case; a dollar-prefixed cashtag is explicitly case-insensitive."""
    boundary = r"[A-Za-z0-9]"
    spellings = "|".join(re.escape(value) for value in _class_share_evidence_spellings(canonical))
    bare = rf"(?<!{boundary})(?:{spellings})(?!{boundary})"
    cashtag = rf"(?<!{boundary})\$(?:{spellings})(?!{boundary})"
    return re.search(bare, evidence) is not None or re.search(cashtag, evidence, re.I) is not None


def _sorted_merge_drops(drops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Produce a complete deterministic order for the frozen merge drop ledger."""
    return sorted(drops, key=lambda row: (row["stage"], row["theme_id"], row["reason"], row["detail"]))


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
    web_types, web_raw_payloads = _verify_receipt(
        web_artifact, web_receipt, "web", expected_decision_date,
    )
    x_types, x_raw_payloads = _verify_receipt(
        x_artifact, x_receipt, "x", expected_decision_date,
    )
    raw_payloads_by_id = {**web_raw_payloads, **x_raw_payloads}
    refs_by_id: dict[str, dict[str, str]] = {}
    receipt_refs_by_id: dict[str, dict[str, Any]] = {}
    for receipt in (web_receipt, x_receipt):
        for ref in receipt.get("source_refs", []):
            receipt_refs_by_id[ref["source_id"]] = dict(ref)
    for artifact, source_type in ((web_artifact, "web"), (x_artifact, "x")):
        for ref in artifact["source_refs"]:
            source_id = ref["source_id"]
            prior = refs_by_id.get(source_id)
            candidate = {"source_id": source_id, "source_type": source_type, "observed_at": ref["observed_at"],
                         # Carried for `_document_identity` only, so the builder and
                         # `validate_merged_packet` (whose manifest refs always carry it) decide
                         # corroboration from the SAME identity; `project_knife1_source_refs`
                         # whitelists its keys, so this never reaches the frozen artifact.
                         "canonical_locator": receipt_refs_by_id[source_id]["canonical_locator"],
                         "evidence_attestation": receipt_refs_by_id[source_id].get("evidence_attestation", "provider_attested")}
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
                    "source_ref_ids": [], "members": {}, "semantic_assertions": [],
                    "cross_industry_validation_status": "not_run", "market_confirmation_status": "not_run",
                }
            target = merged[key]
            target["source_ref_ids"] = sorted(set(target["source_ref_ids"]) | set(theme["source_ref_ids"]))
            # Compare INSTANTS, not strings: a lexical max over mixed UTC offsets picks the earlier
            # real instant, which then predates a cited source and kills the week.
            target["observed_at"] = max(
                target["observed_at"], theme["observed_at"],
                key=lambda value: web._parse_dt(value, field="theme.observed_at"),
            )
            if isinstance(theme.get("semantic_assertions"), list):
                target["semantic_assertions"].extend(
                    json.loads(json.dumps(theme["semantic_assertions"], ensure_ascii=False))
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
    merge_drops: list[dict[str, Any]] = []
    for theme in merged.values():
        unbound_tickers: list[str] = []
        for ticker, row in theme["members"].items():
            bound = [refs_by_id[ref_id] for ref_id in row["source_ref_ids"] if ref_id in refs_by_id]
            redundant = _corroboration(bound)[2]
            if redundant:
                row["source_ref_ids"] = sorted(set(row["source_ref_ids"]) - set(redundant))
                redundant_by_member[(theme["theme_id"], canonical_us_ticker(ticker) or ticker)] = redundant
            retained_bound = [refs_by_id[ref_id] for ref_id in row["source_ref_ids"] if ref_id in refs_by_id]
            retained_tier = _corroboration(retained_bound)[1]
            if retained_tier is None:
                continue
            # User decision 2026-07-30 (K3-R105 b): the frozen text must name the ticker for EVERY
            # paying tier, not only for `both`.  A `single` member is 2.0 points — 40% of the cap —
            # and used to reach the score with no content binding at all, so a model could mint it
            # by naming a ticker no cited document ever mentions.
            verified = [
                ref["source_id"] for ref in retained_bound
                if (raw_payload := raw_payloads_by_id.get(ref["source_id"])) is not None
                and _raw_payload_mentions_ticker(raw_payload, ticker)
            ]
            verified_bound = [refs_by_id[ref_id] for ref_id in verified]
            _, verified_tier, _ = _corroboration(verified_bound)
            if verified_tier == retained_tier:
                # Same tier, but refs can still have been pruned here.  A silent prune lowers the
                # theme's `distinct_web_x_source_ref_count`, which is a knife-2 top-8 ranking key,
                # so a theme could lose its slot with nothing in any ledger explaining why.
                pruned = sorted(set(row["source_ref_ids"]) - set(verified))
                if pruned:
                    merge_drops.append({
                        "stage": "theme", "theme_id": theme["theme_id"],
                        "reason": "member_evidence_ref_unbound_pruned",
                        "detail": f"{canonical_us_ticker(ticker) or ticker}:{','.join(pruned)}",
                    })
                row["source_ref_ids"] = sorted(verified)
                continue
            prior = row["source_ref_ids"]
            if not verified:
                # No ref survives ticker verification, so this MEMBER has no evidence.  Leaving it
                # with an empty ref list makes the ingest reject the member and the per-theme guard
                # then drops the WHOLE theme — one unverifiable member would destroy its siblings'
                # genuine two-document evidence (§五 red line #4).  Drop the member instead.
                unbound_tickers.append(ticker)
                merge_drops.append({
                    "stage": "theme", "theme_id": theme["theme_id"],
                    "reason": "member_evidence_unbound_ticker_dropped",
                    "detail": f"{canonical_us_ticker(ticker) or ticker}:{','.join(sorted(set(prior)))}",
                })
                continue
            row["source_ref_ids"] = sorted(verified)
            merge_drops.append({
                "stage": "theme", "theme_id": theme["theme_id"],
                "reason": "member_evidence_demoted_unbound_ticker",
                "detail": f"{canonical_us_ticker(ticker) or ticker}:{','.join(sorted(set(prior) - set(verified)))}",
            })
        for ticker in unbound_tickers:
            theme["members"].pop(ticker, None)
    # Member/source pruning can invalidate a semantic assertion even when the remaining
    # discovery members are still usable.  Re-check each assertion at this boundary so an
    # invalid lane assertion is recorded and removed, never silently left as a passing claim.
    ref_types = {source_id: ref["source_type"] for source_id, ref in refs_by_id.items()}
    ref_times = {
        source_id: _instant(ref["observed_at"], f"source_refs[{source_id}].observed_at")
        for source_id, ref in refs_by_id.items()
    }
    for theme in merged.values():
        assertions = theme.get("semantic_assertions")
        if not isinstance(assertions, list) or not assertions:
            continue
        valid_assertions: list[dict[str, Any]] = []
        member_ref_ids = {
            member["ticker"]: set(member["source_ref_ids"])
            for member in theme["members"].values()
        }
        for assertion_index, assertion in enumerate(assertions):
            try:
                assertion_for_validation = assertion
                links = assertion.get("member_links") if isinstance(assertion, dict) else None
                if isinstance(links, list):
                    retained_links = []
                    pruned_tickers = []
                    for link in links:
                        if (
                            isinstance(link, dict)
                            and isinstance(link.get("ticker"), str)
                            and isinstance(link.get("source_ref_ids"), list)
                            and (
                                link["ticker"] not in member_ref_ids
                                or not set(link["source_ref_ids"]).issubset(
                                    member_ref_ids[link["ticker"]]
                                )
                            )
                        ):
                            pruned_tickers.append(link["ticker"])
                            continue
                        retained_links.append(link)
                    if pruned_tickers:
                        assertion_for_validation = dict(assertion)
                        assertion_for_validation["member_links"] = retained_links
                        merge_drops.append({
                            "stage": "theme", "theme_id": theme["theme_id"],
                            "reason": "semantic_assertion_member_link_pruned",
                            "detail": (
                                f"assertion[{assertion_index}]:"
                                f"{','.join(sorted(set(pruned_tickers)))}"
                            ),
                        })
                valid_assertions.extend(ingest.normalize_semantic_assertions(
                    [assertion_for_validation],
                    theme_ref_ids=set(theme["source_ref_ids"]),
                    member_ref_ids=member_ref_ids,
                    ref_types=ref_types,
                    ref_times=ref_times,
                    theme_observed_at=_instant(theme["observed_at"], "theme.observed_at"),
                    field=f"theme[{theme['theme_id']}].semantic_assertions[{assertion_index}]",
                ))
            except Exception as exc:
                merge_drops.append({
                    "stage": "theme", "theme_id": theme["theme_id"],
                    "reason": "semantic_assertion_invalid_after_merge_prune",
                    "detail": f"assertion[{assertion_index}]:{type(exc).__name__}",
                })
        theme["semantic_assertions"] = valid_assertions
        if not valid_assertions:
            merge_drops.append({
                "stage": "theme", "theme_id": theme["theme_id"],
                "reason": "theme_has_no_valid_semantic_assertion",
                "detail": "all_assertions_invalid_after_merge_prune",
            })
            theme["_drop_after_semantic_prune"] = True
    semantic_mode = any(
        isinstance(theme.get("semantic_assertions"), list)
        and bool(theme["semantic_assertions"])
        for theme in merged.values()
    )
    if semantic_mode:
        for theme in merged.values():
            if theme.get("_drop_after_semantic_prune") or theme.get("semantic_assertions"):
                continue
            merge_drops.append({
                "stage": "theme", "theme_id": theme["theme_id"],
                "reason": "missing_semantic_assertions",
                "detail": "theme omitted by mixed semantic/non-semantic merge",
            })
            theme["_drop_after_semantic_prune"] = True
    # Attestation is merge-manifest metadata, not a Knife-1 discovery input field.  Letting it
    # reach the normalizer changes `input_sha256`, while the consumer correctly reconstructs
    # only Knife-1's three source fields; keep those two representations deliberately separate.
    discovery_input = {
        "source_refs": ingest.project_knife1_source_refs(list(refs_by_id.values())),
        "themes": [],
    }
    for theme in merged.values():
        if theme.get("_drop_after_semantic_prune"):
            continue
        theme = dict(theme)
        theme.pop("_drop_after_semantic_prune", None)
        theme["members"] = list(theme["members"].values())
        if not theme["semantic_assertions"]:
            theme.pop("semantic_assertions")
        discovery_input["themes"].append(theme)
    from runners.us_short_llm_theme_discovery import normalize_discovery_payload
    # §五 red-line #4 extends past the fetch layer: one theme the ingest cannot normalize must be
    # dropped with a ledger row, not allowed to abort the whole week's merge.
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
            model_transcribed_x_evidence = any(
                ref["source_type"] == "x" and ref.get("evidence_attestation") == "model_transcribed"
                for ref in bound
            )
            row = {"ticker": member["ticker"], "discovery_sources": sources, "evidence_tier": tier,
                   "source_ref_ids": member["source_ref_ids"],
                   "redundant_source_ref_ids": redundant_by_member.get((theme["theme_id"], member["ticker"]), []),
                   "model_transcribed_x_evidence": model_transcribed_x_evidence}
            member_rows.append({"theme_id": theme["theme_id"], **row})
            theme_member_rows.append(row)
        theme_rows.append({
            "theme_id": theme["theme_id"], "discovery_sources": theme_sources,
            "semantic_assertion_origins": [
                {
                    "origin_source_type": assertion["origin_source_type"],
                    "origin_scope_type": assertion["origin_scope_type"],
                    "origin_scope_index": assertion["origin_scope_index"],
                }
                for assertion in theme.get("semantic_assertions", [])
            ],
            "members": theme_member_rows,
        })
    manifest = {
        "schema_name": "us_short_llm_theme_discovery_merge", "schema_version": "1.0.0", "generated_at": generated_at,
        "decision_clock": {"expected_decision_date": expected_decision_date, "cutoff_policy": "before_decision_open_et", "pit_enforced": True},
        "merge_contract": {"producer_kind": "web_x_discovery_merge", "execution_mode": "offline_local_receipts", "scoring_eligible": False, "top15_effect_enabled": False, "operation_advice_effect_enabled": False, "dynamic_seats_enabled": False, "theme_probe_enabled": False, "lifecycle_actions_enabled": False},
        "input_artifact_sha256": {"web": web._discovery_evidence_hash(web_artifact), "x": web._discovery_evidence_hash(x_artifact)}, "source_refs": [dict(receipt_refs_by_id[source_id], evidence_attestation=receipt_refs_by_id[source_id].get("evidence_attestation", "provider_attested")) for source_id in sorted(receipt_refs_by_id)], "themes": theme_rows,
        "drop_ledger": _sorted_merge_drops(merge_drops),
        "summary": {"web_theme_count": len(web_artifact["themes"]), "x_theme_count": len(x_artifact["themes"]), "merged_theme_count": len(theme_rows), "dropped_theme_count": sum(row["reason"] in {"theme_rejected_by_ingest", "theme_has_no_valid_semantic_assertion"} for row in merge_drops), "member_evidence_demotion_count": sum(row["reason"] == "member_evidence_demoted_unbound_ticker" for row in merge_drops), "both_member_count": sum(row["evidence_tier"] == "both" for row in member_rows), "single_member_count": sum(row["evidence_tier"] == "single" for row in member_rows), "zero_member_count": sum(row["evidence_tier"] is None for row in member_rows), "redundant_member_count": sum(bool(row["redundant_source_ref_ids"]) for row in member_rows), "model_transcribed_x_member_count": sum(row["model_transcribed_x_evidence"] for row in member_rows)},
    }
    _schema_validate(SCHEMA_PATH, manifest)
    return merged_artifact, manifest


def _ingest_input(artifact: dict[str, Any]) -> dict[str, Any]:
    """Project a frozen merge artifact back to Knife1's inert input surface."""
    return {
        "source_refs": ingest.project_knife1_source_refs(artifact["source_refs"]),
        "themes": [
            {
                "theme_id": theme["theme_id"],
                "display_name": theme["display_name"],
                "summary": theme["summary"],
                "status": theme["status"],
                "observed_at": theme["observed_at"],
                "source_ref_ids": list(theme["source_ref_ids"]),
                **({"semantic_assertions": json.loads(json.dumps(theme["semantic_assertions"], ensure_ascii=False))}
                   if isinstance(theme.get("semantic_assertions"), list) else {}),
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
        expected_origins = [
            {
                "origin_source_type": assertion["origin_source_type"],
                "origin_scope_type": assertion["origin_scope_type"],
                "origin_scope_index": assertion["origin_scope_index"],
            }
            for assertion in artifact_theme.get("semantic_assertions", [])
        ]
        if manifest_theme.get("semantic_assertion_origins", []) != expected_origins:
            raise ThemeDiscoveryMergeError("merge manifest semantic assertion origins do not bind the artifact")
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
        # Count THEME drops, exactly as the builder does.  Counting the whole ledger made an
        # ordinary member demotion (a tweet naming a company without its ticker) publish a manifest
        # this validator then refused forever, zeroing the week's soft boost on the immutable slot.
        "dropped_theme_count": sum(
            row.get("reason") in {"theme_rejected_by_ingest", "theme_has_no_valid_semantic_assertion"}
            for row in manifest["drop_ledger"]
        ),
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
