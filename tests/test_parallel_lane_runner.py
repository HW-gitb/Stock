"""Guard for the parallel full-pack driver.

Every case here builds a small real test tree and runs the real driver over it
with real worker processes.  Nothing about the aggregation is worth asserting
against a mock: what has to hold is that a pack carried by eight processes
reaches the same verdict a single process would, and that each way it could
quietly under-report is a FAIL rather than a smaller green.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".tools"))
import parallel_lane_runner as driver  # noqa: E402
from bounded_unittest import FULL_PACK_RUNTIME_ARGS, NESTED_RUN_MARKER, Result, run_command  # noqa: E402

PASSING_MODULE = """\
import unittest


class Cases(unittest.TestCase):
{bodies}
"""


def _passing_module(count: int) -> str:
    bodies = "\n".join(
        f"    def test_case_{index}(self):\n        self.assertTrue(True)"
        for index in range(count)
    )
    return PASSING_MODULE.format(bodies=bodies)


FAILING_MODULE = """\
import unittest


class Cases(unittest.TestCase):
    def test_planted_red(self):
        self.assertEqual(1, 2)
"""

# A worker killed mid-run leaves an exit code but no terminal "Ran N" line.
# `os._exit` reproduces exactly that shape without needing to race a real kill.
VANISHING_MODULE = """\
import os
import unittest


class Cases(unittest.TestCase):
    def test_worker_disappears(self):
        os._exit(0)
"""

SLOW_MODULE = """\
import time
import unittest


class Cases(unittest.TestCase):
    def test_slow_enough_to_set_the_floor(self):
        time.sleep(3)
"""

HANGING_MODULE = """\
import time
import unittest


class Cases(unittest.TestCase):
    def test_never_returns(self):
        time.sleep(600)
