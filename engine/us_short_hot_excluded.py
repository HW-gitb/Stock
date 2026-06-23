# -*- coding: utf-8 -*-
"""US-short §11.4 hot_excluded 审计 — batch-3 (#19): high-theme-heat-but-gate-dropped detector (audit only).

Design authority: docs/us_short_system_design.md §11.4 hot_excluded (高 theme_heat 但被安全闸/流动性/数据 gate
剔除的票 → hot_excluded + 原因;绝不救回 hard veto / 不改准入;持仓票私密拆分;周报横幅计数与明细一致) /
§11.2 banner ⑤ / §18.1 #19. Criteria authority = the FROZEN
presets/us_short_exclusion_summary_governance_20260620.json ``hot_excluded`` block
("theme_heat_score_at_percentile_but_dropped_at_safety_liquidity_data_gate"; ``never_rescue_hard_veto`` ;
``never_change_admission`` ; the percentile threshold itself is FORWARD, not pinned).

hot_excluded surfaces MISTAKEN KILLS: a name with high theme heat that a SAFETY / LIQUIDITY / DATA gate dropped,
so §13 review can ask "is the system too conservative?". It is an AUDIT ONLY:
  * it never rescues a hard-veto kill — a high-heat name dropped at any gate OTHER than safety/liquidity/data
    (e.g. a hard veto / fundamental gate) is NOT hot_excluded; it was correctly killed (§11.4 不救回 hard veto);
  * it never changes admission — ``detect_hot_excluded`` returns a filtered VIEW of shallow row copies; the
    caller's exclusion rows are never mutated (§11.4 不改准入).
The heat cutoff is a caller-supplied parameter (the percentile→cutoff is forward, per governance — not pinned
here). ``hot_excluded_summary`` bridges the detected rows to the §11.4 exclusion_summary ``hot_excluded`` input
+ the §11.2 banner ⑤ count from ONE source (so the banner count and the §11.4 detail can never disagree), with
the privacy split: a public-universe count (de-identified, trackable) + the HOLDING rows (private detail). Pure
/ offline: filters dicts; no provider / live / DataHub / network; no A-share crossing.
"""
from __future__ import annotations

import math

# The gates where a high-heat kill MIGHT be a mistake worth auditing (sourced from the frozen criteria
# "...dropped_at_safety_liquidity_data_gate"). A hard-veto / fundamental gate is deliberately NOT here — a
# high-heat name killed there was correctly killed and is never surfaced / rescued as hot_excluded.
AUDIT_ELIGIBLE_GATES = frozenset({"safety", "liquidity", "data"})


class HotExcludedError(ValueError):
    """Raised when hot_excluded input violates the §11.4 contract (row shape, gate, heat, or threshold)."""


def _finite_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _nonblank_str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _validate_row(row) -> None:
    if not isinstance(row, dict):
        raise HotExcludedError("excluded row must be a dict, got %r" % (type(row).__name__,))
    if not _nonblank_str(row.get("ticker")):
        raise HotExcludedError("excluded row ticker must be a non-blank string, got %r" % (row.get("ticker"),))
    heat = row.get("theme_heat_score")
    if not (_finite_number(heat) and heat >= 0):
        raise HotExcludedError("theme_heat_score must be a finite non-negative number, got %r" % (heat,))
    if not _nonblank_str(row.get("dropped_at_gate")):
        raise HotExcludedError("dropped_at_gate must be a non-blank string, got %r" % (row.get("dropped_at_gate"),))
    if not isinstance(row.get("is_holding"), bool):
        raise HotExcludedError("is_holding must be a bool, got %r" % (row.get("is_holding"),))


def detect_hot_excluded(excluded_rows, *, heat_threshold):
    """Return the AUDIT-ONLY hot_excluded view: excluded rows whose ``theme_heat_score >= heat_threshold`` AND
    that were dropped at a SAFETY / LIQUIDITY / DATA gate (the mistaken-kill candidates, §11.4). A high-heat name
    dropped at any OTHER gate (hard veto / fundamental) is NEVER included — it was correctly killed, never
    rescued. ``excluded_rows`` is a list of ``{ticker, theme_heat_score, dropped_at_gate, is_holding}``. The
    input is NOT modified (audit only — never changes admission); the returned rows are shallow copies. Raises
    ``HotExcludedError`` on a malformed row / threshold."""
    if not isinstance(excluded_rows, list):
        raise HotExcludedError("excluded_rows must be a list, got %r" % (type(excluded_rows).__name__,))
    if not (_finite_number(heat_threshold) and heat_threshold >= 0):
        raise HotExcludedError("heat_threshold must be a finite non-negative number, got %r" % (heat_threshold,))
    hot = []
    for row in excluded_rows:
        _validate_row(row)
        if row["theme_heat_score"] >= heat_threshold and row["dropped_at_gate"] in AUDIT_ELIGIBLE_GATES:
            hot.append(dict(row))  # shallow copy — never mutate / hand back the caller's row (audit only)
    return hot


def hot_excluded_summary(excluded_rows, *, heat_threshold) -> dict:
    """Build the official §11.4 hot_excluded ``{public_heat_count, holdings}`` bridge (consumed by
    ``build_exclusion_summary`` + the §11.2 banner ⑤) from the RAW weekly excluded rows.

    It internally runs ``detect_hot_excluded`` — the ONLY path — so the eligible-gate + heat-threshold contract
    is ALWAYS applied: a caller CANNOT bypass it by handing in fabricated / pre-filtered rows. Hard-veto /
    fundamental / unknown-gate rows and low-heat rows are filtered out and never counted as official hot_excluded
    (§11.4 绝不救回 hard veto / 不混入低热), instead of being trusted as already-detected. Returns
    ``{"public_heat_count": <count of NON-holding hot names — de-identified, trackable>, "holdings": [{"ticker",
    "reason"} for the HOLDING hot rows — private detail]}``: the public count excludes holdings so the tracked
    number reveals nothing about real positions (§11.4 纯公开 universe 热票计数可 tracked / 持仓票私密拆分); the
    holding rows carry ticker + the dropping gate as the reason. Raises ``HotExcludedError`` on a malformed row /
    threshold (via the detector)."""
    hot = detect_hot_excluded(excluded_rows, heat_threshold=heat_threshold)  # detector contract is the only gate
    return {
        "public_heat_count": sum(1 for row in hot if not row["is_holding"]),  # public universe only → tracked-safe
        "holdings": [
            {"ticker": row["ticker"], "reason": row["dropped_at_gate"]}
            for row in hot if row["is_holding"]  # real positions → private detail
        ],
    }
