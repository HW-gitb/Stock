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

from engine.us_short_risk_downgrade import risk_downgrade  # noqa: E402
from engine.us_short_seam_catalyst import DISPOSITION_SCORED_REALIZED  # noqa: E402
from engine.us_short_seam_score import compose_score_inputs  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _candidate_artifact,
    _constant_projection,
)
from tests.provider.us_short_projection_binding_test_helpers import bound_projection  # noqa: E402


STATE_DIR = ROOT / "state" / "us_short"
SUMMARY_DIR = ROOT / "provider_samples" / "us_short_batch5_full_candidate_projection_inputs_20260706"
PREFLIGHT_SUMMARY_DIR = ROOT / "provider_samples" / "us_short_batch5_full_candidate_pass2_preflight_20260706"
MODULE = "runners.us_short_batch5_full_candidate_projection_inputs"


def _write_json(path: Path, payload) -> Path:
    binding = payload.get("source_binding") if type(payload) is dict else None
    if type(payload) is dict and "_source_" in path.stem and (
        type(binding) is not dict or binding.get("producer_id") == "us_short_test_fixture"
    ):
        component = "momentum" if "momentum_by_ticker" in payload else "theme" if "theme_block_by_ticker" in payload else None
        candidate_path = path.with_name(path.stem.split("_source_", 1)[0] + "_candidate.json")
        if component is not None and candidate_path.is_file():
            payload = bound_projection(
                candidate_path=candidate_path, component=component, projection=payload,
                producer_id=f"us_short_batch5_full_universe_{component}_producer",
                source_roles=(
                    ("candidate_artifact", "momentum_series_packet")
                    if component == "momentum"
                    else ("candidate_artifact", "momentum_series_packet", "sector_classification_packet")
                ),
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _constant_catalyst_projection(targets, *, score=50.0):
    return {
        "catalyst_block_by_ticker": {ticker: score for ticker in targets},
        "neutral_fill_tickers": [],
        "coverage": {ticker: DISPOSITION_SCORED_REALIZED for ticker in targets},
        "target_count": len(targets),
        "scored_count": len(targets),
    }


class FullCandidateProjectionInputsTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_projection_inputs_{os.getpid()}_{self._testMethodName[:24]}"
        self.paths = {
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "source_momentum": STATE_DIR / f"{self.slug}_source_momentum.json",
            "source_theme": STATE_DIR / f"{self.slug}_source_theme.json",
            "output_momentum": STATE_DIR / f"{self.slug}_output_momentum.json",
            "output_theme": STATE_DIR / f"{self.slug}_output_theme.json",
            "summary": SUMMARY_DIR / self.slug / "summary.json",
            "preflight_summary": PREFLIGHT_SUMMARY_DIR / self.slug / "preflight_summary.json",
        }
        self.paths["summary"].parent.mkdir(parents=True, exist_ok=True)
        self.paths["preflight_summary"].parent.mkdir(parents=True, exist_ok=True)
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))
        _write_json(
            self.paths["source_momentum"],
            _constant_projection(
                "momentum_by_ticker", ("AAPL", "MSFT"), "scored", score=65.0,
                candidate_path=self.paths["candidate"], component="momentum",
                producer_id="us_short_batch5_full_universe_momentum_producer",
                source_roles=("candidate_artifact", "momentum_series_packet"),
            ),
        )
        _write_json(
            self.paths["source_theme"],
            _constant_projection(
                "theme_block_by_ticker", ("AAPL", "JPM"), "scored_theme_base", score=60.0,
                candidate_path=self.paths["candidate"], component="theme",
                producer_id="us_short_batch5_full_universe_theme_producer",
                source_roles=("candidate_artifact", "momentum_series_packet", "sector_classification_packet"),
            ),
        )

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        root = SUMMARY_DIR / self.slug
        if root.exists():
            for item in sorted(root.rglob("*"), reverse=True):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            root.rmdir()
        preflight_root = PREFLIGHT_SUMMARY_DIR / self.slug
        if preflight_root.exists():
            for item in sorted(preflight_root.rglob("*"), reverse=True):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            preflight_root.rmdir()

    def test_merges_partial_real_projections_with_explicit_neutral_full_candidate_coverage(self):
        runner = importlib.import_module(MODULE)

        summary = runner.run_packet(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            source_momentum_projection_path=self.paths["source_momentum"],
            source_theme_projection_path=self.paths["source_theme"],
            output_momentum_projection_path=self.paths["output_momentum"],
            output_theme_projection_path=self.paths["output_theme"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )

        self.assertEqual(summary["scope"]["status"], "full_candidate_projection_inputs_written")
        self.assertFalse(summary["scope"]["provider_calls_performed"])
        self.assertEqual(summary["candidate_universe"]["eligible_count"], 3)
        self.assertEqual(summary["output_projection_contract"]["target_count"], 3)
        self.assertEqual(summary["output_projection_contract"]["momentum_scored_count"], 2)
        self.assertEqual(summary["output_projection_contract"]["theme_scored_count"], 2)
        self.assertEqual(summary["output_projection_contract"]["momentum_neutral_fill_count"], 1)
        self.assertEqual(summary["output_projection_contract"]["theme_neutral_fill_count"], 1)

        momentum = _read_json(self.paths["output_momentum"])
        theme = _read_json(self.paths["output_theme"])
        self.assertEqual(set(momentum["momentum_by_ticker"]), {"AAPL", "MSFT"})
        self.assertEqual(momentum["neutral_fill_tickers"], ["JPM"])
        self.assertEqual(set(theme["theme_block_by_ticker"]), {"AAPL", "JPM"})
        self.assertEqual(theme["neutral_fill_tickers"], ["MSFT"])
        self.assertEqual(set(momentum["coverage"]), {"AAPL", "MSFT", "JPM"})
        self.assertEqual(set(theme["coverage"]), {"AAPL", "MSFT", "JPM"})

        composed = compose_score_inputs(
            target_tickers=["AAPL", "MSFT", "JPM"],
            momentum_projection=momentum,
            theme_projection=theme,
            catalyst_projection=_constant_catalyst_projection(("AAPL", "MSFT", "JPM")),
            risk_downgrade_by_ticker={ticker: risk_downgrade() for ticker in ("AAPL", "MSFT", "JPM")},
            theme_opportunity_state="strong",
        )
        self.assertEqual(set(composed["selection_inputs"]["per_ticker"]), {"AAPL", "MSFT", "JPM"})
        self.assertEqual(composed["scored_component_counts"]["momentum"], 2)
        self.assertEqual(composed["scored_component_counts"]["theme"], 2)

    def test_clockless_source_projection_is_rejected_before_outputs(self):
        runner = importlib.import_module(MODULE)
        source = _read_json(self.paths["source_momentum"])
        source.pop("source_binding")
        _write_json(self.paths["source_momentum"], source)
        with self.assertRaises(runner.FullCandidateProjectionInputsError):
            runner.run_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                source_momentum_projection_path=self.paths["source_momentum"],
                source_theme_projection_path=self.paths["source_theme"],
                output_momentum_projection_path=self.paths["output_momentum"],
                output_theme_projection_path=self.paths["output_theme"],
                summary_path=self.paths["summary"],
                generated_at="2026-07-06T12:00:00+00:00",
            )
        self.assertFalse(self.paths["output_momentum"].exists())
        self.assertFalse(self.paths["output_theme"].exists())

    def test_same_tickers_stale_decision_clock_is_rejected_before_outputs(self):
        runner = importlib.import_module(MODULE)
        source = _read_json(self.paths["source_momentum"])
        source["source_binding"]["decision_clock"]["expected_decision_date"] = "20260614"
        _write_json(self.paths["source_momentum"], source)
        with self.assertRaisesRegex(runner.FullCandidateProjectionInputsError, "decision clock"):
            runner.run_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                source_momentum_projection_path=self.paths["source_momentum"],
                source_theme_projection_path=self.paths["source_theme"],
                output_momentum_projection_path=self.paths["output_momentum"],
                output_theme_projection_path=self.paths["output_theme"],
                summary_path=self.paths["summary"],
                generated_at="2026-07-06T12:00:00+00:00",
            )
        self.assertFalse(self.paths["output_momentum"].exists())
        self.assertFalse(self.paths["output_theme"].exists())

    def test_source_artifact_hash_mismatch_is_rejected_before_outputs(self):
        runner = importlib.import_module(MODULE)
        source = _read_json(self.paths["source_theme"])
        source["source_binding"]["source_artifacts"][0]["sha256"] = "0" * 64
        _write_json(self.paths["source_theme"], source)
        with self.assertRaisesRegex(runner.FullCandidateProjectionInputsError, "hash mismatch"):
            runner.run_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                source_momentum_projection_path=self.paths["source_momentum"],
                source_theme_projection_path=self.paths["source_theme"],
                output_momentum_projection_path=self.paths["output_momentum"],
                output_theme_projection_path=self.paths["output_theme"],
                summary_path=self.paths["summary"],
                generated_at="2026-07-06T12:00:00+00:00",
            )
        self.assertFalse(self.paths["output_momentum"].exists())
        self.assertFalse(self.paths["output_theme"].exists())

    def test_preflight_treats_scored_plus_neutral_partition_as_full_local_coverage(self):
        runner = importlib.import_module(MODULE)
        preflight = importlib.import_module("runners.us_short_batch5_full_candidate_pass2_preflight")
        runner.run_packet(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            source_momentum_projection_path=self.paths["source_momentum"],
            source_theme_projection_path=self.paths["source_theme"],
            output_momentum_projection_path=self.paths["output_momentum"],
            output_theme_projection_path=self.paths["output_theme"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )

        summary = preflight.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["output_momentum"],
            theme_projection_path=self.paths["output_theme"],
            summary_path=self.paths["preflight_summary"],
            authorized_total_call_budget=16,
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:05:00+00:00",
        )

        self.assertEqual(summary["scope"]["status"], "ready_for_reviewed_live_execution")
        self.assertTrue(summary["local_input_coverage"]["all_required_local_inputs_cover_candidates"])
        self.assertEqual(summary["local_input_coverage"]["momentum_projection"]["missing_count"], 0)
        self.assertEqual(summary["local_input_coverage"]["theme_projection"]["missing_count"], 0)
        self.assertEqual(summary["pass2_target_universe"]["target_count"], 3)
        self.assertEqual(summary["pass2_target_universe"]["target_symbols"], ["AAPL", "JPM", "MSFT"])
        self.assertEqual(summary["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"], 16)
        self.assertEqual(summary["endpoint_call_forecast"]["total_calls_for_full_candidate_cut"], 16)
        self.assertFalse(summary["scope"]["network_access_performed"])

    def test_unhashable_coverage_disposition_raises_typed_error_before_writes(self):
        runner = importlib.import_module(MODULE)
        for bad_disposition in ([], {}):
            with self.subTest(type=type(bad_disposition).__name__):
                source = _constant_projection("momentum_by_ticker", ("AAPL", "MSFT"), "scored", score=65.0)
                source["coverage"]["AAPL"] = bad_disposition
                _write_json(self.paths["source_momentum"], source)
                self.paths["output_momentum"].unlink(missing_ok=True)
                self.paths["output_theme"].unlink(missing_ok=True)
                self.paths["summary"].unlink(missing_ok=True)

                with self.assertRaisesRegex(runner.FullCandidateProjectionInputsError, "disposition"):
                    runner.run_packet(
                        candidate_artifact_path=self.paths["candidate"],
                        expected_decision_date=_DECISION_DATE,
                        source_momentum_projection_path=self.paths["source_momentum"],
                        source_theme_projection_path=self.paths["source_theme"],
                        output_momentum_projection_path=self.paths["output_momentum"],
                        output_theme_projection_path=self.paths["output_theme"],
                        summary_path=self.paths["summary"],
                        generated_at="2026-06-15T12:00:00+00:00",
                    )

                self.assertFalse(self.paths["output_momentum"].exists())
                self.assertFalse(self.paths["output_theme"].exists())
                self.assertFalse(self.paths["summary"].exists())


if __name__ == "__main__":
    unittest.main()
