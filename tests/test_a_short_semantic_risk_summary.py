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
    validate_summary_consistency, _sina_sources,
    _match_risk,
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
    explicit no-occupation negation'; everything else -> risk for web_llm advisory to downgrade.
    Residual errors are false positives only (web_llm advisory downgrades), never 漏报 (real risk hidden)."""

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
        # suppressed headlessly -> risk (web_llm advisory downgrades). Reverses the earlier over-suppression.
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


class SkillPatchPathRetired(unittest.TestCase):
    """Slice 3a retired the skill-patch web path (the DeepSeek adapter superseded it). These
    symbols/files must STAY gone; M6.7 uses runners/a_short_deepseek_semantic_adapter.judge_web_llm."""
    def test_patch_merge_functions_gone(self):
        import runners.a_short_semantic_risk_summary as m
        self.assertFalse(hasattr(m, "validate_web_llm_patch"))
        self.assertFalse(hasattr(m, "apply_web_llm_patch"))
        self.assertFalse(hasattr(m, "PATCH_SCHEMA_PATH"))

    def test_standalone_summary_cli_retired(self):
        # Slice 3b-2: the standalone summary CLI is retired (weekly_screening runs the M6.7 pipeline
        # instead); the reused builders stay for the M6.7 cninfo provider.
        import runners.a_short_semantic_risk_summary as m
        self.assertFalse(hasattr(m, "main"))
        self.assertFalse(hasattr(m, "write_summary"))
        self.assertFalse(hasattr(m, "_watch_pool_from_analysis_input"))
        self.assertTrue(hasattr(m, "build_summary_from_fetches"))   # reused by the M6.7 cninfo provider

    def test_patch_schema_and_skill_prompt_files_gone(self):
        self.assertFalse((ROOT / "schemas" / "a_short_semantic_risk_web_llm_patch.schema.json").exists())
        self.assertFalse((ROOT / "skills" / "a_short_analysis" / "prompts" / "semantic_risk_web_llm.md").exists())

    def test_web_llm_invariant_still_enforced_by_shared_fn(self):
        # the invariant the retired patch validator used now lives ONLY in _web_llm_consistency_error
        # (shared by the DeepSeek adapter + engine): no-evidence non-unknown rejected; neutral triple ok.
        from runners.a_short_semantic_risk_summary import _web_llm_consistency_error
        self.assertIsNotNone(_web_llm_consistency_error(
            {"status": "clear_light", "risk_level": "none", "action": "no_action"}, []))
        self.assertIsNone(_web_llm_consistency_error(
            {"status": "unknown", "risk_level": "unknown", "action": "no_action"}, []))

if __name__ == "__main__":
    unittest.main()
