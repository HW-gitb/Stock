"""Focused tests for the A-short P4 health companion."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema

from runners.a_short_weekly_sidecar_health import (
    AUTHORITATIVE_ARTIFACT_SIDECARS,
    BEST_EFFORT_SELF_REPORT_SIDECARS,
    HEALTH_SCHEMA,
    OUTCOME_SCHEMA,
    SIDECAR_SPECS,
    _m67_evidence,
    build_health,
    write_health_bundle,
)
from runners import a_short_weekly_sidecar_health as sidecar_health
from runners.a_short_regime_comparison_runner import write_candidate_effect_outcome
from tests._a_short_weekly_publish_test_utils import write_content_bound_bundle


def _manifest(sidecars, expected=None):
    return {
        "schema_name": "a_short_weekly_sidecar_outcomes",
        "schema_version": "1.0.0",
        "as_of": "20260727",
        "run_id": None,
        "candidate_digest": None,
        "expected_sidecars": expected or [row["name"] for row in sidecars],
        "sidecars": sidecars,
    }


def _row(name, *, execution="succeeded", progress="advanced", expected=True, **extra):
    row = {
        "name": name,
        "expected": expected,
        "attempted": expected,
        "execution_status": execution,
        "progress_status": progress,
        "expected_data_through": None,
        "observed_decision_as_of": "20260727" if progress in {"advanced", "already_current"} else None,
        "observed_data_through": None,
        "error_code": None,
        "skip_reason": None,
    }
    row.update(extra)
    return row


def _candidate_summary(*, latest_evidence_as_of):
    payload = json.loads(
        (Path(__file__).resolve().parents[1]
         / "research/results/a_short/regime_candidate_effect_summary.json").read_text(
             encoding="utf-8"
         )
    )
    payload["latest_evidence_as_of"] = latest_evidence_as_of
    payload["source_hash"] = "0" * 64
    return payload


def _iv_feed(*, as_of):
    return {
        "schema_name": "a_short_iv_feed",
        "schema_version": "1.1.0",
        "generated_at": "2026-07-27T00:00:00+00:00",
        "as_of": as_of,
        "underlying": "510050.SH",
        "params": {
            "risk_free": 0.02,
            "div_yield": 0.0,
            "const_maturity_days": 30,
            "min_t_days": 5,
            "roll_window": 252,
            "min_roll_obs": 60,
            "hv_window": 21,
        },
        "n_days": 0,
        "series": [],
        "boundary": {
            "production": False,
            "real_money": False,
            "satisfies_ship_gate": False,
            "iv_method": "bs_atm_constant_maturity_feasibility_grade",
        },
    }


def _write_valid_weekly_bundle(root: Path) -> Path:
    out_dir = root / "20260727"
    write_content_bound_bundle(
        out_dir / "weekly_m67.json",
        {
            "as_of": "20260727",
            "run_lineage": {
                "run_id": "a-short-20260727-0123456789abcdef",
                "candidate_digest": "a" * 64,
                "price_freshness": {
                    "mode": "strict_as_of",
                    "run_date": "20260727",
                    "price_data_through": "20260727",
                },
            },
        },
    )
    return out_dir


class AShortSidecarHealthTests(unittest.TestCase):
    def test_complete_m67_identity_comes_only_from_validated_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = _write_valid_weekly_bundle(Path(tmp))
            evidence = _m67_evidence(out_dir, "20260727")
            manifest = _manifest([_row("data_canary")])
            manifest["run_id"] = evidence["run_id"]
            manifest["candidate_digest"] = evidence["candidate_digest"]
            result = build_health(
                as_of="20260727",
                launcher_manifest=manifest,
                project_root=Path(tmp),
                m67_out_dir=out_dir,
            )
        self.assertEqual(result["m67_status"], "complete")
        self.assertEqual(result["run_id"], "a-short-20260727-0123456789abcdef")
        self.assertEqual(result["candidate_digest"], "a" * 64)
        self.assertEqual(len(result["source_receipt_sha256"]), 64)

    def test_manifest_identity_cannot_override_validated_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = _write_valid_weekly_bundle(Path(tmp))
            manifest = _manifest([_row("data_canary")])
            manifest["run_id"] = "a-short-20260727-fedcba9876543210"
            manifest["candidate_digest"] = "b" * 64
            result = build_health(
                as_of="20260727",
                launcher_manifest=manifest,
                project_root=Path(tmp),
                m67_out_dir=out_dir,
            )
        self.assertEqual(result["m67_status"], "unavailable")
        self.assertEqual(result["overall"], "degraded")
        self.assertIsNone(result["run_id"])
        self.assertIsNone(result["candidate_digest"])
        self.assertIsNone(result["source_receipt_sha256"])

    def test_current_skip_or_not_run_cannot_reuse_stale_complete_bundle_or_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = _write_valid_weekly_bundle(Path(tmp))
            stale_pipeline = _manifest([_row("factor_v2_capture")])
            stale_pipeline["run_id"] = "a-short-20260727-0123456789abcdef"
            stale_pipeline["candidate_digest"] = "a" * 64
            launcher = _manifest([_row("data_canary")])
            for invocation in ("skipped", "not_run"):
                with self.subTest(invocation=invocation):
                    result = build_health(
                        as_of="20260727",
                        launcher_manifest=launcher,
                        pipeline_manifest=stale_pipeline,
                        project_root=Path(tmp),
                        m67_out_dir=out_dir,
                        m67_invocation=invocation,
                    )
                    self.assertEqual(result["m67_status"], invocation)
                    self.assertEqual(
                        result["overall"],
                        "partial" if invocation == "skipped" else "healthy",
                    )
                    self.assertIsNone(result["run_id"])
                    self.assertIsNone(result["candidate_digest"])
                    self.assertIsNone(result["source_receipt_sha256"])
                    self.assertEqual(
                        [row["name"] for row in result["sidecars"]],
                        ["data_canary"],
                    )
            requested = build_health(
                as_of="20260727",
                launcher_manifest=launcher,
                pipeline_manifest=stale_pipeline,
                project_root=Path(tmp),
                m67_out_dir=out_dir,
                m67_invocation="requested",
            )
        self.assertEqual(requested["m67_status"], "complete")
        self.assertEqual(
            requested["run_id"], "a-short-20260727-0123456789abcdef"
        )
        self.assertIn(
            "factor_v2_capture",
            [row["name"] for row in requested["sidecars"]],
        )

    def test_tampered_bundle_replaces_prior_complete_health_with_unavailable(self):
        for target in ("json", "markdown"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                out_dir = _write_valid_weekly_bundle(Path(tmp))
                manifest = _manifest([_row("data_canary")])
                initial = build_health(
                    as_of="20260727",
                    launcher_manifest=manifest,
                    project_root=Path(tmp),
                    m67_out_dir=out_dir,
                )
                write_health_bundle(initial, out_dir)
                if target == "json":
                    path = out_dir / "weekly_m67.json"
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    payload["tampered_operation"] = "建仓"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                else:
                    path = out_dir / "weekly_m67.md"
                    path.write_text(path.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
                replacement = build_health(
                    as_of="20260727",
                    launcher_manifest=manifest,
                    project_root=Path(tmp),
                    m67_out_dir=out_dir,
                )
                write_health_bundle(replacement, out_dir)
                persisted = json.loads((out_dir / "sidecar_health.json").read_text(encoding="utf-8"))
                self.assertEqual(persisted["m67_status"], "unavailable")
                self.assertEqual(persisted["overall"], "degraded")
                self.assertIsNone(persisted["source_receipt_sha256"])

    def test_failed_and_invalid_receipts_have_honest_m67_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "20260727"
            out_dir.mkdir()
            receipt = out_dir / "weekly_m67.receipt.json"
            receipt.write_text(json.dumps({
                "schema_name": "a_short_weekly_publish_receipt",
                "schema_version": "1.1.0",
                "as_of": "20260727",
                "stage_status": "failed",
                "failure_reason": "weekly_failed",
                "exit_code": 22,
            }), encoding="utf-8")
            failed = _m67_evidence(out_dir, "20260727")
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(len(failed["source_receipt_sha256"]), 64)
            self.assertIsNone(failed["run_id"])
            for invalid in (
                {"schema_name": "a_short_weekly_publish_receipt", "schema_version": "1.0.0",
                 "as_of": "20260727", "stage_status": "failed", "failure_reason": "x", "exit_code": 1},
                {"stage_status": "failed"},
            ):
                receipt.write_text(json.dumps(invalid), encoding="utf-8")
                self.assertEqual(_m67_evidence(out_dir, "20260727")["status"], "unavailable")
            receipt.write_text("{", encoding="utf-8")
            self.assertEqual(_m67_evidence(out_dir, "20260727")["status"], "unavailable")

    def test_failed_receipt_remains_failed_when_old_complete_outputs_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = _write_valid_weekly_bundle(Path(tmp))
            receipt = out_dir / "weekly_m67.receipt.json"
            receipt.write_text(json.dumps({
                "schema_name": "a_short_weekly_publish_receipt",
                "schema_version": "1.1.0",
                "as_of": "20260727",
                "stage_status": "failed",
                "failure_reason": "weekly_failed",
                "exit_code": 22,
            }), encoding="utf-8")
            evidence = _m67_evidence(out_dir, "20260727")
        self.assertEqual(evidence["status"], "failed")
        self.assertEqual(len(evidence["source_receipt_sha256"]), 64)
        self.assertIsNone(evidence["run_id"])
        self.assertIsNone(evidence["candidate_digest"])

    def test_failed_receipt_replaces_old_complete_health_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = _write_valid_weekly_bundle(Path(tmp))
            complete = build_health(
                as_of="20260727",
                launcher_manifest=_manifest([_row("data_canary")]),
                project_root=Path(tmp),
                m67_out_dir=out_dir,
                m67_invocation="requested",
            )
            write_health_bundle(complete, out_dir)
            for leaf in (
                "weekly_m67.json",
                "weekly_m67.md",
                "sidecar_health.json",
                "sidecar_health.md",
                "sidecar_health.receipt.json",
            ):
                (out_dir / leaf).unlink(missing_ok=True)
            receipt = out_dir / "weekly_m67.receipt.json"
            receipt.write_text(json.dumps({
                "schema_name": "a_short_weekly_publish_receipt",
                "schema_version": "1.1.0",
                "as_of": "20260727",
                "stage_status": "failed",
                "failure_reason": "weekly_failed",
                "exit_code": 22,
            }), encoding="utf-8")
            failed = build_health(
                as_of="20260727",
                project_root=Path(tmp),
                m67_out_dir=out_dir,
                m67_invocation="requested",
            )
            write_health_bundle(failed, out_dir)
            persisted = json.loads(
                (out_dir / "sidecar_health.json").read_text(encoding="utf-8")
            )
        self.assertEqual(persisted["m67_status"], "failed")
        self.assertEqual(persisted["overall"], "degraded")
        self.assertIsNone(persisted["run_id"])
        self.assertIsNone(persisted["candidate_digest"])
        self.assertEqual(len(persisted["source_receipt_sha256"]), 64)

    def test_empty_sidecars_are_rejected_for_complete_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = _write_valid_weekly_bundle(Path(tmp))
            with self.assertRaises(jsonschema.ValidationError):
                build_health(
                    as_of="20260727",
                    project_root=Path(tmp),
                    m67_out_dir=out_dir,
                    m67_invocation="requested",
                )

    def test_incomplete_complete_receipt_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = _write_valid_weekly_bundle(Path(tmp))
            receipt = out_dir / "weekly_m67.receipt.json"
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload.pop("outputs_digest")
            receipt.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(_m67_evidence(out_dir, "20260727")["status"], "unavailable")

    def test_every_registered_sidecar_has_one_validation_bucket(self):
        self.assertFalse(AUTHORITATIVE_ARTIFACT_SIDECARS & BEST_EFFORT_SELF_REPORT_SIDECARS)
        self.assertEqual(
            set(SIDECAR_SPECS),
            AUTHORITATIVE_ARTIFACT_SIDECARS | BEST_EFFORT_SELF_REPORT_SIDECARS,
        )
        self.assertEqual(
            build_health(
                as_of="20260727",
                launcher_manifest=_manifest([_row("data_canary")]),
                project_root=Path("."),
            )["overall"],
            "healthy",
        )
        with patch.dict(
            sidecar_health.SIDECAR_SPECS,
            {"unclassified_sidecar": "forward_evidence"},
        ):
            with self.assertRaisesRegex(ValueError, "validation bucket"):
                sidecar_health.build_health(
                    as_of="20260727",
                    launcher_manifest=_manifest([], expected=["unclassified_sidecar"]),
                    project_root=Path("."),
                )

    def test_source_mismatch_receipt_with_prior_evidence_is_health_stalled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "research/results/a_short/regime_candidate_effect_summary.json"
            outcome_path = root / "research/results/a_short/candidate_effect_outcome.json"
            summary_path.parent.mkdir(parents=True)
            summary_path.write_text(json.dumps(_candidate_summary(latest_evidence_as_of="20260720")), encoding="utf-8")
            receipt = write_candidate_effect_outcome(
                as_of="20260727",
                result={"status": "skipped_source_mismatch", "reason_code": "run_identity_mismatch"},
                summary_path=str(summary_path), outcome_path=str(outcome_path),
            )
            manifest = _manifest([_row(
                "candidate_effect", execution="succeeded", progress="stalled",
                observed_decision_as_of=receipt["observed_as_of"], error_code=receipt["reason_code"],
            )])
            result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=root)
        self.assertEqual(receipt["status"], "skipped_source_mismatch")
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["progress_status"], "stalled")
        self.assertEqual(result["sidecars"][0]["observed_decision_as_of"], "20260720")

    def test_settled_regime_clock_is_not_stalled(self):
        manifest = _manifest([
            _row(
                "regime_daily",
                expected_data_through="20260724",
                observed_decision_as_of=None,
                observed_data_through="20260724",
            )
        ])
        result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=Path("."))
        self.assertEqual(result["overall"], "healthy")
        self.assertEqual(result["sidecars"][0]["progress_status"], "advanced")

    def test_old_artifact_cannot_mask_current_run_failure(self):
        manifest = _manifest([
            _row(
                "factor_v2_capture",
                execution="failed",
                progress="unavailable",
                observed_decision_as_of="20260720",
                error_code="capture_unavailable",
            )
        ])
        result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=Path("."))
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["execution_status"], "failed")
        self.assertEqual(result["sidecars"][0]["progress_status"], "stalled")

    def test_zero_exit_with_stale_progress_is_stalled(self):
        manifest = _manifest([_row(
            "factor_v2_capture",
            execution="succeeded",
            progress="advanced",
            observed_decision_as_of="20260720",
        )])
        result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=Path("."))
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["progress_status"], "stalled")

    def test_artifact_probe_overrides_launcher_current_week_self_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "research/results/a_short/regime_action_comparison_records.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps([{"as_of": "20260720"}]), encoding="utf-8")
            manifest = _manifest([_row(
                "regime_action",
                execution="succeeded",
                progress="advanced",
                observed_decision_as_of="20260727",
            )])
            result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=root)
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["observed_decision_as_of"], "20260720")
        self.assertEqual(result["sidecars"][0]["progress_status"], "stalled")

    def test_candidate_effect_probe_exposes_stale_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "research/results/a_short/regime_candidate_effect_summary.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(_candidate_summary(latest_evidence_as_of="20260720")),
                encoding="utf-8",
            )
            manifest = _manifest([_row(
                "candidate_effect",
                execution="succeeded",
                progress="advanced",
                observed_decision_as_of="20260727",
            )])
            result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=root)
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["progress_status"], "stalled")

    def test_candidate_null_artifact_clock_overrides_launcher_current_self_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "research/results/a_short/regime_candidate_effect_summary.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(_candidate_summary(latest_evidence_as_of=None)),
                encoding="utf-8",
            )
            manifest = _manifest([_row(
                "candidate_effect",
                execution="succeeded",
                progress="advanced",
                observed_decision_as_of="20260727",
            )])
            result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=root)
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["execution_status"], "succeeded")
        self.assertIsNone(result["sidecars"][0]["observed_decision_as_of"])
        self.assertEqual(result["sidecars"][0]["progress_status"], "unavailable")

    def test_iv_feed_probe_uses_artifact_as_of(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "research/results/a_short/iv_feed_20260727/iv_feed.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(_iv_feed(as_of="20260720")), encoding="utf-8")
            manifest = _manifest([_row(
                "iv_feed",
                execution="succeeded",
                progress="advanced",
                observed_decision_as_of="20260727",
            )])
            result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=root)
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["observed_decision_as_of"], "20260720")
        self.assertEqual(result["sidecars"][0]["progress_status"], "stalled")

    def test_schema_invalid_candidate_summary_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "research/results/a_short/regime_candidate_effect_summary.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"latest_evidence_as_of": "20260727"}), encoding="utf-8")
            manifest = _manifest([_row("candidate_effect")])
            result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=root)
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["execution_status"], "failed")
        self.assertEqual(result["sidecars"][0]["progress_status"], "unavailable")

    def test_candidate_summary_with_stale_policy_binding_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "research/results/a_short/regime_candidate_effect_summary.json"
            path.parent.mkdir(parents=True)
            payload = _candidate_summary(latest_evidence_as_of="20260727")
            payload["policy"]["policy_fingerprint"] = "0" * 64
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = build_health(as_of="20260727", launcher_manifest=_manifest([_row("candidate_effect")]), project_root=root)
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["execution_status"], "failed")

    def test_schema_invalid_iv_feed_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "research/results/a_short/iv_feed_20260727/iv_feed.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"as_of": "20260727"}), encoding="utf-8")
            manifest = _manifest([_row("iv_feed")])
            result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=root)
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["execution_status"], "failed")

    def test_missing_candidate_effect_outcome_is_unavailable_and_failed(self):
        manifest = _manifest([], expected=["candidate_effect"])
        with tempfile.TemporaryDirectory() as tmp:
            result = build_health(
                as_of="20260727", launcher_manifest=manifest, project_root=Path(tmp)
            )
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["sidecars"][0]["progress_status"], "unavailable")

    def test_candidate_self_report_cannot_mask_missing_summary(self):
        manifest = _manifest([_row(
            "candidate_effect",
            execution="succeeded",
            progress="advanced",
            observed_decision_as_of="20260727",
        )])
        with tempfile.TemporaryDirectory() as tmp:
            result = build_health(
                as_of="20260727", launcher_manifest=manifest, project_root=Path(tmp)
            )
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["sidecars"][0]["execution_status"], "failed")
        self.assertEqual(result["sidecars"][0]["progress_status"], "unavailable")

    def test_iv_self_report_cannot_mask_missing_feed(self):
        manifest = _manifest([_row(
            "iv_feed",
            execution="succeeded",
            progress="advanced",
            observed_decision_as_of="20260727",
        )])
        with tempfile.TemporaryDirectory() as tmp:
            result = build_health(
                as_of="20260727", launcher_manifest=manifest, project_root=Path(tmp)
            )
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["sidecars"][0]["execution_status"], "failed")

    def test_missing_expected_outcome_is_degraded(self):
        manifest = _manifest([], expected=["overlay_adjudication_capture"])
        result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=Path("."))
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["execution_status"], "missing_outcome")

    def test_explicit_skip_is_partial_not_stalled(self):
        manifest = _manifest([_row("overlay_adjudication_capture", execution="skipped", progress="not_applicable", expected=False)])
        result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=Path("."))
        self.assertEqual(result["overall"], "partial")
        self.assertEqual(result["sidecars"][0]["progress_status"], "not_applicable")

    def test_theme_comparison_progress_comes_from_packet_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = root / "research" / "results" / "a_short_theme_forward_comparison.json"
            packet.parent.mkdir(parents=True)
            packet.write_text(
                json.dumps({"latest_evidence_as_of": "20260727"}), encoding="utf-8"
            )
            manifest = _manifest([_row(
                "theme_forward_comparison",
                progress="not_applicable",
                observed_decision_as_of=None,
            )])
            result = build_health(
                as_of="20260727", launcher_manifest=manifest, project_root=root
            )
        self.assertEqual(result["overall"], "healthy")
        self.assertEqual(result["sidecars"][0]["observed_decision_as_of"], "20260727")
        self.assertEqual(result["sidecars"][0]["progress_status"], "advanced")

    def test_theme_comparison_epoch_mismatch_is_stalled_even_when_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = root / "research" / "results" / "a_short_theme_forward_comparison.json"
            packet.parent.mkdir(parents=True)
            packet.write_text(json.dumps({
                "latest_evidence_as_of": "20260727",
                "adjudication_mode": "epoch_contract_mismatch",
            }), encoding="utf-8")
            manifest = _manifest([_row(
                "theme_forward_comparison",
                progress="not_applicable",
                observed_decision_as_of=None,
            )])
            result = build_health(
                as_of="20260727", launcher_manifest=manifest, project_root=root
            )
        self.assertEqual(result["overall"], "degraded")
        self.assertEqual(result["sidecars"][0]["progress_status"], "stalled")
        self.assertIn("epoch_contract_mismatch", result["sidecars"][0]["error_code"])

    def test_bundle_is_schema_valid_and_deidentified(self):
        manifest = _manifest([_row("data_canary")])
        result = build_health(as_of="20260727", launcher_manifest=manifest, project_root=Path("."))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = write_health_bundle(result, root)
            payload = json.loads(paths[0].read_text(encoding="utf-8"))
            jsonschema.validate(payload, json.loads(HEALTH_SCHEMA.read_text(encoding="utf-8")))
            self.assertIsNone(payload["source_receipt_sha256"])
            self.assertNotIn("ts_code", paths[1].read_text(encoding="utf-8"))
            self.assertNotIn(str(root), paths[1].read_text(encoding="utf-8"))


class AShortSidecarOutcomeSchemaTests(unittest.TestCase):
    def test_manifest_schema_is_closed(self):
        manifest = _manifest([_row("data_canary")])
        jsonschema.validate(manifest, json.loads(OUTCOME_SCHEMA.read_text(encoding="utf-8")))

    def test_failure_writer_replaces_all_stale_health_surfaces(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "runners" / "weekly_screening.ps1").read_text(
            encoding="utf-8"
        )
        failure_writer = (
            "function Write-M67Utf8NoBom"
            + launcher.split("function Write-M67Utf8NoBom", 1)[1].split(
                "function Write-KnownM67FailureReceipt", 1
            )[0]
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "20260727"
            out_dir.mkdir()
            for leaf in (
                "weekly_m67.json",
                "weekly_m67.md",
                "sidecar_health.json",
                "sidecar_health.md",
                "sidecar_health.receipt.json",
                "weekly_m67.pipeline_sidecar_outcomes.json",
                "launcher_sidecar_outcomes.json",
            ):
                (out_dir / leaf).write_text("stale\n", encoding="utf-8")
            quote = lambda value: str(value).replace("'", "''")
            command = "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    "$AsOf = '20260727'",
                    f"$ProjectRoot = '{quote(root)}'",
                    f"$PythonExe = '{quote(sys.executable)}'",
                    failure_writer,
                    (
                        "Write-M67FailureReceipt "
                        f"-Directory '{quote(out_dir)}' "
                        "-Reason 'weekly_pipeline_failed' -ExitCode 22"
                    ),
                )
            )
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"stdout={completed.stdout}\nstderr={completed.stderr}",
            )
            payload = json.loads(
                (out_dir / "sidecar_health.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["m67_status"], "failed")
            self.assertEqual(payload["overall"], "degraded")
            self.assertEqual(payload["sidecars"], [])
            self.assertIsNone(payload["run_id"])
            self.assertIsNone(payload["candidate_digest"])
            self.assertEqual(len(payload["source_receipt_sha256"]), 64)
            self.assertTrue((out_dir / "sidecar_health.md").is_file())
            self.assertTrue((out_dir / "sidecar_health.receipt.json").is_file())
            self.assertFalse(
                (out_dir / "weekly_m67.pipeline_sidecar_outcomes.json").exists()
            )
            self.assertFalse((out_dir / "launcher_sidecar_outcomes.json").exists())

    def test_failure_writer_invalidates_before_temp_write_failure(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "runners" / "weekly_screening.ps1").read_text(
            encoding="utf-8"
        )
        failure_writer = (
            "function Write-M67Utf8NoBom"
            + launcher.split("function Write-M67Utf8NoBom", 1)[1].split(
                "function Write-KnownM67FailureReceipt", 1
            )[0]
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "20260727"
            out_dir.mkdir()
            stale_leaves = (
                "weekly_m67.receipt.json",
                "sidecar_health.receipt.json",
                "weekly_m67.json",
                "weekly_m67.md",
                "sidecar_health.json",
                "sidecar_health.md",
                "weekly_m67.pipeline_sidecar_outcomes.json",
                "launcher_sidecar_outcomes.json",
            )
            for leaf in stale_leaves:
                (out_dir / leaf).write_text("stale\n", encoding="utf-8")
            quote = lambda value: str(value).replace("'", "''")
            command = "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    "$AsOf = '20260727'",
                    f"$ProjectRoot = '{quote(root)}'",
                    f"$PythonExe = '{quote(sys.executable)}'",
                    failure_writer,
                    "function Write-M67Utf8NoBom {",
                    "  param([string]$LiteralPath, [string]$Text)",
                    "  if ($LiteralPath.EndsWith('.tmp')) { throw 'injected tmp write failure' }",
                    "  $Encoding = [System.Text.UTF8Encoding]::new($false)",
                    "  [System.IO.File]::WriteAllText($LiteralPath, $Text, $Encoding)",
                    "}",
                    (
                        "Write-M67FailureReceipt "
                        f"-Directory '{quote(out_dir)}' "
                        "-Reason 'weekly_pipeline_failed' -ExitCode 22"
                    ),
                )
            )
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            for leaf in stale_leaves:
                self.assertFalse(
                    (out_dir / leaf).exists(),
                    msg=f"stale surface survived tmp write failure: {leaf}",
                )

    def test_failure_writer_survives_mid_cleanup_delete_failure(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "runners" / "weekly_screening.ps1").read_text(
            encoding="utf-8"
        )
        failure_writer = (
            "function Write-M67Utf8NoBom"
            + launcher.split("function Write-M67Utf8NoBom", 1)[1].split(
                "function Write-KnownM67FailureReceipt", 1
            )[0]
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "20260727"
            out_dir.mkdir()
            for leaf in (
                "weekly_m67.receipt.json",
                "sidecar_health.receipt.json",
                "weekly_m67.json",
                "weekly_m67.md",
                "sidecar_health.json",
                "sidecar_health.md",
            ):
                (out_dir / leaf).write_text("stale\n", encoding="utf-8")
            quote = lambda value: str(value).replace("'", "''")
            fail_path = out_dir / "sidecar_health.json"
            command = "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    "$AsOf = '20260727'",
                    f"$ProjectRoot = '{quote(root)}'",
                    f"$PythonExe = '{quote(sys.executable)}'",
                    failure_writer,
                    f"$script:InjectedDeletePath = '{quote(fail_path)}'",
                    "$script:InjectedDeleteRaised = $false",
                    "function Remove-Item {",
                    "  [CmdletBinding()]",
                    "  param([Parameter(Mandatory=$true)][string]$LiteralPath, [switch]$Force)",
                    "  if ($LiteralPath -eq $script:InjectedDeletePath -and -not $script:InjectedDeleteRaised) {",
                    "    $script:InjectedDeleteRaised = $true",
                    "    throw 'injected delete failure'",
                    "  }",
                    "  Microsoft.PowerShell.Management\\Remove-Item -LiteralPath $LiteralPath -Force:$Force -ErrorAction Stop",
                    "}",
                    (
                        "Write-M67FailureReceipt "
                        f"-Directory '{quote(out_dir)}' "
                        "-Reason 'weekly_pipeline_failed' -ExitCode 22"
                    ),
                )
            )
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"stdout={completed.stdout}\nstderr={completed.stderr}",
            )
            payload = json.loads(
                (out_dir / "sidecar_health.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["m67_status"], "failed")
            self.assertEqual(payload["overall"], "degraded")

    def test_failure_writer_attempts_every_surface_after_delete_and_tombstone_failure(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "runners" / "weekly_screening.ps1").read_text(
            encoding="utf-8"
        )
        failure_writer = (
            "function Write-M67Utf8NoBom"
            + launcher.split("function Write-M67Utf8NoBom", 1)[1].split(
                "function Write-KnownM67FailureReceipt", 1
            )[0]
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "20260727"
            out_dir.mkdir()
            stale_leaves = (
                "weekly_m67.receipt.json",
                "sidecar_health.receipt.json",
                "weekly_m67.json",
                "weekly_m67.md",
                "sidecar_health.json",
                "sidecar_health.md",
                "weekly_m67.pipeline_sidecar_outcomes.json",
                "launcher_sidecar_outcomes.json",
            )
            for leaf in stale_leaves:
                (out_dir / leaf).write_text("stale\n", encoding="utf-8")
            quote = lambda value: str(value).replace("'", "''")
            fail_path = out_dir / "weekly_m67.receipt.json"
            command = "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    "$AsOf = '20260727'",
                    f"$ProjectRoot = '{quote(root)}'",
                    f"$PythonExe = '{quote(sys.executable)}'",
                    failure_writer,
                    f"$script:InjectedDoubleFailurePath = '{quote(fail_path)}'",
                    "function Remove-Item {",
                    "  [CmdletBinding()]",
                    "  param([Parameter(Mandatory=$true)][string]$LiteralPath, [switch]$Force)",
                    "  if ($LiteralPath -eq $script:InjectedDoubleFailurePath) {",
                    "    throw 'injected delete failure'",
                    "  }",
                    "  Microsoft.PowerShell.Management\\Remove-Item -LiteralPath $LiteralPath -Force:$Force -ErrorAction Stop",
                    "}",
                    "function Write-M67Utf8NoBom {",
                    "  param([string]$LiteralPath, [string]$Text)",
                    "  if ($LiteralPath -eq $script:InjectedDoubleFailurePath) {",
                    "    throw 'injected tombstone failure'",
                    "  }",
                    "  $Encoding = [System.Text.UTF8Encoding]::new($false)",
                    "  [System.IO.File]::WriteAllText($LiteralPath, $Text, $Encoding)",
                    "}",
                    (
                        "Write-M67FailureReceipt "
                        f"-Directory '{quote(out_dir)}' "
                        "-Reason 'weekly_pipeline_failed' -ExitCode 22"
                    ),
                )
            )
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertTrue(fail_path.exists())
            for leaf in stale_leaves[1:]:
                self.assertFalse(
                    (out_dir / leaf).exists(),
                    msg=f"cleanup stopped before later surface: {leaf}",
                )

    def test_failure_writer_cleans_missing_and_partial_health_companion(self):
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "runners" / "weekly_screening.ps1").read_text(
            encoding="utf-8"
        )
        failure_writer = (
            "function Write-M67Utf8NoBom"
            + launcher.split("function Write-M67Utf8NoBom", 1)[1].split(
                "function Write-KnownM67FailureReceipt", 1
            )[0]
        )
        for mode in ("missing", "partial_nonzero"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                temp_root = Path(tmp) / "project"
                out_dir = Path(tmp) / "20260727"
                temp_root.mkdir()
                out_dir.mkdir()
                if mode == "partial_nonzero":
                    runners = temp_root / "runners"
                    runners.mkdir()
                    (runners / "a_short_weekly_sidecar_health.py").write_text(
                        "from pathlib import Path\n"
                        "import sys\n"
                        "out = Path(sys.argv[sys.argv.index('--out-dir') + 1])\n"
                        "for leaf in ('sidecar_health.json', 'sidecar_health.md', "
                        "'sidecar_health.receipt.json'):\n"
                        "    (out / leaf).write_text('partial', encoding='utf-8')\n"
                        "raise SystemExit(9)\n",
                        encoding="utf-8",
                    )
                for leaf in (
                    "sidecar_health.json",
                    "sidecar_health.md",
                    "sidecar_health.receipt.json",
                ):
                    (out_dir / leaf).write_text("stale\n", encoding="utf-8")
                quote = lambda value: str(value).replace("'", "''")
                command = "\n".join(
                    (
                        "$ErrorActionPreference = 'Stop'",
                        "$AsOf = '20260727'",
                        f"$ProjectRoot = '{quote(temp_root)}'",
                        f"$PythonExe = '{quote(sys.executable)}'",
                        failure_writer,
                        (
                            "Write-M67FailureReceipt "
                            f"-Directory '{quote(out_dir)}' "
                            "-Reason 'weekly_pipeline_failed' -ExitCode 22"
                        ),
                    )
                )
                completed = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        command,
                    ],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    msg=f"stdout={completed.stdout}\nstderr={completed.stderr}",
                )
                for leaf in (
                    "sidecar_health.json",
                    "sidecar_health.md",
                    "sidecar_health.receipt.json",
                ):
                    self.assertFalse(
                        (out_dir / leaf).exists(),
                        msg=f"{mode} left partial health surface: {leaf}",
                    )

    def test_launcher_runs_health_after_all_stages_and_keeps_unavailable_visible(self):
        text = (Path(__file__).resolve().parents[1] / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        self.assertIn("a_short_weekly_sidecar_health.py", text)
        self.assertIn("--m67-invocation", text)
        self.assertIn("{ 'skipped' } else { 'requested' }", text)
        self.assertRegex(
            text,
            r"if \(-not \$SkipSemanticRisk\) \{\s*"
            r"\$HealthArgs \+= @\('--pipeline-outcomes'",
        )
        self.assertNotIn("$M67StatusForHealth", text)
        self.assertNotIn("$WeeklyForHealth", text)
        self.assertNotRegex(text, r"Get-Content[^\r\n]*weekly_m67\.json")
        self.assertIn("[sidecar-health] UNAVAILABLE", text)
        self.assertLess(text.index("a_short_weekly_sidecar_health.py"), text.index("=== Pipeline done ==="))
        failure_writer = text.split(
            "function Write-M67Utf8NoBom", 1
        )[1].split("function Write-KnownM67FailureReceipt", 1)[0]
        for leaf in (
            "sidecar_health.json",
            "sidecar_health.md",
            "sidecar_health.receipt.json",
            "weekly_m67.pipeline_sidecar_outcomes.json",
            "launcher_sidecar_outcomes.json",
        ):
            self.assertIn(leaf, failure_writer)
        self.assertIn("a_short_weekly_sidecar_health.py", failure_writer)
        self.assertIn("'--m67-invocation', 'requested'", failure_writer)
        self.assertLess(
            failure_writer.index("Move-Item -LiteralPath $Tmp"),
            failure_writer.index("a_short_weekly_sidecar_health.py"),
        )

    def test_launcher_runs_theme_comparison_after_tracker_without_epoch_start(self):
        text = (Path(__file__).resolve().parents[1] / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        invocation = "runners\\a_short_theme_forward_comparison.py"
        self.assertIn(invocation, text)
        self.assertLess(text.index("forward_tracker.py backfill"), text.index(invocation))
        self.assertNotIn("--start-epoch", text)

    def test_launcher_registers_candidate_effect_and_iv_health_outcomes(self):
        text = (Path(__file__).resolve().parents[1] / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        self.assertIn("candidate_effect_outcome.json", text)
        self.assertIn("Add-SidecarOutcome -Name 'candidate_effect'", text)
        self.assertIn("Add-SidecarOutcome -Name 'iv_feed'", text)

    def test_pipeline_writes_outcomes_after_publish_without_rewriting_bundle(self):
        text = (Path(__file__).resolve().parents[1] / "runners" / "a_short_weekly_pipeline.py").read_text(encoding="utf-8")
        self.assertLess(text.index("receipt_path = publish_weekly_bundle("), text.rindex("_write_pipeline_sidecar_outcomes("))
        self.assertIn("official_operation_capture", text)
        self.assertIn("shared comparison cache", (Path(__file__).resolve().parents[1] / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
