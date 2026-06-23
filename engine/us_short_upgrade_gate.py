# -*- coding: utf-8 -*-
"""US-short §12.2 比较轨 anti-self-deception upgrade gate — batch-3 (#13/#24/#28 follow-up): pure readiness decision.

Design authority: docs/us_short_system_design.md §12.2 (升级闸防自欺四机制: ① 只数 live forward 观测[决策当日 PIT、
无 look-ahead]入升级时钟; ② 胜出 margin 必须先冻[governance 填死数值阈值后才允许触发升级复审]; ③ 陈旧/错位 artifact
fail-closed; ④ 每周运行时醒目横幅) / §13 #1/#28 / §12 (升级仍需用户决定、绝不自动切生产). Borrows the A-share
``runners/a_short_overlay_eval`` anti-self-deception structure (margin-frozen-or-no-upgrade, forward-obs-only clock,
status = accumulating / review_due_margin_pending / review_due_ready, non-production boundary). Consumes the weekly
two-way scorecard comparison observations (engine.us_short_paper_scorecard_comparison) accumulated over weeks.

This cut = the PURE readiness DECISION: count the forward (live decision-day, PIT, no look-ahead) comparison
observations vs the frozen ``min_comparison_weeks``, GATED by whether the §12.2 ② stable-win margin is FROZEN in
governance. If the margin is not a frozen finite number — the CURRENT state: the scoring_profile governance has no
numeric ``comparison_win_margin`` — the gate NEVER authorizes an upgrade review, even at/over the min weeks
(防"先看数据再定胜出线": you cannot decide the winning line after seeing the data). An upgrade ALWAYS needs a USER
decision and NEVER auto-switches production (§12) — this only SURFACES readiness. ②③① are honoured here at the
eval layer: ``validate_upgrade_eval`` RE-DERIVES the gates from governance so the artifact can NEVER self-author
readiness (``comparison_win_margin_frozen`` / ``min_comparison_weeks`` must equal the re-derived governance values),
and each forward obs must be EXACTLY ``{"as_of"}`` (de-identified — no nested ticker / performance), ``<= as_of``
(no look-ahead, §12.2 ①) and strictly ascending + unique (§12.2 ③); a non-dict governance fails closed. The
forward-obs discover/accumulate (scanning the private shadow_compare buckets), the de-identified tracked
summary/writer, and the runtime banner (④) are follow-up cuts.

Pure / offline: reads the FROZEN scoring_profile governance preset; arithmetic on dicts; no provider / live /
DataHub / network; no jsonschema (inline date gate); no A-share crossing. Malformed input fails closed
(``UpgradeGateError``).
"""
from __future__ import annotations

import datetime
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_GOV_PATH = ROOT / "presets" / "us_short_scoring_profile_governance_20260620.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

ACCUMULATING = "accumulating"                            # < min_comparison_weeks forward observations
REVIEW_DUE_MARGIN_PENDING = "review_due_margin_pending"  # at/over min weeks but the §12.2 ② win margin is NOT frozen
REVIEW_DUE_READY = "review_due_ready"                    # at/over min weeks AND margin frozen → an upgrade review may be RAISED (user decides)
_DECISION_STATUSES = (ACCUMULATING, REVIEW_DUE_MARGIN_PENDING, REVIEW_DUE_READY)
# the frozen non-production boundary every eval carries (the gate SURFACES readiness; it is NOT the upgrade
# decision and NEVER counts ship-gate, §12 / §13)
_BOUNDARY = {"production": False, "is_upgrade_decision": False, "satisfies_ship_gate": False}
_EVAL_KEYS = frozenset({"as_of", "min_comparison_weeks", "n_forward_observations", "upgrade_review_due",
                        "comparison_win_margin_frozen", "decision_status", "forward_observations", "boundary"})


class UpgradeGateError(ValueError):
    """Raised when the §12.2 upgrade-gate contract is violated (governance / observations / consistency)."""


def _strict_yyyymmdd(s) -> bool:
    # inlined (with the isascii() guard) so this stays jsonschema-free
    if not (isinstance(s, str) and len(s) == 8 and s.isascii() and s.isdigit()):
        return False
    try:
        datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return True
    except ValueError:
        return False


def _pos_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= 1


def _require_gov(governance):
    """Fail closed (``UpgradeGateError``, not a raw AttributeError) on a non-dict governance."""
    if not isinstance(governance, dict):
        raise UpgradeGateError("governance must be a dict, got %r" % (type(governance).__name__,))
    return governance


def margin_frozen(governance=_GOV) -> bool:
    """§12.2 ②: the stable-win margin is FROZEN only if governance carries a NUMERIC finite ``comparison_win_margin``
    (not absent / a placeholder string / bool). Until a REVIEWED governance change freezes it, the gate never
    authorizes an upgrade review even at/over the min weeks (防"先看数据再定胜出线")."""
    m = _require_gov(governance).get("comparison_win_margin")
    return isinstance(m, (int, float)) and not isinstance(m, bool) and math.isfinite(m)


