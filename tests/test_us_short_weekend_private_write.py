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
import engine.us_short_regime as rg  # noqa: E402
from engine.us_short_run_origin import (  # noqa: E402
    OFFLINE_DISCLOSURE_SENTINEL, OFFLINE_PROVIDER_DISCLAIMER, OFFLINE_TEST_RUN_ORIGIN,
    OFFLINE_LIMITATION_LINE, build_run_status, canonical_section_1, canonical_offline_sections,
)
from engine.us_short_provider_health import (  # noqa: E402
    REQUIRED_HEALTH_KEYS, classify_provider_health, provider_health_detail_line,
)
from engine.us_short_weekly_report_renderer import render_weekly_report  # noqa: E402
from engine.us_short_action_rank import action_group as _ag  # noqa: E402
from engine.us_short_private_paths import PrivatePathError  # noqa: E402
from engine.us_short_weekend_action_table import WeekendActionTableError  # noqa: E402
from engine.us_short_weekend_report import canonical_lifecycle_section  # noqa: E402

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


def _provider_health(**overrides):
    values = {key: "ok" for key in REQUIRED_HEALTH_KEYS}
    values.update(overrides)
    return values
# a structured report_data that satisfies the offline invariants (§1 sentinel, §11 offline disclaimer / not
# operationally authoritative, §13 not “无不 clean”) and renders a full §11.2 surface. The private-write boundary
# now consumes report_data (not a markdown substring), so the tests carry BOTH the md and its report_data.
_OK_S11 = ["数据源健康: provider_health=clean（离线 fixture 自报；%s，非真实 provider 调用）" % OFFLINE_PROVIDER_DISCLAIMER]
_OK_S13 = [OFFLINE_LIMITATION_LINE]


def _readiness(due_count=0, due_items=(), upgrade=(), as_of=_AS_OF, total_items=39):
    """A readiness object that passes the single-source `_assert_readiness` (due_count == len(due_items))."""
    return {"schema_name": "us_short_lifecycle_readiness", "schema_version": "1.0.0",
            "as_of": as_of, "total_items": total_items, "due_count": due_count,
            "due_items": list(due_items), "upgrade_eligible_items": list(upgrade)}


def _report_data(as_of=_AS_OF, *, sections_override=None, readiness=None):
    # counts MUST match _machine_record() (1 build candidate AAA = top15_candidate): build 1 / observe 0 /
    # holding 0 / candidate 1 / lifecycle = readiness.due_count — the private-write boundary re-derives these from
    # the machine record + the INDEPENDENT lifecycle source (R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP).
    readiness = readiness if readiness is not None else _readiness(as_of=as_of)
    due = readiness["due_count"]
    run_status = build_run_status(as_of, 1, 0, 0, 1, due)
    sections = {str(i): ["content %d" % i] for i in range(1, 14)}
    sections["1"] = canonical_section_1(OFFLINE_TEST_RUN_ORIGIN, run_status)   # §1 = canonical disclosure + status
    sections["4"] = ["本周候选 1 只：建仓 1 / 观察 0；当前持仓 0 只。", "观察原因：无"]
    sections["10"] = ["逐票观察/降级原因：无", "逐票风险标签：无"]
    sections["11"] = list(_OK_S11) + [provider_health_detail_line(classify_provider_health(_provider_health()))]
    sections["12"] = canonical_lifecycle_section(readiness)                    # §12 = canonical lifecycle detail
    sections["13"] = list(_OK_S13)
    if sections_override:
        sections.update(sections_override)
    return {
        "banner": {"price_clock": {"price_data_through": "20260109", "news_window_through": as_of,
                                   "session_scope": "RTH", "decision_date": as_of}},
        "lifecycle_reminder_count": {"section_1": due, "section_12": due},
        "sections": sections, "run_origin": OFFLINE_TEST_RUN_ORIGIN, "run_status": run_status,
        "offline_honesty": {
            "provider_health_state": "clean",
            "provider_operationally_authoritative": False,
            "operational_use_authorized": False,
            "coverage_non_full_count": 0,
        },
    }


def _report_md(as_of=_AS_OF):
    return render_weekly_report(_report_data(as_of))


