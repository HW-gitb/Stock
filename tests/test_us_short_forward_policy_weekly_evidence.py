# -*- coding: utf-8 -*-
"""Projection tests from one validated private forward week to six-head H10 comparison evidence."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from engine import us_short_forward_policy_order_snapshot as snapshot
from engine import us_short_forward_policy_private_week as private_week
from engine import us_short_forward_policy_weekly_evidence as weekly_evidence
from engine.us_short_forward_policy_heads import SELECTION_POLICY_IDS
from engine.us_short_forward_policy_statistical_plan import statistical_plan_sha256
from engine.us_short_forward_policy_effect_surface import baseline_epoch_sha256


POOL = [f"T{index:02d}" for index in range(16)]
BALANCED = POOL[:15]
THEME_PLUS = BALANCED[:-1] + [POOL[-1]]
COST = {"commission_fee": 0.001, "slippage_bps": 10.0, "spread_cost": 0.0005}
AGGRESSIVE = {"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _decision(admitted: list[str]) -> dict:
    return {
        "out_of_window": False, "decision_date": "20260713", "price_basis_date": "20260710",
        "run_date": "20260712", "cheap_eligible": list(POOL), "candidates": list(POOL),
        "recall_available": False, "recall_added": [], "recall_excluded": [], "exclusion_records": [],
        "admitted": list(admitted), "selection_seats": {},
        "theme_selection_mode": "industry_heat_v1_cross_industry_disabled", "full_analysis_leader_upgrades": [],
        "selection_details": [], "holdings": [],
    }


def _capture(*, selected_count: int = 15) -> dict:
    balanced = POOL[:selected_count]
    theme_plus = balanced[:-1] + [POOL[-1]] if selected_count == 15 else list(balanced)
    selections = {policy_id: list(balanced) for policy_id in SELECTION_POLICY_IDS}
    selections["theme_plus"] = theme_plus
    return {
        "schema_name": "us_short_forward_policy_shadow_selection", "schema_version": "2.1.0",
        "decision_date": "20260713", "price_basis_date": "20260710", "generated_at": "2026-07-13T08:00:00-04:00",
        "source_context_sha256": "a" * 64, "comparison_contract_sha256": statistical_plan_sha256(), "baseline_epoch_sha256": baseline_epoch_sha256(),
        "common_selection_pool": list(POOL), "common_selection_pool_sha256": _digest(POOL),
        "selection_policies": list(SELECTION_POLICY_IDS),
        "selection_decisions": {policy_id: _decision(selections[policy_id]) for policy_id in SELECTION_POLICY_IDS},
        "boundary": {
            "track": "comparison_non_production", "evidence_level": "shadow_selection_only",
            "shadow_counts_ship_gate": False, "full_size_ship_gate_allowed": False,
            "provider_calls_added": False, "broker_or_order_automation_allowed": False,
        },
    }


def _price_inputs() -> dict:
    return {
        ticker: {
            "ticker": ticker,
            "price_input": {"close": 100.0, "indicators": {
                "effective_support": 98.0, "effective_resistance": 110.0, "atr": 2.0,
                "support_quality": "strong", "resistance_quality": "strong",
            }},
            "sub_mode": "pullback", "defensive_breakout_probe_allowed": False, "overextension": None,
        }
        for ticker in POOL
    }


def _order_snapshot(capture: dict, *, no_count: bool = False) -> dict:
    return snapshot.produce_forward_policy_order_snapshot(
        capture=capture, price_basis_date="20260710", candidate_price_inputs_by_ticker=_price_inputs(),
        market_axis_regimes={} if no_count else dict(AGGRESSIVE), prior_regime=None, prior_upgrade_count=0,
    )


def _adjustment_evidence() -> dict:
    return {
        "schema_name": "us_short_paper_eval_adjustment_evidence", "schema_version": "1.0.0",
        "decision_date": "20260713", "source_refs": [{
            "id": "fixture_price_basis", "path": "state/us_short/private/fixture_price_basis.json", "sha256": "b" * 64,
        }],
        "adjustment_mode": {"status": "confirmed", "mode": "split_dividend_adjusted", "source_ref_ids": ["fixture_price_basis"]},
        "split_handling": {"status": "no_events", "source_ref_ids": ["fixture_price_basis"], "event_refs": []},
        "dividend_handling": {"status": "no_events", "source_ref_ids": ["fixture_price_basis"], "event_refs": []},
        "ex_date_price_consistency": {
            "status": "not_applicable_no_events", "source_ref_ids": ["fixture_price_basis"], "checked_event_ids": [],
        },
        "scope": {
            "offline_detection_only": True, "provider_call_performed": False,
            "corporate_action_reconciliation_claimed": False, "ship_gate_or_production_authorized": False,
        },
    }


def _session_dates() -> list[str]:
    current, dates = date(2026, 7, 13), []
    while len(dates) < 20:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


def _bars() -> dict:
    output = {}
    for ticker in POOL:
        bars = []
        for index, session_date in enumerate(_session_dates(), start=1):
            close = 103.0 if ticker == POOL[-1] and index == 10 else 100.0
            bars.append({
                "session_index": index, "session_date": session_date,
                "open": 100.0, "high": max(101.0, close), "low": 99.0, "close": close,
            })
        output[ticker] = bars
    return output


def _private_record(*, selected_count: int = 15, no_count: bool = False, incomplete: bool = False) -> dict:
    capture = _capture(selected_count=selected_count)
    bars = _bars()
    if incomplete:
        bars[POOL[-1]] = bars[POOL[-1]][:9]
    with tempfile.TemporaryDirectory() as tmp:
        result = private_week.materialize_forward_policy_private_week(
            capture=capture, order_snapshot=_order_snapshot(capture, no_count=no_count),
            daily_bars_by_ticker=None if no_count else bars,
            cost_prior=None if no_count else dict(COST),
            adjustment_evidence=None if no_count else _adjustment_evidence(),
            maturity_as_of=_session_dates()[-1],
            maturity_source_packet_sha256="c" * 64,
            private_output_path=Path(tmp) / "forward_policy_outcome_20260713.json",
        )
        return json.loads(Path(result["private_record_path"]).read_text(encoding="utf-8"))


class ForwardPolicyWeeklyEvidenceTests(unittest.TestCase):
    def test_projects_one_validated_private_week_to_the_preregistered_h10_policy_deltas(self):
        record = _private_record()
        result = weekly_evidence.build_forward_policy_h10_weekly_evidence(record)

        weekly_evidence.validate_forward_policy_h10_weekly_evidence(result)
        self.assertEqual(result["projection_status"], "ready_for_private_accumulation")
        self.assertEqual(result["h10_session_date"], _session_dates()[9])
        self.assertEqual(result["outcome_available_as_of"], _session_dates()[19])
        self.assertEqual(set(result["candidate_after_cost_net_return"]), set(POOL))
        self.assertEqual(result["factor_questions"]["theme_weight_choice"], list(SELECTION_POLICY_IDS[:4]))
        self.assertAlmostEqual(result["policy_minus_balanced"]["theme_plus"], 0.03 / 15.0)
        self.assertEqual(result["policy_minus_balanced"]["catalyst_off"], 0.0)
        self.assertFalse(result["boundary"]["produces_forward_evidence"])
        self.assertFalse(result["boundary"]["issues_formal_recommendation"])
        self.assertFalse(result["boundary"]["evaluation_mark_is_production_exit"])
        self.assertFalse(result["boundary"]["evaluation_mark_changes_model_paper_ledger"])

    def test_outcome_stage_no_count_keeps_only_a_real_prior_order_digest_not_h10_values(self):
        result = weekly_evidence.build_forward_policy_h10_weekly_evidence(_private_record(incomplete=True))

        self.assertEqual(result["projection_status"], "data_degraded_whole_week_no_count")
        self.assertEqual(result["degradation_reason"], "outcome:incomplete_price_series")
        self.assertEqual(len(result["common_order_snapshot_sha256"]), 64)
        self.assertIsNone(result["common_price_snapshot_sha256"])
        self.assertIsNone(result["candidate_after_cost_net_return"])
        weekly_evidence.validate_forward_policy_h10_weekly_evidence(result)

    def test_carries_an_explicit_non_counting_projection_without_inventing_h10_values(self):
        result = weekly_evidence.build_forward_policy_h10_weekly_evidence(_private_record(no_count=True))

        self.assertEqual(result["projection_status"], "data_degraded_whole_week_no_count")
        self.assertEqual(result["degradation_reason"], "order_snapshot:new_entry_not_permitted")
        self.assertIsNone(result["h10_session_date"])
        self.assertIsNone(result["candidate_after_cost_net_return"])
        self.assertIsNone(result["policy_h10_after_cost_net_return"])
        weekly_evidence.validate_forward_policy_h10_weekly_evidence(result)

    def test_rejects_private_record_tamper_and_a_ready_week_without_the_frozen_top15_denominator(self):
        record = _private_record()
        record["outcome_packet"]["candidate_outcomes"][0]["h10"]["candidate_after_cost_net_return"] = 0.5
        with self.assertRaises(weekly_evidence.ForwardPolicyWeeklyEvidenceError):
            weekly_evidence.build_forward_policy_h10_weekly_evidence(record)

        with self.assertRaises(weekly_evidence.ForwardPolicyWeeklyEvidenceError):
            weekly_evidence.build_forward_policy_h10_weekly_evidence(_private_record(selected_count=14))

    def test_rejects_tampered_projected_delta_or_false_forward_evidence_flag(self):
        result = weekly_evidence.build_forward_policy_h10_weekly_evidence(_private_record())
        result["policy_minus_balanced"]["theme_plus"] = 0.0
        with self.assertRaises(weekly_evidence.ForwardPolicyWeeklyEvidenceError):
            weekly_evidence.validate_forward_policy_h10_weekly_evidence(result)

        result = weekly_evidence.build_forward_policy_h10_weekly_evidence(_private_record())
        result["policy_selections"]["theme_plus"] = list(BALANCED)
        result["policy_h10_after_cost_net_return"]["theme_plus"] = result["policy_h10_after_cost_net_return"]["balanced"]
        result["policy_minus_balanced"]["theme_plus"] = 0.0
        with self.assertRaises(weekly_evidence.ForwardPolicyWeeklyEvidenceError):
            weekly_evidence.validate_forward_policy_h10_weekly_evidence(result)

        result = weekly_evidence.build_forward_policy_h10_weekly_evidence(_private_record())
        result["common_selection_pool"] = list(reversed(POOL))
        with self.assertRaises(weekly_evidence.ForwardPolicyWeeklyEvidenceError):
            weekly_evidence.validate_forward_policy_h10_weekly_evidence(result)

        result = weekly_evidence.build_forward_policy_h10_weekly_evidence(_private_record())
        result["candidate_after_cost_net_return"][POOL[-1]] = 0.0
        result["policy_h10_after_cost_net_return"]["theme_plus"] -= 0.03 / 15.0
        result["policy_minus_balanced"]["theme_plus"] -= 0.03 / 15.0
        with self.assertRaises(weekly_evidence.ForwardPolicyWeeklyEvidenceError):
            weekly_evidence.validate_forward_policy_h10_weekly_evidence(result)

        result = weekly_evidence.build_forward_policy_h10_weekly_evidence(_private_record())
        result["h10_session_date"] = _session_dates()[10]
        with self.assertRaises(weekly_evidence.ForwardPolicyWeeklyEvidenceError):
            weekly_evidence.validate_forward_policy_h10_weekly_evidence(result)

        result = weekly_evidence.build_forward_policy_h10_weekly_evidence(_private_record())
        result["boundary"]["produces_forward_evidence"] = True
        with self.assertRaises(weekly_evidence.ForwardPolicyWeeklyEvidenceError):
            weekly_evidence.validate_forward_policy_h10_weekly_evidence(result)

        result = weekly_evidence.build_forward_policy_h10_weekly_evidence(_private_record())
        result["boundary"]["evaluation_mark_is_production_exit"] = True
        with self.assertRaises(weekly_evidence.ForwardPolicyWeeklyEvidenceError):
            weekly_evidence.validate_forward_policy_h10_weekly_evidence(result)


if __name__ == "__main__":
    unittest.main()
