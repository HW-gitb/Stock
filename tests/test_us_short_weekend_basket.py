# -*- coding: utf-8 -*-
"""Tests for the US-short weekend-pipeline build-gate resolution (engine/us_short_weekend_basket.py) — batch4 slice 4d-ii-e/f/g.

Design authority: docs/us_short_system_design.md §8 (line 227 weekly build-limit + 同主题 cap; line 228-231
强赛道试探名额 theme_probe; line 230/238 portfolio_guard / symbol_cooldown new-build block) / §9 / §18.2.

Covers selection_rank by the PRESERVED Top15 rank (slice 2b: from selection_record, not a re-derived core_score),
the §8 BASE per-regime weekly build-limit (进攻3/震荡2/防御1/极度防御0),
the 同主题 weekly cap (≤2), the no-promotion interaction, capacity_or_budget_deferred emission, the 4d-ii-f
new-build blocking (portfolio_guard cooldown 禁新建 + per-symbol cooldown → 观察(risk_cooldown), removed before
ranking so a blocked symbol frees its slot), the 4d-ii-g theme_probe extra seats (promote eligible
capacity-deferred strong-theme builds up to the §8 #27 seat budget, under the 同主题 cap, tagged
theme_probe_min_size + entry-mode, size forced to min-executable), non-建仓 carry-through, the
symbol_cooldown status⟺engine triangulation, and fail-closed inputs.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_basket as wb  # noqa: E402
import engine.us_short_symbol_cooldown as sc  # noqa: E402
from engine.us_short_position_sizing import MIN_EXECUTABLE_SHARES  # noqa: E402


_DEFAULT = object()
# a default (non-eligible) theme_probe input block — low confidence so it never earns a probe by accident
_TP_OFF = {"theme_lifecycle_state": None, "high_confidence": False, "coverage_status": "full",
           "no_gap_week": False, "entry_in_band": False}


def _tp(hc=True, lc="confirmed_active", cov="full", gap=False, band=False):
    """A theme_probe eligibility input block (eligible by default)."""
    return {"theme_lifecycle_state": lc, "high_confidence": hc, "coverage_status": cov,
            "no_gap_week": gap, "entry_in_band": band}


def _brow(ticker, score, final="建仓", sizing=_DEFAULT):
    sz = ({"desired_model_shares": 50, "status": "sized"} if final == "建仓" else None) if sizing is _DEFAULT else sizing
    return {"ticker": ticker, "row_source": "top15_candidate", "row_context": "candidate",
            "final_action": final, "observe_reason_type": "data_restricted" if final == "观察" else None,
            "price": {"executable": True, "action_fields": {}, "trace": {}},
            "score": {"core_score": float(score), "profile": "balanced"},
            "sizing": sz}


def _sized(rows, regime="进攻"):
    # slice 2b: the basket now ranks builds by the PRESERVED Top15 selection_rank. Auto-attach a selection_record
    # to each 建仓 row (ranked by core_score desc, so the existing selection_rank-by-score expectations hold)
    # UNLESS the row already carries one — a test can inject an explicit rank to prove the basket consumes the
    # PRESERVED rank, not a re-derived core_score.
    auto_builds = sorted([r for r in rows if r.get("final_action") == "建仓" and "selection_record" not in r
                          and isinstance(r.get("score"), dict)],
                         key=lambda r: (-r["score"]["core_score"], r["ticker"]))
    auto = {r["ticker"]: i for i, r in enumerate(auto_builds, start=1)}
    out = [({**r, "selection_record": {"selection_rank": auto[r["ticker"]], "selection_bucket": "core_top",
                                       "core_score": r["score"]["core_score"], "theme_momentum_score": 0.0}}
            if r.get("ticker") in auto else r) for r in rows]
    return {"regime": {"market_risk_regime": regime, "position_cap": 1.0}, "rows": out}


def _ctx(theme_map, guard="normal", cooldowns=None, opp="no_strong_theme", probes=None, holding_themes=None):
    cooldowns = cooldowns or {}
    probes = probes or {}
    return {"per_ticker": {t: {"theme": th, "symbol_cooldown_status": cooldowns.get(t, "none"),
                              "theme_probe": probes.get(t, _TP_OFF)} for t, th in theme_map.items()},
            "holding_themes": holding_themes or {}, "portfolio_guard_status": guard,
            "theme_opportunity_state": opp}


def _resolve(rows, regime, theme_map, guard="normal", cooldowns=None, opp="no_strong_theme", probes=None):
    return wb.resolve_build_capacity(_sized(rows, regime),
                                     basket_context=_ctx(theme_map, guard, cooldowns, opp, probes))


def _by(out):
    return {r["ticker"]: r for r in out["rows"]}


class ResolveBuildCapacityTests(unittest.TestCase):
    # --- weekly build-limit by regime ---
    def test_aggressive_limit_3_excess_deferred(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80), _brow("CCC", 70), _brow("DDD", 60)],
                       "进攻", {"AAA": "t1", "BBB": "t2", "CCC": "t3", "DDD": "t4"})
        self.assertEqual(out["weekly_build_limit"], 3)
        self.assertEqual(out["build_count"], 3)
        by = _by(out)
        self.assertEqual([by[t]["final_action"] for t in ("AAA", "BBB", "CCC")], ["建仓"] * 3)
        self.assertEqual(by["DDD"]["final_action"], "观察")
        self.assertEqual(by["DDD"]["observe_reason_type"], "capacity_or_budget_deferred")
        self.assertEqual([by[t]["selection_rank"] for t in ("AAA", "BBB", "CCC", "DDD")], [1, 2, 3, 4])

    def test_neutral_limit_2(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80), _brow("CCC", 70)],
                       "震荡", {"AAA": "t1", "BBB": "t2", "CCC": "t3"})
        self.assertEqual((out["weekly_build_limit"], out["build_count"]), (2, 2))
        self.assertEqual(_by(out)["CCC"]["observe_reason_type"], "capacity_or_budget_deferred")

    def test_defensive_limit_1(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "防御", {"AAA": "t1", "BBB": "t2"})
        self.assertEqual((out["weekly_build_limit"], out["build_count"]), (1, 1))
        self.assertEqual(_by(out)["BBB"]["final_action"], "观察")

    def test_extreme_defensive_limit_0(self):
        # 极度防御 weekly limit 0 (safety net — 4d-ii-c position_cap==0 normally already deferred these)
        out = _resolve([_brow("AAA", 90)], "极度防御", {"AAA": "t1"})
        self.assertEqual((out["weekly_build_limit"], out["build_count"]), (0, 0))
        self.assertEqual(_by(out)["AAA"]["observe_reason_type"], "capacity_or_budget_deferred")

    # --- 同主题 weekly cap (≤2) ---
    def test_same_theme_cap_within_limit(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80), _brow("CCC", 70)],
                       "进攻", {"AAA": "tX", "BBB": "tX", "CCC": "tX"})  # all same theme, limit 3
        self.assertEqual(out["build_count"], 2)   # ≤2 per theme
        by = _by(out)
        self.assertEqual([by[t]["final_action"] for t in ("AAA", "BBB")], ["建仓", "建仓"])
        self.assertEqual(by["CCC"]["observe_reason_type"], "capacity_or_budget_deferred")

    def test_theme_cap_no_promotion(self):
        # top-3 by rank are tA,tA,tA; tB is rank 4. theme cap drops 3rd tA; tB is NOT base-promoted into the slot.
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80), _brow("CCC", 70), _brow("DDD", 60)],
                       "进攻", {"AAA": "tA", "BBB": "tA", "CCC": "tA", "DDD": "tB"})
        by = _by(out)
        self.assertEqual(out["build_count"], 2)   # AAA, BBB only — no base promotion of DDD
        self.assertEqual([by[t]["final_action"] for t in ("AAA", "BBB")], ["建仓", "建仓"])
        self.assertEqual(by["CCC"]["final_action"], "观察")
        self.assertEqual(by["DDD"]["final_action"], "观察")

    # --- selection_rank ordering ---
    def test_selection_rank_by_score(self):
        out = _resolve([_brow("LOW", 10), _brow("HIGH", 99), _brow("MID", 55)],
                       "进攻", {"LOW": "t1", "HIGH": "t2", "MID": "t3"})
        by = _by(out)
        self.assertEqual((by["HIGH"]["selection_rank"], by["MID"]["selection_rank"], by["LOW"]["selection_rank"]),
                         (1, 2, 3))

    # --- non-build carry-through ---
    def test_non_build_rows_carry_through(self):
        out = _resolve([_brow("AAA", 90), _brow("OBS", 50, final="观察"), _brow("HLD", 0, final="持有")],
                       "进攻", {"AAA": "t1"})   # per_ticker only the build
        by = _by(out)
        self.assertEqual(by["AAA"]["final_action"], "建仓")
        self.assertIsNone(by["OBS"]["selection_rank"])
        self.assertEqual(by["OBS"]["final_action"], "观察")
        self.assertEqual(by["OBS"]["observe_reason_type"], "data_restricted")   # unchanged
        self.assertIsNone(by["HLD"]["selection_rank"])

    def test_no_builds_zero_count(self):
        out = _resolve([_brow("HLD", 0, final="持有")], "进攻", {})
        self.assertEqual(out["build_count"], 0)

    # --- 4d-ii-f: portfolio_guard / symbol_cooldown new-build blocking → 观察(risk_cooldown) ---
    def test_portfolio_guard_cooldown_blocks_all_builds(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "进攻",
                       {"AAA": "t1", "BBB": "t2"}, guard="cooldown")
        self.assertEqual(out["build_count"], 0)
        by = _by(out)
        for t in ("AAA", "BBB"):
            self.assertEqual(by[t]["final_action"], "观察")
            self.assertEqual(by[t]["observe_reason_type"], "risk_cooldown")
            self.assertIsNone(by[t]["selection_rank"])

    def test_portfolio_guard_caution_does_not_block(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "进攻",
                       {"AAA": "t1", "BBB": "t2"}, guard="caution")
        self.assertEqual(out["build_count"], 2)
        self.assertTrue(all(_by(out)[t]["final_action"] == "建仓" for t in ("AAA", "BBB")))

    def test_portfolio_guard_recovery_does_not_block(self):
        out = _resolve([_brow("AAA", 90)], "进攻", {"AAA": "t1"}, guard="recovery")
        self.assertEqual(_by(out)["AAA"]["final_action"], "建仓")

    def test_symbol_in_cooldown_blocks_that_build_only(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "进攻",
                       {"AAA": "t1", "BBB": "t2"}, cooldowns={"BBB": "in_cooldown"})
        by = _by(out)
        self.assertEqual(by["AAA"]["final_action"], "建仓")
        self.assertEqual(by["BBB"]["final_action"], "观察")
        self.assertEqual(by["BBB"]["observe_reason_type"], "risk_cooldown")
        self.assertIsNone(by["BBB"]["selection_rank"])
        self.assertEqual(out["build_count"], 1)

    def test_symbol_entering_cooldown_blocks(self):
        out = _resolve([_brow("AAA", 90)], "进攻", {"AAA": "t1"}, cooldowns={"AAA": "entering_cooldown"})
        self.assertEqual(_by(out)["AAA"]["observe_reason_type"], "risk_cooldown")

    def test_symbol_reentry_allowed_does_not_block(self):
        out = _resolve([_brow("AAA", 90)], "进攻", {"AAA": "t1"}, cooldowns={"AAA": "reentry_allowed"})
        self.assertEqual(_by(out)["AAA"]["final_action"], "建仓")

    def test_symbol_none_does_not_block(self):
        out = _resolve([_brow("AAA", 90)], "进攻", {"AAA": "t1"}, cooldowns={"AAA": "none"})
        self.assertEqual(_by(out)["AAA"]["final_action"], "建仓")

    def test_blocked_build_frees_slot_before_ranking(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80), _brow("CCC", 70), _brow("DDD", 60)],
                       "进攻", {"AAA": "t1", "BBB": "t2", "CCC": "t3", "DDD": "t4"},
                       cooldowns={"AAA": "in_cooldown"})
        by = _by(out)
        self.assertEqual(by["AAA"]["observe_reason_type"], "risk_cooldown")
        self.assertEqual(out["build_count"], 3)   # BBB, CCC, DDD — AAA's slot was freed, DDD not deferred
        self.assertTrue(all(by[t]["final_action"] == "建仓" for t in ("BBB", "CCC", "DDD")))

    def test_block_takes_precedence_over_capacity(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "防御",
                       {"AAA": "t1", "BBB": "t2"}, cooldowns={"AAA": "in_cooldown"})
        by = _by(out)
        self.assertEqual(by["AAA"]["observe_reason_type"], "risk_cooldown")
        self.assertIsNone(by["AAA"]["selection_rank"])
        self.assertEqual(by["BBB"]["final_action"], "建仓")
        self.assertEqual(out["build_count"], 1)

    # --- 4d-ii-g: theme_probe extra seats (§8 强赛道试探名额) ---
    def test_theme_probe_promotes_deferred_strong(self):
        # 防御 limit 1: AAA base, BBB deferred; 防御+strong = 1 seat → BBB promoted (建仓 + theme_probe tag).
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "防御",
                       {"AAA": "t1", "BBB": "t2"}, opp="strong",
                       probes={"AAA": _tp(), "BBB": _tp()})
        by = _by(out)
        self.assertEqual(out["build_count"], 2)
        self.assertEqual(by["BBB"]["final_action"], "建仓")
        self.assertEqual(by["BBB"]["theme_probe"]["risk_tag"], "theme_probe_min_size")
        self.assertEqual(by["BBB"]["selection_rank"], 2)              # keeps its rank
        self.assertEqual(by["BBB"]["sizing"]["desired_model_shares"], MIN_EXECUTABLE_SHARES)   # forced min size
        self.assertEqual(by["BBB"]["sizing"]["pre_probe_risk_shares"], 50)   # pre-probe risk size kept as trace
        self.assertNotIn("theme_probe", by["AAA"])                   # a base build is not a probe

    def test_promoted_probe_forced_to_min_executable_size(self):
        # §8 forced-min invariant: a promoted probe must NOT keep its 4d-ii-c risk size — whatever it was
        # (here 500), it is forced to MIN_EXECUTABLE_SHARES, with the pre-probe risk size kept as a trace.
        big = {"desired_model_shares": 500, "status": "sized"}
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80, sizing=big)], "防御",
                       {"AAA": "t1", "BBB": "t2"}, opp="strong", probes={"AAA": _tp(), "BBB": _tp()})
        probe = _by(out)["BBB"]
        self.assertEqual(probe["final_action"], "建仓")
        self.assertEqual(probe["theme_probe"]["risk_tag"], "theme_probe_min_size")
        self.assertEqual(probe["sizing"]["desired_model_shares"], MIN_EXECUTABLE_SHARES)
        self.assertLessEqual(probe["sizing"]["desired_model_shares"], MIN_EXECUTABLE_SHARES)   # never > min
        self.assertEqual(probe["sizing"]["pre_probe_risk_shares"], 500)   # original risk size preserved
        self.assertEqual(probe["sizing"]["reason"], "theme_probe_forced_min")

    def test_no_strong_theme_no_probe(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "防御",
                       {"AAA": "t1", "BBB": "t2"}, opp="no_strong_theme",
                       probes={"AAA": _tp(), "BBB": _tp()})
        self.assertEqual(out["build_count"], 1)   # 0 seats
        self.assertEqual(_by(out)["BBB"]["observe_reason_type"], "capacity_or_budget_deferred")

    def test_normal_theme_no_probe(self):
        # `normal` theme_opportunity_state is also 0 seats (matrix: only strong/extreme grant probes) —
        # a deferred eligible build is NOT promoted under `normal`.
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "防御",
                       {"AAA": "t1", "BBB": "t2"}, opp="normal",
                       probes={"AAA": _tp(), "BBB": _tp()})
        self.assertEqual(out["build_count"], 1)   # 0 seats → BBB stays deferred
        self.assertEqual(_by(out)["BBB"]["observe_reason_type"], "capacity_or_budget_deferred")

    def test_theme_probe_ineligible_low_confidence(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "防御",
                       {"AAA": "t1", "BBB": "t2"}, opp="strong",
                       probes={"AAA": _tp(), "BBB": _tp(hc=False)})
        self.assertEqual(_by(out)["BBB"]["final_action"], "观察")   # low confidence → no probe

    def test_theme_probe_ineligible_restricted_coverage(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "防御",
                       {"AAA": "t1", "BBB": "t2"}, opp="strong",
                       probes={"AAA": _tp(), "BBB": _tp(cov="restricted")})
        self.assertEqual(_by(out)["BBB"]["final_action"], "观察")   # restricted coverage → no probe

    def test_theme_probe_ineligible_degraded_lifecycle(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "防御",
                       {"AAA": "t1", "BBB": "t2"}, opp="strong",
                       probes={"AAA": _tp(), "BBB": _tp(lc="cooling")})
        self.assertEqual(_by(out)["BBB"]["final_action"], "观察")   # cooling theme → no new probe

    def test_theme_probe_seat_budget_caps_promotions(self):
        # 进攻 limit 3 + extreme = 2 seats; 5 builds → 3 base + 2 deferred, both eligible → exactly 2 promoted.
        rows = [_brow(t, 90 - i) for i, t in enumerate(["A", "B", "C", "D", "E"])]
        out = _resolve(rows, "进攻", {t: "th" + t for t in "ABCDE"}, opp="extreme",
                       probes={t: _tp() for t in "ABCDE"})
        self.assertEqual(out["build_count"], 5)   # 3 base + 2 probe (seat budget 2)

    def test_theme_probe_respects_same_theme_cap(self):
        # 防御 limit 1, theme X: AAA base (X count 1). extreme = 1 seat. BBB(X) promoted (X→2=cap); CCC(X) blocked.
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80), _brow("CCC", 70)], "防御",
                       {"AAA": "X", "BBB": "X", "CCC": "X"}, opp="extreme",
                       probes={t: _tp() for t in ("AAA", "BBB", "CCC")})
        by = _by(out)
        self.assertEqual(out["build_count"], 2)   # AAA base + BBB probe; CCC deferred (theme cap)
        self.assertEqual(by["CCC"]["observe_reason_type"], "capacity_or_budget_deferred")

    def test_theme_probe_same_theme_cap_blocks_with_spare_seats(self):
        # 进攻 limit 3, all theme X: AAA+BBB base (X→2=cap), CCC deferred. extreme = 2 seats (spare), but X
        # is already at the 同主题 cap → CCC is NOT promoted even with a free seat (theme cap, not seat budget).
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80), _brow("CCC", 70)], "进攻",
                       {"AAA": "X", "BBB": "X", "CCC": "X"}, opp="extreme",
                       probes={t: _tp() for t in ("AAA", "BBB", "CCC")})
        self.assertEqual(out["build_count"], 2)   # AAA+BBB base; CCC blocked by 同主题 cap despite a spare seat
        self.assertEqual(_by(out)["CCC"]["observe_reason_type"], "capacity_or_budget_deferred")

    def test_extreme_defensive_no_probe_even_extreme(self):
        out = _resolve([_brow("AAA", 90)], "极度防御", {"AAA": "t1"}, opp="extreme",
                       probes={"AAA": _tp()})
        self.assertEqual(out["build_count"], 0)   # 极度防御 row = 0 seats regardless of theme state

    def test_promoted_probe_defensive_pullback_entry_mode(self):
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "防御",
                       {"AAA": "t1", "BBB": "t2"}, opp="strong",
                       probes={"AAA": _tp(), "BBB": _tp()})
        self.assertEqual(_by(out)["BBB"]["theme_probe"]["entry_mode_constraint"], "pullback_only")

    def test_promoted_probe_defensive_breakout_exception(self):
        # 防御 + extreme + no_gap_week + entry_in_band → the single breakout-exception entry mode.
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "防御",
                       {"AAA": "t1", "BBB": "t2"}, opp="extreme",
                       probes={"AAA": _tp(gap=True, band=True), "BBB": _tp(gap=True, band=True)})
        self.assertEqual(_by(out)["BBB"]["theme_probe"]["entry_mode_constraint"], "breakout_exception_allowed")

    # --- fail-closed ---
    def test_malformed_sized_result_raises(self):
        for bad in ({"rows": []}, {"regime": {}}, {"regime": {"market_risk_regime": "进攻"}, "rows": {}}):
            with self.assertRaises(wb.WeekendBasketError):
                wb.resolve_build_capacity(bad, basket_context=_ctx({}))

    def test_bad_regime_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90)], "bull_market", {"AAA": "t1"})

    def test_bad_basket_context_raises(self):
        base = _ctx({"AAA": "t1"})
        for ctx in ({**base, "x": 1},                                          # extra top-level key
                    {"per_ticker": "nope", "holding_themes": {}, "portfolio_guard_status": "normal",
                     "theme_opportunity_state": "no_strong_theme"},            # per_ticker not a dict
                    {k: v for k, v in base.items() if k != "portfolio_guard_status"},   # missing guard
                    {k: v for k, v in base.items() if k != "theme_opportunity_state"},  # missing opp state
                    {k: v for k, v in base.items() if k != "holding_themes"}):           # missing holding themes
            with self.assertRaises(wb.WeekendBasketError):
                wb.resolve_build_capacity(_sized([_brow("AAA", 90)]), basket_context=ctx)

    def test_bad_portfolio_guard_status_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90)], "进攻", {"AAA": "t1"}, guard="halt")

    def test_bad_theme_opportunity_state_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90)], "进攻", {"AAA": "t1"}, opp="mega_strong")

    def test_bad_symbol_cooldown_status_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90)], "进攻", {"AAA": "t1"}, cooldowns={"AAA": "frozen"})

    def test_missing_symbol_cooldown_status_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            wb.resolve_build_capacity(
                _sized([_brow("AAA", 90)]),
                basket_context={"per_ticker": {"AAA": {"theme": "t1", "theme_probe": _TP_OFF}},
                                "holding_themes": {}, "portfolio_guard_status": "normal",
                                "theme_opportunity_state": "no_strong_theme"})

    def test_malformed_theme_probe_shape_raises(self):
        for tp in (None, {"high_confidence": True}, {**_TP_OFF, "x": 1}):
            with self.assertRaises(wb.WeekendBasketError):
                wb.resolve_build_capacity(
                    _sized([_brow("AAA", 90)]),
                    basket_context={"per_ticker": {"AAA": {"theme": "t1", "symbol_cooldown_status": "none",
                                                          "theme_probe": tp}},
                                    "holding_themes": {}, "portfolio_guard_status": "normal",
                                    "theme_opportunity_state": "no_strong_theme"})

    def test_missing_build_theme_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90)], "进攻", {})   # build AAA has no per_ticker entry

    def test_stale_per_ticker_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90)], "进攻", {"AAA": "t1", "STALE": "t2"})

    def test_build_missing_selection_record_raises(self):
        # slice 2b: a 建仓 with no preserved selection_record (selection identity lost) fails closed — the basket
        # must NOT silently fall back to a re-derived rank.
        row = _brow("AAA", 90)
        row["selection_record"] = None
        with self.assertRaises(wb.WeekendBasketError):
            wb.resolve_build_capacity(_sized([row]), basket_context=_ctx({"AAA": "t1"}))

    def test_per_ticker_bad_theme_shape_raises(self):
        for tinfo in ({"theme": "t1", "symbol_cooldown_status": "none", "theme_probe": _TP_OFF, "x": 1},  # extra key
                      {"theme": "", "symbol_cooldown_status": "none", "theme_probe": _TP_OFF},   # blank theme
                      {"theme": "t1", "symbol_cooldown_status": "none"}):                        # missing theme_probe
            with self.assertRaises(wb.WeekendBasketError):
                wb.resolve_build_capacity(
                    _sized([_brow("AAA", 90)]),
                    basket_context={"per_ticker": {"AAA": tinfo}, "holding_themes": {}, "portfolio_guard_status": "normal",
                                    "theme_opportunity_state": "no_strong_theme"})

    def test_duplicate_build_ticker_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            wb.resolve_build_capacity(_sized([_brow("AAA", 90), _brow("AAA", 80)]),
                                      basket_context=_ctx({"AAA": "t1"}))

    # --- value-contract: frozen action vocab / canonical ticker / sizing payload / theme normalization ---
    def test_unknown_final_action_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90, final="BANANA")], "进攻", {})

    def test_lowercase_build_ticker_emitted_uppercase(self):
        out = _resolve([_brow("aapl", 90)], "进攻", {"AAPL": "t1"})   # per_ticker canonical
        self.assertEqual(_by(out)["AAPL"]["ticker"], "AAPL")
        self.assertEqual(_by(out)["AAPL"]["final_action"], "建仓")


class PreservedSelectionRankTests(unittest.TestCase):
    """R-USSHORT-BATCH4-SELECTION-TRACE-AND-RECALL-CLOSURE-GAP (slice 2b): the basket ranks builds by the
    PRESERVED Top15 selection_rank, NOT a re-derived analysis core_score — so a downstream re-score can never
    reverse the selection-time build/cash priority (the exact reversal the strict review reproduced)."""

    @staticmethod
    def _ranked(ticker, core, sel_rank):
        r = _brow(ticker, core)   # core kept on the row (machine-record evidence) but no longer drives the rank
        r["selection_record"] = {"selection_rank": sel_rank, "selection_bucket": "core_top",
                                 "core_score": float(core), "theme_momentum_score": 0.0}
        return r

    def test_preserved_rank_overrides_core_order(self):
        # AAA has the HIGHER analysis core (90 vs 10) but BBB has the BETTER preserved Top15 rank (1 vs 2) →
        # the basket must emit BBB rank 1 / AAA rank 2 (preserved wins), not reverse it to follow core.
        out = _resolve([self._ranked("AAA", 90, 2), self._ranked("BBB", 10, 1)], "进攻",
                       {"AAA": "t1", "BBB": "t2"})
        by = _by(out)
        self.assertEqual((by["BBB"]["selection_rank"], by["AAA"]["selection_rank"]), (1, 2))

    def test_weekly_limit_uses_preserved_order(self):
        # defensive limit 1: the single survivor is the preserved-rank-1 name (BBB), NOT the high-core AAA.
        out = _resolve([self._ranked("AAA", 90, 2), self._ranked("BBB", 10, 1)], "防御",
                       {"AAA": "t1", "BBB": "t2"})
        by = _by(out)
        self.assertEqual((by["BBB"]["final_action"], by["AAA"]["final_action"]), ("建仓", "观察"))
        self.assertEqual(by["AAA"]["observe_reason_type"], "capacity_or_budget_deferred")

    def test_sparse_preserved_rank_emitted_verbatim(self):
        # a Top15 name downgraded upstream leaves a gap → the surviving builds keep their SPARSE preserved ranks
        # (1 and 3), not a re-densified 1,2 — the emitted selection_rank is the真实 Top15 rank.
        out = _resolve([self._ranked("AAA", 90, 1), self._ranked("CCC", 70, 3)], "进攻",
                       {"AAA": "t1", "CCC": "t3"})
        by = _by(out)
        self.assertEqual((by["AAA"]["selection_rank"], by["CCC"]["selection_rank"]), (1, 3))

    def test_non_build_lowercase_ticker_emitted_uppercase(self):
        out = _resolve([_brow("AAA", 90), _brow("obs", 50, final="观察")], "进攻", {"AAA": "t1"})
        self.assertEqual(_by(out)["OBS"]["ticker"], "OBS")   # non-build ticker canonicalized + emitted too

    def test_lowercase_per_ticker_key_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("aapl", 90)], "进攻", {"aapl": "t1"})   # non-canonical per_ticker key → coverage mismatch

    def test_non_canonical_ticker_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("000001.SZ", 90)], "进攻", {"000001.SZ": "t1"})

    def test_duplicate_canonical_identity_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            wb.resolve_build_capacity(_sized([_brow("AAA", 90), _brow("aaa", 80, final="观察")]),
                                      basket_context=_ctx({"AAA": "t1"}))   # AAA / aaa = one stock

    def test_build_invalid_sizing_payload_raises(self):
        for bad in (None, {"status": "observe", "desired_model_shares": 50},
                    {"status": "sized", "desired_model_shares": 0}, {"status": "sized"},
                    {"desired_model_shares": 50}):
            with self.assertRaises(wb.WeekendBasketError):
                wb.resolve_build_capacity(_sized([_brow("AAA", 90, sizing=bad)]), basket_context=_ctx({"AAA": "t1"}))

    # --- observe_reason_type ⟺ final_action consistency ---
    def test_observe_row_bad_reason_raises(self):
        row = _brow("OBS", 50, final="观察")
        row["observe_reason_type"] = "BANANA"
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([row], "进攻", {})

    def test_observe_row_missing_reason_raises(self):
        row = _brow("OBS", 50, final="观察")
        row["observe_reason_type"] = None
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([row], "进攻", {})

    def test_non_observe_row_stale_reason_raises(self):
        row = _brow("HLD", 0, final="持有")
        row["observe_reason_type"] = "data_restricted"   # 持有 must NOT carry an observe reason
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([row], "进攻", {})

    def test_whitespace_theme_variants_capped(self):
        # "AI" / " AI " / "AI" are the SAME theme after strip → ≤2 builds even at weekly limit 3 (no dodge)
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80), _brow("CCC", 70)],
                       "进攻", {"AAA": "AI", "BBB": " AI ", "CCC": "AI"})
        self.assertEqual(out["build_count"], 2)
        self.assertEqual(_by(out)["CCC"]["observe_reason_type"], "capacity_or_budget_deferred")

    # --- triangulation: the local symbol-cooldown blocking set is pinned to the engine's actual behavior ---
    def test_symbol_cooldown_blocking_set_matches_engine(self):
        cases = [
            sc.symbol_cooldown_status(False),                                                 # none
            sc.symbol_cooldown_status(False, trigger="filled_then_stop_loss"),               # entering_cooldown
            sc.symbol_cooldown_status(False, trigger="filled_then_breakout_failure"),        # entering_cooldown
            sc.symbol_cooldown_status(True),                                                 # in_cooldown
            sc.symbol_cooldown_status(True, new_catalyst=True, new_structure=True, cooldown_expired=True),  # reentry
            sc.symbol_cooldown_status("garbage"),                                            # malformed → in_cooldown
        ]
        seen = set()
        for res in cases:
            status, action = res["status"], res["action"]
            seen.add(status)
            self.assertIn(status, wb.SYMBOL_COOLDOWN_STATUSES)
            self.assertEqual(status in wb._SYMBOL_COOLDOWN_BLOCKS_NEW, action == "downgrade_to_observe")
        self.assertEqual(seen, set(wb.SYMBOL_COOLDOWN_STATUSES))   # all four statuses exercised


if __name__ == "__main__":
    unittest.main()
