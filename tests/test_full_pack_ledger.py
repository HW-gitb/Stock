"""Guard for the full-pack run ledger (verification tiering rule 4: one full run per unchanged code diff)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".tools"))
import full_pack_ledger as fpl  # noqa: E402


class FullPackLedgerTests(unittest.TestCase):
    def test_docs_and_markdown_edits_do_not_count_as_code_state(self):
        # rule 4: a docs/register/SESSION_LOG-only correction must NOT invalidate a code full-pack.
        for doc in ("docs/SESSION_LOG.md", "docs/system_risk_register.md", "AGENTS.md", "README.md"):
            self.assertFalse(fpl._is_code_path(doc), doc)
        for code in ("engine/us_short_core_score.py", "presets/x.json", "schemas/y.schema.json", "tests/test_z.py"):
            self.assertTrue(fpl._is_code_path(code), code)

    def test_fingerprint_is_deterministic_and_state_sensitive(self):
        base = {"engine/x.py": "aaa", "@HEAD": "h1"}
        self.assertEqual(fpl.fingerprint(base), fpl.fingerprint(dict(base)))          # deterministic
        self.assertNotEqual(fpl.fingerprint(base), fpl.fingerprint({"engine/x.py": "bbb", "@HEAD": "h1"}))  # code edit
        self.assertNotEqual(fpl.fingerprint(base), fpl.fingerprint({"engine/x.py": "aaa", "@HEAD": "h2"}))  # HEAD moved

    def test_cache_hit_returns_count_only_on_the_exact_same_code_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@HEAD": "h1"}
            fpl.record("us_short", "4497 OK", state=state, ledger=ledger)
            # same code state -> hit; it returns the count so a re-run "just for a number" is unnecessary.
            hit = fpl.cached_green("us_short", state=state, ledger=ledger)
            self.assertIsNotNone(hit)
            self.assertEqual(hit["count"], "4497 OK")
            # a real code change -> miss (a full run is warranted if rule 3 applies).
            self.assertIsNone(fpl.cached_green("us_short", state={"engine/x.py": "bbb", "@HEAD": "h1"}, ledger=ledger))
            # a different lane never reuses this lane's green.
            self.assertIsNone(fpl.cached_green("a_short", state=state, ledger=ledger))

    def test_docs_only_edit_keeps_the_cached_green_via_collect_filter(self):
        # A docs-only change leaves the code-state map identical, so the cached green still matches.
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            code_state = {"engine/x.py": "aaa", "@HEAD": "h1"}       # docs paths are filtered out by collect_code_state
            fpl.record("us_short", "4497 OK", state=code_state, ledger=ledger)
            self.assertIsNotNone(fpl.cached_green("us_short", state=code_state, ledger=ledger))


if __name__ == "__main__":
    unittest.main()
