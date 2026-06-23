# -*- coding: utf-8 -*-
"""Tests for US-short §11.4 hot_excluded detector (engine/us_short_hot_excluded.py).

Covers: detection (heat >= threshold AND safety/liquidity/data gate); never-rescue-hard-veto (a high-heat name
dropped at a non-audit gate is never hot); audit-only (the input rows are never mutated; never changes
admission); the privacy-split summary bridge (public count = non-holding names, holdings = private detail);
and the whole malformed-input class (row shape, non-finite / negative heat, bad gate, non-bool is_holding, bad
threshold). Pure/offline; no provider/live; no A-share crossing.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_hot_excluded as he  # noqa: E402


def _row(ticker="AAPL", heat=0.9, gate="safety", is_holding=False):
    return {"ticker": ticker, "theme_heat_score": heat, "dropped_at_gate": gate, "is_holding": is_holding}


class Detect(unittest.TestCase):
    def test_high_heat_eligible_gate_is_hot(self):
        for gate in ("safety", "liquidity", "data"):
            hot = he.detect_hot_excluded([_row(gate=gate, heat=0.8)], heat_threshold=0.5)
            self.assertEqual(len(hot), 1, gate)

    def test_threshold_is_inclusive(self):
        self.assertEqual(len(he.detect_hot_excluded([_row(heat=0.5)], heat_threshold=0.5)), 1)
        self.assertEqual(len(he.detect_hot_excluded([_row(heat=0.49)], heat_threshold=0.5)), 0)

    def test_low_heat_not_hot(self):
        self.assertEqual(he.detect_hot_excluded([_row(heat=0.1)], heat_threshold=0.5), [])

    def test_never_rescue_non_audit_gate(self):  # high heat dropped at a hard-veto / unknown gate is NOT hot
        for gate in ("hard_veto", "fundamental", "sec_offering", "made_up_gate"):
            self.assertEqual(he.detect_hot_excluded([_row(gate=gate, heat=0.99)], heat_threshold=0.5), [], gate)

    def test_mixed_filters_correctly(self):
        rows = [_row("A", 0.9, "safety"), _row("B", 0.9, "hard_veto"), _row("C", 0.2, "data"), _row("D", 0.7, "liquidity")]
        hot = he.detect_hot_excluded(rows, heat_threshold=0.5)
        self.assertEqual({r["ticker"] for r in hot}, {"A", "D"})

    def test_empty_is_empty(self):  # positive control
        self.assertEqual(he.detect_hot_excluded([], heat_threshold=0.5), [])


class AuditOnly(unittest.TestCase):
    def test_input_rows_not_mutated_and_outputs_are_copies(self):
        rows = [_row("A", 0.9, "safety")]
        original = dict(rows[0])
        hot = he.detect_hot_excluded(rows, heat_threshold=0.5)
        hot[0]["ticker"] = "MUTATED"
        self.assertEqual(rows[0], original)         # caller's row untouched
        self.assertIsNot(hot[0], rows[0])           # returned row is a distinct copy
        self.assertEqual(len(rows), 1)              # admission set unchanged (never adds/removes)


class SummaryPrivacySplit(unittest.TestCase):
    def test_public_count_excludes_holdings_private_carries_them(self):
        rows = [_row("A", 0.9, "safety", is_holding=False),
                _row("B", 0.9, "liquidity", is_holding=True),
                _row("C", 0.9, "data", is_holding=False)]
        s = he.hot_excluded_summary(rows, heat_threshold=0.5)
        self.assertEqual(s["public_heat_count"], 2)          # only non-holding names in the tracked count
        self.assertEqual([h["ticker"] for h in s["holdings"]], ["B"])
        self.assertEqual(s["holdings"][0]["reason"], "liquidity")

    def test_bridge_shape_matches_exclusion_summary_input(self):
        s = he.hot_excluded_summary([_row("A", 0.9, "safety", is_holding=True)], heat_threshold=0.5)
        self.assertEqual(set(s), {"public_heat_count", "holdings"})
        self.assertTrue(all(set(h) == {"ticker", "reason"} for h in s["holdings"]))

    def test_empty_summary(self):  # positive control
        self.assertEqual(he.hot_excluded_summary([], heat_threshold=0.5), {"public_heat_count": 0, "holdings": []})


class SummaryBridgeCannotBypassDetector(unittest.TestCase):
    """R-USSHORT-BATCH3-HOT-EXCLUDED-SUMMARY-BYPASS-GAP: the official bridge runs the detector internally, so raw
    rows with a non-audit gate (hard_veto / fundamental / unknown) or below-threshold heat are filtered out and
    never surfaced as official hot_excluded — for BOTH the public count and the private holding detail."""

    def test_non_audit_gate_rows_filtered_from_public_count(self):
        rows = [_row("A", 0.9, "safety"), _row("B", 0.9, "hard_veto"), _row("C", 0.9, "fundamental"),
                _row("D", 0.9, "made_up_gate"), _row("E", 0.9, "sec_offering")]
        s = he.hot_excluded_summary(rows, heat_threshold=0.5)
        self.assertEqual(s["public_heat_count"], 1)  # only the safety row survives
        self.assertEqual(s["holdings"], [])

    def test_non_audit_gate_holding_filtered_from_private_detail(self):
        rows = [_row("MSFT", 0.9, "hard_veto", is_holding=True), _row("AAPL", 0.9, "safety", is_holding=True)]
        s = he.hot_excluded_summary(rows, heat_threshold=0.5)
        self.assertEqual([h["ticker"] for h in s["holdings"]], ["AAPL"])  # hard_veto holding never surfaced

    def test_low_heat_rows_filtered(self):
        rows = [_row("A", 0.01, "safety"), _row("B", 0.01, "data", is_holding=True), _row("C", 0.9, "safety")]
        s = he.hot_excluded_summary(rows, heat_threshold=0.5)
        self.assertEqual(s["public_heat_count"], 1)  # only C (high heat)
        self.assertEqual(s["holdings"], [])          # low-heat holding filtered too

    def test_matches_detect_then_aggregate(self):  # the bridge == manual detect + aggregate (single source)
        rows = [_row("A", 0.9, "safety"), _row("B", 0.1, "data"), _row("C", 0.9, "hard_veto"),
                _row("D", 0.9, "liquidity", is_holding=True)]
        hot = he.detect_hot_excluded(rows, heat_threshold=0.5)
        s = he.hot_excluded_summary(rows, heat_threshold=0.5)
        self.assertEqual(s["public_heat_count"], sum(1 for r in hot if not r["is_holding"]))
        self.assertEqual(len(s["holdings"]), sum(1 for r in hot if r["is_holding"]))

    def test_summary_bad_threshold_refused(self):
        for bad in (float("nan"), -0.1, "0.5", True):
            with self.assertRaises(he.HotExcludedError, msg=repr(bad)):
                he.hot_excluded_summary([_row()], heat_threshold=bad)


class MalformedFailsClosed(unittest.TestCase):
    def test_non_list_refused(self):
        for bad in (None, "x", 5, {}):
            with self.assertRaises(he.HotExcludedError, msg=repr(bad)):
                he.detect_hot_excluded(bad, heat_threshold=0.5)

    def test_bad_threshold_refused(self):
        for bad in (None, "0.5", True, -0.1, float("nan"), float("inf")):
            with self.assertRaises(he.HotExcludedError, msg=repr(bad)):
                he.detect_hot_excluded([_row()], heat_threshold=bad)

    def test_bad_row_refused(self):
        bad_rows = [
            "notadict", 5, None,
            _row(ticker=""), _row(ticker="   "), _row(ticker=None),
            _row(heat=None), _row(heat="0.9"), _row(heat=True), _row(heat=-0.1),
            _row(heat=float("nan")), _row(heat=float("inf")),
            _row(gate=""), _row(gate=None),
            _row(is_holding="yes"), _row(is_holding=1), _row(is_holding=None),
        ]
        for bad in bad_rows:
            with self.assertRaises(he.HotExcludedError, msg=repr(bad)):
                he.detect_hot_excluded([bad], heat_threshold=0.5)

    def test_summary_validates_rows(self):
        for bad in ("notalist", [_row(ticker="")], [_row(heat=float("inf"))], [_row(is_holding="x")]):
            with self.assertRaises(he.HotExcludedError, msg=repr(bad)):
                he.hot_excluded_summary(bad, heat_threshold=0.5)


class GatesSourcedFromCriteria(unittest.TestCase):
    def test_audit_eligible_gates(self):
        self.assertEqual(he.AUDIT_ELIGIBLE_GATES, frozenset({"safety", "liquidity", "data"}))


if __name__ == "__main__":
    unittest.main()
