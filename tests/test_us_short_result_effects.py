# -*- coding: utf-8 -*-
"""Second-cut result-effects tests: factors must have one sourced output effect, not just a middle-stage flag."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_result_effects import (  # noqa: E402
    ResultEffectsError,
    _evidence_ref,
    apply_result_effects,
    finalize_result_effects,
    validate_result_effects,
)

_AS_OF = "20260615"


def _guard(state="normal"):
    return {"state": state, "evidence_ref": {"kind": "source_id", "value": "test:paper-track", "as_of": _AS_OF}}


def _cooldown(status="none"):
    return {"status": status, "cooldown_until": None, "reentry_allowed_reason": None,
            "evidence_ref": {"kind": "source_id", "value": "test:cooldown", "as_of": _AS_OF}}


def _decision(row):
    return {"regime": {"market_risk_regime": "进攻", "position_cap": 1.0}, "rows": [row]}


class ResultEffectsTests(unittest.TestCase):
    def test_evidence_ref_allows_only_declared_optional_as_of(self):
        self.assertEqual(_evidence_ref({"kind": "source_id", "value": "x"}, as_of=_AS_OF, where="test")["as_of"], _AS_OF)
        self.assertEqual(_evidence_ref({"kind": "source_id", "value": "x", "as_of": _AS_OF}, as_of=_AS_OF, where="test")["as_of"], _AS_OF)
        with self.assertRaises(ResultEffectsError):
            _evidence_ref({"kind": "source_id", "value": "x", "rogue": True}, as_of=_AS_OF, where="test")

    def test_in_window_earnings_overrides_new_build_and_keeps_claim_evidence(self):
        out = apply_result_effects(
            _decision({"ticker": "AAA", "final_action": "建仓", "observe_reason_type": None,
                       "forward_event": {"event_type": "earnings", "days_to_event": 3.0,
                                         "in_window": True, "direction": "reduce_or_observe",
                                         "evidence_ref": {"kind": "SEC filing", "value": "sec:AAA:10-Q", "as_of": _AS_OF}}}),
            portfolio_guard_result=_guard(), cooldown_by_ticker={"AAA": _cooldown()}, as_of=_AS_OF)
        row = out["rows"][0]
        self.assertEqual((row["final_action"], row["observe_reason_type"], row["action_confidence"]),
                         ("观察", "event_window", 0.0))
        self.assertIn("upcoming_event:earnings", row["risk_tags"])
        self.assertEqual(row["result_effects"]["evidence_refs"]["upcoming_event:earnings"],
                         {"kind": "SEC filing", "value": "sec:AAA:10-Q", "as_of": _AS_OF})
        validate_result_effects(row, as_of=_AS_OF)

    def test_caution_uses_one_harshest_size_discount_and_confidence_cap(self):
        out = apply_result_effects(
            _decision({"ticker": "AAA", "final_action": "建仓", "observe_reason_type": None,
                       "event_data_gap": {"status": "reduce_caution"}}),
            portfolio_guard_result=_guard("caution"), cooldown_by_ticker={"AAA": _cooldown()}, as_of=_AS_OF)
        row = out["rows"][0]
        # Two 0.5 risks are not multiplied to 0.25. The reducer selects the single harshest 0.5 effect.
        self.assertEqual(row["result_effects"]["selected_size_multiplier"], 0.5)
        self.assertEqual(row["action_confidence"], 0.6)
        self.assertIn("portfolio_guard:caution", row["risk_tags"])
        validate_result_effects(row, as_of=_AS_OF)

    def test_final_action_change_reprojects_confidence_without_recomputing_evidence(self):
        out = apply_result_effects(
            _decision({"ticker": "AAA", "final_action": "建仓", "observe_reason_type": None}),
            portfolio_guard_result=_guard("caution"), cooldown_by_ticker={"AAA": _cooldown()}, as_of=_AS_OF)
        row = finalize_result_effects({**out, "rows": [{**out["rows"][0], "final_action": "观察",
                                                           "observe_reason_type": "capacity_or_budget_deferred"}]})["rows"][0]
        self.assertEqual(row["action_confidence"], 0.0)
        self.assertEqual(row["result_effects"]["evidence_refs"]["portfolio_guard"]["value"], "test:paper-track")
        validate_result_effects(row, as_of=_AS_OF)

    def test_projection_tampering_fails_closed(self):
        out = apply_result_effects(
            _decision({"ticker": "AAA", "final_action": "建仓", "observe_reason_type": None}),
            portfolio_guard_result=_guard(), cooldown_by_ticker={"AAA": _cooldown()}, as_of=_AS_OF)
        row = {**out["rows"][0], "action_confidence": 0.25}
        with self.assertRaises(ResultEffectsError):
            validate_result_effects(row, as_of=_AS_OF)
