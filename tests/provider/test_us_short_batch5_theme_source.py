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
from engine.us_short_seam_momentum import DISPOSITION_SCORED as MOMENTUM_SCORED  # noqa: E402
from engine.us_short_seam_score import compose_score_inputs  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import _DECISION_DATE, _candidate_artifact  # noqa: E402


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_theme_source_20260705"
RUNNER_MODULE = "runners.us_short_batch5_theme_source"

_PRICE_BASIS_COMPACT = "20260612"
_PRICE_BASIS_YMD = "2026-06-12"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _runner():
    return importlib.import_module(RUNNER_MODULE)


def _dates(n: int, *, as_of: str = _PRICE_BASIS_YMD) -> list[str]:
    end = datetime.strptime(as_of, "%Y-%m-%d").date()
    return [(end - timedelta(days=(n - 1 - idx))).isoformat() for idx in range(n)]


def _series(*, start: float, step: float, volume_start: float, volume_step: float, as_of: str = _PRICE_BASIS_YMD) -> dict:
    return {
        "as_of": as_of,
        "session": "RTH",
        "adjustment_mode": "split_adjusted",
        "points": [
            {"date": date, "close": start + (idx * step), "volume": volume_start + (idx * volume_step)}
            for idx, date in enumerate(_dates(72, as_of=as_of))
        ],
    }


def _hot_series() -> dict:
    return _series(start=100.0, step=2.0, volume_start=1_000_000.0, volume_step=50_000.0)


def _cold_series() -> dict:
    return _series(start=200.0, step=-0.75, volume_start=2_000_000.0, volume_step=0.0)


def _benchmark_series() -> dict:
    return _series(start=100.0, step=0.5, volume_start=5_000_000.0, volume_step=5_000.0)


