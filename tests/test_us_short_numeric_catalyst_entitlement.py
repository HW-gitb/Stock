import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_catalyst import load_catalyst_governance  # noqa: E402
from engine.us_short_numeric_catalyst_entitlement import (  # noqa: E402
    NumericCatalystEntitlementError,
    resolve_numeric_catalyst_with_entitlement,
)


AS_OF = "20260630"
OBSERVED_AT = "2026-06-30T08:00:00-04:00"


def _packet(http_status, rows):
    return {
        "http_status": http_status,
        "source_as_of": AS_OF,
        "rows": rows,
    }


class NumericCatalystEntitlementTest(unittest.TestCase):
    def setUp(self):
        self.gov = load_catalyst_governance()

    def test_not_entitled_probe_skips_per_symbol_fetch_and_projects_neutral(self):
        result = resolve_numeric_catalyst_with_entitlement(
            as_of=AS_OF,
            observed_at=OBSERVED_AT,
            endpoint_packets={
                "earnings_surprises": _packet(404, "ignored because not entitled"),
                "analyst_estimate_revisions": _packet(400, {"AAPL": "ignored"}),
            },
            target_tickers=["AAPL", "MSFT"],
            governance=self.gov,
        )

        self.assertEqual(result["source_result"], {"signals": {}, "provenance": {}, "excluded": {}})
        self.assertEqual(result["projection"]["catalyst_block_by_ticker"], {})
        self.assertEqual(result["projection"]["neutral_fill_tickers"], ["AAPL", "MSFT"])
        self.assertEqual(result["entitlement"]["earnings_surprises"]["status"], "not_entitled")
        self.assertFalse(result["entitlement"]["earnings_surprises"]["per_symbol_fetch_allowed"])
        self.assertTrue(result["entitlement"]["earnings_surprises"]["skipped_per_symbol_fetch"])
        self.assertEqual(result["entitlement"]["analyst_estimate_revisions"]["status"], "not_entitled")

    def test_entitled_normalized_rows_feed_source_resolver_and_catalyst_block(self):
        result = resolve_numeric_catalyst_with_entitlement(
            as_of=AS_OF,
            observed_at=OBSERVED_AT,
            endpoint_packets={
                "earnings_surprises": _packet(
                    200,
                    [
                        {
                            "ticker": "aapl",
                            "earnings_surprise_pct": 15.0,
                            "earnings_report_date": "20260625",
                            "record_id": "earn-aapl-1",
                        }
                    ],
                ),
                "analyst_estimate_revisions": _packet(
                    200,
                    [
                        {
                            "ticker": "AAPL",
                            "analyst_revision_net": 4,
                            "analyst_revision_date": "20260624",
                            "record_id": "rev-aapl-1",
                        }
                    ],
                ),
            },
            target_tickers=["AAPL", "MSFT"],
            governance=self.gov,
        )

        self.assertIn("AAPL", result["source_result"]["signals"])
        self.assertIn("earnings_surprise_pct", result["source_result"]["signals"]["AAPL"])
        self.assertIn("analyst_revision_net", result["source_result"]["signals"]["AAPL"])
        self.assertGreater(result["projection"]["catalyst_block_by_ticker"]["AAPL"], self.gov["neutral_catalyst_score"])
        self.assertEqual(result["projection"]["neutral_fill_tickers"], ["MSFT"])
        self.assertEqual(result["entitlement"]["earnings_surprises"]["status"], "entitled")
        self.assertTrue(result["entitlement"]["earnings_surprises"]["per_symbol_fetch_allowed"])

    def test_malformed_200_payload_falls_back_to_neutral_without_raw_exception(self):
        result = resolve_numeric_catalyst_with_entitlement(
            as_of=AS_OF,
            observed_at=OBSERVED_AT,
            endpoint_packets={
                "earnings_surprises": _packet(200, [{"ticker": "AAPL", "record_id": "missing-value"}]),
                "analyst_estimate_revisions": _packet(404, []),
            },
            target_tickers=["AAPL"],
            governance=self.gov,
        )

        self.assertEqual(result["source_result"], {"signals": {}, "provenance": {}, "excluded": {}})
        self.assertEqual(result["projection"]["neutral_fill_tickers"], ["AAPL"])
        self.assertEqual(result["entitlement"]["earnings_surprises"]["status"], "malformed_200_neutral_fallback")

    def test_malformed_200_numeric_value_falls_back_to_neutral(self):
        result = resolve_numeric_catalyst_with_entitlement(
            as_of=AS_OF,
            observed_at=OBSERVED_AT,
            endpoint_packets={
                "earnings_surprises": _packet(
                    200,
                    [
                        {
                            "ticker": "AAPL",
                            "earnings_surprise_pct": "15.0",
                            "earnings_report_date": "20260625",
                            "record_id": "earn-aapl-1",
                        }
                    ],
                ),
                "analyst_estimate_revisions": _packet(404, []),
            },
            target_tickers=["AAPL"],
            governance=self.gov,
        )

        self.assertEqual(result["source_result"], {"signals": {}, "provenance": {}, "excluded": {}})
        self.assertEqual(result["projection"]["neutral_fill_tickers"], ["AAPL"])
        self.assertEqual(result["entitlement"]["earnings_surprises"]["status"], "malformed_200_neutral_fallback")

    def test_bad_endpoint_packet_shape_raises_typed_error(self):
        with self.assertRaises(NumericCatalystEntitlementError):
            resolve_numeric_catalyst_with_entitlement(
                as_of=AS_OF,
                observed_at=OBSERVED_AT,
                endpoint_packets={"earnings_surprises": []},
                target_tickers=["AAPL"],
                governance=self.gov,
            )


if __name__ == "__main__":
    unittest.main()
