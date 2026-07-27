"""M5.5/M5.5B deterministic concentration and final M6.7 allocation tests."""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_portfolio_risk import (  # noqa: E402
    HIGH_RISK_HOLDING_CAP_MULTIPLIER,
    build_context, evaluate_candidate, commit_candidate, final_summary, fact_from_normalized,
)
from engine.a_short_runtime_config import load_runtime_configuration  # noqa: E402
from runners.a_short_m67_render import render_weekly_markdown  # noqa: E402
from runners.a_short_weekly_pipeline import (  # noqa: E402
    _fetch_portfolio_risk_fact_overrides, _holding_adds_portfolio_risk,
    build_weekly_report, validate_weekly_report,
)
from tests.test_a_short_weekly_pipeline import (  # noqa: E402
    AS_OF, GEN, _feed, _normalized, _sized_lineage,
)


def _facts(code, l2, *, north=1.0, margin=1.0, index=False, circ_mv=10_000_000_000.0):
    return {
        "ts_code": code, "as_of": AS_OF, "source": "fixture", "sw_l2_key": l2,
        "circ_mv_rmb": circ_mv, "northbound_holding_ratio_pct": north,
        "margin_balance_to_float_mv_pct": margin, "is_large_index_component": index,
    }


def _normal(code, l2, *, held_shares=None):
    row = _normalized(code)
    if held_shares is not None:
        row["stateful_risk"] = {
            "position_state": "held",
            "position": {"ts_code": code, "shares": held_shares, "avg_cost": 2.7,
                         "entry_date": "20260601", "stop_loss": 2.5},
        }
    return row


