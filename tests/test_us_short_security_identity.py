from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_security_identity as identity  # noqa: E402


def build_identity(*, ticker: str = "AAPL", cik: str = "320193") -> dict:
    return identity.record_security_identity(
        issuer_cik=cik,
        security_class="COMMON",
        current_ticker=ticker,
        issuer_name="Example Issuer",
        primary_exchange="NASDAQ",
        observed_as_of="20260713",
        source_id="manual_seed",
        source_ref_sha256="a" * 64,
    )


class SecurityIdentityTest(unittest.TestCase):
    def test_stable_cik_class_identity_survives_ticker_change(self):
        before = build_identity(ticker="AAPL")
        after = build_identity(ticker="NEW", cik="0000320193")
        self.assertEqual(before["security_id"], "US-CIK-0000320193-COMMON")
        self.assertEqual(after["security_id"], before["security_id"])
        self.assertEqual(before["current_ticker"], "AAPL")
        self.assertEqual(after["current_ticker"], "NEW")
        self.assertFalse(before["boundary"]["provider_call_performed"])
        self.assertFalse(before["boundary"]["selection_or_ranking_changed"])

    def test_same_issuer_distinct_share_classes_do_not_collapse(self):
        common = build_identity()
        class_a = identity.record_security_identity(
            issuer_cik="320193",
            security_class="CLASS_A",
            current_ticker="AAPLA",
            issuer_name="Example Issuer",
            primary_exchange="NASDAQ",
            observed_as_of="20260713",
            source_id="manual_seed",
            source_ref_sha256="a" * 64,
        )
        self.assertEqual(common["issuer_cik"], class_a["issuer_cik"])
        self.assertNotEqual(common["security_id"], class_a["security_id"])
        self.assertEqual(class_a["security_id"], "US-CIK-0000320193-CLASS_A")

    def test_source_failure_freezes_only_bound_security_ticker(self):
        record = build_identity()
        freeze = identity.build_ticker_scoped_source_freeze(
            record,
            source_id="yfinance",
            failure_class="unavailable_or_malformed_response",
        )
        self.assertEqual(freeze["frozen_security_id"], record["security_id"])
        self.assertEqual(freeze["frozen_tickers"], ["AAPL"])
        self.assertTrue(freeze["manual_review_required"])
        self.assertFalse(freeze["global_run_blocked"])
        self.assertFalse(freeze["boundary"]["provider_retry_performed"])
        self.assertFalse(freeze["boundary"]["unrelated_symbols_frozen"])

    def test_bad_identity_or_tampered_record_is_rejected(self):
        with self.assertRaises(identity.SecurityIdentityError):
            build_identity(ticker="aapl")
        with self.assertRaises(identity.SecurityIdentityError):
            build_identity(cik="not-a-cik")
        with self.assertRaises(identity.SecurityIdentityError):
            identity.record_security_identity(
                issuer_cik=True,
                security_class="COMMON",
                current_ticker="AAPL",
                issuer_name="Example Issuer",
                primary_exchange="NASDAQ",
                observed_as_of="20260713",
                source_id="manual_seed",
                source_ref_sha256="a" * 64,
            )
        tampered = copy.deepcopy(build_identity())
        tampered["security_id"] = "US-CIK-0000000000-COMMON"
        with self.assertRaises(identity.SecurityIdentityError):
            identity.validate_security_identity(tampered)


if __name__ == "__main__":
    unittest.main()
