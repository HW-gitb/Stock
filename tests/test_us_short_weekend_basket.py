# -*- coding: utf-8 -*-
"""Tests for the US-short weekend-pipeline build-gate resolution (engine/us_short_weekend_basket.py) — batch4 slice 4d-ii-e/f.

Design authority: docs/us_short_system_design.md §8 (line 227 weekly build-limit + 同主题 cap; line 230/238
portfolio_guard / symbol_cooldown new-build block) / §9 / §18.2.

Covers selection_rank by core_score, the §8 BASE per-regime weekly build-limit (进攻3/震荡2/防御1/极度防御0),
the 同主题 weekly cap (≤2), the no-promotion interaction, capacity_or_budget_deferred emission for
capacity-deferred builds, the 4d-ii-f new-build blocking (portfolio_guard cooldown 禁新建 + per-symbol
cooldown → 观察(risk_cooldown), removed before ranking so a blocked symbol frees its slot), non-建仓
carry-through, the symbol_cooldown status⟺engine triangulation, and fail-closed sized_result / regime /
basket_context / guard-state / cooldown-state inputs.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_basket as wb  # noqa: E402
import engine.us_short_symbol_cooldown as sc  # noqa: E402


_DEFAULT = object()


def _brow(ticker, score, final="建仓", sizing=_DEFAULT):
    sz = ({"desired_model_shares": 50, "status": "sized"} if final == "建仓" else None) if sizing is _DEFAULT else sizing
    return {"ticker": ticker, "row_source": "top15_candidate", "row_context": "candidate",
            "final_action": final, "observe_reason_type": "data_restricted" if final == "观察" else None,
            "price": {"executable": True, "action_fields": {}, "trace": {}},
            "score": {"core_score": float(score), "profile": "balanced"},
            "sizing": sz}


def _sized(rows, regime="进攻"):
    return {"regime": {"market_risk_regime": regime, "position_cap": 1.0}, "rows": rows}


def _ctx(theme_map, guard="normal", cooldowns=None):
    cooldowns = cooldowns or {}
    return {"per_ticker": {t: {"theme": th, "symbol_cooldown_status": cooldowns.get(t, "none")}
                           for t, th in theme_map.items()},
            "portfolio_guard_status": guard}


def _resolve(rows, regime, theme_map, guard="normal", cooldowns=None):
    return wb.resolve_build_capacity(_sized(rows, regime), basket_context=_ctx(theme_map, guard, cooldowns))


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
        # top-3 by rank are tA,tA,tA; tB is rank 4. theme cap drops 3rd tA; tB is NOT promoted into the slot.
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80), _brow("CCC", 70), _brow("DDD", 60)],
                       "进攻", {"AAA": "tA", "BBB": "tA", "CCC": "tA", "DDD": "tB"})
        by = _by(out)
        self.assertEqual(out["build_count"], 2)   # AAA, BBB only — no promotion of DDD
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
        # account cooldown (禁新建) → every provisional 建仓 → 观察(risk_cooldown), no rank, zero build_count.
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "进攻",
                       {"AAA": "t1", "BBB": "t2"}, guard="cooldown")
        self.assertEqual(out["build_count"], 0)
        by = _by(out)
        for t in ("AAA", "BBB"):
            self.assertEqual(by[t]["final_action"], "观察")
            self.assertEqual(by[t]["observe_reason_type"], "risk_cooldown")
            self.assertIsNone(by[t]["selection_rank"])

    def test_portfolio_guard_caution_does_not_block(self):
        # caution has block_new_entry=False (its reduce_* graded effects are out of this slice's scope).
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
        # 进攻 limit 3; top-ranked AAA is symbol-cooled → it does NOT consume a slot, so BBB/CCC/DDD all build.
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80), _brow("CCC", 70), _brow("DDD", 60)],
                       "进攻", {"AAA": "t1", "BBB": "t2", "CCC": "t3", "DDD": "t4"},
                       cooldowns={"AAA": "in_cooldown"})
        by = _by(out)
        self.assertEqual(by["AAA"]["observe_reason_type"], "risk_cooldown")
        self.assertEqual(out["build_count"], 3)   # BBB, CCC, DDD — AAA's slot was freed, DDD not deferred
        self.assertTrue(all(by[t]["final_action"] == "建仓" for t in ("BBB", "CCC", "DDD")))

    def test_block_takes_precedence_over_capacity(self):
        # 防御 limit 1; top-ranked AAA is blocked → risk_cooldown (NOT capacity_or_budget_deferred); BBB builds.
        out = _resolve([_brow("AAA", 90), _brow("BBB", 80)], "防御",
                       {"AAA": "t1", "BBB": "t2"}, cooldowns={"AAA": "in_cooldown"})
        by = _by(out)
        self.assertEqual(by["AAA"]["observe_reason_type"], "risk_cooldown")
        self.assertIsNone(by["AAA"]["selection_rank"])
        self.assertEqual(by["BBB"]["final_action"], "建仓")
        self.assertEqual(out["build_count"], 1)

    # --- fail-closed ---
    def test_malformed_sized_result_raises(self):
        for bad in ({"rows": []}, {"regime": {}}, {"regime": {"market_risk_regime": "进攻"}, "rows": {}}):
            with self.assertRaises(wb.WeekendBasketError):
                wb.resolve_build_capacity(bad, basket_context=_ctx({}))

    def test_bad_regime_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90)], "bull_market", {"AAA": "t1"})

    def test_bad_basket_context_raises(self):
        for ctx in ({"per_ticker": {}, "portfolio_guard_status": "normal", "x": 1},   # extra top-level key
                    {"per_ticker": "nope", "portfolio_guard_status": "normal"},         # per_ticker not a dict
                    {"per_ticker": {}}):                                                # missing portfolio_guard_status
            with self.assertRaises(wb.WeekendBasketError):
                wb.resolve_build_capacity(_sized([_brow("AAA", 90)]), basket_context=ctx)

    def test_bad_portfolio_guard_status_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90)], "进攻", {"AAA": "t1"}, guard="halt")

    def test_bad_symbol_cooldown_status_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90)], "进攻", {"AAA": "t1"}, cooldowns={"AAA": "frozen"})

    def test_missing_symbol_cooldown_status_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            wb.resolve_build_capacity(_sized([_brow("AAA", 90)]),
                                      basket_context={"per_ticker": {"AAA": {"theme": "t1"}},
                                                      "portfolio_guard_status": "normal"})

    def test_missing_build_theme_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90)], "进攻", {})   # build AAA has no per_ticker entry

    def test_stale_per_ticker_raises(self):
        with self.assertRaises(wb.WeekendBasketError):
            _resolve([_brow("AAA", 90)], "进攻", {"AAA": "t1", "STALE": "t2"})

    def test_build_missing_core_score_raises(self):
        row = _brow("AAA", 90)
        row["score"] = None
        with self.assertRaises(wb.WeekendBasketError):
            wb.resolve_build_capacity(_sized([row]), basket_context=_ctx({"AAA": "t1"}))

    def test_per_ticker_bad_theme_shape_raises(self):
        for tinfo in ({"theme": "t1", "x": 1},                              # extra key
                      {"theme": "", "symbol_cooldown_status": "none"}):      # blank theme
            with self.assertRaises(wb.WeekendBasketError):
                wb.resolve_build_capacity(
                    _sized([_brow("AAA", 90)]),
                    basket_context={"per_ticker": {"AAA": tinfo}, "portfolio_guard_status": "normal"})

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

    # --- observe_reason_type ⟺ final_action consistency (Codex residual) ---
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
        # Every status the engine can emit must be in SYMBOL_COOLDOWN_STATUSES, and a status blocks a new
        # build (∈ _SYMBOL_COOLDOWN_BLOCKS_NEW) IFF the engine downgrades it to observe — so this module's
        # mapping cannot silently drift from us_short_symbol_cooldown.
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
