"""Offline fifth-knife coverage for the shared A-short margin source contract."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pandas as pd

from engine.data.analysis_input_contract import AnalysisInputContractError, validate_analysis_input_contract
from runners.a_short_m67_render import render_weekly_markdown
from runners.a_short_phase5_engine import _margin_source_is_unavailable
from runners.a_short_weekly_pipeline import build_weekly_report, validate_weekly_report
from tests.test_a_short_weekly_pipeline import AS_OF, GEN, _feed, _normalized, _weekly


ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"
ANALYSIS_INPUT_SCHEMA = ROOT / "schemas" / "analysis_input.schema.json"
ANALYSIS_INPUT_EXAMPLE = ROOT / "schemas" / "examples" / "analysis_input.example.json"
WEEKLY_SCHEMA = ROOT / "schemas" / "a_short_weekly_report.schema.json"
DATA_HEALTH_SCHEMA = ROOT / "schemas" / "data_health.schema.json"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_margin_coverage_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class MarginCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.egs = _load_egs_module()

    def test_latest_not_published_uses_prior_complete_reference_date(self):
        em = self.egs
        dates = [f"202607{day:02d}" for day in range(14, 1, -1)]
        frame = pd.DataFrame([
            {"ts_code": code, "trade_date": date, "rzye": 100.0, "rqye": 100.0}
            for date in dates[1:] for code in ("600000.SH", "000001.SZ")
        ])
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 2):
            observed = em._margin_observation(frame, dates)
        self.assertEqual(observed.reference_date, dates[0])
        self.assertEqual(observed.effective_ref_date, dates[1])
        self.assertEqual(observed.status, "complete")
        self.assertTrue(observed.coverage_complete)

    def test_empty_incomplete_and_malformed_sources_never_claim_complete(self):
        em = self.egs
        dates = ["20260714", "20260713"]
        empty = em._margin_observation(pd.DataFrame(), dates)
        incomplete = em._margin_observation(pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": "20260714", "rzye": 1.0, "rqye": 1.0},
        ]), dates)
        malformed = em._margin_observation(pd.DataFrame([
            {"ts_code": "BAD", "trade_date": "20260714", "rzye": 1.0, "rqye": 1.0},
        ]), dates)
        malformed_value = em._margin_observation(pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": "20260714", "rzye": "bad", "rqye": 1.0},
        ]), dates)
        self.assertEqual(empty.status, "unavailable")
        self.assertEqual(incomplete.status, "incomplete")
        self.assertEqual(malformed.status, "invalid")
        self.assertEqual(malformed_value.status, "invalid")
        self.assertFalse(any(item.coverage_complete for item in (empty, incomplete, malformed, malformed_value)))

    def test_non_reference_numeric_gap_does_not_block_clean_reference_day(self):
        em = self.egs
        dates = ["20260714", "20260713", "20260710"]
        frame = pd.DataFrame([
            {"ts_code": code, "trade_date": date, "rzye": 100.0, "rqye": 100.0}
            for date in dates[:2] for code in ("600000.SH", "000001.SZ")
        ] + [
            {"ts_code": "600000.SH", "trade_date": dates[2], "rzye": 100.0, "rqye": float("nan")},
        ])
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 2):
            observed = em._margin_observation(frame, dates)
        self.assertEqual(observed.effective_ref_date, dates[0])
        self.assertEqual(observed.row_count, 5)
        self.assertEqual(observed.universe_size, 2)
        self.assertEqual(observed.status, "complete")
        self.assertTrue(observed.coverage_complete)

    def test_newest_fully_valid_allowed_date_wins_over_newer_partial_date(self):
        em = self.egs
        dates = ["20260714", "20260713", "20260710"]
        frame = pd.DataFrame([
            {"ts_code": code, "trade_date": dates[0], "rzye": 100.0,
             "rqye": float("nan") if code == "000001.SZ" else 100.0}
            for code in ("600000.SH", "000001.SZ")
        ] + [
            {"ts_code": code, "trade_date": date, "rzye": 100.0, "rqye": 100.0}
            for date in dates[1:] for code in ("600000.SH", "000001.SZ")
        ])
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 2):
            observed = em._margin_observation(frame, dates)
        self.assertEqual(observed.effective_ref_date, dates[1])
        self.assertEqual(observed.universe_size, 2)
        self.assertEqual(observed.status, "complete")
        self.assertTrue(observed.coverage_complete)

    def test_reference_selection_does_not_cross_actual_calendar_lag_when_d0_missing(self):
        em = self.egs
        dates = ["20260731", "20260730", "20260729"]
        frame = pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": dates[1], "rzye": 100.0, "rqye": 100.0},
            {"ts_code": "000001.SZ", "trade_date": dates[1], "rzye": 100.0, "rqye": float("nan")},
        ] + [
            {"ts_code": code, "trade_date": dates[2], "rzye": 100.0, "rqye": 100.0}
            for code in ("600000.SH", "000001.SZ")
        ])
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 2):
            observed = em._margin_observation(frame, dates)
        self.assertEqual(observed.effective_ref_date, dates[1])
        self.assertEqual(observed.universe_size, 1)
        self.assertEqual(observed.status, "incomplete")
        self.assertFalse(observed.coverage_complete)

    def test_no_fully_valid_allowed_date_keeps_existing_partial_selection(self):
        em = self.egs
        dates = ["20260714", "20260713", "20260710"]
        frame = pd.DataFrame([
            {"ts_code": code, "trade_date": date, "rzye": 100.0,
             "rqye": float("nan") if code == "000001.SZ" else 100.0}
            for date in dates[:2] for code in ("600000.SH", "000001.SZ")
        ] + [
            {"ts_code": code, "trade_date": dates[2], "rzye": 100.0, "rqye": 100.0}
            for code in ("600000.SH", "000001.SZ")
        ])
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 2):
            observed = em._margin_observation(frame, dates)
        self.assertEqual(observed.effective_ref_date, dates[0])
        self.assertEqual(observed.universe_size, 1)
        self.assertEqual(observed.status, "incomplete")
        self.assertFalse(observed.coverage_complete)

    def test_clean_day_beyond_allowed_lag_stays_incomplete(self):
        em = self.egs
        dates = ["20260714", "20260713", "20260710"]
        frame = pd.DataFrame([
            {"ts_code": code, "trade_date": dates[2], "rzye": 100.0, "rqye": 100.0}
            for code in ("600000.SH", "000001.SZ")
        ])
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 2):
            observed = em._margin_observation(frame, dates)
        self.assertEqual(observed.effective_ref_date, dates[2])
        self.assertEqual(observed.universe_size, 2)
        self.assertEqual(observed.status, "incomplete")
        self.assertFalse(observed.coverage_complete)

    def test_cache_observation_and_live_observation_have_the_same_contract(self):
        em = self.egs
        dates = ["20260714"]
        cached = em.MarginObservation(pd.DataFrame(), "20260714", None, 0, 0, False, "unavailable")
        with patch.object(em, "load_cache", return_value=cached), \
             patch.object(em, "safe_api", return_value=None) as safe_api, \
             patch.object(em, "save_cache"):
            self.assertEqual(em.get_margin(dates).public_dict(), cached.public_dict())
        safe_api.assert_called_once()
        poisoned = em.MarginObservation(pd.DataFrame(), "20260714", "20260714", 0, 1, True, "complete")
        with patch.object(em, "load_cache", return_value=poisoned), \
             patch.object(em, "safe_api", return_value=None) as safe_api, \
             patch.object(em, "save_cache"):
            observed = em.get_margin(dates)
        self.assertEqual(observed.status, "unavailable")
        safe_api.assert_called_once()
        with patch.object(em, "load_cache", return_value=pd.DataFrame()):
            with self.assertRaisesRegex(RuntimeError, "observation contract"):
                em.get_margin(dates)

    def test_margin_cache_key_is_versioned_and_window_bound(self):
        em = self.egs
        dates = ["20260714", "20260713", "20260710"]
        key = em._margin_cache_key(dates)
        self.assertIn("rule6_v5", key)
        self.assertNotIn("rule6_v4", key)
        self.assertNotEqual(key, em._margin_cache_key([dates[0], "20260709", dates[2]]))
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 2):
            self.assertNotEqual(key, em._margin_cache_key(dates))

    def test_margin_cache_key_rotates_with_observation_semantics_fingerprint(self):
        em = self.egs
        dates = ["20260714", "20260713"]
        with patch.object(em, "_margin_semantics_fingerprint", return_value="old-contract"):
            old_key = em._margin_cache_key(dates)
        with patch.object(em, "_margin_semantics_fingerprint", return_value="new-contract"):
            new_key = em._margin_cache_key(dates)
        self.assertNotEqual(old_key, new_key)
        self.assertIn("old-contract", old_key)
        self.assertIn("new-contract", new_key)

    def test_legacy_v4_cache_is_not_loaded(self):
        em = self.egs
        dates = ["20260714"]
        loaded_keys = []
        frame = pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": "20260714", "rzye": 1.0, "rqye": 1.0},
        ])

        def load(key):
            loaded_keys.append(key)
            return None

        with patch.object(em, "load_cache", side_effect=load), \
             patch.object(em, "safe_api", return_value=frame), \
             patch.object(em, "save_cache"):
            em.get_margin(dates)
        self.assertEqual(len(loaded_keys), 1)
        self.assertIn("rule6_v5", loaded_keys[0])
        self.assertNotIn("rule6_v4", loaded_keys[0])

    def test_current_complete_cache_hit_does_not_refetch(self):
        em = self.egs
        dates = ["20260714"]
        frame = pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": "20260714", "rzye": 1.0, "rqye": 1.0},
        ])
        cached = em.MarginObservation(frame, "20260714", "20260714", 1, 1, True, "complete")
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 1), \
             patch.object(em, "load_cache", return_value=cached), \
             patch.object(em, "safe_api") as safe_api:
            observed = em.get_margin(dates)
        self.assertEqual(observed.public_dict(), cached.public_dict())
        safe_api.assert_not_called()

    def test_rule6_binds_to_effective_reference_and_five_session_short_baseline(self):
        em = self.egs
        code, other = "600000.SH", "000001.SZ"
        dates = [f"202607{day:02d}" for day in range(14, 1, -1)]
        margin_dates = dates[1:]
        margin = pd.DataFrame([
            {"ts_code": ticker, "trade_date": date,
             "rzye": 121.0 if (ticker, date) == (code, margin_dates[0]) else 100.0,
             "rqye": 100.0}
            for ticker in (code, other) for date in margin_dates
        ])
        daily = pd.DataFrame([
            {"ts_code": code, "trade_date": date, "vol": 100.0, "pct_chg": 1.0,
             "high": 11.0, "low": 9.0, "close": 100.0,
             "qfq_high": 11.0, "qfq_low": 9.0, "qfq_close": 100.0, "qfq_pct_chg": 1.0}
            for date in dates
        ])
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 2), \
             patch.object(em, "get_rule6_balancesheets", return_value={code: []}), \
             patch.object(em, "get_rule6_block_trades", return_value={date: [] for date in dates[:10]}):
            observation = em._margin_observation(margin, dates)
            result = em._collect_rule6_evaluations(
                pd.DataFrame({"ts_code": [code]}), daily, observation, dates,
                {"rule6_holder_events": []}, pd.DataFrame(),
            )[code]
        metrics = result["rule6_margin_extreme_accumulation"]["metrics"]
        self.assertEqual(metrics["effective_ref_date"], margin_dates[0])
        self.assertEqual(metrics["status"], "complete")
        self.assertEqual(result["rule6_margin_extreme_accumulation"]["status"], "fail")

    def test_incomplete_source_opens_only_proven_margin_candidate_rules(self):
        em = self.egs
        code, other = "600000.SH", "000001.SZ"
        dates = [f"202607{day:02d}" for day in range(14, 1, -1)]
        margin_dates = dates[1:]
        margin_rows = []
        for ticker in (code, other):
            for index, date in enumerate(margin_dates):
                missing_other_window = ticker == other and index in (0, 1, 5, 10)
                margin_rows.append({
                    "ts_code": ticker,
                    "trade_date": date,
                    "rzye": (121.0 if (ticker, index) == (code, 0) else
                              (float("nan") if missing_other_window else 100.0)),
                    "rqye": float("nan") if missing_other_window else 100.0,
                })
        margin = pd.DataFrame(margin_rows)
        daily = pd.DataFrame([
            {"ts_code": ticker, "trade_date": date, "vol": 100.0, "pct_chg": 1.0,
             "high": 11.0, "low": 9.0, "close": 100.0,
             "qfq_high": 11.0, "qfq_low": 9.0, "qfq_close": 100.0, "qfq_pct_chg": 1.0}
            for ticker in (code, other) for date in dates
        ])
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 2), \
             patch.object(em, "get_rule6_balancesheets", return_value={code: [], other: []}), \
             patch.object(em, "get_rule6_block_trades", return_value={date: [] for date in dates[:10]}):
            observation = em._margin_observation(margin, dates)
            results = em._collect_rule6_evaluations(
                pd.DataFrame({"ts_code": [code, other]}), daily, observation, dates,
                {"rule6_holder_events": []}, pd.DataFrame(),
            )
        self.assertEqual(observation.status, "incomplete")
        self.assertEqual(results[code]["rule6_margin_extreme_accumulation"]["status"], "fail")
        self.assertEqual(results[code]["rule6_short_selling_surge"]["status"], "pass")
        self.assertEqual(results[other]["rule6_margin_extreme_accumulation"]["status"], "unknown")
        self.assertEqual(results[other]["rule6_short_selling_surge"]["status"], "unknown")

    def test_l2_margin_veto_normalizes_integer_trade_dates(self):
        em = self.egs
        code = "600000.SH"
        dates = [f"202607{day:02d}" for day in range(14, 1, -1)]
        margin = pd.DataFrame([
            {"ts_code": code, "trade_date": int(date),
             "rzye": 120.0 if date == dates[0] else 100.0, "rqye": 1.0}
            for date in dates
        ])
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 1):
            observation = em._margin_observation(margin, dates)
        reasons = {}
        output = em.score_l2(
            pd.DataFrame([{
                "ts_code": code, "l2_name": "test", "q0_dt_yoy": 1.0,
                "q1_dt_yoy": 1.0, "pe": 1.0, "pb": 1.0, "roe": 1.0,
                "pct_20d_n": 0.0, "reduce_deduct": 0.0,
                "avg_amount_5d": 1.0, "avg_amount_20d": 1.0,
            }]),
            observation.frame, dates, {"test": 1.0},
            exclusion_reasons=reasons, margin_observation=observation,
        )
        self.assertTrue(output.empty)
        self.assertEqual(reasons[code], "l2_margin_growth_veto")

    def test_margin_schema_rejects_inconsistent_complete_status_on_all_surfaces(self):
        invalid = {
            "reference_date": "20260714", "effective_ref_date": None,
            "row_count": 0, "universe_size": 0,
            "coverage_complete": False, "status": "complete",
        }
        analysis = json.loads(ANALYSIS_INPUT_EXAMPLE.read_text(encoding="utf-8"))
        analysis["schema_version"] = "1.3.0"
        analysis["market_context"]["margin_coverage"] = invalid
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(analysis, json.loads(ANALYSIS_INPUT_SCHEMA.read_text(encoding="utf-8")))

        weekly = _weekly()
        weekly["margin_coverage"] = copy.deepcopy(invalid)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(weekly, json.loads(WEEKLY_SCHEMA.read_text(encoding="utf-8")))

        health_margin_schema = json.loads(DATA_HEALTH_SCHEMA.read_text(encoding="utf-8"))["properties"]["metrics"]["properties"]["margin_coverage"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(invalid, health_margin_schema)

    def test_weekly_source_binding_rejects_future_complete_reference_date(self):
        future_complete = {
            "reference_date": "20990101", "effective_ref_date": "20260714",
            "row_count": 1, "universe_size": 1,
            "coverage_complete": True, "status": "complete",
        }
        with self.assertRaisesRegex(ValueError, "reference_date"):
            build_weekly_report([], "20260714", GEN, margin_coverage=future_complete)

    def test_margin_clock_binds_to_price_data_through_not_decision_date(self):
        analysis = json.loads(ANALYSIS_INPUT_EXAMPLE.read_text(encoding="utf-8"))
        analysis["schema_version"] = "1.3.0"
        analysis["trade_date"] = "20260727"
        analysis["decision_as_of"] = "20260727"
        analysis["price_data_through"] = "20260724"
        analysis["source"]["clocks"] = {
            "decision_as_of": "20260727", "run_date": "20260727",
            "price_data_through": "20260724",
        }
        analysis["market_context"]["margin_coverage"] = {
            "reference_date": "20260724", "effective_ref_date": "20260724",
            "row_count": 1000, "universe_size": 1000,
            "coverage_complete": True, "status": "complete",
        }
        validate_analysis_input_contract(analysis)

        margin = analysis["market_context"]["margin_coverage"]
        lineage = {"account_status": "absent", "sizing_mode": "observation_only_no_account",
                   "account_snapshot": None,
                   "price_freshness": {"mode": "intraday_prior_settled", "run_date": "20260727",
                                        "accepted_prior_settled_date": "20260724",
                                        "price_data_through": "20260724"}}
        candidate = _normalized()
        candidate["rule6_checks"] = [
            {"id": "rule6_margin_extreme_accumulation", "status": "pass", "metrics": {"status": "complete"}},
            {"id": "rule6_short_selling_surge", "status": "pass", "metrics": {"status": "complete"}},
        ]
        weekly = build_weekly_report([candidate], "20260727", GEN, run_lineage=lineage,
                                     margin_coverage=margin)
        self.assertEqual(weekly["price_data_through"], "20260724")
        self.assertEqual(weekly["margin_coverage"]["reference_date"], "20260724")
        self.assertFalse(
            weekly["reports"][0]["machine"]["layer"]["decision_reasons"]["margin_source_unavailable"]
        )
        feed = copy.deepcopy(_feed())
        feed.update({
            "as_of": "20260724",
            "n_days": 1,
            "series": [{"trade_date": "20260724", "iv_value": 0.2,
                         "iv_percentile_252d": 50.0, "hv_value": 0.18}],
        })
        validate_weekly_report(weekly, feed)

        analysis["market_context"]["margin_coverage"]["reference_date"] = "20260727"
        with self.assertRaisesRegex(AnalysisInputContractError, "reference_date must equal price_data_through"):
            validate_analysis_input_contract(analysis)
        with self.assertRaisesRegex(ValueError, "reference_date"):
            build_weekly_report([candidate], "20260727", GEN, run_lineage=lineage,
                                margin_coverage=analysis["market_context"]["margin_coverage"])

    def test_weekly_renderer_emits_one_system_margin_banner(self):
        markdown = render_weekly_markdown({
            "as_of": "20260714", "reports": [],
            "margin_coverage": {"reference_date": "20260714", "effective_ref_date": None,
                                "row_count": 0, "universe_size": 0,
                                "coverage_complete": False, "status": "unavailable"},
        })
        self.assertEqual(markdown.count("两融数据源本周不可用或覆盖不足"), 1)

    def test_margin_observation_rejects_source_date_outside_trade_calendar(self):
        em = self.egs
        dates = ["20260714", "20260713"]
        frame = pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": "20260712", "rzye": 1.0, "rqye": 1.0},
        ])
        observed = em._margin_observation(frame, dates)
        self.assertEqual(observed.status, "invalid")
        self.assertFalse(observed.coverage_complete)

    def test_rule6_price_volume_window_is_not_shifted_by_one_session_margin_lag(self):
        em = self.egs
        code, other = "600000.SH", "000001.SZ"
        dates = [f"202607{day:02d}" for day in range(14, 1, -1)]
        margin_dates = dates[1:]
        margin = pd.DataFrame([
            {"ts_code": ticker, "trade_date": date, "rzye": 100.0, "rqye": 100.0}
            for ticker in (code, other) for date in margin_dates
        ])
        # D0 is the sole high-volume session.  A lagged margin date must not
        # slide Rule6 volume-stall to D1..D6 and turn the failure into a pass.
        daily = pd.DataFrame([
            {"ts_code": code, "trade_date": date,
             "vol": 1000.0 if date == dates[0] else 100.0, "pct_chg": 0.0,
             "high": 101.0, "low": 99.0, "close": 99.2,
             "qfq_high": 101.0, "qfq_low": 99.0, "qfq_close": 99.2, "qfq_pct_chg": 0.0}
            for date in dates
        ])
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 2), \
             patch.object(em, "get_rule6_balancesheets", return_value={code: []}), \
             patch.object(em, "get_rule6_block_trades", return_value={date: [] for date in dates[:10]}):
            observation = em._margin_observation(margin, dates)
            result = em._collect_rule6_evaluations(
                pd.DataFrame({"ts_code": [code]}), daily, observation, dates,
                {"rule6_holder_events": []}, pd.DataFrame(),
            )[code]
        self.assertEqual(result["rule6_volume_stall"]["status"], "fail")

    def test_l2_margin_veto_uses_fixed_ten_session_calendar_baseline(self):
        em = self.egs
        code = "600000.SH"
        dates = [f"202607{day:02d}" for day in range(14, 1, -1)]
        margin = pd.DataFrame([
            {"ts_code": code, "trade_date": date,
             "rzye": 130.0 if date == dates[0] else (118.0 if date == dates[9] else 100.0),
             "rqye": 1.0}
            for date in dates
        ])
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 1):
            observation = em._margin_observation(margin, dates)
        reasons = {}
        output = em.score_l2(
            pd.DataFrame([{"ts_code": code, "l2_name": "test", "q0_dt_yoy": 1.0,
                          "q1_dt_yoy": 1.0, "pe": 1.0, "pb": 1.0, "roe": 1.0,
                          "pct_20d_n": 0.0, "reduce_deduct": 0.0,
                          "avg_amount_5d": 1.0, "avg_amount_20d": 1.0}]),
            observation.frame, dates, {"test": 1.0},
            exclusion_reasons=reasons, margin_observation=observation,
        )
        self.assertFalse(output.empty)
        self.assertNotIn(code, reasons)

    def test_complete_zero_universe_is_rejected_on_runtime_and_schema_surfaces(self):
        em = self.egs
        invalid = {"reference_date": AS_OF, "effective_ref_date": AS_OF,
                   "row_count": 0, "universe_size": 0,
                   "coverage_complete": True, "status": "complete"}
        with self.assertRaisesRegex(ValueError, "floor"):
            build_weekly_report([], AS_OF, GEN, margin_coverage=invalid)
        health = {"metrics": {"watch_pool_reconciliation": em.build_watch_pool_reconciliation(0, 0, 0),
            "sw_industry_membership": {"status": "not_observed", "source": None,
            "active_count": None, "min_active": None, "fast_path_used": False,
            "fallback_used": False, "cache_hit": False}, "margin_coverage": invalid}}
        with self.assertRaisesRegex(ValueError, "margin coverage"):
            self.egs.validate_data_health_consistency(health)

    def test_source_outage_reaches_one_system_banner_and_blocks_new_entry(self):
        normalized = _normalized()
        for check in normalized["rule6_checks"]:
            if check["id"] in {
                "rule6_margin_extreme_accumulation", "rule6_short_selling_surge",
            }:
                check["metrics"] = {
                    "status": "complete", "effective_ref_date": AS_OF,
                    "coverage_complete": True,
                }
        margin_coverage = {
            "reference_date": AS_OF, "effective_ref_date": None,
            "row_count": 0, "universe_size": 0,
            "coverage_complete": False, "status": "unavailable",
        }
        weekly = build_weekly_report(
            [normalized], AS_OF, GEN, margin_coverage=margin_coverage,
        )
        report = weekly["reports"][0]
        reasons = report["machine"]["layer"]["decision_reasons"]
        self.assertTrue(reasons["margin_source_unavailable"])
        self.assertEqual(reasons["manual_review"], [])
        self.assertIn("系统级：两融数据源本周不可用/覆盖不足",
                      report["machine"]["entry_exit_size_star"]["reject_reason"])
        markdown = render_weekly_markdown(weekly)
        self.assertEqual(markdown.count("两融数据源本周不可用或覆盖不足"), 1)

    def test_partial_margin_gate_opens_only_positive_candidate_with_two_known_checks(self):
        coverage = {
            "reference_date": AS_OF,
            "effective_ref_date": "20260608",
            "row_count": 1900,
            "universe_size": 100,
            "coverage_complete": False,
            "status": "incomplete",
        }
        checks = [
            {
                "id": "rule6_margin_extreme_accumulation",
                "status": "fail",
                "metrics": {
                    "status": "incomplete", "coverage_complete": False,
                    "reference_date": AS_OF, "effective_ref_date": "20260608",
                    "margin_candidate_eligibility": True,
                },
            },
            {
                "id": "rule6_short_selling_surge",
                "status": "pass",
                "metrics": {
                    "status": "incomplete", "coverage_complete": False,
                    "reference_date": AS_OF, "effective_ref_date": "20260608",
                    "margin_candidate_eligibility": True,
                },
            },
        ]
        inp = {"margin_coverage": coverage, "price_data_through": AS_OF,
               "rule6_checks": checks}
        self.assertFalse(_margin_source_is_unavailable(inp, AS_OF))

        for mutation in (
            lambda item: item.update(status="unknown"),
            lambda item: item["metrics"].update(margin_candidate_eligibility=None),
            lambda item: item["metrics"].update(effective_ref_date="20260710"),
        ):
            mutated = copy.deepcopy(inp)
            mutation(mutated["rule6_checks"][0])
            self.assertTrue(_margin_source_is_unavailable(mutated, AS_OF))

        absent_candidate = copy.deepcopy(inp)
        absent_candidate["rule6_checks"][0]["metrics"]["margin_candidate_eligibility"] = None
        absent_candidate["rule6_checks"][1]["metrics"]["margin_candidate_eligibility"] = None
        self.assertTrue(_margin_source_is_unavailable(absent_candidate, AS_OF))

    def test_partial_margin_gate_reaches_weekly_report_without_system_banner(self):
        normalized = _normalized()
        for check in normalized["rule6_checks"]:
            if check["id"] in {
                "rule6_margin_extreme_accumulation", "rule6_short_selling_surge",
            }:
                check["status"] = "pass"
                check["metrics"] = {
                    "status": "incomplete", "coverage_complete": False,
                    "reference_date": AS_OF, "effective_ref_date": "20260608",
                    "margin_candidate_eligibility": True,
                }
        weekly = build_weekly_report(
            [normalized], AS_OF, GEN,
            margin_coverage={
                "reference_date": AS_OF, "effective_ref_date": "20260608",
                "row_count": 1900, "universe_size": 100,
                "coverage_complete": False, "status": "incomplete",
            },
        )
        report = weekly["reports"][0]
        self.assertFalse(report["machine"]["layer"]["decision_reasons"]["margin_source_unavailable"])

    def _weekly_with_margin_check_metrics(self, metrics):
        normalized = _normalized()
        for check in normalized["rule6_checks"]:
            if check["id"] in {
                "rule6_margin_extreme_accumulation", "rule6_short_selling_surge",
            }:
                check["metrics"] = dict(metrics)
        return build_weekly_report(
            [normalized], AS_OF, GEN,
            margin_coverage={"reference_date": AS_OF, "effective_ref_date": AS_OF,
                             "row_count": 1200, "universe_size": 1100,
                             "coverage_complete": True, "status": "complete"},
        )

    def test_banner_follows_the_blocking_decision_not_only_batch_coverage(self):
        # Coverage reads complete while the two margin checks do not, so Phase5
        # still blocks every ticker; the Markdown may not stay silent about it.
        weekly = self._weekly_with_margin_check_metrics({"status": "partial"})
        report = weekly["reports"][0]
        self.assertTrue(report["machine"]["layer"]["decision_reasons"]["margin_source_unavailable"])
        markdown = render_weekly_markdown(weekly)
        self.assertEqual(markdown.count("两融数据源本周不可用或覆盖不足"), 1)
        self.assertIn("complete/两融规则未标记完成", markdown)

    def test_banner_is_absent_when_no_report_is_blocked(self):
        weekly = self._weekly_with_margin_check_metrics({"status": "complete"})
        report = weekly["reports"][0]
        self.assertFalse(report["machine"]["layer"]["decision_reasons"]["margin_source_unavailable"])
        markdown = render_weekly_markdown(weekly)
        self.assertEqual(markdown.count("两融数据源本周不可用或覆盖不足"), 0)


if __name__ == "__main__":
    unittest.main()
