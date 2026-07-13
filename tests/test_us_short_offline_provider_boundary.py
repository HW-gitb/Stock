from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_offline_provider_boundary as boundary  # noqa: E402
from engine import us_short_security_identity as identity  # noqa: E402


def security_identity() -> dict:
    return identity.record_security_identity(
        issuer_cik="320193",
        security_class="COMMON",
        current_ticker="AAPL",
        issuer_name="Example Issuer",
        primary_exchange="NASDAQ",
        observed_as_of="20260713",
        source_id="manual_seed",
        source_ref_sha256="a" * 64,
    )


class OfflineProviderBoundaryTest(unittest.TestCase):
    def test_yfinance_alarm_and_sec_entry_are_offline_by_default(self):
        self.assertNotIn("yfinance", sys.modules)
        result = boundary.build_offline_provider_boundary(security_identity())
        self.assertEqual(result["yfinance_smoke_alarm"]["status"], "not_executed_offline")
        self.assertFalse(result["yfinance_smoke_alarm"]["package_import_attempted"])
        self.assertEqual(result["yfinance_smoke_alarm"]["failure_disposition"], "ticker_scoped_freeze")
        self.assertFalse(result["sec_corporate_event_interface"]["fetch_invoked"])
        self.assertFalse(result["sec_corporate_event_interface"]["raw_payload_read"])
        self.assertEqual(result["sec_corporate_event_interface"]["parser_entry_status"], "awaits_separately_authorized_source_bound_payload")
        self.assertNotIn("yfinance", sys.modules)

    def test_sec_gateway_rejects_fetch_and_parser_entry_does_not_parse(self):
        record = security_identity()
        gateway = boundary.OfflineSecCorporateEventGateway()
        with self.assertRaises(boundary.OfflineProviderBoundaryError):
            gateway.fetch(boundary.build_sec_corporate_event_fetch_request(record))
        entry = boundary.parse_sec_corporate_event_payload(record)
        self.assertEqual(entry["parser_entry_status"], "awaits_separately_authorized_source_bound_payload")
        self.assertFalse(entry["raw_payload_read"])
        self.assertFalse(entry["corporate_event_semantics_confirmed"])

    def test_identity_tamper_is_rejected_before_any_provider_boundary_output(self):
        record = security_identity()
        record["current_ticker"] = "MSFT"
        with self.assertRaises(boundary.OfflineProviderBoundaryError):
            boundary.build_offline_provider_boundary(record)
