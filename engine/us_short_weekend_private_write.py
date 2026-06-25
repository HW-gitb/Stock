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
from engine.us_short_private_paths import reject_nonprivate_output_path
from engine.us_short_weekend_action_table import flatten_machine_record

ROOT = Path(__file__).resolve().parent.parent
RUNS_PRIVATE_ROOT = ROOT / "state" / "us_short" / "runs_private"      # machine layer (§11.1, gitignored)
WEEKLY_PRIVATE_ROOT = ROOT / "state" / "us_short" / "weekly_private"  # weekly_report.md + action_table.csv (§11.1)
_REPORT_CONTRACT_PATH = ROOT / "presets" / "us_short_weekly_report_contract_20260620.json"

# §11.1: weekly_private/<dd>/ holds ONLY these two official files — any pre-existing extra file/dir fails closed.
_OFFICIAL_WEEKLY_FILES = frozenset({"weekly_report.md", "action_table.csv"})
# the rendered §11.2 price-clock banner ④ line (render_weekly_report emits exactly one "- ④ price_clock: ...").
_PRICE_CLOCK_LINE = "price_clock:"
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


def write_run_private(*, decision_date, machine_record, weekly_report_md,
                      runs_private_root=None, weekly_private_root=None) -> dict:
    """4d-ii-n idempotent private write. Persists the run's machine layer + §11.1 weekly_private surface to the
    gitignored private dirs, fail-closed behind the §18.0 P0 private-path guard, keyed (idempotent) by decision_date.

    decision_date = the run's canonical decision_date (the per-run private dir key).
    machine_record = the 4d-ii-k `assemble_machine_record` output (flattened here via slice m1).
    weekly_report_md = the 4d-ii-m2 `build_weekly_report` weekly_report markdown.
    runs_private_root / weekly_private_root = override the default private roots (tests / an external private
        location); a relative / non-gitignored in-repo destination is refused by the §18.0 guard.

    Returns {"machine_record_path", "action_table_path", "weekly_report_path"} (the written Paths). Raises
    WeekendPrivateWriteError on a blank weekly_report, a decision_date that disagrees with machine_record.as_of
    or the weekly_report's rendered price-clock banner (§2.1 same-run reconciliation), or — via the §18.0 guard /
    `WeekendActionTableError` — a non-private destination / malformed machine record."""
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
    pc_lines = [ln for ln in weekly_report_md.splitlines() if _PRICE_CLOCK_LINE in ln]
    if len(pc_lines) != 1:
        raise WeekendPrivateWriteError(f"weekly_report_md 须恰含 1 行 price-clock 横幅 ④（实得 {len(pc_lines)} 行）")
    pc_line = pc_lines[0].strip()
    if not pc_line.startswith(_PRICE_CLOCK_PREFIX):
        raise WeekendPrivateWriteError("weekly_report_md 的 price-clock 必须是渲染器输出的横幅 ④ 行")
    dates = _PRICE_CLOCK_DECISION_DATE.findall(pc_line)
    if len(dates) != 1 or dates[0] != decision_date:
        raise WeekendPrivateWriteError(
            f"weekly_report price-clock decision_date {dates if dates else None!r} != {decision_date!r}（疑跨周/歧义周报）")

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
