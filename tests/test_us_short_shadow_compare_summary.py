# -*- coding: utf-8 -*-
"""Tests for US-short §12.2 shadow comparison TRACKED de-identified summary (engine/us_short_shadow_compare_summary.py).

Covers: build from a validated comparison → de-identified counts ONLY (no tickers; divergence sizes match the
comparison set-diffs; selected_count == min(top_n,pool_size); #24 theme_off divergence non-degenerate); refuses an
un-validated comparison; the schema de-identification gate (a smuggled ticker / extra key refused via
additionalProperties:false); the cross-field consistency gate (overlap+balanced_only == selected ==
overlap+shadow_extra; bad as_of); and write roundtrip + refuses-bad-before-write. Pure-ish; no provider/live; no
A-share crossing. (Imports jsonschema for the de-id gate — like the schema suite, this is blocked on a runtime
without jsonschema.)
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_shadow_compare as sc  # noqa: E402
import engine.us_short_shadow_compare_summary as summ  # noqa: E402

POOL = [
    {"ticker": "AAA", "blocks": {"momentum": 90, "theme": 10, "catalyst": 50}},
    {"ticker": "BBB", "blocks": {"momentum": 10, "theme": 90, "catalyst": 50}},
    {"ticker": "CCC", "blocks": {"momentum": 50, "theme": 50, "catalyst": 50}},
    {"ticker": "DDD", "blocks": {"momentum": 20, "theme": 20, "catalyst": 90}},
    {"ticker": "EEE", "blocks": {"momentum": 60, "theme": 60, "catalyst": 20}},
]


def _summary(as_of="20260112", top_n=3):
    return summ.build_shadow_compare_summary(sc.build_shadow_comparison(POOL, top_n=top_n), as_of=as_of)


class BuildDeidentified(unittest.TestCase):
    def test_deidentified_keys_no_tickers(self):
        s = _summary()
        self.assertEqual(s["schema_name"], "us_short_shadow_compare_summary")
        self.assertEqual(s["track"], "comparison_non_production")
        self.assertEqual(s["primary_profile"], "balanced")
        self.assertEqual(s["selected_count"], 3)
        self.assertEqual(set(s["divergence"]), {"theme_plus", "theme_aggressive", "theme_off"})
        # divergence entries are integer counts only — no ticker can hide in the de-identified summary
        for d in s["divergence"].values():
            self.assertEqual(set(d), {"balanced_only_count", "shadow_extra_count", "overlap_count"})
            for v in d.values():
                self.assertIsInstance(v, int)
        # the whole summary JSON-serialized contains no pool ticker
        blob = json.dumps(s)
        for t in ("AAA", "BBB", "CCC", "DDD", "EEE"):
            self.assertNotIn(t, blob)

    def test_divergence_counts_match_comparison(self):
        comp = sc.build_shadow_comparison(POOL, top_n=3)
        s = summ.build_shadow_compare_summary(comp, as_of="20260112")
        for name, vs in comp["vs_balanced"].items():
            self.assertEqual(s["divergence"][name]["balanced_only_count"], len(vs["balanced_only"]))
            self.assertEqual(s["divergence"][name]["shadow_extra_count"], len(vs["shadow_extra"]))
            self.assertEqual(s["divergence"][name]["overlap_count"], vs["overlap_count"])

    def test_theme_off_divergence_nondegenerate(self):
        # #24: theme_off (theme weight 0) selection diverges from balanced — a real, trackable, no-ticker count
        s = _summary()
        d = s["divergence"]["theme_off"]
        self.assertEqual((d["balanced_only_count"], d["shadow_extra_count"], d["overlap_count"]), (1, 1, 2))

    def test_boundary_carried(self):
        s = _summary()
        self.assertEqual(s["boundary"], {"production": False, "is_buy_advice": False,
                                         "shadow_counts_ship_gate": False, "changes_primary_selection": False})

    def test_empty_pool_summary(self):
        s = summ.build_shadow_compare_summary(sc.build_shadow_comparison([], top_n=3), as_of="20260112")
        self.assertEqual(s["selected_count"], 0)
        for d in s["divergence"].values():
            self.assertEqual((d["balanced_only_count"], d["shadow_extra_count"], d["overlap_count"]), (0, 0, 0))


class RefusesBadInput(unittest.TestCase):
    def test_refuses_unvalidated_comparison(self):
        comp = sc.build_shadow_comparison(POOL, top_n=3)
        comp["boundary"]["shadow_counts_ship_gate"] = True  # breaks the §12.2 contract
        with self.assertRaises(sc.ShadowCompareError):
            summ.build_shadow_compare_summary(comp, as_of="20260112")

    def test_bad_as_of_refused(self):
        comp = sc.build_shadow_comparison(POOL, top_n=3)
        with self.assertRaises(summ.ShadowCompareSummaryError):
            summ.build_shadow_compare_summary(comp, as_of="20260231")  # not a real date


class DeidGateAndConsistency(unittest.TestCase):
    def setUp(self):
        self.good = _summary()

    def _assert_rejects(self, mutate):
        bad = copy.deepcopy(self.good)
        mutate(bad)
        with self.assertRaises(summ.ShadowCompareSummaryError):
            summ._assert_summary(bad)

    def test_good_passes(self):
        summ._assert_summary(self.good)

    def test_smuggled_ticker_extra_key_refused(self):
        self._assert_rejects(lambda b: b.__setitem__("tickers", ["AAPL"]))  # additionalProperties:false

    def test_divergence_entry_extra_key_refused(self):
        self._assert_rejects(lambda b: b["divergence"]["theme_off"].__setitem__("leaked", "AAPL"))

    def test_inconsistent_counts_refused(self):
        self._assert_rejects(lambda b: b["divergence"]["theme_off"].__setitem__("overlap_count", 99))

    def test_selected_count_mismatch_refused(self):
        self._assert_rejects(lambda b: b.__setitem__("selected_count", 99))

    def test_boundary_tampered_refused(self):
        self._assert_rejects(lambda b: b["boundary"].__setitem__("shadow_counts_ship_gate", True))

    def test_missing_shadow_profile_refused(self):
        self._assert_rejects(lambda b: b["divergence"].pop("theme_off"))


class WriteRoundtrip(unittest.TestCase):
    def test_roundtrip(self):
        s = _summary()
        with tempfile.TemporaryDirectory() as d:
            p = summ.write_shadow_compare_summary(s, Path(d) / "summary.json")
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), s)

    def test_refuses_bad_before_write(self):
        bad = copy.deepcopy(_summary())
        bad["selected_count"] = 99  # inconsistent
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "summary.json"
            with self.assertRaises(summ.ShadowCompareSummaryError):
                summ.write_shadow_compare_summary(bad, p)
            self.assertFalse(p.exists())


if __name__ == "__main__":
    unittest.main()
