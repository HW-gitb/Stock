from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft7Validator

from engine import us_short_serenity_quality_forward as quality
from engine import us_short_serenity_structural_theme_annotation as annotation_contract


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "us_short_serenity_structural_theme_annotation_v0_1.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _review(annotation, decision_date):
    identity = {
        "annotation_id": annotation["annotation_id"],
        "schema_version": annotation["schema_version"],
        "rubric_version": annotation["identity_envelope"]["rubric_version"],
        "upstream_decision_result_id": annotation["identity_envelope"]["upstream_decision_result_id"],
        "upstream_policy_version": annotation["identity_envelope"]["upstream_policy_version"],
        "upstream_decision_date": annotation["identity_envelope"]["upstream_decision_date"],
        "annotation_author_kind": annotation["identity_envelope"]["annotation_author_kind"],
        "annotation_prompt_version": annotation["identity_envelope"]["prompt_or_protocol_id"],
        "producer_model_identity": annotation["identity_envelope"]["model_identity"],
    }
    return {
        "schema_name": "us_short_serenity_quality_review",
        "schema_version": "1.0.0",
        "decision_date": decision_date,
        "quality_policy_version": quality.QUALITY_POLICY_VERSION,
        "consumer_version": quality.CONSUMER_VERSION,
        "reviewer_kind": "human",
        "reviewed_at": "2026-08-10T08:00:00+00:00",
        "reviewer_identity": {
            "identity_version": quality.REVIEWER_IDENTITY_VERSION,
            "reviewer_id": "claude_code_quality_reviewer",
            "model_identity": "claude-code-reviewer-v0.1.0",
            "prompt_version": quality.REVIEW_PROMPT_VERSION,
        },
        "review_scope": {
            "source_bound_only": True,
            "future_returns_viewed": False,
            "selection_results_viewed": False,
            "operation_advice_viewed": False,
        },
        "annotation_identity": identity,
        "metrics": [
            {
                "metric_id": metric_id,
                "verdict": "pass",
                "rationale": f"observed judgment for {metric_id}",
                "evidence_ref_ids": [f"review:{metric_id}"],
            }
            for metric_id in quality.METRIC_IDS
        ],
    }


def _run(root, decision_date, *, annotation, review):
    state = root / "state" / "us_short"
    state.mkdir(parents=True, exist_ok=True)
    annotation_path = state / "annotation.json"
    review_path = state / "review.json"
    observation_path = state / f"observation_{decision_date}.json"
    ledger_path = state / "ledger.json"
    gate_path = state / f"gate_{decision_date}.json"
    annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    return quality.run_quality_forward(
        annotation_path=annotation_path,
        review_path=review_path,
        observation_path=observation_path,
        ledger_path=ledger_path,
        gate_path=gate_path,
        decision_date=decision_date,
        observed_at="2026-08-10T08:00:00+00:00",
        root=root,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )


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
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                result = _run(
                    root,
                    "20260810",
                    annotation=FIXTURE,
                    review=_review(FIXTURE, "20260810"),
                )
            for name, value in (
                ("us_short_serenity_quality_forward_observation.schema.json", result["observation"]),
                ("us_short_serenity_quality_forward_ledger.schema.json", result["ledger"]),
                ("us_short_serenity_quality_gate_result.schema.json", result["quality_gate"]),
                ("us_short_serenity_g1_blade6_preflight.schema.json", result["g1_blade6_preflight"]),
            ):
                self.assertEqual(list(Draft7Validator(_schema(name)).iter_errors(value)), [], name)
            self.assertTrue(all(value is False for value in result["observation"]["effects"].values()))
            self.assertTrue(all(value is False for value in result["ledger"]["effects"].values()))
            self.assertTrue(all(value is False for value in result["quality_gate"]["effects"].values()))
            self.assertTrue(all(value is False for value in result["g1_blade6_preflight"]["effects"].values()))

    def test_closed_output_rejects_extra_field_and_effect_flip(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                observation = _run(
                    root,
                    "20260810",
                    annotation=FIXTURE,
                    review=_review(FIXTURE, "20260810"),
                )["observation"]
            extra = copy.deepcopy(observation)
            extra["unregistered"] = True
            self.assertTrue(list(Draft7Validator(_schema("us_short_serenity_quality_forward_observation.schema.json")).iter_errors(extra)))
            effect = copy.deepcopy(observation)
            effect["effects"]["scoring_eligible"] = True
            self.assertTrue(list(Draft7Validator(_schema("us_short_serenity_quality_forward_observation.schema.json")).iter_errors(effect)))


if __name__ == "__main__":
    unittest.main()
