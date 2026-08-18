"""Offline common-order snapshot production for the US-short comparison v2 contract."""
from __future__ import annotations

import copy
import hashlib
import json
import unittest

from engine import us_short_forward_policy_order_snapshot as snapshot
from engine.us_short_forward_policy_heads import SELECTION_POLICY_IDS
from engine.us_short_paper_fill import simulate_fill
from engine.us_short_forward_policy_statistical_plan import statistical_plan_sha256
from engine.us_short_forward_policy_effect_surface import baseline_epoch_sha256


COMMON_POOL = ["ALFA", "BETA"]
_AGGRESSIVE = {"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"}
_DEFENSIVE = {"vix": "防御", "market_trend": "防御", "breadth": "防御"}


def _pool_digest() -> str:
    return hashlib.sha256(json.dumps(COMMON_POOL, separators=(",", ":")).encode("utf-8")).hexdigest()


def _decision() -> dict:
    return {
        "out_of_window": False,
        "decision_date": "20260713",
        "price_basis_date": "20260710",
        "run_date": "20260712",
        "cheap_eligible": list(COMMON_POOL),
        "candidates": list(COMMON_POOL),
        "recall_available": False,
        "recall_added": [],
        "recall_excluded": [],
        "exclusion_records": [],
        "admitted": list(COMMON_POOL),
        "selection_seats": {},
        "theme_selection_mode": "industry_heat_v1_cross_industry_disabled",
        "full_analysis_leader_upgrades": [],
        "selection_details": [],
        "holdings": [],
    }


def _capture() -> dict:
    return {
        "schema_name": "us_short_forward_policy_shadow_selection",
        "schema_version": "2.1.0",
        "decision_date": "20260713",
        "price_basis_date": "20260710",
        "generated_at": "2026-07-13T08:00:00-04:00",
        "source_context_sha256": "a" * 64,
        "comparison_contract_sha256": statistical_plan_sha256(),
        "baseline_epoch_sha256": baseline_epoch_sha256(),
        "common_selection_pool": list(COMMON_POOL),
        "common_selection_pool_sha256": _pool_digest(),
        "selection_policies": list(SELECTION_POLICY_IDS),
        "selection_decisions": {policy_id: _decision() for policy_id in SELECTION_POLICY_IDS},
        "boundary": {
            "track": "comparison_non_production",
            "evidence_level": "shadow_selection_only",
            "shadow_counts_ship_gate": False,
            "full_size_ship_gate_allowed": False,
            "provider_calls_added": False,
            "broker_or_order_automation_allowed": False,
        },
    }


def _indicators(offset: float = 0.0) -> dict:
    return {
        "effective_support": 98.0 + offset,
        "effective_resistance": 110.0 + offset,
        "atr": 2.0,
        "support_quality": "strong",
        "resistance_quality": "strong",
    }


def _candidate_price_inputs() -> dict:
    return {
        "ALFA": {
            "ticker": "ALFA",
            "price_input": {"close": 100.0, "indicators": _indicators()},
            "sub_mode": "pullback",
            "defensive_breakout_probe_allowed": False,
            "overextension": None,
        },
        "BETA": {
            "ticker": "BETA",
            "price_input": {
                "close": 100.0,
                "indicators": {
                    "effective_support": 90.0,
                    "effective_resistance": 110.0,
                    "atr": 2.0,
                    "support_quality": "strong",
                    "resistance_quality": "strong",
                },
            },
            "sub_mode": "breakout",
            "defensive_breakout_probe_allowed": False,
            "overextension": None,
        },
    }


