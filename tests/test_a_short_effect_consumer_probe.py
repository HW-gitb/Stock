from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from engine.a_short_effect_consumer_probe import (
    ConsumerProbeError,
    build_consumer_probe,
    validate_consumer_probe,
)
from engine.a_short_effect_contract import (
    build_effect_contract_ledger,
    leaf_effects,
    leaf_natures,
    load_contract,
    static_contract_error,
    static_inventory,
    validate_unavailable_manual_review_trend,
)
from runners.a_short_weekly_pipeline import (
    _bind_effect_contract_trend_guard,
    validate_weekly_report,
)
from tests.test_a_short_weekly_pipeline import AS_OF, GEN, _feed, _normalized
from runners.a_short_weekly_pipeline import build_weekly_report


class AShortNatureLedgerTests(unittest.TestCase):
    def test_all_analysis_input_leaves_have_explicit_nature(self):
        natures = leaf_natures()
        self.assertEqual(len(natures), 388)
        self.assertEqual(set(natures.values()), {
            "true_dangling", "partial_consumption", "display_audit",
            "main_decision", "comparison_track", "duplicate_source",
        })
        self.assertEqual(sum(1 for _ in natures), 388)

    def test_missing_or_bulk_independent_relabel_fails_closed(self):
        contract = load_contract()
        del contract["leaf_nature_by_group"]["candidate_event_risk"]
        error = static_contract_error(contract, inventory=static_inventory())
        self.assertIn("nature", error)

        contract = load_contract()
        contract["leaf_nature_by_group"]["candidate_event_risk"] = "display_audit"
        error = static_contract_error(contract, inventory=static_inventory())
        self.assertIn("requires intentionally_independent policy", error)

        contract = load_contract()
        contract["leaf_nature_by_group"]["candidate_event_risk"] = "main_decision"
        error = static_contract_error(contract, inventory=static_inventory())
        self.assertIn("requires runtime_handler", error)

        contract = load_contract()
        contract["leaf_nature_by_group"]["industry_trend"] = "true_dangling"
        error = static_contract_error(contract, inventory=static_inventory())
        self.assertIn("requires runtime_handler", error)

    def test_ledger_records_leaf_natures_and_388_leaf_summary(self):
        weekly = {"as_of": "20260727"}
        ledger = build_effect_contract_ledger(weekly)
        self.assertEqual(sum(ledger["summary"]["nature_counts"].values()), 388)
        group = next(row for row in ledger["records"] if row["id"] == "candidate_event_risk")
        # rule6_checks[].status already reaches Phase5, so the leftover group is
        # partially consumed -- not wholly dangling.
        self.assertEqual(group["nature"], "partial_consumption")
        self.assertTrue(group["leaf_natures"])
        track = next(row for row in ledger["records"] if row["id"] == "candidate_data_quality_shadow")
        self.assertEqual(track["nature"], "comparison_track")

    def test_leaf_effect_categories_are_explicit_and_proof_bound(self):
        effects = leaf_effects()
        self.assertEqual(len(effects), 388)
        # true_dangling is now an adjudicated label reachable only through an
        # explicit override; the un-audited remainder is pending, not dangling.
        self.assertLessEqual(set(effects.values()), {
            "m67_main_decision", "formal_comparison_verdict",
            "upstream_candidate_set_or_rank", "duplicate_or_display_audit",
            "intentionally_independent_or_delete", "producer_constant_null",
            "true_dangling", "unclassified_pending_audit",
        })
        self.assertIn("unclassified_pending_audit", set(effects.values()))
        self.assertEqual(effects["candidates[].scores.final_score"],
                         "upstream_candidate_set_or_rank")
        self.assertEqual(effects["market_context.market_regime.status"],
                         "m67_main_decision")
        self.assertEqual(effects["candidates[].analyst.target_price_mean"],
                         "producer_constant_null")
        self.assertEqual(effects["schema_version"],
                         "intentionally_independent_or_delete")
        ledger = build_effect_contract_ledger({"as_of": "20260801"})
        self.assertEqual(sum(ledger["summary"]["effect_counts"].values()), 388)
        self.assertIsInstance(ledger["records"][0]["leaf_effects"], dict)

    def test_unavailable_manual_review_trend_only_allows_flat_or_lower(self):
        previous = {"summary": {"unavailable_manual_review": 21}}
        current = {"summary": {"unavailable_manual_review": 20}}
        validate_unavailable_manual_review_trend(previous, current)
        validate_unavailable_manual_review_trend(previous, {"summary": {"unavailable_manual_review": 21}})
        with self.assertRaisesRegex(ValueError, "trend regressed"):
            validate_unavailable_manual_review_trend(previous, {"summary": {"unavailable_manual_review": 22}})

    def test_weekly_validator_runs_trend_guard_and_records_explicit_bootstrap_skip(self):
        weekly = build_weekly_report([_normalized()], AS_OF, GEN)
        self.assertEqual(weekly["effect_contract_ledger"]["trend_guard"]["status"],
                         "skipped_no_prior_ledger")
        validate_weekly_report(weekly, _feed())

        previous = {"as_of": "20260726", "summary": {"unavailable_manual_review": 0}}
        guard = copy.deepcopy(weekly["effect_contract_ledger"]["trend_guard"])
        guard.update({
            "status": "checked",
            "previous_as_of": previous["as_of"],
            "previous_unavailable_manual_review": 0,
            "reason": "test previous published ledger",
        })
        from engine.a_short_effect_contract import build_effect_contract_ledger
        weekly["effect_contract_ledger"] = build_effect_contract_ledger(
            weekly, trend_guard=guard)
        with self.assertRaisesRegex(ValueError, "trend regressed"):
            validate_weekly_report(weekly, _feed(), previous_ledger=previous)

    def test_production_binding_resolves_latest_prior_canonical_ledger(self):
        weekly = build_weekly_report([_normalized()], AS_OF, GEN)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prior_as_of = "20260608"
            prior_dir = root / prior_as_of
            current_dir = root / AS_OF
            prior_dir.mkdir()
            current_dir.mkdir()
            prior_ledger = build_effect_contract_ledger({"as_of": prior_as_of})
            prior_ledger["summary"]["unavailable_manual_review"] = 999
            (prior_dir / "weekly_m67.json").write_text(
                json.dumps({"as_of": prior_as_of, "effect_contract_ledger": prior_ledger}),
                encoding="utf-8",
            )
            previous = _bind_effect_contract_trend_guard(
                weekly, current_dir / "weekly_m67.json")
            self.assertEqual(previous["as_of"], prior_as_of)
            self.assertEqual(
                weekly["effect_contract_ledger"]["trend_guard"]["status"],
                "checked",
            )
            validate_weekly_report(weekly, _feed(), previous_ledger=previous)

    def test_pre_effect_legacy_prior_report_is_an_explicit_bootstrap_skip(self):
        weekly = build_weekly_report([_normalized()], AS_OF, GEN)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prior_dir = root / "20260608"
            current_dir = root / AS_OF
            prior_dir.mkdir()
            current_dir.mkdir()
            (prior_dir / "weekly_m67.json").write_text(
                json.dumps({"as_of": "20260608", "reports": []}), encoding="utf-8"
            )
            previous = _bind_effect_contract_trend_guard(
                weekly, current_dir / "weekly_m67.json"
            )
            self.assertIsNone(previous)
            guard = weekly["effect_contract_ledger"]["trend_guard"]
            self.assertEqual(guard["status"], "skipped_no_prior_ledger")
            self.assertIsNone(guard["previous_as_of"])
            self.assertIn("pre-effect-contract legacy", guard["reason"])
            validate_weekly_report(weekly, _feed())

    def test_pre_effect_legacy_report_is_skipped_before_an_older_valid_ledger(self):
        weekly = build_weekly_report([_normalized()], AS_OF, GEN)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_dir = root / "20260629"
            valid_dir = root / "20260608"
            current_dir = root / AS_OF
            legacy_dir.mkdir()
            valid_dir.mkdir()
            current_dir.mkdir()
            (legacy_dir / "weekly_m67.json").write_text(
                json.dumps({"as_of": "20260629", "reports": []}), encoding="utf-8"
            )
            prior_ledger = build_effect_contract_ledger({"as_of": "20260608"})
            prior_ledger["summary"]["unavailable_manual_review"] = 999
            (valid_dir / "weekly_m67.json").write_text(
                json.dumps({"as_of": "20260608", "effect_contract_ledger": prior_ledger}),
                encoding="utf-8",
            )
            previous = _bind_effect_contract_trend_guard(
                weekly, current_dir / "weekly_m67.json"
            )
            self.assertIsNotNone(previous)
            self.assertEqual(previous["as_of"], "20260608")
            self.assertEqual(
                weekly["effect_contract_ledger"]["trend_guard"]["status"], "checked"
            )
            self.assertEqual(
                weekly["effect_contract_ledger"]["trend_guard"]["previous_as_of"], "20260608"
            )
            validate_weekly_report(weekly, _feed(), previous_ledger=previous)

    def test_present_but_malformed_prior_ledger_still_fails_closed(self):
        weekly = build_weekly_report([_normalized()], AS_OF, GEN)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prior_dir = root / "20260608"
            current_dir = root / AS_OF
            prior_dir.mkdir()
            current_dir.mkdir()
            (prior_dir / "weekly_m67.json").write_text(
                json.dumps({"as_of": "20260608", "effect_contract_ledger": None}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing or date-mismatched"):
                _bind_effect_contract_trend_guard(weekly, current_dir / "weekly_m67.json")

    def test_missing_shadow_is_rejected_by_validator(self):
        weekly = build_weekly_report([_normalized()], AS_OF, GEN)
        weekly.pop("data_quality_shadow")
        with self.assertRaises(ValueError):
            validate_weekly_report(weekly, _feed())

    def test_missing_shadow_is_rejected_by_weekly_schema(self):
        weekly = build_weekly_report([_normalized()], AS_OF, GEN)
        weekly.pop("data_quality_shadow")
        schema = json.loads((Path(__file__).resolve().parents[1]
                             / "schemas" / "a_short_weekly_report.schema.json").read_text(encoding="utf-8"))
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(weekly, schema)


class AShortConsumerProbeTests(unittest.TestCase):
    def test_three_selected_leaf_chains_are_source_bound_and_shadow_only(self):
        payload = build_consumer_probe()
        self.assertEqual(payload["probe_status"], "feasible_probe_pass")
        self.assertFalse(payload["production_effect_enabled"])
        self.assertEqual({row["id"] for row in payload["probes"]}, {
            "crash_veto_to_negative_event",
            "industry_trend_to_star",
            "data_quality_to_shadow_verdict",
        })
        validate_consumer_probe(payload)

    def test_negative_control_removing_crash_veto_consumer_fails(self):
        from pathlib import Path

        path = Path("runners/a_short_weekly_pipeline.py")
        source = path.read_text(encoding="utf-8")
        mutated = source.replace('d.get("has_crash_veto")', 'd.get("future_probe_flag")', 1)
        with self.assertRaisesRegex(ConsumerProbeError, "crash_veto_to_negative_event"):
            build_consumer_probe({"runners/a_short_weekly_pipeline.py": mutated})

    def test_negative_control_tampered_terminal_kind_fails_schema(self):
        payload = copy.deepcopy(build_consumer_probe())
        next(row for row in payload["probes"] if row["id"] == "data_quality_to_shadow_verdict")["terminal_kind"] = "production"
        with self.assertRaises(Exception):
            validate_consumer_probe(payload)


if __name__ == "__main__":
    unittest.main()
