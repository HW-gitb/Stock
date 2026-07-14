"""Adversarial tests for the A-short 4.3 manual-tables -> account_state converter.

Matrix (pre-Codex checklist A: defect class x exit; C: reverse-failure; F: determinism / anti-coercion):
  parsing / anti Excel-coercion, account-level gates, positions, Rule13 progression (incl. reverse:
  the date gate is not bypassed by confirmations; manual_block only tightens), Rule12 auto-progression,
  facts/decision as_of, determinism + row-order independence, and the existing-validator integration.
"""
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
from runners.a_short_weekly_pipeline import validate_account_state  # noqa: E402

AS_OF = "20260615"
EXAMPLE_DIR = ROOT / "schemas" / "examples" / "a_short_account_state_csv"


def _tables():
    """Fresh deep copy of a valid base table set (csv.DictReader-shaped: str cells)."""
    return copy.deepcopy({
        "account": [{
            "as_of": "20260615", "available_cash": "500000", "total_equity": "1200000",
            "current_gross_exposure": "300000", "manual_order_only": "TRUE",
            "broker_connection_allowed": "FALSE",
        }],
        "positions": [{
            "ts_code": "600000.SH", "name": "浦发银行", "shares": "1000", "avg_cost": "9.80",
            "entry_date": "20260601", "stop_loss": "9.20", "take_profit_1": "10.50",
            "take_profit_2": "", "last_exit_date": "", "last_exit_reason": "", "manual_notes": "",
        }],
        "trades": [
            {"trade_date": "20260601", "ts_code": "600000.SH", "name": "浦发银行", "side": "BUY",
             "shares": "1000", "price": "9.80", "reason": "entry", "order_manual": "TRUE", "notes": ""},
            {"trade_date": "20260615", "ts_code": "600519.SH", "name": "贵州茅台", "side": "SELL",
             "shares": "100", "price": "1620.00", "reason": "stop_loss", "order_manual": "TRUE", "notes": ""},
            {"trade_date": "20260605", "ts_code": "601318.SH", "name": "中国平安", "side": "SELL",
             "shares": "500", "price": "48.50", "reason": "stop_loss", "order_manual": "TRUE", "notes": ""},
        ],
        "manual_controls": [{
            "ts_code": "601318.SH", "new_catalyst_confirmed": "FALSE", "m4_recheck_passed": "FALSE",
            "max_reentry_position_pct": "0.5", "override_status": "", "override_reason": "",
        }],
        "portfolio_rule12": [{
            "status": "recovery_1", "reason": "组合熔断恢复期", "triggered_at": "20260610",
            "cooldown_until": "20260612", "recovery_position_multiplier": "0.5",
            "consecutive_stop_losses_window": "3", "drawdown_pct": "0.12", "iv_change_abs_1d_pctpt": "",
        }],
    })


def _r13(acc):
    return {c["ts_code"]: c for c in acc["rule13_cooldowns"]}


