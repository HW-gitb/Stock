"""Tests for the V14.3 regime comparison runner (slice 2b-impl ②b-2) — pure core + persistence.

Pins: iv_series_to_map validates the IV feed (reject dup/wrong-schema); make_feature_provider yields
valid rows; production-path guard; ledger/records/panel persistence; run_regime_step is
explicit-bootstrap-only (no-ledger+no-bootstrap raises; <252-day bootstrap raises; >=252 bootstrap
persists), supports weekly append with a ledger-spanning calendar + narrow daily window, and is
idempotent across reruns; CLI rejects a non-canonical --as-of before any fetch. The thin real Tushare
fetch is not unit-tested (it is the user-authorized 执行 layer).
"""
from __future__ import annotations

import sys
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_regime_comparison_runner import (  # noqa: E402
    iv_series_to_map, make_feature_provider, run_regime_step, save_panel, save_ledger,
    save_comparison_records, load_ledger, load_comparison_records, main, main_board_only,
    _latest_settled_as_of, save_action_records,
)
from engine.a_short_regime_action_comparison import build_action_record  # noqa: E402
from engine.a_short_regime_features import compute_regime_daily_features  # noqa: E402
from engine.a_short_regime_ledger import build_ledger, BACKFILL_MIN_TRADING_DAYS  # noqa: E402


def _dates(n, start=date(2023, 1, 2)):
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def _daily(cal):
    return pd.DataFrame([(d, "A", 11.0, 10.0) for d in cal],
                        columns=["trade_date", "ts_code", "high", "close"])


def _limit(cal):
    return pd.DataFrame([(d, "A", 11.0, 9.0) for d in cal],
                        columns=["trade_date", "ts_code", "up_limit", "down_limit"])


def _idx(cal):
    return pd.DataFrame([(d, 100.0 + i) for i, d in enumerate(cal)], columns=["trade_date", "close"])


def _feed(cal):
    return {
        "schema_name": "a_short_iv_feed", "schema_version": "1.1.0", "generated_at": "x",
        "as_of": cal[-1], "underlying": "510050.SH",
        "params": {"risk_free": 0.02, "div_yield": 0.0, "const_maturity_days": 30, "min_t_days": 5,
                   "roll_window": 252, "min_roll_obs": 60, "hv_window": 21},
        "n_days": len(cal),
        "series": [{"trade_date": d, "iv_value": 0.2, "iv_percentile_252d": 50.0, "hv_value": 0.18} for d in cal],
        "boundary": {"production": False, "real_money": False, "satisfies_ship_gate": False,
                     "iv_method": "bs_atm_constant_maturity_feasibility_grade"},
    }


def _row(d):
    return {
        "schema_name": "a_short_market_regime_daily", "schema_version": "1.0.0",
        "as_of": d, "limit_up_count": 0, "limit_down_count": 0, "net_limit": 0,
        "max_limit_streak": 0, "promotion_rate": None, "failed_limit_rate": None,
        "iv_percentile_252d": 50.0, "csi300_ret_1d": None, "csi1000_ret_1d": None,
        "pct_above_ma20": None, "csi1000_below_ma20": None,
        "data_quality_flags": ["csi1000_unavailable"],
        "boundary": {"production": False, "comparison_only": True, "drives_phase5_risk_posture": False},
    }


