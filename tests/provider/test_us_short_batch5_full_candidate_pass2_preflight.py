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
from engine.us_short_projection_binding import projection_payload_sha256  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _candidate_artifact,
    _constant_projection,
)
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402
from tests.provider.us_short_projection_binding_test_helpers import bound_projection  # noqa: E402
from tests.provider.us_short_private_test_root import (  # noqa: E402
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)


STATE_DIR = ROOT / "state" / "us_short"
SUMMARY_DIR = ROOT / "provider_samples" / "us_short_batch5_full_candidate_pass2_preflight" / _DECISION_DATE
MODULE = "runners.us_short_batch5_full_candidate_pass2_preflight"


def _write_json(path: Path, payload) -> Path:
    binding = payload.get("source_binding") if type(payload) is dict else None
    if type(payload) is dict and (
        type(binding) is not dict or binding.get("producer_id") == "us_short_test_fixture"
    ):
        component = "momentum" if "momentum_by_ticker" in payload else "theme" if "theme_block_by_ticker" in payload else None
        candidate_path = path.with_name(path.stem.rsplit("_", 1)[0] + "_candidate.json")
        if component is not None and candidate_path.is_file():
            payload = bound_projection(candidate_path=candidate_path, component=component, projection=payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class FullCandidatePass2PreflightTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_dir = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._summary_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_full_candidate_pass2_preflight" / _DECISION_DATE
        )
        self.summary_root = Path(self._summary_root_context.__enter__())
        self.addCleanup(self._summary_root_context.__exit__, None, None, None)
        runner = importlib.import_module(MODULE)
        original_git_ignored = runner._git_ignored
        state_root = self.state_dir.resolve()

        def _git_ignored_for_private_test(path):
            resolved = Path(path).resolve()
            if resolved == state_root or state_root in resolved.parents:
                return True
            return original_git_ignored(path)

        runner._git_ignored = _git_ignored_for_private_test
        self.addCleanup(setattr, runner, "_git_ignored", original_git_ignored)
        self.slug = f"test_full_candidate_pass2_preflight_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "candidate": self.state_dir / f"{self.slug}_candidate.json",
            "momentum": self.state_dir / f"{self.slug}_momentum.json",
            "theme": self.state_dir / f"{self.slug}_theme.json",
            "summary": self.summary_root / self.slug / "summary.json",
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

    def _module(self):
        return importlib.import_module(MODULE)

    def test_massive_market_cap_candidate_is_the_pass2_preflight_target(self):
        runner = self._module()
        candidate = _candidate_artifact(("COIN",))
        row = candidate["rows"][0]
        row["shares"] = None
        row["market_cap_usd"] = 2e11
        row["market_cap_source"] = "massive_ticker_overview"
        row["coverage_status"] = "no_shares"
        row["lineage"]["shares_source"] = "none"
        row["lineage"]["market_cap_source"] = "massive_ticker_overview"
        for key in ("shares_end", "shares_filed", "shares_accession"):
            row["lineage"].pop(key, None)
        candidate["summary"] = universe_fetch.summarize_rows(candidate["rows"])
        _write_json(self.paths["candidate"], candidate)
        _write_json(
            self.paths["momentum"],
            _constant_projection(
                "momentum_by_ticker", ("COIN",), "scored", score=50.0,
                candidate_path=self.paths["candidate"],
            ),
        )
        _write_json(
            self.paths["theme"],
            _constant_projection(
                "theme_block_by_ticker", ("COIN",), "scored_theme_base", score=50.0,
                candidate_path=self.paths["candidate"],
            ),
        )
        summary = runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"],
            authorized_total_call_budget=32,
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )
        self.assertEqual(summary["pass2_target_universe"]["target_symbols"], ["COIN"])
        self.assertEqual(summary["pass2_target_universe"]["target_count"], 1)
        self.assertFalse(summary["scope"]["network_access_performed"])

    def test_preflight_blocks_when_local_score_inputs_do_not_cover_full_candidate_set(self):
        runner = self._module()

        summary = runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"],
            authorized_total_call_budget=33,
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
            33,
        )
        self.assertEqual(
            summary["endpoint_call_forecast"]["families"]["corporate_action_live_half"]["total_calls"],
            0,
        )
        self.assertEqual(summary["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"], 33)
        self.assertEqual(summary["endpoint_call_forecast"]["total_calls_for_full_candidate_cut"], 34)
        self.assertTrue(summary["endpoint_call_forecast"]["total_calls_for_full_candidate_cut_is_hypothetical"])
        self.assertEqual(summary["pass2_target_universe"]["eligible_count"], 3)
        self.assertEqual(summary["pass2_target_universe"]["target_count"], 2)
        self.assertEqual(summary["pass2_target_universe"]["target_symbols"], ["AAPL", "MSFT"])
        self.assertTrue(summary["pass2_target_universe"]["neutral_fill_tickers_excluded_from_expensive_pass2"])
        self.assertFalse(summary["execution_gate"]["ready_to_run_full_candidate_live_packet"])
        self.assertTrue(self.paths["summary"].exists())
        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com", text.lower())
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn('"payload"', text)

    def test_stale_clock_source_projection_binding_is_rejected(self):
        # Reverse control (Required B, Top-K consumer): a same-ticker momentum projection whose
        # source_binding decision clock is stale is rejected against the CANDIDATE clock before any
        # coverage / Pass2-target computation, and no summary is written.
        runner = self._module()
        momentum = _constant_projection(
            "momentum_by_ticker", ("AAPL", "MSFT"), "scored", score=50.0,
            candidate_path=self.paths["candidate"], component="momentum",
        )
        momentum["source_binding"]["decision_clock"]["expected_decision_date"] = "20260614"
        _write_json(self.paths["momentum"], momentum)
        with self.assertRaisesRegex(runner.FullCandidatePass2PreflightError, "source binding"):
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

    def test_top_k_narrows_ready_preflight_to_top_k_by_momentum_score(self):
        # R-USSHORT-BATCH5-MOMENTUM-TOPK-NARROWING-MISSING: with all 3 candidates momentum-scored (full coverage
        # -> ready), momentum_top_k=2 must narrow the expensive Pass2 target to the 2 highest-momentum tickers.
        runner = self._module()
        momentum = _constant_projection(
            "momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0
        )
        momentum["momentum_by_ticker"] = {"AAPL": 90.0, "MSFT": 80.0, "JPM": 10.0}
        _write_json(self.paths["momentum"], momentum)
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
            momentum_top_k=2,
            authorized_total_call_budget=33,
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )

        self.assertEqual(summary["scope"]["status"], "ready_for_reviewed_live_execution")
        pass2 = summary["pass2_target_universe"]
        self.assertEqual(pass2["momentum_top_k"], 2)
        self.assertEqual(pass2["momentum_scored_candidate_count"], 3)  # all 3 scored (pre-cap)
        self.assertEqual(pass2["target_count"], 2)  # narrowed to top-2
        self.assertEqual(pass2["target_symbols"], ["AAPL", "MSFT"])  # top-2 by score = AAPL(90), MSFT(80); JPM(10) dropped
        self.assertEqual(pass2["eligible_selected_count"], 2)
        self.assertEqual(pass2["eligible_not_selected_count"], 1)
        self.assertEqual(pass2["eligible_scored_not_selected_count"], 1)
        self.assertEqual(pass2["eligible_unscored_not_selected_count"], 0)
        self.assertTrue(pass2["eligible_partition_conserved"])
        self.assertTrue(pass2["fmp_grade_calls_within_free_daily_cap"])
        self.assertEqual(summary["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"], 33)

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
            authorized_total_call_budget=34,
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )

        self.assertEqual(summary["scope"]["status"], "ready_for_reviewed_live_execution")
        self.assertFalse(summary["scope"]["network_access_performed"])
        self.assertEqual(summary["local_input_coverage"]["momentum_projection"]["missing_count"], 0)
        self.assertEqual(summary["pass2_target_universe"]["target_count"], 3)
        self.assertEqual(summary["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"], 34)
        self.assertEqual(summary["endpoint_call_forecast"]["total_calls_for_full_candidate_cut"], 34)
        self.assertTrue(summary["execution_gate"]["ready_to_run_full_candidate_live_packet"])

    def test_budget_preview_derives_exact_forecast_but_does_not_authorize_execution(self):
        # P2: the first preflight must be able to tell the operator the exact budget without turning that
        # observation into an authorization.  A separate, exact budget-bearing rerun remains mandatory.
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
            momentum_top_k=2,
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )

        self.assertEqual(summary["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"], 33)
        self.assertEqual(summary["scope"]["status"], "blocked_execution_constraints")
        self.assertFalse(summary["execution_gate"]["ready_to_run_full_candidate_live_packet"])
        self.assertFalse(summary["execution_gate"]["authorized_budget_matches_rederived_forecast"])
        self.assertNotIn("authorized_total_call_budget", summary["execution_gate"])
        self.assertIn("pass2_call_budget_not_yet_authorized", summary["execution_gate"]["block_reasons"])

    def test_neutral_fill_local_coverage_is_not_used_as_expensive_pass2_target(self):
        runner = self._module()
        momentum = _constant_projection(
            "momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0
        )
        momentum["momentum_by_ticker"] = {"AAPL": 75.0, "MSFT": 70.0}
        momentum["neutral_fill_tickers"] = ["JPM"]
        momentum["coverage"]["JPM"] = "absent_from_pool"
        momentum["scored_count"] = 2
        _write_json(self.paths["momentum"], momentum)
        theme = _constant_projection(
            "theme_block_by_ticker", ("AAPL", "MSFT", "JPM"), "scored_theme_base", score=50.0
        )
        theme["theme_block_by_ticker"] = {"AAPL": 65.0}
        theme["neutral_fill_tickers"] = ["MSFT", "JPM"]
        theme["coverage"]["MSFT"] = "neutral_missing_theme_and_industry_base"
        theme["coverage"]["JPM"] = "neutral_missing_theme_and_industry_base"
        theme["scored_count"] = 1
        _write_json(self.paths["theme"], theme)

        summary = runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"],
            authorized_total_call_budget=33,
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )

        self.assertEqual(summary["scope"]["status"], "ready_for_reviewed_live_execution")
        self.assertTrue(summary["local_input_coverage"]["all_required_local_inputs_cover_candidates"])
        self.assertEqual(summary["candidate_universe"]["eligible_count"], 3)
        self.assertEqual(
            summary["pass2_target_universe"]["selection_mode"],
            "momentum_theme_top_k_plus_catalyst_recall_plus_forced_holdings",
        )
        self.assertEqual(summary["pass2_target_universe"]["momentum_scored_candidate_count"], 2)
        self.assertEqual(summary["pass2_target_universe"]["forced_holding_count"], 0)
        self.assertEqual(summary["pass2_target_universe"]["target_count"], 2)
        self.assertEqual(summary["pass2_target_universe"]["target_symbols"], ["AAPL", "MSFT"])
        self.assertEqual(summary["pass2_target_universe"]["eligible_not_selected_count"], 1)
        self.assertEqual(summary["pass2_target_universe"]["eligible_unscored_not_selected_count"], 1)
        self.assertTrue(summary["pass2_target_universe"]["eligible_partition_conserved"])
        self.assertFalse(summary["pass2_target_universe"]["expensive_pass2_targets_full_eligible_set"])
        self.assertEqual(summary["endpoint_call_forecast"]["families"]["pass2_source_packet"]["fmp_grades_calls"], 0)
        self.assertEqual(summary["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"], 33)
        self.assertEqual(summary["endpoint_call_forecast"]["total_calls_for_full_candidate_cut"], 34)

    def test_authorization_required_before_summary_write(self):
        runner = self._module()

        with self.assertRaisesRegex(runner.FullCandidatePass2PreflightError, "authorization"):
            runner.run_preflight(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                momentum_projection_path=self.paths["momentum"],
                theme_projection_path=self.paths["theme"],
                summary_path=self.paths["summary"],
                authorized_total_call_budget=11,
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
                        authorized_total_call_budget=11,
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
            authorized_total_call_budget=11,
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
            (("pass2_target_universe", "selection_mode"), "full_candidate_set"),
            (("pass2_target_universe", "fmp_grade_call_cap"), 999),
        ):
            mutated = copy.deepcopy(summary)
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertFalse(validator.is_valid(mutated), path)

    def test_two_axis_rank_catalyst_recall_and_external_holding_are_all_preserved(self):
        runner = self._module()
        _write_json(
            self.paths["momentum"],
            {
                "momentum_by_ticker": {"AAPL": 90.0, "MSFT": 80.0, "JPM": 10.0},
                "neutral_fill_tickers": [],
                "coverage": {"AAPL": "scored", "MSFT": "scored", "JPM": "scored"},
                "target_count": 3, "scored_count": 3,
            },
        )
        _write_json(
            self.paths["theme"],
            {
                "theme_block_by_ticker": {"AAPL": 0.0, "MSFT": 0.0, "JPM": 100.0},
                "neutral_fill_tickers": [],
                "coverage": {"AAPL": "scored_theme_base", "MSFT": "scored_theme_base", "JPM": "scored_theme_base"},
                "target_count": 3, "scored_count": 3,
            },
        )
        summary = runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"], expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"], theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"], momentum_top_k=1,
            catalyst_recall_tickers=["MSFT"], forced_holding_tickers=["HOLD"],
            authorized_total_call_budget=34, confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )
        self.assertEqual(summary["pass2_target_universe"]["target_symbols"], ["HOLD", "JPM", "MSFT"])
        self.assertEqual(summary["pass2_target_universe"]["theme_scored_candidate_count"], 3)
        self.assertEqual(summary["pass2_target_universe"]["catalyst_recall_count"], 1)
        self.assertEqual(summary["pass2_target_universe"]["forced_holding_count"], 1)
        self.assertTrue(summary["execution_gate"]["authorized_budget_matches_rederived_forecast"])

    def test_projection_clock_or_payload_hash_drift_is_rejected(self):
        runner = self._module()
        projection = json.loads(self.paths["momentum"].read_text(encoding="utf-8"))
        projection["source_binding"]["decision_clock"]["source_as_of"] = "2026-07-07"
        self.paths["momentum"].write_text(json.dumps(projection), encoding="utf-8")
        with self.assertRaisesRegex(runner.FullCandidatePass2PreflightError, "decision clock"):
            runner.run_preflight(
                candidate_artifact_path=self.paths["candidate"], expected_decision_date=_DECISION_DATE,
                momentum_projection_path=self.paths["momentum"], theme_projection_path=self.paths["theme"],
                summary_path=self.paths["summary"], authorized_total_call_budget=11,
                confirm_user_authorization=True, generated_at="2026-07-06T12:00:00+00:00",
            )
        projection["source_binding"]["decision_clock"]["source_as_of"] = "2026-06-12"
        projection["source_binding"]["generated_at"] = "2026-07-01T12:00:00+00:00"
        self.paths["momentum"].write_text(json.dumps(projection), encoding="utf-8")
        with self.assertRaisesRegex(runner.FullCandidatePass2PreflightError, "before decision-session open"):
            runner.run_preflight(
                candidate_artifact_path=self.paths["candidate"], expected_decision_date=_DECISION_DATE,
                momentum_projection_path=self.paths["momentum"], theme_projection_path=self.paths["theme"],
                summary_path=self.paths["summary"], authorized_total_call_budget=11,
                confirm_user_authorization=True, generated_at="2026-07-06T12:00:00+00:00",
            )

    def test_mismatched_independent_budget_blocks_ready_gate(self):
        runner = self._module()
        _write_json(self.paths["momentum"], _constant_projection("momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored"))
        _write_json(self.paths["theme"], _constant_projection("theme_block_by_ticker", ("AAPL", "MSFT", "JPM"), "scored_theme_base"))
        summary = runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"], expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"], theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"], authorized_total_call_budget=999,
            confirm_user_authorization=True, generated_at="2026-07-06T12:00:00+00:00",
        )
        self.assertEqual(summary["scope"]["status"], "blocked_execution_constraints")
        self.assertFalse(summary["execution_gate"]["authorized_budget_matches_rederived_forecast"])
        self.assertIn("authorized_call_budget_does_not_match_rederived_target_forecast", summary["execution_gate"]["block_reasons"])

    def test_producer_role_time_and_disposition_semantics_are_closed_world(self):
        runner = self._module()
        original = json.loads(self.paths["momentum"].read_text(encoding="utf-8"))
        mutations = []
        bad_producer = copy.deepcopy(original)
        bad_producer["source_binding"]["producer_id"] = "foreign_projection_writer"
        mutations.append((bad_producer, "producer"))
        bad_role = copy.deepcopy(original)
        bad_role["source_binding"]["source_artifacts"][0]["role"] = "unrelated_file"
        mutations.append((bad_role, "artifact roles"))
        early = copy.deepcopy(original)
        early["source_binding"]["generated_at"] = "2026-06-01T12:00:00+00:00"
        mutations.append((early, "precedes source_as_of"))
        disposition = copy.deepcopy(original)
        ticker = next(iter(disposition["momentum_by_ticker"]))
        disposition["coverage"][ticker] = "absent_from_pool"
        disposition["source_binding"]["projection_sha256"] = projection_payload_sha256(disposition)
        mutations.append((disposition, "scored row has a non-scored disposition"))
        for mutated, message in mutations:
            with self.subTest(message=message):
                self.paths["momentum"].write_text(json.dumps(mutated), encoding="utf-8")
                with self.assertRaisesRegex(runner.FullCandidatePass2PreflightError, message):
                    runner.run_preflight(
                        candidate_artifact_path=self.paths["candidate"], expected_decision_date=_DECISION_DATE,
                        momentum_projection_path=self.paths["momentum"], theme_projection_path=self.paths["theme"],
                        summary_path=self.paths["summary"], authorized_total_call_budget=11,
                        confirm_user_authorization=True, generated_at="2026-07-06T12:00:00+00:00",
                    )
                self.paths["momentum"].write_text(json.dumps(original), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
