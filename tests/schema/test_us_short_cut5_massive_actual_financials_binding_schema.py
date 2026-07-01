# -*- coding: utf-8 -*-
"""Adversarial schema tests for the US-short Cut 5-b Massive actual-financials binding.

Finding D: the schema must FREEZE the load-bearing PIT / duplicate / checked-empty / lineage / authorization
POLICIES, not just the vocabularies. Each mutant flips exactly one const and asserts a schema error; the genuine
binding validates with zero errors.
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

from engine import us_short_massive_financials as mf  # noqa: E402

SCHEMA_PATH = ROOT / "schemas" / "us_short_cut5_massive_actual_financials_binding.schema.json"


class MassiveFinancialsBindingSchemaTest(unittest.TestCase):
    def setUp(self):
        from jsonschema import Draft7Validator
        self._validator = Draft7Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
        self._binding = mf.load_binding()

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

    def test_pit_cutoff_operator_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["pit_clock_contract", "observed_at_cutoff_operator"], "at_or_before")))

    def test_pit_cutoff_reference_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["pit_clock_contract", "observed_at_cutoff_reference"], "period_end")))

    def test_chronology_order_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["pit_clock_contract", "chronology_order"], ["observed_at", "acceptance_datetime", "source_as_of", "as_of"])))

    def test_chronology_relation_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["pit_clock_contract", "chronology_relation"], "any_order")))

    def test_duplicate_identity_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["duplicate_policy", "source_row_identity"], ["fiscal_period"])))

    def test_duplicate_on_duplicate_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["duplicate_policy", "on_duplicate"], "keep_all")))

    def test_checked_empty_disposition_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["checked_empty_disposition"], "silent_drop")))

    def test_allowed_timeframes_drift_rejected(self):
        # re-admitting ttm (the null-filing-date rollup) must fail — the PIT anchor would vanish
        self.assertTrue(self._errors(self._mutated(["allowed_timeframes"], ["quarterly", "annual", "ttm"])))

    def test_lineage_format_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(["lineage_ref_format", "structure"], "free_text")))

    def test_authorization_flip_rejected(self):
        for flag in ("live_fetch", "network", "raw_capture", "runner_wired", "datahub", "production", "ship_gate"):
            self.assertTrue(self._errors(self._mutated(["authorization_boundary", flag], True)),
                            f"authorization_boundary.{flag}=true must be rejected")

    def test_provenance_fields_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["provenance_fields"], ["provider_id", "endpoint_or_filing_type", "source_as_of"])))

    def test_bound_line_items_drift_rejected(self):
        self.assertTrue(self._errors(self._mutated(
            ["bound_line_items", "income_statement"], ["revenues"])))

    def test_extra_top_key_rejected(self):
        b = copy.deepcopy(self._binding)
        b["surprise"] = 1
        self.assertTrue(self._errors(b))


if __name__ == "__main__":
    unittest.main()
