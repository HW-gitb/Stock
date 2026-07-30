from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
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


def _fake_cik_source(cik_map=None):
    data = dict(cik_map or {ticker: index + 1 for index, ticker in enumerate(_ALL_ELIGIBLE)})

    def source(eligible):
        return {ticker: data[ticker] for ticker in eligible if ticker in data}

    return source


class FullUniverseSecSicClassificationFetchTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_sec_sic_fetch_{os.getpid()}_{self._testMethodName}"
        self._case_temp = tempfile.TemporaryDirectory(prefix=f"{self.slug}_")
        self.addCleanup(self._case_temp.cleanup)
        self.case_root = Path(self._case_temp.name).resolve()
        self.state_dir = self.case_root / "state" / "us_short"
        self.candidate = self.state_dir / "candidate.json"
        self.packet = self.state_dir / "classification.json"
        self.summary = (
            self.case_root
            / "provider_samples"
            / "us_short_batch5_full_universe_sec_sic_classification_fetch"
            / "summary.json"
        )
        self.series = self.state_dir / "series.json"
        self.theme_projection = self.state_dir / "theme.json"
        self.theme_summary = (
            self.case_root
            / "provider_samples"
            / "us_short_batch5_full_universe_theme_20260707"
            / "summary.json"
        )
        self.snapshot_root = self.state_dir / "sec_sic_classification_snapshots"
        self.assertFalse(self.case_root.is_relative_to(ROOT.resolve()))
        for path in (
            self.candidate,
            self.packet,
            self.summary,
            self.series,
            self.theme_projection,
            self.theme_summary,
            self.snapshot_root,
        ):
            self.assertTrue(path.resolve().is_relative_to(self.case_root))
            self.assertFalse(path.resolve().is_relative_to(ROOT.resolve()))
        _write_json(self.candidate, _candidate_artifact(_ALL_ELIGIBLE))

    def _run(self, **overrides):
        kwargs = {
            "candidate_artifact_path": self.candidate,
            "classification_packet_path": self.packet,
            "summary_path": self.summary,
            "generated_at": "2026-06-15T12:00:00+00:00",
            "confirm_user_authorization": True,
            "sic_source": _fake_source(),
            "cik_source": _fake_cik_source(),
            "snapshot_root": self.snapshot_root,
            "interval_seconds": 0,
        }
        kwargs.update(overrides)
        mod = _fetch()
        with (
            patch.object(mod, "ROOT", self.case_root),
            patch.object(mod, "STATE_US_SHORT_DIR", self.state_dir),
            patch.object(mod.universe_fetch, "_check_gitignore", return_value=True),
            patch.object(mod.universe_fetch, "_git_check_ignored", return_value=True),
        ):
            return mod.run_fetch(**kwargs)

    def test_all_generated_data_stays_inside_one_system_temp_root(self):
        self._run()
        generated = [
            path.resolve()
            for path in self.case_root.rglob("*")
            if path.is_file()
        ]
        self.assertGreater(len(generated), 2)
        self.assertTrue(all(path.is_relative_to(self.case_root) for path in generated))
        self.assertTrue(all(not path.is_relative_to(ROOT.resolve()) for path in generated))

    def test_fetch_coarsens_to_major_group_and_writes_packet(self):
        summary = self._run()

        self.assertEqual(summary["scope"]["status"], "classification_packet_written")
        self.assertFalse(summary["scope"]["gics_classification_claimed"])
        self.assertEqual(summary["classification"]["classification_source"], "sec_sic_major_group")
        self.assertEqual(summary["classification"]["sic_resolved_count"], 5)
        self.assertEqual(summary["classification"]["sector_group_count"], 3)  # 35, 60, 59
        self.assertEqual(summary["provider_call_evidence"]["actual_total_calls"], 0)
        self.assertFalse(summary["provider_call_evidence"]["provider_calls_performed"])
        self.assertEqual(summary["classification"]["cache_refreshed_count"], 5)

        packet = _read_json(self.packet)
        self.assertEqual(packet["schema_name"], "us_short_batch5_full_universe_sector_classification_packet")
        self.assertEqual(packet["classification_contract"]["classification_source"], "sec_sic_major_group")
        self.assertEqual(packet["decision_clock"]["source_as_of"], "2026-06-15")
        self.assertEqual(packet["classification_contract"]["as_of"], "2026-06-15")
        self.assertEqual(packet["decision_clock"]["price_basis_date"], "2026-06-12")
        self.assertEqual(packet["sector_by_ticker"],
                         {"AAPL": "35", "MSFT": "35", "GOOG": "35", "JPM": "60", "AMZN": "59"})
        self.assertEqual(packet["classification_contract"]["cache_freshness_days"], 90)
        self.assertTrue(all(not item["cache_reused"] for item in packet["provenance_by_ticker"].values()))

    def test_reuses_fresh_cik_snapshot_without_second_submissions_fetch(self):
        first = self._run()
        mod = _fetch()
        with patch.dict(os.environ, {"SEC_USER_AGENT": ""}), \
                patch.object(mod.universe_fetch, "fetch_sec_tickers", side_effect=AssertionError("must not fetch ticker map")) as ticker_ref, \
                patch.object(mod.universe_fetch, "_sec_get", side_effect=AssertionError("must not fetch submissions")) as submissions:
            second = self._run(sic_source=None, cik_source=None, confirm_user_authorization=False)
        self.assertEqual(first["classification"]["cache_refreshed_count"], 5)
        self.assertEqual(second["classification"]["cache_reused_count"], 5)
        self.assertEqual(second["classification"]["cache_refreshed_count"], 0)
        self.assertFalse(second["scope"]["network_access_performed"])
        self.assertEqual(second["provider_call_evidence"]["actual_total_calls"], 0)
        ticker_ref.assert_not_called()
        submissions.assert_not_called()
        packet = _read_json(self.packet)
        self.assertTrue(all(item["cache_reused"] for item in packet["provenance_by_ticker"].values()))

    def test_partial_cache_fetches_reference_once_and_only_unresolved_submission(self):
        partial_sic = {ticker: sic for ticker, sic in _SIC.items() if ticker != "AMZN"}
        self._run(sic_source=_fake_source(partial_sic))
        mod = _fetch()
        ticker_map = {ticker: {"cik": index + 1, "exchange": "NASDAQ"}
                      for index, ticker in enumerate(_ALL_ELIGIBLE)}
        submission_urls = []

        def submission(url, sec_ua):
            submission_urls.append(url)
            return {"sic": _SIC["AMZN"]}

        with patch.dict(os.environ, {"SEC_USER_AGENT": "ua@test"}), \
                patch.object(mod.universe_fetch, "fetch_sec_tickers", return_value=ticker_map) as ticker_ref, \
                patch.object(mod.universe_fetch, "_sec_get", side_effect=submission):
            summary = self._run(sic_source=None, cik_source=None)
        ticker_ref.assert_called_once_with("ua@test")
        self.assertEqual(len(submission_urls), 1)
        self.assertTrue(submission_urls[0].endswith("0000000005.json"))
        self.assertEqual(summary["classification"]["cache_reused_count"], 4)
        self.assertEqual(summary["classification"]["cache_refreshed_count"], 1)
        self.assertEqual(summary["provider_call_evidence"]["actual_total_calls"], 2)

    def test_tampered_snapshot_digest_rejects_before_provider_seam(self):
        self._run()
        snapshot = next(self.snapshot_root.glob("*.json"))
        payload = _read_json(snapshot)
        payload["entries"]["1"]["sector"] = "60"
        _write_json(snapshot, payload)
        mod = _fetch()
        with patch.object(mod.universe_fetch, "fetch_sec_tickers", side_effect=AssertionError("provider seam reached")), \
                patch.object(mod.universe_fetch, "_sec_get", side_effect=AssertionError("provider seam reached")):
            with self.assertRaisesRegex(mod.FullUniverseSecSicClassificationFetchError, "digest mismatch"):
                self._run(sic_source=None, cik_source=None, confirm_user_authorization=False)

    def test_miskeyed_snapshot_entry_rejects_before_provider_seam(self):
        self._run()
        mod = _fetch()
        snapshot = next(self.snapshot_root.glob("*.json"))
        payload = _read_json(snapshot)
        payload["entries"]["1"]["cik"] = 999
        payload["snapshot_id"] = mod._snapshot_digest(payload)
        _write_json(snapshot, payload)
        with patch.object(mod.universe_fetch, "fetch_sec_tickers", side_effect=AssertionError("provider seam reached")), \
                patch.object(mod.universe_fetch, "_sec_get", side_effect=AssertionError("provider seam reached")):
            with self.assertRaisesRegex(mod.FullUniverseSecSicClassificationFetchError, "does not match"):
                self._run(sic_source=None, cik_source=None, confirm_user_authorization=False)

    def test_duplicate_ticker_to_different_cik_snapshot_rejects_before_provider_seam(self):
        self._run()
        mod = _fetch()
        conflicting = mod._snapshot_payload(
            generated_at="2026-06-14T12:00:00+00:00", source_as_of="2026-06-14",
            entries={999: {"cik": 999, "tickers": ["AAPL"], "sector": "35"}},
        )
        mod._write_snapshot(self.snapshot_root, conflicting)
        with patch.object(mod.universe_fetch, "fetch_sec_tickers", side_effect=AssertionError("provider seam reached")), \
                patch.object(mod.universe_fetch, "_sec_get", side_effect=AssertionError("provider seam reached")):
            with self.assertRaisesRegex(mod.FullUniverseSecSicClassificationFetchError, "different CIKs"):
                self._run(sic_source=None, cik_source=None, confirm_user_authorization=False)

    def test_snapshot_after_target_or_over_90_days_is_not_reused(self):
        self._run(generated_at="2026-03-15T12:00:00+00:00")
        calls = []

        def refreshed(eligible):
            calls.append(tuple(eligible))
            return dict(_SIC)

        summary = self._run(generated_at="2026-06-15T12:00:00+00:00", sic_source=refreshed)
        self.assertEqual(summary["classification"]["cache_reused_count"], 0)
        self.assertEqual(summary["classification"]["cache_refreshed_count"], 5)
        self.assertEqual(calls, [tuple(_ALL_ELIGIBLE)])

    def test_packet_feeds_theme_producer_end_to_end(self):
        self._run()
        _write_json(self.series, _series_packet(_theme_series_map()))
        theme = importlib.import_module(THEME_MODULE)
        projection_binding = importlib.import_module("engine.us_short_projection_binding")
        with (
            patch.object(theme, "ROOT", self.case_root),
            patch.object(theme, "STATE_US_SHORT_DIR", self.state_dir),
            patch.object(theme, "_git_ignored", return_value=True),
            patch.object(projection_binding, "ROOT", self.case_root),
        ):
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
        self.assertEqual(projection["source_binding"]["schema_name"], "us_short_score_projection_binding")
        self.assertTrue({"AAPL", "MSFT", "GOOG"}.issubset(set(projection["theme_block_by_ticker"])))

    def test_requires_user_authorization(self):
        with self.assertRaises(_fetch().FullUniverseSecSicClassificationFetchError):
            self._run(confirm_user_authorization=False)
        self.assertFalse(self.packet.exists())
        self.assertFalse(self.summary.exists())

    def test_post_decision_observation_is_rejected_before_source_call(self):
        calls = []

        def source(eligible):
            calls.append(tuple(eligible))
            return dict(_SIC)

        with self.assertRaises(_fetch().FullUniverseSecSicClassificationFetchError):
            self._run(generated_at="2026-06-15T14:00:00+00:00", sic_source=source)
        self.assertEqual(calls, [])
        self.assertFalse(self.packet.exists())
        self.assertFalse(self.summary.exists())

    def test_weekend_preopen_observation_is_accepted(self):
        # §2.1: a weekend / pre-open observation (strictly before the decision session's 09:30 ET open) is VALID —
        # the design's normal weekend prep run. Regression guard for the old (2026-07-11) same-calendar-day rule.
        # Sat 2026-06-13 12:00 ET (= 16:00 UTC), strictly before Mon 2026-06-15 09:30 ET; decision 20260615 unchanged.
        summary = self._run(generated_at="2026-06-13T16:00:00+00:00")
        self.assertEqual(summary["scope"]["status"], "classification_packet_written")
        packet = _read_json(self.packet)
        # source_as_of tracks the ET observation date (Saturday); price basis + decision come from the candidate.
        self.assertEqual(packet["decision_clock"]["source_as_of"], "2026-06-13")
        self.assertEqual(packet["decision_clock"]["price_basis_date"], "2026-06-12")
        self.assertEqual(packet["classification_contract"]["as_of"], "2026-06-13")

    def test_real_source_counts_attempted_ticker_and_submission_calls(self):
        mod = _fetch()
        stats = {}
        ticker_map = {ticker: {"cik": index + 1, "exchange": "NASDAQ"}
                      for index, ticker in enumerate(_ALL_ELIGIBLE)}

        def submission(url, sec_ua):
            if url.endswith("0000000003.json"):
                raise OSError("provider failure still counts as an attempted call")
            return {"sic": "3571"}

        with patch.object(mod.universe_fetch, "_sec_get", side_effect=submission):
            source = mod._real_sic_source("ua@test", {ticker: rec["cik"] for ticker, rec in ticker_map.items()},
                                          interval_seconds=0, stats_out=stats)
            out = source(list(_ALL_ELIGIBLE))
        self.assertEqual(stats["submissions_calls"], len(_ALL_ELIGIBLE))
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
            self._run(classification_packet_path=self.case_root / "docs" / "classification.json")

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