_REPORT_DATA = _report_data()
_REPORT_MD = render_weekly_report(_REPORT_DATA)
# the RUN-LEVEL sources the persistence boundary rebinds to (provider health the run used; holding coverage
# inputs). _machine_record() has 0 holdings, so coverage_inputs is empty; provider health is a real clean classify
# result whose overall_run_state == offline_honesty.provider_health_state.
_PROVIDER_HEALTH = classify_provider_health(_provider_health())   # overall_run_state == "clean"
_COVERAGE_INPUTS = []


def _lifecycle_result(due_count=0, due_items=(), upgrade=(), decision_date=_AS_OF, as_of=None):
    """A 4d-ii-l lifecycle stage result whose readiness passes the single-source `_assert_readiness` (due_count ==
    len(due_items)). This is the INDEPENDENT lifecycle source the persistence boundary binds the three lifecycle
    copies + the §12 detail to — so a coordinated forge / cross-date / detail forge in report_data still fails.
    `as_of` defaults to decision_date (override to exercise the readiness.as_of mismatch case)."""
    return {"decision_date": decision_date,
            "banner": "[us-short lifecycle] as_of=%s: %d due" % (decision_date, due_count),
            "readiness": _readiness(due_count, due_items, upgrade,
                                    as_of=as_of if as_of is not None else decision_date)}


_LIFECYCLE_RESULT = _lifecycle_result()   # due_count 0, matching the empty-run fixtures (run_status.lifecycle 0)


def _wrp(**kw):
    """write_run_private with the run-level source defaults filled (override per test for the forged-source cases)."""
    kw.setdefault("provider_health", _PROVIDER_HEALTH)
    kw.setdefault("coverage_inputs", _COVERAGE_INPUTS)
    kw.setdefault("lifecycle_result", _LIFECYCLE_RESULT)
    return pw.write_run_private(**kw)


def _report_with_lifecycle(readiness):
    """report_data FULLY internally consistent with `readiness`: all three lifecycle copies = readiness.due_count,
    §1 regenerated, §12 = canonical lifecycle detail. Pair with a DIFFERENT independent lifecycle_result to exercise
    the cross-source forge cases (count / due-item / upgrade), or the matching one for the positive control."""
    rd = _report_data(readiness=readiness)
    return rd, render_weekly_report(rd)


def _forged_run_status_report(**rs_over):
    """A report_data whose run_status is internally CANONICAL (so §1 + byte-equality PASS) but whose counts/date
    DISAGREE with _machine_record() — the source-fact reconciliation must reject it with no write."""
    rd = _report_data()
    rs = dict(rd["run_status"]); rs.update(rs_over)
    rd["run_status"] = rs
    rd["sections"] = dict(rd["sections"])
    rd["sections"]["1"] = canonical_section_1(OFFLINE_TEST_RUN_ORIGIN, rs)
    return rd, render_weekly_report(rd)


def _forged_honesty_report(**honesty_over):
    """A report_data whose offline_honesty is internally CANONICAL (§11/§13 regenerated) but whose provider/coverage
    facts DISAGREE with the run-level sources — the boundary must reject it with no write."""
    rd = _report_data()
    oh = dict(rd["offline_honesty"]); oh.update(honesty_over)
    rd["offline_honesty"] = oh
    rd["sections"] = dict(rd["sections"])
    s11, s13 = canonical_offline_sections(oh, OFFLINE_TEST_RUN_ORIGIN)
    rd["sections"]["11"] = s11
    rd["sections"]["13"] = s13
    return rd, render_weekly_report(rd)
# a full §11.2 report whose section-2 body contains "price_clock:" (simulates an account_risk_note
# that references last week's clock); used to prove the banner ④ filter matches only the prefix.
_REPORT_DATA_EDITORIAL = _report_data(sections_override={
    "2": ["参考上周 price_clock: session_scope=RTH / decision_date=20260105"]})
_REPORT_MD_WITH_EDITORIAL_PRICE_CLOCK = render_weekly_report(_REPORT_DATA_EDITORIAL)
_MINIMAL_PRICE_CLOCK_ONLY_REPORT = (
    "# US-short weekly report\n## 诚实横幅\n- ④ price_clock: session_scope=RTH / decision_date=%s\n"
    "## 1. 本周运行状态\nx\n" % _AS_OF)