class PureHelperTests(unittest.TestCase):
    def test_latest_settled_as_of_caps_to_available_settled_day(self):
        # intraday: requested Monday(0615) but daily settled only through Friday(0612) → cap to Friday
        d = pd.DataFrame({"trade_date": ["20260611", "20260612"], "ts_code": ["A", "A"],
                          "high": [1.0, 1.0], "close": [1.0, 1.0]})
        self.assertEqual(_latest_settled_as_of(d, "20260615"), "20260612")
        # settled requested day present → no-op (max == requested)
        self.assertEqual(_latest_settled_as_of(d, "20260612"), "20260612")
        # rows after requested are ignored (only <= requested counts)
        d2 = pd.DataFrame({"trade_date": ["20260612", "20260618"], "ts_code": ["A", "A"],
                           "high": [1.0, 1.0], "close": [1.0, 1.0]})
        self.assertEqual(_latest_settled_as_of(d2, "20260615"), "20260612")
        # empty panel → requested (caller guards empty separately)
        self.assertEqual(_latest_settled_as_of(pd.DataFrame(columns=["trade_date"]), "20260615"), "20260615")

    def test_iv_series_to_map_validates(self):
        cal = _dates(3)
        self.assertEqual(iv_series_to_map(None), {})
        self.assertEqual(iv_series_to_map(_feed(cal))[cal[0]], 50.0)

    def test_iv_feed_duplicate_date_rejected(self):
        cal = _dates(3)
        feed = _feed(cal)
        feed["series"].append({"trade_date": cal[0], "iv_value": 0.2, "iv_percentile_252d": 95.0})
        feed["n_days"] = len(feed["series"])
        with self.assertRaises(Exception):
            iv_series_to_map(feed)

    def test_iv_feed_wrong_schema_rejected(self):
        feed = _feed(_dates(3))
        feed["schema_name"] = "bogus"
        with self.assertRaises(Exception):
            iv_series_to_map(feed)

    def test_make_feature_provider_yields_valid_row(self):
        cal = _dates(3)
        provider = make_feature_provider(_daily(cal), _limit(cal), _idx(cal), _idx(cal),
                                         iv_series_to_map(_feed(cal)))
        row = provider(cal[-1])
        self.assertEqual(row["as_of"], cal[-1])
        self.assertEqual(row["net_limit"], row["limit_up_count"] - row["limit_down_count"])

    def test_production_path_guard(self):
        with self.assertRaises(ValueError):
            save_panel("x", str(ROOT / "result" / "a_short" / "20240101" / "panel.md"))

    def test_main_board_only_filters_non_main(self):
        # R-V143-PREBOOTSTRAP-MAINBOARD-FILTER-BSHARE-LEAK: B-shares (200/900) must also be dropped.
        df = pd.DataFrame([("600000.SH",), ("000001.SZ",), ("002001.SZ",), ("003001.SZ",),
                           ("300750.SZ",), ("688981.SH",), ("920083.BJ",),
                           ("200001.SZ",), ("900901.SH",), ("garbage",)], columns=["ts_code"])
        kept = set(main_board_only(df)["ts_code"])
        self.assertEqual(kept, {"600000.SH", "000001.SZ", "002001.SZ", "003001.SZ"})

    def test_init_pro_delegates_to_sanctioned_init(self):
        # Optional: prove _init_pro uses the no-set_token sanctioned initializer, not ts.set_token.
        import os as _os, runners.a_short_regime_comparison_runner as r
        import runners.a_short_iv_feed_probe as probe
        from unittest import mock
        sentinel = object()
        with mock.patch.dict(_os.environ, {"TUSHARE_TOKEN": "tok"}), \
                mock.patch.object(probe, "init_tushare_pro", return_value=sentinel) as m:
            self.assertIs(r._init_pro(), sentinel)
            m.assert_called_once_with("tok")

    def test_main_board_filter_enables_compute(self):
        # mirrors the probe finding: a .BJ stock without stk_limit trips the fail-closed gate; filtering
        # to main board resolves it. d="20240105" canonical.
        d = "20240105"
        daily = pd.DataFrame([(d, "600000.SH", 11.0, 10.0), (d, "920083.BJ", 11.0, 10.0)],
                             columns=["trade_date", "ts_code", "high", "close"])
        stk_limit = pd.DataFrame([(d, "600000.SH", 11.0, 9.0)],   # no usable .BJ limit row
                                 columns=["trade_date", "ts_code", "up_limit", "down_limit"])
        with self.assertRaises(ValueError):                       # unfiltered → fail-closed on .BJ
            compute_regime_daily_features(d, daily, stk_limit, _idx([d]), _idx([d]))
        row = compute_regime_daily_features(d, main_board_only(daily), main_board_only(stk_limit),
                                            _idx([d]), _idx([d]))   # filtered → succeeds
        self.assertEqual(row["as_of"], d)

    def test_save_records_rejects_duplicate(self):
        from engine.a_short_regime_classifier import build_comparison_record
        rec = build_comparison_record([_row(_dates(1)[0])], "unknown", as_of=_dates(1)[0])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                save_comparison_records([rec, dict(rec)], str(Path(tmp) / "r.json"))


