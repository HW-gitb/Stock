"""Tests for the A-short weekly pipeline (batch ②).

Covers normalize_candidate (EGS candidate → engine input mapping), build_weekly_report (per-stock
M6.7 envelope), validate_weekly_report (incl. the P2 consumer-validation: it MUST validate the IV
feed it consumed + every M6.7), write_weekly_report contract, latest_iv_percentile, IV-missing
propagation, and main() wiring with an injected price provider (no live Tushare). Synthetic inputs.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_weekly_pipeline import (  # noqa: E402
    normalize_candidate, build_weekly_report, validate_weekly_report,
    write_weekly_report, latest_iv_percentile, main, SCHEMA_PATH,
    _fetch_price_series, _load_validated_overlay, MIN_PRICE_OBS,
    _semantic_panel_from_summary,
)
from runners.a_short_m67_render import render_weekly_markdown, write_weekly_markdown  # noqa: E402
from runners.a_short_semantic_risk_summary import build_summary_from_fetches  # noqa: E402
from runners.a_short_theme_overlay_comparison import (  # noqa: E402
    assemble_overlay, build_summary,
)

AS_OF = "20260609"
GEN = "2026-06-09T12:00:00+08:00"
M67_SCHEMA = ROOT / "schemas" / "a_short_m67_report.schema.json"
FIXT_AI = ROOT / "schemas" / "examples" / "analysis_input.example.json"


def _analysis_input(trade_date=AS_OF, candidates=None):
    """Schema+PIT-valid analysis_input envelope (from the repo example) with our candidates."""
    base = json.loads(FIXT_AI.read_text(encoding="utf-8"))
    base["trade_date"] = trade_date
    src = base.get("source") or {}
    if src.get("l3_mode") == "pit":               # keep PIT invariant: snapshot <= trade_date
        src["l3_snapshot_date"] = trade_date
    if candidates is not None:
        base["candidates"] = candidates
    return base


def _series():
    # mirrors the engine test fixture: day12 carries support 2.87 + resistance 3.10.
    s = []
    for i in range(30):
        s.append({"high": 3.10, "low": 2.87, "close": 2.90} if i == 12
                 else {"high": 2.92, "low": 2.88, "close": 2.90})
    return s


def _egs_candidate(ts_code="600000.SH", **over):
    # mirrors the REAL egs_main analysis_input contract (derived_flags.is_lock / hard_veto;
    # event_risk.suspension.is_suspended) — NOT the engine-input shape.
    cand = {
        "ts_code": ts_code, "name": "测试",
        "quote": {"close": 2.90},
        "scores": {"esp_score": 60, "l4_score": 70},
        "liquidity": {"avg_amount_5d": 2e8, "avg_amount_20d": 2e8},
        "derived_flags": {"chasing_high": False, "overheat_flag": False, "has_crash_veto": False,
                          "is_lock": False, "is_breakout": False, "m4_review_required": None,
                          "hard_veto": False},
        "event_risk": {"holder_reduction": {"active_plan": False},
                       "suspension": {"is_suspended": False},
                       "delisting": {"st_flag": False, "delisting_warning": False}},
    }
    cand.update(over)
    return cand


_EXAMPLE_CAND = json.loads(FIXT_AI.read_text(encoding="utf-8"))["candidates"][0]


def _ai_candidate(ts_code="600000.SH", close=2.90, is_lock=False, suspended=False,
                  hard_veto=False, active_plan=False):
    """Full schema-valid candidate (deep-copied from the repo example), leaf-overridden.
    close defaults to 2.90 to align with the injected `_series()` support (低吸→建仓 path)."""
    c = copy.deepcopy(_EXAMPLE_CAND)
    c["ts_code"] = ts_code
    c["quote"]["close"] = close
    c["derived_flags"]["is_lock"] = is_lock
    c["derived_flags"]["hard_veto"] = hard_veto
    c["event_risk"]["suspension"]["is_suspended"] = suspended
    c["event_risk"]["holder_reduction"]["active_plan"] = active_plan
    return c


def _overlay_row(eligible=True, crowding=False):
    return {"eligible": eligible, "crowding_hit": crowding}


def _account():
    return {"available_cash": 500000.0, "market_regime": "震荡期"}


def _feed(last_pct=55.0):
    series = [{"trade_date": d, "iv_value": 0.15 + 0.001 * i,
               "iv_percentile_252d": (last_pct if i == 4 else 40.0)}
              for i, d in enumerate(["20260601", "20260602", "20260603", "20260604", "20260605"])]
    return {"as_of": AS_OF, "n_days": len(series), "series": series}


def _valid_overlay_for(codes, as_of=AS_OF):
    """Schema + consistency valid overlay summary for an arbitrary candidate set (Slice A builders)."""
    pool = pd.DataFrame([
        {"ts_code": c, "baseline_rank": i + 1, "esp_score": 60.0 - i, "l4_score": 70.0,
         "overheat_flag": False, "chasing_high": False, "chase_flag": False, "high_pos_shrink": False}
        for i, c in enumerate(codes)])
    theme_heat = {"score": {c: 90.0 - i for i, c in enumerate(codes)},
                  "best_concept": {c: "c1" for c in codes}}
    industry_heat_by_l2 = {"半导体": 95.0, "银行": 20.0}
    sw_l2_by_code = {c: "半导体" for c in codes}
    breadth = {c: {"up_frac": 0.8, "vol_frac": 0.6, "pass": True} for c in codes}
    persistence = {c: 1.0 for c in codes}
    fit = {c: 0.8 for c in codes}
    assembled = assemble_overlay(pool, theme_heat, industry_heat_by_l2, breadth,
                                 persistence, fit, sw_l2_by_code)
    return build_summary(assembled, as_of=as_of,
                         pit_source={"concept_membership": "pit", "sw_mapping": "forward"},
                         dropped_at_l0_l5=[], generated_at="2026-06-10T00:00:00+08:00")


def _valid_overlay(as_of=AS_OF):
    """Schema + consistency valid overlay covering exactly the default weekly pool."""
    return _valid_overlay_for(["600000.SH", "000001.SZ"], as_of)


def _normalized(ts_code="600000.SH", iv_pct=55.0, **cand_over):
    return normalize_candidate(_egs_candidate(ts_code, **cand_over), _series(),
                               _overlay_row(), iv_pct, {"available_cash": 500000.0}, "震荡期")


def _weekly(normalized_list=None, iv_feed_ref="iv_feed.json"):
    nl = normalized_list if normalized_list is not None else [_normalized()]
    return build_weekly_report(nl, AS_OF, GEN, iv_feed_ref=iv_feed_ref)


class NormalizeTests(unittest.TestCase):
    def test_maps_egs_fields(self):
        n = _normalized()
        self.assertEqual(n["close"], 2.90)
        self.assertEqual(n["esp_score"], 60)
        self.assertTrue(n["overlay"]["eligible"])
        self.assertEqual(n["iv"]["iv_percentile_252d"], 55.0)
        self.assertEqual(n["liquidity"]["avg_amount_5d"], 2e8)
        self.assertEqual(n["market_regime"], "震荡期")

    def test_maps_event_and_derived_flags(self):
        n = normalize_candidate(
            _egs_candidate(derived_flags={"overheat_flag": True, "chasing_high": False,
                                          "has_crash_veto": False, "is_lock": False,
                                          "is_breakout": False, "hard_veto": False},
                           event_risk={"holder_reduction": {"active_plan": True},
                                       "suspension": {"is_suspended": False},
                                       "delisting": {"st_flag": True, "delisting_warning": False}}),
            _series(), _overlay_row(), 55.0, {}, "震荡期")
        self.assertTrue(n["derived"]["overheat"])
        self.assertTrue(n["event"]["holder_reduction_active"])
        self.assertTrue(n["event"]["st_or_delisting"])

    def test_maps_real_egs_hard_risk_contract_fields(self):
        # R-ASHORT-WEEKLY-EGS-HARD-RISK-MAPPING-GAP: real keys is_lock / suspension.is_suspended /
        # hard_veto must reach the engine hard-risk inputs (not the wrong limit_locked/suspended keys).
        n = normalize_candidate(
            _egs_candidate(derived_flags={"chasing_high": False, "overheat_flag": False,
                                          "has_crash_veto": False, "is_lock": True,
                                          "is_breakout": False, "hard_veto": True},
                           event_risk={"holder_reduction": {"active_plan": False},
                                       "suspension": {"is_suspended": True},
                                       "delisting": {"st_flag": False, "delisting_warning": False}}),
            _series(), _overlay_row(), 55.0, {}, "震荡期")
        self.assertTrue(n["derived"]["limit_locked"])
        self.assertTrue(n["derived"]["suspended"])
        self.assertTrue(n["derived"]["hard_veto"])

    def test_missing_overlay_defaults_false(self):
        n = normalize_candidate(_egs_candidate(), _series(), None, 55.0, {}, "震荡期")
        self.assertFalse(n["overlay"]["eligible"])
        self.assertFalse(n["overlay"]["crowding_hit"])

    def test_maps_vol_confirm(self):
        # vol_confirm now flows from EGS derived_flags → engine breakout entry (no longer dormant).
        n = normalize_candidate(
            _egs_candidate(derived_flags={"chasing_high": False, "overheat_flag": False,
                                          "has_crash_veto": False, "is_lock": False,
                                          "is_breakout": True, "vol_confirm": True, "hard_veto": False}),
            _series(), _overlay_row(), 55.0, {}, "震荡期")
        self.assertTrue(n["derived"]["vol_confirm"])
        self.assertTrue(n["derived"]["breakout"])


class BuildWeeklyTests(unittest.TestCase):
    def test_envelope(self):
        w = _weekly([_normalized("600000.SH"), _normalized("000001.SZ")])
        self.assertEqual(w["schema_name"], "a_short_weekly_report")
        self.assertEqual(w["n_stocks"], 2)
        self.assertEqual(len(w["reports"]), 2)
        self.assertTrue(all(v is False for v in w["boundary"].values()))

    def test_buildable_candidate_yields_jiacang(self):
        w = _weekly([_normalized()])
        self.assertEqual(w["reports"][0]["m67"]["table"]["操作"], "建仓")

    def test_hard_veto_candidate_yields_fouju_null_trade(self):
        n = _normalized(event_risk={"holder_reduction": {"active_plan": True},
                                    "suspension": {"is_suspended": False},
                                    "delisting": {"st_flag": False, "delisting_warning": False}})
        rep = _weekly([n])["reports"][0]
        self.assertEqual(rep["m67"]["table"]["操作"], "否决")
        for k in ("股数", "入", "盈一", "盈二", "损"):
            self.assertIsNone(rep["m67"]["table"][k])

    def test_real_egs_hard_risk_fields_cannot_become_jiacang(self):
        # actual-analysis-input-shape: is_lock / suspension.is_suspended / hard_veto each → not 建仓.
        def _df(**kw):
            base = {"chasing_high": False, "overheat_flag": False, "has_crash_veto": False,
                    "is_lock": False, "is_breakout": False, "hard_veto": False}
            base.update(kw)
            return base
        cases = [
            {"derived_flags": _df(is_lock=True)},
            {"derived_flags": _df(hard_veto=True)},
            {"event_risk": {"holder_reduction": {"active_plan": False},
                            "suspension": {"is_suspended": True},
                            "delisting": {"st_flag": False, "delisting_warning": False}}},
        ]
        for over in cases:
            rep = _weekly([_normalized(**over)])["reports"][0]
            self.assertNotEqual(rep["m67"]["table"]["操作"], "建仓", over)


class ValidateWeeklyTests(unittest.TestCase):
    def test_good_passes(self):
        validate_weekly_report(_weekly(), _feed())  # no raise

    def test_consumer_validates_iv_feed_p2(self):
        # P2: the pipeline MUST validate the feed it consumed → a corrupt feed is caught here.
        bad_feed = _feed()
        bad_feed["series"][0]["iv_value"] = -1.0
        with self.assertRaises(ValueError):
            validate_weekly_report(_weekly(), bad_feed)

    def test_rejects_future_dated_feed(self):
        bad_feed = _feed()
        bad_feed["series"][-1]["trade_date"] = "20260631"  # invalid calendar
        with self.assertRaises(ValueError):
            validate_weekly_report(_weekly(), bad_feed)

    def test_rejects_feed_as_of_after_weekly_as_of(self):
        # R-ASHORT-WEEKLY-IV-FEED-PIT-CROSS-ASOF: feed from after the weekly run = future IV.
        future = {"as_of": "20260612", "n_days": 1,
                  "series": [{"trade_date": "20260612", "iv_value": 0.15, "iv_percentile_252d": 50.0}]}
        with self.assertRaises(ValueError):
            validate_weekly_report(_weekly(), future)  # weekly as_of = 20260609

    def test_rejects_n_stocks_mismatch(self):
        w = _weekly()
        w["n_stocks"] = 99
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_report_as_of_mismatch(self):
        w = _weekly()
        w["reports"][0]["as_of"] = "20260101"
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_duplicate_ts_code(self):
        w = _weekly([_normalized("600000.SH"), _normalized("600000.SH")])
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_boundary_not_all_false(self):
        w = _weekly()
        w["boundary"]["production"] = True
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())


class WriteWeeklyTests(unittest.TestCase):
    def test_write_roundtrip(self):
        w = _weekly()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "weekly.json"
            write_weekly_report(w, _feed(), str(out))
            loaded = json.loads(out.read_text(encoding="utf-8"))
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            jsonschema.validate(loaded, json.load(f))
        self.assertEqual(loaded["n_stocks"], 1)

    def test_write_rejects_tampered_report(self):
        w = _weekly()
        # tamper a 建仓 report's table to drift from machine plan → per-report m67 consistency fails
        w["reports"][0]["m67"]["table"]["入"] = 999.0
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "weekly.json"
            with self.assertRaises((ValueError, jsonschema.ValidationError)):
                write_weekly_report(w, _feed(), str(out))
            self.assertFalse(out.exists())

    def test_write_rejects_production_output_path(self):
        # R-ASHORT-WEEKLY-OFFICIAL-OUTPUT-PATH-BOUNDARY: never write result/a_short/<date>.
        w = _weekly()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "result" / "a_short" / "20260609" / "weekly.json"
            with self.assertRaises(ValueError):
                write_weekly_report(w, _feed(), str(out))
            self.assertFalse(out.exists())

    def test_write_rejects_noncalendar_as_of_even_empty(self):
        # R-ASHORT-WEEKLY-WRITE-ASOF-CALENDAR-GAP: invalid calendar as_of rejected incl. empty reports.
        w = build_weekly_report([], "20260631", GEN, iv_feed_ref="f")  # 0 reports, bad calendar
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "weekly.json"
            with self.assertRaises(ValueError):
                write_weekly_report(w, _feed(), str(out))
            self.assertFalse(out.exists())


class IVMissingTests(unittest.TestCase):
    def test_latest_iv_percentile(self):
        self.assertEqual(latest_iv_percentile(_feed(last_pct=67.0)), 67.0)
        self.assertIsNone(latest_iv_percentile({"series": []}))

    def test_iv_missing_propagates_observe_only(self):
        n = _normalized(iv_pct=None)
        rep = _weekly([n])["reports"][0]
        self.assertEqual(rep["machine"]["iv_gate"]["status"], "observe_only_missing_feed")
        self.assertIn("IV未知", rep["m67"]["精简结论区"]["波动率状态"])


class MainWiringTests(unittest.TestCase):
    def _write_inputs(self, td, feed=None, ai=None):
        ai = ai if ai is not None else _analysis_input(
            candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
        (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
        (Path(td) / "feed.json").write_text(json.dumps(feed or _feed()), encoding="utf-8")
        (Path(td) / "acct.json").write_text(json.dumps(_account()), encoding="utf-8")

    def test_main_with_injected_price_provider(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["n_stocks"], 2)
        self.assertEqual(loaded["iv_feed_ref"], "feed.json")
        self.assertEqual(loaded["reports"][0]["m67"]["table"]["操作"], "建仓")

    def test_main_writes_markdown_sibling_with_banner(self):
        # pipeline main emits a readable weekly_m67.md sibling next to the json (honesty banner present).
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly_m67.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            md = Path(td) / "weekly_m67.md"
            self.assertTrue(md.exists())
            text = md.read_text(encoding="utf-8")
        self.assertIn("# A-short 周报 M6.7", text)
        self.assertIn("edge 未验证", text)        # honesty banner
        self.assertIn("## 一览", text)

    def test_main_invalid_as_of_aborts(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            with self.assertRaises(SystemExit):
                main(["--as-of", "20260631", "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--out", str(Path(td) / "w.json")],
                     price_provider=lambda code: _series())

    def test_main_no_provider_without_confirm_aborts(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--out", str(Path(td) / "w.json")])

    def test_main_empty_price_series_aborts_no_file(self):
        # R-ASHORT-WEEKLY-PRICE-FETCH-FAIL-OPEN: missing price coverage must NOT degrade to 观察.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)], price_provider=lambda code: [])
            self.assertFalse(out.exists())

    def test_main_short_price_series_aborts_no_file(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)], price_provider=lambda code: _series()[:MIN_PRICE_OBS - 1])
            self.assertFalse(out.exists())

    def test_main_analysis_input_trade_date_mismatch_aborts(self):
        # R-ASHORT-WEEKLY-ANALYSIS-INPUT-CONSUMER-VALIDATION-GAP: trade_date must == --as-of.
        for td_val in ("20260601", "20260612"):   # stale, future
            with tempfile.TemporaryDirectory() as td:
                self._write_inputs(td, ai=_analysis_input(
                    trade_date=td_val, candidates=[_ai_candidate("600000.SH")]))
                out = Path(td) / "weekly.json"
                with self.assertRaises(SystemExit):
                    main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                          "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                          "--out", str(out)], price_provider=lambda code: _series())
                self.assertFalse(out.exists())

    def test_main_malformed_analysis_input_aborts(self):
        with tempfile.TemporaryDirectory() as td:
            bad = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            del bad["source"]                       # drop a schema-required top-level field
            self._write_inputs(td, ai=bad)
            out = Path(td) / "weekly.json"
            with self.assertRaises((ValueError, SystemExit)):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)], price_provider=lambda code: _series())
            self.assertFalse(out.exists())

    def test_main_regime_from_analysis_input_takes_precedence(self):
        # market_regime sourced from analysis_input.market_context (EGS), overriding the account file.
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            ai["market_context"]["market_regime"]["status"] = "attack"   # → 进攻期
            self._write_inputs(td, ai=ai)                                # account.json says 震荡期
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["reports"][0]["m67"]["精简结论区"]["当前环境"], "进攻期")

    def test_main_with_valid_overlay_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            (Path(td) / "ov.json").write_text(json.dumps(_valid_overlay(AS_OF)), encoding="utf-8")
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--overlay", str(Path(td) / "ov.json"), "--out", str(out)],
                 price_provider=lambda code: _series())
            self.assertTrue(out.exists())

    def _run_main_with_sem(self, td, summary):
        # write a semantic-risk summary file and run main with --semantic-risk-summary; returns out path
        (Path(td) / "sem.json").write_text(json.dumps(summary), encoding="utf-8")
        out = Path(td) / "weekly.json"
        main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
              "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
              "--semantic-risk-summary", str(Path(td) / "sem.json"), "--out", str(out)],
             price_provider=lambda code: _series())
        return out

    def test_main_valid_semantic_summary_writes_both(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = self._run_main_with_sem(td, _sem_summary_for(WEEKLY_POOL))   # pool matches weekly EGS
            md = Path(td) / "weekly.md"
            self.assertTrue(out.exists() and md.exists())
            loaded = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(loaded["n_stocks"], 2)                 # deterministic JSON shape preserved
            self.assertNotIn("advisory", json.dumps(loaded))        # advisory NEVER in deterministic JSON
            self.assertIn("advisory", md.read_text(encoding="utf-8"))

    def _assert_main_sem_aborts_no_file(self, summary=None, drop_file=False, exc=Exception):
        # R-ASHORT-SEMANTIC-PANEL-MAIN-PARTIAL-WRITE-ON-INVALID-SUMMARY: an invalid semantic-risk
        # summary must abort BEFORE any write — neither weekly.json nor its .md sibling may exist.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            md = Path(td) / "weekly.md"
            if not drop_file:
                (Path(td) / "sem.json").write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(exc):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--semantic-risk-summary", str(Path(td) / "sem.json"), "--out", str(out)],
                     price_provider=lambda code: _series())
            self.assertFalse(out.exists(), "weekly.json written despite invalid semantic summary")
            self.assertFalse(md.exists(), "weekly.md written despite invalid semantic summary")

    def test_main_semantic_summary_schema_tamper_writes_no_file(self):
        s = _sem_summary_for(WEEKLY_POOL); s["schema_version"] = "0.9.0"   # matching pool, schema tamper
        self._assert_main_sem_aborts_no_file(s, exc=jsonschema.ValidationError)

    def test_main_semantic_summary_boundary_tamper_writes_no_file(self):
        s = _sem_summary_for(WEEKLY_POOL); s["boundary"]["hard_veto"] = True   # matching pool, boundary const
        self._assert_main_sem_aborts_no_file(s, exc=jsonschema.ValidationError)

    def test_main_semantic_summary_as_of_mismatch_writes_no_file(self):
        self._assert_main_sem_aborts_no_file(_sem_summary_for(WEEKLY_POOL, "20260601"), exc=ValueError)

    def test_main_missing_semantic_summary_file_writes_no_file(self):
        self._assert_main_sem_aborts_no_file(drop_file=True, exc=FileNotFoundError)

    def test_main_semantic_summary_wrong_candidate_pool_writes_no_file(self):
        # R-ASHORT-WEEKLY-AUX-ARTIFACT-CANDIDATE-SET-MISMATCH: same-date, schema+consistency-valid
        # summary but for a DIFFERENT candidate pool must abort before any write.
        self._assert_main_sem_aborts_no_file(_sem_summary_for(["600000.SH", "600001.SH"]), exc=ValueError)

    def _assert_main_overlay_aborts_no_file(self, overlay_obj):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            (Path(td) / "ov.json").write_text(json.dumps(overlay_obj), encoding="utf-8")
            out = Path(td) / "weekly.json"
            md = Path(td) / "weekly.md"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--overlay", str(Path(td) / "ov.json"), "--out", str(out)],
                     price_provider=lambda code: _series())
            self.assertFalse(out.exists(), "weekly.json written despite invalid overlay")   # each absent
            self.assertFalse(md.exists(), "weekly.md written despite invalid overlay")       # separately

    def test_main_overlay_missing_weekly_candidate_writes_no_file(self):
        # internally-valid overlay covering only 600000.SH while weekly candidates are
        # [600000.SH, 000001.SZ]; the missing row would silently default to eligible/crowding=false
        # → MY lineage check (not overlay-internal consistency) must abort before any write.
        self._assert_main_overlay_aborts_no_file(_valid_overlay_for(["600000.SH"]))

    def test_main_overlay_wrong_candidate_set_writes_no_file(self):
        # internally-valid overlay for a different same-size set (600002.SH instead of 000001.SZ).
        self._assert_main_overlay_aborts_no_file(_valid_overlay_for(["600000.SH", "600002.SH"]))

    def test_main_overlay_duplicate_candidate_writes_no_file(self):
        # schema+consistency-valid overlay with a DUPLICATE current candidate row: dict/set collapse
        # would hide it (3 rows -> set of 2 == weekly set). The raw-list dup check must abort before write.
        self._assert_main_overlay_aborts_no_file(_valid_overlay_for(["600000.SH", "000001.SZ", "000001.SZ"]))

    def test_main_semantic_provider_folds_into_m67(self):
        # Slice 1 end-to-end: injected semantic_provider (high official) folds into M6.7 → 否决;
        # a stock with no semantic stays neutral (impact none). No network (provider injected).
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)],
                 price_provider=lambda code: _series(),
                 semantic_provider=lambda code: (_official("risk", "high", "立案调查")
                                                 if code == "600000.SH" else None))
            w = json.loads(out.read_text(encoding="utf-8"))
        by = {r["ts_code"]: r for r in w["reports"]}
        self.assertEqual(by["600000.SH"]["m67"]["table"]["操作"], "否决")                # semantic high → 否决
        self.assertEqual(by["000001.SZ"]["machine"]["layer"]["semantic_risk"]["impact"], "none")  # no semantic


def _fake_ts(df):
    class _FakeTs:
        def __init__(self):
            self.calls = {}

        def pro_bar(self, **kw):
            self.calls.update(kw)
            return df
    return _FakeTs()


class PriceFetchTests(unittest.TestCase):
    def test_uses_stock_asset_E_and_returns_bars(self):
        # R-ASHORT-WEEKLY-PRICE-FETCH-FAIL-OPEN: A-share stocks need asset="E"; latest bar == end.
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260108", "20260109"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        out = _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")
        self.assertEqual(ts.calls.get("asset"), "E")
        self.assertEqual(ts.calls.get("adj"), "qfq")
        self.assertEqual(len(out), 2)
        self.assertNotIn("trade_date", out[0])      # engine input shape is {high,low,close}

    def test_provider_exception_aborts(self):
        ts = _fake_ts(None)
        ts.pro_bar = lambda **kw: (_ for _ in ()).throw(
            RuntimeError("request failed url=https://api.example.invalid token=SECRET123"))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")

    def test_future_bar_aborts(self):
        # R-ASHORT-WEEKLY-PRICE-SERIES-PIT-FRESHNESS-GAP: trade_date > as_of must abort.
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260109", "20260630"], "high": [3.0, 99.0],
                                    "low": [2.9, 1.0], "close": [3.0, 50.0]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")

    def test_stale_latest_bar_aborts(self):
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260101", "20260102"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20251201", "20260109")

    def test_noncalendar_trade_date_aborts(self):
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260631"], "high": [3.0], "low": [2.9], "close": [2.95]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")

    def test_main_future_price_row_writes_no_file(self):
        # Codex repro: a fake tushare through main(--confirm-fetch-authorized) must NOT write.
        fake = _fake_ts(pd.DataFrame({"trade_date": ["20260630"], "high": [99.0],
                                      "low": [1.0], "close": [50.0]}))
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            (Path(td) / "acct.json").write_text(json.dumps(_account()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            old = sys.modules.get("tushare")
            sys.modules["tushare"] = fake
            try:
                with self.assertRaises(SystemExit):
                    main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                          "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                          "--out", str(out), "--confirm-fetch-authorized"], pro_factory=lambda: object())
            finally:
                if old is not None:
                    sys.modules["tushare"] = old
                else:
                    sys.modules.pop("tushare", None)
            self.assertFalse(out.exists())


class OverlayConsumerTests(unittest.TestCase):
    # R-ASHORT-WEEKLY-OVERLAY-CONSUMER-VALIDATION-GAP
    def _write(self, td, ov):
        p = Path(td) / "ov.json"
        p.write_text(json.dumps(ov), encoding="utf-8")
        return str(p)

    def test_valid_same_as_of_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            m = _load_validated_overlay(self._write(td, _valid_overlay(AS_OF)), AS_OF)
            self.assertIn("600000.SH", m)

    def test_future_or_stale_as_of_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):  # future
                _load_validated_overlay(self._write(td, _valid_overlay("20260612")), AS_OF)
            with self.assertRaises(SystemExit):  # stale
                _load_validated_overlay(self._write(td, _valid_overlay("20260101")), AS_OF)

    def test_candidate_count_drift_rejected(self):
        ov = _valid_overlay(AS_OF)
        ov["candidate_count"] += 1
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                _load_validated_overlay(self._write(td, ov), AS_OF)

    def test_malformed_overlay_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(jsonschema.ValidationError):
                _load_validated_overlay(self._write(td, {"foo": 1}), AS_OF)


class SchemaTests(unittest.TestCase):
    def test_weekly_schema_valid(self):
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.Draft7Validator.check_schema(schema)


def _sem_summary_for(codes, as_of=AS_OF):
    cninfo = {ts: {"ts_code": ts, "ok": True, "error_category": None,
                   "announcements": [{"announcementTitle": "2025 年年度报告", "adjunctUrl": "u",
                                      "announcementTime": 1700000000000, "secCode": ts.split(".")[0]}]}
              for ts in codes}
    return build_summary_from_fetches(list(codes), as_of, cninfo, None, GEN)


def _sem_summary(as_of=AS_OF):
    return _sem_summary_for([f"6000{i:02d}.SH" for i in range(4)], as_of)


# the main-board Top15 pool implied by MainWiringTests._write_inputs default candidates
WEEKLY_POOL = ["600000.SH", "000001.SZ"]


class SemanticRiskPanelWiring(unittest.TestCase):
    """Slice 2b-ii-B: advisory panel appended to the weekly .md only, never into the deterministic JSON."""

    def test_panel_from_summary_valid(self):
        panel = _semantic_panel_from_summary(_sem_summary(), AS_OF)
        self.assertIn("advisory", panel)
        self.assertIn("as_of 20260609", panel)

    def test_panel_as_of_mismatch_raises(self):
        with self.assertRaises(ValueError):
            _semantic_panel_from_summary(_sem_summary("20260601"), AS_OF)

    def test_panel_schema_name_mismatch_raises(self):
        s = _sem_summary()
        s["schema_name"] = "wrong"
        with self.assertRaises(ValueError):
            _semantic_panel_from_summary(s, AS_OF)

    def test_panel_invalid_summary_raises(self):
        s = _sem_summary()
        s["candidates"][0]["ts_code"] = "300750.SZ"   # non-main → validate_summary_consistency raises
        with self.assertRaises(ValueError):
            _semantic_panel_from_summary(s, AS_OF)

    def test_panel_rejects_schema_version_tamper(self):
        s = _sem_summary()
        s["schema_version"] = "0.9.0"                  # schema const 1.0.0 -> jsonschema rejects
        with self.assertRaises(jsonschema.ValidationError):
            _semantic_panel_from_summary(s, AS_OF)

    def test_panel_rejects_boundary_tamper(self):
        for key in ("hard_veto", "production"):
            s = _sem_summary()
            s["boundary"][key] = True                 # boundary consts are all-false
            with self.assertRaises(jsonschema.ValidationError):
                _semantic_panel_from_summary(s, AS_OF)

    def test_panel_rejects_extra_top_level_hard_decision_field(self):
        s = _sem_summary()
        s["decision"] = "hard_veto"                    # additionalProperties:false -> rejected
        with self.assertRaises(jsonschema.ValidationError):
            _semantic_panel_from_summary(s, AS_OF)

    def test_md_appends_panel_after_deterministic_separator(self):
        weekly = _weekly([_normalized()])
        panel = _semantic_panel_from_summary(_sem_summary(), AS_OF)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "weekly.md"
            write_weekly_markdown(weekly, str(out), semantic_panel=panel)
            md = out.read_text(encoding="utf-8")
        deterministic = render_weekly_markdown(weekly)
        self.assertTrue(md.startswith(deterministic))     # advisory is purely appended after the M6.7 md
        self.assertIn("\n---\n", md[len(deterministic):])  # separated from deterministic section
        self.assertIn("advisory", md)

    def test_md_has_no_panel_when_none(self):
        weekly = _weekly([_normalized()])
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "weekly.md"
            write_weekly_markdown(weekly, str(out))        # no semantic_panel
            md = out.read_text(encoding="utf-8")
        self.assertEqual(md, render_weekly_markdown(weekly))   # identical to deterministic-only render


def _official(status, sev=None, rt="x", dd="20260601"):
    # full PIT official_structured evidence shape (matches build_official_structured output)
    evs = [{"source": "cninfo", "title": "t", "category": "c", "disclosure_date": dd,
            "url_or_pdf": "u", "risk_type": rt, "severity": sev}] if sev else []
    return {"status": status, "events": evs, "had_pit_announcements": bool(evs)}


class SemanticIntoM67(unittest.TestCase):
    """Slice 1: cninfo official_structured folded into M6.7 via the semantic_official family.
    high→否决; medium/low→待核 (no penalty, no clear); clear/unknown/None→neutral; never rescues;
    machine.layer.semantic_risk trace; consistency preserved by construction."""
    GEN = "2026-06-09T00:00:00+08:00"

    def _report(self, semantic, **over):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized(**over)
        n["semantic"] = semantic
        r = build_m67_report(n, AS_OF, self.GEN)
        validate_m67_consistency(r)          # must ALWAYS stay consistent (table↔action, 否决→null, …)
        return r

    def test_high_official_forces_fouju_and_nulls_trade(self):
        r = self._report(_official("risk", "high", "立案调查"))
        self.assertEqual(r["m67"]["table"]["操作"], "否决")
        for k in ("股数", "入", "盈一", "盈二", "损"):
            self.assertIsNone(r["m67"]["table"][k])
        self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "veto")
        self.assertIn("语义官方", r["m67"]["精简结论区"]["否决审查触发"])

    def test_medium_official_is_pending_no_penalty(self):
        base = self._report(None)
        self.assertEqual(base["m67"]["table"]["操作"], "建仓")
        r = self._report(_official("risk", "medium", "fund_occupation"))
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")                       # NOT downgraded
        self.assertEqual(r["m67"]["table"]["优先级"], base["m67"]["table"]["优先级"])  # star unchanged
        self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "pending")
        self.assertIn("语义待核", r["m67"]["精简结论区"]["否决审查触发"])
        self.assertTrue(any("semantic_pending_review" in o
                            for o in r["machine"]["layer"]["observe_only"]))

    def test_clear_unknown_none_are_neutral(self):
        base = self._report(None)
        for sem in (_official("clear"), _official("unknown"), None):
            r = self._report(sem)
            self.assertEqual(r["m67"]["table"]["操作"], base["m67"]["table"]["操作"])
            self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "none")
        self.assertEqual(self._report(None)["machine"]["layer"]["semantic_risk"]["official_status"],
                         "unknown")

    def test_semantic_never_rescues_base_hard_veto(self):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized(); n["derived"]["hard_veto"] = True       # base = 否决
        n["semantic"] = _official("clear")                        # semantic clear must NOT upgrade
        r = build_m67_report(n, AS_OF, self.GEN); validate_m67_consistency(r)
        self.assertEqual(r["m67"]["table"]["操作"], "否决")

    def test_invalid_semantic_input_fails_closed(self):
        # R-ASHORT-M67-SEMANTIC-OFFICIAL-INPUT-CONSISTENCY-GAP + ...-EVIDENCE-SHAPE-GAP: malformed /
        # inconsistent / non-PIT / fabricated provider output must ValueError before any report
        # (no action↔trace contradiction; residual/non-PIT evidence cannot trigger M6.7 否决).
        from runners.a_short_phase5_engine import build_m67_report
        ev = {"source": "cninfo", "title": "t", "category": "c", "disclosure_date": "20260601",
              "url_or_pdf": "u", "risk_type": "立案", "severity": "high"}    # one valid PIT event
        bad_inputs = [
            {"status": "clear", "events": [ev]},                        # clear cannot carry events
            {"status": "unknown", "events": [ev]},                      # unknown cannot carry events
            {"events": [ev]},                                           # missing status
            {"status": "risk", "events": []},                           # risk must carry an event
            {"status": "risk", "events": [{**ev, "severity": "huge"}]}, # invalid severity
            {"status": "risk", "events": "abc"},                        # non-list events
            {"status": "risk", "events": ["x"]},                        # non-dict event
            "not-a-dict",                                               # non-dict semantic
            {"status": "risk", "events": [{"severity": "high", "risk_type": "x"}]},  # severity-only, no evidence
            {"status": "risk", "events": [{**ev, "source": "web"}]},    # non-official (manual/web) source
            {"status": "risk", "events": [{**ev, "disclosure_date": "20260701"}]},   # future date > as_of
            {"status": "risk", "events": [{**ev, "disclosure_date": "notadate"}]},   # non-canonical date
            {"status": "risk", "events": [{k: v for k, v in ev.items() if k != "risk_type"}]},  # missing risk_type
            {"status": "risk", "events": [{**ev, "risk_type": ""}]},                  # blank risk_type
            {"status": "risk", "events": [{**ev, "title": ""}]},                      # blank title
            {"status": "risk", "events": [{**ev, "category": ""}]},                   # blank category
            {"status": "risk", "events": [{**ev, "url_or_pdf": ""}]},                 # blank url/pdf
            {"status": "risk", "events": [{**ev, "title": "   "}]},                   # whitespace-only title
            {"status": "risk", "events": [ev], "had_pit_announcements": False},       # risk but no PIT
            {"status": "risk", "events": [ev]},                                       # missing had_pit_announcements
        ]
        for bad in bad_inputs:
            n = _normalized(); n["semantic"] = bad
            with self.assertRaises(ValueError):
                build_m67_report(n, AS_OF, self.GEN)

    def test_normalize_semantic_param_threads_through_build_weekly(self):
        n = normalize_candidate(_egs_candidate(), _series(), _overlay_row(), 55.0,
                                {"available_cash": 500000.0}, "震荡期",
                                semantic=_official("risk", "high", "立案调查"))
        self.assertEqual(n["semantic"]["status"], "risk")
        w = build_weekly_report([n], AS_OF, self.GEN)
        self.assertEqual(w["reports"][0]["m67"]["table"]["操作"], "否决")


if __name__ == "__main__":
    unittest.main()
