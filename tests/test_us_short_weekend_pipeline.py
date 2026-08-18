# -*- coding: utf-8 -*-
"""Tests for the US-short weekend-pipeline selection front (engine/us_short_weekend_pipeline.py) — batch4 slice 4d-i.

Design authority: docs/us_short_system_design.md §2 / §2.1 / §4.0 / §18.2.

Covers the wired selection front end-to-end over an INJECTED data_context: canonical decision-day
threading, the intraday DEAD-ZONE no-emit, Pass1 cheap-eligibility filtering, catalyst_recall
injection, Pass2 audit-safety-gate (candidate exclusion on entry_hard_veto; holdings forced in with
veto surfaced), canonical ticker identity flowing through, and fail-closed data_context shape.
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_pipeline as wp  # noqa: E402
from engine.us_short_eligibility_gate import load_eligibility_governance  # noqa: E402
from engine.us_short_selection_exclusions import build_selection_exclusion_data  # noqa: E402

_SESSIONS = [{"date": "20260612"}, {"date": "20260615"}, {"date": "20260616"}]  # Fri / Mon / Tue (16:00)
_PRESET = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"


def _now(date, hh, mm):
    return datetime(int(date[:4]), int(date[4:6]), int(date[6:]), hh, mm)


def _univ_row(ticker, exchange="NASDAQ", price=150.0, adv=1.0e10, mcap=2.5e12, **status):
    r = {"ticker": ticker, "exchange": exchange, "price": price, "adv_usd": adv, "market_cap_usd": mcap,
         "delisted": False, "halted": False, "bankruptcy": False, "otc": False}
    r.update(status)
    return r


def _selection_inputs(tickers, *, state="no_strong_theme", core_scores=None, theme_scores=None,
                      theme_selection_contract=None):
    core_scores = core_scores or {}
    theme_scores = theme_scores or {}
    return {"theme_opportunity_state": state,
            "theme_selection_contract": theme_selection_contract or _theme_selection_contract(tickers, state=state),
            "per_ticker": {t: {"core_score": core_scores.get(t, 50.0),
                               "theme_momentum_score": theme_scores.get(t, 0.0)}
                           for t in tickers}}


def _theme_selection_contract(tickers, *, lifecycle_by_ticker=None, origin_by_ticker=None,
                              source_by_ticker=None, leader_rs_by_ticker=None, theme_id_by_ticker=None,
                              market_confirmed_by_ticker=None, individual_gate_by_ticker=None,
                              overextension_by_ticker=None,
                              mode="industry_heat_v1_cross_industry_disabled", state="no_strong_theme"):
    lifecycle_by_ticker = lifecycle_by_ticker or {}
    origin_by_ticker = origin_by_ticker or {}
    source_by_ticker = source_by_ticker or {}
    leader_rs_by_ticker = leader_rs_by_ticker or {}
    theme_id_by_ticker = theme_id_by_ticker or {}
    market_confirmed_by_ticker = market_confirmed_by_ticker or {}
    individual_gate_by_ticker = individual_gate_by_ticker or {}
    overextension_by_ticker = overextension_by_ticker or {}
    return {
        "as_of": "20260615",
        "mode": mode,
        "cross_industry_provisional_enabled": mode != "industry_heat_v1_cross_industry_disabled",
        "theme_opportunity_state": state,
        "per_ticker": {
            ticker: {
                "theme_id": theme_id_by_ticker.get(ticker, "industry:" + ticker),
                "theme_source": source_by_ticker.get(ticker, "industry_heat_v1"),
                "theme_lifecycle_state": lifecycle_by_ticker.get(ticker, "confirmed_active"),
                "theme_leader_rs": leader_rs_by_ticker.get(ticker, 0.0),
                "membership_origin": origin_by_ticker.get(ticker, "automatic_discovery"),
                "market_confirmed": market_confirmed_by_ticker.get(ticker, True),
                "individual_theme_gate_passed": individual_gate_by_ticker.get(ticker, True),
                "overextension_state": overextension_by_ticker.get(ticker, "none"),
                "macro_cluster": "unclassified_conservative",
            }
            for ticker in tickers
        },
    }


def _dc(universe, *, recall=None, holdings=None, pass2=None, selection_inputs=None,
        pass1_exclusion_summary=None):
    pass2 = pass2 or {}
    if selection_inputs is None:
        selection_inputs = _selection_inputs(list(pass2))
    dc = {"universe": universe, "catalyst_recall_feed": recall,
          "holdings": holdings or [], "candidate_pass2_signals": pass2,
          "selection_inputs": selection_inputs}
    if pass1_exclusion_summary is not None:
        dc["pass1_exclusion_summary"] = pass1_exclusion_summary
    return dc


class RunSelectionTests(unittest.TestCase):
    def setUp(self):
        self.gov = load_eligibility_governance(_PRESET)

    def _run(self, dc, now=("20260613", 10, 0)):
        return wp.run_selection(_now(*now), _SESSIONS, dc, eligibility_governance=self.gov)

    def test_happy_path_selection(self):
        dc = _dc([_univ_row("AAPL"), _univ_row("PENNY", price=1.0), _univ_row("OTCX", exchange="OTC")],
                 pass2={"AAPL": {}})
        out = self._run(dc)
        self.assertFalse(out["out_of_window"])
        self.assertEqual(out["decision_date"], "20260615")     # Sat -> upcoming Mon
        self.assertEqual(out["price_basis_date"], "20260612")  # prior Fri
        self.assertEqual(out["cheap_eligible"], ["AAPL"])      # PENNY below floor, OTCX off-whitelist
        self.assertEqual(out["candidates"], ["AAPL"])
        self.assertEqual(out["admitted"], ["AAPL"])

    def test_out_of_window_no_emit(self):
        out = self._run(_dc([_univ_row("AAPL")]), now=("20260615", 11, 0))  # Mon 11:00 = intraday dead zone
        self.assertTrue(out["out_of_window"])
        self.assertIsNone(out["decision_date"])
        self.assertEqual(out["candidates"], [])
        self.assertEqual(out["admitted"], [])

    def test_catalyst_recall_off_universe_excluded(self):
        # MSFT recalled but NOT an active universe row → floored out (recall_excluded), never admitted ahead of
        # AAPL (the finding's off-universe probe); the candidate set stays the cheap-eligible universe names only.
        out = self._run(_dc([_univ_row("AAPL")], recall=["MSFT"], pass2={"AAPL": {}}))
        self.assertTrue(out["recall_available"])
        self.assertEqual(out["candidates"], ["AAPL"])
        self.assertEqual(out["recall_added"], [])
        self.assertEqual(out["recall_excluded"], [{"ticker": "MSFT", "reason": "off_universe"}])

    def test_catalyst_feed_none_no_fabrication(self):
        out = self._run(_dc([_univ_row("AAPL")], recall=None, pass2={"AAPL": {}}))
        self.assertFalse(out["recall_available"])
        self.assertEqual(out["recall_added"], [])

    def test_duplicate_universe_identity_rejected(self):
        # two canonical-AAPL universe rows (one eligible, one below-floor) → fail closed; the floor verdict map
        # must NOT silently last-row-wins (R-USSHORT-BATCH4-SELECTION-TRACE-AND-RECALL-CLOSURE-GAP).
        for order in ([_univ_row("AAPL"), _univ_row("AAPL", price=0.5)],            # eligible then below-floor
                      [_univ_row("AAPL", price=0.5), _univ_row("AAPL")],            # below-floor then eligible
                      [_univ_row("AAPL"), _univ_row("aapl")]):                      # case-variant same identity
            with self.assertRaises(wp.WeekendPipelineError):
                self._run(_dc(order, pass2={"AAPL": {}}))

    def test_pass2_excludes_entry_hard_veto_candidate(self):
        # both cheap-eligible (clean Pass1 status); Pass2 SEC-audit finds BADX delisted -> excluded
        dc = _dc([_univ_row("AAPL"), _univ_row("BADX")],
                 pass2={"AAPL": {}, "BADX": {"delisted": True}},
                 selection_inputs=_selection_inputs(["AAPL"]))
        out = self._run(dc)
        self.assertEqual(out["candidates"], ["AAPL", "BADX"])
        self.assertIn("AAPL", out["admitted"])
        self.assertNotIn("BADX", out["admitted"])
        self.assertEqual(out["exclusion_records"], [{
            "stage": "pass2_audit_gate", "ticker": "BADX", "category": "停牌退市破产",
            "reasons": ["5.1a:退市"],
        }])

    def test_pass1_rejects_are_retained_with_frozen_categories(self):
        low_adv = _univ_row("ILLIQ", adv=1.0)
        penny = _univ_row("PENNY", price=1.0)
        otc = _univ_row("OTCX", exchange="OTC")
        unknown = _univ_row("MISS")
        unknown["price"] = None
        out = self._run(_dc([_univ_row("AAPL"), low_adv, penny, otc, unknown], pass2={"AAPL": {}}))
        by_ticker = {r["ticker"]: r for r in out["exclusion_records"]}
        self.assertEqual(by_ticker["ILLIQ"]["category"], "流动性")
        self.assertEqual(by_ticker["PENNY"]["category"], "价格市值")
        self.assertEqual(by_ticker["OTCX"]["category"], "停牌退市破产")
        self.assertEqual(by_ticker["MISS"]["category"], "数据unknown")
        summary = build_selection_exclusion_data(out)
        self.assertEqual(summary["stage_counts"], {
            "pass1_eligibility": 4, "pass2_audit_gate": 0, "top15_selection": 0,
        })
        self.assertEqual(sum(row["public_count"] for row in summary["categories"].values()), 4)

    def test_mixed_source_pass1_summary_is_mutually_exclusive_and_recall_is_separate(self):
        # BOTH fails price and ADV together; the upstream summary carries one primary Pass1 ticket,
        # while recall_excluded may name the same ticker without entering the exclusion total.
        pass1_summary = {
            "total_excluded": 1,
            "category_counts": {
                "流动性": 1, "价格市值": 0, "停牌退市破产": 0, "增发SEC": 0,
                "数据unknown": 0, "事件unknown": 0, "数据源失败": 0, "分不够": 0,
            },
        }
        out = self._run(_dc(
            [_univ_row("AAPL"), _univ_row("BOTH", price=1.0, adv=1.0)],
            recall=["BOTH"], pass2={"AAPL": {}}, selection_inputs=_selection_inputs(["AAPL"]),
            pass1_exclusion_summary=pass1_summary,
        ))
        self.assertEqual(out["recall_excluded"], [{"ticker": "BOTH", "reason": "below_floor"}])
        self.assertFalse(any(row["stage"] == "pass1_eligibility" for row in out["exclusion_records"]))
        report_selection = {**out, "pass1_exclusion_summary": pass1_summary}
        exclusion_data = build_selection_exclusion_data(report_selection)
        self.assertEqual(exclusion_data["stage_counts"], {
            "pass1_eligibility": 1, "pass2_audit_gate": 0, "top15_selection": 0,
        })
        self.assertEqual(exclusion_data["categories"]["流动性"]["public_count"], 1)
        self.assertEqual(exclusion_data["catalyst_recall_rejected_count"], 1)

    def test_mixed_source_pass1_summary_mismatch_fails_before_selection(self):
        bad_summary = {
            "total_excluded": 0,
            "category_counts": {
                "流动性": 0, "价格市值": 0, "停牌退市破产": 0, "增发SEC": 0,
                "数据unknown": 0, "事件unknown": 0, "数据源失败": 0, "分不够": 0,
            },
        }
        dc = _dc([_univ_row("AAPL"), _univ_row("LOW", adv=1.0)],
                 pass2={"AAPL": {}}, selection_inputs=_selection_inputs(["AAPL"]),
                 pass1_exclusion_summary=bad_summary)
        with self.assertRaises(wp.WeekendPipelineError):
            wp.run_selection(_now("20260613", 10, 0), _SESSIONS, dc,
                             eligibility_governance=self.gov,
                             require_pass1_exclusion_summary=True)

    def test_mixed_source_requires_upstream_pass1_summary(self):
        dc = _dc([_univ_row("AAPL")], pass2={"AAPL": {}})
        with self.assertRaises(wp.WeekendPipelineError):
            wp.run_selection(_now("20260613", 10, 0), _SESSIONS, dc,
                             eligibility_governance=self.gov,
                             require_pass1_exclusion_summary=True)

    def test_public_builder_rejects_local_pass1_record_when_upstream_summary_exists(self):
        summary = {
            "total_excluded": 0,
            "category_counts": {
                "流动性": 0, "价格市值": 0, "停牌退市破产": 0, "增发SEC": 0,
                "数据unknown": 0, "事件unknown": 0, "数据源失败": 0, "分不够": 0,
            },
        }
        out = self._run(_dc([_univ_row("AAPL")], pass2={"AAPL": {}},
                             pass1_exclusion_summary=summary))
        forged = {**out, "pass1_exclusion_summary": summary,
                  "exclusion_records": [{
                      "stage": "pass1_eligibility", "ticker": "AAPL", "category": "价格市值",
                      "reasons": ["price_below_floor"],
                  }]}
        with self.assertRaises(ValueError):
            build_selection_exclusion_data(forged)

    def test_real_pass1_exclusion_joins_same_run_heat_without_rescue(self):
        contract = _theme_selection_contract(["AAPL"])
        contract["hot_excluded_audit"] = {
            "heat_threshold": 90.0,
            "per_ticker": {"AAPL": 50.0, "ILLIQ": 95.0},
        }
        out = self._run(_dc(
            [_univ_row("AAPL"), _univ_row("ILLIQ", adv=1.0)],
            pass2={"AAPL": {}},
            selection_inputs=_selection_inputs(["AAPL"], theme_selection_contract=contract),
        ))
        hot = build_selection_exclusion_data(out)["hot_excluded"]
        self.assertEqual(hot["public_heat_count"], 1)
        self.assertEqual(hot["unevaluable_count"], 0)
        self.assertEqual(out["admitted"], ["AAPL"])
        self.assertEqual(out["hot_excluded_audit"]["source_digest"], out["theme_contract_digest"])

    def test_pass2_offering_and_top15_score_reject_are_retained(self):
        tickers = ["A%02d" % i for i in range(16)] + ["OFFER"]
        pass2 = {t: {} for t in tickers}
        pass2["OFFER"] = {"active_offering": {"recency": "recent", "status": "active",
                                                    "materiality": "material"}}
        clean_for_scoring = tickers[:-1]
        out = self._run(_dc([_univ_row(t) for t in tickers], pass2=pass2,
                            selection_inputs=_selection_inputs(clean_for_scoring)))
        by_ticker = {r["ticker"]: r for r in out["exclusion_records"]}
        self.assertEqual(by_ticker["OFFER"]["category"], "增发SEC")
        self.assertEqual(by_ticker["A15"]["category"], "分不够")
        self.assertEqual(by_ticker["A15"]["stage"], "top15_selection")
        summary = build_selection_exclusion_data(out)
        self.assertEqual(summary["stage_counts"], {
            "pass1_eligibility": 0, "pass2_audit_gate": 1, "top15_selection": 1,
        })
        self.assertEqual(sum(row["public_count"] for row in summary["categories"].values()), 2)

    def test_top15_cap_enforced_for_pass2_clean_candidates(self):
        tickers = ["A%02d" % i for i in range(16)]
        dc = _dc([_univ_row(t) for t in tickers], pass2={t: {} for t in tickers})
        out = self._run(dc)
        self.assertEqual(len(out["admitted"]), 15)
        self.assertNotIn("A15", out["admitted"])

    def test_dynamic_seats_select_core_and_theme_buckets(self):
        core = ["C%02d" % i for i in range(13)]
        theme = ["T%02d" % i for i in range(5)]
        tickers = core + theme
        core_scores = {t: 100.0 - i for i, t in enumerate(core)}
        core_scores.update({t: 10.0 - i for i, t in enumerate(theme)})
        theme_scores = {t: 1.0 for t in core}
        theme_scores.update({t: 100.0 - i for i, t in enumerate(theme)})
        dc = _dc([_univ_row(t) for t in tickers], pass2={t: {} for t in tickers},
                 selection_inputs=_selection_inputs(
                     tickers, state="no_strong_theme", core_scores=core_scores, theme_scores=theme_scores))
        out = self._run(dc)
        self.assertEqual(out["selection_seats"], {"core_top": 12, "theme_momentum": 3})
        self.assertEqual(set(out["admitted"]), set(core[:12] + theme[:3]))
        self.assertNotIn("C12", out["admitted"])
        self.assertNotIn("T03", out["admitted"])
        self.assertEqual({d["ticker"]: d["selection_bucket"] for d in out["selection_details"] if d["ticker"] in theme[:3]},
                         {t: "theme_momentum" for t in theme[:3]})

    def test_decayed_theme_cannot_take_theme_seat_and_contract_is_reported(self):
        core = ["C%02d" % i for i in range(13)]
        theme = ["T%02d" % i for i in range(4)]
        tickers = core + theme
        core_scores = {ticker: 100.0 - i for i, ticker in enumerate(core)}
        core_scores.update({ticker: 10.0 - i for i, ticker in enumerate(theme)})
        theme_scores = {ticker: 1.0 for ticker in core}
        theme_scores.update({ticker: 100.0 - i for i, ticker in enumerate(theme)})
        selection_inputs = _selection_inputs(
            tickers, state="no_strong_theme", core_scores=core_scores, theme_scores=theme_scores)
        selection_inputs["theme_selection_contract"] = _theme_selection_contract(
            tickers, lifecycle_by_ticker={"T00": "decayed"})
        out = self._run(_dc([_univ_row(ticker) for ticker in tickers],
                            pass2={ticker: {} for ticker in tickers}, selection_inputs=selection_inputs))
        self.assertNotIn("T00", out["admitted"])
        self.assertEqual(out["theme_selection_mode"], "industry_heat_v1_cross_industry_disabled")

    def test_cooling_theme_has_halved_theme_seat_capacity(self):
        core = ["C%02d" % i for i in range(13)]
        theme = ["T%02d" % i for i in range(4)]
        tickers = core + theme
        core_scores = {ticker: 100.0 - i for i, ticker in enumerate(core)}
        core_scores.update({ticker: 10.0 - i for i, ticker in enumerate(theme)})
        theme_scores = {ticker: 1.0 for ticker in core}
        theme_scores.update({ticker: 100.0 - i for i, ticker in enumerate(theme)})
        selection_inputs = _selection_inputs(
            tickers, state="no_strong_theme", core_scores=core_scores, theme_scores=theme_scores)
        selection_inputs["theme_selection_contract"] = _theme_selection_contract(
            tickers, lifecycle_by_ticker={ticker: "cooling" for ticker in theme},
            theme_id_by_ticker={ticker: "industry:cooling" for ticker in theme})
        out = self._run(_dc([_univ_row(ticker) for ticker in tickers],
                            pass2={ticker: {} for ticker in tickers}, selection_inputs=selection_inputs))
        by_ticker = {row["ticker"]: row for row in out["selection_details"]}
        cooled_theme_seats = [ticker for ticker in theme if by_ticker.get(ticker, {}).get("selection_bucket") == "theme_momentum"]
        self.assertEqual(cooled_theme_seats, ["T00"])  # floor(3 × 0.5) = one theme seat

    def test_theme_seats_reserve_automatic_discovery_and_cap_manual_watchlist(self):
        core = ["C%02d" % i for i in range(8)]
        auto = ["A%02d" % i for i in range(4)]
        manual = ["M%02d" % i for i in range(4)]
        tickers = core + auto + manual
        core_scores = {ticker: 100.0 - i for i, ticker in enumerate(core)}
        core_scores.update({ticker: 10.0 for ticker in auto + manual})
        theme_scores = {ticker: 1.0 for ticker in core}
        theme_scores.update({ticker: 60.0 - i for i, ticker in enumerate(auto)})
        theme_scores.update({ticker: 100.0 - i for i, ticker in enumerate(manual)})
        selection_inputs = _selection_inputs(
            tickers, state="strong", core_scores=core_scores, theme_scores=theme_scores)
        selection_inputs["theme_selection_contract"] = _theme_selection_contract(
            tickers, state="strong",
            origin_by_ticker={ticker: "manual_watchlist" for ticker in manual})
        out = self._run(_dc([_univ_row(ticker) for ticker in tickers],
                            pass2={ticker: {} for ticker in tickers}, selection_inputs=selection_inputs))
        theme_rows = [row for row in out["selection_details"] if row["selection_bucket"] == "theme_momentum"]
        origins = [row["theme_selection"]["membership_origin"] for row in theme_rows]
        self.assertGreaterEqual(origins.count("automatic_discovery"), 2)
        self.assertLessEqual(origins.count("manual_watchlist"), 2)

    def test_same_theme_crowding_cap_and_leader_upgrade_are_applied_before_analysis(self):
        core = ["C%02d" % i for i in range(8)]
        crowded = ["T%02d" % i for i in range(4)]
        other = ["O%02d" % i for i in range(3)]
        tickers = core + crowded + other
        core_scores = {ticker: 100.0 - i for i, ticker in enumerate(core)}
        core_scores.update({ticker: 10.0 for ticker in crowded + other})
        theme_scores = {ticker: 1.0 for ticker in core}
        theme_scores.update({ticker: 100.0 - i for i, ticker in enumerate(crowded + other)})
        selection_inputs = _selection_inputs(
            tickers, state="strong", core_scores=core_scores, theme_scores=theme_scores)
        selection_inputs["theme_selection_contract"] = _theme_selection_contract(
            tickers, state="strong",
            theme_id_by_ticker={ticker: "industry:crowded" for ticker in crowded},
            leader_rs_by_ticker={"T00": 10.0, "T01": 30.0, "T02": 20.0, "T03": 40.0,
                                 "O00": 5.0, "O01": 4.0, "O02": 3.0},
            overextension_by_ticker={"T03": "chasing_extreme"})
        out = self._run(_dc([_univ_row(ticker) for ticker in tickers],
                            pass2={ticker: {} for ticker in tickers}, selection_inputs=selection_inputs))
        theme_rows = [row for row in out["selection_details"] if row["selection_bucket"] == "theme_momentum"]
        self.assertLessEqual(sum(row["theme_selection"]["theme_id"] == "industry:crowded" for row in theme_rows), 3)
        self.assertEqual(out["full_analysis_leader_upgrades"], ["T01", "T02"])

    def test_provisional_theme_requires_enabled_mode_market_confirmation_and_individual_gate(self):
        core = ["C%02d" % i for i in range(8)]
        theme = ["BAD", "GOOD"]
        tickers = core + theme
        core_scores = {ticker: 100.0 - i for i, ticker in enumerate(core)}
        core_scores.update({ticker: 10.0 for ticker in theme})
        theme_scores = {ticker: 1.0 for ticker in core}
        theme_scores.update({"BAD": 100.0, "GOOD": 99.0})
        selection_inputs = _selection_inputs(
            tickers, state="strong", core_scores=core_scores, theme_scores=theme_scores)
        selection_inputs["theme_selection_contract"] = _theme_selection_contract(
            tickers, state="strong", mode="provisional_cross_industry_enabled",
            source_by_ticker={"BAD": "provisional_discovered", "GOOD": "provisional_discovered"},
            market_confirmed_by_ticker={"BAD": False, "GOOD": True},
            individual_gate_by_ticker={"BAD": False, "GOOD": True})
        out = self._run(_dc([_univ_row(ticker) for ticker in tickers],
                            pass2={ticker: {} for ticker in tickers}, selection_inputs=selection_inputs))
        buckets = {row["ticker"]: row["selection_bucket"] for row in out["selection_details"]}
        self.assertNotEqual(buckets.get("BAD"), "theme_momentum")
        self.assertEqual(buckets.get("GOOD"), "theme_momentum")

    def test_missing_selection_input_for_pass2_clean_candidate_raises(self):
        with self.assertRaises(wp.WeekendPipelineError):
            self._run(_dc([_univ_row("AAPL")], pass2={"AAPL": {}},
                          selection_inputs=_selection_inputs([])))

    def test_stale_selection_input_raises(self):
        with self.assertRaises(wp.WeekendPipelineError):
            self._run(_dc([_univ_row("AAPL")], pass2={"AAPL": {}},
                          selection_inputs=_selection_inputs(["AAPL", "MSFT"])))

    def test_bad_selection_score_raises(self):
        bad = _selection_inputs(["AAPL"])
        bad["per_ticker"]["AAPL"]["core_score"] = "99"
        with self.assertRaises(wp.WeekendPipelineError):
            self._run(_dc([_univ_row("AAPL")], pass2={"AAPL": {}}, selection_inputs=bad))

    def test_malformed_theme_state_fails_closed(self):
        si = _selection_inputs(["AAPL"], state=["strong"])
        with self.assertRaises(wp.WeekendPipelineError):
            self._run(_dc([_univ_row("AAPL")], pass2={"AAPL": {}}, selection_inputs=si))

    def test_holdings_forced_in_with_veto_surfaced(self):
        dc = _dc([_univ_row("AAPL")], holdings=[{"ticker": "GOOG", "signals": {"delisted": True}}],
                 pass2={"AAPL": {}})
        out = self._run(dc)
        h = out["holdings"][0]
        self.assertEqual(h["ticker"], "GOOG")
        self.assertTrue(h["admit_to_topn"])             # §4.0 强制含持仓 — never excluded by the gate
        self.assertEqual(h["veto_tier"], "position_hard_veto")  # surfaced for §9 action

    def test_canonicality_flows_through(self):
        out = self._run(_dc([_univ_row("aapl")], pass2={"AAPL": {}}))  # lowercase universe ticker
        self.assertEqual(out["candidates"], ["AAPL"])    # canonicalized in Pass1

    def test_malformed_data_context_raises(self):
        with self.assertRaises(wp.WeekendPipelineError):
            wp.run_selection(_now("20260613", 10, 0), _SESSIONS, {"universe": []},
                             eligibility_governance=self.gov)

    def test_bad_holding_row_raises(self):
        dc = _dc([_univ_row("AAPL")], holdings=[{"ticker": "GOOG"}])  # missing signals
        with self.assertRaises(wp.WeekendPipelineError):
            self._run(dc)

    def test_decision_date_threaded_into_result(self):
        out = self._run(_dc([_univ_row("AAPL")], pass2={"AAPL": {}}))
        self.assertEqual(out["decision_date"], "20260615")
        self.assertEqual(out["run_date"], "20260613")

    # --- Pass2 signal coverage / canonicality (no default-clean by omission) ---
    def test_missing_candidate_pass2_signal_raises(self):
        with self.assertRaises(wp.WeekendPipelineError):
            self._run(_dc([_univ_row("AAPL")], pass2={}))

    def test_miscased_pass2_key_applies_veto(self):
        # 'aapl' canonicalizes to 'AAPL' and its veto now applies (no bypass via key drift)
        out = self._run(_dc([_univ_row("AAPL")], pass2={"aapl": {"delisted": True}},
                           selection_inputs=_selection_inputs([])))
        self.assertNotIn("AAPL", out["admitted"])

    def test_in_universe_recall_no_double_add(self):
        # MSFT IS an active universe row that passes the floor → already a candidate (base); the recall lane does
        # NOT double-add it and records no exclusion (the floor's positive control).
        out = self._run(_dc([_univ_row("AAPL"), _univ_row("MSFT")], recall=["MSFT"],
                            pass2={"AAPL": {}, "MSFT": {}}))
        self.assertEqual(sorted(out["candidates"]), ["AAPL", "MSFT"])
        self.assertEqual((out["recall_added"], out["recall_excluded"]), ([], []))

    def test_stale_extra_pass2_key_raises(self):
        with self.assertRaises(wp.WeekendPipelineError):
            self._run(_dc([_univ_row("AAPL")], pass2={"AAPL": {}, "ZZZZ": {}}))

    def test_non_canonical_pass2_key_raises(self):
        with self.assertRaises(wp.WeekendPipelineError):
            self._run(_dc([_univ_row("AAPL")], pass2={"AAPL": {}, "000001.SZ": {}}))

    def test_non_dict_pass2_payload_raises(self):
        with self.assertRaises(wp.WeekendPipelineError):
            self._run(_dc([_univ_row("AAPL")], pass2={"AAPL": "not-a-dict"}))

    # --- holding ticker canonical identity (same policy as candidates) ---
    def test_holding_ticker_canonicalized(self):
        dc = _dc([_univ_row("AAPL")], holdings=[{"ticker": " goog ", "signals": {}}], pass2={"AAPL": {}})
        self.assertEqual(self._run(dc)["holdings"][0]["ticker"], "GOOG")

    def test_holding_class_share_preserved(self):
        dc = _dc([_univ_row("AAPL")], holdings=[{"ticker": "BRK.B", "signals": {}}], pass2={"AAPL": {}})
        self.assertEqual(self._run(dc)["holdings"][0]["ticker"], "BRK.B")

    def test_holding_a_share_code_raises(self):
        dc = _dc([_univ_row("AAPL")], holdings=[{"ticker": "000001.SZ", "signals": {}}], pass2={"AAPL": {}})
        with self.assertRaises(wp.WeekendPipelineError):
            self._run(dc)

    def test_duplicate_holding_identity_raises(self):
        dc = _dc([_univ_row("AAPL")],
                 holdings=[{"ticker": "GOOG", "signals": {}}, {"ticker": "goog", "signals": {}}],
                 pass2={"AAPL": {}})
        with self.assertRaises(wp.WeekendPipelineError):
            self._run(dc)


if __name__ == "__main__":
    unittest.main()