def upgrade_readiness(n_forward_obs, min_weeks, is_margin_frozen) -> dict:
    """Pure decision: forward-obs count vs ``min_weeks`` + whether the §12.2 ② margin is frozen → decision_status.
    Returns ``{upgrade_review_due, decision_status}``. Raises ``UpgradeGateError`` on a bad count / min_weeks."""
    if not (isinstance(n_forward_obs, int) and not isinstance(n_forward_obs, bool) and n_forward_obs >= 0):
        raise UpgradeGateError("n_forward_obs must be a non-negative int, got %r" % (n_forward_obs,))
    if not _pos_int(min_weeks):
        raise UpgradeGateError("min_weeks must be a positive int, got %r" % (min_weeks,))
    if not isinstance(is_margin_frozen, bool):
        raise UpgradeGateError("is_margin_frozen must be a bool, got %r" % (is_margin_frozen,))
    due = n_forward_obs >= min_weeks
    if not due:
        status = ACCUMULATING
    elif not is_margin_frozen:
        status = REVIEW_DUE_MARGIN_PENDING
    else:
        status = REVIEW_DUE_READY
    return {"upgrade_review_due": due, "decision_status": status}


def build_upgrade_eval(forward_observations, *, as_of, governance=_GOV) -> dict:
    """Build the §12.2 upgrade-readiness eval from the forward (live decision-day, PIT) comparison observations.

    ``forward_observations`` = a list of weekly comparison obs, each a dict with a strict ``as_of`` (one per
    decision week — STRICTLY ASCENDING + UNIQUE, so a stale / out-of-order / double-counted week can't advance the
    clock, §12.2 ③); the caller/discover supplies forward-only obs (① at the artifact layer is a follow-up).
    ``as_of`` = this eval's decision_date; ``governance`` = the scoring_profile governance (min_comparison_weeks +
    the §12.2 ② comparison_win_margin). Returns the eval summary (re-validated through ``validate_upgrade_eval``).
    The summary is de-identified (only decision-week dates + counts). Raises ``UpgradeGateError`` on malformed input.
    Upgrade ALWAYS needs a USER decision (§12) — this only surfaces readiness."""
    if not _strict_yyyymmdd(as_of):
        raise UpgradeGateError("as_of must be a strict real YYYYMMDD, got %r" % (as_of,))
    min_weeks = _require_gov(governance).get("min_comparison_weeks")
    if not _pos_int(min_weeks):
        raise UpgradeGateError("governance.min_comparison_weeks must be a positive int, got %r" % (min_weeks,))
    if not isinstance(forward_observations, list):
        raise UpgradeGateError("forward_observations must be a list, got %r" % (type(forward_observations).__name__,))
    obs_out, prev = [], None
    for i, o in enumerate(forward_observations):
        if not isinstance(o, dict):
            raise UpgradeGateError("forward_observations[%d] must be a dict, got %r" % (i, type(o).__name__))
        if set(o) != {"as_of"}:  # de-identified: EXACTLY {as_of} — no ticker / performance field may ride along
            raise UpgradeGateError("forward_observations[%d] must be EXACTLY {'as_of'} (no nested ticker / performance field), got %s" % (i, sorted(map(str, o))))
        oa = o["as_of"]
        if not _strict_yyyymmdd(oa):
            raise UpgradeGateError("forward_observations[%d].as_of must be a strict real YYYYMMDD, got %r" % (i, oa))
        if oa > as_of:  # §12.2 ① no look-ahead: a week AFTER the decision date can't be counted into it
            raise UpgradeGateError("forward_observations[%d].as_of %r is AFTER the eval as_of %r (look-ahead, §12.2 ①)" % (i, oa, as_of))
        if prev is not None and oa <= prev:
            raise UpgradeGateError(
                "forward_observations must be STRICTLY ascending + unique by as_of (no out-of-order / double-counted week, §12.2 ③): %r after %r" % (oa, prev))
        prev = oa
        obs_out.append({"as_of": oa})  # de-identified: only the decision-week date counts toward the upgrade clock
    n = len(obs_out)
    is_frozen = margin_frozen(governance)
    readiness = upgrade_readiness(n, min_weeks, is_frozen)
    result = {
        "as_of": as_of,
        "min_comparison_weeks": min_weeks,
        "n_forward_observations": n,
        "upgrade_review_due": readiness["upgrade_review_due"],
        "comparison_win_margin_frozen": is_frozen,
        "decision_status": readiness["decision_status"],
        "forward_observations": obs_out,
        "boundary": dict(_BOUNDARY),
    }
    validate_upgrade_eval(result, governance=governance)  # re-validate against the SAME governance (re-derives margin/min)
    return result


