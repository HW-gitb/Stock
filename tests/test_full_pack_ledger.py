"""Guard for the full-pack run ledger (verification tiering rule 4: one full run per unchanged code diff)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".tools"))
from bounded_unittest import Result  # noqa: E402
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
            fpl.prepare("us_short", "shared engine", "focused=12 OK", state=state, ledger=ledger)
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
            fpl.prepare("us_short", "shared engine", "focused=12 OK", state=code_state, ledger=ledger)
            fpl.record("us_short", "4497 OK", state=code_state, ledger=ledger)
            self.assertIsNotNone(fpl.cached_green("us_short", state=code_state, ledger=ledger))

    def test_record_refuses_without_a_matching_af_prepare(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@HEAD": "h1"}
            with self.assertRaisesRegex(ValueError, "matching prepare"):
                fpl.record("a_short", "2000 OK", state=state, ledger=ledger)

    def test_behavior_change_after_prepare_invalidates_the_final_full_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            prepared_state = {"engine/x.py": "aaa", "@HEAD": "h1"}
            changed_state = {"engine/x.py": "bbb", "@HEAD": "h1"}
            fpl.prepare("a_short", "production consumer", "focused=20 OK",
                        state=prepared_state, ledger=ledger)
            with self.assertRaisesRegex(ValueError, "matching prepare"):
                fpl.record("a_short", "2000 OK", state=changed_state, ledger=ledger)
            self.assertIsNone(fpl.prepared_review("a_short", state=changed_state, ledger=ledger))

    def test_prepare_requires_a_trigger_reason_and_focused_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@HEAD": "h1"}
            with self.assertRaisesRegex(ValueError, "trigger reason"):
                fpl.prepare("a_short", "", "focused=20 OK", state=state, ledger=ledger)
            with self.assertRaisesRegex(ValueError, "focused-test evidence"):
                fpl.prepare("a_short", "production consumer", "", state=state, ledger=ledger)

    def test_cli_prepare_refuses_missing_attestation_without_a_traceback(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(fpl.main(["ledger", "prepare", "a_short", "", "focused=20 OK"]), 2)
        self.assertIn("REFUSED", output.getvalue())

    def test_public_manual_record_is_retired(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(fpl.main(["ledger", "record", "a_short", "2000 OK"]), 2)
        self.assertIn("single `run` command", output.getvalue())

    def test_cli_single_run_routes_the_whole_chain(self):
        with patch.object(fpl, "run_full_pack", return_value=0) as runner:
            self.assertEqual(
                fpl.main([
                    "ledger", "run", "a_short", "shared schema", "focused=12 OK",
                    "30", "--", "tests.test_x",
                ]),
                0,
            )
        runner.assert_called_once_with(
            "a_short", "shared schema", "focused=12 OK", 30, ["tests.test_x"]
        )

    def test_single_run_command_prepares_runs_and_records_only_real_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@HEAD": "h1"}
            passed = Result("PASS", 0, 3, 0.2, "Ran 3 tests in 0.1s\n\nOK\n")
            with patch.object(fpl, "run_unittest", return_value=passed):
                self.assertEqual(
                    fpl.run_full_pack(
                        "a_short",
                        "shared schema",
                        "focused=12 OK",
                        30,
                        ["tests.test_x"],
                        state=state,
                        ledger=ledger,
                    ),
                    0,
                )
            hit = fpl.cached_green("a_short", state=state, ledger=ledger)
            self.assertIsNotNone(hit)
            self.assertEqual(hit["count"], "3 OK")

    def test_single_run_timeout_never_records_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@HEAD": "h1"}
            timed_out = Result("TIMEOUT", 124, None, 1.0, "")
            with patch.object(fpl, "run_unittest", return_value=timed_out):
                self.assertEqual(
                    fpl.run_full_pack(
                        "a_short",
                        "shared schema",
                        "focused=12 OK",
                        30,
                        ["tests.test_x"],
                        state=state,
                        ledger=ledger,
                    ),
                    124,
                )
            self.assertIsNone(fpl.cached_green("a_short", state=state, ledger=ledger))

    def test_check_shows_the_prepared_review_and_matching_green_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@HEAD": "h1"}
            fpl.prepare("a_short", "shared schema", "focused=31 OK", state=state, ledger=ledger)
            fpl.record("a_short", "2000 OK", state=state, ledger=ledger)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(fpl._check("a_short", state=state, ledger=ledger), 0)
            self.assertIn("PREPARED A-F", output.getvalue())
            self.assertIn("CACHED GREEN", output.getvalue())

    def test_legacy_green_is_historical_but_not_reusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@HEAD": "h1"}
            ledger.write_text(
                '{"a_short": {"fingerprint": "' + fpl.fingerprint(state)
                + '", "count": "1999 OK", "recorded_at": "old"}}',
                encoding="utf-8",
            )
            self.assertIsNone(fpl.cached_green("a_short", state=state, ledger=ledger))
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(fpl._check("a_short", state=state, ledger=ledger), 1)
            self.assertIn("STALE LEGACY GREEN", output.getvalue())
            self.assertIn("not reusable closeout evidence", output.getvalue())

            passed = Result("PASS", 0, 2, 0.1, "Ran 2 tests in 0.1s\n\nOK\n")
            with patch.object(fpl, "run_unittest", return_value=passed) as runner:
                self.assertEqual(
                    fpl.run_full_pack(
                        "a_short", "production entrypoint", "focused=9 OK", 30,
                        ["tests.test_x"], state=state, ledger=ledger,
                    ),
                    0,
                )
            runner.assert_called_once()
            self.assertEqual(fpl.cached_green("a_short", state=state, ledger=ledger)["count"], "2 OK")


if __name__ == "__main__":
    unittest.main()
