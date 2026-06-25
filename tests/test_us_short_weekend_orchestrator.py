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

_SESSIONS = [{"date": "20260612"}, {"date": "20260615"}, {"date": "20260616"}]   # Fri / Mon / Tue
_DD = "20260615"          # canonical decision_date for a Sat run (upcoming Mon)
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
        "price_clock": {"price_data_through": _PRICE_BASIS, "news_window_through": _DD,
                        "session_scope": "RTH", "decision_date": _DD},
        "exclusion_data": {"as_of": _DD, "categories": {}, "hot_excluded": {"public_heat_count": 0, "holdings": []}},
        "coverage_inputs": [], "account_risk_note": "portfolio_guard=normal",
        "theme_opportunity_state": "no_strong_theme", "core_conclusion": "empty run 占位",
        "risk_downgrade_note": "无", "provider_health_note": "FMP/SEC 健康", "macro_cluster_banner": "",
        "ship_gate_note": "ship-gate: paper 累积中",
    }


def _pipeline_context(reg_path, runs_root, weekly_root, *, universe=None, pass2=None, per_ticker_analysis=None):
    return {
        "data_context": {"universe": universe or [], "catalyst_recall_feed": None, "holdings": [],
                         "candidate_pass2_signals": pass2 or {}},
        "eligibility_governance": load_eligibility_governance(_PRESET),
        "per_ticker_analysis": {} if per_ticker_analysis is None else per_ticker_analysis,
        "market_axis_regimes": {"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"},
        "prior_regime": None, "prior_upgrade_count": 0,
        "sizing_context": {"short_bucket_dollars": 10000.0, "per_ticker": {}},
        "basket_context": {"per_ticker": {}, "portfolio_guard_status": "normal",
                           "theme_opportunity_state": "no_strong_theme"},
        "cost_inputs": {}, "available_cash": 4000.0, "report_context": _report_context(),
        "lifecycle_register_path": reg_path, "lifecycle_readiness_out_path": None,
        "runs_private_root": runs_root, "weekly_private_root": weekly_root,
    }


class EmptyRunEndToEnd(unittest.TestCase):
    def test_empty_run_emits_and_writes(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr)
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), _SESSIONS, pc)   # Sat → Mon decision
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
            out = orch.run_weekend_pipeline(_now("20260613", 10, 0), _SESSIONS,
                                            _pipeline_context(reg, rr, wr))
            # one canonical decision_date through selection / machine record / lifecycle / report
            self.assertEqual(out["decision_date"], _DD)
            self.assertEqual(out["lifecycle_result"]["decision_date"], _DD)
            self.assertEqual(out["report_data"]["lifecycle_reminder_count"], {"section_1": 0, "section_12": 0})


class OutOfWindowNoEmit(unittest.TestCase):
    def test_intraday_dead_zone_no_emit(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr)
            out = orch.run_weekend_pipeline(_now(_DD, 11, 0), _SESSIONS, pc)   # Mon 11:00 = intraday dead zone
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
                orch.run_weekend_pipeline(_now("20260613", 10, 0), _SESSIONS, pc)
            pc2 = _pipeline_context(reg, rr, wr)
            pc2["EXTRA"] = 1                   # extra key
            with self.assertRaises(orch.WeekendOrchestratorError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), _SESSIONS, pc2)

    def test_seam_per_ticker_analysis_must_cover_selection(self):
        # AAPL is admitted but per_ticker_analysis does not cover it → the selection→analysis seam fails closed
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            reg = Path(d) / "reg.json"
            reg.write_text(json.dumps(_register()), encoding="utf-8")
            pc = _pipeline_context(reg, rr, wr, universe=[_univ_row("AAPL")], pass2={"AAPL": {}},
                                   per_ticker_analysis={})   # missing AAPL
            with self.assertRaises(orch.WeekendOrchestratorError):
                orch.run_weekend_pipeline(_now("20260613", 10, 0), _SESSIONS, pc)


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
