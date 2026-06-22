# -*- coding: utf-8 -*-
"""Tests for US-short §4.5 dynamic seats (engine/us_short_dynamic_seats.py) — design test item #15.

Adversarial focus: the theme_opportunity_state → Top15 split (12+3 / 10+5 / 8+7, total 15), fail-closed
to the no_strong_theme split on an unknown state, copy-safety, and the 强赛道周 leader-upgrade allowance.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_dynamic_seats as ds  # noqa: E402

_GOV = ROOT / "presets" / "us_short_theme_probe_governance_20260622.json"


class SeatSplitTests(unittest.TestCase):
    def test_split_per_state(self):
        self.assertEqual(ds.selection_seats("no_strong_theme"), {"core_top": 12, "theme_momentum": 3})
        self.assertEqual(ds.selection_seats("normal"), {"core_top": 10, "theme_momentum": 5})
        self.assertEqual(ds.selection_seats("strong"), {"core_top": 8, "theme_momentum": 7})
        self.assertEqual(ds.selection_seats("extreme"), {"core_top": 8, "theme_momentum": 7})

    def test_total_always_15(self):
        for state in ("no_strong_theme", "normal", "strong", "extreme", "bogus", None):
            s = ds.selection_seats(state)
            self.assertEqual(s["core_top"] + s["theme_momentum"], ds.SELECTION_SEAT_TOTAL, state)

    def test_unknown_state_fails_closed_to_no_strong_split(self):
        for bad in ("bogus", None, "", 1, "STRONG"):
            self.assertEqual(ds.selection_seats(bad), {"core_top": 12, "theme_momentum": 3}, repr(bad))

    def test_returned_split_is_copy_safe(self):
        s = ds.selection_seats("strong")
        s["theme_momentum"] = 99
        self.assertEqual(ds.selection_seats("strong"), {"core_top": 8, "theme_momentum": 7})


class LeaderUpgradeTests(unittest.TestCase):
    def test_strong_week_allows_upgrades(self):
        self.assertEqual(ds.strong_theme_leader_upgrade_max("strong"), ds.STRONG_THEME_LEADER_UPGRADE_MAX)
        self.assertEqual(ds.strong_theme_leader_upgrade_max("extreme"), ds.STRONG_THEME_LEADER_UPGRADE_MAX)

    def test_non_strong_week_allows_none(self):
        for state in ("no_strong_theme", "normal", "bogus", None, "STRONG"):
            self.assertEqual(ds.strong_theme_leader_upgrade_max(state), 0, repr(state))

    def test_upgrade_max_is_one_or_two(self):
        self.assertIn(ds.STRONG_THEME_LEADER_UPGRADE_MAX, (1, 2))   # §4.5 line 52 "1–2 只"


class ContractTests(unittest.TestCase):
    def test_splits_match_preset_map(self):
        gov = json.loads(_GOV.read_text(encoding="utf-8"))
        self.assertEqual(ds.SELECTION_SEAT_TOTAL, gov["selection_seat_total"])
        for row in gov["selection_seat_map"]:
            self.assertEqual(ds.selection_seats(row["state"]),
                             {"core_top": row["core_top"], "theme_momentum": row["theme_momentum"]}, row["state"])


if __name__ == "__main__":
    unittest.main()
