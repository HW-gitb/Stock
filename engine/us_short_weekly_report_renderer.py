# -*- coding: utf-8 -*-
"""US-short weekly_report.md renderer — batch-3 (first cut: §11.2 13-section skeleton + honest banner + count reconcile).

Design authority: docs/us_short_system_design.md §11.1 / §11.2 (周报 13 节 + 诚实横幅 + price_clock + lifecycle 数量对账)
/ §13 (lifecycle 提醒) / §2.1 (price clock 语义).

Renders the §11.2 weekly_report.md FROM a ``report_data`` dict, with the section SET + ORDER, the mandatory
honest-banner elements, the price_clock fields, and the lifecycle-count-consistency rule all read from the
FROZEN ``us_short_weekly_report_contract`` (single source — no hardcoded copy), so the rendered surface can
never drift from the §11.2 contract. Three hard invariants are enforced fail-closed at render time:

  * the price_clock banner element ④ is ALWAYS shown — a missing / incomplete price_clock (any of the 4 fields
    absent or blank) refuses to render (§11.2 ④ always_shown; the reader must always see which prices/dates
    were used) AND it must pass the §21 consistency gate (engine.us_short_price_clock.validate_price_clock:
    session=RTH, real dates, price_data_through < decision_date, news_window in range) — the renderer is the
    official §11.2 output path, so a stale / same-day / future / non-RTH clock fails closed here, not just in a
    standalone helper (the machine-layer as_of/session cross-check is deferred to the pipeline that supplies it);
  * the §11.2 lifecycle-reminder count MUST match across section 1 (本周运行状态) and section 12
    (字段·模块生命周期提醒) — a mismatch refuses to render (the lifecycle 数量对账, this slice's 2c-末片);
  * every one of the 13 frozen sections must carry content — a missing section refuses to render.

The optional banner elements ①②③⑤ (always_shown=false) are shown only when present. The §11.2/§11.4/§11.5
section + banner FORMATTERS now all exist — exclusion_summary (engine.us_short_exclusion_summary
.render_exclusion_section), hot_excluded banner ⑤ (engine.us_short_hot_excluded.render_hot_excluded_banner),
observe-split banner ① (engine.us_short_observe_split.render_observe_split), coverage-honesty §11.5
(engine.us_short_coverage_honesty.render_coverage_section); ASSEMBLING their output into ``report_data`` is the
batch-4 weekly pipeline's job (this renderer stays content-agnostic). Pure / offline: formats a markdown string;
no provider/live/DataHub; no A-share crossing.
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.us_short_price_clock import PriceClockError, validate_price_clock

ROOT = Path(__file__).resolve().parent.parent
_CONTRACT_PRESET = ROOT / "presets" / "us_short_weekly_report_contract_20260620.json"

_CACHE: dict = {}


class WeeklyReportRenderError(ValueError):
    """Raised when report_data violates a §11.2 render invariant (price_clock, lifecycle count, section coverage)."""


def _contract() -> dict:
    if "contract" not in _CACHE:
        _CACHE["contract"] = json.loads(_CONTRACT_PRESET.read_text(encoding="utf-8"))
    return _CACHE["contract"]


def _int_not_bool(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _nonblank_str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _section_has_content(content) -> bool:
    """A §11.2 section body must carry NON-BLANK content: a non-blank string, or a non-empty list/tuple whose
    EVERY item is a non-blank string. An empty / whitespace-only string, an empty list, a list with a blank or
    None item, or any non-(str/list) value all render an empty body and are refused (fail-closed)."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, (list, tuple)):
        return bool(content) and all(_nonblank_str(x) for x in content)
    return False


