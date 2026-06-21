# -*- coding: utf-8 -*-
"""Tests for US-short forward known-date events (engine/us_short_forward_events.py) — §8.1.

Adversarial focus: the window boundary (past / out-of-window → none), per-type direction coverage, the
sensitive-type missing-data escalation (biotech / recent_ipo are NOT plain unknowns), and whole-class
input validation incl. the `window_days` default param and a strict `has_event_data` flag.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_forward_events as fe  # noqa: E402


class ForwardEventEffectTests(unittest.TestCase):
    def test_every_event_type_has_its_direction_in_window(self):
        for et in fe.EVENT_TYPES:
            out = fe.forward_event_effect(et, 5)
            self.assertTrue(out["in_window"], et)
            self.assertEqual(out["direction"], fe._EVENT_DIRECTION[et], et)

    def test_window_boundaries_inclusive(self):
        self.assertTrue(fe.forward_event_effect("earnings", 0)["in_window"])        # today
        self.assertTrue(fe.forward_event_effect("earnings", fe.WINDOW_DAYS)["in_window"])  # exactly the window
        self.assertFalse(fe.forward_event_effect("earnings", fe.WINDOW_DAYS + 1)["in_window"])

    def test_past_event_is_not_in_window(self):
        out = fe.forward_event_effect("earnings", -1)
        self.assertFalse(out["in_window"])
        self.assertEqual(out["direction"], "none")

    def test_unknown_event_type_is_none(self):
        out = fe.forward_event_effect("merger_rumor", 5)
        self.assertFalse(out["in_window"])
        self.assertEqual(out["direction"], "none")

    def test_malformed_days_is_none(self):
        for bad in ("5", True, float("nan"), float("inf"), None):
            out = fe.forward_event_effect("earnings", bad)
            self.assertFalse(out["in_window"], repr(bad))
            self.assertEqual(out["direction"], "none", repr(bad))

    def test_window_override_and_bad_window_fail_closed(self):
        self.assertTrue(fe.forward_event_effect("earnings", 30, window_days=35)["in_window"])   # valid wider window
        for bad in ("35", True, None, 0, -5, float("nan")):
            # bad window → default 21 → a 30-day-out earnings is out of window
            self.assertFalse(fe.forward_event_effect("earnings", 30, window_days=bad)["in_window"], repr(bad))


class EventDataGapTests(unittest.TestCase):
    def test_sensitive_missing_data_escalates(self):
        self.assertEqual(fe.event_data_gap_status("biotech", False)["status"], "restricted")
        self.assertEqual(fe.event_data_gap_status("biotech", None)["status"], "restricted")
        self.assertEqual(fe.event_data_gap_status("recent_ipo", False)["status"], "reduce_caution")

    def test_spac_missing_lockup_escalates_like_ipo(self):
        # design §8.1 "IPO/SPAC": every SPAC spelling / case must escalate, never fall to ordinary tag
        for t in ("spac", "SPAC", "recent_spac", "recent_ipo_spac", " spac "):
            self.assertEqual(fe.event_data_gap_status(t, False)["status"], "reduce_caution", repr(t))

    def test_only_explicit_ordinary_is_tag(self):
        self.assertEqual(fe.event_data_gap_status("ordinary", False)["status"], "tag")
        self.assertEqual(fe.event_data_gap_status(" ORDINARY ", False)["status"], "tag")   # normalised

    def test_unknown_or_malformed_type_fails_closed_not_tag(self):
        # REVERSE-FAILURE control: an unknown / malformed sensitive type + missing data must NOT pass as the
        # lenient ordinary tag — it fails closed to restricted (§8.1 缺数据≠普通 unknown).
        for bad in ("bogus", "biotechh", "", None, True, 1, 0):
            self.assertEqual(fe.event_data_gap_status(bad, False)["status"], "restricted", repr(bad))

    def test_case_and_whitespace_normalise(self):
        self.assertEqual(fe.event_data_gap_status(" Biotech ", False)["status"], "restricted")

    def test_has_data_only_exact_true_is_ok(self):
        self.assertEqual(fe.event_data_gap_status("biotech", True)["status"], "ok")
        # a truthy-but-not-True flag is treated as missing (fail closed) -> biotech escalates
        self.assertEqual(fe.event_data_gap_status("biotech", "yes")["status"], "restricted")
        self.assertEqual(fe.event_data_gap_status("biotech", 1)["status"], "restricted")


class ContractTests(unittest.TestCase):
    def test_direction_map_covers_every_event_type(self):
        self.assertEqual(set(fe._EVENT_DIRECTION), set(fe.EVENT_TYPES))

    def test_forward_events_never_hard_veto(self):
        # §8.1: forward events affect sizing/risk/display only — the direction vocab carries no veto
        for et in fe.EVENT_TYPES:
            self.assertNotIn("veto", fe.forward_event_effect(et, 5)["direction"])


if __name__ == "__main__":
    unittest.main()
