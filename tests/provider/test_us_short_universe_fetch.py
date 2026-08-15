"""Tests for runners/us_short_universe_fetch.py (Massive + SEC + yfinance free path, no broker).

Offline-only: no live Massive/SEC/FMP calls. Covers the pure logic:
- SEC ticker/CIK/exchange parsing + exchange normalization
- SEC shares frames merge (latest per CIK across quarters)
- Massive grouped daily ADV WINDOW parsing (canonical ticker, multi-day average dollar volume,
  delayed-day skip, min-coverage conservative null)
- Pass1 per-row records: market_cap = SEC shares × close; ADV = multi-day average; yfinance fallback precedence
- ADV semantics: a single-day spike must NOT pass the (multi-day) ADV floor
- summary recomputed from rows; per-run artifact schema + semantic validate-before-write
- canonical decision_date binds the output path
- yfinance market-cap fallback (single info read, identity/rate-stop/pacing); authorization / gitignore / raw_root / now-et guards
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
from tests.provider.us_short_private_test_root import (
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)

_GOV_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
_CAL_PATH = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"
STATE_DIR = ROOT / "state" / "us_short"


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


class TestIntegratedBankruptcySubmissionsFetch(unittest.TestCase):
    def test_fetches_exact_eligible_set_once_and_writes_only_raw_wrappers(self):
        import tempfile

        sec_map = {
            "AAPL": {"cik": 320193, "exchange": "NASDAQ"},
            "MSFT": {"cik": 789019, "exchange": "NASDAQ"},
            "LOWADV": {"cik": 999999, "exchange": "NYSE"},
        }
        payloads = [
            _sec_submissions(forms=[], filing_dates=[], accessions=[], items=[]),
            _sec_submissions(forms=["8-K"], filing_dates=["2026-06-20"],
                             accessions=["0000789019-26-000001"], items=["9.01"]),
        ]
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(_mod, "_sec_get", side_effect=payloads) as sec_get, \
             patch.object(_mod.time, "sleep") as sleep:
            raw_root = Path(tmp) / "raw"
            screen, stats = _mod.fetch_bankruptcy_submissions_for_eligible(
                sec_map=sec_map,
                eligible_tickers=["AAPL", "MSFT"],
                sec_ua="ua@test",
                raw_root=raw_root,
                status_as_of=STATUS_AS_OF,
                observed_at=STATUS_OBSERVED_AT,
            )

            self.assertEqual(list(screen["by_ticker"]), ["AAPL", "MSFT"])
            self.assertEqual(screen["by_ticker"]["AAPL"]["screen_status"], "screened_no_filing")
            self.assertEqual(screen["by_ticker"]["MSFT"]["screen_status"], "screened_no_filing")
            self.assertEqual(stats, {"eligible_symbol_count": 2, "sec_company_submissions_calls": 2})
            self.assertEqual(sec_get.call_count, 2)
            self.assertEqual(sec_get.call_args_list[0].args[0], _mod.SEC_SUBMISSIONS_URL.format(cik=320193))
            self.assertEqual(sec_get.call_args_list[1].args[0], _mod.SEC_SUBMISSIONS_URL.format(cik=789019))
            sleep.assert_called_once_with(_mod.SEC_FAIR_ACCESS_SLEEP)
            self.assertTrue((raw_root / "bankruptcy_8k" / "AAPL" /
                             "company_submissions_recent_filings.json").is_file())
            self.assertTrue((raw_root / "bankruptcy_8k" / "MSFT" /
                             "company_submissions_recent_filings.json").is_file())
            self.assertFalse((raw_root / "bankruptcy_8k" / "LOWADV").exists())

    def test_missing_cik_rejects_whole_scan_before_any_fetch_or_write(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, patch.object(_mod, "_sec_get") as sec_get:
            raw_root = Path(tmp) / "raw"
            with self.assertRaisesRegex(RuntimeError, "missing positive SEC CIK"):
                _mod.fetch_bankruptcy_submissions_for_eligible(
                    sec_map={"AAPL": {"cik": 320193, "exchange": "NASDAQ"},
                             "BROKEN": {"cik": None, "exchange": "NYSE"}},
                    eligible_tickers=["AAPL", "BROKEN"],
                    sec_ua="ua@test",
                    raw_root=raw_root,
                    status_as_of=STATUS_AS_OF,
                    observed_at=STATUS_OBSERVED_AT,
                )
            sec_get.assert_not_called()
            self.assertFalse(raw_root.exists())

    def test_malformed_submissions_fails_before_screened_clean_wrapper(self):
        import tempfile

        malformed = _sec_submissions(
            forms=["8-K"], filing_dates=[], accessions=["0000320193-26-000001"], items=["1.03"])
        with tempfile.TemporaryDirectory() as tmp, patch.object(_mod, "_sec_get", return_value=malformed):
            raw_root = Path(tmp) / "raw"
            with self.assertRaisesRegex(Exception, "length mismatch"):
                _mod.fetch_bankruptcy_submissions_for_eligible(
                    sec_map={"AAPL": {"cik": 320193, "exchange": "NASDAQ"}},
                    eligible_tickers=["AAPL"],
                    sec_ua="ua@test",
                    raw_root=raw_root,
                    status_as_of=STATUS_AS_OF,
                    observed_at=STATUS_OBSERVED_AT,
                )
            self.assertFalse((raw_root / "bankruptcy_8k" / "AAPL" /
                              "company_submissions_recent_filings.json").exists())

    def test_transient_429_503_and_timeout_are_bounded_retried_then_screen_completes(self):
        import tempfile

        clean = _sec_submissions(forms=[], filing_dates=[], accessions=[], items=[])
        transient = [
            _mod.urllib.error.HTTPError(
                "https://data.sec.gov/submissions/CIK0000320193.json", 429, "rate", {}, None),
            _mod.urllib.error.HTTPError(
                "https://data.sec.gov/submissions/CIK0000320193.json", 503, "down", {}, None),
            TimeoutError("read timed out"),
            clean,
        ]
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(_mod, "_sec_get", side_effect=transient) as sec_get, \
             patch.object(_mod.time, "sleep") as sleep:
            raw_root = Path(tmp) / "raw"
            screen, stats = _mod.fetch_bankruptcy_submissions_for_eligible(
                sec_map={"AAPL": {"cik": 320193, "exchange": "NASDAQ"}},
                eligible_tickers=["AAPL"],
                sec_ua="ua@test",
                raw_root=raw_root,
                status_as_of=STATUS_AS_OF,
                observed_at=STATUS_OBSERVED_AT,
            )

        self.assertEqual(sec_get.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 2.0, 4.0])
        self.assertEqual(screen["by_ticker"]["AAPL"]["screen_status"], "screened_no_filing")
        self.assertEqual(stats["sec_company_submissions_calls"], 4)

    def test_persistent_503_exhausts_bounded_attempts_without_clean_wrapper(self):
        import tempfile

        error = _mod.urllib.error.HTTPError(
            "https://data.sec.gov/submissions/CIK0000320193.json", 503, "down", {}, None)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(_mod, "_sec_get", side_effect=error) as sec_get, \
             patch.object(_mod.time, "sleep") as sleep:
            raw_root = Path(tmp) / "raw"
            with self.assertRaisesRegex(RuntimeError, "HTTP 503 after 3 retry") as ctx:
                _mod.fetch_bankruptcy_submissions_for_eligible(
                    sec_map={"AAPL": {"cik": 320193, "exchange": "NASDAQ"}},
                    eligible_tickers=["AAPL"],
                    sec_ua="ua@test",
                    raw_root=raw_root,
                    status_as_of=STATUS_AS_OF,
                    observed_at=STATUS_OBSERVED_AT,
                )

            self.assertEqual(sec_get.call_count, 4)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 2.0, 4.0])
            self.assertNotIn("https://", str(ctx.exception))
            self.assertIsNone(ctx.exception.__cause__)
            self.assertTrue(ctx.exception.__suppress_context__)
            self.assertFalse((raw_root / "bankruptcy_8k" / "AAPL" /
                              "company_submissions_recent_filings.json").exists())

    def test_urlerror_wrapped_timeout_is_retried_and_counted(self):
        import tempfile

        clean = _sec_submissions(forms=[], filing_dates=[], accessions=[], items=[])
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(
                 _mod,
                 "_sec_get",
                 side_effect=[_mod.urllib.error.URLError(TimeoutError("connect timed out")), clean],
             ) as sec_get, patch.object(_mod.time, "sleep") as sleep:
            screen, stats = _mod.fetch_bankruptcy_submissions_for_eligible(
                sec_map={"AAPL": {"cik": 320193, "exchange": "NASDAQ"}},
                eligible_tickers=["AAPL"],
                sec_ua="ua@test",
                raw_root=Path(tmp) / "raw",
                status_as_of=STATUS_AS_OF,
                observed_at=STATUS_OBSERVED_AT,
            )

        self.assertEqual(sec_get.call_count, 2)
        sleep.assert_called_once_with(1.0)
        self.assertEqual(screen["by_ticker"]["AAPL"]["screen_status"], "screened_no_filing")
        self.assertEqual(stats["sec_company_submissions_calls"], 2)

    def test_403_and_404_fail_fast_without_retry_or_clean_wrapper(self):
        import tempfile

        for code in (403, 404):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp, \
                 patch.object(
                     _mod,
                     "_sec_get",
                     side_effect=_mod.urllib.error.HTTPError(
                         "https://data.sec.gov/submissions/CIK0000320193.json", code, "client", {}, None),
                 ) as sec_get, patch.object(_mod.time, "sleep") as sleep:
                raw_root = Path(tmp) / "raw"
                with self.assertRaisesRegex(RuntimeError, f"HTTP {code} is not retryable") as ctx:
                    _mod.fetch_bankruptcy_submissions_for_eligible(
                        sec_map={"AAPL": {"cik": 320193, "exchange": "NASDAQ"}},
                        eligible_tickers=["AAPL"],
                        sec_ua="ua@test",
                        raw_root=raw_root,
                        status_as_of=STATUS_AS_OF,
                        observed_at=STATUS_OBSERVED_AT,
                    )

                sec_get.assert_called_once()
                sleep.assert_not_called()
                self.assertNotIn("https://", str(ctx.exception))
                self.assertIsNone(ctx.exception.__cause__)
                self.assertTrue(ctx.exception.__suppress_context__)
                self.assertFalse((raw_root / "bankruptcy_8k" / "AAPL" /
                                  "company_submissions_recent_filings.json").exists())


class TestFetchSecShares(unittest.TestCase):
    def test_completed_frames_follow_price_basis_and_calendar_boundaries(self):
        self.assertEqual(
            _mod.completed_sec_share_frames("20260807"),
            ["CY2026Q2I", "CY2026Q1I", "CY2025Q4I", "CY2025Q3I"],
        )
        self.assertEqual(
            _mod.completed_sec_share_frames("20260102"),
            ["CY2025Q4I", "CY2025Q3I", "CY2025Q2I", "CY2025Q1I"],
        )
        self.assertEqual(
            _mod.completed_sec_share_frames("20260401"),
            ["CY2026Q1I", "CY2025Q4I", "CY2025Q3I", "CY2025Q2I"],
        )
        self.assertEqual(_mod.completed_sec_share_frames("20260630")[0], "CY2026Q2I")

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

    def test_companyfacts_accepts_only_pit_latest_dei_then_us_gaap_fallback(self):
        def facts(*, dei=(), us_gaap=()):
            return {
                "facts": {
                    "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": list(dei)}}},
                    "us-gaap": {"CommonStockSharesOutstanding": {"units": {"shares": list(us_gaap)}}},
                }
            }

        payloads = {
            1: facts(
                dei=(
                    {"val": 90, "end": "2025-12-31", "filed": "2026-01-15", "form": "10-K", "accn": "old"},
                    {"val": 100, "end": "2026-03-31", "filed": "2026-04-20", "form": "10-Q", "accn": "new"},
                    {"val": 101, "end": "2026-03-31", "filed": "2026-07-01", "form": "10-Q", "accn": "future-filed"},
                    {"val": 102, "end": "2026-06-30", "filed": "2026-06-20", "form": "10-Q", "accn": "future-end"},
                    {"val": -1, "end": "2026-03-31", "filed": "2026-04-20", "form": "10-Q", "accn": "negative"},
                    {"val": 103, "end": "2026-03-31", "filed": "2026-04-20", "form": "8-K", "accn": "wrong-form"},
                ),
                us_gaap=(
                    {"val": 999, "end": "2026-03-31", "filed": "2026-04-20", "form": "10-Q", "accn": "gaap"},
                ),
            ),
            2: facts(
                dei=({"val": 200, "end": "2026-03-31", "filed": "2026-04-20", "form": "8-K", "accn": "bad-dei"},),
                us_gaap=({"val": 300, "end": "2026-03-31", "filed": "2026-04-20", "form": "20-F/A", "accn": "gaap-ok"},),
            ),
            3: {"facts": {}},
        }
        stats = {}
        with patch.object(
            _mod, "_sec_get",
            side_effect=lambda url, ua: payloads[int(url.split("CIK", 1)[1].split(".json", 1)[0])],
        ) as sec_get, \
             patch.object(_mod.time, "sleep") as sleep:
            out = _mod.fetch_sec_companyfacts(
                "ua@test", [1, 1, 2, 3], decision_date="20260629", price_basis_date="20260626",
                stats_out=stats,
            )

        self.assertEqual(sec_get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(stats["actual_request_count"], 3)
        self.assertEqual(out[1], {
            "shares": 100.0, "end": "2026-03-31", "filed": "2026-04-20",
            "accession": "new", "accn": "new", "source": "sec_xbrl_companyfacts",
        })
        self.assertEqual(out[2]["shares"], 300.0)
        self.assertEqual(out[2]["source"], "sec_xbrl_companyfacts")
        self.assertNotIn(3, out)

    def test_companyfacts_equal_precedence_conflict_fails_closed(self):
        def facts(values):
            return {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {
                "units": {"shares": values},
            }}}}

        base = {"end": "2026-03-31", "filed": "2026-04-20", "form": "10-Q", "accn": "same"}
        conflict = facts([{**base, "val": 100}, {**base, "val": 900}])
        duplicate = facts([{**base, "val": 100}, {**base, "val": 100}])

        self.assertIsNone(_mod._companyfacts_share_record(
            conflict, decision_date="20260629", price_basis_date="20260626",
        ))
        accepted = _mod._companyfacts_share_record(
            duplicate, decision_date="20260629", price_basis_date="20260626",
        )
        self.assertEqual(accepted["shares"], 100.0)


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

    def test_server_5xx_raises_not_skipped_to_older_price_day(self):
        import urllib.error

        def fake(date, key):
            if date == "2026-06-26":
                raise urllib.error.HTTPError(None, 503, "service unavailable", {}, None)
            return [{"T": "AAPL", "c": 10.0, "v": 600_000}]

        with patch.object(_mod, "_massive_grouped_for_date", side_effect=fake):
            with self.assertRaises(RuntimeError) as ctx:
                _mod.fetch_massive_window("k", ["2026-06-26", "2026-06-25"], window=1, min_days=1)
        self.assertIn("503", str(ctx.exception))
        self.assertIn("not a missing trading day", str(ctx.exception))

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


class TestFetchMassiveTickerOverview(unittest.TestCase):
    def test_requests_iso_price_basis_and_accepts_only_matching_positive_cap(self):
        class Resp:
            def read(self):
                return json.dumps({"results": {"ticker": "COIN", "market_cap": 1.2e11}}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch.object(_mod.urllib.request, "urlopen", return_value=Resp()) as urlopen:
            out = _mod._massive_ticker_overview_for_date("COIN", "20260807", "key")

        self.assertEqual(out["market_cap"], 1.2e11)
        request = urlopen.call_args.args[0]
        self.assertIn("/v3/reference/tickers/COIN", request.full_url)
        self.assertIn("date=2026-08-07", request.full_url)

    def test_exact_residual_identity_positive_cap_and_bounded_429_retry(self):
        responses = [
            _mod.urllib.error.HTTPError(None, 429, "rate", {}, None),
            {"ticker": "COIN", "market_cap": 1.2e11},
            {"ticker": "MSTR", "market_cap": 3.0e11},
        ]
        stats = {}
        sleeps = []

        def fake(ticker, price_basis_date, key):
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        with patch.object(_mod, "_massive_ticker_overview_for_date", side_effect=fake):
            out = _mod.fetch_massive_ticker_overview(
                ["COIN", "MSTR"], "20260807", "key", stats_out=stats, sleep_func=sleeps.append,
            )

        self.assertEqual(out, {"COIN": 1.2e11, "MSTR": 3.0e11})
        self.assertEqual(stats["actual_request_count"], 3)
        self.assertEqual(sleeps, [_mod.MASSIVE_RATE_LIMIT_RETRY_SECONDS, _mod.MASSIVE_GROUPED_REQUEST_INTERVAL_SECONDS])

    def test_zero_negative_nan_infinity_and_bad_identity_remain_unresolved(self):
        responses = [
            {"ticker": "A", "market_cap": 0},
            {"ticker": "B", "market_cap": -1},
            {"ticker": "C", "market_cap": float("nan")},
            {"ticker": "D", "market_cap": float("inf")},
            {"ticker": "OTHER", "market_cap": 1e9},
        ]

        with patch.object(_mod, "_massive_ticker_overview_for_date", side_effect=lambda *args: responses.pop(0)):
            out = _mod.fetch_massive_ticker_overview(
                ["A", "B", "C", "D", "E"], "20260807", "key", sleep_func=lambda _: None,
            )

        self.assertEqual(out, {})

    def test_non_429_failures_stay_unresolved_but_physical_calls_are_observable(self):
        stats = {}
        with patch.object(_mod, "_massive_ticker_overview_for_date", side_effect=RuntimeError("offline failure")):
            out = _mod.fetch_massive_ticker_overview(
                ["COIN", "MSTR"], "20260807", "key", stats_out=stats, sleep_func=lambda _: None,
            )

        self.assertEqual(out, {})
        self.assertEqual(stats["actual_request_count"], 2)


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

    def test_yfinance_snapshot_cap_rescues(self):
        sec = {"GOOGL": {"cik": 1652044, "exchange": "NASDAQ"}}
        rows = self._rows(
            sec, {}, {"GOOGL": _md(340.0, 50_000_000.0)},
            yfinance_caps={"GOOGL": {
                "market_cap": 2e12,
                "market_cap_source": _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT,
                "market_cap_source_observed_at": "2026-06-29T12:00:00+00:00",
                "market_cap_clock_semantics": _mod.YFINANCE_CLOCK_MARKET_CAP_SNAPSHOT,
            }},
        )
        self.assertTrue(rows[0]["eligible"])
        self.assertEqual(rows[0]["market_cap_source"], _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT)

    def test_massive_overview_cap_rescues_after_yfinance(self):
        sec = {"COIN": {"cik": 9001, "exchange": "NASDAQ"}}
        rows = self._rows(
            sec, {}, {"COIN": _md(200.0, 50_000_000.0)},
            massive_caps={"COIN": 2e11},
        )
        self.assertTrue(rows[0]["eligible"])
        self.assertEqual(rows[0]["market_cap_source"], "massive_ticker_overview")
        self.assertEqual(rows[0]["lineage"]["market_cap_source"], "massive_ticker_overview")

    def test_companyfacts_lineage_is_retained_and_validated(self):
        sec = {"MSTR": {"cik": 9002, "exchange": "NASDAQ"}}
        shares = {
            9002: {
                "shares": 200_000_000, "end": "2026-03-31", "filed": "2026-04-20",
                "accession": "00009002-26-000001", "accn": "00009002-26-000001",
                "source": "sec_xbrl_companyfacts",
            }
        }
        rows = self._rows(sec, shares, {"MSTR": _md(200.0, 50_000_000.0)})
        self.assertEqual(rows[0]["lineage"]["shares_source"], "sec_xbrl_companyfacts")
        self.assertEqual(rows[0]["lineage"]["shares_accession"], "00009002-26-000001")
        artifact = _mod.build_candidate_artifact(
            rows=rows, decision_date="20260629", price_basis_date="20260626", used_date="2026-06-26",
            observed_window_dates=["2026-06-26"], generated_at="2026-06-29T12:00:00+00:00",
            calendar_verification_status="pending_authoritative_cross_check",
        )
        _mod.validate_candidate_artifact(artifact, expected_decision_date="20260629", governance=self.gov)

    def test_invalid_fallback_caps_are_not_used(self):
        sec = {"COIN": {"cik": 9001, "exchange": "NASDAQ"}}
        rows = self._rows(
            sec, {}, {"COIN": _md(200.0, 50_000_000.0)},
            yfinance_caps={"COIN": {"market_cap": 0}}, massive_caps={"COIN": float("nan")},
        )
        self.assertFalse(rows[0]["eligible"])
        self.assertEqual(rows[0]["market_cap_source"], "none")
        self.assertIsNone(rows[0]["market_cap_usd"])

    def test_overflowing_sec_shares_times_close_falls_through_to_valid_fallback(self):
        sec = {"GIANT": {"cik": 9010, "exchange": "NASDAQ"}}
        shares = {9010: {"shares": 1e308, "end": "2026-03-31", "source": "sec_xbrl_frames"}}
        market_data = {"GIANT": _md(1e308, 50_000_000.0)}

        rows = self._rows(sec, shares, market_data, yfinance_caps={"GIANT": {
            "market_cap": 1e9,
            "market_cap_source": _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT,
            "market_cap_source_observed_at": "2026-06-29T12:00:00+00:00",
            "market_cap_clock_semantics": _mod.YFINANCE_CLOCK_MARKET_CAP_SNAPSHOT,
        }})
        self.assertEqual(rows[0]["market_cap_source"], _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT)
        self.assertEqual(rows[0]["market_cap_usd"], 1e9)

        unresolved_rows = self._rows(sec, shares, market_data)
        self.assertEqual(unresolved_rows[0]["market_cap_source"], "none")
        self.assertIsNone(unresolved_rows[0]["market_cap_usd"])
        artifact = _mod.build_candidate_artifact(
            rows=unresolved_rows, decision_date="20260629", price_basis_date="20260626", used_date="2026-06-26",
            observed_window_dates=["2026-06-26"], generated_at="2026-06-29T12:00:00+00:00",
            calendar_verification_status="pending_authoritative_cross_check",
        )
        _mod.validate_candidate_artifact(artifact, expected_decision_date="20260629", governance=self.gov)

    def test_sec_shares_precedence_over_yfinance(self):
        sec = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}
        rows = self._rows(
            sec, shares, {"AAPL": _md(200.0, 50_000_000.0)},
            yfinance_caps={"AAPL": {
                "market_cap": 1.0,
                "market_cap_source": _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT,
                "market_cap_source_observed_at": "2026-06-29T12:00:00+00:00",
                "market_cap_clock_semantics": _mod.YFINANCE_CLOCK_MARKET_CAP_SNAPSHOT,
            }}, massive_caps={"AAPL": 2e12},
        )
        self.assertTrue(rows[0]["eligible"])               # SEC shares used, bogus FMP cap ignored
        self.assertEqual(rows[0]["market_cap_source"], "sec_shares_x_close")

    def test_yfinance_precedence_over_later_massive_overview(self):
        sec = {"COIN": {"cik": 9001, "exchange": "NASDAQ"}}
        rows = self._rows(
            sec, {}, {"COIN": _md(200.0, 50_000_000.0)},
            yfinance_caps={"COIN": {
                "market_cap": 1e11,
                "market_cap_source": _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT,
                "market_cap_source_observed_at": "2026-06-29T12:00:00+00:00",
                "market_cap_clock_semantics": _mod.YFINANCE_CLOCK_MARKET_CAP_SNAPSHOT,
            }}, massive_caps={"COIN": 2e11},
        )
        self.assertEqual(rows[0]["market_cap_source"], _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT)
        self.assertEqual(rows[0]["market_cap_usd"], 1e11)

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
                          "shares_source", "market_cap_source", "shares_end"})
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

    def _yfinance_rows(self, yfinance_caps):
        # one ticker with NO SEC shares (so the producer falls back to yfinance / none precedence)
        sec = {"NOSEC": {"cik": 999, "exchange": "NYSE"}}
        md = {"NOSEC": _md(50.0, 20_000_000.0)}
        return _mod.apply_pass1(sec, {}, md, governance=self.gov, yfinance_caps=yfinance_caps,
                                as_of="2026-06-26", observed_at="2026-06-29T12:00:00+00:00")

    def _yfinance_artifact(self, rows):
        return _mod.build_candidate_artifact(
            rows=rows, decision_date="20260629", price_basis_date="20260626", used_date="2026-06-26",
            observed_window_dates=["2026-06-26"], generated_at="2026-06-29T12:00:00+00:00",
            calendar_verification_status="pending_authoritative_cross_check")

    def test_validate_rejects_forged_yfinance_source_when_sec_available(self):
        # Codex cc_r1_v1 residual: SEC shares+price available → producer uses sec_shares_x_close; forging
        # market_cap_source (and matching lineage) to yfinance snapshot must be REJECTED (producer precedence).
        art = self._artifact()
        for r in art["rows"]:
            if r["ticker"] == "AAPL":   # SEC shares 15e9 + price 200 → sec_shares_x_close
                r["market_cap_source"] = _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT
                r["lineage"]["market_cap_source"] = _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT
                r["lineage"]["market_cap_source_observed_at"] = "2026-06-29T12:00:00+00:00"
                r["lineage"]["market_cap_clock_semantics"] = _mod.YFINANCE_CLOCK_MARKET_CAP_SNAPSHOT
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(art, expected_decision_date="20260629", governance=self.gov)

    def test_validate_accepts_yfinance_snapshot_when_sec_unavailable(self):
        # yfinance snapshot POSITIVE: no SEC shares + finite snapshot cap is accepted with retrieval lineage.
        rows = self._yfinance_rows({"NOSEC": {
            "market_cap": 5e8,
            "market_cap_source": _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT,
            "market_cap_source_observed_at": "2026-06-29T12:00:00+00:00",
            "market_cap_clock_semantics": _mod.YFINANCE_CLOCK_MARKET_CAP_SNAPSHOT,
        }})
        self.assertEqual(rows[0]["market_cap_source"], _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT)
        self.assertIsNone(rows[0]["shares"])
        _mod.validate_candidate_artifact(self._yfinance_artifact(rows), expected_decision_date="20260629", governance=self.gov)

    def test_validate_accepts_yfinance_shares_times_delayed_close(self):
        rows = _mod.apply_pass1(
            {"NOSEC": {"cik": 999, "exchange": "NYSE"}}, {},
            {"NOSEC": _md(50.0, 20_000_000.0, price_as_of="2026-06-25")},
            governance=self.gov,
            yfinance_caps={"NOSEC": {
                "market_cap": 50e9,
                "market_cap_source": _mod.YFINANCE_SOURCE_SHARES_X_MASSIVE_CLOSE,
                "market_cap_basis_shares": 1e9,
                "market_cap_source_observed_at": "2026-06-29T12:00:00+00:00",
                "market_cap_clock_semantics": _mod.YFINANCE_CLOCK_SHARES_X_MASSIVE_CLOSE,
            }},
            as_of="2026-06-25", observed_at="2026-06-29T12:00:00+00:00",
        )
        self.assertEqual(rows[0]["market_cap_source"], _mod.YFINANCE_SOURCE_SHARES_X_MASSIVE_CLOSE)
        _mod.validate_candidate_artifact(
            _mod.build_candidate_artifact(
                rows=rows, decision_date="20260629", price_basis_date="20260626", used_date="2026-06-25",
                observed_window_dates=["2026-06-25"], generated_at="2026-06-29T12:00:00+00:00",
                calendar_verification_status="pending_authoritative_cross_check",
            ),
            expected_decision_date="20260629", governance=self.gov,
        )

    def test_validate_accepts_massive_overview_fallback_when_sec_and_yfinance_unavailable(self):
        rows = _mod.apply_pass1(
            {"COIN": {"cik": 999, "exchange": "NASDAQ"}}, {},
            {"COIN": _md(50.0, 20_000_000.0)}, governance=self.gov,
            massive_caps={"COIN": 5e8}, as_of="2026-06-26", observed_at="2026-06-29T12:00:00+00:00",
        )
        self.assertEqual(rows[0]["market_cap_source"], "massive_ticker_overview")
        _mod.validate_candidate_artifact(
            self._yfinance_artifact(rows), expected_decision_date="20260629", governance=self.gov,
        )

    def test_validate_accepts_none_source_when_no_market_cap(self):
        # none POSITIVE: no SEC shares + no yfinance cap → market_cap_source=none, market_cap_usd=None accepted.
        rows = self._yfinance_rows({})
        self.assertEqual(rows[0]["market_cap_source"], "none")
        self.assertIsNone(rows[0]["market_cap_usd"])
        _mod.validate_candidate_artifact(self._yfinance_artifact(rows), expected_decision_date="20260629", governance=self.gov)

    def test_validate_rejects_none_source_with_finite_market_cap(self):
        # none NEGATIVE boundary: market_cap_source=none must not carry a finite market_cap (forge rejected).
        rows = self._yfinance_rows({})
        rows[0]["market_cap_usd"] = 5e8   # forged finite cap while market_cap_source stays "none"
        with self.assertRaises(RuntimeError):
            _mod.validate_candidate_artifact(self._yfinance_artifact(rows), expected_decision_date="20260629", governance=self.gov)


class _FakeYFinanceTicker:
    def __init__(self, info):
        self.info = info


class _FakeYFinanceModule:
    def __init__(self, infos):
        self.infos = infos
        self.calls = []

    def Ticker(self, ticker):
        self.calls.append(ticker)
        value = self.infos[ticker]
        if isinstance(value, Exception):
            raise value
        return _FakeYFinanceTicker(value)


class TestFetchYfinanceMarketCaps(unittest.TestCase):
    def _fetch(self, infos, *, market_data=None, tickers=None, stats=None, sleeps=None, pace_seconds=0.2):
        module = _FakeYFinanceModule(infos)
        market_data = market_data or {ticker: _md(100.0, 20_000_000.0) for ticker in infos}
        sleeps = sleeps if sleeps is not None else []
        out = _mod.fetch_yfinance_market_caps(
            tickers or list(infos), market_data, "20260626", market_cap_floor=300_000_000.0,
            observed_at="2026-06-29T12:00:00+00:00", client=_mod._YFinanceClient(module),
            sleep_func=sleeps.append, pace_seconds=pace_seconds, stats_out=stats,
        )
        return out, module

    def test_shares_times_price_basis_close(self):
        stats = {}
        out, module = self._fetch({"AAPL": {"symbol": "AAPL", "sharesOutstanding": 4_000_000_000}} , stats=stats)
        self.assertEqual(module.calls, ["AAPL"])
        self.assertEqual(out["AAPL"]["market_cap"], 4e11)
        self.assertEqual(out["AAPL"]["market_cap_source"], _mod.YFINANCE_SOURCE_SHARES_X_MASSIVE_CLOSE)
        self.assertEqual(out["AAPL"]["market_cap_basis_shares"], 4e9)
        self.assertEqual(stats["logical_ticker_attempt_count"], 1)
        self.assertEqual(stats["rescued_count"], 1)

    def test_shares_times_delayed_massive_close(self):
        out, _ = self._fetch(
            {"AAPL": {"symbol": "AAPL", "sharesOutstanding": 4_000_000_000}},
            market_data={"AAPL": _md(100.0, 20_000_000.0, price_as_of="2026-06-25")},
        )
        self.assertEqual(out["AAPL"]["market_cap"], 4e11)
        self.assertEqual(out["AAPL"]["market_cap_source"], _mod.YFINANCE_SOURCE_SHARES_X_MASSIVE_CLOSE)

    def test_market_cap_snapshot_when_values_cross_governance_threshold(self):
        out, _ = self._fetch({"ADS": {
            "symbol": "ADS", "sharesOutstanding": 1_000_000, "marketCap": 500_000_000,
        }}, market_data={"ADS": _md(100.0, 20_000_000.0)})
        self.assertEqual(out["ADS"]["market_cap"], 500_000_000)
        self.assertEqual(out["ADS"]["market_cap_source"], _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT)
        self.assertEqual(out["ADS"]["market_cap_clock_semantics"], _mod.YFINANCE_CLOCK_MARKET_CAP_SNAPSHOT)

    def test_both_missing_remains_unresolved(self):
        stats = {}
        out, _ = self._fetch({"MISS": {"symbol": "MISS"}}, stats=stats)
        self.assertEqual(out, {})
        self.assertEqual(stats["rescued_count"], 0)

    def test_identity_mismatch_remains_unresolved(self):
        stats = {}
        out, _ = self._fetch({"COIN": {"symbol": "OTHER", "marketCap": 2e12}}, stats=stats)
        self.assertEqual(out, {})
        self.assertEqual(stats["identity_mismatch_count"], 1)

    def test_bad_values_and_ordinary_exception_are_noncritical(self):
        stats = {}
        out, _ = self._fetch({"BAD": {"symbol": "BAD", "marketCap": -1}, "ERR": RuntimeError("down")}, stats=stats)
        self.assertEqual(out, {})
        self.assertEqual(stats["ordinary_failure_count"], 2)

    def test_rate_or_crumb_signal_stops_current_and_remaining(self):
        stats = {}
        out, module = self._fetch({"A": {"symbol": "A", "marketCap": 1e9},
                                   "B": RuntimeError("Too Many Requests: crumb invalid"),
                                   "C": {"symbol": "C", "marketCap": 1e9}}, stats=stats)
        self.assertEqual(set(out), {"A"})
        self.assertEqual(module.calls, ["A", "B"])
        self.assertTrue(stats["stopped_on_rate_limit_or_crumb"])
        self.assertEqual(stats["logical_ticker_attempt_count"], 2)

    def test_successful_info_ignores_benign_rate_limit_log(self):
        class NoisyModule:
            def __init__(self):
                self.calls = []

            def Ticker(self, ticker):
                self.calls.append(ticker)

                class NoisyTicker:
                    @property
                    def info(self):
                        print("Yahoo Finance may rate-limit or block this client.", file=sys.stderr)
                        return {"symbol": ticker, "marketCap": 1e9}

                return NoisyTicker()

        module = NoisyModule()
        stats = {}
        sleeps = []
        out = _mod.fetch_yfinance_market_caps(
            ["A", "B"], {"A": _md(100.0, 20_000_000.0), "B": _md(100.0, 20_000_000.0)},
            "20260626", market_cap_floor=300_000_000.0,
            observed_at="2026-06-29T12:00:00+00:00", client=_mod._YFinanceClient(module),
            sleep_func=sleeps.append, stats_out=stats,
        )
        self.assertEqual(set(out), {"A", "B"})
        self.assertEqual(module.calls, ["A", "B"])
        self.assertEqual(sleeps, [0.2])
        self.assertFalse(stats["stopped_on_rate_limit_or_crumb"])
        self.assertEqual(stats["rate_limit_or_crumb_failure_count"], 0)

    def test_crumb_query_parameter_in_ordinary_http_error_does_not_stop_remaining(self):
        stats = {}
        out, module = self._fetch({
            "A": RuntimeError(
                "404 Client Error: Not Found for url: "
                "https://query2.finance.yahoo.com/v7/finance/quote?symbols=A&crumb=Ab1cD"
            ),
            "B": {"symbol": "B", "marketCap": 1e9},
        }, stats=stats)
        self.assertEqual(set(out), {"B"})
        self.assertEqual(module.calls, ["A", "B"])
        self.assertFalse(stats["stopped_on_rate_limit_or_crumb"])
        self.assertEqual(stats["rate_limit_or_crumb_failure_count"], 0)
        self.assertEqual(stats["ordinary_failure_count"], 1)

    def test_rate_limit_in_exception_cause_stops_current_and_remaining(self):
        try:
            try:
                raise RuntimeError("HTTP 429")
            except RuntimeError as cause:
                raise RuntimeError("wrapped request failure") from cause
        except RuntimeError as caught:
            wrapped_exc = caught

        stats = {}
        out, module = self._fetch({"A": wrapped_exc, "B": {"symbol": "B", "marketCap": 1e9}}, stats=stats)
        self.assertEqual(out, {})
        self.assertEqual(module.calls, ["A"])
        self.assertTrue(stats["stopped_on_rate_limit_or_crumb"])
        self.assertEqual(stats["rate_limit_or_crumb_failure_count"], 1)

    def test_fixed_pacing_skips_first_attempt(self):
        sleeps = []
        self._fetch({"A": {"symbol": "A", "marketCap": 1e9}, "B": {"symbol": "B", "marketCap": 1e9}}, sleeps=sleeps)
        self.assertEqual(sleeps, [0.2])

    def test_missing_dependency_degrades_without_provider_call(self):
        stats = {}
        out = _mod.fetch_yfinance_market_caps(
            ["A"], {"A": _md(100.0, 20_000_000.0)}, "20260626", market_cap_floor=300_000_000.0,
            observed_at="2026-06-29T12:00:00+00:00", importer=lambda _: (_ for _ in ()).throw(ModuleNotFoundError()),
            stats_out=stats,
        )
        self.assertEqual(out, {})
        self.assertTrue(stats["dependency_missing"])


class TestProblem7MarketCapChain(unittest.TestCase):
    def setUp(self):
        self.gov = _load_gov()
        self.tickers = [f"P{idx:02d}X" for idx in range(43)]
        self.sec = {
            ticker: {"cik": 700000 + idx, "exchange": "NASDAQ"}
            for idx, ticker in enumerate(self.tickers)
        }
        self.market_data = {
            ticker: _md(100.0 + idx, 25_000_000.0)
            for idx, ticker in enumerate(self.tickers)
        }

    def test_layer_target_guard_rejects_a_truncated_residual(self):
        with self.assertRaisesRegex(RuntimeError, "exactly equal"):
            _mod._assert_exact_market_cap_layer_targets(
                ["AAA", "BBB"], ["AAA"], layer="Massive ticker-overview fallback",
            )

    def test_43_targets_complete_yfinance_then_exact_massive_residual_without_loss(self):
        initial_rows = _mod.apply_pass1(
            self.sec, {}, self.market_data, governance=self.gov,
            as_of="2026-08-07", observed_at="2026-08-10T12:00:00+00:00",
        )
        initial = _mod.summarize_rows(initial_rows)["needs_market_cap"]
        self.assertEqual(initial, self.tickers)

        yfinance_module = _FakeYFinanceModule({
            ticker: ({"symbol": ticker, "marketCap": 1e9} if ticker in self.tickers[:40]
                     else {"symbol": ticker})
            for ticker in self.tickers
        })
        yfinance_stats = {}
        yfinance_caps = _mod.fetch_yfinance_market_caps(
            initial, self.market_data, "20260807", market_cap_floor=300_000_000.0,
            observed_at="2026-08-10T12:00:00+00:00", client=_mod._YFinanceClient(yfinance_module),
            sleep_func=lambda _: None, stats_out=yfinance_stats,
        )
        self.assertEqual(yfinance_module.calls, self.tickers)
        self.assertEqual(yfinance_stats["logical_ticker_attempt_count"], 43)
        self.assertEqual(set(yfinance_caps), set(self.tickers[:40]))

        after_yfinance_rows = _mod.apply_pass1(
            self.sec, {}, self.market_data, governance=self.gov, yfinance_caps=yfinance_caps,
            as_of="2026-08-07", observed_at="2026-08-10T12:00:00+00:00",
        )
        after_yfinance = _mod.summarize_rows(after_yfinance_rows)["needs_market_cap"]
        self.assertEqual(after_yfinance, self.tickers[40:])

        overview_calls = []

        def overview_fake(ticker, price_basis_date, key):
            overview_calls.append((ticker, price_basis_date))
            return {"ticker": ticker, "market_cap": 2e9}

        overview_stats = {}
        with patch.object(_mod, "_massive_ticker_overview_for_date", side_effect=overview_fake):
            massive_caps = _mod.fetch_massive_ticker_overview(
                after_yfinance, "20260807", "key", stats_out=overview_stats, sleep_func=lambda _: None,
            )
        self.assertEqual(overview_calls, [(ticker, "20260807") for ticker in self.tickers[40:]])
        self.assertEqual(overview_stats["actual_request_count"], 3)

        final_rows = _mod.apply_pass1(
            self.sec, {}, self.market_data, governance=self.gov, yfinance_caps=yfinance_caps,
            massive_caps=massive_caps, as_of="2026-08-07", observed_at="2026-08-10T12:00:00+00:00",
        )
        final = _mod.summarize_rows(final_rows)
        self.assertEqual(final["needs_market_cap"], [])
        self.assertEqual(set(_mod.eligible_tickers_from_rows(final_rows)), set(self.tickers))
        completion = _mod.build_market_cap_completion(
            initial_needs=initial, after_companyfacts_needs=initial, after_yfinance_needs=after_yfinance,
            final_needs=final["needs_market_cap"], sec_companyfacts_target_count=0,
            sec_companyfacts_request_count=0, yfinance_attempted_count=yfinance_stats["logical_ticker_attempt_count"],
            massive_overview_attempted_count=len(after_yfinance),
        )
        self.assertEqual(completion["needed_count"], 43)
        self.assertEqual(completion["yfinance_rescued_count"], 40)
        self.assertEqual(completion["massive_overview_rescued_count"], 3)
        self.assertEqual(completion["final_unresolved_count"], 0)

    def test_failed_final_residual_stays_unresolved_and_conserved(self):
        initial_rows = _mod.apply_pass1(
            self.sec, {}, self.market_data, governance=self.gov,
            as_of="2026-08-07", observed_at="2026-08-10T12:00:00+00:00",
        )
        initial = _mod.summarize_rows(initial_rows)["needs_market_cap"]
        yfinance_caps = {ticker: {
            "market_cap": 1e9,
            "market_cap_source": _mod.YFINANCE_SOURCE_MARKET_CAP_SNAPSHOT,
            "market_cap_source_observed_at": "2026-08-10T12:00:00+00:00",
            "market_cap_clock_semantics": _mod.YFINANCE_CLOCK_MARKET_CAP_SNAPSHOT,
        } for ticker in initial[:40]}
        after_yfinance = _mod.summarize_rows(_mod.apply_pass1(
            self.sec, {}, self.market_data, governance=self.gov, yfinance_caps=yfinance_caps,
            as_of="2026-08-07", observed_at="2026-08-10T12:00:00+00:00",
        ))["needs_market_cap"]

        def overview_fake(ticker, price_basis_date, key):
            return {"ticker": ticker, "market_cap": 2e9} if ticker != self.tickers[-1] else {"ticker": ticker, "market_cap": 0}

        with patch.object(_mod, "_massive_ticker_overview_for_date", side_effect=overview_fake):
            massive_caps = _mod.fetch_massive_ticker_overview(
                after_yfinance, "20260807", "key", sleep_func=lambda _: None,
            )
        final_rows = _mod.apply_pass1(
            self.sec, {}, self.market_data, governance=self.gov, yfinance_caps=yfinance_caps,
            massive_caps=massive_caps, as_of="2026-08-07", observed_at="2026-08-10T12:00:00+00:00",
        )
        final = _mod.summarize_rows(final_rows)
        self.assertEqual(final["needs_market_cap"], [self.tickers[-1]])
        completion = _mod.build_market_cap_completion(
            initial_needs=initial, after_companyfacts_needs=initial, after_yfinance_needs=after_yfinance,
            final_needs=final["needs_market_cap"], sec_companyfacts_target_count=0,
            sec_companyfacts_request_count=0, yfinance_attempted_count=40,
            massive_overview_attempted_count=3,
        )
        self.assertEqual(completion["final_unresolved_count"], len(final["needs_market_cap"]))
        self.assertEqual(
            completion["needed_count"],
            completion["yfinance_rescued_count"] + completion["massive_overview_rescued_count"]
            + completion["final_unresolved_count"],
        )

    def test_completion_rejects_yfinance_rescue_above_logical_attempts(self):
        with self.assertRaisesRegex(RuntimeError, "call counts exceed"):
            _mod.build_market_cap_completion(
                initial_needs=["A"], after_companyfacts_needs=["A"], after_yfinance_needs=[], final_needs=[],
                sec_companyfacts_target_count=0, sec_companyfacts_request_count=0,
                yfinance_attempted_count=0, massive_overview_attempted_count=0,
            )


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
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._sample_root_context = temporary_us_short_directory(ROOT, Path("provider_samples"))
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        self._orig_candidate_list_dir = _mod.CANDIDATE_LIST_DIR
        self._orig_raw_root_dir = _mod.RAW_ROOT_DIR
        self._orig_summary_dir = _mod.SUMMARY_DIR
        _mod.CANDIDATE_LIST_DIR = self.state_root
        _mod.RAW_ROOT_DIR = self.sample_root
        _mod.SUMMARY_DIR = self.sample_root
        self.addCleanup(setattr, _mod, "CANDIDATE_LIST_DIR", self._orig_candidate_list_dir)
        self.addCleanup(setattr, _mod, "RAW_ROOT_DIR", self._orig_raw_root_dir)
        self.addCleanup(setattr, _mod, "SUMMARY_DIR", self._orig_summary_dir)
        self._orig_git_check_ignored = _mod._git_check_ignored
        state_root = self.state_root.resolve()

        def _git_check_ignored_for_private_test(path):
            resolved = Path(path).resolve()
            if resolved == state_root or state_root in resolved.parents:
                return True
            return self._orig_git_check_ignored(path)

        _mod._git_check_ignored = _git_check_ignored_for_private_test
        self.addCleanup(setattr, _mod, "_git_check_ignored", self._orig_git_check_ignored)

        def no_companyfacts(sec_ua, ciks, *, decision_date, price_basis_date, stats_out=None):
            if stats_out is not None:
                stats_out["actual_request_count"] = len({cik for cik in ciks if type(cik) is int and cik > 0})
            return {}

        def no_massive_overview(tickers, price_basis_date, key, *, stats_out=None, sleep_func=None):
            if stats_out is not None:
                stats_out["actual_request_count"] = len(tickers)
            return {}

        def no_yfinance_market_caps(tickers, market_data, price_basis_date, *, market_cap_floor,
                                    observed_at, **kwargs):
            stats_out = kwargs.get("stats_out")
            if stats_out is not None:
                stats_out.update({
                    "logical_ticker_attempt_count": 0, "rescued_count": 0,
                    "shares_x_close_count": 0, "market_cap_snapshot_count": 0,
                    "identity_mismatch_count": 0, "ordinary_failure_count": 0,
                    "rate_limit_or_crumb_failure_count": 0,
                    "stopped_on_rate_limit_or_crumb": False, "dependency_missing": True,
                })
            return {}

        self._offline_companyfacts_patch = patch.object(
            _mod, "fetch_sec_companyfacts", side_effect=no_companyfacts,
        )
        self._offline_massive_overview_patch = patch.object(
            _mod, "fetch_massive_ticker_overview", side_effect=no_massive_overview,
        )
        self._offline_yfinance_patch = patch.object(
            _mod, "fetch_yfinance_market_caps", side_effect=no_yfinance_market_caps,
        )
        self._offline_companyfacts_patch.start()
        self._offline_massive_overview_patch.start()
        self._offline_yfinance_patch.start()
        self.addCleanup(self._offline_companyfacts_patch.stop)
        self.addCleanup(self._offline_massive_overview_patch.stop)
        self.addCleanup(self._offline_yfinance_patch.stop)

    def test_tracked_20260706_summary_provider_health_fmp_counts_match_recorded_counts(self):
        summary_path = ROOT / "docs" / "us_short_universe_fetch_summary_20260706.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

        needs_market_cap = summary["pass1_result"]["needs_market_cap"]
        fallback = summary["provider_health"]["opportunistic_fallbacks"]["fmp_profile_market_cap"]
        attempted = summary["universe"]["fmp_mktcap_fallback_attempted"]
        rescued = summary["universe"]["fmp_mktcap_fallback_rescued"]
        # The 20260706 evidence summary records its own historical cap; pin it here so current policy changes
        # do not retroactively rewrite frozen evidence.
        free_cap = 240

        self.assertEqual(fallback["unresolved_count"], len(needs_market_cap))
        self.assertEqual(fallback["needed_count"], len(needs_market_cap) + rescued)
        self.assertEqual(fallback["attempted_count"], attempted)
        self.assertEqual(fallback["rescued_count"], rescued)
        self.assertEqual(attempted, min(fallback["needed_count"], free_cap))

    def test_full_offline_run_binds_decision_date_and_recomputes(self):
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"},
                   "LOWADV": {"cik": 5, "exchange": "NYSE"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"},
                  5: {"shares": 1_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000},   # huge ADV
                    {"T": "LOWADV", "c": 10.0, "v": 100}]          # ~$1k/day ADV → below floor

        cand = self.state_root / "candidate_universe_20260629.json"  # canonical for decision_date 20260629 (gitignored)
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
            self.assertEqual(summary["provider_health"]["overall_run_state"], "clean")
            calls = summary["provider_call_evidence"]
            self.assertTrue(calls["network_access_performed"])
            self.assertTrue(calls["provider_calls_performed"])
            self.assertEqual(calls["massive_grouped_daily_calls"], _mod.ADV_WINDOW_TRADING_DAYS)
            self.assertEqual(
                calls["actual_total_calls"],
                calls["sec_ticker_reference_calls"] + calls["nasdaq_halt_feed_calls"]
                + calls["massive_grouped_daily_calls"] + calls["sec_share_frame_calls"]
                + calls["sec_companyfacts_calls"]
                + calls["massive_ticker_overview_calls"],
            )
            self.assertTrue(summary["complete"])
            self.assertEqual(summary["completed_through"], "universe_fetch_and_pass1_completed")
            self.assertEqual(json.loads((tmpp / "sum.json").read_text(encoding="utf-8")), summary)
            self.assertFalse((tmpp / "sum.json.partial").exists())

            artifact = json.loads(cand.read_text(encoding="utf-8"))
        self.assertEqual(artifact["decision_date"], "20260629")
        self.assertEqual(artifact["summary"], _mod.summarize_rows(artifact["rows"]))
        self.assertEqual(artifact["adv_window"]["trading_days"], _mod.ADV_WINDOW_TRADING_DAYS)
        aapl = next(r for r in artifact["rows"] if r["ticker"] == "AAPL")
        self.assertEqual(aapl["adv_days_observed"], _mod.ADV_WINDOW_TRADING_DAYS)
        self.assertTrue(aapl["adv_coverage_ok"])
        self.assertEqual(summary["pass1_result"], {**_mod.summarize_rows(artifact["rows"]),
                                                   "eligible_tickers": ["AAPL"]})

    def test_market_cap_checkpoint_summary_survives_late_failure(self):
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000}]

        cand = self.state_root / "candidate_universe_20260629.json"
        cand.unlink(missing_ok=True)
        self.addCleanup(cand.unlink, missing_ok=True)
        self.addCleanup(cand.with_name(cand.name + ".tmp").unlink, missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            with patch.dict(os.environ, {
                "SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "MASSIVE_SECRET_ZZZ", "FMP_API_KEY": "",
            }), patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value=shares), \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod, "fetch_nasdaq_trade_halt_feed", return_value={
                     "observed": True, "observed_at": "2026-06-29T12:00:00+00:00", "halted_symbols": [],
                 }), patch.object(_mod.time, "sleep"), \
                 patch.object(_mod._sv, "validate_raw_root"), \
                 patch.object(_mod, "build_candidate_artifact",
                              side_effect=RuntimeError("candidate construction failed")):
                with self.assertRaisesRegex(RuntimeError, "candidate construction failed"):
                    _mod.run_fetch(
                        now_et=datetime(2026, 6, 29, 8, 0, 0), summary_path=tmpp / "sum.json",
                        raw_root=tmpp / "raw", candidate_list_path=cand,
                        generated_at="2026-06-29T12:00:00+00:00", confirm_user_authorization=True,
                    )

            partial = json.loads((tmpp / "sum.json").read_text(encoding="utf-8"))

        self.assertEqual(set(partial), {
            "schema_name", "schema_version", "complete", "completed_through", "generated_at", "scope",
            "decision_clock", "market_cap_completion", "market_cap_fallback_observability",
        })
        self.assertEqual(partial["schema_version"], _mod.UNIVERSE_SUMMARY_SCHEMA_VERSION)
        self.assertIs(partial["complete"], False)
        self.assertEqual(partial["completed_through"], "market_cap_completion")
        self.assertEqual(partial["scope"], {"status": "market_cap_completed_universe_incomplete"})
        self.assertEqual(partial["decision_clock"]["decision_date"], "20260629")
        completion = partial["market_cap_completion"]
        self.assertEqual(
            completion["needed_count"],
            completion["sec_companyfacts_rescued_count"]
            + completion["yfinance_rescued_count"]
            + completion["massive_overview_rescued_count"]
            + completion["final_unresolved_count"],
        )
        self.assertFalse(cand.exists())
        for omitted in ("pass1_result", "eligible_tickers", "status_screening", "provider_health", "storage"):
            self.assertNotIn(omitted, partial)

    def test_run_fetch_residual_massive_cap_enters_final_artifact(self):
        sec_map = {"COIN": {"cik": 17299, "exchange": "NASDAQ"}}

        def fake_grouped(date, key):
            return [{"T": "COIN", "c": 200.0, "v": 50_000_000}]

        def fake_companyfacts(sec_ua, ciks, *, decision_date, price_basis_date, stats_out=None):
            self.assertEqual(ciks, [17299])
            if stats_out is not None:
                stats_out["actual_request_count"] = 1
            return {}

        def fake_overview(tickers, price_basis_date, key, *, stats_out=None, sleep_func=None):
            self.assertEqual(tickers, ["COIN"])
            self.assertEqual(price_basis_date, "20260626")
            if stats_out is not None:
                stats_out["actual_request_count"] = 1
            return {"COIN": 2e11}

        cand = self.state_root / "candidate_universe_20260629.json"
        cand.unlink(missing_ok=True)
        self.addCleanup(cand.unlink, missing_ok=True)
        self.addCleanup(cand.with_name(cand.name + ".tmp").unlink, missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            with patch.dict(os.environ, {
                "SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "MASSIVE_SECRET_ZZZ", "FMP_API_KEY": "",
            }), patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value={}) as frame_fetch, \
                 patch.object(_mod, "fetch_sec_companyfacts", side_effect=fake_companyfacts), \
                 patch.object(_mod, "fetch_massive_ticker_overview", side_effect=fake_overview), \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod, "fetch_nasdaq_trade_halt_feed", return_value={
                     "observed": True, "observed_at": "2026-06-29T12:00:00+00:00", "halted_symbols": [],
                 }), patch.object(_mod.time, "sleep"), \
                 patch.object(_mod._sv, "validate_raw_root"):
                summary = _mod.run_fetch(
                    now_et=datetime(2026, 6, 29, 8, 0, 0), summary_path=tmpp / "sum.json",
                    raw_root=tmpp / "raw", candidate_list_path=cand,
                    generated_at="2026-06-29T12:00:00+00:00", confirm_user_authorization=True,
                )
            artifact = json.loads(cand.read_text(encoding="utf-8"))

        self.assertEqual(artifact["eligible_tickers"], ["COIN"])
        self.assertEqual(artifact["rows"][0]["market_cap_source"], "massive_ticker_overview")
        expected_frames = ["CY2026Q1I", "CY2025Q4I", "CY2025Q3I", "CY2025Q2I"]
        self.assertEqual(summary["universe"]["sec_share_frames"], expected_frames)
        self.assertEqual(summary["universe"]["sec_share_frame_count"], 4)
        self.assertEqual(summary["provider_call_evidence"]["sec_share_frames"], expected_frames)
        self.assertEqual(frame_fetch.call_args.kwargs["frames"], expected_frames)
        completion = summary["market_cap_completion"]
        self.assertEqual(completion["needed_count"], 1)
        self.assertEqual(completion["sec_companyfacts_target_count"], 1)
        self.assertEqual(completion["sec_companyfacts_request_count"], 1)
        self.assertEqual(completion["yfinance_attempted_count"], 0)
        self.assertEqual(completion["massive_overview_attempted_count"], 1)
        self.assertEqual(completion["massive_overview_rescued_count"], 1)
        self.assertEqual(completion["final_unresolved_count"], 0)
        self.assertEqual(summary["provider_call_evidence"]["sec_companyfacts_calls"], 1)
        self.assertEqual(summary["provider_call_evidence"]["massive_ticker_overview_calls"], 1)
        self.assertEqual(summary["provider_health"]["overall_run_state"], "usable_with_fallback")
        fallback = summary["provider_health"]["opportunistic_fallbacks"]["yfinance_market_cap"]
        self.assertEqual(fallback["unresolved_after_yfinance_count"], 1)
        self.assertEqual(fallback["unresolved_count"], 0)
        massive_observation = summary["market_cap_fallback_observability"]["massive_ticker_overview"]
        self.assertEqual(massive_observation["target_count"], 1)
        self.assertEqual(massive_observation["physical_http_call_count"], 1)
        self.assertEqual(massive_observation["rescued_count"], 1)
        self.assertEqual(massive_observation["final_unresolved_count"], 0)
        self.assertEqual(massive_observation["outcome"], "all_targets_rescued")

    def test_run_fetch_preserves_frames_over_conflicting_companyfacts_record(self):
        sec_map = {
            "FRAME": {"cik": 101, "exchange": "NASDAQ"},
            "HOLE": {"cik": 102, "exchange": "NYSE"},
        }
        frame_shares = {
            101: {"shares": 2_000_000, "end": "2026-03-31", "source": "sec_xbrl_frames"},
        }

        def fake_grouped(date, key):
            return [
                {"T": "FRAME", "c": 200.0, "v": 50_000_000},
                {"T": "HOLE", "c": 200.0, "v": 50_000_000},
            ]

        def fake_companyfacts(sec_ua, ciks, *, decision_date, price_basis_date, stats_out=None):
            self.assertEqual(ciks, [102])
            if stats_out is not None:
                stats_out["actual_request_count"] = 1
            return {
                101: {"shares": 1_000, "end": "2026-03-31", "filed": "2026-04-20",
                      "accession": "conflict-frame", "accn": "conflict-frame", "source": "sec_xbrl_companyfacts"},
                102: {"shares": 2_000_000, "end": "2026-03-31", "filed": "2026-04-20",
                      "accession": "hole", "accn": "hole", "source": "sec_xbrl_companyfacts"},
            }

        cand = self.state_root / "candidate_universe_20260629.json"
        cand.unlink(missing_ok=True)
        self.addCleanup(cand.unlink, missing_ok=True)
        self.addCleanup(cand.with_name(cand.name + ".tmp").unlink, missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            with patch.dict(os.environ, {
                "SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "MASSIVE_SECRET_ZZZ", "FMP_API_KEY": "",
            }), patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value=frame_shares), \
                 patch.object(_mod, "fetch_sec_companyfacts", side_effect=fake_companyfacts), \
                 patch.object(_mod, "fetch_massive_ticker_overview") as overview, \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod, "fetch_nasdaq_trade_halt_feed", return_value={
                     "observed": True, "observed_at": "2026-06-29T12:00:00+00:00", "halted_symbols": [],
                 }), patch.object(_mod.time, "sleep"), \
                 patch.object(_mod._sv, "validate_raw_root"):
                _mod.run_fetch(
                    now_et=datetime(2026, 6, 29, 8, 0, 0), summary_path=tmpp / "sum.json",
                    raw_root=tmpp / "raw", candidate_list_path=cand,
                    generated_at="2026-06-29T12:00:00+00:00", confirm_user_authorization=True,
                )

        overview.assert_not_called()
        artifact = json.loads(cand.read_text(encoding="utf-8"))
        rows = {row["ticker"]: row for row in artifact["rows"]}
        self.assertEqual(rows["FRAME"]["shares"], 2_000_000.0)
        self.assertEqual(rows["FRAME"]["lineage"]["shares_source"], "sec_xbrl_frames")
        self.assertEqual(rows["FRAME"]["market_cap_source"], "sec_shares_x_close")
        self.assertEqual(rows["HOLE"]["lineage"]["shares_source"], "sec_xbrl_companyfacts")

    def test_run_fetch_sends_the_full_43_residual_to_both_fallback_layers(self):
        tickers = [f"P{idx:02d}X" for idx in range(43)]
        sec_map = {
            ticker: {"cik": 700_000 + idx, "exchange": "NASDAQ"}
            for idx, ticker in enumerate(tickers)
        }
        yfinance_seen = []
        massive_seen = []

        def fake_grouped(date, key):
            return [{"T": ticker, "c": 100.0, "v": 25_000_000} for ticker in tickers]

        def fake_companyfacts(sec_ua, ciks, *, decision_date, price_basis_date, stats_out=None):
            self.assertEqual(ciks, [sec_map[ticker]["cik"] for ticker in tickers])
            if stats_out is not None:
                stats_out["actual_request_count"] = len(ciks)
            return {}

        def fake_yfinance(targets, market_data, price_basis_date, *, market_cap_floor, observed_at,
                          stats_out=None, **kwargs):
            yfinance_seen.append(list(targets))
            self.assertEqual(price_basis_date, "20260626")
            if stats_out is not None:
                stats_out.update({"logical_ticker_attempt_count": len(targets), "rescued_count": 0})
            return {}

        def fake_overview(targets, price_basis_date, key, *, stats_out=None, sleep_func=None):
            massive_seen.append(list(targets))
            self.assertEqual(price_basis_date, "20260626")
            if stats_out is not None:
                stats_out["actual_request_count"] = len(targets)
            return {ticker: 1e9 for ticker in targets}

        cand = self.state_root / "candidate_universe_20260629.json"
        cand.unlink(missing_ok=True)
        self.addCleanup(cand.unlink, missing_ok=True)
        self.addCleanup(cand.with_name(cand.name + ".tmp").unlink, missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            with patch.dict(os.environ, {
                "SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "MASSIVE_SECRET_ZZZ",
            }), patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value={}), \
                 patch.object(_mod, "fetch_sec_companyfacts", side_effect=fake_companyfacts), \
                 patch.object(_mod, "fetch_yfinance_market_caps", side_effect=fake_yfinance), \
                 patch.object(_mod, "fetch_massive_ticker_overview", side_effect=fake_overview), \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod, "fetch_nasdaq_trade_halt_feed", return_value={
                     "observed": True, "observed_at": "2026-06-29T12:00:00+00:00", "halted_symbols": [],
                 }), patch.object(_mod.time, "sleep"), \
                 patch.object(_mod._sv, "validate_raw_root"):
                summary = _mod.run_fetch(
                    now_et=datetime(2026, 6, 29, 8, 0, 0), summary_path=tmpp / "sum.json",
                    raw_root=tmpp / "raw", candidate_list_path=cand,
                    generated_at="2026-06-29T12:00:00+00:00", confirm_user_authorization=True,
                )

        self.assertEqual(yfinance_seen, [tickers])
        self.assertEqual(massive_seen, [tickers])
        artifact = json.loads(cand.read_text(encoding="utf-8"))
        self.assertEqual(artifact["eligible_tickers"], tickers)
        self.assertEqual(summary["market_cap_completion"]["massive_overview_rescued_count"], 43)
        self.assertEqual(summary["market_cap_completion"]["final_unresolved_count"], 0)
        fallback = summary["provider_health"]["opportunistic_fallbacks"]["yfinance_market_cap"]
        self.assertEqual(fallback["unresolved_after_yfinance_count"], 43)
        self.assertEqual(fallback["unresolved_count"], 0)
        massive_observation = summary["market_cap_fallback_observability"]["massive_ticker_overview"]
        self.assertEqual(massive_observation["target_count"], 43)
        self.assertEqual(massive_observation["physical_http_call_count"], 43)
        self.assertEqual(massive_observation["initial_attempt_minimum_pacing_seconds"], 42 * 13.0)
        self.assertEqual(massive_observation["outcome"], "all_targets_rescued")

    def test_run_fetch_records_no_rescue_massive_outcome_without_a_second_health_family(self):
        sec_map = {"COIN": {"cik": 17299, "exchange": "NASDAQ"}}

        def fake_grouped(date, key):
            return [{"T": "COIN", "c": 200.0, "v": 50_000_000}]

        cand = self.state_root / "candidate_universe_20260629.json"
        cand.unlink(missing_ok=True)
        self.addCleanup(cand.unlink, missing_ok=True)
        self.addCleanup(cand.with_name(cand.name + ".tmp").unlink, missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            with patch.dict(os.environ, {
                "SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "MASSIVE_SECRET_ZZZ", "FMP_API_KEY": "",
            }), patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value={}), \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod, "fetch_nasdaq_trade_halt_feed", return_value={
                     "observed": True, "observed_at": "2026-06-29T12:00:00+00:00", "halted_symbols": [],
                 }), patch.object(_mod.time, "sleep"), \
                 patch.object(_mod._sv, "validate_raw_root"):
                summary = _mod.run_fetch(
                    now_et=datetime(2026, 6, 29, 8, 0, 0), summary_path=tmpp / "sum.json",
                    raw_root=tmpp / "raw", candidate_list_path=cand,
                    generated_at="2026-06-29T12:00:00+00:00", confirm_user_authorization=True,
                )

        massive_observation = summary["market_cap_fallback_observability"]["massive_ticker_overview"]
        self.assertEqual(massive_observation["target_count"], 1)
        self.assertEqual(massive_observation["physical_http_call_count"], 1)
        self.assertEqual(massive_observation["rescued_count"], 0)
        self.assertEqual(massive_observation["final_unresolved_count"], 1)
        self.assertEqual(massive_observation["outcome"], "no_target_rescued")
        self.assertFalse(massive_observation["provider_readiness_evidence"])
        self.assertEqual(summary["pass1_result"]["eligible_tickers"], [])

    def test_live_run_wires_status_records_from_sec_reference_and_halt_feed(self):
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"},
                   "HALT": {"cik": 999999, "exchange": "NYSE"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"},
                  999999: {"shares": 1_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000},
                    {"T": "HALT", "c": 20.0, "v": 10_000_000}]

        cand = self.state_root / "candidate_universe_20260629.json"
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

    def test_integrated_eligible_bankruptcy_scan_rebuilds_final_candidate_before_pass2(self):
        """The capstone seam must not emit the preliminary unscreened candidate artifact.

        Scan exactly the preliminary Pass1-eligible set, then rebuild status provenance and eligibility from the
        fresh SEC Item 1.03 screen. A positive bankruptcy row drops out; every surviving eligible row is explicitly
        screened_no_filing. A low-ADV row is never sent to the per-issuer SEC scan.
        """
        sec_map = {
            "AAPL": {"cik": 320193, "exchange": "NASDAQ"},
            "BANKR": {"cik": 123456, "exchange": "NYSE"},
            "LOWADV": {"cik": 999999, "exchange": "NYSE"},
        }
        shares = {
            320193: {"shares": 15_000_000_000, "end": "2026-03-31"},
            123456: {"shares": 1_000_000_000, "end": "2026-03-31"},
            999999: {"shares": 1_000_000_000, "end": "2026-03-31"},
        }
        screen = {
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

        def fake_grouped(date, key):
            return [
                {"T": "AAPL", "c": 200.0, "v": 50_000_000},
                {"T": "BANKR", "c": 20.0, "v": 10_000_000},
                {"T": "LOWADV", "c": 10.0, "v": 100},
            ]

        cand = self.state_root / "candidate_universe_20260629.json"
        cand.unlink(missing_ok=True)
        self.addCleanup(cand.unlink, missing_ok=True)
        self.addCleanup(cand.with_name(cand.name + ".tmp").unlink, missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            with patch.dict(os.environ, {
                "SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "MASSIVE_SECRET_ZZZ", "FMP_API_KEY": "",
            }), patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value=shares), \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod, "fetch_nasdaq_trade_halt_feed", return_value={
                     "observed": True,
                     "observed_at": "2026-06-29T12:00:00+00:00",
                     "halted_symbols": [],
                 }), patch.object(
                     _mod,
                     "fetch_bankruptcy_submissions_for_eligible",
                     return_value=(screen, {
                         "eligible_symbol_count": 2,
                         "sec_company_submissions_calls": 2,
                     }),
                 ) as bankruptcy_fetch, patch.object(_mod.time, "sleep"), \
                 patch.object(_mod._sv, "validate_raw_root"):
                summary = _mod.run_fetch(
                    now_et=datetime(2026, 6, 29, 8, 0, 0),
                    summary_path=tmpp / "sum.json",
                    raw_root=tmpp / "raw",
                    candidate_list_path=cand,
                    generated_at="2026-06-29T12:00:00+00:00",
                    confirm_user_authorization=True,
                    scan_bankruptcy_for_eligible=True,
                )
            artifact = json.loads(cand.read_text(encoding="utf-8"))

        self.assertEqual(
            bankruptcy_fetch.call_args.kwargs["eligible_tickers"],
            ["AAPL", "BANKR"],
        )
        by_ticker = {row["ticker"]: row for row in artifact["rows"]}
        self.assertEqual(artifact["eligible_tickers"], ["AAPL"])
        self.assertEqual(
            by_ticker["AAPL"]["status_provenance"]["flags"]["bankruptcy"]["screen_status"],
            "screened_no_filing",
        )
        self.assertTrue(by_ticker["BANKR"]["bankruptcy"])
        self.assertFalse(by_ticker["BANKR"]["eligible"])
        self.assertEqual(
            summary["status_screening"]["bankruptcy_8k_source"],
            "integrated_eligible_sec_submissions",
        )
        self.assertEqual(summary["status_screening"]["bankruptcy_8k_input_symbol_count"], 2)
        self.assertEqual(summary["provider_call_evidence"]["sec_bankruptcy_submissions_calls"], 2)
        self.assertTrue(all(
            row["status_provenance"]["flags"]["bankruptcy"]["screen_status"] == "screened_no_filing"
            for row in artifact["rows"] if row["eligible"]
        ))

    def test_run_fetch_can_consume_injected_sec_bankruptcy_submissions(self):
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"},
                   "BANKR": {"cik": 123456, "exchange": "NYSE"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"},
                  123456: {"shares": 1_000_000_000, "end": "2026-03-31"}}
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

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000},
                    {"T": "BANKR", "c": 20.0, "v": 10_000_000}]

        cand = self.state_root / "candidate_universe_20260629.json"
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
                    bankruptcy_submissions_by_ticker=submissions_by_ticker,
                )

            artifact = json.loads(cand.read_text(encoding="utf-8"))

        self.assertTrue(summary["status_screening"]["bankruptcy_8k_scan_performed"])
        self.assertEqual(summary["status_screening"]["status_source_outcome"]["per_source"]["sec_8k_item_103"], "ok")
        by_ticker = {row["ticker"]: row for row in artifact["rows"]}
        self.assertFalse(by_ticker["AAPL"]["bankruptcy"])
        self.assertTrue(by_ticker["BANKR"]["bankruptcy"])
        self.assertFalse(by_ticker["BANKR"]["eligible"])
        self.assertIn("status_bankruptcy", by_ticker["BANKR"]["reasons"])
        self.assertEqual(
            by_ticker["BANKR"]["status_provenance"]["flags"]["bankruptcy"]["filing_accession_if_found"],
            "0001140361-26-000001",
        )

    def test_run_fetch_can_consume_merged_gitignored_bankruptcy_screen_paths(self):
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"},
                   "BANKR": {"cik": 123456, "exchange": "NYSE"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"},
                  123456: {"shares": 1_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000},
                    {"T": "BANKR", "c": 20.0, "v": 10_000_000}]

        screen_a = self.state_root / "test_bankruptcy_screen_a_20260629.json"
        screen_b = self.state_root / "test_bankruptcy_screen_b_20260629.json"
        cand = self.state_root / "candidate_universe_20260629.json"
        for p in (screen_a, screen_b, cand):
            p.unlink(missing_ok=True)
            self.addCleanup(p.unlink, missing_ok=True)
            self.addCleanup(p.with_name(p.name + ".tmp").unlink, missing_ok=True)
        screen_a.write_text(json.dumps({
            "observed": True,
            "observed_at": "2026-06-29T11:55:00+00:00",
            "lookback_window": "P90D",
            "by_ticker": {"AAPL": {"screen_status": "screened_no_filing"}},
        }), encoding="utf-8")
        screen_b.write_text(json.dumps({
            "observed": True,
            "observed_at": "2026-06-29T12:00:00+00:00",
            "lookback_window": "P90D",
            "by_ticker": {"BANKR": {
                "screen_status": "bankrupt_8k_found",
                "filing_accession": "0001140361-26-000001",
            }},
        }), encoding="utf-8")

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
                    bankruptcy_screen_paths=[screen_a, screen_b],
                )

            artifact = json.loads(cand.read_text(encoding="utf-8"))

        screening = summary["status_screening"]
        self.assertTrue(screening["bankruptcy_8k_scan_performed"])
        self.assertEqual(screening["bankruptcy_8k_source"], "injected_bankruptcy_screen")
        self.assertEqual(screening["bankruptcy_8k_input_symbol_count"], 2)
        self.assertEqual(screening["bankruptcy_8k_screen_file_count"], 2)
        by_ticker = {row["ticker"]: row for row in artifact["rows"]}
        self.assertEqual(
            by_ticker["AAPL"]["status_provenance"]["flags"]["bankruptcy"]["screen_status"],
            "screened_no_filing",
        )
        self.assertTrue(by_ticker["BANKR"]["bankruptcy"])
        self.assertFalse(by_ticker["BANKR"]["eligible"])
        self.assertIn("status_bankruptcy", by_ticker["BANKR"]["reasons"])

    def test_halt_feed_failure_keeps_halted_unknown_not_clean(self):
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000}]

        cand = self.state_root / "candidate_universe_20260629.json"
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
        self.assertEqual(summary["provider_health"]["status_sources"]["state"], "restricted")
        self.assertEqual(summary["provider_health"]["overall_run_state"], "restricted")

    def test_run_fetch_provider_health_marks_yfinance_fallback_as_opportunistic(self):
        sec_map = {
            "AAPL": {"cik": 320193, "exchange": "NASDAQ"},
            "GOOGL": {"cik": 1652044, "exchange": "NASDAQ"},
            "MSFT": {"cik": 789019, "exchange": "NASDAQ"},
        }
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [
                {"T": "AAPL", "c": 200.0, "v": 50_000_000},
                {"T": "GOOGL", "c": 340.0, "v": 50_000_000},
                {"T": "MSFT", "c": 450.0, "v": 50_000_000},
            ]

        def stopped_yfinance_fetch(tickers, market_data, price_basis_date, *, market_cap_floor, observed_at,
                                   stats_out=None, **kwargs):
            self.assertEqual(tickers, ["GOOGL", "MSFT"])
            if stats_out is not None:
                stats_out.update({
                    "logical_ticker_attempt_count": 1, "rescued_count": 0,
                    "ordinary_failure_count": 1, "rate_limit_or_crumb_failure_count": 1,
                    "stopped_on_rate_limit_or_crumb": True,
                })
            return {}

        cand = self.state_root / "candidate_universe_20260629.json"
        cand.unlink(missing_ok=True)
        self.addCleanup(cand.unlink, missing_ok=True)
        self.addCleanup(cand.with_name(cand.name + ".tmp").unlink, missing_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            with patch.dict(os.environ, {"SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "MASSIVE_SECRET_ZZZ"}), \
                 patch.object(_mod, "fetch_sec_tickers", return_value=sec_map), \
                 patch.object(_mod, "fetch_sec_shares", return_value=shares), \
                 patch.object(_mod, "_massive_grouped_for_date", side_effect=fake_grouped), \
                 patch.object(_mod, "fetch_yfinance_market_caps", side_effect=stopped_yfinance_fetch), \
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

        health = summary["provider_health"]
        self.assertEqual(health["overall_run_state"], "usable_with_fallback")
        self.assertEqual(health["critical_sources"]["massive_grouped_daily"], "clean")
        self.assertEqual(health["critical_sources"]["sec_edgar"], "clean")
        fallback = health["opportunistic_fallbacks"]["yfinance_market_cap"]
        self.assertEqual(fallback["state"], "usable_with_fallback")
        self.assertEqual(fallback["attempted_count"], 1)
        self.assertEqual(fallback["rescued_count"], 0)
        self.assertEqual(fallback["unresolved_count"], 2)
        self.assertEqual(summary["universe"]["yfinance_mktcap_fallback_attempted"], 1)
        self.assertEqual(summary["provider_call_evidence"]["yfinance_info_logical_ticker_attempts"], 1)
        yfinance_observation = summary["market_cap_fallback_observability"]["yfinance_info"]
        self.assertEqual(yfinance_observation["ordinary_failure_count"], 1)
        self.assertEqual(yfinance_observation["rate_limit_or_crumb_failure_count"], 1)
        self.assertTrue(yfinance_observation["stopped_on_rate_limit_or_crumb"])
        self.assertFalse(fallback["provider_readiness_evidence"])
        self.assertTrue(health["critical_failure_no_emit_policy"])
        self.assertFalse(health["provider_selection_or_production_claimed"])

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
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)

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
        self.assertTrue(_mod._git_check_ignored(self.state_root / "candidate_universe_20260629.json"))

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
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._original_candidate_list_dir = _mod.CANDIDATE_LIST_DIR
        _mod.CANDIDATE_LIST_DIR = self.state_root
        self.addCleanup(setattr, _mod, "CANDIDATE_LIST_DIR", self._original_candidate_list_dir)

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
            _mod._validate_candidate_path(self.state_root / "candidate_universe_19000101.json", "20260629")
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

    def test_cli_accepts_repeated_bankruptcy_screen_paths(self):
        args = _mod.parse_args([
            "--bankruptcy-screen-path", "state/us_short/a.json",
            "--bankruptcy-screen-path", "state/us_short/b.json",
        ])
        self.assertEqual(args.bankruptcy_screen_paths, [Path("state/us_short/a.json"), Path("state/us_short/b.json")])

    def test_full_run_non_gitignored_bankruptcy_screen_path_leaves_no_residue(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpp = Path(tmp)
            bad_screen = tmpp / "screen.json"
            bad_screen.write_text(json.dumps({
                "observed": True,
                "observed_at": "2026-06-29T12:00:00+00:00",
                "lookback_window": "P90D",
                "by_ticker": {"AAPL": {"screen_status": "screened_no_filing"}},
            }), encoding="utf-8")
            cand = self.state_root / "candidate_universe_20260629.json"
            cand.unlink(missing_ok=True)
            self.addCleanup(cand.unlink, missing_ok=True)
            self.addCleanup(cand.with_name(cand.name + ".tmp").unlink, missing_ok=True)
            summ = tmpp / "sum.json"

            with patch.dict(os.environ, {"SEC_USER_AGENT": "ua@test", "MASSIVE_API_KEY": "k", "FMP_API_KEY": ""}), \
                 patch.object(_mod, "fetch_sec_tickers", side_effect=AssertionError("must reject before provider fetch")), \
                 patch.object(_mod._sv, "validate_raw_root"):
                with self.assertRaises(RuntimeError) as ctx:
                    _mod.run_fetch(
                        now_et=datetime(2026, 6, 29, 8, 0, 0),
                        summary_path=summ, raw_root=tmpp / "raw",
                        candidate_list_path=cand,
                        generated_at="2026-06-29T12:00:00+00:00", confirm_user_authorization=True,
                        bankruptcy_screen_paths=[bad_screen],
                    )
            self.assertIn("bankruptcy screen", str(ctx.exception).lower())
            self.assertFalse(cand.exists())
            self.assertFalse(cand.with_name(cand.name + ".tmp").exists())
            self.assertFalse(summ.exists())

    def test_bankruptcy_screen_non_string_status_rejected_without_typeerror(self):
        screen_path = self.state_root / f"screen_status_bad_{os.getpid()}_{self._testMethodName}.json"
        self.addCleanup(screen_path.unlink, missing_ok=True)
        for bad_status in ([], {}):
            with self.subTest(screen_status=type(bad_status).__name__):
                screen_path.parent.mkdir(parents=True, exist_ok=True)
                screen_path.write_text(json.dumps({
                    "observed": True,
                    "observed_at": STATUS_OBSERVED_AT,
                    "lookback_window": "P90D",
                    "by_ticker": {
                        "AAPL": {"screen_status": "screened_no_filing"},
                        "MSFT": {"screen_status": bad_status},
                    },
                }), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "invalid screen_status"):
                    _mod._load_bankruptcy_screen_paths(
                        [screen_path],
                        decision_date="20260629",
                        generated_at=STATUS_OBSERVED_AT,
                    )

    def test_full_run_wrong_date_candidate_leaves_no_residue(self):
        # Codex's exact probe: a gitignored but WRONG-DATE candidate path on a 20260629 run must fail closed
        # BEFORE writing the priced artifact or the tracked summary (no candidate/.tmp/summary residue).
        sec_map = {"AAPL": {"cik": 320193, "exchange": "NASDAQ"}}
        shares = {320193: {"shares": 15_000_000_000, "end": "2026-03-31"}}

        def fake_grouped(date, key):
            return [{"T": "AAPL", "c": 200.0, "v": 50_000_000}]

        wrong = self.state_root / "candidate_universe_19000101.json"
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
