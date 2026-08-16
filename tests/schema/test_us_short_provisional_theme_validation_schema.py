from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_PATH = ROOT / "schemas" / "us_short_provisional_theme_validation.schema.json"


def _artifact():
    return {
        "schema_name": "us_short_provisional_theme_validation", "schema_version": "1.2.0", "generated_at": "2026-06-15T11:00:00+00:00",
        "decision_clock": {"expected_decision_date": "20260615", "candidate_price_basis_date": "20260612", "universe_used_date": "2026-06-12", "classification_source_as_of": "2026-06-15", "cutoff_policy": "before_decision_open_et", "pit_enforced": True},
        "validation_contract": {"producer_kind": "provisional_theme_validate", "input_mode": "offline_local_artifacts", "membership_status": "provisional_validated", "market_confirmation_status": "not_run", "scoring_eligible": False, "top15_effect_enabled": False, "operation_advice_effect_enabled": False, "dynamic_seats_enabled": False, "theme_probe_enabled": False, "lifecycle_actions_enabled": False},
        "input_artifacts": {"discovery_artifact_sha256": "a" * 64, "candidate_artifact_sha256": "b" * 64, "classification_packet_sha256": "c" * 64, "eligible_ticker_count": 4, "classification_ticker_count": 4},
        "source_ref_types": {"web:theme": "web", "x:theme": "x"},
        "themes": [{"theme_id": "theme_01", "display_name": "Theme", "summary": "Validated.", "status": "provisional_validated", "observed_at": "2026-06-12T12:10:00+00:00", "source_ref_ids": ["web:theme", "x:theme"], "cross_industry_validation_status": "validated_by_sec_sic_major_group", "market_confirmation_status": "not_run", "validation": {"selection_rank": 1, "qualified_member_count": 4, "industry_count": 2, "industry_codes": ["10", "20"], "source_type_counts": {"web": 3, "x": 3, "both": 2}}, "semantic_validation": {"status": "validated_shared_commercial_driver", "anchor_origin": {"origin_source_type": "web", "origin_scope_type": "web_chunk", "origin_scope_index": 0}, "passing_origins": [{"origin_source_type": "web", "origin_scope_type": "web_chunk", "origin_scope_index": 0, "linked_tickers": ["AAPL", "MSFT", "JPM"]}, {"origin_source_type": "x", "origin_scope_type": "x_response", "origin_scope_index": 0, "linked_tickers": ["AAPL", "JPM", "NVDA"]}], "semantically_linked_qualified_member_count": 4, "semantically_linked_sec_sic_industry_count": 2, "passing_source_ref_ids": ["web:theme", "x:theme"], "final_member_tickers": ["AAPL", "JPM", "MSFT", "NVDA"]}, "members": [{"ticker": ticker, "membership_status": "provisional_validated", "source_ref_ids": ["web:theme", "x:theme"], "source_types": (["web"] if ticker == "MSFT" else ["web", "x"] if ticker in {"AAPL", "JPM"} else ["x"]), "evidence_tier": ("single" if ticker in {"MSFT", "NVDA"} else "both"), "industry_code": code, "industry_source": "sec_sic_major_group"} for ticker, code in (("AAPL", "10"), ("MSFT", "10"), ("JPM", "20"), ("NVDA", "10"))]}],
        "drop_ledger": [], "summary": {"discovered_theme_count": 1, "validated_theme_count": 1, "validated_member_count": 4, "rejected_theme_count": 0, "dropped_member_count": 0, "truncated_theme_count": 0},
    }


class ProvisionalThemeValidationSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = Draft7Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_valid_artifact(self):
        self.assertEqual(list(self.validator.iter_errors(_artifact())), [])

    def test_all_effect_flags_are_const_false(self):
        for key in ("scoring_eligible", "top15_effect_enabled", "operation_advice_effect_enabled", "dynamic_seats_enabled", "theme_probe_enabled", "lifecycle_actions_enabled"):
            bad = copy.deepcopy(_artifact())
            bad["validation_contract"][key] = True
            self.assertTrue(list(self.validator.iter_errors(bad)), key)

    def test_unknown_fields_rejected(self):
        bad = copy.deepcopy(_artifact())
        bad["validation_contract"]["theme_score"] = 5
        self.assertTrue(list(self.validator.iter_errors(bad)))

    def test_non_cross_industry_status_rejected(self):
        bad = copy.deepcopy(_artifact())
        bad["themes"][0]["cross_industry_validation_status"] = "not_run"
        self.assertTrue(list(self.validator.iter_errors(bad)))

    def test_evidence_tier_must_match_source_types(self):
        bad = copy.deepcopy(_artifact())
        bad["themes"][0]["members"][0]["evidence_tier"] = "single"
        self.assertTrue(list(self.validator.iter_errors(bad)))

    def test_schema_reencodes_theme_count_and_industry_diversity_gates(self):
        bad = copy.deepcopy(_artifact())
        bad["themes"] = bad["themes"] * 9
        self.assertTrue(list(self.validator.iter_errors(bad)))
        bad = copy.deepcopy(_artifact())
        bad["themes"][0]["validation"]["industry_codes"] = ["10", "10"]
        self.assertTrue(list(self.validator.iter_errors(bad)))


if __name__ == "__main__":
    unittest.main()
