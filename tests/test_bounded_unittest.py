from __future__ import annotations

import os
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".tools"))
import bounded_unittest as bounded  # noqa: E402


class BoundedUnittestTests(unittest.TestCase):
    def test_runner_does_not_force_pythonioencoding_into_children(self):
        source = Path(bounded.__file__).read_text(encoding="utf-8")
        self.assertNotIn('child_env["PYTHONIOENCODING"]', source)

    def test_real_unittest_pass_has_terminal_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "test_sample.py"
            test_file.write_text(
                "import unittest\n"
                "class Sample(unittest.TestCase):\n"
                "    def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            result = bounded.run_unittest(["discover", "-s", tmp], 10)
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.tests, 1)

    def test_a_share_provider_dependencies_do_not_poison_us_short_full_gate(self):
        with (
            patch.object(
                bounded,
                "find_spec",
                side_effect=lambda name: None if name in {"akshare", "tushare"} else object(),
            ),
        ):
            a_short_error = bounded.external_test_dependency_error("a_short")
            us_short_error = bounded.external_test_dependency_error("us_short")
        self.assertIn("akshare", a_short_error)
        self.assertIn("tushare", a_short_error)
        self.assertIsNone(us_short_error)

    def test_us_short_discovery_uses_the_official_unittest_entry(self):
        passed = bounded.Result("PASS", 0, 1, 0.1, "Ran 1 test in 0.1s\n\nOK\n")
        with (
            patch.object(bounded, "find_spec", return_value=None),
            patch.object(bounded, "run_command", return_value=passed) as runner,
        ):
            result = bounded.run_unittest(["discover", "-s", "tests", "-p", "test_us_short*.py"], 10)
        self.assertEqual(result, passed)
        runner.assert_called_once_with(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_us_short*.py"],
            10,
            cwd=bounded.ROOT,
            extra_env=None,
        )

    def test_zero_exit_without_unittest_summary_is_unknown(self):
        result = bounded.run_command([sys.executable, "-c", "print('not a test result')"], 10)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.exit_code, bounded.INVALID_EVIDENCE_EXIT)

    def test_zero_tests_is_unknown_not_pass(self):
        result = bounded.run_command(
            [sys.executable, "-c", "print('Ran 0 tests in 0.0s')"],
            10,
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.exit_code, bounded.INVALID_EVIDENCE_EXIT)

    def test_timeout_is_bounded_and_not_pass(self):
        result = bounded.run_command(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            1,
        )
        self.assertEqual(result.status, "TIMEOUT")
        self.assertEqual(result.exit_code, bounded.TIMEOUT_EXIT)
        self.assertLess(result.elapsed_seconds, 5)

    def test_cli_keeps_separate_full_and_explicit_focused_ceilings(self):
        self.assertEqual(bounded.FULL_MAX_SECONDS, 860)
        self.assertEqual(bounded.FOCUSED_DEFAULT_SECONDS, 300)
        self.assertEqual(bounded.FOCUSED_MAX_SECONDS, 1300)
        self.assertEqual(
            bounded._parse(["full", "860", "--", "tests"]),
            ("full", 860, ["tests"]),
        )
        self.assertEqual(
            bounded._parse(["focused", "600", "--", "tests"]),
            ("focused", 600, ["tests"]),
        )
        self.assertEqual(
            bounded.main(["focused", str(bounded.FOCUSED_MAX_SECONDS + 1), "--", "tests"]),
            2,
        )

    def test_launcher_passes_explicit_timeout_without_leaking_it_to_unittest(self):
        launcher = Path(__file__).resolve().parents[1] / ".tools" / "run_unittest_with_repo_pythonpath.cmd"
        result = subprocess.run(
            [
                str(launcher), "--timeout-seconds", "600",
                "tests.test_bounded_unittest.BoundedUnittestTests.test_zero_tests_is_unknown_not_pass",
            ],
            cwd=str(launcher.parents[1]),
            env=dict(os.environ, STOCK_BOUNDED_UNITTEST_ACTIVE="1"),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("deadline=600s", result.stdout)

    def test_launcher_usage_errors_exit_non_zero_and_run_no_tests(self):
        """GOV-R4: a usage error printed a message but exited 0, so a typo read as a green pack."""
        launcher = Path(__file__).resolve().parents[1] / ".tools" / "run_unittest_with_repo_pythonpath.cmd"
        for args, expected_message in (
            (["--timeout-seconds"], "requires a positive integer"),
            (["--timeout-seconds", "600"], "requires unittest arguments"),
        ):
            with self.subTest(args=args):
                result = subprocess.run(
                    [str(launcher), *args],
                    cwd=str(launcher.parents[1]),
                    env=dict(os.environ, STOCK_BOUNDED_UNITTEST_ACTIVE="1"),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(expected_message, result.stdout)
                self.assertNotIn("Ran ", result.stdout)

    def test_cleanup_failure_path_is_still_bounded(self):
        class StuckProcess:
            pid = 123
            returncode = None

            def __init__(self):
                self.calls = 0
                self.killed = False

            def communicate(self, timeout=None):
                self.calls += 1
                raise bounded.subprocess.TimeoutExpired(["fake"], timeout, output="partial")

            def kill(self):
                self.killed = True

            def poll(self):
                return None

        cleanup_errors = (
            bounded.subprocess.TimeoutExpired(["taskkill"], 5),
            OSError("taskkill could not start"),
        )
        for cleanup_error in cleanup_errors:
            with self.subTest(cleanup_error=type(cleanup_error).__name__):
                process = StuckProcess()
                with (
                    patch.object(bounded.subprocess, "Popen", return_value=process),
                    patch.object(bounded, "_stop_owned_tree", side_effect=cleanup_error),
                ):
                    result = bounded.run_command(["fake"], 1)
                self.assertTrue(process.killed)
                self.assertEqual(process.calls, 3)
                self.assertEqual(result.status, "TIMEOUT")
                self.assertEqual(result.exit_code, bounded.TIMEOUT_EXIT)

    def test_windows_cleanup_targets_only_the_owned_pid_tree(self):
        source = Path(bounded.__file__).read_text(encoding="utf-8")
        self.assertIn('["taskkill", "/PID", str(process.pid), "/T", "/F"]', source)
        self.assertNotIn("Get-Process", source)
        self.assertNotIn("psutil", source)
        self.assertEqual(
            bounded.main(["full", str(bounded.FULL_MAX_SECONDS + 1), "--", "tests"]),
            2,
        )


if __name__ == "__main__":
    unittest.main()


class NestedRunDoesNotClobberReceiptTests(unittest.TestCase):
    """A launcher run started from inside another run must not touch the receipt.

    Several tests legitimately spawn the launcher -- the jsonschema self-check
    in the doc-governance guard, the preflight guard, and this module.  Each of
    those minted a bundle-less receipt over the real one, so `.githooks/pre-commit`
    destroyed the evidence it then demanded and every bundle-requiring commit was
    permanently blocked.  The fix is a nesting marker in bounded_unittest, so this
    covers the whole class rather than the one spawn site that demonstrated it.
    """

    def test_marker_suppresses_the_receipt_write(self):
        launcher = Path(__file__).resolve().parents[1] / ".tools" / "run_unittest_with_repo_pythonpath.cmd"
        root = launcher.parents[1]
        receipt_path = root / ".tools" / "state" / "focused_acceptance_receipt.json"
        before = receipt_path.read_bytes() if receipt_path.exists() else None

        env = os.environ.copy()
        env["STOCK_BOUNDED_UNITTEST_ACTIVE"] = "1"
        result = subprocess.run(
            [str(launcher), "tests.test_doc_governance_guard.JsonschemaImportSmoke"],
            cwd=str(root), env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("NESTED - acceptance receipt left untouched", result.stdout)

        after = receipt_path.read_bytes() if receipt_path.exists() else None
        self.assertEqual(before, after, "a nested run overwrote the acceptance receipt")

    def test_every_launcher_spawn_in_tests_sets_the_marker(self):
        """No new spawn site may forget it -- that is how this class recurs.

        Patching the four existing sites fixes today; this guard fixes tomorrow.
        A test that spawns the launcher without the marker mints a bundle-less
        receipt over the real one, which is what blocked every bundle-requiring
        commit until it was found.
        """
        import ast

        tests_dir = Path(__file__).resolve().parent
        offenders = []
        for path in sorted(tests_dir.rglob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # The marker may be set at the call or where its env dict is built,
            # so the enclosing function is the honest scope to search.
            scopes = [n for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for scope in scopes:
                marked = "STOCK_BOUNDED_UNITTEST_ACTIVE" in ast.dump(scope)
                for node in ast.walk(scope):
                    if not isinstance(node, ast.Call):
                        continue
                    if getattr(node.func, "attr", None) != "run" or not node.args:
                        continue
                    argv = ast.dump(node.args[0])
                    if "launcher" not in argv and "run_unittest_with_repo_pythonpath" not in argv:
                        continue
                    if not marked:
                        offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(
            offenders, [],
            "these launcher spawns would clobber the acceptance receipt; pass "
            "STOCK_BOUNDED_UNITTEST_ACTIVE=1 in their env: " + ", ".join(offenders),
        )


class DocumentOnlyRunDoesNotClobberReceiptTests(unittest.TestCase):
    DOC_ARGS = [
        "tests.test_route_doc_ledger_status_consistency",
        "tests.test_doc_governance_guard",
    ]

    def test_document_gate_classifier_is_exact_and_bidirectional(self):
        self.assertTrue(bounded._is_document_only_focused_run(self.DOC_ARGS))
        self.assertTrue(bounded._is_document_only_focused_run(list(reversed(self.DOC_ARGS))))
        self.assertFalse(bounded._is_document_only_focused_run(self.DOC_ARGS + ["-v"]))
        self.assertFalse(bounded._is_document_only_focused_run([self.DOC_ARGS[0], self.DOC_ARGS[0]]))
        self.assertFalse(bounded._is_document_only_focused_run(["tests.test_bounded_unittest"]))

    def test_document_gate_preserves_existing_receipt_without_collecting_or_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt_path = root / "focused_acceptance_receipt.json"
            sentinel = b"existing-code-receipt\n"
            receipt_path.write_bytes(sentinel)
            result = bounded.Result("PASS", 0, 55, 0.1, "Ran 55 tests in 0.1s\n\nOK\n")
            with (
                patch.object(bounded, "ROOT", root),
                patch.object(bounded, "run_unittest", return_value=result),
                patch.object(bounded.receipts, "RECEIPT_PATH", receipt_path),
                patch.object(bounded.receipts, "collect_code_state") as collect_state,
                patch.object(bounded.receipts, "write_focused_receipt") as write_receipt,
                patch.dict(os.environ, {bounded.NESTED_RUN_MARKER: ""}),
            ):
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = bounded.main(["focused", "300", "--", *self.DOC_ARGS])
            self.assertEqual(exit_code, 0, output.getvalue())
            self.assertEqual(receipt_path.read_bytes(), sentinel)
            collect_state.assert_not_called()
            write_receipt.assert_not_called()
            self.assertIn("DOC_ONLY - acceptance receipt left untouched", output.getvalue())

    def test_document_gate_does_not_fabricate_missing_receipt_and_code_gate_still_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt_path = root / "focused_acceptance_receipt.json"
            result = bounded.Result("PASS", 0, 1, 0.1, "Ran 1 test in 0.1s\n\nOK\n")
            replacement = {
                "receipt_id": "new",
                "bundles": [],
                "tests": 1,
                "python_executable": str(bounded.receipts.PINNED_PYTHON),
            }
            with (
                patch.object(bounded, "ROOT", root),
                patch.object(bounded, "run_unittest", return_value=result),
                patch.object(bounded.receipts, "RECEIPT_PATH", receipt_path),
                patch.object(bounded.receipts, "collect_code_state", return_value={"@CODE_CONTENT": "x"}),
                patch.object(bounded.receipts, "write_focused_receipt", return_value=replacement) as write_receipt,
                patch.dict(os.environ, {bounded.NESTED_RUN_MARKER: ""}),
            ):
                with redirect_stdout(io.StringIO()):
                    document_exit = bounded.main(["focused", "300", "--", *self.DOC_ARGS])
                self.assertEqual(document_exit, 0)
                self.assertFalse(receipt_path.exists())
                write_receipt.assert_not_called()
                with patch.dict(os.environ, {bounded.NESTED_RUN_MARKER: ""}):
                    with redirect_stdout(io.StringIO()):
                        code_exit = bounded.main(["focused", "300", "--", "tests.test_bounded_unittest"])
                self.assertEqual(code_exit, 0)
                write_receipt.assert_called_once()
