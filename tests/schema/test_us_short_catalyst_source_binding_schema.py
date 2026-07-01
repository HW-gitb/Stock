# -*- coding: utf-8 -*-
"""Adversarial schema tests for the frozen US-short Cut 4 catalyst-source binding.

The binding freezes the offline catalyst-source contract (per-source value/date + provider/endpoint family,
required provenance fields, coverage/parser enums, all-gated authorization boundary). Every drift mutation must
produce >=1 schema error while the real artifact validates (§18.2 schema-first-before-consumption).
"""
import copy
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

SCHEMA_PATH = ROOT / "schemas" / "us_short_catalyst_source_binding.schema.json"
BINDING_PATH = ROOT / "docs" / "us_short_catalyst_source_binding_20260701.json"


class CatalystSourceBindingSchemaTest(unittest.TestCase):
    def _load(self, path):
        self.assertTrue(path.exists(), f"missing required file: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _schema(self):
        return self._load(SCHEMA_PATH)

    def _binding(self):
        return self._load(BINDING_PATH)

    def _errors(self, payload):
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
        self.assertEqual(schema["properties"]["schema_name"]["const"], "us_short_catalyst_source_binding")
        self.assertFalse(schema["additionalProperties"])

    def test_real_binding_validates(self):
        self.assertEqual(self._errors(self._binding()), [])

    def test_source_value_key_drift_rejected(self):
        b = copy.deepcopy(self._binding())
        b["sources"]["earnings"]["value_key"] = "event_8k_class"     # wrong source-to-field mapping
        self.assertTrue(self._errors(b))

    def test_source_provider_drift_rejected(self):
        b = copy.deepcopy(self._binding())
        b["sources"]["event_8k"]["provider_id"] = "fmp"             # 8-K is SEC, not FMP
        self.assertTrue(self._errors(b))

    def test_source_endpoint_drift_rejected(self):
        b = copy.deepcopy(self._binding())
        b["sources"]["earnings"]["endpoint_or_filing_type"] = "form_8k"
        self.assertTrue(self._errors(b))

    def test_extra_source_rejected(self):
        b = copy.deepcopy(self._binding())
        b["sources"]["surprise"] = dict(b["sources"]["earnings"])
        self.assertTrue(self._errors(b))                            # additionalProperties:false on sources

    def test_missing_source_rejected(self):
        b = copy.deepcopy(self._binding())
        del b["sources"]["semantic"]
        self.assertTrue(self._errors(b))

    def test_authorization_flip_rejected(self):
        for f, v in (("provider_calls_authorized", True), ("live_fetch_executed_by_this_artifact", True),
                     ("network_access_required", True), ("sr_provider_001_gated", False)):
            b = copy.deepcopy(self._binding())
            b["authorization_boundary"][f] = v
            self.assertTrue(self._errors(b), f)

    def test_provenance_required_fields_drift_rejected(self):
        b = copy.deepcopy(self._binding())
        b["provenance_required_fields"] = [x for x in b["provenance_required_fields"] if x != "lineage_ref"]
        self.assertTrue(self._errors(b))

    def test_coverage_or_parser_enum_drift_rejected(self):
        for key in ("coverage_status_allowed", "parser_status_allowed"):
            b = copy.deepcopy(self._binding())
            b[key] = b[key] + ["anything"]
            self.assertTrue(self._errors(b), key)

    def test_extra_top_key_rejected(self):
        b = copy.deepcopy(self._binding())
        b["surprise"] = True
        self.assertTrue(self._errors(b))

    def test_extra_source_artifact_ref_rejected(self):
        b = copy.deepcopy(self._binding())
        b["source_artifact_refs"].append(dict(b["source_artifact_refs"][0]))
        self.assertTrue(self._errors(b))                            # maxItems 3

    def test_forged_source_ref_rejected(self):
        b = copy.deepcopy(self._binding())
        b["source_artifact_refs"][1] = {"artifact_id": "fake", "path": "missing/not-real.md", "role": "trust me"}
        self.assertTrue(self._errors(b))                            # per-position const mismatch

    def test_duplicated_source_ref_rejected(self):
        b = copy.deepcopy(self._binding())
        b["source_artifact_refs"] = [copy.deepcopy(b["source_artifact_refs"][0]) for _ in range(3)]
        self.assertTrue(self._errors(b))                            # positions 1/2 no longer match their const

    def test_reordered_source_ref_rejected(self):
        b = copy.deepcopy(self._binding())
        b["source_artifact_refs"] = list(reversed(b["source_artifact_refs"]))
        self.assertTrue(self._errors(b))                            # tuple-position const

    def test_as_of_drift_rejected(self):
        for bad in ("20261399", "20260101", "2026-07-01"):
            b = copy.deepcopy(self._binding())
            b["as_of"] = bad
            self.assertTrue(self._errors(b), bad)                   # as_of is const-pinned to the frozen date

    def test_pit_clock_contract_drift_rejected(self):
        # the PIT clock contract (residual-2 A) is const-pinned so it can't silently drift to a weaker clock
        for key, bad in (("decision_timezone", "UTC"), ("decision_cutoff_et", "16:00"),
                         ("observed_at_format", "yyyymmdd"), ("as_of_format", "rfc3339")):
            b = copy.deepcopy(self._binding())
            b["pit_clock_contract"][key] = bad
            self.assertTrue(self._errors(b), key)

    def test_pit_clock_contract_extra_or_missing_rejected(self):
        b = copy.deepcopy(self._binding())
        b["pit_clock_contract"]["surprise"] = 1
        self.assertTrue(self._errors(b))                            # additionalProperties:false
        b2 = copy.deepcopy(self._binding())
        del b2["pit_clock_contract"]
        self.assertTrue(self._errors(b2))                           # required top-level field

    def test_machine_policy_drift_rejected(self):
        # residual-3 B: the PIT/emission/lineage POLICIES (not just vocab/text) are const-pinned, so a same-shaped
        # binding that contradicts the runtime policy fails the schema (§18.2 schema-first shared contract).
        for path, bad in (
            (("pit_clock_contract", "observed_at_cutoff_operator"), "at_or_before"),   # would re-admit 09:30
            (("pit_clock_contract", "observed_at_cutoff_reference"), "prior_close"),
            (("pit_clock_contract", "chronology_relation"), "any"),
            (("emission_fitness", "score_ready_coverage_status"), "partial"),          # would score partial as clean
            (("emission_fitness", "score_ready_parser_status"), "degraded"),
            (("emission_fitness", "all_other_states"), "scored"),
            (("lineage_ref_format", "structure"), "trust-me"),
            (("lineage_ref_format", "record_id_rule"), "anything"),
        ):
            b = copy.deepcopy(self._binding())
            node = b
            for k in path[:-1]:
                node = node[k]
            node[path[-1]] = bad
            self.assertTrue(self._errors(b), path)

    def test_chronology_order_drift_rejected(self):
        b = copy.deepcopy(self._binding())
        b["pit_clock_contract"]["chronology_order"] = ["as_of", "source_as_of", "observed_at", "event_date"]
        self.assertTrue(self._errors(b))                            # tuple-position const

    def test_emission_fitness_and_lineage_format_required_and_closed(self):
        for key in ("emission_fitness", "lineage_ref_format"):
            b = copy.deepcopy(self._binding())
            del b[key]
            self.assertTrue(self._errors(b), key)                   # required top-level field
        b2 = copy.deepcopy(self._binding())
        b2["emission_fitness"]["surprise"] = 1
        self.assertTrue(self._errors(b2))                           # additionalProperties:false


if __name__ == "__main__":
    unittest.main()
