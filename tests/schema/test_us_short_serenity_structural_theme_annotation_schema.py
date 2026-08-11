from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator

from engine.us_short_schema_formats import FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[2]
ANNOTATION_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_structural_theme_annotation.schema.json"
RUBRIC_SCHEMA_PATH = ROOT / "schemas" / "us_short_serenity_annotation_rubric.schema.json"
RUBRIC_PATH = ROOT / "presets" / "us_short_serenity_annotation_rubric_v0.1.0.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "us_short_serenity_structural_theme_annotation_v0_1.json"


class SerenityStructuralThemeAnnotationSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.annotation_schema = json.loads(ANNOTATION_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.rubric_schema = json.loads(RUBRIC_SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.rubric = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_annotation_fixture_satisfies_closed_schema(self):
        errors = sorted(
            Draft7Validator(self.annotation_schema, format_checker=FORMAT_CHECKER).iter_errors(self.fixture),
            key=lambda error: list(error.absolute_path),
        )
        self.assertEqual(errors, [])

    def test_rubric_satisfies_closed_schema_and_explicit_policy_allowlist(self):
        errors = sorted(
            Draft7Validator(self.rubric_schema, format_checker=FORMAT_CHECKER).iter_errors(self.rubric),
            key=lambda error: list(error.absolute_path),
        )
        self.assertEqual(errors, [])
        self.assertEqual(
            self.rubric["accepted_upstream_policy_versions"],
            ["soft_discovery_query_policy_v0.2.0", "soft_discovery_query_policy_v0.3.0"],
        )
        self.assertFalse(self.rubric["production_annotation_activated"])

    def test_identity_and_effect_contract_are_explicit(self):
        identity = self.annotation_schema["$defs"]["identity_envelope"]
        self.assertEqual(
            identity["required"][:4],
            [
                "upstream_input_packet_id",
                "upstream_decision_result_id",
                "upstream_policy_version",
                "upstream_decision_date",
            ],
        )
        self.assertEqual(
            identity["properties"]["upstream_policy_version"]["enum"],
            ["soft_discovery_query_policy_v0.2.0", "soft_discovery_query_policy_v0.3.0"],
        )
        effect = self.annotation_schema["$defs"]["effect_boundary"]["properties"]
        self.assertEqual(
            {name: value["const"] for name, value in effect.items()},
            {
                "scoring_eligible": False,
                "top15_effect_enabled": False,
                "operation_advice_effect_enabled": False,
            },
        )
        self.assertNotIn("policy_disposition", self.annotation_schema["properties"])
        self.assertNotIn("policy_disposition", identity["properties"])
        self.assertNotIn("policy_disposition", self.annotation_schema["$defs"]["canonical_annotation"]["properties"])


if __name__ == "__main__":
    unittest.main()
