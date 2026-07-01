from __future__ import annotations

import copy
import inspect
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_status_source import (  # noqa: E402
    _valid_observed_at,                 # strict RFC3339 (single source, Cut 1a)
    validate_access_packet_errors,      # THE packet validation path: jsonschema + semantic generated_at
)

SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_status_source_access_packet.schema.json"
ARTIFACT_PATH = ROOT / "docs" / "us_short_batch5_status_source_access_packet_20260630.json"


class StatusSourceAccessPacketSchemaTest(unittest.TestCase):
    def _load(self, path: Path) -> dict:
        self.assertTrue(path.exists(), f"missing required file: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _schema(self) -> dict:
        return self._load(SCHEMA_PATH)

    def _artifact(self) -> dict:
        return self._load(ARTIFACT_PATH)

    def _errors(self, payload: dict) -> list:
        # Validate THROUGH the repo helper (jsonschema + semantic generated_at) against the CANONICAL repo schema
        # the helper loads itself — NO caller-supplied schema (Codex residual B: a caller passing {} / a permissive
        # schema must not be able to validate an authorization mutant). The test calls the same path 1b will.
        try:
            return validate_access_packet_errors(payload)
        except RuntimeError as exc:   # helper fails closed when jsonschema is unavailable -> skip (cannot test)
            raise unittest.SkipTest(str(exc)) from exc

    def test_schema_meta(self):
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed") from exc
        schema = self._schema()
        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"],
                         "us_short_batch5_status_source_access_packet")
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates(self):
        self.assertEqual(self._errors(self._artifact()), [])

    def test_scope_authorizes_nothing_live(self):
        scope = self._artifact()["scope"]
        self.assertTrue(scope["user_authorized_real_status_source_integration"])
        self.assertTrue(scope["small_sample_first_required"])
        for f in ("status_source_calls_executed_by_this_artifact", "network_access_required_for_this_artifact",
                  "status_calls_allowed_without_future_authorization", "bankruptcy_8k_per_issuer_scan_allowed",
                  "full_market_or_per_symbol_fetch_allowed", "parser_into_runner_integration_allowed",
                  "candidate_artifact_schema_change_allowed", "datahub_consumption_allowed",
                  "production_storage_allowed", "yfinance_allowed", "web_x_allowed", "paid_access_allowed",
                  "ship_gate_evidence_allowed", "production_ready_claim_allowed"):
            self.assertFalse(scope[f], f)

    def test_prohibited_claims_all_false(self):
        for f, v in self._artifact()["prohibited_claims"].items():
            self.assertFalse(v, f)

    def test_budget_is_two_calls_zero_retry(self):
        b = self._artifact()["status_source_probe_boundary"]["endpoint_call_budget"]
        self.assertEqual(b["max_total_endpoint_calls"], 2)
        self.assertEqual(b["bankruptcy_8k_calls"], 0)
        self.assertEqual(b["retry_count_allowed"], 0)
        self.assertFalse(b["budget_authorized_by_this_artifact"])

    def test_deferred_scope_records_bankruptcy_and_runner_rewire(self):
        d = self._artifact()["deferred_scope"]
        self.assertEqual(d["bankruptcy_8k_per_issuer_scan"], "deferred_separate_packet_per_issuer_budget")
        self.assertEqual(d["parser_into_runner_apply_pass1"], "deferred_to_1b_with_live_fetch")
        self.assertEqual(d["candidate_artifact_status_provenance_schema"], "deferred_to_1b_with_live_producer")

    # --- adversarial drift: every mutation must produce >=1 schema error ---
    def test_scope_allow_flip_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["scope"]["full_market_or_per_symbol_fetch_allowed"] = True
        self.assertTrue(self._errors(art))

    def test_status_call_now_flip_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["scope"]["status_source_calls_executed_by_this_artifact"] = True
        self.assertTrue(self._errors(art))

    def test_prohibited_claim_flip_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["prohibited_claims"]["bankruptcy_8k_scanned"] = True
        self.assertTrue(self._errors(art))

    def test_budget_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["status_source_probe_boundary"]["endpoint_call_budget"]["max_total_endpoint_calls"] = 9999
        self.assertTrue(self._errors(art))

    def test_bankruptcy_budget_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["status_source_probe_boundary"]["endpoint_call_budget"]["bankruptcy_8k_calls"] = 2323
        self.assertTrue(self._errors(art))

    def test_retry_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["status_source_probe_boundary"]["endpoint_call_budget"]["retry_count_allowed"] = 3
        self.assertTrue(self._errors(art))

    def test_endpoint_family_source_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        for fam in art["status_source_probe_boundary"]["endpoint_families"]:
            if fam["source_id"] == "exchange_halt_feed":
                fam["source_id"] = "ticker_reference"   # both families would be ticker_reference -> contains fails
        self.assertTrue(self._errors(art))

    def test_extra_endpoint_family_rejected(self):
        art = copy.deepcopy(self._artifact())
        extra = copy.deepcopy(art["status_source_probe_boundary"]["endpoint_families"][0])
        art["status_source_probe_boundary"]["endpoint_families"].append(extra)
        self.assertTrue(self._errors(art))   # maxItems 2

    def test_deferred_scope_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["deferred_scope"]["bankruptcy_8k_per_issuer_scan"] = "authorized_full_market_now"
        self.assertTrue(self._errors(art))

    def test_authorization_status_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["status_source_probe_boundary"]["authorization_status"] = "authorized"
        self.assertTrue(self._errors(art))

    def test_missing_source_ref_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["source_artifact_refs"] = [r for r in art["source_artifact_refs"]
                                       if r["artifact_id"] != "us_short_status_source_binding"]
        self.assertTrue(self._errors(art))

    def test_extra_top_key_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["surprise"] = True
        self.assertTrue(self._errors(art))

    # --- Codex finding B (R-USSHORT-BATCH5-STATUS-SOURCE-CLOCK-AND-ACCESS-PACKET-PIN-GAP): same-shape
    # authorization-routing drift must error while the real artifact stays valid (id↔path↔role pinned,
    # exact ref cardinality, source↔flag pinned, generated_at format enforced). ---
    def test_source_ref_path_and_role_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["source_artifact_refs"][0]["path"] = "docs/CURRENT.md"
        art["source_artifact_refs"][0]["role"] = "now claims full-market authorization"
        self.assertTrue(self._errors(art))

    def test_source_ref_role_only_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["source_artifact_refs"][1]["role"] = "drifted role prose"
        self.assertTrue(self._errors(art))

    def test_extra_source_ref_rejected(self):
        art = copy.deepcopy(self._artifact())
        extra = copy.deepcopy(art["source_artifact_refs"][0]); extra["artifact_id"] = "x_extra"
        art["source_artifact_refs"].append(extra)
        self.assertTrue(self._errors(art))   # maxItems 4

    def test_ticker_ref_endpoint_flags_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        for fam in art["status_source_probe_boundary"]["endpoint_families"]:
            if fam["source_id"] == "ticker_reference":
                fam["flags"] = ["halted"]            # ticker_reference must stay ['delisted','otc']
        self.assertTrue(self._errors(art))

    def test_halt_feed_endpoint_flags_drift_rejected(self):
        art = copy.deepcopy(self._artifact())
        for fam in art["status_source_probe_boundary"]["endpoint_families"]:
            if fam["source_id"] == "exchange_halt_feed":
                fam["flags"] = ["delisted"]          # halt feed must stay ['halted']
        self.assertTrue(self._errors(art))

    def test_bad_generated_at_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["generated_at"] = "not-a-date"           # const-pin (+ semantic helper) rejects any non-exact value
        self.assertTrue(self._errors(art))

    def test_impossible_generated_at_fails_packet_validation(self):
        # Codex residual 2 + A3: generated_at is const-pinned to the exact reviewed dated value AND the helper
        # semantically rejects impossible RFC3339 — a calendar-impossible value fails the validation path.
        for bad in ("2026-99-99T99:99:99+99:99", "2026-02-31T00:00:00+00:00"):   # impossible range + Feb-31
            art = copy.deepcopy(self._artifact())
            art["generated_at"] = bad
            self.assertTrue(self._errors(art), bad)

    def test_future_or_non_exact_generated_at_rejected(self):
        # Codex residual A3: this is a FIXED dated packet, so generated_at is const-pinned to the exact reviewed
        # instant. A future generation chronology — or ANY semantically-valid but non-exact value — must be
        # rejected through the canonical validation path (the dated packet cannot claim a future/other gen time).
        for bad in ("2099-01-01T00:00:00+00:00",        # far-future
                    "2026-07-01T00:30:00Z",             # day after the dated packet
                    "2026-06-30T00:00:00Z"):            # semantically valid but != the pinned dated value
            art = copy.deepcopy(self._artifact())
            art["generated_at"] = bad
            self.assertTrue(self._errors(art), bad)

    def test_real_generated_at_semantically_valid(self):
        self.assertTrue(_valid_observed_at(self._artifact()["generated_at"]))

    def test_generated_at_helper_positive_and_negative_controls(self):
        for ok in ("2026-06-30T00:00:00+08:00", "2026-06-30T00:00:00Z"):     # tz-aware (offset + Z) accepted
            self.assertTrue(_valid_observed_at(ok), ok)
        for bad in ("2026-06-30", "2026-06-30T12:00:00", "2026-06-30 12:00:00"):  # date-only / no-tz / space-sep
            self.assertFalse(_valid_observed_at(bad), bad)

    # --- Codex residual B: the validation path owns its rules; no caller-supplied schema can bypass const-pins ---
    def test_helper_has_no_caller_schema_override(self):
        params = inspect.signature(validate_access_packet_errors).parameters
        self.assertEqual(set(params), {"packet"})        # no `schema=` seam → a caller can't pass {} / a permissive schema

    def test_authorization_mutant_rejected_through_canonical_path(self):
        # the same authorization mutant Codex bypassed with schema={} must error through the no-injection path.
        art = copy.deepcopy(self._artifact())
        art["scope"]["status_calls_allowed_without_future_authorization"] = True
        art["prohibited_claims"]["status_call_authorized_now"] = True
        self.assertTrue(self._errors(art))

    # --- Codex residual C: operational/authorization prose must not contradict the typed gates (const-pinned) ---
    def test_next_steps_operational_mutation_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["next_steps"] = ["Execute live calls immediately without approval or preflight."]
        self.assertTrue(self._errors(art))

    def test_limitations_operational_mutation_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["limitations"] = ["This packet authorizes production and ship-gate use now."]
        self.assertTrue(self._errors(art))

    def test_provider_role_operational_mutation_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["status_source_probe_boundary"]["endpoint_families"][0]["provider_role"] = \
            "This authorizes runner/DataHub/production consumption now."
        self.assertTrue(self._errors(art))

    def test_provider_candidates_mutation_rejected(self):
        art = copy.deepcopy(self._artifact())
        art["status_source_probe_boundary"]["endpoint_families"][1]["provider_candidates"] = \
            ["an arbitrary unreviewed provider"]
        self.assertTrue(self._errors(art))


if __name__ == "__main__":
    unittest.main()
