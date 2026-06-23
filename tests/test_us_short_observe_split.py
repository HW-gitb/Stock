# -*- coding: utf-8 -*-
"""Tests for US-short §11.2 honest-banner ① observe split (engine/us_short_observe_split.py).

Covers: closed-world observe_reason_type (unknown / non-string refused); aggregation correctness (per-reason
counts over ALL frozen reasons with zeros explicit, total, sizing_artifact_count = cash_or_account_missing);
the fail-closed validate gate (per_reason key set, non-negative int counts, total==sum, sizing==sum-of-artifact
reasons); frozen single-source; and the banner render (non-blank, honest sizing-artifact framing, de-identified).
Pure/offline; no provider/live; no A-share crossing.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_observe_split as obs  # noqa: E402

REASONS = json.loads((ROOT / "presets" / "us_short_action_table_contract_20260620.json").read_text(encoding="utf-8"))["design_locked_enums"]["observe_reason_type"]
CASH = "cash_or_account_missing"
SIGNAL = "signal_not_ready"


class Aggregate(unittest.TestCase):
    def test_counts_total_and_all_reasons_present(self):
        s = obs.aggregate_observe_split([SIGNAL, SIGNAL, CASH])
        self.assertEqual(s["total"], 3)
        self.assertEqual(set(s["per_reason"]), set(REASONS))  # all frozen reasons present (zeros explicit)
        self.assertEqual(s["per_reason"][SIGNAL], 2)
        self.assertEqual(s["per_reason"][CASH], 1)
        self.assertEqual(sum(s["per_reason"].values()), 3)

    def test_sizing_artifact_count_is_cash_only(self):
        s = obs.aggregate_observe_split([CASH, CASH, SIGNAL, "price_not_executable"])
        self.assertEqual(s["sizing_artifact_count"], 2)  # only cash_or_account_missing is the fake/sizing artifact

    def test_empty_week_is_zero(self):  # positive control
        s = obs.aggregate_observe_split([])
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["sizing_artifact_count"], 0)
        self.assertEqual(set(s["per_reason"]), set(REASONS))
        self.assertTrue(all(v == 0 for v in s["per_reason"].values()))

    def test_every_frozen_reason_accepted(self):
        s = obs.aggregate_observe_split(list(REASONS))
        self.assertEqual(s["total"], len(REASONS))
        self.assertTrue(all(s["per_reason"][r] == 1 for r in REASONS))


class ClosedWorldAndMalformed(unittest.TestCase):
    def test_unknown_reason_refused(self):
        with self.assertRaises(obs.ObserveSplitError):
            obs.aggregate_observe_split([SIGNAL, "made_up_reason"])

    def test_non_string_reason_refused(self):
        for bad in (None, 5, True, ["x"]):
            with self.assertRaises(obs.ObserveSplitError, msg=repr(bad)):
                obs.aggregate_observe_split([bad])

    def test_non_list_input_refused(self):
        for bad in (None, "x", 5, {}):
            with self.assertRaises(obs.ObserveSplitError, msg=repr(bad)):
                obs.aggregate_observe_split(bad)


class ValidateFailsClosed(unittest.TestCase):
    def _good(self, **over):
        s = obs.aggregate_observe_split([CASH, SIGNAL])
        s.update(over)
        return s

    def test_good_passes(self):
        obs.validate_observe_split(self._good())

    def test_per_reason_key_mismatch_refused(self):
        s = self._good(); del s["per_reason"][SIGNAL]
        with self.assertRaises(obs.ObserveSplitError):
            obs.validate_observe_split(s)

    def test_total_mismatch_refused(self):
        with self.assertRaises(obs.ObserveSplitError):
            obs.validate_observe_split(self._good(total=99))

    def test_negative_or_bool_count_refused(self):
        s = self._good(); s["per_reason"][SIGNAL] = -1
        with self.assertRaises(obs.ObserveSplitError):
            obs.validate_observe_split(s)
        s2 = self._good(); s2["per_reason"][SIGNAL] = True
        with self.assertRaises(obs.ObserveSplitError):
            obs.validate_observe_split(s2)

    def test_sizing_count_mismatch_refused(self):  # can't overstate the fake count vs the breakdown
        with self.assertRaises(obs.ObserveSplitError):
            obs.validate_observe_split(self._good(sizing_artifact_count=5))

    def test_non_dict_refused(self):
        for bad in (None, "x", 5, []):
            with self.assertRaises(obs.ObserveSplitError, msg=repr(bad)):
                obs.validate_observe_split(bad)


class FrozenSingleSource(unittest.TestCase):
    def test_reasons_match_frozen_contract(self):
        self.assertEqual(obs._reasons(), REASONS)


class Render(unittest.TestCase):
    def test_non_blank_with_total_and_sizing_framing(self):
        out = obs.render_observe_split(obs.aggregate_observe_split([CASH, SIGNAL, SIGNAL]))
        self.assertTrue(out.strip())
        self.assertIn("本周 3 只观察", out)
        self.assertIn("sizing 假象", out)
        self.assertIn("系统并非不看好", out)
        for r in REASONS:
            self.assertIn(r, out)

    def test_render_refuses_bad_split(self):
        s = obs.aggregate_observe_split([CASH]); s["total"] = 99
        with self.assertRaises(obs.ObserveSplitError):
            obs.render_observe_split(s)


if __name__ == "__main__":
    unittest.main()
