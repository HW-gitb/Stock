from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_sec_simple_corporate_action_parser as parser  # noqa: E402
from engine import us_short_security_identity as identity  # noqa: E402


def security(ticker: str, cik: str) -> dict:
    return identity.record_security_identity(
        issuer_cik=cik,
        security_class="COMMON",
        current_ticker=ticker,
        issuer_name=f"{ticker} issuer",
        primary_exchange="NASDAQ",
        observed_as_of="20260713",
        source_id="manual_seed",
        source_ref_sha256="a" * 64,
    )


def filing(text: str, *, cik: str = "0000101830", form: str = "8-K") -> dict:
    return {
        "provider_id": "sec_edgar",
        "issuer_cik": cik,
        "form_type": form,
        "accession_number": "0000101830-26-000001",
        "filed_date": "2026-07-10",
        "accepted_at": "2026-07-10T12:00:00Z",
        "observed_at": "2026-07-10T12:05:00Z",
        "document_ref_sha256": "b" * 64,
        "document_text": text,
        "network_access_performed": False,
    }


class SecSimpleCorporateActionParserTests(unittest.TestCase):
    def setUp(self):
        self.old = security("OLD", "101830")
        self.new = security("NEW", "1283699")

    def test_extracts_exact_cash_terms_as_unconfirmed_candidate(self):
        result = parser.parse_simple_sec_corporate_action(
            identity_record=self.old,
            filing=filing(
                "The merger became effective on July 10, 2026. "
                "Each share was converted into the right to receive $54.20 in cash."
            ),
        )
        self.assertEqual(result["parse_status"], "candidate_terms_extracted")
        self.assertEqual(result["event_candidate"]["event_type"], "cash_consideration")
        self.assertEqual(result["event_candidate"]["cash_per_share_cents"], 5420)
        self.assertEqual(result["event_candidate"]["effective_date"], "20260710")
        self.assertTrue(result["human_confirmation_required"])
        self.assertFalse(result["boundary"]["source_semantics_confirmed"])
        self.assertNotIn("document_text", str(result))

    def test_extracts_exact_stock_and_cash_with_identity_bound_successor(self):
        result = parser.parse_simple_sec_corporate_action(
            identity_record=self.old,
            successor_identity_record=self.new,
            filing=filing(
                "The merger became effective on July 10, 2026. Each share was converted into the right "
                "to receive 0.10256 shares of the successor. The successor's ticker symbol is \"NEW\". "
                "Each share was also converted into the right to receive $5.00 in cash."
            ),
        )
        event = result["event_candidate"]
        self.assertEqual(event["event_type"], "stock_and_cash_consideration")
        self.assertEqual(event["successor_ticker"], "NEW")
        self.assertEqual((event["exchange_ratio_numerator"], event["exchange_ratio_denominator"]), (641, 6250))
        self.assertEqual(event["cash_per_share_cents"], 500)

    def test_complex_or_ambiguous_terms_freeze_instead_of_guessing(self):
        cases = (
            "Each share receives $10.00 in cash and one contingent value right. Effective on July 10, 2026.",
            "Each share receives 0.5 shares, subject to adjustment. Effective on July 10, 2026.",
            "Each share may elect cash or stock. Effective on July 10, 2026.",
        )
        for text in cases:
            with self.subTest(text=text):
                result = parser.parse_simple_sec_corporate_action(
                    identity_record=self.old,
                    successor_identity_record=self.new,
                    filing=filing(text),
                )
                self.assertEqual(result["parse_status"], "manual_review")
                self.assertIsNone(result["event_candidate"])
                self.assertTrue(result["ticker_scoped_freeze_required"])

    def test_defm14a_and_unbound_source_cik_cannot_auto_extract(self):
        result = parser.parse_simple_sec_corporate_action(
            identity_record=self.old,
            filing=filing("Effective on July 10, 2026. Each share receives $54.20 in cash.", form="DEFM14A"),
        )
        self.assertEqual(result["parse_status"], "manual_review")
        bad = filing("Effective on July 10, 2026. Each share receives $54.20 in cash.", cik="0001418091")
        with self.assertRaises(parser.SecCorporateActionParserError):
            parser.parse_simple_sec_corporate_action(identity_record=self.old, filing=bad)

    def test_multiple_values_and_future_observation_are_rejected_or_frozen(self):
        ambiguous = parser.parse_simple_sec_corporate_action(
            identity_record=self.old,
            filing=filing(
                "Effective on July 10, 2026. Each share was converted into the right to receive $54.20 in cash. "
                "Each share was also converted into the right to receive $10.00 in cash."
            ),
        )
        self.assertEqual(ambiguous["parse_status"], "manual_review")
        bad = filing("Effective on July 10, 2026. Each share receives $54.20 in cash.")
        bad["observed_at"] = "2026-07-10T11:59:59Z"
        with self.assertRaises(parser.SecCorporateActionParserError):
            parser.parse_simple_sec_corporate_action(identity_record=self.old, filing=bad)

    def test_input_is_not_mutated(self):
        item = filing("Effective on July 10, 2026. Each share was converted into the right to receive $54.20 in cash.")
        before = copy.deepcopy(item)
        parser.parse_simple_sec_corporate_action(identity_record=self.old, filing=item)
        self.assertEqual(item, before)

    def test_successor_filed_8k_is_allowed_only_when_identity_bound(self):
        result = parser.parse_simple_sec_corporate_action(
            identity_record=self.old,
            successor_identity_record=self.new,
            filing=filing(
                "The merger became effective on July 10, 2026. Each share was converted into the right "
                "to receive 0.5 shares of the successor. The successor ticker symbol is NEW.",
                cik="0001283699",
            ),
        )
        self.assertEqual(result["parse_status"], "candidate_terms_extracted")
        self.assertEqual(result["event_candidate"]["successor_ticker"], "NEW")


if __name__ == "__main__":
    unittest.main()
