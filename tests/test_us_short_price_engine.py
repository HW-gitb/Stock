# -*- coding: utf-8 -*-
"""Tests for the US-short price engine (engine/us_short_price_engine.py) — §6 / §6.1.

Covers batch-2 首刀 price geometry (§18.1 #5 + #16): de-spike wick rejection, side-aware tick +
post-round RR recheck, min_rr_gate, pullback/breakout sub-modes, holding passive levels + breach,
degrade-to-observe (never fabricate), and conformance of every emitted field to the frozen
us_short_action_table_contract columns + locked vocab. Adversarial by design (fewer FAIL->修复 rounds):
the post-round-break and missing-data cases are reverse-failure controls.
"""
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_price_engine as pe  # noqa: E402

_CONTRACT = ROOT / "presets" / "us_short_action_table_contract_20260620.json"


def _bars(n, high, low, close):
    return [{"high": high, "low": low, "close": close} for _ in range(n)]


def _ind(sup, res, atr, sup_q="strong", res_q="strong"):
    return {"effective_support": sup, "support_quality": sup_q,
            "effective_resistance": res, "resistance_quality": res_q, "atr": atr}


# ── indicators: ATR + de-spike ────────────────────────────────────────────────────────────
class IndicatorTests(unittest.TestCase):
    def test_atr_constant_range(self):
        bars = _bars(20, 102.0, 98.0, 100.0)  # TR each = max(4, 2, 2) = 4
        self.assertAlmostEqual(pe.atr(bars), 4.0)

    def test_atr_insufficient_bars_none(self):
        self.assertIsNone(pe.atr(_bars(10, 102.0, 98.0, 100.0)))  # < 14+1

    def test_effective_support_strong_extreme_backed(self):
        lows = [99.0] + [100.0] * 19          # raw 99, 2nd-low 100, diff 1 <= 1*ATR(2) -> not a wick
        bars = [{"high": 101.0, "low": x, "close": 100.0} for x in lows]
        self.assertEqual(pe.effective_support(bars, 2.0), (99.0, "strong", 99.0))

    def test_effective_support_weak_wick_rejected(self):
        lows = [90.0] + [100.0] * 19          # raw 90, 2nd-low 100, diff 10 > 1*ATR(2) -> wick -> take 2nd
        bars = [{"high": 101.0, "low": x, "close": 100.0} for x in lows]
        self.assertEqual(pe.effective_support(bars, 2.0), (100.0, "weak", 90.0))

    def test_effective_support_fallback_when_no_atr(self):
        bars = [{"high": 101.0, "low": x, "close": 100.0} for x in ([90.0] + [100.0] * 19)]
        self.assertEqual(pe.effective_support(bars, None), (90.0, "fallback_extreme", 90.0))

    def test_effective_resistance_weak_wick_rejected(self):
        highs = [110.0] + [100.0] * 19        # raw 110, 2nd-high 100, diff 10 > 1*ATR(2) -> wick -> 2nd
        bars = [{"high": x, "low": 99.0, "close": 100.0} for x in highs]
        self.assertEqual(pe.effective_resistance(bars, 2.0), (100.0, "weak", 110.0))

    def test_effective_resistance_strong(self):
        highs = [101.0] + [100.0] * 19        # raw 101, 2nd 100, diff 1 <= 2 -> strong
        bars = [{"high": x, "low": 99.0, "close": 100.0} for x in highs]
        self.assertEqual(pe.effective_resistance(bars, 2.0), (101.0, "strong", 101.0))

    def test_empty_bars_none(self):
        self.assertEqual(pe.effective_support([], 2.0), (None, None, None))
        self.assertEqual(pe.effective_resistance([], 2.0), (None, None, None))


# ── side-aware tick ───────────────────────────────────────────────────────────────────────
class TickTests(unittest.TestCase):
    PENNY = Decimal("0.01")

    def test_tick_ref_half_up(self):
        self.assertEqual(pe.tick_ref(9.014, self.PENNY), 9.01)
        self.assertEqual(pe.tick_ref(9.016, self.PENNY), 9.02)

    def test_tick_up_ceils(self):
        self.assertEqual(pe.tick_up(9.001, self.PENNY), 9.01)

    def test_tick_down_floors(self):
        self.assertEqual(pe.tick_down(9.009, self.PENNY), 9.00)

    def test_tick_none_naninf_returns_none(self):
        self.assertIsNone(pe.tick_ref(None, self.PENNY))
        self.assertIsNone(pe.tick_ref(float("nan"), self.PENNY))
        self.assertIsNone(pe.tick_ref(float("inf"), self.PENNY))

    def test_tick_size_for_subpenny_carveout(self):
        self.assertEqual(pe.tick_size_for(0.5), Decimal("0.0001"))   # < $1 -> sub-penny
        self.assertEqual(pe.tick_size_for(1.0), Decimal("0.01"))     # >= $1 -> penny
        self.assertEqual(pe.tick_size_for(5.0), Decimal("0.01"))
        self.assertEqual(pe.tick_size_for(0), Decimal("0.01"))       # 0 is not > 0 -> penny
        self.assertEqual(pe.tick_size_for(None), Decimal("0.01"))

    def test_subpenny_tick_applied_below_one_dollar(self):
        r = pe.support_atr_engine({"close": 0.50, "indicators": _ind(0.49, 0.60, 0.005)}, "震荡", "pullback")
        self.assertEqual(r["trace"]["execution_tick"], 0.0001)