class HappyPathTests(unittest.TestCase):
    def test_build_happy_path_structure(self):
        acc, ln = conv.build_account_state(_tables(), AS_OF)
        self.assertEqual(acc["as_of"], AS_OF)
        self.assertEqual(acc["available_cash"], 500000.0)
        self.assertEqual(acc["manual_order_only"], True)
        self.assertEqual(acc["broker_connection_allowed"], False)
        self.assertEqual([p["ts_code"] for p in acc["positions"]], ["600000.SH"])
        self.assertEqual(acc["rule12"]["status"], "recovery_1")
        self.assertEqual(acc["rule12"]["recovery_position_multiplier"], 0.5)
        r13 = _r13(acc)
        self.assertEqual(r13["600519.SH"]["status"], "active_cooldown")     # 刚止损(今天)
        self.assertEqual(r13["600519.SH"]["cooldown_until"], "20260616")    # +1 日历日
        self.assertEqual(r13["601318.SH"]["status"], "pending_recheck")     # 过期未复核
        self.assertEqual(ln["facts_staleness"], "current")

    def test_output_passes_existing_validator(self):
        acc, _ = conv.build_account_state(_tables(), AS_OF)
        self.assertEqual(validate_account_state(acc, AS_OF), acc)

    def test_blank_stop_loss_optional_v110(self):
        # S3a:stop_loss 降可选(系统算止损)→ 空白合法、不再 FATAL;输出 schema_version 1.1.0、stop_loss None、过 validator。
        tables = _tables()
        tables["positions"][0]["stop_loss"] = ""
        acc, _ = conv.build_account_state(tables, AS_OF)
        self.assertEqual(acc["schema_version"], "1.1.0")
        self.assertIsNone(acc["positions"][0]["stop_loss"])
        self.assertEqual(validate_account_state(acc, AS_OF), acc)

    def test_filled_stop_loss_kept_as_manual_ref_v110(self):
        # 填了 stop 仍保留(降为手填参考),不报错;输出 1.1.0。
        acc, _ = conv.build_account_state(_tables(), AS_OF)
        self.assertEqual(acc["schema_version"], "1.1.0")
        self.assertEqual(acc["positions"][0]["stop_loss"], 9.20)

    def test_no_active_cooldown_is_left_expired(self):
        # defense-in-depth invariant: converter never emits an expired active_cooldown
        acc, _ = conv.build_account_state(_tables(), AS_OF)
        for cd in acc["rule13_cooldowns"]:
            if cd["status"] == "active_cooldown":
                self.assertGreaterEqual(cd["cooldown_until"], AS_OF)
        if acc["rule12"]["status"] == "active_cooldown":
            self.assertGreaterEqual(acc["rule12"]["cooldown_until"], AS_OF)

    def test_example_csv_dir_converts_and_validates(self):
        tables = {name: conv._read_csv_table(EXAMPLE_DIR / f"{name}.csv", name)
                  for name in conv.REQUIRED_TABLES + conv.OPTIONAL_TABLES}
        acc, ln = conv.build_account_state(tables, AS_OF, conv._load_preset_config())
        validate_account_state(acc, AS_OF)
        self.assertEqual(_r13(acc)["600519.SH"]["status"], "active_cooldown")
        self.assertEqual(_r13(acc)["601318.SH"]["status"], "pending_recheck")
        self.assertEqual(acc["rule12"]["status"], "recovery_1")


class DeterminismTests(unittest.TestCase):
    def test_byte_identical_on_repeat(self):
        a1, _ = conv.build_account_state(_tables(), AS_OF)
        a2, _ = conv.build_account_state(_tables(), AS_OF)
        self.assertEqual(json.dumps(a1, sort_keys=True), json.dumps(a2, sort_keys=True))

    def test_row_order_independence(self):
        base = _tables()
        a1, _ = conv.build_account_state(base, AS_OF)
        shuffled = _tables()
        shuffled["trades"] = list(reversed(shuffled["trades"]))
        shuffled["positions"] = list(reversed(shuffled["positions"]))
        a2, _ = conv.build_account_state(shuffled, AS_OF)
        self.assertEqual(a1, a2)


