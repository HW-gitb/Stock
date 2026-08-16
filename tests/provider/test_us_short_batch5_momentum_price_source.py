from __future__ import annotations

import importlib
import importlib.util
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
from engine.us_short_risk_downgrade import risk_downgrade  # noqa: E402
from engine.us_short_seam_catalyst import DISPOSITION_SCORED_REALIZED  # noqa: E402
from engine.us_short_seam_score import compose_score_inputs  # noqa: E402
from engine.us_short_seam_theme import DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import _DECISION_DATE, _candidate_artifact  # noqa: E402
from tests.provider.us_short_private_test_root_light import (  # noqa: E402
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_momentum_price_source_20260705"
RUNNER_MODULE = "runners.us_short_batch5_momentum_price_source"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _runner():
    return importlib.import_module(RUNNER_MODULE)


_PRICE_BASIS_COMPACT = "20260612"
_PRICE_BASIS_YMD = "2026-06-12"


def _dates(n: int, *, as_of: str = _PRICE_BASIS_YMD) -> list[str]:
    end = datetime.strptime(as_of, "%Y-%m-%d").date()
    return [(end - timedelta(days=(n - 1 - idx))).isoformat() for idx in range(n)]


def _series(symbol: str, *, start: float, step: float, as_of: str = _PRICE_BASIS_YMD) -> dict:
    dates = _dates(72, as_of=as_of)
    return {
        "as_of": as_of,
        "session": "RTH",
        "adjustment_mode": "split_adjusted",
        "points": [
            {"date": date, "close": start + (idx * step), "volume": 1_000_000.0 + idx}
            for idx, date in enumerate(dates)
        ],
    }


def _provenance(symbol: str, *, source_as_of: str = _PRICE_BASIS_YMD) -> dict:
    return {
        "provider_id": "local_test_price_packet",
        "endpoint_or_family": "daily_price_history",
        "source_as_of": source_as_of,
        "observed_at": "2026-06-13T10:00:00+00:00",
        "coverage_status": "full",
        "parser_status": "ok",
        "lineage_ref": f"local_test_price_packet:daily_price_history:{source_as_of}#{symbol.lower()}",
    }


def _source_packet(*, symbols=("AAPL", "MSFT"), price_basis_date: str = _PRICE_BASIS_YMD) -> dict:
    series = {
        "AAPL": _series("AAPL", start=100.0, step=2.0, as_of=price_basis_date),
        "MSFT": _series("MSFT", start=100.0, step=0.25, as_of=price_basis_date),
        "SPY": _series("SPY", start=100.0, step=0.9, as_of=price_basis_date),
        "QQQ": _series("QQQ", start=100.0, step=1.0, as_of=price_basis_date),
    }
    return {
        "schema_name": "us_short_batch5_momentum_price_source_packet",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-13T10:00:00+00:00",
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "price_history_source_packet_ready_for_local_momentum_projection",
            "network_access_performed_by_packet_producer": False,
            "provider_calls_performed_by_packet_producer": False,
            "raw_payload_refs_gitignored": True,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": _DECISION_DATE,
            "candidate_price_basis_date": _PRICE_BASIS_COMPACT,
            "price_basis_date": price_basis_date,
            "source_as_of": price_basis_date,
        },
        "series_contract": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "selected_symbols": list(symbols),
            "benchmark_symbols": ["SPY", "QQQ"],
            "session": "RTH",
            "adjustment_mode": "split_adjusted",
            "min_points_per_series": 64,
            "full_market_sample": False,
        },
        "series_by_ticker": {symbol: series[symbol] for symbol in list(symbols) + ["SPY", "QQQ"]},
        "provenance_by_ticker": {
            symbol: _provenance(symbol, source_as_of=price_basis_date)
            for symbol in list(symbols) + ["SPY", "QQQ"]
        },
        "preflight_gates": {
            "local_files_only": True,
            "candidate_artifact_must_match_price_basis": True,
            "selected_symbols_must_be_pass1_eligible": True,
            "benchmarks_required": True,
            "output_must_be_gitignored": True,
            "no_provider_fetch_by_runner": True,
            "no_datahub_or_production": True,
        },
        "prohibited_claims": {
            "provider_selection_complete": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "live_normalized_evidence": False,
            "ship_gate_evidence": False,
            "production_ready": False,
            "datahub_consumed": False,
        },
    }


def _theme_projection(targets):
    return {
        "theme_block_by_ticker": {},
        "neutral_fill_tickers": list(targets),
        "coverage": {
            ticker: DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE
            for ticker in targets
        },
        "target_count": len(targets),
        "scored_count": 0,
    }


