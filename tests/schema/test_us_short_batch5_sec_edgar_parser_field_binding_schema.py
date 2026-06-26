from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))

SCHEMA_PATH = Path("schemas/us_short_batch5_sec_edgar_parser_field_binding.schema.json")
ARTIFACT_PATH = Path("docs/us_short_batch5_sec_edgar_parser_field_binding_20260625.json")

EXPECTED_FIELD_FAMILIES = {
    "company_identity_cik_ticker": (
        "blocked_supporting_identity_only",
        "blocked_pending_identity_mapping_review",
    ),
    "filing_metadata_accession": (
        "blocked_lineage_gate_only",
        "blocked_pending_time_lineage_review",
    ),
    "accepted_filed_timestamps": (
        "blocked_lineage_gate_only",
        "blocked_pending_time_lineage_review",
    ),
    "fiscal_period_context": (
        "blocked_lineage_gate_only",
        "blocked_pending_taxonomy_context_review",
    ),
    "income_statement_audit": (
        "in_scope_audit_only",
        "blocked_pending_parser_mapping_review",
    ),
    "balance_sheet_audit": (
        "in_scope_audit_only",
        "blocked_pending_parser_mapping_review",
    ),
    "cash_flow_audit": (
        "in_scope_audit_only",
        "blocked_pending_parser_mapping_review",
    ),
    "shares_outstanding_audit": (
        "in_scope_audit_only",
        "blocked_audit_only_not_production_provider",
    ),
    "taxonomy_units_currency": (
        "blocked_lineage_gate_only",
        "blocked_pending_taxonomy_context_review",
    ),
    "amendment_restatement_chain": (
        "blocked_lineage_gate_only",
        "blocked_pending_time_lineage_review",
    ),
}

EXPECTED_LINEAGE = {
    "cik_ticker_identity",
    "accession_number",
    "submission_ref",
    "form_type",
    "accepted_timestamp",
    "filed_date",
    "report_period_date",
    "fiscal_year_period",
    "amendment_or_restatement_flag",
    "taxonomy_tag",
    "taxonomy_extension",
    "unit_and_currency",
    "period_start_end_dates",
    "context_dimensions",
    "source_endpoint_and_params",
    "as_of_eligibility_rule",
}

EXPECTED_GATES = {
    "sec_access_packet_approval": "pending_user_approval",
    "parser_implementation_review": "pending_later_parser_review",
    "taxonomy_context_mapping_review": "pending_later_mapping_review",
    "fmp_cross_check_mapping_review": "pending_later_mapping_review",
    "artifact_retention_fixture_policy": "pending_later_artifact_policy",
    "phase7c_consumption_gate": "blocked",
}

EXPECTED_SOURCE_ARTIFACTS = {
    "us_short_system_design": (
        "docs/us_short_system_design.md",
        "US-short single design authority; batch5 SEC parser and field mapping remain separately gated under SR-PROVIDER-001.",
    ),
    "us_short_batch5_license_storage_retention_decision_20260625": (
        "docs/us_short_batch5_license_storage_retention_decision_20260625.json",
        "Keeps SEC broader reconstruction blocked pending parser, fair-access, artifact-retention, PIT lineage, and separate endpoint authorization.",
    ),
    "provider_p1_sec_edgar_audit_parser_scope_contract_20260602": (
        "docs/provider_evidence_p1_us_sec_edgar_audit_parser_scope_contract_20260602.json",
        "Owner P1 no-access contract for SEC audit-only parser scope, fair-access, lineage, and artifact gates.",
    ),
    "provider_p1_sec_edgar_field_family_mapping_contract_20260602": (
        "docs/provider_evidence_p1_us_sec_edgar_field_family_mapping_contract_20260602.json",
        "Owner P1 no-access contract for SEC audit field-family mappings and cross-check policy.",
    ),
    "provider_p1_license_storage_retention_review_20260602": (
        "docs/provider_evidence_p1_us_license_storage_retention_review_20260602.json",
        "Requires SEC parser / fair-access / artifact-retention contract before broader SEC reconstruction or production storage.",
    ),
    "sr_provider_001": (
        "docs/system_risk_register.md",
        "Open provider blocker; this binding does not resolve broader SEC access, parser implementation, field mapping, fixture generation, DataHub, production readiness, live_normalized, or ship-gate boundaries.",
    ),
}

