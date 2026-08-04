from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from engine.us_short_schema_formats import FORMAT_CHECKER
from engine import us_short_llm_theme_discovery_query_policy as query_policy
from runners import us_short_llm_theme_discovery_build_parent_plan as builder


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "us_short_soft_discovery_query_quality_probe_packet_20260808.schema.json"
ARTIFACT_PATH = ROOT / "docs" / "us_short_soft_discovery_query_quality_probe_packet_20260808.json"


class UsShortSoftDiscoveryQueryQualityProbePacket20260808SchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.packet = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    def _errors(self, payload: dict) -> list:
        from jsonschema import Draft7Validator

        return list(
            Draft7Validator(self.schema, format_checker=FORMAT_CHECKER).iter_errors(payload)
        )

    def test_schema_and_packet_validate(self) -> None:
        from jsonschema import Draft7Validator

        Draft7Validator.check_schema(self.schema)
        self.assertEqual(self._errors(self.packet), [])

    def test_exact_bytes_bind_policy_packet_and_parent_plan(self) -> None:
        policy = query_policy.load_query_policy()
        expected_packet_templates = [
            {
                "query_id": row["query_id"],
                "text": row["text"],
                "angles": row["angles"],
            }
            for row in policy["policy_core"]["stage1_templates"]
        ]
        self.assertEqual(self.packet["query_templates"], expected_packet_templates)
        parent_plan = builder.build_parent_plan_from_reviewed_policy(
            decision_date="20260808",
            generated_at="2026-08-03T12:00:00+00:00",
        )
        self.assertEqual(
            [row["query_text"] for row in parent_plan["canonical_plan_core"]["stage1_queries"]],
            [row["text"] for row in self.packet["query_templates"]],
        )

    def test_new_slot_and_budget_arithmetic_are_not_the_burned_slot(self) -> None:
        boundary = self.packet["probe_boundary"]
        budget = self.packet["provider_budget"]
        self.assertEqual(boundary["expected_decision_date"], "20260808")
        self.assertNotIn("20260808", boundary["forbidden_reused_decision_dates"])
        self.assertEqual(budget["max_actual_provider_calls"], 4 + 4 + 4)
        self.assertEqual(budget["current_ledger_reservation_units"], 12)
        self.assertTrue(all("20260808" in value for value in self.packet["execution_slot_map"]["decision_outputs"].values()))
        self.assertTrue(all("20260808" in value for value in self.packet["execution_slot_map"]["budget_ledgers"].values()))
        self.assertIn("20260808", self.packet["execution_slot_map"]["assessment_path"])

    def test_schema_rejects_query_or_gate_mutations(self) -> None:
        for path in (
            ("query_templates", 0, "text"),
            ("pre_execution_gates", "fresh_explicit_user_authorization_required"),
            ("probe_boundary", "expected_decision_date"),
        ):
            with self.subTest(path=path):
                mutated = copy.deepcopy(self.packet)
                target = mutated
                for part in path[:-1]:
                    target = target[part]
                value = target[path[-1]]
                target[path[-1]] = value + "_mutated" if isinstance(value, str) else not value
                self.assertTrue(self._errors(mutated))


if __name__ == "__main__":
    unittest.main()