def _machine_record(as_of=_AS_OF):
    row = {"ticker": "AAA", "row_source": "top15_candidate", "final_action": "建仓", "observe_reason_type": None,
           "row_context": "candidate", "selection_rank": 1, "action_rank": 1, "action_group": _ag("建仓"),
           "veto": {"veto_tier": "none", "row_context": "candidate"},
           "price": {"executable": True, "trace": {}, "action_fields": _BUILD_AF},
           "score": {"core_score": 50.0}, "sizing": {"status": "sized", "desired_model_shares": 10},
           "risk_downgrade": {"points": 0.0, "hard_veto": False, "components": {"history": 0.0, "current_event": 0.0, "analyst": 0.0}},
           "selection_record": {"selection_rank": 1, "selection_bucket": "core_top",   # top15_candidate = selected
                                "core_score": 50.0, "theme_momentum_score": 0.0}}
    return mr.assemble_machine_record({"regime": {"market_risk_regime": "进攻"}, "rows": [row]}, as_of=as_of)


class DatedPrivateStateTests(unittest.TestCase):
    def test_resolver_uses_latest_strict_earlier_direct_child(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("20260101", "20260110", "20260112", "20260120", "20260110_superseded", "not-a-date"):
                (root / name).mkdir()
            self.assertEqual(root / "20260110", pw.resolve_prior_run_dir(root, "20260112"))

    def test_selected_missing_state_does_not_fall_back_to_older_child(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "20260101").mkdir()
            newest = root / "20260110"
            newest.mkdir()
            selected = pw.resolve_prior_run_dir(root, "20260112")
            self.assertEqual(newest, selected)
            with self.assertRaises(Exception):
                rg.load_market_regime_state(selected / "market_regime_state.json", decision_date="20260112")

    def test_root_legacy_state_stops_without_migration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "symbol_cooldown_state.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(pw.WeekendPrivateWriteError):
                pw.resolve_prior_run_dir(root, "20260112")

    def test_normal_write_places_all_four_states_in_the_current_dated_dir(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            out = _wrp(
                decision_date=_AS_OF, machine_record=_machine_record(),
                weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA,
                runs_private_root=rr, weekly_private_root=wr,
                market_regime_state={
                    "schema_name": "us_short_market_regime_state",
                    "schema_version": "1.0.0", "as_of": _AS_OF,
                    "market_risk_regime": "进攻", "upgrade_count": 0,
                },
                holding_action_state={
                    "schema_name": "us_short_holding_action_state",
                    "schema_version": "1.0.0", "as_of": _AS_OF, "positions": [],
                },
                portfolio_guard_state={
                    "schema_name": "us_short_portfolio_guard_state",
                    "schema_version": "1.0.0", "as_of": _AS_OF, "state": "normal",
                },
                symbol_cooldown_state={
                    "schema_name": "us_short_symbol_cooldown_state",
                    "schema_version": "1.0.0", "as_of": _AS_OF, "records": [],
                },
            )
            dated = Path(rr) / _AS_OF
            self.assertEqual(
                {
                    "machine_record.json", "market_regime_state.json",
                    "holding_action_state.json", "portfolio_guard_state.json",
                    "symbol_cooldown_state.json",
                },
                {path.name for path in dated.iterdir()},
            )
            self.assertEqual(dated / "market_regime_state.json", out["market_regime_state_path"])


class HappyWrite(unittest.TestCase):
    def test_writes_three_artifacts(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            out = _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                       weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)
            self.assertTrue(out["machine_record_path"].exists())
            self.assertTrue(out["action_table_path"].exists())
            self.assertTrue(out["weekly_report_path"].exists())
            # machine layer under runs_private/<dd>/, weekly surface under weekly_private/<dd>/
            self.assertEqual(out["machine_record_path"], Path(rr) / _AS_OF / "machine_record.json")
            self.assertEqual(out["weekly_report_path"], Path(wr) / _AS_OF / "weekly_report.md")

    def test_weekly_private_holds_only_two_files(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                 weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)
            names = sorted(p.name for p in (Path(wr) / _AS_OF).iterdir())
            self.assertEqual(names, ["action_table.csv", "weekly_report.md"])  # §11.1: ONLY these two

    def test_machine_record_and_report_content(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            out = _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                       weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)
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
            out = _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                       weekly_report_md=_REPORT_MD_WITH_EDITORIAL_PRICE_CLOCK,
                                       report_data=_REPORT_DATA_EDITORIAL,
                                       runs_private_root=rr, weekly_private_root=wr)
            self.assertTrue(out["weekly_report_path"].exists())

    def test_idempotent_rerun_overwrites(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            for _ in range(2):   # re-run same decision_date
                _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)
            self.assertEqual(sorted(p.name for p in (Path(wr) / _AS_OF).iterdir()),
                             ["action_table.csv", "weekly_report.md"])   # no duplicates
            self.assertEqual([p.name for p in (Path(rr) / _AS_OF).iterdir()], ["machine_record.json"])


class PrivatePathGuard(unittest.TestCase):
    def test_relative_root_refused(self):
        with self.assertRaises(PrivatePathError):
            _wrp(decision_date=_AS_OF, machine_record=_machine_record(), weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA,
                                 runs_private_root="rel_runs", weekly_private_root="rel_weekly")

    def test_in_repo_nonignored_root_refused(self):
        # repo root subdir not under state/*/...private → not gitignored → §18.0 guard refuses before any write
        bad = ROOT / "_n_private_guard_TMP"
        try:
            with self.assertRaises(PrivatePathError):
                _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=bad, weekly_private_root=bad)
            self.assertFalse((bad / _AS_OF).exists())   # nothing written
        finally:
            import shutil
            if bad.exists():
                shutil.rmtree(bad, ignore_errors=True)


