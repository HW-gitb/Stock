from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = [
    "us_short_model_paper_decision_bundle.schema.json",
    "us_short_model_paper_portfolio_state.schema.json",
    "us_short_model_paper_settlement.schema.json",
    "us_short_model_paper_nav_snapshot.schema.json",
    "us_short_model_paper_head_manifest.schema.json",
]


class ModelPaperSchemaTest(unittest.TestCase):
    def test_all_schemas_are_valid_draft7_and_closed_world_at_root(self) -> None:
        for name in SCHEMAS:
            with self.subTest(schema=name):
                schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
                Draft7Validator.check_schema(schema)
                self.assertFalse(schema["additionalProperties"])

    def test_runtime_artifacts_validate_and_unknown_root_key_fails(self) -> None:
        from engine.us_short_model_paper_portfolio import seed_portfolio_state, settle_decision_bundle
        from tests.test_us_short_model_paper_portfolio import _bar, _decision, _order, _packet

        seed = seed_portfolio_state("20260717")
        decision = _decision(seed, [_order()])
        settlement, state, nav = settle_decision_bundle(
            seed,
            decision,
            _packet({"ABC": [_bar("20260720", 10.1, 10.2, 9.8, 10.1)]}, "20260720"),
            "20260720",
        )
        for name, artifact in zip(SCHEMAS[:4], [decision, state, settlement, nav], strict=True):
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            validator = Draft7Validator(schema)
            self.assertEqual([], list(validator.iter_errors(artifact)))
            forged = copy.deepcopy(artifact)
            forged["unexpected"] = True
            self.assertTrue(list(validator.iter_errors(forged)))


if __name__ == "__main__":
    unittest.main()