class Rule13ProgressionTests(unittest.TestCase):
    def test_active_when_within_cooldown(self):
        acc, _ = conv.build_account_state(_tables(), AS_OF)
        self.assertEqual(_r13(acc)["600519.SH"]["status"], "active_cooldown")

    def test_pending_when_expired_and_unconfirmed(self):
        acc, _ = conv.build_account_state(_tables(), AS_OF)
        self.assertEqual(_r13(acc)["601318.SH"]["status"], "pending_recheck")

    def test_cleared_when_expired_and_both_confirmed(self):
        t = _tables()
        t["manual_controls"][0].update(new_catalyst_confirmed="TRUE", m4_recheck_passed="TRUE")
        acc, ln = conv.build_account_state(t, AS_OF)
        self.assertEqual(_r13(acc)["601318.SH"]["status"], "cleared_for_reentry")
        prog = {c["ts_code"]: c["progressed"] for c in ln["rule13_cooldowns"]}
        self.assertEqual(prog["601318.SH"], {"from_status": "active_cooldown", "to_status": "cleared_for_reentry"})

    def test_reverse_date_gate_not_bypassed_by_confirmations(self):
        # 600519 stopped out TODAY -> within cooldown -> stays active even if both confirmations true
        t = _tables()
        t["manual_controls"].append({
            "ts_code": "600519.SH", "new_catalyst_confirmed": "TRUE", "m4_recheck_passed": "TRUE",
            "max_reentry_position_pct": "0.5", "override_status": "", "override_reason": "",
        })
        acc, _ = conv.build_account_state(t, AS_OF)
        self.assertEqual(_r13(acc)["600519.SH"]["status"], "active_cooldown")

    def test_held_stock_gets_no_cooldown(self):
        t = _tables()
        t["positions"].append({
            "ts_code": "601318.SH", "name": "中国平安", "shares": "500", "avg_cost": "48.0",
            "entry_date": "20260606", "stop_loss": "45.0", "take_profit_1": "", "take_profit_2": "",
            "last_exit_date": "", "last_exit_reason": "", "manual_notes": "",
        })
        acc, _ = conv.build_account_state(t, AS_OF)
        self.assertNotIn("601318.SH", _r13(acc))

    def test_latest_sell_take_profit_means_no_cooldown(self):
        t = _tables()
        # later SELL with take_profit supersedes the earlier stop_loss as the most-recent exit
        t["trades"].append({"trade_date": "20260610", "ts_code": "601318.SH", "name": "中国平安",
                            "side": "SELL", "shares": "500", "price": "52.0", "reason": "take_profit",
                            "order_manual": "TRUE", "notes": ""})
        acc, _ = conv.build_account_state(t, AS_OF)
        self.assertNotIn("601318.SH", _r13(acc))

    def test_same_day_any_stop_loss_is_conservative(self):
        t = _tables()
        t["trades"].append({"trade_date": "20260605", "ts_code": "601318.SH", "name": "中国平安",
                            "side": "SELL", "shares": "100", "price": "49.0", "reason": "take_profit",
                            "order_manual": "TRUE", "notes": "同日部分止盈"})
        acc, _ = conv.build_account_state(t, AS_OF)
        self.assertIn("601318.SH", _r13(acc))  # 同日另有 stop_loss -> 保守仍冷静

    def test_manual_block_only_tightens(self):
        t = _tables()
        t["manual_controls"][0].update(new_catalyst_confirmed="TRUE", m4_recheck_passed="TRUE",
                                       override_status="manual_block")
        acc, ln = conv.build_account_state(t, AS_OF)
        self.assertEqual(_r13(acc)["601318.SH"]["status"], "pending_recheck")  # 本应 cleared，被强制阻断
        block = {c["ts_code"]: c["manual_block_applied"] for c in ln["rule13_cooldowns"]}
        self.assertTrue(block["601318.SH"])

    def test_manual_block_on_no_cooldown_is_fatal(self):
        t = _tables()
        t["manual_controls"].append({
            "ts_code": "600036.SH", "new_catalyst_confirmed": "FALSE", "m4_recheck_passed": "FALSE",
            "max_reentry_position_pct": "", "override_status": "manual_block", "override_reason": "想拉黑",
        })
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_manual_block_on_held_is_fatal(self):
        t = _tables()
        t["manual_controls"].append({
            "ts_code": "600000.SH", "new_catalyst_confirmed": "FALSE", "m4_recheck_passed": "FALSE",
            "max_reentry_position_pct": "", "override_status": "manual_block", "override_reason": "",
        })
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_manual_allow_rejected(self):
        t = _tables()
        t["manual_controls"][0]["override_status"] = "manual_allow"
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)


class Rule12Tests(unittest.TestCase):
    def test_missing_rule12_table_fails_closed(self):
        t = _tables()
        t["portfolio_rule12"] = []
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_active_within_cooldown_stays_active(self):
        t = _tables()
        t["portfolio_rule12"][0].update(status="active_cooldown", cooldown_until="20260620",
                                        recovery_position_multiplier="")
        acc, _ = conv.build_account_state(t, AS_OF)
        self.assertEqual(acc["rule12"]["status"], "active_cooldown")

    def test_expired_active_auto_advances_to_recovery(self):
        t = _tables()
        t["portfolio_rule12"][0].update(status="active_cooldown", cooldown_until="20260612",
                                        recovery_position_multiplier="")
        acc, ln = conv.build_account_state(t, AS_OF)
        self.assertEqual(acc["rule12"]["status"], "recovery_1")
        self.assertEqual(acc["rule12"]["recovery_position_multiplier"], 0.5)  # default
        self.assertEqual(ln["rule12"]["progressed"], {"from_status": "active_cooldown", "to_status": "recovery_1"})

    def test_active_without_cooldown_until_is_fatal(self):
        t = _tables()
        t["portfolio_rule12"][0].update(status="active_cooldown", cooldown_until="")
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_invalid_status_fatal(self):
        t = _tables()
        t["portfolio_rule12"][0]["status"] = "inactive_typo"
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_more_than_one_row_fatal(self):
        t = _tables()
        t["portfolio_rule12"].append(dict(t["portfolio_rule12"][0]))
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)


