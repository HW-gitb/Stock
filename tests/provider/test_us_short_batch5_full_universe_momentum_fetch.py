from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.provider.test_us_short_batch5_full_universe_momentum_producer import (  # noqa: E402
    _ALL_ELIGIBLE,
    _DECISION_DATE,
    _candidate_artifact,
)
from tests.provider.us_short_private_test_root_light import (  # noqa: E402
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_universe_momentum_fetch"
PRODUCER_SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_universe_momentum" / _DECISION_DATE
OVEREXT_PRODUCER_SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_universe_overextension" / _DECISION_DATE
FETCH_MODULE = "runners.us_short_batch5_full_universe_momentum_fetch"
PRODUCER_MODULE = "runners.us_short_batch5_full_universe_momentum_producer"
OVEREXT_PRODUCER_MODULE = "runners.us_short_batch5_full_universe_overextension_producer"

_WANTED = list(_ALL_ELIGIBLE) + ["SPY", "QQQ"]
_NOISE = ["ZZZA", "ZZZB"]          # whole-market noise the fetch must discard (not eligible / not a benchmark)
_BASES = {t: 100.0 + 5.0 * h for h, t in enumerate(_WANTED + _NOISE)}
_EPOCH = date(2020, 1, 1)


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch():
    return importlib.import_module(FETCH_MODULE)


def _day_index(date_iso: str) -> int:
    return (date.fromisoformat(date_iso) - _EPOCH).days


def _fake_grouped(*, tickers=None, only_dates=None):
    """A fake whole-market grouped-daily seam: for each requested date it returns Massive-shaped {T,c,v} rows
    for `tickers` (+ noise), trending by day so momentum has signal. `only_dates` (a set) limits which dates
    return data (to simulate a too-short window)."""
    row_tickers = (tickers if tickers is not None else _WANTED) + _NOISE

    def fetch(date_iso: str):
        if only_dates is not None and date_iso not in only_dates:
            return []
        i = _day_index(date_iso)
        return [
            {"T": t, "c": _BASES[t] + i * (0.1 + 0.01 * h), "v": 1_000_000 + (i % 50)}
            for h, t in enumerate(row_tickers)
        ]

    return fetch


def _fake_grouped_ohlcv(*, tickers=None, only_dates=None):
    """Like _fake_grouped but each Massive row also carries h/l (high/low) around the close, so the cut-2b-iii
    OHLCV reconstruct can build ATR-bearing bars for the §4.3 overextension producer."""
    row_tickers = (tickers if tickers is not None else _WANTED) + _NOISE

    def fetch(date_iso: str):
        if only_dates is not None and date_iso not in only_dates:
            return []
        i = _day_index(date_iso)
        rows = []
        for h, t in enumerate(row_tickers):
            c = _BASES[t] + i * (0.1 + 0.01 * h)
            rows.append({"T": t, "c": c, "h": c + 0.5, "l": c - 0.5, "v": 1_000_000 + (i % 50)})
        return rows

    return fetch


def _fake_grouped_with_dupe():
    """Whole-market feed that emits a SECOND, lower-volume AAPL row each session (a real Massive quirk: >1 row
    for one symbol). The fetch must dedup to the max-volume (primary) print — the sentinel c=1.0 must be dropped."""
    base = _fake_grouped()

    def fetch(date_iso: str):
        rows = base(date_iso)
        if rows:
            rows = rows + [{"T": "AAPL", "c": 1.0, "v": 1.0}]
        return rows

    return fetch


class FullUniverseMomentumFetchTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_full_universe_momentum_fetch"
        )
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        self._producer_sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_full_universe_momentum" / _DECISION_DATE
        )
        self.producer_sample_root = Path(self._producer_sample_root_context.__enter__())
        self.addCleanup(self._producer_sample_root_context.__exit__, None, None, None)
        self._overext_sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_full_universe_overextension" / _DECISION_DATE
        )
        self.overext_sample_root = Path(self._overext_sample_root_context.__enter__())
        self.addCleanup(self._overext_sample_root_context.__exit__, None, None, None)
        universe_fetch = importlib.import_module("runners.us_short_universe_fetch")
        original_git_check_ignored = universe_fetch._git_check_ignored
        state_root = self.state_root.resolve()

        def _git_check_ignored_for_private_test(path):
            resolved = Path(path).resolve()
            if resolved == state_root or state_root in resolved.parents:
                return True
            return original_git_check_ignored(path)

        universe_fetch._git_check_ignored = _git_check_ignored_for_private_test
        self.addCleanup(setattr, universe_fetch, "_git_check_ignored", original_git_check_ignored)
        self.slug = f"test_full_universe_momentum_fetch_{os.getpid()}_{self._testMethodName}"
        self.candidate = self.state_root / f"{self.slug}_candidate.json"
        self.packet = self.state_root / f"{self.slug}_packet.json"
        self.ohlcv_packet = self.state_root / f"{self.slug}_ohlcv_packet.json"
        self.summary = self.sample_root / "full_universe_momentum_fetch" / self.slug / "summary.json"
        self.projection = self.state_root / f"{self.slug}_projection.json"
        self.producer_summary = self.producer_sample_root / self.slug / "summary.json"
        self.overext_producer_summary = self.overext_sample_root / self.slug / "summary.json"
        for path in (self.candidate, self.packet, self.ohlcv_packet, self.projection):
            path.unlink(missing_ok=True)
        _write_json(self.candidate, _candidate_artifact(_ALL_ELIGIBLE))

    def tearDown(self):
        for path in (self.candidate, self.packet, self.ohlcv_packet, self.projection):
            path.unlink(missing_ok=True)

    def _run(self, **overrides):
        kwargs = {
            "candidate_artifact_path": self.candidate,
            "series_packet_path": self.packet,
            "summary_path": self.summary,
            "generated_at": "2026-06-13T10:00:00+00:00",
            "confirm_user_authorization": True,
            "grouped_fetch": _fake_grouped(),
            "interval_seconds": 0,
        }
        kwargs.update(overrides)
        return _fetch().run_fetch(**kwargs)

    def test_fetch_writes_packet_and_summary_then_feeds_producer(self):
        summary = self._run()

        self.assertEqual(summary["scope"]["status"], "series_packet_written")
        self.assertTrue(summary["coverage"]["benchmarks_present"])
        self.assertEqual(summary["fetch_stats"]["sessions_with_data"], summary["coverage"]["grouped_session_count"])
        self.assertGreaterEqual(summary["fetch_stats"]["sessions_with_data"], summary["fetch_stats"]["min_sessions_required"])
        self.assertTrue(self.packet.exists())

        packet = _read_json(self.packet)
        self.assertEqual(packet["schema_name"], "us_short_batch5_full_universe_momentum_series_packet")
        self.assertEqual(set(_ALL_ELIGIBLE) | {"SPY", "QQQ"}, set(packet["series_by_ticker"]))
        self.assertNotIn("ZZZA", packet["series_by_ticker"])  # whole-market noise discarded

        # End-to-end: the fetched packet feeds the offline producer and scores the eligible universe.
        producer = importlib.import_module(PRODUCER_MODULE)
        producer_summary = producer.run_packet(
            candidate_artifact_path=self.candidate,
            series_packet_path=self.packet,
            output_projection_path=self.projection,
            summary_path=self.producer_summary,
            generated_at="2026-06-15T12:00:00+00:00",
        )
        self.assertEqual(producer_summary["projection_contract"]["target_count"], len(_ALL_ELIGIBLE))
        self.assertGreater(producer_summary["projection_contract"]["momentum_scored_count"], 0)
        projection = _read_json(self.projection)
        self.assertEqual(projection["source_binding"]["schema_name"], "us_short_score_projection_binding")
        self.assertTrue(set(projection["momentum_by_ticker"]).issubset(set(_ALL_ELIGIBLE)))

    def test_duplicate_ticker_rows_deduped_by_max_volume(self):
        summary = self._run(grouped_fetch=_fake_grouped_with_dupe())
        self.assertEqual(summary["scope"]["status"], "series_packet_written")
        self.assertEqual(
            summary["fetch_stats"]["duplicate_ticker_rows_collapsed"],
            summary["fetch_stats"]["sessions_with_data"],
        )
        packet = _read_json(self.packet)
        aapl_points = packet["series_by_ticker"]["AAPL"]["points"]
        self.assertTrue(all(point["close"] != 1.0 for point in aapl_points))  # low-volume sentinel discarded

    def test_tracked_summary_counts_only_no_ticker_no_secret(self):
        self._run()
        text = self.summary.read_text(encoding="utf-8")
        lower = text.lower()
        for fragment in ("apikey=", "api.massive.com", "https://", "http://", "bearer ", "token=", '"points"', '"t":', '"c":'):
            self.assertNotIn(fragment, lower)
        # counts-only: no PRIVATE eligible-universe ticker names, no price rows. (The fixed public benchmark
        # constant ["SPY","QQQ"] is allowed — it is a schema const, not the private candidate universe, and it
        # appears in every sibling summary.)
        for ticker in _ALL_ELIGIBLE:
            self.assertNotIn(ticker, text)

    def test_requires_user_authorization(self):
        with self.assertRaises(_fetch().FullUniverseMomentumFetchError):
            self._run(confirm_user_authorization=False)
        self.assertFalse(self.packet.exists())
        self.assertFalse(self.summary.exists())

    def test_missing_benchmark_fails_closed_no_packet(self):
        with self.assertRaises(_fetch().FullUniverseMomentumFetchError):
            self._run(grouped_fetch=_fake_grouped(tickers=list(_ALL_ELIGIBLE) + ["QQQ"]))  # SPY absent
        self.assertFalse(self.packet.exists())
        self.assertFalse(self.summary.exists())

    def test_too_short_window_fails_closed(self):
        # Only 10 dates return data -> below min_sessions -> fail closed, no packet.
        fetch = _fetch()
        calendar = importlib.import_module("runners.us_short_universe_fetch").load_market_calendar(fetch.CALENDAR_PRESET)
        dates = importlib.import_module("runners.us_short_universe_fetch").adv_window_session_dates(
            "20260612", calendar, count=fetch.SESSION_WINDOW_TARGET + fetch.SESSION_FETCH_BUFFER
        )
        with self.assertRaises(fetch.FullUniverseMomentumFetchError):
            self._run(grouped_fetch=_fake_grouped(only_dates=set(dates[:10])))
        self.assertFalse(self.packet.exists())

    def test_auth_quota_http_error_raises(self):
        def hostile(date_iso: str):
            raise urllib.error.HTTPError(url="x", code=403, msg="Forbidden", hdrs=None, fp=None)

        with self.assertRaises(_fetch().FullUniverseMomentumFetchError):
            self._run(grouped_fetch=hostile)
        self.assertFalse(self.packet.exists())

    def test_transient_provider_http_error_fails_closed(self):
        base = _fake_grouped()

        def hostile(date_iso: str):
            if date_iso == "2026-06-12":
                raise urllib.error.HTTPError(url="x", code=503, msg="Unavailable", hdrs=None, fp=None)
            return base(date_iso)

        with self.assertRaises(_fetch().FullUniverseMomentumFetchError):
            self._run(grouped_fetch=hostile)
        self.assertFalse(self.packet.exists())

    def test_missing_candidate_used_date_fails_closed(self):
        base = _fake_grouped()

        def missing_used_date(date_iso: str):
            return [] if date_iso == "2026-06-12" else base(date_iso)

        with self.assertRaises(_fetch().FullUniverseMomentumFetchError):
            self._run(grouped_fetch=missing_used_date)
        self.assertFalse(self.packet.exists())

    def test_valid_delayed_candidate_uses_actual_used_date_not_nominal_price_basis(self):
        artifact = _candidate_artifact(_ALL_ELIGIBLE)
        actual_used_date = "2026-06-11"
        artifact["used_date"] = actual_used_date
        artifact["adv_window"]["latest_date"] = actual_used_date
        artifact["adv_window"]["observed_window_dates"] = [actual_used_date, "2026-06-10"]
        for row in artifact["rows"]:
            row["price_as_of"] = actual_used_date
            row["as_of"] = actual_used_date
        _write_json(self.candidate, artifact)

        self._run()
        packet = _read_json(self.packet)
        self.assertEqual(packet["decision_clock"]["candidate_price_basis_date"], "20260612")
        self.assertEqual(packet["decision_clock"]["price_basis_date"], actual_used_date)
        self.assertEqual(packet["decision_clock"]["source_as_of"], actual_used_date)
        self.assertEqual(packet["series_by_ticker"]["AAPL"]["points"][-1]["date"], actual_used_date)

    def test_duplicate_huge_integer_volume_is_contained_and_primary_row_wins(self):
        base = _fake_grouped()
        for huge_first in (False, True):
            with self.subTest(huge_first=huge_first):
                def huge_duplicate(date_iso: str):
                    rows = base(date_iso)
                    if not rows:
                        return rows
                    huge = [{"T": "AAPL", "c": 1.0, "v": 10**10000}]
                    return huge + rows if huge_first else rows + huge

                summary = self._run(grouped_fetch=huge_duplicate)
                packet = _read_json(self.packet)
                self.assertGreater(summary["fetch_stats"]["duplicate_ticker_rows_collapsed"], 0)
                self.assertNotEqual(packet["series_by_ticker"]["AAPL"]["points"][-1]["close"], 1.0)

    def test_real_path_requires_massive_key(self):
        with mock.patch.dict(os.environ, {"MASSIVE_API_KEY": ""}):
            with self.assertRaises(_fetch().FullUniverseMomentumFetchError):
                self._run(grouped_fetch=None)
        self.assertFalse(self.packet.exists())

    def test_packet_path_must_be_gitignored_state_json(self):
        with self.assertRaises(_fetch().FullUniverseMomentumFetchError):
            self._run(series_packet_path=ROOT / "docs" / f"{self.slug}_packet.json")

    def test_summary_schema_rejects_scope_creep(self):
        from jsonschema import Draft7Validator
        summary = self._run()
        validator = Draft7Validator(_read_json(_fetch().SUMMARY_SCHEMA_PATH))
        for path, value in (
            (("scope", "raw_grouped_window_persisted"), True),
            (("scope", "ship_gate_or_live_normalized_evidence_claimed"), True),
            (("prohibited_claims", "corporate_action_reconciliation_performed"), True),
            (("storage", "summary_contains_secrets"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)


    def test_opt_in_ohlcv_writes_separate_eligible_only_packet_and_feeds_overextension_producer(self):
        base = _fake_grouped_ohlcv()

        def flat_chl(date_iso: str):
            rows = base(date_iso)
            for row in rows:
                if row["T"] == "AAPL":
                    row.update({"c": 100.0, "h": 100.5, "l": 99.5})
            return rows

        summary = self._run(grouped_fetch=flat_chl, ohlcv_series_packet_path=self.ohlcv_packet)

        # the momentum packet is still written and its frozen {date,close,volume} point contract is BYTE-IDENTICAL
        # (no high/low leaked in despite line-244 now retaining them upstream).
        self.assertTrue(self.packet.exists())
        momentum_packet = _read_json(self.packet)
        self.assertEqual(momentum_packet["schema_name"], "us_short_batch5_full_universe_momentum_series_packet")
        self.assertEqual(set(_ALL_ELIGIBLE) | {"SPY", "QQQ"}, set(momentum_packet["series_by_ticker"]))
        self.assertEqual(set(momentum_packet["series_by_ticker"]["AAPL"]["points"][0]), {"date", "close", "volume"})

        # the SEPARATE OHLCV packet is written: schema-valid, ELIGIBLE-ONLY (benchmarks excluded), points carry h/l.
        self.assertTrue(self.ohlcv_packet.exists())
        ohlcv_packet = _read_json(self.ohlcv_packet)
        self.assertEqual(ohlcv_packet["schema_name"], "us_short_batch5_full_universe_ohlcv_series_packet")
        self.assertEqual(set(_ALL_ELIGIBLE), set(ohlcv_packet["series_by_ticker"]))
        self.assertNotIn("SPY", ohlcv_packet["series_by_ticker"])
        self.assertNotIn("ZZZA", ohlcv_packet["series_by_ticker"])   # whole-market noise still discarded
        self.assertEqual(
            set(ohlcv_packet["series_by_ticker"]["AAPL"]["points"][0]), {"date", "high", "low", "close", "volume"})
        from engine.us_short_execution_cost_prior import build_execution_cost_prior
        self.assertEqual(
            build_execution_cost_prior(
                ohlcv_packet["series_by_ticker"]["AAPL"]["points"], adv_usd=100_000_000.0
            )["spread_source"],
            "modeled_chl_winsor_v1",
        )
        from jsonschema import Draft7Validator
        self.assertEqual(
            list(Draft7Validator(_read_json(_fetch().OHLCV_PACKET_SCHEMA_PATH)).iter_errors(ohlcv_packet)), [])

        # the tracked summary records the OHLCV packet (traceability) without leaking anything.
        self.assertTrue(summary["paths"]["ohlcv_series_packet_path"].startswith("state/us_short/"))
        self.assertTrue(summary["storage"]["ohlcv_series_packet_path_gitignored"])

        # end-to-end: the OHLCV packet feeds the 2b-ii-B overextension producer over the eligible universe.
        producer = importlib.import_module(OVEREXT_PRODUCER_MODULE)
        producer_summary = producer.run_packet(
            candidate_artifact_path=self.candidate,
            series_packet_path=self.ohlcv_packet,
            output_projection_path=self.projection,
            summary_path=self.overext_producer_summary,
            generated_at="2026-06-15T12:00:00+00:00",
        )
        self.assertEqual(producer_summary["projection_contract"]["target_count"], len(_ALL_ELIGIBLE))
        self.assertGreater(producer_summary["projection_contract"]["overextension_scored_count"], 0)

    def test_ohlcv_execution_bars_do_not_drop_volume(self):
        base = _fake_grouped_ohlcv()

        def missing_volume_once(date_iso: str):
            rows = base(date_iso)
            if date_iso == "2026-06-12":
                for row in rows:
                    if row["T"] == "AAPL":
                        row.pop("v")
                        break
            return rows

        self._run(grouped_fetch=missing_volume_once, ohlcv_series_packet_path=self.ohlcv_packet)
        packet = _read_json(self.ohlcv_packet)
        aapl_points = packet["series_by_ticker"]["AAPL"]["points"]
        self.assertLess(len(aapl_points), len(packet["series_by_ticker"]["MSFT"]["points"]))
        self.assertTrue(all("volume" in point for point in aapl_points))

    def test_default_no_ohlcv_path_writes_only_the_momentum_packet(self):
        summary = self._run()   # opt-out: no ohlcv_series_packet_path
        self.assertTrue(self.packet.exists())
        self.assertFalse(self.ohlcv_packet.exists())
        self.assertNotIn("ohlcv_series_packet_path", summary["paths"])
        self.assertNotIn("ohlcv_series_packet_path_gitignored", summary["storage"])

    def test_ohlcv_packet_path_must_be_gitignored_state_json_and_distinct(self):
        fetch = _fetch()
        with self.assertRaises(fetch.FullUniverseMomentumFetchError):   # not gitignored / not under state/us_short/
            self._run(grouped_fetch=_fake_grouped_ohlcv(),
                      ohlcv_series_packet_path=ROOT / "docs" / f"{self.slug}_ohlcv.json")
        with self.assertRaises(fetch.FullUniverseMomentumFetchError):   # same path as the momentum packet
            self._run(grouped_fetch=_fake_grouped_ohlcv(), ohlcv_series_packet_path=self.packet)
        self.assertFalse(self.ohlcv_packet.exists())

    def test_ohlcv_all_or_nothing_no_orphan_when_summary_write_fails(self):
        # if the summary write fails AFTER both packets are written, neither packet may remain (all-or-nothing).
        with mock.patch("runners.us_short_universe_fetch._write_summary_safe", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._run(grouped_fetch=_fake_grouped_ohlcv(), ohlcv_series_packet_path=self.ohlcv_packet)
        self.assertFalse(self.packet.exists())        # momentum packet cleaned up
        self.assertFalse(self.ohlcv_packet.exists())  # OHLCV packet cleaned up

    def test_fail_closed_with_ohlcv_path_set_writes_no_partial_artifact(self):
        # a fetch auth/quota failure must fail closed for the OHLCV path too — no momentum packet, no OHLCV packet.
        def hostile(date_iso: str):
            raise urllib.error.HTTPError(url="x", code=403, msg="Forbidden", hdrs=None, fp=None)

        with self.assertRaises(_fetch().FullUniverseMomentumFetchError):
            self._run(grouped_fetch=hostile, ohlcv_series_packet_path=self.ohlcv_packet)
        self.assertFalse(self.packet.exists())
        self.assertFalse(self.ohlcv_packet.exists())

    def test_missing_high_low_in_rows_is_gapped_not_crashed(self):
        # a Massive row missing high/low → that ticker/date is a gap in the OHLCV packet (never zero-filled); the
        # run still completes and the packet stays schema-valid + eligible-⊆ (the producer dispositions the absent
        # ticker as insufficient_data). The momentum packet (close/volume) is unaffected.
        base = _fake_grouped_ohlcv()

        def fetch(date_iso: str):
            rows = base(date_iso)
            for row in rows:
                if row["T"] == "MSFT":
                    row.pop("l", None)   # MSFT loses its low every session → no valid OHLCV bar → dropped
            return rows

        self._run(grouped_fetch=fetch, ohlcv_series_packet_path=self.ohlcv_packet)
        ohlcv_packet = _read_json(self.ohlcv_packet)
        self.assertNotIn("MSFT", ohlcv_packet["series_by_ticker"])
        self.assertIn("AAPL", ohlcv_packet["series_by_ticker"])
        self.assertTrue(set(ohlcv_packet["series_by_ticker"]).issubset(set(_ALL_ELIGIBLE)))
        from jsonschema import Draft7Validator
        self.assertEqual(
            list(Draft7Validator(_read_json(_fetch().OHLCV_PACKET_SCHEMA_PATH)).iter_errors(ohlcv_packet)), [])


if __name__ == "__main__":
    unittest.main()