# ── support_atr_engine: pullback / breakout / RR gate / post-round / missing ───────────────
class SupportAtrEngineTests(unittest.TestCase):
    def test_pullback_happy_path(self):
        r = pe.support_atr_engine({"close": 100.0, "indicators": _ind(98.0, 110.0, 2.0)}, "震荡", "pullback")
        f = r["action_fields"]
        self.assertTrue(r["executable"])
        self.assertEqual(f["price_engine_used"], "support_atr_engine")
        self.assertEqual(f["price_sub_mode"], "pullback")
        self.assertEqual(f["order_type"], "pullback_limit")
        self.assertEqual(f["order_expiry"], "first_regular_session_only")
        self.assertEqual(f["stop_clear_price"], 95.5)            # 98 - 1.25*2
        self.assertEqual(f["take_profit_reduce_price"], 110.0)   # structural resistance
        self.assertEqual(f["take_profit_exit_price"], 112.5)     # max(110+2.5, 100+9)
        self.assertEqual((f["valid_entry_low"], f["valid_entry_high"]), (99.0, 100.0))
        self.assertEqual(f["pullback_entry_price"], 99.0)
        self.assertIsNone(f["breakout_entry_price"])
        self.assertEqual(f["min_rr_gate_status"], "pass")
        self.assertEqual(f["post_round_rr_status"], "ok")
        self.assertEqual(f["structure_quality"], "strong")
        self.assertAlmostEqual(f["risk_reward_ratio"], 2.222, places=3)

    def test_breakout_happy_path_uses_atr_fallback_tp(self):
        r = pe.support_atr_engine({"close": 100.0, "indicators": _ind(90.0, 100.0, 2.0)}, "进攻", "breakout")
        f = r["action_fields"]
        self.assertTrue(r["executable"])
        self.assertEqual(f["price_sub_mode"], "breakout")
        self.assertEqual(f["order_type"], "breakout_stop_limit")
        self.assertEqual(f["stop_clear_price"], 99.0)            # res 100 - 0.5*ATR(2) = failure line
        self.assertEqual(f["take_profit_reduce_price"], 106.0)   # ATR fallback: 100 + 3.0*2 (§13 #20)
        self.assertEqual(f["breakout_entry_price"], 100.0)
        self.assertIsNone(f["pullback_entry_price"])
        self.assertEqual(f["valid_entry_high"], 101.0)           # chase cap: 100 + 0.5*2
        self.assertEqual(f["limit_order_price"], 101.0)
        self.assertEqual(r["trace"]["t1_basis"], "breakout_atr_fallback")

    def test_rr_gate_blocks_when_reward_too_small(self):
        r = pe.support_atr_engine({"close": 100.0, "indicators": _ind(99.0, 100.5, 2.0)}, "震荡", "pullback")
        f = r["action_fields"]
        self.assertFalse(r["executable"])
        self.assertEqual(f["min_rr_gate_status"], "fail_below_floor")
        self.assertIsNone(f["stop_clear_price"])                 # no fabricated levels on observe

    def test_post_round_structure_break_is_reverse_failure_control(self):
        # raw RR is huge, but a sub-cent stop rounds UP to the entry -> structure collapses post-round.
        r = pe.support_atr_engine({"close": 100.0, "indicators": _ind(99.996, 100.10, 0.002)}, "震荡", "pullback")
        f = r["action_fields"]
        self.assertFalse(r["executable"])
        self.assertEqual(f["post_round_rr_status"], "broke_after_round")
        self.assertIsNone(f["stop_clear_price"])

    def test_missing_inputs_degrade_to_observe_no_fabrication(self):
        r = pe.support_atr_engine({"close": None, "bars": []}, "震荡", "pullback")
        f = r["action_fields"]
        self.assertFalse(r["executable"])
        for k in ("stop_clear_price", "take_profit_reduce_price", "take_profit_exit_price",
                  "valid_entry_low", "valid_entry_high", "pullback_entry_price", "breakout_entry_price"):
            self.assertIsNone(f[k], f"{k} must not be fabricated when inputs are missing")

    def test_missing_support_for_pullback_observes(self):
        r = pe.support_atr_engine({"close": 100.0, "indicators": _ind(None, 110.0, 2.0)}, "震荡", "pullback")
        self.assertFalse(r["executable"])
        self.assertIsNone(r["action_fields"]["stop_clear_price"])

    def test_pullback_support_at_or_above_close_observes_not_rescued(self):
        # support 101 is ABOVE close 100 -> not a valid low-absorb structure; the engine must observe,
        # not collapse the contradictory (valid_low_raw > valid_high_raw) band into a current-price plan.
        r = pe.support_atr_engine({"close": 100.0, "indicators": _ind(101.0, 110.0, 2.0)}, "震荡", "pullback")
        f = r["action_fields"]
        self.assertFalse(r["executable"])
        self.assertIsNone(f["stop_clear_price"])
        self.assertIsNone(f["valid_entry_low"])
        self.assertIsNone(f["valid_entry_high"])

    def test_unknown_submode_defaults_pullback(self):
        r = pe.support_atr_engine({"close": 100.0, "indicators": _ind(98.0, 110.0, 2.0)}, "震荡", "bogus")
        self.assertEqual(r["action_fields"]["price_sub_mode"], "pullback")


