"""No-network source-to-export coverage for the machine-computable Rule6 set."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"
COMPUTABLE_IDS = {
    "rule6_holder_below_5pct",
    "rule6_volume_stall",
    "rule6_margin_extreme_accumulation",
    "rule6_short_selling_surge",
    "rule6_cash_debt_double_high",
    "rule6_ar_growth_gt_revenue_growth",
    "rule6_block_trade_discount",
}


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_rule6_wiring_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class EgsRule6ComputableWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.egs = _load_egs_module()

    def _margin_observation(self, frame, dates, *, status=None):
        frame = frame.copy()
        status = status or ("complete" if not frame.empty else "unavailable")
        effective = dates[0] if not frame.empty else None
        universe = (
            int(frame["ts_code"].dropna().astype(str).nunique())
            if "ts_code" in frame.columns else 0
        )
        return self.egs.MarginObservation(
            frame, dates[0] if dates else None, effective, int(len(frame)),
            universe, status == "complete", status,
        )

    def test_api_inventory_and_full_source_bundle_emit_every_computable_check(self):
        em = self.egs
        self.assertTrue({"balancesheet", "block_trade"}.issubset(em.EGS_API_FAMILIES))
        self.assertTrue(any(
            isinstance(value, str) and "rqye" in value
            for value in em.get_margin.__code__.co_consts
        ))

        code = "600000.SH"
        dates = [f"202607{day:02d}" for day in range(14, 3, -1)]
        daily = pd.DataFrame([
            {"ts_code": code, "trade_date": date, "vol": 100.0,
             "pct_chg": 1.0, "high": 11.0, "low": 9.0, "close": 10.0,
             "qfq_high": 11.0, "qfq_low": 9.0, "qfq_close": 10.0, "qfq_pct_chg": 1.0}
            for date in dates
        ])
        margin = pd.DataFrame([
            {"ts_code": code, "trade_date": date, "rzye": 100.0, "rqye": 100.0}
            for date in dates
        ])
        balances = [{
            "ann_date": "20260714", "end_date": period,
            "money_cap": 100.0, "st_borr": 100.0, "total_assets": 1000.0,
            "accounts_receiv": receivables, "contract_liab": 100.0,
        } for period, receivables in {
            "20260331": 130.0, "20250331": 100.0,
            "20251231": 140.0, "20241231": 100.0,
        }.items()]
        financial = pd.DataFrame([{
            "ts_code": code,
            "q0_end_date": "20260331", "q0_ann_date": "20260430", "q0_revenue_yoy": 50.0,
            "q1_end_date": "20251231", "q1_ann_date": "20260331", "q1_revenue_yoy": 50.0,
        }])
        watch = pd.DataFrame({"ts_code": [code]})

        with patch.object(em, "get_rule6_balancesheets", return_value={code: balances}), \
             patch.object(em, "get_rule6_block_trades", return_value={date: [] for date in dates}):
            evaluations = em._collect_rule6_evaluations(
                watch, daily, self._margin_observation(margin, dates), dates,
                {"rule6_holder_events": []}, financial,
            )[code]

        self.assertEqual(set(evaluations), COMPUTABLE_IDS)
        self.assertEqual({item["status"] for item in evaluations.values()}, {"pass"})

        candidate = em._candidate_from_row(
            pd.Series({"ts_code": code, "close": 10.0}), 1, {code}, dates[0], set(), set(),
            rule6_evaluations=evaluations,
        )
        exported = {item["id"]: item for item in candidate["event_risk"]["rule6_checks"]}
        self.assertEqual({exported[check_id]["status"] for check_id in COMPUTABLE_IDS}, {"pass"})

    def test_missing_evaluation_is_unknown_not_a_clear_or_manual_only_disposition(self):
        em = self.egs
        candidate = em._candidate_from_row(
            pd.Series({"ts_code": "600000.SH", "close": 10.0}), 1, {"600000.SH"},
            "20260714", set(), set(), rule6_evaluations={},
        )
        exported = {item["id"]: item for item in candidate["event_risk"]["rule6_checks"]}
        for check_id in COMPUTABLE_IDS:
            with self.subTest(check_id=check_id):
                self.assertEqual(exported[check_id]["status"], "unknown")
                self.assertEqual(exported[check_id]["severity"], "watch")

    def test_non_margin_target_is_not_applicable_when_universe_present(self):
        em = self.egs
        code, other = "600000.SH", "000002.SZ"
        dates = [f"202607{day:02d}" for day in range(14, 3, -1)]
        daily = pd.DataFrame([
            {"ts_code": code, "trade_date": d, "vol": 100.0, "pct_chg": 1.0,
             "high": 11.0, "low": 9.0, "close": 10.0} for d in dates])
        # Universe present (covers dates[0]) but the candidate is absent from it.
        # (Floor patched low so a compact synthetic universe counts as complete;
        # the real floor is exercised by the sub-threshold test below.)
        margin = pd.DataFrame([
            {"ts_code": other, "trade_date": d, "rzye": 100.0, "rqye": 100.0} for d in dates])
        watch = pd.DataFrame({"ts_code": [code]})
        with patch.object(em, "MARGIN_ELIGIBILITY_MIN_UNIVERSE", 1), \
             patch.object(em, "get_rule6_balancesheets", return_value={code: []}), \
             patch.object(em, "get_rule6_block_trades", return_value={d: [] for d in dates}):
            ev = em._collect_rule6_evaluations(
                watch, daily, self._margin_observation(margin, dates), dates,
                {"rule6_holder_events": []}, pd.DataFrame())[code]
        self.assertEqual(ev["rule6_margin_extreme_accumulation"]["status"], "not_applicable")
        self.assertEqual(ev["rule6_short_selling_surge"]["status"], "not_applicable")

    def test_subthreshold_or_garbage_reference_universe_stays_unknown(self):
        # Fail-closed hardening: a non-empty but partial (below the real-universe
        # floor) or garbage-ts_code reference-date margin response must NOT be
        # read as a complete universe; absent candidates stay unknown, never
        # not_applicable (else a provider anomaly silently clears the vetoes).
        em = self.egs
        code = "600000.SH"
        dates = [f"202607{day:02d}" for day in range(14, 3, -1)]
        daily = pd.DataFrame([
            {"ts_code": code, "trade_date": d, "vol": 100.0, "pct_chg": 1.0,
             "high": 11.0, "low": 9.0, "close": 10.0} for d in dates])
        subthreshold = pd.DataFrame([
            {"ts_code": f"9000{i:02d}.SZ", "trade_date": d, "rzye": 100.0, "rqye": 100.0}
            for d in dates for i in range(3)])          # 3 codes << MARGIN_ELIGIBILITY_MIN_UNIVERSE
        garbage = pd.DataFrame([
            {"ts_code": float("nan"), "trade_date": d, "rzye": 100.0, "rqye": 100.0}
            for d in dates for _ in range(50)])         # rows exist but ts_code all null
        watch = pd.DataFrame({"ts_code": [code]})
        for label, margin in (("subthreshold", subthreshold), ("garbage", garbage)):
            with self.subTest(case=label), \
                 patch.object(em, "get_rule6_balancesheets", return_value={code: []}), \
                 patch.object(em, "get_rule6_block_trades", return_value={d: [] for d in dates}):
                ev = em._collect_rule6_evaluations(
                    watch, daily, self._margin_observation(margin, dates, status="incomplete"), dates,
                    {"rule6_holder_events": []}, pd.DataFrame())[code]
            self.assertEqual(ev["rule6_margin_extreme_accumulation"]["status"], "unknown")
            self.assertEqual(ev["rule6_short_selling_surge"]["status"], "unknown")

    def test_absent_margin_universe_stays_unknown_not_not_applicable(self):
        # Fail-open guard: an empty margin_df (fetch failed / not published) must
        # NOT be read as "every candidate is non-margin"; the two margin checks
        # stay unknown (fail-closed → manual_review), never silently cleared.
        em = self.egs
        code = "600000.SH"
        dates = [f"202607{day:02d}" for day in range(14, 3, -1)]
        daily = pd.DataFrame([
            {"ts_code": code, "trade_date": d, "vol": 100.0, "pct_chg": 1.0,
             "high": 11.0, "low": 9.0, "close": 10.0} for d in dates])
        watch = pd.DataFrame({"ts_code": [code]})
        with patch.object(em, "get_rule6_balancesheets", return_value={code: []}), \
             patch.object(em, "get_rule6_block_trades", return_value={d: [] for d in dates}):
            ev = em._collect_rule6_evaluations(
                watch, daily, self._margin_observation(pd.DataFrame(), dates), dates,
                {"rule6_holder_events": []}, pd.DataFrame())[code]
        self.assertEqual(ev["rule6_margin_extreme_accumulation"]["status"], "unknown")
        self.assertEqual(ev["rule6_short_selling_surge"]["status"], "unknown")

    def test_format_drifted_or_padded_reference_universe_stays_unknown(self):
        # ts_code namespace/format drift must not pass the floor as a complete
        # universe: canonicalization drops non-canonical shapes (suffix-less /
        # float / wrong case) and dedups whitespace variants by security, so a
        # drifted or duplicate-inflated response falls below the floor → unknown
        # (fail-closed), never a silent not_applicable clear for absent candidates.
        em = self.egs
        code = "600000.SH"
        dates = [f"202607{day:02d}" for day in range(14, 3, -1)]
        daily = pd.DataFrame([
            {"ts_code": code, "trade_date": d, "vol": 100.0, "pct_chg": 1.0,
             "high": 11.0, "low": 9.0, "close": 10.0} for d in dates])
        suffixless = pd.DataFrame([                       # 1100 codes, no exchange suffix → non-canonical
            {"ts_code": f"{600001 + i}", "trade_date": d, "rzye": 100.0, "rqye": 100.0}
            for d in dates for i in range(1100)])
        dup_padded = pd.DataFrame([                       # 800 real securities, leading+trailing-space dup
            {"ts_code": fmt.format(600001 + i), "trade_date": d, "rzye": 100.0, "rqye": 100.0}
            for d in dates for i in range(800) for fmt in (" {}.SH", "{}.SH ")])
        watch = pd.DataFrame({"ts_code": [code]})
        for label, margin in (("suffixless", suffixless), ("dup_padded", dup_padded)):
            with self.subTest(case=label), \
                 patch.object(em, "get_rule6_balancesheets", return_value={code: []}), \
                 patch.object(em, "get_rule6_block_trades", return_value={d: [] for d in dates}):
                ev = em._collect_rule6_evaluations(
                    watch, daily, self._margin_observation(margin, dates, status="incomplete"), dates,
                    {"rule6_holder_events": []}, pd.DataFrame())[code]
            self.assertEqual(ev["rule6_margin_extreme_accumulation"]["status"], "unknown")
            self.assertEqual(ev["rule6_short_selling_surge"]["status"], "unknown")

    def test_any_malformed_reference_row_fails_closed_to_unknown(self):
        # A clean, complete universe with even ONE malformed reference-date ts_code
        # (selective per-candidate corruption: trailing junk / digit typo / bad
        # symbol) must NOT be trusted to prove a candidate's absence -- eligibility
        # stays unknown, so a corrupt row can never silently clear the vetoes.
        em = self.egs
        code = "600000.SH"
        dates = [f"202607{day:02d}" for day in range(14, 3, -1)]
        daily = pd.DataFrame([
            {"ts_code": code, "trade_date": d, "vol": 100.0, "pct_chg": 1.0,
             "high": 11.0, "low": 9.0, "close": 10.0} for d in dates])
        clean = [{"ts_code": f"{600001 + i}.SH", "trade_date": d, "rzye": 100.0, "rqye": 100.0}
                 for d in dates for i in range(1100)]
        for label, bad in (("candidate_trailing_junk", "600000.SH*"),
                           ("candidate_digit_typo", "6000000.SH"),
                           ("other_ticker_bad_symbol", "60000A.SH")):
            margin = pd.DataFrame(clean + [
                {"ts_code": bad, "trade_date": dates[0], "rzye": 140.0, "rqye": 100.0}])
            watch = pd.DataFrame({"ts_code": [code]})
            with self.subTest(case=label), \
                 patch.object(em, "get_rule6_balancesheets", return_value={code: []}), \
                 patch.object(em, "get_rule6_block_trades", return_value={d: [] for d in dates}):
                ev = em._collect_rule6_evaluations(
                    watch, daily, self._margin_observation(margin, dates, status="incomplete"), dates,
                    {"rule6_holder_events": []}, pd.DataFrame())[code]
            self.assertEqual(ev["rule6_margin_extreme_accumulation"]["status"], "unknown")
            self.assertEqual(ev["rule6_short_selling_surge"]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
