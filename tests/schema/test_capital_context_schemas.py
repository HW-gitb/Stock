from __future__ import annotations

import json
import unittest
from pathlib import Path


PORTFOLIO_SCHEMA_PATH = Path("schemas/portfolio_allocation.schema.json")
CASH_STATE_SCHEMA_PATH = Path("schemas/cash_buffer_state.schema.json")
PORTFOLIO_FIXTURE_PATH = Path("tests/fixtures/portfolio_allocation_minimal.json")
CASH_STATE_FIXTURE_PATH = Path("tests/fixtures/cash_buffer_state_minimal.json")


class CapitalContextSchemaTest(unittest.TestCase):
    def validator_for(self, schema_path: Path):
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        return Draft7Validator(schema), schema

    def test_portfolio_allocation_schema_and_fixture_validate(self) -> None:
        validator, schema = self.validator_for(PORTFOLIO_SCHEMA_PATH)
        fixture = json.loads(PORTFOLIO_FIXTURE_PATH.read_text(encoding="utf-8"))

        errors = sorted(validator.iter_errors(fixture), key=lambda item: list(item.path))

        self.assertEqual(errors, [])
        self.assertEqual(schema["properties"]["schema_name"]["const"], "portfolio_allocation")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertNotIn("horizon", schema["$defs"]["bucketAllocation"]["required"])
        self.assertNotIn("horizon", schema["$defs"]["bucketAllocation"]["properties"])
        self.assertEqual(
            schema["$defs"]["marketAllocation"]["properties"]["cross_market_transfer_policy"][
                "const"
            ],
            "manual_only_non_fungible",
        )
        self.assertEqual(fixture["markets"][0]["allocation_pct"], 0.35)
        self.assertEqual(fixture["markets"][1]["allocation_pct"], 0.65)
        self.assertEqual(
            fixture["liquidity_policy"]["cross_market_cash_default"],
            "non_fungible",
        )
        self.assertTrue(fixture["execution_boundary"]["manual_order_only"])

    def test_cash_buffer_state_schema_and_fixture_validate(self) -> None:
        validator, schema = self.validator_for(CASH_STATE_SCHEMA_PATH)
        fixture = json.loads(CASH_STATE_FIXTURE_PATH.read_text(encoding="utf-8"))

        errors = sorted(validator.iter_errors(fixture), key=lambda item: list(item.path))

        self.assertEqual(errors, [])
        self.assertEqual(schema["properties"]["schema_name"]["const"], "cash_buffer_state")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertTrue(fixture["state_management"]["atomic_write_required"])
        self.assertEqual(
            fixture["state_management"]["writer"],
            "engine.analyzer.state_manager.atomic_write_json",
        )
        self.assertFalse(
            fixture["markets"][0]["cash_buffer"]["transfer_allowed_to_other_market"]
        )


if __name__ == "__main__":
    unittest.main()
