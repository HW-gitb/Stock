from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_data_quality_shadow import (  # noqa: E402
    build_data_quality_shadow,
    classify_data_quality_shadow,
    validate_data_quality_shadow,
)
from runners.a_short_m67_render import render_weekly_markdown  # noqa: E402
from runners.a_short_weekly_pipeline import build_weekly_report  # noqa: E402
from tests.test_a_short_weekly_pipeline import AS_OF, GEN, _feed, _normalized  # noqa: E402


class DataQualityShadowTests(unittest.TestCase):
    def _quality(self, **overrides):
        payload = {
            "completeness_score": 1.0,
            "missing_fields": [],
            "pending_fields": [],
            "rule11_required": [],
        }
        payload.update(overrides)
        return payload

    def _weekly(self, quality):
        normalized = _normalized()
        normalized["data_quality"] = quality
        return build_weekly_report([normalized], AS_OF, GEN)

    def test_each_quality_leaf_has_a_shadow_outcome(self):
        self.assertEqual(classify_data_quality_shadow(self._quality())["status"], "clean")
        self.assertEqual(
            classify_data_quality_shadow(
                self._quality(missing_fields=["technical.atr.atr_14"])
            )["status"], "block")
        self.assertEqual(
            classify_data_quality_shadow(self._quality(completeness_score=0.9))["status"],
            "degrade",
        )
        self.assertEqual(
            classify_data_quality_shadow(self._quality(pending_fields=["future.review"]))["status"],
            "warn",
        )
        self.assertEqual(classify_data_quality_shadow(None)["status"], "block")

    def test_shadow_mutation_changes_formal_comparison_but_not_action_or_shares(self):
        clean = self._weekly(self._quality())
        blocked = self._weekly(self._quality(missing_fields=["technical.atr.atr_14"]))
        self.assertEqual(clean["data_quality_shadow"]["verdict"]["observed_outcome"], "clean_observed")
        self.assertEqual(blocked["data_quality_shadow"]["verdict"]["observed_outcome"], "block_observed")
        self.assertNotEqual(clean["data_quality_shadow"], blocked["data_quality_shadow"])
        self.assertEqual(clean["reports"][0]["m67"]["table"]["操作"], blocked["reports"][0]["m67"]["table"]["操作"])
        self.assertEqual(clean["reports"][0]["m67"]["table"]["股数"], blocked["reports"][0]["m67"]["table"]["股数"])
        self.assertFalse(blocked["data_quality_shadow"]["production_effect_enabled"])
        validate_data_quality_shadow(blocked["data_quality_shadow"], expected_as_of=AS_OF)

    def test_complete_technical_quality_no_longer_blocks_but_shadow_stays_disabled(self):
        shadow = build_data_quality_shadow(
            [{"ts_code": "600000.SH", "data_quality": self._quality()}],
            AS_OF,
        )
        self.assertEqual(shadow["verdict"]["observed_outcome"], "clean_observed")
        self.assertEqual(shadow["policy"]["activation"], "disabled_pending_shadow_review")
        self.assertTrue(shadow["comparison_only"])
        self.assertFalse(shadow["production_effect_enabled"])
        validate_data_quality_shadow(shadow, expected_as_of=AS_OF)

    def test_unavailable_classifications_are_visible_without_changing_shadow_action(self):
        missing = [
            "capital_flow.northbound",
            "capital_flow.block_trade",
            "analyst.target_price_mean",
        ]
        base_quality = self._quality(missing_fields=missing)
        classified_quality = self._quality(
            missing_fields=missing,
            permanently_unavailable=["capital_flow.northbound"],
            paid_source_declined=["analyst.target_price_mean"],
            candidate_output_deferred=["capital_flow.block_trade"],
        )
        base_result = classify_data_quality_shadow(base_quality)
        classified_result = classify_data_quality_shadow(classified_quality)
        self.assertEqual(classified_result["status"], base_result["status"])
        self.assertEqual(classified_result["block"], base_result["block"])
        self.assertEqual(classified_result["degrade"], base_result["degrade"])
        self.assertEqual(classified_result["warn"], base_result["warn"])
        self.assertEqual(classified_result["permanently_unavailable"], [
            "capital_flow.northbound",
        ])
        self.assertEqual(classified_result["paid_source_declined"], [
            "analyst.target_price_mean",
        ])
        self.assertEqual(classified_result["candidate_output_deferred"], [
            "capital_flow.block_trade",
        ])

        base_weekly = self._weekly(base_quality)
        classified_weekly = self._weekly(classified_quality)
        self.assertEqual(
            base_weekly["reports"][0]["m67"]["table"]["操作"],
            classified_weekly["reports"][0]["m67"]["table"]["操作"],
        )
        self.assertEqual(
            base_weekly["reports"][0]["m67"]["table"]["股数"],
            classified_weekly["reports"][0]["m67"]["table"]["股数"],
        )
        shadow = build_data_quality_shadow(
            [{"ts_code": "600000.SH", "data_quality": classified_quality}],
            AS_OF,
        )
        self.assertEqual(shadow["schema_version"], "1.1.0")
        row = shadow["candidates"][0]
        self.assertEqual(row["permanently_unavailable"], ["capital_flow.northbound"])
        self.assertEqual(row["paid_source_declined"], ["analyst.target_price_mean"])
        self.assertEqual(row["candidate_output_deferred"], ["capital_flow.block_trade"])
        validate_data_quality_shadow(shadow, expected_as_of=AS_OF)

    def test_warn_and_degrade_are_visible_without_production_effect(self):
        base = self._weekly(self._quality())
        degraded = self._weekly(self._quality(completeness_score=0.9))
        warned = self._weekly(self._quality(pending_fields=["future.review"]))
        for weekly in (degraded, warned):
            self.assertFalse(weekly["data_quality_shadow"]["production_effect_enabled"])
            self.assertEqual(weekly["reports"][0]["m67"]["table"]["操作"], base["reports"][0]["m67"]["table"]["操作"])
        markdown = render_weekly_markdown(warned)
        self.assertIn("data_quality shadow comparison", markdown)
        self.assertIn("warn=1", markdown)

    def test_shadow_validator_rejects_tampered_summary(self):
        payload = build_data_quality_shadow([{"ts_code": "600000.SH", "data_quality": self._quality()}], AS_OF)
        tampered = copy.deepcopy(payload)
        tampered["summary"]["clean_count"] = 0
        with self.assertRaises(ValueError):
            validate_data_quality_shadow(tampered, expected_as_of=AS_OF)

    def test_missing_shadow_is_not_a_silent_legacy_fixture(self):
        with self.assertRaisesRegex(ValueError, "required"):
            validate_data_quality_shadow(None, expected_as_of=AS_OF)

    def test_empty_shadow_is_a_real_no_candidates_verdict(self):
        payload = build_data_quality_shadow([], AS_OF)
        self.assertEqual(payload["verdict"]["observed_outcome"], "no_candidates")
        validate_data_quality_shadow(payload, expected_as_of=AS_OF)


if __name__ == "__main__":
    unittest.main()
