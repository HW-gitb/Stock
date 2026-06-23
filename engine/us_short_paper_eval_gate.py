# -*- coding: utf-8 -*-
"""US-short §12.1 复权/公司行动门 — batch-3 (#29): paper_performance evaluability fail-closed gate.

Design authority: docs/us_short_system_design.md §12.1 (复权/公司行动硬门: 未确认 adjustment_mode + split/dividend
处理 + 除权日价位一致 → paper_performance 一律 not_evaluable/data_degraded, 不进 ship-gate/alpha) / §18.0 P0
(复权/公司行动门, SR-PROVIDER-001) / §18.1 #29 / §12 (paper 仅设计迭代、绝不判满仓 ship-gate).

paper_performance is adjustment-evaluable for paper / reporting / shadow (design-iteration) use ONLY when all
three corporate-action confirmations are explicitly true: the price adjustment mode is confirmed, splits/dividends
are handled, and the ex-date price levels are consistent. CRUCIALLY this is a PAPER gate — even when fully
adjustment-confirmed, paper_performance is NEVER full-size ship-gate eligible (§12 / §27: model_paper_track is
design-iteration evidence; only ``live_normalized`` = manual_actual + reconciliation graduates). So the output
carries an explicit, always-False ship-gate invariant so corporate-action evaluability can never be read as a
ship-gate permission. The gate is FAIL-CLOSED: a confirmation that is not literally ``True`` (missing, False,
None, or a truthy non-bool like ``1`` / ``"yes"``) does NOT count as confirmed, so the default is
``not_evaluable`` — paper performance never silently becomes usable on an unverified / sloppily-truthy
corporate-action state (SR-PROVIDER-001: active price adjustment / corporate-action reconciliation is unproven,
current call count 0). Pure / offline: reads bool confirmations from a dict; no provider / live / DataHub /
network; no A-share crossing.
"""
from __future__ import annotations

# the three §12.1 corporate-action confirmations that gate paper_performance evaluability (design prose source)
_CONFIRMATIONS = ("adjustment_mode_confirmed", "split_dividend_handled", "ex_date_price_consistent")


class PaperEvalGateError(ValueError):
    """Raised when the corporate-action context is malformed (non-dict, or an unknown confirmation key)."""


def paper_performance_evaluability(adjustment_context) -> dict:
    """Decide whether paper_performance is adjustment-evaluable for paper / reporting / shadow use (§12.1 复权门,
    fail-closed) — NEVER a full-size ship-gate permission (§12 / §27; the output keeps that explicitly disallowed).

    ``adjustment_context`` is a dict over (a subset of) the three §12.1 corporate-action confirmations — each is
    counted as confirmed ONLY when its value is literally ``True`` (a missing key, ``False``, ``None``, or a
    truthy non-bool does NOT confirm). Returns ``{"status": "evaluable" | "not_evaluable", "unconfirmed":
    [<confirmations not literally True>], "blocks_paper_performance_due_to_corporate_action": bool,
    "full_size_ship_gate_allowed": False, "ship_gate_evidence_level": "paper_not_live_normalized"}`` — ``evaluable``
    (paper / reporting / shadow design-iteration use) ONLY when all three are confirmed, else ``not_evaluable``.
    ``full_size_ship_gate_allowed`` / ``ship_gate_evidence_level`` are FIXED (paper is never full-size ship-gate
    eligible, §12 / §27), so corporate-action evaluability can never be mistaken for ship-gate permission. Raises
    ``PaperEvalGateError`` on a non-dict context or an UNKNOWN confirmation key (closed-world — a typo'd key would
    otherwise silently leave a real confirmation unreported and could look confirmed)."""
    if not isinstance(adjustment_context, dict):
        raise PaperEvalGateError("adjustment_context must be a dict, got %r" % (type(adjustment_context).__name__,))
    unknown = [k for k in adjustment_context if k not in _CONFIRMATIONS]
    if unknown:
        raise PaperEvalGateError(
            "unknown corporate-action confirmation key(s) %s — not in %s (closed-world: a typo'd key must fail "
            "closed, never silently drop a confirmation)" % (sorted(map(str, unknown)), list(_CONFIRMATIONS))
        )
    unconfirmed = [k for k in _CONFIRMATIONS if adjustment_context.get(k) is not True]  # ONLY literal True confirms
    blocked = bool(unconfirmed)
    return {
        "status": "not_evaluable" if blocked else "evaluable",
        "unconfirmed": unconfirmed,
        # LOCAL corporate-action cause ONLY — True when an unconfirmed corporate-action keeps paper_performance
        # out of paper / reporting / shadow use. It is NOT a ship-gate permission signal.
        "blocks_paper_performance_due_to_corporate_action": blocked,
        # §12 / §27 HARD invariant — stays fixed regardless of corporate-action confirmation: this is a PAPER
        # gate; model_paper_track evidence is design-iteration only and is NEVER full-size ship-gate eligible
        # (only live_normalized = manual_actual + reconciliation graduates). So evaluability here can never be
        # read as ship-gate permission (R-USSHORT-BATCH3-PAPER-EVAL-GATE-SHIP-GATE-PERMISSION-GAP).
        "full_size_ship_gate_allowed": False,
        "ship_gate_evidence_level": "paper_not_live_normalized",
    }
