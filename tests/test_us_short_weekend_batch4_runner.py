# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from runners import us_short_weekend_batch4 as runner
from tests.test_us_short_weekend_orchestrator import (
    _cal, _now, _pipeline_context, _register,
)

ROOT = Path(__file__).resolve().parents[1]


def _packet(base: Path, *, with_register=True):
    runs_root = base / "runs_private"
    weekly_root = base / "weekly_private"
    reg_path = base / "lifecycle" / "lifecycle_register.json"
    if with_register:
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(_register()), encoding="utf-8")
    cal_path = base / "calendar.json"
    cal_path.write_text(json.dumps(_cal()), encoding="utf-8")
    pc = _pipeline_context(reg_path, runs_root, weekly_root)
    pc.pop("prior_runs_private_root")  # runner derives the internal history root from its output root by default
    sizing_per_ticker = pc.pop("sizing_context")["per_ticker"]
    pc.pop("available_cash")
    pc.pop("account_state")  # runner consumes the private account_state_path, then injects account_state internally
    pc.pop("eligibility_governance")
    pc.pop("calendar")
    account_path = base / "account_state.json"
    account_path.write_text(json.dumps({
        "schema_name": "us_short_account_state", "schema_version": "1.0.0", "as_of": "20260615",
        "us_market_equity": 30000.0, "us_short_bucket_capital": 10000.0,
        "us_short_available_cash": 4000.0, "positions": [],
        "holding_action_reconciliation": {
            "schema_name": "us_short_holding_action_reconciliation", "schema_version": "1.0.0",
            "as_of": "20260615", "positions": []},
        "symbol_cooldown_reconciliation": {
            "schema_name": "us_short_symbol_cooldown_reconciliation", "schema_version": "1.0.0",
            "as_of": "20260615", "events": []},
        "manual_order_only": True, "broker_connection_allowed": False,
    }), encoding="utf-8")
    packet = {
        **pc,
        "eligibility_governance_path": str(ROOT / "presets" / "us_short_eligibility_governance_20260624.json"),
        "calendar_path": str(cal_path),
        "account_state_path": str(account_path),
        "sizing_per_ticker": sizing_per_ticker,
        "lifecycle_register_path": str(reg_path),
        "lifecycle_readiness_out_path": None,
        "runs_private_root": str(runs_root),
        "weekly_private_root": str(weekly_root),
    }
    packet_path = base / "packet.json"
    packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
    return packet_path, reg_path, runs_root, weekly_root


class RunnerTests(unittest.TestCase):
    def test_dry_run_executes_without_persistent_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            packet, _, runs_root, weekly_root = _packet(Path(d))
            summary = runner.run_packet(packet, now_et=_now("20260613", 10, 0), dry_run=True)
            self.assertTrue(summary["emitted"])
            self.assertTrue(summary["dry_run"])
            self.assertFalse(runs_root.exists())
            self.assertFalse(weekly_root.exists())
            self.assertNotIn("selection", summary)
            self.assertNotIn("machine_record", summary)

    def test_out_of_window_no_emit_and_no_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            packet, _, runs_root, weekly_root = _packet(Path(d))
            summary = runner.run_packet(packet, now_et=_now("20260615", 11, 0))
            self.assertFalse(summary["emitted"])
            self.assertEqual(summary["no_emit_reason"], "out_of_window")
            self.assertFalse(runs_root.exists())
            self.assertFalse(weekly_root.exists())

    def test_missing_lifecycle_register_blocks_without_bootstrap(self):
        with tempfile.TemporaryDirectory() as d:
            packet, reg_path, _, _ = _packet(Path(d), with_register=False)
            with self.assertRaises(runner.Batch4RunnerError):
                runner.run_packet(packet, now_et=_now("20260613", 10, 0))
            self.assertFalse(reg_path.exists())

    def test_lifecycle_bootstrap_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            packet, reg_path, _, _ = _packet(Path(d), with_register=False)
            first = runner.run_packet(packet, now_et=_now("20260613", 10, 0),
                                      bootstrap_lifecycle=True, dry_run=True)
            before = reg_path.read_bytes()
            second = runner.run_packet(packet, now_et=_now("20260613", 10, 0),
                                       bootstrap_lifecycle=True, dry_run=True)
            self.assertTrue(first["emitted"] and second["emitted"])
            self.assertEqual(reg_path.read_bytes(), before)

    def test_live_mode_remains_gated(self):
        with tempfile.TemporaryDirectory() as d:
            packet, _, _, _ = _packet(Path(d))
            with self.assertRaises(Exception):
                runner.run_packet(packet, now_et=_now("20260613", 10, 0), run_mode="live")

    def test_unknown_packet_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            packet, _, _, _ = _packet(Path(d))
            payload = json.loads(packet.read_text(encoding="utf-8"))
            payload["EXTRA"] = True
            packet.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(runner.Batch4RunnerError):
                runner.run_packet(packet, now_et=_now("20260613", 10, 0))

    def test_account_holdings_must_match_data_context(self):
        with tempfile.TemporaryDirectory() as d:
            packet, _, _, _ = _packet(Path(d))
            payload = json.loads(packet.read_text(encoding="utf-8"))
            account_path = Path(payload["account_state_path"])
            account = json.loads(account_path.read_text(encoding="utf-8"))
            account["positions"] = [{"ticker": "AAPL", "direction": "long", "shares": 1,
                                     "avg_cost_usd": 100.0, "entry_date": "20260601"}]
            account_path.write_text(json.dumps(account), encoding="utf-8")
            with self.assertRaises(runner.Batch4RunnerError):
                runner.run_packet(packet, now_et=_now("20260613", 10, 0))

    def test_nonprivate_output_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            packet, _, _, _ = _packet(Path(d))
            payload = json.loads(packet.read_text(encoding="utf-8"))
            payload["runs_private_root"] = str(ROOT / "docs" / "_batch4_runner_probe")
            packet.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(Exception):
                runner.run_packet(packet, now_et=_now("20260613", 10, 0))
            self.assertFalse((ROOT / "docs" / "_batch4_runner_probe").exists())

    def test_selected_prior_must_belong_to_history_root(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            packet, _, _, _ = _packet(Path(d))
            prior = Path(outside) / "20260601"
            prior.mkdir()
            (prior / "machine_record.json").write_text("{}", encoding="utf-8")
            payload = json.loads(packet.read_text(encoding="utf-8"))
            payload["prior_run_dir"] = str(prior)
            packet.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(runner.Batch4RunnerError):
                runner.run_packet(packet, now_et=_now("20260613", 10, 0))


if __name__ == "__main__":
    unittest.main()
