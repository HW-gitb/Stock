# -*- coding: utf-8 -*-
"""Private persistence seam tests for the US-short A1 comparison v2 forward week."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from engine import us_short_forward_policy_order_snapshot as snapshot
from engine import us_short_forward_policy_private_week as private_week
from engine.us_short_forward_policy_heads import SELECTION_POLICY_IDS
from engine.us_short_forward_policy_statistical_plan import statistical_plan_sha256
from engine.us_short_forward_policy_effect_surface import baseline_epoch_sha256


COMMON_POOL = ["ALFA", "BETA"]
COST = {"commission_fee": 0.001, "slippage_bps": 10.0, "spread_cost": 0.0005}
AGGRESSIVE = {"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _decision() -> dict:
    return {
        "out_of_window": False, "decision_date": "20260713", "price_basis_date": "20260710",
        "run_date": "20260712", "cheap_eligible": list(COMMON_POOL), "candidates": list(COMMON_POOL),
        "recall_available": False, "recall_added": [], "recall_excluded": [], "exclusion_records": [],
        "admitted": list(COMMON_POOL), "selection_seats": {},
        "theme_selection_mode": "industry_heat_v1_cross_industry_disabled", "full_analysis_leader_upgrades": [],
        "selection_details": [], "holdings": [],
    }


def _capture() -> dict:
    return {
        "schema_name": "us_short_forward_policy_shadow_selection", "schema_version": "2.1.0",
        "decision_date": "20260713", "price_basis_date": "20260710", "generated_at": "2026-07-13T08:00:00-04:00",
        "source_context_sha256": "a" * 64, "comparison_contract_sha256": statistical_plan_sha256(), "baseline_epoch_sha256": baseline_epoch_sha256(),
        "common_selection_pool": list(COMMON_POOL), "common_selection_pool_sha256": _digest(COMMON_POOL),
        "selection_policies": list(SELECTION_POLICY_IDS),
        "selection_decisions": {policy_id: _decision() for policy_id in SELECTION_POLICY_IDS},
        "boundary": {
            "track": "comparison_non_production", "evidence_level": "shadow_selection_only",
            "shadow_counts_ship_gate": False, "full_size_ship_gate_allowed": False,
            "provider_calls_added": False, "broker_or_order_automation_allowed": False,
        },
    }


def _price_inputs() -> dict:
    return {
        "ALFA": {
            "ticker": "ALFA",
            "price_input": {"close": 100.0, "indicators": {
                "effective_support": 98.0, "effective_resistance": 110.0, "atr": 2.0,
                "support_quality": "strong", "resistance_quality": "strong",
            }},
            "sub_mode": "pullback", "defensive_breakout_probe_allowed": False, "overextension": None,
        },
        "BETA": {
            "ticker": "BETA",
            "price_input": {"close": 100.0, "indicators": {
                "effective_support": 90.0, "effective_resistance": 100.0, "atr": 2.0,
                "support_quality": "strong", "resistance_quality": "strong",
            }},
            "sub_mode": "breakout", "defensive_breakout_probe_allowed": False, "overextension": None,
        },
    }


def _order_snapshot() -> dict:
    return snapshot.produce_forward_policy_order_snapshot(
        capture=_capture(), price_basis_date="20260710", candidate_price_inputs_by_ticker=_price_inputs(),
        market_axis_regimes=dict(AGGRESSIVE), prior_regime=None, prior_upgrade_count=0,
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


def _bar(index: int, session_date: str, open_: float, high: float, low: float, close: float) -> dict:
    return {"session_index": index, "session_date": session_date, "open": open_, "high": high, "low": low, "close": close}


def _bars() -> dict:
    alfa, beta = [], []
    for index, session_date in enumerate(_session_dates(), start=1):
        if index == 1:
            alfa.append(_bar(index, session_date, 100.0, 102.0, 99.0, 101.0))
        elif index < 5:
            alfa.append(_bar(index, session_date, 102.0, 103.0, 101.0, 102.0))
        elif index == 5:
            alfa.append(_bar(index, session_date, 104.0, 105.0, 102.0, 104.0))
        elif index < 10:
            alfa.append(_bar(index, session_date, 106.0, 107.0, 103.0, 106.0))
        elif index == 10:
            alfa.append(_bar(index, session_date, 109.0, 109.5, 106.0, 109.0))
        elif index == 11:
            alfa.append(_bar(index, session_date, 109.0, 111.0, 108.0, 110.0))
        else:
            alfa.append(_bar(index, session_date, 111.0, 112.0, 110.0, 111.0))
        beta.append(_bar(index, session_date, 105.0, 106.0, 104.0, 105.0))
    return {"ALFA": alfa, "BETA": beta}


class ForwardPolicyPrivateWeekTests(unittest.TestCase):
    def _materialize(self, root: Path, **overrides) -> dict:
        kwargs = {
            "capture": _capture(), "order_snapshot": _order_snapshot(), "daily_bars_by_ticker": _bars(),
            "cost_prior": dict(COST), "adjustment_evidence": _adjustment_evidence(),
            "maturity_as_of": _session_dates()[-1], "maturity_source_packet_sha256": "c" * 64,
            "private_output_path": root / "forward_policy_outcome_20260713.json",
        }
        kwargs.update(overrides)
        return private_week.materialize_forward_policy_private_week(**kwargs)

    def test_persists_one_recomputed_common_pool_outcome_with_all_three_digest_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._materialize(Path(tmp))
            record = json.loads(Path(result["private_record_path"]).read_text(encoding="utf-8"))

        private_week.validate_forward_policy_private_week_record(record)
        self.assertEqual(result["materialization_status"], "ready_for_accumulation")
        self.assertEqual(record["capture_sha256"], _digest(_capture()))
        self.assertEqual(record["order_snapshot_packet_sha256"], _digest(_order_snapshot()))
        self.assertEqual(record["outcome_packet"]["common_order_snapshot_sha256"], _order_snapshot()["common_order_snapshot_sha256"])
        self.assertEqual(record["outcome_packet"]["common_selection_pool"], COMMON_POOL)
        self.assertEqual(record["outcome_packet"]["outcome_status"], "ready_for_comparison")
        self.assertEqual(record["maturity_observability"]["maturity_as_of"], _session_dates()[-1])
        self.assertTrue(record["boundary"]["writes_private_forward_packet"])
        self.assertFalse(record["boundary"]["writes_model_paper_ledger"])

    def test_snapshot_no_count_is_persisted_without_forward_inputs_or_an_invented_outcome(self):
        no_count = snapshot.produce_forward_policy_order_snapshot(
            capture=_capture(), price_basis_date="20260710", candidate_price_inputs_by_ticker=_price_inputs(),
            market_axis_regimes={}, prior_regime=None, prior_upgrade_count=0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = self._materialize(
                Path(tmp), order_snapshot=no_count, daily_bars_by_ticker=None, cost_prior=None, adjustment_evidence=None,
            )
            record = json.loads(Path(result["private_record_path"]).read_text(encoding="utf-8"))

        self.assertEqual(record["materialization_status"], "data_degraded_whole_week_no_count")
        self.assertEqual(record["degradation_reason"], "order_snapshot:new_entry_not_permitted")
        self.assertIsNone(record["forward_inputs"])
        self.assertIsNone(record["outcome_packet"])
        private_week.validate_forward_policy_private_week_record(record)

    def test_incomplete_or_adjustment_blocked_inputs_are_persisted_as_non_counting_private_evidence(self):
        bars = _bars()
        bars["BETA"] = bars["BETA"][:9]
        with tempfile.TemporaryDirectory() as tmp:
            result = self._materialize(Path(tmp), daily_bars_by_ticker=bars)
            record = json.loads(Path(result["private_record_path"]).read_text(encoding="utf-8"))

        self.assertEqual(result["materialization_status"], "data_degraded_whole_week_no_count")
        self.assertEqual(record["degradation_reason"], "outcome:incomplete_price_series")
        self.assertIsNotNone(record["forward_inputs"])
        self.assertEqual(record["outcome_packet"]["outcome_status"], "data_degraded_whole_week_no_count")
        private_week.validate_forward_policy_private_week_record(record)

    def test_rejects_capture_order_or_outcome_binding_drift_before_any_private_write(self):
        bad_capture = _capture()
        bad_capture["source_context_sha256"] = "c" * 64
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "forward_policy_outcome_20260713.json"
            with self.assertRaises(private_week.ForwardPolicyPrivateWeekError):
                self._materialize(Path(tmp), capture=bad_capture)
            self.assertFalse(path.exists())

        bad_snapshot = _order_snapshot()
        bad_snapshot["common_order_snapshot_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(private_week.ForwardPolicyPrivateWeekError):
                self._materialize(Path(tmp), order_snapshot=bad_snapshot)

    def test_rejects_tampered_digest_or_valid_replacement_input_with_an_old_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._materialize(Path(tmp))
            record = json.loads(Path(result["private_record_path"]).read_text(encoding="utf-8"))
        tampered = copy.deepcopy(record)
        tampered["forward_input_snapshot_sha256"] = "0" * 64
        with self.assertRaises(private_week.ForwardPolicyPrivateWeekError):
            private_week.validate_forward_policy_private_week_record(tampered)

        # This remains a valid cost object and gets a matching replacement input digest, so merely validating each
        # nested packet would accept it.  The private-week consumer must rederive the outcome and reject the stale one.
        replaced_input = copy.deepcopy(record)
        replaced_input["forward_inputs"]["cost_prior"]["commission_fee"] = 0.002
        replaced_input["forward_input_snapshot_sha256"] = _digest(replaced_input["forward_inputs"])
        with self.assertRaises(private_week.ForwardPolicyPrivateWeekError):
            private_week.validate_forward_policy_private_week_record(replaced_input)

    def test_rejects_noncanonical_in_repo_path(self):
        repo_path = private_week.ROOT / "state" / "us_short" / "shadow_compare_private" / "wrong_name.json"
        with self.assertRaises(private_week.ForwardPolicyPrivateWeekError):
            self._materialize(repo_path.parent, private_output_path=repo_path)


if __name__ == "__main__":
    unittest.main()
