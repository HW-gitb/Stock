from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CorporateActionWorkflowSchemaTest(unittest.TestCase):
    def test_schema_const_pins_all_authority_boundaries(self):
        schema = json.loads(
            (ROOT / "schemas" / "us_short_corporate_action_workflow.schema.json").read_text(encoding="utf-8")
        )
        Draft7Validator.check_schema(schema)
        boundary = schema["$defs"]["boundary"]["properties"]
        for key in (
            "provider_call_performed",
            "raw_payload_persisted",
            "corporate_action_semantics_auto_confirmed",
            "account_state_mutated",
            "broker_order_placed",
            "return_calculation_performed",
            "selection_or_ranking_changed",
            "datahub_consumption_allowed",
            "paper_gate_confirmation_claimed",
            "ship_gate_evidence_claimed",
        ):
            self.assertEqual(boundary[key]["const"], False, key)


if __name__ == "__main__":
    unittest.main()
