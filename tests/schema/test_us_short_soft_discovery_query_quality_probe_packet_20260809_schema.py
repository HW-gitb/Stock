from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from engine.us_short_schema_formats import FORMAT_CHECKER
from engine import us_short_llm_theme_discovery_query_policy as query_policy
from runners import us_short_llm_theme_discovery_build_parent_plan as builder
from runners import us_short_soft_discovery_query_quality_probe_assess as assess


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "us_short_soft_discovery_query_quality_probe_packet_20260809.schema.json"
ARTIFACT_PATH = ROOT / "docs" / "us_short_soft_discovery_query_quality_probe_packet_20260809.json"
CURRENT_SCHEMA_PATH = ROOT / "schemas" / "us_short_soft_discovery_query_quality_probe_packet_20260815.schema.json"
CURRENT_ARTIFACT_PATH = ROOT / "docs" / "us_short_soft_discovery_query_quality_probe_packet_20260815.json"
FROZEN_20260809_PATHS = {
    ARTIFACT_PATH: "ccbba88dd2fb37ff27b80c2e44f4edb1f9e2e8ead1f2df26fab084a92850f526",
    SCHEMA_PATH: "60b1d8e5ff48a19d48bfdfdf5a5d738b5cf88c0ef96337a04d5d1fe1725a430a",
    ROOT / "docs" / "us_short_soft_discovery_query_quality_probe_assessment_20260809.json":
        "afb6e9030d04273b061825b8ab6ffe00cc93d7552de07f895bcf23d8e22bce11",
}


class UsShortSoftDiscoveryQueryQualityProbePacket20260809SchemaTest(unittest.TestCase):
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

    def test_exact_bytes_keep_the_executed_packet_bound_to_the_reviewed_policy(self) -> None:
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

    def test_new_slot_and_budget_arithmetic_are_not_the_burned_slot(self) -> None:
        boundary = self.packet["probe_boundary"]
        budget = self.packet["provider_budget"]
        self.assertEqual(boundary["expected_decision_date"], "20260809")
        self.assertNotIn("20260809", boundary["forbidden_reused_decision_dates"])
        self.assertEqual(budget["max_actual_provider_calls"], 4 + 4 + 4)
        self.assertEqual(budget["current_ledger_reservation_units"], 12)
        self.assertTrue(all("20260809" in value for value in self.packet["execution_slot_map"]["decision_outputs"].values()))
        self.assertTrue(all("20260809" in value for value in self.packet["execution_slot_map"]["budget_ledgers"].values()))
        self.assertIn("20260809", self.packet["execution_slot_map"]["assessment_path"])

    def test_executed_packet_remains_an_explicit_registered_assessor_slot(self) -> None:
        packet_path, schema_path = assess._packet_spec(ARTIFACT_PATH)
        self.assertEqual(packet_path, ARTIFACT_PATH.absolute())
        self.assertEqual(schema_path, SCHEMA_PATH)

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


class UsShortSoftDiscoveryQueryQualityProbePacket20260815SchemaTest(unittest.TestCase):
    """The historical module also owns the current slot so IO inventory gains no empty module."""

    def setUp(self) -> None:
        self.schema = json.loads(CURRENT_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.packet = json.loads(CURRENT_ARTIFACT_PATH.read_text(encoding="utf-8"))

    def _errors(self, payload: dict) -> list:
        from jsonschema import Draft7Validator

        return list(
            Draft7Validator(self.schema, format_checker=FORMAT_CHECKER).iter_errors(payload)
        )

    def test_schema_packet_and_current_assessor_registration_validate(self) -> None:
        from jsonschema import Draft7Validator

        Draft7Validator.check_schema(self.schema)
        self.assertEqual(self._errors(self.packet), [])
        packet_path, schema_path = assess._packet_spec(CURRENT_ARTIFACT_PATH)
        self.assertEqual(packet_path, CURRENT_ARTIFACT_PATH.absolute())
        self.assertEqual(schema_path, CURRENT_SCHEMA_PATH)

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
            decision_date="20260815",
            generated_at=self.packet["generated_at"],
        )
        self.assertEqual(
            [row["query_text"] for row in parent_plan["canonical_plan_core"]["stage1_queries"]],
            [row["text"] for row in self.packet["query_templates"]],
        )

    def test_new_slot_budget_and_burned_dates_are_exact(self) -> None:
        boundary = self.packet["probe_boundary"]
        budget = self.packet["provider_budget"]
        self.assertEqual(boundary["expected_decision_date"], "20260815")
        self.assertNotIn("20260815", boundary["forbidden_reused_decision_dates"])
        self.assertTrue(
            {"20260730", "20260731", "20260801", "20260802", "20260808", "20260809"}
            <= set(boundary["forbidden_reused_decision_dates"])
        )
        self.assertEqual(budget["max_actual_provider_calls"], 4 + 4 + 4)
        self.assertEqual(budget["current_ledger_reservation_units"], 12)
        self.assertTrue(all(
            "20260815" in value
            for value in self.packet["execution_slot_map"]["decision_outputs"].values()
        ))
        self.assertTrue(all(
            "20260815" in value
            for value in self.packet["execution_slot_map"]["budget_ledgers"].values()
        ))
        self.assertIn("20260815", self.packet["execution_slot_map"]["assessment_path"])

    def test_reslot_does_not_change_queries_budgets_metrics_thresholds_or_effects(self) -> None:
        frozen = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        for field in (
            "scope",
            "policy_draft",
            "query_templates",
            "provider_budget",
            "pre_execution_gates",
            "preregistered_evaluation",
            "storage_and_secret_boundary",
            "prohibited_effects",
        ):
            with self.subTest(field=field):
                self.assertEqual(self.packet[field], frozen[field])

    def test_schema_rejects_query_gate_threshold_or_date_mutations(self) -> None:
        for path in (
            ("query_templates", 0, "text"),
            ("pre_execution_gates", "fresh_explicit_user_authorization_required"),
            ("probe_boundary", "expected_decision_date"),
            ("preregistered_evaluation", "per_lane_quality_thresholds", "minimum_member_bound_source_ratio"),
        ):
            with self.subTest(path=path):
                mutated = copy.deepcopy(self.packet)
                target = mutated
                for part in path[:-1]:
                    target = target[part]
                value = target[path[-1]]
                target[path[-1]] = value + "_mutated" if isinstance(value, str) else not value
                self.assertTrue(self._errors(mutated))

    def test_executed_20260809_data_artifacts_remain_byte_immutable(self) -> None:
        for path, expected_sha256 in FROZEN_20260809_PATHS.items():
            with self.subTest(path=path.name):
                from hashlib import sha256

                self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected_sha256)


if __name__ == "__main__":
    unittest.main()
