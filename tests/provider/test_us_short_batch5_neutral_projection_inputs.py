from __future__ import annotations

import importlib
import importlib.util
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
from engine.us_short_risk_downgrade import risk_downgrade  # noqa: E402
from engine.us_short_seam_catalyst import DISPOSITION_SCORED_REALIZED  # noqa: E402
from engine.us_short_seam_score import compose_score_inputs  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _candidate_artifact,
)


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_neutral_projection_inputs_20260704"
RUNNER_MODULE = "runners.us_short_batch5_neutral_projection_inputs"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _runner():
    return importlib.import_module(RUNNER_MODULE)


def _constant_catalyst_projection(targets, *, score=50.0):
    return {
        "catalyst_block_by_ticker": {ticker: score for ticker in targets},
        "neutral_fill_tickers": [],
        "coverage": {ticker: DISPOSITION_SCORED_REALIZED for ticker in targets},
        "target_count": len(targets),
        "scored_count": len(targets),
    }


class NeutralProjectionInputsTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_neutral_projection_inputs_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "momentum": STATE_DIR / f"{self.slug}_momentum_projection.json",
            "theme": STATE_DIR / f"{self.slug}_theme_projection.json",
            "summary": SAMPLE_ROOT / self.slug / "summary.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM", "LOWADV")))

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

    def test_runner_and_schema_are_routed_artifacts(self):
        self.assertIsNotNone(importlib.util.find_spec(RUNNER_MODULE))
        runner = _runner()
        self.assertTrue(runner.SUMMARY_SCHEMA_PATH.exists())

    def test_writes_neutral_projection_inputs_that_the_score_composer_consumes(self):
        runner = _runner()
        summary = runner.run_packet(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            selected_symbols=["aapl", "MSFT"],
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )

        self.assertEqual(summary["scope"]["status"], "neutral_projection_inputs_written")
        self.assertFalse(summary["scope"]["provider_calls_performed"])
        self.assertFalse(summary["scope"]["datahub_consumption_performed"])
        self.assertTrue(summary["storage"]["projection_paths_gitignored"])
        self.assertEqual(summary["sample_universe"]["symbols"], ["AAPL", "MSFT"])

        momentum = _read_json(self.paths["momentum"])
        theme = _read_json(self.paths["theme"])
        self.assertEqual(momentum["momentum_by_ticker"], {})
        self.assertEqual(momentum["neutral_fill_tickers"], ["AAPL", "MSFT"])
        self.assertEqual(set(momentum["coverage"].values()), {"absent_from_pool"})
        self.assertEqual(momentum["target_count"], 2)
        self.assertEqual(momentum["scored_count"], 0)
        self.assertEqual(theme["theme_block_by_ticker"], {})
        self.assertEqual(theme["neutral_fill_tickers"], ["AAPL", "MSFT"])
        self.assertEqual(set(theme["coverage"].values()), {"neutral_missing_theme_and_industry_base"})
        self.assertEqual(theme["target_count"], 2)
        self.assertEqual(theme["scored_count"], 0)

        composed = compose_score_inputs(
            target_tickers=["AAPL", "MSFT"],
            momentum_projection=momentum,
            theme_projection=theme,
            catalyst_projection=_constant_catalyst_projection(("AAPL", "MSFT")),
            risk_downgrade_by_ticker={ticker: risk_downgrade() for ticker in ("AAPL", "MSFT")},
            theme_opportunity_state="strong",
        )
        self.assertEqual(set(composed["selection_inputs"]["per_ticker"]), {"AAPL", "MSFT"})
        self.assertEqual(composed["scored_component_counts"]["momentum"], 0)
        self.assertEqual(composed["scored_component_counts"]["theme"], 0)
        self.assertEqual(composed["analysis_by_ticker"]["AAPL"]["score_blocks"], {"catalyst": 50.0})

        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com", text.lower())
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn('"payload"', text)

    def test_preflight_does_not_write_projection_or_summary_files(self):
        runner = _runner()
        result = runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            selected_symbols=["AAPL"],
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )

        self.assertEqual(result["scope"]["preflight_status"], "offline_preflight_passed")
        self.assertFalse(self.paths["momentum"].exists())
        self.assertFalse(self.paths["theme"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_selected_symbols_must_be_pass1_eligible_before_any_write(self):
        runner = _runner()

        with self.assertRaises(runner.NeutralProjectionInputsError):
            runner.run_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["LOWADV"],
                momentum_projection_path=self.paths["momentum"],
                theme_projection_path=self.paths["theme"],
                summary_path=self.paths["summary"],
                generated_at="2026-06-15T12:00:00+00:00",
            )

        self.assertFalse(self.paths["momentum"].exists())
        self.assertFalse(self.paths["theme"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_projection_outputs_must_be_gitignored_state_json(self):
        runner = _runner()

        with self.assertRaises(runner.NeutralProjectionInputsError):
            runner.run_preflight(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL"],
                momentum_projection_path=ROOT / "docs" / f"{self.slug}_momentum.json",
                theme_projection_path=self.paths["theme"],
                summary_path=self.paths["summary"],
                generated_at="2026-06-15T12:00:00+00:00",
            )

    def test_projection_outputs_must_not_collide_with_each_other_or_candidate_input(self):
        runner = _runner()

        with self.assertRaises(runner.NeutralProjectionInputsError):
            runner.run_preflight(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL"],
                momentum_projection_path=self.paths["momentum"],
                theme_projection_path=self.paths["momentum"],
                summary_path=self.paths["summary"],
                generated_at="2026-06-15T12:00:00+00:00",
            )

        with self.assertRaises(runner.NeutralProjectionInputsError):
            runner.run_preflight(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL"],
                momentum_projection_path=self.paths["candidate"],
                theme_projection_path=self.paths["theme"],
                summary_path=self.paths["summary"],
                generated_at="2026-06-15T12:00:00+00:00",
            )

    def test_summary_schema_rejects_scope_creep_claims(self):
        runner = _runner()
        summary = runner.run_packet(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            selected_symbols=["AAPL"],
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"],
            generated_at="2026-06-15T12:00:00+00:00",
        )
        schema = _read_json(runner.SUMMARY_SCHEMA_PATH)
        validator = Draft7Validator(schema)

        for path, value in (
            (("scope", "provider_calls_performed"), True),
            (("scope", "datahub_consumption_performed"), True),
            (("prohibited_claims", "live_momentum_source_evidence"), True),
            (("prohibited_claims", "live_theme_source_evidence"), True),
            (("prohibited_claims", "ship_gate_evidence_claimed"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)


if __name__ == "__main__":
    unittest.main()