class PortfolioRiskPureTests(unittest.TestCase):
    def test_first_position_is_not_applicable(self):
        row = _normal("600000.SH", "bank")
        ctx = build_context([row], AS_OF, fact_overrides={"600000.SH": _facts("600000.SH", "bank")})
        result = evaluate_candidate(ctx, "600000.SH", 100_000)
        self.assertEqual(result["status"], "not_applicable")
        self.assertEqual(result["action"], "none")

    def test_same_industry_over_40_replaces_candidate(self):
        held = _normal("000001.SZ", "bank", held_shares=20_000)
        candidate = _normal("600000.SH", "bank")
        ctx = build_context([held, candidate], AS_OF, fact_overrides={
            "000001.SZ": _facts("000001.SZ", "bank"),
            "600000.SH": _facts("600000.SH", "bank"),
        })
        result = evaluate_candidate(ctx, "600000.SH", 100_000)
        self.assertEqual(result["action"], "replace")
        self.assertTrue(result["same_sw_l2"]["over_threshold"])

    def test_new_diversifying_l2_is_not_blocked_while_a_basket_is_being_built(self):
        held = _normal("000001.SZ", "bank", held_shares=20_000)
        candidate = _normal("600000.SH", "tech")
        ctx = build_context([held, candidate], AS_OF, fact_overrides={
            "000001.SZ": _facts("000001.SZ", "bank"),
            "600000.SH": _facts("600000.SH", "tech"),
        })
        result = evaluate_candidate(ctx, "600000.SH", 100_000)
        self.assertEqual(result["action"], "allow")
        self.assertTrue(result["same_sw_l2"]["over_threshold"])

    def test_each_factor_over_threshold_blocks_same_direction(self):
        cases = [
            ("north", {"north": 15.0}),
            ("margin", {"margin": 12.0}),
            ("index", {"index": True}),
            ("small", {"circ_mv": 7_000_000_000.0}),
        ]
        for label, changes in cases:
            with self.subTest(label=label):
                held = _normal("000001.SZ", "bank", held_shares=100_000)
                candidate = _normal("600000.SH", "tech")
                held_changes = dict(changes)
                candidate_changes = dict(changes)
                # For ratio factors, the new position must make the already
                # high exposure worse.  Equal values would be a diversifier
                # neutral case, not an M5.5B "do not add" case.
                if label == "north":
                    held_changes["north"], candidate_changes["north"] = 15.0, 25.0
                elif label == "margin":
                    held_changes["margin"], candidate_changes["margin"] = 12.0, 20.0
                facts = {
                    "000001.SZ": _facts("000001.SZ", "bank", **held_changes),
                    "600000.SH": _facts("600000.SH", "tech", **candidate_changes),
                }
                ctx = build_context([held, candidate], AS_OF, fact_overrides=facts)
                result = evaluate_candidate(ctx, "600000.SH", 100_000)
                self.assertEqual(result["action"], "observe_required")
                self.assertEqual(result["status"], "factor_resonance")

    def test_diversifier_does_not_get_blocked_by_existing_high_factor(self):
        held = _normal("000001.SZ", "bank", held_shares=100_000)
        candidate = _normal("600000.SH", "tech")
        ctx = build_context([held, candidate], AS_OF, fact_overrides={
            "000001.SZ": _facts("000001.SZ", "bank", north=20.0),
            "600000.SH": _facts("600000.SH", "tech", north=1.0),
        })
        result = evaluate_candidate(ctx, "600000.SH", 100_000)
        self.assertEqual(result["status"], "factor_resonance")
        self.assertEqual(result["action"], "allow")

    def test_missing_or_wrong_date_fact_is_manual_review_not_clear(self):
        held = _normal("000001.SZ", "bank", held_shares=20_000)
        candidate = _normal("600000.SH", "tech")
        missing = _facts("600000.SH", "tech")
        missing["northbound_holding_ratio_pct"] = None
        ctx = build_context([held, candidate], AS_OF, fact_overrides={
            "000001.SZ": _facts("000001.SZ", "bank"), "600000.SH": missing,
        })
        result = evaluate_candidate(ctx, "600000.SH", 100_000)
        self.assertEqual(result["status"], "manual_review_required")
        self.assertEqual(result["action"], "observe_required")
        self.assertTrue(result["missing_fields"])

        foreign = _facts("000001.SZ", "foreign")
        foreign["as_of"] = "20260610"
        fact = fact_from_normalized(candidate, AS_OF, foreign)
        self.assertEqual(fact["source"], "portfolio_risk_invalid_override")
        self.assertIsNone(fact["northbound_holding_ratio_pct"])

        wrong_stock = _facts("000001.SZ", "foreign")
        fact = fact_from_normalized(candidate, AS_OF, wrong_stock)
        self.assertEqual(fact["source"], "portfolio_risk_invalid_override")

    def test_zero_value_holding_is_manual_review_not_factor_division(self):
        held = _normal("000001.SZ", "bank", held_shares=0)
        candidate = _normal("600000.SH", "tech")
        facts = {
            "000001.SZ": _facts("000001.SZ", "bank"),
            "600000.SH": _facts("600000.SH", "tech"),
        }
        context = build_context([held, candidate], AS_OF, fact_overrides=facts)
        result = evaluate_candidate(context, "600000.SH", 100_000)
        self.assertEqual(result["status"], "manual_review_required")
        self.assertEqual(result["action"], "observe_required")
        self.assertIn("000001.SZ:position_value", result["missing_fields"])

        second_zero_holding = _normal("600000.SH", "tech", held_shares=0)
        empty_context = build_context([held, second_zero_holding], AS_OF, fact_overrides=facts)
        summary = final_summary(empty_context)
        self.assertEqual(summary["status"], "manual_review_required")
        self.assertTrue(summary["daily_manual_review_required"])
        self.assertIn("000001.SZ:position_value", summary["missing_fields"])
        self.assertIn("600000.SH:position_value", summary["missing_fields"])

    def test_two_factors_high_require_daily_review_and_single_cap_cut(self):
        first = _normal("000001.SZ", "bank", held_shares=20_000)
        second = _normal("600000.SH", "tech", held_shares=20_000)
        ctx = build_context([first, second], AS_OF, fact_overrides={
            "000001.SZ": _facts("000001.SZ", "bank", north=20.0, margin=12.0),
            "600000.SH": _facts("600000.SH", "tech", north=20.0, margin=12.0),
        })
        summary = final_summary(ctx)
        self.assertEqual(summary["status"], "factor_resonance_high_risk")
        self.assertTrue(summary["daily_manual_review_required"])
        self.assertEqual(summary["holding_single_position_cap_multiplier"], HIGH_RISK_HOLDING_CAP_MULTIPLIER)

    def test_provider_empty_endpoint_is_unverified_not_silently_zero(self):
        class Frame:
            def __init__(self, rows):
                self.rows = rows

            def to_dict(self, orient):
                self_orient = orient
                if self_orient != "records":
                    raise ValueError("unexpected frame orientation")
                return self.rows

        class Provider:
            def daily_basic(self, **_kwargs):
                return Frame([])  # endpoint changed/empty: cannot prove zero market cap

            def margin_detail(self, **_kwargs):
                return Frame([{"ts_code": "600000.SH", "rzye": 100_000_000.0}])

            def hk_hold(self, **_kwargs):
                return Frame([{"ts_code": "600000.SH", "ratio": 2.0}])

            def index_member(self, index_code, **_kwargs):
                return Frame([{"con_code": "600000.SH" if index_code == "000300.SH" else "000001.SZ",
                               "in_date": "20260101", "out_date": None}])

        fact = _fetch_portfolio_risk_fact_overrides(Provider(), AS_OF, ["600000.SH"])["600000.SH"]
        self.assertIsNone(fact["circ_mv_rmb"])
        self.assertEqual(fact["source"], "tushare:daily_basic+margin_detail+hk_hold+index_member")


