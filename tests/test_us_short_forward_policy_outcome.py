"""Offline H5/H10/H20 outcome production for the US-short comparison v2 contract."""
from __future__ import annotations

import copy
import hashlib
import json
import unittest
from datetime import date, timedelta

from engine import us_short_forward_policy_outcome as outcome
from engine.us_short_forward_policy_heads import SELECTION_POLICY_IDS
from engine.us_short_forward_policy_statistical_plan import statistical_plan_sha256
from engine.us_short_forward_policy_effect_surface import baseline_epoch_sha256


COMMON_POOL = ["ALFA", "BETA"]
COST = {"commission_fee": 0.001, "slippage_bps": 10.0, "spread_cost": 0.0005}


def _pool_digest() -> str:
    return hashlib.sha256(json.dumps(COMMON_POOL, separators=(",", ":")).encode("utf-8")).hexdigest()


def _decision(policy_id: str) -> dict:
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
        "selection_decisions": {policy_id: _decision(policy_id) for policy_id in SELECTION_POLICY_IDS},
        "boundary": {
            "track": "comparison_non_production",
            "evidence_level": "shadow_selection_only",
            "shadow_counts_ship_gate": False,
            "full_size_ship_gate_allowed": False,
            "provider_calls_added": False,
            "broker_or_order_automation_allowed": False,
        },
    }