class AccountGateTests(unittest.TestCase):
    def test_zero_cash_allowed_for_holding_management(self):
        t = _tables()
        t["account"][0]["available_cash"] = "0"
        acc, _ = conv.build_account_state(t, AS_OF)
        self.assertEqual(acc["available_cash"], 0.0)

    def test_manual_order_only_false_fatal(self):
        t = _tables()
        t["account"][0]["manual_order_only"] = "FALSE"
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_broker_allowed_true_fatal(self):
        t = _tables()
        t["account"][0]["broker_connection_allowed"] = "TRUE"
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_account_not_single_row_fatal(self):
        t = _tables()
        t["account"].append(dict(t["account"][0]))
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_future_facts_fatal(self):
        t = _tables()
        t["account"][0]["as_of"] = "20260616"  # > decision
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_stale_facts_warns_in_lineage(self):
        t = _tables()
        t["account"][0]["as_of"] = "20260612"  # < decision (Friday facts, Monday decision)
        acc, ln = conv.build_account_state(t, AS_OF)
        self.assertEqual(ln["facts_staleness"], "stale_warning")
        self.assertEqual(acc["as_of"], AS_OF)


class ParsingAntiCoercionTests(unittest.TestCase):
    def test_coerced_float_date_fatal(self):
        t = _tables()
        t["positions"][0]["entry_date"] = "20260601.0"
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_bool_one_fatal(self):
        t = _tables()
        t["account"][0]["manual_order_only"] = "1"
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_fractional_shares_fatal(self):
        t = _tables()
        t["positions"][0]["shares"] = "1000.0"
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_non_main_board_ts_code_fatal(self):
        t = _tables()
        t["positions"][0]["ts_code"] = "300750.SZ"  # ChiNext
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_malformed_ts_code_fatal(self):
        t = _tables()
        t["positions"][0]["ts_code"] = "60000.SH"
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_duplicate_position_fatal(self):
        t = _tables()
        t["positions"].append(dict(t["positions"][0]))
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_trade_order_manual_false_fatal(self):
        t = _tables()
        t["trades"][1]["order_manual"] = "FALSE"
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)

    def test_trade_bad_side_fatal(self):
        t = _tables()
        t["trades"][1]["side"] = "HOLD"
        with self.assertRaises(conv.ConvertError):
            conv.build_account_state(t, AS_OF)


class FileLevelTests(unittest.TestCase):
    def test_missing_required_column_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "account.csv"
            p.write_text("as_of,available_cash\n20260615,500000\n", encoding="utf-8")
            with self.assertRaises(conv.ConvertError):
                conv._read_csv_table(p, "account")

    def test_main_missing_required_file_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            # only account.csv present -> missing positions/trades/manual_controls
            (Path(d) / "account.csv").write_text(
                "as_of,available_cash,manual_order_only,broker_connection_allowed\n"
                "20260615,500000,TRUE,FALSE\n", encoding="utf-8")
            with self.assertRaises(conv.ConvertError):
                conv.main(["--input-dir", d, "--as-of", AS_OF, "--out", str(Path(d) / "o.json")])

    def test_main_end_to_end_writes_valid_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "account_state.json"
            rc = conv.main(["--input-dir", str(EXAMPLE_DIR), "--as-of", AS_OF, "--out", str(out)])
            self.assertEqual(rc, 0)
            bundle = json.loads(out.read_text(encoding="utf-8"))
            conv.validate_account_bundle(bundle, AS_OF)
            self.assertFalse(out.with_name("account_state_lineage.json").exists())
            lineage = bundle["lineage"]
            self.assertEqual({s["name"] for s in lineage["source_tables"]},
                             {"account", "positions", "trades", "manual_controls", "portfolio_rule12"})
            self.assertEqual(len(lineage["source_tables"][0]["sha256"]), 64)


