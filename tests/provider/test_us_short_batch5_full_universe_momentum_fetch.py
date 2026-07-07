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
    _candidate_artifact,
)


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_universe_momentum_fetch"
PRODUCER_SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_universe_momentum_20260707"
FETCH_MODULE = "runners.us_short_batch5_full_universe_momentum_fetch"
PRODUCER_MODULE = "runners.us_short_batch5_full_universe_momentum_producer"

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
        self.slug = f"test_full_universe_momentum_fetch_{os.getpid()}_{self._testMethodName}"
        self.candidate = STATE_DIR / f"{self.slug}_candidate.json"
        self.packet = STATE_DIR / f"{self.slug}_packet.json"
        self.summary = SAMPLE_ROOT / self.slug / "summary.json"
        self.projection = STATE_DIR / f"{self.slug}_projection.json"
        self.producer_summary = PRODUCER_SAMPLE_ROOT / self.slug / "summary.json"
        for path in (self.candidate, self.packet, self.projection):
            path.unlink(missing_ok=True)
        _write_json(self.candidate, _candidate_artifact(_ALL_ELIGIBLE))

    def tearDown(self):
        for path in (self.candidate, self.packet, self.projection):
            path.unlink(missing_ok=True)
        for root in (SAMPLE_ROOT / self.slug, PRODUCER_SAMPLE_ROOT / self.slug):
            if root.exists():
                for item in sorted(root.rglob("*"), reverse=True):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        item.rmdir()
                root.rmdir()

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


if __name__ == "__main__":
    unittest.main()