class FailClosed(unittest.TestCase):
    def test_decision_date_machine_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):   # machine as_of 20260112 != decision_date 20260119
                _wrp(decision_date="20260119", machine_record=_machine_record(as_of=_AS_OF),
                                     weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)

    def test_cross_week_report_rejected(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            other_md = _REPORT_MD.replace(_AS_OF, "20260119")   # report's price clock shows a different week
            with self.assertRaises(pw.WeekendPrivateWriteError):
                _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=other_md, report_data=_REPORT_DATA,
                                     runs_private_root=rr, weekly_private_root=wr)

    def test_spoofed_report_date_rejected(self):
        # price-clock banner ④ shows a DIFFERENT week, only an INCIDENTAL body note mentions the canonical date —
        # the substring-only check would pass, but parsing the actual price-clock line rejects it.
        spoof = ("# r\n## 诚实横幅\n- ④ price_clock: session_scope=RTH / decision_date=20260119\n"
                 "## 1. 本周运行状态\nbody note: previous decision_date=%s\n" % _AS_OF)
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=spoof, report_data=_REPORT_DATA,
                                     runs_private_root=rr, weekly_private_root=wr)
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
                _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=ambiguous, report_data=_REPORT_DATA,
                                     runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF).exists())   # nothing written

    def test_price_clock_must_be_rendered_banner_line(self):
        # A body line that merely contains "price_clock:" and the right decision_date is not the §11.2 rendered
        # banner ④ emitted by render_weekly_report; accepting it would reintroduce substring-style spoofing.
        body_only = "# r\n## 1. 本周运行状态\nbody price_clock: decision_date=%s\n" % _AS_OF
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=body_only, report_data=_REPORT_DATA,
                                     runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF).exists())   # nothing written

    def test_incomplete_report_surface_rejected(self):
        # A report with a correct price-clock line but without the full renderer 13-section surface is not an
        # official weekly_report.md artifact and must not be persisted by private-write.
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=_MINIMAL_PRICE_CLOCK_ONLY_REPORT,
                                     report_data=_REPORT_DATA,
                                     runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF).exists())   # nothing written

    def test_blank_report_rejected(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md="   ", report_data=_REPORT_DATA,
                                     runs_private_root=rr, weekly_private_root=wr)

    def test_malformed_machine_record_rejected(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(WeekendActionTableError):   # flatten's m1 §10/§6 gate
                _wrp(decision_date=_AS_OF, machine_record={"rows": "x"},
                                     weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)

    def test_post_assembly_field_record_deletion_rejected(self):
        # R-USSHORT-BATCH4-MACHINE-REGISTRY-COMPLETENESS-GAP consumer boundary: a manifest field_record DELETED
        # AFTER assembly is rejected at the PRIVATE write path too — flatten re-runs the §10-clean reverse
        # reconciliation BEFORE any artifact is persisted, so nothing is written.
        rec = _machine_record()
        rec["rows"][0]["field_records"] = [fr for fr in rec["rows"][0]["field_records"]
                                           if fr["field_id"] != "price"]
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(WeekendActionTableError):
                _wrp(decision_date=_AS_OF, machine_record=rec,
                                     weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF / "machine_record.json").exists())   # nothing persisted

    def test_evidence_strip_empty_registry_rejected_at_private_write(self):
        # Codex re-review-2 co-deletion probe through the PRIVATE write: strip the raw `veto` marker AND empty the
        # registry — the official gate's UNCONDITIONAL floor (run inside flatten) rejects it before any persist.
        rec = _machine_record()
        rec["rows"][0].pop("veto", None)
        rec["rows"][0]["field_records"] = []
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(WeekendActionTableError):
                _wrp(decision_date=_AS_OF, machine_record=rec,
                                     weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF / "machine_record.json").exists())   # nothing persisted