def _catalyst_projection(targets, *, score=50.0):
    return {
        "catalyst_block_by_ticker": {ticker: score for ticker in targets},
        "neutral_fill_tickers": [],
        "coverage": {ticker: DISPOSITION_SCORED_REALIZED for ticker in targets},
        "target_count": len(targets),
        "scored_count": len(targets),
    }


class MomentumPriceSourceRunnerTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_momentum_price_source_20260705"
        )
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        self.slug = f"test_momentum_price_source_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "candidate": self.state_root / f"{self.slug}_candidate.json",
            "source_packet": self.state_root / f"{self.slug}_source_packet.json",
            "projection": self.state_root / f"{self.slug}_momentum_projection.json",
            "summary": self.sample_root / "momentum_price_source_20260705" / self.slug / "summary.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))
        _write_json(self.paths["source_packet"], _source_packet(symbols=("AAPL", "MSFT")))

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)

    def test_runner_and_schemas_are_routed_artifacts(self):
        self.assertIsNotNone(importlib.util.find_spec(RUNNER_MODULE))
        runner = _runner()
        self.assertTrue(runner.PACKET_SCHEMA_PATH.exists())
        self.assertTrue(runner.SUMMARY_SCHEMA_PATH.exists())

    def test_writes_momentum_projection_from_price_source_packet(self):
        runner = _runner()
        summary = runner.run_packet(
            candidate_artifact_path=self.paths["candidate"],
            source_packet_path=self.paths["source_packet"],
            output_projection_path=self.paths["projection"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )

        self.assertEqual(summary["scope"]["status"], "momentum_projection_written")
        self.assertFalse(summary["scope"]["network_access_performed_by_runner"])
        self.assertFalse(summary["scope"]["provider_calls_performed_by_runner"])
        self.assertTrue(summary["storage"]["output_projection_path_gitignored"])
        self.assertEqual(summary["sample_universe"]["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(summary["price_source"]["benchmark_symbols"], ["SPY", "QQQ"])
        self.assertEqual(summary["projection_contract"]["momentum_scored_count"], 2)

        projection = _read_json(self.paths["projection"])
        self.assertEqual(projection["target_count"], 2)
        self.assertEqual(projection["scored_count"], 2)
        self.assertEqual(projection["neutral_fill_tickers"], [])
        self.assertEqual(set(projection["coverage"].values()), {"scored"})
        self.assertEqual(set(projection["momentum_by_ticker"]), {"AAPL", "MSFT"})
        self.assertGreater(projection["momentum_by_ticker"]["AAPL"], projection["momentum_by_ticker"]["MSFT"])

        composed = compose_score_inputs(
            target_tickers=["AAPL", "MSFT"],
            momentum_projection=projection,
            theme_projection=_theme_projection(("AAPL", "MSFT")),
            catalyst_projection=_catalyst_projection(("AAPL", "MSFT")),
            risk_downgrade_by_ticker={ticker: risk_downgrade() for ticker in ("AAPL", "MSFT")},
            theme_opportunity_state="strong",
        )
        self.assertEqual(composed["scored_component_counts"]["momentum"], 2)
        self.assertEqual(set(composed["selection_inputs"]["per_ticker"]), {"AAPL", "MSFT"})

        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com", text.lower())
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn('"points"', text)

    def test_hostile_provider_ids_are_rejected_before_tracked_summary_write(self):
        runner = _runner()
        packet_schema = _read_json(runner.PACKET_SCHEMA_PATH)
        validator = Draft7Validator(packet_schema)
        hostile_provider_ids = (
            "Bearer CANARY_TOKEN",
            "http://provider.test/v3?token=CANARY",
            "AWS_STYLE_ACCESS_KEY_CANARY",
            "user:CANARY@db.internal/prices",
            " ",
        )

        for idx, provider_id in enumerate(hostile_provider_ids):
            source_packet_path = self.state_root / f"{self.slug}_{idx}_source_packet.json"
            projection_path = self.state_root / f"{self.slug}_{idx}_momentum_projection.json"
            summary_path = self.sample_root / "momentum_price_source_20260705" / self.slug / f"hostile_summary_{idx}.json"
            packet = _source_packet(symbols=("AAPL", "MSFT"))
            for provenance in packet["provenance_by_ticker"].values():
                provenance["provider_id"] = provider_id
            _write_json(source_packet_path, packet)

            try:
                with self.subTest(provider_id=provider_id):
                    self.assertGreater(len(list(validator.iter_errors(packet))), 0)
                    with self.assertRaises(runner.MomentumPriceSourceError):
                        runner.run_packet(
                            candidate_artifact_path=self.paths["candidate"],
                            source_packet_path=source_packet_path,
                            output_projection_path=projection_path,
                            summary_path=summary_path,
                            generated_at="2026-06-15T12:00:00+00:00",
                        )
                    self.assertFalse(projection_path.exists())
                    self.assertFalse(summary_path.exists())
            finally:
                source_packet_path.unlink(missing_ok=True)
                projection_path.unlink(missing_ok=True)
                summary_path.unlink(missing_ok=True)

    def test_summary_parent_file_fails_closed_before_projection_write(self):
        bad_parent = self.sample_root / "momentum_price_source_20260705" / self.slug / "summary_parent_file"
        bad_parent.parent.mkdir(parents=True, exist_ok=True)
        bad_parent.write_text("not a directory", encoding="utf-8")
        bad_summary_path = bad_parent / "summary.json"
        runner = _runner()

        with self.assertRaises(runner.MomentumPriceSourceError):
            runner.run_packet(
                candidate_artifact_path=self.paths["candidate"],
                source_packet_path=self.paths["source_packet"],
                output_projection_path=self.paths["projection"],
                summary_path=bad_summary_path,
                generated_at="2026-06-15T12:00:00+00:00",
            )

        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(bad_summary_path.exists())

    def test_preflight_validates_without_writing_outputs(self):
        runner = _runner()
        result = runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            source_packet_path=self.paths["source_packet"],
            output_projection_path=self.paths["projection"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )

        self.assertEqual(result["scope"]["preflight_status"], "offline_preflight_passed")
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_rejects_price_basis_mismatch_before_any_write(self):
        _write_json(self.paths["source_packet"], _source_packet(price_basis_date="2026-06-11"))
        runner = _runner()

        with self.assertRaises(runner.MomentumPriceSourceError):
            runner.run_packet(
                candidate_artifact_path=self.paths["candidate"],
                source_packet_path=self.paths["source_packet"],
                output_projection_path=self.paths["projection"],
                summary_path=self.paths["summary"],
                generated_at="2026-06-15T12:00:00+00:00",
            )

        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_huge_price_number_fails_closed_without_bare_overflow(self):
        packet = _source_packet()
        packet["series_by_ticker"]["AAPL"]["points"][10]["close"] = 10**400
        _write_json(self.paths["source_packet"], packet)
        runner = _runner()

        with self.assertRaises(runner.MomentumPriceSourceError):
            runner.run_packet(
                candidate_artifact_path=self.paths["candidate"],
                source_packet_path=self.paths["source_packet"],
                output_projection_path=self.paths["projection"],
                summary_path=self.paths["summary"],
                generated_at="2026-06-15T12:00:00+00:00",
            )

        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_missing_required_benchmark_rejected(self):
        packet = _source_packet()
        del packet["series_by_ticker"]["QQQ"]
        del packet["provenance_by_ticker"]["QQQ"]
        _write_json(self.paths["source_packet"], packet)
        runner = _runner()

        with self.assertRaises(runner.MomentumPriceSourceError):
            runner.run_preflight(
                candidate_artifact_path=self.paths["candidate"],
                source_packet_path=self.paths["source_packet"],
                output_projection_path=self.paths["projection"],
                summary_path=self.paths["summary"],
                generated_at="2026-06-15T12:00:00+00:00",
            )

    def test_output_path_must_be_gitignored_state_json(self):
        runner = _runner()

        with self.assertRaises(runner.MomentumPriceSourceError):
            runner.run_preflight(
                candidate_artifact_path=self.paths["candidate"],
                source_packet_path=self.paths["source_packet"],
                output_projection_path=ROOT / "docs" / f"{self.slug}_momentum.json",
                summary_path=self.paths["summary"],
                generated_at="2026-06-15T12:00:00+00:00",
            )

    def test_summary_schema_rejects_scope_creep_claims(self):
        runner = _runner()
        summary = runner.run_packet(
            candidate_artifact_path=self.paths["candidate"],
            source_packet_path=self.paths["source_packet"],
            output_projection_path=self.paths["projection"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )
        schema = _read_json(runner.SUMMARY_SCHEMA_PATH)
        validator = Draft7Validator(schema)

        for path, value in (
            (("scope", "provider_calls_performed_by_runner"), True),
            (("scope", "datahub_consumption_performed"), True),
            (("prohibited_claims", "ship_gate_evidence_claimed"), True),
            (("projection_contract", "real_theme_or_gics_source_consumed"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)


if __name__ == "__main__":
    unittest.main()
