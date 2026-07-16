import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from jsonschema import Draft7Validator

from runners.a_short_d4_policy_ablation import (
    LEDGER_PATH, PREREG_PATH, PREREG_SCHEMA, SUMMARY_SCHEMA, _atomic_write_json,
    _bool, _commit_spent_result, _load, build_summary,
)

RESULT_PATH = PREREG_PATH.parents[2] / "research/results/a_short_d4_policy_ablation_20260714/execution_summary.json"
RUNNER_PATH = PREREG_PATH.parents[2] / "runners/a_short_d4_policy_ablation.py"


def _row(**overrides):
    row = {
        "trade_date": "20240131", "tier": "Tier1", "hard_veto": False,
        "ret_5d_status": "ok", "ret_5d_t1_net": 2.0,
        "chasing_high": False, "overheat_flag": False, "l2_name": "industry", "esp_raw": 1.0,
    }
    row.update(overrides)
    return row


class D4PolicyAblationTests(unittest.TestCase):
    def test_numeric_hard_veto_is_parsed_like_rule6(self):
        self.assertEqual(_bool(pd.Series([1.0, 0.0, "true", "false"])).tolist(),
                         [True, False, True, False])

    def test_spend_is_committed_before_result_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            result = Path(tmp) / "result.json"
            calls = []

            def writer(path, value):
                calls.append(path)
                if path == result:
                    raise OSError("simulated result publish failure")

            with patch("runners.a_short_d4_policy_ablation._atomic_write_json", side_effect=writer):
                with self.assertRaises(OSError):
                    _commit_spent_result(summary={"result": True}, ledger={"spent": True},
                                         out_path=result, ledger_path=ledger)
            self.assertEqual(calls, [ledger, result])

    def test_atomic_json_write_replaces_without_temp_residue(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.json"
            path.write_text('{"old": true}\n', encoding="utf-8")
            _atomic_write_json(path, {"new": True})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"new": True})
            self.assertFalse(list(Path(tmp).glob(".result.json.*.tmp")))

    def test_preregistration_schema_is_frozen(self):
        prereg = _load(PREREG_PATH)
        self.assertEqual(list(Draft7Validator(_load(PREREG_SCHEMA)).iter_errors(prereg)), [])

    def test_spent_result_is_explicitly_posthoc_and_reviewer_trust_only(self):
        summary = _load(RESULT_PATH)
        ledger = _load(LEDGER_PATH)
        self.assertEqual(summary["schema_version"], "1.1.0")
        self.assertEqual(summary["input_integrity"]["binding_status"], "posthoc_recorded_unverified")
        self.assertEqual(list(Draft7Validator(_load(SUMMARY_SCHEMA)).iter_errors(summary)), [])
        evidence = " ".join([
            *ledger["singleton_scope"]["applies_to"],
            ledger["budget_policy"]["spend_rule"],
            ledger["test_spend_log"][0]["result_summary"],
        ]).lower()
        self.assertIn("post-hoc", evidence)
        self.assertIn("reviewer-trust-only", evidence)
        self.assertNotIn("source-hash-bound", evidence)
        self.assertNotIn("source-hash-bound", RUNNER_PATH.read_text(encoding="utf-8").lower())

    def test_all_heads_are_emitted_and_crash_is_not_backfilled(self):
        rows = [
            _row(trade_date="20240131", ret_5d_t1_net=2.0),
            _row(trade_date="20240229", chasing_high=True, ret_5d_t1_net=-5.0),
            _row(trade_date="20240329", overheat_flag=True, ret_5d_t1_net=-3.0),
            _row(trade_date="20240430", l2_name="未知", ret_5d_t1_net=-4.0),
            _row(trade_date="20240531", esp_raw=0.0, ret_5d_t1_net=-2.0),
            _row(trade_date="20240628", tier="Tier2", ret_5d_t1_net=1.0),
            _row(trade_date="20240731", hard_veto=True, ret_5d_t1_net=99.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            samples = Path(tmp) / "rank_samples.csv"
            pd.DataFrame(rows).to_csv(samples, index=False)
            summary = build_summary(samples_path=samples, prereg=_load(PREREG_PATH),
                                    generated_at="2026-07-14T18:30:00+08:00")
        self.assertEqual(len(summary["population_views"]), 4)
        self.assertEqual(len(summary["policy_comparison"]), 2)
        self.assertEqual(len(summary["rule6_ablation"]), 8)
        self.assertEqual(summary["crash_window_comparison"]["status"], "not_available")
        self.assertFalse(summary["decision"]["rule_deletion_allowed"])
        self.assertEqual(list(Draft7Validator(_load(SUMMARY_SCHEMA)).iter_errors(summary)), [])

    def test_crash_summary_requires_two_frozen_cohorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            samples = Path(tmp) / "rank_samples.csv"
            pd.DataFrame([_row(), _row(trade_date="20240229")]).to_csv(samples, index=False)
            crash = Path(tmp) / "crash.json"
            crash.write_text(json.dumps({"variants": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_summary(samples_path=samples, prereg=_load(PREREG_PATH),
                              generated_at="2026-07-14T18:30:00+08:00", crash_summary_path=crash)


if __name__ == "__main__":
    unittest.main()
