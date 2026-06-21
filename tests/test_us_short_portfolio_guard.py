# -*- coding: utf-8 -*-
"""Tests for US-short portfolio_guard (engine/us_short_portfolio_guard.py) — §8 组合级熔断.

Adversarial focus: the fail-safe (paper track not evaluable / malformed metrics → caution, NEVER clean),
the trigger→state mapping, per-state effects + copy-safety, and conformance to the frozen preset.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_portfolio_guard as pg  # noqa: E402

_GOV = ROOT / "presets" / "us_short_portfolio_guard_governance_20260620.json"


class FailSafeTests(unittest.TestCase):
    def test_paper_not_evaluable_never_clean(self):
        # REVERSE-FAILURE control: anything but exact True for paper_evaluable → caution (no data ≠ safe)
        for bad in (False, None, "yes", 1, 0):
            out = pg.classify_portfolio_guard(bad, consecutive_stops=0, paper_drawdown_frac=0.0)
            self.assertEqual(out["state"], "caution", repr(bad))
            self.assertTrue(out["fail_safe"], repr(bad))

    def test_malformed_metrics_on_evaluable_track_fail_closed(self):
        for stops, dd in (("3", 0.0), (None, 0.0), (-1, 0.0), (0, "0.1"), (0, float("nan")), (0, -0.1)):
            out = pg.classify_portfolio_guard(True, consecutive_stops=stops, paper_drawdown_frac=dd)
            self.assertEqual(out["state"], "caution", (stops, dd))
            self.assertTrue(out["fail_safe"], (stops, dd))

    def test_fractional_or_nonint_stop_count_fails_closed(self):
        # a consecutive-stop COUNT is an integer event tally — fractional / bool / integer-valued float
        # must NOT pass as a live metric (2.9 -> normal or 3.1 -> cooldown both wrong); fail closed
        for stops in (0.5, 2.1, 2.9, 3.0, 3.1, True, "3"):
            out = pg.classify_portfolio_guard(True, consecutive_stops=stops, paper_drawdown_frac=0.0)
            self.assertEqual(out["state"], "caution", repr(stops))
            self.assertEqual(out["reason"], "malformed_paper_metrics", repr(stops))
            self.assertTrue(out["fail_safe"], repr(stops))

    def test_malformed_prior_state_fails_closed_not_normal(self):
        # a corrupted persisted guard state must NOT yield a clean normal (metrics otherwise clean)
        for ps in ("bogus", None, True, 1, "", "Cooldown"):
            out = pg.classify_portfolio_guard(True, consecutive_stops=0, paper_drawdown_frac=0.0, prior_state=ps)
            self.assertEqual(out["state"], "caution", repr(ps))
            self.assertEqual(out["reason"], "malformed_prior_state", repr(ps))
            self.assertTrue(out["fail_safe"], repr(ps))


class TriggerTests(unittest.TestCase):
    def test_consecutive_stops_trigger_cooldown(self):
        self.assertEqual(pg.classify_portfolio_guard(True, consecutive_stops=3)["state"], "cooldown")

    def test_drawdown_thresholds(self):
        self.assertEqual(pg.classify_portfolio_guard(True, paper_drawdown_frac=0.10)["state"], "cooldown")
        self.assertEqual(pg.classify_portfolio_guard(True, paper_drawdown_frac=0.05)["state"], "caution")
        self.assertEqual(pg.classify_portfolio_guard(True, paper_drawdown_frac=0.0)["state"], "normal")

    def test_integer_stop_counts_valid(self):
        # positive control: legal integer counts are NOT over-suppressed by the new count validation
        self.assertEqual(pg.classify_portfolio_guard(True, consecutive_stops=0)["state"], "normal")
        self.assertEqual(pg.classify_portfolio_guard(True, consecutive_stops=2)["state"], "normal")
        self.assertEqual(pg.classify_portfolio_guard(True, consecutive_stops=3)["state"], "cooldown")

    def test_valid_prior_states_not_over_suppressed(self):
        # cooldown prior -> recovery; every other VALID prior with clean metrics -> normal (not caution)
        self.assertEqual(pg.classify_portfolio_guard(True, prior_state="cooldown")["state"], "recovery")
        for ps in ("normal", "caution", "recovery"):
            out = pg.classify_portfolio_guard(True, prior_state=ps)
            self.assertEqual(out["state"], "normal", ps)
            self.assertFalse(out["fail_safe"], ps)


class EffectsTests(unittest.TestCase):
    def test_cooldown_blocks_new_and_add(self):
        e = pg.portfolio_guard_effects("cooldown")
        self.assertTrue(e["block_new_entry"])
        self.assertTrue(e["block_add"])
        self.assertTrue(e["holding_risk_control_only"])

    def test_caution_reduces(self):
        e = pg.portfolio_guard_effects("caution")
        self.assertTrue(e["reduce_position_size"])
        self.assertTrue(e["reduce_weekly_new_count"])

    def test_unknown_state_fails_closed(self):
        with self.assertRaises(KeyError):
            pg.portfolio_guard_effects("bogus")

    def test_effects_are_copy_safe(self):
        e = pg.portfolio_guard_effects("cooldown")
        e["block_new_entry"] = False
        self.assertTrue(pg.portfolio_guard_effects("cooldown")["block_new_entry"])


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gov = json.loads(_GOV.read_text(encoding="utf-8"))

    def test_state_set_matches_preset(self):
        self.assertEqual(pg.PORTFOLIO_GUARD_STATES, tuple(self.gov["portfolio_guard_states"]))

    def test_effects_match_preset(self):
        preset = {e["state"]: e["effects"] for e in self.gov["state_effects"]}
        for s in pg.PORTFOLIO_GUARD_STATES:
            self.assertEqual(pg.portfolio_guard_effects(s), preset[s], s)

    def test_advisory_only_and_failsafe_declared(self):
        self.assertTrue(self.gov["advisory_only"])
        self.assertTrue(self.gov["fail_safe"]["paper_not_evaluable_forbids_clean"])


if __name__ == "__main__":
    unittest.main()