class ConsistencyCheckTests(unittest.TestCase):
    """4.3-D: trades-net vs positions advisory (WARN-only; never overrides positions)."""

    def _warns(self, tables):
        return conv.build_account_state(tables, AS_OF)[1]["consistency_warnings"]

    def test_base_example_has_no_warnings(self):
        # 600000 BUY 1000 == positions 1000; 600519/601318 are stop-loss sells (not held) → no warn
        self.assertEqual(self._warns(_tables()), [])

    def test_net_buy_not_in_positions_warns(self):
        t = _tables()
        t["trades"].append({"trade_date": "20260610", "ts_code": "600036.SH", "name": "招商银行",
                            "side": "BUY", "shares": "300", "price": "38.0", "reason": "entry",
                            "order_manual": "TRUE", "notes": ""})
        w = self._warns(t)
        self.assertEqual([x["kind"] for x in w], ["net_buy_not_in_positions"])
        self.assertEqual(w[0]["ts_code"], "600036.SH")

    def test_shares_mismatch_warns_but_positions_authoritative(self):
        t = _tables()
        # extra partial SELL of the held 600000 → trades net 900 != positions 1000 (held → no Rule13 change)
        t["trades"].append({"trade_date": "20260610", "ts_code": "600000.SH", "name": "浦发银行",
                            "side": "SELL", "shares": "100", "price": "10.2", "reason": "take_profit",
                            "order_manual": "TRUE", "notes": ""})
        acc, ln = conv.build_account_state(t, AS_OF)
        self.assertIn("shares_mismatch", [x["kind"] for x in ln["consistency_warnings"]])
        # positions stays authoritative — reconcile NEVER overrides
        self.assertEqual([p for p in acc["positions"] if p["ts_code"] == "600000.SH"][0]["shares"], 1000)

    def test_position_without_trades_no_warning(self):
        t = _tables()
        t["positions"].append({"ts_code": "600036.SH", "name": "招商银行", "shares": "500", "avg_cost": "38.0",
                               "entry_date": "20260601", "stop_loss": "35.0", "take_profit_1": "",
                               "take_profit_2": "", "last_exit_date": "", "last_exit_reason": "", "manual_notes": ""})
        # 600036 held but has NO trades → not netted → no mismatch warn for it
        self.assertNotIn("600036.SH", [w["ts_code"] for w in self._warns(t)])

    def test_stop_loss_soldout_not_held_no_warning(self):
        # reverse: a SELL that left you flat (601318) is a normal exit, not a consistency warning
        self.assertNotIn("601318.SH", [w["ts_code"] for w in self._warns(_tables())])

    def test_pure_helper_direct_net_buy(self):
        warns = conv.reconcile_trades_positions(
            [{"trade_date": "20260610", "ts_code": "600036.SH", "name": "招商银行", "side": "BUY",
              "shares": "300", "price": "38.0", "reason": "entry", "order_manual": "TRUE", "notes": ""}], [])
        self.assertEqual(warns[0]["kind"], "net_buy_not_in_positions")


class ConverterOutputPrivacyGuardTests(unittest.TestCase):
    """P0(Codex Slice4):converter 写 account_state/lineage 前过私密守门,拒仓库内 git 未忽略路径(防账户隐私被提交)。"""

    def _write_csvs(self, d):
        import csv
        for name, rows in _tables().items():
            with open(Path(d) / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)

    def test_converter_rejects_tracked_repo_output_path(self):
        import tempfile
        leak = ROOT / "__converter_leak_probe__.json"   # repo 根,git 不忽略
        lin = leak.with_name(leak.stem + "_lineage.json")
        with tempfile.TemporaryDirectory() as d:
            self._write_csvs(d)
            try:
                with self.assertRaises(SystemExit):
                    conv.main(["--input-dir", d, "--as-of", "20260615", "--out", str(leak)])
            finally:
                for p in (leak, lin):
                    if p.exists():
                        p.unlink()
        self.assertFalse(leak.exists())   # guard 在写盘前 raise → 不创建

    def test_converter_allows_gitignored_private_path(self):
        import tempfile
        import shutil
        base = ROOT / "state" / "a_short" / "weekly_private" / "__probe_conv__"
        out = base / "account_state.json"
        with tempfile.TemporaryDirectory() as d:
            self._write_csvs(d)
            try:
                conv.main(["--input-dir", d, "--as-of", "20260615", "--out", str(out)])
                self.assertTrue(out.exists())
            finally:
                if base.exists():
                    shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
