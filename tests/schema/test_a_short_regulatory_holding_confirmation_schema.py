from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RegulatoryHoldingConfirmationSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(
            (ROOT / "schemas" / "a_short_regulatory_holding_confirmation.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.example = json.loads(
            (ROOT / "schemas" / "examples" / "a_short_regulatory_holding_confirmation.example.json").read_text(
                encoding="utf-8"
            )
        )

    def test_example_validates(self):
        jsonschema.validate(self.example, self.schema)

    def test_boundary_requires_private_account_scope(self):
        self.example["boundary"]["private_account_only"] = False
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(self.example, self.schema)


if __name__ == "__main__":
    unittest.main()