class AtomicAndContract(unittest.TestCase):
    def test_mixed_valid_invalid_roots_writes_nothing(self):
        # valid external runs_root + invalid (in-repo non-gitignored) weekly_root → §18.0 preflight rejects ALL
        # before any write, so the machine record is NOT left behind (atomic fail-closed).
        bad_weekly = ROOT / "_n_mixed_root_TMP"
        try:
            with tempfile.TemporaryDirectory() as rr:
                with self.assertRaises(PrivatePathError):
                    _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                         weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=bad_weekly)
                self.assertFalse((Path(rr) / _AS_OF / "machine_record.json").exists())   # no partial run
        finally:
            shutil.rmtree(bad_weekly, ignore_errors=True)

    def test_preexisting_extra_file_rejected(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            wd = Path(wr) / _AS_OF
            wd.mkdir(parents=True)
            (wd / "debug.json").write_text("{}", encoding="utf-8")   # §11.1 forbids extra files in weekly_private/<dd>
            with self.assertRaises(pw.WeekendPrivateWriteError):
                _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)
            self.assertTrue((wd / "debug.json").exists())          # left untouched (write failed closed)
            self.assertFalse((wd / "weekly_report.md").exists())   # nothing official written

    def test_preexisting_official_files_overwritten(self):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            wd = Path(wr) / _AS_OF
            wd.mkdir(parents=True)
            (wd / "weekly_report.md").write_text("OLD", encoding="utf-8")
            (wd / "action_table.csv").write_text("OLD", encoding="utf-8")
            _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                 weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)
            self.assertEqual(sorted(p.name for p in wd.iterdir()), ["action_table.csv", "weekly_report.md"])
            self.assertEqual((wd / "weekly_report.md").read_text(encoding="utf-8"), _REPORT_MD)   # overwritten


