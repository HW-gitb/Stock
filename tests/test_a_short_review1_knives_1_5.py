"""Focused adversarial closure tests for desktop ``ashort_review1.md`` cuts 1-5."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import a_short_account_state_from_manual_tables as conv  # noqa: E402
from runners.a_short_weekly_pipeline import (  # noqa: E402
    _apply_holding_ratchet, account_integrity_from_lineage, resolve_market_regime,
    stateful_risk_for_candidate, validate_iv_feed_freshness)
from runners.a_short_weekly_pipeline import main as weekly_main  # noqa: E402
from runners.a_short_phase5_engine import build_m67_report, exit_and_size  # noqa: E402
from engine.a_short_rule6_contract import RULE6_CHECKS, RULE6_D_TIER_REASONS  # noqa: E402


DECISION = "20260713"
FACTS = "20260712"
_CONFIG = {
    "rule13_cooldown_calendar_days": 1,
    "rule13_default_max_reentry_position_pct": 0.5,
    "rule12_default_recovery_position_multiplier": 0.5,
}


def _clear_rule6_checks():
    return [
        {"id": check_id, "group": group,
         "status": "not_applicable" if check_id in RULE6_D_TIER_REASONS else "pass",
         "notes": RULE6_D_TIER_REASONS.get(check_id)}
        for check_id, group in RULE6_CHECKS
    ]


def _tables():
    return copy.deepcopy({
        "account": [{
            "as_of": FACTS,
            "available_cash": "500000",
            "total_equity": "1200000",
            "current_gross_exposure": "300000",
            "manual_order_only": "TRUE",
            "broker_connection_allowed": "FALSE",
        }],
        "positions": [],
        "trades": [],
        "manual_controls": [],
        "portfolio_rule12": [{
            "status": "inactive", "reason": "", "triggered_at": "", "cooldown_until": "",
            "recovery_position_multiplier": "", "consecutive_stop_losses_window": "0",
            "drawdown_pct": "0", "iv_change_abs_1d_pctpt": "0",
        }],
    })


class Cut1AccountBundleTests(unittest.TestCase):
    def test_stale_facts_keep_true_date_and_bundle_identity(self):
        bundle = conv.build_account_bundle(_tables(), DECISION, _CONFIG)
        self.assertEqual(bundle["decision_as_of"], DECISION)
        self.assertEqual(bundle["facts_as_of"], FACTS)
        self.assertEqual(bundle["account"]["as_of"], FACTS)
        self.assertEqual(bundle["lineage"]["facts_as_of"], FACTS)
        self.assertRegex(bundle["snapshot_id"], rf"^a-short-account-{FACTS}-[0-9a-f]{{16}}$")
        self.assertRegex(bundle["snapshot_digest"], r"^[0-9a-f]{64}$")
        self.assertIs(conv.validate_account_bundle(bundle, DECISION), bundle)

    def test_tampered_account_cannot_reuse_old_lineage_or_digest(self):
        bundle = conv.build_account_bundle(_tables(), DECISION, _CONFIG)
        bundle["account"]["available_cash"] += 1
        with self.assertRaises(SystemExit):
            conv.validate_account_bundle(bundle, DECISION)

    def test_decision_day_may_advance_rule12_after_prior_facts_date(self):
        tables = _tables()
        tables["portfolio_rule12"][0].update({
            "status": "active_cooldown",
            "reason": "manual confirmed circuit",
            "triggered_at": FACTS,
            "cooldown_until": DECISION,
        })
        bundle = conv.build_account_bundle(tables, DECISION, _CONFIG)
        self.assertEqual(bundle["account"]["as_of"], FACTS)
        self.assertEqual(bundle["account"]["rule12"]["cooldown_until"], DECISION)
        self.assertIs(conv.validate_account_bundle(bundle, DECISION), bundle)


def _prices(close=2.90):
    rows = []
    for i in range(30):
        high, low = ((3.10, 2.87) if i == 12 else
                     ((3.10, 2.88) if i == 13 else (2.92, 2.88)))
        rows.append({"trade_date": f"202606{i + 1:02d}", "high": high, "low": low, "close": close})
    return rows


def _engine_input(stateful, cash=0.0):
    checks = _clear_rule6_checks()
    for check in checks:
        if check["id"] in {"rule6_margin_extreme_accumulation", "rule6_short_selling_surge"}:
            check["metrics"] = {"status": "complete"}
    return {
        "analysis_role": "final",
        "ts_code": "600000.SH", "name": "测试", "close": 2.90, "price_series": _prices(),
        "derived": {}, "event": {}, "liquidity": {"avg_amount_5d": 1e8},
        "rule6_checks": checks,
        "margin_coverage": {"reference_date": DECISION, "effective_ref_date": DECISION,
                            "row_count": 1200, "universe_size": 1100,
                            "coverage_complete": True, "status": "complete"},
        "price_data_through": DECISION,
        "iv": {"iv_percentile_252d": 50.0}, "market_regime": "震荡期",
        "account": {"available_cash": cash, "total_equity": 1_200_000.0,
                    "current_gross_exposure": 300_000.0,
                    "bucket_ceiling_pct": 0.333333,
                    "bucket_capital": 399_999.6,
                    "new_exposure_capacity": 99_999.6},
        "portfolio": {}, "stateful_risk": stateful,
    }


class Cut2AccountFailClosedTests(unittest.TestCase):
    def test_missing_rule12_table_is_not_default_inactive(self):
        tables = _tables()
        tables["portfolio_rule12"] = []
        with self.assertRaises(SystemExit):
            conv.build_account_bundle(tables, DECISION, _CONFIG)

    def test_zero_cash_keeps_existing_holding_management(self):
        tables = _tables()
        tables["account"][0]["available_cash"] = "0"
        tables["positions"] = [{
            "ts_code": "600000.SH", "name": "测试", "shares": "1000", "avg_cost": "9.8",
            "entry_date": "20260701", "stop_loss": "9.2", "take_profit_1": "", "take_profit_2": "",
            "last_exit_date": "", "last_exit_reason": "", "manual_notes": "",
        }]
        bundle = conv.build_account_bundle(tables, DECISION, _CONFIG)
        stateful = stateful_risk_for_candidate(bundle["account"], "600000.SH", DECISION)
        report = build_m67_report(_engine_input(stateful, cash=0.0), DECISION, "2026-07-13T08:00:00+08:00")
        self.assertEqual(report["m67"]["table"]["操作"], "持有")

    def test_net_buy_missing_position_blocks_new_entries(self):
        tables = _tables()
        tables["trades"].append({
            "trade_date": FACTS, "ts_code": "600000.SH", "name": "测试", "side": "BUY",
            "shares": "100", "price": "10", "reason": "entry", "order_manual": "TRUE", "notes": "",
        })
        bundle = conv.build_account_bundle(tables, DECISION, _CONFIG)
        integrity = account_integrity_from_lineage(bundle["lineage"])
        self.assertEqual(integrity["status"], "blocked")
        stateful = stateful_risk_for_candidate(
            bundle["account"], "600000.SH", DECISION, account_integrity=integrity)
        report = build_m67_report(_engine_input(stateful, cash=500000.0), DECISION,
                                  "2026-07-13T08:00:00+08:00")
        self.assertEqual(report["m67"]["table"]["操作"], "否决")
        self.assertIn("account_integrity", "|".join(report["machine"]["layer"]["hard_veto"]))


class Cut3CapitalAndReasonTests(unittest.TestCase):
    def test_full_bucket_forces_zero_new_shares(self):
        inp = _engine_input({}, cash=500_000.0)
        inp["account"]["current_gross_exposure"] = 400_000.0
        inp["account"]["new_exposure_capacity"] = 0.0
        report = build_m67_report(inp, DECISION, "2026-07-13T08:00:00+08:00")
        self.assertEqual(report["m67"]["table"]["操作"], "观察")
        self.assertIsNone(report["m67"]["table"]["股数"])
        self.assertIn("bucket", "|".join(report["machine"]["layer"]["decision_reasons"]["sizing_block"]))

    def test_existing_exposure_reduces_new_position_size(self):
        roomy = _engine_input({}, cash=500_000.0)
        roomy["account"]["current_gross_exposure"] = 0.0
        roomy["account"]["new_exposure_capacity"] = roomy["account"]["bucket_capital"]
        tight = copy.deepcopy(roomy)
        tight["account"]["current_gross_exposure"] = 370_000.0
        tight["account"]["new_exposure_capacity"] = tight["account"]["bucket_capital"] - 370_000.0
        r1 = build_m67_report(roomy, DECISION, "2026-07-13T08:00:00+08:00")
        r2 = build_m67_report(tight, DECISION, "2026-07-13T08:00:00+08:00")
        self.assertEqual(r1["m67"]["table"]["操作"], "建仓")
        self.assertEqual(r2["m67"]["table"]["操作"], "建仓")
        self.assertLess(r2["m67"]["table"]["股数"], r1["m67"]["table"]["股数"])

    def test_downgrade_never_appears_as_hard_veto(self):
        stateful = {"position_state": "flat", "position": None,
                    "rule12": {"status": "recovery_1"}, "rule13": {"status": "none"},
                    "size_multiplier": 0.5, "reasons": ["Rule12 recovery_1:size_multiplier=0.50"]}
        report = build_m67_report(_engine_input(stateful, cash=500_000.0), DECISION,
                                  "2026-07-13T08:00:00+08:00")
        reasons = report["machine"]["layer"]["decision_reasons"]
        self.assertTrue(reasons["downgrade"])
        self.assertFalse(reasons["hard_veto"])


class Cut4StopAndRRTests(unittest.TestCase):
    def test_breakout_rr_fallback_uses_same_entry_high_basis(self):
        inp = _engine_input({}, cash=500_000.0)
        inp["close"] = 10.0
        inp["account"].update(bucket_capital=400_000.0, new_exposure_capacity=400_000.0)
        ind = {"support": 9.0, "support_quality": "strong", "resistance": 9.5,
               "resistance_quality": "weak", "atr14": 0.8}
        plan, reject = exit_and_size(inp, ind, "震荡期", etype="突破")
        self.assertIsNone(reject)
        self.assertGreaterEqual(plan["rr_at_entry_high"], plan["rr_floor"])
        self.assertEqual(plan["t1_basis"], "rr_floor_fallback")

    def test_pre_entry_high_cannot_raise_holding_stop(self):
        inp = _engine_input({
            "position_state": "held",
            "position": {"ts_code": "600000.SH", "shares": 1000, "avg_cost": 2.80,
                         "entry_date": "20260620", "stop_loss": 2.75},
            "rule12": {"status": "inactive"}, "rule13": {"status": "none"},
            "size_multiplier": 1.0, "reasons": [],
        })
        # Two pre-entry spikes would become a false effective resistance under the old 20-day logic.
        inp["price_series"][12]["high"] = 5.0
        inp["price_series"][13]["high"] = 5.0
        report = build_m67_report(inp, DECISION, "2026-07-13T08:00:00+08:00")
        plan = report["machine"]["entry_exit_size_star"]["plan"]
        self.assertFalse(plan["breached"])
        self.assertGreaterEqual(plan["stop"], 2.75)
        self.assertLess(plan["stop"], inp["close"])
        self.assertEqual(plan["highest_since_entry"], 2.92)

    def test_cross_week_ratchet_updates_final_report_stop(self):
        stateful = {
            "position_state": "held",
            "position": {"ts_code": "600000.SH", "shares": 1000, "avg_cost": 2.70,
                         "entry_date": "20260620", "stop_loss": 2.70},
            "rule12": {"status": "inactive"}, "rule13": {"status": "none"},
            "size_multiplier": 1.0, "reasons": [],
        }
        report = build_m67_report(_engine_input(stateful), DECISION, "2026-07-13T08:00:00+08:00")
        old = report["machine"]["entry_exit_size_star"]["plan"]["stop"]
        previous = {"600000.SH|20260620": {
            "ts_code": "600000.SH", "entry_date": "20260620", "last_as_of": "20260706",
            "ratcheted_stop": old + 0.02, "last_disposition": "hold",
            "last_reduce_price": None, "last_clear_price": old + 0.02,
            "week_count": 1, "cross_week_price_cross": "none", "bootstrap": True}}
        weekly = {"reports": [report]}
        _apply_holding_ratchet(weekly, previous, DECISION)
        final_stop = report["machine"]["ratchet"]["ratcheted_stop"]
        self.assertEqual(report["machine"]["entry_exit_size_star"]["plan"]["stop"], final_stop)
        self.assertEqual(report["m67"]["table"]["损"], final_stop)
        advice = report["m67"]["精简结论区"]["操作建议"]
        self.assertIn(f"跨周最终止损 {final_stop}", advice)
        self.assertNotIn(f"系统跟踪止损 {old}", advice)


class Cut5IVAndRegimeTests(unittest.TestCase):
    def test_stale_iv_is_blocked_against_effective_price_clock(self):
        feed = {"series": [{"trade_date": "20260710", "iv_percentile_252d": 50.0}]}
        with self.assertRaises(SystemExit):
            validate_iv_feed_freshness(feed, "20260713")
        status = validate_iv_feed_freshness(feed, "20260710")
        self.assertEqual(status["status"], "aligned")

    def test_unknown_raw_regime_has_explicit_shock_effective_state(self):
        ai = {"market_context": {"market_regime": {"status": "unknown"}}}
        regime, fallback = resolve_market_regime(ai)
        self.assertEqual(regime, "震荡期")
        self.assertEqual(fallback["source_status"], "unknown")
        self.assertEqual(fallback["effective_status"], "shock")

    def test_weekly_wrapper_passes_effective_v142_regime_to_comparison(self):
        script = (ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        self.assertIn("--v14_2-regime", script)
        self.assertIn("$EffectiveV142Regime = 'shock'", script)

    def test_main_emits_bound_clocks_and_effective_regime(self):
        from tests.test_a_short_weekly_pipeline import (  # local reuse of schema-valid fixtures
            _account_bundle, _ai_candidate, _analysis_input, _feed, _series)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "ai.json").write_text(
                json.dumps(_analysis_input(candidates=[_ai_candidate("600000.SH")])), encoding="utf-8")
            (base / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            (base / "acct.json").write_text(json.dumps(_account_bundle()), encoding="utf-8")
            out = base / "weekly.json"
            weekly_main(["--as-of", "20260609", "--analysis-input", str(base / "ai.json"),
                         "--iv-feed", str(base / "feed.json"), "--account", str(base / "acct.json"),
                         "--out", str(out), "--skip-ratchet"],
                        price_provider=lambda code: _series())
            weekly = json.loads(out.read_text(encoding="utf-8"))
        lineage = weekly["run_lineage"]
        self.assertEqual(lineage["iv_freshness"]["status"], "aligned")
        self.assertEqual(lineage["market_regime"]["effective_status"], "shock")
        self.assertEqual(lineage["account_snapshot"]["integrity_status"], "clear")


if __name__ == "__main__":
    unittest.main()
