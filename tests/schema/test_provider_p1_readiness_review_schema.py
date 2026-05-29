from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_readiness_review.schema.json")
MATRIX_PATH = Path("docs/provider_evidence_p1_us_readiness_review_matrix_20260529.json")


class ProviderP1ReadinessReviewSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_matrix(self) -> dict:
        return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "provider_p1_readiness_review")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertIn("does not select providers", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_matrix_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        errors = list(Draft7Validator(self._load_schema()).iter_errors(self._load_matrix()))

        self.assertEqual(errors, [])

    def test_scope_locks_matrix_to_non_authorizing_review(self) -> None:
        matrix = self._load_matrix()
        scope = matrix["scope"]
        disposition = matrix["readiness_disposition"]

        self.assertEqual(scope["p1_snapshot_collection_status"], "six_snapshots_reviewed")
        self.assertFalse(scope["provider_selection_allowed"])
        self.assertFalse(scope["paid_access_approved"])
        self.assertFalse(scope["data_fetch_allowed"])
        self.assertFalse(scope["provider_adapter_allowed"])
        self.assertFalse(scope["datahub_table_implementation_allowed"])
        self.assertFalse(scope["runner_change_allowed"])
        self.assertFalse(scope["phase7c_authorized_by_this_artifact"])
        self.assertTrue(disposition["p1_collection_complete"])
        self.assertFalse(disposition["p1_ready_for_phase7c"])
        self.assertFalse(disposition["p1_ready_for_provider_selection"])
        self.assertFalse(disposition["p1_ready_for_data_fetch"])

    def test_matrix_covers_required_area_ids_and_blocks_datahub_consumption(self) -> None:
        matrix = self._load_matrix()
        areas = {item["area_id"]: item for item in matrix["review_dimensions"]}

        self.assertEqual(
            set(areas),
            {
                "security_master_survivorship",
                "adjusted_eod_ohlcv_liquidity",
                "corporate_actions_capital_actions",
                "fundamentals_observed_date_pit",
                "benchmark_returns",
                "gics_pit_membership",
                "coverage_counts",
                "authorization_license_cost",
                "fallback_incident_stability",
                "sample_row_validation_lineage",
            },
        )
        self.assertTrue(
            all(
                not item["datahub_consumption_allowed"] and not item["provider_selection_made"]
                for item in areas.values()
            )
        )
        self.assertIn(
            "p1.us_intrinio_filing_fundamentals_observed_date_candidate",
            {
                record_id
                for ref in areas["fundamentals_observed_date_pit"]["source_record_refs"]
                for record_id in ref["record_ids"]
            },
        )
        self.assertIn(
            "p1.us_gics_taxonomy_and_pit_membership_candidate",
            {
                record_id
                for ref in areas["gics_pit_membership"]["source_record_refs"]
                for record_id in ref["record_ids"]
            },
        )

    def test_source_refs_match_existing_snapshots_and_record_ids(self) -> None:
        matrix = self._load_matrix()
        snapshot_paths = {item["snapshot_id"]: Path(item["path"]) for item in matrix["source_snapshot_refs"]}

        for snapshot_id, path in snapshot_paths.items():
            with self.subTest(snapshot_id=snapshot_id):
                self.assertTrue(path.exists())

        for snapshot_ref in matrix["source_snapshot_refs"]:
            snapshot = json.loads(Path(snapshot_ref["path"]).read_text(encoding="utf-8"))
            p1_records = [record for record in snapshot["provider_evidence_records"] if record["priority"] == "P1"]
            self.assertEqual(snapshot_ref["p1_record_count"], len(p1_records))

        records_by_snapshot = {}
        for snapshot_id, path in snapshot_paths.items():
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            records_by_snapshot[snapshot_id] = {
                record["record_id"] for record in snapshot["provider_evidence_records"]
            }

        for dimension in matrix["review_dimensions"]:
            for ref in dimension["source_record_refs"]:
                with self.subTest(area=dimension["area_id"], snapshot=ref["snapshot_id"]):
                    self.assertIn(ref["snapshot_id"], records_by_snapshot)
                    self.assertTrue(set(ref["record_ids"]).issubset(records_by_snapshot[ref["snapshot_id"]]))

    def test_provider_rollup_preserves_key_blocker_conclusions(self) -> None:
        matrix = self._load_matrix()
        rollup = {item["provider_candidate_id"]: item for item in matrix["provider_candidate_rollup"]}

        self.assertEqual(
            rollup["intrinio_filing_fundamentals"]["candidate_evidence_grade"],
            "strong_candidate_but_blocked",
        )
        self.assertEqual(
            rollup["norgate_us_stock_market_platinum"]["candidate_evidence_grade"],
            "strong_candidate_but_blocked",
        )
        self.assertIn(
            "Do not treat Norgate current fundamentals as historical PIT fundamentals.",
            rollup["norgate_us_stock_market_platinum"]["prohibited_interpretations"],
        )
        self.assertIn(
            "Do not treat WebFetched traces as legal continuity proof.",
            rollup["massive_polygon_stocks_api"]["prohibited_interpretations"],
        )
        self.assertFalse(any(item["provider_selection_made"] for item in rollup.values()))

    def test_recommended_next_step_is_access_plan_not_phase7c(self) -> None:
        matrix = self._load_matrix()
        disposition = matrix["readiness_disposition"]

        self.assertEqual(
            disposition["recommended_next_step"],
            "p1_access_decision_and_sample_validation_plan",
        )
        self.assertTrue(
            any("cost ceiling" in item for item in disposition["unresolved_gate_items"])
        )
        self.assertTrue(
            any("Sample rows" in item for item in disposition["unresolved_gate_items"])
        )
        self.assertIn("not ready for Phase 7c", disposition["summary"])

    def test_phase7c_authorization_change_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        invalid = copy.deepcopy(self._load_matrix())
        invalid["scope"]["phase7c_authorized_by_this_artifact"] = True
        invalid["readiness_disposition"]["p1_ready_for_phase7c"] = True

        errors = list(Draft7Validator(self._load_schema()).iter_errors(invalid))

        self.assertNotEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
