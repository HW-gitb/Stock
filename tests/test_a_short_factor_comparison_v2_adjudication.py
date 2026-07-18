"""Knife-2 private-ledger adjudication contracts and boundary regressions."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_factor_comparison_v2 import (  # noqa: E402
    ComparisonV2Error, _digest, _load_experiment_batches, load_v2_governance,
)
from engine.a_short_factor_comparison_v2_adjudication import (  # noqa: E402
    _cross_epoch_summary, _risk_gate, adjudicate_v2_from_private_ledger, decide_v2_receipt,
    request_v2_question_reactivation, _simultaneous_winner, _combination_scheduler,
    _register_combination_batch,
)


def _root(tmp: str) -> Path:
    return Path(tmp) / "state" / "a_short" / "factor_comparison_private" / "v2"


def _risk(*, max_drawdown: float = 10.0) -> dict:
    return {
        "max_drawdown_pct": max_drawdown, "bad_name_rate": 0.10, "tail_loss_pct": -5.0,
        "loss_distribution_basis": "filled_positions_only", "loss_distribution_count": 2,
        "cash_drag_pct": 20.0, "unfilled_rate": 0.20, "fill_rate": 0.80, "turnover_pct": 100.0,
        "total_cost_pct": 0.16, "max_name_weight_pct": 50.0, "adjustment_coverage_pct": 100.0,
    }


def _week_dates(count: int) -> list[str]:
    current = date(2026, 1, 2)
    return [(current + timedelta(days=index * 7)).strftime("%Y%m%d") for index in range(count)]


def _arm_capture(arm_id: str, *, changed: bool) -> dict:
    return {
        "arm_definition": {"arm_id": arm_id}, "arm_definition_sha256": _digest({"arm_id": arm_id}),
        "selected_symbols": ["600000.SH"] if not changed else ["600001.SH"],
        "decisions": [{"ts_code": "600000.SH" if not changed else "600001.SH", "selected": True,
                       "plan": {"entry": 10.0 if not changed else 9.9}}],
    }


def _arm_outcome(arm_id: str, *, net_return: float, risk: dict, exit_date: str) -> dict:
    return {"arm_id": arm_id, "outcome": {"horizons": {"h10": {"status": "settled", "exit_date": exit_date,
                                                                     "net_return_pct": net_return}},
                                                "risk_evidence": copy.deepcopy(risk)}}


def _outcome_payload_digest(payload: dict) -> str:
    return _digest({key: value for key, value in payload.items() if key != "outcome_sha256"})


def _write_fixture(root: Path, *, effects: dict[str, list[float]], states: list[str] | None = None,
                   epochs: list[str] | None = None, risks: dict[str, dict] | None = None) -> None:
    governance = load_v2_governance()
    dates = _week_dates(len(next(iter(effects.values()))))
    states = states or ["状态A" if index % 2 == 0 else "状态B" for index in range(len(dates))]
    epochs = epochs or ["epoch-111111111111"] * len(dates)
    risks = risks or {arm_id: _risk() for arm_id in effects}
    entries = []
    questions = {row["question_id"]: row for row in governance["questions"]}
    for index, decision_date in enumerate(dates):
        day = root / "weeks" / decision_date
        day.mkdir(parents=True, exist_ok=True)
        capture_sha, outcome_sha = f"{index + 1:064x}", f"{index + 101:064x}"
        d1_arms = [_arm_capture("baseline", changed=False)] + [
            _arm_capture(arm_id, changed=True) for arm_id in questions["d1_entry_anchor"]["ordered_arm_ids"]
            if arm_id != "baseline"
        ]
        exit_date = (datetime.strptime(decision_date, "%Y%m%d").date() + timedelta(days=10)).strftime("%Y%m%d")
        d1_outcomes = [_arm_outcome("baseline", net_return=0.0, risk=_risk(), exit_date=exit_date)] + [
            _arm_outcome(arm_id, net_return=effects.get(arm_id, [0.0] * len(dates))[index],
                         risk=risks.get(arm_id, _risk()), exit_date=exit_date)
            for arm_id in questions["d1_entry_anchor"]["ordered_arm_ids"] if arm_id != "baseline"
        ]
        capture = {"payload": {"capture_sha256": capture_sha,
                                 "candidate_universe": [{"market_regime": states[index]}],
                                 "questions": [{"question_id": "d1_entry_anchor",
                                                "experiment_batch_id": questions["d1_entry_anchor"]["experiment_batch_id"],
                                                "arms": d1_arms}]}}
        outcome_payload = {"questions": [{"question_id": "d1_entry_anchor", "status": "settled", "arms": d1_outcomes}]}
        outcome_payload["outcome_sha256"] = _outcome_payload_digest(outcome_payload)
        outcome = {"schema_name": "a_short_factor_comparison_v2_weekly", "schema_version": "2.0.0",
                   "record_type": "outcome", "program_id": "a_short_factor_comparison_v2",
                   "decision_date": decision_date, "epoch_id": epochs[index],
                   "payload": outcome_payload,
                   "boundary": {"production": False, "automatic_policy_switch": False,
                                "historical_replay_counts_as_forward": False, "provider_calls_during_settlement": False}}
        (day / "capture.json").write_text(json.dumps(capture), encoding="utf-8")
        (day / "outcome.json").write_text(json.dumps(outcome), encoding="utf-8")
        (day / "source_receipt.json").write_text("{}", encoding="utf-8")
        entries.append({"decision_date": decision_date, "question_id": "d1_entry_anchor",
                        "experiment_batch_id": questions["d1_entry_anchor"]["experiment_batch_id"], "epoch_id": epochs[index],
                        "forward_eligible": True, "outcome_status": "settled", "capture_sha256": capture_sha,
                        "outcome_sha256": outcome_payload["outcome_sha256"]})
    ledger = {"schema_name": "a_short_factor_comparison_v2_ledger", "schema_version": "2.0.0",
              "program_id": "a_short_factor_comparison_v2", "stage": "capture_only", "entries": entries,
              "boundary": {"production": False, "automatic_policy_switch": False,
                           "historical_replay_counts_as_forward": False, "provider_calls_during_settlement": False}}
    root.mkdir(parents=True, exist_ok=True)
    (root / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")


class AdjudicationTests(unittest.TestCase):
    def _adjudicate(self, root: Path, *, require_evidence: bool = True) -> dict:
        with mock.patch("engine.a_short_factor_comparison_v2_adjudication._validate_source_receipt") as source_gate:
            result = adjudicate_v2_from_private_ledger(root=root)
        if require_evidence:
            self.assertGreater(source_gate.call_count, 0)
        return result

    def test_12_weeks_is_preliminary_and_cannot_emit_a_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _write_fixture(root, effects={"entry_ma_pullback": [0.8] * 12, "entry_range_pullback": [0.1] * 12})
            result = self._adjudicate(root)
            question = result["adjudication"]["questions"][0]
            self.assertEqual(question["status"], "preliminary_review_due")
            self.assertEqual(question["recommendations"], [])
            self.assertFalse((root / "reminder.json").read_text(encoding="utf-8").count("receipt_sha256"))

    def test_24_week_unique_qualified_arm_emits_human_gated_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _write_fixture(root, effects={"entry_ma_pullback": [0.8] * 24, "entry_range_pullback": [0.1] * 24})
            result = self._adjudicate(root)
            question = result["adjudication"]["questions"][0]
            self.assertEqual(question["status"], "recommend_adopt_arm")
            self.assertEqual(question["recommendations"][0]["arm_id"], "entry_ma_pullback")
            receipts = json.loads((root / "decision_receipts.json").read_text(encoding="utf-8"))
            self.assertEqual(len(receipts["receipts"]), 1)
            self.assertEqual(receipts["receipts"][0]["receipt"]["status"], "pending")
            self.assertTrue(result["production_unchanged"])

    def test_tampered_outcome_payload_with_stale_hash_cannot_be_adjudicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            mutations = {
                "net_return_pct": lambda arm: arm["outcome"]["horizons"]["h10"].update({"net_return_pct": 9.9}),
                "max_drawdown_pct": lambda arm: arm["outcome"]["risk_evidence"].update({"max_drawdown_pct": 0.0}),
                "exit_date": lambda arm: arm["outcome"]["horizons"]["h10"].update({"exit_date": "20260102"}),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    root = _root(str(Path(tmp) / name))
                    _write_fixture(root, effects={"entry_ma_pullback": [0.8] * 24,
                                                  "entry_range_pullback": [0.1] * 24})
                    outcome_path = root / "weeks" / _week_dates(24)[0] / "outcome.json"
                    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
                    stale_hash = outcome["payload"]["outcome_sha256"]
                    mutate(outcome["payload"]["questions"][0]["arms"][1])
                    self.assertEqual(outcome["payload"]["outcome_sha256"], stale_hash)
                    outcome_path.write_text(json.dumps(outcome), encoding="utf-8")
                    with self.assertRaises(ComparisonV2Error):
                        self._adjudicate(root)

    def test_lone_challenger_requires_confidence_lower_bound_to_clear_economic_margin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            effects = [0.55, 0.55, 0.03, 0.03] * 6
            states = ["state_a", "state_a", "state_b", "state_b"] * 6
            _write_fixture(root, effects={"entry_ma_pullback": effects, "entry_range_pullback": [0.1] * 24},
                           states=states)
            question = self._adjudicate(root)["adjudication"]["questions"][0]
            arm = next(row for row in question["arm_verdicts"] if row["arm_id"] == "entry_ma_pullback")
            self.assertGreaterEqual(arm["nonoverlap_mean_paired_net_excess_pct"], 0.25)
            self.assertGreater(arm["paired_bootstrap_ci"]["lower_pct"], 0.0)
            self.assertLess(arm["paired_bootstrap_ci"]["lower_pct"], 0.25)
            self.assertFalse(arm["eligible_for_adopt"])
            self.assertEqual(question["status"], "inconclusive")

            at_margin_root = _root(str(Path(tmp) / "at_margin"))
            _write_fixture(at_margin_root, effects={"entry_ma_pullback": [0.25] * 24,
                                                    "entry_range_pullback": [0.1] * 24})
            at_margin = self._adjudicate(at_margin_root)["adjudication"]["questions"][0]
            at_margin_arm = next(row for row in at_margin["arm_verdicts"] if row["arm_id"] == "entry_ma_pullback")
            self.assertAlmostEqual(at_margin_arm["paired_bootstrap_ci"]["lower_pct"], 0.25)
            self.assertTrue(at_margin_arm["eligible_for_adopt"])

    def test_multiple_qualified_arms_need_simultaneous_economic_superiority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _write_fixture(root, effects={"entry_ma_pullback": [0.80] * 24, "entry_range_pullback": [0.75] * 24})
            question = self._adjudicate(root)["adjudication"]["questions"][0]
            self.assertEqual(question["status"], "inconclusive")
            self.assertEqual(question["recommendations"], [])
            self.assertTrue(question["finalist_comparisons"])

    def test_36_weeks_distinguishes_retain_from_persistent_harm(self):
        with tempfile.TemporaryDirectory() as tmp:
            retain_root = _root(str(Path(tmp) / "retain"))
            _write_fixture(retain_root, effects={"entry_ma_pullback": [0.10] * 36, "entry_range_pullback": [0.10] * 36})
            self.assertEqual(self._adjudicate(retain_root)["adjudication"]["questions"][0]["status"],
                             "recommend_retain_baseline")

            discard_root = _root(str(Path(tmp) / "discard"))
            bad_risk = _risk(max_drawdown=20.0)
            _write_fixture(discard_root, effects={"entry_ma_pullback": [-0.8] * 36, "entry_range_pullback": [0.1] * 36},
                           risks={"entry_ma_pullback": bad_risk, "entry_range_pullback": _risk()})
            discarded = self._adjudicate(discard_root)["adjudication"]["questions"][0]
            self.assertEqual(discarded["status"], "recommend_discard_arm")
            self.assertEqual(discarded["recommendations"][0]["arm_id"], "entry_ma_pullback")

    def test_every_risk_metric_and_no_count_gate_can_block_adoption(self):
        contract = load_v2_governance()["adjudication_contract"]
        base_row = {"risk_evidence": _risk(), "baseline_risk_evidence": _risk()}
        self.assertTrue(_risk_gate([base_row], no_count_rate=0.0, contract=contract)["passed"])
        mutations = {
            "max_drawdown_pct": 15.01, "bad_name_rate": 0.351, "tail_loss_pct": -10.01,
            "loss_distribution_count": 0, "cash_drag_pct": 50.01, "unfilled_rate": 0.501,
            "fill_rate": 0.499, "turnover_pct": 100.01, "total_cost_pct": 0.161,
            "max_name_weight_pct": 50.01, "adjustment_coverage_pct": 99.99,
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                row = copy.deepcopy(base_row)
                row["risk_evidence"][field] = value
                self.assertFalse(_risk_gate([row], no_count_rate=0.0, contract=contract)["passed"])
        bad_basis = copy.deepcopy(base_row)
        bad_basis["risk_evidence"]["loss_distribution_basis"] = "all_selected"
        self.assertFalse(_risk_gate([bad_basis], no_count_rate=0.0, contract=contract)["passed"])
        self.assertFalse(_risk_gate([base_row], no_count_rate=0.201, contract=contract)["passed"])

    def test_cross_epoch_uses_random_effects_and_blocks_direction_conflict(self):
        contract = load_v2_governance()["adjudication_contract"]
        blocks = ([{"epoch_id": "epoch-111111111111", "effect_pct": 0.8} for _ in range(4)] +
                  [{"epoch_id": "epoch-222222222222", "effect_pct": -0.8} for _ in range(4)])
        summary = _cross_epoch_summary(blocks, current_epoch_id="epoch-222222222222", contract=contract)
        self.assertEqual(summary["method"], "random_effects_reml_hartung_knapp")
        self.assertTrue(summary["direction_conflict"])
        self.assertTrue(summary["current_epoch_harm"])

    def test_current_epoch_needs_its_own_minimum_blocks_before_adoption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            epochs = ["epoch-111111111111"] * 21 + ["epoch-222222222222"] * 3
            _write_fixture(root, effects={"entry_ma_pullback": [0.8] * 24,
                                          "entry_range_pullback": [0.1] * 24}, epochs=epochs)
            question = self._adjudicate(root)["adjudication"]["questions"][0]
            arm = next(row for row in question["arm_verdicts"] if row["arm_id"] == "entry_ma_pullback")
            self.assertFalse(arm["cross_epoch"]["current_epoch_qualified"])
            self.assertFalse(arm["eligible_for_adopt"])
            self.assertNotEqual(question["status"], "recommend_adopt_arm")

    def test_epoch_transition_rebuilds_statistical_summary_without_reusing_old_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            epochs = ["epoch-111111111111"] * 12 + ["epoch-222222222222"] * 12
            _write_fixture(root, effects={"entry_ma_pullback": [0.8] * 24,
                                          "entry_range_pullback": [0.1] * 24}, epochs=epochs)
            ledger_path = root / "ledger.json"
            full_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            first_epoch = copy.deepcopy(full_ledger)
            first_epoch["entries"] = first_epoch["entries"][:12]
            ledger_path.write_text(json.dumps(first_epoch), encoding="utf-8")
            self._adjudicate(root)
            ledger_path.write_text(json.dumps(full_ledger), encoding="utf-8")
            result = self._adjudicate(root)
            arm = next(row for row in result["adjudication"]["questions"][0]["arm_verdicts"]
                       if row["arm_id"] == "entry_ma_pullback")
            self.assertEqual(arm["cross_epoch"]["method"], "random_effects_reml_hartung_knapp")

    def test_simultaneous_winner_requires_a_full_common_block_sample(self):
        contract = dict(load_v2_governance()["adjudication_contract"])
        contender = [{"decision_date": f"20260{index + 1:03d}", "evaluation_exit_date": f"20260{index + 1:03d}",
                      "effect_pct": 0.8} for index in range(12)]
        opponent = [{"decision_date": "2026001", "evaluation_exit_date": "2026001", "effect_pct": 0.1}]
        winner, details = _simultaneous_winner(["entry_ma_pullback", "entry_range_pullback"],
                                                {"entry_ma_pullback": contender,
                                                 "entry_range_pullback": opponent}, checkpoint=24,
                                                contract=contract)
        self.assertIsNone(winner)
        self.assertFalse(details["entry_ma_pullback"]["entry_range_pullback"]["passed"])

    def test_stale_receipt_cannot_be_used_to_stop_a_current_reminder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _write_fixture(root, effects={"entry_ma_pullback": [0.8] * 36, "entry_range_pullback": [0.1] * 36})
            ledger_path = root / "ledger.json"
            full_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            initial_ledger = copy.deepcopy(full_ledger)
            initial_ledger["entries"] = initial_ledger["entries"][:24]
            ledger_path.write_text(json.dumps(initial_ledger), encoding="utf-8")
            self._adjudicate(root)
            receipts = json.loads((root / "decision_receipts.json").read_text(encoding="utf-8"))
            stale_receipt_sha = receipts["receipts"][0]["receipt_sha256"]
            ledger_path.write_text(json.dumps(full_ledger), encoding="utf-8")
            current = self._adjudicate(root)
            current_receipt_sha = current["adjudication"]["questions"][0]["recommendations"][0]["receipt_sha256"]
            self.assertNotEqual(stale_receipt_sha, current_receipt_sha)
            reminder = json.loads((root / "reminder.json").read_text(encoding="utf-8"))
            self.assertEqual([row["receipt_sha256"] for row in reminder["reminders"]], [current_receipt_sha])
            with mock.patch("engine.a_short_factor_comparison_v2_adjudication._validate_source_receipt"):
                with self.assertRaises(ComparisonV2Error):
                    decide_v2_receipt(root=root, receipt_sha256=stale_receipt_sha, decision="accepted")
                recorded = decide_v2_receipt(root=root, receipt_sha256=current_receipt_sha, decision="accepted")
            self.assertEqual(recorded["status"], "receipt_recorded")
            with mock.patch("engine.a_short_factor_comparison_v2_adjudication._validate_source_receipt"):
                with self.assertRaises(ComparisonV2Error):
                    decide_v2_receipt(root=root, receipt_sha256=current_receipt_sha, decision="rejected")

    def test_dormant_question_can_only_queue_a_new_forward_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            alternating = [-0.8 if index % 2 == 0 else 0.8 for index in range(36)]
            _write_fixture(root, effects={"entry_ma_pullback": alternating,
                                          "entry_range_pullback": [0.1] * 36})
            ledger_path = root / "ledger.json"
            full_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            initial_ledger = copy.deepcopy(full_ledger)
            initial_ledger["entries"] = initial_ledger["entries"][:24]
            ledger_path.write_text(json.dumps(initial_ledger), encoding="utf-8")
            self.assertEqual(self._adjudicate(root)["adjudication"]["questions"][0]["status"], "inconclusive")
            ledger_path.write_text(json.dumps(full_ledger), encoding="utf-8")
            result = self._adjudicate(root)
            question = result["adjudication"]["questions"][0]
            self.assertEqual(question["status"], "dormant_inconclusive")
            recorded = request_v2_question_reactivation(
                root=root, question_id="d1_entry_anchor", reason="new independent forward batch",
            )
            self.assertEqual(recorded["status"], "reactivation_recorded_new_forward_batch_required")
            stored = json.loads((root / "adjudication.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["queue"]["queued_question_ids"], ["d1_entry_anchor"])
            self.assertTrue(stored["reactivation_requests"][0]["historical_backfill_forbidden"])
            batches = json.loads((root / "experiment_batches.json").read_text(encoding="utf-8"))
            batch = batches["questions"][0]
            self.assertEqual(batch["active_experiment_batch_id"], recorded["experiment_batch_id"])
            self.assertNotEqual(batch["active_experiment_batch_id"], "batch_20260718_d1_entry_anchor")
            restarted = self._adjudicate(root, require_evidence=False)["adjudication"]["questions"][0]
            self.assertEqual(restarted["experiment_batch_id"], recorded["experiment_batch_id"])
            self.assertEqual(restarted["effective_difference_weeks"], 0)

    def test_receipt_decision_rejects_a_drifted_adjudication_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _write_fixture(root, effects={"entry_ma_pullback": [0.8] * 24, "entry_range_pullback": [0.1] * 24})
            self._adjudicate(root)
            receipts = json.loads((root / "decision_receipts.json").read_text(encoding="utf-8"))
            stored_path = root / "adjudication.json"
            stored = json.loads(stored_path.read_text(encoding="utf-8"))
            stored["comparison_contract_sha256"] = "0" * 64
            stored_path.write_text(json.dumps(stored), encoding="utf-8")
            with self.assertRaises(ComparisonV2Error):
                decide_v2_receipt(root=root, receipt_sha256=receipts["receipts"][0]["receipt_sha256"],
                                  decision="accepted")

    def test_combination_acceptance_creates_a_new_forward_only_batch_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            root.mkdir(parents=True)
            governance = load_v2_governance()
            contract_sha = _digest({"test": "combination"})
            adjudication = {
                "comparison_contract_sha256": contract_sha,
                "questions": [
                    {"question_id": "d1_entry_anchor", "status": "recommend_adopt_arm"},
                    {"question_id": "d3_iv_policy", "status": "recommend_adopt_arm"},
                ],
            }
            receipts = {"receipts": [
                {"receipt_sha256": "1" * 64, "receipt": {"question_id": "d1_entry_anchor", "arm_id": "entry_ma_pullback", "status": "accepted"}},
                {"receipt_sha256": "2" * 64, "receipt": {"question_id": "d3_iv_policy", "arm_id": "iv_step_down", "status": "accepted"}},
            ]}
            batches = _load_experiment_batches(root, governance)
            _register_combination_batch(adjudication, receipts, batches)
            scheduler = _combination_scheduler(adjudication, receipts, batches)
            self.assertTrue(scheduler["new_forward_batch_required"])
            self.assertTrue(scheduler["pre_registered_combination_question_required"])
            self.assertIsNotNone(scheduler["combination_experiment_batch_id"])
            record = batches["combination_batches"][0]
            self.assertTrue(record["historical_backfill_forbidden"])


if __name__ == "__main__":
    unittest.main()
