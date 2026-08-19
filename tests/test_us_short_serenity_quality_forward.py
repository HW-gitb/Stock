from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from engine import us_short_serenity_quality_forward as quality
from engine import us_short_serenity_structural_theme_annotation as annotation_contract
from engine import us_short_serenity_shadow_consumers as shadow


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "us_short_serenity_structural_theme_annotation_v0_1.json"


class SerenityQualityForwardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def _review(self, annotation, decision_date, *, verdict="pass", reviewer_model="claude-code-reviewer-v0.1.0"):
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
                "model_identity": reviewer_model,
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
                    "verdict": verdict,
                    "rationale": f"observed judgment for {metric_id}",
                    "evidence_ref_ids": [f"review:{metric_id}"],
                }
                for metric_id in quality.METRIC_IDS
            ],
        }

    def _formal_fixture(self):
        annotation = copy.deepcopy(self.fixture)
        annotation["identity_envelope"]["annotation_author_kind"] = "llm"
        annotation["identity_envelope"]["model_identity"] = "serenity-producer-v0.1.0"
        return annotation

    def _legacy_ledger(self):
        # Shape written before the two-action Blade5 fields were added; it deliberately has no pending arrays.
        return {
            "schema_name": quality.LEDGER_SCHEMA_NAME,
            "schema_version": quality.LEGACY_LEDGER_SCHEMA_VERSION,
            "quality_policy_version": quality.QUALITY_POLICY_VERSION,
            "cross_cohort_aggregation_allowed": False,
            "cohorts": [],
            "effects": dict(quality.EFFECT_BOUNDARY),
        }

    def _run(self, root, decision_date, *, annotation=None, review=None, ledger=None,
             annotation_name="annotation.json", review_name="review.json"):
        state = root / "state" / "us_short"
        state.mkdir(parents=True, exist_ok=True)
        annotation_path = state / annotation_name
        review_path = state / review_name
        observation_path = state / f"observation_{decision_date}.json"
        ledger_path = ledger or state / "ledger.json"
        gate_path = state / f"gate_{decision_date}.json"
        if annotation is not None:
            annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
        if review is not None:
            review_path.write_text(json.dumps(review), encoding="utf-8")
        return quality.run_quality_forward(
            annotation_path=annotation_path,
            review_path=review_path,
            observation_path=observation_path,
            gate_path=gate_path,
            decision_date=decision_date,
            observed_at="2026-08-10T08:00:00+00:00",
            root=root,
            now=datetime(2026, 8, 10, tzinfo=timezone.utc),
            **{"ledger_path": ledger_path},
        )

    def test_policy_freezes_five_judgment_metrics_and_window(self):
        policy = quality.load_quality_policy()
        self.assertEqual(tuple(item["metric_id"] for item in policy["metrics"]), quality.METRIC_IDS)
        self.assertEqual(policy["frozen_window"], {
            "minimum_eligible_weeks": 4,
            "minimum_evaluable_rate": 0.75,
            "minimum_pass_rate": 0.8,
        })
        self.assertFalse(policy["cross_cohort_aggregation_allowed"])
        self.assertTrue(all(set(item) == {"metric_id", "what", "why"} for item in policy["metrics"]))
        self.assertTrue(all(value is False for value in policy["effect_boundary"].values()))

    def test_valid_annotation_and_review_bind_identity_and_create_eligible_observation(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            review = self._review(self.fixture, "20260810")
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                result = self._run(root, "20260810", annotation=self.fixture, review=review)
            self.assertEqual(result["status"], "eligible")
            self.assertEqual(result["shadow_consumption"]["status"], "active")
            self.assertFalse(result["main_task_should_abort"])
            expected = {
                "annotation_id": self.fixture["annotation_id"],
                "schema_version": "1.0.0",
                "rubric_version": "serenity_annotation_rubric_v0.1.0",
                "upstream_decision_result_id": self.fixture["identity_envelope"]["upstream_decision_result_id"],
                "upstream_policy_version": "soft_discovery_query_policy_v0.3.0",
                "upstream_decision_date": "20260809",
                "annotation_author_kind": "human",
                "annotation_prompt_version": "serenity_blade3_rubric_v0.1.0",
                "producer_model_identity": None,
            }
            self.assertEqual(result["observation"]["annotation_identity"], expected)
            self.assertEqual(result["ledger"]["cohorts"][0]["records"][0]["annotation_identity"], expected)
            self.assertEqual(result["quality_gate"]["verdict"], "continue_accumulating")
            self.assertTrue(all(value is False for value in result["effects"].values()))

    def test_missing_annotation_is_sleeping_and_does_not_validate_or_overlay(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch.object(annotation_contract, "validate_annotation", side_effect=AssertionError("must not run")):
                result = self._run(root, "20260810")
            self.assertEqual(result["status"], "sleeping")
            self.assertEqual(result["shadow_consumption"]["status"], "sleeping")
            self.assertFalse(result["observation"]["annotation_present"])
            self.assertIsNone(result["observation"]["annotation_identity"])
            self.assertEqual(result["quality_gate"]["window"]["eligible_week_count"], 0)

    def test_missing_review_keeps_active_advisory_shadow_but_does_not_count_week(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                result = self._run(root, "20260810", annotation=self.fixture)
            self.assertEqual(result["status"], "not_evaluable")
            self.assertEqual(result["shadow_consumption"]["status"], "active")
            self.assertEqual(result["quality_gate"]["window"]["eligible_week_count"], 0)
            self.assertEqual(len(result["ledger"]["pending_annotations"]), 1)
            self.assertEqual(result["observation"]["settlement_status"], "pending_review")

    def test_legacy_empty_ledger_is_migrated_once_and_week_continues(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state" / "us_short"
            state.mkdir(parents=True, exist_ok=True)
            ledger = state / "ledger.json"
            ledger.write_text(json.dumps(self._legacy_ledger(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            result = self._run(root, "20260810", ledger=ledger)
            self.assertEqual(result["status"], "sleeping")
            self.assertFalse(result["main_task_should_abort"])
            self.assertEqual(result["quality_gate"]["window"]["eligible_week_count"], 0)
            migrated = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], quality.LEDGER_SCHEMA_VERSION)
            self.assertEqual(migrated["pending_annotations"], [])
            self.assertEqual(migrated["closed_pending_annotations"], [])

            settlement = quality.settle_pending_review(
                ledger_path=ledger,
                current_decision_date="20260817",
                observed_at="2026-08-17T08:00:00+00:00",
                state_dir=state,
                root=root,
                now=datetime(2026, 8, 17, 8, tzinfo=timezone.utc),
            )
            self.assertEqual(settlement["status"], "no_pending")
            self.assertEqual(json.loads(ledger.read_text(encoding="utf-8")), migrated)

    def test_complete_legacy_ledger_upgrades_without_losing_pending_state(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state" / "us_short"
            annotation = self._formal_fixture()
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                self._run(
                    root, "20260810", annotation=annotation,
                    annotation_name="annotation_20260810.json", review_name="review_20260810.json",
                )
            ledger = state / "ledger.json"
            legacy = json.loads(ledger.read_text(encoding="utf-8"))
            legacy["schema_version"] = quality.LEGACY_LEDGER_SCHEMA_VERSION
            ledger.write_text(json.dumps(legacy), encoding="utf-8")

            target = quality.load_pending_review_target(ledger_path=ledger, state_dir=state)

            migrated = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(target["pending"]["decision_date"], "20260810")
            self.assertEqual(migrated["schema_version"], quality.LEDGER_SCHEMA_VERSION)
            self.assertEqual(migrated["pending_annotations"], legacy["pending_annotations"])
            self.assertEqual(migrated["cohorts"], legacy["cohorts"])

    def test_complete_legacy_ledger_upgrades_without_losing_current_cohort(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state" / "us_short"
            ledger = state / "ledger.json"
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                self._run(
                    root, "20260810", annotation=self.fixture,
                    review=self._review(self.fixture, "20260810"), ledger=ledger,
                )
            legacy = json.loads(ledger.read_text(encoding="utf-8"))
            legacy["schema_version"] = quality.LEGACY_LEDGER_SCHEMA_VERSION
            ledger.write_text(json.dumps(legacy), encoding="utf-8")

            settlement = quality.settle_pending_review(
                ledger_path=ledger,
                current_decision_date="20260817",
                observed_at="2026-08-17T08:00:00+00:00",
                state_dir=state,
                root=root,
                now=datetime(2026, 8, 17, 8, tzinfo=timezone.utc),
            )

            migrated = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(settlement["status"], "no_pending")
            self.assertEqual(migrated["schema_version"], quality.LEDGER_SCHEMA_VERSION)
            self.assertEqual(migrated["cohorts"], legacy["cohorts"])

    def test_unmigratable_legacy_cohort_is_rejected_without_rewrite(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state" / "us_short"
            state.mkdir(parents=True, exist_ok=True)
            ledger = state / "ledger.json"
            legacy = self._legacy_ledger()
            legacy["cohorts"] = [{"legacy_record": True}]
            legacy_bytes = (json.dumps(legacy, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            ledger.write_bytes(legacy_bytes)

            result = self._run(root, "20260810", ledger=ledger)

            self.assertEqual(result["status"], "invalid_evidence")
            self.assertEqual(result["error"]["code"], "SERENITY_QUALITY_LEDGER_REJECTED")
            self.assertEqual(ledger.read_bytes(), legacy_bytes)

    def test_pending_target_requires_exactly_one_and_review_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state" / "us_short"
            annotation = self._formal_fixture()
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                self._run(
                    root, "20260810", annotation=annotation,
                    annotation_name="annotation_20260810.json", review_name="review_20260810.json",
                )
            ledger = state / "ledger.json"
            target = quality.load_pending_review_target(ledger_path=ledger, state_dir=state)
            self.assertEqual(target["review_path"], state / "review_20260810.json")
            review = self._review(annotation, "20260810")
            first = quality.write_independent_quality_review(
                ledger_path=ledger, state_dir=state, review=review,
                now=datetime(2026, 8, 10, 9, tzinfo=timezone.utc),
            )
            second = quality.write_independent_quality_review(
                ledger_path=ledger, state_dir=state, review=review,
                now=datetime(2026, 8, 10, 9, tzinfo=timezone.utc),
            )
            self.assertEqual(first["status"], "written")
            self.assertEqual(second["status"], "idempotent")
            different = copy.deepcopy(review)
            different["metrics"][0]["verdict"] = "fail"
            with self.assertRaises(quality.SerenityQualityForwardError):
                quality.write_independent_quality_review(
                    ledger_path=ledger, state_dir=state, review=different,
                    now=datetime(2026, 8, 10, 9, tzinfo=timezone.utc),
                )
            saved = json.loads(ledger.read_text(encoding="utf-8"))
            saved["pending_annotations"].append(copy.deepcopy(saved["pending_annotations"][0]))
            ledger.write_text(json.dumps(saved), encoding="utf-8")
            with self.assertRaisesRegex(quality.SerenityQualityForwardError, "exactly one"):
                quality.load_pending_review_target(ledger_path=ledger, state_dir=state)

    def test_two_week_settlement_closes_previous_review_before_new_pending(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state" / "us_short"
            ledger = state / "ledger.json"
            annotation = self._formal_fixture()
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                self._run(
                    root, "20260810", annotation=annotation, ledger=ledger,
                    annotation_name="annotation_20260810.json", review_name="review_20260810.json",
                )
                quality.write_independent_quality_review(
                    ledger_path=ledger, state_dir=state,
                    review=self._review(annotation, "20260810"),
                    now=datetime(2026, 8, 10, 9, tzinfo=timezone.utc),
                )
                settled = quality.settle_pending_review(
                    ledger_path=ledger, current_decision_date="20260817",
                    observed_at="2026-08-17T08:00:00+00:00", state_dir=state, root=root,
                    now=datetime(2026, 8, 17, 8, tzinfo=timezone.utc),
                )
                self.assertEqual(settled["status"], "settled")
                after_settlement = json.loads(ledger.read_text(encoding="utf-8"))
                self.assertEqual(after_settlement["pending_annotations"], [])
                self.assertEqual(after_settlement["closed_pending_annotations"][0]["settlement_status"], "eligible")
                self.assertEqual(len(after_settlement["cohorts"][0]["records"]), 1)
                self.assertTrue(after_settlement["cohorts"][0]["records"][0]["formal_count_eligible"])
                current = self._run(
                    root, "20260817", annotation=annotation, ledger=ledger,
                    annotation_name="annotation_20260817.json", review_name="review_20260817.json",
                )
            self.assertEqual(current["status"], "not_evaluable")
            self.assertEqual(len(current["ledger"]["pending_annotations"]), 1)
            self.assertEqual(
                quality.settle_pending_review(
                    ledger_path=ledger, current_decision_date="20260817",
                    observed_at="2026-08-17T08:00:00+00:00", state_dir=state, root=root,
                    now=datetime(2026, 8, 17, 8, tzinfo=timezone.utc),
                )["status"],
                "not_due",
            )

    def test_late_review_is_no_count_and_cannot_be_backfilled(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state" / "us_short"
            ledger = state / "ledger.json"
            annotation = self._formal_fixture()
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                self._run(
                    root, "20260810", annotation=annotation, ledger=ledger,
                    annotation_name="annotation_20260810.json", review_name="review_20260810.json",
                )
                settled = quality.settle_pending_review(
                    ledger_path=ledger, current_decision_date="20260817",
                    observed_at="2026-08-17T08:00:00+00:00", state_dir=state, root=root,
                    now=datetime(2026, 8, 17, 8, tzinfo=timezone.utc),
                )
            self.assertEqual(settled["status"], "no_count")
            closed = json.loads(ledger.read_text(encoding="utf-8"))["closed_pending_annotations"]
            self.assertEqual(closed[0]["settlement_status"], "no_count")
            late_review = self._review(annotation, "20260810")
            (state / "review_20260810.json").write_text(json.dumps(late_review), encoding="utf-8")
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                result = self._run(
                    root, "20260810", annotation=annotation, review=late_review, ledger=ledger,
                    annotation_name="annotation_20260810.json", review_name="review_20260810.json",
                )
            self.assertEqual(result["status"], "invalid_evidence")
            saved = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["cohorts"]), 0)
            self.assertEqual(saved["closed_pending_annotations"][0]["settlement_status"], "no_count")

    def test_producer_rejects_wrong_upstream_date_and_never_synthesizes_payload(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "state" / "us_short" / "annotation.json"
            annotation = self._formal_fixture()
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                produced = quality.produce_annotation_for_week(
                    annotation_path=path, decision_date="20260810",
                    soft_discovery_result={"status": "valid_nonempty"}, annotation_payload=annotation,
                    root=root, now=datetime(2026, 8, 10, tzinfo=timezone.utc),
                )
            self.assertEqual(produced["status"], "invalid_evidence")
            self.assertFalse(path.exists())
            pending = quality.produce_annotation_for_week(
                annotation_path=path, decision_date="20260810",
                soft_discovery_result={"status": "valid_nonempty"}, root=root,
            )
            self.assertEqual(pending["status"], "pending")

    def test_reviewer_cannot_use_the_producer_model_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            annotation = self._formal_fixture()
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                result = self._run(
                    root, "20260810", annotation=annotation,
                    review=self._review(annotation, "20260810", reviewer_model="serenity-producer-v0.1.0"),
                )
            self.assertEqual(result["status"], "invalid_evidence")
            self.assertIn("producer identity", result["error"]["message"])
            self.assertTrue(result["observation"]["report_overlay_available"])

    def test_review_identity_or_version_mismatch_is_local_invalid_evidence(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            review = self._review(self.fixture, "20260810")
            review["annotation_identity"]["upstream_policy_version"] = "soft_discovery_query_policy_v0.2.0"
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                result = self._run(root, "20260810", annotation=self.fixture, review=review)
            self.assertEqual(result["status"], "invalid_evidence")
            self.assertEqual(result["error"]["code"], "SERENITY_QUALITY_REVIEW_REJECTED")
            self.assertEqual(result["quality_gate"]["window"]["eligible_week_count"], 0)
            self.assertFalse(result["main_task_should_abort"])

    def test_same_date_different_review_conflicts_without_overwriting_frozen_record(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ledger = root / "state" / "us_short" / "ledger.json"
            first = self._review(self.fixture, "20260810", verdict="pass")
            second = self._review(self.fixture, "20260810", verdict="fail")
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                self._run(root, "20260810", annotation=self.fixture, review=first, ledger=ledger)
                result = self._run(root, "20260810", annotation=self.fixture, review=second, ledger=ledger)
            self.assertEqual(result["status"], "invalid_evidence")
            self.assertIn("same decision_date", result["error"]["message"])
            saved = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(saved["cohorts"][0]["records"][0]["metrics"][0]["verdict"], "pass")

    def test_four_eligible_weeks_create_quality_gate_result_without_effect(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ledger = root / "state" / "us_short" / "ledger.json"
            result = None
            annotation = self._formal_fixture()
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                for decision_date in ("20260810", "20260817", "20260824", "20260831"):
                    result = self._run(
                        root,
                        decision_date,
                        annotation=annotation,
                        review=self._review(annotation, decision_date),
                        ledger=ledger,
                    )
            assert result is not None
            self.assertEqual(result["quality_gate"]["verdict"], "quality_gate_pass")
            self.assertTrue(result["quality_gate_result_id"].startswith("serenity_quality_gate:"))
            self.assertEqual(result["quality_gate"]["window"]["eligible_week_count"], 4)
            self.assertEqual(
                result["ledger"]["cohorts"][0]["quality_gate_result_id"],
                result["quality_gate_result_id"],
            )
            self.assertTrue(all(value is False for value in result["quality_gate"]["effects"].values()))

    def test_four_eligible_weeks_below_pass_threshold_do_not_create_gate_id(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ledger = root / "state" / "us_short" / "ledger.json"
            result = None
            annotation = self._formal_fixture()
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                for decision_date in ("20260810", "20260817", "20260824", "20260831"):
                    result = self._run(
                        root,
                        decision_date,
                        annotation=annotation,
                        review=self._review(annotation, decision_date, verdict="fail"),
                        ledger=ledger,
                    )
            assert result is not None
            self.assertEqual(result["quality_gate"]["verdict"], "quality_below_threshold")
            self.assertIsNone(result["quality_gate_result_id"])

    def test_upstream_policy_version_change_opens_new_cohort_without_mixing(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ledger = root / "state" / "us_short" / "ledger.json"
            formal = self._formal_fixture()
            changed_formal = copy.deepcopy(formal)
            changed_formal["identity_envelope"]["upstream_policy_version"] = "soft_discovery_query_policy_v0.2.0"
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                first = self._run(
                    root, "20260810", annotation=formal,
                    review=self._review(formal, "20260810"), ledger=ledger,
                )
                second = self._run(
                    root, "20260817", annotation=changed_formal,
                    review=self._review(changed_formal, "20260817"), ledger=ledger,
                )
            self.assertEqual(len(second["ledger"]["cohorts"]), 2)
            self.assertNotEqual(
                second["ledger"]["cohorts"][0]["cohort_id"],
                second["ledger"]["cohorts"][1]["cohort_id"],
            )
            self.assertEqual(first["quality_gate"]["window"]["eligible_week_count"], 1)
            self.assertFalse(second["quality_gate"]["window"]["eligible_week_count"] > 1)

    def test_weekly_bridge_delivers_registered_overlay_and_failure_does_not_abort(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            report_path = root / "weekly_private" / "weekly_report.md"
            report_path.parent.mkdir(parents=True)
            report = "# report\n\n## 诚实横幅\n- clock\n\n## 12. lifecycle\n- ordinary\n"
            report_path.write_text(report, encoding="utf-8")
            with patch.object(annotation_contract, "validate_annotation", return_value=True):
                active = shadow.consume_serenity_annotation(self.fixture)
                quality_result = self._run(
                    root,
                    "20260810",
                    annotation=self.fixture,
                    review=self._review(self.fixture, "20260810"),
                    ledger=root / "state" / "us_short" / "quality_ledger.json",
                )
            observation_path = root / "state" / "us_short" / "observation_20260810.json"
            ctx = SimpleNamespace(
                theme_soft_boost_enabled=False,
                soft_discovery_run_result=None,
                forward_policy_comparison_ledger_path=root / "state" / "us_short" / "shadow_compare_private" / "forward_policy_comparison_ledger.json",
                vix_regime_summary_path=root / "vix.json",
                serenity_shadow_result=active,
                serenity_quality_run_result=quality_result,
                serenity_quality_observation_path=observation_path,
                official_output_root=root,
                private_root=root,
                source_packet_path=root / "source.json",
                batch4_template_path=root / "template.json",
                account_state_path=root / "account.json",
                provider_health_path=root / "health.json",
                context_components_path=root / "components.json",
                now_et=datetime(2026, 8, 10, 8, 0, 0),
                generated_at="2026-08-10T08:00:00+00:00",
            )
            (root / "vix.json").write_text("{}", encoding="utf-8")
            bridge_summary = {"batch4_run": {"output_paths": {"weekly_report_path": str(report_path)}}}
            with patch("runners.us_short_weekly_capstone_stages._write_provider_health"), \
                 patch("runners.us_short_weekly_capstone_stages._build_market_axis_regimes",
                       return_value={"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"}), \
                 patch("runners.us_short_weekly_capstone_stages._bridge.run_e2e", return_value=bridge_summary):
                from runners.us_short_weekly_capstone_stages import run_weekly_bridge

                run_weekly_bridge(ctx)
            rendered = report_path.read_text(encoding="utf-8")
            self.assertEqual(rendered.count("## "), report.count("## "))
            self.assertIn("us_short_serenity_structural_annotation_shadow", rendered)
            observed = json.loads(observation_path.read_text(encoding="utf-8"))
            self.assertTrue(observed["report_block_delivered"])
            self.assertIsNone(observed["report_block_problem"])

            report_path.write_text("# malformed\n", encoding="utf-8")
            with patch("runners.us_short_weekly_capstone_stages._write_provider_health"), \
                 patch("runners.us_short_weekly_capstone_stages._build_market_axis_regimes",
                       return_value={"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"}), \
                 patch("runners.us_short_weekly_capstone_stages._bridge.run_e2e", return_value=bridge_summary):
                run_weekly_bridge(ctx)
            rendered = report_path.read_text(encoding="utf-8")
            self.assertTrue(rendered.startswith("# malformed\n"))
            self.assertIn("serenity_report_delivery/SERENITY_REPORT_DELIVERY_FAILED", rendered)
            observed = json.loads(observation_path.read_text(encoding="utf-8"))
            self.assertFalse(observed["report_block_delivered"])
            self.assertIn("honest-banner", observed["report_block_problem"])


if __name__ == "__main__":
    unittest.main()
