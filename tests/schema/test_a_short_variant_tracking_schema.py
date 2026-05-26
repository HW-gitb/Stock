from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/a_short_variant_tracking.schema.json")
EXAMPLE_PATH = Path("schemas/examples/a_short_variant_tracking.example.json")


class AShortVariantTrackingSchemaTest(unittest.TestCase):
    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "a_short_variant_tracking")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertIn("six bounded A-short variant families", schema["description"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["required"],
            [
                "schema_name",
                "schema_version",
                "generated_at",
                "scope",
                "baseline",
                "variant_families",
                "evidence_policy",
                "promotion_policy",
                "data_boundaries",
                "limitations",
            ],
        )

    def test_variant_family_set_is_exact_and_tracking_only(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        variant_families = schema["$defs"]["variantFamilies"]
        self.assertEqual(
            variant_families["required"],
            [
                "chasing_high_veto",
                "overheat_veto",
                "tier1_only_trading",
                "esp_cap_or_winsorize",
                "rank_bucket_split",
                "exit_policy_variants",
            ],
        )
        self.assertFalse(variant_families["additionalProperties"])

        scope = schema["$defs"]["scope"]
        self.assertEqual(scope["properties"]["contract_status"]["const"], "tracking_contract_only")

        variant_family = schema["$defs"]["variantFamily"]
        self.assertEqual(variant_family["properties"]["track_status"]["const"], "tracking_only")
        self.assertEqual(
            variant_family["properties"]["comparison_baseline"]["const"],
            "steady_a_short_baseline",
        )
        self.assertEqual(variant_family["properties"]["promotion_rule_ref"]["const"], "promotion_policy")

    def test_shutdown_threshold_note_is_independent_from_benchmark_switch(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        shutdown_policy = schema["$defs"]["promotionPolicy"]["properties"][
            "shutdown_after_consecutive_underperformance"
        ]
        self.assertEqual(shutdown_policy["const"], 6)
        self.assertIn("independent", shutdown_policy["description"])
        self.assertIn("benchmark primary-switch", shutdown_policy["description"])

    def test_boundaries_prevent_scope_creep(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        data_boundaries = schema["$defs"]["dataBoundaries"]["properties"]
        self.assertEqual(data_boundaries["mutates_egs"]["const"], False)
        self.assertEqual(data_boundaries["mutates_phase3_hard_veto"]["const"], False)
        self.assertEqual(data_boundaries["implements_burst_lane"]["const"], False)
        self.assertEqual(data_boundaries["manual_order_only"]["const"], True)
        self.assertEqual(data_boundaries["requires_p0a_capital_context"]["const"], True)

        evidence_policy = schema["$defs"]["evidencePolicy"]["properties"]
        self.assertEqual(
            evidence_policy["source"]["const"],
            "pre_outcome_live_captured_analysis_input",
        )
        self.assertEqual(evidence_policy["backtest_only_promotion_allowed"]["const"], False)
        self.assertEqual(evidence_policy["benchmark_sensitivity_required"]["const"], True)

    def test_example_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        errors = list(Draft7Validator(schema).iter_errors(example))

        self.assertEqual(errors, [])

    def test_missing_required_variant_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["variant_families"].pop("overheat_veto")
        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertTrue(any("overheat_veto" in error.message for error in errors))

    def test_extra_variant_family_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["variant_families"]["new_alpha_variant"] = copy.deepcopy(
            invalid["variant_families"]["overheat_veto"]
        )
        invalid["variant_families"]["new_alpha_variant"]["id"] = "new_alpha_variant"
        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertTrue(any("new_alpha_variant" in error.message for error in errors))

    def test_wrong_variant_id_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["variant_families"]["overheat_veto"]["id"] = "chasing_high_veto"
        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertTrue(any("overheat_veto" in error.schema_path for error in errors))

    def test_non_tracking_status_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(example)
        invalid["variant_families"]["overheat_veto"]["track_status"] = "promotion_candidate"
        errors = list(Draft7Validator(schema).iter_errors(invalid))

        self.assertTrue(any("tracking_only" in error.message for error in errors))


if __name__ == "__main__":
    unittest.main()
