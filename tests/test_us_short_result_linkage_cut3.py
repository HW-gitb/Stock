# -*- coding: utf-8 -*-
"""Focused red/green tests for US-short result-linkage Cut3."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_macro_cluster import apply_macro_cluster_two_pass, render_macro_cluster_banner  # noqa: E402
from engine.us_short_result_effects import apply_result_effects, validate_result_effects  # noqa: E402
from engine.us_short_selection_exclusions import (  # noqa: E402
    SelectionExclusionError,
    build_hot_excluded_audit,
    build_selection_exclusion_data,
    pass1_category,
    pass2_category,
)
from engine.us_short_theme_result_linkage import (  # noqa: E402
    apply_theme_lifecycle_effects,
    bind_theme_contexts,
)

AS_OF = "20260615"


def _theme(*, lifecycle="confirmed_active", cluster="ai_complex"):
    return {
        "theme_id": "industry:technology",
        "theme_source": "industry_heat_v1",
        "theme_lifecycle_state": lifecycle,
        "theme_leader_rs": 88.0,
        "membership_origin": "automatic_discovery",
        "market_confirmed": True,
        "individual_theme_gate_passed": True,
        "overextension_state": "none",
        "macro_cluster": cluster,
    }


def _selection(theme):
    return {
        "admitted": ["AAA"],
        "holdings": [],
        "selection_details": [{
            "ticker": "AAA", "selection_rank": 1, "selection_bucket": "core_top",
            "core_score": 75.0, "theme_momentum_score": 80.0,
            "theme_selection": theme,
        }],
        "theme_contract_digest": "a" * 64,
    }


def _guard():
    return {"state": "normal", "evidence_ref": {
        "kind": "source_id", "value": "test:paper", "as_of": AS_OF}}


def _cooldown(ticker):
    return {ticker: {"status": "none", "cooldown_until": None, "reentry_allowed_reason": None,
                     "evidence_ref": {"kind": "source_id", "value": "test:cooldown:" + ticker,
                                      "as_of": AS_OF}}}


def _selection_provenance():
    return {
        "as_of": AS_OF, "observed_at": "2026-06-14T10:00:00",
        "price_basis_date": None, "session": None, "adjustment": None, "row_count": 1,
        "source_refs": [{"role": "theme_selection_contract", "path": "state/us_short/test_theme.json"}],
    }


def _build_row(ticker, *, cluster="ai_complex"):
    return {
        "ticker": ticker, "row_source": "top15_candidate", "row_context": "candidate",
        "final_action": "建仓", "observe_reason_type": None,
        "price": {"executable": True, "trace": {},
                  "action_fields": {"valid_entry_high": 100.0, "stop_clear_price": 90.0}},
        "theme_context": {**_theme(cluster=cluster),
                          "evidence_ref": {"kind": "source_id",
                                           "value": "theme:" + ticker, "as_of": AS_OF}},
    }


class ThemeBindingTests(unittest.TestCase):
    def test_candidate_theme_is_carried_verbatim_with_digest_bound_evidence(self):
        theme = _theme()
        rows, complete = bind_theme_contexts(
            _selection(theme),
            [{"ticker": "AAA", "row_source": "top15_candidate", "selection_theme": theme}],
            account_state={"positions": []}, decision_date=AS_OF,
            selection_input_provenance=_selection_provenance(),
        )
        self.assertTrue(complete)
        self.assertEqual({k: rows[0]["theme_context"][k] for k in theme}, theme)
        self.assertIn("a" * 64, rows[0]["theme_context"]["evidence_ref"]["value"])
        self.assertIn("run_provenance:sha256:", rows[0]["theme_context"]["evidence_ref"]["value"])

    def test_same_theme_identity_conflict_between_candidate_and_holding_fails(self):
        selection = _selection(_theme())
        selection["holdings"] = [{"ticker": "AAA"}]
        account = {"positions": [{"ticker": "AAA", "shares": 3}],
                   "holding_theme_reconciliation": {
                       "schema_name": "us_short_holding_theme_reconciliation", "schema_version": "1.0.0",
                       "as_of": AS_OF, "positions": [{
                           "ticker": "AAA", "theme_id": "industry:technology",
                           "theme_source": "industry_heat_v1",
                           "theme_lifecycle_state": "confirmed_active",
                           "macro_cluster": "rates_sensitive",
                           "evidence_ref": {"kind": "source_id", "value": "manual:AAA", "as_of": AS_OF},
                       }]}}
        with self.assertRaises(ValueError):
            bind_theme_contexts(selection, [{"ticker": "AAA", "row_source": "holding_in_top15"}],
                                account_state=account, decision_date=AS_OF,
                                selection_input_provenance=_selection_provenance())


class LifecycleEffectTests(unittest.TestCase):
    def _effected(self, row):
        return apply_result_effects(
            {"regime": {"market_risk_regime": "进攻", "position_cap": 1.0}, "rows": [row]},
            portfolio_guard_result=_guard(), cooldown_by_ticker=_cooldown(row["ticker"]), as_of=AS_OF)

    def test_decayed_candidate_becomes_observe_not_hard_veto(self):
        effected = self._effected(_build_row("AAA"))
        effected["rows"][0]["theme_context"]["theme_lifecycle_state"] = "decayed"
        row = apply_theme_lifecycle_effects(effected, as_of=AS_OF)["rows"][0]
        self.assertEqual((row["final_action"], row["observe_reason_type"]),
                         ("观察", "signal_not_ready"))
        self.assertIn("theme_decay:decayed", row["risk_tags"])
        self.assertNotEqual(row.get("veto", {}).get("veto_tier"), "entry_hard_veto")
        validate_result_effects(row, as_of=AS_OF)

    def test_cooling_holding_lowers_confidence_tags_and_never_clears(self):
        row = _build_row("HLD")
        row.update({"row_source": "holding_account_only", "row_context": "holding",
                    "final_action": "持有"})
        row["theme_context"]["theme_lifecycle_state"] = "cooling"
        out = apply_theme_lifecycle_effects(self._effected(row), as_of=AS_OF)["rows"][0]
        self.assertEqual(out["final_action"], "持有")
        self.assertLess(out["action_confidence"], 1.0)
        self.assertIn("theme_decay:cooling", out["risk_tags"])
        self.assertIn("theme_lifecycle_section9_reeval", out["invalid_conditions"])
        validate_result_effects(out, as_of=AS_OF)


class MacroTwoPassTests(unittest.TestCase):
    def _effected(self, rows):
        return apply_result_effects(
            {"regime": {"market_risk_regime": "进攻", "position_cap": 1.0}, "rows": rows},
            portfolio_guard_result=_guard(),
            cooldown_by_ticker={t: _cooldown(t)[t] for t in (row["ticker"] for row in rows)},
            as_of=AS_OF,
        )

    def test_high_cluster_reduces_final_shares_and_records_four_fields(self):
        effected = self._effected([_build_row("AAA"), _build_row("BBB")])
        sizing = {"short_bucket_dollars": 100000.0, "per_ticker": {
            "AAA": {"discount_mults": [1.0], "liquidity_cap_shares": 100000},
            "BBB": {"discount_mults": [1.0], "liquidity_cap_shares": 100000},
        }}
        out = apply_macro_cluster_two_pass(
            effected, sizing_context=sizing,
            existing_positions=[{"ticker": "HLD", "shares": 500, "mark_price": 100.0,
                                 "macro_cluster": "ai_complex"}],
            as_of=AS_OF)
        for row in out["rows"]:
            self.assertEqual(row["macro_cluster"], "ai_complex")
            self.assertEqual(row["macro_cluster_warning_level"], "high")
            self.assertGreaterEqual(row["macro_cluster_exposure_frac"], 0.40)
            self.assertGreater(row["macro_cluster_size_adjustment"], 0)
            self.assertIn("macro_cluster:high", row["risk_tags"])
        self.assertIn("建仓候选2个,暴露", render_macro_cluster_banner(out["rows"]))

    def test_small_single_position_uses_bucket_denominator_not_invested_only(self):
        effected = self._effected([_build_row("AAA")])
        sizing = {"short_bucket_dollars": 100000.0, "per_ticker": {
            "AAA": {"discount_mults": [1.0], "liquidity_cap_shares": 100000}}}
        row = apply_macro_cluster_two_pass(
            effected, sizing_context=sizing, existing_positions=[], as_of=AS_OF)["rows"][0]
        self.assertLess(row["macro_cluster_exposure_frac"], 0.25)
        self.assertEqual(row["macro_cluster_warning_level"], "none")
        self.assertEqual(row["macro_cluster_size_adjustment"], 0)

    def test_macro_discount_joins_harshest_stack_without_compounding(self):
        effected = self._effected([_build_row("AAA")])
        original = copy.deepcopy(effected)
        effects = effected["rows"][0]["result_effects"]
        effects["size_reduction_candidates"].append({"source": "existing", "multiplier": 0.4})
        effects["evidence_refs"]["size:existing"] = {
            "kind": "source_id", "value": "existing", "as_of": AS_OF}
        effects["selected_size_multiplier"] = 0.4
        sizing = {"short_bucket_dollars": 100000.0, "per_ticker": {
            "AAA": {"discount_mults": [1.0], "liquidity_cap_shares": 100000}}}
        out = apply_macro_cluster_two_pass(
            effected, sizing_context=sizing,
            existing_positions=[{"ticker": "HLD", "shares": 500, "mark_price": 100.0,
                                 "macro_cluster": "ai_complex"}],
            as_of=AS_OF)
        self.assertEqual(out["rows"][0]["result_effects"]["selected_size_multiplier"], 0.4)
        self.assertEqual(out["rows"][0]["macro_cluster_size_adjustment"], 0)
        self.assertEqual(original["rows"][0]["result_effects"]["selected_size_multiplier"], 1.0)


class HotExcludedLinkageTests(unittest.TestCase):
    def test_real_exclusions_join_same_digest_without_rescue_and_missing_heat_is_visible(self):
        records = [
            {"stage": "pass1_eligibility", "ticker": "HOT",
             "category": pass1_category(["adv_usd_below_floor"]),
             "reasons": ["adv_usd_below_floor"]},
            {"stage": "pass2_audit_gate", "ticker": "KILL",
             "category": pass2_category(["SEC增发 hard veto"]),
             "reasons": ["SEC增发 hard veto"]},
            {"stage": "pass1_eligibility", "ticker": "MISS",
             "category": pass1_category(["missing_price"]),
             "reasons": ["missing_price"]},
        ]
        before = copy.deepcopy(records)
        audit = build_hot_excluded_audit(
            records,
            heat_audit={"heat_threshold": 90.0, "per_ticker": {"HOT": 95.0, "KILL": 99.0}},
            as_of=AS_OF, source_digest="b" * 64,
        )
        selection = {"decision_date": AS_OF, "admitted": ["SAFE"], "theme_contract_digest": "b" * 64,
                     "exclusion_records": records, "hot_excluded_audit": audit}
        result = build_selection_exclusion_data(selection)["hot_excluded"]
        self.assertEqual(result["public_heat_count"], 1)
        self.assertEqual(result["unevaluable_count"], 1)
        self.assertEqual(selection["admitted"], ["SAFE"])
        self.assertEqual(records, before)

    def test_price_market_cap_is_safety_and_cross_run_digest_is_rejected(self):
        records = [
            {"stage": "pass1_eligibility", "ticker": "AAPL", "category": "价格市值",
             "reasons": ["price_below_floor"]},
        ]
        digest = "a" * 64
        audit = build_hot_excluded_audit(
            records, heat_audit={"heat_threshold": 80.0, "per_ticker": {"AAPL": 95.0}},
            as_of=AS_OF, source_digest=digest)
        selection = {"decision_date": AS_OF, "exclusion_records": records,
                     "theme_contract_digest": digest, "hot_excluded_audit": audit}
        self.assertEqual(
            build_selection_exclusion_data(selection)["hot_excluded"]["public_heat_count"], 1)
        selection["hot_excluded_audit"] = {**audit, "source_digest": "b" * 64}
        with self.assertRaises(SelectionExclusionError):
            build_selection_exclusion_data(selection)


if __name__ == "__main__":
    unittest.main()
