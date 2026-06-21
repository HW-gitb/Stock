# -*- coding: utf-8 -*-
"""Tests for US-short ship_gate_sizing (engine/us_short_ship_gate_sizing.py) — §8 ship-gate sizing.

Adversarial focus: hard veto = 0 position, maturity is a reminder NOT a cap (model size never shrunk),
paper / not-evaluable / un-graduated evidence is NEVER a full-size license, and malformed size fails closed.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_ship_gate_sizing as sg  # noqa: E402

_GOV = ROOT / "presets" / "us_short_ship_gate_sizing_governance_20260620.json"


class PermissionTests(unittest.TestCase):
    def test_hard_veto_is_minimal_only(self):
        self.assertEqual(sg.classify_live_permission(True, "live_normalized", True), "paper_or_minimal_only")

    def test_paper_and_not_evaluable_never_full_size(self):
        for ev in ("paper", "not_evaluable"):
            self.assertEqual(sg.classify_live_permission(False, ev, True), "paper_or_minimal_only", ev)

    def test_unknown_evidence_fails_closed(self):
        for ev in ("bogus", None, True, "", "Live_Normalized"):
            self.assertEqual(sg.classify_live_permission(False, ev, True), "paper_or_minimal_only", repr(ev))

    def test_live_normalized_graduation(self):
        self.assertEqual(sg.classify_live_permission(False, "live_normalized", True), "full_size_eligible")
        self.assertEqual(sg.classify_live_permission(False, "live_normalized", False), "not_full_size_eligible")

    def test_graduation_flag_strict_true(self):
        # a truthy-but-not-True graduation flag must NOT unlock full size
        for truthy in (1, "yes", [1]):
            self.assertEqual(sg.classify_live_permission(False, "live_normalized", truthy),
                             "not_full_size_eligible", repr(truthy))


class SizingTests(unittest.TestCase):
    def test_hard_veto_zeroes_position(self):
        out = sg.ship_gate_sizing(5000.0, 100, hard_veto=True, evidence_level="live_normalized",
                                  graduated_full_size=True)
        self.assertEqual(out["model_position_size_amount"], 0.0)
        self.assertEqual(out["model_position_size_shares"], 0)
        self.assertEqual(out["live_permission_status"], "paper_or_minimal_only")
        self.assertEqual(out["live_size_warning"], "hard_veto_zero_position")

    def test_maturity_is_reminder_not_cap(self):
        # paper evidence must NOT shrink the model size — only the permission/warning change
        out = sg.ship_gate_sizing(5000.0, 100, hard_veto=False, evidence_level="paper")
        self.assertEqual(out["model_position_size_shares"], 100)
        self.assertEqual(out["model_position_size_amount"], 5000.0)
        self.assertEqual(out["live_permission_status"], "paper_or_minimal_only")
        self.assertIsNotNone(out["live_size_warning"])

    def test_ungraduated_live_track_not_full_size_but_keeps_size(self):
        out = sg.ship_gate_sizing(5000.0, 100, evidence_level="live_normalized", graduated_full_size=False)
        self.assertEqual(out["live_permission_status"], "not_full_size_eligible")
        self.assertEqual(out["model_position_size_shares"], 100)   # not capped

    def test_full_size_eligible_has_no_warning(self):
        out = sg.ship_gate_sizing(5000.0, 100, evidence_level="live_normalized", graduated_full_size=True)
        self.assertEqual(out["live_permission_status"], "full_size_eligible")
        self.assertIsNone(out["live_size_warning"])

    def test_malformed_model_size_fails_closed(self):
        for amt, sh in ((float("nan"), 100), ("5000", 100), (-1.0, 100), (5000.0, 2.5), (5000.0, -1), (5000.0, True)):
            out = sg.ship_gate_sizing(amt, sh, evidence_level="live_normalized", graduated_full_size=True)
            self.assertEqual(out["model_position_size_shares"], 0, (amt, sh))
            self.assertEqual(out["model_position_size_amount"], 0.0, (amt, sh))
            self.assertEqual(out["live_permission_status"], "paper_or_minimal_only", (amt, sh))
            self.assertEqual(out["live_size_warning"], "malformed_model_size", (amt, sh))


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gov = json.loads(_GOV.read_text(encoding="utf-8"))

    def test_result_keys_are_the_frozen_sizing_fields(self):
        out = sg.ship_gate_sizing(100.0, 1, evidence_level="paper")
        self.assertEqual(set(out.keys()), set(sg.SIZING_FIELDS))

    def test_permission_vocab_matches_preset(self):
        self.assertEqual(sg.LIVE_PERMISSION_VOCAB, tuple(self.gov["live_permission_status_vocab"]))

    def test_safety_invariants_pinned_true(self):
        for flag in ("maturity_is_reminder_not_cap", "ungraduated_not_full_size_license",
                     "real_money_amount_manual", "hard_veto_zero_position"):
            self.assertIs(self.gov[flag], True, flag)


if __name__ == "__main__":
    unittest.main()