def _adjustment_evidence() -> dict:
    return {
        "schema_name": "us_short_paper_eval_adjustment_evidence",
        "schema_version": "1.0.0",
        "decision_date": "20260713",
        "source_refs": [{
            "id": "fixture_price_basis",
            "path": "state/us_short/private/fixture_price_basis.json",
            "sha256": "b" * 64,
        }],
        "adjustment_mode": {
            "status": "confirmed",
            "mode": "split_dividend_adjusted",
            "source_ref_ids": ["fixture_price_basis"],
        },
        "split_handling": {
            "status": "no_events",
            "source_ref_ids": ["fixture_price_basis"],
            "event_refs": [],
        },
        "dividend_handling": {
            "status": "no_events",
            "source_ref_ids": ["fixture_price_basis"],
            "event_refs": [],
        },
        "ex_date_price_consistency": {
            "status": "not_applicable_no_events",
            "source_ref_ids": ["fixture_price_basis"],
            "checked_event_ids": [],
        },
        "scope": {
            "offline_detection_only": True,
            "provider_call_performed": False,
            "corporate_action_reconciliation_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
    }


def _order() -> dict:
    return {
        "order_type": "pullback_limit",
        "order_expiry": "first_regular_session_only",
        "valid_entry_low": 99.0,
        "valid_entry_high": 101.0,
        "limit_order_price": 100.0,
        "stop_clear_price": 95.0,
        "take_profit_exit_price": 110.0,
    }


def _session_dates() -> list[str]:
    value = date(2026, 7, 13)
    dates = []
    while len(dates) < 20:
        if value.weekday() < 5:
            dates.append(value.strftime("%Y%m%d"))
        value += timedelta(days=1)
    return dates


def _bar(*, index: int, session_date: str, open_: float, high: float, low: float, close: float) -> dict:
    return {
        "session_index": index,
        "session_date": session_date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
    }


def _bars() -> dict[str, list[dict]]:
    alfa, beta = [], []
    for index, session_date in enumerate(_session_dates(), start=1):
        if index == 1:
            alfa.append(_bar(index=index, session_date=session_date, open_=100.0, high=102.0, low=99.0, close=101.0))
        elif index < 5:
            alfa.append(_bar(index=index, session_date=session_date, open_=102.0, high=103.0, low=101.0, close=102.0))
        elif index == 5:
            alfa.append(_bar(index=index, session_date=session_date, open_=104.0, high=105.0, low=102.0, close=104.0))
        elif index < 10:
            alfa.append(_bar(index=index, session_date=session_date, open_=106.0, high=107.0, low=103.0, close=106.0))
        elif index == 10:
            alfa.append(_bar(index=index, session_date=session_date, open_=109.0, high=109.5, low=106.0, close=109.0))
        elif index == 11:
            alfa.append(_bar(index=index, session_date=session_date, open_=109.0, high=111.0, low=108.0, close=110.0))
        else:
            alfa.append(_bar(index=index, session_date=session_date, open_=111.0, high=112.0, low=110.0, close=111.0))
        beta.append(_bar(index=index, session_date=session_date, open_=105.0, high=106.0, low=104.0, close=105.0))
    return {"ALFA": alfa, "BETA": beta}


class ForwardPolicyOutcomeTests(unittest.TestCase):
    def _produce(self, **overrides) -> dict:
        kwargs = {
            "capture": _capture(),
            "orders_by_ticker": {ticker: _order() for ticker in COMMON_POOL},
            "daily_bars_by_ticker": _bars(),
            "cost_prior": dict(COST),
            "adjustment_evidence": _adjustment_evidence(),
        }
        kwargs.update(overrides)
        return outcome.produce_forward_policy_outcome(**kwargs)

    def test_produces_private_h5_h10_h20_values_from_one_common_order_snapshot(self):
        result = self._produce()
        outcome.validate_forward_policy_outcome_packet(result)

        self.assertEqual(result["outcome_status"], "ready_for_comparison")
        self.assertEqual(result["entry_session_date"], "20260713")
        self.assertEqual(len(result["common_price_snapshot_sha256"]), 64)
        self.assertEqual(result["outcome_as_of"], _session_dates()[19])
        self.assertEqual(result["horizon_session_dates"], {
            "h5": _session_dates()[4], "h10": _session_dates()[9], "h20": _session_dates()[19],
        })
        self.assertEqual(result["candidate_outcomes"][0]["ticker"], "ALFA")
        alfa = result["candidate_outcomes"][0]
        self.assertEqual(alfa["h5"]["outcome"], "evaluation_mark_only")
        self.assertEqual(alfa["h5"]["model_paper_status"], "filled_held")
        self.assertAlmostEqual(alfa["h5"]["candidate_after_cost_net_return"], 0.0375)
        self.assertEqual(alfa["h10"]["outcome"], "evaluation_mark_only")
        self.assertFalse(alfa["h10"]["realized"])
        self.assertAlmostEqual(alfa["h10"]["candidate_after_cost_net_return"], 0.0875)
        self.assertEqual(alfa["h20"]["outcome"], "model_paper_exit")
        self.assertTrue(alfa["h20"]["realized"])
        self.assertAlmostEqual(alfa["h20"]["candidate_after_cost_net_return"], 0.0975)

        beta = result["candidate_outcomes"][1]
        self.assertEqual(beta["ticker"], "BETA")
        self.assertTrue(all(
            item["outcome"] == "cash_unfilled" for item in (beta["h5"], beta["h10"], beta["h20"])
        ))
        self.assertFalse(result["boundary"]["evaluation_mark_is_production_exit"])
        self.assertFalse(result["boundary"]["evaluation_mark_changes_model_paper_ledger"])
        self.assertFalse(result["boundary"]["writes_outcome_data"])

    def test_adjustment_gate_or_incomplete_series_returns_whole_week_no_count_without_values(self):
        unevaluable = _adjustment_evidence()
        unevaluable["adjustment_mode"]["status"] = "missing"
        adjustment_blocked = self._produce(adjustment_evidence=unevaluable)
        self.assertEqual(adjustment_blocked["outcome_status"], "data_degraded_whole_week_no_count")
        self.assertEqual(adjustment_blocked["degradation_reason"], "adjustment_evidence_not_evaluable")
        self.assertEqual(adjustment_blocked["candidate_outcomes"], [])
        self.assertIsNone(adjustment_blocked["outcome_as_of"])
        self.assertIsNone(adjustment_blocked["common_price_snapshot_sha256"])

        incomplete = _bars()
        incomplete["BETA"] = incomplete["BETA"][:9]
        series_blocked = self._produce(daily_bars_by_ticker=incomplete)
        self.assertEqual(series_blocked["outcome_status"], "data_degraded_whole_week_no_count")
        self.assertEqual(series_blocked["degradation_reason"], "incomplete_price_series")
        self.assertEqual(series_blocked["candidate_outcomes"], [])

    def test_stop_priority_and_packet_validation_apply_to_every_horizon(self):
        bars = _bars()
        bars["ALFA"][0] = _bar(
            index=1, session_date=_session_dates()[0], open_=100.0, high=112.0, low=95.0, close=100.0,
        )
        result = self._produce(daily_bars_by_ticker=bars)
        alfa = result["candidate_outcomes"][0]
        for label in ("h5", "h10", "h20"):
            self.assertEqual(alfa[label]["outcome"], "model_paper_exit")
            self.assertEqual(alfa[label]["model_paper_status"], "filled_stopped")
            self.assertAlmostEqual(alfa[label]["candidate_after_cost_net_return"], -0.0525)

        tampered = copy.deepcopy(result)
        tampered["candidate_outcomes"][0]["h10"]["candidate_after_cost_net_return"] = 0.5
        with self.assertRaises(outcome.ForwardPolicyOutcomeError):
            outcome.validate_forward_policy_outcome_packet(tampered)

    def test_rejects_horizon_calendar_that_is_not_forward_of_the_capture(self):
        stale_dates = []
        value = date(2026, 6, 1)
        while len(stale_dates) < 20:
            if value.weekday() < 5:
                stale_dates.append(value.strftime("%Y%m%d"))
            value += timedelta(days=1)
        bars = _bars()
        for series in bars.values():
            for index, bar in enumerate(series):
                bar["session_date"] = stale_dates[index]
        with self.assertRaises(outcome.ForwardPolicyOutcomeError):
            self._produce(daily_bars_by_ticker=bars)

    def test_rejects_pool_order_or_capture_drift_instead_of_silently_reusing_a_policy_specific_input(self):
        extra_order = {ticker: _order() for ticker in COMMON_POOL}
        extra_order["LEAK"] = _order()
        with self.assertRaises(outcome.ForwardPolicyOutcomeError):
            self._produce(orders_by_ticker=extra_order)

        bad_capture = _capture()
        bad_capture["comparison_contract_sha256"] = "0" * 64
        with self.assertRaises(outcome.ForwardPolicyOutcomeError):
            self._produce(capture=bad_capture)


if __name__ == "__main__":
    unittest.main()