class ForwardPolicyOrderSnapshotTests(unittest.TestCase):
    def _produce(self, **overrides) -> dict:
        kwargs = {
            "capture": _capture(),
            "price_basis_date": "20260710",
            "candidate_price_inputs_by_ticker": _candidate_price_inputs(),
            "market_axis_regimes": dict(_AGGRESSIVE),
            "prior_regime": None,
            "prior_upgrade_count": 0,
        }
        kwargs.update(overrides)
        return snapshot.produce_forward_policy_order_snapshot(**kwargs)

    def test_builds_one_common_order_for_each_pass2_clean_candidate(self):
        result = self._produce()
        snapshot.validate_forward_policy_order_snapshot_packet(result)

        self.assertEqual(result["order_snapshot_status"], "ready_for_outcome")
        self.assertEqual(result["common_selection_pool"], COMMON_POOL)
        self.assertEqual(result["market_risk_regime"], "进攻")
        self.assertEqual(result["non_executable_tickers"], [])
        self.assertIsNone(result["degradation_reason"])
        self.assertEqual(set(result["orders_by_ticker"]), set(COMMON_POOL))
        self.assertEqual(result["orders_by_ticker"]["ALFA"]["order_type"], "pullback_limit")
        self.assertEqual(result["orders_by_ticker"]["BETA"]["order_type"], "breakout_stop_limit")
        self.assertEqual(len(result["common_price_input_snapshot_sha256"]), 64)
        self.assertEqual(len(result["common_order_snapshot_sha256"]), 64)
        self.assertFalse(result["boundary"]["writes_order_snapshot"])
        self.assertFalse(result["boundary"]["writes_outcome_data"])

    def test_uses_one_regime_and_existing_price_guard_for_every_candidate(self):
        result = self._produce(market_axis_regimes=dict(_DEFENSIVE))
        self.assertEqual(result["market_risk_regime"], "防御")
        # BETA asks for breakout, but the established §8 defensive guard makes every candidate's
        # counterfactual order obey the same no-chase policy before the snapshot is frozen.
        self.assertEqual(result["orders_by_ticker"]["BETA"]["order_type"], "pullback_limit")

    def test_complete_snapshot_orders_are_accepted_by_the_existing_model_paper_fill_contract(self):
        result = self._produce()
        day_bar = {"open": 100.0, "high": 102.0, "low": 99.0, "close": 100.0}
        for order in result["orders_by_ticker"].values():
            self.assertIn(
                simulate_fill(order, day_bar)["status"],
                {"not_filled", "filled_held", "filled_stopped", "filled_tp_exit"},
            )

    def test_unbuildable_common_candidate_returns_whole_week_no_count_not_partial_orders(self):
        rows = _candidate_price_inputs()
        rows["BETA"]["price_input"] = {"close": None, "indicators": _indicators(1.0)}
        result = self._produce(candidate_price_inputs_by_ticker=rows)

        self.assertEqual(result["order_snapshot_status"], "data_degraded_whole_week_no_count")
        self.assertEqual(result["degradation_reason"], "common_candidate_order_not_executable")
        self.assertEqual(result["orders_by_ticker"], {})
        self.assertEqual(result["non_executable_tickers"], ["BETA"])
        self.assertIsNone(result["common_order_snapshot_sha256"])

    def test_marketwide_no_new_entry_is_no_count_without_inventing_candidate_failures(self):
        result = self._produce(market_axis_regimes={})

        self.assertEqual(result["order_snapshot_status"], "data_degraded_whole_week_no_count")
        self.assertEqual(result["degradation_reason"], "new_entry_not_permitted")
        self.assertEqual(result["orders_by_ticker"], {})
        self.assertEqual(result["non_executable_tickers"], [])

    def test_rejects_mixed_pool_or_price_basis_drift_instead_of_reusing_partial_input(self):
        rows = _candidate_price_inputs()
        rows.pop("BETA")
        with self.assertRaises(snapshot.ForwardPolicyOrderSnapshotError):
            self._produce(candidate_price_inputs_by_ticker=rows)

        with self.assertRaises(snapshot.ForwardPolicyOrderSnapshotError):
            self._produce(price_basis_date="20260709")

        swapped = _candidate_price_inputs()
        swapped["ALFA"]["ticker"] = "BETA"
        with self.assertRaises(snapshot.ForwardPolicyOrderSnapshotError):
            self._produce(candidate_price_inputs_by_ticker=swapped)

        tampered = self._produce()
        tampered["orders_by_ticker"]["ALFA"]["stop_clear_price"] = 200.0
        with self.assertRaises(snapshot.ForwardPolicyOrderSnapshotError):
            snapshot.validate_forward_policy_order_snapshot_packet(tampered)

    def test_rejects_malformed_price_input_container_rather_than_converting_it_to_no_count(self):
        rows = _candidate_price_inputs()
        rows["ALFA"]["price_input"] = "not-an-object"
        with self.assertRaises(snapshot.ForwardPolicyOrderSnapshotError):
            self._produce(candidate_price_inputs_by_ticker=rows)

    def test_rejects_malformed_regime_carry_state_before_the_shared_price_analysis_runs(self):
        with self.assertRaises(snapshot.ForwardPolicyOrderSnapshotError):
            self._produce(prior_regime="进攻", prior_upgrade_count="one")


if __name__ == "__main__":
    unittest.main()
