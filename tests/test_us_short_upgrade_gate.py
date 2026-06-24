# -*- coding: utf-8 -*-
"""Tests for US-short §12.2 anti-self-deception upgrade gate (engine/us_short_upgrade_gate.py).

Covers: the readiness decision (accumulating < min_comparison_weeks; at/over min but margin NOT frozen →
review_due_margin_pending [the current governance state]; at/over min AND margin frozen → review_due_ready);
margin_frozen only on a numeric finite comparison_win_margin; the §12.2 ② anti-self-deception (12+ obs without a
frozen margin still never authorizes, AND a self-authored comparison_win_margin_frozen=True + review_due_ready is
re-derived from governance and refused); §12.2 ③ forward obs strictly ascending + unique (out-of-order / duplicate
refused); §12.2 ① no look-ahead (obs after the eval as_of refused on build + validate); de-identified obs (nested
ticker / performance field refused); non-dict governance fails closed; the non-production boundary; and the
CLOSED-WORLD validator (extra key / boundary tamper / doctored due or status refused, incl. a strict bool gate on
upgrade_review_due so a numerically-equal `0==False` int bypass is refused). Pure/offline; no provider/live; no
A-share crossing.
"""
import copy
import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_upgrade_gate as ug  # noqa: E402

AS_OF = "20260330"
FROZEN_GOV = {"min_comparison_weeks": 12, "comparison_win_margin": 0.02}  # a reviewed governance that froze the margin


def _obs(n):
    """n strictly-ascending unique weekly observations (real calendar dates)."""
    start = datetime.date(2026, 1, 5)
    return [{"as_of": (start + datetime.timedelta(days=7 * i)).strftime("%Y%m%d")} for i in range(n)]


class Readiness(unittest.TestCase):
    def test_accumulating_below_min(self):
        s = ug.build_upgrade_eval(_obs(5), as_of=AS_OF)
        self.assertEqual(s["decision_status"], ug.ACCUMULATING)
        self.assertFalse(s["upgrade_review_due"])
        self.assertEqual(s["n_forward_observations"], 5)
        self.assertEqual(s["min_comparison_weeks"], 12)

    def test_due_margin_pending_current_governance(self):
        # 12 obs but the real scoring_profile governance has NO numeric comparison_win_margin → never authorizes
        s = ug.build_upgrade_eval(_obs(12), as_of=AS_OF)
        self.assertTrue(s["upgrade_review_due"])
        self.assertFalse(s["comparison_win_margin_frozen"])
        self.assertEqual(s["decision_status"], ug.REVIEW_DUE_MARGIN_PENDING)

    def test_due_ready_when_margin_frozen(self):
        s = ug.build_upgrade_eval(_obs(12), as_of=AS_OF, governance=FROZEN_GOV)
        self.assertTrue(s["comparison_win_margin_frozen"])
        self.assertEqual(s["decision_status"], ug.REVIEW_DUE_READY)

    def test_over_min_without_margin_still_pending(self):
        # §12.2 ② anti-self-deception: even well over the min weeks, no frozen margin → no upgrade authorization
        s = ug.build_upgrade_eval(_obs(30), as_of="20260801")  # as_of after the last weekly obs (no look-ahead)
        self.assertEqual(s["decision_status"], ug.REVIEW_DUE_MARGIN_PENDING)

    def test_boundary_non_production(self):
        s = ug.build_upgrade_eval(_obs(3), as_of=AS_OF)
        self.assertEqual(s["boundary"], {"production": False, "is_upgrade_decision": False, "satisfies_ship_gate": False})

    def test_empty_obs_accumulating(self):
        s = ug.build_upgrade_eval([], as_of=AS_OF)
        self.assertEqual((s["n_forward_observations"], s["decision_status"]), (0, ug.ACCUMULATING))


class MarginFrozen(unittest.TestCase):
    def test_numeric_margin_frozen(self):
        self.assertTrue(ug.margin_frozen({"comparison_win_margin": 0.0}))
        self.assertTrue(ug.margin_frozen({"comparison_win_margin": 0.05}))

    def test_non_numeric_or_absent_not_frozen(self):
        for gov in ({}, {"comparison_win_margin": None}, {"comparison_win_margin": "pending"},
                    {"comparison_win_margin": True}, {"comparison_win_margin": float("nan")}):
            self.assertFalse(ug.margin_frozen(gov))

    def test_real_preset_margin_not_frozen(self):
        self.assertFalse(ug.margin_frozen())  # the committed scoring_profile governance has no numeric margin yet


