# -*- coding: utf-8 -*-
"""US-short weekend-pipeline idempotent private write — batch4 slice 4d-ii-n (§18.0 P0 private-path 守卫).

Design authority: docs/us_short_system_design.md §11.1 (机器层 → runs_private; weekly_report.md + action_table.csv
→ weekly_private) / §11.6 (输出路径护栏: 所有 private 目录 gitignored) / §18.0 P0 (private-path fail-closed guard) /
§18.1 #1 / §2.1 (canonical decision_date / 幂等不重复) / §18.2 batch4 slice 4d.

The post-pass after 4d-ii-k (machine record) + 4d-ii-m1 (action_table) + 4d-ii-m2 (weekly_report). It PERSISTS
the run's official artifacts to the GITIGNORED private dirs, fail-closed behind the §18.0 P0 private-path guard
(these artifacts carry tickers / entry / stop / size / holdings and MUST NOT land on a tracked path):

  * the machine layer (the §10 record flattened to the §11.3 columns — 全字段 + 原始分数 + decision_trace +
    registry, §11.1) → `state/us_short/runs_private/<decision_date>/machine_record.json`;
  * the §11.1 weekly_private surface — ONLY `weekly_report.md` (4d-ii-m2) + `action_table.csv` (rendered from the
    flattened record) → `state/us_short/weekly_private/<decision_date>/`. Nothing else lands in weekly_private
    (no design / test / debug / decision-packet / run-summary / raw data, §11.1).

EVERY write goes through `engine.us_short_private_paths.reject_nonprivate_output_path` (§18.0 P0) BEFORE any file
side effect — a relative / non-gitignored in-repo destination is refused, and a git-check failure is also refused
(privacy unprovable). Idempotent by `decision_date` (§2.1 重跑不重复计数): the per-decision-date dir is the key,
so re-running the same decision_date OVERWRITES the artifacts (a write, never an append) — no double-count.

Multi-artifact source-reconciliation (the recurring batch4 lesson — a boundary holding several official artifacts
must prove they belong to the SAME run): the machine record is flattened through the m1 §10/§6 gate, the run's
`decision_date` must equal `machine_record.as_of` (§2.1 single canonical decision_date), and the weekly_report
must carry that decision_date as the singleton date token in its rendered price-clock banner ④ (a cross-week or
ambiguous report is refused). Pure/offline beyond
the private file writes; no provider/live/network/DataHub; no broker/auto-order; no A-share crossing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from engine.us_short_action_table_renderer import write_action_table
from engine.us_short_lifecycle_readiness import _assert_readiness
from engine.us_short_private_paths import reject_nonprivate_output_path
from engine.us_short_provider_health import validate_provider_health_result
from engine.us_short_run_origin import (
    OFFLINE_TEST_RUN_ORIGIN,
    assert_offline_report_invariants,
    require_research_live_capability,
    validate_run_origin,
)
from engine.us_short_weekend_action_table import flatten_machine_record
from engine.us_short_weekend_report import (
    canonical_lifecycle_section,
    reconcile_holding_coverage,
    report_row_groups,
)
from engine.us_short_weekly_report_renderer import render_weekly_report

ROOT = Path(__file__).resolve().parent.parent
RUNS_PRIVATE_ROOT = ROOT / "state" / "us_short" / "runs_private"      # machine layer (§11.1, gitignored)
WEEKLY_PRIVATE_ROOT = ROOT / "state" / "us_short" / "weekly_private"  # weekly_report.md + action_table.csv (§11.1)
_REPORT_CONTRACT_PATH = ROOT / "presets" / "us_short_weekly_report_contract_20260620.json"

# §11.1: weekly_private/<dd>/ holds ONLY these two official files — any pre-existing extra file/dir fails closed.
_OFFICIAL_WEEKLY_FILES = frozenset({"weekly_report.md", "action_table.csv"})
# the rendered §11.2 price-clock banner ④ line — only a line STARTING with this prefix is the real
# banner (render_weekly_report emits exactly one such line; editorial content with "price_clock:" elsewhere
# in the body must not be counted as a second banner line).
_PRICE_CLOCK_PREFIX = "- ④ price_clock:"
_PRICE_CLOCK_DECISION_DATE = re.compile(r"decision_date=(\d{8})")
_REPORT_TITLE = "# US-short weekly report"
_BANNER_TITLE = "## 诚实横幅"


class WeekendPrivateWriteError(Exception):
    """The run artifacts are malformed / cross-week, or a destination is not provably private (fail-closed)."""


def _write_text_private(path, text):
    """§18.0 P0: refuse to write unless the path is provably private (the guard runs BEFORE any file side
    effect — mkdir included), then write the text. Returns the written Path."""
    reject_nonprivate_output_path(path)   # §18.0 P0 guard — before mkdir / write (raises PrivatePathError)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _report_sections():
    return json.loads(_REPORT_CONTRACT_PATH.read_text(encoding="utf-8"))["sections"]


def _validate_weekly_report_surface(weekly_report_md):
    """Refuse non-renderer-like markdown before private persistence.

    Private-write is intentionally the last artifact boundary. The upstream renderer owns exact content, but this
    boundary must still prove it is persisting the official §11.2 surface, not an arbitrary markdown string with a
    spoofed price-clock line. The renderer surface has one title, one honest banner, and the frozen 13 section
    headers in order.
    """
    lines = [ln.strip() for ln in weekly_report_md.splitlines()]
    if lines.count(_REPORT_TITLE) != 1 or _REPORT_TITLE not in lines[:2]:
        raise WeekendPrivateWriteError("weekly_report_md 必须是渲染器输出：须含唯一 '# US-short weekly report' 标题")
    if lines.count(_BANNER_TITLE) != 1:
        raise WeekendPrivateWriteError("weekly_report_md 必须是渲染器输出：须含唯一 '## 诚实横幅'")
    expected_headers = ["## %d. %s" % (i, title) for i, title in enumerate(_report_sections(), start=1)]
    positions = []
    for header in expected_headers:
        if lines.count(header) != 1:
            raise WeekendPrivateWriteError("weekly_report_md 必须是完整 §11.2 周报：缺失或重复节标题 %r" % header)
        positions.append(lines.index(header))
    if positions != sorted(positions):
        raise WeekendPrivateWriteError("weekly_report_md §11.2 节标题顺序必须与冻结 contract 一致")
    allowed_h2 = {_BANNER_TITLE, *expected_headers}
    extra_h2 = [ln for ln in lines if ln.startswith("## ") and ln not in allowed_h2]
    if extra_h2:
        raise WeekendPrivateWriteError("weekly_report_md 含非冻结 §11.2 二级节标题: %s" % extra_h2)


def _reconcile_official_source_facts(flat, report_data, decision_date, *, provider_health, coverage_inputs,
                                     lifecycle_result):
    """R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP (strict full re-review): canonical §1/§11/§13 + byte
    equality only prove the PROSE matches report_data's typed run_status / offline_honesty — those objects are
    caller-controlled at this persistence boundary. So INDEPENDENTLY re-derive the run_status counts from the
    validated machine record, bind the lifecycle count to the independent re-validated lifecycle stage result
    (NOT another report_data field — a coordinated all-copies forge must still fail), and bind provider-health +
    coverage to the RUN-LEVEL sources (which cannot be replaced inside report_data). A forged build/observe/
    holding/candidate/lifecycle/provider/coverage value fails closed here with NO write."""
    run_status = report_data.get("run_status") if isinstance(report_data, dict) else None
    offline_honesty = report_data.get("offline_honesty") if isinstance(report_data, dict) else None
    if not (isinstance(run_status, dict) and isinstance(offline_honesty, dict)):
        raise WeekendPrivateWriteError("report_data 缺 run_status/offline_honesty（源对账失败，拒写，无落盘）")
    # (1) build/observe/holding/candidate counts RE-DERIVED from the validated machine record (NOT report_data).
    groups = report_row_groups(flat.get("rows", []))
    expected = {"build_count": len(groups["builds"]), "observe_count": len(groups["observes"]),
                "holding_count": len(groups["holdings"]), "candidate_count": len(groups["selected"])}
    for key, want in expected.items():
        if run_status.get(key) != want:
            raise WeekendPrivateWriteError(
                f"run_status.{key}={run_status.get(key)!r} 与机器记录重算 {want} 不符（疑伪造计数，拒写，无落盘）")
    if run_status.get("decision_date") != decision_date:
        raise WeekendPrivateWriteError(
            f"run_status.decision_date={run_status.get('decision_date')!r} != {decision_date!r}（拒写，无落盘）")
    # (2) lifecycle count bound to the INDEPENDENT lifecycle stage result (NOT another report_data field): the
    # readiness is re-validated by the single-source `_assert_readiness` (due_count == len(due_items) + item ids
    # in range + upgrade ⊆ due), then ALL THREE caller-controlled lifecycle copies (run_status + §1/§12) must
    # equal that independent due_count — a COORDINATED all-copies forge fails because the real due_count cannot
    # be replaced inside report_data (Codex strict source-binding re-review: lifecycle all-copies spoof).
    if not (isinstance(lifecycle_result, dict) and isinstance(lifecycle_result.get("readiness"), dict)):
        raise WeekendPrivateWriteError("lifecycle_result 须为含 readiness(dict) 的 4d-ii-l 输出（独立 lifecycle 源缺失，拒写，无落盘）")
    readiness = lifecycle_result["readiness"]
    try:
        _assert_readiness(readiness)
    except Exception as exc:
        raise WeekendPrivateWriteError(f"lifecycle_result.readiness 非内部一致（独立 lifecycle 源校验失败，拒写，无落盘）: {exc}")
    # the lifecycle source must BELONG to this run: a valid lifecycle result for another date is not this run's.
    if lifecycle_result.get("decision_date") != decision_date or readiness.get("as_of") != decision_date:
        raise WeekendPrivateWriteError(
            f"lifecycle_result 不属于本 run（decision_date={lifecycle_result.get('decision_date')!r} / "
            f"readiness.as_of={readiness.get('as_of')!r} != {decision_date!r}，拒写，无落盘）")
    due_count = readiness["due_count"]
    lrc = report_data.get("lifecycle_reminder_count")
    if not (isinstance(lrc, dict) and lrc.get("section_1") == due_count and lrc.get("section_12") == due_count
            and run_status.get("lifecycle_reminder_count") == due_count):
        raise WeekendPrivateWriteError(
            f"lifecycle 计数与独立 lifecycle 源 due_count={due_count} 不一致（run_status/§1/§12 须全等，疑协同伪造，拒写，无落盘）")
    # §12 DETAIL (due-item / upgrade identities, not only the count) must equal the canonical projection of the
    # validated readiness — a same-count / different-due-items or different-upgrade forge fails closed.
    sections = report_data.get("sections")
    s12 = sections.get(12, sections.get("12")) if isinstance(sections, dict) else None
    if s12 != canonical_lifecycle_section(readiness):
        raise WeekendPrivateWriteError(
            "report §12 生命周期明细与独立 lifecycle 源 canonical 投影不符（疑伪造 due-item/upgrade，拒写，无落盘）")
    # (3) provider-health bound to the RUN-LEVEL classifier result (not report_data): revalidate its exact
    # internal-consistent shape, then require offline_honesty.provider_health_state == its overall_run_state.
    if not validate_provider_health_result(provider_health):
        raise WeekendPrivateWriteError("provider_health 非内部一致的 classify 结果（运行级源校验失败，拒写，无落盘）")
    if offline_honesty.get("provider_health_state") != provider_health["overall_run_state"]:
        raise WeekendPrivateWriteError(
            "offline_honesty.provider_health_state 与运行级 provider 健康源不符（疑伪造，拒写，无落盘）")
    # (4) coverage_non_full_count bound to validated holding coverage (coverage_inputs reconciled 1:1 to the
    # machine holding rows via the report's single-source helper, independent of report_data).
    try:
        coverage_records = reconcile_holding_coverage(groups["holdings"], coverage_inputs)
    except Exception as exc:
        raise WeekendPrivateWriteError(f"coverage 源对账失败（拒写，无落盘）: {exc}")
    non_full = sum(1 for c in coverage_records if c.get("coverage_status") != "full")
    if offline_honesty.get("coverage_non_full_count") != non_full:
        raise WeekendPrivateWriteError(
            f"offline_honesty.coverage_non_full_count={offline_honesty.get('coverage_non_full_count')!r} "
            f"与持仓覆盖重算 {non_full} 不符（拒写，无落盘）")


def write_run_private(*, decision_date, machine_record, weekly_report_md, report_data,
                      provider_health, coverage_inputs, lifecycle_result,
                      runs_private_root=None, weekly_private_root=None,
                      run_origin=OFFLINE_TEST_RUN_ORIGIN, research_live_capability=None) -> dict:
    """4d-ii-n idempotent private write. Persists the run's machine layer + §11.1 weekly_private surface to the
    gitignored private dirs, fail-closed behind the §18.0 P0 private-path guard, keyed (idempotent) by decision_date.

    decision_date = the run's canonical decision_date (the per-run private dir key).
    machine_record = the 4d-ii-k `assemble_machine_record` output (flattened here via slice m1).
    weekly_report_md = the 4d-ii-m2 `build_weekly_report` weekly_report markdown.
    report_data = the 4d-ii-m2 `build_weekly_report` STRUCTURED report_data — the boundary re-validates its offline
        provenance (run_origin three-way + §1/§11/§13 invariants) and requires render(report_data)==weekly_report_md
        (R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP: structured provenance, not a markdown substring).
    provider_health = the RUN-LEVEL `classify_provider_health` result the run used; revalidated here and bound to
        report_data.offline_honesty.provider_health_state (a run-level source that cannot be replaced inside report_data).
    coverage_inputs = the run's holding coverage inputs; reconciled 1:1 to the machine holding rows and bound to
        report_data.offline_honesty.coverage_non_full_count (R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP).
    lifecycle_result = the 4d-ii-l lifecycle stage result; re-validated here (readiness internal consistency +
        decision_date / readiness.as_of == this run) as the INDEPENDENT source the three lifecycle count copies
        (run_status + §1/§12) AND the §12 due-item/upgrade detail must match — so a coordinated count forge, a
        cross-date lifecycle result, or a same-count detail forge all fail closed.
    runs_private_root / weekly_private_root = override the default private roots (tests / an external private
        location); a relative / non-gitignored in-repo destination is refused by the §18.0 guard.

    Returns {"machine_record_path", "action_table_path", "weekly_report_path"} (the written Paths). Raises
    WeekendPrivateWriteError on a blank weekly_report, a decision_date that disagrees with machine_record.as_of
    or the weekly_report's rendered price-clock banner (§2.1 same-run reconciliation), or — via the §18.0 guard /
    `WeekendActionTableError` — a non-private destination / malformed machine record."""
    require_research_live_capability(run_origin, research_live_capability)   # consumer-layer honesty gate (Required A) — first
    if not (isinstance(weekly_report_md, str) and weekly_report_md.strip()):
        raise WeekendPrivateWriteError("weekly_report_md 须为非空 str")
    _validate_weekly_report_surface(weekly_report_md)
    # flatten through the m1 §10/§6 gate (validates the machine record + projects the §11.3 columns).
    flat = flatten_machine_record(machine_record)   # raises WeekendActionTableError on a malformed record
    # §2.1 same-run reconciliation: the machine layer + the run's decision_date must be one run.
    if flat.get("as_of") != decision_date:
        raise WeekendPrivateWriteError(
            f"decision_date {decision_date!r} != machine_record.as_of {flat.get('as_of')!r}（§2.1 同一 run）")
    # the official weekly_report's RENDERED price-clock banner ④ must be for THIS decision_date — parse the actual
    # rendered price_clock banner line (exactly one, render_weekly_report emits one), NOT an arbitrary substring,
    # so an incidental old/new `decision_date=` elsewhere in the body cannot spoof a cross-week report (§2.1 同一 run).
    pc_lines = [ln for ln in weekly_report_md.splitlines() if ln.strip().startswith(_PRICE_CLOCK_PREFIX)]
    if len(pc_lines) != 1:
        raise WeekendPrivateWriteError(f"weekly_report_md 须恰含 1 行 price-clock 横幅 ④（实得 {len(pc_lines)} 行）")
    pc_line = pc_lines[0].strip()
    if not pc_line.startswith(_PRICE_CLOCK_PREFIX):
        raise WeekendPrivateWriteError("weekly_report_md 的 price-clock 必须是渲染器输出的横幅 ④ 行")
    dates = _PRICE_CLOCK_DECISION_DATE.findall(pc_line)
    if len(dates) != 1 or dates[0] != decision_date:
        raise WeekendPrivateWriteError(
            f"weekly_report price-clock decision_date {dates if dates else None!r} != {decision_date!r}（疑跨周/歧义周报）")

    # batch4 honesty provenance (R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP, round-1 FAIL): the
    # persistence boundary validates STRUCTURED report provenance, not a markdown substring. Runs AFTER the
    # flatten/§10 gate (a malformed record surfaces its own typed error first) and before any write:
    #   (1) machine record + report_data + run_origin all carry the SAME immutable offline fact (three-way);
    #   (2) the §1/§11/§13 offline invariants hold on report_data — so a renderer-valid report that keeps the §1
    #       sentinel but restores a “provider 权威 clean” / “本周无不 clean” surface fails closed;
    #   (3) re-render report_data and require BYTE EQUALITY with weekly_report_md — so a hand-edited markdown
    #       string that no longer matches the structured data is rejected.
    validate_run_origin(run_origin)
    if (machine_record.get("run_origin") if isinstance(machine_record, dict) else None) != run_origin:
        raise WeekendPrivateWriteError(
            "machine_record.run_origin 与本次 run_origin 不一致（offline/fixture 来源对账失败，拒写，无落盘）")
    try:
        assert_offline_report_invariants(report_data, run_origin)   # report_data.run_origin == run_origin + §1/§11/§13
    except ValueError as exc:
        raise WeekendPrivateWriteError(f"report_data 离线 provenance 不变式失败（拒写，无落盘）: {exc}")
    if render_weekly_report(report_data) != weekly_report_md:
        raise WeekendPrivateWriteError(
            "weekly_report_md 与 report_data 重渲染不一致（疑手改 markdown，拒写，无落盘）")
    # source-fact reconciliation (R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP strict full re-review):
    # re-derive run_status counts from the machine record + bind provider-health/coverage/lifecycle to run-level
    # sources, so a caller-forged report_data.run_status / offline_honesty value cannot ride byte-equality.
    _reconcile_official_source_facts(flat, report_data, decision_date,
                                     provider_health=provider_health, coverage_inputs=coverage_inputs,
                                     lifecycle_result=lifecycle_result)

    runs_root = Path(runs_private_root) if runs_private_root is not None else RUNS_PRIVATE_ROOT
    weekly_root = Path(weekly_private_root) if weekly_private_root is not None else WEEKLY_PRIVATE_ROOT
    runs_dir, weekly_dir = runs_root / decision_date, weekly_root / decision_date
    machine_path, action_path = runs_dir / "machine_record.json", weekly_dir / "action_table.csv"
    report_path = weekly_dir / "weekly_report.md"

    # PREFLIGHT every destination with the §18.0 P0 guard BEFORE any directory / file is created, so a mixed
    # valid/invalid set of roots leaves NO partial private run (atomic fail-closed for the guard case).
    for p in (machine_path, action_path, report_path):
        reject_nonprivate_output_path(p)
    # §11.1 only-two-files: on rerun the two official files are overwritten, but a pre-existing EXTRA file/dir in
    # weekly_private/<dd>/ (debug / summary / raw / decision-packet …) fails closed — that per-date weekly surface
    # is the official manual-review folder and must hold ONLY the report + action table.
    if weekly_dir.exists():
        extra = sorted(p.name for p in weekly_dir.iterdir() if p.name not in _OFFICIAL_WEEKLY_FILES)
        if extra:
            raise WeekendPrivateWriteError(
                f"weekly_private/{decision_date}/ 含非官方文件 {extra}（§11.1 只放 {sorted(_OFFICIAL_WEEKLY_FILES)}）")

    # all gates passed → write. machine layer → runs_private; the two official files → weekly_private. Each write
    # re-runs the §18.0 guard (single source) as belt; the preflight above is the atomicity guarantee.
    _write_text_private(machine_path, json.dumps(flat, ensure_ascii=False, indent=2, sort_keys=True))
    write_action_table(flat, action_path)   # renders the flattened record + §18.0 guard
    _write_text_private(report_path, weekly_report_md)
    return {"machine_record_path": machine_path, "action_table_path": action_path, "weekly_report_path": report_path}
