from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_corporate_action_coverage.schema.json"


def _packet():
    empty_sha = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e18ef1b6f5f1f3f8f42f0d7"
    family = {
        "status": "complete", "date_field": "execution_date", "pages_fetched": 1,
        "pagination_exhausted": True, "result_count": 0, "result_sha256": empty_sha,
        "raw_page_sha256": ["a" * 64], "events": [], "failure_reason": None,
    }
    return {
        "schema_name": "us_short_forward_policy_corporate_action_coverage", "schema_version": "1.0.0",
        "authorization_ref": "user_chat_20260718_us_short_a1_zero_event_certificate", "generated_at": "x",
        "maturity_as_of": "20260810", "maturity_ohlcv_sha256": "b" * 64,
        "query_window": {"from": "2026-07-20", "to": "2026-08-08"},
        "capture_bindings": [{"decision_date": "20260720", "common_selection_pool_sha256": "c" * 64,
                              "window_start": "2026-07-20", "h20_session_date": "2026-08-08"}],
        "families": {"splits": family, "dividends": {**family, "date_field": "ex_dividend_date"}},
        "boundary": {"track": "comparison_non_production", "provider_id": "massive",
                     "plan": "stocks_basic_free", "spend_usd": 0, "market_wide_queries_only": True,
                     "event_week_reconciliation_performed": False, "ship_gate_or_production_authorized": False,
                     "broker_or_order_automation_allowed": False},
    }


class CorporateActionCoverageSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(cls.schema)
        cls.validator = Draft7Validator(cls.schema)

    def test_accepts_exact_complete_empty_coverage(self):
        self.assertEqual(list(self.validator.iter_errors(_packet())), [])

    def test_rejects_authorization_page_limit_and_closed_world_drift(self):
        for mutation in ("authorization", "pages", "extra"):
            packet = copy.deepcopy(_packet())
            if mutation == "authorization":
                packet["authorization_ref"] = "caller_claim"
            elif mutation == "pages":
                packet["families"]["splits"]["pages_fetched"] = 3
            else:
                packet["ticker"] = "AAPL"
            with self.subTest(mutation=mutation):
                self.assertTrue(list(self.validator.iter_errors(packet)))


if __name__ == "__main__":
    unittest.main()
