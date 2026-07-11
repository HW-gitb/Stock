# -*- coding: utf-8 -*-
"""Schema-structure tests for us_short_machine_record_contract (design §10 + §11.1).

This contract pins the SHAPE of the batch-3 machine record (run-level + rows[] + each row's
field_records[] = the §10 10-key registry record). It deliberately does NOT re-enumerate the frozen
vocabularies (those are owned by us_short_field_registry_governance + us_short_action_table_contract and
enforced at runtime by engine/us_short_no_dangling_validator.py) — so these tests check STRUCTURE only:
required keys, types, additionalProperties tightness on the field_record, the disposition enum, and the
evidence_ref sub-shape. The §10 cross-field semantics are exercised in tests/test_us_short_no_dangling_validator.py.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = ROOT / "schemas" / "us_short_machine_record_contract.schema.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _field_record():
    return {
        "field_id": "theme_heat_score",
        "owner_module": "engine.us_short_theme_heat",
        "data_source": "FMP",
        "pit_basis": "prior_friday_close",
        "privacy_class": "public_universe",
        "current_landing_surface": "weekly_report.theme_section",
        "terminal_surface_target": "action_confidence",
        "operation_impact": "调信心",
        "evidence_ref_kind": "source_id",
        "lifecycle_item_id": 8,
        "field_class": "theme_opportunity_state",
        "disposition": "landed",
        "impact_target": "action_confidence",
        "claim_type": "赛道热度",
        "evidence_ref": {"kind": "source_id", "value": "theme:ai_complex", "as_of": "20260622"},
    }


def _record():
    return {
        "schema_name": "us_short_machine_record_contract",
        "schema_version": "1.0.0",
        "as_of": "20260622",
        "rows": [
            {
                "ticker": "AAPL",
                "row_source": "top15_candidate",
                "final_action": "持有",
                "action_rank": 8,
                "decision_trace": "theme strong",
                "field_records": [_field_record()],
            }
        ],
    }


class MachineRecordContractSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)

    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_valid_record_validates(self):
        jsonschema.validate(_record(), self.schema)

    def test_mixed_source_run_origin_is_exact_and_pairing_bound(self):
        record = _record()
        record["run_origin"] = {
            "run_mode": "mixed_source",
            "data_origin": "real_provider_plus_caller_template",
            "operational_use": "not_authorized",
        }
        jsonschema.validate(record, self.schema)
        record["run_origin"]["data_origin"] = "real_provider_pre_authoritative"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(record, self.schema)

    def _reject(self, mutate):
        bad = _record()
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_name_const(self):
        self._reject(lambda d: d.__setitem__("schema_name", "other"))

    def test_missing_run_level_required_key(self):
        for k in ("schema_name", "schema_version", "as_of", "rows"):
            self._reject(lambda d, key=k: d.pop(key))

    def test_run_level_additional_property_rejected(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))

    def test_rows_must_be_array(self):
        self._reject(lambda d: d.__setitem__("rows", "notarray"))

    def test_as_of_pattern(self):
        self._reject(lambda d: d.__setitem__("as_of", "2026-06-22"))

    def test_row_missing_required_key(self):
        for k in ("ticker", "row_source", "final_action", "field_records"):
            self._reject(lambda d, key=k: d["rows"][0].pop(key))

    def test_field_record_missing_registry_key_rejected(self):
        # every one of the 12 required field_record keys (10 registry + field_class + disposition)
        for k in ("field_id", "owner_module", "data_source", "pit_basis", "privacy_class",
                  "current_landing_surface", "terminal_surface_target", "operation_impact",
                  "evidence_ref_kind", "lifecycle_item_id", "field_class", "disposition"):
            self._reject(lambda d, key=k: d["rows"][0]["field_records"][0].pop(key))

    def test_field_record_additional_property_rejected(self):
        self._reject(lambda d: d["rows"][0]["field_records"][0].__setitem__("stray", 1))

    def test_disposition_enum_enforced(self):
        self._reject(lambda d: d["rows"][0]["field_records"][0].__setitem__("disposition", "weird"))

    def test_nullable_registry_fields_accept_null(self):
        # evidence_ref_kind / lifecycle_item_id / impact_target / claim_type / evidence_ref are nullable
        ok = _record()
        fr = ok["rows"][0]["field_records"][0]
        fr.update({"evidence_ref_kind": None, "lifecycle_item_id": None,
                   "impact_target": None, "claim_type": None, "evidence_ref": None})
        jsonschema.validate(ok, self.schema)

    def test_evidence_ref_bad_as_of_rejected(self):
        self._reject(lambda d: d["rows"][0]["field_records"][0]["evidence_ref"].__setitem__("as_of", "2026-06-22"))

    def test_evidence_ref_additional_property_rejected(self):
        self._reject(lambda d: d["rows"][0]["field_records"][0]["evidence_ref"].__setitem__("extra", 1))

    def test_as_of_is_structural_only_real_date_lives_in_validator(self):
        # documents the structural-vs-semantic split (R-USSHORT-BATCH3-PIT-EVIDENCE-TRACEBACK-GAP):
        # the schema regex is 8-digit STRUCTURAL only and accepts impossible calendar dates like 20260231;
        # real-date validity of the run-level/evidence as_of is enforced by engine/us_short_no_dangling_validator.py.
        ok = _record()
        ok["as_of"] = "20260231"  # impossible date, 8 digits → schema MUST still accept (structural-only)
        jsonschema.validate(ok, self.schema)
        ev = _record()
        ev["rows"][0]["field_records"][0]["evidence_ref"]["as_of"] = "20260231"
        jsonschema.validate(ev, self.schema)

    def test_required_keys_pin_validator_enforced_set(self):
        # the validator fails closed on these required keys; pin schema.required so validator-enforced ==
        # schema-required (R-USSHORT-BATCH3-MACHINE-RECORD-REQUIRED-FIELD-BYPASS — no validator/schema drift).
        reg = json.loads((ROOT / "presets" / "us_short_field_registry_governance_20260620.json").read_text(
            encoding="utf-8"))["registry_record_fields"]
        self.assertEqual(set(self.schema["definitions"]["row"]["required"]),
                         {"ticker", "row_source", "final_action", "field_records"})
        self.assertEqual(set(self.schema["definitions"]["field_record"]["required"]),
                         set(reg) | {"field_class", "disposition"})

    def test_provenance_phrases_in_design(self):
        text = DESIGN.read_text(encoding="utf-8")
        for phrase in ("机器层", "runs_private", "不悬空", "证据反查", "registry",
                       "operation_impact", "decision_trace", "landing_surface"):
            self.assertIn(phrase, text, f"machine-record provenance phrase missing from design: {phrase}")


if __name__ == "__main__":
    unittest.main()
