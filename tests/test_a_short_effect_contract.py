"""Regression guards for the closed-world A-short M6.7 effect contract."""
from __future__ import annotations

import copy
from collections import Counter
import ast
import hashlib
import json
import sys
import tempfile
import unittest
import jsonschema
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_effect_contract import (  # noqa: E402
    load_contract, static_contract_error, static_inventory, leaf_effects,
    build_effect_contract_ledger, validate_effect_contract_ledger, load_legacy_effect_contract,
)
from engine import a_short_effect_contract as effect_contract_module  # noqa: E402
from runners.a_short_m67_render import render_weekly_markdown  # noqa: E402
from engine.a_short_industry_theme import classify_industry_trend  # noqa: E402
from engine.egs_industry_heat import load_governance  # noqa: E402
from runners.a_short_phase5_engine import build_m67_report  # noqa: E402
from runners.a_short_weekly_pipeline import (  # noqa: E402
    build_weekly_report, normalize_candidate, validate_published_weekly_bundle,
    validate_weekly_report,
)
from tests.test_a_short_weekly_pipeline import (  # noqa: E402
    AS_OF, GEN, _egs_candidate, _feed, _normalized, _overlay_row, _series,
)


#: The 225 analysis_input leaves that nothing mechanical classified on the day
#: the pending-audit gate landed (2026-08-07).  Frozen here, in a different
#: file from the contract, so the live baseline can be checked against an
#: anchor a contract edit does not travel with.  Entries may leave this list
#: (a leaf gets wired or deleted); nothing may ever be added.
_PENDING_AUDIT_LANDING_SNAPSHOT = (
    "account_context.mode",
    "account_context.positions[].current_price",
    "account_context.positions[].entry_date",
    "account_context.positions[].entry_price",
    "account_context.positions[].floating_pnl_pct",
    "account_context.positions[].name",
    "account_context.positions[].shares",
    "account_context.positions[].stop_loss",
    "account_context.positions[].take_profit_1",
    "account_context.positions[].take_profit_2",
    "account_context.positions[].ts_code",
    "candidates[].analysis_role",
    "candidates[].board",
    "candidates[].capital_flow.moneyflow.big_order_ratio",
    "candidates[].catalyst.concept_strength_score",
    "candidates[].catalyst.concepts[]",
    "candidates[].catalyst.policy_news[].published_at",
    "candidates[].catalyst.policy_news[].source",
    "candidates[].catalyst.policy_news[].title",
    "candidates[].catalyst.policy_news[].url",
    "candidates[].catalyst.theme_taxonomy.automatic_promotion",
    "candidates[].catalyst.theme_taxonomy.canonical_themes[]",
    "candidates[].catalyst.theme_taxonomy.comparison_metrics.breadth_pass",
    "candidates[].catalyst.theme_taxonomy.comparison_metrics.comparison_status",
    "candidates[].catalyst.theme_taxonomy.comparison_metrics.fit_pass",
    "candidates[].catalyst.theme_taxonomy.comparison_metrics.fit_score",
    "candidates[].catalyst.theme_taxonomy.comparison_metrics.persistence_mult",
    "candidates[].catalyst.theme_taxonomy.comparison_status",
    "candidates[].catalyst.theme_taxonomy.l3_provenance.coverage_complete",
    "candidates[].catalyst.theme_taxonomy.l3_provenance.coverage_digest",
    "candidates[].catalyst.theme_taxonomy.l3_provenance.provider",
    "candidates[].catalyst.theme_taxonomy.l3_provenance.raw_membership_source",
    "candidates[].catalyst.theme_taxonomy.l3_provenance.scoring_universe",
    "candidates[].catalyst.theme_taxonomy.l3_provenance.snapshot_date",
    "candidates[].catalyst.theme_taxonomy.l3_provenance.validation_status",
    "candidates[].catalyst.theme_taxonomy.primary_canonical_theme_id",
    "candidates[].catalyst.theme_taxonomy.production_effect_enabled",
    "candidates[].catalyst.theme_taxonomy.raw_concepts[]",
    "candidates[].catalyst.theme_taxonomy.source_as_of",
    "candidates[].catalyst.theme_taxonomy.taxonomy_configuration_fingerprint",
    "candidates[].catalyst.theme_taxonomy.taxonomy_schema_name",
    "candidates[].catalyst.theme_taxonomy.taxonomy_schema_version",
    "candidates[].catalyst.theme_taxonomy.unavailable_reason",
    "candidates[].catalyst.time_window",
    "candidates[].event_risk.holder_reduction.observed_at",
    "candidates[].event_risk.holder_reduction.reduce_penalty",
    "candidates[].event_risk.holder_reduction.source_status",
    "candidates[].event_risk.regulatory.evidence[].published_at",
    "candidates[].event_risk.regulatory.evidence[].source",
    "candidates[].event_risk.regulatory.evidence[].title",
    "candidates[].event_risk.regulatory.evidence[].url",
    "candidates[].event_risk.regulatory.negative_depth",
    "candidates[].event_risk.rule6_checks[].evidence[].published_at",
    "candidates[].event_risk.rule6_checks[].evidence[].source",
    "candidates[].event_risk.rule6_checks[].evidence[].title",
    "candidates[].event_risk.rule6_checks[].evidence[].url",
    "candidates[].event_risk.rule6_checks[].group",
    "candidates[].event_risk.rule6_checks[].id",
    "candidates[].event_risk.rule6_checks[].metrics",
    "candidates[].event_risk.rule6_checks[].name",
    "candidates[].event_risk.rule6_checks[].notes",
    "candidates[].event_risk.suspension.observed_at",
    "candidates[].event_risk.suspension.source_status",
    "candidates[].event_risk.unlock.denominator",
    "candidates[].event_risk.unlock.large_unlock_flag",
    "candidates[].event_risk.unlock.observed_at",
    "candidates[].event_risk.unlock.source_status",
    "candidates[].event_risk.unlock.unlock_date",
    "candidates[].event_risk.unlock.unlock_pct",
    "candidates[].exchange",
    "candidates[].fundamental.expectation.esp_raw",
    "candidates[].fundamental.expectation.ind_median_profit_growth",
    "candidates[].fundamental.profitability.q0_net_income",
    "candidates[].fundamental.profitability.q0_profit_dedt",
    "candidates[].fundamental.profitability.q1_dt_yoy",
    "candidates[].fundamental.profitability.roe",
    "candidates[].fundamental.profitability.ttm_profit_dedt",
    "candidates[].fundamental.quality.q0_dt_profit_ratio",
    "candidates[].fundamental.quality.ttm_ocf_ratio",
    "candidates[].fundamental.valuation.pb",
    "candidates[].fundamental.valuation.pe",
    "candidates[].fundamental.valuation.pe_ttm",
    "candidates[].fundamental.valuation.peg",
    "candidates[].fundamental.valuation.total_mv",
    "candidates[].fundamental.valuation.val_bonus",
    "candidates[].fundamental.valuation.val_penalty",
    "candidates[].industry.industry_fundamental_trend",
    "candidates[].industry.industry_fundamental_trend_evidence[].published_at",
    "candidates[].industry.industry_fundamental_trend_evidence[].source",
    "candidates[].industry.industry_fundamental_trend_evidence[].title",
    "candidates[].industry.industry_fundamental_trend_evidence[].url",
    "candidates[].industry.industry_trend",
    "candidates[].industry.industry_trend_evidence[].published_at",
    "candidates[].industry.industry_trend_evidence[].source",
    "candidates[].industry.industry_trend_evidence[].title",
    "candidates[].industry.industry_trend_evidence[].url",
    "candidates[].industry.industry_trend_signal.classification",
    "candidates[].industry.industry_trend_signal.classifier_version",
    "candidates[].industry.industry_trend_signal.configuration_fingerprint",
    "candidates[].industry.industry_trend_signal.forward_calibration_required",
    "candidates[].industry.industry_trend_signal.industry_heat_score",
    "candidates[].industry.industry_trend_signal.industry_trend",
    "candidates[].industry.industry_trend_signal.positive_effect_enabled",
    "candidates[].industry.industry_trend_signal.risk_filter_v1_prior",
    "candidates[].industry.industry_trend_signal.source_as_of",
    "candidates[].industry.industry_trend_signal.source_id",
    "candidates[].industry.industry_trend_signal.sw_l2_code",
    "candidates[].industry.industry_trend_signal.sw_l2_name",
    "candidates[].industry.industry_trend_signal.thresholds.headwind_max",
    "candidates[].industry.industry_trend_signal.thresholds.tailwind_min",
    "candidates[].industry.industry_trend_signal.unavailable_reason",
    "candidates[].industry.industry_trend_signal.validation_status",
    "candidates[].industry.sw_l1_code",
    "candidates[].industry.sw_l1_name",
    "candidates[].industry.sw_l2_code",
    "candidates[].industry.sw_l2_name",
    "candidates[].liquidity.avg_amount_20d",
    "candidates[].liquidity.turnover_rate",
    "candidates[].name",
    "candidates[].portfolio_impact.correlation_action",
    "candidates[].portfolio_impact.factor_exposures[].factor",
    "candidates[].portfolio_impact.factor_exposures[].status",
    "candidates[].portfolio_impact.factor_exposures[].threshold",
    "candidates[].quote.adjustment",
    "candidates[].quote.close",
    "candidates[].quote.current_price",
    "candidates[].quote.price_source",
    "candidates[].quote.price_time",
    "candidates[].quote.source_trade_date",
    "candidates[].scores.cat_flag",
    "candidates[].scores.cat_score",
    "candidates[].scores.deduct",
    "candidates[].scores.egs_base",
    "candidates[].scores.esp_score",
    "candidates[].scores.industry_heat_score",
    "candidates[].scores.l1_score",
    "candidates[].scores.l2_flags",
    "candidates[].scores.l4_flag",
    "candidates[].scores.l4_score",
    "candidates[].scores.multiplier",
    "candidates[].selection.cninfo_flag",
    "candidates[].selection.entry_flag",
    "candidates[].selection.rank",
    "candidates[].selection.still_in_pool",
    "candidates[].selection.tier",
    "candidates[].ts_code",
    "decision_as_of",
    "horizon",
    "market",
    "market_context.margin_coverage.coverage_complete",
    "market_context.margin_coverage.effective_ref_date",
    "market_context.margin_coverage.reference_date",
    "market_context.margin_coverage.row_count",
    "market_context.margin_coverage.status",
    "market_context.margin_coverage.universe_size",
    "market_context.market_regime.confidence",
    "market_context.market_regime.triggers[].id",
    "market_context.market_regime.triggers[].status",
    "market_context.market_regime.triggers[].threshold",
    "market_context.market_regime.triggers[].value",
    "market_context.moneyflow_coverage.coverage_complete",
    "market_context.moneyflow_coverage.observed_trade_dates[]",
    "market_context.moneyflow_coverage.reference_date",
    "market_context.moneyflow_coverage.requested_trade_dates[]",
    "market_context.moneyflow_coverage.row_count",
    "market_context.moneyflow_coverage.status",
    "market_context.moneyflow_coverage.target_complete_count",
    "market_context.moneyflow_coverage.target_universe_size",
    "market_context.moneyflow_coverage.universe_size",
    "market_context.trade_calendar.calendar_source",
    "market_context.trade_calendar.latest_trade_date",
    "market_context.trade_calendar.recent_trade_dates[]",
    "market_context.volatility.awakening_status",
    "market_context.volatility.iv_symbol",
    "market_context.volatility.rule3_status",
    "preset",
    "price_data_through",
    "run_date",
    "schema_name",
    "source.clocks.decision_as_of",
    "source.clocks.price_data_through",
    "source.clocks.run_date",
    "source.data_provider",
    "source.hard_veto_source_health.holder_reduction.observed_at",
    "source.hard_veto_source_health.holder_reduction.status",
    "source.hard_veto_source_health.suspension.observed_at",
    "source.hard_veto_source_health.suspension.status",
    "source.hard_veto_source_health.unlock.observed_at",
    "source.hard_veto_source_health.unlock.status",
    "source.l3_coverage.catalog_board_count",
    "source.l3_coverage.catalog_digest",
    "source.l3_coverage.catalog_tag",
    "source.l3_coverage.complete",
    "source.l3_coverage.excluded_non_main_board_member_count",
    "source.l3_coverage.main_board_member_pair_count",
    "source.l3_coverage.market_suffix_counts",
    "source.l3_coverage.out_of_a_share_member_count",
    "source.l3_coverage.raw_member_row_count",
    "source.l3_coverage.received_board_count",
    "source.l3_coverage.scope_filtered_empty_board_count",
    "source.l3_coverage.scoring_universe",
    "source.l3_coverage.source",
    "source.l3_coverage.unique_member_pair_count",
    "source.l3_coverage.verified_empty_board_count",
    "source.l3_mode",
    "source.l3_pit_strict",
    "source.l3_provider",
    "source.l3_snapshot_date",
    "source.run_identity.candidate_digest",
    "source.run_identity.run_id",
    "source.run_identity.stage_status",
    "source.screening_engine",
    "source.screening_engine_version",
    "state_refs.circuit_breaker",
    "state_refs.execution_log",
    "state_refs.positions",
    "state_refs.veto_log",
    "trade_date",
    "universe_summary.excluded_counts",
    "universe_summary.final_count",
    "universe_summary.full_count",
    "universe_summary.rank_exclusion_counts.l1_industry_leader",
    "universe_summary.rank_exclusion_counts.l2_quality_risk",
    "universe_summary.rank_exclusion_counts.rank_unexpected",
    "universe_summary.watch_count",
)