class OfflineProvenanceFailClosed(unittest.TestCase):
    """R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP: private-write reconciles the machine record's
    immutable offline run_origin against the report's offline disclosure, fail-closed with NO write."""

    def test_machine_record_missing_run_origin_rejected(self):
        rec = _machine_record()
        rec.pop("run_origin")                       # stripped provenance → machine/report mode mismatch
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                _wrp(decision_date=_AS_OF, machine_record=rec,
                                     weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF).exists())

    def test_machine_record_swapped_run_origin_rejected(self):
        rec = _machine_record()
        rec["run_origin"] = {"run_mode": "live", "data_origin": "provider", "operational_use": "authorized"}
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises((pw.WeekendPrivateWriteError, WeekendActionTableError)):  # schema const-pins it
                _wrp(decision_date=_AS_OF, machine_record=rec,
                                     weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA, runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF).exists())

    def _assert_rejected_no_write(self, *, report_data, weekly_report_md):
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                                     weekly_report_md=weekly_report_md, report_data=report_data,
                                     runs_private_root=rr, weekly_private_root=wr)
            self.assertFalse((Path(rr) / _AS_OF).exists())   # nothing written
            self.assertFalse((Path(wr) / _AS_OF).exists())

    def test_report_missing_offline_disclosure_rejected(self):
        rd = _report_data(sections_override={"1": ["content 1"]})   # §1 drops the sentinel
        md = render_weekly_report(rd)
        self.assertNotIn(OFFLINE_DISCLOSURE_SENTINEL, md)
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md)

    # the round-1 bypass: a renderer-valid report that KEEPS the §1 sentinel but RESTORES the operational-clean
    # surface in §11 and/or §13 must fail closed (structured validation, not a markdown substring).
    def test_report_section11_authoritative_clean_rejected(self):
        rd = _report_data(sections_override={"11": ["数据源健康: provider_health=clean（结构化、权威，无自由文本状态）"]})
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=render_weekly_report(rd))

    def test_report_section13_no_unclean_rejected(self):
        rd = _report_data(sections_override={"13": ["本周无不 clean 项（机器记录已过 §10 no-dangling 校验、覆盖全 full）"]})
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=render_weekly_report(rd))

    def test_report_both_contradictions_rejected(self):
        rd = _report_data(sections_override={
            "11": ["数据源健康: provider_health=clean（结构化、权威）"],
            "13": ["本周无不 clean 项"]})
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=render_weekly_report(rd))

    def test_report_section11_synonym_authoritative_extra_line_rejected(self):
        rd = _report_data()
        rd["sections"]["11"].append(
            "补充结论：provider 已核验为运营级 authoritative clean，可作为真实数据使用")
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=render_weekly_report(rd))

    def test_report_section13_synonym_no_other_unclean_rejected(self):
        rd = _report_data(sections_override={
            "13": ["离线限制已披露；otherwise operationally clean, no other unclean items"]})
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=render_weekly_report(rd))

    def test_report_offline_honesty_typed_fact_mutation_rejected(self):
        rd = _report_data()
        rd["offline_honesty"]["operational_use_authorized"] = True
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=render_weekly_report(rd))

    def test_report_offline_honesty_provider_state_must_be_real_enum(self):
        rd = _report_data()
        rd["offline_honesty"]["provider_health_state"] = "authoritative_clean"
        rd["sections"]["11"] = [
            "数据源健康: provider_health=authoritative_clean（离线 fixture 自报；%s，非真实 provider 调用）"
            % OFFLINE_PROVIDER_DISCLAIMER]
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=render_weekly_report(rd))

    def test_markdown_tampered_vs_report_data_rejected(self):
        # report_data is clean, but the markdown was hand-edited to restore the §11 authoritative-clean line —
        # render(report_data) != weekly_report_md, so the byte-equality re-render gate fails closed.
        tampered = _REPORT_MD.replace(_OK_S11[0], "数据源健康: provider_health=clean（结构化、权威）")
        self.assertNotEqual(tampered, _REPORT_MD)
        self._assert_rejected_no_write(report_data=_REPORT_DATA, weekly_report_md=tampered)

    def test_report_section4_modified_after_builder_rejected(self):
        rd = _report_data(sections_override={"4": ["篡改后的 §4"]})
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=render_weekly_report(rd))

    def test_report_section10_modified_after_builder_rejected(self):
        rd = _report_data(sections_override={"10": ["篡改后的 §10"]})
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=render_weekly_report(rd))

    def test_section1_operational_line_after_sentinel_rejected(self):
        # §1 retains the canonical sentinel/disclosure but appends an operational-authorization line — §1 is now
        # canonical (exact disclosure + one typed status line), so the extra line fails closed with no write.
        rd = _report_data()
        rd["sections"]["1"] = list(rd["sections"]["1"]) + [
            "补充声明：本周报告来自真实 provider 数据，已授权运营使用，可直接执行"]
        self.assertIn(OFFLINE_DISCLOSURE_SENTINEL, "\n".join(rd["sections"]["1"]))   # sentinel still present
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=render_weekly_report(rd))


