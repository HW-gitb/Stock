"""Tests for runners/us_short_universe_fetch.py (Massive + SEC free data path, no broker).

Offline-only: no live Massive/SEC/FMP calls. Covers the pure logic:
- SEC ticker/CIK/exchange parsing + exchange normalization
- SEC shares frames merge (latest per CIK across quarters)
- Massive grouped daily parsing (canonical ticker, close/volume, last-trading-day fallback)
- Pass1 join: market_cap = SEC shares × close; ADV = volume × close; FMP fallback precedence
- FMP market-cap fallback (budget cap, 429 stop)
- Authorization + gitignore + raw_root guards
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runners.us_short_universe_fetch as _mod

_GOV_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"


def _load_gov():
    from engine.us_short_eligibility_gate import load_eligibility_governance
    return load_eligibility_governance(_GOV_PATH)


class TestFetchSecTickers(unittest.TestCase):
    def _resp(self, rows):
        return {"fields": ["cik", "name", "ticker", "exchange"], "data": rows}

    def test_nyse_nasdaq_with_cik(self):
        resp = self._resp([[320193, "Apple", "AAPL", "Nasdaq"], [19617, "JPM", "JPM", "NYSE"]])
        with patch.object(_mod, "_sec_get", return_value=resp):
            out = _mod.fetch_sec_tickers("ua@test.com")
        self.assertEqual(out["AAPL"], {"cik": 320193, "exchange": "NASDAQ"})
        self.assertEqual(out["JPM"], {"cik": 19617, "exchange": "NYSE"})

    def test_non_whitelist_excluded(self):
        resp = self._resp([[1, "US", "AAPL", "NYSE"], [2, "LON", "VOD", "LSE"]])
        with patch.object(_mod, "_sec_get", return_value=resp):
            out = _mod.fetch_sec_tickers("ua@test.com")
        self.assertIn("AAPL", out)
        self.assertNotIn("VOD", out)

    def test_a_share_code_excluded(self):
        resp = self._resp([[9, "A", "000001.SZ", "NYSE"]])
        with patch.object(_mod, "_sec_get", return_value=resp):
            out = _mod.fetch_sec_tickers("ua@test.com")
        self.assertNotIn("000001.SZ", out)

    def test_missing_cik_field_raises(self):
        resp = {"fields": ["name", "ticker", "exchange"], "data": [["X", "AAPL", "NYSE"]]}
        with patch.object(_mod, "_sec_get", return_value=resp):
            with self.assertRaises(RuntimeError):
                _mod.fetch_sec_tickers("ua@test.com")


class TestFetchSecShares(unittest.TestCase):
    def test_latest_end_per_cik_wins(self):
        q1 = {"data": [{"cik": 1, "val": 100, "end": "2026-03-31"}]}
        q4 = {"data": [{"cik": 1, "val": 90, "end": "2025-12-31"}]}
        with patch.object(_mod, "_sec_get", side_effect=lambda url, ua: q1 if "CY2026Q1I" in url else q4):
            out = _mod.fetch_sec_shares("ua@test.com", frames=["CY2026Q1I", "CY2025Q4I"])
        self.assertEqual(out[1]["shares"], 100.0)

    def test_invalid_skipped(self):
        frame = {"data": [{"cik": 1, "val": 0, "end": "2026-03-31"},
                          {"cik": 2, "val": -5, "end": "2026-03-31"},
                          {"cik": 3, "val": 500, "end": "2026-03-31"}]}
        with patch.object(_mod, "_sec_get", return_value=frame):
            out = _mod.fetch_sec_shares("ua@test.com", frames=["CY2026Q1I"])
        self.assertNotIn(1, out)
        self.assertNotIn(2, out)
        self.assertEqual(out[3]["shares"], 500.0)


class TestFetchMassiveUniverse(unittest.TestCase):
    def test_parses_canonical_close_volume(self):
        results = [{"T": "AAPL", "c": 275.0, "v": 50000000},
                   {"T": "MSFT", "c": 350.0, "v": 20000000}]
        with patch.object(_mod, "_massive_grouped_for_date", return_value=results):
            used, data = _mod.fetch_massive_universe("k", as_of_date="2026-06-25")
        self.assertEqual(used, "2026-06-25")
        self.assertEqual(data["AAPL"], {"close": 275.0, "volume": 50000000.0})

    def test_skips_non_canonical_and_missing_close(self):
        results = [{"T": "000001.SZ", "c": 10, "v": 1},   # A-share code → skipped
                   {"T": "GOOD", "c": 5.0, "v": 100},
                   {"T": "NOCLOSE", "c": None, "v": 100}]  # no close → skipped
        with patch.object(_mod, "_massive_grouped_for_date", return_value=results):
            _, data = _mod.fetch_massive_universe("k", as_of_date="2026-06-25")
        self.assertIn("GOOD", data)
        self.assertNotIn("000001.SZ", data)
        self.assertNotIn("NOCLOSE", data)

    def test_steps_back_to_last_trading_day(self):
        # first date empty (holiday/weekend), second has data
        calls = {"n": 0}

        def fake(date, key):
            calls["n"] += 1
            return [] if calls["n"] == 1 else [{"T": "AAPL", "c": 275.0, "v": 1000}]

        with patch.object(_mod, "_massive_grouped_for_date", side_effect=fake):
            used, data = _mod.fetch_massive_universe("k", as_of_date=None, lookback=3)
        self.assertIn("AAPL", data)
        self.assertEqual(calls["n"], 2)

    def test_raises_when_all_empty(self):
        with patch.object(_mod, "_massive_grouped_for_date", return_value=[]):
            with self.assertRaises(RuntimeError):
                _mod.fetch_massive_universe("k", as_of_date=None, lookback=2)


class TestApplyPass1(unittest.TestCase):
    def setUp(self):
        self.gov = _load_gov()

    def test_eligible_when_all_pass(self):
        sec = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        md = {"AAPL": {"close": 200.0, "volume": 50_000_000}}
        out = _mod.apply_pass1(sec, shares, md, governance=self.gov)
        self.assertEqual(out["eligible_count"], 1)
        self.assertIn("AAPL", out["eligible_tickers"])

    def test_market_cap_below_floor(self):
        sec = {"S": {"cik": 5, "exchange": "NYSE"}}
        shares = {5: {"shares": 10_000_000, "end": "2026-03-31"}}
        md = {"S": {"close": 5.0, "volume": 50_000_000}}
        out = _mod.apply_pass1(sec, shares, md, governance=self.gov)
        self.assertEqual(out["eligible_count"], 0)
        self.assertIn("market_cap_usd_below_floor", out["reason_distribution"])

    def test_adv_below_floor(self):
        sec = {"T": {"cik": 3, "exchange": "NYSE"}}
        shares = {3: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        md = {"T": {"close": 10.0, "volume": 100}}
        out = _mod.apply_pass1(sec, shares, md, governance=self.gov)
        self.assertEqual(out["eligible_count"], 0)
        self.assertIn("adv_usd_below_floor", out["reason_distribution"])

    def test_needs_market_cap_when_only_missing_mktcap(self):
        sec = {"GOOGL": {"cik": 1652044, "exchange": "NASDAQ"}}
        md = {"GOOGL": {"close": 340.0, "volume": 20_000_000}}
        out = _mod.apply_pass1(sec, {}, md, governance=self.gov)
        self.assertIn("GOOGL", out["needs_market_cap"])
        self.assertEqual(out["eligible_count"], 0)

    def test_fmp_cap_rescues(self):
        sec = {"GOOGL": {"cik": 1652044, "exchange": "NASDAQ"}}
        md = {"GOOGL": {"close": 340.0, "volume": 20_000_000}}
        out = _mod.apply_pass1(sec, {}, md, governance=self.gov, fmp_caps={"GOOGL": 2e12})
        self.assertEqual(out["eligible_count"], 1)

    def test_sec_shares_precedence_over_fmp(self):
        sec = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        md = {"AAPL": {"close": 200.0, "volume": 50_000_000}}
        out = _mod.apply_pass1(sec, shares, md, governance=self.gov, fmp_caps={"AAPL": 1.0})
        self.assertEqual(out["eligible_count"], 1)  # SEC shares used, bogus FMP cap ignored

    def test_no_price_fails(self):
        sec = {"X": {"cik": 7, "exchange": "NYSE"}}
        shares = {7: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        md = {"X": {"close": None, "volume": None}}
        out = _mod.apply_pass1(sec, shares, md, governance=self.gov)
        self.assertEqual(out["eligible_count"], 0)
        self.assertEqual(out["no_price_count"], 1)


class TestFetchFmpMarketCaps(unittest.TestCase):
    class _Resp:
        def __init__(self, body): self._b = body
        def read(self): return self._b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def test_parses_market_cap(self):
        payload = json.dumps([{"symbol": "GOOGL", "marketCap": 2e12}]).encode()
        with patch("urllib.request.urlopen", return_value=self._Resp(payload)), \
             patch.object(_mod.time, "sleep"):
            out = _mod.fetch_fmp_market_caps(["GOOGL"], "key", budget=10)
        self.assertEqual(out["GOOGL"], 2e12)

    def test_budget_caps_calls(self):
        calls = {"n": 0}

        def fake(req, timeout=20):
            calls["n"] += 1
            return self._Resp(json.dumps([{"symbol": "X", "marketCap": 5e11}]).encode())

        with patch("urllib.request.urlopen", side_effect=fake), patch.object(_mod.time, "sleep"):
            _mod.fetch_fmp_market_caps([f"T{i}" for i in range(10)], "key", budget=3)
        self.assertEqual(calls["n"], 3)

    def test_429_stops(self):
        import urllib.error

        def fake(req, timeout=20):
            raise urllib.error.HTTPError(None, 429, "rate", {}, None)

        with patch("urllib.request.urlopen", side_effect=fake), patch.object(_mod.time, "sleep"):
            out = _mod.fetch_fmp_market_caps(["A", "B"], "key", budget=10)
        self.assertEqual(out, {})


class TestGuards(unittest.TestCase):
    def test_requires_authorization(self):
        with self.assertRaises(RuntimeError) as ctx:
            _mod.run_fetch(confirm_user_authorization=False, dry_run_env=False)
        self.assertIn("confirm-user-authorization", str(ctx.exception))

    def test_dry_run_env_no_auth(self):
        with patch.object(_mod, "_check_gitignore", return_value=True), \
             patch.object(_mod._sv, "validate_raw_root"):
            out = _mod.run_fetch(dry_run_env=True, confirm_user_authorization=False)
        self.assertEqual(out["scope"]["status"], "dry_run_env_only")

    def test_raw_root_escape_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "escaped"
            with patch.object(_mod, "_check_gitignore", return_value=True):
                with self.assertRaises((ValueError, RuntimeError)):
                    _mod.run_fetch(raw_root=bad, confirm_user_authorization=True)
            self.assertFalse(any(bad.rglob("*")))


if __name__ == "__main__":
    unittest.main()
