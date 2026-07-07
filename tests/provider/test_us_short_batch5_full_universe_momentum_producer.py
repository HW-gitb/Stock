from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402
from engine.us_short_eligibility_gate import load_eligibility_governance  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _GENERATED_AT,
    _PRICE_BASIS_DATE,
    _USED_DATE,
    _constant_projection,
)


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_universe_momentum_20260707"
PROJECTION_INPUTS_SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_full_candidate_projection_inputs_20260706"
RUNNER_MODULE = "runners.us_short_batch5_full_universe_momentum_producer"
_GOV_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
_PRICE_BASIS_YMD = _USED_DATE  # "2026-06-12"

# Five liquid, all-eligible names so one test can exercise every honest disposition at once.
_SPECS = {
    "AAPL": {"cik": 320193, "exchange": "NASDAQ", "shares": 15_000_000_000, "price": 200.0, "adv_usd": 50_000_000.0},
    "MSFT": {"cik": 789019, "exchange": "NASDAQ", "shares": 7_000_000_000, "price": 400.0, "adv_usd": 80_000_000.0},
    "JPM": {"cik": 19617, "exchange": "NYSE", "shares": 3_000_000_000, "price": 200.0, "adv_usd": 70_000_000.0},
    "GOOG": {"cik": 1652044, "exchange": "NASDAQ", "shares": 6_000_000_000, "price": 180.0, "adv_usd": 60_000_000.0},
    "AMZN": {"cik": 1018724, "exchange": "NASDAQ", "shares": 10_000_000_000, "price": 190.0, "adv_usd": 65_000_000.0},
}
_ALL_ELIGIBLE = ("AAPL", "MSFT", "JPM", "GOOG", "AMZN")


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _runner():
    return importlib.import_module(RUNNER_MODULE)


def _gov():
    return load_eligibility_governance(_GOV_PATH)


def _candidate_artifact(tickers):
    sec_tickers = {t: {"cik": _SPECS[t]["cik"], "exchange": _SPECS[t]["exchange"]} for t in tickers}
    sec_shares = {_SPECS[t]["cik"]: {"shares": _SPECS[t]["shares"], "end": "2026-03-31"} for t in tickers}
    market_data = {
        t: {
            "close": _SPECS[t]["price"],
            "volume": 100_000,
            "adv_usd": _SPECS[t]["adv_usd"],
            "adv_days_observed": 20,
            "price_as_of": _USED_DATE,
        }
        for t in tickers
    }
    rows = universe_fetch.apply_pass1(
        sec_tickers, sec_shares, market_data, governance=_gov(), as_of=_USED_DATE, observed_at=_GENERATED_AT
    )
    return universe_fetch.build_candidate_artifact(
        rows=rows,
        decision_date=_DECISION_DATE,
        price_basis_date=_PRICE_BASIS_DATE,
        used_date=_USED_DATE,
        observed_window_dates=[_USED_DATE, "2026-06-11"],
        generated_at=_GENERATED_AT,
        calendar_verification_status="pending_authoritative_cross_check",
    )


def _dates(n: int, *, as_of: str = _PRICE_BASIS_YMD) -> list[str]:
    end = datetime.strptime(as_of, "%Y-%m-%d").date()
    return [(end - timedelta(days=(n - 1 - idx))).isoformat() for idx in range(n)]


def _series(*, start: float, step: float, n: int = 72, as_of: str = _PRICE_BASIS_YMD,
            session: str = "RTH", adjustment_mode: str = "split_div_adjusted") -> dict:
    return {
        "as_of": as_of,
        "session": session,
        "adjustment_mode": adjustment_mode,
        "points": [
            {"date": date, "close": start + (idx * step), "volume": 1_000_000.0 + idx}
            for idx, date in enumerate(_dates(n, as_of=as_of))
        ],
    }


def _base_series_map() -> dict:
    # AAPL/MSFT full (scored); GOOG thin (insufficient_coverage, 8 pts -> only ret_5d);
    # AMZN too-short (insufficient_history, 3 pts < MIN_HISTORY); JPM ABSENT (absent_from_pool); benchmarks full.
    return {
        "AAPL": _series(start=100.0, step=2.0),
        "MSFT": _series(start=100.0, step=0.25),
        "GOOG": _series(start=100.0, step=1.0, n=8),
        "AMZN": _series(start=100.0, step=1.0, n=3),
        "SPY": _series(start=100.0, step=0.9),
        "QQQ": _series(start=100.0, step=1.0),
    }


