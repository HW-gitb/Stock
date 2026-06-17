"""Tests for the A-short weekly pipeline (batch ②).

Covers normalize_candidate (EGS candidate → engine input mapping), build_weekly_report (per-stock
M6.7 envelope), validate_weekly_report (incl. the P2 consumer-validation: it MUST validate the IV
feed it consumed + every M6.7), write_weekly_report contract, latest_iv_percentile, IV-missing
propagation, and main() wiring with an injected price provider (no live Tushare). Synthetic inputs.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_weekly_pipeline import (  # noqa: E402
    normalize_candidate, build_weekly_report, validate_weekly_report,
    write_weekly_report, latest_iv_percentile, latest_iv_hv, main, SCHEMA_PATH,
    _fetch_price_series, _prev_trading_day, _load_validated_overlay, MIN_PRICE_OBS, resolve_market_regime,
    validate_account_state, stateful_risk_for_candidate, _ex_div_notices, _fetch_dividends,
)
from runners.a_short_m67_render import render_weekly_markdown, write_weekly_markdown  # noqa: E402
from runners.a_short_semantic_risk_summary import build_summary_from_fetches  # noqa: E402
from runners.a_short_theme_overlay_comparison import (  # noqa: E402
    assemble_overlay, build_summary,
)

AS_OF = "20260609"
GEN = "2026-06-09T12:00:00+08:00"
M67_SCHEMA = ROOT / "schemas" / "a_short_m67_report.schema.json"
FIXT_AI = ROOT / "schemas" / "examples" / "analysis_input.example.json"


def _analysis_input(trade_date=AS_OF, candidates=None):
    """Schema+PIT-valid analysis_input envelope (from the repo example) with our candidates."""
    base = json.loads(FIXT_AI.read_text(encoding="utf-8"))
    base["trade_date"] = trade_date
    src = base.get("source") or {}
    if src.get("l3_mode") == "pit":               # keep PIT invariant: snapshot <= trade_date
        src["l3_snapshot_date"] = trade_date
    if candidates is not None:
        base["candidates"] = candidates
    return base


def _series():
    # mirrors the engine test fixture: day12 carries support 2.87 + resistance 3.10.
    s = []
    for i in range(30):
        s.append({"high": 3.10, "low": 2.87, "close": 2.90} if i == 12
                 else {"high": 2.92, "low": 2.88, "close": 2.90})
    return s


def _egs_candidate(ts_code="600000.SH", **over):
    # mirrors the REAL egs_main analysis_input contract (derived_flags.is_lock / hard_veto;
    # event_risk.suspension.is_suspended) — NOT the engine-input shape.
    cand = {
        "ts_code": ts_code, "name": "测试",
        "quote": {"close": 2.90},
        "scores": {"esp_score": 60, "l4_score": 70},
        "liquidity": {"avg_amount_5d": 2e8, "avg_amount_20d": 2e8},
        "derived_flags": {"chasing_high": False, "overheat_flag": False, "has_crash_veto": False,
                          "is_lock": False, "is_breakout": False, "m4_review_required": None,
                          "hard_veto": False},
        "event_risk": {"holder_reduction": {"active_plan": False},
                       "suspension": {"is_suspended": False},
                       "delisting": {"st_flag": False, "delisting_warning": False}},
    }
    cand.update(over)
    return cand


_EXAMPLE_CAND = json.loads(FIXT_AI.read_text(encoding="utf-8"))["candidates"][0]


def _ai_candidate(ts_code="600000.SH", close=2.90, is_lock=False, suspended=False,
                  hard_veto=False, active_plan=False):
    """Full schema-valid candidate (deep-copied from the repo example), leaf-overridden.
    close defaults to 2.90 to align with the injected `_series()` support (低吸→建仓 path)."""
    c = copy.deepcopy(_EXAMPLE_CAND)
    c["ts_code"] = ts_code
    c["quote"]["close"] = close
    c["derived_flags"]["is_lock"] = is_lock
    c["derived_flags"]["hard_veto"] = hard_veto
    c["event_risk"]["suspension"]["is_suspended"] = suspended
    c["event_risk"]["holder_reduction"]["active_plan"] = active_plan
    return c


def _overlay_row(eligible=True, crowding=False):
    return {"eligible": eligible, "crowding_hit": crowding}


def _account():
    return {
        "schema_name": "a_short_account_state",
        "schema_version": "1.0.0",
        "as_of": AS_OF,
        "available_cash": 500000.0,
        "total_equity": 1000000.0,
        "current_gross_exposure": 0.0,
        "positions": [],
        "rule12": {
            "status": "inactive",
            "reason": None,
            "triggered_at": None,
            "cooldown_until": None,
            "recovery_position_multiplier": None,
            "consecutive_stop_losses_window": 0,
            "drawdown_pct": 0.0,
            "iv_change_abs_1d_pctpt": 0.0,
        },
        "rule13_cooldowns": [],
        "manual_order_only": True,
        "broker_connection_allowed": False,
    }


def _feed(last_pct=55.0):
    series = [{"trade_date": d, "iv_value": 0.15 + 0.001 * i,
               "iv_percentile_252d": (last_pct if i == 4 else 40.0),
               "hv_value": 0.14 + 0.001 * i}
              for i, d in enumerate(["20260601", "20260602", "20260603", "20260604", "20260605"])]
    return {"as_of": AS_OF, "n_days": len(series), "series": series}


def _valid_overlay_for(codes, as_of=AS_OF):
    """Schema + consistency valid overlay summary for an arbitrary candidate set (Slice A builders)."""
    pool = pd.DataFrame([
        {"ts_code": c, "baseline_rank": i + 1, "esp_score": 60.0 - i, "l4_score": 70.0,
         "overheat_flag": False, "chasing_high": False, "chase_flag": False, "high_pos_shrink": False}
        for i, c in enumerate(codes)])
    theme_heat = {"score": {c: 90.0 - i for i, c in enumerate(codes)},
                  "best_concept": {c: "c1" for c in codes}}
    industry_heat_by_l2 = {"半导体": 95.0, "银行": 20.0}
    sw_l2_by_code = {c: "半导体" for c in codes}
    breadth = {c: {"up_frac": 0.8, "vol_frac": 0.6, "pass": True} for c in codes}
    persistence = {c: 1.0 for c in codes}
    fit = {c: 0.8 for c in codes}
    assembled = assemble_overlay(pool, theme_heat, industry_heat_by_l2, breadth,
                                 persistence, fit, sw_l2_by_code)
    return build_summary(assembled, as_of=as_of,
                         pit_source={"concept_membership": "pit", "sw_mapping": "forward"},
                         dropped_at_l0_l5=[], generated_at="2026-06-10T00:00:00+08:00")


def _valid_overlay(as_of=AS_OF):
    """Schema + consistency valid overlay covering exactly the default weekly pool."""
    return _valid_overlay_for(["600000.SH", "000001.SZ"], as_of)


def _normalized(ts_code="600000.SH", iv_pct=55.0, **cand_over):
    return normalize_candidate(_egs_candidate(ts_code, **cand_over), _series(),
                               _overlay_row(), iv_pct, {"available_cash": 500000.0}, "震荡期")


def _weekly(normalized_list=None, iv_feed_ref="iv_feed.json"):
    nl = normalized_list if normalized_list is not None else [_normalized()]
    return build_weekly_report(nl, AS_OF, GEN, iv_feed_ref=iv_feed_ref)


def _sized_lineage():
    # (provided, sized) run_lineage —— 带账户定量的合法 lineage(配 available_cash>0 用,过 #3 双向不变式)。
    return {"analysis_input": "ai.json", "selection_bucket": "bucket", "iv_feed": "iv_feed.json",
            "account_ref": "acct.json", "account_status": "provided", "sizing_mode": "sized",
            "price_freshness": {"mode": "strict_as_of", "run_date": None,
                                "accepted_prior_settled_date": None, "price_data_through": AS_OF}}


class NormalizeTests(unittest.TestCase):
    def test_maps_egs_fields(self):
        n = _normalized()
        self.assertEqual(n["close"], 2.90)
        self.assertEqual(n["esp_score"], 60)
        self.assertTrue(n["overlay"]["eligible"])
        self.assertEqual(n["iv"]["iv_percentile_252d"], 55.0)
        self.assertEqual(n["liquidity"]["avg_amount_5d"], 2e8)
        self.assertEqual(n["market_regime"], "震荡期")

    def test_maps_event_and_derived_flags(self):
        n = normalize_candidate(
            _egs_candidate(derived_flags={"overheat_flag": True, "chasing_high": False,
                                          "has_crash_veto": False, "is_lock": False,
                                          "is_breakout": False, "hard_veto": False},
                           event_risk={"holder_reduction": {"active_plan": True},
                                       "suspension": {"is_suspended": False},
                                       "delisting": {"st_flag": True, "delisting_warning": False}}),
            _series(), _overlay_row(), 55.0, {}, "震荡期")
        self.assertTrue(n["derived"]["overheat"])
        self.assertTrue(n["event"]["holder_reduction_active"])
        self.assertTrue(n["event"]["st_or_delisting"])

    def test_maps_real_egs_hard_risk_contract_fields(self):
        # R-ASHORT-WEEKLY-EGS-HARD-RISK-MAPPING-GAP: real keys is_lock / suspension.is_suspended /
        # hard_veto must reach the engine hard-risk inputs (not the wrong limit_locked/suspended keys).
        n = normalize_candidate(
            _egs_candidate(derived_flags={"chasing_high": False, "overheat_flag": False,
                                          "has_crash_veto": False, "is_lock": True,
                                          "is_breakout": False, "hard_veto": True},
                           event_risk={"holder_reduction": {"active_plan": False},
                                       "suspension": {"is_suspended": True},
                                       "delisting": {"st_flag": False, "delisting_warning": False}}),
            _series(), _overlay_row(), 55.0, {}, "震荡期")
        self.assertTrue(n["derived"]["limit_locked"])
        self.assertTrue(n["derived"]["suspended"])
        self.assertTrue(n["derived"]["hard_veto"])

    def test_missing_overlay_defaults_false(self):
        n = normalize_candidate(_egs_candidate(), _series(), None, 55.0, {}, "震荡期")
        self.assertFalse(n["overlay"]["eligible"])
        self.assertFalse(n["overlay"]["crowding_hit"])

    def test_maps_vol_confirm(self):
        # vol_confirm now flows from EGS derived_flags → engine breakout entry (no longer dormant).
        n = normalize_candidate(
            _egs_candidate(derived_flags={"chasing_high": False, "overheat_flag": False,
                                          "has_crash_veto": False, "is_lock": False,
                                          "is_breakout": True, "vol_confirm": True, "hard_veto": False}),
            _series(), _overlay_row(), 55.0, {}, "震荡期")
        self.assertTrue(n["derived"]["vol_confirm"])
        self.assertTrue(n["derived"]["breakout"])

    def test_regime_fallback_flows_to_engine_input(self):
        n = normalize_candidate(_egs_candidate(), _series(), _overlay_row(), 55.0, {},
                                "震荡期", regime_fallback={"active": True, "reason": "x"})
        self.assertTrue(n["regime_fallback"]["active"])


class AccountStateTests(unittest.TestCase):
    def test_validate_account_state_accepts_contract_shape(self):
        acct = validate_account_state(copy.deepcopy(_account()), AS_OF)
        self.assertEqual(acct["available_cash"], 500000.0)

    def test_validate_account_state_rejects_duplicate_positions(self):
        acct = copy.deepcopy(_account())
        pos = {"ts_code": "600000.SH", "name": "测试", "shares": 1000,
               "avg_cost": 2.70, "entry_date": "20260601", "stop_loss": 2.55}
        acct["positions"] = [copy.deepcopy(pos), copy.deepcopy(pos)]
        with self.assertRaises(SystemExit):
            validate_account_state(acct, AS_OF)

    def test_validate_account_state_rejects_stale_rule12_active(self):
        acct = copy.deepcopy(_account())
        acct["rule12"] = {"status": "active_cooldown", "cooldown_until": "20260608"}
        with self.assertRaises(SystemExit):
            validate_account_state(acct, AS_OF)

    def test_stateful_risk_maps_held_position(self):
        acct = copy.deepcopy(_account())
        acct["positions"] = [{"ts_code": "600000.SH", "name": "测试", "shares": 1000,
                              "avg_cost": 2.70, "entry_date": "20260601", "stop_loss": 2.55}]
        ctx = stateful_risk_for_candidate(acct, "600000.SH", AS_OF)
        self.assertEqual(ctx["position_state"], "held")
        self.assertEqual(ctx["position"]["avg_cost"], 2.70)

    def test_stateful_risk_maps_rule13_cooldown(self):
        acct = copy.deepcopy(_account())
        acct["rule13_cooldowns"] = [{
            "ts_code": "600000.SH",
            "status": "active_cooldown",
            "exit_date": "20260608",
            "cooldown_until": "20260610",
            "requires_new_catalyst": True,
            "new_catalyst_confirmed": False,
            "requires_m4_recheck": True,
            "m4_recheck_passed": False,
            "max_reentry_position_pct": 0.5,
        }]
        ctx = stateful_risk_for_candidate(acct, "600000.SH", AS_OF)
        self.assertEqual(ctx["position_state"], "flat")
        self.assertTrue(ctx["rule13"]["reentry_blocked"])


class BuildWeeklyTests(unittest.TestCase):
    def test_envelope(self):
        w = _weekly([_normalized("600000.SH"), _normalized("000001.SZ")])
        self.assertEqual(w["schema_name"], "a_short_weekly_report")
        self.assertEqual(w["n_stocks"], 2)
        self.assertEqual(len(w["reports"]), 2)
        self.assertTrue(all(v is False for v in w["boundary"].values()))

    def test_buildable_candidate_yields_jiacang(self):
        w = _weekly([_normalized()])
        self.assertEqual(w["reports"][0]["m67"]["table"]["操作"], "建仓")

    def test_hard_veto_candidate_yields_fouju_null_trade(self):
        n = _normalized(event_risk={"holder_reduction": {"active_plan": True},
                                    "suspension": {"is_suspended": False},
                                    "delisting": {"st_flag": False, "delisting_warning": False}})
        rep = _weekly([n])["reports"][0]
        self.assertEqual(rep["m67"]["table"]["操作"], "否决")
        for k in ("股数", "入", "盈一", "盈二", "损"):
            self.assertIsNone(rep["m67"]["table"][k])

    def test_real_egs_hard_risk_fields_cannot_become_jiacang(self):
        # actual-analysis-input-shape: is_lock / suspension.is_suspended / hard_veto each → not 建仓.
        def _df(**kw):
            base = {"chasing_high": False, "overheat_flag": False, "has_crash_veto": False,
                    "is_lock": False, "is_breakout": False, "hard_veto": False}
            base.update(kw)
            return base
        cases = [
            {"derived_flags": _df(is_lock=True)},
            {"derived_flags": _df(hard_veto=True)},
            {"event_risk": {"holder_reduction": {"active_plan": False},
                            "suspension": {"is_suspended": True},
                            "delisting": {"st_flag": False, "delisting_warning": False}}},
        ]
        for over in cases:
            rep = _weekly([_normalized(**over)])["reports"][0]
            self.assertNotEqual(rep["m67"]["table"]["操作"], "建仓", over)


class ValidateWeeklyTests(unittest.TestCase):
    def test_good_passes(self):
        validate_weekly_report(_weekly(), _feed())  # no raise

    def test_consumer_validates_iv_feed_p2(self):
        # P2: the pipeline MUST validate the feed it consumed → a corrupt feed is caught here.
        bad_feed = _feed()
        bad_feed["series"][0]["iv_value"] = -1.0
        with self.assertRaises(ValueError):
            validate_weekly_report(_weekly(), bad_feed)

    def test_rejects_future_dated_feed(self):
        bad_feed = _feed()
        bad_feed["series"][-1]["trade_date"] = "20260631"  # invalid calendar
        with self.assertRaises(ValueError):
            validate_weekly_report(_weekly(), bad_feed)

    def test_rejects_feed_as_of_after_weekly_as_of(self):
        # R-ASHORT-WEEKLY-IV-FEED-PIT-CROSS-ASOF: feed from after the weekly run = future IV.
        future = {"as_of": "20260612", "n_days": 1,
                  "series": [{"trade_date": "20260612", "iv_value": 0.15, "iv_percentile_252d": 50.0}]}
        with self.assertRaises(ValueError):
            validate_weekly_report(_weekly(), future)  # weekly as_of = 20260609

    def test_rejects_n_stocks_mismatch(self):
        w = _weekly()
        w["n_stocks"] = 99
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_report_as_of_mismatch(self):
        w = _weekly()
        w["reports"][0]["as_of"] = "20260101"
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_duplicate_ts_code(self):
        w = _weekly([_normalized("600000.SH"), _normalized("600000.SH")])
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_boundary_not_all_false(self):
        w = _weekly()
        w["boundary"]["production"] = True
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_run_lineage_status_mode_mismatch(self):
        # #1 hardening: (account_status, sizing_mode) is a STRICT bijection. A contradictory pair must not
        # pass, else a mislabeled lineage could let a sizing-less 观察 read as account-backed (or vice versa).
        # Both off-diagonal pairings must raise — incl. (provided, observation_only_no_account), which the
        # prior two-rule check let through.
        for acct_st, size_md in [("provided", "observation_only_no_account"), ("absent", "sized")]:
            w = _weekly()
            w["run_lineage"]["account_status"] = acct_st
            w["run_lineage"]["sizing_mode"] = size_md
            with self.assertRaises(ValueError):
                validate_weekly_report(w, _feed())


class WriteWeeklyTests(unittest.TestCase):
    def test_write_roundtrip(self):
        w = _weekly()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "weekly.json"
            write_weekly_report(w, _feed(), str(out))
            loaded = json.loads(out.read_text(encoding="utf-8"))
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            jsonschema.validate(loaded, json.load(f))
        self.assertEqual(loaded["n_stocks"], 1)

    def test_write_rejects_tampered_report(self):
        w = _weekly()
        # tamper a 建仓 report's table to drift from machine plan → per-report m67 consistency fails
        w["reports"][0]["m67"]["table"]["入"] = 999.0
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "weekly.json"
            with self.assertRaises((ValueError, jsonschema.ValidationError)):
                write_weekly_report(w, _feed(), str(out))
            self.assertFalse(out.exists())

    def test_write_rejects_production_output_path(self):
        # R-ASHORT-WEEKLY-OFFICIAL-OUTPUT-PATH-BOUNDARY: never write result/a_short/<date>.
        w = _weekly()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "result" / "a_short" / "20260609" / "weekly.json"
            with self.assertRaises(ValueError):
                write_weekly_report(w, _feed(), str(out))
            self.assertFalse(out.exists())

    def test_write_rejects_noncalendar_as_of_even_empty(self):
        # R-ASHORT-WEEKLY-WRITE-ASOF-CALENDAR-GAP: invalid calendar as_of rejected incl. empty reports.
        w = build_weekly_report([], "20260631", GEN, iv_feed_ref="f")  # 0 reports, bad calendar
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "weekly.json"
            with self.assertRaises(ValueError):
                write_weekly_report(w, _feed(), str(out))
            self.assertFalse(out.exists())


class IVMissingTests(unittest.TestCase):
    def test_latest_iv_percentile(self):
        self.assertEqual(latest_iv_percentile(_feed(last_pct=67.0)), 67.0)
        self.assertIsNone(latest_iv_percentile({"series": []}))

    def test_latest_iv_hv(self):
        iv_v, hv_v = latest_iv_hv(_feed())
        self.assertAlmostEqual(iv_v, 0.154, places=6)      # i=4: 0.15+0.004
        self.assertAlmostEqual(hv_v, 0.144, places=6)      # i=4: 0.14+0.004
        self.assertEqual(latest_iv_hv({"series": []}), (None, None))
        self.assertEqual(latest_iv_hv({}), (None, None))

    def test_normalize_threads_iv_value_hv_value(self):
        n = normalize_candidate(_egs_candidate(), _series(), None, 55.0, {}, "震荡期",
                                iv_value=0.30, hv_value=0.20)
        self.assertEqual(n["iv"]["iv_value"], 0.30)
        self.assertEqual(n["iv"]["hv_value"], 0.20)
        self.assertEqual(n["iv"]["iv_percentile_252d"], 55.0)

    def test_iv_hv_surfaces_in_weekly_m67(self):
        # 端到端:feed 的 iv_value/hv_value → normalize → 引擎 M6.7 波动率状态含 IV/HV 标签
        n = normalize_candidate(_egs_candidate(), _series(), None, 55.0, {}, "震荡期",
                                iv_value=0.30, hv_value=0.20)
        rep = _weekly([n])["reports"][0]
        self.assertIn("IV/HV", rep["m67"]["精简结论区"]["波动率状态"])
        self.assertEqual(rep["machine"]["iv_gate"]["iv_hv_regime"], "iv_rich")

    def test_iv_missing_propagates_observe_only(self):
        n = _normalized(iv_pct=None)
        rep = _weekly([n])["reports"][0]
        self.assertEqual(rep["machine"]["iv_gate"]["status"], "observe_only_missing_feed")
        self.assertIn("IV未知", rep["m67"]["精简结论区"]["波动率状态"])


class MainWiringTests(unittest.TestCase):
    def _write_inputs(self, td, feed=None, ai=None):
        ai = ai if ai is not None else _analysis_input(
            candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
        (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
        (Path(td) / "feed.json").write_text(json.dumps(feed or _feed()), encoding="utf-8")
        (Path(td) / "acct.json").write_text(json.dumps(_account()), encoding="utf-8")

    def test_main_with_injected_price_provider(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["n_stocks"], 2)
        self.assertEqual(loaded["iv_feed_ref"], "feed.json")
        self.assertEqual(loaded["reports"][0]["m67"]["table"]["操作"], "建仓")

    def test_price_freshness_mode_controls_tolerance(self):
        # the intraday tolerance is gated on the EXPLICIT --price-freshness-mode (NOT inferred from
        # run-date==as-of). Spy on _fetch_price_series to capture what main passed as the accepted clock.
        import runners.a_short_weekly_pipeline as wp
        cap = {}

        def _spy(ts, pro, code, start, end, accept_prior_settled_date=None):
            cap["accept"] = accept_prior_settled_date
            raise SystemExit("captured")                   # short-circuit once the wiring is observed

        class _Pro:
            def trade_cal(self, **kw):
                return pd.DataFrame({"cal_date": ["20260605", "20260608", AS_OF]})

        orig = wp._fetch_price_series
        wp._fetch_price_series = _spy
        try:
            with tempfile.TemporaryDirectory() as td:
                self._write_inputs(td)
                base = ["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                        "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                        "--out", str(Path(td) / "w.json"), "--confirm-fetch-authorized", "--skip-semantic"]
                kw = dict(pro_factory=lambda: _Pro(), semantic_provider=lambda c: None,
                          web_llm_provider=lambda c: None)
                with self.assertRaises(SystemExit):        # explicit intraday mode + run-date==as-of
                    main(base + ["--run-date", AS_OF, "--price-freshness-mode", "intraday_prior_settled"], **kw)
                self.assertEqual(cap["accept"], "20260608")   # prior trading day passed
                cap.clear()
                with self.assertRaises(SystemExit):        # default strict — NO tolerance even if run-date==as-of
                    main(base + ["--run-date", AS_OF], **kw)
                self.assertIsNone(cap["accept"])
        finally:
            wp._fetch_price_series = orig

    def test_intraday_mode_requires_run_date_equals_as_of(self):
        # explicit intraday mode on a non-same-day run-date is rejected up front (guard), before fetch.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--run-date", "20260605", "--price-freshness-mode",
                      "intraday_prior_settled", "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(Path(td) / "w.json"), "--confirm-fetch-authorized", "--skip-semantic"],
                     pro_factory=lambda: object(), semantic_provider=lambda c: None,
                     web_llm_provider=lambda c: None)

    def test_strict_mode_records_price_freshness_lineage(self):
        # default strict run: the artifact records the price clock = as_of (injected list → strict clock).
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            pf = json.loads(out.read_text(encoding="utf-8"))["run_lineage"]["price_freshness"]
        self.assertEqual(pf["mode"], "strict_as_of")
        self.assertEqual(pf["price_data_through"], AS_OF)
        self.assertIsNone(pf["accepted_prior_settled_date"])

    def test_intraday_mode_records_prior_settled_and_renders_clock(self):
        # full intraday path (real _fetch_price_series via fake tushare): bars end at the prior settled
        # day; the artifact + Markdown must honestly state price_data_through == prior settled, != as_of.
        dates = pd.date_range(end="20260608", periods=25, freq="D").strftime("%Y%m%d").tolist()
        fake = _fake_ts(pd.DataFrame({"trade_date": dates, "high": [3.1] * 25,
                                      "low": [2.8] * 25, "close": [2.9] * 25}))

        class _Pro:
            def trade_cal(self, **kw):
                return pd.DataFrame({"cal_date": ["20260605", "20260608", AS_OF]})

        old = sys.modules.get("tushare")
        sys.modules["tushare"] = fake
        try:
            with tempfile.TemporaryDirectory() as td:
                self._write_inputs(td)
                out = Path(td) / "weekly_m67.json"
                main(["--as-of", AS_OF, "--run-date", AS_OF, "--price-freshness-mode", "intraday_prior_settled",
                      "--analysis-input", str(Path(td) / "ai.json"), "--iv-feed", str(Path(td) / "feed.json"),
                      "--account", str(Path(td) / "acct.json"), "--out", str(out), "--confirm-fetch-authorized",
                      "--skip-semantic"], pro_factory=lambda: _Pro(),
                     semantic_provider=lambda c: None, web_llm_provider=lambda c: None)
                pf = json.loads(out.read_text(encoding="utf-8"))["run_lineage"]["price_freshness"]
                md = (Path(td) / "weekly_m67.md").read_text(encoding="utf-8")
        finally:
            if old is not None:
                sys.modules["tushare"] = old
            else:
                sys.modules.pop("tushare", None)
        self.assertEqual(pf["mode"], "intraday_prior_settled")
        self.assertEqual(pf["run_date"], AS_OF)
        self.assertEqual(pf["accepted_prior_settled_date"], "20260608")
        self.assertEqual(pf["price_data_through"], "20260608")     # honest: features through prior settled day
        self.assertIn("价格时钟", md)                               # clock visible to the user in Markdown
        self.assertIn("20260608", md)

    def test_mixed_price_latest_dates_abort_no_file(self):
        # candidates with differing latest price-bar dates (uneven endpoint) → fail-closed, no file.
        def _prov(code):
            return (_series(), "20260609" if code == "600000.SH" else "20260608")  # (series, latest) differs
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "w.json"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)], price_provider=_prov)
            self.assertFalse(out.exists())

    def test_main_writes_markdown_sibling_with_banner(self):
        # pipeline main emits a readable weekly_m67.md sibling next to the json (honesty banner present).
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly_m67.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            md = Path(td) / "weekly_m67.md"
            self.assertTrue(md.exists())
            text = md.read_text(encoding="utf-8")
        self.assertIn("# A-short 周报 M6.7", text)
        self.assertIn("edge 未验证", text)        # honesty banner
        self.assertIn("## 一览", text)

    def test_main_with_account_records_sized_lineage(self):
        # R-ASHORT-WEEKLYSCREENING-M67-MISSING-ACCOUNT (behavioral): a valid account -> run_lineage sized + 建仓.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            w = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(w["run_lineage"]["account_status"], "provided")
        self.assertEqual(w["run_lineage"]["sizing_mode"], "sized")
        self.assertEqual(w["reports"][0]["m67"]["table"]["操作"], "建仓")     # sized -> buildable

    def test_main_account_position_outputs_hold_for_held_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            acct = _account()
            acct["positions"] = [{"ts_code": "600000.SH", "name": "测试", "shares": 1000,
                                  "avg_cost": 2.70, "entry_date": "20260601", "stop_loss": 2.55}]
            (Path(td) / "acct.json").write_text(json.dumps(acct), encoding="utf-8")
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            w = json.loads(out.read_text(encoding="utf-8"))
        by = {r["ts_code"]: r for r in w["reports"]}
        self.assertEqual(by["600000.SH"]["m67"]["table"]["操作"], "持有")
        self.assertIn("已有持仓", by["600000.SH"]["m67"]["精简结论区"]["操作建议"])
        self.assertEqual(by["000001.SZ"]["m67"]["table"]["操作"], "建仓")

    def test_main_rule13_active_blocks_flat_reentry(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            acct = _account()
            acct["rule13_cooldowns"] = [{
                "ts_code": "600000.SH",
                "status": "active_cooldown",
                "exit_date": "20260608",
                "cooldown_until": "20260610",
                "requires_new_catalyst": True,
                "new_catalyst_confirmed": False,
                "requires_m4_recheck": True,
                "m4_recheck_passed": False,
                "max_reentry_position_pct": 0.5,
            }]
            (Path(td) / "acct.json").write_text(json.dumps(acct), encoding="utf-8")
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            w = json.loads(out.read_text(encoding="utf-8"))
        by = {r["ts_code"]: r for r in w["reports"]}
        self.assertEqual(by["600000.SH"]["m67"]["table"]["操作"], "否决")
        self.assertIn("Rule13", "|".join(by["600000.SH"]["machine"]["layer"]["hard_veto"]))

    def test_main_without_account_is_observation_only_and_artifact_labeled(self):
        # the same candidate that builds WITH account becomes 观察 with NO account; the durable artifact
        # (json run_lineage + md banner) marks it sizing-less so a reader can't mistake it for a real avoid.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly_m67.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],   # NO --account
                 price_provider=lambda code: _series())
            w = json.loads(out.read_text(encoding="utf-8"))
            md = (Path(td) / "weekly_m67.md").read_text(encoding="utf-8")
        self.assertEqual(w["run_lineage"]["account_status"], "absent")
        self.assertEqual(w["run_lineage"]["sizing_mode"], "observation_only_no_account")
        self.assertNotEqual(w["reports"][0]["m67"]["table"]["操作"], "建仓")   # no sizing -> not 建仓
        self.assertIn("无账户", md)                                            # durable no-sizing banner in the .md
        self.assertIn("sizing 假象", md)

    def test_main_account_file_with_bad_cash_aborts_no_silent_sizingless(self):
        # account FILE supplied but available_cash missing/non-numeric -> refuse (do not silently run sizing-less)
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            (Path(td) / "bad_acct.json").write_text(json.dumps({"market_regime": "震荡期"}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "bad_acct.json"),
                      "--out", str(Path(td) / "w.json")], price_provider=lambda code: _series())

    def test_main_invalid_as_of_aborts(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            with self.assertRaises(SystemExit):
                main(["--as-of", "20260631", "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--out", str(Path(td) / "w.json")],
                     price_provider=lambda code: _series())

    def test_main_no_provider_without_confirm_aborts(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--out", str(Path(td) / "w.json")])

    def test_main_empty_price_series_aborts_no_file(self):
        # R-ASHORT-WEEKLY-PRICE-FETCH-FAIL-OPEN: missing price coverage must NOT degrade to 观察.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)], price_provider=lambda code: [])
            self.assertFalse(out.exists())

    def test_main_short_price_series_aborts_no_file(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)], price_provider=lambda code: _series()[:MIN_PRICE_OBS - 1])
            self.assertFalse(out.exists())

    def test_main_analysis_input_trade_date_mismatch_aborts(self):
        # R-ASHORT-WEEKLY-ANALYSIS-INPUT-CONSUMER-VALIDATION-GAP: trade_date must == --as-of.
        for td_val in ("20260601", "20260612"):   # stale, future
            with tempfile.TemporaryDirectory() as td:
                self._write_inputs(td, ai=_analysis_input(
                    trade_date=td_val, candidates=[_ai_candidate("600000.SH")]))
                out = Path(td) / "weekly.json"
                with self.assertRaises(SystemExit):
                    main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                          "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                          "--out", str(out)], price_provider=lambda code: _series())
                self.assertFalse(out.exists())

    def test_main_malformed_analysis_input_aborts(self):
        with tempfile.TemporaryDirectory() as td:
            bad = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            del bad["source"]                       # drop a schema-required top-level field
            self._write_inputs(td, ai=bad)
            out = Path(td) / "weekly.json"
            with self.assertRaises((ValueError, SystemExit)):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)], price_provider=lambda code: _series())
            self.assertFalse(out.exists())

    def test_main_regime_from_analysis_input_takes_precedence(self):
        # market_regime sourced from analysis_input.market_context (EGS); account state is cash/position only.
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            ai["market_context"]["market_regime"]["status"] = "attack"   # → 进攻期
            self._write_inputs(td, ai=ai)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["reports"][0]["m67"]["精简结论区"]["当前环境"], "进攻期")

    def test_unknown_regime_fallback_cannot_be_overridden_by_account(self):
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            ai["market_context"]["market_regime"]["status"] = "unknown"
            self._write_inputs(td, ai=ai)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            loaded = json.loads(out.read_text(encoding="utf-8"))
        rep = loaded["reports"][0]
        self.assertIn("震荡期", rep["m67"]["精简结论区"]["当前环境"])
        self.assertIn("EGS regime unknown", rep["m67"]["精简结论区"]["当前环境"])
        self.assertEqual(rep["machine"]["risk_families"]["market_regime"]["action"], "downgrade")
        self.assertIn("regime unknown", rep["m67"]["精简结论区"]["操作建议"])

    def test_resolve_market_regime_unknown_returns_conservative_fallback(self):
        ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
        ai["market_context"]["market_regime"]["status"] = "unknown"
        regime, fallback = resolve_market_regime(ai)
        self.assertEqual(regime, "震荡期")
        self.assertEqual(fallback["action"], "downgrade_and_halve")

    def test_main_with_valid_overlay_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            (Path(td) / "ov.json").write_text(json.dumps(_valid_overlay(AS_OF)), encoding="utf-8")
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--overlay", str(Path(td) / "ov.json"), "--out", str(out)],
                 price_provider=lambda code: _series())
            self.assertTrue(out.exists())

    def _assert_main_overlay_aborts_no_file(self, overlay_obj):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            (Path(td) / "ov.json").write_text(json.dumps(overlay_obj), encoding="utf-8")
            out = Path(td) / "weekly.json"
            md = Path(td) / "weekly.md"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--overlay", str(Path(td) / "ov.json"), "--out", str(out)],
                     price_provider=lambda code: _series())
            self.assertFalse(out.exists(), "weekly.json written despite invalid overlay")   # each absent
            self.assertFalse(md.exists(), "weekly.md written despite invalid overlay")       # separately

    def test_main_overlay_missing_weekly_candidate_writes_no_file(self):
        # internally-valid overlay covering only 600000.SH while weekly candidates are
        # [600000.SH, 000001.SZ]; the missing row would silently default to eligible/crowding=false
        # → MY lineage check (not overlay-internal consistency) must abort before any write.
        self._assert_main_overlay_aborts_no_file(_valid_overlay_for(["600000.SH"]))

    def test_main_overlay_wrong_candidate_set_writes_no_file(self):
        # internally-valid overlay for a different same-size set (600002.SH instead of 000001.SZ).
        self._assert_main_overlay_aborts_no_file(_valid_overlay_for(["600000.SH", "600002.SH"]))

    def test_main_overlay_duplicate_candidate_writes_no_file(self):
        # schema+consistency-valid overlay with a DUPLICATE current candidate row: dict/set collapse
        # would hide it (3 rows -> set of 2 == weekly set). The raw-list dup check must abort before write.
        self._assert_main_overlay_aborts_no_file(_valid_overlay_for(["600000.SH", "000001.SZ", "000001.SZ"]))

    def test_main_skip_semantic_leaves_semantic_neutral(self):
        # --skip-semantic (even with --confirm) must NOT auto-fetch cninfo; semantic stays neutral.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out), "--confirm-fetch-authorized", "--skip-semantic"],
                 price_provider=lambda code: _series())
            w = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(w["reports"][0]["machine"]["layer"]["semantic_risk"]["impact"], "none")

    def test_cninfo_provider_reuses_summary_gates(self):
        # R-ASHORT-M67-CNINFO-PROVIDER-BYPASSES-SEMANTIC-SUMMARY-GATES: provider must reuse the
        # reviewed summary gates (main_board_top15 + missing->unknown + batch-empty->unknown).
        from runners.a_short_weekly_pipeline import _build_cninfo_semantic_provider
        calls = {}

        def fetch_factory(raws):
            def f(codes, a, l):
                calls["codes"] = list(codes)
                return raws
            return f
        empty = [{"ts_code": c, "ok": True, "error_category": None, "announcements": []}
                 for c in ("600000.SH", "000001.SZ", "600519.SH")]
        prov = _build_cninfo_semantic_provider(["600000.SH", "000001.SZ", "600519.SH"], AS_OF, 90,
                                               fetcher=fetch_factory(empty))
        self.assertEqual(prov("600000.SH")["status"], "unknown")     # mass ok-empty -> unknown (NOT clear)
        # non-main (ChiNext 300750) is neither fetched nor fed
        prov2 = _build_cninfo_semantic_provider(["600000.SH", "300750.SZ"], AS_OF, 90,
                                                fetcher=fetch_factory(empty))
        self.assertNotIn("300750.SZ", calls["codes"])               # not fetched
        self.assertIsNone(prov2("300750.SZ"))                       # not fed into M6.7
        # malformed raw (no ts_code) -> no "None" mapping; requested code missing -> unknown
        prov3 = _build_cninfo_semantic_provider(["600000.SH"], AS_OF, 90,
                                                fetcher=fetch_factory([{"ok": True, "announcements": []}]))
        self.assertIsNone(prov3("None"))
        self.assertEqual(prov3("600000.SH")["status"], "unknown")

    def test_cninfo_provider_rejects_bad_lookback_without_fetch(self):
        from runners.a_short_weekly_pipeline import _build_cninfo_semantic_provider
        called = {"n": 0}

        def f(c, a, l):
            called["n"] += 1
            return []
        for bad in (0, -5, "90", None):
            self.assertIsNone(_build_cninfo_semantic_provider(["600000.SH"], AS_OF, bad, fetcher=f))
        self.assertEqual(called["n"], 0)                            # never fetched on bad lookback

    def test_cninfo_provider_feeds_official_risk(self):
        from runners.a_short_weekly_pipeline import _build_cninfo_semantic_provider
        risk = [{"ts_code": "600000.SH", "ok": True, "error_category": None, "announcements": [
            {"announcementTitle": "关于立案调查的公告", "adjunctUrl": "http://x/p.pdf",
             "announcementTime": 1700000000000, "secCode": "600000"}]}]
        prov = _build_cninfo_semantic_provider(["600000.SH"], AS_OF, 90, fetcher=lambda c, a, l: risk)
        self.assertEqual(prov("600000.SH")["status"], "risk")       # genuine official risk still feeds
        self.assertTrue(prov("600000.SH")["events"])

    def test_build_cninfo_semantic_provider_nonblocking_on_failure(self):
        from runners.a_short_weekly_pipeline import _build_cninfo_semantic_provider

        def boom(codes, a, l):
            raise RuntimeError("net down")
        self.assertIsNone(_build_cninfo_semantic_provider(["600000.SH"], AS_OF, 90, fetcher=boom))

    def test_main_semantic_provider_folds_into_m67(self):
        # Slice 1 end-to-end: injected semantic_provider (high official) folds into M6.7 → 否决;
        # a stock with no semantic stays neutral (impact none). No network (provider injected).
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)],
                 price_provider=lambda code: _series(),
                 semantic_provider=lambda code: (_official("risk", "high", "立案调查")
                                                 if code == "600000.SH" else None))
            w = json.loads(out.read_text(encoding="utf-8"))
        by = {r["ts_code"]: r for r in w["reports"]}
        self.assertEqual(by["600000.SH"]["m67"]["table"]["操作"], "否决")                # evidence-full high → 否决
        self.assertEqual(by["000001.SZ"]["machine"]["layer"]["semantic_risk"]["impact"], "none")  # no semantic


def _fake_ts(df):
    class _FakeTs:
        def __init__(self):
            self.calls = {}

        def pro_bar(self, **kw):
            self.calls.update(kw)
            return df
    return _FakeTs()


class PriceFetchTests(unittest.TestCase):
    def test_uses_stock_asset_E_and_returns_bars(self):
        # R-ASHORT-WEEKLY-PRICE-FETCH-FAIL-OPEN: A-share stocks need asset="E"; latest bar == end.
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260108", "20260109"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        series, latest = _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")
        self.assertEqual(ts.calls.get("asset"), "E")
        self.assertEqual(ts.calls.get("adj"), "qfq")
        self.assertEqual(len(series), 2)
        self.assertNotIn("trade_date", series[0])   # engine input shape is {high,low,close}
        self.assertEqual(latest, "20260109")        # actual latest bar date surfaced for lineage

    def test_provider_exception_aborts(self):
        ts = _fake_ts(None)
        ts.pro_bar = lambda **kw: (_ for _ in ()).throw(
            RuntimeError("request failed url=https://api.example.invalid token=SECRET123"))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")

    def test_future_bar_aborts(self):
        # R-ASHORT-WEEKLY-PRICE-SERIES-PIT-FRESHNESS-GAP: trade_date > as_of must abort.
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260109", "20260630"], "high": [3.0, 99.0],
                                    "low": [2.9, 1.0], "close": [3.0, 50.0]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")

    def test_stale_latest_bar_aborts(self):
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260101", "20260102"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20251201", "20260109")

    def test_noncalendar_trade_date_aborts(self):
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260631"], "high": [3.0], "low": [2.9], "close": [2.95]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")

    # --- reviewed intraday tolerance (R-ASHORT-WEEKLY-PRICE-SERIES-PIT-FRESHNESS-GAP) ---
    def test_intraday_prior_settled_bar_accepted(self):
        # as_of=Monday(0615), today's EOD not published → latest bar == prior trading day(Friday 0612)
        # is the latest SETTLED data and is accepted (not stale) when the tolerance is supplied.
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260611", "20260612"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        series, latest = _fetch_price_series(ts, object(), "600000.SH", "20260201", "20260615",
                                             accept_prior_settled_date="20260612")
        self.assertEqual(len(series), 2)                   # accepted: Friday-latest for a Monday as_of
        self.assertEqual(latest, "20260612")               # surfaces the prior-settled clock for lineage

    def test_intraday_tolerance_rejects_older_than_prior_settled(self):
        # the tolerance accepts ONLY the prior trading day; anything older is genuine staleness → abort.
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260610", "20260611"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        with self.assertRaises(SystemExit):                # latest 0611 < prior_settled 0612 → stale
            _fetch_price_series(ts, object(), "600000.SH", "20260201", "20260615",
                                accept_prior_settled_date="20260612")

    def test_intraday_tolerance_never_accepts_future_bar(self):
        # even with the tolerance set, a bar after as_of is never accepted (future-row guard precedes it).
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260612", "20260630"], "high": [3.0, 9.0],
                                    "low": [2.9, 1.0], "close": [3.0, 5.0]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260201", "20260615",
                                accept_prior_settled_date="20260612")

    def test_no_tolerance_stays_strict(self):
        # default (no tolerance, e.g. historical replay): latest != as_of still aborts (unchanged gate).
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260611", "20260612"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260201", "20260615")

    def test_prev_trading_day_returns_latest_strictly_before_as_of(self):
        class _Pro:
            def trade_cal(self, **kw):
                return pd.DataFrame({"cal_date": ["20260605", "20260608", "20260609"]})
        self.assertEqual(_prev_trading_day(_Pro(), "20260609"), "20260608")   # excludes as_of itself

    def test_prev_trading_day_none_when_empty_or_error(self):
        class _Empty:
            def trade_cal(self, **kw):
                return pd.DataFrame({"cal_date": []})
        self.assertIsNone(_prev_trading_day(_Empty(), "20260609"))
        class _Boom:
            def trade_cal(self, **kw):
                raise RuntimeError("trade_cal api down")
        self.assertIsNone(_prev_trading_day(_Boom(), "20260609"))            # fail-closed to strict

    def test_main_future_price_row_writes_no_file(self):
        # Codex repro: a fake tushare through main(--confirm-fetch-authorized) must NOT write.
        fake = _fake_ts(pd.DataFrame({"trade_date": ["20260630"], "high": [99.0],
                                      "low": [1.0], "close": [50.0]}))
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            (Path(td) / "acct.json").write_text(json.dumps(_account()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            old = sys.modules.get("tushare")
            sys.modules["tushare"] = fake
            try:
                with self.assertRaises(SystemExit):
                    main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                          "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                          "--out", str(out), "--confirm-fetch-authorized",
                          "--skip-semantic"], pro_factory=lambda: object())  # no real cninfo fetch in unit test
            finally:
                if old is not None:
                    sys.modules["tushare"] = old
                else:
                    sys.modules.pop("tushare", None)
            self.assertFalse(out.exists())


class OverlayConsumerTests(unittest.TestCase):
    # R-ASHORT-WEEKLY-OVERLAY-CONSUMER-VALIDATION-GAP
    def _write(self, td, ov):
        p = Path(td) / "ov.json"
        p.write_text(json.dumps(ov), encoding="utf-8")
        return str(p)

    def test_valid_same_as_of_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            m = _load_validated_overlay(self._write(td, _valid_overlay(AS_OF)), AS_OF)
            self.assertIn("600000.SH", m)

    def test_future_or_stale_as_of_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):  # future
                _load_validated_overlay(self._write(td, _valid_overlay("20260612")), AS_OF)
            with self.assertRaises(SystemExit):  # stale
                _load_validated_overlay(self._write(td, _valid_overlay("20260101")), AS_OF)

    def test_candidate_count_drift_rejected(self):
        ov = _valid_overlay(AS_OF)
        ov["candidate_count"] += 1
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                _load_validated_overlay(self._write(td, ov), AS_OF)

    def test_malformed_overlay_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(jsonschema.ValidationError):
                _load_validated_overlay(self._write(td, {"foo": 1}), AS_OF)


class SchemaTests(unittest.TestCase):
    def test_weekly_schema_valid(self):
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.Draft7Validator.check_schema(schema)

    def test_schema_requires_price_freshness_in_run_lineage(self):
        # Codex R-ASHORT-M67-INTRADAY-PRICE-FRESHNESS-LINEAGE-GAP: the price clock must be machine-readable
        # and the schema must reject a missing/invalid price_freshness block.
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        self.assertIn("price_freshness", schema["properties"]["run_lineage"]["required"])
        w = build_weekly_report([], AS_OF, GEN, iv_feed_ref="f")     # default lineage incl. price_freshness
        jsonschema.validate(w, schema)                               # valid as built
        del w["run_lineage"]["price_freshness"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(w, schema)                           # missing → rejected
        w2 = build_weekly_report([], AS_OF, GEN, iv_feed_ref="f")
        w2["run_lineage"]["price_freshness"]["mode"] = "bogus_mode"  # invalid enum
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(w2, schema)

    def test_weekly_design_doc_documents_schema_required_run_lineage(self):
        # R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT R3: the active weekly pipeline DESIGN doc must
        # not drift back to omitting run_lineage / its account semantics while the schema requires them.
        # Doc↔schema sync guard: every schema-required run_lineage subfield must be named in the design doc.
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        self.assertIn("run_lineage", schema["required"])
        required_subfields = schema["properties"]["run_lineage"]["required"]
        design = (ROOT / "docs" / "a_short_weekly_pipeline_design_20260610.md").read_text(encoding="utf-8")
        self.assertIn("run_lineage", design)
        for field in required_subfields:        # analysis_input/selection_bucket/iv_feed/account_status/sizing_mode
            self.assertIn(field, design, f"weekly design doc omits schema-required run_lineage.{field}")

    def test_weekly_design_doc_marks_overlay_wiring_done_not_future(self):
        # R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT R4: Slice A overlay data-loading is WIRED
        # (A-EGS/egs_main.py calls build_overlay_summary_from_panels; weekly_screening.ps1 passes --overlay;
        # the pipeline consumes it via _load_validated_overlay). Regression-pin so the active design doc cannot
        # drift back to listing overlay data-loading as 仍未来/future while README + code already wire it.
        import re
        design = (ROOT / "docs" / "a_short_weekly_pipeline_design_20260610.md").read_text(encoding="utf-8")
        self.assertIn("--overlay", design)                          # positive: overlay consumption documented
        for seg in re.findall(r"仍未来[^\n]*", design):              # no future-heading may list overlay
            self.assertNotIn("overlay", seg.lower(),
                             f"weekly design lists overlay as 仍未来 while code/README wire it: {seg!r}")


def _official(status, sev=None, rt="x", dd="20260601", url="u"):
    # full PIT official_structured evidence shape (matches build_official_structured output)
    evs = [{"source": "cninfo", "title": "t", "category": "c", "disclosure_date": dd,
            "url_or_pdf": url, "risk_type": rt, "severity": sev}] if sev else []
    return {"status": status, "events": evs, "had_pit_announcements": bool(evs)}


def _web(status, risk, action="downgrade", n_sources=1):
    # Slice 2 engine input shape: {"web_llm": {...}, "sources": [...]} (DeepSeek 判官产出)
    src = [{"title": "t", "url": "http://x/%d" % i, "source_type": "sina"} for i in range(n_sources)]
    return {"web_llm": {"status": status, "risk_level": risk, "action": action}, "sources": src}


class SemanticIntoM67(unittest.TestCase):
    """Slice 1/1b: cninfo official_structured folded into M6.7 via the semantic_official family.
    official high WITH complete evidence (non-empty url_or_pdf)→否决; high with blank URL→待核 (pending,
    never veto); medium/low→待核 (no penalty, no clear); clear/unknown/None→neutral; never rescues;
    machine.layer.semantic_risk trace; consistency preserved by construction."""
    GEN = "2026-06-09T00:00:00+08:00"

    def _report(self, semantic, **over):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized(**over)
        n["semantic"] = semantic
        r = build_m67_report(n, AS_OF, self.GEN)
        validate_m67_consistency(r)          # must ALWAYS stay consistent (table↔action, 否决→null, …)
        return r

    def test_high_official_forces_fouju_and_nulls_trade(self):
        r = self._report(_official("risk", "high", "立案调查"))
        self.assertEqual(r["m67"]["table"]["操作"], "否决")
        for k in ("股数", "入", "盈一", "盈二", "损"):
            self.assertIsNone(r["m67"]["table"][k])
        self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "veto")
        self.assertIn("语义官方", r["m67"]["精简结论区"]["否决审查触发"])

    def test_medium_official_is_pending_no_penalty(self):
        base = self._report(None)
        self.assertEqual(base["m67"]["table"]["操作"], "建仓")
        r = self._report(_official("risk", "medium", "fund_occupation"))
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")                       # NOT downgraded
        self.assertEqual(r["m67"]["table"]["优先级"], base["m67"]["table"]["优先级"])  # star unchanged
        self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "pending")
        self.assertIn("语义待核", r["m67"]["精简结论区"]["否决审查触发"])
        self.assertTrue(any("semantic_pending_review" in o
                            for o in r["machine"]["layer"]["observe_only"]))

    def test_clear_unknown_none_are_neutral(self):
        base = self._report(None)
        for sem in (_official("clear"), _official("unknown"), None):
            r = self._report(sem)
            self.assertEqual(r["m67"]["table"]["操作"], base["m67"]["table"]["操作"])
            self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "none")
        self.assertEqual(self._report(None)["machine"]["layer"]["semantic_risk"]["official_status"],
                         "unknown")

    def test_semantic_never_rescues_base_hard_veto(self):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized(); n["derived"]["hard_veto"] = True       # base = 否决
        n["semantic"] = _official("clear")                        # semantic clear must NOT upgrade
        r = build_m67_report(n, AS_OF, self.GEN); validate_m67_consistency(r)
        self.assertEqual(r["m67"]["table"]["操作"], "否决")

    def test_invalid_semantic_input_fails_closed(self):
        # R-ASHORT-M67-SEMANTIC-OFFICIAL-INPUT-CONSISTENCY-GAP + ...-EVIDENCE-SHAPE-GAP: malformed /
        # inconsistent / non-PIT / fabricated provider output must ValueError before any report
        # (no action↔trace contradiction; residual/non-PIT evidence cannot trigger M6.7 否决).
        from runners.a_short_phase5_engine import build_m67_report
        ev = {"source": "cninfo", "title": "t", "category": "c", "disclosure_date": "20260601",
              "url_or_pdf": "u", "risk_type": "立案", "severity": "high"}    # one valid PIT event
        bad_inputs = [
            {"status": "clear", "events": [ev]},                        # clear cannot carry events
            {"status": "unknown", "events": [ev]},                      # unknown cannot carry events
            {"events": [ev]},                                           # missing status
            {"status": "risk", "events": []},                           # risk must carry an event
            {"status": "risk", "events": [{**ev, "severity": "huge"}]}, # invalid severity
            {"status": "risk", "events": "abc"},                        # non-list events
            {"status": "risk", "events": ["x"]},                        # non-dict event
            "not-a-dict",                                               # non-dict semantic
            {"status": "risk", "events": [{"severity": "high", "risk_type": "x"}]},  # severity-only, no evidence
            {"status": "risk", "events": [{**ev, "source": "web"}]},    # non-official (manual/web) source
            {"status": "risk", "events": [{**ev, "disclosure_date": "20260701"}]},   # future date > as_of
            {"status": "risk", "events": [{**ev, "disclosure_date": "notadate"}]},   # non-canonical date
            {"status": "risk", "events": [{k: v for k, v in ev.items() if k != "risk_type"}]},  # missing risk_type
            {"status": "risk", "events": [{**ev, "risk_type": ""}]},                  # blank risk_type
            {"status": "risk", "events": [{**ev, "title": ""}]},                      # blank title
            {"status": "risk", "events": [{**ev, "category": ""}]},                   # blank category
            {"status": "risk", "events": [{**ev, "url_or_pdf": 123}]},                # url_or_pdf non-string
            {"status": "risk", "events": [{**ev, "title": "   "}]},                   # whitespace-only title
            {"status": "risk", "events": [ev], "had_pit_announcements": False},       # risk but no PIT
            {"status": "risk", "events": [ev]},                                       # missing had_pit_announcements
        ]
        # NOTE: blank url_or_pdf is NOT fail-closed here — Slice 1b approach A demotes it to 待核
        # (see test_high_with_empty_url_demotes_to_pending), it must not abort.
        for bad in bad_inputs:
            n = _normalized(); n["semantic"] = bad
            with self.assertRaises(ValueError):
                build_m67_report(n, AS_OF, self.GEN)

    def test_consumption_map_states_evidence_full_rule_not_generic(self):
        # R-ASHORT-M67-EVIDENCE-FULL-RUNTIME-EXPLANATION-DRIFT: the runtime consumption trace
        # (machine.consumption.semantic) must state the evidence-full rule, not the old generic
        # a generic "veto on any official high" — else the trace contradicts the blank-URL pending behavior.
        cm = self._report(_official("risk", "high", "立案调查"))["machine"]["consumption"]["semantic"]
        for kw in ("url_or_pdf", "证据齐全", "待核"):
            self.assertIn(kw, cm, f"consumption.semantic lost evidence-full anchor: {kw}")

    def test_high_with_empty_url_demotes_to_pending(self):
        # Slice 1b approach A: a high event with blank/whitespace url_or_pdf is evidence-incomplete →
        # 待核 (NOT 否决, NOT crash); only full-evidence high vetoes.
        for blank in ("", "   "):
            r = self._report(_official("risk", "high", "立案调查", url=blank))
            self.assertEqual(r["m67"]["table"]["操作"], "建仓")        # demoted, not 否决
            sr = r["machine"]["layer"]["semantic_risk"]
            self.assertEqual(sr["impact"], "pending")
            self.assertEqual(sr["evidence_incomplete_high"], 1)
            self.assertEqual(sr["severity_max"], "high")               # severity honest, impact demoted
            self.assertIn("缺 URL/PDF", r["m67"]["精简结论区"]["否决审查触发"])

    def test_full_url_high_vetoes_even_alongside_a_blank_url_high(self):
        sem = {"status": "risk", "had_pit_announcements": True, "events": [
            {"source": "cninfo", "title": "t", "category": "c", "disclosure_date": "20260601",
             "url_or_pdf": "u", "risk_type": "立案", "severity": "high"},
            {"source": "cninfo", "title": "t2", "category": "c", "disclosure_date": "20260601",
             "url_or_pdf": "", "risk_type": "处罚", "severity": "high"}]}
        r = self._report(sem)
        self.assertEqual(r["m67"]["table"]["操作"], "否决")            # full-evidence high still vetoes
        self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "veto")

    def test_normalize_semantic_param_threads_through_build_weekly(self):
        n = normalize_candidate(_egs_candidate(), _series(), _overlay_row(), 55.0,
                                {"available_cash": 500000.0}, "震荡期",
                                semantic=_official("risk", "high", "立案调查"))
        self.assertEqual(n["semantic"]["status"], "risk")
        w = build_weekly_report([n], AS_OF, self.GEN)
        self.assertEqual(w["reports"][0]["m67"]["table"]["操作"], "否决")


class SemanticWebLLMIntoM67(unittest.TestCase):
    """Slice 2: DeepSeek web_llm folded into M6.7 via the semantic_web_llm family.
    web risk/risk_candidate/headwind WITH sources → downgrade (**NEVER hard_veto**); tailwind/clear_light →
    no downgrade + never rescues hard risk; unknown/None → neutral; contract-violating/malformed web →
    neutralized with a trace flag (advisory non-blocking, NOT a fail-closed abort like official)."""
    GEN = "2026-06-09T00:00:00+08:00"

    def _report(self, web, **over):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized(**over)
        n["semantic_web_llm"] = web
        r = build_m67_report(n, AS_OF, self.GEN)
        validate_m67_consistency(r)              # must ALWAYS stay consistent
        return r

    def _wtrace(self, r):
        return r["machine"]["layer"]["semantic_risk"]["web_llm"]

    def _web_downgrades(self, r):
        return [d for d in r["machine"]["layer"]["downgrade"] if "语义web/LLM" in d]

    def test_web_risk_with_sources_downgrades_never_vetoes(self):
        r = self._report(_web("risk", "high"))
        self.assertNotEqual(r["m67"]["table"]["操作"], "否决")     # web NEVER hard_veto
        self.assertEqual(self._wtrace(r)["impact"], "downgrade")
        self.assertTrue(self._web_downgrades(r))

    def test_web_risk_candidate_and_headwind_downgrade(self):
        for st in ("risk_candidate", "headwind"):
            r = self._report(_web(st, "medium"))
            self.assertEqual(self._wtrace(r)["impact"], "downgrade")
            self.assertNotEqual(r["m67"]["table"]["操作"], "否决")
            self.assertTrue(self._web_downgrades(r))

    def test_web_tailwind_and_clear_light_no_downgrade(self):
        for web in (_web("tailwind", "low", action="no_action"),
                    _web("clear_light", "none", action="no_action")):
            r = self._report(web)
            self.assertEqual(self._wtrace(r)["impact"], "none")
            self.assertFalse(self._web_downgrades(r))

    def test_web_unknown_and_none_are_neutral(self):
        for web in (_web("unknown", "unknown", action="no_action", n_sources=0), None):
            r = self._report(web)
            self.assertEqual(self._wtrace(r)["status"], "unknown")
            self.assertEqual(self._wtrace(r)["impact"], "none")
            self.assertFalse(self._web_downgrades(r))

    def test_web_tailwind_never_rescues_official_hard_veto(self):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized()
        n["semantic"] = _official("risk", "high", "立案调查")     # official high → 否决
        n["semantic_web_llm"] = _web("tailwind", "low", action="no_action")
        r = build_m67_report(n, AS_OF, self.GEN); validate_m67_consistency(r)
        self.assertEqual(r["m67"]["table"]["操作"], "否决")        # web tailwind cannot upgrade

    def test_web_never_rescues_base_hard_veto(self):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized(); n["derived"]["hard_veto"] = True
        n["semantic_web_llm"] = _web("tailwind", "low", action="no_action")
        r = build_m67_report(n, AS_OF, self.GEN); validate_m67_consistency(r)
        self.assertEqual(r["m67"]["table"]["操作"], "否决")

    def test_invalid_web_neutralized_not_aborted(self):
        # advisory non-blocking: contract-violating / malformed web is NEUTRALIZED (trace flag), NOT raised
        # (unlike official's fail-closed abort). Each invalid shape → impact none + invalid_neutralized=True.
        bad = [
            _web("risk", "none"),                                              # risk ⇒ low/med/high
            {"web_llm": {"status": "risk", "risk_level": "high", "action": "downgrade"}, "sources": []},  # assessed needs sources
            _web("clear_light", "high", action="no_action"),                  # clear_light ⇒ none
            {"web_llm": {"status": "risk"}, "sources": [{"title": "t", "url": "u"}]},  # missing keys
            {"web_llm": "notdict", "sources": []},                            # web_llm non-dict
            {"sources": [{"title": "t", "url": "u"}]},                         # missing web_llm
        ]
        for w in bad:
            r = self._report(w)                                               # must NOT raise
            tr = self._wtrace(r)
            self.assertTrue(tr["invalid_neutralized"], f"not neutralized: {w}")
            self.assertEqual(tr["impact"], "none")
            self.assertEqual(tr["status"], "unknown")
            self.assertFalse(self._web_downgrades(r))

    def test_web_trace_populated_from_judgment(self):
        r = self._report(_web("risk", "medium", action="observe", n_sources=2))
        tr = self._wtrace(r)
        self.assertEqual((tr["status"], tr["risk_level"], tr["action"]), ("risk", "medium", "observe"))
        self.assertEqual(tr["sources_count"], 2)
        self.assertFalse(tr["invalid_neutralized"])

    def test_consumption_map_states_web_llm_rule(self):
        cm = self._report(None)["machine"]["consumption"]["semantic"]
        for kw in ("semantic_web_llm", "downgrade", "hard_veto"):
            self.assertIn(kw, cm, f"consumption.semantic lost web_llm anchor: {kw}")

    def test_web_provider_threads_through_normalize_and_build_weekly(self):
        n = normalize_candidate(_egs_candidate(), _series(), _overlay_row(), 55.0,
                                {"available_cash": 500000.0}, "震荡期",
                                semantic_web_llm=_web("risk", "high"))
        self.assertEqual(n["semantic_web_llm"]["web_llm"]["status"], "risk")
        w = build_weekly_report([n], AS_OF, self.GEN)
        wt = w["reports"][0]["machine"]["layer"]["semantic_risk"]["web_llm"]
        self.assertEqual(wt["impact"], "downgrade")


class DeepSeekWebProviderWiring(unittest.TestCase):
    """Slice 2 pipeline glue: _build_deepseek_web_llm_provider (em news fetch + DeepSeek judge, non-blocking).
    Injected fake news_fetcher(codes, names, as_of, lookback) + fake ds_client → no network. Covers per-code
    judge, no-items→None, no-key→whole-layer-None, fetch-failure→None, main-board Top15 gate (non-blocking)."""
    def _client(self, content):
        from tests.test_a_short_deepseek_semantic_adapter import _FakeClient
        return _FakeClient(content)

    def test_provider_judges_per_code_and_unknown_is_none(self):
        from runners.a_short_weekly_pipeline import _build_deepseek_web_llm_provider
        raws = [{"ts_code": "600000.SH", "ok": True, "items": [{"title": "公司被立案调查", "url": "u"}]},
                {"ts_code": "600001.SH", "ok": True, "items": []}]      # no items → judge unknown → None
        prov = _build_deepseek_web_llm_provider(
            ["600000.SH", "600001.SH"], {"600000.SH": "A", "600001.SH": "B"}, AS_OF,
            news_fetcher=lambda codes, names, as_of, lookback: raws,
            ds_client=self._client('{"status":"risk","risk_level":"high","action":"downgrade","summary":"立案"}'))
        self.assertIsNotNone(prov)
        self.assertEqual(prov("600000.SH")["web_llm"]["status"], "risk")
        self.assertEqual(prov("600000.SH")["sources"][0]["source_type"], "em")   # em-sourced evidence
        self.assertIsNone(prov("600001.SH"))                            # unknown → None (中性)

    def test_provider_none_without_client(self):
        import os
        from unittest import mock
        from runners.a_short_weekly_pipeline import _build_deepseek_web_llm_provider
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)                    # no key + no injected client
            prov = _build_deepseek_web_llm_provider(
                ["600000.SH"], {}, AS_OF, news_fetcher=lambda codes, names, as_of, lookback: [])
        self.assertIsNone(prov)                                         # whole web layer unknown (non-blocking)

    def test_provider_none_on_fetch_failure(self):
        from runners.a_short_weekly_pipeline import _build_deepseek_web_llm_provider
        def boom(codes, names, as_of, lookback):
            raise RuntimeError("em down")
        prov = _build_deepseek_web_llm_provider(["600000.SH"], {}, AS_OF, news_fetcher=boom,
                                                ds_client=self._client("{}"))
        self.assertIsNone(prov)                                         # fetch fail → non-blocking None

    def test_provider_filters_to_main_board_top15(self):
        # R-ASHORT-M67-DEEPSEEK-WEBLLM-TOP15-SCOPE-BYPASS: provider must reuse the official main_board_top15
        # gate BEFORE any em fetch / DeepSeek judge — only the deduped main-board Top15 is fetched, and a
        # non-main-board (or beyond-cap) candidate gets neutral None even if the weekly report still lists it.
        from runners.a_short_weekly_pipeline import _build_deepseek_web_llm_provider
        from runners.a_short_semantic_risk_probe import main_board_top15
        codes = [f"60{i:04d}.SH" for i in range(20)] + ["300750.SZ", "688111.SH"]  # 20 main + ChiNext + STAR
        main_codes, _ = main_board_top15(codes)
        self.assertLessEqual(len(main_codes), 15)
        self.assertNotIn("300750.SZ", main_codes)
        seen = {}
        def fetcher(cs, names, as_of, lookback):
            seen["codes"] = list(cs)
            return [{"ts_code": c, "ok": True, "items": [{"title": "公司被立案", "url": "u"}]} for c in cs]
        prov = _build_deepseek_web_llm_provider(
            codes, {}, AS_OF, news_fetcher=fetcher,
            ds_client=self._client('{"status":"risk","risk_level":"high","action":"downgrade","summary":"x"}'))
        self.assertEqual(seen["codes"], list(main_codes))    # fetcher 只收过滤后的主板 Top15(不含 300750/688/超界)
        self.assertNotIn("300750.SZ", seen["codes"])
        self.assertIsNone(prov("300750.SZ"))                 # 非主板候选 → 中性 None(不抓不判)
        self.assertIsNotNone(prov(main_codes[0]))            # 主板 Top15 内 → 正常判


class CashAllocationTests(unittest.TestCase):
    """#3 全局现金分配:多只建仓按区间上沿统一消耗 available_cash,确定性排序,归零转观察,过 schema+validator。"""
    def _builds(self):
        return [_normalized("600000.SH"), _normalized("600519.SH"), _normalized("601318.SH")]

    def test_no_account_no_cash_allocation(self):
        w = build_weekly_report([_normalized()], AS_OF, GEN)        # 默认 absent lineage + available_cash None
        self.assertIsNone(w["cash_allocation"])
        validate_weekly_report(w, _feed())                          # observation-only 一致(absent⟺cash_allocation None)

    def test_global_cash_allocation_demotes_under_budget_and_validates(self):
        # 全局现金不足 3 只满额 → 排序 rank1 满、靠后不足 → 转观察;sized lineage + 整份过 schema/validator。
        w = build_weekly_report(self._builds(), AS_OF, GEN, iv_feed_ref="iv_feed.json",
                                run_lineage=_sized_lineage(), available_cash=150000.0)
        ops = [r["m67"]["table"]["操作"] for r in w["reports"]]
        self.assertTrue(all(o in ("建仓", "观察") for o in ops))
        self.assertEqual(w["reports"][0]["m67"]["table"]["操作"], "建仓")   # rank1(index 0)满足
        self.assertIn("观察", ops)                                          # 现金不足 → 至少一只转观察(非伪建仓)
        cs = w["cash_allocation"]
        self.assertEqual(cs["available_cash_start"], 150000.0)
        self.assertLessEqual(cs["allocated_cash_total"], 150000.0 + 1e-6)
        self.assertGreaterEqual(cs["remaining_cash"], -1e-6)
        for r in w["reports"]:
            if r["m67"]["table"]["操作"] == "建仓":                          # 存活建仓:股数正 + 审计字段齐
                self.assertGreaterEqual(r["m67"]["table"]["股数"], 100)
                pl = r["machine"]["entry_exit_size_star"]["plan"]
                for fld in ("cash_allocation_rank", "cash_budget_used", "raw_shares", "allocated_shares"):
                    self.assertIsNotNone(pl.get(fld))
        with tempfile.TemporaryDirectory() as td:    # write_weekly_report = jsonschema + validate_weekly_report
            write_weekly_report(w, _feed(), str(Path(td) / "w.json"))

    def test_cash_allocation_deterministic(self):
        a = build_weekly_report(self._builds(), AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=150000.0)
        b = build_weekly_report(self._builds(), AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=150000.0)
        self.assertEqual([r["m67"]["table"]["股数"] for r in a["reports"]],
                         [r["m67"]["table"]["股数"] for r in b["reports"]])
        self.assertEqual(a["cash_allocation"], b["cash_allocation"])

    def test_ample_cash_demotes_nothing(self):
        # C 反向失败:现金充裕时不得过度降级——全部保持建仓,剩余现金>0(防把够钱的建仓错降为观察)。
        w = build_weekly_report(self._builds(), AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=10_000_000.0)
        ops = [r["m67"]["table"]["操作"] for r in w["reports"]]
        self.assertTrue(all(o == "建仓" for o in ops))
        self.assertGreater(w["cash_allocation"]["remaining_cash"], 0)
        validate_weekly_report(w, _feed())

    def test_sized_lineage_without_cash_allocation_rejected(self):
        # 对抗矛盾①:声称账户定量(sized)却无 cash_allocation → 必拒(防静默跳过全局分配,重开过度分配 bug)。
        w = build_weekly_report(self._builds(), AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=None)
        self.assertIsNone(w["cash_allocation"])
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_observation_lineage_with_cash_allocation_rejected(self):
        # 对抗矛盾②:声称无账户(observation-only,默认 lineage)却带 cash_allocation 对象 → 必拒。
        w = build_weekly_report(self._builds(), AS_OF, GEN, available_cash=150000.0)   # 默认 absent lineage
        self.assertIsNotNone(w["cash_allocation"])
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def _sized_weekly(self):
        return build_weekly_report(self._builds(), AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=150000.0)

    def _first_build(self, w):
        return next(r for r in w["reports"] if r["m67"]["table"]["操作"] == "建仓")

    def test_forged_allocated_shares_rejected(self):
        # audit-math:伪造 allocated_shares(≠ shares/table 股数)→ 必拒(防伪造分配冒充已做全局现金分配)。
        w = self._sized_weekly()
        self._first_build(w)["machine"]["entry_exit_size_star"]["plan"]["allocated_shares"] = 999999
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_forged_cash_budget_used_rejected(self):
        # audit-math:伪造 cash_budget_used(≠ round(shares×entry_high,2))→ 必拒。
        w = self._sized_weekly()
        self._first_build(w)["machine"]["entry_exit_size_star"]["plan"]["cash_budget_used"] = 0.01
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_forged_weekly_cash_summary_rejected(self):
        # audit-math:伪造 cash_allocation 摘要(allocated_cash_total/remaining_cash 与 Σ 不符)→ 必拒。
        w = self._sized_weekly()
        w["cash_allocation"]["allocated_cash_total"] = 1.0
        w["cash_allocation"]["remaining_cash"] = 999999.0
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())


