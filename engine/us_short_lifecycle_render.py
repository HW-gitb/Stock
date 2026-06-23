# -*- coding: utf-8 -*-
"""US-short §13 lifecycle runtime render — slice 2c (first cut): GBK-safe due-scan banner.

Design authority: docs/us_short_system_design.md §13 (运行时露出: 达标醒目横幅, 不只靠周报文字 / 不靠某个 LLM 记得读
register) / §2 (lifecycle eval → 运行时醒目横幅) / §18.1 #20 (扫全部 §13.1 forward 项 + 醒目横幅; upgrade 需用户决定,
绝不自动切生产) / §12.2 (升级仍需用户决定).

Renders evaluate_lifecycle's due-scan result into a ONE-LINE, GBK-safe (ASCII-only) runtime banner so the
lifecycle reminder is visible on a Windows GBK console for whoever runs the weekly pipeline — independent of a
reader noticing the weekly_report text. The eval-result CONTRACT is fully validated before rendering, so a
malformed / inconsistent / non-ASCII result fails closed to a conservative 'UNAVAILABLE' banner — never a
misleading 0-due banner, never a silent empty string, and never non-ASCII output that breaks the GBK console
(R-USSHORT-BATCH3-R2-LIFECYCLE-BANNER-FAILCLOSED-GBK-GAP). Upgrade eligibility is SURFACED, never acted on (an
upgrade always needs a USER decision, never auto-production).

Pure / offline: formats a string from the eval-result dict; no IO, no provider/live; NO jsonschema/engine
import (the runtime banner stays importable + testable on a minimal runtime). No A-share crossing. The
weekly-report lifecycle section / top banner + count reconcile + the readiness artifact are the next 2c cuts.
"""
from __future__ import annotations

from datetime import datetime

_BANNER_PREFIX = "[us-short lifecycle]"
_UNAVAILABLE = "%s due scan UNAVAILABLE (malformed eval result) - treat as NOT clean" % _BANNER_PREFIX


def _pos_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x > 0


def _nonneg_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def _strict_ascii_date(s) -> bool:
    """A strict ASCII YYYYMMDD (ASCII → GBK-safe; the eval as_of contract guarantees this for a clean register)."""
    if not isinstance(s, str) or not s.isascii() or len(s) != 8 or not s.isdigit():
        return False
    try:
        datetime.strptime(s, "%Y%m%d")
        return True
    except ValueError:
        return False


def _validated(eval_result):
    """Validate the full evaluate_lifecycle result contract → ``(as_of_str, total, due_items, upgrade)`` or None.

    None (→ UNAVAILABLE) on ANY violation, so a malformed / inconsistent / non-ASCII due-scan result can never
    render as a normal banner or leak non-ASCII into the GBK console: dict input; total_items a positive int;
    due_items / upgrade are lists of UNIQUE positive ints within [1, total_items]; due_count a nonneg int ==
    len(due_items); len(due_items) <= total_items; upgrade ⊆ due_items; as_of absent/unknown or a strict ASCII
    date.
    """
    if not isinstance(eval_result, dict):
        return None
    total = eval_result.get("total_items")
    due_count = eval_result.get("due_count")
    due_items = eval_result.get("due_items")
    upgrade = eval_result.get("upgrade_eligible_items")
    as_of = eval_result.get("as_of")
    if not _pos_int(total):
        return None
    if not isinstance(due_items, list) or not isinstance(upgrade, list):
        return None
    if not all(_pos_int(n) and n <= total for n in due_items):       # ids: unique positive ints within range
        return None
    if not all(_pos_int(n) and n <= total for n in upgrade):
        return None
    if len(set(due_items)) != len(due_items) or len(set(upgrade)) != len(upgrade):
        return None
    if not _nonneg_int(due_count) or due_count != len(due_items):     # due_count consistency
        return None
    if len(due_items) > total:
        return None
    if set(upgrade) - set(due_items):                                 # upgrade must be a subset of due
        return None
    if as_of is None:
        as_of_s = "unknown"
    elif _strict_ascii_date(as_of):
        as_of_s = as_of
    else:
        return None
    return as_of_s, total, due_items, upgrade


def lifecycle_banner(eval_result) -> str:
    """Return a one-line ASCII (GBK-safe) runtime banner from an ``evaluate_lifecycle`` result.

    Validates the full eval-result contract first (see ``_validated``): a malformed / inconsistent / non-ASCII
    result fails closed to the conservative UNAVAILABLE banner — never a misleading 0-due banner, never an
    empty string, never non-ASCII output. Surfaces how many §13.1 items reached their review bar + which
    numbers + which are §12.2② upgrade-eligible, with an explicit 'upgrade needs a USER decision (never
    auto-production)' caveat (it SURFACES upgrade eligibility, never triggers it). The returned banner is
    GUARANTEED ASCII — a final encode guard floors it so malformed non-ASCII content can never reach the GBK
    console.
    """
    v = _validated(eval_result)
    if v is None:
        return _UNAVAILABLE
    as_of_s, total, due_items, upgrade = v
    if not due_items:
        banner = "%s as_of=%s: 0/%d calibration items (13.1) due for review this run." % (_BANNER_PREFIX, as_of_s, total)
    else:
        banner = "%s as_of=%s: %d/%d calibration items (13.1) DUE for review: %s" % (
            _BANNER_PREFIX, as_of_s, len(due_items), total, ", ".join("#%d" % n for n in due_items))
        if upgrade:
            banner += " | %d upgrade-eligible (12.2 margin frozen): %s" % (
                len(upgrade), ", ".join("#%d" % n for n in upgrade))
        banner += " | upgrade needs a USER decision (never auto-production)."
    try:
        banner.encode("ascii")  # belt-and-suspenders: validated content is ASCII; never leak non-ASCII to GBK
    except UnicodeEncodeError:
        return _UNAVAILABLE
    return banner
