# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_action_table_contract (US-short batch 1, design §11.3).

The contract freezes the action_table column set/order + the column vocabularies the design pins
verbatim. Tests assert (a) the const-pins, (b) the preset stays byte-faithful to design §11.3
(single-source guard), (c) cross-schema equalities draft-07 can't express
(final_action == converter TRADE_ACTIONS; theme_lifecycle_state == lifecycle-governance states),
and (d) a full battery of negative schema cases (drop/reorder/extend/vocab-drift).
"""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runners.us_short_account_state_from_manual_tables as conv  # noqa: E402

SCHEMA = ROOT / "schemas" / "us_short_action_table_contract.schema.json"
PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
LIFECYCLE_PRESET = ROOT / "presets" / "us_short_theme_lifecycle_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

EXPECTED_ENUMS = {
    "row_source": ["top15_candidate", "holding_in_top15", "holding_pass2_only", "holding_account_only"],
    "final_action": ["建仓", "加仓", "减仓", "清仓-止损", "清仓-止盈", "清仓-事件", "持有", "观察", "否决/避开"],
    "observe_reason_type": ["signal_not_ready", "price_not_executable", "cash_or_account_missing",
                            "risk_cooldown", "data_restricted", "event_window", "cost_inefficient_min_size",
                            "capacity_or_budget_deferred"],
    "order_type": ["pullback_limit", "breakout_stop_limit"],
    "order_expiry": ["first_regular_session_only"],
    "price_engine_used": ["support_atr_engine", "holding_exit_engine"],
    "price_sub_mode": ["pullback", "breakout"],
    "overextension_state": ["none", "warning", "chasing_extreme"],
    "portfolio_guard_status": ["normal", "caution", "cooldown", "recovery"],
    "live_permission_status": ["paper_or_minimal_only", "not_full_size_eligible", "full_size_eligible"],
    "coverage_status": ["full", "partial", "restricted", "blocked"],
    "theme_lifecycle_state": ["provisional_active", "confirmed_active", "cooling", "decayed", "retired"],
    "theme_source": ["industry_heat_v1", "gics_established", "provisional_discovered"],
    "macro_cluster_warning_level": ["none", "elevated", "high"],              # §8 l228 (labels locked; frac thresholds = §13 #31)
}


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_section_11_3_columns():
    """Extract the §11.3 action_table column list straight from the design doc (single source of truth)."""
    text = DESIGN.read_text(encoding="utf-8")
    idx = text.index("### 11.3")
    # first backtick-delimited span after the header that contains the comma-separated column list
    for span in re.findall(r"`([^`]+)`", text[idx:]):
        if "," in span and span.strip().startswith("ticker"):
            return [c.strip() for c in span.split(",")]
    raise AssertionError("could not locate §11.3 column list in design doc")


class UsShortActionTableContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)
        cls.cols = cls.preset["core_columns"]
        cls.enums = cls.preset["design_locked_enums"]

    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_core_columns_count_and_unique(self):
        self.assertEqual(len(self.cols), 55)
        self.assertEqual(len(self.cols), len(set(self.cols)), "duplicate column id")

    def test_core_columns_byte_faithful_to_design_11_3(self):
        # single-source guard (checklist §B2): preset column set+order == design §11.3 verbatim
        self.assertEqual(self.cols, _design_section_11_3_columns())

    def test_design_locked_enum_keys_are_real_columns(self):
        # every enum-pinned key must be an actual core column (no enum for a non-existent column)
        for key in self.enums:
            self.assertIn(key, self.cols, key)

    def test_each_design_locked_enum_exact(self):
        self.assertEqual(set(self.enums), set(EXPECTED_ENUMS))   # exactly these 14 columns pinned
        for key, vocab in EXPECTED_ENUMS.items():
            self.assertEqual(self.enums[key], vocab, key)

    def test_final_action_matches_converter_trade_actions(self):
        # cross-schema: action_table.final_action vocab == the 9 §9/§6.1 trade actions pinned in the converter
        self.assertEqual(set(self.enums["final_action"]), set(conv.TRADE_ACTIONS))
        self.assertEqual(len(self.enums["final_action"]), len(conv.TRADE_ACTIONS))   # no dup masking a drop

    def test_theme_lifecycle_state_matches_lifecycle_governance(self):
        # cross-schema: action_table.theme_lifecycle_state vocab == the lifecycle-governance state set
        lifecycle_states = _load(LIFECYCLE_PRESET)["states"]
        self.assertEqual(self.enums["theme_lifecycle_state"], lifecycle_states)

    def test_set_notation_vocabs_fully_covered(self):
        # recurrence guard: EVERY action_table column the design declares via `field ∈ {…}` MUST be
        # pinned here with the exact set. Auto-discovers the convention so a future ∈-vocab can't be missed.
        text = DESIGN.read_text(encoding="utf-8")
        found = 0
        for m in re.finditer(r"`?([a-z][a-z0-9_]+)`?\s*∈\s*\{([^}]+)\}", text):
            field, body = m.group(1), m.group(2)
            if field in self.cols:
                vocab = [v.strip().strip("`") for v in body.split(",")]
                self.assertIn(field, self.enums, f"{field} has a design ∈-vocab but is not pinned")
                self.assertEqual(self.enums[field], vocab, field)
                found += 1
        self.assertGreaterEqual(found, 4)   # theme_lifecycle_state / overextension_state / price_sub_mode / portfolio_guard_status

    def test_parenthetical_vocab_values_are_in_design(self):
        # the two columns declared via the `field`（v / v）convention were the prior miss — assert each
        # pinned value actually occurs in the design (single-source: catches invented/mis-transcribed vocab)
        text = DESIGN.read_text(encoding="utf-8")
        for field in ("theme_source", "macro_cluster_warning_level"):
            self.assertIn(field, text)
            for v in self.enums[field]:
                self.assertIn(v, text, f"{field} value {v} not found in design (invented?)")

    def test_price_engine_used_is_v1_real_engines_only(self):
        # candidate engines (ema_trailing / earnings_gap, §13 #6) are NOT emitted in v1
        self.assertNotIn("ema_trailing_engine", self.enums["price_engine_used"])
        self.assertNotIn("earnings_gap_engine", self.enums["price_engine_used"])

    def test_extension_policy_pinned(self):
        ep = self.preset["extension_policy"]
        self.assertTrue(ep["candidate_fields_allowed"])
        self.assertTrue(ep["appended_after_core"])
        self.assertTrue(ep["must_register_in_field_registry"])
        self.assertTrue(ep["must_not_shadow_core_columns"])

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_dropped_core_column(self):
        self._reject(lambda d: d["core_columns"].remove("final_action"))

    def test_schema_rejects_extra_core_column(self):
        self._reject(lambda d: d["core_columns"].append("theme_heat_score"))

    def test_schema_rejects_reordered_core_columns(self):
        def swap(d):
            c = d["core_columns"]
            c[1], c[2] = c[2], c[1]
        self._reject(swap)   # const array is order-sensitive

    def test_schema_rejects_final_action_vocab_drift(self):
        self._reject(lambda d: d["design_locked_enums"]["final_action"].__setitem__(8, "否决"))

    def test_schema_rejects_order_expiry_multiday_added(self):
        self._reject(lambda d: d["design_locked_enums"]["order_expiry"].append("multi_day_gtc"))

    def test_schema_rejects_overextension_extra_state(self):
        self._reject(lambda d: d["design_locked_enums"]["overextension_state"].append("surging"))

    def test_schema_rejects_coverage_status_drift(self):
        self._reject(lambda d: d["design_locked_enums"]["coverage_status"].__setitem__(0, "complete"))

    def test_schema_rejects_theme_source_drift(self):
        self._reject(lambda d: d["design_locked_enums"]["theme_source"].__setitem__(0, "gics_official"))

    def test_schema_rejects_macro_cluster_warning_level_drift(self):
        self._reject(lambda d: d["design_locked_enums"]["macro_cluster_warning_level"].append("critical"))

    def test_schema_rejects_dropped_design_locked_enum(self):
        # dropping a now-required enum (e.g. the newly-pinned ones) must fail — required keys = 14
        self._reject(lambda d: d["design_locked_enums"].pop("theme_source"))

    def test_schema_rejects_price_engine_candidate_leak(self):
        self._reject(lambda d: d["design_locked_enums"]["price_engine_used"].append("ema_trailing_engine"))

    def test_schema_rejects_unknown_enum_key(self):
        self._reject(lambda d: d["design_locked_enums"].__setitem__("selection_bucket", ["a", "b"]))

    def test_schema_rejects_extension_policy_shadow_allowed(self):
        self._reject(lambda d: d["extension_policy"].__setitem__("must_not_shadow_core_columns", False))

    def test_schema_rejects_extension_policy_unregistered(self):
        self._reject(lambda d: d["extension_policy"].__setitem__("must_register_in_field_registry", False))


if __name__ == "__main__":
    unittest.main()
