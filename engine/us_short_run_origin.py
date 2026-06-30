# -*- coding: utf-8 -*-
"""US-short weekend-pipeline execution / data-origin fact — batch4 honesty provenance (single source).

Design authority: docs/us_short_system_design.md §11 (诚实) / §18.0 / §18.2 batch4. Closes
R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP: a batch4 weekend run is ALWAYS an offline
engineering run over a CALLER-SUPPLIED fixture (live is hard-gated upstream in the orchestrator and never
reaches the official machine-record / weekly-report chain). The official artifacts must carry this fact so a
synthetic fixture run can never be mistaken for an operational, real-data weekly selection/advice artifact.

This module is the ONE immutable source of that fact + its validator + the always-visible offline disclosure
text the report renders and the private-write boundary reconciles. No provider/live/network; offline only.
"""
from __future__ import annotations

from datetime import datetime

from engine.us_short_provider_health import RUN_STATES

# the immutable batch4 execution / data-origin fact. run_mode=offline_test (live gated → batch5);
# data_origin=caller_supplied_fixture (no provider call produced any market/provider fact);
# operational_use=not_authorized (the artifacts are NOT actionable weekly advice).
OFFLINE_TEST_RUN_ORIGIN = {
    "run_mode": "offline_test",
    "data_origin": "caller_supplied_fixture",
    "operational_use": "not_authorized",
}
_REQUIRED_KEYS = frozenset(OFFLINE_TEST_RUN_ORIGIN)

# the stable always-visible offline disclosure sentinel — rendered into the weekly report (§11.2) and
# reconciled at the §18.0 private-write boundary so an offline machine record can never be written beside a
# report that omits the disclosure (machine/report mode mismatch fails closed).
OFFLINE_DISCLOSURE_SENTINEL = "⚠ 离线工程运行（OFFLINE_TEST·调用方注入 fixture·非真实数据·不可执行）"

# the STRUCTURED offline report invariants the §18.0 private-write boundary enforces on report_data (NOT a
# markdown substring): §11 provider health must carry the offline disclaimer and must NOT restore the
# operationally-authoritative phrasing; §13 must NOT claim there is no unclean item. Single source so the
# report builder (which renders these) and the private-write consumer (which re-validates) cannot drift.
OFFLINE_PROVIDER_DISCLAIMER = "offline_test 不认定运营级权威 clean"   # §11 MUST contain this
PROVIDER_AUTHORITATIVE_CLEAN_MARK = "结构化、权威"                    # §11 MUST NOT contain this (operational-authority claim)
NO_UNCLEAN_CLAIM_MARK = "本周无不 clean 项"                          # §13 MUST NOT contain this
_HONESTY_KEYS = frozenset({
    "provider_health_state", "provider_operationally_authoritative",
    "operational_use_authorized", "coverage_non_full_count",
})
OFFLINE_LIMITATION_LINE = (
    "本周不 clean 项 ①: 离线工程运行（offline_test·调用方注入 fixture），所有 provider/市场事实非真实、"
    "不可作运营周报（operational_use=not_authorized）"
)

# the EDITORIAL (caller free-text) sections an offline report carries — §4 core_conclusion, §10
# risk_downgrade_note. The report's OWN structured-authority vocabulary must not be reintroducible here, so the
# §11/§13 forbidden marks are also rejected in these caller sections (a narrow, false-positive-free guard over
# the two exact marks; the legitimate §2 portfolio_guard “结构化、权威” home is NOT an editorial section). Open-
# ended operational prose (“可执行” …) is intentionally NOT keyword-policed — the always-visible §1 banner is the
# dominant, robust disclosure; a free-text denylist would be whack-a-mole and would break legitimate narrative.
_EDITORIAL_SECTIONS = (4, 10)


class RunOriginError(ValueError):
    """The execution/data-origin fact is missing or is not the immutable offline_test fact (fail-closed)."""


def build_offline_honesty(provider_health_state, coverage_non_full_count):
    """Build the typed, closed-world honesty facts from stage outputs."""
    if provider_health_state not in RUN_STATES:
        raise RunOriginError("provider_health_state 须来自 provider-health 冻结枚举")
    if (not isinstance(coverage_non_full_count, int) or isinstance(coverage_non_full_count, bool)
            or coverage_non_full_count < 0):
        raise RunOriginError("coverage_non_full_count 须为非负 int")
    return {
        "provider_health_state": provider_health_state,
        "provider_operationally_authoritative": False,
        "operational_use_authorized": False,
        "coverage_non_full_count": coverage_non_full_count,
    }


