"""Offline V3-A/V4 cross-validation through the durable health consumer."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import a_short_theme_forward_comparison as theme_comparison  # noqa: E402
from runners.a_short_regime_comparison_runner import write_candidate_effect_outcome  # noqa: E402
from runners.a_short_weekly_pipeline import (  # noqa: E402
    _sidecar_result_fields,
    _write_pipeline_sidecar_outcomes,
)
from runners.a_short_weekly_sidecar_health import (  # noqa: E402
    OUTCOME_SCHEMA,
    build_health,
    write_health_bundle,
)
from tests.test_a_short_theme_forward_comparison import _week  # noqa: E402


AS_OF = "20260727"
RUN_ID = "a-short-20260727-0123456789abcdef"
CANDIDATE_DIGEST = "a" * 64


def _row(
    name: str,
    *,
    execution: str = "succeeded",
    progress: str = "unavailable",
    error_code: str | None = None,
    error_detail: str | None = None,
    observed_decision_as_of: str | None = None,
    observed_data_through: str | None = None,
) -> dict:
    return {
        "name": name,
        "expected": True,
        "attempted": True,
        "execution_status": execution,
        "progress_status": progress,
        "expected_data_through": None,
        "observed_decision_as_of": observed_decision_as_of,
        "observed_data_through": observed_data_through,
        "error_code": error_code,
        "error_detail": error_detail,
        "skip_reason": None,
    }


def _manifest(rows: list[dict], *, run_revision_id: str | None = None) -> dict:
    payload = {
        "schema_name": "a_short_weekly_sidecar_outcomes",
        "schema_version": "1.0.0",
        "as_of": AS_OF,
        "run_revision_id": run_revision_id,
        "run_id": RUN_ID,
        "candidate_digest": CANDIDATE_DIGEST,
        "expected_sidecars": [row["name"] for row in rows],
        "sidecars": rows,
    }
    jsonschema.validate(payload, json.loads(OUTCOME_SCHEMA.read_text(encoding="utf-8")))
    return payload


def _write_manifest(path: Path, payload: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_valid_candidate_summary(root: Path) -> Path:
    source = json.loads(
        (ROOT / "research/results/a_short/regime_candidate_effect_summary.json")
        .read_text(encoding="utf-8")
    )
    source["latest_evidence_as_of"] = None
    source["source_hash"] = "0" * 64
    path = root / "research/results/a_short/regime_candidate_effect_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_theme_packet(root: Path) -> Path:
    dates = pd.date_range("2026-01-02", periods=12, freq="7D").strftime("%Y%m%d")
    original_today = theme_comparison._today_date
    theme_comparison._today_date = lambda: date(2026, 12, 31)
    try:
        packet = theme_comparison.evaluate_theme_forward_comparison(
            pd.DataFrame([row for day in dates for row in _week(day)])
        )
    finally:
        theme_comparison._today_date = original_today
    packet["latest_evidence_as_of"] = AS_OF
    packet["rejected_atomic_cohorts"] = {
        AS_OF: "invalid taxonomy L3 snapshot date",
    }
    theme_comparison.validate_comparison_packet(packet)
    path = root / "research/results/a_short_theme_forward_comparison.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _assert_durable_bundle(test: unittest.TestCase, payload: dict, out_dir: Path) -> None:
    json_path, md_path, receipt_path = write_health_bundle(payload, out_dir)
    test.assertTrue(json_path.is_file())
    test.assertTrue(md_path.is_file())
    test.assertTrue(receipt_path.is_file())
    written = json_path.read_bytes()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    test.assertEqual(receipt["health_sha256"], hashlib.sha256(written).hexdigest())
    test.assertIn(payload["sidecars"][0]["name"], md_path.read_text(encoding="utf-8"))


class V3AV4CrossValidationTests(unittest.TestCase):
    def _build(self, root: Path, *, launcher=None, pipeline=None):
        return build_health(
            as_of=AS_OF,
            launcher_manifest=launcher,
            pipeline_manifest=pipeline,
            project_root=root,
            m67_invocation="requested",
            m67_out_dir=root / "m67",
        )

    def test_candidate_reason_survives_v3a_to_v4_authoritative_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = _write_valid_candidate_summary(root)
            outcome = write_candidate_effect_outcome(
                as_of=AS_OF,
                result={
                    "status": "updated",
                    "reason_code": "updated",
                    "summary": json.loads(summary_path.read_text(encoding="utf-8")),
                },
                summary_path=str(summary_path),
                outcome_path=str(root / "candidate_effect_outcome.json"),
            )
            launcher = _write_manifest(root / "launcher.json", _manifest([
                _row(
                    "candidate_effect",
                    progress="advanced",
                    observed_decision_as_of=outcome["observed_as_of"],
                ),
            ]))
            payload = self._build(root, launcher=launcher)
            item = payload["sidecars"][0]
            self.assertEqual(item["progress_status"], "unavailable")
            self.assertEqual(item["error_code"], "candidate_effect_no_observed_evidence")
            self.assertEqual(item["error_detail"], "authoritative_summary_observed_as_of=missing")
            _assert_durable_bundle(self, payload, root / "health")

    def test_industry_and_overlay_conflicts_survive_v4_without_advanced_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = [
                "industry_weight_capture", "industry_weight_settlement",
                "overlay_adjudication_capture", "overlay_adjudication_settlement",
            ]
            rows = []
            for name in names:
                progress, code, detail = _sidecar_result_fields({
                    "status": "conflict_recorded_no_count",
                    "reason_code": "immutable_capture_conflict",
                })
                rows.append(_row(
                    name,
                    progress=progress,
                    error_code=code,
                    error_detail=detail,
                    observed_decision_as_of=AS_OF,
                ))
            _write_pipeline_sidecar_outcomes(
                root / "weekly_m67.pipeline_sidecar_outcomes.json",
                as_of=AS_OF,
                run_id=RUN_ID,
                candidate_digest=CANDIDATE_DIGEST,
                expected=names,
                outcomes=rows,
            )
            pipeline = json.loads(
                (root / "weekly_m67.pipeline_sidecar_outcomes.json")
                .read_text(encoding="utf-8")
            )
            payload = self._build(root, pipeline=pipeline)
            by_name = {item["name"]: item for item in payload["sidecars"]}
            for name in names:
                self.assertEqual(by_name[name]["progress_status"], "stalled")
                self.assertEqual(by_name[name]["error_code"], "immutable_capture_conflict")
                self.assertNotEqual(by_name[name]["progress_status"], "advanced")
            _assert_durable_bundle(self, payload, root / "health")

    def test_theme_reason_and_v4_clock_survive_in_same_health_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_theme_packet(root)
            progress, code, _detail = _sidecar_result_fields({
                "status": "unavailable",
                "reason_code": "theme_cohort_rejected",
            })
            launcher = _write_manifest(root / "launcher.json", _manifest([
                _row(
                    "theme_forward_comparison",
                    progress=progress,
                    error_code=code,
                    error_detail="reason=ValueError: invalid taxonomy L3 snapshot date",
                ),
            ]))
            payload = self._build(root, launcher=launcher)
            item = payload["sidecars"][0]
            self.assertEqual(item["progress_status"], "unavailable")
            self.assertEqual(item["observed_decision_as_of"], AS_OF)
            self.assertEqual(item["error_code"], "theme_cohort_rejected")
            self.assertIn("invalid taxonomy L3 snapshot date", item["error_detail"])
            _assert_durable_bundle(self, payload, root / "health")


if __name__ == "__main__":
    unittest.main()
