# -*- coding: utf-8 -*-
"""Second-cut private symbol-cooldown state: filled failures persist; unfilled attempts never enter it."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_symbol_cooldown_state import (  # noqa: E402
    SymbolCooldownStateError,
    _validate_evidence_ref,
    build_next_symbol_cooldown_state,
    load_symbol_cooldown_state,
    resolve_symbol_cooldowns,
)
from runners.us_short_account_state_from_manual_tables import _build_symbol_cooldown_reconciliation  # noqa: E402


def _reconciliation(events, as_of="20260615"):
    return {"schema_name": "us_short_symbol_cooldown_reconciliation", "schema_version": "1.0.0",
            "as_of": as_of, "events": events}


class SymbolCooldownStateTests(unittest.TestCase):
    def test_evidence_ref_allows_only_declared_optional_as_of(self):
        _validate_evidence_ref({"kind": "source_id", "value": "x"}, "test")
        _validate_evidence_ref({"kind": "source_id", "value": "x", "as_of": "20260615"}, "test")
        with self.assertRaises(SymbolCooldownStateError):
            _validate_evidence_ref({"kind": "source_id", "value": "x", "rogue": True}, "test")

    def test_unfilled_breakout_never_creates_a_cooldown_reconciliation_event(self):
        reconciliation = _build_symbol_cooldown_reconciliation(
            [{"ticker": "AAA", "decision_date": "20260615", "suggested_action": "建仓",
              "executed": False, "failure_trigger": None}], "20260615")
        self.assertEqual(reconciliation["events"], [])

    def test_filled_stop_enters_and_persists_through_expiry(self):
        prior = load_symbol_cooldown_state(Path("does-not-exist.json"), decision_date="20260615")
        state = build_next_symbol_cooldown_state(
            prior, _reconciliation([{"ticker": "AAA", "trigger": "filled_then_stop_loss", "triggered_at": "20260601",
                                      "source_reconciliation_ref": "manual:trade-1"}]), decision_date="20260615")
        out = resolve_symbol_cooldowns(state, [{"ticker": "AAA"}], decision_date="20260615")["AAA"]
        self.assertEqual((out["status"], out["cooldown_until"]), ("in_cooldown", "20260621"))

    def test_expired_cooldown_needs_both_new_evidenced_conditions(self):
        prior = load_symbol_cooldown_state(Path("does-not-exist.json"), decision_date="20260615")
        state = build_next_symbol_cooldown_state(
            prior, _reconciliation([{"ticker": "AAA", "trigger": "filled_then_breakout_failure", "triggered_at": "20260601",
                                      "source_reconciliation_ref": "manual:trade-2"}]), decision_date="20260615")
        evidence = {"kind": "source_id", "value": "test:new-fact", "as_of": "20260622"}
        row = {"ticker": "AAA", "reentry_evidence": {
            "new_catalyst": {"present": True, "evidence_ref": evidence},
            "new_structure": {"present": True, "evidence_ref": evidence},
        }}
        out = resolve_symbol_cooldowns(state, [row], decision_date="20260622")["AAA"]
        self.assertEqual(out["status"], "reentry_allowed")
        self.assertEqual(out["reentry_allowed_reason"], "new_catalyst+new_structure+cooldown_expired")
