from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator

from engine.us_short_schema_formats import FORMAT_CHECKER
from engine import us_short_llm_theme_discovery_query_policy as query_policy


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "presets" / "us_short_llm_theme_discovery_query_policy_v0.3.0.json"
SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery_query_policy_v0.3.0.schema.json"


class QueryPolicyV03SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_v03_policy_validates_and_is_registered(self) -> None:
        Draft7Validator.check_schema(self.schema)
        self.assertEqual(
            list(Draft7Validator(self.schema, format_checker=FORMAT_CHECKER).iter_errors(self.policy)),
            [],
        )
        self.assertTrue(query_policy.validate_query_policy(self.policy))
        self.assertEqual(
            query_policy.load_query_policy_for_version(query_policy.V0_3_POLICY_VERSION),
            self.policy,
        )

    def test_v03_schema_is_closed_and_content_digest_is_load_bearing(self) -> None:
        unexpected = copy.deepcopy(self.policy)
        unexpected["source_packet"] = {"path": "docs/unused.json", "sha256": "0" * 64}
        self.assertTrue(list(Draft7Validator(self.schema).iter_errors(unexpected)))

        drifted = copy.deepcopy(self.policy)
        drifted["policy_core"]["stage1_templates"][2]["text"] += " drift"
        with self.assertRaises(query_policy.QueryPolicyError):
            query_policy.validate_query_policy(drifted)


if __name__ == "__main__":
    unittest.main()
