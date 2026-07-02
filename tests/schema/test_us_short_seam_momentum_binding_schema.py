# -*- coding: utf-8 -*-
"""Adversarial schema tests for the US-short Cut 6-a momentum scoring-seam binding.

The schema must FREEZE the load-bearing seam policies (accepted producer key set, block value domain,
numeric policy, sub-feature universe, coverage row shape, coverage partition policy, disposition
vocabulary, projection output shape, producer ref, authorization boundary), not just document them. Each
mutant flips exactly one const and asserts a schema error; the genuine binding validates with zero errors.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_seam_momentum as sm  # noqa: E402

SCHEMA_PATH = ROOT / "schemas" / "us_short_seam_momentum_binding.schema.json"


class SeamMomentumBindingSchemaTest(unittest.TestCase):
    def setUp(self):
        from jsonschema import Draft7Validator
        self._validator = Draft7Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
        self._binding = sm.load_binding()

    def _errors(self, binding):
        return list(self._validator.iter_errors(binding))

    def _mutated(self, path, value):
        b = copy.deepcopy(self._binding)
        node = b
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        return b

    def test_real_binding_validates(self):
        self.assertEqual(self._errors(self._binding), [])

    def test_binding_name_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["binding_name"], "other")))

    def test_producer_ref_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["producer_ref"], "engine/other.py::fn")))

    def test_block_value_domain_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["block_value_domain"], [0.0, 1.0])))

    def test_numeric_policy_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["numeric_value_policy"], "isinstance_number")))

    def test_accepted_keys_drift_rejected(self):
        # dropping coverage_matrix (the ignored-then-required key) must fail
        self.assertTrue(self._errors(self._mutated(
            ["accepted_producer_result_keys"],
            ["momentum_block", "insufficient_history", "insufficient_coverage", "sub_feature_coverage", "min_coverage"])))

    def test_sub_feature_universe_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["sub_feature_universe"], ["ret_1m", "ret_3m", "ret_5d", "ret_10d", "rel_spy_1m", "rel_qqq_1m"])))

    def test_coverage_row_shape_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["coverage_row_shape"], ["n_present", "scored", "extra"])))

    def test_disposition_vocab_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["disposition_vocabulary"], ["scored", "insufficient_history", "insufficient_coverage"])))

    def test_partition_scored_relation_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["coverage_partition_policy", "scored_relation"], "always true")))

    def test_partition_history_relation_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["coverage_partition_policy", "history_relation"], "n_present > 0")))

    def test_partition_duplicate_policy_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["coverage_partition_policy", "duplicate_policy"], "silently collapse duplicates")))

    def test_identity_policy_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["identity_policy"], "some other identity authority")))

    def test_neutral_fill_note_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["neutral_fill_note"], "some other omission rule")))

    def test_neutral_fill_note_required(self):
        b = copy.deepcopy(self._binding)
        del b["neutral_fill_note"]
        self.assertTrue(self._errors(b))

    def test_partition_margin_conservation_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["coverage_partition_policy", "margin_conservation"], "row and column totals need not match")))

    def test_partition_margin_realizability_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["coverage_partition_policy", "margin_realizability"], "any independent margins are fine")))

    def test_projection_output_keys_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["projection_output_keys"], ["momentum_by_ticker", "neutral_fill_tickers", "coverage"])))

    def test_authorization_flip_rejected(self):
        for flag in ("live_fetch", "network", "raw_capture", "runner_wired", "datahub", "production", "ship_gate"):
            self.assertTrue(self._errors(self._mutated(["authorization_boundary", flag], True)),
                            f"authorization_boundary.{flag}=true must be rejected")

    def test_extra_top_key_rejected(self):
        b = copy.deepcopy(self._binding)
        b["surprise"] = 1
        self.assertTrue(self._errors(b))

    def test_partition_extra_key_rejected(self):
        b = copy.deepcopy(self._binding)
        b["coverage_partition_policy"]["surprise"] = "x"
        self.assertTrue(self._errors(b))


if __name__ == "__main__":
    unittest.main()
