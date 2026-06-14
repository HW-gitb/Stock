"""Adversarial tests for the EM (东方财富) news-feed feasibility probe.

Covers the defect-class × exit matrix (recent / quiet / stale / future / bad-date / bad-shape /
transport-fail), the reverse-failure self-checks (a future-dated / unparseable / malformed item
must make the code `unknown`, NEVER `reachable`), feasibility gates, consistency invariants
(incl. hand-forged-summary rejection), the production-path write guard, schema validity, and the
thin CLI via an injected fetcher (no real HTTP)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402

from runners.a_short_em_news_probe import (  # noqa: E402
    MIN_EM_OK_CODES, assess_em_feasibility, build_em_probe_summary, classify_em_code,
    fetch_em_news_unfiltered, validate_em_probe_summary_consistency, write_em_probe_summary,
    main, SCHEMA_PATH,
)

AS_OF = "20260609"          # window [2026-05-10, 2026-06-09] at lookback 30
GEN = "2026-06-09T10:00:00+08:00"

# 15 canonical A-share MAIN-BOARD codes (600/601/603/605 .SH + 000/001/002/003 .SZ)
MAIN15 = ["600000.SH", "600519.SH", "601318.SH", "603259.SH", "605499.SH",
          "000001.SZ", "000002.SZ", "001979.SZ", "002415.SZ", "003816.SZ",
          "600036.SH", "600276.SH", "600887.SH", "601012.SH", "000333.SZ"]


def _item(title="负面新闻", url="http://e/a", date="2026-06-07 10:00:00"):
    return {"title": title, "url": url, "published_at": date}


def _ok(ts, items):
    return {"ts_code": ts, "ok": True, "error_category": None, "items": list(items)}


def _fail(ts, cat="anti_scrape"):
    return {"ts_code": ts, "ok": False, "error_category": cat, "items": []}


def _recent(ts):
    return _ok(ts, [_item()])


def _all_recent():
    return [_recent(ts) for ts in MAIN15]


def _summary(raws, *, as_of=AS_OF, lookback=30, main=None, dropped=None, requested=None):
    em = assess_em_feasibility(raws, as_of, lookback)
    main = list(MAIN15) if main is None else main
    universe = {"requested": requested if requested is not None else list(main),
                "main_board_top15": main, "dropped_non_main": dropped or []}
    return build_em_probe_summary(universe, em, as_of, GEN)


# ── classify_em_code: defect-class × exit matrix ─────────────────────────────
class ClassifyEmCode(unittest.TestCase):
    def test_recent_news_is_reachable_with_news(self):
        c = classify_em_code(_ok("600000.SH", [_item(date="2026-06-07 10:00:00")]), AS_OF, 30)
        self.assertEqual(c["status"], "reachable_with_news")
        self.assertEqual((c["n_items"], c["n_recent"], c["n_future"]), (1, 1, 0))

    def test_zero_items_is_reachable_quiet(self):
        c = classify_em_code(_ok("600000.SH", []), AS_OF, 30)
        self.assertEqual(c["status"], "reachable_quiet")
        self.assertEqual((c["n_items"], c["n_recent"]), (0, 0))

    def test_stale_only_is_quiet_not_defect(self):
        # 2026-04-01 is PIT-ok (<= as_of) but older than the 30d window start -> stale, NOT a defect
        c = classify_em_code(_ok("600000.SH", [_item(date="2026-04-01 09:00:00")]), AS_OF, 30)
        self.assertEqual(c["status"], "reachable_quiet")
        self.assertEqual((c["n_stale"], c["n_recent"], c["n_future"], c["n_bad_date"]), (1, 0, 0, 0))

    def test_transport_failure_is_unknown(self):
        for cat in ("no_name", "anti_scrape", "network", "bad_as_of"):
            c = classify_em_code(_fail("600000.SH", cat), AS_OF, 30)
            self.assertEqual(c["status"], "unknown")
            self.assertEqual(c["error_category"], cat)

    def test_future_dated_item_is_unknown_never_reachable(self):
        # PIT leak: published_at > as_of must make the code unknown (the core advisory safety property)
        c = classify_em_code(_ok("600000.SH", [_item(date="2026-06-20 08:00:00")]), AS_OF, 30)
        self.assertEqual(c["status"], "unknown")
        self.assertEqual((c["n_future"], c["n_recent"]), (1, 0))

    def test_bad_date_item_is_unknown(self):
        c = classify_em_code(_ok("600000.SH", [_item(date="not-a-date")]), AS_OF, 30)
        self.assertEqual(c["status"], "unknown")
        self.assertEqual(c["n_bad_date"], 1)

    def test_bad_shape_item_is_unknown(self):
        c = classify_em_code(_ok("600000.SH", [{"title": "t", "url": "", "published_at": "2026-06-07 10:00:00"}]),
                             AS_OF, 30)
        self.assertEqual(c["status"], "unknown")
        self.assertEqual(c["n_bad_shape"], 1)

    def test_non_dict_item_is_bad_shape(self):
        c = classify_em_code(_ok("600000.SH", ["a string"]), AS_OF, 30)
        self.assertEqual(c["status"], "unknown")
        self.assertEqual(c["n_bad_shape"], 1)

    def test_defect_wins_even_with_a_recent_item(self):
        # one recent + one future -> defect present -> unknown (must NOT be reachable_with_news)
        c = classify_em_code(_ok("600000.SH", [_item(date="2026-06-07 10:00:00"),
                                               _item(date="2026-06-20 08:00:00")]), AS_OF, 30)
        self.assertEqual(c["status"], "unknown")
        self.assertEqual((c["n_recent"], c["n_future"], c["n_items"]), (1, 1, 2))

    def test_exact_partition(self):
        items = [_item(date="2026-06-07 10:00:00"),   # recent
                 _item(date="2026-06-20 08:00:00"),   # future
                 _item(date="2026-04-01 09:00:00"),   # stale
                 _item(date="bad"),                   # bad_date
                 {"title": "", "url": "u", "published_at": "2026-06-06 08:00:00"}]  # bad_shape
        c = classify_em_code(_ok("600000.SH", items), AS_OF, 30)
        self.assertEqual(c["n_recent"] + c["n_future"] + c["n_stale"] + c["n_bad_date"]
                         + c["n_bad_shape"], c["n_items"])
        self.assertEqual((c["n_recent"], c["n_future"], c["n_stale"], c["n_bad_date"], c["n_bad_shape"]),
                         (1, 1, 1, 1, 1))


# ── assess_em_feasibility: gates ─────────────────────────────────────────────
class AssessEmFeasibility(unittest.TestCase):
    def test_all_recent_is_feasible(self):
        em = assess_em_feasibility(_all_recent(), AS_OF, 30)
        self.assertTrue(em["feasible"])
        self.assertEqual(em["reasons"], [])
        self.assertTrue(em["future_dated_rejection"])
        self.assertFalse(em["backtest_evidence_capable"])     # advisory media source, never backtest evidence
        self.assertEqual(em["n_with_recent_news"], 15)

    def test_too_few_ok_codes_not_feasible(self):
        raws = [_recent(c) for c in MAIN15[:7]] + [_fail(c) for c in MAIN15[7:]]
        em = assess_em_feasibility(raws, AS_OF, 30)
        self.assertFalse(em["feasible"])
        self.assertEqual(em["n_ok"], 7)
        self.assertTrue(any("成功响应代码数" in r for r in em["reasons"]))

    def test_low_ratio_not_feasible(self):
        # 8 ok of 15 -> passes the >=8 code-count gate but 0.533 < 0.6 ratio gate
        raws = [_recent(c) for c in MAIN15[:8]] + [_fail(c) for c in MAIN15[8:]]
        em = assess_em_feasibility(raws, AS_OF, 30)
        self.assertEqual(em["n_ok"], MIN_EM_OK_CODES)
        self.assertLess(em["ok_ratio"], 0.6)
        self.assertFalse(em["feasible"])
        self.assertTrue(any("成功率" in r for r in em["reasons"]))

    def test_reachable_but_no_recent_news_not_feasible(self):
        # all reachable_quiet (endpoint OK but no recent news) -> can't confirm the link is truly live
        raws = [_ok(c, []) for c in MAIN15[:10]]
        em = assess_em_feasibility(raws, AS_OF, 30)
        self.assertEqual(em["n_ok"], 10)
        self.assertEqual(em["n_with_recent_news"], 0)
        self.assertFalse(em["feasible"])
        self.assertTrue(any("近期新闻" in r for r in em["reasons"]))

    def test_future_leak_blocks_feasible_and_flags_rejection_false(self):
        raws = [_recent(c) for c in MAIN15[:14]] + [_ok(MAIN15[14], [_item(date="2026-06-20 08:00:00")])]
        em = assess_em_feasibility(raws, AS_OF, 30)
        self.assertEqual(em["n_future_leak_codes"], 1)
        self.assertFalse(em["future_dated_rejection"])
        self.assertFalse(em["feasible"])

    def test_bad_shape_blocks_feasible(self):
        raws = [_recent(c) for c in MAIN15[:14]] + [_ok(MAIN15[14], [{"title": "t", "url": "", "published_at": "2026-06-06 08:00:00"}])]
        em = assess_em_feasibility(raws, AS_OF, 30)
        self.assertEqual(em["n_bad_shape_codes"], 1)
        self.assertFalse(em["feasible"])

    def test_empty_pool_not_feasible(self):
        em = assess_em_feasibility([], AS_OF, 30)
        self.assertFalse(em["feasible"])
        self.assertEqual((em["n_requested"], em["ok_ratio"]), (0, 0.0))
        self.assertTrue(any("未探测任何代码" in r for r in em["reasons"]))

    def test_bad_as_of_not_feasible(self):
        em = assess_em_feasibility(_all_recent(), "2026-06-09", 30)
        self.assertFalse(em["as_of_is_valid_date"])
        self.assertFalse(em["feasible"])


# ── consistency: invariants + hand-forged-summary rejection ──────────────────
class Consistency(unittest.TestCase):
    def test_valid_feasible_summary_passes(self):
        validate_em_probe_summary_consistency(_summary(_all_recent()))

    def test_top_feasible_mismatch_raises(self):
        s = _summary(_all_recent())
        s["em"]["feasible"] = False
        with self.assertRaises(ValueError):
            validate_em_probe_summary_consistency(s)

    def test_non_main_in_universe_raises(self):
        s = _summary(_all_recent())
        s["universe"]["main_board_top15"][0] = "300750.SZ"   # ChiNext, not main-board
        with self.assertRaises(ValueError):
            validate_em_probe_summary_consistency(s)

    def test_requested_count_mismatch_raises(self):
        s = _summary([_recent(c) for c in MAIN15[:14]], main=list(MAIN15))  # em.n_requested=14 != 15
        with self.assertRaises(ValueError):
            validate_em_probe_summary_consistency(s)

    def test_backtest_evidence_capable_true_raises(self):
        s = _summary(_all_recent())
        s["em"]["backtest_evidence_capable"] = True
        with self.assertRaises(ValueError):
            validate_em_probe_summary_consistency(s)

    def test_future_dated_rejection_mismatch_raises(self):
        s = _summary(_all_recent())
        s["em"]["future_dated_rejection"] = False        # claims a leak while n_future_leak_codes=0
        with self.assertRaises(ValueError):
            validate_em_probe_summary_consistency(s)

    def test_forged_reachable_with_defect_raises(self):
        # hand-forge an ok code that has a future item but is labeled reachable_with_news
        s = _summary([_recent(c) for c in MAIN15])
        pc = s["em"]["per_code"][0]
        pc["n_future"] = 1
        pc["n_items"] = 2
        pc["status"] = "reachable_with_news"
        s["em"]["n_future_leak_codes"] = 1
        with self.assertRaises(ValueError):
            validate_em_probe_summary_consistency(s)

    def test_forged_failed_code_labeled_reachable_raises(self):
        s = _summary([_recent(c) for c in MAIN15[:14]] + [_fail(MAIN15[14])])
        pc = next(p for p in s["em"]["per_code"] if not p["ok"])
        pc["status"] = "reachable_quiet"     # transport failure disguised as reachable
        with self.assertRaises(ValueError):
            validate_em_probe_summary_consistency(s)

    def test_feasible_true_with_failing_gate_raises(self):
        s = _summary(_all_recent())
        s["feasible"] = True
        s["em"]["feasible"] = True
        s["em"]["n_with_recent_news"] = 2     # below the >=3 gate but feasible still claimed
        with self.assertRaises(ValueError):
            validate_em_probe_summary_consistency(s)


# ── write guard + schema ─────────────────────────────────────────────────────
class WriteAndSchema(unittest.TestCase):
    def test_refuses_production_path(self):
        s = _summary(_all_recent())
        with tempfile.TemporaryDirectory() as d:
            bad = str(Path(d) / "result" / "a_short" / "em_probe.json")
            with self.assertRaises(ValueError):
                write_em_probe_summary(s, bad)

    def test_write_then_reload_is_schema_valid(self):
        s = _summary(_all_recent())
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "research" / "em_probe.json"
            write_em_probe_summary(s, str(out))
            reloaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(reloaded["feasible"])
        self.assertEqual(reloaded["schema_name"], "a_short_em_news_probe_summary")
        self.assertTrue(reloaded["boundary"]["advisory_only"])
        self.assertFalse(reloaded["boundary"]["hard_veto"])

    def test_build_summary_is_schema_valid(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(_summary(_all_recent()), schema)
        jsonschema.validate(_summary([]), schema)                 # not-feasible empty pool also valid

    def test_schema_rejects_feasible_top_without_em_feasible(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        s = _summary([_ok(c, []) for c in MAIN15])    # all quiet -> em.feasible False
        self.assertFalse(s["feasible"])
        s["feasible"] = True                           # forge top feasible while em.feasible stays False
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(s, schema)


# ── thin CLI via injected fetcher (no real HTTP) ─────────────────────────────
class MainCli(unittest.TestCase):
    @staticmethod
    def _fake(codes, names):
        return [_ok(c, [_item(date="2026-06-07 10:00:00")]) for c in codes]

    def _names_arg(self, codes):
        return ",".join(f"{c}:名{i}" for i, c in enumerate(codes))

    def test_requires_confirm(self):
        with self.assertRaises(SystemExit):
            main(["--as-of", AS_OF, "--watch-pool", ",".join(MAIN15),
                  "--names", self._names_arg(MAIN15), "--out", "x.json"],
                 news_fetcher=self._fake)

    def test_bad_as_of_exits(self):
        with self.assertRaises(SystemExit):
            main(["--as-of", "2026-06-09", "--watch-pool", ",".join(MAIN15),
                  "--names", self._names_arg(MAIN15), "--out", "x.json",
                  "--confirm-fetch-authorized"], news_fetcher=self._fake)

    def test_production_out_path_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            bad = str(Path(d) / "result" / "a_short" / "em.json")
            with self.assertRaises(ValueError):
                main(["--as-of", AS_OF, "--watch-pool", ",".join(MAIN15),
                      "--names", self._names_arg(MAIN15), "--out", bad,
                      "--confirm-fetch-authorized"], news_fetcher=self._fake)

    def test_end_to_end_writes_feasible_summary(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "research" / "em_probe.json"
            main(["--as-of", AS_OF, "--watch-pool", ",".join(MAIN15),
                  "--names", self._names_arg(MAIN15), "--out", str(out),
                  "--confirm-fetch-authorized"], news_fetcher=self._fake)
            s = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(s["feasible"])
        self.assertEqual(s["em"]["n_with_recent_news"], 15)
        self.assertEqual(len(s["universe"]["main_board_top15"]), 15)

    def test_non_main_codes_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "research" / "em_probe.json"
            pool = MAIN15 + ["300750.SZ", "688981.SH"]      # ChiNext + STAR, must be dropped
            main(["--as-of", AS_OF, "--watch-pool", ",".join(pool),
                  "--names", self._names_arg(pool), "--out", str(out),
                  "--confirm-fetch-authorized"], news_fetcher=self._fake)
            s = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(set(s["universe"]["dropped_non_main"]), {"300750.SZ", "688981.SH"})
        self.assertEqual(len(s["universe"]["main_board_top15"]), 15)


# ── real fetcher → probe integration: unfiltered fetch preserves defects for audit ──────────
class FetchEmNewsUnfiltered(unittest.TestCase):
    """R-ASHORT-EM-PROBE-FETCHER-FILTER-AUDIT-GAP: the probe's OWN unfiltered fetcher must PRESERVE
    future / stale / bad-shape / bad-date raw rows (unlike production `fetch_em_news`, which pre-filters
    them) so `classify_em_code` can actually audit endpoint quality on the real fetcher→probe path.
    Synthetic JSONP carrying EM's NATIVE `date` field, no real HTTP."""
    class _Resp:
        def __init__(self, text, status=200):
            self.text, self.status_code = text, status

    class _Sess:
        def __init__(self, body, status=200):
            self._body, self._status = body, status

        def get(self, url, headers=None, timeout=None):
            return FetchEmNewsUnfiltered._Resp(self._body, self._status)

    def _jsonp(self, rows):
        return "cb(" + json.dumps({"code": 0, "result": {"cmsArticleWeb": rows}}, ensure_ascii=False) + ")"

    def test_unfiltered_preserves_all_defect_rows_for_audit(self):
        rows = [
            {"title": "近期", "url": "http://e/r", "date": "2026-06-07 10:00:00"},   # recent
            {"title": "未来文", "url": "http://e/f", "date": "2026-06-20 08:00:00"},  # future — prod fetch_em_news DROPS
            {"title": "旧", "url": "http://e/s", "date": "2026-04-01 09:00:00"},      # stale
            {"title": "坏日期", "url": "http://e/b", "date": "not-a-date"},           # bad_date
            {"title": "缺url", "url": "", "date": "2026-06-06 08:00:00"},            # bad_shape — prod DROPS
        ]
        out = fetch_em_news_unfiltered(["600519.SH"], {"600519.SH": "贵州茅台"},
                                       session=self._Sess(self._jsonp(rows)))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["ok"])
        self.assertEqual(len(out[0]["items"]), 5)        # ALL preserved (filtered fetch_em_news would keep ~1)
        # the REAL fetcher→probe path: classify must now SEE and count the defects
        c = classify_em_code(out[0], AS_OF, 30)
        self.assertEqual(c["status"], "unknown")          # future/bad_date/bad_shape present -> unknown
        self.assertEqual((c["n_recent"], c["n_future"], c["n_stale"], c["n_bad_date"], c["n_bad_shape"]),
                         (1, 1, 1, 1, 1))

    def test_unfiltered_future_row_blocks_feasible_via_real_path(self):
        # 14 clean-recent codes + 1 whose raw EM payload carries a future-dated row -> not feasible
        clean = self._jsonp([{"title": "近期", "url": "http://e/r", "date": "2026-06-07 10:00:00"}])
        leaky = self._jsonp([{"title": "近期", "url": "http://e/r", "date": "2026-06-07 10:00:00"},
                             {"title": "未来", "url": "http://e/f", "date": "2026-06-20 08:00:00"}])
        bodies = {c: clean for c in MAIN15[:14]}
        bodies[MAIN15[14]] = leaky

        def fetcher(codes, names):
            out = []
            for c in codes:
                out.extend(fetch_em_news_unfiltered([c], {c: "n"},
                                                    session=FetchEmNewsUnfiltered._Sess(bodies[c])))
            return out

        em = assess_em_feasibility(fetcher(MAIN15, None), AS_OF, 30)
        self.assertEqual(em["n_future_leak_codes"], 1)
        self.assertFalse(em["future_dated_rejection"])
        self.assertFalse(em["feasible"])

    def test_unfiltered_clean_recent_is_reachable(self):
        out = fetch_em_news_unfiltered(["600519.SH"], {"600519.SH": "茅台"}, session=self._Sess(
            self._jsonp([{"title": "近期", "url": "http://e/r", "date": "2026-06-07 10:00:00"}])))
        self.assertEqual(classify_em_code(out[0], AS_OF, 30)["status"], "reachable_with_news")

    def test_unfiltered_non_dict_row_is_bad_shape(self):
        out = fetch_em_news_unfiltered(["600519.SH"], {"600519.SH": "茅台"},
                                       session=self._Sess(self._jsonp(["a string"])))
        c = classify_em_code(out[0], AS_OF, 30)
        self.assertEqual(c["status"], "unknown")
        self.assertEqual(c["n_bad_shape"], 1)

    def test_unfiltered_no_name_and_non_200_fail_closed(self):
        self.assertFalse(fetch_em_news_unfiltered(["600519.SH"], {}, session=self._Sess(self._jsonp([])))[0]["ok"])
        blocked = fetch_em_news_unfiltered(["600519.SH"], {"600519.SH": "茅台"},
                                           session=self._Sess("blocked", status=403))
        self.assertFalse(blocked[0]["ok"])
        self.assertEqual(blocked[0]["error_category"], "anti_scrape")


if __name__ == "__main__":
    unittest.main()
