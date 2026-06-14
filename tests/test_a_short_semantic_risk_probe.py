"""Tests for the A-short semantic-risk provider feasibility probe (Slice 1, probe-only).

Covers the design's stated probe goals: field presence, disclosure-date parseability (PIT),
secCode mapping, main-board Top15 input filtering, failure->unknown (never clear), no
production-path write, and the feasible=>all-gates-pass anti-fabrication invariant.
Pure logic + schema + consistency. Synthetic fixtures; no live HTTP / no fetch.
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

from runners.a_short_semantic_risk_probe import (  # noqa: E402
    main_board_top15, classify_cninfo_code, assess_cninfo_feasibility,
    classify_sina_code, assess_sina_feasibility, build_probe_summary,
    validate_probe_summary_consistency, write_probe_summary, _guard_out_path,
    _parse_disclosure_date, fetch_cninfo, fetch_cninfo_orgid_map, MIN_CNINFO_OK_CODES,
    fetch_em_news,
)

SCHEMA_PATH = ROOT / "schemas" / "a_short_semantic_risk_probe_summary.schema.json"
AS_OF = "20260630"
EPOCH_MS = 1700000000000          # 2023-11-15 (UTC+8), parses and <= AS_OF


def _codes(n):
    return [f"6000{i:02d}.SH" for i in range(n)]          # 600000.SH .. canonical main-board


def _ann(code="600000", title="2025 年年度报告", t=EPOCH_MS, url="finalpage/x.pdf"):
    return {"announcementTitle": title, "adjunctUrl": url, "announcementTime": t, "secCode": code}


def _cninfo_ok(ts, anns):
    return {"ts_code": ts, "ok": True, "error_category": None, "announcements": anns}


def _cninfo_empty(ts):
    return {"ts_code": ts, "ok": True, "error_category": None, "announcements": []}


def _cninfo_fail(ts, cat="network"):
    return {"ts_code": ts, "ok": False, "error_category": cat, "announcements": []}


def _feasible_cninfo_raw(n_ok=12, n_announced=4):
    main = _codes(n_ok)
    raw = []
    for i, ts in enumerate(main):
        if i < n_announced:
            raw.append(_cninfo_ok(ts, [_ann(code=ts.split(".")[0])]))
        else:
            raw.append(_cninfo_empty(ts))
    return main, raw


def _feasible_summary(as_of=AS_OF):
    main, raw = _feasible_cninfo_raw()
    cninfo = assess_cninfo_feasibility(raw, as_of)
    sina = assess_sina_feasibility([], as_of)
    universe = {"requested": main, "main_board_top15": main, "dropped_non_main": []}
    return build_probe_summary(universe, cninfo, sina, as_of, "2026-06-30T12:00:00+08:00")


class MainBoardTop15(unittest.TestCase):
    def test_drops_non_main_and_caps_and_dedups(self):
        pool = (["600000.SH", "000001.SZ", "002415.SZ"]          # main
                + ["300750.SZ", "688981.SH", "920083.BJ", "200001.SZ", "900901.SH"]  # non-main
                + ["600000.SH"]                                   # dup
                + [f"6010{i:02d}.SH" for i in range(20)])         # 20 more main -> forces cap
        main, dropped = main_board_top15(pool)
        self.assertEqual(len(main), 15)
        self.assertTrue(all("." in c for c in main))
        for c in main:
            from engine.data.a_share_board_scope import is_a_share_main_board
            self.assertTrue(is_a_share_main_board(c))
        for c in ["300750.SZ", "688981.SH", "920083.BJ", "200001.SZ", "900901.SH"]:
            self.assertIn(c, dropped)
        self.assertEqual(main.count("600000.SH"), 1)              # deduped


class CninfoClassify(unittest.TestCase):
    def test_fail_is_unknown_never_clear(self):
        c = classify_cninfo_code(_cninfo_fail("600000.SH", "anti_scrape"), AS_OF)
        self.assertFalse(c["ok"])
        self.assertEqual(c["status"], "unknown")
        self.assertIsNone(c["required_fields_ok"])

    def test_empty_ok_is_clear_light(self):
        c = classify_cninfo_code(_cninfo_empty("600000.SH"), AS_OF)
        self.assertEqual(c["status"], "clear_light")
        self.assertEqual(c["n_announcements"], 0)

    def test_announced_all_ok(self):
        c = classify_cninfo_code(_cninfo_ok("600000.SH", [_ann(code="600000")]), AS_OF)
        self.assertTrue(c["required_fields_ok"])
        self.assertTrue(c["dates_pit_ok"])
        self.assertTrue(c["code_mapping_ok"])
        self.assertEqual(c["n_announcements"], 1)
        self.assertEqual(c["n_future_dated"], 0)
        self.assertEqual(c["status"], "clear_light")

    def test_missing_required_field_flags(self):
        ann = _ann(code="600000")
        del ann["adjunctUrl"]
        c = classify_cninfo_code(_cninfo_ok("600000.SH", [ann]), AS_OF)
        self.assertFalse(c["required_fields_ok"])
        self.assertEqual(c["status"], "unknown")         # invalid fields -> not clear

    def test_unparseable_date_flags(self):
        c = classify_cninfo_code(_cninfo_ok("600000.SH", [_ann(code="600000", t="garbage")]), AS_OF)
        self.assertFalse(c["dates_pit_ok"])
        self.assertEqual(c["n_announcements"], 0)        # unparseable not counted as PIT evidence

    def test_code_mapping_mismatch_flags(self):
        c = classify_cninfo_code(_cninfo_ok("600000.SH", [_ann(code="999999")]), AS_OF)
        self.assertFalse(c["code_mapping_ok"])
        self.assertEqual(c["status"], "unknown")         # mapping mismatch -> not clear

    def test_regulator_keyword_is_risk_candidate(self):
        c = classify_cninfo_code(_cninfo_ok("600000.SH", [_ann(code="600000", title="收到立案调查通知书")]), AS_OF)
        self.assertEqual(c["status"], "risk_candidate")

    def test_future_canonical_date_not_pit(self):
        c = classify_cninfo_code(_cninfo_ok("600000.SH", [_ann(code="600000", t="20990101")]), AS_OF)
        self.assertEqual(c["n_future_dated"], 1)
        self.assertEqual(c["n_announcements"], 0)        # future excluded from PIT evidence
        self.assertFalse(c["dates_pit_ok"])
        self.assertEqual(c["status"], "unknown")         # future-row quality defect -> not clear

    def test_future_epoch_ms_not_pit(self):
        c = classify_cninfo_code(_cninfo_ok("600000.SH", [_ann(code="600000", t=4070908800000)]), AS_OF)
        self.assertEqual(c["n_future_dated"], 1)
        self.assertEqual(c["n_announcements"], 0)

    def test_future_regulator_row_cannot_be_risk_candidate(self):
        c = classify_cninfo_code(
            _cninfo_ok("600000.SH", [_ann(code="600000", title="收到立案调查通知书", t="20990101")]), AS_OF)
        self.assertEqual(c["status"], "unknown")             # future veto-keyword row -> unknown, not risk/clear
        self.assertEqual(c["n_future_dated"], 1)

    def test_mixed_past_future(self):
        c = classify_cninfo_code(_cninfo_ok("600000.SH",
                                            [_ann(code="600000"), _ann(code="600000", t="20990101")]), AS_OF)
        self.assertEqual(c["n_announcements"], 1)            # only the past one counts
        self.assertEqual(c["n_future_dated"], 1)
        self.assertFalse(c["dates_pit_ok"])                  # mixed -> not PIT-clean

    def test_unparseable_date_row_counted_not_dropped(self):
        c = classify_cninfo_code(_cninfo_ok("600000.SH", [_ann(code="600000", t="garbage")]), AS_OF)
        self.assertEqual(c["n_returned"], 1)
        self.assertEqual(c["n_unparseable_dates"], 1)
        self.assertEqual(c["n_announcements"], 0)
        self.assertFalse(c["dates_pit_ok"])
        self.assertEqual(c["status"], "unknown")             # unparseable -> not clear

    def test_non_dict_row_counted_not_dropped(self):
        c = classify_cninfo_code({"ts_code": "600000.SH", "ok": True, "error_category": None,
                                  "announcements": ["i-am-not-a-dict", _ann(code="600000")]}, AS_OF)
        self.assertEqual(c["n_returned"], 2)                 # raw count BEFORE isinstance filter
        self.assertEqual(c["n_bad_shape"], 1)
        self.assertEqual(c["n_announcements"], 1)
        self.assertFalse(c["dates_pit_ok"])                  # bad-shape row -> not clean
        self.assertEqual(c["status"], "unknown")             # bad-shape -> not clear even with a PIT row

    def test_partition_sums_to_n_returned(self):
        c = classify_cninfo_code({"ts_code": "600000.SH", "ok": True, "error_category": None,
                                  "announcements": [_ann(code="600000"), _ann(code="600000", t="20990101"),
                                                    _ann(code="600000", t="garbage"), 42]}, AS_OF)
        self.assertEqual(c["n_returned"], 4)
        self.assertEqual(c["n_announcements"] + c["n_future_dated"]
                         + c["n_unparseable_dates"] + c["n_bad_shape"], 4)


class DateParsing(unittest.TestCase):
    def test_epoch_ms(self):
        self.assertEqual(_parse_disclosure_date(EPOCH_MS), "20231115")

    def test_iso_string(self):
        self.assertEqual(_parse_disclosure_date("2026-01-15"), "20260115")

    def test_canonical_string(self):
        self.assertEqual(_parse_disclosure_date("20260115"), "20260115")

    def test_garbage_none(self):
        self.assertIsNone(_parse_disclosure_date("not-a-date"))
        self.assertIsNone(_parse_disclosure_date(None))


class CninfoAssess(unittest.TestCase):
    def test_feasible_happy(self):
        _, raw = _feasible_cninfo_raw()
        a = assess_cninfo_feasibility(raw, AS_OF)
        self.assertTrue(a["feasible"], a["reasons"])
        self.assertEqual(a["reasons"], [])
        self.assertEqual(a["n_ok"], 12)
        self.assertEqual(a["n_announced"], 4)

    def test_not_enough_ok_codes(self):
        main = _codes(MIN_CNINFO_OK_CODES - 1)
        raw = [_cninfo_ok(ts, [_ann(code=ts.split(".")[0])]) for ts in main]
        a = assess_cninfo_feasibility(raw, AS_OF)
        self.assertFalse(a["feasible"])
        self.assertTrue(any("provider 不够可达" in r for r in a["reasons"]))

    def test_low_ratio(self):
        main = _codes(20)
        raw = [_cninfo_ok(ts, [_ann(code=ts.split(".")[0])]) if i < 11 else _cninfo_fail(ts)
               for i, ts in enumerate(main)]            # 11 ok / 20 = 0.55 < 0.6
        a = assess_cninfo_feasibility(raw, AS_OF)
        self.assertFalse(a["feasible"])
        self.assertTrue(any("成功率" in r for r in a["reasons"]))

    def test_not_enough_announced(self):
        main = _codes(12)
        raw = [_cninfo_ok(ts, [_ann(code=ts.split(".")[0])]) if i < 2 else _cninfo_empty(ts)
               for i, ts in enumerate(main)]            # only 2 announced < 3
        a = assess_cninfo_feasibility(raw, AS_OF)
        self.assertFalse(a["feasible"])
        self.assertTrue(any("无法验证字段" in r for r in a["reasons"]))

    def test_field_drift_blocks_feasible(self):
        main = _codes(12)
        raw = []
        for i, ts in enumerate(main):
            if i < 4:
                ann = _ann(code=ts.split(".")[0])
                if i == 0:
                    del ann["secCode"]                  # field drift on one announced code
                raw.append(_cninfo_ok(ts, [ann]))
            else:
                raw.append(_cninfo_empty(ts))
        a = assess_cninfo_feasibility(raw, AS_OF)
        self.assertFalse(a["feasible"])
        self.assertTrue(any("字段漂移" in r for r in a["reasons"]))

    def test_invalid_as_of_blocks(self):
        _, raw = _feasible_cninfo_raw()
        a = assess_cninfo_feasibility(raw, "20261301")   # invalid month
        self.assertFalse(a["feasible"])
        self.assertFalse(a["as_of_is_valid_date"])

    def test_future_dated_announcements_block_feasible(self):
        # exact Codex repro: would-be-feasible codes whose announcements are all future-dated
        main = _codes(12)
        raw = []
        for i, ts in enumerate(main):
            if i < 4:
                raw.append(_cninfo_ok(ts, [_ann(code=ts.split(".")[0], t="20990101")]))  # future
            else:
                raw.append(_cninfo_empty(ts))
        a = assess_cninfo_feasibility(raw, AS_OF)
        self.assertFalse(a["feasible"])                  # future rows must NOT make it feasible
        self.assertEqual(a["n_announced"], 0)            # future excluded -> nothing announced
        self.assertEqual(a["n_future_dated_codes"], 4)
        self.assertTrue(any("未来日期" in r for r in a["reasons"]))

    def test_mixed_future_blocks_feasible(self):
        # enough PIT-announced codes, but some also carry a future row -> future-date gate fails
        main = _codes(12)
        raw = []
        for i, ts in enumerate(main):
            sym = ts.split(".")[0]
            if i < 4:
                raw.append(_cninfo_ok(ts, [_ann(code=sym), _ann(code=sym, t="20990101")]))
            else:
                raw.append(_cninfo_empty(ts))
        a = assess_cninfo_feasibility(raw, AS_OF)
        self.assertEqual(a["n_announced"], 4)            # past rows still announced
        self.assertEqual(a["n_future_dated_codes"], 4)
        self.assertFalse(a["feasible"])                  # but future-date gate blocks feasibility

    def test_unparseable_date_code_blocks_feasible(self):
        # exact Codex repro: 4 clean PIT-announced + 1 code whose only row has a bad date
        main = _codes(12)
        raw = []
        for i, ts in enumerate(main):
            sym = ts.split(".")[0]
            if i < 4:
                raw.append(_cninfo_ok(ts, [_ann(code=sym)]))
            elif i == 4:
                raw.append(_cninfo_ok(ts, [_ann(code=sym, t="not-a-date")]))
            else:
                raw.append(_cninfo_empty(ts))
        a = assess_cninfo_feasibility(raw, AS_OF)
        self.assertEqual(a["n_unparseable_date_codes"], 1)
        self.assertFalse(a["feasible"])                  # bad-date code must block feasibility
        self.assertTrue(any("不可解析" in r for r in a["reasons"]))

    def test_non_dict_row_code_blocks_feasible(self):
        # exact Codex repro: 4 clean PIT-announced + 1 code with a non-dict returned row
        main = _codes(12)
        raw = []
        for i, ts in enumerate(main):
            sym = ts.split(".")[0]
            if i < 4:
                raw.append(_cninfo_ok(ts, [_ann(code=sym)]))
            elif i == 4:
                raw.append({"ts_code": ts, "ok": True, "error_category": None,
                            "announcements": ["malformed-non-dict-row"]})
            else:
                raw.append(_cninfo_empty(ts))
        a = assess_cninfo_feasibility(raw, AS_OF)
        self.assertEqual(a["n_bad_shape_codes"], 1)
        self.assertFalse(a["feasible"])                  # malformed row must block feasibility
        self.assertTrue(any("非字典" in r for r in a["reasons"]))


class SinaAssess(unittest.TestCase):
    def test_not_run_not_feasible(self):
        a = assess_sina_feasibility([], AS_OF)
        self.assertFalse(a["feasible"])
        self.assertEqual(a["n_requested"], 0)
        self.assertIs(a["pit_capable"], False)

    def test_feasible_happy(self):
        main = _codes(10)
        raw = []
        for i, ts in enumerate(main):
            if i < 8:
                raw.append({"ts_code": ts, "ok": True, "error_category": None,
                            "items": [{"title": "t", "url": "u"}, {"title": "t2", "url": "u2"}]})
            else:
                raw.append({"ts_code": ts, "ok": False, "error_category": "network", "items": []})
        a = assess_sina_feasibility(raw, AS_OF)
        self.assertTrue(a["feasible"], a["reasons"])
        self.assertIs(a["pit_capable"], False)

    def test_failure_is_unknown(self):
        c = classify_sina_code({"ts_code": "600000.SH", "ok": False, "error_category": "network", "items": []})
        self.assertEqual(c["status"], "unknown")


class Consistency(unittest.TestCase):
    def test_happy_validates(self):
        validate_probe_summary_consistency(_feasible_summary())   # no raise

    def test_top_feasible_must_equal_cninfo(self):
        s = _feasible_summary()
        s["feasible"] = False
        with self.assertRaises(ValueError):
            validate_probe_summary_consistency(s)

    def test_failure_unknown_invariant(self):
        s = _feasible_summary()
        # inject a failed code but mislabel it clear_light -> must raise
        s["cninfo"]["per_code"].append({"ts_code": "600099.SH", "ok": False,
                                        "error_category": "network", "n_returned": 0,
                                        "n_announcements": 0, "n_future_dated": 0,
                                        "n_unparseable_dates": 0, "n_bad_shape": 0,
                                        "required_fields_ok": None, "dates_pit_ok": None,
                                        "code_mapping_ok": None, "status": "clear_light"})
        with self.assertRaises(ValueError):
            validate_probe_summary_consistency(s)

    def test_feasible_true_with_gate_fail_raises(self):
        s = _feasible_summary()
        s["cninfo"]["n_ok"] = 1                          # contradicts feasible=true
        with self.assertRaises(ValueError):
            validate_probe_summary_consistency(s)

    def test_cninfo_nrequested_must_equal_main(self):
        s = _feasible_summary()
        s["universe"]["main_board_top15"] = s["universe"]["main_board_top15"][:5]
        with self.assertRaises(ValueError):
            validate_probe_summary_consistency(s)

    def test_universe_rejects_non_main(self):
        s = _feasible_summary()
        s["universe"]["main_board_top15"].append("300750.SZ")
        with self.assertRaises(ValueError):
            validate_probe_summary_consistency(s)

    def test_defective_row_labelled_clear_raises(self):
        # a code with a future-dated row but mislabelled clear_light must be rejected
        s = _feasible_summary()
        c = s["cninfo"]["per_code"][0]
        c["n_future_dated"] = 1
        c["n_returned"] = c["n_announcements"] + 1
        c["dates_pit_ok"] = False
        c["status"] = "clear_light"                          # the violation
        with self.assertRaises(ValueError):
            validate_probe_summary_consistency(s)


class SchemaValidation(unittest.TestCase):
    def setUp(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_happy_validates(self):
        jsonschema.validate(_feasible_summary(), self.schema)

    def test_boundary_must_be_all_false(self):
        s = _feasible_summary()
        s["boundary"]["hard_veto"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(s, self.schema)

    def test_feasible_true_requires_cninfo_feasible(self):
        s = _feasible_summary()
        s["cninfo"]["feasible"] = False                  # but top feasible stays true
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(s, self.schema)


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


class _FakeCninfo:
    """No-network stand-in: get() returns the orgId stock-list JSON, post() returns announcements
    keyed by the exact `stock` param (so a test can assert the orgId was used in the query)."""
    def __init__(self, orgmap_status=200, orgmap_rows=None, ann_for_stock=None):
        self.orgmap_status = orgmap_status
        self.orgmap_rows = orgmap_rows if orgmap_rows is not None else []
        self.ann_for_stock = ann_for_stock or {}
        self.posted_stocks = []

    def get(self, url, **kw):
        return _Resp(self.orgmap_status, {"stockList": self.orgmap_rows})

    def post(self, url, data=None, **kw):
        stock = (data or {}).get("stock")
        self.posted_stocks.append(stock)
        return _Resp(200, {"announcements": self.ann_for_stock.get(stock, [])})


class FetchCninfoOrgId(unittest.TestCase):
    def test_orgid_map_parsed(self):
        sess = _FakeCninfo(orgmap_rows=[{"code": "600519", "orgId": "gssh0600519"},
                                        {"code": "000001", "orgId": "gssz0000001"}])
        m, ok = fetch_cninfo_orgid_map(sess)
        self.assertTrue(ok)
        self.assertEqual(m["600519"], "gssh0600519")
        self.assertEqual(m["000001"], "gssz0000001")

    def test_orgid_map_fetch_failure(self):
        m, ok = fetch_cninfo_orgid_map(_FakeCninfo(orgmap_status=500))
        self.assertFalse(ok)
        self.assertEqual(m, {})

    def test_fetch_uses_orgid_and_returns_announcements(self):
        ann = [_ann(code="600519")]
        sess = _FakeCninfo(orgmap_rows=[{"code": "600519", "orgId": "gssh0600519"}],
                           ann_for_stock={"600519,gssh0600519": ann})
        res = fetch_cninfo(["600519.SH"], AS_OF, request_delay=0, session=sess)
        self.assertTrue(res[0]["ok"])
        self.assertEqual(res[0]["announcements"], ann)
        self.assertIn("600519,gssh0600519", sess.posted_stocks)   # orgId actually used in query

    def test_code_without_orgid_is_no_orgid_failure(self):
        sess = _FakeCninfo(orgmap_rows=[{"code": "600519", "orgId": "gssh0600519"}])
        res = fetch_cninfo(["000001.SZ"], AS_OF, request_delay=0, session=sess)
        self.assertFalse(res[0]["ok"])
        self.assertEqual(res[0]["error_category"], "no_orgid")
        # flows through pure logic as a failure -> unknown, never clear
        self.assertEqual(classify_cninfo_code(res[0], AS_OF)["status"], "unknown")

    def test_orgid_map_failed_marks_all_codes(self):
        sess = _FakeCninfo(orgmap_status=503)
        res = fetch_cninfo(["600519.SH", "000001.SZ"], AS_OF, request_delay=0, session=sess)
        self.assertTrue(all(not r["ok"] and r["error_category"] == "orgid_map_failed" for r in res))
        a = assess_cninfo_feasibility(res, AS_OF)
        self.assertFalse(a["feasible"])
        self.assertEqual(a["failure_categories"].get("orgid_map_failed"), 2)


class WritePath(unittest.TestCase):
    def test_guard_rejects_production_path(self):
        with self.assertRaises(ValueError):
            _guard_out_path("result/a_short/probe.json")

    def test_write_roundtrip_research_lane(self):
        s = _feasible_summary()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "sub" / "probe.json"
            write_probe_summary(s, str(out))
            reloaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(reloaded["feasible"])
        self.assertEqual(reloaded["schema_name"], "a_short_semantic_risk_probe_summary")


class FetchEmNews(unittest.TestCase):
    """em 资讯 fetch:JSONP 剥壳 → result.cmsArticleWeb → normalize → PIT 近 N 天窗过滤 + 倒序 cap;
    fail-closed(无 name / 非 200 / 坏 as_of → ok:False、items:[])。合成 fixture,无真 HTTP(对齐 `执行` 实测 shape)。"""
    class _Resp:
        def __init__(self, text, status=200):
            self.text, self.status_code = text, status

    class _Sess:
        def __init__(self, body, status=200):
            self._body, self._status = body, status

        def get(self, url, headers=None, timeout=None):
            return FetchEmNews._Resp(self._body, self._status)

    def _jsonp(self, items):
        return "cb(" + json.dumps({"code": 0, "result": {"cmsArticleWeb": items}}, ensure_ascii=False) + ")"

    def test_jsonp_parse_recency_filter_and_cap(self):
        items = [
            {"title": "近期负面A", "url": "http://e/a", "date": "2026-06-07 10:00:00"},   # in window, newest
            {"title": "近期负面B", "url": "http://e/b", "date": "2026-05-20 09:00:00"},   # in window
            {"title": "陈年旧文", "url": "http://e/old", "date": "2024-02-19 17:48:16"},  # out of window → drop
            {"title": "未来文PIT泄漏", "url": "http://e/f", "date": "2026-06-20 08:00:00"},  # > as_of → drop
            {"title": "缺URL", "url": "", "date": "2026-06-06 08:00:00"},                  # no url → drop
        ]
        out = fetch_em_news(["600519.SH"], {"600519.SH": "贵州茅台"}, "20260609",
                            lookback_days=30, cap=5, session=self._Sess(self._jsonp(items)))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["ok"])
        self.assertEqual([it["title"] for it in out[0]["items"]], ["近期负面A", "近期负面B"])  # in-window, date-desc
        self.assertEqual(out[0]["items"][0]["published_at"], "2026-06-07 10:00:00")
        self.assertEqual(set(out[0]["items"][0]), {"title", "url", "published_at"})

    def test_cap_limits_to_newest(self):
        items = [{"title": f"t{i}", "url": f"http://e/{i}", "date": f"2026-06-0{i} 10:00:00"} for i in range(1, 6)]
        out = fetch_em_news(["600519.SH"], {"600519.SH": "茅台"}, "20260609",
                            lookback_days=60, cap=2, session=self._Sess(self._jsonp(items)))
        self.assertEqual(len(out[0]["items"]), 2)                       # capped
        self.assertEqual(out[0]["items"][0]["published_at"], "2026-06-05 10:00:00")  # newest first

    def test_no_name_is_ok_false(self):
        out = fetch_em_news(["600519.SH"], {}, "20260609", session=self._Sess(self._jsonp([])))
        self.assertFalse(out[0]["ok"])
        self.assertEqual(out[0]["error_category"], "no_name")

    def test_non_200_is_ok_false(self):
        out = fetch_em_news(["600519.SH"], {"600519.SH": "茅台"}, "20260609",
                            session=self._Sess("blocked", status=403))
        self.assertFalse(out[0]["ok"])
        self.assertEqual(out[0]["error_category"], "anti_scrape")

    def test_bad_as_of_all_ok_false(self):
        out = fetch_em_news(["600519.SH"], {"600519.SH": "茅台"}, "2026-06-09",
                            session=self._Sess("x"))
        self.assertFalse(out[0]["ok"])
        self.assertEqual(out[0]["error_category"], "bad_as_of")


if __name__ == "__main__":
    unittest.main()
