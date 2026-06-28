# -*- coding: utf-8 -*-
"""Tests for US-short weekend idempotent private write (batch4 slice 4d-ii-n).

Covers: the machine layer + the §11.1 weekly_private surface (ONLY weekly_report.md + action_table.csv) are
written to the gitignored private dirs keyed by decision_date; the §18.0 P0 private-path guard refuses a
relative / non-gitignored in-repo destination BEFORE any write; the write is idempotent (re-running the same
decision_date overwrites, never duplicates); the action_table.csv is populated from the flattened record; and
fail-closed on a cross-week decision_date / weekly_report, spoofed or ambiguous price-clock markdown, a blank
report, and a malformed machine record. Pure/offline (private file writes only); no provider/live; no A-share
crossing.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_private_write as pw  # noqa: E402
import engine.us_short_weekend_machine_record as mr  # noqa: E402
from engine.us_short_weekly_report_renderer import render_weekly_report  # noqa: E402
from engine.us_short_action_rank import action_group as _ag  # noqa: E402
from engine.us_short_private_paths import PrivatePathError  # noqa: E402
from engine.us_short_weekend_action_table import WeekendActionTableError  # noqa: E402

_AS_OF = "20260112"
_BUILD_AF = {
    "order_type": "pullback_limit", "entry_plan": "pullback", "pullback_entry_price": 99.0,
    "breakout_entry_price": None, "limit_order_price": 101.0, "valid_entry_low": 99.0, "valid_entry_high": 101.0,
    "order_expiry": "first_regular_session_only", "gap_policy": "limit_band_first_session_no_chase",
    "effective_support": 98.0, "effective_resistance": 110.0, "structure_quality": "strong",
    "stop_clear_price": 98.0, "take_profit_reduce_price": 105.0, "take_profit_exit_price": 110.0,
    "risk_reward_ratio": 2.0, "min_rr_gate_status": "pass", "post_round_rr_status": "ok",
    "price_engine_used": "support_atr_engine", "price_sub_mode": "pullback",
}
def _report_md(as_of=_AS_OF):
    return render_weekly_report({
        "banner": {"price_clock": {"price_data_through": "20260109", "news_window_through": as_of,
                                   "session_scope": "RTH", "decision_date": as_of}},
        "lifecycle_reminder_count": {"section_1": 0, "section_12": 0},
        "sections": {str(i): ["content %d" % i] for i in range(1, 14)},
    })


_REPORT_MD = _report_md()
# a full §11.2 report whose section-2 body contains "price_clock:" (simulates an account_risk_note
# that references last week's clock); used to prove the banner ④ filter matches only the prefix.
_REPORT_MD_WITH_EDITORIAL_PRICE_CLOCK = render_weekly_report({
    "banner": {"price_clock": {"price_data_through": "20260109", "news_window_through": _AS_OF,
                               "session_scope": "RTH", "decision_date": _AS_OF}},
    "lifecycle_reminder_count": {"section_1": 0, "section_12": 0},
    "sections": {**{str(i): ["content %d" % i] for i in range(1, 14)},
                 "2": ["参考上周 price_clock: session_scope=RTH / decision_date=20260105"]},
})
_MINIMAL_PRICE_CLOCK_ONLY_REPORT = (
    "# US-short weekly report\n## 诚实横幅\n- ④ price_clock: session_scope=RTH / decision_date=%s\n"
    "## 1. 本周运行状态\nx\n" % _AS_OF)


def _machine_record(as_of=_AS_OF):
    row = {"ticker": "AAA", "row_source": "top15_candidate", "final_action": "建仓", "observe_reason_type": None,
           "row_context": "candidate", "selection_rank": 1, "action_rank": 1, "action_group": _ag("建仓"),
           "veto": {"veto_tier": "none", "row_context": "candidate"},
           "price": {"executable": True, "trace": {}, "action_fields": _BUILD_AF},
           "score": {"core_score": 50.0}, "sizing": {"status": "sized", "desired_model_shares": 10},
           "selection_record": {"selection_rank": 1, "selection_bucket": "core_top",   # top15_candidate = selected
                                "core_score": 50.0, "theme_momentum_score": 0.0}}
    return mr.assemble_machine_record({"regime": {"market_risk_regime": "进攻"}, "rows": [row]}, as_of=as_of)


class HappyWrite(unittest.TestCase):
    def test_writes_three_artifacts(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            out = pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                       weekly_report_md=_REPORT_MD, runs_private_root=rr, weekly_private_root=wr)
            self.assertTrue(out["machine_record_path"].exists())
            self.assertTrue(out["action_table_path"].exists())
            self.assertTrue(out["weekly_report_path"].exists())
            # machine layer under runs_private/<dd>/, weekly surface under weekly_private/<dd>/
            self.assertEqual(out["machine_record_path"], Path(rr) / _AS_OF / "machine_record.json")
            self.assertEqual(out["weekly_report_path"], Path(wr) / _AS_OF / "weekly_report.md")

    def test_weekly_private_holds_only_two_files(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                 weekly_report_md=_REPORT_MD, runs_private_root=rr, weekly_private_root=wr)
            names = sorted(p.name for p in (Path(wr) / _AS_OF).iterdir())
            self.assertEqual(names, ["action_table.csv", "weekly_report.md"])  # §11.1: ONLY these two

    def test_machine_record_and_report_content(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            out = pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                       weekly_report_md=_REPORT_MD, runs_private_root=rr, weekly_private_root=wr)
            rec = json.loads(out["machine_record_path"].read_text(encoding="utf-8"))
            self.assertEqual(rec["as_of"], _AS_OF)
            self.assertIn("field_records", rec["rows"][0])     # the §10 machine layer
            self.assertIn("valid_entry_high", out["action_table_path"].read_text(encoding="utf-8"))  # populated CSV header
            self.assertEqual(out["weekly_report_path"].read_text(encoding="utf-8"), _REPORT_MD)

    def test_editorial_body_with_price_clock_string_does_not_count_as_banner(self):
        # A valid §11.2 report where an editorial section body contains "price_clock:" must still pass —
        # it is not the rendered banner ④ line and must not be miscounted (the filter now matches prefix,
        # not substring).
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            out = pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                       weekly_report_md=_REPORT_MD_WITH_EDITORIAL_PRICE_CLOCK,
                                       runs_private_root=rr, weekly_private_root=wr)
            self.assertTrue(out["weekly_report_path"].exists())

    def test_idempotent_rerun_overwrites(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            for _ in range(2):   # re-run same decision_date
                pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=_REPORT_MD, runs_private_root=rr, weekly_private_root=wr)
            self.assertEqual(sorted(p.name for p in (Path(wr) / _AS_OF).iterdir()),
                             ["action_table.csv", "weekly_report.md"])   # no duplicates
            self.assertEqual([p.name for p in (Path(rr) / _AS_OF).iterdir()], ["machine_record.json"])


class PrivatePathGuard(unittest.TestCase):
    def test_relative_root_refused(self):
        with self.assertRaises(PrivatePathError):
            pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(), weekly_report_md=_REPORT_MD,
                                 runs_private_root="rel_runs", weekly_private_root="rel_weekly")

    def test_in_repo_nonignored_root_refused(self):
        # repo root subdir not under state/*/...private → not gitignored → §18.0 guard refuses before any write
        bad = ROOT / "_n_private_guard_TMP"
        try:
            with self.assertRaises(PrivatePathError):
                pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=_REPORT_MD, runs_private_root=bad, weekly_private_root=bad)
            self.assertFalse((bad / _AS_OF).exists())   # nothing written
        finally:
            import shutil
            if bad.exists():
                shutil.rmtree(bad, ignore_errors=True)


class FailClosed(unittest.TestCase):
    def test_decision_date_machine_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):   # machine as_of 20260112 != decision_date 20260119
                pw.write_run_private(decision_date="20260119", machine_record=_machine_record(as_of=_AS_OF),
                                     weekly_report_md=_REPORT_MD, runs_private_root=rr, weekly_private_root=wr)

    def test_cross_week_report_rejected(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            other_md = _REPORT_MD.replace(_AS_OF, "20260119")   # report's price clock shows a different week
            with self.assertRaises(pw.WeekendPrivateWriteError):
                pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=other_md, runs_private_root=rr, weekly_private_root=wr)

    def test_spoofed_report_date_rejected(self):
        # price-clock banner ④ shows a DIFFERENT week, only an INCIDENTAL body note mentions the canonical date —
        # the substring-only check would pass, but parsing the actual price-clock line rejects it.
        spoof = ("# r\n## 诚实横幅\n- ④ price_clock: session_scope=RTH / decision_date=20260119\n"
                 "## 1. 本周运行状态\nbody note: previous decision_date=%s\n" % _AS_OF)
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=spoof, runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF).exists())   # nothing written

    def test_duplicate_decision_date_on_price_clock_line_rejected(self):
        # Ambiguous rendered-line spoof: the first date is canonical but the same price-clock line also carries
        # another decision_date. The private writer must require a singleton decision_date token on the banner line.
        ambiguous = (
            "# r\n## 诚实横幅\n"
            "- ④ price_clock: session_scope=RTH / decision_date=%s / decision_date=20260119\n"
            "## 1. 本周运行状态\nx\n" % _AS_OF
        )
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=ambiguous, runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF).exists())   # nothing written

    def test_price_clock_must_be_rendered_banner_line(self):
        # A body line that merely contains "price_clock:" and the right decision_date is not the §11.2 rendered
        # banner ④ emitted by render_weekly_report; accepting it would reintroduce substring-style spoofing.
        body_only = "# r\n## 1. 本周运行状态\nbody price_clock: decision_date=%s\n" % _AS_OF
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=body_only, runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF).exists())   # nothing written

    def test_incomplete_report_surface_rejected(self):
        # A report with a correct price-clock line but without the full renderer 13-section surface is not an
        # official weekly_report.md artifact and must not be persisted by private-write.
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=_MINIMAL_PRICE_CLOCK_ONLY_REPORT,
                                     runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF).exists())   # nothing written

    def test_blank_report_rejected(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md="   ", runs_private_root=rr, weekly_private_root=wr)

    def test_malformed_machine_record_rejected(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(WeekendActionTableError):   # flatten's m1 §10/§6 gate
                pw.write_run_private(decision_date=_AS_OF, machine_record={"rows": "x"},
                                     weekly_report_md=_REPORT_MD, runs_private_root=rr, weekly_private_root=wr)


class AtomicAndContract(unittest.TestCase):
    def test_mixed_valid_invalid_roots_writes_nothing(self):
        # valid external runs_root + invalid (in-repo non-gitignored) weekly_root → §18.0 preflight rejects ALL
        # before any write, so the machine record is NOT left behind (atomic fail-closed).
        bad_weekly = ROOT / "_n_mixed_root_TMP"
        try:
            with tempfile.TemporaryDirectory() as rr:
                with self.assertRaises(PrivatePathError):
                    pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                         weekly_report_md=_REPORT_MD, runs_private_root=rr, weekly_private_root=bad_weekly)
                self.assertFalse((Path(rr) / _AS_OF / "machine_record.json").exists())   # no partial run
        finally:
            shutil.rmtree(bad_weekly, ignore_errors=True)

    def test_preexisting_extra_file_rejected(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            wd = Path(wr) / _AS_OF
            wd.mkdir(parents=True)
            (wd / "debug.json").write_text("{}", encoding="utf-8")   # §11.1 forbids extra files in weekly_private/<dd>
            with self.assertRaises(pw.WeekendPrivateWriteError):
                pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=_REPORT_MD, runs_private_root=rr, weekly_private_root=wr)
            self.assertTrue((wd / "debug.json").exists())          # left untouched (write failed closed)
            self.assertFalse((wd / "weekly_report.md").exists())   # nothing official written

    def test_preexisting_official_files_overwritten(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            wd = Path(wr) / _AS_OF
            wd.mkdir(parents=True)
            (wd / "weekly_report.md").write_text("OLD", encoding="utf-8")
            (wd / "action_table.csv").write_text("OLD", encoding="utf-8")
            pw.write_run_private(decision_date=_AS_OF, machine_record=_machine_record(),
                                 weekly_report_md=_REPORT_MD, runs_private_root=rr, weekly_private_root=wr)
            self.assertEqual(sorted(p.name for p in wd.iterdir()), ["action_table.csv", "weekly_report.md"])
            self.assertEqual((wd / "weekly_report.md").read_text(encoding="utf-8"), _REPORT_MD)   # overwritten


if __name__ == "__main__":
    unittest.main()