class PortfolioRiskRuntimePolicyTests(unittest.TestCase):
    @staticmethod
    def _mutated_configuration():
        """Build a hermetic 80亿→60亿、0.8→0.7 policy snapshot."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copytree(ROOT / "presets", root / "presets")
            policy_path = root / "presets" / "a_short_m67_runtime_policy_20260715.json"
            payload = json.loads(policy_path.read_text(encoding="utf-8"))
            portfolio = payload["portfolio_risk"]
            portfolio["small_float_mv_rmb"] = 6_000_000_000.0
            portfolio["high_risk_holding_cap_multiplier"] = 0.7
            policy_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return load_runtime_configuration(root=root)

    @staticmethod
    def _load_consumer(rel: str, module_name: str, configuration: dict):
        spec = importlib.util.spec_from_file_location(module_name, ROOT / rel)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load isolated consumer {rel}")
        module = importlib.util.module_from_spec(spec)
        with patch("engine.a_short_runtime_config.load_runtime_configuration", return_value=configuration):
            spec.loader.exec_module(module)
        return module

    def _high_risk_weekly(self):
        first = _normal("000001.SZ", "bank", held_shares=20_000)
        second = _normal("600000.SH", "tech", held_shares=20_000)
        facts = {
            "000001.SZ": _facts("000001.SZ", "bank", north=20.0, margin=12.0),
            "600000.SH": _facts("600000.SH", "tech", north=20.0, margin=12.0),
        }
        positions = [
            {"ts_code": "000001.SZ", "shares": 20_000, "avg_cost": 2.7,
             "entry_date": "20260601", "stop_loss": 2.5},
            {"ts_code": "600000.SH", "shares": 20_000, "avg_cost": 2.7,
             "entry_date": "20260601", "stop_loss": 2.5},
        ]
        return build_weekly_report([first, second], AS_OF, GEN, run_lineage=_sized_lineage(),
                                   available_cash=1_000_000.0, portfolio_fact_overrides=facts,
                                   account_positions=positions)

    def test_isolated_policy_mutant_reloads_all_portfolio_consumers(self):
        configuration = self._mutated_configuration()
        portfolio = self._load_consumer("engine/a_short_portfolio_risk.py", "_portfolio_policy_mutant", configuration)
        weekly = self._load_consumer("runners/a_short_weekly_pipeline.py", "_weekly_policy_mutant", configuration)

        self.assertEqual(portfolio.SMALL_FLOAT_MV_RMB, 6_000_000_000.0)
        self.assertEqual(portfolio.HIGH_RISK_HOLDING_CAP_MULTIPLIER, 0.7)
        self.assertNotEqual(configuration["lineage"]["configuration_fingerprint"],
                            load_runtime_configuration()["lineage"]["configuration_fingerprint"])

        small_float_breach = {
            "status": "factor_resonance",
            "industry_exposures": [],
            "factor_exposures": [{"factor": "small_float_mv_pct", "over_threshold": True}],
        }
        fact = {"circ_mv_rmb": 7_000_000_000.0}
        self.assertTrue(_holding_adds_portfolio_risk(fact, small_float_breach))
        self.assertFalse(weekly._holding_adds_portfolio_risk(fact, small_float_breach))

        first = _normal("000001.SZ", "bank", held_shares=20_000)
        second = _normal("600000.SH", "tech", held_shares=20_000)
        context = portfolio.build_context([first, second], AS_OF, fact_overrides={
            "000001.SZ": _facts("000001.SZ", "bank", north=20.0, margin=12.0),
            "600000.SH": _facts("600000.SH", "tech", north=20.0, margin=12.0),
        })
        summary = portfolio.final_summary(context)
        self.assertEqual(summary["status"], "factor_resonance_high_risk")
        self.assertEqual(summary["holding_single_position_cap_multiplier"], 0.7)
        self.assertIn("小流通市值(<60亿元)",
                      next(row[1] for row in portfolio._FACTOR_SPECS if row[0] == "small_float_mv_pct"))
        self.assertIn("下调30%", summary["reasons"][0])

        report = self._high_risk_weekly()
        self.assertEqual(report["portfolio_risk"]["status"], "factor_resonance_high_risk")
        report["portfolio_risk"]["summary"] = copy.deepcopy(summary)
        report["run_lineage"]["runtime_configuration"] = copy.deepcopy(configuration["lineage"])
        weekly.validate_runtime_configuration_lineage = lambda lineage: (
            None if lineage == configuration["lineage"] else (_ for _ in ()).throw(ValueError("mutant lineage mismatch"))
        )
        weekly.validate_weekly_report(report, _feed())
        markdown = render_weekly_markdown(report)
        self.assertIn("小流通市值(<60亿元)", markdown)
        self.assertIn("下调30%", markdown)


MARGIN_COMPLETE = {"reference_date": AS_OF, "effective_ref_date": AS_OF, "row_count": 1200,
                   "universe_size": 1100, "coverage_complete": True, "status": "complete"}


def _with_complete_margin_checks(row):
    """Give a pre-margin-knife fixture row the source metrics the gate now requires."""
    for check in row.get("rule6_checks") or []:
        if check.get("id") in {"rule6_margin_extreme_accumulation", "rule6_short_selling_surge"}:
            check["metrics"] = {"status": "complete"}
    return row


class PortfolioRiskM67IntegrationTests(unittest.TestCase):
    def _weekly(self, *, missing=False, margin_source_complete=True):
        held = _normal("000001.SZ", "bank", held_shares=100_000)
        first = _normal("600000.SH", "bank")       # same industry as held -> must be blocked
        second = _normal("600519.SH", "tech")       # can use freed cash
        third = _normal("601318.SH", "health")
        facts = {
            "000001.SZ": _facts("000001.SZ", "bank"),
            "600000.SH": _facts("600000.SH", "bank"),
            "600519.SH": _facts("600519.SH", "tech"),
            "601318.SH": _facts("601318.SH", "health"),
        }
        if missing:
            facts["600000.SH"]["northbound_holding_ratio_pct"] = None
        positions = [{"ts_code": "000001.SZ", "shares": 100_000, "avg_cost": 2.7,
                      "entry_date": "20260601", "stop_loss": 2.5}]
        rows = [held, first, second, third]
        if margin_source_complete:
            rows = [_with_complete_margin_checks(row) for row in rows]
        return build_weekly_report(rows, AS_OF, GEN,
                                   run_lineage=_sized_lineage(), available_cash=1_000_000.0,
                                   portfolio_fact_overrides=facts, account_positions=positions,
                                   margin_coverage=(copy.deepcopy(MARGIN_COMPLETE)
                                                    if margin_source_complete else None))

    def test_blocked_candidate_changes_json_markdown_and_reallocates_cash(self):
        weekly = self._weekly()
        by_code = {report["ts_code"]: report for report in weekly["reports"]}
        blocked = by_code["600000.SH"]
        self.assertEqual(blocked["m67"]["table"]["操作"], "观察")
        self.assertIsNone(blocked["m67"]["table"]["股数"])
        self.assertEqual(blocked["machine"]["layer"]["portfolio_risk"]["action"], "replace")
        self.assertEqual(by_code["600519.SH"]["m67"]["table"]["操作"], "建仓")
        self.assertEqual(by_code["601318.SH"]["m67"]["table"]["操作"], "建仓")
        self.assertEqual(len(weekly["portfolio_risk"]["stock_results"]), weekly["n_stocks"])
        effects = {record["id"]: record for record in weekly["effect_contract_ledger"]["records"]}
        # The real M5.5/M5.5B action is applied above; the all-leaf contract
        # stays manual until portfolio_impact's unused sibling leaves are split.
        self.assertEqual(effects["portfolio_concentration_factor_resonance"]["status"],
                         "unavailable_manual_review")
        # This fixture supplies no deterministic industry-trend evidence.  It
        # must remain visibly unverified rather than being silently treated as
        # a neutral, non-triggered signal.
        self.assertEqual(effects["industry_trend"]["status"], "unavailable_manual_review")
        validate_weekly_report(weekly, _feed())
        markdown = render_weekly_markdown(weekly)
        self.assertIn("组合集中度与因子共振", markdown)
        self.assertIn("字段/规则联动台账", markdown)
        self.assertIn("600000.SH", markdown)

    def test_unknown_fact_is_visible_manual_review_and_tamper_is_rejected(self):
        weekly = self._weekly(missing=True)
        blocked = next(report for report in weekly["reports"] if report["ts_code"] == "600000.SH")
        self.assertEqual(blocked["m67"]["table"]["操作"], "观察")
        self.assertEqual(blocked["machine"]["layer"]["portfolio_risk"]["status"], "manual_review_required")
        self.assertIn("未核查", render_weekly_markdown(weekly))
        tampered = copy.deepcopy(weekly)
        next(item for item in tampered["portfolio_risk"]["stock_results"]
             if item["ts_code"] == "600000.SH")["action"] = "allow"
        with self.assertRaises(ValueError):
            validate_weekly_report(tampered, _feed())

    def test_margin_outage_does_not_erase_portfolio_manual_review(self):
        # The outage stops the trial, but "could not evaluate" must not be
        # reported as "this portfolio rule does not apply".
        weekly = self._weekly(missing=True, margin_source_complete=False)
        blocked = next(r for r in weekly["reports"] if r["ts_code"] == "600000.SH")
        risk = blocked["machine"]["layer"]["portfolio_risk"]
        self.assertTrue(blocked["machine"]["layer"]["decision_reasons"]["margin_source_unavailable"])
        self.assertEqual(risk["status"], "manual_review_required")
        self.assertFalse(risk["evaluated"])
        self.assertIn("两融数据源不可用", risk["reasons"][0])
        validate_weekly_report(weekly, _feed())
