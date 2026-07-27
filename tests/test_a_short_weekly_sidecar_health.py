"""Focused tests for the A-short P4 health companion."""
from __future__ import annotations

import json
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
    build_health,
    write_health_bundle,
)
from runners import a_short_weekly_sidecar_health as sidecar_health
from runners.a_short_regime_comparison_runner import write_candidate_effect_outcome


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


class AShortSidecarHealthTests(unittest.TestCase):
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
            source = root / "weekly_m67.receipt.json"
            source.write_text('{"stage_status":"complete"}\n', encoding="utf-8")
            paths = write_health_bundle(result, root, source)
            payload = json.loads(paths[0].read_text(encoding="utf-8"))
            jsonschema.validate(payload, json.loads(HEALTH_SCHEMA.read_text(encoding="utf-8")))
            self.assertEqual(len(payload["source_receipt_sha256"]), 64)
            self.assertNotIn("ts_code", paths[1].read_text(encoding="utf-8"))
            self.assertNotIn(str(root), paths[1].read_text(encoding="utf-8"))


class AShortSidecarOutcomeSchemaTests(unittest.TestCase):
    def test_manifest_schema_is_closed(self):
        manifest = _manifest([_row("data_canary")])
        jsonschema.validate(manifest, json.loads(OUTCOME_SCHEMA.read_text(encoding="utf-8")))

    def test_launcher_runs_health_after_all_stages_and_keeps_unavailable_visible(self):
        text = (Path(__file__).resolve().parents[1] / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        self.assertIn("a_short_weekly_sidecar_health.py", text)
        self.assertIn("--weekly-receipt", text)
        self.assertIn("[sidecar-health] UNAVAILABLE", text)
        self.assertLess(text.index("a_short_weekly_sidecar_health.py"), text.index("=== Pipeline done ==="))

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
