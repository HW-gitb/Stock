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

from engine import us_short_forward_policy_statistical_evaluation as evaluation  # noqa: E402


SCHEMA = json.loads(
    (ROOT / "schemas" / "us_short_forward_policy_statistical_evaluation_summary.schema.json").read_text(encoding="utf-8")
)


class ForwardPolicyStatisticalEvaluationSummarySchemaTests(unittest.TestCase):
    def test_accepts_deidentified_zero_week_summary(self):
        summary = evaluation.evaluate_forward_policy_statistical_evaluation([], as_of="20260712")
        jsonschema.validate(summary, SCHEMA)

    def test_rejects_ticker_or_boundary_leak(self):
        for mutate in (
            lambda value: value.__setitem__("tickers", ["AAPL"]),
            lambda value: value["policy_verdicts"]["theme_plus"].__setitem__("ticker", "AAPL"),
            lambda value: value["boundary"].__setitem__("shadow_counts_ship_gate", True),
        ):
            bad = evaluation.evaluate_forward_policy_statistical_evaluation([], as_of="20260712")
            mutate(bad)
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(bad, SCHEMA)

    def test_const_pins_the_immediate_selection_namespace(self):
        bad = evaluation.evaluate_forward_policy_statistical_evaluation([], as_of="20260712")
        bad["selection_policies"].append("overextension_execution_off")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, SCHEMA)


if __name__ == "__main__":
    unittest.main()
