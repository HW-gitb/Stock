# -*- coding: utf-8 -*-
"""First-cut TP1/TP2 holding-action closure: quantity, price, and private-state behavior."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_holding_action as ha  # noqa: E402
from engine.us_short_weekend_decision import action_quantity_error  # noqa: E402


def _context(**over):
    out = {
        "status": "ready", "shares": 100, "entry_date": "20260601", "avg_cost_usd": 100.0,
        "tp1_completed": False, "tp1_completed_at": None, "active_tp1_price": 110.0,
        "active_tp2_price": 120.0, "levels_as_of": "20260612",
        "source_reconciliation_ref": "manual_account:test", "price_basis_date": "20260619",
        "price_session": "RTH", "price_adjustment": "split_adjusted",
        "cost_input": {"commission_round_trip": 0.0, "slippage_dollars": 0.0, "spread_dollars": 0.0},
        "price_basis_value": 110.0,
    }
    out.update(over)
    return out


def _evidence(**over):
    out = {
        "row_context": "holding", "holding_action_context": _context(),
        "price": {"executable": True, "trace": {"breached": False}, "action_fields": {
            "stop_clear_price": 95.0, "take_profit_reduce_price": 112.0,
            "take_profit_exit_price": 124.0, "event_clear_reference_price": 94.0,
        }},
    }
    out.update(over)
    return out


class HoldingActionPlannerTests(unittest.TestCase):
    def test_tp1_is_fixed_ten_percent_of_reconciled_remaining_shares(self):
        action, reason, proposal, price = ha.plan_holding_action(_evidence(), "持有", None)
        self.assertEqual((action, reason), ("减仓", None))
        self.assertEqual(proposal["recommended_action_shares"], 10)
        self.assertEqual(proposal["price_target_field"], "take_profit_reduce_price")
        self.assertEqual(price["action_fields"]["take_profit_reduce_price"], 110.0)
        self.assertIsNone(action_quantity_error(action, {"row_context": "holding", "action_proposal": proposal}))

    def test_tp2_full_exit_precedes_tp1(self):
        ev = _evidence(holding_action_context=_context(price_basis_value=120.0))
        action, reason, proposal, price = ha.plan_holding_action(ev, "持有", None)
        self.assertEqual((action, reason), ("清仓-止盈", None))
        self.assertEqual(proposal["recommended_action_shares"], 100)
        self.assertEqual(proposal["price_target_field"], "take_profit_exit_price")
        self.assertEqual(price["action_fields"]["take_profit_exit_price"], 120.0)

    def test_event_and_stop_keep_precedence_and_use_all_reconciled_shares(self):
        for action_in in ("清仓-事件", "清仓-止损"):
            action, _, proposal, _ = ha.plan_holding_action(_evidence(), action_in, None)
            self.assertEqual(action, action_in)
            self.assertEqual(proposal["recommended_action_shares"], 100)

    def test_tp1_never_repeats_after_manual_completion(self):
        ev = _evidence(holding_action_context=_context(tp1_completed=True, tp1_completed_at="20260619"))
        action, reason, proposal, _ = ha.plan_holding_action(ev, "持有", None)
        self.assertEqual((action, reason), ("持有", None))
        self.assertIsNone(proposal["recommended_action_shares"])

    def test_under_one_share_and_missing_cost_do_not_emit_zero_share_reduce(self):
        ev = _evidence(holding_action_context=_context(shares=9))
        action, _, proposal, _ = ha.plan_holding_action(ev, "持有", None)
        self.assertEqual(action, "持有")
        self.assertEqual(proposal["reason"], "tp1_deferred_below_min")
        self.assertIsNone(proposal["recommended_action_shares"])
        ev = _evidence(holding_action_context=_context(cost_input=None))
        action, _, proposal, _ = ha.plan_holding_action(ev, "持有", None)
        self.assertEqual(action, "持有")
        self.assertEqual(proposal["reason"], "tp1_deferred_unverifiable_cost")

    def test_untrusted_reconciliation_keeps_mandatory_exit_with_manual_share_confirmation(self):
        ev = _evidence(holding_action_context={"status": "untrusted"})
        for base_action in ("清仓-止损", "清仓-事件"):
            action, reason, proposal, _ = ha.plan_holding_action(ev, base_action, None)
            self.assertEqual((action, reason), (base_action, None))
            self.assertIsNone(proposal["recommended_action_shares"])
            self.assertEqual(proposal["reason"], "mandatory_holding_exit_manual_share_confirmation")
            self.assertIsNotNone(proposal["price_target_field"])
            self.assertIsNone(action_quantity_error(action, {"row_context": "holding", "action_proposal": proposal}))

    def test_untrusted_reconciliation_still_observes_a_non_mandatory_action(self):
        ev = _evidence(holding_action_context={"status": "untrusted"})
        action, reason, proposal, _ = ha.plan_holding_action(ev, "持有", None)
        self.assertEqual((action, reason), ("观察", "cash_or_account_missing"))
        self.assertEqual(proposal["reason"], "holding_action_state_untrusted")

    def test_one_bad_reconciliation_row_only_marks_its_own_ticker_untrusted(self):
        account = {
            "positions": [
                {"ticker": "AAPL", "shares": 90, "entry_date": "20260601", "avg_cost_usd": 100.0},
                {"ticker": "MSFT", "shares": 80, "entry_date": "20260602", "avg_cost_usd": 200.0},
            ],
            "holding_action_reconciliation": {
                "positions": [
                    {"ticker": "AAPL", "remaining_shares": 90, "entry_date": "20260601",
                     "tp1_completed": False, "tp1_completed_at": None,
                     "source_reconciliation_ref": "manual_account:aapl"},
                    {"ticker": "MSFT", "remaining_shares": 0, "entry_date": "20260602",
                     "tp1_completed": False, "tp1_completed_at": None,
                     "source_reconciliation_ref": "manual_account:msft"},
                ]
            },
        }
        contexts = ha.build_holding_action_context(account, None)
        self.assertEqual(contexts["AAPL"]["status"], "seed_required")
        self.assertEqual(contexts["MSFT"], {"status": "untrusted"})


class HoldingActionStateTests(unittest.TestCase):
    def test_first_run_seeds_levels_but_never_marks_a_recommendation_executed(self):
        ev = _evidence(holding_action_context=_context(status="seed_required", active_tp1_price=None,
                                                        active_tp2_price=None, levels_as_of=None,
                                                        price_basis_value=105.0))
        action, _, proposal, price = ha.plan_holding_action(ev, "持有", None)
        self.assertEqual(action, "持有")
        state = ha.build_next_holding_action_state("20260622", [{
            "ticker": "AAPL", "row_context": "holding", "holding_action_context": ev["holding_action_context"],
            "price": price, "action_proposal": proposal, "final_action": action,
        }])
        item = state["positions"][0]
        self.assertEqual((item["active_tp1_price"], item["active_tp2_price"]), (112.0, 124.0))
        self.assertFalse(item["tp1_completed"])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ha.STATE_FILENAME
            p.write_text(__import__("json").dumps(state), encoding="utf-8")
            self.assertEqual(ha.load_holding_action_state(p, decision_date="20260622"), state)

    def test_account_reconciliation_is_the_only_completion_source(self):
        account = {"positions": [{"ticker": "AAPL", "shares": 90, "entry_date": "20260601", "avg_cost_usd": 100.0}],
                   "holding_action_reconciliation": {"positions": [{
                       "ticker": "AAPL", "remaining_shares": 90, "entry_date": "20260601",
                       "tp1_completed": True, "tp1_completed_at": "20260619",
                       "source_reconciliation_ref": "manual_account:filled"}]}}
        context = ha.build_holding_action_context(account, None)["AAPL"]
        self.assertTrue(context["tp1_completed"])
        self.assertEqual(context["remaining_shares"] if "remaining_shares" in context else context["shares"], 90)

    def test_future_private_tp1_completion_is_rejected(self):
        ev = _evidence(holding_action_context=_context(status="seed_required", active_tp1_price=None,
                                                        active_tp2_price=None, levels_as_of=None))
        _, _, proposal, price = ha.plan_holding_action(ev, "持有", None)
        state = ha.build_next_holding_action_state("20260622", [{
            "ticker": "AAPL", "row_context": "holding", "holding_action_context": ev["holding_action_context"],
            "price": price, "action_proposal": proposal, "final_action": "持有",
        }])
        state["positions"][0]["tp1_completed"] = True
        state["positions"][0]["tp1_completed_at"] = "20260623"
        with self.assertRaises(ha.HoldingActionError):
            ha.validate_holding_action_state(state, decision_date="20260622")


if __name__ == "__main__":
    unittest.main()