# ── holding_exit_engine: levels / breach / missing / event ref ────────────────────────────
class HoldingExitEngineTests(unittest.TestCase):
    def test_holding_levels_happy_path(self):
        r = pe.holding_exit_engine({"close": 109.0, "indicators": _ind(95.0, 110.0, 2.0)}, "震荡")
        f = r["action_fields"]
        self.assertTrue(r["executable"])
        self.assertEqual(f["price_engine_used"], "holding_exit_engine")
        self.assertIsNone(f["price_sub_mode"])
        self.assertEqual(f["stop_clear_price"], 107.5)           # 110 - 1.25*2 (de-spiked recent high)
        self.assertEqual(f["take_profit_reduce_price"], 110.0)
        self.assertEqual(f["take_profit_exit_price"], 112.5)
        self.assertFalse(r["trace"]["breached"])

    def test_holding_breach_no_fabricated_tp(self):
        r = pe.holding_exit_engine({"close": 105.0, "indicators": _ind(95.0, 110.0, 2.0)}, "震荡")
        f = r["action_fields"]
        self.assertTrue(r["executable"])
        self.assertTrue(r["trace"]["breached"])                  # close 105 <= stop 107.5
        self.assertEqual(f["stop_clear_price"], 107.5)
        self.assertIsNone(f["take_profit_reduce_price"])
        self.assertIsNone(f["take_profit_exit_price"])

    def test_holding_tp_round_failure_is_not_a_breach(self):
        # close 109 is well above stop 106.51 (NOT breached), but res 109.001 rounds TP into an invalid
        # order. The engine must NOT fabricate a breach: stop stays, TP is None, breached=False.
        r = pe.holding_exit_engine({"close": 109.0, "indicators": _ind(95.0, 109.001, 2.0)}, "震荡")
        f = r["action_fields"]
        self.assertTrue(r["executable"])
        self.assertFalse(r["trace"]["breached"])                 # close 109 > stop 106.51 -> not breached
        self.assertEqual(f["stop_clear_price"], 106.51)
        self.assertIsNone(f["take_profit_reduce_price"])
        self.assertIsNone(f["take_profit_exit_price"])
        self.assertEqual(f["post_round_rr_status"], "tp_not_computable")

    def test_holding_missing_structure_observes(self):
        r = pe.holding_exit_engine({"close": 100.0, "indicators": _ind(95.0, None, None)}, "震荡")
        self.assertFalse(r["executable"])
        self.assertIsNone(r["action_fields"]["stop_clear_price"])

    def test_holding_event_reference_passthrough_ticked(self):
        r = pe.holding_exit_engine({"close": 109.0, "indicators": _ind(95.0, 110.0, 2.0)}, "震荡",
                                   event_reference_price=95.004)
        self.assertEqual(r["action_fields"]["event_clear_reference_price"], 95.0)


# ── conformance to the frozen action_table_contract (schema-first binding) ────────────────
class ContractConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads(_CONTRACT.read_text(encoding="utf-8"))
        cls.core = set(data["core_columns"])
        cls.enums = data["design_locked_enums"]

    def _samples(self):
        return [
            pe.support_atr_engine({"close": 100.0, "indicators": _ind(98.0, 110.0, 2.0)}, "震荡", "pullback"),
            pe.support_atr_engine({"close": 100.0, "indicators": _ind(90.0, 100.0, 2.0)}, "进攻", "breakout"),
            pe.support_atr_engine({"close": 100.0, "indicators": _ind(99.0, 100.5, 2.0)}, "震荡", "pullback"),  # observe
            pe.holding_exit_engine({"close": 109.0, "indicators": _ind(95.0, 110.0, 2.0)}, "震荡"),
            pe.holding_exit_engine({"close": 105.0, "indicators": _ind(95.0, 110.0, 2.0)}, "震荡"),  # breach
        ]

    def test_every_emitted_field_is_a_frozen_column(self):
        for r in self._samples():
            extra = set(r["action_fields"]) - self.core
            self.assertEqual(extra, set(), f"engine emitted non-contract columns: {extra}")

    def test_vocab_fields_match_locked_enums(self):
        for field in ("price_engine_used", "price_sub_mode", "order_type", "order_expiry"):
            for r in self._samples():
                v = r["action_fields"].get(field)
                if v is not None:
                    self.assertIn(v, self.enums[field], f"{field}={v!r} not in locked enum")

    def test_engine_used_value_pinned(self):
        for r in self._samples():
            self.assertIn(r["price_engine_used"], pe.PRICE_ENGINES)


if __name__ == "__main__":
    unittest.main()
