"""Regression guards for the closed-world A-short M6.7 effect contract."""
from __future__ import annotations

import copy
import ast
import hashlib
import json
import sys
import unittest
import jsonschema
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_effect_contract import (  # noqa: E402
    load_contract, static_contract_error, static_inventory,
)
from engine import a_short_effect_contract as effect_contract_module  # noqa: E402
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


class EffectContractMemoTests(unittest.TestCase):
    def setUp(self):
        effect_contract_module._default_static_inventory_from_snapshot.cache_clear()
        effect_contract_module._contract_from_source.cache_clear()
        effect_contract_module._source_tree.cache_clear()
        effect_contract_module._predicate_hashes_for_source.cache_clear()
        effect_contract_module._constant_inventory_items.cache_clear()
        effect_contract_module._governed_python_literal_names_for_source.cache_clear()
        effect_contract_module._runtime_portfolio_policy_literal_violations_for_sources.cache_clear()
        effect_contract_module._string_assignment_items.cache_clear()
        effect_contract_module._operation_impact_sources_for_source.cache_clear()
        effect_contract_module._literal_string_assignment_values.cache_clear()

    def test_default_inventory_memo_reuses_same_snapshot_and_returns_copies(self):
        with patch.object(effect_contract_module, "_build_static_inventory",
                          wraps=effect_contract_module._build_static_inventory) as build:
            first = static_inventory()
            first["decision_predicate_sha256"]["A-EGS/egs_main.py"] = "mutated"
            second = static_inventory()
        self.assertEqual(build.call_count, 1)
        self.assertNotEqual(second["decision_predicate_sha256"]["A-EGS/egs_main.py"], "mutated")

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

    def test_override_reuses_unchanged_derived_analysis_but_recomputes_changed_source(self):
        portfolio_rel = "engine/a_short_portfolio_risk.py"
        portfolio = (ROOT / portfolio_rel).read_text(encoding="utf-8")
        changed = portfolio + "\n# derived-analysis-cache-probe\n"

        static_inventory(source_overrides={portfolio_rel: portfolio})
        baseline = effect_contract_module._predicate_hashes_for_source.cache_info()
        static_inventory(source_overrides={portfolio_rel: portfolio})
        same_override = effect_contract_module._predicate_hashes_for_source.cache_info()
        static_inventory(source_overrides={portfolio_rel: changed})
        changed_override = effect_contract_module._predicate_hashes_for_source.cache_info()

        self.assertEqual(same_override.misses, baseline.misses)
        self.assertGreater(same_override.hits, baseline.hits)
        self.assertEqual(changed_override.misses, same_override.misses + 1)


class EffectContractStaticTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_contract()

    def test_current_schema_fields_rules_thresholds_and_output_are_registered(self):
        self.assertIsNone(static_contract_error(self.contract))

    def test_ast_fingerprints_do_not_depend_on_cpython_dump_format(self):
        baseline = static_inventory()
        effect_contract_module._default_static_inventory_from_snapshot.cache_clear()
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

    def test_watch_pool_selector_predicate_cannot_escape_registration(self):
        rel = "engine/egs_industry_heat.py"
        source = (ROOT / rel).read_text(encoding="utf-8").replace(
            "if l2 in overflow and count >= 15:",
            "if l2 in overflow and count >= 16:",
            1,
        )
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

    def test_stale_governed_leaf_in_contract_body_cannot_hide_behind_updated_hashes(self):
        """Deleting a governed leaf must also delete every contract-body reader entry."""
        inventory = static_inventory()
        contract = copy.deepcopy(self.contract)
        rel = "presets/a_short_m67_runtime_policy_20260715.json"
        contract["runtime_policy_paths_sha256"] = inventory["runtime_policy_paths_sha256"]
        contract["runtime_policy_leaf_readers_sha256"] = hashlib.sha256(
            json.dumps(inventory["runtime_policy_leaf_readers"], ensure_ascii=False,
                       sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
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
        contract["runtime_policy_leaf_readers_sha256"] = hashlib.sha256(
            json.dumps(inventory["runtime_policy_leaf_readers"], ensure_ascii=False,
                       sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
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


class EffectContractRuntimeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
