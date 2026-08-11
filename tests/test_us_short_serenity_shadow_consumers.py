from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from engine import us_short_serenity_shadow_consumers as shadow
from engine import us_short_serenity_structural_theme_annotation as annotation_contract
from tests.test_us_short_serenity_structural_theme_annotation import _materialized_root


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "us_short_serenity_structural_theme_annotation_v0_1.json"


class SerenityShadowConsumerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def _active(self):
        # Blade3 owns identity validation; this test isolates the Blade4 routing matrix.
        with patch.object(annotation_contract, "validate_annotation", return_value=True):
            return shadow.consume_serenity_annotation(self.fixture)

    def test_active_routes_three_surfaces_and_preserves_identity(self):
        result = self._active()
        self.assertEqual(result["status"], "active")
        self.assertTrue(result["advisory_only"])
        self.assertFalse(result["main_task_should_abort"])
        expected = {
            "annotation_id": self.fixture["annotation_id"],
            "schema_version": self.fixture["schema_version"],
            "rubric_version": self.fixture["identity_envelope"]["rubric_version"],
            "upstream_decision_result_id": self.fixture["identity_envelope"]["upstream_decision_result_id"],
            "upstream_policy_version": self.fixture["identity_envelope"]["upstream_policy_version"],
            "upstream_decision_date": self.fixture["identity_envelope"]["upstream_decision_date"],
        }
        self.assertEqual(result["annotation_identity"], expected)
        for surface_name in (
            "structural_constraint_cluster_shadow",
            "us_short_relevance_hint",
            "us_long_research_candidate",
            "registered_report_block",
            "decision_trace",
        ):
            self.assertEqual(
                {key: result[surface_name][key] for key in expected},
                expected,
                surface_name,
            )
        self.assertEqual(
            result["structural_constraint_cluster_shadow"]["common_constraint_id"],
            "constraint:fixture-supply",
        )
        self.assertEqual(result["us_short_relevance_hint"]["status"], "advisory")
        self.assertEqual(result["us_long_research_candidate"]["status"], "candidate")
        self.assertFalse(result["us_short_relevance_hint"]["theme_removed"])
        self.assertFalse(result["us_short_relevance_hint"]["theme_downgraded"])
        self.assertFalse(result["us_short_relevance_hint"]["theme_migrated"])
        self.assertFalse(result["us_long_research_candidate"]["automatic_write"])
        self.assertFalse(result["us_long_research_candidate"]["us_long_write_performed"])

    def test_active_routes_through_real_blade3_validator(self):
        with _materialized_root(policy_version="soft_discovery_query_policy_v0.3.0") as (root, _):
            validator_options = {
                "root": root,
                "now": datetime(2026, 8, 10, tzinfo=timezone.utc),
            }
            result = shadow.consume_serenity_annotation(self.fixture, **validator_options)
        self.assertEqual(result["status"], "active")
        self.assertFalse(result["main_task_should_abort"])

    def test_report_overlay_uses_registered_sections_without_new_h2(self):
        result = self._active()
        report = (
            "# US-short weekly report\n\n"
            "## 诚实横幅\n"
            "- ④ price_clock: price_data_through=20260807 / news_window_through=20260807 / "
            "session_scope=RTH / decision_date=20260810\n\n"
            "## 12. 字段·模块生命周期提醒\n"
            "- lifecycle reminder\n\n"
            "## 13. 本周不 clean 项\n"
            "- offline boundary\n"
        )
        delivered = shadow.deliver_serenity_shadow_to_report(report, result)
        self.assertTrue(delivered["report_block_delivered"])
        self.assertFalse(delivered["main_task_should_abort"])
        rendered = delivered["report_text"]
        self.assertIn(result["registered_report_block"]["banner_line"], rendered)
        for line in result["registered_report_block"]["advisory_appendix_lines"]:
            self.assertIn(line, rendered)
        self.assertEqual(rendered.count("## "), report.count("## "))
        inserted = [
            line for line in rendered.splitlines()
            if line.startswith("- [us_short_serenity_structural_annotation_shadow]")
            or line.startswith("- structural_constraint_cluster_shadow:")
            or line.startswith("- us_short_relevance_hint:")
            or line.startswith("- us_long_research_candidate:")
        ]
        self.assertTrue(inserted)
        self.assertTrue(all(not line.startswith("## ") for line in inserted))

    def test_registered_overlay_is_fail_closed_but_does_not_abort_main_task(self):
        result = self._active()
        delivered = shadow.deliver_serenity_shadow_to_report("# no registered sections\n", result)
        self.assertFalse(delivered["report_block_delivered"])
        self.assertEqual(delivered["report_text"], "# no registered sections\n")
        self.assertFalse(delivered["main_task_should_abort"])
        self.assertIn("registered", delivered["report_block_problem"])

    def test_sleeping_week_does_not_validate_or_change_report_text(self):
        with patch.object(annotation_contract, "validate_annotation", side_effect=AssertionError("must not run")):
            result = shadow.consume_serenity_annotation(None)
        self.assertEqual(result["status"], "sleeping")
        self.assertIsNone(result["registered_report_block"])
        self.assertFalse(result["main_task_should_abort"])
        report = "# unchanged\n"
        delivered = shadow.deliver_serenity_shadow_to_report(report, result)
        self.assertEqual(delivered["report_text"], report)
        self.assertFalse(delivered["report_block_delivered"])
        self.assertIsNone(delivered["report_block_problem"])

    def test_version_mismatch_is_local_invalid_annotation(self):
        broken = copy.deepcopy(self.fixture)
        broken["schema_version"] = "9.9.9"
        with patch.object(annotation_contract, "validate_annotation", return_value=True):
            result = shadow.consume_serenity_annotation(broken)
        self.assertEqual(result["status"], "invalid_annotation")
        self.assertEqual(result["error"]["code"], "SERENITY_ANNOTATION_REJECTED")
        self.assertIsNone(result["structural_constraint_cluster_shadow"])
        self.assertIsNone(result["us_short_relevance_hint"])
        self.assertIsNone(result["us_long_research_candidate"])
        self.assertFalse(result["main_task_should_abort"])

    def test_effect_or_theme_mutation_is_rejected_by_output_contract(self):
        result = self._active()
        tampered = copy.deepcopy(result)
        tampered["structural_constraint_cluster_shadow"]["changes_selection_or_action"] = True
        with self.assertRaises(shadow.SerenityShadowConsumerError):
            shadow.render_registered_report_overlay("## 诚实横幅\n\n## 12. lifecycle\n", tampered)

        tampered = copy.deepcopy(result)
        tampered["effect_boundary"]["top15_effect_enabled"] = True
        with self.assertRaises(shadow.SerenityShadowConsumerError):
            shadow.render_registered_report_overlay("## 诚实横幅\n\n## 12. lifecycle\n", tampered)

    def test_duplicate_registered_block_is_rejected(self):
        result = self._active()
        report = (
            "## 诚实横幅\n"
            "- [us_short_serenity_structural_annotation_shadow] existing\n\n"
            "## 12. lifecycle\n"
        )
        with self.assertRaises(shadow.SerenityShadowConsumerError):
            shadow.render_registered_report_overlay(report, result)


if __name__ == "__main__":
    unittest.main()
