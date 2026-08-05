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

from pathlib import Path
from typing import Any, Mapping

from engine.us_short_market_diagnostic_attribution import (
    AttributionError,
    build_attribution_input,
    build_attribution_report,
)
from engine.us_short_market_diagnostic_lifecycle import (
    DEFAULT_ROOT,
    MarketDiagnosticLifecycleError,
    load_lifecycle_register,
    load_settled_weekly_records,
    render_weekly_report_reminder,
)
from engine.us_short_market_diagnostic_start_receipt import (
    DiagnosticStartReceiptError,
    load_start_receipt,
)
from engine.us_short_market_diagnostic_weekly_producer import register_exists


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
    """

    try:
        receipt = load_start_receipt(root, verify_design_against_disk=False)
    except DiagnosticStartReceiptError as exc:
        return {
            "status": "broken",
            "problem": str(exc),
            "report_lines": [
                "26 周诊断轨：起始收据无法读取，本周未记账；这是故障，不是「尚未开始」。"
            ],
            "attribution": None,
        }
    if receipt is None:
        if register_exists(root):
            # Counted weeks with no receipt is destroyed evidence, and it reads
            # exactly like a clean slate unless something says otherwise.
            return {
                "status": "broken",
                "problem": "weeks have been counted but the start receipt that authorized them is gone",
                "report_lines": [
                    "26 周诊断轨：已记过周，但授权它们的起始收据不见了；这是故障，不是「尚未开始」。"
                ],
                "attribution": None,
            }
        return {"status": "not_started", "report_lines": [], "attribution": None}

    try:
        register = load_lifecycle_register(root, as_of_date=as_of_date)
        records = load_settled_weekly_records(root, as_of_date=as_of_date)
    except MarketDiagnosticLifecycleError as exc:
        return {
            "status": "broken",
            "problem": str(exc),
            "report_lines": [
                "26 周诊断轨：账本无法读取，已积累的周数暂不可知；这是故障，不是「尚未开始」。"
            ],
            "attribution": None,
        }

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


__all__ = ["weekly_diagnostic_step"]
