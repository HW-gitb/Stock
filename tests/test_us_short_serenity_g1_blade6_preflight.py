from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engine import us_short_serenity_g1_blade6_preflight as preflight
from engine import us_short_serenity_quality_forward as quality
from engine import us_short_serenity_structural_theme_annotation as annotation_contract
ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "us_short_serenity_structural_theme_annotation_v0_1.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _formal_fixture():
    annotation = copy.deepcopy(FIXTURE)
    annotation["identity_envelope"]["annotation_author_kind"] = "llm"
    annotation["identity_envelope"]["model_identity"] = "serenity-producer-v0.1.0"
    return annotation


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


def _run(root, decision_date, *, annotation, review, ledger):
    state = root / "state" / "us_short"
    state.mkdir(parents=True, exist_ok=True)
    annotation_path = state / f"annotation_{decision_date}.json"
    review_path = state / f"review_{decision_date}.json"
    observation_path = state / f"observation_{decision_date}.json"
    gate_path = state / f"gate_{decision_date}.json"
    annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    return quality.run_quality_forward(
        annotation_path=annotation_path,
        review_path=review_path,
        observation_path=observation_path,
        ledger_path=ledger,
        gate_path=gate_path,
        decision_date=decision_date,
        observed_at="2026-08-10T08:00:00+00:00",
        root=root,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )


class SerenityG1Blade6PreflightTest(unittest.TestCase):
    def test_quality_gate_without_explicit_g1_stays_blocked_and_zero_effect(self):
        annotation = _formal_fixture()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ledger = root / "state" / "us_short" / "ledger.json"
            result = None
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                for decision_date in ("20260810", "20260817", "20260824", "20260831"):
                    result = _run(
                        root, decision_date, annotation=annotation,
                        review=_review(annotation, decision_date), ledger=ledger,
                    )
            assert result is not None
            self.assertEqual(result["quality_gate"]["verdict"], "quality_gate_pass")
            self.assertEqual(result["g1_blade6_preflight"]["status"], "blocked")
            self.assertIn("g1_decision_unavailable", result["g1_blade6_preflight"]["blocking_reasons"])
            self.assertFalse(result["g1_blade6_preflight"]["effects"]["preregistration_created"])

    def test_preflight_rejects_g1_quality_gate_binding_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            gate_path = root / "gate.json"
            g1_path = root / "g1.json"
            output_path = root / "preflight.json"
            gate = {
                "schema_name": "us_short_serenity_quality_gate_result",
                "schema_version": "1.0.0",
                "generated_at": "2026-08-31T08:00:00+00:00",
                "quality_policy_version": quality.QUALITY_POLICY_VERSION,
                "cohort_id": "serenity_quality_cohort:1.0.0:serenity_annotation_rubric_v0.1.0:serenity_shadow_consumer_v0.1.0:soft_discovery_query_policy_v0.3.0:serenity_annotation_producer_v0.1.0:serenity_blade3_rubric_v0.1.0:serenity_quality_reviewer_v0.1.0:serenity_quality_reviewer_prompt_v0.1.0",
                "cohort_dimensions": {
                    "annotation_schema_version": "1.0.0",
                    "rubric_version": "serenity_annotation_rubric_v0.1.0",
                    "consumer_version": "serenity_shadow_consumer_v0.1.0",
                    "upstream_policy_version": "soft_discovery_query_policy_v0.3.0",
                    "producer_identity_version": "serenity_annotation_producer_v0.1.0",
                    "annotation_prompt_version": "serenity_blade3_rubric_v0.1.0",
                    "reviewer_identity_version": "serenity_quality_reviewer_v0.1.0",
                    "review_prompt_version": "serenity_quality_reviewer_prompt_v0.1.0",
                },
                "verdict": "quality_gate_pass",
                "quality_gate_result_id": "serenity_quality_gate:bound",
                "formal_count_ready": True,
                "formal_blockers": [],
                "window": {"start_decision_date": "20260810", "end_decision_date": "20260831", "eligible_week_count": 4, "record_ids": []},
                "metric_assessments": [
                    {"metric_id": metric, "evaluable_count": 4, "evaluable_rate": 1.0, "pass_count": 4, "pass_rate": 1.0, "verdict": "pass"}
                    for metric in quality.METRIC_IDS
                ],
                "thresholds": {"minimum_eligible_weeks": 4, "minimum_evaluable_rate": 0.75, "minimum_pass_rate": 0.8},
                "effects": {
                    "scoring_eligible": False, "top15_effect_enabled": False, "operation_advice_effect_enabled": False,
                    "provider_calls_performed": False, "network_access_performed": False, "main_task_should_abort": False,
                },
            }
            gate_path.write_text(json.dumps(gate), encoding="utf-8")
            g1_path.write_text(json.dumps({
                "schema_name": "us_short_serenity_g1_decision", "schema_version": "1.0.0",
                "decision_date": "20260831", "decision": "open_effect_experiment",
                "selected_route": preflight.ROUTE, "effect_experiment_enabled": True,
                "operation_advice_effect_enabled": False, "g1_decision_id": "serenity_g1_decision:test",
                "quality_gate_result_id": "serenity_quality_gate:wrong",
            }), encoding="utf-8")
            result = preflight.run_g1_blade6_preflight(
                quality_gate_path=gate_path, g1_decision_path=g1_path,
                output_path=output_path, decision_date="20260831", generated_at="2026-08-31T08:00:00+00:00",
            )
            self.assertEqual(result["status"], "blocked")
            self.assertIn("g1_quality_gate_binding_mismatch", result["blocking_reasons"])


if __name__ == "__main__":
    unittest.main()