class EffectContractMemoTests(unittest.TestCase):
    def setUp(self):
        effect_contract_module._default_static_inventory_from_snapshot.cache_clear()
        effect_contract_module._contract_from_source.cache_clear()
        effect_contract_module._source_tree.cache_clear()
        effect_contract_module._governed_python_literal_names_for_source.cache_clear()
        effect_contract_module._runtime_portfolio_policy_literal_violations_for_sources.cache_clear()
        effect_contract_module._string_assignment_items.cache_clear()
        effect_contract_module._operation_impact_sources_for_source.cache_clear()
        effect_contract_module._literal_string_assignment_values.cache_clear()

    def test_default_inventory_memo_reuses_same_snapshot_and_returns_copies(self):
        with patch.object(effect_contract_module, "_build_static_inventory",
                          wraps=effect_contract_module._build_static_inventory) as build:
            first = static_inventory()
            first["analysis_input_paths"][0] = "mutated"
            second = static_inventory()
        self.assertEqual(build.call_count, 1)
        self.assertNotEqual(second["analysis_input_paths"][0], "mutated")
        self.assertFalse(any(key.endswith("_sha256") for key in second))

    def test_inventory_memo_key_changes_with_source_bytes_and_overrides_stay_uncached(self):
        baseline = effect_contract_module._read_default_static_snapshot()
        changed = tuple(
            (rel, text + "\n# memo-cache-probe\n" if rel == "runners/a_short_weekly_pipeline.py" else text)
            for rel, text in baseline
        )
        with patch.object(effect_contract_module, "_build_static_inventory",
                          wraps=effect_contract_module._build_static_inventory) as build:
            effect_contract_module._default_static_inventory_from_snapshot(baseline)
            effect_contract_module._default_static_inventory_from_snapshot(changed)
            source = (ROOT / "engine" / "a_short_portfolio_risk.py").read_text(encoding="utf-8")
            static_inventory(source_overrides={"engine/a_short_portfolio_risk.py": source})
            static_inventory(source_overrides={"engine/a_short_portfolio_risk.py": source})
        self.assertEqual(build.call_count, 4)

    def test_contract_memo_keys_on_json_bytes_and_returns_copies(self):
        first = load_contract()
        first["schema_name"] = "mutated"
        second = load_contract()
        self.assertEqual(effect_contract_module._contract_from_source.cache_info().misses, 1)
        self.assertEqual(second["schema_name"], "a_short_m67_effect_contract")

        raw = effect_contract_module.CONTRACT_PATH.read_text(encoding="utf-8")
        effect_contract_module._contract_from_source.cache_clear()
        effect_contract_module._contract_from_source(raw)
        effect_contract_module._contract_from_source(raw + "\n")
        self.assertEqual(effect_contract_module._contract_from_source.cache_info().misses, 2)

    def test_override_reuses_unchanged_source_trees_but_parses_changed_source(self):
        portfolio_rel = "engine/a_short_portfolio_risk.py"
        portfolio = (ROOT / portfolio_rel).read_text(encoding="utf-8")
        changed = portfolio + "\n# source-tree-cache-probe\n"

        static_inventory(source_overrides={portfolio_rel: portfolio})
        baseline = effect_contract_module._source_tree.cache_info()
        static_inventory(source_overrides={portfolio_rel: portfolio})
        same_override = effect_contract_module._source_tree.cache_info()
        static_inventory(source_overrides={portfolio_rel: changed})
        changed_override = effect_contract_module._source_tree.cache_info()

        self.assertEqual(same_override.misses, baseline.misses)
        self.assertGreater(same_override.hits, baseline.hits)
        self.assertEqual(changed_override.misses, same_override.misses + 1)

class EffectContractStaticTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_contract()

    def test_current_schema_fields_rules_thresholds_and_output_are_registered(self):
        self.assertIsNone(static_contract_error(self.contract))

    def test_legacy_migration_registry_is_static_list_bound(self):
        tampered = copy.deepcopy(self.contract)
        tampered["legacy_migration_entries"][0]["source_commit"] = "0" * 40
        self.assertEqual(
            static_contract_error(tampered),
            "legacy effect-contract migration registry changed without effect-contract update",
        )

    def test_legacy_migration_entries_match_git_history(self):
        for fp in (
            "ff549e8c9016671fbfae48913bce5a8d74f855c75c5c2175f7b2297a06d8a179",
            "2fbfc215d3609a2482359b9efefd0dc7ae5ea3a186d14faee3b8673dbec30c12",
        ):
            snapshot = load_legacy_effect_contract(fp)
            self.assertIsInstance(snapshot, dict)
            self.assertEqual(effect_contract_module.contract_fingerprint(snapshot), fp)

    def test_inventory_has_no_retired_derived_fingerprints(self):
        baseline = static_inventory()
        effect_contract_module._default_static_inventory_from_snapshot.cache_clear()
        portable = static_inventory()
        self.assertEqual(portable["analysis_input_paths"], baseline["analysis_input_paths"])
        self.assertEqual(portable["runtime_policy_schema_paths"], baseline["runtime_policy_schema_paths"])
        self.assertFalse(any(key.endswith("_sha256") for key in portable))

    def test_new_analysis_input_field_cannot_escape_registration(self):
        schema = json.loads((ROOT / "schemas" / "analysis_input.schema.json").read_text(encoding="utf-8"))
        schema["properties"]["future_effect_probe"] = {"type": "string"}
        error = static_contract_error(self.contract, inventory=static_inventory(analysis_schema=schema))
        self.assertIsNotNone(error)
        self.assertIn("coverage", error)

    def test_new_or_changed_decision_predicate_does_not_require_reseal(self):
        rel = "engine/a_short_portfolio_risk.py"
        source = (ROOT / rel).read_text(encoding="utf-8") + "\nif False:\n    pass\n"
        error = static_contract_error(self.contract, inventory=static_inventory(source_overrides={rel: source}))
        self.assertIsNone(error)

    def test_watch_pool_selector_predicate_does_not_require_reseal(self):
        rel = "engine/egs_industry_heat.py"
        source = (ROOT / rel).read_text(encoding="utf-8").replace(
            "if l2 in overflow and count >= 15:",
            "if l2 in overflow and count >= 16:",
            1,
        )
        error = static_contract_error(self.contract, inventory=static_inventory(source_overrides={rel: source}))
        self.assertIsNone(error)

    def test_changed_runtime_policy_value_does_not_require_reseal(self):
        rel = "presets/a_short_m67_runtime_policy_20260715.json"
        policy = (ROOT / rel).read_text(encoding="utf-8").replace(
            '"same_sw_l2_threshold_pct": 40.0', '"same_sw_l2_threshold_pct": 41.0', 1)
        error = static_contract_error(
            self.contract, inventory=static_inventory(runtime_policy_overrides={rel: policy}))
        self.assertIsNone(error)

    def test_governed_threshold_literal_cannot_return_to_python(self):
        rel = "engine/a_short_portfolio_risk.py"
        source = (ROOT / rel).read_text(encoding="utf-8") + "\nSAME_SW_L2_THRESHOLD_PCT = 41.0\n"
        error = static_contract_error(self.contract, inventory=static_inventory(source_overrides={rel: source}))
        self.assertIn("governed business threshold literal returned to Python", error)

    def test_runtime_portfolio_policy_literal_cannot_return_to_result_consumers(self):
        weekly_rel = "runners/a_short_weekly_pipeline.py"
        weekly = (ROOT / weekly_rel).read_text(encoding="utf-8").replace(
            'fact["circ_mv_rmb"] < SMALL_FLOAT_MV_RMB', 'fact["circ_mv_rmb"] < 8_000_000_000.0', 1)
        error = static_contract_error(self.contract, inventory=static_inventory(source_overrides={weekly_rel: weekly}))
        self.assertIn("runtime portfolio policy literal returned to result consumers", error)
        self.assertIn("small_float_mv_rmb", error)

        portfolio_rel = "engine/a_short_portfolio_risk.py"
        portfolio = (ROOT / portfolio_rel).read_text(encoding="utf-8") + '\n_POLICY_LABEL_PROBE = "小流通市值(<80亿元)"\n'
        error = static_contract_error(self.contract, inventory=static_inventory(source_overrides={portfolio_rel: portfolio}))
        self.assertIn("runtime portfolio policy literal returned to result consumers", error)
        self.assertIn("small_float_label", error)

    def test_new_runtime_policy_field_cannot_escape_consumer_registration(self):
        rel = "presets/a_short_m67_runtime_policy_20260715.json"
        policy = (ROOT / rel).read_text(encoding="utf-8").replace(
            '"impact_cost_frac": 0.005', '"impact_cost_frac": 0.005, "future_threshold": 1', 1)
        error = static_contract_error(
            self.contract, inventory=static_inventory(runtime_policy_overrides={rel: policy}))
        self.assertIn("runtime policy", error)

    def test_stale_governed_leaf_in_contract_body_cannot_hide_behind_updated_hashes(self):
        """Deleting a governed leaf must also delete every contract-body reader entry."""
        inventory = static_inventory()
        contract = copy.deepcopy(self.contract)
        rel = "presets/a_short_m67_runtime_policy_20260715.json"
        contract["runtime_policy_paths"][rel].append("portfolio_risk.retired_probe")
        contract["runtime_policy_leaf_readers"][rel]["portfolio_risk.retired_probe"] = [
            "stale reader"
        ]
        error = static_contract_error(contract, inventory=inventory)
        self.assertEqual(error, "runtime policy field inventory body changed without effect contract update")

    def test_stale_leaf_reader_body_cannot_hide_behind_updated_hashes(self):
        """The per-leaf reader body has its own reverse guard, not just the paths body."""
        inventory = static_inventory()
        contract = copy.deepcopy(self.contract)
        rel = "presets/a_short_m67_runtime_policy_20260715.json"
        path = next(iter(contract["runtime_policy_leaf_readers"][rel]))
        contract["runtime_policy_leaf_readers"][rel][path] = ["stale reader"]
        error = static_contract_error(contract, inventory=inventory)
        self.assertEqual(error, "runtime policy per-leaf reader mapping body changed without effect contract update")

    def test_runtime_binding_consumer_ref_must_name_an_actual_leaf_reader(self):
        """A prose locator cannot survive when its policy consumer moves."""
        contract = copy.deepcopy(self.contract)
        binding = next(row for row in contract["runtime_policy_bindings"] if row["id"] == "phase5_thresholds")
        binding["consumer_refs"][1] = "runners/a_short_weekly_pipeline.py::_PHASE5_POLICY"
        error = static_contract_error(contract, inventory=static_inventory())
        self.assertIn("phase5_thresholds consumer_ref is not an actual reader", error)
        self.assertIn("a_short_weekly_pipeline.py::_PHASE5_POLICY", error)

    def test_new_policy_field_still_fails_after_hashes_and_generic_binding_are_updated(self):
        """A broad section-level consumer note cannot pretend an unread leaf is wired."""
        rel = "presets/a_short_m67_runtime_policy_20260715.json"
        policy = (ROOT / rel).read_text(encoding="utf-8").replace(
            '"impact_cost_frac": 0.005', '"impact_cost_frac": 0.005, "future_threshold": 1', 1)
        inventory = static_inventory(runtime_policy_overrides={rel: policy})
        contract = copy.deepcopy(self.contract)
        contract["runtime_policy_paths"] = inventory["runtime_policy_paths"]
        binding = next(row for row in contract["runtime_policy_bindings"] if row["id"] == "phase5_thresholds")
        matched = [path for path in inventory["runtime_policy_paths"][rel]
                   if path == "phase5" or path.startswith("phase5.")]
        binding["source_paths_sha256"] = hashlib.sha256(
            json.dumps(matched, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        error = static_contract_error(contract, inventory=inventory)
        self.assertIn("no actual result reader", error)
        self.assertIn("phase5.future_threshold", error)

    def test_top_level_policy_assignment_without_result_use_still_fails(self):
        """Reading a policy into an unused global is not a result consumer."""
        rel = "presets/a_short_m67_runtime_policy_20260715.json"
        policy = (ROOT / rel).read_text(encoding="utf-8").replace(
            '"impact_cost_frac": 0.005', '"impact_cost_frac": 0.005, "future_threshold": 1', 1)
        config_rel = "engine/a_short_runtime_config.py"
        loader = (ROOT / config_rel).read_text(encoding="utf-8").replace(
            '_PHASE5_KEYS = (', '_PHASE5_KEYS = ("future_threshold", ', 1)
        needle = ('        "impact_cost_frac": _number(phase["impact_cost_frac"], '
                  '"m67.phase5.impact_cost_frac", minimum=0.0, maximum=1.0),')
        loader = loader.replace(
            needle, needle + '\n        "future_threshold": _number(phase["future_threshold"], '
            '"m67.phase5.future_threshold", minimum=0.0),', 1)
        phase5_rel = "runners/a_short_phase5_engine.py"
        phase5 = (ROOT / phase5_rel).read_text(encoding="utf-8") + (
            '\nFUTURE_THRESHOLD = _PHASE5_POLICY["future_threshold"]\n')
        inventory = static_inventory(
            runtime_policy_overrides={rel: policy},
            source_overrides={config_rel: loader, phase5_rel: phase5},
        )
        contract = copy.deepcopy(self.contract)
        contract["runtime_policy_paths"] = inventory["runtime_policy_paths"]
        binding = next(row for row in contract["runtime_policy_bindings"] if row["id"] == "phase5_thresholds")
        matched = [path for path in inventory["runtime_policy_paths"][rel]
                   if path == "phase5" or path.startswith("phase5.")]
        binding["source_paths_sha256"] = hashlib.sha256(
            json.dumps(matched, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        error = static_contract_error(contract, inventory=inventory)
        self.assertIn("no actual result reader", error)
        self.assertIn("phase5.future_threshold", error)

    def test_new_operation_impact_source_and_llm_task_type_cannot_escape_registration(self):
        weekly_rel = "runners/a_short_weekly_pipeline.py"
        weekly_source = (ROOT / weekly_rel).read_text(encoding="utf-8") + "\n_probe = {'source_field': 'future_effect_probe'}\n"
        error = static_contract_error(self.contract, inventory=static_inventory(source_overrides={weekly_rel: weekly_source}))
        self.assertEqual(error, "operation_impact source_field changed without effect contract update")

        schema = json.loads((ROOT / "schemas" / "analysis_input.schema.json").read_text(encoding="utf-8"))
        schema["$defs"]["llmTask"]["properties"]["prompt"]["enum"].append("future_hidden_risk")
        error = static_contract_error(self.contract, inventory=static_inventory(analysis_schema=schema))
        self.assertEqual(error, "LLM task type changed without effect contract update")

    def test_new_weekly_output_schema_field_cannot_escape_registration(self):
        rel = "schemas/a_short_weekly_report.schema.json"
        schema = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        schema.setdefault("properties", {})["future_effect_probe"] = {"type": "string"}
        text = json.dumps(schema, ensure_ascii=False, indent=2)
        error = static_contract_error(self.contract, inventory=static_inventory(output_schema_overrides={rel: text}))
        self.assertEqual(error, "weekly/M6.7 output schema changed without effect contract update")

    def test_readable_structure_lists_reject_planted_additions(self):
        cases = (
            (
                "analysis_input_paths",
                lambda contract: contract["analysis_input_paths"].append("candidates[].planted"),
                "analysis_input schema changed without effect contract update",
            ),
            (
                "runtime_policy_paths",
                lambda contract: contract["runtime_policy_paths"][
                    "presets/a_short_m67_runtime_policy_20260715.json"
                ].append("phase5.planted"),
                "runtime policy field inventory body changed without effect contract update",
            ),
            (
                "runtime_policy_schema_paths",
                lambda contract: contract["runtime_policy_schema_paths"][
                    "schemas/a_short_m67_runtime_policy.schema.json"
                ].append("phase5.planted"),
                "runtime policy schema changed without effect contract update",
            ),
            (
                "output_schema_paths",
                lambda contract: contract["output_schema_paths"][
                    "schemas/a_short_m67_report.schema.json"
                ].append("machine.planted"),
                "weekly/M6.7 output schema changed without effect contract update",
            ),
        )
        for key, plant, expected in cases:
            with self.subTest(key=key):
                contract = copy.deepcopy(self.contract)
                plant(contract)
                self.assertEqual(static_contract_error(contract), expected)

    def test_readable_structure_lists_ignore_reordering(self):
        contract = copy.deepcopy(self.contract)
        contract["analysis_input_paths"].reverse()
        for key in ("runtime_policy_paths", "runtime_policy_schema_paths", "output_schema_paths"):
            for paths in contract[key].values():
                paths.reverse()
        contract["legacy_migration_entries"].reverse()
        self.assertIsNone(static_contract_error(contract))

    def test_report_presence_cannot_be_declared_a_field_consumer(self):
        contract = copy.deepcopy(self.contract)
        group = next(row for row in contract["groups"] if row["id"] == "candidate_technical")
        group["runtime_handler"] = "upstream_candidate_set"
        error = static_contract_error(contract)
        self.assertIn("may not treat report presence as a field consumer", error)

    def test_direct_runtime_handler_requires_all_leaf_consumer_proof(self):
        for handler in ("phase5_decision", "lineage_gate"):
            contract = copy.deepcopy(self.contract)
            group = next(row for row in contract["groups"] if row["id"] == "candidate_quote")
            group["runtime_handler"] = handler
            group.pop("unresolved_reason")
            error = static_contract_error(contract)
            self.assertIn("direct runtime handler lacks all-leaf consumer proof", error)

    def test_m4_producer_binding_is_explicit_and_currently_constant_null(self):
        group = next(row for row in self.contract["groups"]
                     if row["id"] == "candidate_derived_flags_m4_review")
        self.assertEqual(group["producer_binding"]["status"], "constant_null")
        source = ast.parse((ROOT / "A-EGS" / "egs_main.py").read_text(encoding="utf-8"))
        values = []
        for node in ast.walk(source):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "m4_review_required":
                    values.append(value)
        self.assertEqual(len(values), 1)
        self.assertIsInstance(values[0], ast.Constant)
        self.assertIsNone(values[0].value)

    def test_m4_producer_binding_mutation_is_rejected(self):
        contract = copy.deepcopy(self.contract)
        group = next(row for row in contract["groups"]
                     if row["id"] == "candidate_derived_flags_m4_review")
        group["producer_binding"]["status"] = "available"
        error = static_contract_error(contract)
        self.assertIn("producer binding", error)

    def test_m4_and_comparison_machine_nodes_are_schema_bound(self):
        schema = json.loads((ROOT / "schemas" / "a_short_m67_report.schema.json").read_text(encoding="utf-8"))
        report = build_m67_report(_normalized(), AS_OF, GEN)
        jsonschema.validate(report, schema)
        for node_name, field, value in (
            ("m4_review_gate", "producer_status", "available"),
            ("derived_flag_comparison", "comparison_only", False),
        ):
            mutant = copy.deepcopy(report)
            mutant["machine"][node_name][field] = value
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(mutant, schema)

    def test_technical_volatility_comparison_is_schema_bound_and_mutation_visible(self):
        schema = json.loads((ROOT / "schemas" / "a_short_m67_report.schema.json").read_text(encoding="utf-8"))
        baseline_input = _normalized()
        baseline = build_m67_report(baseline_input, AS_OF, GEN)
        jsonschema.validate(baseline, schema)
        base_node = baseline["machine"]["technical_volatility_comparison"]
        self.assertTrue(base_node["comparison_only"])
        self.assertFalse(base_node["production_effect_enabled"])
        self.assertEqual(base_node["technical"]["leaf_count"], 39)
        self.assertEqual(base_node["volatility"]["leaf_count"], 3)

        technical_mutant = _normalized()
        technical_mutant["source_technical"].setdefault("moving_averages", {})
        technical_mutant["source_technical"]["moving_averages"]["ma10"] = 12.34
        changed_technical = build_m67_report(technical_mutant, AS_OF, GEN)
        self.assertNotEqual(
            base_node["technical"]["input_sha256"],
            changed_technical["machine"]["technical_volatility_comparison"]["technical"]["input_sha256"],
        )
        self.assertEqual(baseline["m67"]["table"]["操作"], changed_technical["m67"]["table"]["操作"])

        volatility_mutant = _normalized()
        volatility_mutant["source_volatility"]["iv_hv_ratio"] = 1.2
        changed_volatility = build_m67_report(volatility_mutant, AS_OF, GEN)
        changed_node = changed_volatility["machine"]["technical_volatility_comparison"]
        self.assertEqual(changed_node["volatility"]["observed_outcome"], "snapshot_observed")
        self.assertEqual(changed_node["verdict"], "source_snapshot_observed")
        self.assertEqual(changed_volatility["m67"]["table"]["操作"], baseline["m67"]["table"]["操作"])

        malformed = _normalized()
        malformed["source_volatility"]["iv_hv_ratio"] = object()
        malformed_report = build_m67_report(malformed, AS_OF, GEN)
        self.assertEqual(
            malformed_report["machine"]["technical_volatility_comparison"]["verdict"],
            "unavailable_manual_review",
        )

    def test_volatility_constant_null_producer_binding_is_ast_guarded(self):
        group = next(row for row in self.contract["groups"] if row["id"] == "candidate_volatility")
        self.assertEqual(group["producer_binding"]["status"], "constant_null")
        source = ast.parse((ROOT / "A-EGS" / "egs_main.py").read_text(encoding="utf-8"))
        function = next(node for node in source.body
                        if isinstance(node, ast.FunctionDef) and node.name == "_candidate_from_row")
        matches = []
        for node in ast.walk(function):
            if not isinstance(node, ast.Dict):
                continue
            keys = [key.value for key in node.keys if isinstance(key, ast.Constant)]
            if {"hv_252d", "iv_hv_ratio", "iv_hv_position_cut_pct"}.issubset(keys):
                matches.append(node)
        self.assertEqual(len(matches), 1)
        values = {key.value: value for key, value in zip(matches[0].keys, matches[0].values)
                  if isinstance(key, ast.Constant)}
        self.assertTrue(all(isinstance(values[key], ast.Constant) and values[key].value is None
                            for key in ("hv_252d", "iv_hv_ratio", "iv_hv_position_cut_pct")))

    def test_volatility_producer_binding_mutation_is_rejected(self):
        contract = copy.deepcopy(self.contract)
        group = next(row for row in contract["groups"] if row["id"] == "candidate_volatility")
        group["producer_binding"]["status"] = "available"
        error = static_contract_error(contract)
        self.assertIn("candidate_volatility producer binding", error)

    def test_comparison_track_requires_non_digest_verdict_variation_binding(self):
        contract = copy.deepcopy(self.contract)
        group = next(row for row in contract["groups"] if row["id"] == "candidate_data_quality")
        group.pop("comparison_verdict_binding")
        error = static_contract_error(contract)
        self.assertIn("comparison verdict binding missing", error)

        contract = copy.deepcopy(self.contract)
        group = next(row for row in contract["groups"] if row["id"] == "candidate_derived_flags_vol_confirm")
        group["comparison_verdict_binding"]["verdict_field"] = "input_sha256"
        error = static_contract_error(contract)
        self.assertIn("digest-only", error)

        contract = copy.deepcopy(self.contract)
        group = next(row for row in contract["groups"] if row["id"] == "candidate_data_quality")
        group["comparison_verdict_binding"]["variation_proof"]["variant_outcome"] = \
            group["comparison_verdict_binding"]["variation_proof"]["baseline_outcome"]
        error = static_contract_error(contract)
        self.assertIn("must change outcome", error)

    def test_event_risk_phase5_gate_batch_is_leaf_bound_and_changes_main_decision(self):
        group = next(row for row in self.contract["groups"]
                     if row["id"] == "candidate_event_risk_phase5_gates")
        expected = sorted([
            "candidates[].event_risk.delisting.delisting_warning",
            "candidates[].event_risk.delisting.st_flag",
            "candidates[].event_risk.holder_reduction.active_plan",
            "candidates[].event_risk.suspension.is_suspended",
        ])
        self.assertEqual(group["runtime_handler"], "phase5_risk")
        self.assertEqual(group["proven_consumer_paths"], expected)
        self.assertIsNone(static_contract_error(self.contract))

        # The source-side mutations must reach the normalized Phase5 risk inputs.
        source_mutations = {
            "st_flag": ("delisting", "st_flag"),
            "delisting_warning": ("delisting", "delisting_warning"),
            "active_plan": ("holder_reduction", "active_plan"),
            "is_suspended": ("suspension", "is_suspended"),
        }
        for label, (section, key) in source_mutations.items():
            source = _egs_candidate()
            source["event_risk"][section][key] = True
            normalized = normalize_candidate(
                source, _series(), _overlay_row(), 55.0,
                {"available_cash": 500000.0}, "震荡市",
            )
            mapped = (normalized["event"]["st_or_delisting"]
                      if label in {"st_flag", "delisting_warning"}
                      else normalized["event"]["holder_reduction_active"]
                      if label == "active_plan"
                      else normalized["derived"]["suspended"])
            self.assertTrue(mapped, label)

        # Each mapped gate is load-bearing: a clean candidate can build, while
        # the corresponding source-derived flag becomes a Phase5 hard veto.
        for section, key, normalized_section, normalized_key, family in (
            ("event", "holder_reduction_active", "event", "holder_reduction_active", "negative_event"),
            ("event", "st_or_delisting", "event", "st_or_delisting", "negative_event"),
            ("derived", "suspended", "derived", "suspended", "liquidity_execution"),
        ):
            baseline = build_m67_report(_normalized(), AS_OF, GEN)
            mutant_input = _normalized()
            mutant_input[normalized_section][normalized_key] = True
            mutant = build_m67_report(mutant_input, AS_OF, GEN)
            self.assertTrue(baseline["machine"]["model_build_eligible"])
            self.assertFalse(mutant["machine"]["model_build_eligible"])
            self.assertEqual(mutant["machine"]["risk_families"][family]["action"], "hard_veto")
            self.assertEqual(mutant["m67"]["table"]["操作"], "否决")


class EffectContractRuntimeTests(unittest.TestCase):
    def test_registered_historical_bundle_revalidates_through_publish_boundary(self):
        from runners.a_short_m67_render import render_weekly_markdown
        for day in ("20260720", "20260727"):
            with self.subTest(day=day), tempfile.TemporaryDirectory() as td:
                source = ROOT / "research" / "results" / "a_short" / day / "weekly_m67.json"
                weekly = json.loads(source.read_text(encoding="utf-8"))
                out = Path(td) / day / "weekly_m67.json"
                out.parent.mkdir(parents=True)
                weekly_bytes = source.read_bytes()
                markdown_bytes = render_weekly_markdown(weekly).encode("utf-8")
                out.write_bytes(weekly_bytes)
                out.with_suffix(".md").write_bytes(markdown_bytes)
                lineage = weekly.get("run_lineage") or {}
                freshness = lineage.get("price_freshness") or {}
                receipt = {
                    "schema_name": "a_short_weekly_publish_receipt",
                    "schema_version": "1.1.0",
                    "as_of": weekly["as_of"],
                    "decision_as_of": weekly.get("decision_as_of") or weekly["as_of"],
                    "run_date": weekly.get("run_date") or lineage.get("run_date") or freshness.get("run_date"),
                    "price_data_through": weekly.get("price_data_through") or freshness.get("price_data_through"),
                    "run_id": lineage.get("run_id"),
                    "candidate_digest": lineage.get("candidate_digest"),
                    "published_at": "2026-08-02T00:00:00+08:00",
                    "account_snapshot": lineage.get("account_snapshot"),
                    "stage_status": "complete",
                    "outputs": ["weekly_m67.json", "weekly_m67.md"],
                    "outputs_digest": {
                        "weekly_m67.json": {"sha256": hashlib.sha256(weekly_bytes).hexdigest(),
                                            "byte_length": len(weekly_bytes)},
                        "weekly_m67.md": {"sha256": hashlib.sha256(markdown_bytes).hexdigest(),
                                           "byte_length": len(markdown_bytes)},
                    },
                }
                receipt_path = out.with_name("weekly_m67.receipt.json")
                receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                validate_published_weekly_bundle(out, receipt_path)

    def test_registered_historical_ledgers_validate_and_tampering_is_rejected(self):
        paths = (
            ROOT / "research" / "results" / "a_short" / "20260720" / "weekly_m67.json",
            ROOT / "research" / "results" / "a_short" / "20260727" / "weekly_m67.json",
        )
        for path in paths:
            with self.subTest(path=path):
                weekly = json.loads(path.read_text(encoding="utf-8"))
                validate_effect_contract_ledger(weekly)
                tampered = copy.deepcopy(weekly)
                tampered["effect_contract_ledger"]["records"][0]["reason"] = "tampered"
                with self.assertRaises(ValueError):
                    validate_effect_contract_ledger(tampered)

    def test_weekly_json_markdown_and_validator_expose_unwired_or_independent_groups(self):
        weekly = build_weekly_report([_normalized()], AS_OF, GEN)
        records = {record["id"]: record for record in weekly["effect_contract_ledger"]["records"]}
        self.assertEqual(records["industry_trend"]["status"], "unavailable_manual_review")
        self.assertEqual(records["lineage_metadata"]["status"], "intentionally_independent")
        for group_id in ("candidate_technical", "candidate_fundamental", "candidate_capital_flow",
                         "candidate_catalyst", "candidate_volatility", "candidate_analyst",
                         "market_context", "account_context", "candidate_quote",
                         "candidate_industry_classification", "candidate_scores", "candidate_event_risk",
                         "candidate_liquidity", "portfolio_concentration_factor_resonance",
                         "identity_batch_gate"):
            expected = ("intentionally_independent" if group_id in {"candidate_technical", "candidate_volatility"}
                        else "unavailable_manual_review")
            self.assertEqual(records[group_id]["status"], expected)
        self.assertEqual(records["candidate_derived_flags_phase5_risk"]["status"], "applied")
        self.assertEqual(records["candidate_derived_flags_phase5_entry"]["status"], "applied")
        self.assertEqual(records["candidate_derived_flags_m4_review"]["status"], "not_triggered")
        self.assertIn("constant-null", records["candidate_derived_flags_m4_review"]["reason"])
        self.assertEqual(records["candidate_derived_flags_vol_confirm"]["status"], "applied")
        self.assertEqual(records["candidate_data_quality"]["status"], "applied")
        self.assertEqual(records["candidate_volatility"]["status"], "intentionally_independent")
        self.assertEqual(weekly["effect_contract_ledger"]["summary"]["total"], len(records))
        markdown = render_weekly_markdown(weekly)
        self.assertIn("字段/规则联动台账", markdown)
        self.assertIn("industry_trend=unknown (fail-closed; manual review, no star adjustment)", markdown)
        self.assertIn("不能只因本周有候选就报已联动", markdown)

        tampered = copy.deepcopy(weekly)
        next(row for row in tampered["effect_contract_ledger"]["records"]
             if row["id"] == "industry_trend")["status"] = "applied"
        with self.assertRaises(ValueError):
            validate_weekly_report(tampered, _feed())

    def test_m4_ledger_status_is_not_triggered_until_a_true_flag_is_observed(self):
        baseline = build_weekly_report([_normalized()], AS_OF, GEN)
        baseline_record = next(row for row in baseline["effect_contract_ledger"]["records"]
                              if row["id"] == "candidate_derived_flags_m4_review")
        self.assertEqual(baseline_record["status"], "not_triggered")
        self.assertIn("constant-null", baseline_record["reason"])
        self.assertEqual(baseline["reports"][0]["machine"]["m4_review_gate"]["observed_state"], "inactive")
        missing = _normalized()
        missing["derived"].pop("m4_review_required", None)
        explicit_false = _normalized()
        explicit_false["derived"]["m4_review_required"] = False
        self.assertEqual(
            baseline["reports"][0],
            build_weekly_report([missing], AS_OF, GEN)["reports"][0],
        )
        self.assertEqual(
            baseline["reports"][0],
            build_weekly_report([explicit_false], AS_OF, GEN)["reports"][0],
        )

        flags = copy.deepcopy(_egs_candidate()["derived_flags"])
        flags["m4_review_required"] = True
        triggered = build_weekly_report([_normalized(derived_flags=flags)], AS_OF, GEN)
        triggered_record = next(row for row in triggered["effect_contract_ledger"]["records"]
                               if row["id"] == "candidate_derived_flags_m4_review")
        self.assertEqual(triggered_record["status"], "applied")
        self.assertEqual(triggered["reports"][0]["machine"]["m4_review_gate"]["observed_state"], "true")

        malformed = copy.deepcopy(_egs_candidate()["derived_flags"])
        malformed["m4_review_required"] = "true"
        unavailable = build_weekly_report([_normalized(derived_flags=malformed)], AS_OF, GEN)
        unavailable_record = next(row for row in unavailable["effect_contract_ledger"]["records"]
                                  if row["id"] == "candidate_derived_flags_m4_review")
        self.assertEqual(unavailable_record["status"], "unavailable_manual_review")

    def test_source_bound_headwind_is_recorded_as_applied(self):
        signal = classify_industry_trend(
            score=20.0, sw_l2_code="801080", sw_l2_name="测试行业",
            source_as_of=AS_OF, expected_as_of=AS_OF, governance=load_governance(),
        )
        normalized = normalize_candidate(
            _egs_candidate(
                _weekly_as_of=AS_OF,
                scores={"esp_score": 60, "l4_score": 70, "industry_heat_score": 20.0},
                industry={
                    "sw_l2_code": "801080", "sw_l2_name": "测试行业",
                    "industry_trend": "headwind", "industry_trend_signal": signal,
                },
            ),
            _series(), _overlay_row(), 55.0, {"available_cash": 500000.0}, "震荡期",
        )
        weekly = build_weekly_report([normalized], AS_OF, GEN)
        report = weekly["reports"][0]
        records = {record["id"]: record for record in weekly["effect_contract_ledger"]["records"]}
        self.assertEqual(report["machine"]["industry_trend"]["effect"], "star_down")
        self.assertEqual(report["machine"]["entry_exit_size_star"]["star"], 2)
        self.assertEqual(records["industry_trend"]["status"], "applied")
        validate_weekly_report(weekly, _feed())

    def test_retired_legacy_portfolio_flags_cannot_change_phase5_star_or_action(self):
        base = _normalized()
        legacy = copy.deepcopy(base)
        legacy["portfolio"] = {"same_l2_exposure_over_cap": True, "factor_resonance": True}
        normal_report = build_m67_report(base, AS_OF, GEN)
        legacy_report = build_m67_report(legacy, AS_OF, GEN)
        self.assertNotIn("portfolio_concentration", legacy_report["machine"]["risk_families"])
        self.assertEqual(legacy_report["m67"]["table"]["优先级"], normal_report["m67"]["table"]["优先级"])
        self.assertEqual(legacy_report["m67"]["table"]["操作"], normal_report["m67"]["table"]["操作"])
        self.assertNotIn("portfolio", _normalized())

    def test_derived_flags_each_reaches_phase5_or_formal_comparison(self):
        base_flags = copy.deepcopy(_egs_candidate()["derived_flags"])

        def report_for(source_key, value):
            flags = copy.deepcopy(base_flags)
            flags[source_key] = value
            return build_m67_report(
                _normalized(derived_flags=flags), AS_OF, GEN,
            )

        base = build_m67_report(_normalized(), AS_OF, GEN)
        for source_key in ("chasing_high", "overheat_flag"):
            changed = report_for(source_key, True)
            self.assertNotEqual(
                changed["machine"]["entry_exit_size_star"]["star"],
                base["machine"]["entry_exit_size_star"]["star"],
                source_key,
            )
        for source_key in ("has_crash_veto", "is_lock", "hard_veto"):
            changed = report_for(source_key, True)
            self.assertEqual(changed["m67"]["table"]["操作"], "否决", source_key)

        breakout = report_for("is_breakout", True)
        self.assertEqual(breakout["machine"]["entry_exit_size_star"]["type"], "突破")

        review = report_for("m4_review_required", True)
        self.assertEqual(review["m67"]["table"]["操作"], "观察")
        self.assertIn("m4_review_required:升级审查", review["machine"]["layer"]["observe_only"])
        self.assertFalse(review["machine"]["model_build_eligible"])

        vol_false = report_for("vol_confirm", False)
        vol_true = report_for("vol_confirm", True)
        self.assertEqual(
            vol_false["machine"]["derived_flag_comparison"]["observed_outcome"],
            "vol_confirm_false",
        )
        self.assertEqual(
            vol_true["machine"]["derived_flag_comparison"]["observed_outcome"],
            "vol_confirm_true",
        )
        self.assertEqual(vol_false["m67"]["table"]["操作"], vol_true["m67"]["table"]["操作"])
        self.assertEqual(
            vol_false["machine"]["entry_exit_size_star"]["type"],
            vol_true["machine"]["entry_exit_size_star"]["type"],
        )

        weekly = build_weekly_report([_normalized()], AS_OF, GEN)
        records = {row["id"]: row for row in weekly["effect_contract_ledger"]["records"]}
        self.assertEqual(records["candidate_derived_flags_phase5_risk"]["nature"], "main_decision")
        self.assertEqual(records["candidate_derived_flags_phase5_entry"]["nature"], "main_decision")
        self.assertEqual(records["candidate_derived_flags_m4_review"]["nature"], "main_decision")
        self.assertEqual(records["candidate_derived_flags_vol_confirm"]["nature"], "comparison_track")
        self.assertEqual(records["candidate_derived_flags_vol_confirm"]["status"], "applied")


class LeafEffectPendingAuditTests(unittest.TestCase):
    """The published leaf-effect counts may never contradict the producer source."""

    def setUp(self):
        self.contract = load_contract()
        self.inventory = static_inventory()
        self.paths = self.inventory["analysis_input_paths"]
        self.effects = leaf_effects(self.contract, self.inventory)
        self.live = {"m67_main_decision", "formal_comparison_verdict",
                     "upstream_candidate_set_or_rank"}

    def test_producer_constant_null_is_derived_from_the_real_producer(self):
        from engine.a_short_effect_contract import _producer_literal_leaves
        source = (ROOT / "A-EGS" / "egs_main.py").read_text(encoding="utf-8")
        derived = {path for path, kind in _producer_literal_leaves(source).items()
                   if kind == "constant_null"} & set(self.paths)
        self.assertEqual(set(self.inventory["producer_constant_null_leaves"]), derived)
        self.assertGreater(len(derived), 50)
        # no hard-coded-None leaf may be published as dangling, pending, or live
        leaked = sorted(path for path in derived if self.effects[path] in (
            {"true_dangling", "unclassified_pending_audit"} | self.live))
        self.assertEqual(leaked, [])

    def test_q0_net_income_compatibility_null_is_explicitly_documented(self):
        schema = json.loads((ROOT / "schemas" / "analysis_input.schema.json").read_text(encoding="utf-8"))
        description = schema["$defs"]["candidate"]["properties"]["fundamental"][
            "properties"]["profitability"]["properties"]["q0_net_income"]["description"]
        self.assertIn("intentionally unavailable", description)
        self.assertIn("not a live decision input", description)
        self.assertIn("q0_dt_profit_ratio", description)
        coverage = (ROOT / "schemas" / "analysis_input_coverage.md").read_text(encoding="utf-8")
        self.assertIn("有意不可用的兼容字段", coverage)
        self.assertIn("q0_net_income", coverage)
        self.assertIn("q0_dt_profit_ratio", coverage)

    def test_derivation_follows_the_producer_when_a_literal_changes(self):
        from engine.a_short_effect_contract import _producer_literal_leaves
        source = (ROOT / "A-EGS" / "egs_main.py").read_text(encoding="utf-8")
        leaf = "candidates[].derived_flags.m4_review_required"
        patched = source.replace('"m4_review_required": None,',
                                 '"m4_review_required": _json_bool(0),', 1)
        self.assertNotEqual(patched, source)
        before = {p for p, k in _producer_literal_leaves(source).items() if k == "constant_null"}
        after = {p for p, k in _producer_literal_leaves(patched).items() if k == "constant_null"}
        self.assertIn(leaf, before)
        self.assertNotIn(leaf, after)

    def test_unproven_leaves_are_pending_not_adjudicated_dangling(self):
        counts = Counter(self.effects.values())
        self.assertEqual(counts["true_dangling"], 0)
        self.assertGreater(counts["unclassified_pending_audit"], 0)

    def test_true_dangling_requires_an_explicit_override(self):
        target = next(p for p, v in self.effects.items()
                      if v == "unclassified_pending_audit")
        claimed = copy.deepcopy(self.contract)
        claimed["leaf_effect_overrides"][target] = {"category": "true_dangling"}
        # Adjudicating a leaf is two steps: record the category and take the
        # leaf off the frozen debt list.  Doing only the first is refused.
        self.assertIn("may only shrink",
                      static_contract_error(claimed, inventory=self.inventory) or "")
        claimed["unclassified_pending_audit_baseline"] = [
            path for path in claimed["unclassified_pending_audit_baseline"]
            if path != target
        ]
        self.assertIsNone(static_contract_error(claimed, inventory=self.inventory))
        unproven = copy.deepcopy(self.contract)
        unproven["leaf_effect_overrides"][target] = {"category": "m67_main_decision"}
        unproven["unclassified_pending_audit_baseline"] = [
            path for path in unproven["unclassified_pending_audit_baseline"]
            if path != target
        ]
        self.assertIn("effect proof incomplete",
                      static_contract_error(unproven, inventory=self.inventory) or "")

    def test_a_live_claim_may_not_be_written_in_the_evidence_free_form(self):
        """A bare-string override names a category and can hold no proof.

        The proof check used to skip every non-dict override, so the one form
        that cannot carry `consumer_ref` / `terminal_surface` /
        `mutation_evidence` was also the one form exempt from providing them.
        """
        bare = {path for path, override in self.contract["leaf_effect_overrides"].items()
                if not isinstance(override, dict)}
        self.assertTrue(bare, "fixture assumes at least one bare-string override exists")
        # every existing bare override names a non-live category, and stays legal
        for path in bare:
            self.assertNotIn(self.effects[path], self.live)
        self.assertIsNone(static_contract_error(self.contract, inventory=self.inventory))
        for live_category in sorted(self.live - {"upstream_candidate_set_or_rank"}):
            claimed = copy.deepcopy(self.contract)
            claimed["leaf_effect_overrides"][sorted(bare)[0]] = live_category
            self.assertIn("bare string",
                          static_contract_error(claimed, inventory=self.inventory) or "",
                          live_category)

    def test_every_group_holding_a_live_leaf_cannot_be_true_dangling(self):
        from engine.a_short_effect_contract import _paths_for_prefixes
        checked = 0
        for group in self.contract["groups"]:
            group_paths = _paths_for_prefixes(self.paths, group["source_prefixes"])
            if not any(self.effects[p] in self.live for p in group_paths):
                continue
            checked += 1
            mutated = copy.deepcopy(self.contract)
            mutated["leaf_nature_by_group"][group["id"]] = "true_dangling"
            self.assertIn("true_dangling",
                          static_contract_error(mutated, inventory=self.inventory) or "",
                          group["id"])
        self.assertGreaterEqual(checked, 6)

    def test_leaf_effect_reconciles_with_the_full_schema_inventory(self):
        self.assertEqual(len(self.effects), len(self.paths))
        self.assertEqual(sum(Counter(self.effects.values()).values()), len(self.paths))
        weekly = {"as_of": "20260801", "reports": []}
        summary = build_effect_contract_ledger(weekly, self.contract)["summary"]
        self.assertEqual(sum(summary["effect_counts"].values()), len(self.paths))

    def test_final_score_terminal_names_the_m67_column(self):
        override = self.contract["leaf_effect_overrides"]["candidates[].scores.final_score"]
        self.assertIn("reports[].m67.table.EGS分", override["terminal_surface"])
        self.assertIn("1795", override["mutation_evidence"])


class UnclassifiedPendingBaselineGateTests(unittest.TestCase):
    """Today's unproven remainder is frozen debt; a new arrival must be judged.

    The old fallback silently absorbed any leaf nothing else classified, so
    adding or reworking a field never forced the question "does this reach a
    result?".  The baseline turns that fallback into a closed list: it may
    shrink as leaves get wired or deleted, and nothing new may join it.
    """

    #: The pending set on the day this gate landed.  The live baseline is
    #: asserted to be a subset of it, so the list can never be refreshed with
    #: new debt -- only entries present on landing day may remain.
    LANDING_SNAPSHOT = frozenset(_PENDING_AUDIT_LANDING_SNAPSHOT)

    #: A group whose leaves are computed, must affect a result, and are not
    #: proven -- the shape a genuinely new business field arrives in.
    UNPROVEN_GROUP_PREFIX = "state_refs"
    #: A group that is adjudicated independent, so new leaves classify without
    #: anyone being asked.
    INDEPENDENT_GROUP_PREFIX = "source.input_files"

    def setUp(self):
        self.contract = load_contract()
        self.inventory = static_inventory()
        self.paths = self.inventory["analysis_input_paths"]
        self.derived_null = tuple(self.inventory["producer_constant_null_leaves"])
        self.effects = leaf_effects(self.contract, self.inventory)
        self.baseline = self.contract["unclassified_pending_audit_baseline"]

    def _classify(self, contract, paths, derived_null=None):
        return effect_contract_module._leaf_effect_map(
            contract, paths,
            self.derived_null if derived_null is None else derived_null)

    def test_the_baseline_is_exactly_todays_unclassified_remainder(self):
        pending = {path for path, category in self.effects.items()
                   if category == "unclassified_pending_audit"}
        self.assertEqual(set(self.baseline), pending)
        self.assertEqual(self.baseline, sorted(set(self.baseline)))

    def test_the_baseline_may_only_shrink_from_the_landing_snapshot(self):
        added = sorted(set(self.baseline) - self.LANDING_SNAPSHOT)
        self.assertEqual(added, [], "the frozen debt list may not gain members")

    def test_a_new_computed_leaf_must_be_adjudicated_when_it_arrives(self):
        new_leaf = f"{self.UNPROVEN_GROUP_PREFIX}.invented_business_field"
        self.assertNotIn(new_leaf, self.paths)
        with self.assertRaises(ValueError) as caught:
            self._classify(self.contract, self.paths + [new_leaf])
        self.assertIn(new_leaf, str(caught.exception))
        self.assertIn("leaf_effect_overrides", str(caught.exception))

    def test_the_baseline_is_what_refuses_the_new_leaf(self):
        """Control: same input, gate opened -- the leaf classifies, no raise."""
        new_leaf = f"{self.UNPROVEN_GROUP_PREFIX}.invented_business_field"
        opened = copy.deepcopy(self.contract)
        opened["unclassified_pending_audit_baseline"] = sorted(
            set(self.baseline) | {new_leaf})
        effects = self._classify(opened, self.paths + [new_leaf])
        self.assertEqual(effects[new_leaf], "unclassified_pending_audit")

    def test_a_leaf_that_stops_being_producer_null_must_be_adjudicated(self):
        target = next(path for path in self.derived_null
                      if self.effects[path] == "producer_constant_null"
                      and path not in self.contract["leaf_effect_overrides"])
        shrunk = tuple(path for path in self.derived_null if path != target)
        with self.assertRaises(ValueError) as caught:
            self._classify(self.contract, self.paths, derived_null=shrunk)
        self.assertIn(target, str(caught.exception))

    def test_a_new_leaf_that_classifies_mechanically_is_not_asked_about(self):
        independent_leaf = f"{self.INDEPENDENT_GROUP_PREFIX}.invented_lineage_note"
        effects = self._classify(self.contract, self.paths + [independent_leaf])
        self.assertIn(effects[independent_leaf],
                      {"duplicate_or_display_audit", "intentionally_independent_or_delete"})
        null_leaf = f"{self.UNPROVEN_GROUP_PREFIX}.invented_null_field"
        effects = self._classify(self.contract, self.paths + [null_leaf],
                                 derived_null=self.derived_null + (null_leaf,))
        self.assertEqual(effects[null_leaf], "producer_constant_null")

    def test_a_wired_leaf_may_not_stay_on_the_baseline(self):
        target = self.baseline[0]
        wired = copy.deepcopy(self.contract)
        wired["leaf_effect_overrides"][target] = {"category": "true_dangling"}
        error = static_contract_error(wired, inventory=self.inventory) or ""
        self.assertIn("may only shrink", error)
        self.assertIn(target, error)

    def test_a_deleted_leaf_may_not_stay_on_the_baseline(self):
        stale = copy.deepcopy(self.contract)
        stale["unclassified_pending_audit_baseline"] = sorted(
            set(self.baseline) | {"candidates[].removed_last_release"})
        error = static_contract_error(stale, inventory=self.inventory) or ""
        self.assertIn("may only shrink", error)
        self.assertIn("candidates[].removed_last_release", error)

    def test_a_leaf_turned_constant_null_may_not_stay_on_the_baseline(self):
        target = self.baseline[0]
        inventory = dict(self.inventory)
        inventory["producer_constant_null_leaves"] = list(self.derived_null) + [target]
        error = static_contract_error(self.contract, inventory=inventory) or ""
        self.assertIn("may only shrink", error)
        self.assertIn(target, error)

    def test_the_baseline_must_stay_sorted_and_duplicate_free(self):
        churned = copy.deepcopy(self.contract)
        churned["unclassified_pending_audit_baseline"] = list(reversed(self.baseline))
        self.assertIn("sorted and duplicate-free",
                      static_contract_error(churned, inventory=self.inventory) or "")
        duplicated = copy.deepcopy(self.contract)
        duplicated["unclassified_pending_audit_baseline"] = self.baseline + [self.baseline[0]]
        self.assertIn("sorted and duplicate-free",
                      static_contract_error(duplicated, inventory=self.inventory) or "")

    def test_new_debt_cannot_be_booked_through_an_explicit_override(self):
        """The fallback gate is not the only door: an override outranks it."""
        target = next(path for path, category in self.effects.items()
                      if category != "unclassified_pending_audit"
                      and path not in self.contract["leaf_effect_overrides"])
        booked = copy.deepcopy(self.contract)
        booked["leaf_effect_overrides"][target] = {"category": "unclassified_pending_audit"}
        error = static_contract_error(booked, inventory=self.inventory) or ""
        self.assertIn("baseline does not list", error)
        self.assertIn(target, error)
        # and the honest direction still passes
        self.assertIsNone(static_contract_error(self.contract, inventory=self.inventory))

    def test_a_missing_baseline_is_refused_rather_than_defaulted(self):
        absent = copy.deepcopy(self.contract)
        del absent["unclassified_pending_audit_baseline"]
        self.assertIn("unclassified_pending_audit_baseline",
                      static_contract_error(absent, inventory=self.inventory) or "")
        with self.assertRaises(ValueError):
            self._classify(absent, self.paths)


if __name__ == "__main__":
    unittest.main()
