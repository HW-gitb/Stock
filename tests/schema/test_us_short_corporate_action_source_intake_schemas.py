from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402

from engine import us_short_sec_simple_corporate_action_parser as sec_parser  # noqa: E402
from engine import us_short_security_identity as identity  # noqa: E402
from engine import us_short_yfinance_corporate_action_alarm as yf_alarm  # noqa: E402


def security(ticker="OLD", cik="101830"):
    return identity.record_security_identity(
        issuer_cik=cik, security_class="COMMON", current_ticker=ticker, issuer_name=ticker,
        primary_exchange="NASDAQ", observed_as_of="20260713", source_id="manual_seed",
        source_ref_sha256="a" * 64,
    )


class CorporateActionSourceIntakeSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sec_schema = json.loads((ROOT / "schemas/us_short_sec_corporate_action_parse_candidate.schema.json").read_text(encoding="utf-8"))
        cls.yf_schema = json.loads((ROOT / "schemas/us_short_yfinance_corporate_action_alarm.schema.json").read_text(encoding="utf-8"))
        cls.request_schema = json.loads((ROOT / "schemas/us_short_sec_corporate_action_fetch_request.schema.json").read_text(encoding="utf-8"))
        Draft7Validator.check_schema(cls.sec_schema)
        Draft7Validator.check_schema(cls.yf_schema)
        Draft7Validator.check_schema(cls.request_schema)
        cls.sec_validator = Draft7Validator(cls.sec_schema)
        cls.yf_validator = Draft7Validator(cls.yf_schema)
        cls.request_validator = Draft7Validator(cls.request_schema)

    def test_sec_fetch_request_budget_and_no_auto_confirmation_are_const_pinned(self):
        request = {
            "schema_name": "us_short_sec_corporate_action_fetch_request", "schema_version": "1.0.0",
            "provider_id": "sec_edgar",
            "document_url": "https://www.sec.gov/Archives/edgar/data/101830/000010183026000001/old.htm",
            "issuer_cik": "0000101830", "form_type": "8-K",
            "accession_number": "0000101830-26-000001", "filed_date": "2026-07-10",
            "accepted_at": "2026-07-10T12:00:00Z", "max_provider_calls": 1,
            "raw_document_persist_allowed": False, "automatic_confirmation_allowed": False,
        }
        self.assertEqual(list(self.request_validator.iter_errors(request)), [])
        for field, value in (("max_provider_calls", 2), ("raw_document_persist_allowed", True),
                             ("automatic_confirmation_allowed", True)):
            bad = copy.deepcopy(request)
            bad[field] = value
            self.assertNotEqual(list(self.request_validator.iter_errors(bad)), [])

    def test_engine_outputs_validate(self):
        sec = sec_parser.parse_simple_sec_corporate_action(
            identity_record=security(),
            filing={
                "provider_id": "sec_edgar", "issuer_cik": "0000101830", "form_type": "8-K",
                "accession_number": "0000101830-26-000001", "filed_date": "2026-07-10",
                "accepted_at": "2026-07-10T12:00:00Z", "observed_at": "2026-07-10T12:05:00Z",
                "document_ref_sha256": "b" * 64,
                "document_text": "The merger became effective on July 10, 2026. Each share was converted into the right to receive $54.20 in cash.",
                "network_access_performed": False,
            },
        )
        yf = yf_alarm.evaluate_yfinance_daily_alarm(security("AAPL", "320193"), {
            "source_ticker": "AAPL", "returned_ticker": "AAPL", "expected_price_date": "2026-07-10",
            "observed_at": "2026-07-10T22:00:00Z", "fetch_status": "ok", "price_date": "2026-07-10",
            "close": 200.0, "stock_splits": 4.0, "dividends": 0.0, "network_access_performed": False,
        })
        self.assertEqual(list(self.sec_validator.iter_errors(sec)), [])
        self.assertEqual(list(self.yf_validator.iter_errors(yf)), [])

    def test_schemas_reject_false_authority_claims(self):
        sec = sec_parser.parse_simple_sec_corporate_action(
            identity_record=security(),
            filing={
                "provider_id": "sec_edgar", "issuer_cik": "0000101830", "form_type": "DEFM14A",
                "accession_number": "0000101830-26-000001", "filed_date": "2026-07-10",
                "accepted_at": "2026-07-10T12:00:00Z", "observed_at": "2026-07-10T12:05:00Z",
                "document_ref_sha256": "b" * 64, "document_text": "complex", "network_access_performed": False,
            },
        )
        for field in ("source_semantics_confirmed", "planner_event_emitted", "selection_or_ranking_changed"):
            bad = copy.deepcopy(sec)
            bad["boundary"][field] = True
            self.assertNotEqual(list(self.sec_validator.iter_errors(bad)), [])

        yf = yf_alarm.evaluate_yfinance_daily_alarm(security("AAPL", "320193"), {
            "source_ticker": "AAPL", "returned_ticker": None, "expected_price_date": "2026-07-10",
            "observed_at": "2026-07-10T22:00:00Z", "fetch_status": "empty", "price_date": None,
            "close": None, "stock_splits": None, "dividends": None, "network_access_performed": False,
        })
        for field in ("corporate_event_semantics_confirmed", "selection_use_allowed",
                      "provider_health_gate_use_allowed", "paper_performance_confirmation_allowed"):
            bad = copy.deepcopy(yf)
            bad["boundary"][field] = True
            self.assertNotEqual(list(self.yf_validator.iter_errors(bad)), [])


if __name__ == "__main__":
    unittest.main()
