from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft7Validator

from engine import us_short_serenity_quality_forward as quality
from engine import us_short_serenity_structural_theme_annotation as annotation_contract
from tests.test_us_short_serenity_quality_forward import SerenityQualityForwardTest


ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


class SerenityQualityForwardSchemaTest(unittest.TestCase):
    def test_policy_and_review_schema_are_closed_and_match_frozen_constants(self):
        policy = quality.load_quality_policy()
        policy_errors = list(Draft7Validator(_schema("us_short_serenity_quality_forward_policy.schema.json")).iter_errors(policy))
        self.assertEqual(policy_errors, [])
        metric_ids = tuple(item["metric_id"] for item in policy["metrics"])
        self.assertEqual(metric_ids, quality.METRIC_IDS)
        broken = copy.deepcopy(policy)
        broken["frozen_window"]["minimum_pass_rate"] = 0.7
        self.assertTrue(list(Draft7Validator(_schema("us_short_serenity_quality_forward_policy.schema.json")).iter_errors(broken)))

    def test_observation_ledger_and_gate_outputs_validate_as_closed_artifacts(self):
        case = SerenityQualityForwardTest("test_valid_annotation_and_review_bind_identity_and_create_eligible_observation")
        case.setUpClass()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                result = case._run(
                    root,
                    "20260810",
                    annotation=case.fixture,
                    review=case._review(case.fixture, "20260810"),
                )
            for name, value in (
                ("us_short_serenity_quality_forward_observation.schema.json", result["observation"]),
                ("us_short_serenity_quality_forward_ledger.schema.json", result["ledger"]),
                ("us_short_serenity_quality_gate_result.schema.json", result["quality_gate"]),
            ):
                self.assertEqual(list(Draft7Validator(_schema(name)).iter_errors(value)), [], name)
            self.assertTrue(all(value is False for value in result["observation"]["effects"].values()))
            self.assertTrue(all(value is False for value in result["ledger"]["effects"].values()))
            self.assertTrue(all(value is False for value in result["quality_gate"]["effects"].values()))

    def test_closed_output_rejects_extra_field_and_effect_flip(self):
        case = SerenityQualityForwardTest("test_valid_annotation_and_review_bind_identity_and_create_eligible_observation")
        case.setUpClass()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                observation = case._run(
                    root,
                    "20260810",
                    annotation=case.fixture,
                    review=case._review(case.fixture, "20260810"),
                )["observation"]
            extra = copy.deepcopy(observation)
            extra["unregistered"] = True
            self.assertTrue(list(Draft7Validator(_schema("us_short_serenity_quality_forward_observation.schema.json")).iter_errors(extra)))
            effect = copy.deepcopy(observation)
            effect["effects"]["scoring_eligible"] = True
            self.assertTrue(list(Draft7Validator(_schema("us_short_serenity_quality_forward_observation.schema.json")).iter_errors(effect)))


if __name__ == "__main__":
    unittest.main()
