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


if __name__ == "__main__":
    unittest.main()
