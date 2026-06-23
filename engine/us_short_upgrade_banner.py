# -*- coding: utf-8 -*-
"""US-short §12.2 upgrade-gate runtime banner — batch-3 (#13/#24/#28 follow-up; ④ 运行时醒目横幅).

Design authority: docs/us_short_system_design.md §12.2 升级闸防自欺 ④ (每周运行时醒目横幅) / §13 (运行时露出, 不只靠
周报文字 / 不靠某个 LLM 记得读 register) / §12 (升级需用户决定、绝不自动切生产). Renders an
``engine.us_short_upgrade_gate`` eval into a ONE-LINE, GBK-safe (ASCII-only) runtime banner so the upgrade-readiness
status is visible on a Windows GBK console for whoever runs the weekly pipeline — independent of a reader noticing
the weekly_report text.

The eval is RE-VALIDATED through ``validate_upgrade_eval`` (against governance — re-deriving the margin-frozen /
min gate from authority, so a SELF-AUTHORED / malformed / look-ahead eval fails closed to a conservative
UNAVAILABLE banner, never a misleading 'ready' banner). The returned banner is GUARANTEED ASCII (a final encode
guard), so non-ASCII can never break the GBK console. Upgrade readiness is SURFACED, never acted on (a USER decides,
never auto-production). Pure / offline: formats a string; no IO, no provider/live; imports only the pure
``us_short_upgrade_gate`` (no jsonschema); no A-share crossing.
"""
from __future__ import annotations

from engine.us_short_upgrade_gate import (
    ACCUMULATING,
    REVIEW_DUE_MARGIN_PENDING,
    REVIEW_DUE_READY,
    UpgradeGateError,
    validate_upgrade_eval,
)

_PREFIX = "[us-short upgrade gate]"
_UNAVAILABLE = "%s readiness UNAVAILABLE (eval not contract-clean) - treat as NOT due" % _PREFIX


def upgrade_banner(eval_result, *, governance=None) -> str:
    """Return a one-line ASCII (GBK-safe) runtime banner from an ``us_short_upgrade_gate`` eval.

    Re-validates the eval through ``validate_upgrade_eval`` (against ``governance`` if given, else the frozen
    scoring_profile preset) — a self-authored (e.g. ``comparison_win_margin_frozen`` edited to True under the
    current no-margin governance) / malformed / look-ahead eval fails closed to the conservative UNAVAILABLE banner,
    never a misleading 'ready' banner. Surfaces the ``decision_status`` + forward-week count vs the min + the
    margin-frozen state, with the explicit 'a USER decides, never auto-production' caveat (it SURFACES readiness,
    never triggers it). The returned banner is GUARANTEED ASCII (a final encode guard floors it)."""
    try:
        if governance is None:
            validate_upgrade_eval(eval_result)
        else:
            validate_upgrade_eval(eval_result, governance=governance)
    except UpgradeGateError:
        return _UNAVAILABLE
    as_of = eval_result["as_of"]
    n, mw = eval_result["n_forward_observations"], eval_result["min_comparison_weeks"]
    status = eval_result["decision_status"]
    if status == ACCUMULATING:
        banner = "%s as_of=%s: ACCUMULATING %d/%d forward comparison weeks - not yet due for upgrade review." % (_PREFIX, as_of, n, mw)
    elif status == REVIEW_DUE_MARGIN_PENDING:
        banner = ("%s as_of=%s: %d/%d weeks DUE but the win-margin is NOT frozen in governance - upgrade NOT "
                  "authorized (freeze the margin first); never auto-production." % (_PREFIX, as_of, n, mw))
    else:  # REVIEW_DUE_READY
        banner = ("%s as_of=%s: %d/%d weeks DUE + win-margin frozen - an upgrade review may be RAISED; a USER "
                  "decides, never auto-production." % (_PREFIX, as_of, n, mw))
    try:
        banner.encode("ascii")  # belt-and-suspenders: validated content is ASCII; never leak non-ASCII to a GBK console
    except UnicodeEncodeError:
        return _UNAVAILABLE
    return banner