def render_weekly_report(report_data) -> str:
    """Render the §11.2 weekly_report.md markdown from ``report_data``; returns the markdown string.

    ``report_data`` = ``{"banner": {"price_clock": {<the 4 fields>}, "<optional ①②③⑤ tag>": str, ...},
    "lifecycle_reminder_count": {"section_1": int, "section_12": int}, "sections": {"1": content, … "13":
    content}}`` where content is a str or list-of-str. The section SET/ORDER, banner elements, price_clock
    fields and the count-consistency rule come from the FROZEN contract (single source). Refuses (raises
    ``WeeklyReportRenderError``) on an incomplete always-shown price_clock, a section-1↔section-12 lifecycle
    count mismatch, or any section missing content — the renderer never emits a §11.2 surface that violates
    the frozen contract.
    """
    if not isinstance(report_data, dict):
        raise WeeklyReportRenderError("report_data must be a dict")
    contract = _contract()
    sections = contract["sections"]
    pc_fields = contract["price_clock"]["fields"]
    banner_elements = contract["mandatory_banner"]["elements"]
    cc = contract["lifecycle_reminder_count_consistency"]

    lines = ["# US-short weekly report", ""]

    # --- mandatory honest banner: ④ price_clock ALWAYS shown (fail-closed if incomplete); ①②③⑤ if present ---
    banner = report_data.get("banner")
    if not isinstance(banner, dict):
        raise WeeklyReportRenderError("report_data['banner'] must be a dict")
    price_clock = banner.get("price_clock")
    if not isinstance(price_clock, dict) or any(not _nonblank_str(price_clock.get(f)) for f in pc_fields):
        raise WeeklyReportRenderError(
            "price_clock (always-shown banner element ④) is missing / incomplete / blank — it must carry a non-blank value for all of %s" % (pc_fields,))
    try:
        # §21 fail-closed consistency gate — the renderer IS the official §11.2 output path, so it must ENFORCE the
        # clock (session=RTH, real dates, price_data_through < decision_date, news_window within range), not just
        # display it (R-USSHORT-BATCH3-PRICE-CLOCK-VALIDATOR-BYPASS-GAP). The machine-layer as_of/session
        # cross-check is deferred to the pipeline that supplies machine context (the batch-4 canonical resolver).
        validate_price_clock(price_clock)
    except PriceClockError as e:
        raise WeeklyReportRenderError("price_clock failed the §21 consistency gate: %s" % (e,))
    lines.append("## 诚实横幅")
    for el in banner_elements:
        if el["tag"] == "price_clock":
            lines.append("- %s price_clock: %s" % (el["id"], " / ".join("%s=%s" % (f, price_clock[f]) for f in pc_fields)))
        else:  # optional (always_shown=false) — shown only when supplied with a non-blank value (never blank whitespace)
            val = banner.get(el["tag"])
            if _nonblank_str(val):
                lines.append("- %s %s: %s" % (el["id"], el["tag"], val.strip()))
    lines.append("")

    # --- §11.2 lifecycle-reminder count reconcile: section_a count == section_b count (fail-closed) ---
    counts = report_data.get("lifecycle_reminder_count")
    if not isinstance(counts, dict):
        raise WeeklyReportRenderError("report_data['lifecycle_reminder_count'] must be a dict")
    a_key, b_key = "section_%d" % cc["section_number_a"], "section_%d" % cc["section_number_b"]
    a, b = counts.get(a_key), counts.get(b_key)
    if not (_int_not_bool(a) and a >= 0 and _int_not_bool(b) and b >= 0):
        raise WeeklyReportRenderError("lifecycle reminder counts %s / %s must be NON-NEGATIVE integers, got %r / %r" % (a_key, b_key, a, b))
    if cc["must_match"] and a != b:
        raise WeeklyReportRenderError(
            "§11.2 lifecycle-reminder count mismatch: section %d (%s)=%d != section %d (%s)=%d"
            % (cc["section_number_a"], sections[cc["section_number_a"] - 1], a,
               cc["section_number_b"], sections[cc["section_number_b"] - 1], b))

    # --- the 13 frozen sections in exact contract order (header = single source; body from report_data) ---
    body = report_data.get("sections")
    if not isinstance(body, dict):
        raise WeeklyReportRenderError("report_data['sections'] must be a dict keyed by section number")
    for i, title in enumerate(sections, start=1):
        content = body.get(str(i), body.get(i))
        if not _section_has_content(content):
            raise WeeklyReportRenderError("section %d (%s) has no non-blank content (every §11.2 section must carry real content)" % (i, title))
        lines.append("## %d. %s" % (i, title))
        lines.extend(str(x) for x in content) if isinstance(content, (list, tuple)) else lines.append(str(content))
        lines.append("")
    return "\n".join(lines)
