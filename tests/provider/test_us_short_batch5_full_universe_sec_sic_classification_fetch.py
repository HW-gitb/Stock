from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402
from tests.provider.test_us_short_batch5_full_universe_momentum_producer import (  # noqa: E402
    _ALL_ELIGIBLE,
    _DECISION_DATE,
    _candidate_artifact,
    _series_packet,
)
from tests.provider.test_us_short_batch5_full_universe_theme_producer import _theme_series_map  # noqa: E402


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_universe_sec_sic_classification_fetch"
THEME_SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_universe_theme_20260707"
FETCH_MODULE = "runners.us_short_batch5_full_universe_sec_sic_classification_fetch"
THEME_MODULE = "runners.us_short_batch5_full_universe_theme_producer"

# 4-digit SIC per ticker; AAPL/MSFT/GOOG map to major group "35" (>=3 -> a scored sector once priced),
# JPM -> "60", AMZN -> "59" (lone -> insufficient).
_SIC = {"AAPL": "3571", "MSFT": "3572", "GOOG": "3576", "JPM": "6021", "AMZN": "5961"}


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch():
    return importlib.import_module(FETCH_MODULE)


def _fake_source(sic_map=None):
    data = dict(_SIC if sic_map is None else sic_map)

    def source(eligible):
        return {t: data[t] for t in eligible if t in data}

    return source


class FullUniverseSecSicClassificationFetchTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_sec_sic_fetch_{os.getpid()}_{self._testMethodName}"
        self.candidate = STATE_DIR / f"{self.slug}_candidate.json"
        self.packet = STATE_DIR / f"{self.slug}_classification.json"
        self.summary = SAMPLE_ROOT / self.slug / "summary.json"
        self.series = STATE_DIR / f"{self.slug}_series.json"
        self.theme_projection = STATE_DIR / f"{self.slug}_theme.json"
        self.theme_summary = THEME_SAMPLE_ROOT / self.slug / "summary.json"
        for p in (self.candidate, self.packet, self.series, self.theme_projection):
            p.unlink(missing_ok=True)
        _write_json(self.candidate, _candidate_artifact(_ALL_ELIGIBLE))

    def tearDown(self):
        for p in (self.candidate, self.packet, self.series, self.theme_projection):
            p.unlink(missing_ok=True)
        for root in (SAMPLE_ROOT / self.slug, THEME_SAMPLE_ROOT / self.slug):
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
            "classification_packet_path": self.packet,
            "summary_path": self.summary,
            "generated_at": "2026-06-13T10:00:00+00:00",
            "confirm_user_authorization": True,
            "sic_source": _fake_source(),
            "interval_seconds": 0,
        }
        kwargs.update(overrides)
        return _fetch().run_fetch(**kwargs)

    def test_fetch_coarsens_to_major_group_and_writes_packet(self):
        summary = self._run()

        self.assertEqual(summary["scope"]["status"], "classification_packet_written")
        self.assertFalse(summary["scope"]["gics_classification_claimed"])
        self.assertEqual(summary["classification"]["classification_source"], "sec_sic_major_group")
        self.assertEqual(summary["classification"]["sic_resolved_count"], 5)
        self.assertEqual(summary["classification"]["sector_group_count"], 3)  # 35, 60, 59
        self.assertEqual(summary["provider_call_evidence"]["actual_total_calls"], 0)
        self.assertFalse(summary["provider_call_evidence"]["provider_calls_performed"])

        packet = _read_json(self.packet)
        self.assertEqual(packet["schema_name"], "us_short_batch5_full_universe_sector_classification_packet")
        self.assertEqual(packet["classification_contract"]["classification_source"], "sec_sic_major_group")
        self.assertEqual(packet["sector_by_ticker"],
                         {"AAPL": "35", "MSFT": "35", "GOOG": "35", "JPM": "60", "AMZN": "59"})

    def test_packet_feeds_theme_producer_end_to_end(self):
        self._run()
        _write_json(self.series, _series_packet(_theme_series_map()))
        theme = importlib.import_module(THEME_MODULE)
        theme_summary = theme.run_packet(
            candidate_artifact_path=self.candidate,
            series_packet_path=self.series,
            classification_packet_path=self.packet,
            output_projection_path=self.theme_projection,
            summary_path=self.theme_summary,
            generated_at="2026-06-15T12:00:00+00:00",
        )
        # group "35" = AAPL/MSFT/GOOG, all full-history -> a scored sector.
        self.assertEqual(theme_summary["theme_source"]["classification_source"], "sec_sic_major_group")
        self.assertGreaterEqual(theme_summary["projection_contract"]["theme_scored_count"], 3)
        projection = _read_json(self.theme_projection)
        self.assertTrue({"AAPL", "MSFT", "GOOG"}.issubset(set(projection["theme_block_by_ticker"])))

    def test_requires_user_authorization(self):
        with self.assertRaises(_fetch().FullUniverseSecSicClassificationFetchError):
            self._run(confirm_user_authorization=False)
        self.assertFalse(self.packet.exists())
        self.assertFalse(self.summary.exists())

    def test_real_source_counts_attempted_ticker_and_submission_calls(self):
        mod = _fetch()
        stats = {}
        ticker_map = {ticker: {"cik": index + 1, "exchange": "NASDAQ"}
                      for index, ticker in enumerate(_ALL_ELIGIBLE)}

        def submission(url, sec_ua):
            if url.endswith("0000000003.json"):
                raise OSError("provider failure still counts as an attempted call")
            return {"sic": "3571"}

        with patch.object(mod.universe_fetch, "fetch_sec_tickers", return_value=ticker_map), \
             patch.object(mod.universe_fetch, "_sec_get", side_effect=submission):
            source = mod._real_sic_source("ua@test", interval_seconds=0, stats_out=stats)
            out = source(list(_ALL_ELIGIBLE))
        self.assertEqual(stats["ticker_reference_calls"], 1)
        self.assertEqual(stats["submissions_calls"], len(_ALL_ELIGIBLE))
        self.assertEqual(stats["actual_total_calls"], 1 + len(_ALL_ELIGIBLE))
        self.assertEqual(len(out), len(_ALL_ELIGIBLE) - 1)

    def test_zero_classified_fails_closed(self):
        with self.assertRaises(_fetch().FullUniverseSecSicClassificationFetchError):
            self._run(sic_source=_fake_source({}))  # SEC returned nothing usable
        self.assertFalse(self.packet.exists())
        self.assertFalse(self.summary.exists())

    def test_stray_and_malformed_sic_are_skipped(self):
        # TSLA not eligible -> ignored; SHORT sic "3" too short -> skipped; BADX non-numeric -> skipped.
        summary = self._run(sic_source=_fake_source(
            {"AAPL": "3571", "MSFT": "7372", "JPM": "6021", "TSLA": "3711", "GOOG": "3", "AMZN": "xxxx"}))
        packet = _read_json(self.packet)
        self.assertEqual(set(packet["sector_by_ticker"]), {"AAPL", "MSFT", "JPM"})  # GOOG/AMZN malformed, TSLA stray
        self.assertNotIn("TSLA", packet["sector_by_ticker"])
        self.assertEqual(summary["classification"]["sic_resolved_count"], 3)

    def test_tracked_summary_counts_only_no_ticker_no_sector(self):
        self._run()
        text = self.summary.read_text(encoding="utf-8")
        lower = text.lower()
        for fragment in ("data.sec.gov", "https://", "http://", "@", '"sector_by_ticker"', '"3571"', '"35"'):
            self.assertNotIn(fragment, lower)
        for ticker in _ALL_ELIGIBLE:
            self.assertNotIn(ticker, text)

    def test_packet_path_must_be_gitignored_state_json(self):
        with self.assertRaises(_fetch().FullUniverseSecSicClassificationFetchError):
            self._run(classification_packet_path=ROOT / "docs" / f"{self.slug}_classification.json")

    def test_summary_schema_rejects_scope_creep(self):
        from jsonschema import Draft7Validator as V
        summary = self._run()
        validator = V(_read_json(_fetch().SUMMARY_SCHEMA_PATH))
        for path, value in (
            (("scope", "gics_classification_claimed"), True),
            (("scope", "raw_submissions_persisted"), True),
            (("prohibited_claims", "gics_classification_claimed"), True),
            (("storage", "summary_contains_sec_user_agent"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)


if __name__ == "__main__":
    unittest.main()
