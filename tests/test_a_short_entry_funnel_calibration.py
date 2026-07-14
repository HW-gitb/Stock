from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft7Validator

from runners.a_short_entry_funnel_calibration import (
    PREREG_PATH,
    PREREG_SCHEMA_PATH,
    REPORT_SCHEMA_PATH,
    build_report,
    load_json,
    main,
)


class AShortEntryFunnelCalibrationTests(unittest.TestCase):
    def test_frozen_preregistration_and_real_seen_report_validate(self) -> None:
        prereg = load_json(PREREG_PATH)
        self.assertEqual(
            list(Draft7Validator(load_json(PREREG_SCHEMA_PATH)).iter_errors(prereg)), []
        )
        report = build_report(prereg, "2026-07-13T18:30:00+08:00")
        self.assertEqual(
            list(Draft7Validator(load_json(REPORT_SCHEMA_PATH)).iter_errors(report)), []
        )
        self.assertEqual(report["funnel"]["candidate_count"], 38)
        self.assertEqual(report["funnel"]["hard_veto_count"], 8)
        self.assertEqual(report["funnel"]["ma_shape_failure_count"], 8)
        self.assertEqual(report["funnel"]["entry_trigger_failure_count"], 22)
        self.assertEqual(report["funnel"]["rr_plan_count"], 0)
        self.assertEqual(
            report["calibration_conclusion"]["status"],
            "insufficient_sample_with_entry_trigger_bottleneck",
        )

    def test_iv_boundary_and_overlay_seen_future_split_are_frozen(self) -> None:
        report = build_report(load_json(PREREG_PATH), "2026-07-13T18:30:00+08:00")
        self.assertEqual(report["iv_boundary"]["observation_count"], 7)
        self.assertEqual(report["iv_boundary"]["above_80_count"], 4)
        self.assertEqual(report["iv_boundary"]["above_90_count"], 2)
        self.assertEqual(report["overlay_evidence"]["seen_observations"], 4)
        self.assertEqual(report["overlay_evidence"]["future_confirmatory_observations"], 0)
        self.assertFalse(report["overlay_evidence"]["promotion_evaluable"])

    def test_cli_writes_only_calibration_not_threshold_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "calibration_report.json"
            self.assertEqual(main(["--out", str(out)]), 0)
            report = json.loads(out.read_text(encoding="utf-8"))
        self.assertFalse(report["calibration_conclusion"]["production_threshold_change"])
        self.assertFalse(report["boundary"]["full_size_allowed"])


if __name__ == "__main__":
    unittest.main()
