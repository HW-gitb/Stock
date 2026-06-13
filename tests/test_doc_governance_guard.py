"""Narrow doc-governance drift guard (anti-recurrence for the 2026-06-13 doc-simplification slice).

The SESSION_LOG-archival + handoff-index-consolidation work hit the SAME class of drift across many
review rounds: a contract/rule restated in a second place goes stale, or a live count is written into
a durable doc. This guard pins the CURRENT rule regions so those exact regressions fail automatically.

Scope is deliberately narrow — it checks only active rule docs (`AGENTS.md`, the handoff index, and
the archive-file HEADERS). It does NOT scan `docs/SESSION_LOG.md` bodies or archived entry bodies, so
historical review records that legitimately mention old counts never false-positive.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
HANDOFF_DIR = ROOT / "docs" / "handoff"
HANDOFF_INDEX = HANDOFF_DIR / "README.md"
ARCHIVE_SESSION_LOG_DIR = ROOT / "docs" / "archive" / "session_log"


def _archive_header(text: str) -> str:
    """The archive file's own header = everything before its first dated entry; never the entry bodies."""
    return re.split(r"(?m)^## \d{4}-\d{2}-\d{2} ", text, maxsplit=1)[0]


class DocGovernanceGuard(unittest.TestCase):
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
        text = AGENTS.read_text(encoding="utf-8")
        self.assertIn("Register = material finding 详情的单一来源", text,
                      "AGENTS lost the register-single-source rule")
        self.assertIn("### 评审循环 entry 极简模板", text,
                      "AGENTS lost the minimal review-cycle SESSION_LOG template")
        # B2 must carry the generalized single-source principle (not just the old contract-anchor wording)
        m = re.search(r"(?ms)\*\*B2[^\n]*\*\*.*?(?=\n   - \*\*C|\n   \*\*Proof-of-use)", text)
        self.assertIsNotNone(m, "AGENTS lost the B2 item")
        b2 = m.group(0)
        for kw in ("单一来源", "planted-failure", "靠人记"):
            self.assertIn(kw, b2, f"B2 single-source principle lost anchor: {kw}")

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

    @classmethod
    def _review_cycle_offenders(cls, zone_text):
        # SHARED single-source logic for the live guard AND the planted-failure tests (so the guard
        # and its proof can't drift apart). For each review-cycle entry in the COMPLIANT ZONE that
        # cites a Required ID, enforce the EXACT minimal template.
        offenders = []
        parts = re.split(r"(?m)^## (\d{4}-\d{2}-\d{2}) — ", zone_text)
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
                if not s or s.startswith("<!--"):
                    continue                              # blank / the adoption-marker comment line
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

    PRE_CODEX_CHECKLIST = ROOT / "docs" / "pre_codex_self_review_checklist.md"
    B_ANCHORS = ("零残留", "字符串字面量", "test_", "全仓 guard")   # emit-string + test-surface + evidence + tree-guard

    @classmethod
    def _b_sections(cls):
        # the B ripple-grep region in BOTH authoritative surfaces: AGENTS item-7 bullet AND the
        # detailed checklist implementers are routed to. (Pinning only AGENTS let the checklist drift.)
        agents = AGENTS.read_text(encoding="utf-8")
        cl = cls.PRE_CODEX_CHECKLIST.read_text(encoding="utf-8")
        am = re.search(r"(?ms)- \*\*B ripple grep.*?(?=\n   - \*\*B2)", agents)
        cm = re.search(r"(?ms)^## B\..*?(?=^## C\.)", cl)
        return {"AGENTS B": am.group(0) if am else None,
                "checklist B": cm.group(0) if cm else None}

    def test_b_ripple_grep_anchors_pinned_in_agents_and_checklist(self):
        # R-DOCGOV-B-RIPPLE-GREP-PROOF-AND-CHECKLIST-GUARD-GAP: the strengthened B (exhaustive grep
        # incl emitted runtime string literals + test docstrings/comments, zero-residual evidence,
        # recurring-rule tree-wide guard) must be pinned in BOTH AGENTS and the routed-to checklist,
        # so neither can drift back to the narrow form the same-R-ID re-FAILs came from.
        for name, region in self._b_sections().items():
            self.assertIsNotNone(region, f"{name} section not found")
            for kw in self.B_ANCHORS:
                self.assertIn(kw, region, f"{name} lost B anchor: {kw}")

    def test_b_ripple_grep_anchor_guard_is_real_planted(self):
        # proves the guard actually fails when an anchor is dropped from EITHER B section (not a no-op).
        for name, region in self._b_sections().items():
            for kw in self.B_ANCHORS:
                planted = region.replace(kw, "")   # remove ALL occurrences (an anchor may repeat in a section)
                self.assertFalse(all(a in planted for a in self.B_ANCHORS),
                                 f"dropping {kw!r} from {name} must fail the anchor check")

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
        }
        stale = []
        for line in reg.split("\n"):
            m = re.search(r"Required ID `(R-[A-Z0-9-]+)`", line)
            if m and m.group(1) in committed_resolved and "status `open`" in line:
                stale.append(m.group(1))
        self.assertEqual(stale, [], f"committed-and-fixed entries still stale `status open`: {stale}")

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


if __name__ == "__main__":
    unittest.main()