class _StubDividendPro:
    """测试用 tushare pro 桩:dividend() 返回注入的 DataFrame(测 _fetch_dividends 的列/过滤逻辑,不抓网络)。"""
    def __init__(self, df):
        self._df = df

    def dividend(self, **kwargs):
        return self._df


class ExDivNoticeTests(unittest.TestCase):
    """#1 除权除息提示(advisory,不改决策):PIT(ann≤as_of)+ 窗口(as_of..as_of+14)+ 每票最近;过 schema/validator/render。"""
    def _prov(self, mapping):
        return lambda code: mapping.get(code, [])

    def test_in_window_pit_announced(self):
        prov = self._prov({"600000.SH": [{"ann_date": "20260601", "ex_date": "20260615"}]})
        n = _ex_div_notices([("600000.SH", "甲")], AS_OF, prov)     # AS_OF=20260609 → 6 天
        self.assertEqual(len(n), 1)
        self.assertEqual((n[0]["ex_date"], n[0]["days_to_ex"]), ("20260615", 6))

    def test_outside_window_excluded(self):
        prov = self._prov({"600000.SH": [{"ann_date": "20260601", "ex_date": "20260710"}]})   # >14 天
        self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, prov), [])

    def test_lookahead_announcement_excluded(self):
        # ann_date 晚于 as_of → 该除权在 as_of 时尚未公告,提示即 look-ahead → 剔除
        prov = self._prov({"600000.SH": [{"ann_date": "20260612", "ex_date": "20260615"}]})
        self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, prov), [])

    def test_bad_ex_date_skipped_no_fabrication(self):
        prov = self._prov({"600000.SH": [{"ann_date": "20260601", "ex_date": "2026XX15"}]})
        self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, prov), [])

    def test_no_provider_empty(self):
        self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, None), [])

    def test_nearest_per_code(self):
        prov = self._prov({"600000.SH": [{"ann_date": "20260601", "ex_date": "20260620"},
                                          {"ann_date": "20260601", "ex_date": "20260611"}]})
        n = _ex_div_notices([("600000.SH", "甲")], AS_OF, prov)
        self.assertEqual([x["ex_date"] for x in n], ["20260611"])     # 同票取最近一次

    def test_weekly_attach_schema_validator_render(self):
        w = build_weekly_report([_normalized()], AS_OF, GEN)
        w["ex_div_notices"] = [{"ts_code": "600000.SH", "name": "甲", "ex_date": "20260615", "days_to_ex": 6}]
        with tempfile.TemporaryDirectory() as td:    # write = jsonschema + validate_weekly_report
            write_weekly_report(w, _feed(), str(Path(td) / "w.json"))
        md = render_weekly_markdown(w)
        self.assertIn("除权除息提示", md)
        self.assertIn("20260615", md)

    def test_validator_rejects_inconsistent_days(self):
        w = build_weekly_report([_normalized()], AS_OF, GEN)
        w["ex_div_notices"] = [{"ts_code": "600000.SH", "name": "甲", "ex_date": "20260615", "days_to_ex": 99}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_missing_ann_date_no_notice(self):
        # PIT-EVIDENCE-GAP 修复:无 ann_date → 无法证 as_of 时已公告 → 不提示(防 look-ahead)
        prov = self._prov({"600000.SH": [{"ex_date": "20260615"}]})   # 缺 ann_date
        self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, prov), [])

    def test_validator_rejects_foreign_ts(self):
        # VALIDATOR-GUARD-GAP 修复:提示 ts_code 不在本周候选/持仓 → 必拒(张冠李戴)
        w = build_weekly_report([_normalized()], AS_OF, GEN)           # report ts=600000.SH
        w["ex_div_notices"] = [{"ts_code": "999999.SH", "name": "无关", "ex_date": "20260615", "days_to_ex": 6}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_rejects_far_window(self):
        # VALIDATOR-GUARD-GAP 修复:超 14 日窗口的提示 → 必拒(20260609→20260709=30 天)
        w = build_weekly_report([_normalized()], AS_OF, GEN)
        w["ex_div_notices"] = [{"ts_code": "600000.SH", "name": "甲", "ex_date": "20260709", "days_to_ex": 30}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_blank_or_invalid_ann_date_no_notice(self):
        # PIT 证据:空白/非法 ann_date 同样无法证 PIT → 不提示
        for bad in ("", "   ", "2026XX01"):
            prov = self._prov({"600000.SH": [{"ann_date": bad, "ex_date": "20260615"}]})
            self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, prov), [], f"ann={bad!r}")

    def test_fetch_dividends_fail_closed_missing_div_proc_column(self):
        # _fetch_dividends fail-closed:provider 响应缺 div_proc 列 → 无法证 实施 → []
        df = pd.DataFrame([{"ts_code": "600000.SH", "ann_date": "20260601", "ex_date": "20260615"}])
        self.assertEqual(_fetch_dividends(_StubDividendPro(df), "600000.SH"), [])

    def test_fetch_dividends_filters_to_shishi(self):
        df = pd.DataFrame([{"ts_code": "600000.SH", "ann_date": "20260601", "div_proc": "预案", "ex_date": "20260615"},
                           {"ts_code": "600000.SH", "ann_date": "20260602", "div_proc": "实施", "ex_date": "20260616"}])
        self.assertEqual(_fetch_dividends(_StubDividendPro(df), "600000.SH"),
                         [{"ann_date": "20260602", "ex_date": "20260616"}])   # 仅 实施

    def test_validator_accepts_manual_review_holding_notice(self):
        # 正向:提示 ts_code 属 holdings_manual_review(无价持仓)→ validator 接受(在周报 universe 内)
        w = build_weekly_report([_normalized()], AS_OF, GEN)
        w["holdings_manual_review"] = [{"ts_code": "600519.SH", "name": "乙", "reason": "停牌"}]
        w["ex_div_notices"] = [{"ts_code": "600519.SH", "name": "乙", "ex_date": "20260615", "days_to_ex": 6}]
        validate_weekly_report(w, _feed())     # 不 raise


if __name__ == "__main__":
    unittest.main()