def canonical_offline_sections(honesty):
    """Recompute the only permitted §11/§13 section bodies from typed honesty facts."""
    if not isinstance(honesty, dict) or set(honesty) != _HONESTY_KEYS:
        raise RunOriginError("offline_honesty 须为 closed-world typed object")
    expected = build_offline_honesty(
        honesty.get("provider_health_state"), honesty.get("coverage_non_full_count"))
    if honesty != expected:
        raise RunOriginError("offline_honesty 不得授权运营权威或运营使用")
    count = honesty["coverage_non_full_count"]
    s11 = ["数据源健康: provider_health=%s（离线 fixture 自报；%s，非真实 provider 调用）"
           % (honesty["provider_health_state"], OFFLINE_PROVIDER_DISCLAIMER)]
    s13 = [OFFLINE_LIMITATION_LINE]
    if count:
        s13.append("② 本周 %d 行覆盖非 full（partial/restricted/blocked），明细见 §6 持仓覆盖诚实度节" % count)
    return s11, s13


# §1 is the SYSTEM-OWNED authoritative run-status section, part of the required provenance surface — it must be
# exactly the canonical offline disclosure lines + ONE validated run-status line (no extra/reordered prose can be
# slipped in after the sentinel). The dynamic counts/date are a closed-world typed object, recomputed independently
# at the consumer boundary so a “补充声明：…真实 provider…可直接执行” line cannot ride through byte equality.
_RUN_STATUS_KEYS = frozenset({
    "decision_date", "build_count", "observe_count", "holding_count",
    "candidate_count", "lifecycle_reminder_count",
})
_RUN_STATUS_COUNT_KEYS = ("build_count", "observe_count", "holding_count", "candidate_count", "lifecycle_reminder_count")


def _real_yyyymmdd(value):
    if not (isinstance(value, str) and len(value) == 8 and value.isascii() and value.isdigit()):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
        return True
    except ValueError:
        return False


def build_run_status(decision_date, build_count, observe_count, holding_count, candidate_count,
                     lifecycle_reminder_count):
    """Build the typed, closed-world §1 run-status facts from stage outputs (real YYYYMMDD + non-negative counts)."""
    if not _real_yyyymmdd(decision_date):
        raise RunOriginError("run_status.decision_date 须为真实 YYYYMMDD")
    status = {"decision_date": decision_date, "build_count": build_count, "observe_count": observe_count,
              "holding_count": holding_count, "candidate_count": candidate_count,
              "lifecycle_reminder_count": lifecycle_reminder_count}
    for k in _RUN_STATUS_COUNT_KEYS:
        v = status[k]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise RunOriginError(f"run_status.{k} 须为非负 int")
    return status


def canonical_section_1(origin, run_status):
    """Recompute the only permitted §1 body = the two offline disclosure lines + ONE run-status line, from the
    immutable run_origin + the typed run_status. Any extra/reordered §1 prose fails the consumer equality check."""
    if not isinstance(run_status, dict) or set(run_status) != _RUN_STATUS_KEYS:
        raise RunOriginError("run_status 须为 closed-world typed object")
    rs = build_run_status(run_status.get("decision_date"), run_status.get("build_count"),
                          run_status.get("observe_count"), run_status.get("holding_count"),
                          run_status.get("candidate_count"), run_status.get("lifecycle_reminder_count"))
    status_line = ("本周运行状态: decision_date=%s; 建仓 %d / 观察 %d / 持仓 %d / 候选 %d; lifecycle 提醒 %d 项"
                   % (rs["decision_date"], rs["build_count"], rs["observe_count"], rs["holding_count"],
                      rs["candidate_count"], rs["lifecycle_reminder_count"]))
    return offline_disclosure_lines(origin) + [status_line]


def _section_text(sections, n):
    """Join one report_data section (keyed by int or str; content = str or list-of-str) into one string."""
    content = sections.get(n, sections.get(str(n))) if isinstance(sections, dict) else None
    if isinstance(content, (list, tuple)):
        return "\n".join(str(x) for x in content)
    return "" if content is None else str(content)