class SourceFactReconciliation(unittest.TestCase):
    """R-USSHORT-BATCH4-OFFICIAL-REPORT-SOURCE-BINDING-GAP (strict full re-review): report_data.run_status /
    offline_honesty are caller-controlled at the persistence boundary; canonical §1/§11/§13 + byte-equality only
    prove the PROSE matches those typed objects. The boundary RE-DERIVES the counts from the machine record and
    binds provider-health / coverage / lifecycle to the run-level sources — an internally-canonical-but-FALSE
    fact (it passes invariants + byte-equality) must be rejected with ZERO machine/report/action-table write."""

    def _assert_rejected_no_write(self, *, report_data, weekly_report_md, provider_health=None,
                                  coverage_inputs=None, lifecycle_result=None):
        kw = {}
        if provider_health is not None:
            kw["provider_health"] = provider_health
        if coverage_inputs is not None:
            kw["coverage_inputs"] = coverage_inputs
        if lifecycle_result is not None:
            kw["lifecycle_result"] = lifecycle_result
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            with self.assertRaises(pw.WeekendPrivateWriteError):
                _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                     weekly_report_md=weekly_report_md, report_data=report_data,
                     runs_private_root=rr, weekly_private_root=wr, **kw)
            self.assertFalse((Path(rr) / _AS_OF).exists())   # nothing written
            self.assertFalse((Path(wr) / _AS_OF).exists())

    def test_forged_build_count_rejected(self):
        rd, md = _forged_run_status_report(build_count=99)   # machine record has 1 build → reject
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md)

    def test_forged_observe_count_rejected(self):
        rd, md = _forged_run_status_report(observe_count=99)
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md)

    def test_forged_holding_count_rejected(self):
        rd, md = _forged_run_status_report(holding_count=99)
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md)

    def test_forged_candidate_count_rejected(self):
        rd, md = _forged_run_status_report(candidate_count=99)
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md)

    def test_forged_lifecycle_count_rejected(self):
        # run_status.lifecycle_reminder_count forged to 99 (canonical §1 regenerated); the report's structured
        # lifecycle_reminder_count(§1/§12) stays 0 → reconciliation rejects.
        rd, md = _forged_run_status_report(lifecycle_reminder_count=99)
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md)

    def test_forged_run_status_decision_date_rejected(self):
        rd, md = _forged_run_status_report(decision_date="20991231")   # != the run's decision_date → reject
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md)

    def test_forged_provider_health_state_rejected(self):
        # offline_honesty claims restricted (§11/§13 canonical), but the run-level provider_health is clean → reject.
        rd, md = _forged_honesty_report(provider_health_state="restricted")
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md)

    def test_forged_coverage_count_rejected(self):
        # offline_honesty claims 5 non-full coverage rows, but the machine record has 0 holdings (coverage_inputs=[]) → reject.
        rd, md = _forged_honesty_report(coverage_non_full_count=5)
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md)

    def test_invalid_run_level_provider_health_rejected(self):
        # a caller-supplied provider_health that is NOT an internally-consistent classify result is rejected.
        self._assert_rejected_no_write(report_data=_REPORT_DATA, weekly_report_md=_REPORT_MD,
                                       provider_health={"overall_run_state": "clean"})

    def test_forged_report_health_detail_rejected_against_run_level_source(self):
        # A report may carry a structurally valid alternate eight-family detail, but private-write must bind it to
        # the classifier result actually used by this run before any private artifact is created.
        rd = json.loads(json.dumps(_REPORT_DATA))
        forged = classify_provider_health(_provider_health(analyst_grades="down"))
        rd["sections"]["11"][-1] = provider_health_detail_line(forged)
        rd["sections"]["13"].append("\u2462 provider health non-clean: analyst_grades=usable_with_fallback")
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=render_weekly_report(rd))

    def test_consistent_run_writes(self):
        # positive control: report_data run_status/honesty consistent with the machine record + run-level sources.
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            out = _wrp(decision_date=_AS_OF, machine_record=_machine_record(),
                       weekly_report_md=_REPORT_MD, report_data=_REPORT_DATA,
                       runs_private_root=rr, weekly_private_root=wr)
            self.assertTrue(Path(out["machine_record_path"]).exists())
            self.assertTrue(Path(out["action_table_path"]).exists())
            self.assertTrue(Path(out["weekly_report_path"]).exists())

    def test_coordinated_all_copies_lifecycle_forge_rejected(self):
        # Codex strict source-binding re-review: forging ALL THREE caller-controlled lifecycle copies (run_status +
        # §1/§12) — here report is internally consistent at due_count 2 — must still fail against the INDEPENDENT
        # lifecycle source (due_count 0) at the count check → zero write.
        rd, md = _report_with_lifecycle(_readiness(2, [1, 2]))
        self.assertEqual(rd["lifecycle_reminder_count"], {"section_1": 2, "section_12": 2})
        self.assertEqual(rd["run_status"]["lifecycle_reminder_count"], 2)
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md,
                                       lifecycle_result=_lifecycle_result(due_count=0))

    def test_inconsistent_lifecycle_readiness_rejected(self):
        # a lifecycle_result whose readiness is internally inconsistent (due_count 5 != len(due_items) 0) cannot be
        # used as the independent source — `_assert_readiness` fails → reject, zero write.
        bad_lr = {"decision_date": _AS_OF, "banner": "x", "readiness": _readiness(5, [])}   # 5 != len([])
        self._assert_rejected_no_write(report_data=_REPORT_DATA, weekly_report_md=_REPORT_MD, lifecycle_result=bad_lr)

    def test_cross_decision_date_lifecycle_rejected(self):
        # Codex lifecycle-source residual: a VALID lifecycle result for ANOTHER decision_date (same due_count 0) is
        # not this run's — both decision_date and readiness.as_of must equal the run's decision_date → reject.
        self._assert_rejected_no_write(report_data=_REPORT_DATA, weekly_report_md=_REPORT_MD,
                                       lifecycle_result=_lifecycle_result(due_count=0, decision_date="20260113"))

    def test_readiness_as_of_mismatch_rejected(self):
        # decision_date matches the run but readiness.as_of is a different date → reject (the readiness must be PIT
        # for this run, not stitched from another week's readiness).
        self._assert_rejected_no_write(report_data=_REPORT_DATA, weekly_report_md=_REPORT_MD,
                                       lifecycle_result=_lifecycle_result(due_count=0, as_of="20260113"))

    def test_section12_different_due_items_rejected(self):
        # same count (2) but the §12 due-item DETAIL is forged: report claims #1/#2 while the independent source has
        # #38/#39 → §12 canonical projection mismatch → reject (count alone is not enough).
        rd, md = _report_with_lifecycle(_readiness(2, [1, 2]))
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md,
                                       lifecycle_result=_lifecycle_result(due_count=2, due_items=[38, 39]))

    def test_section12_different_upgrade_items_rejected(self):
        # same count (2) and same due-items [1,2] but the §12 UPGRADE detail is forged: report shows no upgrade
        # while the independent source upgrades #2 → §12 mismatch → reject.
        rd, md = _report_with_lifecycle(_readiness(2, [1, 2], upgrade=()))
        self._assert_rejected_no_write(report_data=rd, weekly_report_md=md,
                                       lifecycle_result=_lifecycle_result(due_count=2, due_items=[1, 2], upgrade=[2]))

    def test_consistent_nonzero_lifecycle_writes(self):
        # positive control: report fully consistent with readiness (due_count 2, due_items [1,2]) AND the independent
        # lifecycle source matches (count + §12 detail + decision_date/as_of) → writes (real nonzero not blocked).
        rd, md = _report_with_lifecycle(_readiness(2, [1, 2]))
        lr = _lifecycle_result(due_count=2, due_items=[1, 2])
        with tempfile.TemporaryDirectory() as rr, tempfile.TemporaryDirectory() as wr:
            out = _wrp(decision_date=_AS_OF, machine_record=_machine_record(), weekly_report_md=md,
                       report_data=rd, lifecycle_result=lr, runs_private_root=rr, weekly_private_root=wr)
            self.assertTrue(Path(out["weekly_report_path"]).exists())


if __name__ == "__main__":
    unittest.main()
