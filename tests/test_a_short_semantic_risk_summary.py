"""Tests for the A-short semantic-risk advisory summary — Slice 2a (headless backbone).

Invariant matrix baked in up-front (lesson from the Slice-1 PIT saga): unknown-not-clear at the
official layer (fetch-fail / future / unparseable / non-dict / code-mismatch never => clear),
PIT on official events (canonical AND <= as_of), main-board-only universe, scan_tier deep/light/
upgraded correctness, advisory-only boundary, any non-unknown web status requires sources,
coverage counts.
Pure logic + schema + consistency. Synthetic fixtures; no live HTTP.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_semantic_risk_summary import (  # noqa: E402
    build_official_structured, _scan_tier, build_candidate, build_summary_from_fetches,
    validate_summary_consistency, write_summary, _sina_sources, render_semantic_risk_panel,
    _match_risk, validate_web_llm_patch, apply_web_llm_patch,
    _watch_pool_from_analysis_input, main as summary_main,
)

SCHEMA_PATH = ROOT / "schemas" / "a_short_semantic_risk_summary.schema.json"
AS_OF = "20260630"
EPOCH_MS = 1700000000000          # 2023-11-15, <= AS_OF


def _codes(n):
    return [f"6000{i:02d}.SH" for i in range(n)]


def _ann(code="600000", title="2025 年年度报告", t=EPOCH_MS, url="finalpage/x.pdf"):
    return {"announcementTitle": title, "adjunctUrl": url, "announcementTime": t, "secCode": code}


def _ok(ts, anns):
    return {"ts_code": ts, "ok": True, "error_category": None, "announcements": anns}


def _empty(ts):
    return {"ts_code": ts, "ok": True, "error_category": None, "announcements": []}


def _fail(ts):
    return {"ts_code": ts, "ok": False, "error_category": "orgid_map_failed", "announcements": []}


class OfficialStructured(unittest.TestCase):
    def test_clear_when_no_risk_and_clean(self):
        off, failed = build_official_structured(_ok("600000.SH", [_ann()]), AS_OF)
        self.assertEqual(off["status"], "clear")
        self.assertEqual(off["events"], [])
        self.assertFalse(failed)

    def test_risk_event_with_type_and_pit(self):
        off, _ = build_official_structured(
            _ok("600000.SH", [_ann(title="关于收到立案调查通知书的公告")]), AS_OF)
        self.assertEqual(off["status"], "risk")
        self.assertEqual(len(off["events"]), 1)
        ev = off["events"][0]
        self.assertEqual(ev["risk_type"], "investigation")
        self.assertEqual(ev["disclosure_date"], "20231115")
        self.assertTrue(ev["url_or_pdf"].startswith("http"))

    def test_fetch_fail_is_unknown(self):
        off, failed = build_official_structured(_fail("600000.SH"), AS_OF)
        self.assertEqual(off["status"], "unknown")
        self.assertTrue(failed)

    def test_future_event_excluded_and_unknown(self):
        off, _ = build_official_structured(
            _ok("600000.SH", [_ann(title="关于诉讼的公告", t="20990101")]), AS_OF)
        self.assertEqual(off["status"], "unknown")     # future row -> defect -> not clear, not risk
        self.assertEqual(off["events"], [])

    def test_unparseable_or_mismatch_is_unknown(self):
        off1, _ = build_official_structured(_ok("600000.SH", [_ann(t="garbage")]), AS_OF)
        self.assertEqual(off1["status"], "unknown")
        off2, _ = build_official_structured(_ok("600000.SH", [_ann(code="999999")]), AS_OF)
        self.assertEqual(off2["status"], "unknown")    # secCode mismatch -> can't trust
        off3, _ = build_official_structured(
            {"ts_code": "600000.SH", "ok": True, "announcements": ["not-a-dict"]}, AS_OF)
        self.assertEqual(off3["status"], "unknown")

    def test_risk_priority_over_defect(self):
        # a real PIT risk row plus a defective row -> still risk (real risk surfaced)
        off, _ = build_official_structured(
            _ok("600000.SH", [_ann(title="行政处罚决定书"), _ann(t="garbage")]), AS_OF)
        self.assertEqual(off["status"], "risk")
        self.assertEqual(len(off["events"]), 1)


class KeywordCalibration(unittest.TestCase):
    """Narrowest strategy: headless suppresses ONLY 'routine occupation disclosure form +
    explicit no-occupation negation'; everything else -> risk for the 2b skill to downgrade.
    Residual errors are false positives only (skill downgrades), never 漏报 (real risk hidden)."""

    def test_only_routine_form_WITH_negation_is_suppressed(self):
        # explicit no-occupation negation in a routine form -> clear (the only suppressed case)
        for t in ("关于公司不存在非经营性资金占用情况的专项说明",
                  "关于公司未发生非经营性资金占用情况的专项说明",
                  "关于公司无新增非经营性资金占用情况的专项说明",
                  "2025年度非经营性资金占用及其他关联资金往来情况汇总表(不存在占用)",
                  "关于公司不存在被控股股东非经营性资金占用情况的专项说明"):
            self.assertIsNone(_match_risk(t), t)

    def test_bare_routine_without_negation_now_surfaces_as_risk(self):
        # narrowest strategy: a routine special report WITHOUT an explicit negation is NOT
        # suppressed headlessly -> risk (skill downgrades). Reverses the earlier over-suppression.
        for t in ("上海浦发银行股份有限公司2025年度非经营性资金占用及对外担保情况的专项说明",
                  "控股股东及其他关联方非经营性资金占用及其他关联资金往来情况汇总表"):
            self.assertIsNotNone(_match_risk(t), t)

    def test_explicit_or_suspected_occupation_surfaces_as_risk(self):
        for t in ("关于公司存在非经营性资金占用情况的专项说明",
                  "关于公司发生非经营性资金占用情况的专项说明",
                  "关于公司被控股股东非经营性资金占用情况的专项说明",
                  "控股股东非经营性资金占用整改情况的专项报告",
                  "违规担保事项整改进展的专项报告",
                  "关于收到问询函的专项说明"):
            self.assertIsNotNone(_match_risk(t), t)

    def test_high_severity_always_risk(self):
        off, _ = build_official_structured(
            _ok("600000.SH", [_ann(title="关于收到立案调查通知书的专项说明")]), AS_OF)
        self.assertEqual(off["status"], "risk")
        self.assertEqual(off["events"][0]["severity"], "high")

    def test_severity_grading(self):
        self.assertEqual(_match_risk("关于立案调查的公告")[2], "high")
        self.assertEqual(_match_risk("收到监管问询函")[2], "medium")
        self.assertIsNone(_match_risk("2025年度业绩预告"))

    def test_event_carries_severity(self):
        off, _ = build_official_structured(
            _ok("600000.SH", [_ann(title="行政处罚决定书")]), AS_OF)
        self.assertEqual(off["events"][0]["severity"], "high")


class Panel(unittest.TestCase):
    def test_renders_flagged_with_advisory_labels(self):
        s = _summary(n_codes=6, risk_idx=(5,))            # rank6 risk(low, 诉讼)
        md = render_semantic_risk_panel(s)
        self.assertIn("as_of 20260630", md)
        self.assertIn("不可复现", md)
        self.assertIn("advisory", md)
        self.assertIn(s["candidates"][5]["ts_code"], md)  # the risk candidate listed
        self.assertIn("risk[", md)
        self.assertIn("unknown/unknown/no_action", md)    # headless web cell

    def test_all_clear_summarized(self):
        s = _summary(n_codes=6)                           # no risk
        md = render_semantic_risk_panel(s)
        self.assertIn("无需关注候选", md)


class ScanTier(unittest.TestCase):
    def test_deep_for_top5(self):
        self.assertEqual(_scan_tier(1, "clear"), "deep")
        self.assertEqual(_scan_tier(5, "risk"), "deep")     # deep ranks never 'upgraded'

    def test_light_and_upgrade(self):
        self.assertEqual(_scan_tier(6, "clear"), "light")
        self.assertEqual(_scan_tier(15, "unknown"), "light")
        self.assertEqual(_scan_tier(6, "risk"), "upgraded")  # hit-upgrade for Top6-15


class Candidate(unittest.TestCase):
    def test_web_llm_unknown_scaffold_and_boundary(self):
        c, _ = build_candidate("600000.SH", 1, _ok("600000.SH", [_ann()]), None, AS_OF)
        self.assertEqual(c["web_llm"], {"status": "unknown", "risk_level": "unknown",
                                        "action": "no_action"})
        self.assertEqual(c["boundary"], {"advisory_only": True, "not_deterministic_veto": True})
        self.assertIsNone(c["confidence"])

    def test_sina_sources_normalized(self):
        sina_raw = {"ts_code": "600000.SH", "ok": True,
                    "items": [{"title": "t", "url": "u", "published_at": "2026-06-01"}]}
        srcs = _sina_sources(sina_raw)
        self.assertEqual(srcs[0]["source_type"], "sina")
        self.assertEqual(srcs[0]["title"], "t")

    def test_sina_not_ok_yields_no_sources(self):
        self.assertEqual(_sina_sources({"ts_code": "x", "ok": False, "items": []}), [])


def _summary(n_codes=6, risk_idx=(), as_of=AS_OF, extra_pool=None):
    main = _codes(n_codes)
    cninfo = {}
    for i, ts in enumerate(main):
        if i in risk_idx:
            cninfo[ts] = _ok(ts, [_ann(code=ts.split(".")[0], title="重大诉讼公告")])
        else:
            cninfo[ts] = _ok(ts, [_ann(code=ts.split(".")[0])])
    pool = main + (extra_pool or [])
    return build_summary_from_fetches(pool, as_of, cninfo, None,
                                      "2026-06-30T12:00:00+08:00")


class BuildSummary(unittest.TestCase):
    def test_pipeline_and_coverage(self):
        s = _summary(n_codes=6, risk_idx=(5,))     # rank 6 has a risk
        self.assertEqual(len(s["candidates"]), 6)
        self.assertEqual(s["coverage"]["checked"], 6)
        self.assertEqual(s["coverage"]["unknown"], 0)
        self.assertEqual(s["candidates"][5]["scan_tier"], "upgraded")  # rank6 + risk
        validate_summary_consistency(s)

    def test_main_board_filter(self):
        s = _summary(n_codes=3, extra_pool=["300750.SZ", "688981.SH", "920083.BJ"])
        self.assertEqual(len(s["candidates"]), 3)
        self.assertIn("300750.SZ", s["universe"]["dropped_non_main"])
        validate_summary_consistency(s)

    def test_unknown_counted_not_clear(self):
        main = _codes(4)
        cninfo = {ts: _ok(ts, [_ann(code=ts.split(".")[0])]) for ts in main}
        cninfo[main[0]] = _fail(main[0])                 # fetch failure
        s = build_summary_from_fetches(main, AS_OF, cninfo, None, "2026-06-30T12:00:00+08:00")
        self.assertEqual(s["candidates"][0]["official_structured"]["status"], "unknown")
        self.assertEqual(s["coverage"]["unknown"], 1)
        self.assertEqual(s["coverage"]["failed"], 1)
        validate_summary_consistency(s)

    def test_batch_all_empty_downgraded_to_unknown(self):
        # the cninfo 200+empty failure signature: all 15 ok but empty -> must NOT be 15 clear
        main = _codes(15)
        cninfo = {ts: _empty(ts) for ts in main}
        s = build_summary_from_fetches(main, AS_OF, cninfo, None, "2026-06-30T12:00:00+08:00")
        self.assertEqual(s["coverage"]["checked"], 0)
        self.assertEqual(s["coverage"]["unknown"], 15)
        self.assertTrue(all(c["official_structured"]["status"] == "unknown" for c in s["candidates"]))
        validate_summary_consistency(s)

    def test_single_empty_in_healthy_batch_stays_clear(self):
        main = _codes(6)
        cninfo = {ts: _ok(ts, [_ann(code=ts.split(".")[0])]) for ts in main}
        cninfo[main[0]] = _empty(main[0])                # one genuinely empty, batch otherwise healthy
        s = build_summary_from_fetches(main, AS_OF, cninfo, None, "2026-06-30T12:00:00+08:00")
        self.assertEqual(s["candidates"][0]["official_structured"]["status"], "clear")
        validate_summary_consistency(s)

    def test_forged_all_empty_clear_raises(self):
        main = _codes(15)
        cninfo = {ts: _empty(ts) for ts in main}
        s = build_summary_from_fetches(main, AS_OF, cninfo, None, "2026-06-30T12:00:00+08:00")
        for c in s["candidates"]:                         # forge the batch back to all-clear (the bug)
            c["official_structured"]["status"] = "clear"
        s["coverage"] = {"checked": 15, "unknown": 0, "failed": 0}
        with self.assertRaises(ValueError):
            validate_summary_consistency(s)


class Consistency(unittest.TestCase):
    def test_happy(self):
        validate_summary_consistency(_summary())

    def test_rank_mismatch_raises(self):
        s = _summary()
        s["candidates"][0]["rank"] = 9
        with self.assertRaises(ValueError):
            validate_summary_consistency(s)

    def test_non_main_candidate_raises(self):
        s = _summary()
        s["candidates"][0]["ts_code"] = "300750.SZ"
        s["universe"]["main_board_top15"][0] = "300750.SZ"
        with self.assertRaises(ValueError):
            validate_summary_consistency(s)

    def test_clear_with_events_raises(self):
        s = _summary()
        s["candidates"][0]["official_structured"]["events"] = [
            {"source": "cninfo", "title": "x", "category": "c", "disclosure_date": "20260101",
             "url_or_pdf": "u", "risk_type": "litigation"}]
        with self.assertRaises(ValueError):
            validate_summary_consistency(s)

    def test_future_event_date_raises(self):
        s = _summary(risk_idx=(0,))
        s["candidates"][0]["official_structured"]["events"][0]["disclosure_date"] = "20990101"
        with self.assertRaises(ValueError):
            validate_summary_consistency(s)

    def test_wrong_scan_tier_raises(self):
        s = _summary()
        s["candidates"][0]["scan_tier"] = "light"     # rank1 must be deep
        with self.assertRaises(ValueError):
            validate_summary_consistency(s)

    def test_web_unknown_with_risk_level_raises(self):
        s = _summary()
        s["candidates"][0]["web_llm"]["risk_level"] = "high"   # but status unknown
        with self.assertRaises(ValueError):
            validate_summary_consistency(s)

    def test_web_unknown_with_soft_action_raises(self):
        # no-evidence (unknown) candidate must stay no_action; a soft action is rejected
        s = _summary()
        s["candidates"][0]["web_llm"]["action"] = "downgrade"   # status/risk_level still unknown
        with self.assertRaises(ValueError):
            validate_summary_consistency(s)

    def test_web_risk_status_without_sources_raises(self):
        s = _summary()
        s["candidates"][0]["web_llm"] = {"status": "risk", "risk_level": "high",
                                         "action": "manual_review_required"}
        s["candidates"][0]["sources"] = []
        with self.assertRaises(ValueError):
            validate_summary_consistency(s)

    def test_coverage_tamper_raises(self):
        s = _summary()
        s["coverage"]["checked"] += 1
        with self.assertRaises(ValueError):
            validate_summary_consistency(s)


class SchemaValidation(unittest.TestCase):
    def setUp(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_happy_validates(self):
        jsonschema.validate(_summary(), self.schema)

    def test_boundary_tamper_rejected(self):
        s = _summary()
        s["boundary"]["hard_veto"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(s, self.schema)

    def test_upgraded_rank_le5_rejected_by_schema(self):
        s = _summary()
        s["candidates"][0]["scan_tier"] = "upgraded"   # rank1 -> schema allOf rejects
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(s, self.schema)

    def test_advisory_boundary_const(self):
        s = _summary()
        s["candidates"][0]["boundary"]["not_deterministic_veto"] = False
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(s, self.schema)


_SRC = [{"title": "媒体负面报道", "url": "http://x", "published_at": "2026-06-10",
         "fetched_at": None, "source_type": "web"}]


def _pc(ts, status="clear_light", risk_level="none", action="no_action", sources=None,
        confidence=0.7, summary=None):
    # default carries evidence: any non-unknown web status now REQUIRES sources (unknown-not-clear).
    d = {"ts_code": ts, "web_llm": {"status": status, "risk_level": risk_level, "action": action},
         "sources": [dict(s) for s in _SRC] if sources is None else sources, "confidence": confidence}
    if summary is not None:
        d["summary"] = summary
    return d


def _patch(summary, items):
    return {
        "schema_name": "a_short_semantic_risk_web_llm_patch", "schema_version": "1.0.0",
        "generated_at": "2026-06-30T13:00:00+08:00",
        "target": {"as_of": summary["as_of"], "summary_schema_name": "a_short_semantic_risk_summary",
                   "summary_schema_version": "1.0.0"},
        "source": {"kind": "skill_web_llm", "prompt_refs": ["skills/a_short_analysis/prompts/x.md"]},
        "candidates": items,
        "boundary": {"advisory_only": True, "not_deterministic_veto": True,
                     "never_touches_official": True},
    }


class WebLlmPatch(unittest.TestCase):
    def test_happy_merge_and_official_untouched(self):
        s = _summary(n_codes=6, risk_idx=(5,))
        before_official = copy.deepcopy([c["official_structured"] for c in s["candidates"]])
        before_boundary = copy.deepcopy([c["boundary"] for c in s["candidates"]])
        before_scan = [c["scan_tier"] for c in s["candidates"]]
        ts0, ts1 = s["candidates"][0]["ts_code"], s["candidates"][5]["ts_code"]
        patch = _patch(s, [_pc(ts0, status="clear_light", risk_level="none", action="no_action"),
                           _pc(ts1, status="risk", risk_level="high",
                               action="manual_review_required", sources=_SRC, summary="实质风险")])
        new = apply_web_llm_patch(s, patch)
        self.assertEqual(new["candidates"][0]["web_llm"]["status"], "clear_light")
        self.assertEqual(new["candidates"][5]["web_llm"]["status"], "risk")
        self.assertEqual(new["candidates"][5]["summary"], "实质风险")
        # reverse-failure (checklist C): official_structured / boundary / scan_tier UNCHANGED
        self.assertEqual([c["official_structured"] for c in new["candidates"]], before_official)
        self.assertEqual([c["boundary"] for c in new["candidates"]], before_boundary)
        self.assertEqual([c["scan_tier"] for c in new["candidates"]], before_scan)
        validate_summary_consistency(new)

    def test_partial_patch_leaves_others_unknown(self):
        s = _summary(n_codes=6)
        new = apply_web_llm_patch(s, _patch(s, [_pc(s["candidates"][0]["ts_code"])]))
        self.assertEqual(new["candidates"][0]["web_llm"]["status"], "clear_light")
        self.assertEqual(new["candidates"][1]["web_llm"]["status"], "unknown")   # unpatched stays unknown

    def test_risk_status_without_sources_raises(self):
        s = _summary()
        p = _patch(s, [_pc(s["candidates"][0]["ts_code"], status="risk", risk_level="high",
                           action="downgrade", sources=[])])
        with self.assertRaises(ValueError):
            validate_web_llm_patch(p)

    def test_clear_light_without_coverage_raises(self):
        # unknown-not-clear: a clear conclusion with no evidence is indistinguishable from "not checked"
        s = _summary()
        p = _patch(s, [_pc(s["candidates"][0]["ts_code"], status="clear_light",
                           risk_level="none", action="no_action", sources=[])])
        with self.assertRaises(ValueError):
            validate_web_llm_patch(p)

    def test_tailwind_without_coverage_raises(self):
        s = _summary()
        p = _patch(s, [_pc(s["candidates"][0]["ts_code"], status="tailwind",
                           risk_level="low", action="observe", sources=[])])
        with self.assertRaises(ValueError):
            validate_web_llm_patch(p)

    def test_unknown_may_have_empty_sources(self):
        s = _summary()
        validate_web_llm_patch(_patch(s, [_pc(s["candidates"][0]["ts_code"], status="unknown",
                                              risk_level="unknown", action="no_action", sources=[])]))

    def test_unknown_with_risklevel_raises(self):
        s = _summary()
        p = _patch(s, [_pc(s["candidates"][0]["ts_code"], status="unknown", risk_level="high")])
        with self.assertRaises(ValueError):
            validate_web_llm_patch(p)

    def test_tailwind_high_raises(self):
        s = _summary()
        p = _patch(s, [_pc(s["candidates"][0]["ts_code"], status="tailwind", risk_level="high",
                           sources=_SRC)])
        with self.assertRaises(ValueError):
            validate_web_llm_patch(p)

    def test_duplicate_ts_code_raises(self):
        s = _summary()
        ts = s["candidates"][0]["ts_code"]
        with self.assertRaises(ValueError):
            validate_web_llm_patch(_patch(s, [_pc(ts), _pc(ts)]))

    def test_ts_code_not_in_summary_raises(self):
        s = _summary(n_codes=3)
        with self.assertRaises(ValueError):
            apply_web_llm_patch(s, _patch(s, [_pc("600099.SH")]))

    def test_as_of_mismatch_raises(self):
        s = _summary()
        p = _patch(s, [_pc(s["candidates"][0]["ts_code"])])
        p["target"]["as_of"] = "20260601"
        with self.assertRaises(ValueError):
            apply_web_llm_patch(s, p)

    def test_extra_key_in_patch_candidate_rejected_by_schema(self):
        s = _summary()
        pc = _pc(s["candidates"][0]["ts_code"])
        pc["official_structured"] = {"status": "clear", "events": [], "had_pit_announcements": True}
        with self.assertRaises(jsonschema.ValidationError):     # additionalProperties:false
            validate_web_llm_patch(_patch(s, [pc]))

    def test_no_stale_summary_after_clear_overwrite(self):
        # risk patch with a summary, then a clear patch WITHOUT summary -> old risk summary must vanish
        s = _summary(n_codes=6)
        ts = s["candidates"][0]["ts_code"]
        risky = apply_web_llm_patch(s, _patch(s, [_pc(ts, status="risk", risk_level="high",
                                                      action="manual_review_required", sources=_SRC,
                                                      summary="old risk summary")]))
        self.assertEqual(risky["candidates"][0]["summary"], "old risk summary")
        cleared = apply_web_llm_patch(risky, _patch(s, [_pc(ts, status="clear_light",
                                                            risk_level="none", action="no_action")]))
        self.assertNotIn("old risk summary", cleared["candidates"][0]["summary"])
        self.assertIn("clear_light", cleared["candidates"][0]["summary"])   # reflects current web state

    def test_summary_schema_name_mismatch_raises(self):
        s = _summary()
        s2 = copy.deepcopy(s)
        s2["schema_name"] = "wrong_schema_name"
        with self.assertRaises(ValueError):
            apply_web_llm_patch(s2, _patch(s, [_pc(s["candidates"][0]["ts_code"])]))

    def test_idempotent_overwrite_replaces_sources(self):
        s = _summary(n_codes=6)
        ts = s["candidates"][0]["ts_code"]
        p = _patch(s, [_pc(ts, status="risk", risk_level="medium", action="observe", sources=_SRC)])
        once = apply_web_llm_patch(s, p)
        twice = apply_web_llm_patch(once, p)        # re-apply same patch
        self.assertEqual(once["candidates"][0]["sources"], twice["candidates"][0]["sources"])
        self.assertEqual(len(twice["candidates"][0]["sources"]), 1)   # replaced, not appended


class WritePath(unittest.TestCase):
    def test_guard_rejects_production_path(self):
        from runners.a_short_semantic_risk_summary import _guard_out_path
        with self.assertRaises(ValueError):
            _guard_out_path("result/a_short/sem.json")

    def test_write_roundtrip(self):
        s = _summary(risk_idx=(5,))
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "sub" / "sem.json"
            write_summary(s, str(out))
            reloaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(reloaded["schema_name"], "a_short_semantic_risk_summary")


class AnalysisInputWatchPoolWiring(unittest.TestCase):
    """Slice 2b-ii-B+: weekly_screening Step-1 wiring — derive the watch pool from an EGS
    analysis_input + main(--analysis-input ...). cninfo_fetcher injected → no live HTTP."""

    def test_watch_pool_from_analysis_input_preserves_order_and_skips_blank(self):
        ai = {"trade_date": "20260605", "candidates": [
            {"ts_code": "600000.SH"}, {"ts_code": "000001.SZ"}, {"ts_code": ""},
            {"no_code": 1}, "not-a-dict", {"ts_code": "300750.SZ"}]}
        self.assertEqual(_watch_pool_from_analysis_input(ai),
                         ["600000.SH", "000001.SZ", "300750.SZ"])
        self.assertEqual(_watch_pool_from_analysis_input({}), [])

    def _fake_cninfo(self, main_codes, as_of, lookback_days):
        return [_empty(c) for c in main_codes]      # all clear, no network

    def _valid_ai(self, trade_date, codes):
        # schema+PIT-valid analysis_input (reuse the weekly test's repo-fixture builder)
        from tests.test_a_short_weekly_pipeline import _analysis_input, _ai_candidate
        return _analysis_input(trade_date=trade_date, candidates=[_ai_candidate(c) for c in codes])

    def test_main_analysis_input_builds_summary_from_egs_candidates(self):
        td = "20260609"
        with tempfile.TemporaryDirectory() as d:
            ai = self._valid_ai(td, ["600000.SH", "000001.SZ", "300750.SZ"])   # last ChiNext -> dropped
            ai_path = Path(d) / "analysis_input.json"
            ai_path.write_text(json.dumps(ai), encoding="utf-8")
            out = Path(d) / "sem.json"
            summary_main(["--as-of", td, "--analysis-input", str(ai_path), "--out", str(out),
                          "--confirm-fetch-authorized"], cninfo_fetcher=self._fake_cninfo)
            s = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(s["universe"]["requested"], ["600000.SH", "000001.SZ", "300750.SZ"])
        self.assertEqual(s["universe"]["main_board_top15"], ["600000.SH", "000001.SZ"])  # ChiNext dropped

    def test_main_analysis_input_stale_trade_date_aborts_no_write(self):
        # R-ASHORT-SEMANTIC-SUMMARY-ANALYSIS-INPUT-CONSUMER-VALIDATION-GAP: trade_date must == --as-of.
        with tempfile.TemporaryDirectory() as d:
            ai_path = Path(d) / "ai.json"
            ai_path.write_text(json.dumps(self._valid_ai("20260605", ["600000.SH"])), encoding="utf-8")
            out = Path(d) / "sem.json"
            with self.assertRaises(SystemExit):     # invoked with a different as_of
                summary_main(["--as-of", "20260609", "--analysis-input", str(ai_path), "--out", str(out),
                              "--confirm-fetch-authorized"], cninfo_fetcher=self._fake_cninfo)
            self.assertFalse(out.exists())

    def test_main_analysis_input_schema_invalid_aborts_no_write(self):
        with tempfile.TemporaryDirectory() as d:
            bad = self._valid_ai("20260609", ["600000.SH"]); del bad["source"]   # drop required field
            ai_path = Path(d) / "ai.json"; ai_path.write_text(json.dumps(bad), encoding="utf-8")
            out = Path(d) / "sem.json"
            with self.assertRaises((ValueError, SystemExit)):
                summary_main(["--as-of", "20260609", "--analysis-input", str(ai_path), "--out", str(out),
                              "--confirm-fetch-authorized"], cninfo_fetcher=self._fake_cninfo)
            self.assertFalse(out.exists())

    def test_main_requires_exactly_one_pool_source(self):
        with tempfile.TemporaryDirectory() as d:
            ai = {"trade_date": AS_OF, "candidates": [{"ts_code": "600000.SH"}]}
            ai_path = Path(d) / "ai.json"; ai_path.write_text(json.dumps(ai), encoding="utf-8")
            out = str(Path(d) / "o.json")
            with self.assertRaises(SystemExit):     # neither
                summary_main(["--as-of", AS_OF, "--out", out, "--confirm-fetch-authorized"],
                             cninfo_fetcher=self._fake_cninfo)
            with self.assertRaises(SystemExit):     # both
                summary_main(["--as-of", AS_OF, "--watch-pool", "600000.SH",
                              "--analysis-input", str(ai_path), "--out", out,
                              "--confirm-fetch-authorized"], cninfo_fetcher=self._fake_cninfo)


if __name__ == "__main__":
    unittest.main()
