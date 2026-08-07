"""Knife 7b-iii — the one call the official weekly task makes into the diagnostic track.

Design section 12.8 duty 4 asks the weekly task to read the v1.1 lifecycle state
by itself, remind while it is pending, and call Knife 6 automatically once it is
active — explicitly "不依赖人工记忆". Nothing did: ``v1_1_attribution`` had zero
readers outside the store that writes it, so the automatic activation this track
designed was automatic only in the sense that nobody would ever notice it.

Three properties this module is built around:

* **Dormant is free.** When no clock has been opened the step returns
  ``not_started`` and contributes nothing — no lines, no files, no work. The
  weekly report must be byte-identical to what it is today, and that is asserted
  rather than assumed.
* **Broken is loud.** A store that cannot be read is reported as ``broken`` with
  its reason, never swallowed into "nothing to say". Silence and breakage looking
  alike is the failure this track keeps finding in itself.
* **Missing inputs degrade, they do not block.** With v1.1 active but the target
  exposure or PIT cash return absent, Knife 6 is still called and returns
  explicit ``unavailable`` weeks. No zero fill, no substituted rate, and no
  request for the operator to do something by hand.

The attribution report is returned, not stored: it is a pure function of the
already-persisted weekly records, so it can be recomputed at any time and a
second copy would just be one more thing that can disagree with the store.

Nothing here calls a provider, writes the model-paper account, or changes
selection, action, sizing or NAV.
"""
from __future__ import annotations

from datetime import date as _date
from pathlib import Path
from typing import Any, Mapping, Sequence

from engine.us_short_market_diagnostic_attribution import (
    AttributionError,
    build_attribution_input,
    build_attribution_report,
)
from engine.us_short_market_diagnostic_lifecycle import (
    DEFAULT_ROOT,
    REPORT_REMINDER_SECTION,
    render_weekly_report_reminder,
)
from engine.us_short_market_diagnostic_weekly_producer import diagnostic_store_state

# The registered reminder block says where it lives: `build_weekly_report_reminder`
# publishes `section_number`, and that is the section the lines are spliced into.
# Design section 1.3 allows the diagnostic track to change exactly ONE thing in the
# weekly report — that registered block — and forbids adding a free-text banner of
# its own, so the home is read from the registration rather than chosen here.
_REMINDER_SECTION_HEADER_PREFIX = "## %d. " % REPORT_REMINDER_SECTION
_SECTION_HEADER_PREFIX = "## "


class WeeklyReportSpliceError(Exception):
    """The weekly report cannot carry the registered reminder block."""