AUTHZ_FALSE_FIELDS = [
    "authorizes_sec_api_call",
    "authorizes_raw_payload_parse",
    "authorizes_fixture_generation",
    "authorizes_parser_implementation",
    "authorizes_field_mapping_implementation",
    "authorizes_datahub_or_runner_consumption",
]


class UsShortBatch5SecEdgarParserFieldBindingSchemaTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        self.assertTrue(path.exists(), f"missing required file: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_schema(self) -> dict:
        return self._load_json(SCHEMA_PATH)

    def _load_artifact(self) -> dict:
        return self._load_json(ARTIFACT_PATH)

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_schema()).iter_errors(payload))

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "us_short_batch5_sec_edgar_parser_field_binding")
        self.assertIn("US-short batch5", schema["description"])
        self.assertIn("does not perform SEC API calls", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_review_basis_and_prohibited_actions_are_no_access(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        basis = artifact["review_basis"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["market"], "US")
        self.assertEqual(scope["lane"], "us_short")
        self.assertEqual(scope["batch"], "batch5_provider_live")
        self.assertEqual(scope["artifact_status"], "sec_edgar_parser_field_binding_offline_only")
        for field in [
            "provider_live_call_allowed",
            "network_access_required",
            "sec_api_call_allowed",
            "raw_payload_read_allowed",
            "raw_payload_parse_allowed",
            "fixture_generation_allowed",
            "parser_implementation_allowed",
            "field_mapping_implementation_allowed",
            "fmp_endpoint_call_allowed",
            "provider_selection_allowed",
            "datahub_consumption_allowed",
            "runner_consumption_allowed",
            "production_storage_allowed",
            "live_normalized_evidence_allowed",
            "ship_gate_evidence_allowed",
        ]:
            self.assertFalse(scope[field], field)

        self.assertEqual(basis["basis_type"], "existing_repo_artifacts_no_new_external_review")
        self.assertTrue(basis["uses_existing_reviewed_artifacts_only"])
        self.assertFalse(basis["sec_api_calls_performed"])
        self.assertFalse(basis["raw_payload_read_or_parsed"])
        self.assertFalse(basis["fixture_generated"])
        self.assertFalse(basis["parser_implemented"])
        self.assertFalse(basis["field_mapping_implemented"])

        for field, value in prohibited.items():
            self.assertFalse(value, field)

    def test_source_refs_bind_batch5_to_existing_p1_contracts(self) -> None:
        rows = {
            row["artifact_id"]: row
            for row in self._load_artifact()["source_artifact_refs"]
        }

        self.assertEqual(set(rows), set(EXPECTED_SOURCE_ARTIFACTS))
        for ref_id, (path, role) in EXPECTED_SOURCE_ARTIFACTS.items():
            with self.subTest(ref_id=ref_id):
                self.assertEqual(rows[ref_id]["path"], path)
                self.assertEqual(rows[ref_id]["role"], role)

    def test_schema_rejects_source_artifact_traceback_drift_when_jsonschema_available(self) -> None:
        for ref_id in EXPECTED_SOURCE_ARTIFACTS:
            invalid = copy.deepcopy(self._load_artifact())
            row = next(
                row
                for row in invalid["source_artifact_refs"]
                if row["artifact_id"] == ref_id
            )
            row["path"] = "docs/wrong_source.json"

            with self.subTest(kind="source_path", ref_id=ref_id):
                self.assertNotEqual(self._validate(invalid), [])

            invalid = copy.deepcopy(self._load_artifact())
            row = next(
                row
                for row in invalid["source_artifact_refs"]
                if row["artifact_id"] == ref_id
            )
            row["role"] = "wrong role boundary"

            with self.subTest(kind="source_role", ref_id=ref_id):
                self.assertNotEqual(self._validate(invalid), [])

        invalid = copy.deepcopy(self._load_artifact())
        invalid["source_artifact_refs"].append(
            {
                "artifact_id": "unreviewed_external_source",
                "path": "docs/not_authorized.json",
                "role": "extra unreviewed source",
            }
        )
        self.assertNotEqual(self._validate(invalid), [])

    def test_field_family_rows_are_exact_and_do_not_authorize_execution(self) -> None:
        rows = {
            row["field_family_id"]: row
            for row in self._load_artifact()["audit_field_family_bindings"]
        }

        self.assertEqual(set(rows), set(EXPECTED_FIELD_FAMILIES))
        for field_family_id, (audit_role, mapping_status) in EXPECTED_FIELD_FAMILIES.items():
            with self.subTest(field_family_id=field_family_id):
                row = rows[field_family_id]
                self.assertEqual(row["audit_role"], audit_role)
                self.assertEqual(row["mapping_status"], mapping_status)
                self.assertTrue(row["blocks_broader_parser_or_datahub"])
                for field in AUTHZ_FALSE_FIELDS:
                    self.assertFalse(row[field], field)

    def test_schema_rejects_field_family_status_drift_when_jsonschema_available(self) -> None:
        for field_family_id, (audit_role, mapping_status) in EXPECTED_FIELD_FAMILIES.items():
            invalid = copy.deepcopy(self._load_artifact())
            row = next(
                row
                for row in invalid["audit_field_family_bindings"]
                if row["field_family_id"] == field_family_id
            )
            row["audit_role"] = "in_scope_audit_only" if audit_role != "in_scope_audit_only" else "blocked_lineage_gate_only"
            row["mapping_status"] = (
                "blocked_pending_parser_mapping_review"
                if mapping_status != "blocked_pending_parser_mapping_review"
                else "blocked_pending_time_lineage_review"
            )

            with self.subTest(field_family_id=field_family_id):
                self.assertNotEqual(self._validate(invalid), [])

    def test_schema_rejects_source_traceback_drift_when_jsonschema_available(self) -> None:
        for field_family_id in EXPECTED_FIELD_FAMILIES:
            invalid = copy.deepcopy(self._load_artifact())
            row = next(
                row
                for row in invalid["audit_field_family_bindings"]
                if row["field_family_id"] == field_family_id
            )
            row["source_contract_field_family_ref"] = "wrong_source_ref"

            with self.subTest(kind="field_family", field_family_id=field_family_id):
                self.assertNotEqual(self._validate(invalid), [])

        for requirement_id in EXPECTED_LINEAGE:
            invalid = copy.deepcopy(self._load_artifact())
            row = next(
                row
                for row in invalid["parser_lineage_requirements"]
                if row["requirement_id"] == requirement_id
            )
            row["source_contract_requirement_ref"] = "wrong_source_ref"

            with self.subTest(kind="lineage", requirement_id=requirement_id):
                self.assertNotEqual(self._validate(invalid), [])

        for gate_id in EXPECTED_GATES:
            invalid = copy.deepcopy(self._load_artifact())
            row = next(row for row in invalid["decision_gates"] if row["gate_id"] == gate_id)
            row["source_contract_gate_ref"] = "wrong_source_ref"

            with self.subTest(kind="gate", gate_id=gate_id):
                self.assertNotEqual(self._validate(invalid), [])

    def test_lineage_rows_and_decision_gates_are_locked(self) -> None:
        artifact = self._load_artifact()
        lineage = {row["requirement_id"]: row for row in artifact["parser_lineage_requirements"]}
        gates = {row["gate_id"]: row for row in artifact["decision_gates"]}

        self.assertEqual(set(lineage), EXPECTED_LINEAGE)
        for requirement in lineage.values():
            self.assertEqual(requirement["status"], "required_before_sec_audit_mapping_or_datahub")
            self.assertTrue(requirement["blocks_broader_parser_or_datahub"])
            for field in AUTHZ_FALSE_FIELDS:
                self.assertFalse(requirement[field], field)

        self.assertEqual(set(gates), set(EXPECTED_GATES))
        for gate_id, expected_status in EXPECTED_GATES.items():
            with self.subTest(gate_id=gate_id):
                gate = gates[gate_id]
                self.assertEqual(gate["status"], expected_status)
                self.assertTrue(gate["blocks_implementation"])
                self.assertFalse(gate["authorizes_sec_api_call"])
                self.assertFalse(gate["authorizes_raw_payload_parse"])
                self.assertFalse(gate["authorizes_fixture_generation"])
                self.assertFalse(gate["authorizes_parser_implementation"])
                self.assertFalse(gate["authorizes_field_mapping_implementation"])
                self.assertFalse(gate["authorizes_datahub_or_runner_consumption"])
                self.assertFalse(gate["authorizes_phase7c"])

    def test_schema_rejects_scope_creep_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["sec_api_call_allowed"] = True
        invalid["scope"]["raw_payload_parse_allowed"] = True
        invalid["scope"]["fixture_generation_allowed"] = True
        invalid["scope"]["parser_implementation_allowed"] = True
        invalid["scope"]["datahub_consumption_allowed"] = True
        invalid["scope"]["ship_gate_evidence_allowed"] = True
        invalid["review_basis"]["raw_payload_read_or_parsed"] = True
        invalid["prohibited_actions"]["ship_gate_claim"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
