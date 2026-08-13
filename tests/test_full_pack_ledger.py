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
from tests.provider import us_short_module_runner as module_runner  # noqa: E402

FOCUSED_RECEIPT = "receipt:test"


class FullPackLedgerTests(unittest.TestCase):
    def setUp(self):
        # Production run_full_pack always requires a real receipt and static
        # gate.  These tests use synthetic code states, so inject only the
        # evidence boundary rather than weakening the implementation.
        self._receipt_gate = patch.object(
            fpl,
            "_receipt_matches_current_state",
            return_value=(
                {"tests": 12, "bundles": []},
                "OK",
            ),
        )
        self._static_gate = patch.object(fpl, "_pre_full_static_checks", return_value=True)
        self._receipt_gate.start()
        self._static_gate.start()

    def tearDown(self):
        self._static_gate.stop()
        self._receipt_gate.stop()

    def test_per_module_private_root_snapshot_reports_new_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = {
                "provider_samples": Path(tmp) / "provider_samples",
                "state/us_short": Path(tmp) / "state" / "us_short",
            }
            roots["provider_samples"].mkdir(parents=True)
            before = module_runner.snapshot_protected_entries(roots)
            (roots["provider_samples"] / "new.json").write_text("{}", encoding="utf-8")
            after = module_runner.snapshot_protected_entries(roots)
            self.assertEqual(
                after - before,
                frozenset({("provider_samples", "file", "new.json")}),
            )

    def test_per_module_suite_turns_residue_into_a_test_failure(self):
        passing = unittest.FunctionTestCase(lambda: None)
        guarded = module_runner.GuardedModuleSuite(
            "tests.planted_test_us_short", unittest.TestSuite([passing])
        )
        before = frozenset()
        after = frozenset({("provider_samples", "file", "left.json")})
        result = unittest.TestResult()
        with patch.object(
            module_runner,
            "snapshot_protected_entries",
            side_effect=(before, after),
        ):
            guarded.run(result)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("tests.planted_test_us_short", result.failures[0][0].id())

    def test_full_pack_timeout_ceiling_is_860_seconds(self):
        self.assertEqual(fpl.FULL_MAX_SECONDS, 860)
        with self.assertRaisesRegex(ValueError, r"full timeout must be 1\.\.860 seconds"):
            fpl.run_full_pack(
                "us_short",
                "shared test infrastructure",
                FOCUSED_RECEIPT,
                861,
                ["discover", "-s", "tests", "-p", "test_us_short*.py"],
            )

    def test_interrupted_private_root_cleanup_requires_helper_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "provider_samples"
            parent.mkdir()
            marked = parent / "tmp-marked"
            marked.mkdir()
            (marked / fpl.PRIVATE_TEST_ROOT_MARKER).write_text("", encoding="utf-8")
            unmarked = parent / "tmp-unmarked"
            unmarked.mkdir()
            (unmarked / "keep.json").write_text("{}", encoding="utf-8")
            removed = fpl.cleanup_orphaned_private_test_roots((parent,))
            self.assertEqual(removed, (marked.resolve(),))
            self.assertFalse(marked.exists())
            self.assertTrue(unmarked.exists())

    def test_new_tmp_root_cleanup_is_bound_to_run_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "provider_samples"
            parent.mkdir()
            old = parent / "tmp-old"
            old.mkdir()
            before = fpl.snapshot_private_test_dirs((parent,))
            new = parent / "tmp-new"
            new.mkdir()
            (new / "raw.json").write_text("{}", encoding="utf-8")
            removed = fpl.cleanup_new_private_test_roots(before, (parent,))
            self.assertEqual(removed, (new.resolve(),))
            self.assertTrue(old.exists())

    def test_docs_and_markdown_edits_do_not_count_as_code_state(self):
        # rule 4: a docs/register/SESSION_LOG-only correction must NOT invalidate a code full-pack.
        for doc in ("docs/SESSION_LOG.md", "docs/system_risk_register.md", "AGENTS.md", "README.md"):
            self.assertFalse(fpl._is_code_path(doc), doc)
        for code in (
            "engine/us_short_core_score.py",
            "presets/x.json",
            "schemas/y.schema.json",
            "tests/test_z.py",
            "docs/runtime_contract.json",
        ):
            self.assertTrue(fpl._is_code_path(code), code)

    def test_fingerprint_is_deterministic_and_state_sensitive(self):
        # The `@` key carries the content seal; the per-path entries beside it
        # say which files a commit touches and are deliberately not sealed, so
        # that staging or committing the tested bytes does not move the id.
        base = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
        self.assertEqual(fpl.fingerprint(base), fpl.fingerprint(dict(base)))          # deterministic
        self.assertNotEqual(fpl.fingerprint(base), fpl.fingerprint({"engine/x.py": "aaa", "@CODE_CONTENT": "c2"}))  # code edit
        self.assertEqual(fpl.fingerprint(base), fpl.fingerprint({"@CODE_CONTENT": "c1"}))  # same bytes, now committed

    def test_cache_hit_returns_count_only_on_the_exact_same_code_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
            fpl.prepare("us_short", "shared engine", FOCUSED_RECEIPT, state=state, ledger=ledger)
            fpl.record("us_short", "4497 OK", state=state, ledger=ledger)
            # same code state -> hit; it returns the count so a re-run "just for a number" is unnecessary.
            hit = fpl.cached_green("us_short", state=state, ledger=ledger)
            self.assertIsNotNone(hit)
            self.assertEqual(hit["count"], "4497 OK")
            # a real code change -> miss (a full run is warranted if rule 3 applies).
            self.assertIsNone(fpl.cached_green("us_short", state={"engine/x.py": "aaa", "@CODE_CONTENT": "c2"}, ledger=ledger))
            # a different lane never reuses this lane's green.
            self.assertIsNone(fpl.cached_green("a_short", state=state, ledger=ledger))

    def test_docs_only_edit_keeps_the_cached_green_via_collect_filter(self):
        # A docs-only change leaves the code-state map identical, so the cached green still matches.
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            code_state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}       # docs paths are filtered out by collect_code_state
            fpl.prepare("us_short", "shared engine", FOCUSED_RECEIPT, state=code_state, ledger=ledger)
            fpl.record("us_short", "4497 OK", state=code_state, ledger=ledger)
            self.assertIsNotNone(fpl.cached_green("us_short", state=code_state, ledger=ledger))

    def test_record_refuses_without_a_matching_af_prepare(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
            with self.assertRaisesRegex(ValueError, "matching prepare"):
                fpl.record("a_short", "2000 OK", state=state, ledger=ledger)

    def test_behavior_change_after_prepare_invalidates_the_final_full_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            prepared_state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
            changed_state = {"engine/x.py": "bbb", "@HEAD": "h1"}
            fpl.prepare("a_short", "production consumer", FOCUSED_RECEIPT,
                        state=prepared_state, ledger=ledger)
            with self.assertRaisesRegex(ValueError, "matching prepare"):
                fpl.record("a_short", "2000 OK", state=changed_state, ledger=ledger)
            self.assertIsNone(fpl.prepared_review("a_short", state=changed_state, ledger=ledger))

    def test_prepare_requires_a_trigger_reason_and_focused_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
            with self.assertRaisesRegex(ValueError, "trigger reason"):
                fpl.prepare("a_short", "", FOCUSED_RECEIPT, state=state, ledger=ledger)
            with self.assertRaisesRegex(ValueError, "focused-test evidence"):
                fpl.prepare("a_short", "production consumer", "", state=state, ledger=ledger)

    def test_prepare_rejects_free_text_before_writing_a_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
            with self.assertRaisesRegex(ValueError, "machine focused receipt token"):
                fpl.prepare("a_short", "production consumer", "focused=20 OK", state=state, ledger=ledger)
            self.assertFalse(ledger.exists())

    def test_cli_prepare_refuses_missing_attestation_without_a_traceback(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(fpl.main(["ledger", "prepare", "a_short", "", FOCUSED_RECEIPT]), 2)
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
                    "ledger", "run", "a_short", "shared schema", FOCUSED_RECEIPT,
                    "30", "--", "discover", "-s", "tests", "-p", "test_a_short*.py",
                ]),
                0,
            )
        runner.assert_called_once_with(
            "a_short", "shared schema", FOCUSED_RECEIPT, 30,
            ["discover", "-s", "tests", "-p", "test_a_short*.py"],
        )

    def test_cli_run_argument_errors_are_explicit_and_never_start_a_pack(self):
        for argv, expected in (
            (["ledger", "run", "a_short", "shared schema", FOCUSED_RECEIPT, "30"], "missing `--`"),
            (["ledger", "run", "a_short", "shared schema", FOCUSED_RECEIPT, "30", "unexpected", "--", "discover"],
             "expected `run <lane>"),
        ):
            with self.subTest(argv=argv), patch.object(fpl, "run_full_pack") as runner:
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(fpl.main(argv), 2)
                self.assertIn("REFUSED", output.getvalue())
                self.assertIn(expected, output.getvalue())
                runner.assert_not_called()

    def test_full_pack_rejects_free_text_before_spawning_any_test(self):
        state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                fpl,
                "_receipt_matches_current_state",
                return_value=(None, "focused evidence must be the machine token"),
            ), patch.object(fpl, "external_test_dependency_error", return_value=None), patch.object(
                fpl, "_execute_full_pack"
            ) as runner:
                output = StringIO()
                with redirect_stdout(output):
                    result = fpl.run_full_pack(
                        "a_short",
                        "shared schema",
                        "focused=12 OK",
                        30,
                        ["discover", "-s", "tests", "-p", "test_a_short*.py"],
                        state=state,
                        ledger=Path(tmp) / "ledger.json",
                    )
            self.assertEqual(result, 2)
            self.assertIn("REFUSED", output.getvalue())
            runner.assert_not_called()

    def test_full_pack_prints_start_before_spawning_each_lane(self):
        for lane, args in fpl.FULL_PACK_DISCOVERY_ARGS.items():
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as tmp:
                ledger = Path(tmp) / "ledger.json"
                state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
                output = StringIO()
                passed = Result("PASS", 0, 3, 0.2, "Ran 3 tests in 0.1s\n\nOK\n")

                def observed_run(actual_lane, actual_args, timeout_seconds):
                    self.assertEqual(actual_lane, lane)
                    self.assertEqual(actual_args, list(args))
                    self.assertEqual(timeout_seconds, 30)
                    self.assertIn(f"START lane={lane}", output.getvalue())
                    self.assertIn("fingerprint=", output.getvalue())
                    return passed, {"mode": "parallel"}

                with patch.object(fpl, "_execute_full_pack", side_effect=observed_run):
                    with redirect_stdout(output):
                        self.assertEqual(
                            fpl.run_full_pack(
                                lane, "shared test tool", FOCUSED_RECEIPT, 30, list(args),
                                state=state, ledger=ledger,
                            ),
                            0,
                        )
                self.assertIn("RESULT status=PASS", output.getvalue())

    def test_full_pack_runtime_optimization_keeps_discovery_and_adds_only_safe_flags(self):
        self.assertEqual(
            fpl.FULL_PACK_RUNTIME_ARGS,
            ("-b", "-f", "--durations", "25"),
        )
        for lane, discovery in fpl.FULL_PACK_DISCOVERY_ARGS.items():
            with self.subTest(lane=lane):
                self.assertEqual(discovery[:3], ("discover", "-s", "tests"))
                self.assertIn("-p", discovery)
                self.assertTrue(discovery[-1].startswith("test_"))
                self.assertTrue(discovery[-1].endswith("*.py"))
                # The selector must reach the runner untouched, and the runtime
                # flags must reach it as flags -- not spliced into discovery,
                # where an unrecognised one could quietly change selection.
                with patch.object(fpl.parallel_lane_runner, "run_parallel_pack") as spawn:
                    spawn.return_value = (Result("PASS", 0, 1, 0.1, ""), {"mode": "parallel"})
                    fpl._execute_full_pack(lane, list(discovery), 30)
                spawn.assert_called_once_with(
                    lane, list(discovery), 30, runtime_args=fpl.FULL_PACK_RUNTIME_ARGS,
                )

    def test_only_a_real_unittest_spawn_may_print_start(self):
        state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
        for lane, args in fpl.FULL_PACK_DISCOVERY_ARGS.items():
            with self.subTest(lane=lane, case="dependency"), tempfile.TemporaryDirectory() as tmp:
                output = StringIO()
                with patch.object(fpl, "external_test_dependency_error", return_value="missing test dependency"), \
                        patch.object(fpl, "_execute_full_pack") as runner, redirect_stdout(output):
                    self.assertEqual(
                        fpl.run_full_pack(lane, "shared test tool", FOCUSED_RECEIPT, 30, list(args),
                                          state=state, ledger=Path(tmp) / "ledger.json"),
                        fpl.DEPENDENCY_EXIT,
                    )
                self.assertNotIn("START lane=", output.getvalue())
                runner.assert_not_called()

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            fpl.prepare("a_short", "shared test tool", FOCUSED_RECEIPT, state=state, ledger=ledger)
            fpl.record("a_short", "3 OK", state=state, ledger=ledger)
            output = StringIO()
            with patch.object(fpl, "_execute_full_pack") as runner, redirect_stdout(output):
                self.assertEqual(
                    fpl.run_full_pack(
                        "a_short", "shared test tool", FOCUSED_RECEIPT, 30,
                        ["discover", "-s", "tests", "-p", "test_a_short*.py"],
                        state=state, ledger=ledger,
                    ),
                    0,
                )
            self.assertIn("CACHED GREEN", output.getvalue())
            self.assertNotIn("START lane=", output.getvalue())
            runner.assert_not_called()

        output = StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(ValueError, "unknown lane"):
            fpl.run_full_pack(
                "unknown", "shared test tool", FOCUSED_RECEIPT, 30,
                ["discover", "-s", "tests", "-p", "test_unknown*.py"], state=state,
            )
        self.assertNotIn("START lane=", output.getvalue())

    def test_single_run_command_prepares_runs_and_records_only_real_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
            passed = Result("PASS", 0, 3, 0.2, "Ran 3 tests in 0.1s\n\nOK\n")
            with patch.object(fpl, "_execute_full_pack", return_value=(passed, {"mode": "parallel"})):
                self.assertEqual(
                    fpl.run_full_pack(
                        "a_short",
                        "shared schema",
                        FOCUSED_RECEIPT,
                        30,
                        ["discover", "-s", "tests", "-p", "test_a_short*.py"],
                        state=state,
                        ledger=ledger,
                    ),
                    0,
                )
            hit = fpl.cached_green("a_short", state=state, ledger=ledger)
            self.assertIsNotNone(hit)
            self.assertEqual(hit["count"], "3 OK")

    def test_the_recorded_green_carries_how_it_was_obtained(self):
        # Rule 4 has the reviewer cite this record instead of re-running. A count alone cannot
        # support the claim the run was making, so whatever the executor measured travels with it.
        detail = {"mode": "parallel", "elapsed_seconds": 339.5, "deadline_seconds": 860,
                  "slowest_module": "test_a_short_theme_forward_comparison",
                  "slowest_module_seconds": 330.7, "count_gate_equal": True}
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
            passed = Result("PASS", 0, 3, 0.2, "Ran 3 tests in 0.1s\n\nOK\n")
            with patch.object(fpl, "_execute_full_pack", return_value=(passed, detail)):
                self.assertEqual(
                    fpl.run_full_pack(
                        "a_short", "shared schema", FOCUSED_RECEIPT, 30,
                        ["discover", "-s", "tests", "-p", "test_a_short*.py"],
                        state=state, ledger=ledger,
                    ),
                    0,
                )
            self.assertEqual(
                fpl.cached_green("a_short", state=state, ledger=ledger)["run_detail"], detail
            )

    def test_a_share_provider_dependency_blocks_only_a_short_full_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
            fpl.prepare("a_short", "shared schema", FOCUSED_RECEIPT, state=state, ledger=ledger)
            fpl.record("a_short", "3 OK", state=state, ledger=ledger)
            passed = Result("PASS", 0, 3, 0.2, "Ran 3 tests in 0.1s\n\nOK\n")
            with patch.object(
                fpl,
                "external_test_dependency_error",
                side_effect=lambda lane: "required external test modules unavailable: akshare, tushare"
                if lane == "a_short" else None,
            ), patch.object(
                fpl, "_execute_full_pack", return_value=(passed, {"mode": "parallel"})
            ) as runner:
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        fpl.run_full_pack(
                            "a_short", "shared schema", FOCUSED_RECEIPT, 30,
                            ["discover", "-s", "tests", "-p", "test_a_short*.py"],
                            state=state, ledger=ledger,
                        ),
                        fpl.DEPENDENCY_EXIT,
                    )
                    self.assertEqual(fpl._check("a_short", state=state, ledger=ledger), 1)
                    self.assertEqual(
                        fpl.run_full_pack(
                            "us_short", "shared schema", FOCUSED_RECEIPT, 30,
                            ["discover", "-s", "tests", "-p", "test_us_short*.py"],
                            state=state, ledger=ledger,
                        ),
                        0,
                    )
            self.assertIn("akshare", output.getvalue())
            runner.assert_called_once()
            self.assertIsNotNone(fpl.cached_green("a_short", state=state, ledger=ledger))

    def test_common_dependency_blocks_both_full_pack_lanes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
            with patch.object(
                fpl,
                "external_test_dependency_error",
                return_value="required external test modules unavailable: jsonschema",
            ), patch.object(fpl, "_execute_full_pack") as runner:
                for lane, args in fpl.FULL_PACK_DISCOVERY_ARGS.items():
                    with self.subTest(lane=lane):
                        self.assertEqual(
                            fpl.run_full_pack(lane, "shared schema", FOCUSED_RECEIPT, 30, list(args),
                                              state=state, ledger=ledger),
                            fpl.DEPENDENCY_EXIT,
                        )
            runner.assert_not_called()

    def test_single_run_rejects_subset_and_unknown_lane(self):
        state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            with self.assertRaisesRegex(ValueError, "test_a_short\\*\\.py"):
                fpl.run_full_pack(
                    "a_short", "shared schema", FOCUSED_RECEIPT, 30, ["tests.test_x"],
                    state=state, ledger=ledger,
                )
            with self.assertRaisesRegex(ValueError, "test_a_short\\*\\.py"):
                fpl.run_full_pack(
                    "a_short", "shared schema", FOCUSED_RECEIPT, 30,
                    ["discover", "-s", "other", "-p", "test_a_short*.py"],
                    state=state, ledger=ledger,
                )
            with self.assertRaisesRegex(ValueError, "unknown lane"):
                fpl.run_full_pack(
                    "unknown", "shared schema", FOCUSED_RECEIPT, 30,
                    ["discover", "-s", "tests", "-p", "test_unknown*.py"],
                    state=state, ledger=ledger,
                )

    def test_single_run_timeout_never_records_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
            timed_out = Result("TIMEOUT", 124, None, 1.0, "")
            with patch.object(fpl, "_execute_full_pack", return_value=(timed_out, {"mode": "parallel"})):
                self.assertEqual(
                    fpl.run_full_pack(
                        "a_short",
                        "shared schema",
                        FOCUSED_RECEIPT,
                        30,
                        ["discover", "-s", "tests", "-p", "test_a_short*.py"],
                        state=state,
                        ledger=ledger,
                    ),
                    124,
                )
            self.assertIsNone(fpl.cached_green("a_short", state=state, ledger=ledger))

    def test_check_shows_the_prepared_review_and_matching_green_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
            fpl.prepare("a_short", "shared schema", FOCUSED_RECEIPT, state=state, ledger=ledger)
            fpl.record("a_short", "2000 OK", state=state, ledger=ledger)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(fpl._check("a_short", state=state, ledger=ledger), 0)
            self.assertIn("PREPARED A-F", output.getvalue())
            self.assertIn("CACHED GREEN", output.getvalue())

    def test_legacy_green_is_historical_but_not_reusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            state = {"engine/x.py": "aaa", "@CODE_CONTENT": "c1"}
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
            with patch.object(
                fpl, "_execute_full_pack", return_value=(passed, {"mode": "parallel"})
            ) as runner:
                self.assertEqual(
                    fpl.run_full_pack(
                        "a_short", "production entrypoint", FOCUSED_RECEIPT, 30,
                        ["discover", "-s", "tests", "-p", "test_a_short*.py"],
                        state=state, ledger=ledger,
                    ),
                    0,
                )
            runner.assert_called_once()
            self.assertEqual(fpl.cached_green("a_short", state=state, ledger=ledger)["count"], "2 OK")


if __name__ == "__main__":
    unittest.main()