def validate_upgrade_eval(summary, *, governance=_GOV) -> None:
    """Fail-closed CLOSED-WORLD self-check that RE-DERIVES every mutable gate from authority (the artifact can never
    self-author readiness): the EXACT key set; the frozen non-production boundary; a strict REAL as_of;
    ``min_comparison_weeks == governance["min_comparison_weeks"]`` and ``comparison_win_margin_frozen ==
    margin_frozen(governance)`` (both RE-DERIVED — a doctored margin-frozen / min can't validate); every forward obs
    EXACTLY ``{"as_of": <strict YYYYMMDD>}`` (de-identified — no nested ticker / performance), each ``<= as_of`` (no
    look-ahead, §12.2 ①) and STRICTLY ascending + unique (§12.2 ③); ``n_forward_observations ==
    len(forward_observations)``; ``upgrade_review_due == (n >= min_comparison_weeks)``; and ``decision_status``
    consistent with (due, the re-derived margin_frozen). Raises ``UpgradeGateError`` (incl. on non-dict governance)."""
    if not isinstance(summary, dict):
        raise UpgradeGateError("summary must be a dict, got %r" % (type(summary).__name__,))
    if set(summary) != _EVAL_KEYS:
        raise UpgradeGateError("summary must carry EXACTLY %s (closed-world): missing %s, extra %s"
                               % (sorted(_EVAL_KEYS), sorted(map(str, _EVAL_KEYS - set(summary))), sorted(map(str, set(summary) - _EVAL_KEYS))))
    if summary["boundary"] != _BOUNDARY:
        raise UpgradeGateError("boundary must be the frozen non-production block %r, got %r" % (_BOUNDARY, summary["boundary"]))
    if not _strict_yyyymmdd(summary["as_of"]):
        raise UpgradeGateError("as_of must be a strict real YYYYMMDD, got %r" % (summary["as_of"],))
    expected_min = _require_gov(governance).get("min_comparison_weeks")  # re-derive from authority
    if not _pos_int(expected_min):
        raise UpgradeGateError("governance.min_comparison_weeks must be a positive int, got %r" % (expected_min,))
    mw, n = summary["min_comparison_weeks"], summary["n_forward_observations"]
    if mw != expected_min:  # the artifact can't self-author the min weeks
        raise UpgradeGateError("min_comparison_weeks %r != governance %r (self-authored)" % (mw, expected_min))
    if not (isinstance(n, int) and not isinstance(n, bool) and n >= 0):
        raise UpgradeGateError("n_forward_observations must be a non-negative int, got %r" % (n,))
    as_of = summary["as_of"]
    obs = summary["forward_observations"]
    if not isinstance(obs, list) or n != len(obs):
        raise UpgradeGateError("n_forward_observations %r != len(forward_observations) %r" % (n, len(obs) if isinstance(obs, list) else obs))
    prev = None
    for o in obs:
        if not (isinstance(o, dict) and set(o) == {"as_of"} and _strict_yyyymmdd(o.get("as_of"))):
            raise UpgradeGateError("each forward observation must be EXACTLY {'as_of': <strict YYYYMMDD>} (de-identified — no nested ticker / performance), got %r" % (o,))
        if o["as_of"] > as_of:  # §12.2 ① no look-ahead
            raise UpgradeGateError("forward observation as_of %r is AFTER the eval as_of %r (look-ahead, §12.2 ①)" % (o["as_of"], as_of))
        if prev is not None and o["as_of"] <= prev:
            raise UpgradeGateError("forward_observations must be STRICTLY ascending + unique by as_of, got %r after %r" % (o["as_of"], prev))
        prev = o["as_of"]
    due = n >= mw
    if due != summary["upgrade_review_due"]:
        raise UpgradeGateError("upgrade_review_due %r != (n >= min_comparison_weeks) %r" % (summary["upgrade_review_due"], due))
    expected_frozen = margin_frozen(governance)  # re-derive from authority — NOT trusted from the artifact
    frozen, st = summary["comparison_win_margin_frozen"], summary["decision_status"]
    if not isinstance(frozen, bool):
        raise UpgradeGateError("comparison_win_margin_frozen must be a bool, got %r" % (frozen,))
    if frozen is not expected_frozen:
        raise UpgradeGateError("comparison_win_margin_frozen %r != margin_frozen(governance) %r (self-authored readiness)" % (frozen, expected_frozen))
    expected = ACCUMULATING if not due else (REVIEW_DUE_READY if frozen else REVIEW_DUE_MARGIN_PENDING)
    if st != expected:
        raise UpgradeGateError("decision_status %r inconsistent with (due=%r, margin_frozen=%r) — expected %r" % (st, due, frozen, expected))