def _source_packet(*, selected=("AAPL", "JPM"), selected_only: bool = False) -> dict:
    industry_members = {
        "AAPL": {"sector": "Technology", "series": _hot_series()},
        "MSFT": {"sector": "Technology", "series": _hot_series()},
        "NVDA": {"sector": "Technology", "series": _hot_series()},
        "JPM": {"sector": "Financials", "series": _cold_series()},
        "BAC": {"sector": "Financials", "series": _cold_series()},
        "WFC": {"sector": "Financials", "series": _cold_series()},
    }
    if selected_only:
        industry_members = {ticker: industry_members[ticker] for ticker in selected}

    themes_by_id = {
        "AI": {"members": {"AAPL": _hot_series(), "MSFT": _hot_series(), "NVDA": _hot_series()}},
        "BANKS": {"members": {"JPM": _cold_series(), "BAC": _cold_series(), "WFC": _cold_series()}},
    }
    if selected_only:
        themes_by_id = {
            "AI": {"members": {ticker: _hot_series() for ticker in selected if ticker in {"AAPL", "MSFT", "NVDA"}}},
            "BANKS": {"members": {ticker: _cold_series() for ticker in selected if ticker in {"JPM", "BAC", "WFC"}}},
        }
        themes_by_id = {theme_id: theme for theme_id, theme in themes_by_id.items() if theme["members"]}

    return {
        "schema_name": "us_short_batch5_theme_source_packet",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-13T10:00:00+00:00",
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "theme_source_packet_ready_for_local_projection",
            "network_access_performed_by_packet_producer": False,
            "provider_calls_performed_by_packet_producer": False,
            "raw_payload_refs_gitignored": True,
            "full_gics_peer_pool": not selected_only,
            "provisional_theme_membership_source": "reviewed_local_source_packet",
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": _DECISION_DATE,
            "candidate_price_basis_date": _PRICE_BASIS_COMPACT,
            "price_basis_date": _PRICE_BASIS_YMD,
            "source_as_of": _PRICE_BASIS_YMD,
        },
        "source_contract": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "selected_symbols": list(selected),
            "benchmark_symbols": ["SPY", "QQQ"],
            "session": "RTH",
            "adjustment_mode": "split_adjusted",
            "min_points_per_series": 64,
            "membership_pool_basis": "full_gics_peer_pool_and_provisional_theme_members",
            "full_gics_peer_pool": not selected_only,
            "full_market_sample": False,
            "provisional_theme_membership_frozen": True,
        },
        "industry_members_by_ticker": industry_members,
        "provisional_themes_by_id": themes_by_id,
        "theme_members_by_id": {
            theme_id: list(theme["members"])
            for theme_id, theme in themes_by_id.items()
        },
        "benchmark_series_by_ticker": {"SPY": _benchmark_series(), "QQQ": _benchmark_series()},
        "preflight_gates": {
            "local_files_only": True,
            "candidate_artifact_must_match_price_basis": True,
            "selected_symbols_must_be_pass1_eligible": True,
            "benchmarks_required": True,
            "full_gics_peer_pool_required": True,
            "selected_symbol_only_membership_rejected": True,
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


def _per_scored_group_selected_only_packet() -> dict:
    packet = _source_packet(selected=("AAPL", "MSFT", "JPM"))
    packet["industry_members_by_ticker"] = {
        "AAPL": {"sector": "MegaHot", "series": _hot_series()},
        "MSFT": {"sector": "MegaHot", "series": _hot_series()},
        "JPM": {"sector": "MegaHot", "series": _hot_series()},
        "ZZZZ": {"sector": "InertFiller", "series": _cold_series()},
    }
    packet["provisional_themes_by_id"] = {
        "MEGA": {"members": {"AAPL": _hot_series(), "MSFT": _hot_series(), "JPM": _hot_series()}},
        "INERT": {"members": {"ZZZZ": _cold_series()}},
    }
    packet["theme_members_by_id"] = {
        theme_id: list(theme["members"])
        for theme_id, theme in packet["provisional_themes_by_id"].items()
    }
    return packet


def _momentum_projection(targets):
    return {
        "momentum_by_ticker": {ticker: 75.0 - idx for idx, ticker in enumerate(targets)},
        "neutral_fill_tickers": [],
        "coverage": {ticker: MOMENTUM_SCORED for ticker in targets},
        "target_count": len(targets),
        "scored_count": len(targets),
    }


def _catalyst_projection(targets, *, score=50.0):
    return {
        "catalyst_block_by_ticker": {ticker: score for ticker in targets},
        "neutral_fill_tickers": [],
        "coverage": {ticker: DISPOSITION_SCORED_REALIZED for ticker in targets},
        "target_count": len(targets),
        "scored_count": len(targets),
    }


class ThemeSourceRunnerTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_theme_source_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "source_packet": STATE_DIR / f"{self.slug}_source_packet.json",
            "projection": STATE_DIR / f"{self.slug}_theme_projection.json",
            "summary": SAMPLE_ROOT / self.slug / "summary.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))
        _write_json(self.paths["source_packet"], _source_packet())

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        root = SAMPLE_ROOT / self.slug
        if root.exists():
            for item in sorted(root.rglob("*"), reverse=True):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            root.rmdir()

    def test_runner_and_schemas_are_routed_artifacts(self):
        self.assertIsNotNone(importlib.util.find_spec(RUNNER_MODULE))
        runner = _runner()
        self.assertTrue(runner.PACKET_SCHEMA_PATH.exists())
        self.assertTrue(runner.SUMMARY_SCHEMA_PATH.exists())

    def test_writes_theme_projection_from_full_source_packet(self):
        runner = _runner()
        summary = runner.run_packet(
            candidate_artifact_path=self.paths["candidate"],
            source_packet_path=self.paths["source_packet"],
            output_projection_path=self.paths["projection"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )

        self.assertEqual(summary["scope"]["status"], "theme_projection_written")
        self.assertFalse(summary["scope"]["network_access_performed_by_runner"])
        self.assertFalse(summary["scope"]["provider_calls_performed_by_runner"])
        self.assertTrue(summary["storage"]["output_projection_path_gitignored"])
        self.assertEqual(summary["sample_universe"]["symbols"], ["AAPL", "JPM"])
        self.assertEqual(summary["theme_source"]["industry_member_count"], 6)
        self.assertEqual(summary["theme_source"]["theme_count"], 2)
        self.assertEqual(summary["theme_source"]["benchmark_symbols"], ["SPY", "QQQ"])
        self.assertTrue(summary["projection_contract"]["real_theme_or_gics_source_consumed"])
        self.assertTrue(summary["projection_contract"]["selected_symbol_only_membership_rejected"])

        projection = _read_json(self.paths["projection"])
        self.assertEqual(projection["target_count"], 2)
        self.assertEqual(projection["scored_count"], 2)
        self.assertEqual(projection["neutral_fill_tickers"], [])
        self.assertEqual(set(projection["coverage"].values()), {"scored_theme_base"})
        self.assertEqual(set(projection["theme_block_by_ticker"]), {"AAPL", "JPM"})
        self.assertGreater(projection["theme_block_by_ticker"]["AAPL"], projection["theme_block_by_ticker"]["JPM"])

        composed = compose_score_inputs(
            target_tickers=["AAPL", "JPM"],
            momentum_projection=_momentum_projection(("AAPL", "JPM")),
            theme_projection=projection,
            catalyst_projection=_catalyst_projection(("AAPL", "JPM")),
            risk_downgrade_by_ticker={ticker: risk_downgrade() for ticker in ("AAPL", "JPM")},
            theme_opportunity_state="strong",
        )
        self.assertEqual(composed["scored_component_counts"]["theme"], 2)
        self.assertEqual(set(composed["selection_inputs"]["per_ticker"]), {"AAPL", "JPM"})

        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com", text.lower())
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn('"points"', text)

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
        self.assertEqual(result["projection_preview"]["target_count"], 2)
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_selected_only_membership_rejected_before_any_write(self):
        packet = _source_packet(selected_only=True)
        _write_json(self.paths["source_packet"], packet)
        runner = _runner()

        with self.assertRaises(runner.ThemeSourceError):
            runner.run_preflight(
                candidate_artifact_path=self.paths["candidate"],
                source_packet_path=self.paths["source_packet"],
                output_projection_path=self.paths["projection"],
                summary_path=self.paths["summary"],
                generated_at="2026-06-15T12:00:00+00:00",
            )

        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

        with self.assertRaises(runner.ThemeSourceError):
            runner.run_packet(
                candidate_artifact_path=self.paths["candidate"],
                source_packet_path=self.paths["source_packet"],
                output_projection_path=self.paths["projection"],
                summary_path=self.paths["summary"],
                generated_at="2026-06-15T12:00:00+00:00",
            )

        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_per_scored_group_selected_only_membership_rejected_before_any_write(self):
        packet = _per_scored_group_selected_only_packet()
        _write_json(self.paths["source_packet"], packet)
        runner = _runner()

        with self.assertRaises(runner.ThemeSourceError):
            runner.run_packet(
                candidate_artifact_path=self.paths["candidate"],
                source_packet_path=self.paths["source_packet"],
                output_projection_path=self.paths["projection"],
                summary_path=self.paths["summary"],
                generated_at="2026-06-15T12:00:00+00:00",
            )

        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_summary_parent_file_fails_closed_before_projection_write(self):
        bad_parent = SAMPLE_ROOT / self.slug / "summary_parent_file"
        bad_parent.parent.mkdir(parents=True, exist_ok=True)
        bad_parent.write_text("not a directory", encoding="utf-8")
        bad_summary_path = bad_parent / "summary.json"
        runner = _runner()

        with self.assertRaises(runner.ThemeSourceError):
            runner.run_packet(
                candidate_artifact_path=self.paths["candidate"],
                source_packet_path=self.paths["source_packet"],
                output_projection_path=self.paths["projection"],
                summary_path=bad_summary_path,
                generated_at="2026-06-15T12:00:00+00:00",
            )

        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(bad_summary_path.exists())

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
            (("theme_source", "full_gics_peer_pool_consumed"), False),
            (("projection_contract", "selected_symbol_only_membership_rejected"), False),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)


if __name__ == "__main__":
    unittest.main()
