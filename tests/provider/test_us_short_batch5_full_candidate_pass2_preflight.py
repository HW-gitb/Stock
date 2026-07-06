from __future__ import annotations

import copy
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
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _candidate_artifact,
    _constant_projection,
)


STATE_DIR = ROOT / "state" / "us_short"
SUMMARY_DIR = ROOT / "provider_samples" / "us_short_batch5_full_candidate_pass2_preflight_20260706"
MODULE = "runners.us_short_batch5_full_candidate_pass2_preflight"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class FullCandidatePass2PreflightTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_full_candidate_pass2_preflight_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "momentum": STATE_DIR / f"{self.slug}_momentum.json",
            "theme": STATE_DIR / f"{self.slug}_theme.json",
            "summary": SUMMARY_DIR / self.slug / "summary.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))
        _write_json(
            self.paths["momentum"],
            _constant_projection("momentum_by_ticker", ("AAPL", "MSFT"), "scored", score=50.0),
        )
        _write_json(
            self.paths["theme"],
            _constant_projection("theme_block_by_ticker", ("AAPL", "MSFT"), "scored_theme_base", score=50.0),
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

    def _module(self):
        return importlib.import_module(MODULE)

    def test_preflight_blocks_when_local_score_inputs_do_not_cover_full_candidate_set(self):
        runner = self._module()

        summary = runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"],
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )

        self.assertEqual(summary["scope"]["status"], "blocked_missing_local_inputs")
        self.assertFalse(summary["scope"]["provider_calls_performed"])
        self.assertFalse(summary["scope"]["raw_payload_storage_performed"])
        self.assertEqual(summary["candidate_universe"]["eligible_count"], 3)
        self.assertEqual(summary["local_input_coverage"]["momentum_projection"]["covered_count"], 2)
        self.assertEqual(summary["local_input_coverage"]["theme_projection"]["missing_count"], 1)
        self.assertEqual(
            summary["endpoint_call_forecast"]["families"]["pass2_source_packet"]["total_calls"],
            10,
        )
        self.assertEqual(
            summary["endpoint_call_forecast"]["families"]["corporate_action_live_half"]["total_calls"],
            6,
        )
        self.assertEqual(summary["endpoint_call_forecast"]["total_calls_for_full_candidate_cut"], 16)
        self.assertFalse(summary["execution_gate"]["ready_to_run_full_candidate_live_packet"])
        self.assertTrue(self.paths["summary"].exists())
        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com", text.lower())
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn('"payload"', text)

    def test_preflight_can_mark_ready_without_network_when_local_inputs_cover_all_candidates(self):
        runner = self._module()
        _write_json(
            self.paths["momentum"],
            _constant_projection("momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0),
        )
        _write_json(
            self.paths["theme"],
            _constant_projection("theme_block_by_ticker", ("AAPL", "MSFT", "JPM"), "scored_theme_base", score=50.0),
        )

        summary = runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"],
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )

        self.assertEqual(summary["scope"]["status"], "ready_for_reviewed_live_execution")
        self.assertFalse(summary["scope"]["network_access_performed"])
        self.assertEqual(summary["local_input_coverage"]["momentum_projection"]["missing_count"], 0)
        self.assertTrue(summary["execution_gate"]["ready_to_run_full_candidate_live_packet"])

    def test_authorization_required_before_summary_write(self):
        runner = self._module()

        with self.assertRaisesRegex(runner.FullCandidatePass2PreflightError, "authorization"):
            runner.run_preflight(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                momentum_projection_path=self.paths["momentum"],
                theme_projection_path=self.paths["theme"],
                summary_path=self.paths["summary"],
                confirm_user_authorization=False,
                generated_at="2026-07-06T12:00:00+00:00",
            )

        self.assertFalse(self.paths["summary"].exists())

    def test_invalid_calendar_price_basis_date_raises_typed_error_without_summary(self):
        runner = self._module()

        for bad_date in ("20261301", "20260230"):
            with self.subTest(bad_date=bad_date):
                candidate = _candidate_artifact(("AAPL", "MSFT", "JPM"))
                candidate["price_basis_date"] = bad_date
                _write_json(self.paths["candidate"], candidate)
                self.paths["summary"].unlink(missing_ok=True)

                with self.assertRaisesRegex(runner.FullCandidatePass2PreflightError, "price_basis_date"):
                    runner.run_preflight(
                        candidate_artifact_path=self.paths["candidate"],
                        expected_decision_date=_DECISION_DATE,
                        momentum_projection_path=self.paths["momentum"],
                        theme_projection_path=self.paths["theme"],
                        summary_path=self.paths["summary"],
                        confirm_user_authorization=True,
                        generated_at="2026-07-06T12:00:00+00:00",
                    )

                self.assertFalse(self.paths["summary"].exists())

    def test_summary_schema_rejects_scope_creep_and_drift(self):
        runner = self._module()
        summary = runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"],
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )
        schema = json.loads(runner.SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft7Validator(schema)

        for path, value in (
            (("scope", "network_access_performed"), True),
            (("scope", "provider_calls_performed"), True),
            (("scope", "full_market_call_performed"), True),
            (("scope", "ship_gate_or_live_normalized_evidence_claimed"), True),
            (("prohibited_claims", "datahub_consumed"), True),
            (("endpoint_call_forecast", "families", "pass2_source_packet", "sec_company_tickers_mapping_calls"), 2),
            (("endpoint_call_forecast", "families", "corporate_action_live_half", "corporate_action_reconciliation_performed_by_preflight"), True),
        ):
            mutated = copy.deepcopy(summary)
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertFalse(validator.is_valid(mutated), path)


if __name__ == "__main__":
    unittest.main()
