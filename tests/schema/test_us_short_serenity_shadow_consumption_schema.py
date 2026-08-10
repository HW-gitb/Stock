from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from jsonschema import Draft7Validator

from engine import us_short_serenity_shadow_consumers as shadow
from engine import us_short_serenity_structural_theme_annotation as annotation_contract
from engine.us_short_schema_formats import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_shadow_consumption.schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "us_short_serenity_structural_theme_annotation_v0_1.json"


class SerenityShadowConsumptionSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def _consume(self, payload):
        with patch.object(annotation_contract, "validate_annotation", return_value=True):
            return shadow.consume_serenity_annotation(payload)

    def _assert_valid(self, payload):
        errors = sorted(
            Draft7Validator(self.schema, format_checker=FORMAT_CHECKER).iter_errors(payload),
            key=lambda error: list(error.absolute_path),
        )
        self.assertEqual(errors, [])

    def test_active_sleeping_and_invalid_outputs_are_closed_schema_valid(self):
        self._assert_valid(self._consume(self.fixture))
        self._assert_valid(self._consume(None))
        broken = copy.deepcopy(self.fixture)
        broken["schema_version"] = "9.9.9"
        self._assert_valid(self._consume(broken))

    def test_schema_pins_effect_boundary_and_report_registry(self):
        self.assertEqual(self.schema["properties"]["schema_name"]["const"], "us_short_serenity_shadow_consumption")
        self.assertEqual(self.schema["$defs"]["report_block"]["allOf"][1]["properties"]["registry_key"]["const"], shadow.REPORT_REGISTRY_KEY)
        effect = self.schema["$defs"]["effect_boundary"]["properties"]
        self.assertEqual(
            {key: value["const"] for key, value in effect.items()},
            shadow.EFFECT_BOUNDARY,
        )
        schema_text = SCHEMA_PATH.read_text(encoding="utf-8")
        self.assertNotIn("policy_disposition", schema_text)


if __name__ == "__main__":
    unittest.main()
