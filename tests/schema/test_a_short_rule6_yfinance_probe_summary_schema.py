from __future__ import annotations

import unittest
from pathlib import Path

from runners.a_short_rule6_yfinance_probe import run_probe
from tests.test_a_short_rule6_yfinance_probe import _FakeYfinance


class Rule6YfinanceProbeSummarySchemaTests(unittest.TestCase):
    def test_schema_accepts_only_the_nonwired_probe_summary(self):
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        import json
        import tempfile

        schema = json.loads(Path("schemas/a_short_rule6_yfinance_probe_summary.schema.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_probe(_FakeYfinance, Path(tmp) / "provider_samples/a_short_rule6_yfinance_probe_20260714")
        self.assertEqual(list(Draft7Validator(schema).iter_errors(summary)), [])
        summary["decision"]["downstream_rule6_wiring_authorized"] = True
        self.assertNotEqual(list(Draft7Validator(schema).iter_errors(summary)), [])


if __name__ == "__main__":
    unittest.main()
