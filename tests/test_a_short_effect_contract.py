"""Regression guards for the closed-world A-short M6.7 effect contract."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_effect_contract import (  # noqa: E402
    load_contract, static_contract_error, static_inventory,
)
from runners.a_short_m67_render import render_weekly_markdown  # noqa: E402
from engine.a_short_industry_theme import classify_industry_trend  # noqa: E402
from engine.egs_industry_heat import load_governance  # noqa: E402
from runners.a_short_phase5_engine import build_m67_report  # noqa: E402
from runners.a_short_weekly_pipeline import (  # noqa: E402
    build_weekly_report, normalize_candidate, validate_weekly_report,
)
from tests.test_a_short_weekly_pipeline import (  # noqa: E402
    AS_OF, GEN, _egs_candidate, _feed, _normalized, _overlay_row, _series,
)


class EffectContractStaticTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_contract()

    def test_current_schema_fields_rules_thresholds_and_output_are_registered(self):
        self.assertIsNone(static_contract_error(self.contract))

    def test_ast_fingerprints_do_not_depend_on_cpython_dump_format(self):
        baseline = static_inventory()
        with patch("engine.a_short_effect_contract.ast.dump", side_effect=AssertionError("must not use ast.dump")):
            portable = static_inventory()
        self.assertEqual(portable["decision_predicate_sha256"], baseline["decision_predicate_sha256"])
        self.assertEqual(portable["runtime_constants_sha256"], baseline["runtime_constants_sha256"])

    def test_new_analysis_input_field_cannot_escape_registration(self):
        schema = json.loads((ROOT / "schemas" / "analysis_input.schema.json").read_text(encoding="utf-8"))
        schema["properties"]["future_effect_probe"] = {"type": "string"}
        error = static_contract_error(self.contract, inventory=static_inventory(analysis_schema=schema))
        self.assertIsNotNone(error)
        self.assertIn("coverage", error)

    def test_new_or_changed_decision_predicate_cannot_escape_registration(self):
        rel = "engine/a_short_portfolio_risk.py"
        source = (ROOT / rel).read_text(encoding="utf-8") + "\nif False:\n    pass\n"
        error = static_contract_error(self.contract, inventory=static_inventory(source_overrides={rel: source}))
        self.assertEqual(error, "decision predicate changed without effect contract update")

    def test_changed_runtime_threshold_cannot_escape_registration(self):
        rel = "presets/a_short_m67_runtime_policy_20260715.json"
        policy = (ROOT / rel).read_text(encoding="utf-8").replace(
            '"same_sw_l2_threshold_pct": 40.0', '"same_sw_l2_threshold_pct": 41.0', 1)
        error = static_contract_error(
            self.contract, inventory=static_inventory(runtime_policy_overrides={rel: policy}))
        self.assertEqual(error, "runtime policy value changed without effect contract update")

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

    def test_new_policy_field_still_fails_after_hashes_and_generic_binding_are_updated(self):
        """A broad section-level consumer note cannot pretend an unread leaf is wired."""
        rel = "presets/a_short_m67_runtime_policy_20260715.json"
        policy = (ROOT / rel).read_text(encoding="utf-8").replace(
            '"impact_cost_frac": 0.005', '"impact_cost_frac": 0.005, "future_threshold": 1', 1)
        inventory = static_inventory(runtime_policy_overrides={rel: policy})
        contract = copy.deepcopy(self.contract)
        contract["runtime_policy_paths_sha256"] = inventory["runtime_policy_paths_sha256"]
        contract["runtime_policy_sha256"] = inventory["runtime_policy_sha256"]
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
        contract["runtime_policy_paths_sha256"] = inventory["runtime_policy_paths_sha256"]
        contract["runtime_policy_sha256"] = inventory["runtime_policy_sha256"]
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
        text = (ROOT / rel).read_text(encoding="utf-8") + "\n"
        error = static_contract_error(self.contract, inventory=static_inventory(output_schema_overrides={rel: text}))
        self.assertEqual(error, "weekly/M6.7 output schema changed without effect contract update")

    def test_report_presence_cannot_be_declared_a_field_consumer(self):
        contract = copy.deepcopy(self.contract)
        group = next(row for row in contract["groups"] if row["id"] == "candidate_technical")
        group["runtime_handler"] = "upstream_candidate_set"
        group.pop("unresolved_reason")
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


class EffectContractRuntimeTests(unittest.TestCase):
    def test_weekly_json_markdown_and_validator_expose_unwired_or_independent_groups(self):
        weekly = build_weekly_report([_normalized()], AS_OF, GEN)
        records = {record["id"]: record for record in weekly["effect_contract_ledger"]["records"]}
        self.assertEqual(records["industry_trend"]["status"], "unavailable_manual_review")
        self.assertEqual(records["lineage_metadata"]["status"], "intentionally_independent")
        for group_id in ("candidate_technical", "candidate_fundamental", "candidate_capital_flow",
                         "candidate_catalyst", "candidate_volatility", "candidate_analyst",
                         "candidate_data_quality", "market_context", "account_context", "candidate_quote",
                         "candidate_industry_classification", "candidate_scores", "candidate_event_risk",
                         "candidate_liquidity", "portfolio_concentration_factor_resonance",
                         "candidate_derived_flags", "identity_batch_gate"):
            self.assertEqual(records[group_id]["status"], "unavailable_manual_review")
        self.assertEqual(weekly["effect_contract_ledger"]["summary"]["total"], len(records))
        markdown = render_weekly_markdown(weekly)
        self.assertIn("字段/规则联动台账", markdown)
        self.assertIn("industry_trend=unknown (fail-closed; manual review, no star adjustment)", markdown)
        self.assertIn("不得因候选存在而误报已联动", markdown)

        tampered = copy.deepcopy(weekly)
        next(row for row in tampered["effect_contract_ledger"]["records"]
             if row["id"] == "industry_trend")["status"] = "applied"
        with self.assertRaises(ValueError):
            validate_weekly_report(tampered, _feed())

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


if __name__ == "__main__":
    unittest.main()
