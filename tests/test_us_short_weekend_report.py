# -*- coding: utf-8 -*-
"""Tests for US-short weekend §11.2 weekly_report assembly (batch4 slice 4d-ii-m2).

Covers: the assembler builds a §11.2 report_data (13 sections + honest banner ①③④⑤ [② optional] + the
lifecycle-count reconcile) from the K machine record (flattened via m1) + the L lifecycle result + an injected
closed-world report_context, and renders it; the lifecycle count reconciles across section 1 / 12; the row
sections derive from the flattened §11.3 rows; the formatters (observe split / exclusion / hot-excluded /
coverage) are wired; and fail-closed on a non-closed-world report_context, a malformed lifecycle result, a
malformed coverage input, a blank editorial section, and an incomplete price_clock. Pure/offline; no
provider/live; no A-share crossing.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_report as wr  # noqa: E402
import engine.us_short_weekend_machine_record as mr  # noqa: E402
from engine.us_short_action_rank import action_group as _ag  # noqa: E402

_AS_OF = "20260112"
# a valid executable support_atr build action_fields (carries every m1 _BUILD_REQUIRED field with valid values)
_BUILD_AF = {
    "order_type": "pullback_limit", "entry_plan": "pullback", "pullback_entry_price": 99.0,
    "breakout_entry_price": None, "limit_order_price": 101.0, "valid_entry_low": 99.0, "valid_entry_high": 101.0,
    "order_expiry": "first_regular_session_only", "gap_policy": "limit_band_first_session_no_chase",
    "effective_support": 98.0, "effective_resistance": 110.0, "structure_quality": "strong",
    "stop_clear_price": 98.0, "take_profit_reduce_price": 105.0, "take_profit_exit_price": 110.0,
    "risk_reward_ratio": 2.0, "min_rr_gate_status": "pass", "post_round_rr_status": "ok",
    "price_engine_used": "support_atr_engine", "price_sub_mode": "pullback",
}
_HOLDING_AF = {
    "stop_clear_price": 95.0, "take_profit_reduce_price": 108.0, "take_profit_exit_price": 115.0,
    "risk_reward_ratio": 1.8, "post_round_rr_status": "ok",
    "price_engine_used": "holding_exit_engine", "price_sub_mode": None,
}


def _candidate(ticker="AAA", final_action="建仓", observe_reason_type=None, executable=True, sized=True, af=None):
    row = {"ticker": ticker, "row_source": "top15_candidate", "final_action": final_action,
           "observe_reason_type": observe_reason_type, "row_context": "candidate", "selection_rank": 1,
           "action_rank": 1, "action_group": _ag(final_action),
           "veto": {"veto_tier": "none", "row_context": "candidate"},
           "price": {"executable": executable, "trace": {}, "action_fields": _BUILD_AF if af is None else af},
           "score": {"core_score": 50.0}}
    if sized:
        row["sizing"] = {"status": "sized", "desired_model_shares": 10}
    return row


def _holding(ticker="HLD"):
    return {"ticker": ticker, "row_source": "holding_pass2_only", "final_action": "持有",
            "observe_reason_type": None, "row_context": "holding", "selection_rank": None,
            "action_rank": 2, "action_group": _ag("持有"),
            "veto": {"veto_tier": "none", "row_context": "holding"},
            "price": {"executable": True, "trace": {"breached": False}, "action_fields": _HOLDING_AF}}


def _observe(ticker="OBS"):
    return _candidate(ticker, final_action="观察", observe_reason_type="price_not_executable",
                      executable=False, sized=False,
                      af={"price_engine_used": "support_atr_engine", "price_sub_mode": "pullback",
                          "min_rr_gate_status": "fail_below_floor"})


def _machine_record(rows=None):
    rows = rows if rows is not None else [_candidate("AAA"), _holding("HLD"), _observe("OBS")]
    return mr.assemble_machine_record({"regime": {"market_risk_regime": "进攻"}, "rows": rows}, as_of=_AS_OF)


def _lifecycle_result(due_count=0, due_items=(), upgrade=(), decision_date=_AS_OF, readiness_overrides=None):
    readiness = {"schema_name": "us_short_lifecycle_readiness", "schema_version": "1.0.0",
                 "as_of": decision_date, "total_items": 39, "due_count": due_count,
                 "due_items": list(due_items), "upgrade_eligible_items": list(upgrade)}
    if readiness_overrides:
        readiness.update(readiness_overrides)
    return {"decision_date": decision_date,
            "banner": "[us-short lifecycle] as_of=%s: %d due" % (decision_date, due_count), "readiness": readiness}


def _report_context(**ov):
    rc = {
        "price_clock": {"price_data_through": "20260109", "news_window_through": _AS_OF,
                        "session_scope": "RTH", "decision_date": _AS_OF},
        "exclusion_data": {"as_of": _AS_OF, "categories": {}, "hot_excluded": {"public_heat_count": 0, "holdings": []}},
        "coverage_inputs": [{"row_source": "holding_pass2_only",
                             "data_checks": {"analyst": "ok", "sec_parse": "ok", "event": "ok"}}],
        "account_risk_note": "portfolio_guard=normal", "theme_opportunity_state": "no_strong_theme",
        "core_conclusion": "本周核心结论占位", "risk_downgrade_note": "无重大降级",
        "provider_health_note": "FMP/SEC 健康", "macro_cluster_banner": "", "ship_gate_note": "ship-gate: paper 累积中",
    }
    rc.update(ov)
    return rc


def _run_context(**ov):
    rc = {"decision_date": _AS_OF, "price_basis_date": "20260109", "run_date": _AS_OF}
    rc.update(ov)
    return rc


def _build_report(machine_record, lifecycle_result, *, report_context, run_context=None):
    return wr.build_weekly_report(machine_record, lifecycle_result, report_context=report_context,
                                  run_context=_run_context() if run_context is None else run_context)


class HappyAssembly(unittest.TestCase):
    def test_builds_and_renders(self):
        out = _build_report(_machine_record(), _lifecycle_result(), report_context=_report_context())
        self.assertIsInstance(out["weekly_report_md"], str)
        md = out["weekly_report_md"]
        for i in range(1, 14):
            self.assertIn("## %d." % i, md)            # all 13 sections rendered
        self.assertIn("price_clock", md)               # banner ④ always shown
        # the ①③⑤ banner tags must MATCH the frozen contract tags or the renderer would silently omit them
        for tag in ("true_false_observe_split", "ship_gate_progress", "hot_excluded_notice"):
            self.assertIn(tag, md)

    def test_all_13_sections_have_content(self):
        rd = _build_report(_machine_record(), _lifecycle_result(), report_context=_report_context())["report_data"]
        for i in range(1, 14):
            self.assertTrue(rd["sections"][i], f"section {i} empty")

    def test_lifecycle_count_reconciles(self):
        rd = _build_report(_machine_record(), _lifecycle_result(due_count=2, due_items=(1, 3)),
                                    report_context=_report_context())["report_data"]
        self.assertEqual(rd["lifecycle_reminder_count"], {"section_1": 2, "section_12": 2})
        self.assertIn("#1", str(rd["sections"][12]))   # due items surfaced in §12

    def test_banner_has_observe_split_and_hot_excluded(self):
        rd = _build_report(_machine_record(), _lifecycle_result(), report_context=_report_context())["report_data"]
        self.assertIn("true_false_observe_split", rd["banner"])   # ① derived from observe rows
        self.assertIn("hot_excluded_notice", rd["banner"])        # ⑤
        self.assertNotIn("macro_cluster_warning", rd["banner"])   # ② omitted when blank

    def test_macro_cluster_banner_shown_when_present(self):
        rd = _build_report(_machine_record(), _lifecycle_result(),
                                    report_context=_report_context(macro_cluster_banner="3 建仓同属 AI 集群"))["report_data"]
        self.assertEqual(rd["banner"]["macro_cluster_warning"], "3 建仓同属 AI 集群")

    def test_row_sections_derive_from_machine_rows(self):
        rd = _build_report(_machine_record(), _lifecycle_result(), report_context=_report_context())["report_data"]
        self.assertIn("AAA", str(rd["sections"][5]))   # 操作表 one-glance
        self.assertIn("HLD", str(rd["sections"][6]))   # 持仓复核
        self.assertIn("OBS", str(rd["sections"][8]))   # 观察池

    def test_not_clean_section_reflects_coverage_gap(self):
        rc = _report_context(coverage_inputs=[
            {"row_source": "holding_pass2_only", "data_checks": {"analyst": "missing", "sec_parse": "ok", "event": "ok"}}])
        rd = _build_report(_machine_record(), _lifecycle_result(), report_context=rc)["report_data"]
        self.assertIn("非 full", str(rd["sections"][13]))


class FailClosed(unittest.TestCase):
    def test_non_closed_world_report_context_rejected(self):
        with self.assertRaises(wr.WeekendReportError):     # missing a key
            _build_report(_machine_record(), _lifecycle_result(),
                                   report_context={k: v for k, v in _report_context().items() if k != "ship_gate_note"})
        with self.assertRaises(wr.WeekendReportError):     # extra key
            _build_report(_machine_record(), _lifecycle_result(),
                                   report_context={**_report_context(), "EXTRA": 1})

    def test_malformed_lifecycle_result_rejected(self):
        for bad in ({}, {"readiness": {}, "banner": "x"}, {"readiness": {"due_count": -1, "total_items": 39,
                    "due_items": [], "upgrade_eligible_items": []}, "banner": "x"},
                    {"readiness": _lifecycle_result()["readiness"], "banner": ""}):
            with self.assertRaises(wr.WeekendReportError):
                _build_report(_machine_record(), bad, report_context=_report_context())

    def test_blank_editorial_section_rejected(self):
        for key in ("account_risk_note", "core_conclusion", "provider_health_note", "ship_gate_note"):
            with self.assertRaises(wr.WeekendReportError):
                _build_report(_machine_record(), _lifecycle_result(), report_context=_report_context(**{key: "  "}))

    def test_malformed_coverage_input_rejected(self):
        with self.assertRaises(wr.WeekendReportError):
            _build_report(_machine_record(), _lifecycle_result(),
                                   report_context=_report_context(coverage_inputs=[{"row_source": "holding_pass2_only"}]))

    def test_bad_price_clock_rejected(self):
        # price_data_through not strictly before decision_date → the §21 gate raises (PriceClockError propagates)
        bad_pc = {"price_data_through": _AS_OF, "news_window_through": _AS_OF, "session_scope": "RTH",
                  "decision_date": _AS_OF}
        with self.assertRaises(Exception):
            _build_report(_machine_record(), _lifecycle_result(), report_context=_report_context(price_clock=bad_pc))

    def test_price_clock_must_match_run_context_price_basis(self):
        bad_pc = {"price_data_through": "20260108", "news_window_through": _AS_OF,
                  "session_scope": "RTH", "decision_date": _AS_OF}
        with self.assertRaises(wr.WeekendReportError):
            _build_report(_machine_record(), _lifecycle_result(), report_context=_report_context(price_clock=bad_pc))

    def test_price_clock_news_window_must_stop_at_run_date(self):
        rc = _report_context(price_clock={"price_data_through": "20260109", "news_window_through": _AS_OF,
                                          "session_scope": "RTH", "decision_date": _AS_OF})
        with self.assertRaises(wr.WeekendReportError):
            _build_report(_machine_record(), _lifecycle_result(), report_context=rc,
                          run_context=_run_context(run_date="20260110"))


class SourceReconciliation(unittest.TestCase):
    """R-USSHORT-BATCH4-WEEKLY-REPORT-SOURCE-RECONCILIATION-GAP: the official §11.2 report must thread ONE
    canonical decision_date through every artifact, re-assert the lifecycle readiness contract, and keep
    hot_excluded one source — so the report can never stitch different weeks / contradict itself."""

    def test_price_clock_decision_mismatch_rejected(self):
        bad_pc = {"price_data_through": "20260116", "news_window_through": "20260120",
                  "session_scope": "RTH", "decision_date": "20260120"}   # != machine as_of 20260112
        with self.assertRaises(wr.WeekendReportError):
            _build_report(_machine_record(), _lifecycle_result(), report_context=_report_context(price_clock=bad_pc))

    def test_lifecycle_decision_mismatch_rejected(self):
        with self.assertRaises(wr.WeekendReportError):   # lifecycle decision_date + readiness.as_of = a different week
            _build_report(_machine_record(), _lifecycle_result(decision_date="20260119"),
                                   report_context=_report_context())

    def test_exclusion_as_of_mismatch_rejected(self):
        rc = _report_context(exclusion_data={"as_of": "20260105", "categories": {},
                                             "hot_excluded": {"public_heat_count": 0, "holdings": []}})
        with self.assertRaises(wr.WeekendReportError):
            _build_report(_machine_record(), _lifecycle_result(), report_context=rc)

    def test_inconsistent_readiness_rejected(self):
        # due_count=2 but due_items=[] and upgrade=[7] — the single-source readiness contract rejects it
        bad_lr = _lifecycle_result(readiness_overrides={"due_count": 2, "due_items": [], "upgrade_eligible_items": [7]})
        with self.assertRaises(wr.WeekendReportError):
            _build_report(_machine_record(), bad_lr, report_context=_report_context())

    def test_hot_excluded_single_source(self):
        # one source (exclusion_data["hot_excluded"]) feeds BOTH the banner ⑤ and the §9 detail — they agree
        rc = _report_context(exclusion_data={"as_of": _AS_OF, "categories": {},
                                             "hot_excluded": {"public_heat_count": 3, "holdings": []}})
        rd = _build_report(_machine_record(), _lifecycle_result(), report_context=rc)["report_data"]
        self.assertIn("3", rd["banner"]["hot_excluded_notice"])      # ⑤ reflects the single source
        self.assertIn("3", "\n".join(rd["sections"][9]))             # §9 detail reflects the SAME source

    def test_old_hot_excluded_summary_key_rejected(self):
        # focused deleted-symbol guard: the removed dual-source key `report_context["hot_excluded_summary"]` must be
        # rejected (closed-world) so a future re-add is caught with a clear failure (not just the generic EXTRA test).
        rc = {**_report_context(), "hot_excluded_summary": {"public_heat_count": 2, "holdings": []}}
        with self.assertRaises(wr.WeekendReportError):
            _build_report(_machine_record(), _lifecycle_result(), report_context=rc)

    def test_valid_same_date_report_passes(self):  # positive control: all anchors == canonical
        out = _build_report(_machine_record(), _lifecycle_result(), report_context=_report_context())
        self.assertIn("## 1.", out["weekly_report_md"])


if __name__ == "__main__":
    unittest.main()
