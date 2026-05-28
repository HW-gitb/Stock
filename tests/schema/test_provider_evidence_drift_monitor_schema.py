from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_evidence_drift_monitor.schema.json")
EXAMPLE_PATH = Path("schemas/examples/provider_evidence_drift_monitor.example.json")
P1_PUBLIC_SOURCE_PATH = Path("docs/provider_evidence_p1_us_public_sources_20260528.json")
P1_MARKET_DATA_PATH = Path("docs/provider_evidence_p1_us_market_data_candidates_20260528.json")
P1_AUTH_COST_PATH = Path("docs/provider_evidence_p1_us_authorization_cost_stability_20260528.json")
P1_EVIDENCE_PATHS = [P1_PUBLIC_SOURCE_PATH, P1_MARKET_DATA_PATH, P1_AUTH_COST_PATH]


class ProviderEvidenceDriftMonitorSchemaTest(unittest.TestCase):
    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "provider_evidence_drift_monitor")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.1.0")
        self.assertIn("Phase 7b", schema["description"])
        self.assertIn("does not select providers", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_scope_locks_phase7b_boundaries(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        scope = schema["$defs"]["scope"]["properties"]

        self.assertEqual(scope["phase"]["const"], "7b")
        self.assertEqual(scope["purpose"]["const"], "provider_evidence_drift_monitor_contract")
        self.assertEqual(
            set(scope["contract_status"]["enum"]),
            {"schema_first_contract_only", "provider_evidence_population_snapshot"},
        )
        self.assertEqual(scope["provider_selection_allowed"]["const"], False)
        self.assertEqual(scope["data_fetch_allowed"]["const"], False)
        self.assertEqual(scope["provider_adapter_allowed"]["const"], False)
        self.assertEqual(scope["datahub_table_implementation_allowed"]["const"], False)
        self.assertEqual(scope["strategy_rule_change_allowed"]["const"], False)
        self.assertEqual(scope["broker_or_order_automation_allowed"]["const"], False)
        self.assertEqual(scope["manual_order_only"]["const"], True)
        self.assertEqual(scope["ship_gate_relaxed"]["const"], False)
        self.assertEqual(scope["production_ready_claim_allowed"]["const"], False)

    def test_contract_refs_and_p1_to_p4_queue_are_locked(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        refs = schema["$defs"]["contractRefs"]["properties"]
        queue_all_of = schema["properties"]["evidence_queue"]["allOf"]
        queue_priorities = {
            rule["contains"]["properties"]["priority"]["const"] for rule in queue_all_of
        }
        evidence_families = set(schema["$defs"]["evidenceFamily"]["enum"])

        self.assertEqual(refs["provider_priority_contract_ref"]["const"], "docs/provider_priority_benchmark_contract.md")
        self.assertEqual(
            refs["provider_capability_catalog_schema_ref"]["const"],
            "schemas/provider_capability_catalog.schema.json",
        )
        self.assertEqual(refs["evidence_report_schema_ref"]["const"], "schemas/evidence_report.schema.json")
        self.assertEqual(queue_priorities, {"P1", "P2", "P3", "P4"})
        self.assertEqual(
            evidence_families,
            {
                "us_fundamentals_filings_security_master",
                "a_share_fundamentals_announcements_sw_history",
                "burst_event_flow_options_borrow",
                "a_share_eod_csi_helper_surfaces",
            },
        )

    def test_provider_evidence_prevents_defaults_selection_and_fetch(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        record = schema["$defs"]["providerEvidenceRecord"]["properties"]
        queue = schema["$defs"]["evidenceQueueItem"]["properties"]
        rollup = schema["$defs"]["providerReadinessRollup"]["properties"]

        self.assertEqual(record["silent_default_allowed"]["const"], False)
        self.assertEqual(record["latest_only_historical_evidence_allowed"]["const"], False)
        self.assertEqual(record["provider_selection_made"]["const"], False)
        self.assertEqual(record["data_fetch_performed"]["const"], False)
        self.assertEqual(record["drift_monitoring_required"]["const"], True)
        self.assertEqual(queue["provider_selection_made"]["const"], False)
        self.assertEqual(queue["data_fetch_performed"]["const"], False)
        self.assertEqual(rollup["implementation_authorized_by_this_artifact"]["const"], False)
        self.assertEqual(rollup["provider_selection_authorized_by_this_artifact"]["const"], False)
        self.assertEqual(rollup["ship_gate_claim_authorized_by_this_artifact"]["const"], False)

    def test_reviewed_provider_evidence_requires_source_refs_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["provider_evidence_records"][0]["source_basis"] = "reviewed_provider_evidence"

        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertNotEqual(errors, [])
        self.assertTrue(any("evidence_source_refs" in error.message for error in errors))

    def test_drift_dimensions_and_actions_are_required(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        drift = schema["$defs"]["driftMonitor"]["properties"]
        dimension_rules = drift["dimensions"]["allOf"]
        action_rules = drift["action_set"]["allOf"]
        dimensions = {rule["contains"]["properties"]["dimension"]["const"] for rule in dimension_rules}
        actions = {rule["contains"]["const"] for rule in action_rules}

        self.assertEqual(
            dimensions,
            {
                "coverage_count",
                "freshness_latency",
                "schema_or_field_semantics",
                "pit_as_of_integrity",
                "survivorship_security_master",
                "corporate_action_revision",
                "calendar_timezone_alignment",
                "authorization_cost_quota",
                "provider_incident",
                "outlier_revision_rate",
            },
        )
        self.assertEqual(
            actions,
            {
                "warn",
                "block_production_use",
                "manual_review",
                "fallback_path_review",
                "rerun_provider_evidence",
                "record_incident",
                "freeze_latest_only_claims",
            },
        )
        self.assertEqual(drift["incident_log_required"]["const"], True)
        self.assertEqual(drift["silent_semantic_change_monitor_required"]["const"], True)
        self.assertEqual(drift["no_zero_fill_for_benchmarks"]["const"], True)
        self.assertEqual(drift["latest_only_backfill_allowed"]["const"], False)

    def test_example_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        errors = list(Draft7Validator(schema).iter_errors(example))

        self.assertEqual(errors, [])

    def test_p1_evidence_artifacts_validate_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        for path in P1_EVIDENCE_PATHS:
            with self.subTest(path=str(path)):
                artifact = json.loads(path.read_text(encoding="utf-8"))
                errors = list(Draft7Validator(schema).iter_errors(artifact))

                self.assertEqual(errors, [])

    def test_p1_public_source_artifact_is_partial_and_non_authorizing(self) -> None:
        artifact = json.loads(P1_PUBLIC_SOURCE_PATH.read_text(encoding="utf-8"))
        records = {record["record_id"]: record for record in artifact["provider_evidence_records"]}
        p1_records = [record for record in artifact["provider_evidence_records"] if record["priority"] == "P1"]

        self.assertEqual(artifact["scope"]["contract_status"], "provider_evidence_population_snapshot")
        self.assertEqual(artifact["provider_readiness_rollup"]["p1_status"], "partial")
        self.assertEqual(
            artifact["provider_readiness_rollup"]["implementation_authorized_by_this_artifact"],
            False,
        )
        self.assertEqual(
            artifact["provider_readiness_rollup"]["provider_selection_authorized_by_this_artifact"],
            False,
        )
        self.assertGreaterEqual(len(p1_records), 5)
        self.assertIn("p1.us_sec_edgar_submissions", records)
        self.assertIn("p1.us_sec_xbrl_companyfacts", records)
        self.assertTrue(
            all(
                record["source_basis"] == "reviewed_provider_evidence"
                and record["evidence_source_refs"]
                and not record["provider_selection_made"]
                and not record["data_fetch_performed"]
                for record in p1_records
            )
        )

    def test_p1_market_data_artifact_is_partial_and_non_authorizing(self) -> None:
        artifact = json.loads(P1_MARKET_DATA_PATH.read_text(encoding="utf-8"))
        records = {record["record_id"]: record for record in artifact["provider_evidence_records"]}
        p1_records = [record for record in artifact["provider_evidence_records"] if record["priority"] == "P1"]

        self.assertEqual(artifact["scope"]["contract_status"], "provider_evidence_population_snapshot")
        self.assertEqual(artifact["provider_readiness_rollup"]["p1_status"], "partial")
        self.assertEqual(
            artifact["provider_readiness_rollup"]["implementation_authorized_by_this_artifact"],
            False,
        )
        self.assertEqual(
            artifact["provider_readiness_rollup"]["provider_selection_authorized_by_this_artifact"],
            False,
        )
        self.assertGreaterEqual(len(p1_records), 5)
        self.assertIn("p1.us_massive_tickers_security_master", records)
        self.assertIn("p1.us_massive_adjusted_ohlcv", records)
        self.assertIn("p1.us_massive_corporate_actions", records)
        self.assertIn("p1.us_norgate_survivorship_eod", records)
        self.assertIn("p1.us_norgate_index_membership_listing", records)
        self.assertTrue(
            all(
                record["source_basis"] == "reviewed_provider_evidence"
                and record["evidence_source_refs"]
                and not record["provider_selection_made"]
                and not record["data_fetch_performed"]
                for record in p1_records
            )
        )
        massive_records = [
            records["p1.us_massive_tickers_security_master"],
            records["p1.us_massive_adjusted_ohlcv"],
            records["p1.us_massive_corporate_actions"],
            records["p1.us_massive_market_calendar_exchange_status"],
        ]
        massive_source_refs = [
            source_ref
            for record in massive_records
            for source_ref in record["evidence_source_refs"]
            if source_ref["source_id"].startswith("massive_")
        ]
        polygon_terms_refs = [
            source_ref
            for record in massive_records
            for source_ref in record["evidence_source_refs"]
            if source_ref["source_id"] == "polygon_market_data_terms"
        ]
        self.assertTrue(
            all("WebFetched on 2026-05-28" in source_ref["evidence_note"] for source_ref in massive_source_refs)
        )
        self.assertTrue(
            all(
                "does not independently prove Polygon-to-Massive rebrand" in source_ref["evidence_note"]
                for source_ref in massive_source_refs
            )
        )
        self.assertTrue(
            all("WebFetched on 2026-05-28" in source_ref["evidence_note"] for source_ref in polygon_terms_refs)
        )

    def test_p1_authorization_cost_artifact_is_partial_and_non_authorizing(self) -> None:
        artifact = json.loads(P1_AUTH_COST_PATH.read_text(encoding="utf-8"))
        records = {record["record_id"]: record for record in artifact["provider_evidence_records"]}
        p1_records = [record for record in artifact["provider_evidence_records"] if record["priority"] == "P1"]
        reviewed_p1_records = [
            record for record in p1_records if record["source_basis"] == "reviewed_provider_evidence"
        ]
        massive_source_refs = [
            source_ref
            for record in reviewed_p1_records
            for source_ref in record["evidence_source_refs"]
            if source_ref["source_id"].startswith("massive_")
        ]

        self.assertEqual(artifact["scope"]["contract_status"], "provider_evidence_population_snapshot")
        self.assertEqual(artifact["provider_readiness_rollup"]["p1_status"], "partial")
        self.assertEqual(
            artifact["provider_readiness_rollup"]["implementation_authorized_by_this_artifact"],
            False,
        )
        self.assertEqual(
            artifact["provider_readiness_rollup"]["provider_selection_authorized_by_this_artifact"],
            False,
        )
        self.assertIn("p1.us_massive_authorization_cost_quota", records)
        self.assertIn("p1.us_norgate_authorization_cost_access", records)
        self.assertIn("p1.us_norgate_current_fundamentals_latest_only", records)
        self.assertIn("p1.us_remaining_benchmark_gics_fallback_stability", records)
        self.assertEqual(records["p1.us_norgate_current_fundamentals_latest_only"]["pit_status"], "latest_only")
        self.assertEqual(records["p1.us_norgate_current_fundamentals_latest_only"]["capability_status"], "blocked")
        self.assertEqual(
            records["p1.us_remaining_benchmark_gics_fallback_stability"]["source_basis"],
            "placeholder_pending_review",
        )
        self.assertTrue(
            all(
                record["evidence_source_refs"]
                and not record["provider_selection_made"]
                and not record["data_fetch_performed"]
                for record in reviewed_p1_records
            )
        )
        self.assertTrue(
            all(
                "WebFetched on 2026-05-28" in source_ref["evidence_note"]
                for record in reviewed_p1_records
                for source_ref in record["evidence_source_refs"]
            )
        )
        self.assertGreaterEqual(len(massive_source_refs), 4)
        self.assertTrue(
            all("WebFetched on 2026-05-28" in source_ref["evidence_note"] for source_ref in massive_source_refs)
        )
        self.assertTrue(
            all(
                "does not independently prove Polygon-to-Massive rebrand" in source_ref["evidence_note"]
                for source_ref in massive_source_refs
            )
        )
        self.assertTrue(
            any(
                "Massive/Polygon authorization" in limitation
                for limitation in artifact["limitations"]
            )
        )
        self.assertTrue(
            any(
                "latest-only" in limitation
                for limitation in records["p1.us_norgate_current_fundamentals_latest_only"]["limitations"]
            )
        )

    def test_selected_provider_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["provider_evidence_records"][0]["provider_selection_made"] = True

        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertNotEqual(errors, [])

    def test_latest_only_or_silent_default_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["provider_evidence_records"][1]["latest_only_historical_evidence_allowed"] = True
        invalid["provider_evidence_records"][1]["silent_default_allowed"] = True

        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertNotEqual(errors, [])

    def test_missing_p1_queue_item_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["evidence_queue"][0]["priority"] = "P2"

        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertNotEqual(errors, [])

    def test_missing_drift_dimension_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["drift_monitor"]["dimensions"] = [
            item
            for item in invalid["drift_monitor"]["dimensions"]
            if item["dimension"] != "provider_incident"
        ]

        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertNotEqual(errors, [])

    def test_p4_ready_helper_surface_does_not_authorize_implementation(self) -> None:
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

        records = {record["priority"]: record for record in example["provider_evidence_records"]}
        self.assertEqual(records["P4"]["capability_status"], "ready_evidence_recorded")
        self.assertEqual(records["P4"]["readiness_effect"], "records_ready_helper_surface")
        self.assertEqual(example["provider_readiness_rollup"]["p4_status"], "ready_evidence_recorded")
        self.assertEqual(
            example["provider_readiness_rollup"]["implementation_authorized_by_this_artifact"],
            False,
        )
        self.assertEqual(
            example["provider_readiness_rollup"]["provider_selection_authorized_by_this_artifact"],
            False,
        )


if __name__ == "__main__":
    unittest.main()
