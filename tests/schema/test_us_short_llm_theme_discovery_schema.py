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

SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery.schema.json"


def _artifact():
    return {
        "schema_name": "us_short_llm_theme_discovery",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-12T12:20:00+00:00",
        "input_sha256": "0" * 64,
        "decision_clock": {
            "expected_decision_date": "20260615",
            "cutoff_policy": "before_decision_open_et",
            "pit_enforced": True,
        },
        "discovery_contract": {
            "producer_kind": "llm_theme_discovery",
            "input_mode": "offline_local_input",
            "membership_status": "provisional_unvalidated",
            "market_confirmation_status": "not_run",
            "scoring_eligible": False,
            "top15_effect_enabled": False,
            "operation_advice_effect_enabled": False,
            "dynamic_seats_enabled": False,
            "theme_probe_enabled": False,
            "lifecycle_actions_enabled": False,
        },
        "source_refs": [{
            "source_id": "web:ai-storage",
            "source_type": "web",
            "observed_at": "2026-06-12T12:00:00+00:00",
        }],
        "themes": [{
            "theme_id": "ai_storage",
            "display_name": "AI storage",
            "summary": "Provisional theme.",
            "status": "provisional_discovered",
            "observed_at": "2026-06-12T12:05:00+00:00",
            "source_ref_ids": ["web:ai-storage"],
            "members": [{
                "ticker": "AAPL",
                "membership_status": "provisional_unvalidated",
                "source_ref_ids": ["web:ai-storage"],
            }],
            "cross_industry_validation_status": "not_run",
            "market_confirmation_status": "not_run",
        }],
    }


class LLMThemeDiscoverySchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.validator = Draft7Validator(cls.schema)

    def test_valid_artifact(self):
        self.assertEqual(list(self.validator.iter_errors(_artifact())), [])

    def test_scoring_and_effect_flags_are_const_false(self):
        for path in (
            ("discovery_contract", "scoring_eligible"),
            ("discovery_contract", "top15_effect_enabled"),
            ("discovery_contract", "operation_advice_effect_enabled"),
            ("discovery_contract", "dynamic_seats_enabled"),
            ("discovery_contract", "theme_probe_enabled"),
            ("discovery_contract", "lifecycle_actions_enabled"),
        ):
            bad = copy.deepcopy(_artifact())
            bad[path[0]][path[1]] = True
            self.assertTrue(list(self.validator.iter_errors(bad)), path)

    def test_status_and_confirmation_are_const_pinned(self):
        for path in (
            ("discovery_contract", "membership_status"),
            ("discovery_contract", "market_confirmation_status"),
            ("themes", 0, "status"),
            ("themes", 0, "cross_industry_validation_status"),
            ("themes", 0, "market_confirmation_status"),
            ("themes", 0, "members", 0, "membership_status"),
        ):
            bad = copy.deepcopy(_artifact())
            cursor = bad
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = "confirmed_active" if path[-1] != "membership_status" else "confirmed"
            self.assertTrue(list(self.validator.iter_errors(bad)), path)

    def test_unknown_fields_rejected(self):
        bad = copy.deepcopy(_artifact())
        bad["discovery_contract"]["theme_score"] = 5
        self.assertTrue(list(self.validator.iter_errors(bad)))


if __name__ == "__main__":
    unittest.main()