class ForwardObsContract(unittest.TestCase):
    def test_out_of_order_refused(self):
        with self.assertRaises(ug.UpgradeGateError):
            ug.build_upgrade_eval([{"as_of": "20260112"}, {"as_of": "20260105"}], as_of=AS_OF)

    def test_duplicate_week_refused(self):
        with self.assertRaises(ug.UpgradeGateError):
            ug.build_upgrade_eval([{"as_of": "20260105"}, {"as_of": "20260105"}], as_of=AS_OF)

    def test_bad_obs_as_of_refused(self):
        with self.assertRaises(ug.UpgradeGateError):
            ug.build_upgrade_eval([{"as_of": "20260231"}], as_of=AS_OF)  # not a real date

    def test_obs_not_dict_refused(self):
        with self.assertRaises(ug.UpgradeGateError):
            ug.build_upgrade_eval(["20260105"], as_of=AS_OF)

    def test_obs_not_list_refused(self):
        with self.assertRaises(ug.UpgradeGateError):
            ug.build_upgrade_eval({"as_of": "20260105"}, as_of=AS_OF)

    def test_bad_as_of_param_refused(self):
        with self.assertRaises(ug.UpgradeGateError):
            ug.build_upgrade_eval(_obs(3), as_of="20260231")

    def test_bad_governance_min_weeks_refused(self):
        with self.assertRaises(ug.UpgradeGateError):
            ug.build_upgrade_eval(_obs(3), as_of=AS_OF, governance={"min_comparison_weeks": 0})

    def test_nested_extra_field_in_obs_refused_on_build(self):
        # de-identified: an obs must be EXACTLY {as_of} — a smuggled ticker / performance field is refused
        with self.assertRaises(ug.UpgradeGateError):
            ug.build_upgrade_eval([{"as_of": "20260105", "ticker": "AAA", "net_basket_delta": 0.1}], as_of=AS_OF)

    def test_obs_after_eval_as_of_refused_on_build(self):
        # §12.2 ① no look-ahead: a week dated after the decision date can't be counted into it
        with self.assertRaises(ug.UpgradeGateError):
            ug.build_upgrade_eval([{"as_of": "20260406"}], as_of="20260330")

    def test_nondict_governance_refused_on_build(self):
        with self.assertRaises(ug.UpgradeGateError):
            ug.build_upgrade_eval(_obs(3), as_of=AS_OF, governance=123)


class Validator(unittest.TestCase):
    def setUp(self):
        self.good = ug.build_upgrade_eval(_obs(5), as_of=AS_OF)

    def _rejects(self, mutate):
        bad = copy.deepcopy(self.good)
        mutate(bad)
        with self.assertRaises(ug.UpgradeGateError):
            ug.validate_upgrade_eval(bad)

    def test_good_passes(self):
        ug.validate_upgrade_eval(self.good)

    def test_extra_key_refused(self):
        self._rejects(lambda b: b.__setitem__("note", "x"))

    def test_boundary_tamper_refused(self):
        self._rejects(lambda b: b["boundary"].__setitem__("production", True))

    def test_doctored_due_refused(self):
        self._rejects(lambda b: b.__setitem__("upgrade_review_due", True))  # n=5 < 12 → due must be False

    def test_doctored_status_refused(self):
        self._rejects(lambda b: b.__setitem__("decision_status", ug.REVIEW_DUE_READY))  # inconsistent with not-due

    def test_count_mismatch_refused(self):
        self._rejects(lambda b: b.__setitem__("n_forward_observations", 99))

    def test_self_authored_ready_refused(self):
        # headline anti-self-deception: under the current no-margin governance, a report can't simply edit in
        # comparison_win_margin_frozen=True + review_due_ready (validate re-derives the margin from governance)
        s = ug.build_upgrade_eval(_obs(12), as_of=AS_OF)  # review_due_margin_pending, frozen False
        s["comparison_win_margin_frozen"] = True
        s["decision_status"] = ug.REVIEW_DUE_READY
        with self.assertRaises(ug.UpgradeGateError):
            ug.validate_upgrade_eval(s)  # default (current committed) governance has no numeric margin → rejects

    def test_nested_ticker_in_obs_refused(self):
        self._rejects(lambda b: b["forward_observations"][0].__setitem__("ticker", "AAA"))

    def test_obs_after_eval_as_of_refused(self):
        # §12.2 ① no look-ahead: the last obs set after the eval as_of (still ascending vs prev) is rejected
        self._rejects(lambda b: b["forward_observations"][-1].__setitem__("as_of", "20260801"))

    def test_nondict_governance_in_validate_refused(self):
        with self.assertRaises(ug.UpgradeGateError):
            ug.validate_upgrade_eval(self.good, governance=[1, 2])

    def test_margin_frozen_status_consistency(self):
        # under a frozen-margin governance, due must be review_due_ready, not margin_pending
        good_ready = ug.build_upgrade_eval(_obs(12), as_of=AS_OF, governance=FROZEN_GOV)
        bad = copy.deepcopy(good_ready)
        bad["decision_status"] = ug.REVIEW_DUE_MARGIN_PENDING
        with self.assertRaises(ug.UpgradeGateError):
            ug.validate_upgrade_eval(bad, governance=FROZEN_GOV)

    def test_bool_review_due_refused(self):
        # R-USSHORT-BATCH3-UPGRADE-GATE-DUE-BOOL-BYPASS: upgrade_review_due true value False (n=5<12) doctored to
        # the equal int 0 (0==False) must be refused by the strict bool gate, NOT slip past the bare `!=`
        self.assertFalse(self.good["upgrade_review_due"])
        self._rejects(lambda b: b.__setitem__("upgrade_review_due", 0))


if __name__ == "__main__":
    unittest.main()
