# -*- coding: utf-8 -*-
"""Tests for US-short §12.2 upgrade-gate runtime banner (engine/us_short_upgrade_banner.py).

Covers: the per-status one-line banner (accumulating / review_due_margin_pending under current governance /
review_due_ready under a frozen-margin governance), the 'USER decides, never auto-production' caveat; fail-closed
UNAVAILABLE on a malformed eval, a self-authored frozen-ready eval (re-validated against governance), and a
frozen-margin eval validated without its governance; and the GUARANTEED-ASCII output. Pure/offline; no
provider/live; no A-share crossing.
"""
import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_upgrade_gate as ug  # noqa: E402
import engine.us_short_upgrade_banner as ub  # noqa: E402

AS_OF = "20260330"
FROZEN_GOV = {"min_comparison_weeks": 12, "comparison_win_margin": 0.001}


def _obs(n):
    start = datetime.date(2026, 1, 5)
    return [{"as_of": (start + datetime.timedelta(days=7 * i)).strftime("%Y%m%d")} for i in range(n)]


class Banner(unittest.TestCase):
    def test_accumulating(self):
        b = ub.upgrade_banner(ug.build_upgrade_eval(_obs(5), as_of=AS_OF))
        self.assertIn("ACCUMULATING", b)
        self.assertIn("5/12", b)
        self.assertTrue(b.isascii())

    def test_due_margin_pending_current_governance(self):
        b = ub.upgrade_banner(ug.build_upgrade_eval(_obs(12), as_of=AS_OF))
        self.assertIn("DUE", b)
        self.assertIn("NOT frozen", b)
        self.assertIn("NOT authorized", b)
        self.assertIn("never auto-production", b)

    def test_due_ready_with_frozen_governance(self):
        e = ug.build_upgrade_eval(_obs(12), as_of=AS_OF, governance=FROZEN_GOV)
        b = ub.upgrade_banner(e, governance=FROZEN_GOV)
        self.assertIn("win-margin frozen", b)
        self.assertIn("RAISED", b)
        self.assertIn("USER decides", b)
        self.assertTrue(b.isascii())

    def test_malformed_eval_unavailable(self):
        self.assertEqual(ub.upgrade_banner({}), ub._UNAVAILABLE)
        self.assertEqual(ub.upgrade_banner("nope"), ub._UNAVAILABLE)

    def test_self_authored_ready_unavailable(self):
        # an eval that self-authored frozen=True under the current (no-margin) governance → validate rejects
        e = ug.build_upgrade_eval(_obs(12), as_of=AS_OF)
        e["comparison_win_margin_frozen"] = True
        e["decision_status"] = ug.REVIEW_DUE_READY
        self.assertEqual(ub.upgrade_banner(e), ub._UNAVAILABLE)

    def test_frozen_eval_without_its_governance_unavailable(self):
        # a frozen-margin eval validated against the DEFAULT (no-margin) governance → UNAVAILABLE (must pass the gov)
        e = ug.build_upgrade_eval(_obs(12), as_of=AS_OF, governance=FROZEN_GOV)
        self.assertEqual(ub.upgrade_banner(e), ub._UNAVAILABLE)

    def test_always_ascii(self):
        for e in (ug.build_upgrade_eval(_obs(0), as_of=AS_OF), ug.build_upgrade_eval(_obs(12), as_of=AS_OF)):
            self.assertTrue(ub.upgrade_banner(e).isascii())
        self.assertTrue(ub.upgrade_banner({}).isascii())


if __name__ == "__main__":
    unittest.main()