def assert_offline_report_invariants(report_data, origin):
    """Fail-closed STRUCTURED validation of a weekly report_data's offline provenance (the private-write
    consumer boundary, R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP round-1 FAIL): report_data must
    carry the matching run_origin, §1 must show the offline sentinel, §11 must carry the offline disclaimer and
    NOT the operational-authority phrasing, and §13 must NOT claim there is no unclean item — so a renderer-valid
    report that KEEPS the §1 sentinel but RESTORES a “provider 权威 clean” / “本周无不 clean” surface fails closed."""
    validate_run_origin(origin)
    if not isinstance(report_data, dict):
        raise RunOriginError("report_data 须为 dict")
    if report_data.get("run_origin") != origin:
        raise RunOriginError("report_data.run_origin 与本次 run_origin 不一致（offline 来源对账失败）")
    sections = report_data.get("sections")
    if not isinstance(sections, dict):
        raise RunOriginError("report_data.sections 须为 dict")
    # §1 is system-owned: it must be EXACTLY the canonical disclosure lines + one typed run-status line, not merely
    # "contains the sentinel" — else an operational-authority line can be appended after the retained sentinel.
    expected_s1 = canonical_section_1(origin, report_data.get("run_status"))
    actual_s1 = sections.get(1, sections.get("1"))
    if actual_s1 != expected_s1:
        raise RunOriginError("§1 必须完全由 run_origin + typed run_status canonical 渲染（禁额外运营/权威声明行）")
    expected_s11, expected_s13 = canonical_offline_sections(report_data.get("offline_honesty"))
    actual_s11 = sections.get(11, sections.get("11"))
    actual_s13 = sections.get(13, sections.get("13"))
    if actual_s11 != expected_s11:
        raise RunOriginError("§11 必须完全由 offline_honesty canonical 渲染（禁额外/同义权威声明）")
    if actual_s13 != expected_s13:
        raise RunOriginError("§13 必须完全由 offline_honesty canonical 渲染（禁同义运营 clean 声明）")
    # the report's own structured-authority marks must not reappear in the editorial caller sections (§4/§10),
    # so an offline report cannot undercut its §1/§11/§13 disclosure with copied “结构化、权威” / “本周无不 clean” prose.
    for n in _EDITORIAL_SECTIONS:
        txt = _section_text(sections, n)
        if PROVIDER_AUTHORITATIVE_CLEAN_MARK in txt or NO_UNCLEAN_CLAIM_MARK in txt:
            raise RunOriginError(
                "§%d 编辑段不得含结构化权威/无不clean 运营声明（与 §1 离线披露矛盾）" % n)
    return report_data


def validate_run_origin(origin):
    """Fail-closed: the run_origin MUST be exactly the immutable offline_test / caller_supplied_fixture /
    not_authorized fact (closed-world keys + exact values). Returns the validated dict; raises otherwise."""
    if not isinstance(origin, dict):
        raise RunOriginError("run_origin 须为 dict")
    if set(origin) != _REQUIRED_KEYS:
        raise RunOriginError(
            f"run_origin 顶层键须恰为 {sorted(_REQUIRED_KEYS)}（closed-world）: {sorted(origin)}")
    if origin != OFFLINE_TEST_RUN_ORIGIN:
        raise RunOriginError(
            "run_origin 须为不可变 offline_test 事实 "
            f"{OFFLINE_TEST_RUN_ORIGIN}（batch4 离线·调用方 fixture·非运营）")
    return origin


def run_origin_for_mode(run_mode):
    """The data-origin fact for a batch4 run. batch4 only ever reaches the official chain in `offline_test`
    (live is hard-gated upstream); any other mode here is a wiring bug and fails closed."""
    if run_mode != "offline_test":
        raise RunOriginError(
            f"batch4 官方链只在 offline_test 产出 artifact（live 由 orchestrator 硬阻断）: run_mode={run_mode!r}")
    return dict(OFFLINE_TEST_RUN_ORIGIN)


def offline_disclosure_lines(origin):
    """The always-visible offline/fixture disclosure lines for the weekly report (§11.2). The first line is the
    stable sentinel the private-write boundary checks; the second spells out the immutable fact."""
    validate_run_origin(origin)
    return [
        OFFLINE_DISCLOSURE_SENTINEL,
        "本表所有市场/provider 事实均为调用方注入的 fixture（run_mode=%s, data_origin=%s, operational_use=%s）；"
        "非真实数据、非真实 provider 调用，不构成可执行的周度选股/建议" % (
            origin["run_mode"], origin["data_origin"], origin["operational_use"]),
    ]
