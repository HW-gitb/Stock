# -*- coding: utf-8 -*-
"""Tests for the US-short reusable fail-closed private-path guard (engine/us_short_private_paths.py).

Satisfies the batch-2 首刀 half of §18.0 P0 / §18.1 #1 / R-USSHORT-PRIVATE-PATH-FAILCLOSED-GUARD-TEST:
a guard using the real `git check-ignore` value so any in-repo, non-gitignored private output path
fails fast, AND git-unavailable / unexpected-rc fail-closed. Mirrors the converter's PrivacyGuardTests
(no in-repo override). Adversarial by design — the time-saver is fewer FAIL->修复 rounds.
"""
import inspect
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_private_paths as pp  # noqa: E402

PPE = pp.PrivatePathError

# state/*/runs_private/ AND state/*/*.json are both gitignored -> definitely private
_IGNORED = ROOT / "state" / "us_short" / "runs_private" / "zz_priv_guard_probe.json"
# docs/ is tracked -> definitely NOT gitignored
_NONIGNORED = ROOT / "docs" / "zz_us_short_priv_guard_probe.json"


class PrivatePathGuardTests(unittest.TestCase):
    def test_outside_repo_ok(self):
        with tempfile.TemporaryDirectory() as d:
            pp.reject_nonprivate_output_path(str(Path(d) / "out.json"))  # no raise

    def test_gitignored_in_repo_ok(self):
        pp.reject_nonprivate_output_path(str(_IGNORED))  # no raise (private)

    def test_nonignored_in_repo_raises(self):
        with self.assertRaises(PPE):
            pp.reject_nonprivate_output_path(str(_NONIGNORED))

    def test_no_inrepo_override_exists(self):
        # There must be NO escape that lets an in-repo non-gitignored path through: the guard takes
        # only out_path (no override arg), mirroring the converter's no-override design.
        params = list(inspect.signature(pp.reject_nonprivate_output_path).parameters)
        self.assertEqual(params, ["out_path"], "guard must not accept an override argument")
        with self.assertRaises(PPE):
            pp.reject_nonprivate_output_path(str(_NONIGNORED))

    def test_git_unavailable_fail_closed(self):
        # cannot verify the path is gitignored -> refuse, even for a normally-ignored path
        import unittest.mock as mock
        with mock.patch.object(pp.subprocess, "run", side_effect=FileNotFoundError("git")):
            with self.assertRaises(PPE):
                pp.reject_nonprivate_output_path(str(_IGNORED))

    def test_git_oserror_fail_closed(self):
        import unittest.mock as mock
        with mock.patch.object(pp.subprocess, "run", side_effect=OSError("boom")):
            with self.assertRaises(PPE):
                pp.reject_nonprivate_output_path(str(_IGNORED))

    def test_git_unexpected_rc_fail_closed(self):
        import unittest.mock as mock

        class _R:
            returncode = 2
        with mock.patch.object(pp.subprocess, "run", return_value=_R()):
            with self.assertRaises(PPE):
                pp.reject_nonprivate_output_path(str(_IGNORED))

    def test_outside_repo_does_not_call_git(self):
        # outside-repo short-circuits BEFORE invoking git (so a broken git can't block an external write)
        import unittest.mock as mock
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(pp.subprocess, "run", side_effect=AssertionError("git must not run")) as m:
                pp.reject_nonprivate_output_path(str(Path(d) / "out.json"))
                self.assertEqual(m.call_count, 0)

    def test_relative_path_fails_closed(self):
        # a relative path resolves against the process CWD, not the repo root — from a non-root CWD it could
        # resolve OUTSIDE the repo and bypass the git-check gate, so it must fail closed (require absolute).
        # NB: `state/us_short/runs_private/x.json` would be gitignored-OK if ABSOLUTE, yet is refused as relative.
        for rel in ("state/us_short/runs_private/x.json", "out.json", "../x.json",
                    "state/us_short/weekly_private/x.json", "./runs_private/x.json"):
            with self.assertRaises(PPE, msg=rel):
                pp.reject_nonprivate_output_path(rel)

    def test_relative_path_does_not_call_git(self):
        # the relative-path refusal happens BEFORE any git invocation (fail-closed at the boundary)
        import unittest.mock as mock
        with mock.patch.object(pp.subprocess, "run", side_effect=AssertionError("git must not run")) as m:
            with self.assertRaises(PPE):
                pp.reject_nonprivate_output_path("state/us_short/runs_private/x.json")
            self.assertEqual(m.call_count, 0)


if __name__ == "__main__":
    unittest.main()
