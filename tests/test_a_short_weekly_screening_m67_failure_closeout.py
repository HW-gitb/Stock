"""Static closeout guards for the weekly launcher #03/#04 repair."""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "runners" / "weekly_screening.ps1"


class AShortWeeklyM67FailureCloseoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SCRIPT.read_text(encoding="utf-8")
        cls.stage4 = cls.text[cls.text.index("# --- Stage 4"):cls.text.index("# --- Stage 5")]
        cls.stage5 = cls.text[cls.text.index("# --- Stage 5"):cls.text.index("# P4: health")]

    def test_all_post_egs_failures_use_one_deferred_aggregator(self) -> None:
        self.assertIn("function Set-M67Failure", self.text)
        for reason in (
            "analysis_input_missing",
            "iv_feed_failed",
            "account_path_missing",
            "weekly_pipeline_failed",
        ):
            self.assertRegex(
                self.stage4,
                rf"Set-M67Failure\s+-Reason '{reason}'",
                reason,
            )
        self.assertIn("[switch]$DeferHealth", self.text)
        self.assertIn("if ($DeferHealth)", self.text)
        self.assertNotRegex(self.stage4, r"^\s*exit\s+", re.MULTILINE)

    def test_first_m67_failure_code_is_preserved_and_only_final_exit_remains(self) -> None:
        self.assertIn("if ($script:FinalExitCode -eq 0)", self.text)
        self.assertIn("$script:FinalExitCode = $ExitCode", self.text)
        closeout = self.text[self.text.index("# P4: health"):]
        self.assertEqual(re.findall(r"^\s*exit\s+", closeout, re.MULTILINE), ["exit "])
        self.assertIn("exit $FinalExitCode", closeout)
        self.assertNotIn("exit $M67ExitCode", self.stage4)

    def test_failed_stage5_is_daily_only_and_keeps_unattempted_dependencies(self) -> None:
        complete_start = self.stage5.index("if ($M67InvocationState -eq 'complete')")
        failed_start = self.stage5.index("} elseif ($M67InvocationState -eq 'failed')", complete_start)
        failed_end = self.stage5.index("} else {", failed_start)
        complete_block = self.stage5[complete_start:failed_start]
        failed_block = self.stage5[failed_start:failed_end]
        self.assertIn("--v14_2-raw-regime", complete_block)
        self.assertIn("--m67-report", complete_block)
        self.assertNotIn("--v14_2-raw-regime", failed_block)
        self.assertNotIn("--m67-report", failed_block)
        self.assertIn(
            "-Name 'regime_action' -Expected $true -Attempted $false "
            "-ExecutionStatus 'failed' -ProgressStatus 'unavailable' -ErrorCode 'm67_failed'",
            self.stage5,
        )
        self.assertIn(
            "-Name 'candidate_effect' -Expected $true -Attempted $false "
            "-ExecutionStatus 'failed' -ProgressStatus 'unavailable' -ErrorCode 'm67_failed'",
            self.stage5,
        )
        self.assertNotIn("$SemAnalysisInput", failed_block)
        self.assertNotIn("$M67Out", failed_block)

    def test_skip_and_history_state_matrix_remains_explicit(self) -> None:
        self.assertIn("-SkipReason 'skip_regime'", self.stage5)
        self.assertIn("-SkipReason 'historical_replay'", self.stage5)
        self.assertIn("-SkipReason 'skip_semantic_risk'", self.stage5)
        self.assertIn("M6.7 not requested; running independent daily-only regime evidence", self.stage5)
        self.assertIn("$script:IvFeedReady -and (Test-Path -LiteralPath $RegimeIvFeed -PathType Leaf)", self.stage5)

    def test_atomic_launcher_and_health_fail_closed(self) -> None:
        self.assertIn("$LauncherManifestTmp", self.text)
        self.assertIn("Move-Item -LiteralPath $LauncherManifestTmp -Destination $LauncherManifestPath", self.text)
        self.assertIn("$HealthComplete = ($HealthExitCode -eq 0)", self.text)
        self.assertIn("health companion failed or returned an incomplete JSON/Markdown/receipt trio", self.text)
        self.assertGreaterEqual(self.text.count("Invalidate-M67Artifact -LiteralPath (Join-Path $HealthDir $Leaf)"), 2)
        self.assertEqual(self.text.count("& $PythonExe @HealthArgs"), 1)
        for expected in (
            "official_operation_capture",
            "official_operation_settlement",
            "factor_v2_capture",
            "industry_weight_capture",
            "industry_weight_settlement",
            "target_policy_capture",
            "final_action_capture",
            "overlay_adjudication_capture",
            "overlay_adjudication_settlement",
        ):
            self.assertIn(f"'{expected}'", self.text)

    def test_v5a_required_readers_and_o24_selection_clocks_are_explicit(self) -> None:
        self.assertIn("$IvFailureReceipt = Join-Path $ResearchRevisionDir", self.text)
        self.assertIn(
            "a_short_crash_veto_tracker.py update --as-of $AsOf --rule-confirmed-days 5 "
            "--run-revision-id $RunRevisionId --official-project-root $ProjectRoot --confirm-fetch-authorized",
            self.text,
        )
        self.assertIn("if ($IsHistoricalAsOf) {", self.text)
        self.assertIn("$SelectionStatus = 'validation_only'", self.text)
        self.assertIn("official pointer unchanged", self.text)
        self.assertNotIn("$SelectArgs += '--cutoff-passed'", self.text)
        self.assertIn("if ($FormalStateCommitted) { $SelectArgs += '--formal-state-committed' }", self.text)


if __name__ == "__main__":
    unittest.main()
