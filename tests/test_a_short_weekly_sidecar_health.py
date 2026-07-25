"""Focused tests for the A-short P4 health companion."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from runners.a_short_weekly_sidecar_health import (
    HEALTH_SCHEMA,
    OUTCOME_SCHEMA,
    build_health,
    write_health_bundle,
)


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


class AShortSidecarHealthTests(unittest.TestCase):
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

    def test_pipeline_writes_outcomes_after_publish_without_rewriting_bundle(self):
        text = (Path(__file__).resolve().parents[1] / "runners" / "a_short_weekly_pipeline.py").read_text(encoding="utf-8")
        self.assertLess(text.index("receipt_path = publish_weekly_bundle("), text.rindex("_write_pipeline_sidecar_outcomes("))
        self.assertIn("official_operation_capture", text)
        self.assertIn("shared comparison cache", (Path(__file__).resolve().parents[1] / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
