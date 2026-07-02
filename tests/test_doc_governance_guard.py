"""Narrow doc-governance drift guard (anti-recurrence for the 2026-06-13 doc-simplification slice).

The SESSION_LOG-archival + handoff-index-consolidation work hit the SAME class of drift across many
review rounds: a contract/rule restated in a second place goes stale, or a live count is written into
a durable doc. This guard pins the CURRENT rule regions so those exact regressions fail automatically.

Scope is deliberately narrow — it checks only active rule docs (`AGENTS.md`, the handoff index, and
the archive-file HEADERS). It does NOT scan `docs/SESSION_LOG.md` bodies or archived entry bodies, so
historical review records that legitimately mention old counts never false-positive.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
AI_REVIEW_PROTOCOL = ROOT / "docs" / "AI_REVIEW_PROTOCOL.md"
CURRENT = ROOT / "docs" / "CURRENT.md"
HANDOFF_DIR = ROOT / "docs" / "handoff"
HANDOFF_INDEX = HANDOFF_DIR / "README.md"
ARCHIVE_SESSION_LOG_DIR = ROOT / "docs" / "archive" / "session_log"
# US-short authority demotion (2026-06-20, R-USSHORT-ACTIVE-PROVIDER-DOC-OLD-SPEC-SECTION-DRIFT):
# after docs/us_short_spec.md was demoted to an archive pointer and docs/us_short_system_design.md
# became the single design authority, active provider/evidence CONTRACT INPUT lists must consume the
# live authority, not the archived pointer (a stale "consumes:" dependency — or a dead section anchor
# such as the old "section 9" — would misroute a future US-short provider/DataHub/implementation slice
# past the new authority + its §18.0 P0 gates). Historical JSON/handoff/archive/SESSION_LOG mentions
# are intentionally NOT scanned (retire-not-chase: do not rewrite append-only history to chase mentions).
USSHORT_LIVE_AUTHORITY = "docs/us_short_system_design.md"
USSHORT_ACTIVE_CONTRACT_DOCS = (
    ROOT / "docs" / "provider_data_requirements_audit.md",
    ROOT / "docs" / "provider_priority_benchmark_contract.md",
    ROOT / "docs" / "evidence_feasibility_controls.md",
)
ACTIVE_DESIGN_DOCS = (
    ROOT / "docs" / "a_short_weekly_pipeline_design_20260610.md",
    ROOT / "docs" / "CURRENT.md",
    ROOT / "docs" / "a_short_holdings_in_m67_design.md",
    ROOT / "docs" / "a_short_holdings_s3_system_levels_design.md",
)
CURRENT_FACT_REGISTRY = (
    {
        "name": "a_short_slice_a_overlay_wiring",
        "future_terms": (
            "overlay",
            "Slice A",
            "赛道红利",
            "build_overlay_summary_from_panels",
        ),
        "anchors": (
            (ROOT / "docs" / "README.md", (
                "Data-loading WIRED",
                "build_overlay_summary_from_panels",
                "--overlay",
            )),
            (ROOT / "A-EGS" / "egs_main.py", (
                "emit_overlay",
            )),
            (ROOT / "runners" / "weekly_screening.ps1", (
                "--overlay",
                "overlay.json",
            )),
            (ROOT / "runners" / "a_short_weekly_pipeline.py", (
                "--overlay",
                "_load_validated_overlay",
            )),
        ),
    },
    {
        # 2026-06-20: 4.2 缺口数据接入(全 5 轮)+ S3b 持仓主动管理(R1-R4b)均已实现并提交。
        # 防 durable 文档(CURRENT/持仓 design docs)把已收官的 4.2/S3b 写成「未起草/待实现」(misroute 新会话)。
        "name": "a_short_4_2_s3b_complete",
        "future_terms": (
            "4.2",
            "S3b",
            "持仓处置",
            "减仓价",
        ),
        "anchors": (
            (ROOT / "schemas" / "examples" / "a_short_gap_data_field_registry.example.json", (
                "holding_management_effect",
                "block_trade_appearance",
            )),
            (ROOT / "runners" / "a_short_phase5_engine.py", (
                "_merge_holding_disposition",
                "_holding_ratchet",
            )),
            (ROOT / "runners" / "a_short_weekly_pipeline.py", (
                "_attach_holding_disposition",
                "save_holding_ratchet",
            )),
        ),
    },
)
FUTURE_WORK_MARKERS = (
    "仍未来",
    "未来工作",
    "未接线",
    "尚未接线",
    "not wired",
    "stub",
    "未起草",
    "待起草",
    "待实现",
    "未实现",
)


def _archive_header(text: str) -> str:
    """The archive file's own header = everything before its first dated entry; never the entry bodies."""
    return re.split(r"(?m)^## \d{4}-\d{2}-\d{2} ", text, maxsplit=1)[0]


