# -*- coding: utf-8 -*-
"""US-short §13 lifecycle readiness artifact — slice 2c (second cut): the TRACKED de-identified due-scan summary.

Design authority: docs/us_short_system_design.md §13 (运行时露出: 写 readiness artifact) / §2 (lifecycle eval →
readiness artifact) / §11.6 (lifecycle 隐私: private 计数 vs tracked 脱敏汇总) / §11.2 (weekly lifecycle 节 + 顶部
横幅 + 数量对账) / §18.1 #20.

Builds + writes the TRACKED, de-identified lifecycle readiness artifact from a §13-clean register (via
evaluate_lifecycle). UNLIKE the PRIVATE lifecycle_register (per-item live-forward counts + later ticker /
performance detail → gitignored, §11.6), the readiness artifact carries ONLY normalized indicators — §13.1
item NUMBERS + aggregate counts, NO tickers / $ / performance — so it is safe to TRACK (§11.6 要 tracked 只能放
脱敏汇总). The de-identification GATE is the readiness schema itself: build / write validate the artifact against
schemas/us_short_lifecycle_readiness.schema.json (additionalProperties:false + integer-only item fields), so a
ticker-bearing / malformed dict is refused before it can land on a tracked path — that is why no §18.0
private-path guard is needed here (the §18.0 guard protects PRIVATE outputs; this artifact is provably
de-identified, exactly what §11.6 lets be tracked). The weekly_report lifecycle section / §11.2 top banner
render from this; the §11.2 count reconcile is the next 2c cut (it pairs with the weekly_report renderer).

Pure-ish: builds from a register (no provider/live), writes a de-identified JSON; no A-share crossing.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from engine.us_short_lifecycle_eval import (  # noqa: F401  (LifecycleRegisterError re-exported for callers)
    LifecycleRegisterError,
    _strict_yyyymmdd,  # canonical lifecycle date gate (single source — same real-date contract as validate / banner)
    evaluate_lifecycle,
)

ROOT = Path(__file__).resolve().parent.parent
_READINESS_SCHEMA = ROOT / "schemas" / "us_short_lifecycle_readiness.schema.json"
_SCHEMA_VERSION = "1.0.0"

_CACHE: dict = {}


class LifecycleReadinessError(ValueError):
    """Raised when a readiness artifact does not conform to the de-identified schema / consistency invariants."""


def _schema() -> dict:
    if "schema" not in _CACHE:
        _CACHE["schema"] = json.loads(_READINESS_SCHEMA.read_text(encoding="utf-8"))
    return _CACHE["schema"]


def _assert_readiness(readiness) -> None:
    """De-identification + consistency gate: validate against the readiness schema (additionalProperties:false →
    no ticker/performance field can be smuggled into a tracked artifact), then the draft-07-inexpressible
    cross-field invariants (due_count == len(due_items); item numbers within [1, total_items]; upgrade ⊆ due).
    Raises LifecycleReadinessError on any violation. A clean readiness from build_lifecycle_readiness always passes."""
    for err in jsonschema.Draft7Validator(_schema()).iter_errors(readiness):
        raise LifecycleReadinessError("readiness artifact violates the de-identified schema: %s" % err.message)
    # as_of strict REAL date: the schema pattern only checks 8 digits — it cannot reject an impossible calendar
    # date like 20260231, so re-apply the canonical lifecycle date gate (same contract as validate / banner) so
    # the tracked readiness artifact's PIT anchor is a real date (R-USSHORT-BATCH3-R2-LIFECYCLE-READINESS-ASOF-REAL-DATE-GAP)
    if not _strict_yyyymmdd(readiness["as_of"]):
        raise LifecycleReadinessError("as_of %r is not a strict real YYYYMMDD" % (readiness["as_of"],))
    total, due, upgrade = readiness["total_items"], readiness["due_items"], readiness["upgrade_eligible_items"]
    if readiness["due_count"] != len(due):
        raise LifecycleReadinessError("due_count %r != len(due_items) %d" % (readiness["due_count"], len(due)))
    if len(due) > total or any(n > total for n in due) or any(n > total for n in upgrade):
        raise LifecycleReadinessError("due count / item numbers exceed total_items %d" % total)
    if set(upgrade) - set(due):
        raise LifecycleReadinessError("upgrade_eligible_items %s are not a subset of due_items" % sorted(set(upgrade) - set(due)))


def build_lifecycle_readiness(register, *, calibration=None, authority=None) -> dict:
    """Build the TRACKED de-identified readiness artifact from a §13-clean register (via evaluate_lifecycle).

    REFUSES a not-clean register — evaluate_lifecycle raises ``LifecycleRegisterError`` (the readiness never
    summarizes an un-validated accumulator). The result is de-identified BY CONSTRUCTION (only §13.1 numbers +
    aggregate counts) and self-checked against the readiness schema + consistency invariants, so a
    non-conforming readiness is never emitted.
    """
    res = evaluate_lifecycle(register, calibration=calibration, authority=authority)
    readiness = {
        "schema_name": "us_short_lifecycle_readiness",
        "schema_version": _SCHEMA_VERSION,
        "as_of": res["as_of"],
        "total_items": res["total_items"],
        "due_count": res["due_count"],
        "due_items": res["due_items"],
        "upgrade_eligible_items": res["upgrade_eligible_items"],
    }
    _assert_readiness(readiness)
    return readiness


def write_lifecycle_readiness(readiness, out_path):
    """Write the TRACKED de-identified readiness artifact as JSON. Returns the written ``Path``.

    The readiness schema IS the de-identification gate: ``_assert_readiness`` validates the dict (no
    ticker/performance field via additionalProperties:false, + consistency invariants) BEFORE any write, so a
    malformed / ticker-bearing dict is refused before it can land on a tracked path. No §18.0 private-path
    guard is needed (the §18.0 guard protects PRIVATE outputs; a provably de-identified artifact is exactly
    what §11.6 lets be tracked).
    """
    _assert_readiness(readiness)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return out_path
