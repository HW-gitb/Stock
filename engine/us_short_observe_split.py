# -*- coding: utf-8 -*-
"""US-short §11.2 honest-banner ① — batch-3: observe_reason_type → real-vs-fake observe split aggregator.

Design authority: docs/us_short_system_design.md §11.2 honest banner ① (把 observe_reason_type 聚合成"本周 X 只
观察：…——没账户/没现金那类是 sizing 假象、不是系统不看好") / §18.1 #10. Enum + banner authority = the FROZEN
presets (batch-1, design-locked): the frozen observe_reason_type values are read from
``presets/us_short_action_table_contract_20260620.json`` ``design_locked_enums`` (single source), and the
``true_false_observe_split`` banner element in ``presets/us_short_weekly_report_contract_20260620.json`` pins the
honest framing — "no-account/no-cash = sizing artifact, not disfavor".

The honest banner ① splits this week's observe rows into a REAL-vs-FAKE picture: a ``cash_or_account_missing``
observe is a SIZING ARTIFACT (the system would act but there is no account / cash to size into it — it is NOT
the system disfavouring the name), whereas every other observe reason is a genuine deferral. So a reader can
never mistake "X observed" for "the system passed on X good names" when some of those are pure capital/account
mechanics. Only ``cash_or_account_missing`` is classified fake/sizing here — the one reason both the frozen
banner ref and §11.2 ① name explicitly; that is the conservative, honest direction (it never overstates how many
observes are "just sizing"). ``aggregate_observe_split`` counts every frozen reason (zeros explicit — the full
honest breakdown) and ``validate_observe_split`` is the fail-closed gate. Pure / offline: reads the frozen enum,
counts; no provider / live / DataHub / network; no A-share crossing.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CONTRACT_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"

# The one observe_reason_type both the frozen banner ref and §11.2 ① name as a SIZING ARTIFACT (fake observe):
# no account / no cash to size into — the system would act, so it is not disfavour. Narrow-safe: only the
# explicitly-named reason is fake, so the split never OVERSTATES how many observes are "just sizing".
_SIZING_ARTIFACT_REASONS = frozenset({"cash_or_account_missing"})

_CACHE: dict = {}


class ObserveSplitError(ValueError):
    """Raised when observe input / a split record violates the §11.2 ① contract (enum, count, or consistency)."""


def _reasons() -> list:
    if "reasons" not in _CACHE:
        _CACHE["reasons"] = list(
            json.loads(_CONTRACT_PRESET.read_text(encoding="utf-8"))["design_locked_enums"]["observe_reason_type"]
        )
    return _CACHE["reasons"]


def _int_not_bool(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def aggregate_observe_split(observe_reason_types) -> dict:
    """Aggregate this week's per-row observe reasons into the §11.2 ① real-vs-fake split.

    ``observe_reason_types`` is a list of observe_reason_type values, each one of the frozen
    ``design_locked_enums`` observe_reason_type set (an unknown / non-string value is refused — closed-world).
    Returns ``{"total", "per_reason": {<every frozen reason>: count}, "sizing_artifact_count"}`` where
    ``per_reason`` carries ALL frozen reasons (zeros explicit — the full honest breakdown) and
    ``sizing_artifact_count`` is the number of fake/sizing observes (``cash_or_account_missing``). The result is
    self-validated. Raises ``ObserveSplitError`` on bad input."""
    if not isinstance(observe_reason_types, list):
        raise ObserveSplitError("observe_reason_types must be a list, got %r" % (type(observe_reason_types).__name__,))
    reasons = _reasons()
    allowed = set(reasons)
    per_reason = {r: 0 for r in reasons}  # all frozen reasons present, zeros explicit
    for v in observe_reason_types:
        if not isinstance(v, str) or v not in allowed:
            raise ObserveSplitError(
                "observe_reason_type %r not in the frozen design_locked_enums set %s (closed-world)" % (v, reasons)
            )
        per_reason[v] += 1
    split = {
        "total": len(observe_reason_types),
        "per_reason": per_reason,
        "sizing_artifact_count": sum(per_reason[r] for r in reasons if r in _SIZING_ARTIFACT_REASONS),
    }
    validate_observe_split(split)
    return split


def validate_observe_split(split) -> None:
    """Fail-closed §11.2 ① gate. Enforces: a dict; ``per_reason`` carries EXACTLY the frozen reason set with
    NON-NEGATIVE int counts; ``total`` a non-negative int equal to the sum of the per-reason counts;
    ``sizing_artifact_count`` a non-negative int equal to the sum of the sizing-artifact reasons' counts (so the
    fake count can never be overstated relative to the breakdown). Raises ``ObserveSplitError`` on any violation;
    a record from ``aggregate_observe_split`` always passes."""
    if not isinstance(split, dict):
        raise ObserveSplitError("observe split must be a dict")
    per_reason = split.get("per_reason")
    reasons = _reasons()
    if not isinstance(per_reason, dict) or set(per_reason) != set(reasons):
        raise ObserveSplitError(
            "per_reason must be a dict over EXACTLY the frozen reason set %s, got keys %s"
            % (reasons, sorted(map(str, per_reason)) if isinstance(per_reason, dict) else type(per_reason).__name__)
        )
    if not all(_int_not_bool(per_reason[r]) and per_reason[r] >= 0 for r in reasons):
        raise ObserveSplitError("per_reason counts must be NON-NEGATIVE integers, got %r" % (per_reason,))
    total = split.get("total")
    if not (_int_not_bool(total) and total >= 0):
        raise ObserveSplitError("total must be a NON-NEGATIVE integer, got %r" % (total,))
    if total != sum(per_reason.values()):
        raise ObserveSplitError("total %d != sum(per_reason) %d" % (total, sum(per_reason.values())))
    sizing = split.get("sizing_artifact_count")
    expected_sizing = sum(per_reason[r] for r in reasons if r in _SIZING_ARTIFACT_REASONS)
    if not (_int_not_bool(sizing) and sizing >= 0) or sizing != expected_sizing:
        raise ObserveSplitError("sizing_artifact_count %r != sum of sizing-artifact reasons %d" % (sizing, expected_sizing))


def render_observe_split(split) -> str:
    """Render the §11.2 honest-banner ① string from a split (validated first). Returns a non-blank one-line
    string: the total, the per-reason breakdown (frozen order), and the explicit honest note that the
    sizing-artifact observes are capital/account mechanics, not the system disfavouring those names. De-identified
    (counts only, no tickers)."""
    validate_observe_split(split)
    per_reason = split["per_reason"]
    breakdown = "、".join("%s %d" % (r, per_reason[r]) for r in _reasons())  # frozen order
    return (
        "本周 %d 只观察(%s);其中 %d 只为 sizing 假象(没账户/没现金,系统并非不看好)。"
        % (split["total"], breakdown, split["sizing_artifact_count"])
    )
