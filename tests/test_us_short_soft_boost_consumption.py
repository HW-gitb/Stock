from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from engine import us_short_soft_boost_consumption as consumption
from tests.schema.test_us_short_provisional_theme_validation_schema import _artifact
from tests.provider.us_short_private_test_root import temporary_us_short_directory


ROOT = Path(__file__).resolve().parents[1]
DATE = "20991231"


def _write(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SoftBoostFixture:
    """Just the fixture, deliberately NOT a TestCase.

    A sibling module reuses this setUp by inheriting from it. When what it
    inherited was a TestCase subclass, importing it made unittest discover the
    ten cases below in BOTH modules -- they ran twice on every full lane, and the
    parallel runner's count gate is what finally noticed (discovered 5560, ran
    5570). Splitting the fixture off is what stops a shared setUp from dragging
    its owner's tests along with it.
    """

    def setUp(self):
        self._sample_root_context = temporary_us_short_directory(ROOT, Path("provider_samples"))
        provider_samples = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        self._fixture_dir = tempfile.TemporaryDirectory(
            prefix=f"k4b_{self._testMethodName}_",
            dir=provider_samples,
        )
        self.addCleanup(self._fixture_dir.cleanup)
        fixture_root = Path(self._fixture_dir.name) / "state" / "us_short"
        artifact_root = fixture_root / "inputs"
        self.paths = {
            "candidate": artifact_root / "candidate.json",
            "classification": artifact_root / "classification.json",
            "ingest": artifact_root / "ingest.json",
            "validation": fixture_root / f"us_short_provisional_theme_validation_{DATE}.json",
            "stage": fixture_root / f"us_short_provisional_theme_stage_receipt_{DATE}.json",
            "consumption": fixture_root / f"us_short_soft_boost_consumption_receipt_{DATE}.json",
            "shadow": fixture_root / "shadow_compare_private" / (
                f"us_short_soft_boost_shadow_receipt_{DATE}.json"
            ),
            "ledger": fixture_root / "shadow_compare_private" / (
                f"us_short_soft_boost_comparison_ledger_{DATE}.json"
            ),
        }
        self.fixture_root = fixture_root
        self.artifact_root = artifact_root
        candidate_sha = _write(self.paths["candidate"], {"decision_date": DATE})
        classification_sha = _write(self.paths["classification"], {"decision_date": DATE})
        ingest_sha = _write(self.paths["ingest"], {"decision_date": DATE})
        artifact = _artifact()
        artifact["decision_clock"]["expected_decision_date"] = DATE
        artifact["input_artifacts"].update({
            "discovery_artifact_sha256": ingest_sha,
            "candidate_artifact_sha256": candidate_sha,
            "classification_packet_sha256": classification_sha,
        })
        self.validation = artifact
        validation_sha = _write(self.paths["validation"], artifact)
        self.stage = {
            "schema_name": "us_short_provisional_theme_stage_receipt",
            "schema_version": "1.0.0",
            "generated_at": "2026-06-15T08:30:00-04:00",
            "decision_date": DATE,
            "status": "valid_nonempty",
            "reason_code": None,
            "artifacts": {
                "merge": {"path": "state/us_short/merge.json", "sha256": "1" * 64},
                "merge_manifest": {"path": "state/us_short/manifest.json", "sha256": "2" * 64},
                "ingest": {"path": self.paths["ingest"].relative_to(ROOT).as_posix(), "sha256": ingest_sha},
                "validation": {
                    "path": self.paths["validation"].relative_to(ROOT).as_posix(),
                    "sha256": validation_sha,
                },
            },
            "evidence_anchor": {
                "upstream_pair_anchored": True,
                "document_content_anchored": True,
                "upstream_artifacts": {
                    "web_discovery": {"path": "state/us_short/web.json", "sha256": "3" * 64},
                    "web_receipt": {"path": "state/us_short/web_receipt.json", "sha256": "4" * 64},
                    "x_discovery": {"path": "state/us_short/x.json", "sha256": "5" * 64},
                    "x_receipt": {"path": "state/us_short/x_receipt.json", "sha256": "6" * 64},
                },
            },
            "immutable_conflict": None,
            "validated_theme_count": 1,
            "boostable_ticker_count": 3,
            "drop_summary": {"merge_dropped_theme_count": 0, "validation_drop_count": 0},
            "error_summary": None,
            "effects": {
                "network_access_performed": False,
                "provider_calls_performed": False,
                "scoring_eligible": False,
                "top15_effect_enabled": False,
                "operation_advice_effect_enabled": False,
                "dynamic_seats_enabled": False,
                "theme_probe_enabled": False,
                "lifecycle_actions_enabled": False,
            },
        }
        _write(self.paths["stage"], self.stage)

    def tearDown(self):
        self.doCleanups()
        self._fixture_dir.cleanup()

    def _resolve(self, **overrides):
        kwargs = {
            "expected_decision_date": DATE,
            "theme_soft_boost_enabled": True,
            "current_stage_result": self.stage,
            "stage_receipt_path": self.paths["stage"],
            "validation_artifact_path": self.paths["validation"],
            "candidate_artifact_path": self.paths["candidate"],
            "classification_packet_path": self.paths["classification"],
            "state_dir": self.fixture_root,
        }
        kwargs.update(overrides)
        return consumption.resolve_soft_boost_consumption(**kwargs)


class SoftBoostConsumptionTest(SoftBoostFixture, unittest.TestCase):
    def _decision_lock(self):
        from runners import us_short_weekly_capstone as capstone

        lock = capstone._acquire_decision_lock(SimpleNamespace(
            state_dir=self.fixture_root, decision_date=DATE,
        ))
        self.addCleanup(capstone._release_decision_lock, lock)
        return lock

    def test_artifact_state_requires_this_runs_declared_complete_bundle(self):
        def result(**overrides):
            value = {
                "requested_enabled": True,
                "status": "zero_upstream_unavailable",
                "reason_code": "UPSTREAM_UNAVAILABLE",
                "effective_enabled": False,
                "evidence_bundle_written": False,
                "consumption_receipt_path": self.paths["consumption"].relative_to(ROOT).as_posix(),
                "shadow_receipt_path": None,
                "comparison_ledger_path": None,
                "provider_calls_performed": False,
            }
            value.update(overrides)
            return value

        classify = consumption.classify_soft_boost_artifact_state
        disabled = classify(
            soft_boost_requested=False,
            soft_boost_run_result=None,
            consumption_receipt_path=self.paths["consumption"],
            shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"],
        )
        self.assertEqual(disabled, {
            "state": "none", "reason_code": "SOFT_BOOST_COMPARISON_NOT_REQUESTED",
        })

        missing = classify(
            soft_boost_requested=True,
            soft_boost_run_result=None,
            consumption_receipt_path=self.paths["consumption"],
            shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"],
        )
        self.assertEqual(missing, {
            "state": "none", "reason_code": "SOFT_BOOST_COMPARISON_ARTIFACT_INVALID",
        })

        self.paths["consumption"].parent.mkdir(parents=True, exist_ok=True)
        self.paths["consumption"].write_text("{}", encoding="utf-8")
        zero = classify(
            soft_boost_requested=True,
            soft_boost_run_result=result(),
            consumption_receipt_path=self.paths["consumption"],
            shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"],
        )
        self.assertEqual(zero, {
            "state": "consumption_only", "reason_code": "SOFT_BOOST_COMPARISON_NOT_APPLICABLE",
        })

        for path in (self.paths["shadow"], self.paths["ledger"]):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        ready = classify(
            soft_boost_requested=True,
            soft_boost_run_result=result(
                status="consumed_valid_nonempty",
                reason_code=None,
                effective_enabled=True,
                evidence_bundle_written=True,
                shadow_receipt_path=self.paths["shadow"].relative_to(ROOT).as_posix(),
                comparison_ledger_path=self.paths["ledger"].relative_to(ROOT).as_posix(),
            ),
            consumption_receipt_path=self.paths["consumption"],
            shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"],
        )
        self.assertEqual(ready, {
            "state": "comparison_ready", "reason_code": "SOFT_BOOST_COMPARISON_READY",
        })

        unclaimed = classify(
            soft_boost_requested=True,
            soft_boost_run_result=None,
            consumption_receipt_path=self.paths["consumption"],
            shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"],
        )
        self.assertEqual(unclaimed, {
            "state": "none", "reason_code": "SOFT_BOOST_COMPARISON_ARTIFACT_INVALID",
        })

        wrong_path = classify(
            soft_boost_requested=True,
            soft_boost_run_result=result(
                status="consumed_valid_nonempty",
                reason_code=None,
                effective_enabled=True,
                evidence_bundle_written=True,
                shadow_receipt_path=self.paths["shadow"].with_name(
                    "not_this_runs_shadow.json"
                ).relative_to(ROOT).as_posix(),
                comparison_ledger_path=self.paths["ledger"].relative_to(ROOT).as_posix(),
            ),
            consumption_receipt_path=self.paths["consumption"],
            shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"],
        )
        self.assertEqual(wrong_path, {
            "state": "none", "reason_code": "SOFT_BOOST_COMPARISON_ARTIFACT_INVALID",
        })

        stale = classify(
            soft_boost_requested=True,
            soft_boost_run_result=result(),
            consumption_receipt_path=self.paths["consumption"],
            shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"],
        )
        self.assertEqual(stale, {
            "state": "consumption_only", "reason_code": "SOFT_BOOST_COMPARISON_NOT_APPLICABLE",
        })
        malformed = classify(
            soft_boost_requested=True,
            soft_boost_run_result={"requested_enabled": True},
            consumption_receipt_path=self.paths["consumption"],
            shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"],
        )
        self.assertEqual(malformed, {
            "state": "none", "reason_code": "SOFT_BOOST_COMPARISON_ARTIFACT_INVALID",
        })
        impossible_disabled = classify(
            soft_boost_requested=True,
            soft_boost_run_result=result(status="zero_disabled", reason_code="SOFT_DISCOVERY_DISABLED"),
            consumption_receipt_path=self.paths["consumption"],
            shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"],
        )
        self.assertEqual(impossible_disabled, {
            "state": "none", "reason_code": "SOFT_BOOST_COMPARISON_ARTIFACT_INVALID",
        })

    def test_valid_nonempty_is_the_only_state_that_enables_scoring(self):
        resolved = self._resolve()
        self.assertTrue(resolved["effective_enabled"], resolved)
        self.assertEqual(resolved["status"], "consumed_valid_nonempty")
        self.assertEqual(resolved["input_digests"], {
            "discovery_artifact_sha256": hashlib.sha256(self.paths["ingest"].read_bytes()).hexdigest(),
            "candidate_artifact_sha256": hashlib.sha256(self.paths["candidate"].read_bytes()).hexdigest(),
            "classification_packet_sha256": hashlib.sha256(self.paths["classification"].read_bytes()).hexdigest(),
        })

        stage_schema = json.loads(
            (ROOT / "schemas" / "us_short_provisional_theme_stage_receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        upstream_statuses = set(stage_schema["properties"]["status"]["enum"])
        self.assertEqual(
            upstream_statuses,
            {"valid_nonempty", "valid_empty", "upstream_unavailable", "invalid_evidence", "disabled"},
        )
        for status in sorted(upstream_statuses - {"valid_nonempty"}):
            with self.subTest(status=status):
                stage = copy.deepcopy(self.stage)
                stage["status"] = status
                stage["validated_theme_count"] = 0
                stage["boostable_ticker_count"] = 0
                if status == "upstream_unavailable":
                    stage["reason_code"] = "CANDIDATE_INPUT_UNAVAILABLE"
                    stage["error_summary"] = {
                        "code": "CANDIDATE_INPUT_UNAVAILABLE", "error_type": "SoftDiscoveryEvidenceError",
                    }
                elif status == "invalid_evidence":
                    stage["reason_code"] = "VALIDATION_EVIDENCE_INVALID"
                    stage["error_summary"] = {
                        "code": "VALIDATION_EVIDENCE_INVALID", "error_type": "ProvisionalThemeValidationError",
                    }
                elif status == "disabled":
                    stage["reason_code"] = "SOFT_DISCOVERY_DISABLED"
                    stage["evidence_anchor"]["upstream_pair_anchored"] = False
                    stage["evidence_anchor"]["document_content_anchored"] = False
                if status == "valid_empty":
                    validation = copy.deepcopy(self.validation)
                    validation["themes"] = []
                    validation["summary"]["validated_theme_count"] = 0
                    validation["summary"]["validated_member_count"] = 0
                    validation_sha = _write(self.paths["validation"], validation)
                    stage["artifacts"]["validation"]["sha256"] = validation_sha
                _write(self.paths["stage"], stage)
                resolved = self._resolve(current_stage_result=stage)
                self.assertFalse(resolved["effective_enabled"])
                self.assertEqual(resolved["status"], f"zero_{status}")

    def test_missing_bad_date_digest_and_path_all_degrade_to_typed_zero(self):
        mutations = []
        mutations.append(("missing", lambda: self.paths["stage"].unlink()))
        mutations.append(("date", lambda: self.stage.__setitem__("decision_date", "20260616")))
        mutations.append((
            "digest",
            lambda: self.stage["artifacts"]["validation"].__setitem__("sha256", "f" * 64),
        ))
        mutations.append((
            "path",
            lambda: self.stage["artifacts"]["validation"].__setitem__(
                "path", "state/us_short/not_the_expected_validation.json"
            ),
        ))
        for label, mutate in mutations:
            with self.subTest(label=label):
                self.setUp()
                mutate()
                if self.paths["stage"].exists():
                    _write(self.paths["stage"], self.stage)
                resolved = self._resolve()
                self.assertFalse(resolved["effective_enabled"])
                self.assertEqual(resolved["status"], "zero_invalid_evidence")
                self.tearDown()

    def test_current_run_stage_result_prevents_stale_canonical_valid_receipt_reuse(self):
        current = copy.deepcopy(self.stage)
        current["status"] = "invalid_evidence"
        current["reason_code"] = "SOFT_DISCOVERY_IMMUTABLE_CONFLICT"
        current["validated_theme_count"] = 0
        current["boostable_ticker_count"] = 0
        current["error_summary"] = {
            "code": "SOFT_DISCOVERY_IMMUTABLE_CONFLICT",
            "error_type": "DiscoveryPublishPolicyError",
        }
        current["effects"]["scoring_eligible"] = False
        resolved = self._resolve(current_stage_result=current)
        self.assertEqual(resolved["status"], "zero_invalid_evidence")
        self.assertFalse(resolved["effective_enabled"])

    def test_same_basename_in_wrong_directory_is_rejected(self):
        wrong = self.artifact_root / "nested" / self.paths["stage"].name
        _write(wrong, self.stage)
        resolved = self._resolve(stage_receipt_path=wrong)
        self.assertEqual(resolved["status"], "zero_invalid_evidence")
        self.assertFalse(resolved["effective_enabled"])
        wrong.unlink()
        wrong.parent.rmdir()

    def test_current_run_stage_result_must_equal_the_canonical_receipt(self):
        mismatched = copy.deepcopy(self.stage)
        mismatched["generated_at"] = "2026-06-15T08:32:00-04:00"
        resolved = self._resolve(current_stage_result=mismatched)
        self.assertEqual(resolved["status"], "zero_invalid_evidence")
        self.assertFalse(resolved["effective_enabled"])

    def test_flag_is_exact_bool_and_explicit_off_reads_nothing(self):
        for bad in (1, 0, None, "true"):
            with self.subTest(value=bad), self.assertRaises(consumption.SoftBoostConsumptionError):
                self._resolve(theme_soft_boost_enabled=bad)
        self.paths["stage"].unlink()
        resolved = self._resolve(theme_soft_boost_enabled=False)
        self.assertEqual(resolved["status"], "zero_disabled")
        self.assertFalse(resolved["effective_enabled"])

    def test_receipt_binds_actual_core_and_top15_effect_without_claiming_advice(self):
        resolved = self._resolve()
        receipt = consumption.build_consumption_receipt(
            resolved=resolved,
            generated_at="2026-06-15T08:31:00-04:00",
            on_selection={"AAPL": 100.0, "MSFT": 52.0},
            off_selection={"AAPL": 98.0, "MSFT": 50.0},
            boost_records={
                "AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"},
                "MSFT": {"theme_soft_boost": 2.0, "evidence_tier": "single"},
            },
            on_top15=["AAPL"],
            off_top15=["MSFT"],
        )
        consumption.write_consumption_receipt(
            receipt, self.paths["consumption"], state_dir=self.fixture_root
        )
        saved = json.loads(self.paths["consumption"].read_text(encoding="utf-8"))
        self.assertEqual(saved["top15_impact"], {"entered": ["AAPL"], "exited": ["MSFT"], "changed": True})
        self.assertFalse(saved["effects"]["operation_advice_effect_claimed"])
        self.assertLessEqual(max(row["actual_boost"] for row in saved["per_ticker"]), 5.0)

    def test_shadow_is_same_evidence_local_off_and_week_capture_is_idempotent(self):
        resolved = self._resolve()
        receipt = consumption.build_consumption_receipt(
            resolved=resolved,
            generated_at="2026-06-15T08:31:00-04:00",
            on_selection={"AAPL": 55.0},
            off_selection={"AAPL": 50.0},
            boost_records={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
            on_top15=["AAPL"],
            off_top15=["MSFT"],
        )
        shadow = consumption.build_shadow_receipt(
            resolved=resolved,
            generated_at="2026-06-15T08:31:00-04:00",
            on_top15=["AAPL"], off_top15=["MSFT"],
            common_input_sha256="a" * 64,
        )
        self.assertFalse(hasattr(consumption, "write_shadow_and_update_ledger"))
        consumption.write_evidence_bundle(
            consumption_receipt=receipt,
            consumption_path=self.paths["consumption"],
            shadow_receipt=shadow,
            shadow_path=self.paths["shadow"],
            ledger_path=self.paths["ledger"],
            state_dir=self.fixture_root,
        )
        first = self.paths["ledger"].read_bytes()
        consumption.write_evidence_bundle(
            consumption_receipt=receipt,
            consumption_path=self.paths["consumption"],
            shadow_receipt=shadow,
            shadow_path=self.paths["shadow"],
            ledger_path=self.paths["ledger"],
            state_dir=self.fixture_root,
        )
        self.assertTrue(self.paths["consumption"].is_file())
        self.assertEqual(self.paths["ledger"].read_bytes(), first)
        saved = json.loads(first)
        self.assertEqual(saved["captured_week_count"], 1)
        self.assertEqual(saved["matured_week_count"], 0)
        self.assertEqual(saved["record_scope"], "single_decision_week_capture")
        self.assertFalse(saved["formal_adjudication_performed"])
        self.assertFalse(saved["pending_user_decision_receipt_generated"])
        self.assertEqual(saved["status"], "continue_accumulation")
        self.assertEqual(saved["records"][0]["comparison"], ["soft_boost_on", "soft_boost_off"])
        self.assertEqual(
            saved["records"][0]["statistical_plan_sha256"],
            consumption._serialized_sha256(json.loads(
                (ROOT / "presets" / "us_short_soft_boost_statistical_plan_20260727.json").read_text(encoding="utf-8")
            )),
        )
        self.assertFalse(saved["records"][0]["provider_calls_performed"])

    def test_zero_to_valid_retry_recovers_second_step_failure_only_under_decision_lock(self):
        zero = consumption.degrade_soft_boost_consumption(decision_date=DATE)
        zero_receipt = consumption.build_consumption_receipt(
            resolved=zero, generated_at="2026-06-15T08:30:00-04:00",
            on_selection={"AAPL": 50.0}, off_selection={"AAPL": 50.0},
            boost_records={"AAPL": {"theme_soft_boost": 0.0, "evidence_tier": None}},
            on_top15=["AAPL"], off_top15=["AAPL"],
        )
        consumption.write_consumption_receipt(
            zero_receipt, self.paths["consumption"], state_dir=self.fixture_root,
        )
        resolved = self._resolve()
        receipt = consumption.build_consumption_receipt(
            resolved=resolved, generated_at="2026-06-15T08:31:00-04:00",
            on_selection={"AAPL": 55.0}, off_selection={"AAPL": 50.0},
            boost_records={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
            on_top15=["AAPL"], off_top15=["AAPL"],
        )
        shadow = consumption.build_shadow_receipt(
            resolved=resolved, generated_at="2026-06-15T08:31:00-04:00",
            on_top15=["AAPL"], off_top15=["AAPL"], common_input_sha256="a" * 64,
        )
        with self.assertRaises(consumption.SoftBoostConsumptionError):
            consumption.write_evidence_bundle(
                consumption_receipt=receipt, consumption_path=self.paths["consumption"],
                shadow_receipt=shadow, shadow_path=self.paths["shadow"], ledger_path=self.paths["ledger"],
                state_dir=self.fixture_root,
            )
        self.assertFalse(self.paths["shadow"].exists())
        self.assertFalse(self.paths["ledger"].exists())

        lock = self._decision_lock()
        with mock.patch.object(
            consumption, "write_consumption_receipt",
            side_effect=consumption.SoftBoostConsumptionError("injected second step failure"),
        ):
            with self.assertRaisesRegex(consumption.SoftBoostConsumptionError, "injected second step failure"):
                consumption.write_evidence_bundle(
                    consumption_receipt=receipt, consumption_path=self.paths["consumption"],
                    shadow_receipt=shadow, shadow_path=self.paths["shadow"], ledger_path=self.paths["ledger"],
                    state_dir=self.fixture_root, decision_lock=lock,
                )
        self.assertTrue(self.paths["shadow"].is_file())
        self.assertTrue(self.paths["ledger"].is_file())
        self.assertEqual(json.loads(self.paths["consumption"].read_text(encoding="utf-8"))["status"], "zero_invalid_evidence")

        retry_receipt = consumption.build_consumption_receipt(
            resolved=resolved, generated_at="2026-06-15T08:32:00-04:00",
            on_selection={"AAPL": 55.0}, off_selection={"AAPL": 50.0},
            boost_records={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
            on_top15=["AAPL"], off_top15=["AAPL"],
        )
        retry_shadow = consumption.build_shadow_receipt(
            resolved=resolved, generated_at="2026-06-15T08:32:00-04:00",
            on_top15=["AAPL"], off_top15=["AAPL"], common_input_sha256="a" * 64,
        )
        consumption.write_evidence_bundle(
            consumption_receipt=retry_receipt, consumption_path=self.paths["consumption"],
            shadow_receipt=retry_shadow, shadow_path=self.paths["shadow"], ledger_path=self.paths["ledger"],
            state_dir=self.fixture_root, decision_lock=lock,
        )
        self.assertEqual(json.loads(self.paths["consumption"].read_text(encoding="utf-8"))["status"], "consumed_valid_nonempty")
        self.assertEqual(json.loads(self.paths["shadow"].read_text(encoding="utf-8"))["generated_at"], "2026-06-15T08:31:00-04:00")
        self.assertEqual(json.loads(self.paths["ledger"].read_text(encoding="utf-8"))["records"][0]["generated_at"], "2026-06-15T08:31:00-04:00")

        different_shadow = consumption.build_shadow_receipt(
            resolved=resolved, generated_at="2026-06-15T08:33:00-04:00",
            on_top15=["AAPL"], off_top15=["AAPL"], common_input_sha256="b" * 64,
        )
        with self.assertRaises(consumption.SoftBoostConsumptionError):
            consumption.write_evidence_bundle(
                consumption_receipt=retry_receipt, consumption_path=self.paths["consumption"],
                shadow_receipt=different_shadow, shadow_path=self.paths["shadow"], ledger_path=self.paths["ledger"],
                state_dir=self.fixture_root, decision_lock=lock,
            )

    def test_evidence_epoch_digest_is_invariant_to_tracked_json_line_endings(self):
        epoch = json.loads(consumption.EPOCH_PATH.read_text(encoding="utf-8"))
        lf_path = self.fixture_root / "epoch_lf.json"
        crlf_path = self.fixture_root / "epoch_crlf.json"
        lf = json.dumps(epoch, ensure_ascii=False, indent=2) + "\n"
        lf_path.write_text(lf, encoding="utf-8", newline="")
        crlf_path.write_text(lf.replace("\n", "\r\n"), encoding="utf-8", newline="")
        original = consumption.EPOCH_PATH
        try:
            consumption.EPOCH_PATH = lf_path
            lf_digest, _ = consumption._validated_evidence_contracts()
            consumption.EPOCH_PATH = crlf_path
            crlf_digest, _ = consumption._validated_evidence_contracts()
        finally:
            consumption.EPOCH_PATH = original
        self.assertEqual(lf_digest, crlf_digest)

    def test_statistical_plan_is_frozen_symmetric_and_never_auto_applies(self):
        plan = json.loads(
            (ROOT / "presets" / "us_short_soft_boost_statistical_plan_20260727.json").read_text(
                encoding="utf-8"
            )
        )
        consumption._validate(
            plan,
            ROOT / "schemas" / "us_short_soft_boost_statistical_plan.schema.json",
            label="test K4b statistical plan",
        )
        self.assertEqual(plan["formal_look_divergence_weeks"], [24, 36])
        self.assertEqual(plan["preliminary_eligible_weeks"], 12)
        self.assertTrue(plan["direction_policy"]["symmetric"])
        self.assertTrue(plan["direction_policy"]["absence_of_significance_is_not_reverse_evidence"])
        self.assertFalse(plan["decision_policy"]["automatic_route_change_allowed"])
        self.assertTrue(plan["decision_policy"]["recommendation_requires_pending_user_decision_receipt"])
        self.assertEqual(plan["decision_policy"]["allowed_user_decisions"], ["accept", "reject", "defer"])
        changed = copy.deepcopy(plan)
        changed["outcome_gate"]["mean_paired_advantage_gte"] = 0.0
        with self.assertRaises(consumption.SoftBoostConsumptionError):
            consumption._validate(
                changed,
                ROOT / "schemas" / "us_short_soft_boost_statistical_plan.schema.json",
                label="mutated K4b statistical plan",
            )

if __name__ == "__main__":
    unittest.main()
