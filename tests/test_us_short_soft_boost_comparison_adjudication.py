"""§4c fixed-look ON/OFF adjudication is bounded, source-bound, and never production-changing."""
import json
import tempfile
import unittest
from pathlib import Path

from engine import us_short_soft_boost_comparison_adjudication as adjudication


def _digest(index: int) -> str:
    return f"{index:064x}"


def _records(count: int, *, on_return: float, off_return: float):
    records = []
    for index in range(count):
        records.append({
            "decision_date": f"2026{(index // 28) + 1:02d}{(index % 28) + 1:02d}",
            "consumption_receipt_sha256": _digest(index + 1), "shadow_receipt_sha256": _digest(index + 101),
            "maturity_receipt_sha256": _digest(index + 201), "market_risk_regime": "risk_on" if index < count // 2 else "risk_off",
            "divergent": True, "matured": True, "eligible": True, "non_overlap_h10_block": True,
            "on_net_return": on_return, "off_net_return": off_return,
            "on_max_drawdown": 0.05, "off_max_drawdown": 0.05,
            "on_bad_pick_rate": 0.10, "off_bad_pick_rate": 0.10,
            "on_tail_loss": 0.02, "off_tail_loss": 0.02,
            "on_turnover": 0.10, "off_turnover": 0.10,
            "on_fill_fraction": 0.90, "off_fill_fraction": 0.90,
        })
    return records


class SoftBoostComparisonAdjudicationTests(unittest.TestCase):
    def test_twelve_weeks_are_preliminary_not_a_formal_look(self):
        result = adjudication.evaluate_pairwise_ledger(adjudication.build_pairwise_ledger(_records(12, on_return=0.03, off_return=0.0)))
        self.assertEqual((result["status"], result["formal_look"], result["recommendation"]),
                         ("continue_accumulation", None, "continue_accumulating"))

    def test_fixed_24_and_36_looks_recommend_on_only_with_symmetric_gate(self):
        at_24 = adjudication.evaluate_pairwise_ledger(adjudication.build_pairwise_ledger(_records(24, on_return=0.03, off_return=0.0)))
        at_36 = adjudication.evaluate_pairwise_ledger(adjudication.build_pairwise_ledger(_records(36, on_return=0.03, off_return=0.0)))
        self.assertEqual((at_24["formal_look"], at_24["recommendation"]), (24, "continue_on"))
        self.assertEqual((at_36["formal_look"], at_36["recommendation"]), (36, "continue_on"))
        self.assertIn("permutation_pvalue", at_24["on"])

    def test_symmetric_reverse_direction_can_only_recommend_switch_off(self):
        result = adjudication.evaluate_pairwise_ledger(adjudication.build_pairwise_ledger(_records(24, on_return=0.0, off_return=0.03)))
        self.assertEqual(result["recommendation"], "recommend_switch_off")
        self.assertTrue(result["off"]["passed"])

    def test_insignificant_difference_is_inconclusive_not_reverse_evidence(self):
        result = adjudication.evaluate_pairwise_ledger(adjudication.build_pairwise_ledger(_records(24, on_return=0.0, off_return=0.0)))
        self.assertEqual(result["recommendation"], "insufficient_evidence")
        self.assertFalse(result["on"]["passed"])
        self.assertFalse(result["off"]["passed"])

    def test_accept_reject_defer_receipts_never_change_production_or_route_automatically(self):
        ledger = adjudication.build_pairwise_ledger(_records(24, on_return=0.0, off_return=0.03))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            path.write_text(json.dumps(ledger), encoding="utf-8")
            for decision in ("accept", "reject", "defer"):
                receipt = adjudication.build_adjudication_receipt(path, decision_date=ledger["latest_decision_date"], user_decision=decision)
                self.assertEqual(receipt["recommendation"], "recommend_switch_off")
                self.assertFalse(receipt["automatic_replacement_allowed"])
                self.assertFalse(receipt["production_flag"])

    def test_dying_control_wrong_plan_digest_fails_closed(self):
        ledger = adjudication.build_pairwise_ledger(_records(24, on_return=0.03, off_return=0.0))
        ledger["comparison_statistical_plan_sha256"] = "0" * 64
        with self.assertRaises(adjudication.SoftBoostComparisonAdjudicationError):
            adjudication.evaluate_pairwise_ledger(ledger)

    def test_maturity_observation_requires_a_prior_bound_capture_and_cannot_backfill(self):
        capture = adjudication.build_pairwise_capture(
            decision_date="20260102", consumption_receipt_sha256=_digest(1),
            shadow_receipt_sha256=_digest(101), divergent=True,
        )
        ledger = adjudication.append_pairwise_capture(None, capture)
        observation = {
            "decision_date": "20260102", "consumption_receipt_sha256": _digest(1),
            "shadow_receipt_sha256": _digest(101), "maturity_receipt_sha256": _digest(201),
            "market_risk_regime": "risk_on", "eligible": True, "non_overlap_h10_block": True,
            "on_net_return": 0.03, "off_net_return": 0.0,
            "on_max_drawdown": 0.05, "off_max_drawdown": 0.05,
            "on_bad_pick_rate": 0.10, "off_bad_pick_rate": 0.10,
            "on_tail_loss": 0.02, "off_tail_loss": 0.02,
            "on_turnover": 0.10, "off_turnover": 0.10,
            "on_fill_fraction": 0.90, "off_fill_fraction": 0.90,
        }
        matured = adjudication.apply_maturity_observations(ledger, [observation], maturity_as_of="20260103")
        self.assertEqual((matured["matured_week_count"], matured["eligible_divergence_week_count"]), (1, 1))
        with self.assertRaises(adjudication.SoftBoostComparisonAdjudicationError):
            adjudication.apply_maturity_observations(matured, [observation], maturity_as_of="20260104")
        observation["consumption_receipt_sha256"] = _digest(2)
        with self.assertRaises(adjudication.SoftBoostComparisonAdjudicationError):
            adjudication.apply_maturity_observations(ledger, [observation], maturity_as_of="20260103")


if __name__ == "__main__":
    unittest.main()
