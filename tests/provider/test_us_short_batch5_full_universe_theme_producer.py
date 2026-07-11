from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from pathlib import Path


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
    _PRICE_BASIS_DATE,
    _PRICE_BASIS_YMD,
    _candidate_artifact,
    _series,
    _series_packet,
)
from tests.provider.test_us_short_batch5_data_context import _constant_projection  # noqa: E402


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_universe_theme_20260707"
PROJECTION_INPUTS_SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_candidate_projection_inputs_20260706"
RUNNER_MODULE = "runners.us_short_batch5_full_universe_theme_producer"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _runner():
    return importlib.import_module(RUNNER_MODULE)


def _theme_series_map() -> dict:
    # AAPL/MSFT/GOOG/JPM full (72 pts); AMZN thin (8 pts -> dropped by industry heat's history floor).
    return {
        "AAPL": _series(start=100.0, step=2.0),
        "MSFT": _series(start=100.0, step=0.25),
        "GOOG": _series(start=100.0, step=1.0),
        "JPM": _series(start=100.0, step=0.5),
        "AMZN": _series(start=100.0, step=1.0, n=8),
        "SPY": _series(start=100.0, step=0.9),
        "QQQ": _series(start=100.0, step=1.0),
    }


def _classification_packet(sector_by_ticker: dict, *, classification_source: str = "sec_sic",
                           as_of: str = _PRICE_BASIS_YMD) -> dict:
    return {
        "schema_name": "us_short_batch5_full_universe_sector_classification_packet",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-15T12:00:00+00:00",
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "full_universe_sector_classification_ready_for_local_theme_projection",
            "network_access_performed_by_packet_producer": True,
            "provider_calls_performed_by_packet_producer": True,
            "raw_payload_refs_gitignored": True,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": _DECISION_DATE,
            "candidate_price_basis_date": _PRICE_BASIS_DATE,
            "price_basis_date": as_of,
            "source_as_of": "2026-06-15",
        },
        "classification_contract": {"classification_source": classification_source, "as_of": "2026-06-15"},
        "provenance": {
            "provider_id": "sec_edgar",
            "endpoint_or_family": "submissions_sic",
            "source_as_of": "2026-06-15",
            "observed_at": "2026-06-15T12:00:00+00:00",
            "coverage_status": "full",
            "parser_status": "ok",
        },
        "sector_by_ticker": sector_by_ticker,
    }


# AAPL/MSFT/GOOG usable Technology (3 -> scored); AMZN thin Technology (dropped -> neutral); JPM lone Financials
# (< MIN_SECTOR_MEMBERS -> insufficient -> neutral).
_SECTORS = {"AAPL": "Technology", "MSFT": "Technology", "GOOG": "Technology", "AMZN": "Technology", "JPM": "Financials"}


class FullUniverseThemeProducerTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_full_universe_theme_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "series": STATE_DIR / f"{self.slug}_series.json",
            "classification": STATE_DIR / f"{self.slug}_classification.json",
            "projection": STATE_DIR / f"{self.slug}_theme_projection.json",
            "summary": SAMPLE_ROOT / self.slug / "summary.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact(_ALL_ELIGIBLE))
        _write_json(self.paths["series"], _series_packet(_theme_series_map()))
        _write_json(self.paths["classification"], _classification_packet(dict(_SECTORS)))

    def tearDown(self):
        extra = [STATE_DIR / f"{self.slug}_momentum_src.json",
                 STATE_DIR / f"{self.slug}_out_momentum.json",
                 STATE_DIR / f"{self.slug}_out_theme.json"]
        for path in list(self.paths.values()) + extra:
            path.unlink(missing_ok=True)
        for root in (SAMPLE_ROOT / self.slug, PROJECTION_INPUTS_SAMPLE_ROOT / self.slug):
            if root.exists():
                for item in sorted(root.rglob("*"), reverse=True):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        item.rmdir()
                root.rmdir()

    def _run_packet(self, **overrides):
        kwargs = {
            "candidate_artifact_path": self.paths["candidate"],
            "series_packet_path": self.paths["series"],
            "classification_packet_path": self.paths["classification"],
            "output_projection_path": self.paths["projection"],
            "summary_path": self.paths["summary"],
            "generated_at": "2026-06-15T12:00:00+00:00",
        }
        kwargs.update(overrides)
        return _runner().run_packet(**kwargs)

    def test_scores_eligible_with_industry_base_dispositions(self):
        summary = self._run_packet()

        self.assertEqual(summary["scope"]["status"], "full_universe_theme_projection_written")
        self.assertFalse(summary["scope"]["provisional_cross_sector_theme_consumed"])
        self.assertEqual(summary["theme_source"]["classification_source"], "sec_sic")
        self.assertEqual(summary["theme_source"]["scored_sector_count"], 1)       # Technology
        self.assertEqual(summary["theme_source"]["insufficient_sector_count"], 1)  # Financials (lone JPM)
        self.assertEqual(summary["projection_contract"]["target_count"], 5)
        self.assertEqual(summary["projection_contract"]["theme_scored_count"], 3)
        self.assertEqual(
            summary["projection_contract"]["disposition_counts"],
            {
                "scored_theme_base": 0,
                "scored_industry_base": 3,
                "neutral_insufficient_theme_no_industry": 0,
                "neutral_missing_theme_and_industry_base": 2,
            },
        )

        projection = _read_json(self.paths["projection"])
        self.assertEqual(set(projection["theme_block_by_ticker"]), {"AAPL", "MSFT", "GOOG"})
        self.assertEqual(set(projection["neutral_fill_tickers"]), {"AMZN", "JPM"})
        self.assertEqual(projection["coverage"]["AMZN"], "neutral_missing_theme_and_industry_base")  # thin history
        self.assertEqual(projection["coverage"]["JPM"], "neutral_missing_theme_and_industry_base")   # lone sector
        for value in projection["theme_block_by_ticker"].values():
            self.assertTrue(isinstance(value, float) and 0.0 <= value <= 100.0)

    def test_output_projection_feeds_full_candidate_projection_inputs(self):
        self._run_packet()
        projection_inputs = importlib.import_module("runners.us_short_batch5_full_candidate_projection_inputs")
        momentum_src = STATE_DIR / f"{self.slug}_momentum_src.json"
        _write_json(momentum_src, _constant_projection("momentum_by_ticker", _ALL_ELIGIBLE, "scored", score=65.0))

        out_summary = projection_inputs.run_packet(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            source_momentum_projection_path=momentum_src,
            source_theme_projection_path=self.paths["projection"],
            output_momentum_projection_path=STATE_DIR / f"{self.slug}_out_momentum.json",
            output_theme_projection_path=STATE_DIR / f"{self.slug}_out_theme.json",
            summary_path=PROJECTION_INPUTS_SAMPLE_ROOT / self.slug / "summary.json",
            generated_at="2026-07-06T12:00:00+00:00",
        )
        self.assertEqual(out_summary["output_projection_contract"]["target_count"], 5)
        self.assertEqual(out_summary["output_projection_contract"]["theme_scored_count"], 3)
        merged = _read_json(STATE_DIR / f"{self.slug}_out_theme.json")
        self.assertEqual(set(merged["theme_block_by_ticker"]), {"AAPL", "MSFT", "GOOG"})

    def test_missing_benchmark_fails_closed(self):
        series_map = _theme_series_map()
        del series_map["QQQ"]
        _write_json(self.paths["series"], _series_packet(series_map))
        with self.assertRaises(_runner().FullUniverseThemeProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_classification_clock_mismatch_fails_closed(self):
        _write_json(self.paths["classification"], _classification_packet(dict(_SECTORS), as_of="2026-06-11"))
        with self.assertRaises(_runner().FullUniverseThemeProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_post_open_classification_observation_fails_closed(self):
        # Reverse control for the theme producer's INDEPENDENT _validate_classification_observation gate:
        # a classification snapshot observed AFTER the 09:30 ET decision-day open must be rejected (a
        # post-decision current SIC snapshot cannot be relabelled as pre-decision theme evidence).
        classification = _classification_packet(dict(_SECTORS))
        classification["provenance"]["observed_at"] = "2026-06-15T15:00:00+00:00"  # 11:00 ET, after the 09:30 open
        _write_json(self.paths["classification"], classification)
        with self.assertRaisesRegex(_runner().FullUniverseThemeProducerError, "09:30 ET"):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())

    def test_ticker_without_sector_is_neutral(self):
        sectors = {k: v for k, v in _SECTORS.items() if k != "JPM"}  # JPM has no sector at all
        _write_json(self.paths["classification"], _classification_packet(sectors))
        self._run_packet()
        projection = _read_json(self.paths["projection"])
        self.assertEqual(projection["coverage"]["JPM"], "neutral_missing_theme_and_industry_base")
        self.assertNotIn("JPM", projection["theme_block_by_ticker"])

    def test_huge_close_ticker_gracefully_dispositioned_not_bare_overflow(self):
        # §6a finding A: a huge close must NOT bare-crash industry_heat's _finite; the ticker is dropped
        # (dispositioned neutral) and the run completes, the sector staying scored on its remaining members.
        series_map = _theme_series_map()
        series_map["JPM"] = _series(start=100.0, step=0.5)  # full, then corrupt one point
        series_map["JPM"]["points"][10]["close"] = 10 ** 400
        _write_json(self.paths["series"], _series_packet(series_map))
        _write_json(self.paths["classification"], _classification_packet(
            {"AAPL": "Technology", "MSFT": "Technology", "GOOG": "Technology", "JPM": "Technology", "AMZN": "Financials"}))

        summary = self._run_packet()
        self.assertEqual(summary["scope"]["status"], "full_universe_theme_projection_written")
        projection = _read_json(self.paths["projection"])
        self.assertEqual(projection["coverage"]["JPM"], "neutral_missing_theme_and_industry_base")
        self.assertNotIn("JPM", projection["theme_block_by_ticker"])
        self.assertIn("AAPL", projection["theme_block_by_ticker"])  # sector still scored on its 3 usable members

    def test_stray_series_ticker_fails_closed(self):
        series_map = _theme_series_map()
        series_map["TSLA"] = _series(start=100.0, step=1.0)  # not eligible, not a benchmark
        _write_json(self.paths["series"], _series_packet(series_map))
        with self.assertRaises(_runner().FullUniverseThemeProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_stray_sector_ticker_fails_closed(self):
        sectors = dict(_SECTORS)
        sectors["TSLA"] = "Technology"  # not in the eligible candidate set
        _write_json(self.paths["classification"], _classification_packet(sectors))
        with self.assertRaises(_runner().FullUniverseThemeProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_series_lookahead_as_of_fails_closed(self):
        series_map = _theme_series_map()
        series_map["AAPL"]["as_of"] = "2026-06-15"  # future vs price_basis 2026-06-12 -> look-ahead forgery
        _write_json(self.paths["series"], _series_packet(series_map))
        with self.assertRaises(_runner().FullUniverseThemeProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_tracked_summary_counts_only_no_secret_no_ticker_no_sector(self):
        self._run_packet()
        text = self.paths["summary"].read_text(encoding="utf-8")
        lower = text.lower()
        for fragment in ("apikey=", "api.massive.com", "data.sec.gov", "https://", "http://", "bearer ", "token=",
                         '"points"', '"sector_by_ticker"', "technology", "financials"):
            self.assertNotIn(fragment, lower)
        for ticker in _ALL_ELIGIBLE:
            self.assertNotIn(ticker, text)

    def test_summary_schema_rejects_scope_creep(self):
        summary = self._run_packet()
        validator = Draft7Validator(_read_json(_runner().SUMMARY_SCHEMA_PATH))
        for path, value in (
            (("scope", "provider_calls_performed_by_runner"), True),
            (("scope", "provisional_cross_sector_theme_consumed"), True),
            (("projection_contract", "provisional_cross_sector_theme_consumed"), True),
            (("prohibited_claims", "gics_classification_claimed_when_proxy"), True),
            (("storage", "summary_contains_sector_labels"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)

    def test_preflight_only_no_writes(self):
        result = _runner().run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            series_packet_path=self.paths["series"],
            classification_packet_path=self.paths["classification"],
            output_projection_path=self.paths["projection"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )
        self.assertEqual(result["scope"]["preflight_status"], "offline_preflight_passed")
        self.assertEqual(result["projection_preview"]["theme_scored_count"], 3)
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_output_projection_path_must_be_gitignored(self):
        with self.assertRaises(_runner().FullUniverseThemeProducerError):
            self._run_packet(output_projection_path=ROOT / "docs" / f"{self.slug}_theme.json")


if __name__ == "__main__":
    unittest.main()
