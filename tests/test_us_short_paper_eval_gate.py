# -*- coding: utf-8 -*-
"""Tests for US-short §12.1 / §18.1 #29 corporate-action evaluability gate (engine/us_short_paper_eval_gate.py).

Covers: evaluable (paper / reporting / shadow use) ONLY when all three confirmations are literally True;
fail-closed not_evaluable on any missing / False / None / truthy-non-bool confirmation (only literal True
confirms); the unconfirmed list + the local blocks_paper_performance_due_to_corporate_action cause; the FIXED
full_size_ship_gate_allowed=False ship-gate invariant (paper is never full-size ship-gate eligible, §12 / §27);
and malformed fail-closed (non-dict, unknown confirmation key). Pure/offline; no provider/live; no A-share crossing.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_paper_eval_gate as g  # noqa: E402

ALL = {"adjustment_mode_confirmed": True, "split_dividend_handled": True, "ex_date_price_consistent": True}


class Evaluable(unittest.TestCase):
    def test_all_confirmed_is_evaluable_but_not_ship_gate(self):
        r = g.paper_performance_evaluability(dict(ALL))
        self.assertEqual(r["status"], "evaluable")
        self.assertEqual(r["unconfirmed"], [])
        self.assertFalse(r["blocks_paper_performance_due_to_corporate_action"])
        # evaluable for paper / reporting / shadow use — but NEVER full-size ship-gate eligible (§12 / §27)
        self.assertFalse(r["full_size_ship_gate_allowed"])
        self.assertEqual(r["ship_gate_evidence_level"], "paper_not_live_normalized")


class FailClosed(unittest.TestCase):
    def test_any_false_blocks(self):
        for k in g._CONFIRMATIONS:
            ctx = dict(ALL); ctx[k] = False
            r = g.paper_performance_evaluability(ctx)
            self.assertEqual(r["status"], "not_evaluable", k)
            self.assertEqual(r["unconfirmed"], [k])
            self.assertTrue(r["blocks_paper_performance_due_to_corporate_action"])

    def test_missing_key_is_unconfirmed(self):
        ctx = {"adjustment_mode_confirmed": True, "split_dividend_handled": True}  # ex_date omitted
        r = g.paper_performance_evaluability(ctx)
        self.assertEqual(r["status"], "not_evaluable")
        self.assertEqual(r["unconfirmed"], ["ex_date_price_consistent"])

    def test_empty_context_all_unconfirmed(self):
        r = g.paper_performance_evaluability({})
        self.assertEqual(r["status"], "not_evaluable")
        self.assertEqual(set(r["unconfirmed"]), set(g._CONFIRMATIONS))

    def test_truthy_non_bool_does_not_confirm(self):  # only literal True confirms (no sloppy truthy unlock)
        for truthy in (1, "yes", "true", [1], 1.0):
            ctx = dict(ALL); ctx["adjustment_mode_confirmed"] = truthy
            r = g.paper_performance_evaluability(ctx)
            self.assertEqual(r["status"], "not_evaluable", repr(truthy))
            self.assertIn("adjustment_mode_confirmed", r["unconfirmed"])

    def test_none_does_not_confirm(self):
        ctx = dict(ALL); ctx["split_dividend_handled"] = None
        self.assertEqual(g.paper_performance_evaluability(ctx)["status"], "not_evaluable")


class MalformedFailsClosed(unittest.TestCase):
    def test_non_dict_refused(self):
        for bad in (None, "x", 5, []):
            with self.assertRaises(g.PaperEvalGateError, msg=repr(bad)):
                g.paper_performance_evaluability(bad)

    def test_unknown_key_refused(self):  # a typo'd confirmation key must fail closed, not be silently ignored
        ctx = dict(ALL); ctx["adjustment_mode_confiremd"] = True  # typo
        with self.assertRaises(g.PaperEvalGateError):
            g.paper_performance_evaluability(ctx)


class ShipGateNeverAllowed(unittest.TestCase):
    """R-USSHORT-BATCH3-PAPER-EVAL-GATE-SHIP-GATE-PERMISSION-GAP: corporate-action evaluability NEVER implies
    full-size ship-gate eligibility — paper is design-iteration evidence only (§12 / §27); only live_normalized
    graduates."""

    def test_ship_gate_disallowed_for_all_inputs(self):  # confirmed OR not, full-size ship-gate stays disallowed
        for ctx in (dict(ALL), {}, {"adjustment_mode_confirmed": True},
                    {"adjustment_mode_confirmed": True, "split_dividend_handled": False, "ex_date_price_consistent": True}):
            r = g.paper_performance_evaluability(ctx)
            self.assertFalse(r["full_size_ship_gate_allowed"], ctx)
            self.assertEqual(r["ship_gate_evidence_level"], "paper_not_live_normalized")

    def test_no_ship_gate_named_field_is_true_even_when_evaluable(self):  # would fail if all-confirmed exposed a ship-gate=True
        r = g.paper_performance_evaluability(dict(ALL))
        self.assertNotIn(True, [v for k, v in r.items() if "ship_gate" in k])


if __name__ == "__main__":
    unittest.main()
