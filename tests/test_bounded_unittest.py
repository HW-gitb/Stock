from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".tools"))
import bounded_unittest as bounded  # noqa: E402


class BoundedUnittestTests(unittest.TestCase):
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

    def test_cli_rejects_deadlines_above_tier_caps(self):
        self.assertEqual(
            bounded.main(["focused", str(bounded.FOCUSED_MAX_SECONDS + 1), "--", "tests"]),
            2,
        )

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
