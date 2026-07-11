from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_vix_regime_fetch as vix  # noqa: E402


def _fetcher(payload, status, err=""):
    return lambda key: (payload, status, err)


class VixRegimeFetch(unittest.TestCase):
    def test_dry_run_env_performs_no_fetch(self):
        with mock.patch.dict(os.environ, {"FMP_API_KEY": "K"}, clear=False):
            r = vix.run_fetch(confirm_user_authorization=False, dry_run_env=True)
        self.assertEqual(r["scope"]["status"], "dry_run_env_only")
        self.assertTrue(r["fmp_key_present"])

    def test_missing_authorization_raises_before_fetch(self):
        with mock.patch.dict(os.environ, {"FMP_API_KEY": "K"}, clear=False):
            with self.assertRaises(vix.VixRegimeFetchError):
                vix.run_fetch(confirm_user_authorization=False,
                              quote_fetcher=_fetcher([{"symbol": "^VIX", "price": 16.9}], 200))

    def test_missing_key_raises(self):
        with mock.patch.dict(os.environ, {"FMP_API_KEY": ""}, clear=False):
            with self.assertRaises(vix.VixRegimeFetchError):
                vix.run_fetch(confirm_user_authorization=True,
                              quote_fetcher=_fetcher([{"symbol": "^VIX", "price": 16.9}], 200))

    def test_classifies_fetched_value_across_ladder(self):
        for val, regime in ((16.9, "进攻"), (20.0, "震荡"), (30.0, "防御"), (40.0, "极度防御")):
            with mock.patch.dict(os.environ, {"FMP_API_KEY": "K"}, clear=False):
                r = vix.run_fetch(confirm_user_authorization=True,
                                  quote_fetcher=_fetcher([{"symbol": "^VIX", "price": val}], 200))
            self.assertEqual(r["vix_value"], val)
            self.assertEqual(r["vix_regime"], regime)
            self.assertFalse(r["vix_regime_is_unknown"])

    def test_http_403_paywall_is_unknown_not_crash(self):
        with mock.patch.dict(os.environ, {"FMP_API_KEY": "K"}, clear=False):
            r = vix.run_fetch(confirm_user_authorization=True, quote_fetcher=_fetcher(None, 403, "http_error"))
        self.assertIsNone(r["vix_value"])
        self.assertEqual(r["vix_regime"], vix.UNKNOWN)
        self.assertTrue(r["vix_regime_is_unknown"])
        self.assertEqual(r["http_status"], 403)

    def test_malformed_payloads_are_unknown(self):
        with mock.patch.dict(os.environ, {"FMP_API_KEY": "K"}, clear=False):
            for bad in (None, [], [{"symbol": "^VIX"}], "nope", [{"symbol": "^VIX", "price": "x"}]):
                r = vix.run_fetch(confirm_user_authorization=True, quote_fetcher=_fetcher(bad, 200))
                self.assertEqual(r["vix_regime"], vix.UNKNOWN)

    def test_wrong_symbol_or_semantically_invalid_quote_is_unknown(self):
        bad_payloads = (
            [{"symbol": "SPY", "price": 16.9}],
            [{"symbol": "^VIX", "price": 0}],
            [{"symbol": "^VIX", "price": -1}],
            [{"symbol": "^VIX", "price": 16.9}, {"symbol": "^VIX", "price": 17.0}],
        )
        with mock.patch.dict(os.environ, {"FMP_API_KEY": "K"}, clear=False):
            for payload in bad_payloads:
                r = vix.run_fetch(confirm_user_authorization=True, quote_fetcher=_fetcher(payload, 200))
                self.assertIsNone(r["vix_value"])
                self.assertEqual(r["vix_regime"], vix.UNKNOWN)
                self.assertTrue(r["vix_regime_is_unknown"])

    def test_observation_time_is_recorded_and_supplied_time_is_preserved(self):
        with mock.patch.dict(os.environ, {"FMP_API_KEY": "K"}, clear=False):
            supplied = vix.run_fetch(
                confirm_user_authorization=True,
                quote_fetcher=_fetcher([{"symbol": "^VIX", "price": 16.9}], 200),
                generated_at="2026-07-11T00:00:00+00:00",
            )
            defaulted = vix.run_fetch(
                confirm_user_authorization=True,
                quote_fetcher=_fetcher([{"symbol": "^VIX", "price": 16.9}], 200),
            )
        self.assertEqual(supplied["observed_at"], "2026-07-11T00:00:00+00:00")
        self.assertEqual(supplied["generated_at"], supplied["observed_at"])
        self.assertIsInstance(defaulted["observed_at"], str)
        self.assertTrue(defaulted["observed_at"])

    def test_written_summary_has_no_secret_or_url(self):
        with mock.patch.dict(os.environ, {"FMP_API_KEY": "SECRET_FMP_ZZZ"}, clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "vix_summary.json"
                vix.run_fetch(confirm_user_authorization=True,
                              quote_fetcher=_fetcher([{"symbol": "^VIX", "price": 16.9}], 200), summary_path=p)
                text = p.read_text(encoding="utf-8")
        self.assertNotIn("SECRET_FMP_ZZZ", text)
        self.assertNotIn("financialmodelingprep.com", text)
        self.assertNotIn("apikey=", text)
        self.assertIn("进攻", text)   # the regime IS recorded

    def test_writer_refuses_if_summary_would_leak_secret(self):
        with self.assertRaises(vix.VixRegimeFetchError):
            vix._write_summary_safe({"leak": "SECRET_FMP_ZZZ"},
                                    Path(tempfile.gettempdir()) / "vix_leak.json", "SECRET_FMP_ZZZ")


if __name__ == "__main__":
    unittest.main()
