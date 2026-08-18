# -*- coding: utf-8 -*-
"""US-short §11.4 exclusion_summary — batch-3: privacy-split builder + de-identified public summary + section render.

Design authority: docs/us_short_system_design.md §11.4 (剔除摘要 + 隐私拆分 + hot_excluded 审计) / §11.2 (周报
本周剔除摘要 section) / §11.6 (lifecycle/exclusion 隐私: private 明细 vs tracked 脱敏汇总) / §18.0 P0 (私密路径
guard) / §18.1. Governance authority = the FROZEN presets/us_short_exclusion_summary_governance_20260620.json
(batch-1, design-locked v1): the 8 exclusion categories are read from it (single source).

§11.4 splits the weekly exclusion summary by PRIVACY:
  * PUBLIC (tracked-safe): per-category public-universe exclusion COUNTS + hot_excluded heat and unevaluable
    COUNTS — numbers only, no tickers / holdings / $. The de-identification GATE is the public schema
    (schemas/us_short_exclusion_summary_public.schema.json: additionalProperties:false + integer-only counts),
    exactly mirroring the lifecycle readiness artifact — so write_exclusion_public needs NO §18.0 guard (a
    provably de-identified artifact is what §11.6 lets be tracked).
  * PRIVATE (gitignored): the real-holding exclusion detail (which holdings were excluded, in which category,
    and the hot_excluded holding rows + reasons) — these expose real positions, so write_exclusion_private
    wires the §18.0 P0 private-path guard BEFORE any write, exactly mirroring the lifecycle register persister.

This module is a pure SUMMARY producer: it counts + renders + splits. It NEVER makes an admission / veto
decision, so it structurally cannot rescue a hard-veto / change Pass-1/Pass-2 admission (§11.4 hot_excluded
"绝不救回 hard veto / 不改准入" — a visibility audit only). build_exclusion_summary refuses an UNKNOWN exclusion
category (closed-world against the frozen governance) so a miscategorised / injected reason cannot hide. Pure /
offline: reads the frozen governance preset, builds dicts, formats markdown; no provider / live / DataHub /
network; no A-share crossing.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from engine.us_short_lifecycle_eval import _strict_yyyymmdd  # canonical date gate (single source — same contract as readiness / store)
from engine.us_short_private_paths import reject_nonprivate_output_path

ROOT = Path(__file__).resolve().parent.parent
_GOVERNANCE_PRESET = ROOT / "presets" / "us_short_exclusion_summary_governance_20260620.json"
_PUBLIC_SCHEMA = ROOT / "schemas" / "us_short_exclusion_summary_public.schema.json"
_SCHEMA_VERSION = "1.0.0"

_CACHE: dict = {}


class ExclusionSummaryError(ValueError):
    """Raised when exclusion input / a public summary violates the §11.4 contract (shape, closed-world category,
    de-identification schema, or a cross-field invariant)."""


def _governance() -> dict:
    if "gov" not in _CACHE:
        _CACHE["gov"] = json.loads(_GOVERNANCE_PRESET.read_text(encoding="utf-8"))
    return _CACHE["gov"]


def _public_schema() -> dict:
    if "schema" not in _CACHE:
        _CACHE["schema"] = json.loads(_PUBLIC_SCHEMA.read_text(encoding="utf-8"))
    return _CACHE["schema"]


def _int_not_bool(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _nonblank_str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _categories() -> list:
    return list(_governance()["exclusion_categories"])


_STAGES = ("pass1_eligibility", "pass2_audit_gate", "top15_selection")


def _assert_public(public) -> None:
    """De-identification + consistency gate for the PUBLIC summary. Validate against the public schema
    (additionalProperties:false + integer-only counts → no ticker / holding / $ field can be smuggled onto a
    tracked path), then the draft-07-inexpressible cross-field invariants: as_of a strict REAL date; the
    category set EXACTLY the frozen governance set (closed-world + complete — every category present, none
    extra); total_excluded == sum of the per-category counts and stage counts (derived single source, cannot drift).
    Raises ExclusionSummaryError on any violation. A summary from
    build_exclusion_summary always passes."""
    for err in jsonschema.Draft7Validator(_public_schema()).iter_errors(public):
        raise ExclusionSummaryError("public exclusion summary violates the de-identified schema: %s" % err.message)
    # the schema pattern only checks 8 digits — it cannot reject an impossible calendar date like 20260231
    if not _strict_yyyymmdd(public["as_of"]):
        raise ExclusionSummaryError("as_of %r is not a strict real YYYYMMDD" % (public["as_of"],))
    counts = public["category_counts"]
    if set(counts) != set(_categories()):
        # sorted(map(str, ...)) — a hand-built dict can carry a non-string key alongside the frozen strings;
        # sort the diagnostic on stringified keys so the gate raises ExclusionSummaryError, never a raw TypeError
        raise ExclusionSummaryError(
            "category_counts keys %s != the frozen governance category set %s (closed-world + complete)"
            % (sorted(map(str, counts)), sorted(_categories()))
        )
    total = sum(counts.values())  # values are integers (schema-enforced)
    if public["total_excluded"] != total:
        raise ExclusionSummaryError("total_excluded %r != sum(category_counts) %d" % (public["total_excluded"], total))
    stage_counts = public["stage_counts"]
    if set(stage_counts) != set(_STAGES):
        raise ExclusionSummaryError(
            "stage_counts %s != the frozen stage set %s" % (sorted(stage_counts), sorted(_STAGES))
        )
    if public["total_excluded"] != sum(stage_counts.values()):
        raise ExclusionSummaryError("total_excluded != sum(stage_counts)")


def _public_count(entry, category) -> int:
    """Strict per-category public-universe count: the category entry must be a dict carrying a NON-NEGATIVE int
    public_count (bool / float / numeric-string / negative all refused — a miscount must fail closed, never
    silently de-identify into a tracked number)."""
    if not isinstance(entry, dict):
        raise ExclusionSummaryError("category %r entry must be a dict, got %r" % (category, type(entry).__name__))
    pc = entry.get("public_count")
    if not (_int_not_bool(pc) and pc >= 0):
        raise ExclusionSummaryError("category %r public_count must be a NON-NEGATIVE int, got %r" % (category, pc))
    holdings = entry.get("holdings", [])
    if not isinstance(holdings, list):
        raise ExclusionSummaryError("category %r holdings must be a list, got %r" % (category, type(holdings).__name__))
    return pc


def _validate_private(private) -> None:
    """Fail-closed shape gate for the PRIVATE real-holding detail. The private side is the §11.4 audit trail
    (which real holdings were excluded, and why high-heat names were dropped), so a malformed / null / reason-less
    row must NEVER become official private output (mirrors every other US-short persister refusing a not-clean
    artifact). Requires: a strict REAL ``as_of``; the EXACT frozen category set, each mapping to a list of
    NON-BLANK ticker strings; ``hot_excluded.holdings`` a list of rows that each carry a NON-BLANK ``ticker`` AND a
    NON-BLANK ``reason`` (§11.4 hot_excluded 行 + 各自剔除原因). Rejects None / blank / whitespace / empty-ticker /
    missing-reason / non-list / wrong-shape. Raises ``ExclusionSummaryError``. Used by BOTH
    ``build_exclusion_summary`` (constructed output) and ``write_exclusion_private`` (direct payload) before any
    write side effect — the single private-detail contract (no second gate to drift)."""
    if not isinstance(private, dict):
        raise ExclusionSummaryError("private detail must be a dict")
    as_of = private.get("as_of")
    if not (isinstance(as_of, str) and _strict_yyyymmdd(as_of)):
        raise ExclusionSummaryError("private detail as_of must be a strict real YYYYMMDD, got %r" % (as_of,))
    cats = private.get("categories")
    if not isinstance(cats, dict) or set(cats) != set(_categories()):
        # sorted(map(str, ...)) — a caller-supplied dict may carry mixed-type keys (frozen strings + a non-string
        # sibling); sorting them raw would raise TypeError instead of the sanctioned ExclusionSummaryError
        raise ExclusionSummaryError(
            "private detail categories must be a dict over the EXACT frozen category set %s, got keys %s"
            % (sorted(_categories()), sorted(map(str, cats)) if isinstance(cats, dict) else type(cats).__name__)
        )
    for cat, holdings in cats.items():
        if not isinstance(holdings, list) or not all(_nonblank_str(h) for h in holdings):
            raise ExclusionSummaryError(
                "private detail category %r holdings must be a list of NON-BLANK ticker strings, got %r" % (cat, holdings)
            )
    hot = private.get("hot_excluded")
    if not isinstance(hot, dict):
        raise ExclusionSummaryError("private detail hot_excluded must be a dict")
    rows = hot.get("holdings")
    if not isinstance(rows, list):
        raise ExclusionSummaryError("private detail hot_excluded.holdings must be a list, got %r" % (type(rows).__name__,))
    for row in rows:
        if not (isinstance(row, dict) and _nonblank_str(row.get("ticker")) and _nonblank_str(row.get("reason"))):
            raise ExclusionSummaryError(
                "private detail hot_excluded row must be a dict carrying a NON-BLANK ticker AND a NON-BLANK reason "
                "(§11.4 行 + 各自剔除原因), got %r" % (row,)
            )


def build_exclusion_summary(exclusion_data) -> dict:
    """Split weekly exclusion data into a de-identified PUBLIC summary + a real-holding PRIVATE detail (§11.4).

    ``exclusion_data`` = ``{"as_of": "YYYYMMDD", "categories": {<frozen category>: {"public_count": int,
    "holdings": [<ticker>, ...]}, ...}, "hot_excluded": {"public_heat_count": int, "holdings": [...]}}``. A
    category present in ``categories`` MUST be one of the frozen governance categories (UNKNOWN → refused,
    closed-world) and carry a non-negative int ``public_count``; an omitted category counts 0 (the public
    summary always shows the full 8-category classification). ``holdings`` (real positions excluded) is private
    detail.

    Returns ``{"public": <de-identified summary, schema-validated>, "private": <real-holding detail>}``. The
    public summary is de-identified BY CONSTRUCTION (only counts) and self-checked via ``_assert_public``; the
    private detail carries the holdings and must be written only via ``write_exclusion_private`` (§18.0 guard).
    Raises ``ExclusionSummaryError`` on malformed input or an unknown category.
    """
    if not isinstance(exclusion_data, dict):
        raise ExclusionSummaryError("exclusion_data must be a dict")
    as_of = exclusion_data.get("as_of")
    if not (isinstance(as_of, str) and _strict_yyyymmdd(as_of)):
        raise ExclusionSummaryError("exclusion_data['as_of'] must be a strict real YYYYMMDD, got %r" % (as_of,))
    categories = exclusion_data.get("categories", {})
    if not isinstance(categories, dict):
        raise ExclusionSummaryError("exclusion_data['categories'] must be a dict")
    allowed = set(_categories())
    unknown = [c for c in categories if c not in allowed]
    if unknown:
        # sorted(map(str, ...)) — input keys may be mixed-type; sort stringified so an injected non-string key
        # still fails closed with ExclusionSummaryError rather than a raw TypeError from the diagnostic
        raise ExclusionSummaryError(
            "unknown exclusion category(ies) %s — not in the frozen governance set %s (closed-world: a "
            "miscategorised / injected reason must fail closed)" % (sorted(map(str, unknown)), sorted(allowed))
        )

    # a category PRESENT in the input must carry a valid public_count; an OMITTED category counts 0 (the public
    # summary always shows the full 8-category classification, zeros explicit)
    category_counts = {cat: (_public_count(categories[cat], cat) if cat in categories else 0) for cat in _categories()}
    stage_counts = exclusion_data.get("stage_counts")
    if not (isinstance(stage_counts, dict) and set(stage_counts) == set(_STAGES)
            and all(_int_not_bool(value) and value >= 0 for value in stage_counts.values())):
        raise ExclusionSummaryError("exclusion_data['stage_counts'] 须明确包含三阶段非负整数")
    recall_count = exclusion_data.get("catalyst_recall_rejected_count", 0)
    if not (_int_not_bool(recall_count) and recall_count >= 0):
        raise ExclusionSummaryError(
            "catalyst_recall_rejected_count must be a NON-NEGATIVE int, got %r" % (recall_count,))
    private_categories = {
        cat: list((categories[cat].get("holdings", []) if cat in categories else []) or [])
        for cat in _categories()
    }

    hot = exclusion_data.get("hot_excluded", {})
    if not isinstance(hot, dict):
        raise ExclusionSummaryError("exclusion_data['hot_excluded'] must be a dict")
    heat_count = hot.get("public_heat_count", 0)
    if not (_int_not_bool(heat_count) and heat_count >= 0):
        raise ExclusionSummaryError("hot_excluded.public_heat_count must be a NON-NEGATIVE int, got %r" % (heat_count,))
    unevaluable_count = hot.get("unevaluable_count", 0)
    if not (_int_not_bool(unevaluable_count) and unevaluable_count >= 0):
        raise ExclusionSummaryError(
            "hot_excluded.unevaluable_count must be a NON-NEGATIVE int, got %r" % (unevaluable_count,))
    hot_holdings = hot.get("holdings", [])
    if not isinstance(hot_holdings, list):
        raise ExclusionSummaryError("hot_excluded.holdings must be a list, got %r" % (type(hot_holdings).__name__,))

    public = {
        "schema_name": "us_short_exclusion_summary_public",
        "schema_version": _SCHEMA_VERSION,
        "as_of": as_of,
        "category_counts": category_counts,
        "stage_counts": dict(stage_counts),
        "total_excluded": sum(category_counts.values()),
        "catalyst_recall_rejected_count": recall_count,
        "hot_excluded_public_heat_count": heat_count,
        "hot_excluded_unevaluable_count": unevaluable_count,
    }
    _assert_public(public)
    private = {
        "as_of": as_of,
        "categories": private_categories,          # {category: [real-holding tickers excluded]}
        "hot_excluded": {"holdings": list(hot_holdings)},  # real-holding hot-excluded rows + reasons
    }
    _validate_private(private)  # the constructed audit trail must itself be well-formed (rejects [None] / blank-ticker / reason-less rows that slipped through as a list)
    return {"public": public, "private": private}


def render_exclusion_section(public) -> list:
    """Render the §11.2 weekly_report 本周剔除摘要 section body from a de-identified PUBLIC summary.

    Returns a list of NON-BLANK markdown lines (so the weekly_report renderer's section-content invariant holds
    even for a zero-exclusion week). ``_assert_public`` runs first — the section never renders an unvalidated /
    re-identifying dict. De-identified output only (counts, no tickers)."""
    _assert_public(public)
    counts = public["category_counts"]
    lines = [
        "本周剔除（按实际阶段合计）%d只：" % public["total_excluded"],
        "pass1_eligibility=%d / pass2_audit_gate=%d / top15_selection=%d；" % (
            public["stage_counts"]["pass1_eligibility"],
            public["stage_counts"]["pass2_audit_gate"],
            public["stage_counts"]["top15_selection"],
        ),
    ]
    for cat in _categories():  # frozen order (single source), all 8 shown (zeros explicit — honest classification)
        lines.append("- %s：%d" % (cat, counts[cat]))
    lines.append(
        "高热度被剔除（hot_excluded，仅审计·绝不救回 hard veto / 不改准入）：%d 只（公开 universe 计数）；"
        "缺同轮主题热度、未能评估：%d 只（喂 §13 复审）。"
        % (public["hot_excluded_public_heat_count"], public["hot_excluded_unevaluable_count"])
    )
    lines.append(
        "催化召回未通过地板：%d只（独立审计，可能与Pass1重合，不计入上述合计）"
        % public["catalyst_recall_rejected_count"]
    )
    return lines


def write_exclusion_public(public, out_path):
    """Write the TRACKED de-identified public exclusion summary as JSON. Returns the written ``Path``.

    The public schema IS the de-identification gate: ``_assert_public`` validates the dict (no ticker / holding /
    $ field via additionalProperties:false + integer-only counts, + the cross-field invariants) BEFORE any
    write, so a malformed / re-identifying dict is refused before it can land on a tracked path. No §18.0
    private-path guard is needed (mirrors the lifecycle readiness artifact — a provably de-identified summary is
    exactly what §11.6 lets be tracked)."""
    _assert_public(public)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(public, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def write_exclusion_private(private, out_path):
    """Write the PRIVATE real-holding exclusion detail as JSON to a gitignored private path. Returns the Path.

    The detail carries real-holding tickers (which positions were excluded), so the §18.0 P0 fail-closed
    private-path guard runs BEFORE any write — a relative / non-gitignored in-repo destination is refused
    (``PrivatePathError``), exactly mirroring the lifecycle register persister. The private-detail SHAPE gate
    (``_validate_private``) then runs before any write too, so a malformed direct payload (impossible as_of,
    wrong category set, non-list / reason-less hot rows, blank tickers) is refused before it can become an
    official private artifact — never persist a malformed audit trail (mirrors the store refusing a not-clean
    register). Pass an in-repo gitignored path (e.g. ``state/us_short/runs_private/...``) or an external absolute path."""
    reject_nonprivate_output_path(out_path)  # §18.0 P0 guard — before any write / side effect
    _validate_private(private)               # private-detail shape gate — before any write / side effect
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(private, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return out_path
