# -*- coding: utf-8 -*-
"""Tests for the US-short weekend-pipeline end-to-end orchestrator (batch4 slice 4d-ii-o).

Covers: the orchestrator chains 4d-i selection → 4d-ii-a..j → K → L → m2 → N over an injected closed-world
pipeline_context, threading the one canonical decision_date; the intraday DEAD-ZONE produces an out-of-window
NO-EMIT (no machine record / report / private artifact); an empty run flows end-to-end and writes the official
private artifacts; and fail-closed on a non-closed-world pipeline_context and a selection→analysis seam that the
per_ticker_analysis map does not exactly cover the admitted ∪ holdings union (including the legal holding_in_top15
overlap and the row_source ↔ selection-membership reconciliation). Pure/offline (private writes to tempdirs); no
provider/live; no A-share crossing.
"""
import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_orchestrator as orch  # noqa: E402
from engine.us_short_eligibility_gate import load_eligibility_governance  # noqa: E402
from engine.us_short_private_paths import PrivatePathError  # noqa: E402
from engine.us_short_run_provenance import RunProvenanceError  # noqa: E402

_DD = "20260615"          # canonical decision_date for a Sat run (upcoming Mon); sessions derived from _cal()
_PRICE_BASIS = "20260612"  # prior Fri
_PRESET = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
_CAL = json.loads((ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json").read_text(encoding="utf-8"))
_GOV_TITLE = {g["number"]: g["title"] for g in _CAL["calibration_items"]}


def _now(date, hh, mm):
    return datetime(int(date[:4]), int(date[4:6]), int(date[6:]), hh, mm)


def _univ_row(ticker, exchange="NASDAQ", price=150.0, adv=1.0e10, mcap=2.5e12):
    return {"ticker": ticker, "exchange": exchange, "price": price, "adv_usd": adv, "market_cap_usd": mcap,
            "delisted": False, "halted": False, "bankruptcy": False, "otc": False}


def _register(as_of=_DD):
    return {"schema_name": "us_short_lifecycle_register", "schema_version": "1.0.0", "as_of": as_of,
            "items": [{"number": g["number"], "title": _GOV_TITLE[g["number"]], "forward_observations": {},
                       "secondary_condition_met": False, "upgrade_margin_frozen": False, "due": False}
                      for g in _CAL["calibration_items"]]}


def _report_context():
    return {
        "price_clock": {"price_data_through": _PRICE_BASIS, "news_window_through": "20260613",
                        "session_scope": "RTH", "decision_date": _DD},
        "coverage_inputs": [], "core_conclusion": "empty run 占位",
        "risk_downgrade_note": "无", "macro_cluster_banner": "",
    }


def _theme_selection_contract(tickers, *, state="no_strong_theme"):
    return {
        "as_of": _DD,
        "mode": "industry_heat_v1_cross_industry_disabled",
        "cross_industry_provisional_enabled": False,
        "theme_opportunity_state": state,
        "per_ticker": {
            t: {
                "theme_id": f"industry:{t.lower()}", "theme_source": "industry_heat_v1",
                "theme_lifecycle_state": "confirmed_active", "theme_leader_rs": 0.0,
                "membership_origin": "automatic_discovery", "market_confirmed": True,
                "individual_theme_gate_passed": True, "overextension_state": "none",
            }
            for t in tickers
        },
    }


def _selection_inputs(tickers):
    return {"theme_opportunity_state": "no_strong_theme",
            "theme_selection_contract": _theme_selection_contract(tickers),
            "per_ticker": {t: {"core_score": 50.0, "theme_momentum_score": 0.0} for t in tickers}}


def _account(positions=()):
    positions = list(positions)
    return {"schema_name": "us_short_account_state", "schema_version": "1.0.0", "as_of": _DD,
            "us_market_equity": 30000.0, "us_short_bucket_capital": 10000.0,
            "us_short_available_cash": 4000.0, "positions": positions,
            "holding_action_reconciliation": {
                "schema_name": "us_short_holding_action_reconciliation", "schema_version": "1.0.0", "as_of": _DD,
                "positions": [{"ticker": p["ticker"], "entry_date": p["entry_date"], "remaining_shares": p["shares"],
                               "tp1_completed": False, "tp1_completed_at": None,
                               "source_reconciliation_ref": "test-account:" + p["ticker"]}
                              for p in positions]},
            "symbol_cooldown_reconciliation": {
                "schema_name": "us_short_symbol_cooldown_reconciliation", "schema_version": "1.0.0",
                "as_of": _DD, "events": []},
            "manual_order_only": True, "broker_connection_allowed": False}


_FAMS = ("universe", "per_ticker_analysis", "candidate_pass2_signals", "selection_inputs")


def _run_provenance(counts=None, observed="2026-06-13T08:00:00", *, as_of=_DD, price_basis=_PRICE_BASIS):
    # §2.1 PIT 来源对账 manifest: universe / per_ticker_analysis are price-bearing; the two signal/score families
    # observe-at only (price lineage = None). row_count BINDS the manifest to the actual payload (①a). observed
    # defaults safely before the Sat 10:00 run wall clock.
    counts = counts or {f: 0 for f in _FAMS}
    def source_refs(n):
        return [{"role": "test_fixture", "path": f"tests/fixtures/us_short/{n}.json"}]
    def price_fam(n):
        return {"as_of": as_of, "observed_at": observed, "price_basis_date": price_basis,
                "session": "RTH", "adjustment": "split_adjusted", "row_count": counts[n],
                "source_refs": source_refs(n)}
    def nonprice_fam(n):
        return {"as_of": as_of, "observed_at": observed, "price_basis_date": None,
                "session": None, "adjustment": None, "row_count": counts[n],
                "source_refs": source_refs(n)}
    return {"as_of": as_of, "price_basis_date": price_basis,
            "families": {"universe": price_fam("universe"), "per_ticker_analysis": price_fam("per_ticker_analysis"),
                         "candidate_pass2_signals": nonprice_fam("candidate_pass2_signals"),
                         "selection_inputs": nonprice_fam("selection_inputs")}}


def _cal(status="pending_authoritative_cross_check"):
    # a minimal valid NYSE calendar artifact covering the test window (June 2026; Juneteenth = the one holiday);
    # the §2.1/§3.5 live gate derives from its data_provenance.verification_status (not a caller-attested string).
    return {"calendar": "NYSE_NASDAQ", "timezone": "America/New_York", "start_date": "20260601",
            "end_date": "20260630", "regular_open": "09:30", "regular_close": "16:00",
            "holidays": ["20260619"], "half_days": {},
            "data_provenance": {"source": "test fixture", "verification_status": status, "note": "offline test calendar"}}


def _pipeline_context(reg_path, runs_root, weekly_root, *, universe=None, pass2=None, per_ticker_analysis=None,
                      selection_inputs=None, run_provenance=None, provider_health=None, calendar=None):
    pass2 = pass2 or {}
    if selection_inputs is None:
        selection_inputs = _selection_inputs(list(pass2))
    pta = {} if per_ticker_analysis is None else per_ticker_analysis
    counts = {"universe": len(universe or []), "per_ticker_analysis": len(pta),
              "candidate_pass2_signals": len(pass2), "selection_inputs": len(selection_inputs["per_ticker"])}
    return {
        "data_context": {"universe": universe or [], "catalyst_recall_feed": None, "holdings": [],
                         "candidate_pass2_signals": pass2, "selection_inputs": selection_inputs},
        "eligibility_governance": load_eligibility_governance(_PRESET),
        "per_ticker_analysis": pta,
        "run_provenance": _run_provenance(counts) if run_provenance is None else run_provenance,
        "provider_health": {"fmp": "ok", "sec_edgar": "ok"} if provider_health is None else provider_health,
        "calendar": _cal() if calendar is None else calendar,
        "market_axis_regimes": {"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"},
        "prior_regime": None, "prior_upgrade_count": 0,
        "sizing_context": {"short_bucket_dollars": 10000.0, "per_ticker": {}},
        "basket_context": {"per_ticker": {}, "holding_themes": {}, "theme_opportunity_state": "no_strong_theme"},
        "account_state": _account(),
        "paper_track": {"paper_evaluable": True, "consecutive_stops": 0, "paper_drawdown_frac": 0.0,
                        "evidence_ref": {"kind": "source_id", "value": "test:model_paper_track", "as_of": _DD}},
        "cost_inputs": {}, "available_cash": 4000.0, "report_context": _report_context(),
        "lifecycle_register_path": reg_path, "lifecycle_readiness_out_path": None,
        "runs_private_root": runs_root, "weekly_private_root": weekly_root,
    }


def _uptrend_bars(n=22):
    return [{"high": 100.0 + i * 0.5 + 0.5, "low": 100.0 + i * 0.5, "close": 100.0 + i * 0.5 + 0.3}
            for i in range(n)]


def _analysis_row(ticker, row_source="top15_candidate"):
    row = {"ticker": ticker, "row_source": row_source, "signals": {},
           "price_input": {"close": 110.5 if row_source.startswith("holding") else 101.5,
                           "bars": _uptrend_bars()}}
    if not row_source.startswith("holding"):
        # §4.2 core_score(blocks)=50.0 == the _selection_inputs selection-time core_score (one core_score per run,
        # so the slice-2a selection↔analysis reconciliation passes; a divergent value is tested separately).
        row["score_blocks"] = {"momentum": 50.0, "theme": 50.0, "catalyst": 50.0}
        # §4.2 risk_downgrade typed input (zero penalty → core_score == 50.0, seam stays consistent)
        row["risk_downgrade"] = {"points": 0.0, "hard_veto": False, "components": {"history": 0.0, "current_event": 0.0, "analyst": 0.0}}
    return row


class EmptyRunEndToEnd(unittest.TestCase):
    def test_empty_run_emits_and_writes(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr)
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)   # Sat → Mon decision
            self.assertFalse(out["out_of_window"])
            self.assertTrue(out["emitted"])
            self.assertEqual(out["decision_date"], _DD)
            self.assertEqual(out["machine_record"]["as_of"], _DD)
            self.assertEqual(out["machine_record"]["rows"], [])             # empty run → empty machine record
            # the official private artifacts were written under the per-decision-date dirs
            self.assertTrue(out["written"]["machine_record_path"].exists())
            self.assertEqual(sorted(p.name for p in (Path(wr) / _DD).iterdir()),
                             ["action_table.csv", "weekly_report.md"])
            self.assertIn("decision_date=%s" % _DD, (Path(wr) / _DD / "weekly_report.md").read_text(encoding="utf-8"))

    def test_decision_date_threaded(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0),
                                            _pipeline_context(reg, rr, wr))
            # one canonical decision_date through selection / machine record / lifecycle / report
            self.assertEqual(out["decision_date"], _DD)
            self.assertEqual(out["lifecycle_result"]["decision_date"], _DD)
            self.assertEqual(out["report_data"]["lifecycle_reminder_count"], {"section_1": 0, "section_12": 0})

    def test_price_clock_must_match_resolved_price_basis(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr)
            pc["report_context"]["price_clock"]["price_data_through"] = "20260611"  # resolver basis is 20260612
            with self.assertRaises(Exception):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)

    def test_nonempty_admitted_only_writes_official_artifacts(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr, universe=[_univ_row("AAPL")], pass2={"AAPL": {}},
                                   per_ticker_analysis={"AAPL": _analysis_row("AAPL")})
            pc["sizing_context"]["per_ticker"] = {
                "AAPL": {"discount_mults": [1.0], "liquidity_cap_shares": 100000}}
            pc["basket_context"]["per_ticker"] = {
                "AAPL": {"theme": "software",
                         "theme_probe": {"theme_lifecycle_state": None, "high_confidence": False,
                                         "coverage_status": "full", "no_gap_week": False, "entry_in_band": False}}}
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            self.assertEqual(len(out["machine_record"]["rows"]), 1)
            self.assertTrue(out["written"]["weekly_report_path"].exists())
            action_csv = out["written"]["action_table_path"].read_text(encoding="utf-8")
            self.assertIn("paper_or_minimal_only", action_csv)
            self.assertNotIn("full_size_eligible", action_csv)
            self.assertIn("AAPL", out["written"]["weekly_report_path"].read_text(encoding="utf-8"))
            self.assertIn("AAPL", action_csv)

    def test_second_cut_event_effect_reaches_machine_csv_and_weekly_projection(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            analysis = _analysis_row("AAPL")
            analysis["forward_event"] = {
                "event_type": "earnings", "days_to_event": 3.0,
                "evidence_ref": {"kind": "SEC filing", "value": "test:AAA:earnings", "as_of": _DD},
            }
            pc = _pipeline_context(reg, rr, wr, universe=[_univ_row("AAPL")], pass2={"AAPL": {}},
                                   per_ticker_analysis={"AAPL": analysis})
            pc["sizing_context"]["per_ticker"] = {"AAPL": {"discount_mults": [1.0], "liquidity_cap_shares": 100000}}
            pc["basket_context"]["per_ticker"] = {
                "AAPL": {"theme": "software", "theme_probe": {"theme_lifecycle_state": None,
                    "high_confidence": False, "coverage_status": "full", "no_gap_week": False, "entry_in_band": False}}}
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            row = out["machine_record"]["rows"][0]
            self.assertEqual((row["final_action"], row["observe_reason_type"]), ("观察", "event_window"))
            self.assertIn("upcoming_event:earnings", row["risk_tags"])
            event_record = next(f for f in row["field_records"] if f["field_id"] == "forward_event")
            self.assertEqual((event_record["impact_target"], event_record["claim_type"], event_record["evidence_ref"]["kind"]),
                             ("final_action", "临近财报", "SEC filing"))
            with out["written"]["action_table_path"].open(encoding="utf-8", newline="") as f:
                csv_row = next(csv.DictReader(f))
            self.assertIn("earnings", csv_row["upcoming_events"])
            self.assertIn("trigger=", out["written"]["weekly_report_path"].read_text(encoding="utf-8"))

    def test_second_cut_private_cooldown_blocks_build_and_projects_expiry(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            (Path(rr) / "symbol_cooldown_state.json").write_text(json.dumps({
                "schema_name": "us_short_symbol_cooldown_state", "schema_version": "1.0.0", "as_of": "20260601",
                "records": [{"ticker": "AAPL", "trigger": "filled_then_stop_loss", "triggered_at": "20260601",
                             "cooldown_until": "20260621", "source_reconciliation_ref": "test:filled-stop"}],
            }), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr, universe=[_univ_row("AAPL")], pass2={"AAPL": {}},
                                   per_ticker_analysis={"AAPL": _analysis_row("AAPL")})
            pc["sizing_context"]["per_ticker"] = {"AAPL": {"discount_mults": [1.0], "liquidity_cap_shares": 100000}}
            pc["basket_context"]["per_ticker"] = {
                "AAPL": {"theme": "software", "theme_probe": {"theme_lifecycle_state": None,
                    "high_confidence": False, "coverage_status": "full", "no_gap_week": False, "entry_in_band": False}}}
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            row = out["machine_record"]["rows"][0]
            self.assertEqual((row["final_action"], row["observe_reason_type"], row["symbol_cooldown_status"], row["cooldown_until"]),
                             ("观察", "risk_cooldown", "in_cooldown", "20260621"))
            cooldown_record = next(f for f in row["field_records"] if f["field_id"] == "symbol_cooldown")
            self.assertEqual(cooldown_record["impact_target"], "risk_tags")
            self.assertTrue(out["written"]["symbol_cooldown_state_path"].exists())
            self.assertTrue(out["written"]["portfolio_guard_state_path"].exists())
            with out["written"]["action_table_path"].open(encoding="utf-8", newline="") as f:
                csv_row = next(csv.DictReader(f))
            self.assertEqual(csv_row["cooldown_until"], "20260621")

    def test_existing_holding_current_mark_reduces_total_cap_end_to_end(self):
        # The final capacity stage must use the held name's same-run price_input.close, not avg_cost, before
        # funding a new build.  50 × 110.5 plus the candidate's $1k single-name size exceeds the $6k total cap.
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(
                reg, rr, wr, universe=[_univ_row("AAPL")], pass2={"AAPL": {}},
                per_ticker_analysis={"AAPL": _analysis_row("AAPL"),
                                     "HLD": _analysis_row("HLD", "holding_account_only")})
            pc["data_context"]["holdings"] = [{"ticker": "HLD", "signals": {}}]
            pc["account_state"] = _account([{"ticker": "HLD", "direction": "long", "shares": 50,
                                               "avg_cost_usd": 1.0, "entry_date": "20260601"}])
            pc["sizing_context"]["per_ticker"] = {
                "AAPL": {"discount_mults": [1.0], "liquidity_cap_shares": 100000}}
            pc["basket_context"]["per_ticker"] = {
                "AAPL": {"theme": "new_theme",
                         "theme_probe": {"theme_lifecycle_state": None, "high_confidence": False,
                                         "coverage_status": "full", "no_gap_week": False, "entry_in_band": False}}}
            pc["basket_context"]["holding_themes"] = {"HLD": "held_theme"}
            pc["report_context"]["coverage_inputs"] = [{"ticker": "HLD", "row_source": "holding_account_only",
                "data_checks": {"analyst": "ok", "sec_parse": "ok", "event": "ok"}}]
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            by_ticker = {row["ticker"]: row for row in out["machine_record"]["rows"]}
            self.assertEqual(by_ticker["AAPL"]["final_action"], "观察")
            self.assertEqual(by_ticker["AAPL"]["observe_reason_type"], "capacity_or_budget_deferred")
            self.assertEqual(by_ticker["AAPL"]["portfolio_capacity_status"], "deferred_total_cap")

    def test_existing_holding_theme_reduces_theme_cap_end_to_end(self):
        # The same account/price/theme chain is independently binding for the 30% theme cap: 20 × 110.5 plus
        # the candidate's $1k size stays below total but exceeds the $3k canonical theme bucket.
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(
                reg, rr, wr, universe=[_univ_row("AAPL")], pass2={"AAPL": {}},
                per_ticker_analysis={"AAPL": _analysis_row("AAPL"),
                                     "HLD": _analysis_row("HLD", "holding_account_only")})
            pc["data_context"]["holdings"] = [{"ticker": "HLD", "signals": {}}]
            pc["account_state"] = _account([{"ticker": "HLD", "direction": "long", "shares": 20,
                                               "avg_cost_usd": 1.0, "entry_date": "20260601"}])
            pc["sizing_context"]["per_ticker"] = {
                "AAPL": {"discount_mults": [1.0], "liquidity_cap_shares": 100000}}
            pc["basket_context"]["per_ticker"] = {
                "AAPL": {"theme": " Software ",
                         "theme_probe": {"theme_lifecycle_state": None, "high_confidence": False,
                                         "coverage_status": "full", "no_gap_week": False, "entry_in_band": False}}}
            pc["basket_context"]["holding_themes"] = {"HLD": "software"}
            pc["report_context"]["coverage_inputs"] = [{"ticker": "HLD", "row_source": "holding_account_only",
                "data_checks": {"analyst": "ok", "sec_parse": "ok", "event": "ok"}}]
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            by_ticker = {row["ticker"]: row for row in out["machine_record"]["rows"]}
            self.assertEqual(by_ticker["AAPL"]["final_action"], "观察")
            self.assertEqual(by_ticker["AAPL"]["observe_reason_type"], "capacity_or_budget_deferred")
            self.assertEqual(by_ticker["AAPL"]["portfolio_capacity_status"], "deferred_theme_cap")

    def test_real_pass1_reject_drives_report_exclusion_count(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr, universe=[_univ_row("PENNY", price=1.0)])
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            self.assertTrue(out["emitted"])
            self.assertIn("本周剔除 1 只", "\n".join(out["report_data"]["sections"][9]))

    def test_nonempty_holding_in_top15_overlap_writes_official_artifacts(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr, universe=[_univ_row("AAPL")], pass2={"AAPL": {}},
                                   per_ticker_analysis={"AAPL": _analysis_row("AAPL", "holding_in_top15")})
            pc["data_context"]["holdings"] = [{"ticker": "AAPL", "signals": {}}]
            pc["account_state"] = _account([{"ticker": "AAPL", "direction": "long", "shares": 100,
                                               "avg_cost_usd": 100.0, "entry_date": "20260601"}])
            pc["basket_context"]["holding_themes"] = {"AAPL": "software"}
            pc["report_context"]["coverage_inputs"] = [{"ticker": "AAPL", "row_source": "holding_in_top15",
                "data_checks": {"analyst": "ok", "sec_parse": "ok", "event": "ok"}}]   # 1:1 coverage for the holding
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            row = out["machine_record"]["rows"][0]
            self.assertEqual(row["row_source"], "holding_in_top15")
            self.assertEqual(row["final_action"], "持有")
            self.assertTrue(out["written"]["holding_action_state_path"].exists())
            state = json.loads(out["written"]["holding_action_state_path"].read_text(encoding="utf-8"))
            self.assertEqual(state["positions"][0]["ticker"], "AAPL")
            self.assertFalse(state["positions"][0]["tp1_completed"])
            self.assertIsNotNone(state["positions"][0]["active_tp1_price"])
            self.assertIn("AAPL", out["written"]["weekly_report_path"].read_text(encoding="utf-8"))
            # Re-run against the stored level: TP1 now becomes a real reduce action with a one-time quantity,
            # while the private state remains uncompleted until the manual trade table confirms execution.
            pc["per_ticker_analysis"]["AAPL"]["price_input"]["close"] = state["positions"][0]["active_tp1_price"]
            pc["per_ticker_analysis"]["AAPL"]["holding_action_cost_input"] = {
                "commission_round_trip": 0.0, "slippage_dollars": 0.0, "spread_dollars": 0.0}
            out2 = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            row2 = out2["machine_record"]["rows"][0]
            self.assertEqual(row2["final_action"], "减仓")
            self.assertEqual(row2["action_proposal"]["recommended_action_shares"], 10)
            with out2["written"]["action_table_path"].open(encoding="utf-8", newline="") as f:
                self.assertEqual(next(csv.DictReader(f))["recommended_action_shares"], "10")
            self.assertIn("AAPL 减仓 | shares=10", out2["written"]["weekly_report_path"].read_text(encoding="utf-8"))
            state2 = json.loads(out2["written"]["holding_action_state_path"].read_text(encoding="utf-8"))
            self.assertFalse(state2["positions"][0]["tp1_completed"])


class OutOfWindowNoEmit(unittest.TestCase):
    def test_intraday_dead_zone_no_emit(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr)
            out = orch.run_weekend_pipeline(_now(_DD, 11, 0), pc)   # Mon 11:00 = intraday dead zone
            self.assertTrue(out["out_of_window"])
            self.assertFalse(out["emitted"])
            self.assertIsNone(out["decision_date"])
            self.assertNotIn("machine_record", out)               # NO downstream artifact produced
            self.assertFalse(any(Path(wr).iterdir()))             # nothing written to private dirs


class FailClosed(unittest.TestCase):
    def test_non_closed_world_pipeline_context_rejected(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr)
            pc.pop("report_context")          # missing a key
            with self.assertRaises(orch.WeekendOrchestratorError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            pc2 = _pipeline_context(reg, rr, wr)
            pc2["EXTRA"] = 1                   # extra key
            with self.assertRaises(orch.WeekendOrchestratorError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc2)

    def test_seam_per_ticker_analysis_must_cover_selection(self):
        # AAPL is admitted but per_ticker_analysis does not cover it → the selection→analysis seam fails closed
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr, universe=[_univ_row("AAPL")], pass2={"AAPL": {}},
                                   per_ticker_analysis={})   # missing AAPL
            with self.assertRaises(orch.WeekendOrchestratorError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)


class ProvenanceFailClosed(unittest.TestCase):
    """R-USSHORT-BATCH4-PIPELINE-PIT-...: the §2.1 PIT 来源对账 runs BEFORE analysis, so a consumed input family
    tagged for another run / observed in the future fails the WHOLE pipeline closed — nothing reaches the official
    chain, nothing is written (the exact contamination vector the strict review reproduced)."""

    def test_cross_run_input_family_rejected(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            rp = _run_provenance()
            rp["families"]["universe"]["as_of"] = "20990101"   # universe produced for a DIFFERENT run
            pc = _pipeline_context(reg, rr, wr, run_provenance=rp)
            with self.assertRaises(RunProvenanceError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            self.assertFalse(any(Path(wr).iterdir()))          # NO official artifact written

    def test_future_observed_input_rejected(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr, run_provenance=_run_provenance(observed="2099-01-01T00:00:00"))
            with self.assertRaises(RunProvenanceError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            self.assertFalse(any(Path(wr).iterdir()))

    def test_missing_run_provenance_key_rejected(self):   # closed-world: the 16th key is mandatory
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr)
            pc.pop("run_provenance")
            with self.assertRaises(orch.WeekendOrchestratorError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)

    def test_clean_provenance_positive_control(self):   # the default manifest reconciles → empty run emits
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), _pipeline_context(reg, rr, wr))
            self.assertTrue(out["emitted"])
            self.assertEqual(out["run_provenance"]["as_of"], _DD)
            self.assertEqual(out["run_provenance"]["session"], "RTH")


    def test_source_refs_missing_input_family_rejected(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            rp = _run_provenance()
            rp["families"]["universe"].pop("source_refs")
            pc = _pipeline_context(reg, rr, wr, run_provenance=rp)
            with self.assertRaises(RunProvenanceError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            self.assertFalse(any(Path(wr).iterdir()))


class RunGateHealthAndMode(unittest.TestCase):
    """R-USSHORT-BATCH4-PIPELINE-PIT-HEALTH-CALENDAR-GATE-GAP (health + mode halves): the §3.7 provider-health
    gate permits advisory FMP-grades fallback but NO-EMITs on non-clean critical SEC health; the §2.1 run-mode
    gate fails a live run closed on a non-authoritative calendar; offline_test runs on the pending fixture calendar."""

    def _ctx(self, d, rr, wr, **over):
        reg = Path(d) / "reg.json"
        reg.write_text(json.dumps(_register()), encoding="utf-8")
        return _pipeline_context(reg, rr, wr, **over)

    def test_down_advisory_fmp_health_emits_with_fallback(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            pc = self._ctx(d, rr, wr, provider_health={"fmp": "down", "sec_edgar": "ok"})
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            self.assertTrue(out["emitted"])
            self.assertEqual(out["provider_health"]["overall_run_state"], "usable_with_fallback")
            self.assertEqual(out["provider_health"]["sources"]["fmp"], "usable_with_fallback")

    def test_degraded_critical_sec_health_no_emit(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            pc = self._ctx(d, rr, wr, provider_health={"fmp": "ok", "sec_edgar": "degraded"})
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            self.assertFalse(out["emitted"])
            self.assertEqual(out["no_emit_reason"], "provider_health_restricted")
            self.assertNotIn("machine_record", out)
            self.assertFalse(any(Path(wr).iterdir()))

    def test_down_critical_health_no_emit(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            pc = self._ctx(d, rr, wr, provider_health={"fmp": "ok", "sec_edgar": "down"})
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            self.assertFalse(out["emitted"])
            self.assertEqual(out["no_emit_reason"], "provider_health_blocked")
            self.assertFalse(any(Path(wr).iterdir()))

    def test_missing_critical_source_no_emit(self):   # a critical source absent → missing → blocked → no-emit
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            pc = self._ctx(d, rr, wr, provider_health={"fmp": "ok"})   # sec_edgar missing
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            self.assertFalse(out["emitted"])
            self.assertEqual(out["no_emit_reason"], "provider_health_blocked")

    def test_unauthorized_source_structurally_rejected(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            pc = self._ctx(d, rr, wr, provider_health={"fmp": "ok", "sec_edgar": "ok", "yfinance": "ok"})
            with self.assertRaises(Exception):   # classifier refuses an unauthorized source (§18.1 #3)
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)

    def test_clean_health_positive_control(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), self._ctx(d, rr, wr))
            self.assertTrue(out["emitted"])
            self.assertEqual(out["provider_health"]["overall_run_state"], "clean")

    def test_live_mode_pending_calendar_fails_closed(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            pc = self._ctx(d, rr, wr)   # default calendar = pending_authoritative_cross_check
            with self.assertRaises(orch.WeekendOrchestratorError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc, run_mode="live")
            self.assertFalse(any(Path(wr).iterdir()))

    def test_live_mode_gated_even_with_authoritative_calendar(self):
        # batch4 GATES live entirely — a self-reported authoritative_verified calendar does NOT enable live (the
        # trust anchor is the batch5 cross-checked artifact, not a caller-injected one).
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            pc = self._ctx(d, rr, wr, calendar=_cal(status="authoritative_verified"))
            with self.assertRaises(orch.WeekendOrchestratorError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc, run_mode="live")

    def test_forged_calendar_string_rejected(self):
        # ①c: a bare 'authoritative_verified' STRING is not a calendar artifact → validate_market_calendar rejects
        # it (offline_test so the calendar is actually validated, not short-circuited by the live gate).
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            pc = self._ctx(d, rr, wr, calendar="authoritative_verified")
            with self.assertRaises(Exception):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)

    def test_offline_test_mode_runs_on_pending_calendar(self):   # default mode tolerates the pending fixture calendar
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), self._ctx(d, rr, wr),
                                            run_mode="offline_test")
            self.assertTrue(out["emitted"])

    def test_invalid_run_mode_rejected(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(orch.WeekendOrchestratorError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), self._ctx(d, rr, wr),
                                          run_mode="production")


class SelectionRecordThreaded(unittest.TestCase):
    """R-USSHORT-BATCH4-SELECTION-TRACE-AND-RECALL-CLOSURE-GAP (selection-record half): the canonical Top15
    selection identity (rank/bucket/selection-time scores) is carried through analysis into the machine record;
    a same-run divergence between the selection-time and the recomputed §4.2 core_score fails the run closed."""

    @staticmethod
    def _build_ctx(d, rr, wr, **over):
        reg = Path(d) / "reg.json"
        reg.write_text(json.dumps(_register()), encoding="utf-8")
        pc = _pipeline_context(reg, rr, wr, universe=[_univ_row("AAPL")], pass2={"AAPL": {}},
                               per_ticker_analysis={"AAPL": _analysis_row("AAPL")}, **over)
        pc["sizing_context"]["per_ticker"] = {"AAPL": {"discount_mults": [1.0], "liquidity_cap_shares": 100000}}
        pc["basket_context"]["per_ticker"] = {
            "AAPL": {"theme": "software",
                     "theme_probe": {"theme_lifecycle_state": None, "high_confidence": False,
                                     "coverage_status": "full", "no_gap_week": False, "entry_in_band": False}}}
        return pc

    def test_selection_record_reaches_machine_record(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            pc = self._build_ctx(d, rr, wr)
            pc["data_context"]["selection_inputs"]["per_ticker"]["AAPL"]["theme_momentum_score"] = 1.0
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            rec = out["machine_record"]["rows"][0]["selection_record"]   # carried, not dropped
            self.assertEqual(rec["selection_rank"], 1)                   # AAPL is the top (only) Top15 name
            self.assertEqual(rec["selection_bucket"], "overlap")        # top in both core + theme rank → overlap
            self.assertEqual(rec["core_score"], 50.0)

    def test_divergent_selection_vs_analysis_core_fails_closed(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            pc = self._build_ctx(d, rr, wr)
            pc["data_context"]["selection_inputs"]["per_ticker"]["AAPL"]["core_score"] = 99.0   # ≠ §4.2 analysis 50
            with self.assertRaises(Exception):                          # WeekendAnalysisError through the pipeline
                orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            self.assertFalse(any(Path(wr).iterdir()))                   # nothing written

    def test_holding_only_row_carries_no_selection_record(self):
        # a current holding that did NOT rank into Top15 has selection_record=None (not in selection_details)
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr, per_ticker_analysis={"HLD": _analysis_row("HLD", "holding_account_only")})
            pc["data_context"]["holdings"] = [{"ticker": "HLD", "signals": {}}]
            pc["account_state"] = _account([{"ticker": "HLD", "direction": "long", "shares": 1,
                                               "avg_cost_usd": 100.0, "entry_date": "20260601"}])
            pc["basket_context"]["holding_themes"] = {"HLD": "software"}
            pc["report_context"]["coverage_inputs"] = [{"ticker": "HLD", "row_source": "holding_account_only",
                "data_checks": {"analyst": "ok", "sec_parse": "ok", "event": "ok"}}]   # 1:1 coverage for the holding
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), pc)
            self.assertIsNone(out["machine_record"]["rows"][0]["selection_record"])


class SeamPayloadIdentity(unittest.TestCase):
    """R-USSHORT-BATCH4-O-SELECTION-ANALYSIS-PAYLOAD-ID-GAP: key-only coverage must not let a per_ticker_analysis
    key carry a payload row for a DIFFERENT ticker — each payload's own canonical ticker must equal its key."""

    @staticmethod
    def _row(ticker, row_source="top15_candidate"):
        return {"ticker": ticker, "row_source": row_source, "signals": {}}

    def test_candidate_key_with_other_ticker_payload_rejected(self):
        with self.assertRaises(orch.WeekendOrchestratorError):
            orch._build_analysis_rows({"admitted": ["AAPL"], "holdings": []},
                                      {"AAPL": self._row("MSFT")})

    def test_holding_key_with_other_ticker_payload_rejected(self):
        with self.assertRaises(orch.WeekendOrchestratorError):
            orch._build_analysis_rows(
                {"admitted": [], "holdings": [{"ticker": "HLD", "admit_to_topn": False, "veto_tier": "none"}]},
                {"HLD": self._row("OTH", row_source="holding_pass2_only")})

    def test_two_symbol_swapped_payloads_rejected(self):
        # exact key coverage holds {AAA,BBB} == {AAA,BBB}, but the payloads are swapped → fail closed
        with self.assertRaises(orch.WeekendOrchestratorError):
            orch._build_analysis_rows({"admitted": ["AAA", "BBB"], "holdings": []},
                                      {"AAA": self._row("BBB"), "BBB": self._row("AAA")})

    def test_non_dict_payload_rejected(self):
        with self.assertRaises(orch.WeekendOrchestratorError):
            orch._build_analysis_rows({"admitted": ["AAA"], "holdings": []}, {"AAA": "not-a-dict"})

    def test_matching_payload_passes(self):   # positive control: payload ticker == its key
        rows = orch._build_analysis_rows({"admitted": ["AAA"], "holdings": []},
                                         {"aaa": self._row("AAA")})   # non-canonical key + payload both → AAA
        self.assertEqual([r["ticker"] for r in rows], ["AAA"])


class SeamSelectionMembership(unittest.TestCase):
    """R-USSHORT-BATCH4-O-HOLDING-IN-TOP15-SEAM-BLOCKER: admitted ∩ holdings is the LEGAL holding_in_top15
    overlap (one merged row), not a duplicate error; only a repeat WITHIN admitted / WITHIN holdings is malformed;
    and each row's row_source must match the ticker's selection membership (the official report / machine record
    split holdings vs candidates by row_source)."""

    @staticmethod
    def _row(ticker, row_source):
        return {"ticker": ticker, "row_source": row_source, "signals": {}}

    @staticmethod
    def _hld(ticker):
        return {"ticker": ticker, "admit_to_topn": False, "veto_tier": "none"}

    def _rows(self, selection, ptm):
        return [(r["ticker"], r["row_source"]) for r in orch._build_analysis_rows(selection, ptm)]

    # --- positive: each membership state accepted with a matching row_source ---
    def test_admitted_only_candidate_passes(self):
        self.assertEqual(self._rows({"admitted": ["AAPL"], "holdings": []},
                                    {"AAPL": self._row("AAPL", "top15_candidate")}),
                         [("AAPL", "top15_candidate")])

    def test_holding_only_pass2_source_passes(self):
        self.assertEqual(self._rows({"admitted": [], "holdings": [self._hld("HLD")]},
                                    {"HLD": self._row("HLD", "holding_pass2_only")}),
                         [("HLD", "holding_pass2_only")])

    def test_holding_only_account_source_passes(self):   # both holding sources are valid for a holding-only row
        self.assertEqual(self._rows({"admitted": [], "holdings": [self._hld("HLD")]},
                                    {"HLD": self._row("HLD", "holding_account_only")}),
                         [("HLD", "holding_account_only")])

    def test_holding_in_top15_overlap_accepted_once(self):
        # AAPL is both admitted (Top15) and a current holding → ONE merged row with row_source holding_in_top15
        self.assertEqual(self._rows({"admitted": ["AAPL"], "holdings": [self._hld("AAPL")]},
                                    {"AAPL": self._row("AAPL", "holding_in_top15")}),
                         [("AAPL", "holding_in_top15")])

    def test_overlap_admitted_only_holding_only_mix(self):
        # AAPL admitted+held → holding_in_top15; MSFT admitted-only → top15_candidate; HLD held-only → holding source.
        # exact union coverage; overlap deduped; union order = admitted order then holding-only.
        self.assertEqual(
            self._rows({"admitted": ["AAPL", "MSFT"], "holdings": [self._hld("AAPL"), self._hld("HLD")]},
                       {"AAPL": self._row("AAPL", "holding_in_top15"),
                        "MSFT": self._row("MSFT", "top15_candidate"),
                        "HLD": self._row("HLD", "holding_pass2_only")}),
            [("AAPL", "holding_in_top15"), ("MSFT", "top15_candidate"), ("HLD", "holding_pass2_only")])

    # --- adversarial: row_source not matching the ticker's membership fails closed ---
    def test_overlap_with_wrong_row_source_rejected(self):
        with self.assertRaises(orch.WeekendOrchestratorError):   # overlap must be holding_in_top15, not candidate
            orch._build_analysis_rows({"admitted": ["AAPL"], "holdings": [self._hld("AAPL")]},
                                      {"AAPL": self._row("AAPL", "top15_candidate")})

    def test_admitted_only_with_holding_source_rejected(self):
        with self.assertRaises(orch.WeekendOrchestratorError):   # admitted-only must be top15_candidate
            orch._build_analysis_rows({"admitted": ["AAPL"], "holdings": []},
                                      {"AAPL": self._row("AAPL", "holding_in_top15")})

    def test_holding_only_with_candidate_source_rejected(self):
        with self.assertRaises(orch.WeekendOrchestratorError):   # holding-only must be a holding source
            orch._build_analysis_rows({"admitted": [], "holdings": [self._hld("HLD")]},
                                      {"HLD": self._row("HLD", "top15_candidate")})

    # --- adversarial: a repeat WITHIN one identity space is still malformed (≠ the legal cross-space overlap) ---
    def test_true_duplicate_within_admitted_rejected(self):
        with self.assertRaises(orch.WeekendOrchestratorError):
            orch._build_analysis_rows({"admitted": ["AAPL", "AAPL"], "holdings": []},
                                      {"AAPL": self._row("AAPL", "top15_candidate")})

    def test_true_duplicate_within_holdings_rejected(self):
        with self.assertRaises(orch.WeekendOrchestratorError):
            orch._build_analysis_rows({"admitted": [], "holdings": [self._hld("HLD"), self._hld("HLD")]},
                                      {"HLD": self._row("HLD", "holding_pass2_only")})


if __name__ == "__main__":
    unittest.main()
