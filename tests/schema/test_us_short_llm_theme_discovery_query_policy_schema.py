"""Schema-first checks for the A2 candidate-offline policy container."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator

from engine.us_short_schema_formats import FORMAT_CHECKER
from engine.us_short_llm_theme_discovery_query_policy import (
    POLICY_PATH,
    POLICY_SCHEMA_PATH,
    QueryPolicyError,
    validate_query_policy,
)


class QueryPolicySchemaTests(unittest.TestCase):
    def test_tracked_policy_validates_against_its_schema(self):
        schema = json.loads(POLICY_SCHEMA_PATH.read_text(encoding="utf-8"))
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        errors = sorted(
            Draft7Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(policy),
            key=lambda error: list(error.path),
        )
        self.assertEqual(errors, [])
        self.assertTrue(validate_query_policy(policy))

    def test_schema_is_closed_and_activation_cannot_be_opened(self):
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        policy["unexpected"] = True
        with self.assertRaises(QueryPolicyError):
            validate_query_policy(policy)
        activated = copy.deepcopy(policy)
        activated.pop("unexpected")
        activated["activation_status"] = "active"
        with self.assertRaises(QueryPolicyError):
            validate_query_policy(activated)


if __name__ == "__main__":
    unittest.main()
