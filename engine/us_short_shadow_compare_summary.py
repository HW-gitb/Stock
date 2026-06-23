# -*- coding: utf-8 -*-
"""US-short §12.2 比较轨 shadow comparison TRACKED de-identified summary — batch-3 (#13/#24 follow-up).

Design authority: docs/us_short_system_design.md §12.2 (存储隐私: 含票名的 shadow 选股/成绩 → private; tracked 只出
脱敏归一化指标, 无票名/无 $) / §11.6 (private 明细 vs tracked 脱敏汇总) / §12 (shadow paper-only, 永不计 ship-gate).
Consumes ``engine.us_short_shadow_compare.build_shadow_comparison`` output.

Builds + writes the TRACKED, de-identified summary of a §12.2 shadow comparison. UNLIKE the PRIVATE comparison
artifact (per-profile TopN selections WITH ticker names → gitignored via engine.us_short_shadow_compare_store,
§11.6), this summary carries ONLY normalized indicators — per shadow profile the selection-set DIVERGENCE COUNTS
(``balanced_only`` / ``shadow_extra`` / ``overlap`` SIZES, no tickers), ``top_n`` / ``pool_size`` /
``selected_count``, and the frozen ship-gate-isolation boundary — NO ticker names, NO $, NO performance — so it is
safe to TRACK. The de-identification GATE is the summary schema itself
(``schemas/us_short_shadow_compare_summary.schema.json``: ``additionalProperties:false`` + integer-only counts +
const track / primary / boundary), so a ticker-bearing / malformed dict is refused before it can land on a tracked
path — that is why NO §18.0 private-path guard is needed here (the §18.0 guard protects PRIVATE outputs; this
artifact is provably de-identified, exactly what §11.6 lets be tracked).

This is the SELECTION-level tracked companion of the private persister. The paper-NAV two-way full-caliber
scorecard (§12.2 双向全口径: 多买亏损票 / 回撤 / 成本 / 现金拖累 / 坏票率) and the anti-self-deception upgrade gate
are later §12.2 cuts. Pure-ish: builds from a comparison (no provider/live), writes a de-identified JSON; no
A-share crossing. Malformed input fails closed.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import jsonschema

from engine.us_short_shadow_compare import validate_shadow_comparison

ROOT = Path(__file__).resolve().parent.parent
_SUMMARY_SCHEMA = ROOT / "schemas" / "us_short_shadow_compare_summary.schema.json"
_SCHEMA_VERSION = "1.0.0"

_CACHE: dict = {}


class ShadowCompareSummaryError(ValueError):
    """Raised when a de-identified shadow-compare summary violates the tracked schema / consistency invariants."""


def _schema() -> dict:
    if "schema" not in _CACHE:
        _CACHE["schema"] = json.loads(_SUMMARY_SCHEMA.read_text(encoding="utf-8"))
    return _CACHE["schema"]


def _strict_yyyymmdd(s) -> bool:
    # inlined (with the isascii() guard — the whole-class DATE-ASCII lesson) so the as_of PIT anchor of the
    # tracked summary is a real calendar date; the schema's 8-digit pattern can't reject 20260231
    if not (isinstance(s, str) and len(s) == 8 and s.isascii() and s.isdigit()):
        return False
    try:
        datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return True
    except ValueError:
        return False


def _assert_summary(summary) -> None:
    """De-identification + consistency gate: validate against the summary schema (additionalProperties:false +
    integer-only counts → no ticker / $ / performance can be smuggled into a tracked artifact), then the
    cross-field invariants draft-07 can't express: a strict REAL ``as_of``; ``selected_count == min(top_n,
    pool_size)``; and per shadow profile ``overlap_count + balanced_only_count == selected_count == overlap_count +
    shadow_extra_count`` (|balanced| == |shadow| == selected_count, so the de-identified counts stay internally
    consistent — a doctored count can't pass). Raises ``ShadowCompareSummaryError``; a summary from
    ``build_shadow_compare_summary`` always passes."""
    for err in jsonschema.Draft7Validator(_schema()).iter_errors(summary):
        raise ShadowCompareSummaryError("summary violates the de-identified schema: %s" % err.message)
    if not _strict_yyyymmdd(summary["as_of"]):
        raise ShadowCompareSummaryError("as_of %r is not a strict real YYYYMMDD" % (summary["as_of"],))
    top_n, pool_size, selected = summary["top_n"], summary["pool_size"], summary["selected_count"]
    if selected != min(top_n, pool_size):
        raise ShadowCompareSummaryError("selected_count %d != min(top_n %d, pool_size %d)" % (selected, top_n, pool_size))
    for name, d in summary["divergence"].items():  # schema already pinned the keys to the frozen shadow profiles
        if d["overlap_count"] + d["balanced_only_count"] != selected:
            raise ShadowCompareSummaryError(
                "divergence[%r]: overlap+balanced_only %d != selected_count %d"
                % (name, d["overlap_count"] + d["balanced_only_count"], selected))
        if d["overlap_count"] + d["shadow_extra_count"] != selected:
            raise ShadowCompareSummaryError(
                "divergence[%r]: overlap+shadow_extra %d != selected_count %d"
                % (name, d["overlap_count"] + d["shadow_extra_count"], selected))


def build_shadow_compare_summary(comparison, *, as_of) -> dict:
    """Build the TRACKED de-identified summary from a §12.2 shadow comparison. ``as_of`` = the decision_date
    (YYYYMMDD). REFUSES a comparison that fails ``validate_shadow_comparison`` (never summarizes an un-validated
    artifact — raises ``ShadowCompareError``). The result is de-identified BY CONSTRUCTION (only counts + the frozen
    boundary, NO tickers) and self-checked against the schema + consistency invariants. Raises
    ``ShadowCompareSummaryError`` on a bad as_of / inconsistent result."""
    validate_shadow_comparison(comparison)  # the private artifact must be §12.2-clean (verifies track/primary/boundary/profiles)
    primary = comparison["primary_profile"]  # == "balanced" (validate_shadow_comparison guaranteed)
    selected = len(comparison["profiles"][primary]["selection"])
    divergence = {
        name: {
            "balanced_only_count": len(vs["balanced_only"]),
            "shadow_extra_count": len(vs["shadow_extra"]),
            "overlap_count": vs["overlap_count"],
        }
        for name, vs in comparison["vs_balanced"].items()  # exactly the frozen shadow profiles (validated)
    }
    summary = {
        "schema_name": "us_short_shadow_compare_summary",
        "schema_version": _SCHEMA_VERSION,
        "as_of": as_of,
        "track": comparison["track"],
        "primary_profile": primary,
        "top_n": comparison["top_n"],
        "pool_size": comparison["pool_size"],
        "selected_count": selected,
        "min_comparison_weeks": comparison["min_comparison_weeks"],
        "divergence": divergence,
        "boundary": dict(comparison["boundary"]),
    }
    _assert_summary(summary)
    return summary


def write_shadow_compare_summary(summary, out_path):
    """Write the TRACKED de-identified summary as JSON. Returns the written ``Path``. The summary schema IS the
    de-identification gate: ``_assert_summary`` validates the dict (no ticker / $ via additionalProperties:false +
    integer-only counts, + consistency) BEFORE any write, so a malformed / ticker-bearing dict is refused before it
    can land on a tracked path. NO §18.0 private-path guard is needed (a provably de-identified artifact is exactly
    what §11.6 lets be tracked)."""
    _assert_summary(summary)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return out_path
