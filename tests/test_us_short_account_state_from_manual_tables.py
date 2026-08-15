# -*- coding: utf-8 -*-
"""Converter tests for US-short manual tables -> us_short_account_state (batch 1, slice 1a).

Adversarial by design (the time-saver is fewer FAIL->修复 rounds): Excel coercion, future dates,
A-share-code rejection, dedup, bucket = equity/3, fail-closed privacy guard, and a main() end-to-end.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runners.us_short_account_state_from_manual_tables as conv  # noqa: E402

CE = conv.ConvertError


def _acct(**o):
    base = {"as_of": "20260622", "us_market_equity": "30000", "us_short_available_cash": "4000",
            "portfolio_total_equity": "90000", "manual_order_only": "TRUE", "broker_connection_allowed": "FALSE"}
    base.update(o)
    return base


def _pos(**o):
    base = {"ticker": "AAPL", "shares": "10", "avg_cost_usd": "180", "entry_date": "20260601",
            "current_stop": "165", "notes": "x"}
    base.update(o)
    return base


def _tables(account=None, positions=None):
    return {"account": [account if account is not None else _acct()],
            "positions": positions if positions is not None else [_pos()]}


def _build(account=None, positions=None, as_of="20260622", expected_facts_as_of=None):
    expected = as_of if expected_facts_as_of is None else expected_facts_as_of
    return conv.build_account_state(_tables(account, positions), as_of, expected)


_GOOD_ACCOUNT_CSV = (
    "as_of,us_market_equity,us_short_available_cash,portfolio_total_equity,manual_order_only,broker_connection_allowed\n"
    "20260622,30000,4000,90000,TRUE,FALSE\n")


def _trade(**o):
    base = {"decision_date": "20260601", "ticker": "AAPL", "suggested_action": "建仓",
            "executed": "TRUE", "fill_price": "180", "fill_shares": "10",
            "skip_reason": "", "manual_override": ""}
    base.update(o)
    return base


def _holding_theme(ticker="AAPL", **o):
    base = {
        "as_of": "20260622", "ticker": ticker, "theme_id": "industry:technology",
        "theme_source": "industry_heat_v1", "theme_lifecycle_state": "confirmed_active",
        "macro_cluster": "ai_complex", "evidence_ref_kind": "source_id",
        "evidence_ref_value": "manual:theme:" + ticker,
    }
    base.update(o)
    return base


def _reconcile(trades, positions=None, as_of="20260622"):
    if positions is None:
        positions = conv._build_positions([_pos()], "20260622")   # default AAPL 10 long
    return conv.reconcile_trades_positions(trades, positions, as_of)


class BuildTests(unittest.TestCase):
    def test_older_serialized_state_cannot_be_used_as_target_date_state(self):
        state, _ = _build(as_of="20260622")

        with self.assertRaisesRegex(CE, "20260622 != run --as-of 20260723"):
            conv.validate_account_state(state, "20260723")

    def test_happy_build_validates(self):
        state, lineage = _build()
        conv.validate_account_state(state, "20260622")   # must not raise
        self.assertEqual(state["schema_name"], "us_short_account_state")
        self.assertEqual(state["us_short_bucket_capital"], 10000.0)
        self.assertEqual(state["positions"][0]["direction"], "long")
        self.assertEqual(lineage["bucket_basis"]["divisor"], 3)
        self.assertEqual(lineage["facts_staleness"], "current")

    def test_bucket_is_equity_over_three(self):
        # small equity -> small bucket; keep cash <= bucket (the cash-ceiling invariant)
        state, _ = _build(account=_acct(us_market_equity="1000", us_short_available_cash="100"))
        self.assertAlmostEqual(state["us_short_bucket_capital"], 1000 / 3, places=9)
        conv.validate_account_state(state, "20260622")   # cross-field bucket==equity/3 holds

    def test_positions_sorted_and_all_long(self):
        state, _ = _build(positions=[_pos(ticker="MSFT"), _pos(ticker="AAPL")])
        self.assertEqual([p["ticker"] for p in state["positions"]], ["AAPL", "MSFT"])
        self.assertTrue(all(p["direction"] == "long" for p in state["positions"]))

    def test_holding_action_reconciliation_starts_uncompleted(self):
        state, _ = _build()
        item = state["holding_action_reconciliation"]["positions"][0]
        self.assertEqual(item["remaining_shares"], 10)
        self.assertFalse(item["tp1_completed"])
        self.assertIsNone(item["tp1_completed_at"])

    def test_optional_holding_themes_builds_exact_private_reconciliation(self):
        state, _ = conv.build_account_state(
            {**_tables(), "holding_themes": [_holding_theme()]}, "20260622", "20260622")
        conv.validate_account_state(state, "20260622")
        item = state["holding_theme_reconciliation"]["positions"][0]
        self.assertEqual(item["ticker"], "AAPL")
        self.assertEqual(item["theme_source"], "industry_heat_v1")
        self.assertEqual(item["macro_cluster"], "ai_complex")
        self.assertEqual(item["evidence_ref"]["as_of"], "20260622")

    def test_provided_holding_themes_must_cover_positions_and_use_governed_source(self):
        with self.assertRaises(CE):
            conv.build_account_state(
                {**_tables(positions=[_pos(ticker="AAPL"), _pos(ticker="MSFT")]),
                 "holding_themes": [_holding_theme("AAPL")]}, "20260622", "20260622")
        with self.assertRaises(CE):
            conv.build_account_state(
                {**_tables(), "holding_themes": [_holding_theme(theme_source="gics_guessed")]},
                "20260622", "20260622")

    def test_only_executed_manual_reduce_completes_tp1(self):
        state, _ = conv.build_account_state(
            {**_tables(), "trades": [_trade(suggested_action="减仓", executed="TRUE", fill_shares="3")]},
            "20260622", "20260622")
        item = state["holding_action_reconciliation"]["positions"][0]
        self.assertTrue(item["tp1_completed"])
        self.assertEqual(item["tp1_completed_at"], "20260601")

    def test_duplicate_ticker_fatal(self):
        with self.assertRaises(CE):
            _build(positions=[_pos(), _pos()])

    def test_a_share_code_rejected(self):
        with self.assertRaises(CE) as cm:
            _build(positions=[_pos(ticker="000001.SZ")])
        self.assertIn("A-share", str(cm.exception))

    def test_unicode_folding_ticker_rejected(self):
        # single identity policy: a non-ASCII ticker that .upper() would fold into a fake symbol ('ſ'->'S') must be
        # rejected — consistent with the shared engine canonical_us_ticker, no divergent second policy
        # (R-USSHORT-PROVISIONAL-THEME-IDENTITY-AND-CLOCK-VALIDATION-GAP ripple).
        for bad in ("ſ", "ß", "ı"):
            with self.assertRaises(CE):
                _build(positions=[_pos(ticker=bad)])

    def test_lowercase_ticker_normalized(self):
        state, _ = _build(positions=[_pos(ticker="aapl")])
        self.assertEqual(state["positions"][0]["ticker"], "AAPL")

    def test_class_share_ticker_ok(self):
        state, _ = _build(positions=[_pos(ticker="BRK.B")])
        self.assertEqual(state["positions"][0]["ticker"], "BRK.B")

    def test_shares_float_rejected(self):
        with self.assertRaises(CE):
            _build(positions=[_pos(shares="10.0")])

    def test_share_count_above_manual_ceiling_rejected(self):
        with self.assertRaises(CE):
            _build(positions=[_pos(shares=str(conv.MAX_MANUAL_HOLDING_SHARES + 1))])

    def test_date_coercion_rejected(self):
        with self.assertRaises(CE):
            _build(positions=[_pos(entry_date="20260601.0")])
        with self.assertRaises(CE):
            _build(positions=[_pos(entry_date="2026-06-01")])

    def test_bool_coercion_rejected(self):
        with self.assertRaises(CE):
            _build(account=_acct(manual_order_only="1"))

    def test_future_entry_rejected(self):
        with self.assertRaises(CE):
            _build(positions=[_pos(entry_date="20260701")], as_of="20260622")

    def test_future_facts_rejected(self):
        with self.assertRaises(CE):
            _build(account=_acct(as_of="20260701"), as_of="20260622")

    def test_stale_facts_warning(self):
        _, lineage = _build(account=_acct(as_of="20260601"), as_of="20260622")
        self.assertEqual(lineage["facts_staleness"], "stale_warning")

    def test_monday_decision_uses_latest_settled_facts_clock(self):
        state, lineage = _build(
            account=_acct(as_of="20260814"), as_of="20260817", expected_facts_as_of="20260814")
        self.assertEqual(lineage["expected_facts_as_of"], "20260814")
        self.assertEqual(lineage["facts_staleness"], "current")
        conv.validate_account_state(state, "20260817")

    def test_expected_facts_clock_is_fail_closed(self):
        with self.assertRaisesRegex(CE, "price-basis-date"):
            _build(as_of="20260817", expected_facts_as_of="20260818")
        with self.assertRaisesRegex(CE, "account.as_of"):
            _build(account=_acct(as_of="20260815"), as_of="20260817", expected_facts_as_of="20260814")
        with self.assertRaises(CE):
            _build(as_of="20260817", expected_facts_as_of="2026-08-14")

    def test_account_must_be_one_row(self):
        with self.assertRaises(CE):
            conv.build_account_state({"account": [], "positions": [_pos()]}, "20260622", "20260622")
        with self.assertRaises(CE):
            conv.build_account_state(
                {"account": [_acct(), _acct()], "positions": [_pos()]}, "20260622", "20260622")

    def test_manual_order_only_false_fatal(self):
        with self.assertRaises(CE):
            _build(account=_acct(manual_order_only="FALSE"))

    def test_broker_connection_true_fatal(self):
        with self.assertRaises(CE):
            _build(account=_acct(broker_connection_allowed="TRUE"))

    def test_cash_zero_ok(self):
        state, _ = _build(account=_acct(us_short_available_cash="0"))
        self.assertEqual(state["us_short_available_cash"], 0.0)
        conv.validate_account_state(state, "20260622")

    def test_cash_negative_fatal(self):
        with self.assertRaises(CE):
            _build(account=_acct(us_short_available_cash="-100"))

    def test_cash_exceeds_bucket_fatal(self):
        # equity 30000 -> bucket 10000; cash 50000 > bucket must be rejected (per-market capital policy)
        with self.assertRaises(CE):
            _build(account=_acct(us_short_available_cash="50000"))

    def test_cash_equals_bucket_ok(self):
        state, _ = _build(account=_acct(us_short_available_cash="10000"))   # cash == bucket boundary
        self.assertEqual(state["us_short_available_cash"], 10000.0)
        conv.validate_account_state(state, "20260622")

    def test_positions_extra_direction_column_rejected(self):
        # a user trying to record a short via direction=short must FAIL, not be silently emitted as long
        with self.assertRaises(CE) as cm:
            _build(positions=[_pos(direction="short")])
        self.assertIn("direction", str(cm.exception))

    def test_account_extra_unknown_column_rejected(self):
        with self.assertRaises(CE):
            _build(account=_acct(unexpected_account_flag="x"))

    def test_pure_path_extra_key_rejected(self):
        # the pure build path must not bypass the CSV column gate
        with self.assertRaises(CE):
            conv.build_account_state(
                {"account": [_acct()], "positions": [_pos(foo="bar")]}, "20260622", "20260622")

    def test_optional_empty_fields_become_null(self):
        state, _ = _build(positions=[_pos(current_stop="", notes="")])
        self.assertIsNone(state["positions"][0]["current_stop"])
        self.assertIsNone(state["positions"][0]["notes"])

    def test_no_positions_ok(self):
        state, _ = _build(positions=[])
        self.assertEqual(state["positions"], [])
        conv.validate_account_state(state, "20260622")

    def test_determinism(self):
        a, _ = _build(positions=[_pos(ticker="MSFT"), _pos(ticker="AAPL")])
        b, _ = _build(positions=[_pos(ticker="AAPL"), _pos(ticker="MSFT")])
        self.assertEqual(a["positions"], b["positions"])


class ValidateTests(unittest.TestCase):
    def test_bucket_mismatch_rejected(self):
        state, _ = _build()
        state["us_short_bucket_capital"] = 9999.0
        with self.assertRaises(CE):
            conv.validate_account_state(state, "20260622")

    def test_as_of_mismatch_rejected(self):
        state, _ = _build()
        with self.assertRaisesRegex(CE, r"re-create.*--as-of 20260101"):
            conv.validate_account_state(state, "20260101")

    def test_short_direction_in_state_rejected(self):
        state, _ = _build()
        state["positions"][0]["direction"] = "short"
        with self.assertRaises(CE):
            conv.validate_account_state(state, "20260622")

    def test_duplicate_ticker_in_state_rejected(self):
        state, _ = _build()
        p = dict(state["positions"][0])
        state["positions"].append(p)
        with self.assertRaises(CE):
            conv.validate_account_state(state, "20260622")

    def test_future_entry_date_rejected_by_validator(self):
        # validator is the single source of truth -> must reject a hand-edited future entry date,
        # not only the CSV builder
        state, _ = _build()
        state["positions"][0]["entry_date"] = "20260701"   # > as_of 20260622
        with self.assertRaises(CE):
            conv.validate_account_state(state, "20260622")

    def test_impossible_entry_date_rejected_by_validator(self):
        state, _ = _build()
        state["positions"][0]["entry_date"] = "20260631"   # June 31 is not a real date
        with self.assertRaises(CE):
            conv.validate_account_state(state, "20260622")

    def test_impossible_as_of_rejected_by_validator(self):
        state, _ = _build()
        state["as_of"] = "20260631"
        with self.assertRaises(CE):
            conv.validate_account_state(state, "20260631")

    def test_cash_exceeds_bucket_rejected_by_validator(self):
        state, _ = _build()
        state["us_short_available_cash"] = state["us_short_bucket_capital"] + 1.0
        with self.assertRaises(CE):
            conv.validate_account_state(state, "20260622")

    def test_future_tp1_completion_rejected_by_validator(self):
        state, _ = _build()
        item = state["holding_action_reconciliation"]["positions"][0]
        item["tp1_completed"] = True
        item["tp1_completed_at"] = "20260623"
        with self.assertRaises(CE):
            conv.validate_account_state(state, "20260622")


class ReconcileTests(unittest.TestCase):
    def test_consistent_no_warnings(self):
        self.assertEqual(_reconcile([_trade()]), [])            # AAPL 建仓 10 vs positions AAPL 10

    def test_net_buy_not_in_positions(self):
        w = _reconcile([_trade(ticker="TSLA")])                 # TSLA bought, not in positions
        self.assertEqual([x["kind"] for x in w], ["net_buy_not_in_positions"])

    def test_shares_mismatch(self):
        w = _reconcile([_trade(fill_shares="7")])               # AAPL net 7 vs positions 10
        self.assertEqual([x["kind"] for x in w], ["shares_mismatch"])

    def test_sell_reduces_net(self):
        w = _reconcile([_trade(), _trade(suggested_action="减仓", fill_shares="3")])   # net 10-3=7 vs 10
        self.assertEqual([x["kind"] for x in w], ["shares_mismatch"])

    def test_skipped_trade_not_counted(self):
        w = _reconcile([_trade(executed="FALSE", fill_price="", fill_shares="", skip_reason="价位超带")])
        self.assertEqual(w, [])                                 # non-executed -> not in net -> no mismatch

    def test_invalid_action_rejected(self):
        with self.assertRaises(CE):
            _reconcile([_trade(suggested_action="buy")])        # not the §9 vocab

    def test_executed_nofill_action_rejected(self):
        with self.assertRaises(CE):
            _reconcile([_trade(suggested_action="持有")])       # 持有 cannot be executed=TRUE

    def test_executed_without_fill_rejected(self):
        with self.assertRaises(CE):
            _reconcile([_trade(fill_price="", fill_shares="")])

    def test_not_executed_with_fill_rejected(self):
        with self.assertRaises(CE):
            _reconcile([_trade(executed="FALSE", skip_reason="x")])   # still carries fill_price/shares

    def test_not_executed_without_skip_rejected(self):
        with self.assertRaises(CE):
            _reconcile([_trade(executed="FALSE", fill_price="", fill_shares="", skip_reason="")])

    def test_future_trade_rejected(self):
        with self.assertRaises(CE):
            _reconcile([_trade(decision_date="20260701")], as_of="20260622")

    def test_a_share_ticker_in_trades_rejected(self):
        with self.assertRaises(CE):
            _reconcile([_trade(ticker="000001.SZ")])

    def test_trades_extra_column_rejected_pure_path(self):
        with self.assertRaises(CE):
            conv.build_account_state(
                {"account": [_acct()], "positions": [_pos()], "trades": [_trade(foo="bar")]},
                "20260622", "20260622")

    def test_build_populates_consistency_warnings(self):
        _, lineage = conv.build_account_state(
            {"account": [_acct()], "positions": [_pos()], "trades": [_trade(fill_shares="7")]},
            "20260622", "20260622")
        self.assertEqual([w["kind"] for w in lineage["consistency_warnings"]], ["shares_mismatch"])

    def test_action_vocab_matches_design_section9(self):
        # drift-guard: the trade action vocab must be EXACTLY the §9 final_action set (no alias/omission)
        self.assertEqual(
            set(conv.TRADE_ACTIONS),
            {"建仓", "加仓", "减仓", "清仓-止损", "清仓-止盈", "清仓-事件", "持有", "观察", "否决/避开"})

    def test_all_design_actions_accepted(self):
        for a in ("建仓", "加仓", "减仓", "清仓-止损", "清仓-止盈", "清仓-事件"):
            _reconcile([_trade(suggested_action=a, ticker="TSLA")])                 # executed buy/sell parses
        for a in ("持有", "观察", "否决/避开"):
            _reconcile([_trade(suggested_action=a, executed="FALSE",
                               fill_price="", fill_shares="", skip_reason="x")])     # non-fill parses

    def test_canonical_veto_action_accepted(self):
        w = _reconcile([_trade(suggested_action="否决/避开", executed="FALSE",
                               fill_price="", fill_shares="", skip_reason="avoid")])
        self.assertEqual(w, [])

    def test_veto_alias_without_suffix_rejected(self):
        # `否决` (without /避开) is NOT the §9 value -> rejected, so no hidden second vocabulary
        with self.assertRaises(CE):
            _reconcile([_trade(suggested_action="否决", executed="FALSE",
                               fill_price="", fill_shares="", skip_reason="x")])


class PrivacyGuardTests(unittest.TestCase):
    def test_outside_repo_ok(self):
        with tempfile.TemporaryDirectory() as d:
            conv._reject_nonprivate_account_output_path(str(Path(d) / "out.json"))  # no raise

    def test_ignored_in_repo_ok(self):
        # state/*/*.json is gitignored -> private -> allowed
        conv._reject_nonprivate_account_output_path(str(ROOT / "state" / "us_short" / "us_short_account_state.json"))

    def test_nonignored_in_repo_fatal(self):
        with self.assertRaises(CE):
            conv._reject_nonprivate_account_output_path(str(ROOT / "docs" / "zz_us_short_acct_guard_probe.json"))

    def test_no_inrepo_override_exists(self):
        # R-USSHORT-ACCTSTATE-PRIVATE-OUTPUT-OVERRIDE-BYPASS: there must be NO escape that lets an
        # in-repo non-gitignored path through. The guard takes no override arg, the CLI exposes no
        # nonprivate-override flag, and an in-repo tracked path is rejected with no way to bypass.
        import inspect
        params = list(inspect.signature(conv._reject_nonprivate_account_output_path).parameters)
        self.assertEqual(params, ["out_path"], "privacy guard must not accept an override argument")
        main_src = inspect.getsource(conv.main)
        self.assertNotIn("allow-nonprivate", main_src)
        self.assertNotIn("allow_nonprivate", main_src)
        with self.assertRaises(CE):   # in-repo tracked path: rejected, no escape
            conv._reject_nonprivate_account_output_path(str(ROOT / "docs" / "zz_us_short_acct_guard_probe.json"))

    def test_git_unavailable_fail_closed(self):
        # cannot verify the path is gitignored -> refuse (fail-closed), even for a normally-ignored path
        import unittest.mock as mock
        with mock.patch.object(conv.subprocess, "run", side_effect=FileNotFoundError("git")):
            with self.assertRaises(CE):
                conv._reject_nonprivate_account_output_path(
                    str(ROOT / "state" / "us_short" / "us_short_account_state.json"))

    def test_git_error_rc_fail_closed(self):
        import unittest.mock as mock

        class _R:
            returncode = 2
        with mock.patch.object(conv.subprocess, "run", return_value=_R()):
            with self.assertRaises(CE):
                conv._reject_nonprivate_account_output_path(
                    str(ROOT / "state" / "us_short" / "us_short_account_state.json"))

    def test_relative_path_fails_closed(self):
        # a relative --out resolves against the process CWD, not the repo root — from a non-root CWD it could
        # resolve outside the repo and bypass the git-check gate (real holdings to an unintended location), so
        # the guard requires an absolute path. NB: `state/us_short/...` would be gitignored-OK if ABSOLUTE.
        for rel in ("state/us_short/us_short_account_state.json", "o.json", "../x.json"):
            with self.assertRaises(CE, msg=rel):
                conv._reject_nonprivate_account_output_path(rel)


class MainEndToEndTests(unittest.TestCase):
    def test_main_requires_price_basis_date_before_write(self):
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "account.csv").write_text(_GOOD_ACCOUNT_CSV, encoding="utf-8")
            (dp / "positions.csv").write_text(
                "ticker,shares,avg_cost_usd,entry_date,current_stop,notes\n"
                "AAPL,10,180,20260601,165,core_top\n", encoding="utf-8")
            out = dp / "us_short_account_state.json"
            with self.assertRaises(SystemExit):
                conv.main(["--input-dir", str(dp), "--as-of", "20260622", "--out", str(out)])
            self.assertFalse(out.exists())

    def test_main_writes_valid_output(self):
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "account.csv").write_text(
                "as_of,us_market_equity,us_short_available_cash,portfolio_total_equity,manual_order_only,broker_connection_allowed\n"
                "20260622,30000,4000,90000,TRUE,FALSE\n", encoding="utf-8")
            (dp / "positions.csv").write_text(
                "ticker,shares,avg_cost_usd,entry_date,current_stop,notes\n"
                "AAPL,10,180,20260601,165,core_top\n"
                "BRK.B,5,410,20260520,,\n", encoding="utf-8")
            out = dp / "us_short_account_state.json"   # under tempdir (outside repo) -> guard OK
            rc = conv.main(["--input-dir", str(dp), "--as-of", "20260622",
                            "--price-basis-date", "20260622", "--out", str(out)])
            self.assertEqual(rc, 0)
            state = json.loads(out.read_text(encoding="utf-8"))
            conv.validate_account_state(state, "20260622")
            self.assertEqual([p["ticker"] for p in state["positions"]], ["AAPL", "BRK.B"])
            lineage = json.loads((dp / "us_short_account_state_lineage.json").read_text(encoding="utf-8"))
            self.assertEqual(lineage["expected_facts_as_of"], "20260622")
            self.assertEqual(lineage["facts_staleness"], "current")
            names = {t["name"]: t for t in lineage["source_tables"]}
            self.assertEqual(names["positions"]["row_count"], 2)
            self.assertRegex(names["account"]["sha256"], r"^[0-9a-f]{64}$")

    def test_main_rejects_unknown_csv_column(self):
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "account.csv").write_text(_GOOD_ACCOUNT_CSV, encoding="utf-8")
            (dp / "positions.csv").write_text(   # extra `direction` header column
                "ticker,shares,avg_cost_usd,entry_date,current_stop,notes,direction\n"
                "AAPL,10,180,20260601,165,x,short\n", encoding="utf-8")
            with self.assertRaises(CE):
                conv.main(["--input-dir", str(dp), "--as-of", "20260622",
                           "--price-basis-date", "20260622", "--out", str(dp / "o.json")])

    def test_main_rejects_row_with_too_many_cells(self):
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "account.csv").write_text(_GOOD_ACCOUNT_CSV, encoding="utf-8")
            (dp / "positions.csv").write_text(   # row overflow -> csv.DictReader None restkey
                "ticker,shares,avg_cost_usd,entry_date,current_stop,notes\n"
                "AAPL,10,180,20260601,165,x,EXTRA_CELL\n", encoding="utf-8")
            with self.assertRaises(CE):
                conv.main(["--input-dir", str(dp), "--as-of", "20260622",
                           "--price-basis-date", "20260622", "--out", str(dp / "o.json")])

    def test_main_rejects_duplicate_header(self):
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "account.csv").write_text(_GOOD_ACCOUNT_CSV, encoding="utf-8")
            (dp / "positions.csv").write_text(   # duplicate `ticker` -> DictReader silently keeps last
                "ticker,ticker,shares,avg_cost_usd,entry_date,current_stop,notes\n"
                "AAPL,MSFT,10,180,20260601,165,x\n", encoding="utf-8")
            with self.assertRaises(CE):
                conv.main(["--input-dir", str(dp), "--as-of", "20260622",
                           "--price-basis-date", "20260622", "--out", str(dp / "o.json")])

    def test_main_without_trades_empty_warnings(self):
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "account.csv").write_text(_GOOD_ACCOUNT_CSV, encoding="utf-8")
            (dp / "positions.csv").write_text(
                "ticker,shares,avg_cost_usd,entry_date,current_stop,notes\nAAPL,10,180,20260601,165,x\n",
                encoding="utf-8")
            rc = conv.main(["--input-dir", str(dp), "--as-of", "20260622",
                            "--price-basis-date", "20260622", "--out", str(dp / "o.json")])
            self.assertEqual(rc, 0)
            lineage = json.loads((dp / "o_lineage.json").read_text(encoding="utf-8"))
            self.assertEqual(lineage["consistency_warnings"], [])   # trades.csv absent -> no reconcile

    def test_main_with_trades_mismatch_warns(self):
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "account.csv").write_text(_GOOD_ACCOUNT_CSV, encoding="utf-8")
            (dp / "positions.csv").write_text(
                "ticker,shares,avg_cost_usd,entry_date,current_stop,notes\nAAPL,10,180,20260601,165,x\n",
                encoding="utf-8")
            (dp / "trades.csv").write_text(   # AAPL net 7 vs positions 10 -> advisory mismatch
                "decision_date,ticker,suggested_action,executed,fill_price,fill_shares,skip_reason,manual_override\n"
                "20260601,AAPL,建仓,TRUE,180,7,,\n", encoding="utf-8")
            conv.main(["--input-dir", str(dp), "--as-of", "20260622",
                       "--price-basis-date", "20260622", "--out", str(dp / "o.json")])
            lineage = json.loads((dp / "o_lineage.json").read_text(encoding="utf-8"))
            self.assertEqual([w["kind"] for w in lineage["consistency_warnings"]], ["shares_mismatch"])
            self.assertIn("trades", {t["name"] for t in lineage["source_tables"]})


class ReviewHygieneFixTests(unittest.TestCase):
    """2026-06-21 batch-1 review hygiene fixes (converter footguns F-2..F-5)."""

    # F-2: _parse_float rejects scientific notation / underscore / thousands separator (Excel & Python coercion)
    def test_float_scientific_notation_rejected(self):
        for bad in ("3e4", "1.8E2"):
            with self.assertRaises(CE):
                _build(account=_acct(us_market_equity=bad))

    def test_float_underscore_literal_rejected(self):
        with self.assertRaises(CE):
            _build(positions=[_pos(avg_cost_usd="1_8")])   # Python literal 1_8 -> 18 silently; must reject

    def test_float_thousands_separator_rejected(self):
        with self.assertRaises(CE):
            _build(account=_acct(us_market_equity="30,000"))

    def test_plain_decimal_float_still_ok(self):
        st, _ = _build(positions=[_pos(avg_cost_usd="180.5")])
        self.assertEqual(st["positions"][0]["avg_cost_usd"], 180.5)

    # F-3: the write primitive itself fail-closed-guards an in-repo non-private path (defense-in-depth)
    def test_write_primitive_guards_inrepo_nonprivate_path(self):
        probe = ROOT / "docs" / "zz_hygiene_write_primitive_probe.json"
        with self.assertRaises(CE):
            conv._write_json_atomic(probe, {"x": 1})
        self.assertFalse(probe.exists())   # nothing written

    # F-4: main() rejects --out == --lineage-out (lineage would silently overwrite the account_state)
    def test_main_rejects_same_out_and_lineage(self):
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "account.csv").write_text(_GOOD_ACCOUNT_CSV, encoding="utf-8")
            (dp / "positions.csv").write_text(
                "ticker,shares,avg_cost_usd,entry_date,current_stop,notes\nAAPL,10,180,20260601,165,x\n",
                encoding="utf-8")
            same = dp / "same.json"
            with self.assertRaises(CE):
                conv.main(["--input-dir", str(dp), "--as-of", "20260622",
                           "--price-basis-date", "20260622", "--out", str(same),
                           "--lineage-out", str(same)])

    # F-5: the lineage sidecar is validated against its own schema at runtime
    def test_validate_lineage_rejects_malformed(self):
        with self.assertRaises(CE):
            conv._validate_lineage({"schema_name": "us_short_account_state_lineage"})   # missing required fields


if __name__ == "__main__":
    unittest.main()
