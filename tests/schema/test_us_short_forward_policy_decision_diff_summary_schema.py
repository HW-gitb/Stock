from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_forward_policy_decision_diff import BOUNDARY, UNAVAILABLE  # noqa: E402
from engine.us_short_forward_policy_heads import SELECTION_POLICY_IDS  # noqa: E402


SCHEMA = json.loads(
    (ROOT / "schemas" / "us_short_forward_policy_decision_diff_summary.schema.json").read_text(encoding="utf-8")
)
POLICIES = tuple(SELECTION_POLICY_IDS)


def _counts():
    return {
        "balanced_only_count": 1,
        "policy_only_count": 1,
        "overlap_count": 1,
        "top15_membership_changed_count": 2,
        "rank_changed_count": 0,
        "selection_bucket_changed_count": 0,
        "action_changed_count": 0,
        "size_changed_count": 0,
    }


def _summary():
    return {
        "schema_name": "us_short_forward_policy_decision_diff_summary",
        "schema_version": "1.0.0",
        "decision_date": "20260713",
        "price_basis_date": "20260710",
        "source_context_sha256": "a" * 64,
        "selection_policies": list(POLICIES),
        "primary_policy": "balanced",
        "diff_counts_vs_balanced": {policy: _counts() for policy in POLICIES[1:]},
        "unavailable_surfaces": dict(UNAVAILABLE),
        "boundary": dict(BOUNDARY),
    }


class ForwardPolicyDecisionDiffSummarySchemaTests(unittest.TestCase):
    def test_summary_schema_accepts_counts_only_contract(self):
        jsonschema.validate(_summary(), SCHEMA)

    def test_schema_rejects_ticker_or_action_size_drift(self):
        for mutate in (
            lambda value: value.__setitem__("ticker_diffs", ["AAA"]),
            lambda value: value["diff_counts_vs_balanced"]["theme_plus"].__setitem__("tickers", ["AAA"]),
            lambda value: value["diff_counts_vs_balanced"]["theme_plus"].__setitem__("action_changed_count", 1),
            lambda value: value["unavailable_surfaces"].__setitem__("action_change", "changed"),
            lambda value: value["boundary"].__setitem__("shadow_counts_ship_gate", True),
        ):
            bad = _summary()
            mutate(bad)
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(bad, SCHEMA)

    def test_schema_const_pins_policy_namespace(self):
        bad = copy.deepcopy(_summary())
        bad["selection_policies"].append("overextension_execution_off")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, SCHEMA)


if __name__ == "__main__":
    unittest.main()
