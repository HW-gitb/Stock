# -*- coding: utf-8 -*-
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_paper_eval_adjustment_evidence.schema.json"


def valid_packet():
    return {
        "schema_name": "us_short_paper_eval_adjustment_evidence",
        "schema_version": "1.0.0",
        "decision_date": "20260706",
        "source_refs": [
            {
                "id": "reviewed_local_price_packet",
                "path": "state/us_short/price_adjustment_evidence_20260706.json",
                "sha256": "a" * 64,
            }
        ],
        "adjustment_mode": {
            "status": "confirmed",
            "mode": "split_dividend_adjusted",
            "source_ref_ids": ["reviewed_local_price_packet"],
        },
        "split_handling": {
            "status": "events_reconciled",
            "source_ref_ids": ["reviewed_local_price_packet"],
            "event_refs": [
                {
                    "event_id": "AAPL-split-20200831",
                    "ticker": "AAPL",
                    "ex_date": "2020-08-31",
                    "source_ref_ids": ["reviewed_local_price_packet"],
                }
            ],
        },
        "dividend_handling": {
            "status": "no_events",
            "source_ref_ids": ["reviewed_local_price_packet"],
            "event_refs": [],
        },
        "ex_date_price_consistency": {
            "status": "consistent",
            "source_ref_ids": ["reviewed_local_price_packet"],
            "checked_event_ids": ["AAPL-split-20200831"],
        },
        "scope": {
            "offline_detection_only": True,
            "provider_call_performed": False,
            "corporate_action_reconciliation_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
    }


class UsShortPaperEvalAdjustmentEvidenceSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(cls.schema)
        cls.validator = Draft7Validator(cls.schema)

    def assert_valid(self, packet):
        errors = sorted(self.validator.iter_errors(packet), key=lambda e: list(e.path))
        self.assertEqual(errors, [], [e.message for e in errors])

    def assert_invalid(self, packet):
        errors = sorted(self.validator.iter_errors(packet), key=lambda e: list(e.path))
        self.assertNotEqual(errors, [])

    def test_valid_packet(self):
        self.assert_valid(valid_packet())

    def test_identity_and_scope_are_const_pinned(self):
        for path, value in [
            (("schema_name",), "other"),
            (("schema_version",), "2.0.0"),
            (("scope", "offline_detection_only"), False),
            (("scope", "provider_call_performed"), True),
            (("scope", "corporate_action_reconciliation_claimed"), True),
            (("scope", "ship_gate_or_production_authorized"), True),
        ]:
            packet = valid_packet()
            target = packet
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            self.assert_invalid(packet)

    def test_unknown_top_level_field_rejected(self):
        packet = valid_packet()
        packet["unreviewed_live_fetch"] = True
        self.assert_invalid(packet)

    def test_bad_status_and_mode_rejected(self):
        packet = valid_packet()
        packet["adjustment_mode"]["status"] = "trusted"
        self.assert_invalid(packet)
        packet = valid_packet()
        packet["adjustment_mode"]["mode"] = "raw_close"
        self.assert_invalid(packet)

    def test_source_ref_shape_rejected(self):
        packet = valid_packet()
        packet["source_refs"][0]["path"] = "https://example.com/raw.json"
        self.assert_invalid(packet)
        packet = valid_packet()
        packet["source_refs"][0]["sha256"] = "not-a-sha"
        self.assert_invalid(packet)

    def test_event_ref_requires_ticker_ex_date_and_source_refs(self):
        for field in ("ticker", "ex_date", "source_ref_ids"):
            packet = valid_packet()
            del packet["split_handling"]["event_refs"][0][field]
            self.assert_invalid(packet)

    def test_no_events_packet_valid_with_not_applicable_ex_date(self):
        packet = valid_packet()
        packet["split_handling"] = {
            "status": "no_events",
            "source_ref_ids": ["reviewed_local_price_packet"],
            "event_refs": [],
        }
        packet["ex_date_price_consistency"] = {
            "status": "not_applicable_no_events",
            "source_ref_ids": ["reviewed_local_price_packet"],
            "checked_event_ids": [],
        }
        self.assert_valid(packet)


if __name__ == "__main__":
    unittest.main()
