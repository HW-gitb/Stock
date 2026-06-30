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

SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_status_source_binding.schema.json"
ARTIFACT_PATH = ROOT / "docs" / "us_short_batch5_status_source_binding_20260629.json"

# the frozen per-flag binding the schema const-pins (R-USSHORT-BATCH5-PASS1-CRITICAL-STATUS-HEALTH-FAILOPEN):
# flag -> (authorized_source_id, endpoint_family, unknown_policy)
EXPECTED_FLAG_BINDINGS = {
    "delisted": ("ticker_reference", "active_listing_reference", "conservative_reject"),
    "halted": ("exchange_halt_feed", "public_trading_halt_feed", "conservative_reject"),
    "otc": ("ticker_reference", "primary_exchange_reference", "conservative_reject"),
    "bankruptcy": ("sec_8k_item_103", "sec_8k_bankruptcy_filing_search", "mark_unscreened_not_clean"),
}


class UsShortBatch5StatusSourceBindingSchemaTest(unittest.TestCase):
    def _load(self, path: Path) -> dict:
        self.assertTrue(path.exists(), f"missing required file: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _schema(self) -> dict:
        return self._load(SCHEMA_PATH)

    def _artifact(self) -> dict:
        return self._load(ARTIFACT_PATH)

    def _errors(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._schema()).iter_errors(payload))

    def test_schema_meta(self):
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed") from exc
        schema = self._schema()
        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "us_short_batch5_status_source_binding")
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates(self):
        self.assertEqual(self._errors(self._artifact()), [])

    def test_scope_review_basis_prohibited_are_no_live_call(self):
        art = self._artifact()
        scope = art["scope"]
        self.assertEqual(scope["artifact_status"], "status_source_binding_offline_only")
        self.assertTrue(scope["user_authorized_real_status_source_integration"])
        for f in ("provider_live_call_allowed", "network_access_required", "raw_payload_read_allowed",
                  "parser_implementation_allowed", "gate_integration_implementation_allowed",
                  "datahub_consumption_allowed", "production_storage_allowed", "ship_gate_evidence_allowed"):
            self.assertFalse(scope[f], f)
        self.assertFalse(art["review_basis"]["status_source_calls_performed"])
        for f, v in art["prohibited_actions"].items():
            self.assertFalse(v, f)

    def test_flag_bindings_are_the_frozen_four(self):
        rows = {r["flag_id"]: r for r in self._artifact()["status_flag_bindings"]}
        self.assertEqual(set(rows), set(EXPECTED_FLAG_BINDINGS))
        for flag, (src, ep, unk) in EXPECTED_FLAG_BINDINGS.items():
            self.assertEqual(rows[flag]["authorized_source_id"], src, flag)
            self.assertEqual(rows[flag]["endpoint_family"], ep, flag)
            self.assertEqual(rows[flag]["unknown_policy"], unk, flag)
            self.assertEqual(rows[flag]["eligibility_role"], "disqualifying_status_flag")
            for a in ("authorizes_status_source_call", "authorizes_raw_payload_parse",
                      "authorizes_gate_integration", "authorizes_datahub_or_runner_consumption"):
                self.assertFalse(rows[flag][a], f"{flag}.{a}")

    def test_failure_health_policy_does_not_swallow(self):
        pol = self._artifact()["provider_failure_health_policy"]
        self.assertFalse(pol["swallow_all_exceptions_and_return_empty_allowed"])
        self.assertTrue(pol["failure_feeds_provider_health"])
        self.assertTrue(pol["critical_source_all_fail_must_block_or_no_emit"])
        self.assertFalse(pol["completed_summary_on_critical_failure_allowed"])

    # --- adversarial drift: every mutation must produce >=1 schema error ---
    def test_scope_allow_flip_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["scope"]["provider_live_call_allowed"] = True
        self.assertTrue(self._errors(art))

    def test_flag_authorize_flip_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["status_flag_bindings"][0]["authorizes_status_source_call"] = True
        self.assertTrue(self._errors(art))

    def test_flag_source_drift_rejected(self):
        # bind delisted to the SEC bankruptcy source -> the allOf/contains per-flag binding must reject
        art = copy.deepcopy(self._artifact())
        for row in art["status_flag_bindings"]:
            if row["flag_id"] == "delisted":
                row["authorized_source_id"] = "sec_8k_item_103"
        self.assertTrue(self._errors(art))

    def test_bankruptcy_unknown_policy_drift_rejected(self):
        # bankruptcy must stay mark_unscreened_not_clean (best-effort, no proof of clean); flipping to
        # conservative_reject (or any other) must be rejected by the pinned binding
        art = copy.deepcopy(self._artifact())
        for row in art["status_flag_bindings"]:
            if row["flag_id"] == "bankruptcy":
                row["unknown_policy"] = "conservative_reject"
        self.assertTrue(self._errors(art))

    def test_source_ref_path_swap_rejected(self):
        # point the universe-fetch-runner ref at the design-doc path -> the id<->path contains binding rejects
        art = copy.deepcopy(self._artifact())
        for row in art["source_artifact_refs"]:
            if row["artifact_id"] == "us_short_universe_fetch_runner":
                row["path"] = "docs/us_short_system_design.md"
        self.assertTrue(self._errors(art))

    def test_extra_flag_row_rejected(self):
        art = copy.deepcopy(self._artifact())
        extra = copy.deepcopy(art["status_flag_bindings"][0])
        art["status_flag_bindings"].append(extra)
        self.assertTrue(self._errors(art))   # maxItems 4

    # --- Codex slice-1 re-review: positive-pin the actual contract SEMANTICS, not only routing keys.
    # Each of the five same-shape mutants Codex reproduced (0 errors before) must now error; the artifact stays valid.
    def _flag(self, art, fid):
        return next(r for r in art["status_flag_bindings"] if r["flag_id"] == fid)

    def test_provenance_required_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        self._flag(art, "delisted")["provenance_required"] = ["x", "x", "x", "x", "x"]
        self.assertTrue(self._errors(art))

    def test_missing_provenance_field_rejected(self):
        art = copy.deepcopy(self._artifact())
        self._flag(art, "delisted")["provenance_required"] = ["source_id", "as_of", "observed_at", "coverage"]  # dropped one
        self.assertTrue(self._errors(art))

    def test_derivation_evidence_rule_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        self._flag(art, "delisted")["derivation_evidence_rule"] = "missing reference proves clean false"
        self.assertTrue(self._errors(art))

    def test_bankruptcy_status_semantics_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        self._flag(art, "bankruptcy")["status_semantics"] = "no filing proves solvent and clean"
        self.assertTrue(self._errors(art))

    def test_duplicate_decision_gates_rejected(self):
        art = copy.deepcopy(self._artifact())
        gate = next(g for g in art["decision_gates"] if g["gate_id"] == "phase7c_consumption_gate")
        art["decision_gates"] = [copy.deepcopy(gate) for _ in range(3)]   # 3 duplicate phase7c/blocked rows
        self.assertTrue(self._errors(art))

    def test_missing_decision_gate_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["decision_gates"] = [g for g in art["decision_gates"]
                                 if g["gate_id"] != "parser_and_gate_integration_review"]   # drop one identity
        self.assertTrue(self._errors(art))

    def test_decision_gate_status_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        next(g for g in art["decision_gates"]
             if g["gate_id"] == "phase7c_consumption_gate")["status"] = "pending_user_approval"   # wrong status
        self.assertTrue(self._errors(art))

    def test_source_ref_role_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        for row in art["source_artifact_refs"]:
            if row["artifact_id"] == "us_short_universe_fetch_runner":
                row["role"] = "arbitrary unrelated prose"
        self.assertTrue(self._errors(art))

    # --- Codex scoped re-review residual: each decision gate's `required_resolution` (the resolution class) must
    # be const-pinned too, else an active gate can be rewritten to "no approval required; execute automatically"
    # (cross-LLM authorization drift) while keeping the row shape + false authorization booleans.
    def _gate(self, art, gid):
        return next(g for g in art["decision_gates"] if g["gate_id"] == gid)

    def test_gate_required_resolution_drift_rejected(self):
        unsafe = "No approval or review is required; execute automatically."
        for gid in ("status_source_access_packet_approval", "parser_and_gate_integration_review",
                    "phase7c_consumption_gate"):
            art = copy.deepcopy(self._artifact())
            self._gate(art, gid)["required_resolution"] = unsafe
            self.assertTrue(self._errors(art), gid)   # each gate's canonical resolution is const-pinned

    def test_gate_required_resolution_swap_rejected(self):
        # give the access-packet gate the parser gate's resolution → the pinned per-gate resolution mismatches → reject
        art = copy.deepcopy(self._artifact())
        self._gate(art, "status_source_access_packet_approval")["required_resolution"] = \
            self._gate(art, "parser_and_gate_integration_review")["required_resolution"]
        self.assertTrue(self._errors(art))


if __name__ == "__main__":
    unittest.main()
