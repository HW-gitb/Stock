"""Tests for runners/us_short_universe_fetch.py (Massive + SEC free data path, no broker).

Offline-only: no live Massive/SEC/FMP calls. Covers the pure logic:
- SEC ticker/CIK/exchange parsing + exchange normalization
- SEC shares frames merge (latest per CIK across quarters)
- Massive grouped daily ADV WINDOW parsing (canonical ticker, multi-day average dollar volume,
  delayed-day skip, min-coverage conservative null)
- Pass1 per-row records: market_cap = SEC shares × close; ADV = multi-day average; FMP fallback precedence
- ADV semantics: a single-day spike must NOT pass the (multi-day) ADV floor
- summary recomputed from rows; per-run artifact schema + semantic validate-before-write
- canonical decision_date binds the output path
- FMP market-cap fallback (budget cap, 429 stop); authorization / gitignore / raw_root / now-et guards
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runners.us_short_universe_fetch as _mod

_GOV_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
_CAL_PATH = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"


def _load_gov():
    from engine.us_short_eligibility_gate import load_eligibility_governance
    return load_eligibility_governance(_GOV_PATH)


def _load_cal():
    from engine.us_short_market_calendar import load_market_calendar
    return load_market_calendar(_CAL_PATH)


def _md(close, adv_usd, *, volume=None, adv_days=20, price_as_of="2026-06-26"):
    """A market_data entry as fetch_massive_window now produces it (multi-day ADV precomputed)."""
    return {"close": close, "volume": volume, "adv_usd": adv_usd,
            "adv_days_observed": adv_days, "price_as_of": price_as_of}


STATUS_AS_OF = "2026-06-29"
STATUS_OBSERVED_AT = "2026-06-29T12:00:00+00:00"
_DEFAULT_STATUS_PAYLOAD = object()


def _status_ref(ticker="AAPL", *, exchange="NASDAQ", observed_at=STATUS_OBSERVED_AT):
    return {"observed": True, "observed_at": observed_at, "coverage": "full",
            "active_listings": {ticker: {"active": True, "primary_exchange": exchange}}}


def _status_halt(symbols=(), *, observed_at=STATUS_OBSERVED_AT):
    return {"observed": True, "observed_at": observed_at, "halted_symbols": list(symbols)}


def _status_bank(ticker="AAPL", *, screen_status="screened_no_filing", observed_at=STATUS_OBSERVED_AT):
    return {"observed": True, "observed_at": observed_at, "lookback_window": "P90D",
            "by_ticker": {ticker: {"screen_status": screen_status}}}


def _sec_submissions(*, forms, filing_dates, accessions, items):
    return {"filings": {"recent": {
        "form": list(forms),
        "filingDate": list(filing_dates),
        "accessionNumber": list(accessions),
        "items": list(items),
    }}}


def _status_record(ticker="AAPL", *, exchange="NASDAQ", ticker_reference=_DEFAULT_STATUS_PAYLOAD,
                   halt_feed=_DEFAULT_STATUS_PAYLOAD, bankruptcy_screen=_DEFAULT_STATUS_PAYLOAD):
    from engine import us_short_status_source as ss
    return ss.resolve_status_record(
        ticker, as_of=STATUS_AS_OF, observed_at=STATUS_OBSERVED_AT,
        ticker_reference=(
            _status_ref(ticker, exchange=exchange)
            if ticker_reference is _DEFAULT_STATUS_PAYLOAD else ticker_reference),
        halt_feed=_status_halt() if halt_feed is _DEFAULT_STATUS_PAYLOAD else halt_feed,
        bankruptcy_screen=(
            _status_bank(ticker)
            if bankruptcy_screen is _DEFAULT_STATUS_PAYLOAD else bankruptcy_screen),
    )


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

    def test_all_frames_failed_raises(self):
        # F2 (cc_r1_v1): every frame failing (SEC down) → fail closed, NOT a silent empty map.
        with patch.object(_mod, "_sec_get", side_effect=RuntimeError("SEC down")):
            with self.assertRaises(RuntimeError):
                _mod.fetch_sec_shares("ua@test.com", frames=["CY2026Q1I", "CY2025Q4I"])

    def test_partial_frame_failure_tolerated(self):
        # F2: a SINGLE failed frame is tolerated (other quarters still merge the latest shares per CIK).
        good = {"data": [{"cik": 7, "val": 800, "end": "2026-03-31"}]}

        def se(url, ua):
            if "CY2026Q1I" in url:
                raise RuntimeError("one frame down")
            return good
        with patch.object(_mod, "_sec_get", side_effect=se):
            out = _mod.fetch_sec_shares("ua@test.com", frames=["CY2026Q1I", "CY2025Q4I"])
        self.assertEqual(out[7]["shares"], 800.0)


class TestAdvWindowSessionDates(unittest.TestCase):
    def test_last_n_sessions_newest_first_iso(self):
        cal = _load_cal()
        out = _mod.adv_window_session_dates("20260626", cal, count=5)
        self.assertEqual(out[0], "2026-06-26")             # newest first
        self.assertEqual(len(out), 5)
        self.assertTrue(all(d <= "2026-06-26" for d in out))
        # strictly descending unique ISO trading days (no weekends/holidays)
        self.assertEqual(out, sorted(out, reverse=True))
        self.assertEqual(len(set(out)), len(out))
        self.assertNotIn("2026-06-19", out)                # Juneteenth holiday excluded


class TestFetchMassiveWindow(unittest.TestCase):
    def setUp(self):
        self._sleep_patch = patch.object(_mod.time, "sleep")
        self.sleep_mock = self._sleep_patch.start()
        self.addCleanup(self._sleep_patch.stop)

    def test_collects_window_and_averages_adv(self):
        # 20 days of constant $6M/day dollar volume → adv_usd == 6M, used_date == newest
        dates = [f"2026-06-{d:02d}" for d in range(26, 6, -1)]   # newest-first, 20 entries

        def fake(date, key):
            return [{"T": "AAPL", "c": 10.0, "v": 600_000}]

        with patch.object(_mod, "_massive_grouped_for_date", side_effect=fake):
            used, observed, md = _mod.fetch_massive_window("k", dates, window=20, min_days=10)
        self.assertEqual(used, "2026-06-26")
        self.assertEqual(len(observed), 20)
        self.assertEqual(md["AAPL"]["adv_usd"], 6_000_000.0)
        self.assertEqual(md["AAPL"]["adv_days_observed"], 20)
        self.assertEqual(md["AAPL"]["close"], 10.0)
        self.assertEqual(md["AAPL"]["price_as_of"], "2026-06-26")

    def test_skips_empty_delayed_days(self):
        # Massive has not published the two newest days yet (empty) → used_date steps back, still 20 days
        dates = [f"2026-06-{d:02d}" for d in range(28, 0, -1)]

        def fake(date, key):
            return [] if date in ("2026-06-28", "2026-06-27") else [{"T": "AAPL", "c": 10.0, "v": 600_000}]

        with patch.object(_mod, "_massive_grouped_for_date", side_effect=fake):
            used, observed, md = _mod.fetch_massive_window("k", dates, window=20, min_days=10)
        self.assertEqual(used, "2026-06-26")               # newest day WITH data
        self.assertNotIn("2026-06-27", observed)
        self.assertEqual(len(observed), 20)

    def test_raises_below_min_days(self):
        dates = [f"2026-06-{d:02d}" for d in range(26, 20, -1)]   # only a handful have data

        def fake(date, key):
            return [{"T": "AAPL", "c": 10.0, "v": 600_000}] if date in dates[:3] else []

        with patch.object(_mod, "_massive_grouped_for_date", side_effect=fake):
            with self.assertRaises(RuntimeError):
                _mod.fetch_massive_window("k", dates, window=20, min_days=10)

    def test_auth_error_raises_not_skipped(self):
        import urllib.error

        def fake(date, key):
            raise urllib.error.HTTPError(None, 401, "unauth", {}, None)

        with patch.object(_mod, "_massive_grouped_for_date", side_effect=fake):
            with self.assertRaises(RuntimeError) as ctx:
                _mod.fetch_massive_window("k", ["2026-06-26", "2026-06-25"], window=20, min_days=1)
        self.assertIn("401", str(ctx.exception))

    def test_rate_limit_429_retried_instead_of_failing(self):
        import urllib.error

        calls = []

        def fake(date, key):
            calls.append(date)
            if len(calls) == 1:
                raise urllib.error.HTTPError(None, 429, "rate", {}, None)
            return [{"T": "AAPL", "c": 10.0, "v": 600_000}]

        with patch.object(_mod, "_massive_grouped_for_date", side_effect=fake):
            used, observed, md = _mod.fetch_massive_window("k", ["2026-06-26"], window=1, min_days=1)

        self.assertEqual(calls, ["2026-06-26", "2026-06-26"])
        self.assertEqual(used, "2026-06-26")
        self.assertEqual(observed, ["2026-06-26"])
        self.assertIn("AAPL", md)
        self.sleep_mock.assert_called_with(_mod.MASSIVE_RATE_LIMIT_RETRY_SECONDS)

    def test_massive_window_paces_between_grouped_daily_calls(self):
        dates = ["2026-06-26", "2026-06-25", "2026-06-24"]

        def fake(date, key):
            return [{"T": "AAPL", "c": 10.0, "v": 600_000}]

        with patch.object(_mod, "_massive_grouped_for_date", side_effect=fake):
            _mod.fetch_massive_window("k", dates, window=3, min_days=1)

        self.assertEqual(
            [call.args[0] for call in self.sleep_mock.call_args_list],
            [_mod.MASSIVE_GROUPED_REQUEST_INTERVAL_SECONDS,
             _mod.MASSIVE_GROUPED_REQUEST_INTERVAL_SECONDS],
        )

    def test_adv_insufficient_coverage_null(self):
        # ticker only trades on 4 of the collected days (< min 10) → adv_usd is None (conservative)
        dates = [f"2026-06-{d:02d}" for d in range(26, 6, -1)]

        def fake(date, key):
            rows = [{"T": "BIG", "c": 10.0, "v": 600_000}]
            if date in dates[:4]:
                rows.append({"T": "THIN", "c": 10.0, "v": 600_000})
            return rows

        with patch.object(_mod, "_massive_grouped_for_date", side_effect=fake):
            _, _, md = _mod.fetch_massive_window("k", dates, window=20, min_days=10)
        self.assertIsNone(md["THIN"]["adv_usd"])
        self.assertEqual(md["THIN"]["adv_days_observed"], 4)
        self.assertEqual(md["BIG"]["adv_usd"], 6_000_000.0)

    def test_skips_non_canonical_and_missing_close(self):
        def fake(date, key):
            return [{"T": "000001.SZ", "c": 10, "v": 1},      # A-share code → skipped (non-canonical)
                    {"T": "GOOD", "c": 5.0, "v": 100},
                    {"T": "NOCLS", "c": None, "v": 100}]       # no close → entry kept, price unusable

        with patch.object(_mod, "_massive_grouped_for_date", side_effect=fake):
            _, _, md = _mod.fetch_massive_window("k", ["2026-06-26"], window=20, min_days=1)
        self.assertIn("GOOD", md)
        self.assertNotIn("000001.SZ", md)
        self.assertIsNone(md["NOCLS"]["close"])              # present but no usable price


class TestApplyPass1(unittest.TestCase):
    def setUp(self):
        self.gov = _load_gov()

    def _rows(self, sec, shares, md, **kw):
        return _mod.apply_pass1(sec, shares, md, governance=self.gov,
                                as_of="2026-06-26", observed_at="2026-06-29T12:00:00+00:00", **kw)

    def test_eligible_when_all_pass(self):
        sec = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        rows = self._rows(sec, shares, {"AAPL": _md(200.0, 50_000_000.0)})
        self.assertEqual(_mod.eligible_tickers_from_rows(rows), ["AAPL"])
        self.assertTrue(rows[0]["eligible"])
        self.assertEqual(rows[0]["reasons"], [])

    def test_market_cap_below_floor(self):
        sec = {"S": {"cik": 5, "exchange": "NYSE"}}
        shares = {5: {"shares": 10_000_000, "end": "2026-03-31"}}
        rows = self._rows(sec, shares, {"S": _md(5.0, 50_000_000.0)})
        self.assertFalse(rows[0]["eligible"])
        self.assertIn("market_cap_usd_below_floor", rows[0]["reasons"])

    def test_adv_below_floor(self):
        sec = {"T": {"cik": 3, "exchange": "NYSE"}}
        shares = {3: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        rows = self._rows(sec, shares, {"T": _md(10.0, 1000.0)})
        self.assertFalse(rows[0]["eligible"])
        self.assertIn("adv_usd_below_floor", rows[0]["reasons"])

    def test_adv_insufficient_coverage_is_conservative(self):
        sec = {"T": {"cik": 3, "exchange": "NYSE"}}
        shares = {3: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        rows = self._rows(sec, shares, {"T": _md(10.0, None, adv_days=4)})
        self.assertFalse(rows[0]["eligible"])
        self.assertIn("adv_usd_unknown_or_invalid", rows[0]["reasons"])
        self.assertFalse(rows[0]["adv_coverage_ok"])
        self.assertEqual(rows[0]["coverage_status"], "adv_insufficient")

    def test_needs_market_cap_when_only_missing_mktcap(self):
        sec = {"GOOGL": {"cik": 1652044, "exchange": "NASDAQ"}}
        rows = self._rows(sec, {}, {"GOOGL": _md(340.0, 50_000_000.0)})
        self.assertEqual(_mod.summarize_rows(rows)["needs_market_cap"], ["GOOGL"])
        self.assertFalse(rows[0]["eligible"])

    def test_fmp_cap_rescues(self):
        sec = {"GOOGL": {"cik": 1652044, "exchange": "NASDAQ"}}
        rows = self._rows(sec, {}, {"GOOGL": _md(340.0, 50_000_000.0)}, fmp_caps={"GOOGL": 2e12})
        self.assertTrue(rows[0]["eligible"])
        self.assertEqual(rows[0]["market_cap_source"], "fmp_profile")

    def test_sec_shares_precedence_over_fmp(self):
        sec = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        rows = self._rows(sec, shares, {"AAPL": _md(200.0, 50_000_000.0)}, fmp_caps={"AAPL": 1.0})
        self.assertTrue(rows[0]["eligible"])               # SEC shares used, bogus FMP cap ignored
        self.assertEqual(rows[0]["market_cap_source"], "sec_shares_x_close")

    def test_no_price_fails(self):
        sec = {"X": {"cik": 7, "exchange": "NYSE"}}
        shares = {7: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        rows = self._rows(sec, shares, {"X": _md(None, None, adv_days=0)})
        self.assertFalse(rows[0]["eligible"])
        self.assertEqual(_mod.summarize_rows(rows)["no_price_count"], 1)
        self.assertEqual(rows[0]["coverage_status"], "no_price")

    def test_row_carries_full_lineage(self):
        sec = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        rows = self._rows(sec, shares, {"AAPL": _md(200.0, 50_000_000.0, volume=600_000)})
        r = rows[0]
        for key in ("provider_id", "as_of", "observed_at", "coverage_status", "parser_status", "lineage"):
            self.assertIn(key, r)
        self.assertEqual(set(r["lineage"]),
                         {"price_source", "adv_window_trading_days", "adv_days_observed",
                          "shares_source", "market_cap_source"})
        self.assertEqual(r["as_of"], "2026-06-26")
        self.assertEqual(r["lineage"]["shares_source"], "sec_xbrl_frames")
        self.assertFalse(r["status_flags_sourced"])

    def test_status_records_are_consumed_and_recorded(self):
        sec = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        rec = _status_record("AAPL")
        rows = self._rows(sec, shares, {"AAPL": _md(200.0, 50_000_000.0)},
                          status_records={"AAPL": rec})
        r = rows[0]
        self.assertTrue(r["eligible"], r["reasons"])
        self.assertTrue(r["status_flags_sourced"])
        self.assertEqual(r["status_provenance"], rec)
        self.assertEqual({k: r[k] for k in ("delisted", "halted", "bankruptcy", "otc")},
                         {"delisted": False, "halted": False, "bankruptcy": False, "otc": False})

    def test_status_record_unknown_conservative_flags_remain_unknown(self):
        sec = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        rec = _status_record("AAPL", ticker_reference=None)
        rows = self._rows(sec, shares, {"AAPL": _md(200.0, 50_000_000.0)},
                          status_records={"AAPL": rec})
        r = rows[0]
        self.assertTrue(r["status_flags_sourced"])
        self.assertIsNone(r["delisted"])
        self.assertIsNone(r["otc"])
        self.assertFalse(r["eligible"])
        self.assertIn("status_delisted_unknown_or_invalid", r["reasons"])
        self.assertIn("status_otc_unknown_or_invalid", r["reasons"])

    def test_missing_status_record_raises_when_status_map_supplied(self):
        sec = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"},
               "MSFT": {"cik": 789019, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"},
                  789019: {"shares": 7_400_000_000, "end": "2026-03-31"}}
        md = {"AAPL": _md(200.0, 50_000_000.0), "MSFT": _md(450.0, 60_000_000.0)}
        with self.assertRaises(RuntimeError):
            self._rows(sec, shares, md, status_records={"AAPL": _status_record("AAPL")})


class TestAdvSemantics(unittest.TestCase):
    """The finding's core: single-day dollar volume mislabeled as ADV. A one-day spike that clears the
    floor must NOT make a name eligible once ADV is the real multi-day average."""

    def setUp(self):
        self.gov = _load_gov()
        self.floor = self.gov["cheap_eligibility_thresholds"]["min_adv_usd"]   # 5_000_000

    def test_single_day_spike_does_not_pass_adv_floor(self):
        # newest day $6M (> floor), 19 prior days $4M → 20-day average $4.1M (< floor)
        collected = [("2026-06-26", [{"T": "SPK", "c": 10.0, "v": 600_000}])]
        collected += [(f"d{i}", [{"T": "SPK", "c": 10.0, "v": 400_000}]) for i in range(19)]
        md = _mod._aggregate_window(collected)
        _mod._finalize_adv(md, min_days=_mod.ADV_MIN_DAYS_REQUIRED)
        adv = md["SPK"]["adv_usd"]
        self.assertGreater(10.0 * 600_000, self.floor)     # the spike day ALONE clears the floor
        self.assertLess(adv, self.floor)                   # the multi-day average does not
        rows = _mod.apply_pass1({"SPK": {"cik": 1, "exchange": "NYSE"}},
                                {1: {"shares": 10_000_000_000, "end": "2026-03-31"}},
                                md, governance=self.gov, as_of="2026-06-26", observed_at="t")
        self.assertFalse(rows[0]["eligible"])
        self.assertIn("adv_usd_below_floor", rows[0]["reasons"])

    def test_consistently_liquid_name_passes(self):
        collected = [(f"d{i}", [{"T": "LIQ", "c": 10.0, "v": 600_000}]) for i in range(20)]  # $6M/day
        md = _mod._aggregate_window(collected)
        _mod._finalize_adv(md, min_days=_mod.ADV_MIN_DAYS_REQUIRED)
        self.assertGreaterEqual(md["LIQ"]["adv_usd"], self.floor)
        rows = _mod.apply_pass1({"LIQ": {"cik": 2, "exchange": "NYSE"}},
                                {2: {"shares": 10_000_000_000, "end": "2026-03-31"}},
                                md, governance=self.gov, as_of="2026-06-26", observed_at="t")
        self.assertTrue(rows[0]["eligible"])


class TestSummaryAndArtifact(unittest.TestCase):
    def setUp(self):
        self.gov = _load_gov()

    def _rows(self):
        sec = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"},
               "LOW": {"cik": 5, "exchange": "NYSE"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"},
                  5: {"shares": 10_000_000_000, "end": "2026-03-31"}}
        md = {"AAPL": _md(200.0, 50_000_000.0), "LOW": _md(10.0, 1000.0)}
        return _mod.apply_pass1(sec, shares, md, governance=self.gov,
                                as_of="2026-06-26", observed_at="2026-06-29T12:00:00+00:00")

    def _artifact(self):
        return _mod.build_candidate_artifact(
            rows=self._rows(), decision_date="20260629", price_basis_date="20260626",
            used_date="2026-06-26", observed_window_dates=["2026-06-26", "2026-06-25"],
            generated_at="2026-06-29T12:00:00+00:00",
            calendar_verification_status="pending_authoritative_cross_check")

    def _status_rows(self):
        sec = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"},
               "LOW": {"cik": 5, "exchange": "NYSE"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"},
                  5: {"shares": 10_000_000_000, "end": "2026-03-31"}}
        md = {"AAPL": _md(200.0, 50_000_000.0), "LOW": _md(10.0, 1000.0)}
        return _mod.apply_pass1(
            sec, shares, md, governance=self.gov, as_of="2026-06-26",
            observed_at="2026-06-29T12:00:00+00:00",
            status_records={"AAPL": _status_record("AAPL"),
                            "LOW": _status_record("LOW", exchange="NYSE")},
        )

    def _status_artifact(self):
        return _mod.build_candidate_artifact(
            rows=self._status_rows(), decision_date="20260629", price_basis_date="20260626",
            used_date="2026-06-26", observed_window_dates=["2026-06-26", "2026-06-25"],
            generated_at="2026-06-29T12:00:00+00:00",
            calendar_verification_status="pending_authoritative_cross_check")

    def test_summary_recomputed_matches_rows(self):
        art = self._artifact()
        self.assertEqual(art["summary"], _mod.summarize_rows(art["rows"]))
        self.assertEqual(art["eligible_tickers"], ["AAPL"])
        self.assertEqual(art["eligible_count"], 1)
        self.assertEqual(art["row_count"], 2)

    def test_validate_accepts_valid_artifact(self):
        art = self._artifact()
        _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_accepts_status_sourced_artifact(self):
        art = self._status_artifact()
        self.assertTrue(art["rows"][0]["status_flags_sourced"])
        _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_rejects_status_flag_provenance_mismatch(self):
        art = self._status_artifact()
        row = art["rows"][0]
        row["delisted"] = True
        row["eligible"] = False
        row["reasons"] = ["status_delisted"]
        art["summary"] = _mod.summarize_rows(art["rows"])
        art["eligible_tickers"] = _mod.eligible_tickers_from_rows(art["rows"])
        art["eligible_count"] = len(art["eligible_tickers"])
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_rejects_tampered_summary(self):
        art = self._artifact()
        art["summary"]["eligible_count"] = 99
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_rejects_row_count_mismatch(self):
        art = self._artifact()
        art["row_count"] = 1
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_rejects_decision_date_path_mismatch(self):
        art = self._artifact()
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(art, expected_decision_date="20260622", governance=self.gov)

    def test_validate_rejects_eligible_with_uncovered_adv(self):
        # forge an eligible row whose ADV is null / under-covered: schema permits null adv_usd, the
        # semantic floor check must still reject it (no single-day / no-coverage admit slips through)
        art = self._artifact()
        for r in art["rows"]:
            if r["ticker"] == "AAPL":
                r["adv_usd"] = None
                r["adv_coverage_ok"] = False
        # keep summary consistent with the mutated rows so we isolate the eligible-ADV check
        art["summary"] = _mod.summarize_rows(art["rows"])
        art["eligible_tickers"] = _mod.eligible_tickers_from_rows(art["rows"])
        art["eligible_count"] = len(art["eligible_tickers"])
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_rejects_missing_row_lineage(self):
        art = self._artifact()
        del art["rows"][0]["lineage"]
        with self.assertRaises(Exception):   # jsonschema.ValidationError (required lineage)
            _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_rejects_forged_eligible_below_price_floor(self):
        # F1 (cc_r1_v1) headline: a penny row (price below the $5 floor) forged eligible=True/reasons=[] with a
        # self-consistent summary must be REJECTED — the validator re-derives the verdict via cheap_eligible.
        art = self._artifact()
        for r in art["rows"]:
            if r["ticker"] == "AAPL":
                r["price"] = 3.0                          # below min_price_usd=5.0
                r["market_cap_usd"] = r["shares"] * 3.0   # keep market_cap_source=sec_shares_x_close consistent
                r["eligible"] = True                      # forged
                r["reasons"] = []                         # forged
        art["summary"] = _mod.summarize_rows(art["rows"])           # keep aggregation self-consistent
        art["eligible_tickers"] = _mod.eligible_tickers_from_rows(art["rows"])
        art["eligible_count"] = len(art["eligible_tickers"])
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_rejects_forged_coverage_status(self):
        # F1: coverage_status re-derived from inputs (schema allows the enum value; the semantic layer rejects).
        art = self._artifact()
        art["rows"][0]["coverage_status"] = "no_price"   # AAPL has a price → recompute = "complete"
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_rejects_forged_lineage_source(self):
        # F1: lineage.market_cap_source must equal the row's market_cap_source (re-derived consistency).
        art = self._artifact()
        art["rows"][0]["lineage"]["market_cap_source"] = "none"   # row says sec_shares_x_close
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_rejects_forged_as_of(self):
        # F1: row as_of must be bound to the run clock (== used_date).
        art = self._artifact()
        art["rows"][0]["as_of"] = "1999-01-01"
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def _fmp_rows(self, fmp_caps):
        # one ticker with NO SEC shares (so the producer falls back to FMP / none precedence)
        sec = {"NOSEC": {"cik": 999, "exchange": "NYSE"}}
        md = {"NOSEC": _md(50.0, 20_000_000.0)}
        return _mod.apply_pass1(sec, {}, md, governance=self.gov, fmp_caps=fmp_caps,
                                as_of="2026-06-26", observed_at="2026-06-29T12:00:00+00:00")

    def _fmp_artifact(self, rows):
        return _mod.build_candidate_artifact(
            rows=rows, decision_date="20260629", price_basis_date="20260626", used_date="2026-06-26",
            observed_window_dates=["2026-06-26"], generated_at="2026-06-29T12:00:00+00:00",
            calendar_verification_status="pending_authoritative_cross_check")

    def test_validate_rejects_forged_fmp_source_when_sec_available(self):
        # Codex cc_r1_v1 residual: SEC shares+price available → producer uses sec_shares_x_close; forging
        # market_cap_source (and matching lineage) to fmp_profile must be REJECTED (producer-precedence re-derive).
        art = self._artifact()
        for r in art["rows"]:
            if r["ticker"] == "AAPL":   # SEC shares 15e9 + price 200 → sec_shares_x_close
                r["market_cap_source"] = "fmp_profile"             # forged source
                r["lineage"]["market_cap_source"] = "fmp_profile"  # forged to match → isolates the precedence check
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_accepts_fmp_fallback_when_sec_unavailable(self):
        # FMP fallback POSITIVE: no SEC shares + finite FMP cap → market_cap_source=fmp_profile accepted.
        rows = self._fmp_rows({"NOSEC": 5e8})
        self.assertEqual(rows[0]["market_cap_source"], "fmp_profile")
        self.assertIsNone(rows[0]["shares"])
        _mod.validate_candidate_artifact(self._fmp_artifact(rows), expected_decision_date="20260629", governance=self.gov)

    def test_validate_accepts_none_source_when_no_market_cap(self):
        # none POSITIVE: no SEC shares + no FMP cap → market_cap_source=none, market_cap_usd=None accepted.
        rows = self._fmp_rows({})
        self.assertEqual(rows[0]["market_cap_source"], "none")
        self.assertIsNone(rows[0]["market_cap_usd"])
        _mod.validate_candidate_artifact(self._fmp_artifact(rows), expected_decision_date="20260629", governance=self.gov)

    def test_validate_rejects_none_source_with_finite_market_cap(self):
        # none NEGATIVE boundary: market_cap_source=none must not carry a finite market_cap (forge rejected).
        rows = self._fmp_rows({})
        rows[0]["market_cap_usd"] = 5e8   # forged finite cap while market_cap_source stays "none"
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(self._fmp_artifact(rows), expected_decision_date="20260629", governance=self.gov)


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
        with patch.object(_mod, "_check_gitignore", return_value=True):
            out = _mod.run_fetch(dry_run_env=True, confirm_user_authorization=False)
        self.assertEqual(out["scope"]["status"], "dry_run_env_only")

    def test_requires_now_et_for_live(self):
        with patch.object(_mod, "_check_gitignore", return_value=True), \
             patch.dict(os.environ, {"SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "k"}):
            with self.assertRaises(RuntimeError) as ctx:
                _mod.run_fetch(confirm_user_authorization=True, now_et=None)
        self.assertIn("now-et", str(ctx.exception))

    def test_intraday_out_of_window_fail_closed(self):
        # 2026-06-29 11:00 ET is inside the Monday RTH session → §2.1 dead zone, fail-closed
        with patch.object(_mod, "_check_gitignore", return_value=True), \
             patch.dict(os.environ, {"SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "k"}):
            with self.assertRaises(RuntimeError) as ctx:
                _mod.run_fetch(confirm_user_authorization=True, now_et=datetime(2026, 6, 29, 11, 0, 0))
        self.assertIn("盘中死区", str(ctx.exception))

    def test_raw_root_escape_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "escaped"
            with patch.object(_mod, "_check_gitignore", return_value=True), \
                 patch.dict(os.environ, {"SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "k"}):
                with self.assertRaises((ValueError, RuntimeError)):
                    _mod.run_fetch(confirm_user_authorization=True,
                                   now_et=datetime(2026, 6, 29, 8, 0, 0), raw_root=bad)
            self.assertFalse(any(bad.rglob("*")))


class TestRunFetchE2E(unittest.TestCase):
    def test_full_offline_run_binds_decision_date_and_recomputes(self):
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"},
                   "LOWADV": {"cik": 5, "exchange": "NYSE"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"},
                  5: {"shares": 1_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000},   # huge ADV
                    {"T": "LOWADV", "c": 10.0, "v": 100}]          # ~$1k/day ADV → below floor

        cand = ROOT / "state" / "us_short" / "candidate_universe_20260629.json"  # canonical for decision_date 20260629 (gitignored)
        cand.unlink(missing_ok=True)
        self.addCleanup(cand.unlink, missing_ok=True)
        self.addCleanup(cand.with_name(cand.name + ".tmp").unlink, missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            with patch.dict(os.environ, {"SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "MASSIVE_SECRET_ZZZ", "FMP_API_KEY": ""}), \
                 patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value=shares), \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod, "fetch_nasdaq_trade_halt_feed",
                              return_value={"observed": True, "observed_at": "2026-06-29T12:00:00+00:00",
                                            "halted_symbols": []}), \
                 patch.object(_mod.time, "sleep"), \
                 patch.object(_mod._sv, "validate_raw_root"):
                summary = _mod.run_fetch(
                    now_et=datetime(2026, 6, 29, 8, 0, 0),
                    summary_path=tmpp / "sum.json", raw_root=tmpp / "raw",
                    candidate_list_path=cand,
                    generated_at="2026-06-29T12:00:00+00:00", confirm_user_authorization=True,
                )
            self.assertEqual(summary["decision_clock"]["decision_date"], "20260629")
            self.assertEqual(summary["decision_clock"]["price_basis_date"], "20260626")
            self.assertEqual(summary["decision_clock"]["used_date"], "2026-06-26")
            self.assertIn("AAPL", summary["pass1_result"]["eligible_tickers"])
            self.assertNotIn("LOWADV", summary["pass1_result"]["eligible_tickers"])
            self.assertFalse(summary["storage"]["tracked_summary_contains_prices"])
            self.assertTrue(summary["storage"]["candidate_artifact_gitignored"])   # real True on a completed run

            artifact = json.loads(cand.read_text(encoding="utf-8"))
        self.assertEqual(artifact["decision_date"], "20260629")
        self.assertEqual(artifact["summary"], _mod.summarize_rows(artifact["rows"]))
        self.assertEqual(artifact["adv_window"]["trading_days"], _mod.ADV_WINDOW_TRADING_DAYS)
        aapl = next(r for r in artifact["rows"] if r["ticker"] == "AAPL")
        self.assertEqual(aapl["adv_days_observed"], _mod.ADV_WINDOW_TRADING_DAYS)
        self.assertTrue(aapl["adv_coverage_ok"])
        self.assertEqual(summary["pass1_result"], {**_mod.summarize_rows(artifact["rows"]),
                                                   "eligible_tickers": ["AAPL"]})

    def test_live_run_wires_status_records_from_sec_reference_and_halt_feed(self):
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"},
                   "HALT": {"cik": 999999, "exchange": "NYSE"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"},
                  999999: {"shares": 1_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000},
                    {"T": "HALT", "c": 20.0, "v": 10_000_000}]

        cand = ROOT / "state" / "us_short" / "candidate_universe_20260629.json"
        cand.unlink(missing_ok=True)
        self.addCleanup(cand.unlink, missing_ok=True)
        self.addCleanup(cand.with_name(cand.name + ".tmp").unlink, missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            with patch.dict(os.environ, {"SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "MASSIVE_SECRET_ZZZ", "FMP_API_KEY": ""}), \
                 patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value=shares), \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod, "fetch_nasdaq_trade_halt_feed",
                              return_value={"observed": True, "observed_at": "2026-06-29T12:00:00+00:00",
                                            "halted_symbols": ["HALT"]}), \
                 patch.object(_mod.time, "sleep"), \
                 patch.object(_mod._sv, "validate_raw_root"):
                summary = _mod.run_fetch(
                    now_et=datetime(2026, 6, 29, 8, 0, 0),
                    summary_path=tmpp / "sum.json", raw_root=tmpp / "raw",
                    candidate_list_path=cand,
                    generated_at="2026-06-29T12:00:00+00:00", confirm_user_authorization=True,
                )

            artifact = json.loads(cand.read_text(encoding="utf-8"))

        self.assertTrue(summary["status_screening"]["status_flags_sourced"])
        self.assertFalse(summary["status_screening"]["bankruptcy_8k_scan_performed"])
        self.assertEqual(summary["status_screening"]["status_source_outcome"]["per_source"]["ticker_reference"], "ok")
        self.assertEqual(summary["status_screening"]["status_source_outcome"]["per_source"]["exchange_halt_feed"], "ok")
        self.assertEqual(summary["pass1_result"]["eligible_tickers"], ["AAPL"])
        by_ticker = {row["ticker"]: row for row in artifact["rows"]}
        self.assertTrue(by_ticker["AAPL"]["status_flags_sourced"])
        self.assertFalse(by_ticker["AAPL"]["halted"])
        self.assertTrue(by_ticker["HALT"]["status_flags_sourced"])
        self.assertTrue(by_ticker["HALT"]["halted"])
        self.assertFalse(by_ticker["HALT"]["eligible"])
        self.assertIn("status_halted", by_ticker["HALT"]["reasons"])
        self.assertEqual(by_ticker["HALT"]["status_provenance"]["flags"]["halted"]["source_id"], "exchange_halt_feed")

    def test_halt_feed_failure_keeps_halted_unknown_not_clean(self):
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000}]

        cand = ROOT / "state" / "us_short" / "candidate_universe_20260629.json"
        cand.unlink(missing_ok=True)
        self.addCleanup(cand.unlink, missing_ok=True)
        self.addCleanup(cand.with_name(cand.name + ".tmp").unlink, missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            with patch.dict(os.environ, {"SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "MASSIVE_SECRET_ZZZ", "FMP_API_KEY": ""}), \
                 patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value=shares), \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod, "fetch_nasdaq_trade_halt_feed", side_effect=RuntimeError("halt feed down")), \
                 patch.object(_mod.time, "sleep"), \
                 patch.object(_mod._sv, "validate_raw_root"):
                summary = _mod.run_fetch(
                    now_et=datetime(2026, 6, 29, 8, 0, 0),
                    summary_path=tmpp / "sum.json", raw_root=tmpp / "raw",
                    candidate_list_path=cand,
                    generated_at="2026-06-29T12:00:00+00:00", confirm_user_authorization=True,
                )

            artifact = json.loads(cand.read_text(encoding="utf-8"))

        row = artifact["rows"][0]
        self.assertTrue(row["status_flags_sourced"])
        self.assertIsNone(row["halted"])
        self.assertFalse(row["eligible"])
        self.assertIn("status_halted_unknown_or_invalid", row["reasons"])
        self.assertEqual(summary["status_screening"]["status_source_outcome"]["per_source"]["exchange_halt_feed"], "down")
        self.assertFalse(summary["status_screening"]["status_source_outcome"]["block_or_no_emit"])

    def test_all_critical_status_sources_fail_no_emit(self):
        with self.assertRaisesRegex(RuntimeError, "all critical status sources failed"):
            _mod.build_live_status_records(
                {},
                decision_date="20260629",
                observed_at="2026-06-29T12:00:00+00:00",
                halt_feed={"observed": False},
                halt_feed_state="down",
            )

    def test_build_live_status_records_consumes_provider_fed_bankruptcy_screen(self):
        sec_map = {
            "AAPL": {"cik": 320193, "exchange": "NASDAQ"},
            "BANKR": {"cik": 123456, "exchange": "NYSE"},
        }
        bankruptcy_screen = {
            "observed": True,
            "observed_at": "2026-06-29T12:00:00+00:00",
            "lookback_window": "P90D",
            "by_ticker": {
                "AAPL": {"screen_status": "screened_no_filing"},
                "BANKR": {
                    "screen_status": "bankrupt_8k_found",
                    "filing_accession": "0001140361-26-000001",
                },
            },
        }

        records, outcome, payloads = _mod.build_live_status_records(
            sec_map,
            decision_date="20260629",
            observed_at="2026-06-29T12:00:00+00:00",
            halt_feed=_status_halt(),
            halt_feed_state="ok",
            bankruptcy_screen=bankruptcy_screen,
        )

        self.assertEqual(outcome["per_source"]["sec_8k_item_103"], "ok")
        self.assertIs(payloads["sec_8k_item_103"], bankruptcy_screen)
        self.assertFalse(records["AAPL"]["flags"]["bankruptcy"]["value"])
        self.assertEqual(records["AAPL"]["flags"]["bankruptcy"]["screen_status"], "screened_no_filing")
        self.assertTrue(records["BANKR"]["flags"]["bankruptcy"]["value"])
        self.assertEqual(
            records["BANKR"]["flags"]["bankruptcy"]["filing_accession_if_found"],
            "0001140361-26-000001",
        )

    def test_build_live_status_records_consumes_sec_submissions_bankruptcy_screen(self):
        sec_map = {
            "AAPL": {"cik": 320193, "exchange": "NASDAQ"},
            "BANKR": {"cik": 123456, "exchange": "NYSE"},
        }
        submissions_by_ticker = {
            "AAPL": _sec_submissions(
                forms=["8-K"],
                filing_dates=["2026-06-20"],
                accessions=["0000320193-26-000111"],
                items=["9.01"],
            ),
            "BANKR": _sec_submissions(
                forms=["8-K"],
                filing_dates=["2026-06-20"],
                accessions=["0001140361-26-000001"],
                items=["1.03,9.01"],
            ),
        }

        records, outcome, payloads = _mod.build_live_status_records(
            sec_map,
            decision_date="20260629",
            observed_at=STATUS_OBSERVED_AT,
            halt_feed=_status_halt(),
            halt_feed_state="ok",
            bankruptcy_submissions_by_ticker=submissions_by_ticker,
        )

        self.assertEqual(outcome["per_source"]["sec_8k_item_103"], "ok")
        self.assertEqual(
            payloads["sec_8k_item_103"]["by_ticker"]["BANKR"],
            {"screen_status": "bankrupt_8k_found", "filing_accession": "0001140361-26-000001"},
        )
        self.assertFalse(records["AAPL"]["flags"]["bankruptcy"]["value"])
        self.assertEqual(records["AAPL"]["flags"]["bankruptcy"]["screen_status"], "screened_no_filing")
        self.assertTrue(records["BANKR"]["flags"]["bankruptcy"]["value"])
        self.assertEqual(
            records["BANKR"]["flags"]["bankruptcy"]["filing_accession_if_found"],
            "0001140361-26-000001",
        )

    def test_build_live_status_records_rejects_two_bankruptcy_source_shapes(self):
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        with self.assertRaises(RuntimeError):
            _mod.build_live_status_records(
                sec_map,
                decision_date="20260629",
                observed_at=STATUS_OBSERVED_AT,
                halt_feed=_status_halt(),
                halt_feed_state="ok",
                bankruptcy_screen=_status_bank("AAPL"),
                bankruptcy_submissions_by_ticker={
                    "AAPL": _sec_submissions(
                        forms=["8-K"],
                        filing_dates=["2026-06-20"],
                        accessions=["0000320193-26-000111"],
                        items=["1.03"],
                    ),
                },
            )

    def test_parse_halt_symbols_prefers_namespaced_issue_symbol(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:ndaq="http://www.nasdaqtrader.com/">
  <channel>
    <item>
      <title>Company name, not the parser source</title>
      <ndaq:IssueSymbol>ABTC</ndaq:IssueSymbol>
      <description>Issue Symbol table cell may also contain ABTC</description>
    </item>
  </channel>
</rss>"""
        self.assertEqual(_mod.parse_halt_symbols_from_rss(xml), ["ABTC"])

    def test_parse_halt_symbols_rejects_unparseable_items(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Trading halt notice</title>
      <description>No ticker field was captured</description>
    </item>
  </channel>
</rss>"""
        with self.assertRaisesRegex(RuntimeError, "unparseable"):
            _mod.parse_halt_symbols_from_rss(xml)

    def test_parse_halt_symbols_rejects_symbol_text_without_issue_symbol(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Trading halt notice for another issue</title>
      <description>Operational message includes Symbol: XYZ but omits the authoritative field</description>
    </item>
  </channel>
</rss>"""
        with self.assertRaisesRegex(RuntimeError, "unparseable"):
            _mod.parse_halt_symbols_from_rss(xml)

    def test_parse_halt_symbols_rejects_blank_issue_symbol_instead_of_title_fallback(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:ndaq="http://www.nasdaqtrader.com/">
  <channel>
    <item>
      <ndaq:IssueSymbol> </ndaq:IssueSymbol>
      <title>GME</title>
    </item>
  </channel>
</rss>"""
        with self.assertRaisesRegex(RuntimeError, "unparseable"):
            _mod.parse_halt_symbols_from_rss(xml)

    def test_parse_halt_symbols_rejects_partial_feed_with_unparseable_item(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:ndaq="http://www.nasdaqtrader.com/">
  <channel>
    <item>
      <ndaq:IssueSymbol>HALT</ndaq:IssueSymbol>
      <title>HALT</title>
    </item>
    <item>
      <title>Trading halt notice</title>
      <description>No ticker field was captured</description>
    </item>
  </channel>
</rss>"""
        with self.assertRaisesRegex(RuntimeError, "unparseable"):
            _mod.parse_halt_symbols_from_rss(xml)


class SummarySafetyAndGitignore(unittest.TestCase):
    """R-USSHORT-BATCH5-UNIVERSE-FETCH-SECRET-SCAN-GITIGNORE-GAP (cc_r1 O3): the tracked summary is scanned for
    leaked secrets / provider URLs before write, and the gitignored claims are real `git check-ignore` truths."""

    def _write(self, text):
        import tempfile
        p = Path(tempfile.mkdtemp()) / "summary.json"
        p.write_text(text, encoding="utf-8")
        return p

    def test_assert_summary_safe_passes_clean(self):
        p = self._write('{"eligible_count": 3, "provider": "massive_grouped_daily + sec_shares"}')
        _mod._assert_summary_safe(p, ["SECRETKEY123", ""])   # no forbidden fragment, no secret present

    def test_assert_summary_safe_rejects_secret_value(self):
        p = self._write('{"x": "leaked SECRETKEY123 here"}')
        with self.assertRaises(RuntimeError):
            _mod._assert_summary_safe(p, ["SECRETKEY123"])

    def test_assert_summary_safe_rejects_forbidden_fragment(self):
        p = self._write('{"url": "https://api.massive.com/v2/aggs?apiKey=zzz"}')
        with self.assertRaises(RuntimeError):
            _mod._assert_summary_safe(p, [])

    def test_assert_summary_safe_rejects_nasdaqtrader_domain(self):
        p = self._write('{"url": "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"}')
        with self.assertRaises(RuntimeError):
            _mod._assert_summary_safe(p, [])

    def test_git_check_ignored_true_for_state_json(self):
        # state/us_short/*.json is gitignored (state/*/*.json) → the candidate-artifact claim is a real True
        self.assertTrue(_mod._git_check_ignored(ROOT / "state" / "us_short" / "candidate_universe_20260629.json"))

    def test_git_check_ignored_false_for_tracked_docs(self):
        # a tracked docs path is NOT gitignored → the claim cannot be hard-coded True
        self.assertFalse(_mod._git_check_ignored(ROOT / "docs" / "README.md"))

    def test_write_summary_safe_clean_writes(self):
        import tempfile
        p = Path(tempfile.mkdtemp()) / "summary.json"
        _mod._write_summary_safe({"eligible_count": 3, "provider": "massive_grouped_daily + sec_shares"},
                                 p, ["SECRETKEY123"])
        self.assertTrue(p.exists())

    def test_write_summary_safe_secret_leaves_no_residue(self):
        # scan runs BEFORE the write, so a secret-bearing summary raises with NO file created (no residue) —
        # R-USSHORT-BATCH5-UNIVERSE-FETCH-SECRET-SCAN-GITIGNORE-GAP (post-write-residue fix).
        import tempfile
        p = Path(tempfile.mkdtemp()) / "summary.json"
        with self.assertRaises(RuntimeError):
            _mod._write_summary_safe({"x": "leaked SECRETKEY123 here"}, p, ["SECRETKEY123"])
        self.assertFalse(p.exists())
        self.assertFalse(p.with_name(p.name + ".tmp").exists())   # no temp residue either


class CandidatePathGuard(unittest.TestCase):
    """R-USSHORT-BATCH5-PASS1-LIQUIDITY-LINEAGE-CONTRACT-GAP (Codex reviews 2026-06-30): the per-run candidate
    artifact carries per-row price/ADV/market_cap, so its path is BOUND to the canonical decision_date BEFORE
    any fetch/write — it must be EXACTLY state/us_short/candidate_universe_<decision_date>.json. A non-gitignored
    OR wrong-date path fails closed with no artifact/.tmp/summary/raw residue; the production CLI exposes no
    --candidate-list-path override; storage.candidate_artifact_gitignored can never be false on a completed run."""

    def test_canonical_path_accepted(self):
        _mod._validate_candidate_path(_mod._candidate_path_for("20260629"), "20260629")  # no raise

    def test_wrong_date_gitignored_path_rejected(self):
        # Codex probe: a gitignored state/us_short/ .json whose filename date != the run's decision_date must be
        # rejected — the filename must not lie about which decision-date bucket the priced artifact represents.
        with self.assertRaises(RuntimeError) as ctx:
            _mod._validate_candidate_path(ROOT / "state" / "us_short" / "candidate_universe_19000101.json", "20260629")
        self.assertIn("canonical", str(ctx.exception).lower())

    def test_non_gitignored_path_rejected(self):
        # right filename, wrong (non-gitignored) dir → != canonical → rejected
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as ctx:
                _mod._validate_candidate_path(Path(tmp) / "candidate_universe_20260629.json", "20260629")
        self.assertIn("canonical", str(ctx.exception).lower())

    def test_cli_no_longer_exposes_output_path_overrides(self):
        # the production CLI must not accept a redirect for any dated output artifact — they derive from the
        # canonical decision_date; the run_fetch path kwargs are a private test seam only.
        for flag in ("--candidate-list-path", "--summary-path", "--raw-root"):
            with self.assertRaises(SystemExit):
                _mod.parse_args([flag, "x"])

    def test_full_run_wrong_date_candidate_leaves_no_residue(self):
        # Codex's exact probe: a gitignored but WRONG-DATE candidate path on a 20260629 run must fail closed
        # BEFORE writing the priced artifact or the tracked summary (no candidate/.tmp/summary residue).
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000}]

        wrong = ROOT / "state" / "us_short" / "candidate_universe_19000101.json"
        wrong.unlink(missing_ok=True)
        self.addCleanup(wrong.unlink, missing_ok=True)
        self.addCleanup(wrong.with_name(wrong.name + ".tmp").unlink, missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            summ = tmpp / "sum.json"
            with patch.dict(os.environ, {"SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "k", "FMP_API_KEY": ""}), \
                 patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value=shares), \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod.time, "sleep"), \
                 patch.object(_mod._sv, "validate_raw_root"):
                with self.assertRaises(RuntimeError) as ctx:
                    _mod.run_fetch(
                        now_et=datetime(2026, 6, 29, 8, 0, 0),
                        summary_path=summ, raw_root=tmpp / "raw",
                        candidate_list_path=wrong,
                        generated_at="2026-06-29T12:00:00+00:00", confirm_user_authorization=True,
                    )
            self.assertIn("canonical", str(ctx.exception).lower())
            self.assertFalse(wrong.exists())                                 # no priced artifact written
            self.assertFalse(wrong.with_name(wrong.name + ".tmp").exists())  # no temp residue
            self.assertFalse(summ.exists())                                  # no tracked summary either

    def test_full_run_non_gitignored_candidate_leaves_no_residue(self):
        # a non-gitignored candidate path likewise fails closed before any write.
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000}]

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            bad_cand = tmpp / "candidate_universe_20260629.json"   # right name, NON-gitignored dir
            summ = tmpp / "sum.json"
            with patch.dict(os.environ, {"SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "k", "FMP_API_KEY": ""}), \
                 patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value=shares), \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod.time, "sleep"), \
                 patch.object(_mod._sv, "validate_raw_root"):
                with self.assertRaises(RuntimeError) as ctx:
                    _mod.run_fetch(
                        now_et=datetime(2026, 6, 29, 8, 0, 0),
                        summary_path=summ, raw_root=tmpp / "raw",
                        candidate_list_path=bad_cand,
                        generated_at="2026-06-29T12:00:00+00:00", confirm_user_authorization=True,
                    )
            self.assertIn("canonical", str(ctx.exception).lower())
            self.assertFalse(bad_cand.exists())
            self.assertFalse(bad_cand.with_name(bad_cand.name + ".tmp").exists())
            self.assertFalse(summ.exists())


if __name__ == "__main__":
    unittest.main()