def _series_packet(series_map, *, session: str = "RTH", adjustment_mode: str = "split_div_adjusted",
                   grouped_session_count: int = 90, provider_id: str = "massive",
                   as_of: str = _PRICE_BASIS_YMD) -> dict:
    return {
        "schema_name": "us_short_batch5_full_universe_momentum_series_packet",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-13T10:00:00+00:00",
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "full_universe_per_ticker_series_ready_for_local_momentum_projection",
            "full_market_reconstruction": True,
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
            "source_as_of": as_of,
        },
        "series_contract": {
            "benchmark_symbols": ["SPY", "QQQ"],
            "session": session,
            "adjustment_mode": adjustment_mode,
            "as_of": as_of,
            "grouped_session_count": grouped_session_count,
        },
        "provenance": {
            "provider_id": provider_id,
            "endpoint_or_family": "grouped_daily",
            "source_as_of": as_of,
            "observed_at": "2026-06-13T10:00:00+00:00",
            "coverage_status": "full",
            "parser_status": "ok",
        },
        "series_by_ticker": series_map,
    }


class FullUniverseMomentumProducerTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_full_universe_momentum_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "packet": STATE_DIR / f"{self.slug}_series_packet.json",
            "projection": STATE_DIR / f"{self.slug}_momentum_projection.json",
            "summary": SAMPLE_ROOT / self.slug / "summary.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact(_ALL_ELIGIBLE))
        _write_json(self.paths["packet"], _series_packet(_base_series_map()))

    def tearDown(self):
        extra = [
            STATE_DIR / f"{self.slug}_theme.json",
            STATE_DIR / f"{self.slug}_out_momentum.json",
            STATE_DIR / f"{self.slug}_out_theme.json",
        ]
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
            "series_packet_path": self.paths["packet"],
            "output_projection_path": self.paths["projection"],
            "summary_path": self.paths["summary"],
            "generated_at": "2026-06-15T12:00:00+00:00",
        }
        kwargs.update(overrides)
        return _runner().run_packet(**kwargs)

    def test_runner_and_schemas_are_routed_artifacts(self):
        runner = _runner()
        self.assertTrue(runner.PACKET_SCHEMA_PATH.exists())
        self.assertTrue(runner.SUMMARY_SCHEMA_PATH.exists())

    def test_scores_all_eligible_with_honest_dispositions(self):
        summary = self._run_packet()

        self.assertEqual(summary["scope"]["status"], "full_universe_momentum_projection_written")
        self.assertFalse(summary["scope"]["provider_calls_performed_by_runner"])
        self.assertEqual(summary["candidate_universe"]["eligible_count"], 5)
        self.assertEqual(summary["projection_contract"]["target_count"], 5)
        self.assertEqual(summary["projection_contract"]["momentum_scored_count"], 2)
        self.assertEqual(
            summary["projection_contract"]["disposition_counts"],
            {"scored": 2, "insufficient_history": 1, "insufficient_coverage": 1, "absent_from_pool": 1},
        )
        self.assertTrue(summary["projection_contract"]["real_momentum_price_source_consumed"])

        projection = _read_json(self.paths["projection"])
        self.assertEqual(projection["target_count"], 5)
        self.assertEqual(projection["scored_count"], 2)
        self.assertEqual(set(projection["momentum_by_ticker"]), {"AAPL", "MSFT"})
        self.assertEqual(set(projection["neutral_fill_tickers"]), {"GOOG", "AMZN", "JPM"})
        self.assertEqual(projection["coverage"]["GOOG"], "insufficient_coverage")
        self.assertEqual(projection["coverage"]["AMZN"], "insufficient_history")
        self.assertEqual(projection["coverage"]["JPM"], "absent_from_pool")
        self.assertEqual(
            set(projection),
            {"momentum_by_ticker", "neutral_fill_tickers", "coverage", "target_count", "scored_count"},
        )

    def test_output_projection_feeds_full_candidate_projection_inputs(self):
        # Prove the producer's projection is the SAME shape the funnel already consumes: feed it straight into
        # runners/us_short_batch5_full_candidate_projection_inputs.py as the momentum source and confirm 0 missing.
        self._run_packet()
        projection_inputs = importlib.import_module("runners.us_short_batch5_full_candidate_projection_inputs")

        theme_source = STATE_DIR / f"{self.slug}_theme.json"
        _write_json(theme_source, _constant_projection("theme_block_by_ticker", _ALL_ELIGIBLE, "scored_theme_base", score=60.0))
        out_summary = projection_inputs.run_packet(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            source_momentum_projection_path=self.paths["projection"],
            source_theme_projection_path=theme_source,
            output_momentum_projection_path=STATE_DIR / f"{self.slug}_out_momentum.json",
            output_theme_projection_path=STATE_DIR / f"{self.slug}_out_theme.json",
            summary_path=PROJECTION_INPUTS_SAMPLE_ROOT / self.slug / "summary.json",
            generated_at="2026-07-06T12:00:00+00:00",
        )

        self.assertEqual(out_summary["output_projection_contract"]["target_count"], 5)
        self.assertEqual(out_summary["output_projection_contract"]["momentum_scored_count"], 2)
        self.assertEqual(out_summary["source_inputs"]["source_momentum_scored_count"], 2)
        merged_momentum = _read_json(STATE_DIR / f"{self.slug}_out_momentum.json")
        self.assertEqual(set(merged_momentum["momentum_by_ticker"]), {"AAPL", "MSFT"})
        self.assertEqual(set(merged_momentum["coverage"]), set(_ALL_ELIGIBLE))

    def test_huge_close_ticker_is_gracefully_dispositioned_not_bare_overflow(self):
        # A forged/corrupt huge close must NOT bare-crash (engine _finite OverflowError containment): the ticker
        # is dispositioned insufficient_history and the run still completes writing the projection.
        series_map = _base_series_map()
        series_map["JPM"] = _series(start=100.0, step=2.0)
        series_map["JPM"]["points"][10]["close"] = 10 ** 400
        _write_json(self.paths["packet"], _series_packet(series_map))

        summary = self._run_packet()
        self.assertEqual(summary["scope"]["status"], "full_universe_momentum_projection_written")
        projection = _read_json(self.paths["projection"])
        self.assertEqual(projection["coverage"]["JPM"], "insufficient_history")
        self.assertNotIn("JPM", projection["momentum_by_ticker"])

    def test_missing_benchmark_fails_closed_before_writes(self):
        series_map = _base_series_map()
        del series_map["QQQ"]
        _write_json(self.paths["packet"], _series_packet(series_map))

        with self.assertRaises(_runner().FullUniverseMomentumProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_malformed_benchmark_series_fails_closed(self):
        # A benchmark that cannot parse would silently drop rel-strength for the WHOLE pool -> fail closed.
        series_map = _base_series_map()
        series_map["SPY"] = _series(start=100.0, step=0.9, n=3)  # too short to parse -> pit is None
        _write_json(self.paths["packet"], _series_packet(series_map))

        with self.assertRaises(_runner().FullUniverseMomentumProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_per_ticker_lookahead_as_of_fails_closed(self):
        series_map = _base_series_map()
        series_map["AAPL"]["as_of"] = "2026-06-15"  # future vs price_basis 2026-06-12
        _write_json(self.paths["packet"], _series_packet(series_map))

        with self.assertRaises(_runner().FullUniverseMomentumProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_stray_non_eligible_ticker_fails_closed(self):
        series_map = _base_series_map()
        series_map["TSLA"] = _series(start=100.0, step=1.0)  # not eligible, not a benchmark
        _write_json(self.paths["packet"], _series_packet(series_map))

        with self.assertRaises(_runner().FullUniverseMomentumProducerError):
            self._run_packet()
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_hostile_session_or_adjustment_string_is_rejected_before_write(self):
        # §6a finding A: session / adjustment_mode flow into the TRACKED summary, so they are bounded to a safe
        # charset (both schemas) and a hostile value (URL / secret / ticker-list) fails closed before any write.
        runner = _runner()
        for field, hostile in (("session", "s3://prod-secrets/massive.key"), ("adjustment_mode", "holdings=AAPL,MSFT")):
            with self.subTest(field=field):
                series_map = _base_series_map()
                for series in series_map.values():
                    series[field] = hostile
                packet = _series_packet(series_map, **{field: hostile})
                _write_json(self.paths["packet"], packet)
                self.paths["projection"].unlink(missing_ok=True)
                self.paths["summary"].unlink(missing_ok=True)
                with self.assertRaises(runner.FullUniverseMomentumProducerError):
                    self._run_packet()
                self.assertFalse(self.paths["projection"].exists())
                self.assertFalse(self.paths["summary"].exists())

    def test_tracked_summary_is_counts_only_no_secret_no_tickers(self):
        self._run_packet()
        text = self.paths["summary"].read_text(encoding="utf-8")
        lower = text.lower()
        for fragment in ("apikey=", "financialmodelingprep.com", "api.massive.com", "data.sec.gov",
                         "https://", "http://", "bearer ", "token=", '"points"', '"results"'):
            self.assertNotIn(fragment, lower)
        for ticker in _ALL_ELIGIBLE:
            self.assertNotIn(ticker, text)  # counts-only: no ticker lists in the tracked summary

    def test_summary_schema_rejects_scope_creep_claims(self):
        summary = self._run_packet()
        validator = Draft7Validator(_read_json(_runner().SUMMARY_SCHEMA_PATH))
        for path, value in (
            (("scope", "provider_calls_performed_by_runner"), True),
            (("scope", "full_market_call_performed"), True),
            (("prohibited_claims", "ship_gate_evidence_claimed"), True),
            (("storage", "summary_contains_ticker_lists"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)

    def test_preflight_only_validates_without_writing(self):
        result = _runner().run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            series_packet_path=self.paths["packet"],
            output_projection_path=self.paths["projection"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )
        self.assertEqual(result["scope"]["preflight_status"], "offline_preflight_passed")
        self.assertEqual(result["projection_preview"]["target_count"], 5)
        self.assertEqual(result["projection_preview"]["momentum_scored_count"], 2)
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_output_projection_path_must_be_gitignored_state_json(self):
        with self.assertRaises(_runner().FullUniverseMomentumProducerError):
            self._run_packet(output_projection_path=ROOT / "docs" / f"{self.slug}_momentum.json")


if __name__ == "__main__":
    unittest.main()