class DocGovernanceGuard(unittest.TestCase):
    @staticmethod
    def _contains_term(text: str, term: str) -> bool:
        if term.isascii():
            return term.lower() in text.lower()
        return term in text

    @classmethod
    def _line_lists_completed_fact_as_future(cls, line: str, fact: dict) -> bool:
        if not any(cls._contains_term(line, marker) for marker in FUTURE_WORK_MARKERS):
            return False
        return any(cls._contains_term(line, term) for term in fact["future_terms"])

    def test_current_fact_registry_anchors_are_live(self):
        # The registry is intentionally small: only facts with concrete code/route anchors belong
        # here. If an implementation is refactored, update the registry and this guard together.
        missing = []
        for fact in CURRENT_FACT_REGISTRY:
            for path, anchors in fact["anchors"]:
                text = path.read_text(encoding="utf-8")
                for anchor in anchors:
                    if anchor not in text:
                        missing.append((fact["name"], str(path.relative_to(ROOT)), anchor))
        self.assertEqual(missing, [], f"current-fact registry anchor(s) are stale/missing: {missing}")

    def test_active_design_docs_do_not_list_completed_facts_as_future_work(self):
        # This closes the recurring drift shape behind R4: an active design doc's remaining-work
        # list can silently keep a completed wiring item. Historical docs may be archived; active
        # design docs must either state current truth or avoid live-state remaining-work claims.
        offenders = []
        for path in ACTIVE_DESIGN_DOCS:
            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                for fact in CURRENT_FACT_REGISTRY:
                    if self._line_lists_completed_fact_as_future(line, fact):
                        offenders.append((str(path.relative_to(ROOT)), line_no, fact["name"], line.strip()))
        self.assertEqual(offenders, [], f"active design doc lists completed current fact as future: {offenders}")

    def test_active_design_future_guard_planted_failure(self):
        stale = "- **仍未来**: Slice A overlay 数据装载接线(M6.7 赛道红利星级)"
        current = "- **已接线**: Slice A overlay 数据装载接线(M6.7 赛道红利星级)"
        unrelated_future = "- **仍未来**: EGS regime 分类器尚未生产接线"
        fact = CURRENT_FACT_REGISTRY[0]
        self.assertTrue(self._line_lists_completed_fact_as_future(stale, fact),
                        "guard must catch a completed overlay wiring item listed as future")
        self.assertFalse(self._line_lists_completed_fact_as_future(current, fact),
                         "guard must not flag a completed-fact line that states it is done")
        self.assertFalse(self._line_lists_completed_fact_as_future(unrelated_future, fact),
                         "guard must not block unrelated true future work such as regime classifier")
        # 2026-06-20 new fact: 4.2/S3b 已收官,防 durable doc 写成「未起草/待实现」(misroute 新会话)
        s3b_fact = CURRENT_FACT_REGISTRY[1]
        s3b_stale = "持仓/风险侧剩余两大块(均未起草):① 4.2 ② S3b 持仓处置/减仓价"
        s3b_done = "4.2 与 S3b(持仓处置/减仓价)均已实现并提交"
        s3b_unrelated = "- 仍未来: US-short burst 尚未起草"
        self.assertTrue(self._line_lists_completed_fact_as_future(s3b_stale, s3b_fact),
                        "guard must catch 4.2/S3b listed as 未起草")
        self.assertFalse(self._line_lists_completed_fact_as_future(s3b_done, s3b_fact),
                         "guard must not flag a 4.2/S3b line that states it is done")
        self.assertFalse(self._line_lists_completed_fact_as_future(s3b_unrelated, s3b_fact),
                         "guard must not block unrelated future work (US-short burst)")

    @staticmethod
    def _usshort_old_spec_live_input_offenders(text: str) -> list:
        # An active contract line naming the archived `us_short_spec.md` is an offender UNLESS the same
        # line carries an explicit ARCHIVE-FRAMING token (archived / superseded / pointer / 归档 / 指针).
        # Merely also naming the live authority `us_short_system_design.md` on the line does NOT exempt
        # it — a "- us_short_spec.md / us_short_system_design.md" line lists BOTH as live inputs, a
        # dual-live consumed-input regression, not an archive-pointer note
        # (R-USSHORT-ACTIVE-PROVIDER-DOC-GUARD-DUAL-LIVE-BYPASS). The legitimate framed line in
        # provider_data_requirements_audit.md is exempted by its "supersedes archived" wording, not by
        # the new authority's mere presence.
        out = []
        for ln in text.splitlines():
            if "us_short_spec.md" not in ln:
                continue
            low = ln.lower()
            if any(q in low for q in (
                "archive", "archived", "归档", "pointer", "指针", "superseded", "supersedes",
            )):
                continue
            out.append(ln.strip()[:200])
        return out

    def test_active_contracts_consume_live_us_short_authority_not_archived_spec(self):
        # R-USSHORT-ACTIVE-PROVIDER-DOC-OLD-SPEC-SECTION-DRIFT: after the archive demotion, active
        # provider/evidence contract input lists must consume the live `us_short_system_design.md`,
        # not the archived `us_short_spec.md` (which no longer has the old "section 9" anchor).
        for path in USSHORT_ACTIVE_CONTRACT_DOCS:
            text = path.read_text(encoding="utf-8")
            self.assertIn(USSHORT_LIVE_AUTHORITY, text,
                          f"{path.name} must consume the live US-short authority {USSHORT_LIVE_AUTHORITY}")
            self.assertEqual(
                self._usshort_old_spec_live_input_offenders(text), [],
                f"{path.name} still names archived us_short_spec.md as a live input")

    def test_usshort_old_spec_live_input_guard_planted(self):
        bare = "- `docs/us_short_spec.md` section 9,"
        dual_live_slash = "- `docs/us_short_spec.md` / `docs/us_short_system_design.md`"
        dual_live_and = "`docs/us_short_spec.md` and `docs/us_short_system_design.md`"
        framed_authority = "- `docs/us_short_system_design.md` (supersedes archived `docs/us_short_spec.md`),"
        archived_note = "see `docs/us_short_spec.md` (archived pointer)"
        self.assertTrue(self._usshort_old_spec_live_input_offenders(bare),
                        "guard must catch a bare archived-spec consumed-input line")
        # R-USSHORT-ACTIVE-PROVIDER-DOC-GUARD-DUAL-LIVE-BYPASS: naming both old + new on one line (no
        # archive framing) is a dual-live consumed-input regression and must NOT be exempted by the
        # mere presence of the new authority's name. Both separator forms Codex named are covered.
        self.assertTrue(self._usshort_old_spec_live_input_offenders(dual_live_slash),
                        "guard must catch a dual-live old/new consumed-input line lacking archive framing")
        self.assertTrue(self._usshort_old_spec_live_input_offenders(dual_live_and),
                        "guard must catch a dual-live old-and-new consumed-input line lacking archive framing")
        self.assertEqual(self._usshort_old_spec_live_input_offenders(framed_authority), [],
                         "guard must allow a line that consumes the live authority and frames the old as superseded/archived")
        self.assertEqual(self._usshort_old_spec_live_input_offenders(archived_note), [],
                         "guard must allow an explicit archived-pointer mention")

    def test_session_log_entry_rule_teaches_archive_pointer_exception(self):
        text = AGENTS.read_text(encoding="utf-8")
        # Scope to the `### Entry 格式` section ONLY. `归档指针` also appears in §归档, so a whole-file
        # search would stay green even if THIS rule region regressed — that was the weak v1 of this test.
        m = re.search(r"(?ms)^### Entry 格式.*?(?=^#{2,3} |\Z)", text)
        self.assertIsNotNone(m, "AGENTS.md lost the '### Entry 格式' section")
        section = m.group(0)
        self.assertIn("归档指针", section,
                      "Entry 格式 section lost the archive-pointer exception")
        self.assertIn("指针之后", section,
                      "Entry 格式 section must say new entries go AFTER the archive pointer")
        self.assertIn("无指针", section,
                      "Entry 格式 section must keep the no-pointer fallback (insert after H1 intro)")
        self.assertNotIn("新 entry 永远 prepend 到文件顶部", section,
                         "Entry 格式 section still teaches the pre-fix 'always prepend right after H1' rule")

    def test_archive_session_log_header_has_no_drifting_active_count(self):
        if not ARCHIVE_SESSION_LOG_DIR.exists():
            self.skipTest("no session_log archive yet")
        drifting = ("keeps the most recent 30 entries", "keeps the most recent",
                    "只保留最近 30 条", "保留最近 30 条")
        for f in sorted(ARCHIVE_SESSION_LOG_DIR.glob("*.md")):
            head = _archive_header(f.read_text(encoding="utf-8"))   # header only, not archived bodies
            for phrase in drifting:
                self.assertNotIn(phrase, head,
                                 f"{f.name} header restates a drifting live active-log count: {phrase!r}")

    def test_agents_keeps_no_second_handoff_mini_index(self):
        text = AGENTS.read_text(encoding="utf-8")
        # the root doc must not maintain a per-handoff list; the single annotated index is the
        # handoff README. (A single `docs/handoff/README.md` pointer + prose refs are fine; what is
        # banned is list items pointing at individual *_handoff.md files.)
        items = re.findall(r"(?m)^- `docs/handoff/[^`]*_handoff\.md`", text)
        self.assertEqual(items, [], f"AGENTS.md keeps a second handoff mini-index: {items}")
        self.assertIn("docs/handoff/README.md", text, "AGENTS.md lost the handoff-index pointer")

    def test_handoff_index_reaches_every_handoff(self):
        # complement: the single index must stay COMPLETE (the dropped mini-index was already stale).
        idx = HANDOFF_INDEX.read_text(encoding="utf-8")
        missing = [f.name for f in sorted(HANDOFF_DIR.glob("*_handoff.md")) if f.name not in idx]
        self.assertEqual(missing, [], f"handoff index does not reach: {missing}")

    def test_agents_pins_register_single_source_and_minimal_template(self):
        # 2026-06-13 protocol revision: the register is the single source for a material finding's
        # full detail, and review-cycle SESSION_LOG entries use a minimal template. Pin both rules
        # so a future edit can't silently delete them (zero-false-positive: AGENTS-only).
        # (The B2 single-source principle's rule body now lives in the checklist, not AGENTS — see
        # test_pre_codex_checklist_is_sole_rule_authority; AGENTS item 7 only points to it.)
        text = AGENTS.read_text(encoding="utf-8")
        self.assertIn("Register = material finding 详情的单一来源", text,
                      "AGENTS lost the register-single-source rule")
        self.assertIn("### 评审循环 entry 极简模板", text,
                      "AGENTS lost the minimal review-cycle SESSION_LOG template")

    # R-CODEX-REVIEW-OUTPUT-PLAIN-LANGUAGE-FRONT-GUARD-GAP: the front short entry must front-load BOTH
    # the three output sections AND the 大白话 plain-language layer. Single-source check for the live
    # guard and its planted-failure proof so the two can't drift apart (the previous front entry
    # complied with the section shape while omitting the user-required 大白话 layer).
    FRONT_OUTPUT_SECTIONS = ("Verdict", "Required / Optional / Options", "下一步")
    PLAIN_LANGUAGE_FRONT_ANCHOR = "大白话"

    @classmethod
    def _front_review_output_gaps(cls, front):
        gaps = []
        if not all(s in front for s in cls.FRONT_OUTPUT_SECTIONS):
            gaps.append("three-section-list")
        if cls.PLAIN_LANGUAGE_FRONT_ANCHOR not in front:
            gaps.append("plain-language-大白话")
        return gaps

    def test_agents_front_loads_codex_review_output_short_entry(self):
        text = AGENTS.read_text(encoding="utf-8")
        front = "\n".join(text.splitlines()[:60])

        expected = (
            "## 审查输出/落盘短入口",
            "Codex",
            "docs/SESSION_LOG.md",
            "REVIEW-CYCLE-MINIMAL-TEMPLATE-MARKER",
            "docs/system_risk_register.md",
            "Verdict",
            "Required / Optional / Options",
            "下一步",
            "不得发送",
        )
        for anchor in expected:
            self.assertIn(
                anchor,
                front,
                "AGENTS.md front matter must expose the Codex review output/logging closeout contract.",
            )
        self.assertIn("不再输出 `Findings`", front,
                      "AGENTS.md front short entry must explicitly remove the Findings section from chat output.")
        # the three-section shape alone is not enough — the 大白话 plain-language layer must be front-loaded too.
        self.assertEqual(
            self._front_review_output_gaps(front), [],
            "AGENTS.md front short entry must front-load the three output sections AND the 大白话 layer.",
        )

    def test_agents_front_entry_without_plain_language_fails(self):
        # planted-failure + positive control: a front entry that lists only the three section names but
        # omits the 大白话 layer must be flagged; the real AGENTS front (with 大白话) must pass the
        # same single-source checker.
        three_sections_only = (
            "## 审查输出/落盘短入口（Codex 必读）\n"
            "屏幕最终回复固定三段：`Verdict`、`Required / Optional / Options`、`下一步`。\n"
        )
        self.assertIn("plain-language-大白话", self._front_review_output_gaps(three_sections_only),
                      "a three-section-only front entry without 大白话 must fail the plain-language gate")
        real_front = "\n".join(AGENTS.read_text(encoding="utf-8").splitlines()[:60])
        self.assertEqual(self._front_review_output_gaps(real_front), [],
                         "the real AGENTS front entry must satisfy both the three-section and 大白话 gates")

    def test_agents_codex_review_requires_one_pass_defect_matrix(self):
        # User-directed 2026-06-13 correction: Codex review must not drip-feed one issue per
        # round. Pin the rule in the authoritative Codex review standard, not just chat memory.
        text = AGENTS.read_text(encoding="utf-8")
        m = re.search(r"(?ms)^## Codex adversarial review standard.*?(?=^### Codex review closeout gate)", text)
        self.assertIsNotNone(m, "AGENTS lost the Codex adversarial review standard section")
        section = m.group(0)
        for kw in ("One-pass defect-class matrix", "must not stop after the first obvious finding",
                   "PASS / FAIL / `修复`", "Chinese and English", "verification placeholders",
                   "same-date but wrong lineage/candidate-set artifacts", "partial coverage",
                   "sibling artifact sweep", "positive-control matching-lineage pass",
                   "false-positive controls", "state the exact unreviewed dimensions",
                   "instead of drip-feeding one issue per round"):
            self.assertIn(kw, section, f"Codex one-pass review matrix rule lost anchor: {kw}")

    def test_agents_codex_review_requires_design_code_authority_matrix(self):
        text = AGENTS.read_text(encoding="utf-8")
        m = re.search(r"(?ms)^## Codex adversarial review standard.*?(?=^### Codex review closeout gate)", text)
        self.assertIsNotNone(m, "AGENTS lost the Codex adversarial review standard section")
        section = m.group(0)
        for kw in (
            "Authority-vs-implementation design-code matrix",
            "user-supplied authority artifact",
            "authority / routing consistency",
            "claimed landing surfaces",
            "git status",
            "git diff",
            "design-only / schema-first / user-approval",
            "provider / DataHub / runner consumption",
            "paper / manual_actual / live_normalized",
            "private / gitignored",
            "A/US isolation",
            "no reviewable implementation",
        ):
            self.assertIn(kw, section, f"Codex design-code authority matrix lost anchor: {kw}")

    def test_role_swap_execution_review_contract_is_pinned(self):
        text = AGENTS.read_text(encoding="utf-8")
        m = re.search(r"(?ms)^## Role split and command ownership.*?(?=^## Codex adversarial review standard)", text)
        self.assertIsNotNone(m, "AGENTS lost the role-split section")
        section = m.group(0)

        required = (
            "Codex acts as the Executor + Fixer.",
            "Claude Code acts as the Independent Reviewer + Committer.",
            "standards do not move with the model names",
            "`审查` = Claude Code reviews Codex's current changes independently",
            "`修复` = Codex implements the reviewed repair scope",
            "`执行` = Codex runs the next approved execution slice",
            "`提交` = review-cycle commit is owned by Claude Code after `审查` PASS",
            "Codex must use `using-superpowers` when available before `执行` / `修复`",
            "Codex must run an independent agent self-review before handing work to Claude Code for `审查`",
            "handoff commands belong in `docs/SESSION_LOG.md` / `docs/system_risk_register.md`, not in the final chat",
            "Protocol / guard additions require an explicit user request or a reviewed finding; no unilateral process hardening.",
        )
        for anchor in required:
            self.assertIn(anchor, section, f"role-swap contract lost anchor: {anchor}")

        forbidden = (
            "Codex acts as the Independent Reviewer.",
            "Claude acts as the Designer + Implementer.",
            "`审查` = Codex reviews Claude's current changes independently",
            "`修复` = Claude implements the reviewed repair scope",
            "`提交` = review-cycle commit is owned by Codex after `审查` PASS",
        )
        for anchor in forbidden:
            self.assertNotIn(anchor, section, f"role-swap section still contains old role binding: {anchor}")

        front = "\n".join(text.splitlines()[:60])
        self.assertIn("`Codex：修复`", front, "front review closeout entry must route fixes to current implementer")
        self.assertIn("当前 reviewer/committer 自动提交", front,
                      "front review closeout entry must route PASS commits to current reviewer/committer")
        for anchor in ("`Claude Code：修复`", "`Claude Code：执行`", "Codex 自动提交已审查工作树"):
            self.assertNotIn(anchor, front, f"front review closeout entry still contains old next-actor wording: {anchor}")

        output_rule = re.search(r"(?ms)^## 输出结论规则.*?(?=^## System risk register discipline)", text)
        self.assertIsNotNone(output_rule, "AGENTS lost output conclusion rules section")
        output_section = output_rule.group(0)
        for anchor in (
            "reviewer/committer PASS 后自动提交",
            "`Codex：修复`",
            "`审查` PASS 后 reviewer/committer 必须",
            "Codex 只负责实现/修复",
            "reviewer `审查 FAIL`",
            "implementer `修复`",
        ):
            self.assertIn(anchor, output_section, f"output rules lost role-neutral/current-role anchor: {anchor}")
        for anchor in (
            "2026-06-25 Codex PASS 后自动提交",
            "`Claude Code：修复`",
            "`Claude Code：执行`",
            "`审查` PASS 后 Codex 必须",
            "Claude 只负责实现/修复",
            "Codex `审查 FAIL`",
            "Claude `修复`",
        ):
            self.assertNotIn(anchor, output_section, f"output rules still contain old role binding: {anchor}")

        protocol = AI_REVIEW_PROTOCOL.read_text(encoding="utf-8")
        for anchor in (
            "Codex = executor + fixer.",
            "Claude Code = independent reviewer + post-PASS committer.",
            "`审查` addressed to Claude Code",
            "`修复` addressed to Codex",
        ):
            self.assertIn(anchor, protocol, f"AI_REVIEW_PROTOCOL lost role-swap pointer: {anchor}")
        for anchor in (
            "Codex = independent reviewer + post-PASS committer",
            "Claude = designer + implementer + fixer",
            "`审查` addressed to Codex",
            "`修复` addressed to Claude",
            "do not run `修复` or `执行` business implementation work",
        ):
            self.assertNotIn(anchor, protocol, f"AI_REVIEW_PROTOCOL still contains old role binding: {anchor}")

        current = CURRENT.read_text(encoding="utf-8")
        for anchor in (
            "Codex = Executor+Fixer",
            "Claude Code = Independent Reviewer+Committer",
            "`AGENTS.md` §Role split and command ownership",
        ):
            self.assertIn(anchor, current, f"CURRENT.md lost current role-swap pointer: {anchor}")
        for anchor in (
            "Claude = Designer + Implementer；Codex = Independent Reviewer",
            "Claude = 设计+实现,Codex = 独立审查",
            "2026-06-07 角色互换",
        ):
            self.assertNotIn(anchor, current, f"CURRENT.md still contains old role binding: {anchor}")

        closeout = re.search(r"(?ms)^### Codex review closeout gate.*?(?=^## Claude implementer standard)", text)
        self.assertIsNotNone(closeout, "AGENTS lost the review closeout gate")
        closeout_section = closeout.group(0)
        for anchor in (
            "Claude Code is the reviewer/committer that follows this gate",
            "Before the reviewer/committer replies to any `审查`",
            "On PASS, the reviewer/committer must auto-commit",
            "the reviewer/committer already owns that commit",
            "The reviewer/committer must prepend the review verdict",
        ):
            self.assertIn(anchor, closeout_section, f"closeout gate lost role-neutral anchor: {anchor}")
        for anchor in (
            "Before Codex replies",
            "Codex must auto-commit",
            "Codex already owns that commit",
            "Codex review output must follow",
            "Codex must prepend the review verdict",
        ):
            self.assertNotIn(anchor, closeout_section, f"closeout gate still contains stale Codex committer binding: {anchor}")

        template = re.search(r"(?ms)^### 评审循环 entry 极简模板.*?(?=^### 三层保险机制)", text)
        self.assertIsNotNone(template, "AGENTS lost the review-cycle minimal template section")
        template_section = template.group(0)
        for anchor in (
            "一次 reviewer FAIL、一次 implementer 修复、一次 PASS",
            "legacy section name，current implementer = Codex",
            "纯 `<LLM> PASS (R-ID)` 也照查",
        ):
            self.assertIn(anchor, template_section, f"SESSION_LOG template lost role-neutral anchor: {anchor}")
        for anchor in (
            "一次 Codex FAIL、一次 Claude 修复、一次 PASS",
            "纯 `Codex PASS (R-ID)` 也照查",
        ):
            self.assertNotIn(anchor, template_section, f"SESSION_LOG template still contains stale role binding: {anchor}")

    def test_process_speed_defaults_are_shared_and_scripted(self):
        # User-requested 2026-07-02: make command-speed defaults shared repo policy for both LLMs,
        # not Codex memory. The anchors deliberately cover the six requested points once, without
        # reintroducing a sprawling protocol body.
        text = AGENTS.read_text(encoding="utf-8")
        m = re.search(r"(?ms)^## Role split and command ownership.*?(?=^## Codex adversarial review standard)", text)
        self.assertIsNotNone(m, "AGENTS lost the role-split section")
        section = m.group(0)
        for anchor in (
            "Process-speed defaults (user-requested 2026-07-02)",
            "fixed verification packs",
            "`docs/process`",
            ".tools/verify_doc_process.cmd",
            "focused first, then the required full pack",
        ):
            self.assertIn(anchor, section, f"shared process-speed contract lost anchor: {anchor}")
        for removed_soft_rule in (
            "state one boundary line before tool use",
            "narrow: current diff + current requirement",
            "do not scan or run provider/live/DataHub/production/broker/automatic-order",
        ):
            self.assertNotIn(
                removed_soft_rule,
                section,
                f"process-speed section reintroduced soft-rule tax: {removed_soft_rule}",
            )

        verifier = ROOT / ".tools" / "verify_doc_process.cmd"
        self.assertTrue(verifier.exists(), "missing shared docs/process verification script")
        script = verifier.read_text(encoding="utf-8").replace("\\", "/")
        self.assertIn(".tools/run_unittest_with_repo_pythonpath.cmd", script,
                      "doc-process verifier must route through the repo Python/jsonschema wrapper")
        for module in (
            "tests.test_doc_governance_guard",
            "tests.test_readme_route_row_length",
            "tests.test_route_doc_ledger_status_consistency",
        ):
            self.assertIn(module, script, f"doc-process verifier lost required module: {module}")

    # STRUCTURAL minimal-template contract (allowlist, not keyword blacklist — a blacklist is
    # whack-a-mole: alternate wording / another language escapes it). A compliant-zone review-cycle
    # entry's body may contain ONLY these labelled bullets; any free-form paragraph or extra
    # finding/risk/repair/boundary section is a double-write offender. Full detail belongs ONLY in
    # system_risk_register.md.
    # EXACT minimal-template contract (not a subset allowlist — the strongest invariant so no future
    # entry shape can drip-feed through). A compliant-zone review-cycle entry's body bullets must be
    # EXACTLY the base set (+ a proof bullet for `修复`), no missing/extra/duplicate labels, no
    # free-form paragraph, no Verify placeholder, and no over-long bullet (which would cram the
    # register's full finding into a single allowed bullet). Full detail belongs ONLY in the register.
    EXPECTED_BASE_LABELS = frozenset({"Verdict/Action", "Required", "Verify", "Next"})
    PROOF_LABELS = frozenset({"Pre-Codex self-review", "Proof-of-use"})
    REVIEW_HEADER_KEYS = ("审查", "修复", "PASS", "Pass", "FAIL")     # incl. PASS-only headers
    VERIFY_PLACEHOLDERS = ("N OK", "<N>", "TODO", "占位", "XXX", "TBD")
    MAX_BULLET_LEN = 500          # real entries top out ~260; >500 means crammed copied detail
    ADOPTION_MARKER = "REVIEW-CYCLE-MINIMAL-TEMPLATE-MARKER"
    _BULLET = re.compile(r"-\s+\*\*(.+?)\*\*\s*[:：]")
    # Draft-class (起草/强化) handoff proof gate (R-PRECODEX-CHECKLIST-HANDOFF-PROOF-OF-USE-GAP):
    # checklist line 62 requires a `Pre-Codex self-review` line on every 起草/修复 handoff. 修复 entries
    # are caught by the review-cycle minimal template (missing-proof-of-use); this closes the 起草/强化
    # gap where a non-review-cycle header skipped proof enforcement. Marker-gated like the review-cycle
    # one: entries above DRAFT_PROOF_MARKER are post-adoption (enforced); below = grandfathered history.
    DRAFT_HEADER_KEYS = ("起草", "强化")
    DRAFT_PROOF_MARKER = "DRAFT-HANDOFF-PROOF-MARKER"
    # require an ACTUAL labeled proof line (optional list marker, half/full-width colon), NOT a prose
    # mention of the token (R-PRECODEX-CHECKLIST-HANDOFF-PROOF-LABEL-FALSE-NEGATIVE — the same prose-vs-
    # labeled-line class as the original bug, this time in the guard itself).
    _PROOF_LINE = re.compile(r"(?m)^\s*(?:-\s+)?\*\*(?:Pre-Codex self-review|Proof-of-use)\*\*\s*[:：]")

    @classmethod
    def _review_cycle_offenders(cls, zone_text):
        # SHARED single-source logic for the live guard AND the planted-failure tests (so the guard
        # and its proof can't drift apart). For each review-cycle entry in the COMPLIANT ZONE that
        # cites a Required ID, enforce the EXACT minimal template.
        offenders = []
        parts = re.split(r"(?m)^## (\d{4}-\d{2}-\d{2}) [—–-] ", zone_text)   # — / – / - header separators
        for i in range(1, len(parts), 2):
            block = parts[i + 1]
            lines = block.splitlines()
            header = lines[0] if lines else ""
            if not any(k in header for k in cls.REVIEW_HEADER_KEYS):
                continue                                  # review-cycle rounds incl. PASS-only headers
            if not re.search(r"R-[A-Z0-9][A-Z0-9-]+", block):
                continue                                  # only entries citing a Required ID
            tag = header[:50]
            is_fix = "修复" in header
            labels = []
            for ln in lines[1:]:
                s = ln.strip()
                if not s or s.startswith("<!--") or s.startswith(">"):
                    continue                              # blank / adoption-marker comment / blockquote (e.g. archive note)
                m = cls._BULLET.match(s)
                if not m:
                    offenders.append(("free-form-or-non-template-line", tag))
                    continue
                labels.append(m.group(1).strip())
                if len(s) > cls.MAX_BULLET_LEN:
                    offenders.append(("bullet-too-long", tag))   # detail crammed into one bullet
                if m.group(1).strip() == "Verify" and any(ph in s for ph in cls.VERIFY_PLACEHOLDERS):
                    offenders.append(("verify-placeholder", tag))
            present = set(labels)
            allowed_here = cls.EXPECTED_BASE_LABELS | (cls.PROOF_LABELS if is_fix else frozenset())
            for miss in sorted(cls.EXPECTED_BASE_LABELS - present):
                offenders.append((f"missing-label:{miss}", tag))
            for extra in sorted(present - allowed_here):
                offenders.append((f"unexpected-label:{extra}", tag))
            if len(labels) != len(present):
                offenders.append(("duplicate-label", tag))
            if is_fix and not (present & cls.PROOF_LABELS):
                offenders.append(("missing-proof-of-use", tag))
            if "register" not in block:
                offenders.append(("no-register-pointer", tag))
        return offenders

    @classmethod
    def _draft_handoff_proof_offenders(cls, zone_text):
        # Checklist line 62: every 起草/修复 handoff SESSION_LOG entry must carry a `Pre-Codex
        # self-review` line. 修复 is enforced by _review_cycle_offenders (missing-proof-of-use); this
        # closes the 起草/强化 (draft-class, non-review-cycle header) gap that let a session-style
        # handoff omit the line. Any current implementer entry whose header names draft work must
        # carry the proof line.
        offenders = []
        parts = re.split(r"(?m)^## (\d{4}-\d{2}-\d{2}) [—–-] ", zone_text)   # — / – / - header separators
        for i in range(1, len(parts), 2):
            block = parts[i + 1]
            lines = block.splitlines()
            header = lines[0] if lines else ""
            if not any(name in header for name in ("Claude", "Codex")):
                continue
            if not any(k in header for k in cls.DRAFT_HEADER_KEYS):
                continue
            if not cls._PROOF_LINE.search(block):    # actual labeled line, not a prose token mention
                offenders.append(("missing-pre-codex-self-review", header[:50]))
        return offenders

    def test_review_cycle_minimal_template_enforced_above_marker(self):
        # MARKER-gated (not date-gated): entries ABOVE the adoption marker are the post-adoption
        # compliant zone and are enforced regardless of date (closes the same-day blind spot of the
        # old date gate); entries BELOW are pre-adoption history, grandfathered.
        log = (ROOT / "docs" / "SESSION_LOG.md").read_text(encoding="utf-8")
        self.assertIn(self.ADOPTION_MARKER, log,
                      "SESSION_LOG lost the review-cycle adoption marker (the compliant-zone anchor)")
        compliant_zone = log.split(self.ADOPTION_MARKER, 1)[0]
        offenders = self._review_cycle_offenders(compliant_zone)
        self.assertEqual(offenders, [],
                         f"compliant-zone review-cycle entries violate the minimal template: {offenders}")

    def test_review_cycle_guard_planted_failures(self):
        # Structural enforcement: every wording/language variant of double-write fails, and a
        # `修复` missing its proof line fails (Codex's R-...-NONSTRUCTURAL-FALSE-NEGATIVE cases).
        same_day_no_pointer = ("## 2026-06-13 — Claude `修复` (R-TEST-FOO)\n"
                               "- **Verdict/Action**: fixed it\n- **Pre-Codex self-review**: ok\n- **Next**: 审查\n")
        chinese_duplicated = ("## 2026-06-13 — Claude `修复` (R-TEST-FOO)\n"
                              "- **Required**: R-TEST-FOO — 见 system_risk_register.md\n"
                              "- **Pre-Codex self-review**: ok\n"
                              "问题1: 风险说明、修复要求、边界、关闭证据全部复制在这里。\n- **Next**: 审查\n")
        finding_style_duplicated = ("## 2026-06-14 — Codex `审查` FAIL (R-TEST-FOO)\n"
                                    "- **Verdict/Action**: FAIL\n- **Required**: R-TEST-FOO — see register\n"
                                    "- **Finding-1**: full risk/repair/boundary copied here\n- **Next**: 修复\n")
        repair_missing_proof = ("## 2026-06-14 — Claude `修复` (R-TEST-FOO)\n"
                                "- **Verdict/Action**: fixed\n- **Required**: R-TEST-FOO — see register\n"
                                "- **Verify**: ok\n- **Next**: 审查\n")
        pass_header_with_detail = ("## 2026-06-14 — Codex PASS (R-TEST-FOO)\n"
                                   "- **Verdict/Action**: PASS\n- **Required**: R-TEST-FOO — see register\n"
                                   "- **Finding-1**: extra copied detail under a PASS-only header\n- **Next**: 提交\n")
        verify_placeholder = ("## 2026-06-14 — Claude `修复` (R-TEST-FOO)\n"
                              "- **Verdict/Action**: fixed\n- **Required**: R-TEST-FOO — see register\n"
                              "- **Verify**: tests = N OK\n- **Pre-Codex self-review**: ok\n- **Next**: 审查\n")
        # exact-set + length hardening (this round):
        crammed_into_one_bullet = ("## 2026-06-14 — Claude `修复` (R-TEST-FOO)\n"
                                   "- **Verdict/Action**: " + ("详细复述全部 finding/风险/修复/边界/闭合 " * 30) + "\n"
                                   "- **Required**: R-TEST-FOO — see register\n- **Verify**: 22 OK\n"
                                   "- **Pre-Codex self-review**: ok\n- **Next**: 审查\n")
        missing_required_label = ("## 2026-06-14 — Codex `审查` FAIL (R-TEST-FOO)\n"
                                  "- **Verdict/Action**: FAIL\n- **Required**: R-TEST-FOO — see register\n"
                                  "- **Verify**: 22 OK\n")  # missing Next
        duplicate_label = ("## 2026-06-14 — Codex `审查` FAIL (R-TEST-FOO)\n"
                           "- **Verdict/Action**: FAIL\n- **Required**: R-TEST-FOO — see register\n"
                           "- **Verify**: 22 OK\n- **Verify**: extra copied detail\n- **Next**: 修复\n")
        for name, sample in (("same_day_no_pointer", same_day_no_pointer),
                             ("chinese_duplicated", chinese_duplicated),
                             ("finding_style_duplicated", finding_style_duplicated),
                             ("repair_missing_proof", repair_missing_proof),
                             ("pass_header_with_detail", pass_header_with_detail),
                             ("verify_placeholder", verify_placeholder),
                             ("crammed_into_one_bullet", crammed_into_one_bullet),
                             ("missing_required_label", missing_required_label),
                             ("duplicate_label", duplicate_label)):
            self.assertTrue(self._review_cycle_offenders(sample),
                            f"structural guard misses planted double-write/incomplete case: {name}")
        compliant = ("## 2026-06-14 — Claude `修复` (R-TEST-FOO)\n"
                     "- **Verdict/Action**: fixed\n"
                     "- **Required**: R-TEST-FOO — 详情见 system_risk_register.md(单一来源)\n"
                     "- **Verify**: tests OK\n"
                     "- **Pre-Codex self-review**: A-F checked — evidence\n- **Next**: 审查\n")
        self.assertEqual(self._review_cycle_offenders(compliant), [],
                         "guard false-positives a compliant minimal entry")
        # robustness control: a hyphen-separated review header (Codex's newer "- Codex `review …`" format)
        # must be isolated as its own block, NOT absorbed into the preceding entry (which would double
        # its labels). If the split regresses to em-dash-only this produces a duplicate-label offender.
        hyphen_isolated = (compliant +
                           "\n## 2026-06-14 - Codex `review FAIL` (R-TEST-FOO)\n"
                           "- **Verdict/Action**: FAIL\n"
                           "- **Required**: R-TEST-FOO — see register\n"
                           "- **Verify**: 22 OK\n- **Next**: 修复\n")
        self.assertEqual(self._review_cycle_offenders(hyphen_isolated), [],
                         "hyphen-header review entry not isolated (absorbed into the preceding entry)")
        # robustness control: a blockquote line (e.g. the archive note) must be skipped, not free-form
        with_blockquote = compliant + "\n> 📦 archive note: older entries moved to the archive file\n"
        self.assertEqual(self._review_cycle_offenders(with_blockquote), [],
                         "blockquote line false-flagged as a non-template line")

    def test_draft_handoff_proof_enforced_above_marker(self):
        # R-PRECODEX-CHECKLIST-HANDOFF-PROOF-OF-USE-GAP: a 起草/强化 handoff that omits the required
        # `Pre-Codex self-review` line must fail automatically (the rule can no longer rely on memory).
        # MARKER-gated: entries above DRAFT_PROOF_MARKER are enforced; below = grandfathered history.
        log = (ROOT / "docs" / "SESSION_LOG.md").read_text(encoding="utf-8")
        self.assertIn(self.DRAFT_PROOF_MARKER, log,
                      "SESSION_LOG lost the draft-handoff proof adoption marker")
        zone = log.split(self.DRAFT_PROOF_MARKER, 1)[0]
        offenders = self._draft_handoff_proof_offenders(zone)
        self.assertEqual(offenders, [],
                         f"draft-class (起草/强化) handoff entries missing the Pre-Codex self-review line: {offenders}")

    def test_draft_handoff_proof_guard_planted(self):
        # planted-failure + false-positive controls (so the guard and its proof can't drift apart).
        missing = ("## 2026-06-20 — Claude (US-short 批X foo 起草)\n"
                   "**Worked on**: did a thing\n**Next**: Codex `审查`\n")
        present = ("## 2026-06-20 — Claude (US-short 批X foo 起草)\n"
                   "**Worked on**: did a thing\n**Next**: Codex `审查`\n"
                   "**Pre-Codex self-review**: A-F checked — evidence\n")
        codex_missing = ("## 2026-07-02 — Codex (role-swap foo 起草)\n"
                         "**Worked on**: did a thing\n**Next**: Claude Code `审查`\n")
        codex_present = ("## 2026-07-02 — Codex (role-swap foo 起草)\n"
                         "**Worked on**: did a thing\n**Next**: Claude Code `审查`\n"
                         "**Pre-Codex self-review**: independent agent checked — evidence\n")
        harden_missing = ("## 2026-06-20 — Claude (强化 some checklist 规则)\n"
                          "**Worked on**: hardened a rule\n**Next**: Codex `审查`\n")
        prose_token_no_label = ("## 2026-06-20 — Claude (US-short 批X foo 起草)\n"
                                "**Worked on**: discussed Proof-of-use / Pre-Codex self-review wording, left no labeled line\n"
                                "**Next**: Codex `审查`\n")  # token in prose only → must still be flagged
        not_draft = ("## 2026-06-20 — Claude `执行` (run something)\n"
                     "**Worked on**: ran it\n**Next**: 提交\n")     # 执行 ≠ 起草/强化 → not required
        codex_entry = ("## 2026-06-20 — Codex `审查` PASS (R-X)\n- **Verdict/Action**: PASS\n")
        self.assertTrue(self._draft_handoff_proof_offenders(missing),
                        "guard must flag a 起草 handoff missing the Pre-Codex line")
        self.assertTrue(self._draft_handoff_proof_offenders(harden_missing),
                        "guard must flag a 强化 handoff missing the Pre-Codex line")
        self.assertTrue(self._draft_handoff_proof_offenders(prose_token_no_label),
                        "guard must flag a draft handoff that only MENTIONS the token in prose (no labeled line)")
        self.assertTrue(self._draft_handoff_proof_offenders(codex_missing),
                        "guard must flag a Codex draft handoff missing the Pre-Codex line after role swap")
        self.assertEqual(self._draft_handoff_proof_offenders(present), [],
                         "guard must not flag a 起草 handoff that has the line")
        self.assertEqual(self._draft_handoff_proof_offenders(codex_present), [],
                         "guard must not flag a Codex draft handoff that has the line")
        self.assertEqual(self._draft_handoff_proof_offenders(not_draft), [],
                         "guard must not flag a non-draft (执行) entry")
        self.assertEqual(self._draft_handoff_proof_offenders(codex_entry), [],
                         "guard must not flag a Codex review entry")

    # R-DOCGOV-SESSIONLOG-ORPHANED-REVIEW-ENTRY-GAP: one SESSION_LOG `##` entry records ONE review-cycle
    # action → exactly one `Verdict/Action` bullet. >1 means a prior entry's review bullets were ORPHANED
    # under this heading (e.g. a prepend whose old_string ate the previous `##` heading). The minimal-
    # template guard missed this because it inspects only review-header (审查/修复/PASS/FAIL) entries
    # citing a Required ID, so an orphan hidden under a non-review 起草 heading slipped through. This check
    # is header-type- and position-independent.
    _VERDICT_LINE = re.compile(r"(?m)^\s*-\s+\*\*Verdict/Action\*\*\s*[:：]")

    @classmethod
    def _orphaned_review_block_offenders(cls, zone_text):
        offenders = []
        headers = re.findall(r"(?m)^## (\d{4}-\d{2}-\d{2}\b.*)$", zone_text)
        blocks = re.split(r"(?m)^## \d{4}-\d{2}-\d{2}\b.*$", zone_text)[1:]
        for header, block in zip(headers, blocks):
            n = len(cls._VERDICT_LINE.findall(block))
            if n > 1:
                offenders.append((header[:60], n))
        return offenders

    def test_no_orphaned_review_bullets_above_marker(self):
        log = (ROOT / "docs" / "SESSION_LOG.md").read_text(encoding="utf-8")
        zone = log.split(self.ADOPTION_MARKER, 1)[0]
        self.assertEqual(
            self._orphaned_review_block_offenders(zone), [],
            "a SESSION_LOG entry orphans a prior review bullet set under its heading "
            "(>1 Verdict/Action before the next ## header)")

    def test_orphaned_review_block_guard_planted(self):
        orphaned = ("## 2026-06-24 — Claude `起草` (foo)\n"
                    "- **Verdict/Action**: drafted foo\n- **Next**: 审查\n\n"
                    "- **Verdict/Action**: PASS. prior Codex result orphaned here\n- **Next**: 提交\n")
        fixed = ("## 2026-06-24 — Claude `起草` (foo)\n"
                 "- **Verdict/Action**: drafted foo\n- **Next**: 审查\n\n"
                 "## 2026-06-24 - Codex `审查 PASS` (foo)\n"
                 "- **Verdict/Action**: PASS. prior Codex result\n- **Next**: 提交\n")
        self.assertTrue(self._orphaned_review_block_offenders(orphaned),
                        "guard must catch a review bullet set orphaned under a non-review draft heading")
        self.assertEqual(self._orphaned_review_block_offenders(fixed), [],
                         "guard must not flag two properly-headed entries")

    PRE_CODEX_CHECKLIST = ROOT / "docs" / "pre_codex_self_review_checklist.md"
    # Pre-Codex gate single-source contract (2026-06-13 refactor): the checklist is the SOLE rule
    # body; AGENTS item 7 only points to it. Earlier the rule was restated in BOTH and pinned in
    # both — that double-write was itself the drift surface, so it was collapsed to one authority.
    CHECKLIST_GATE_SECTIONS = ("## A.", "## B.", "## B2.", "## C.", "## D.", "## E.", "## F.")
    CHECKLIST_BODY_ANCHORS = ("零残留", "字符串字面量", "test_", "全仓 guard",   # B body
                              "单一来源", "planted-failure", "靠人记",
                              "活跃设计文档")                                   # B2 body
    # Body phrases that MUST NOT reappear in AGENTS item 7. Naming a rule ("B ripple-grep") is fine;
    # restating its body is the AGENTS<->checklist drift this refactor eliminates.
    AGENTS_ITEM7_FORBIDDEN_BODY = ("零残留", "defect-class", "靠人记", "planted-failure")

    @classmethod
    def _agents_item7(cls):
        text = AGENTS.read_text(encoding="utf-8")
        m = re.search(r"(?ms)^7\. \*\*Pre-Codex self-review gate.*?(?=^## )", text)
        return m.group(0) if m else None

    def test_pre_codex_checklist_is_sole_rule_authority(self):
        # single-source: the checklist holds every gate section header + its load-bearing anchors.
        cl = self.PRE_CODEX_CHECKLIST.read_text(encoding="utf-8")
        for h in self.CHECKLIST_GATE_SECTIONS:
            self.assertIn(h, cl, f"checklist lost gate section: {h}")
        for kw in self.CHECKLIST_BODY_ANCHORS:
            self.assertIn(kw, cl, f"checklist lost load-bearing anchor: {kw}")

    def test_agents_item7_points_to_checklist_and_does_not_restate(self):
        # AGENTS item 7 must be a mandatory pointer (checklist path + 必读必走 + Proof-of-use) and
        # must NOT restate the rule bodies — restatement is the very drift this refactor removes.
        region = self._agents_item7()
        self.assertIsNotNone(region, "AGENTS lost implementer-standard item 7")
        self.assertIn("pre_codex_self_review_checklist.md", region, "item 7 lost the checklist pointer")
        self.assertIn("必读必走", region, "item 7 lost the mandatory-read mandate")
        self.assertIn("Proof-of-use", region, "item 7 lost the Proof-of-use requirement")
        for body in self.AGENTS_ITEM7_FORBIDDEN_BODY:
            self.assertNotIn(body, region,
                             f"AGENTS item 7 restates checklist rule body (single-source drift): {body!r}")

    def test_pre_codex_gate_single_source_guard_is_real_planted(self):
        # proves BOTH directions fail: dropping a checklist section/anchor, AND injecting a rule-body
        # phrase back into AGENTS item 7.
        cl = self.PRE_CODEX_CHECKLIST.read_text(encoding="utf-8")
        for h in self.CHECKLIST_GATE_SECTIONS:                       # checklist loses a gate section
            planted = cl.replace(h, "", 1)
            self.assertFalse(all(x in planted for x in self.CHECKLIST_GATE_SECTIONS),
                             f"dropping {h} from checklist must fail the authority check")
        for kw in self.CHECKLIST_BODY_ANCHORS:                       # checklist loses a body anchor
            planted = cl.replace(kw, "")
            self.assertFalse(all(a in planted for a in self.CHECKLIST_BODY_ANCHORS),
                             f"dropping {kw!r} from checklist must fail the authority check")
        injected = (self._agents_item7() or "") + "\n零残留 defect-class 靠人记 planted-failure"
        self.assertTrue(any(b in injected for b in self.AGENTS_ITEM7_FORBIDDEN_BODY),  # AGENTS restatement
                        "injecting a rule-body phrase into AGENTS item 7 must be detectable")

    def test_committed_required_entries_are_resolved_not_stale_open(self):
        # R-RISK-REGISTER-STALE-OPEN-REPAIRED-HOTQUEUE-SWEEP-GAP: a Required entry whose fix is in a
        # review-passed commit must be `status resolved`, not lingering `status open` (stale-open
        # pollutes the durable queue + misleads 执行/审查). Regression guard over the swept committed
        # R-IDs. In-flight (uncommitted) findings are intentionally NOT in this set → no false-positive.
        reg = (ROOT / "docs" / "system_risk_register.md").read_text(encoding="utf-8")
        committed_resolved = {
            "R-ASHORT-M67-SEMANTIC-OFFICIAL-INPUT-CONSISTENCY-GAP",          # 908f95f
            "R-ASHORT-SEMANTIC-CONTRACT-M67-INTEGRATION-DRIFT",
            "R-ASHORT-M67-SEMANTIC-OFFICIAL-EVIDENCE-SHAPE-GAP",
            "R-ASHORT-M67-SEMANTIC-OFFICIAL-EVIDENCE-NONEMPTY-GAP",
            "R-ASHORT-SEMANTIC-SUMMARY-ANALYSIS-INPUT-CONSUMER-VALIDATION-GAP",  # 92a32c0
            "R-ASHORT-WEEKLY-AUX-ARTIFACT-CANDIDATE-SET-MISMATCH",           # 6709055
            "R-ASHORT-SEMANTIC-PANEL-MAIN-PARTIAL-WRITE-ON-INVALID-SUMMARY",
            "R-ASHORT-SEMANTIC-PANEL-GUARD-FILE-LEVEL-FALSE-NEGATIVE",
            "R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-PROMPT-SURFACE-DRIFT",
            "R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-HELP-DRIFT",
            "R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-DOC-DRIFT",
            "R-ASHORT-SEMANTIC-PANEL-SUMMARY-SCHEMA-BYPASS",
            "R-DOCGOV-MINIMAL-GUARD-PASS-HEADER-GAP",                        # 9918d84
            "R-DOCGOV-SESSIONLOG-VERIFY-PLACEHOLDER",
            "R-DOCGOV-MINIMAL-ENTRY-GUARD-NONSTRUCTURAL-FALSE-NEGATIVE",
            "R-DOCGOV-MINIMAL-ENTRY-GUARD-FALSE-NEGATIVES",
            "R-DOCGOV-AI-REVIEW-FIRST-REVIEW-DOUBLEWRITE-LOOPHOLE",
            # cfc0aa63 (本对话: A-short v3 item 1-4 + item 5 + Slice 3 + route-doc R1/R2 + review-output protocol)
            "R-CODEX-REVIEW-OUTPUT-PLAIN-LANGUAGE-FRONT-GUARD-GAP",
            "R-ASHORT-SLICE3-SEMANTIC-ROUTE-DOC-DRIFT",
            "R-ASHORT-ITEM5-LOWRISK-BATCH",
            "R-ASHORT-SLICE3-LEGACY-PRODUCTION-VETO-RECONCILIATION",
            "R-ASHORT-M67-RENDER-STANDALONE-PRIVACY-PROD-GUARD-GAP",
            "R-ASHORT-ANALYSIS-INPUT-CONTRACT-CALENDAR-DATE-GAP",
            "R-ASHORT-FORWARD-EVENT-HELD-IMPL-STATUS-STALE-S3B",
            "R-ASHORT-ROUTE-DOC-42-S3B-COMPLETED-FACT-AS-FUTURE-DRIFT",
            # 9a8184dc closeout review (this fix: block-level guard + stale Next)
            "R-ASHORT-CFC0AA63-SESSIONLOG-CLOSEOUT-NEXT-STALE",
            "R-ASHORT-CFC0AA63-STALE-OPEN-GUARD-BATCH-HEADER-GAP",
        }
        self.assertEqual(
            self._stale_open_committed_rids(reg, committed_resolved), [],
            "committed-and-fixed entries still declared in a stale-open block",
        )

    @staticmethod
    def _stale_open_committed_rids(reg, committed):
        # Block-level scan (R-ASHORT-CFC0AA63-STALE-OPEN-GUARD-BATCH-HEADER-GAP): a committed R-ID can be
        # DECLARED in a batch entry whose status lives on the header line while the R-IDs live in later
        # bullets, so a same-line scan misses it. Split the register into entries (status-token header
        # lines); an R-ID is DECLARED via `Required ID `R-X`` OR a `- R-X ...` bullet (a mid-sentence
        # cross-reference does NOT count → no false positive); an entry's status is its header-line
        # `status `X`` (or the header's leading status word). A committed R-ID declared in an `open`
        # entry is stale. In-flight (not-yet-committed) R-IDs are absent from `committed` → not flagged.
        committed = set(committed)
        header_re = re.compile(r"^(OPEN|RESOLVED|IN_PROGRESS|BLOCKED)\b[^\n]*\):", re.M)
        decl_re = re.compile(r"Required ID `(R-[A-Z0-9-]+)`|^- (R-[A-Z0-9-]+)\b", re.M)
        starts = [m.start() for m in header_re.finditer(reg)]
        stale = set()
        for i, s in enumerate(starts):
            block = reg[s:(starts[i + 1] if i + 1 < len(starts) else len(reg))]
            header = block.split("\n", 1)[0]
            mstat = re.search(r"status `(\w+)`", header)
            is_open = (mstat.group(1) == "open") if mstat else header.startswith("OPEN")
            if not is_open:
                continue
            declared = {a or b for a, b in decl_re.findall(block)}
            stale |= declared & committed
        return sorted(stale)

    def test_stale_open_guard_covers_batch_header_without_inline_required_id(self):
        # R-ASHORT-CFC0AA63-STALE-OPEN-GUARD-BATCH-HEADER-GAP planted-failure + false-positive controls:
        # a committed batch header (status on the header line, R-ID only in a later bullet) that regressed
        # to `status open` MUST be caught; a resolved one must not; an in-flight R-ID must not.
        committed = {"R-TEST-BATCH-FOO"}
        batch_open = ("OPEN P1/P2 (2026-06-20): some committed batch. status `open`(未 commit).\n"
                      "scope changed: a.py, b.py.\n"
                      "- R-TEST-BATCH-FOO (P2): fixed in the batch.\n")
        self.assertEqual(self._stale_open_committed_rids(batch_open, committed), ["R-TEST-BATCH-FOO"],
                         "batch header (status on header, R-ID in bullet) regressed to open must be caught")
        batch_resolved = (batch_open.replace("OPEN P1/P2", "RESOLVED P1/P2")
                          .replace("status `open`(未 commit)", "status `resolved`(committed abc1234)"))
        self.assertEqual(self._stale_open_committed_rids(batch_resolved, committed), [],
                         "a resolved batch header must not be flagged")
        in_flight = batch_open.replace("R-TEST-BATCH-FOO", "R-TEST-INFLIGHT-NEW")
        self.assertEqual(self._stale_open_committed_rids(in_flight, committed), [],
                         "in-flight (not-yet-committed) R-ID must not be flagged (false-positive control)")

    def test_ai_review_protocol_has_no_first_review_doublewrite_carveout(self):
        # Fixes R-DOCGOV-AI-REVIEW-FIRST-REVIEW-DOUBLEWRITE-LOOPHOLE: the protocol must not exempt
        # the first FAIL from the minimal template (that exemption kept the duplicate-fact loophole).
        text = (ROOT / "docs" / "AI_REVIEW_PROTOCOL.md").read_text(encoding="utf-8")
        self.assertNotIn("first-review recording", text,
                         "AI_REVIEW_PROTOCOL reintroduced the first-review double-write carve-out")
        self.assertIn("system_risk_register", text, "AI_REVIEW_PROTOCOL lost the register single-source pointer")
        self.assertIn("including the first", text.replace("\n", " "),
                      "AI_REVIEW_PROTOCOL must state the minimal template applies to EVERY review-cycle "
                      "entry including the first FAIL")

    _USSHORT_COUNT_RE = re.compile(r"Tests\s*[:(]\s*\d+(?![\w-])")  # a count after `Tests`; the (?![\w-]) excludes e.g. `Tests (8-K …)`

    def test_us_short_route_rows_do_not_restate_exact_test_counts(self):
        # §18.1 #11 「不在别处复述条数以免漂移」 (user decision 2026-06-23): us_short README route rows RETIRE
        # exact test counts — the `Tests (N)` / `Tests: N` form recurred repeatedly as drift because it had to
        # be hand-synced on every test add. A qualitative `Tests: <what's covered>` is fine; an integer count
        # right after `Tests` is not. This enforces the retirement so a count can't creep back — the
        # recurrence is now structurally impossible, not a thing to remember.
        readme = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        offenders = [m.group(0) for line in readme.splitlines() if "us_short" in line.lower()
                     for m in self._USSHORT_COUNT_RE.finditer(line)]
        self.assertEqual(offenders, [], "us_short route row restates an exact test count (retired per §18.1 #11): %s" % offenders)
        # planted-failure control: the detector is real, not a no-op regex
        self.assertTrue(self._USSHORT_COUNT_RE.search("| US-short foo … Tests (42): 10 eval | path us_short |"),
                        "detector must catch a reintroduced Tests (N) count")


    def test_schema_tests_are_routed_through_repo_pythonpath_wrapper(self):
        # The repo carries `.tools/python_libs/jsonschema`; future agents must not rediscover the same
        # missing-jsonschema failure by running schema/project tests through a bare Python environment.
        launcher = ROOT / ".tools" / "run_unittest_with_repo_pythonpath.cmd"
        self.assertTrue(launcher.exists(), "missing cmd launcher for the repo unittest wrapper")
        launcher_script = launcher.read_text(encoding="utf-8")
        normalized_script = launcher_script.replace("\\", "/")
        for forbidden in ("codex-runtimes", "codex-primary-runtime", "-ExecutionPolicy Bypass"):
            self.assertNotIn(forbidden, normalized_script,
                             f"shared unittest wrapper must not require environment-private machinery: {forbidden}")
        for anchor in (
            "PYTHONPATH",
            ".tools/python_libs",
            "jsonschema",
            "STOCK_TEST_PYTHON",
            "%LOCALAPPDATA%/Programs/Python/Python*",
            "%LOCALAPPDATA%/Programs/Python/Launcher/py.exe",
            "-m unittest",
        ):
            self.assertIn(anchor, normalized_script, f"wrapper lost required test-runtime anchor: {anchor}")

        agents = AGENTS.read_text(encoding="utf-8").replace("\\", "/")
        self.assertIn(".tools/run_unittest_with_repo_pythonpath.cmd", agents,
                      "AGENTS must name the canonical unittest wrapper launcher")
        self.assertIn(".tools/python_libs", agents,
                      "AGENTS must name the repo-local Python dependency directory")
        self.assertIn("STOCK_TEST_PYTHON", agents,
                      "AGENTS must document the explicit Python override for environments without python on PATH")
        self.assertIn("%LOCALAPPDATA%/Programs/Python/Python*", agents,
                      "AGENTS must document the common Windows user-install Python fallback")
        self.assertIn("do not accept silent schema-skip behavior", agents,
                      "AGENTS lost the no-silent-schema-skip rule")

        env = os.environ.copy()
        env["STOCK_TEST_PYTHON"] = sys.executable
        result = subprocess.run(
            [str(launcher), "tests.test_doc_governance_guard.JsonschemaImportSmoke"],
            cwd=str(ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)


class JsonschemaImportSmoke(unittest.TestCase):
    def test_jsonschema_is_importable(self):
        import jsonschema

        self.assertTrue(hasattr(jsonschema, "Draft7Validator"),
                        "jsonschema import must expose Draft7Validator")

    def test_repo_pythonpath_fallback_imports_without_site_packages(self):
        repo_libs = str((ROOT / ".tools" / "python_libs").resolve())
        env = os.environ.copy()
        env["PYTHONPATH"] = repo_libs
        result = subprocess.run(
            [sys.executable, "-S", "-c", "import jsonschema; print(jsonschema.__file__)"],
            cwd=str(ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(str(Path(repo_libs)).casefold(), result.stdout.casefold())


if __name__ == "__main__":
    unittest.main()