class BootstrapPolicyTests(unittest.TestCase):
    # inject a fast fake feature_provider so the 252-scale orchestration/policy tests don't trigger
    # 252 real computes (the real compute is covered by test_a_short_regime_features + the provider
    # integration by test_make_feature_provider_yields_valid_row). csi1000 is real (used by backfill).
    def _kw(self, cal, tmp, bootstrap):
        empty_daily = pd.DataFrame(columns=["trade_date", "ts_code", "high", "close"])
        empty_limit = pd.DataFrame(columns=["trade_date", "ts_code", "up_limit", "down_limit"])
        return dict(as_of=cal[-1], trade_calendar=cal, v14_2_regime="unknown",
                    daily=empty_daily, stk_limit=empty_limit, csi300=_idx(cal), csi1000=_idx(cal),
                    iv_feed=None, ledger_path=str(Path(tmp) / "l.json"),
                    records_path=str(Path(tmp) / "r.json"), panel_path=str(Path(tmp) / "p.md"),
                    bootstrap=bootstrap, feature_provider=lambda d: _row(d))

    def test_no_ledger_without_bootstrap_raises(self):
        cal = _dates(6)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_regime_step(**self._kw(cal, tmp, bootstrap=False))

    def test_insufficient_bootstrap_raises(self):
        cal = _dates(6)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_regime_step(**self._kw(cal, tmp, bootstrap=True))   # 6 < 252

    def test_sufficient_bootstrap_persists(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            out = run_regime_step(**self._kw(cal, tmp, bootstrap=True))
            self.assertEqual(out["ledger"]["coverage"]["n"], BACKFILL_MIN_TRADING_DAYS)
            self.assertEqual(out["evidence"]["total_weeks"], 1)
            self.assertEqual(len(load_ledger(str(Path(tmp) / "l.json"))["rows"]),
                             BACKFILL_MIN_TRADING_DAYS)

    def test_weekly_append_with_spanning_calendar_and_narrow_daily(self):
        # R-V143-SLICE2B-RUNNER-SHORT-CALENDAR-BLOCKS-WEEKLY-APPEND: 252-row ledger + 1 new day.
        n = BACKFILL_MIN_TRADING_DAYS
        cal = _dates(n + 1)                       # full span incl. the new day
        with tempfile.TemporaryDirectory() as tmp:
            lpath = str(Path(tmp) / "l.json")
            save_ledger(build_ledger([_row(d) for d in cal[:n]]), lpath,
                        as_of=cal[n - 1], trade_calendar=cal[:n])
            empty_daily = pd.DataFrame(columns=["trade_date", "ts_code", "high", "close"])
            empty_limit = pd.DataFrame(columns=["trade_date", "ts_code", "up_limit", "down_limit"])
            out = run_regime_step(as_of=cal[n], trade_calendar=cal, v14_2_regime="unknown",
                                  daily=empty_daily, stk_limit=empty_limit,
                                  csi300=_idx(cal), csi1000=_idx(cal), iv_feed=None,
                                  ledger_path=lpath, records_path=str(Path(tmp) / "r.json"),
                                  panel_path=str(Path(tmp) / "p.md"), bootstrap=False,
                                  feature_provider=lambda d: _row(d))
            self.assertEqual(out["ledger"]["coverage"]["n"], n + 1)

    def test_rerun_idempotent(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            run_regime_step(**self._kw(cal, tmp, bootstrap=True))
            out2 = run_regime_step(**self._kw(cal, tmp, bootstrap=False))   # rerun weekly
            self.assertEqual(out2["ledger"]["coverage"]["n"], BACKFILL_MIN_TRADING_DAYS)
            self.assertEqual(out2["evidence"]["total_weeks"], 1)

    def test_d2_action_sidecar_freezes_raw_effective_and_source_digest(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report = base / "weekly_m67.json"
            report.write_text(json.dumps({"schema_name": "a_short_weekly_report", "as_of": cal[-1], "reports": []}),
                              encoding="utf-8")
            kw = self._kw(cal, tmp, bootstrap=True)
            kw.update(v14_2_regime="shock", raw_v14_2_regime="unknown",
                      m67_report_path=str(report), action_records_path=str(base / "actions.json"),
                      action_summary_path=str(base / "summary.json"), action_decision_as_of=cal[-1])
            with patch("runners.a_short_regime_comparison_runner._current_run_date", return_value=cal[-1]):
                out = run_regime_step(**kw)
            self.assertEqual(out["action_comparison"]["records"][0]["raw_v14_2_regime"], "unknown")
            self.assertEqual(out["action_comparison"]["records"][0]["effective_v14_2_regime"], "shock")
            self.assertTrue(out["action_comparison"]["records"][0]["forward_eligible"])
            self.assertTrue((base / "actions.json").exists())

    def test_d2_historical_decision_is_derived_not_counted(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report = base / "weekly_m67.json"
            report.write_text(json.dumps({"schema_name": "a_short_weekly_report", "as_of": cal[-1], "reports": []}),
                              encoding="utf-8")
            kw = self._kw(cal, tmp, bootstrap=True)
            kw.update(v14_2_regime="shock", raw_v14_2_regime="unknown", m67_report_path=str(report),
                      action_records_path=str(base / "actions.json"),
                      action_summary_path=str(base / "summary.json"),
                      action_decision_as_of=cal[-2])
            out = run_regime_step(**kw)
            row = out["action_comparison"]["records"][0]
            self.assertFalse(row["forward_eligible"])
            self.assertEqual(out["action_comparison"]["summary"]["total_forward_weeks"], 0)

    def test_d2_rejects_current_decision_date_for_historical_settlement_before_writes(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report = base / "weekly_m67.json"
            report.write_text(json.dumps({"schema_name": "a_short_weekly_report", "as_of": cal[-1], "reports": []}),
                              encoding="utf-8")
            kw = self._kw(cal, tmp, bootstrap=True)
            kw.update(v14_2_regime="shock", raw_v14_2_regime="unknown", m67_report_path=str(report),
                      action_records_path=str(base / "actions.json"),
                      action_summary_path=str(base / "summary.json"), action_decision_as_of="20260716")
            with patch("runners.a_short_regime_comparison_runner._current_run_date", return_value="20260716"):
                with self.assertRaises(ValueError):
                    run_regime_step(**kw)
            self.assertFalse(Path(kw["ledger_path"]).exists())

    def test_d2_action_writer_cannot_seed_historical_forward_row(self):
        regime = {
            "as_of": "20230102", "v14_3_raw_regime": "defense",
            "v14_3_fired_rule": "broad_index_crash",
            "forward_returns": {"h1": None, "h3": None, "h5": None, "h10": None},
            "forward_returns_pending": ["h1", "h3", "h5", "h10"],
        }
        forged = build_action_record(
            regime_record=regime, raw_v14_2_regime="shock", effective_v14_2_regime="shock",
            m67_source={"source_schema_name": "a_short_weekly_report", "source_as_of": "20230102",
                        "source_sha256": "a" * 64, "candidate_build_count": 0},
            forward_origin={"decision_as_of": "20230102", "run_date": "20230102"})
        self.assertTrue(forged["forward_eligible"])
        with tempfile.TemporaryDirectory() as tmp:
            with patch("runners.a_short_regime_comparison_runner._current_run_date", return_value="20260716"):
                with self.assertRaises(ValueError):
                    save_action_records([forged], str(Path(tmp) / "actions.json"), current_action=forged,
                                        regime_records=[])

    def test_partial_d2_action_configuration_aborts_before_comparison_writes(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            kw = self._kw(cal, tmp, bootstrap=True)
            kw.update(raw_v14_2_regime="unknown")
            with self.assertRaises(ValueError):
                run_regime_step(**kw)
            self.assertFalse(Path(kw["ledger_path"]).exists())
            self.assertFalse(Path(kw["records_path"]).exists())
            self.assertFalse(Path(kw["panel_path"]).exists())


class CliGuardTests(unittest.TestCase):
    def test_noncanonical_as_of_rejected_before_fetch(self):
        # R-V143-SLICE2B-RUNNER-CLI-ASOF-LENIENT-FETCH: malformed date fails before any provider call.
        with self.assertRaises(SystemExit):
            main(["--as-of", "2024011", "--confirm-fetch-authorized"])

    def test_cli_refuses_manual_d2_forward_eligibility_flag(self):
        with self.assertRaises(SystemExit):
            main(["--as-of", "20260714", "--d2-forward-eligible"])


if __name__ == "__main__":
    unittest.main()
