from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import jsonschema

from engine.us_short_forward_policy_shadow_stage import _build_summary
from engine.us_short_forward_policy_statistical_plan import statistical_plan_sha256


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas" / "us_short_forward_policy_shadow_summary.schema.json").read_text(encoding="utf-8"))


def _decisions():
    base = {
        "out_of_window": False,
        "decision_date": "20260713",
        "price_basis_date": "20260710",
    }
    return {
        "balanced": {**base, "admitted": ["ALFA", "BETA"]},
        "theme_plus": {**base, "admitted": ["ALFA", "CATA"]},
        "theme_aggressive": {**base, "admitted": ["ALFA", "CATA"]},
        "theme_off": {**base, "admitted": ["BETA", "CATA"]},
        "catalyst_off": {**base, "admitted": ["ALFA", "BETA"]},
        "overextension_selection_off": {**base, "admitted": ["ALFA", "BETA"]},
    }


class ForwardPolicyShadowSummarySchemaTests(unittest.TestCase):
    def _summary(self):
        return _build_summary(
            decision_date="20260713",
            price_basis_date="20260710",
            source_context_sha256="a" * 64,
            common_selection_pool=["ALFA", "BETA", "CATA"],
            common_selection_pool_sha256="b" * 64,
            comparison_contract_sha256=statistical_plan_sha256(),
            decisions=_decisions(),
        )

    def test_valid_summary_matches_schema(self):
        self.assertEqual(list(jsonschema.Draft7Validator(SCHEMA).iter_errors(self._summary())), [])

    def test_schema_rejects_ticker_leak_and_policy_set_drift(self):
        leaked = self._summary()
        leaked["ticker"] = "ALFA"
        self.assertTrue(list(jsonschema.Draft7Validator(SCHEMA).iter_errors(leaked)))
        drift = copy.deepcopy(self._summary())
        drift["selection_policies"] = drift["selection_policies"][:-1]
        self.assertTrue(list(jsonschema.Draft7Validator(SCHEMA).iter_errors(drift)))

        bad_pool = copy.deepcopy(self._summary())
        bad_pool["common_selection_pool_count"] = 0
        self.assertTrue(list(jsonschema.Draft7Validator(SCHEMA).iter_errors(bad_pool)))


if __name__ == "__main__":
    unittest.main()