def weekly_diagnostic_step(
    *,
    root: str | Path = DEFAULT_ROOT,
    as_of_date: str | None = None,
    target_exposure_by_week: Mapping[int, Mapping[str, Any]] | None = None,
    cash_return_by_week: Mapping[int, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """What the weekly task should say and do about the diagnostic track this week.

    Returns a dict whose ``report_lines`` is always a list — empty whenever the
    caller must add nothing — so a host can splice it in unconditionally without
    having to remember a dormancy check of its own.

    ``as_of_date`` defaults to today rather than to ``None``. Left unset it
    reached four public attribution entries with their look-ahead guard switched
    off, so a week dated 2099 would have been summarised without complaint. Both
    current callers pass one; the default is what protects the next caller.
    """

    if as_of_date is None:
        as_of_date = _date.today().strftime("%Y%m%d")
    state = diagnostic_store_state(root, as_of_date=as_of_date)
    if state["state"] == "not_started":
        return {"status": "not_started", "report_lines": [], "attribution": None}
    if state["state"] == "fresh":
        # A clock opened this week with no settled week yet is not a fault. Saying
        # "broken" here was how an operator would be taught to ignore the word.
        return {
            "status": "fresh",
            "diagnostic_epoch": state["receipt"]["diagnostic_epoch"],
            "calendar_week_count": 0,
            "report_lines": ["26 周诊断轨：时钟已开，等待本周第一次记账。"],
            "attribution": None,
        }
    if state["state"] == "broken":
        return {
            "status": "broken",
            "problem": state["problem"],
            "report_lines": [
                "26 周诊断轨：账本无法读取，已积累的周数暂不可知；这是故障，不是「尚未开始」。"
            ],
            "attribution": None,
        }

    register = state["register"]
    records = state["records"]
    lines = [render_weekly_report_reminder(register)]
    attribution_state = register["v1_1_attribution"]
    result: dict[str, Any] = {
        "status": "running",
        "diagnostic_epoch": register["diagnostic_epoch"],
        "calendar_week_count": register["calendar_week_count"],
        "v1_1_status": attribution_state["status"],
        "attribution": None,
    }

    if attribution_state["status"] == "active":
        try:
            packet = build_attribution_input(
                records,
                attribution_epoch=attribution_state["attribution_epoch"],
                target_exposure_by_week=target_exposure_by_week,
                cash_return_by_week=cash_return_by_week,
                as_of_date=as_of_date,
            )
            report = build_attribution_report(packet, as_of_date=as_of_date)
        except AttributionError as exc:
            # A refused packet is a FAULT, and it must not be phrased like the
            # ordinary missing-input degradation two branches below. Knife 6 can
            # refuse for structural reasons that have nothing to do with data
            # availability — the 256-digest ceiling being the known one — and
            # "已记为不可用" would read as "we are still waiting for prices" while
            # the module was in fact unable to run at all. It still never fails
            # the weekly task: the diagnostic track may not block selection.
            result["attribution_error"] = str(exc)
            result["v1_1_status"] = "attribution_faulted"
            lines.append(
                "v1.1 归因：**计算本身失败**（不是缺数据），本周无归因结果；"
                f"原因：{exc}。不影响选股与操作建议。"
            )
        else:
            result["attribution"] = report
            summary = report["summary"]
            if report["status"] == "unavailable":
                lines.append(
                    f"v1.1 归因：{summary['evaluable_weeks']}/{summary['calendar_weeks']} 周可评估，"
                    "其余缺 VTI 总收益、PIT 现金收益或 g*，按不可用记录，不补零。"
                )
            else:
                lines.append(
                    "v1.1 归因：全部 %d 周可评估；raw_excess=%.4f = 仓位效果 %.4f + 主动系统效果 %.4f。"
                    % (
                        summary["calendar_weeks"],
                        summary["raw_excess"],
                        summary["exposure_effect"],
                        summary["active_system_effect"],
                    )
                )

    result["report_lines"] = lines
    return result


def splice_diagnostic_report_lines(report_path: str | Path, lines: Sequence[str]) -> bool:
    """Put this week's diagnostic lines into the weekly report's registered section.

    Until this existed, every state above computed ``report_lines`` and nothing in
    the repository ever read one: the clock could run for 26 weeks and the weekly
    report would never mention it, while design sections 5.2 and 13 both require
    the opposite — the X/4 pending reminder from calendar week one, and the
    accumulated state exposed through the *registered* block rather than through
    prose somebody remembered to write.

    With no lines this does not open the file at all. A dormant week must leave
    the report byte-identical, and never touching it is a stronger guarantee than
    rewriting it with the same bytes.

    Returns True when the report was rewritten. Raises ``WeeklyReportSpliceError``
    rather than writing into a report whose registered section it cannot find —
    a caller that cannot show the reminder must say so, not put it somewhere else.
    """

    if not lines:
        return False
    path = Path(report_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WeeklyReportSpliceError(f"the weekly report cannot be read: {exc}") from exc
    body = text.splitlines()
    headers = [
        index
        for index, line in enumerate(body)
        if line.startswith(_REMINDER_SECTION_HEADER_PREFIX)
    ]
    if len(headers) != 1:
        raise WeeklyReportSpliceError(
            f"the weekly report carries {len(headers)} section-{REPORT_REMINDER_SECTION} headers, "
            "so there is no one registered block to write into"
        )
    start = headers[0]
    end = next(
        (
            index
            for index in range(start + 1, len(body))
            if body[index].startswith(_SECTION_HEADER_PREFIX)
        ),
        len(body),
    )
    # Land after the section's own content and before the blank line that closes
    # it, so the block reads as part of section 12 rather than as an orphan
    # paragraph pushed against the next heading.
    while end > start + 1 and not body[end - 1].strip():
        end -= 1
    body[end:end] = list(lines)
    rewritten = "\n".join(body) + ("\n" if text.endswith("\n") else "")
    temporary = path.with_name(f".{path.name}.market-diagnostic.tmp")
    temporary.write_text(rewritten, encoding="utf-8")
    temporary.replace(path)
    return True


__all__ = [
    "WeeklyReportSpliceError",
    "splice_diagnostic_report_lines",
    "weekly_diagnostic_step",
]
