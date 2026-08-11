"""Fourth-knife wiring tests for the A-short P4 sidecar."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]


ACTIVE_P4_ASSIGNMENTS = (
    "$OverlayAdjudicationStage3 = Join-Path $PublicRevisionDir 'stage3_selection_snapshot.json'",
    "$OverlayAdjudicationSource = Join-Path $PublicRevisionDir 'stage3_overlay_score.json'",
    "$OverlayAdjudicationMarker = Join-Path $PublicRevisionDir 'official_publish.json'",
)


class FourthKnifeP4WiringTests(unittest.TestCase):
    def _assert_p4_wiring(self, text: str) -> None:
        """The gate itself, callable on any launcher text so it can be planted against."""
        required = (
            "$OverlayAdjudicationRoot = Join-Path $ProjectRoot 'state\\a_short\\overlay_adjudication_private\\v1'",
            "$OverlayAdjudicationStage3 = Join-Path $PublicRevisionDir 'stage3_selection_snapshot.json'",
            "$OverlayAdjudicationSource = Join-Path $PublicRevisionDir 'stage3_overlay_score.json'",
            "$OverlayAdjudicationMarker = Join-Path $PublicRevisionDir 'official_publish.json'",
            "'research\\results\\a_short\\overlay_adjudication_summary.json'",
            "'research\\results\\a_short\\overlay_adjudication_summary.md'",
            "--overlay-adjudication-root $OverlayAdjudicationRoot",
            "'--overlay-adjudication-daily-cache', $FactorComparisonV2Cache",
            "'--overlay-adjudication-stage3-snapshot', $OverlayAdjudicationStage3",
            "'--overlay-adjudication-overlay-source', $OverlayAdjudicationSource",
            "'--overlay-adjudication-egs-publish-marker', $OverlayAdjudicationMarker",
            "'--overlay-adjudication-forward')",
        )
        for needle in required:
            self.assertIn(needle, text)
        for legacy in (
            '# "result\\a_short\\$AsOf\\stage3_selection_snapshot.json"',
            '# "result\\a_short\\$AsOf\\stage3_overlay_score.json"',
            '# "result\\a_short\\$AsOf\\official_publish.json"',
        ):
            self.assertNotIn(legacy, text)
        cache_call = next(line for line in text.splitlines() if "a_short_factor_comparison_v2_cache_build.py" in line)
        self.assertIn("--overlay-adjudication-root $OverlayAdjudicationRoot", cache_call)
        self.assertEqual(text.count("'--overlay-adjudication-forward')"), 1)

    def test_standard_launcher_wires_one_as_of_p4_bucket_and_shared_cache(self) -> None:
        self._assert_p4_wiring((ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8"))

    def test_p4_guard_rejects_planted_wrong_active_assignment(self) -> None:
        """Patch the subject, not the yardstick: a broken assignment must make the gate raise."""
        text = (ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        for expected in ACTIVE_P4_ASSIGNMENTS:
            with self.subTest(assignment=expected):
                planted = text.replace(expected, expected.rsplit(" ", 1)[0] + " 'PLANTED_WRONG_TARGET.json'")
                self.assertNotEqual(planted, text, "anchor moved; update this planted control")
                with self.assertRaises(AssertionError):
                    self._assert_p4_wiring(planted)

    def test_p4_forward_flag_is_inside_live_branch(self) -> None:
        text = (ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        live_start = text.index("if (-not $IsHistoricalAsOf) {")
        forward = text.index("'--overlay-adjudication-forward')")
        self.assertGreater(forward, live_start)

    def test_weekly_schema_accepts_terminal_p4_statuses(self) -> None:
        schema = json.loads((ROOT / "schemas" / "a_short_weekly_report.schema.json").read_text(encoding="utf-8"))
        reminder_schema = schema["properties"]["a_short_evidence_reminders"]
        terminal = {
            "schema_name": "a_short_evidence_reminders",
            "schema_version": "1.0.0",
            "as_of": "20260724",
            "status": "closed",
            "reminders": [{
                "track": "p4b_manual_promotion",
                "status": "retain_baseline",
                "message": "保留现有基线，不替换；不会自动改 production 配置。",
            }],
            "message": "comparison-only",
            "production_unchanged": True,
        }
        jsonschema.validate(terminal, reminder_schema)


if __name__ == "__main__":
    unittest.main()