"""


class ParallelLaneRunnerTests(unittest.TestCase):
    def _tree(self, tmp: str, modules: dict[str, str]) -> tuple[Path, list[str]]:
        root = Path(tmp) / "suite"
        root.mkdir()
        for name, source in modules.items():
            (root / f"{name}.py").write_text(source, encoding="utf-8")
        return root, ["discover", "-s", str(root), "-p", "test_*.py"]

    def _run(self, root: Path, args: list[str], tmp: str, *, timeout: int = 120,
             workers: int = 4):
        return driver.run_parallel_pack(
            "synthetic",
            args,
            timeout,
            workers=workers,
            runs_dir=Path(tmp) / "runs",
            durations_path=Path(tmp) / "durations.json",
            cwd=root,
        )

    def test_green_path_reports_pass_only_when_the_ran_counts_sum_to_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, args = self._tree(tmp, {
                "test_alpha": _passing_module(3),
                "test_beta": _passing_module(2),
                "test_gamma": _passing_module(1),
            })
            result, summary = self._run(root, args, tmp)
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.tests, 6)
        self.assertEqual(summary["discovered_cases"], 6)
        self.assertEqual(summary["ran_cases"], 6)
        self.assertTrue(summary["count_gate_equal"])
        self.assertEqual(summary["mode"], "parallel")
        self.assertEqual(summary["modules_run"], 3)
        self.assertIn("Ran 6 tests", result.output)

    def test_serial_and_parallel_agree_on_the_same_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, args = self._tree(tmp, {
                "test_alpha": _passing_module(3),
                "test_beta": _passing_module(2),
                "test_gamma": _passing_module(1),
            })
            serial = run_command(
                [sys.executable, "-m", "unittest", "discover", *FULL_PACK_RUNTIME_ARGS, *args[1:]],
                120,
                cwd=root,
            )
            parallel, summary = self._run(root, args, tmp)
        self.assertEqual(serial.status, "PASS")
        self.assertEqual(parallel.status, "PASS")
        self.assertEqual(serial.tests, parallel.tests)
        self.assertEqual(serial.tests, summary["discovered_cases"])

    def test_a_planted_red_module_fails_the_pack_and_names_the_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, args = self._tree(tmp, {
                "test_alpha": _passing_module(3),
                "test_red": FAILING_MODULE,
            })
            result, summary = self._run(root, args, tmp)
        self.assertEqual(result.status, "FAIL")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("test_red", result.output)
        self.assertIn("test_planted_red", result.output)
        # The count gate is satisfied here -- a red module still reports the
        # cases it ran -- so this also shows the two gates do not fight: the
        # pack is FAIL for the ordinary reason, not for missing evidence.
        self.assertTrue(summary["count_gate_equal"])
        self.assertNotEqual(result.exit_code, driver.INVALID_EVIDENCE_EXIT)

    def test_a_worker_that_vanishes_is_unknown_and_never_counts_as_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, args = self._tree(tmp, {
                "test_alpha": _passing_module(3),
                "test_vanish": VANISHING_MODULE,
            })
            result, _summary = self._run(root, args, tmp)
        # Exit code 0 with no terminal evidence must not be read as success.
        self.assertEqual(result.status, "FAIL")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("UNKNOWN", result.output)

    def test_a_hung_module_is_killed_and_the_pack_returns_inside_its_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, args = self._tree(tmp, {
                "test_alpha": _passing_module(1),
                "test_hang": HANGING_MODULE,
            })
            result, _summary = self._run(root, args, tmp, timeout=15)
        self.assertEqual(result.status, "TIMEOUT")
        self.assertEqual(result.exit_code, 124)
        self.assertIsNone(result.tests)
        self.assertLess(result.elapsed_seconds, 120)

    def test_dropping_a_module_fails_even_though_every_dispatched_module_is_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, args = self._tree(tmp, {
                "test_alpha": _passing_module(3),
                "test_beta": _passing_module(2),
            })
            with patch.object(driver, "schedule_order", side_effect=lambda counts, durations: ["test_alpha"]):
                result, summary = self._run(root, args, tmp)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.exit_code, driver.INVALID_EVIDENCE_EXIT)
        self.assertEqual(summary["discovered_cases"], 5)
        self.assertEqual(summary["ran_cases"], 3)
        self.assertFalse(summary["count_gate_equal"])

    def test_the_record_carries_the_wall_clock_and_the_module_that_floors_it(self):
        # Wall clock is the only reason this driver exists, and a reviewer citing the ledger under
        # rule 4 reads the record, not the console: the first review had to back-compute it from a
        # machine-local sidecar.  The slowest module travels with it because dispatch is per module,
        # so that module is a floor no worker count can go under.
        with tempfile.TemporaryDirectory() as tmp:
            root, args = self._tree(tmp, {
                "test_alpha": _passing_module(3),
                "test_beta": _passing_module(2),
                # Planted floor: this one decides the wall clock, and naming any other module
                # would make the field decorative rather than actionable.
                "test_slow": SLOW_MODULE,
            })
            result, summary = self._run(root, args, tmp, timeout=90)
        self.assertEqual(result.status, "PASS")
        self.assertGreater(summary["elapsed_seconds"], 0)
        self.assertEqual(summary["deadline_seconds"], 90)
        self.assertEqual(summary["slowest_module"], "test_slow")
        self.assertGreaterEqual(summary["slowest_module_seconds"], 3.0)
        self.assertLessEqual(summary["slowest_module_seconds"], summary["elapsed_seconds"])
        self.assertIn("WALL_CLOCK_FLOOR", result.output)
        self.assertIn("More workers cannot go below it", result.output)
        self.assertIn("test_slow", result.output.split("WALL_CLOCK_FLOOR")[1].splitlines()[0])

    def test_a_discovery_that_under_reports_is_refused_although_the_count_gate_agrees(self):
        # The reviewer's exact probe: drop a module inside discovery itself, so the dispatch list
        # and the expected total shrink together and the count gate compares a number with itself.
        # Planting it in the scheduler (the other control) cannot reach this.
        real = driver.discover_modules

        def dropping(unittest_args, **kwargs):
            counts, path_entries = real(unittest_args, **kwargs)
            counts.pop("test_beta")
            return counts, path_entries

        with tempfile.TemporaryDirectory() as tmp:
            root, args = self._tree(tmp, {
                "test_alpha": _passing_module(3),
                "test_beta": _passing_module(2),
            })
            with patch.object(driver, "discover_modules", side_effect=dropping):
                with self.assertRaisesRegex(ValueError, "did not report 1 file"):
                    self._run(root, args, tmp)

    def test_no_matching_file_goes_unreported_on_either_real_lane(self):
        # The invariant worth pinning is "nothing was missed", not an exact count: one file may
        # legitimately be reported under two names (us_short has such a double import today), and
        # pinning equality would red on that without any coverage being lost.  The anchor also has
        # to walk what discovery walks -- both lanes have package subdirectories (tests/schema,
        # tests/phase6, tests/provider) that a naive rglob would count differently.
        for pattern in ("test_a_short*.py", "test_us_short*.py"):
            with self.subTest(pattern=pattern):
                args = ["discover", "-s", "tests", "-p", pattern]
                counts, path_entries = driver.discover_modules(args)
                unreported, _duplicated = driver._files_against_discovery(
                    counts, path_entries, "tests", pattern,
                )
                self.assertEqual([path.name for path in unreported], [])

    def test_workers_carry_the_nested_marker_and_the_ledger_runtime_flags(self):
        seen = {}

        def observed(command, timeout_seconds, *, cwd=None, extra_env=None):
            seen["command"] = command
            seen["extra_env"] = extra_env
            return Result("PASS", 0, 1, 0.1, "Ran 1 test in 0.1s\n\nOK\n")

        with patch.object(driver, "run_command", side_effect=observed):
            driver._run_module("tests.test_example", 30, None)
        self.assertEqual(
            seen["command"],
            [sys.executable, "-m", "unittest", *FULL_PACK_RUNTIME_ARGS, "tests.test_example"],
        )
        # Without this, eight concurrent workers each let a nested launcher
        # overwrite the single acceptance receipt.
        self.assertEqual(seen["extra_env"], {NESTED_RUN_MARKER: "1"})

    def test_the_sidecar_records_every_module_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, args = self._tree(tmp, {
                "test_alpha": _passing_module(3),
                "test_beta": _passing_module(2),
            })
            _result, summary = self._run(root, args, tmp)
            written = sorted((Path(tmp) / "runs").glob("*_parallel.jsonl"))
            self.assertEqual(len(written), 1)
            rows = [line for line in written[0].read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(len(rows), 3)  # two modules plus the slowest-test record
        self.assertIn("test_alpha", rows[0] + rows[1])
        self.assertIn("test_beta", rows[0] + rows[1])
        self.assertIsNotNone(summary["sidecar"])

    def test_discovery_comes_from_the_callers_selector_and_refuses_what_it_cannot_reproduce(self):
        self.assertEqual(
            driver.parse_discovery_args(["discover", "-s", "tests", "-p", "test_a_short*.py"]),
            ("tests", "test_a_short*.py", ""),
        )
        with self.assertRaisesRegex(ValueError, "discover"):
            driver.parse_discovery_args(["tests.test_example"])
        # An unrecognised flag could narrow selection without the driver
        # noticing, so it is refused rather than dropped.
        with self.assertRaisesRegex(ValueError, "cannot reproduce"):
            driver.parse_discovery_args(["discover", "-k", "pattern", "-s", "tests"])

    def test_workers_inherit_the_import_path_discovery_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, args = self._tree(tmp, {"test_alpha": _passing_module(1)})
            counts, path_entries = driver.discover_modules(args, cwd=root)
        self.assertEqual(counts, {"test_alpha": 1})
        # Discovery reaches a bare module name by putting its directory on
        # sys.path; a worker handed only the name needs the same entry.
        self.assertIn(str(root), path_entries)

        with patch.dict("os.environ", {"PYTHONPATH": "existing_entry"}):
            env = driver.worker_environment(
                ["resolved_entry"], cwd=Path(tmp), start_dir="tests"
            )
        self.assertEqual(env[NESTED_RUN_MARKER], "1")
        # Prepended, not replaced: the launcher already puts the vendored
        # library directory here and a worker still needs it.
        self.assertEqual(
            env["PYTHONPATH"],
            os.path.abspath(tmp) + os.pathsep
            + os.path.abspath(os.path.join(tmp, "resolved_entry")) + os.pathsep
            + os.path.abspath(os.path.join(tmp, "tests")) + os.pathsep
            + "existing_entry",
        )

    def test_worker_can_import_nested_discovery_package_from_explicit_start_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "suite"
            package = root / "phase6"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "test_guard.py").write_text(
                _passing_module(2), encoding="utf-8"
            )
            env = driver.worker_environment([], cwd=parent, start_dir=str(root))
            outcome = driver._run_module(
                "phase6.test_guard", 60, None, cwd=parent, worker_env=env
            )
        self.assertEqual(outcome.status, "PASS")
        self.assertEqual(outcome.tests, 2)

    def test_modules_reaching_a_cross_process_lock_are_derived_into_the_serial_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "shared_root.py").write_text(
                "import msvcrt\n\n\ndef take(handle):\n"
                "    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)\n",
                encoding="utf-8",
            )
            (root / "helper.py").write_text("import shared_root\n", encoding="utf-8")
            (root / "test_locked.py").write_text(
                "import helper\n" + _passing_module(1), encoding="utf-8",
            )
            (root / "test_free.py").write_text(_passing_module(1), encoding="utf-8")
            args = ["discover", "-s", str(root), "-p", "test_*.py"]
            counts, path_entries = driver.discover_modules(args, cwd=root)
            tail = driver.serial_tail_modules(counts, path_entries)
        # Reached through an intermediate helper, not only by direct import.
        self.assertEqual(tail, {"test_locked"})

    def test_the_derived_tail_matches_what_each_real_lane_actually_contains(self):
        a_short, a_paths = driver.discover_modules(
            ["discover", "-s", "tests", "-p", "test_a_short*.py"]
        )
        us_short, us_paths = driver.discover_modules(
            ["discover", "-s", "tests", "-p", "test_us_short*.py"]
        )
        # a_short reaches no cross-process lock, which is why its whole pack
        # runs concurrently; us_short shares one private root helper, and its
        # dependents produced `Resource deadlock avoided` before this existed.
        self.assertEqual(driver.serial_tail_modules(a_short, a_paths), set())
        us_tail = driver.serial_tail_modules(us_short, us_paths)
        self.assertIn("provider.test_us_short_universe_fetch", us_tail)

    def test_the_serial_tail_runs_after_the_wave_and_counts_toward_the_same_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "suite"
            root.mkdir()
            (root / "shared_root.py").write_text(
                "import msvcrt\n\n\ndef take(handle):\n"
                "    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)\n",
                encoding="utf-8",
            )
            (root / "test_locked.py").write_text(
                "import shared_root\n" + _passing_module(2), encoding="utf-8",
            )
            (root / "test_free.py").write_text(_passing_module(3), encoding="utf-8")
            args = ["discover", "-s", str(root), "-p", "test_*.py"]
            result, summary = self._run(root, args, tmp)
        self.assertEqual(result.status, "PASS")
        self.assertEqual(summary["serial_tail"], ["test_locked"])
        self.assertEqual(summary["ran_cases"], 5)
        self.assertTrue(summary["count_gate_equal"])
        self.assertEqual(summary["modules_run"], 2)

    def test_longest_first_uses_measurement_when_it_exists_and_case_count_before_that(self):
        counts = {"test_small": 1, "test_big": 500}
        self.assertEqual(driver.schedule_order(counts, {}), ["test_big", "test_small"])
        self.assertEqual(
            driver.schedule_order(counts, {"test_small": 200.0, "test_big": 1.0}),
            ["test_small", "test_big"],
        )


if __name__ == "__main__":
    unittest.main()
