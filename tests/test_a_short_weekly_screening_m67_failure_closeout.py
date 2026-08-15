"""Static closeout guards for the weekly launcher #03/#04 repair."""
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "runners" / "weekly_screening.ps1"
US_SHORT_SCRIPT = ROOT / "runners" / "us_short_paper_one_click.ps1"


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

    def test_nonready_iv_is_recorded_but_still_invokes_degraded_pipeline(self) -> None:
        self.assertIn("if (-not $script:IvFeedReady)", self.stage4)
        self.assertIn("-Name 'iv_feed' -Expected $true -Attempted $true -ExecutionStatus 'failed'", self.stage4)
        self.assertNotIn("iv_feed_failed", self.stage4)
        self.assertIn("if ($script:M67InvocationState -eq 'requested')", self.stage4)
        self.assertIn("'--iv-feed-status', $script:IvFeedStatus", self.stage4)
        self.assertIn("if ($script:IvFeedReady) { $M67Args += @('--iv-feed', $IvFeed) }", self.stage4)

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
        self.assertIn("if ($M67InvocationState -eq 'complete' -and $DesignCompletionAuthorized)", self.stage5)
        self.assertIn("--v14_2-raw-regime", self.stage5)
        self.assertIn("--m67-report", self.stage5)
        self.assertIn("design completion is not authorized", complete_block)
        self.assertIn("design_not_complete", self.stage5)
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

    def test_design_completion_gate_comes_from_python_authority(self) -> None:
        self.assertIn("function Get-DesignCompletionAuthorized", self.text)
        self.assertIn(
            "from engine.a_short_evidence_epoch_mode import design_completion_authorized",
            self.text,
        )
        self.assertIn("$DesignCompletionAuthorization = Get-DesignCompletionAuthorized", self.stage5)
        self.assertIn(
            "$DesignCompletionAuthorized = ($DesignCompletionAuthorization -eq 'authorized')",
            self.stage5,
        )
        self.assertIn("$ProbeExitCode -ne 0", self.text)
        self.assertNotIn(
            "[string]$EpochModeAuthorization.design_completion_authorization.status -eq 'authorized'",
            self.text,
        )
        self.assertNotIn(
            "IsNullOrWhiteSpace([string]$EpochModeAuthorization.design_completion_authorization.directive)",
            self.text,
        )

    def test_all_three_powershell_python_source_calls_use_stdin(self) -> None:
        us_short = US_SHORT_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("$Probe | & $PythonExe -", self.text)
        self.assertIn("$OperationLoaderCode | & $PythonExe -", self.stage4)
        self.assertIn("$stderrToStdoutBootstrap | & $PythonExe - @cliArgs", us_short)
        self.assertNotRegex(self.text, r"(?:-c|[\"']-c[\"'])\s+\$(?:Probe|OperationLoaderCode)")
        self.assertNotRegex(us_short, r"(?:-c|[\"']-c[\"'])\s+\$stderrToStdoutBootstrap")

        source_argument_hazard = re.compile(
            r"(?<![\w])(?:-c|[\"']-c[\"'])\s+\$[A-Za-z_][A-Za-z0-9_]*"
        )
        stale = []
        for path in sorted((ROOT / "runners").glob("*.ps1")):
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if source_argument_hazard.search(line):
                    stale.append(f"{path.name}:{line_no}:{line.strip()}")
        self.assertEqual([], stale)

        planted = (
            "& $PythonExe -c $Probe",
            "& $PythonExe -c $OperationLoaderCode $ProjectRoot $M67Out",
            '& $PythonExe "-c" $stderrToStdoutBootstrap @cliArgs',
        )
        for old_call in planted:
            with self.subTest(old_call=old_call):
                self.assertIsNotNone(source_argument_hazard.search(old_call))

    def test_design_completion_probe_has_explicit_three_state_fail_closed_handling(self) -> None:
        for marker in ("return 'authorized'", "return 'not_authorized'", "return 'probe_failed'"):
            self.assertIn(marker, self.text)
        self.assertIn("$DesignCompletionAuthorization -eq 'probe_failed'", self.stage5)
        self.assertIn("design_completion_probe_failed", self.stage5)
        probe_start = self.stage5.index(
            "if ($M67InvocationState -eq 'complete' -and $DesignCompletionAuthorization -eq 'probe_failed')"
        )
        probe_end = self.stage5.index(
            "} elseif ($M67InvocationState -eq 'complete' -and -not $DesignCompletionAuthorized)",
            probe_start,
        )
        self.assertNotIn("design_not_complete", self.stage5[probe_start:probe_end])

    def test_skip_and_history_state_matrix_remains_explicit(self) -> None:
        self.assertIn("-SkipReason 'skip_regime'", self.stage5)
        self.assertIn("-SkipReason 'historical_replay'", self.stage5)
        self.assertIn("-SkipReason 'skip_semantic_risk'", self.stage5)
        self.assertIn("M6.7 not requested; running independent daily-only regime evidence", self.stage5)
        self.assertIn("$script:IvFeedReady -and (Test-Path -LiteralPath $RegimeIvFeed -PathType Leaf)", self.stage5)

    def test_successful_m67_reads_actual_operation_stage_and_paths(self) -> None:
        self.assertIn("validate_published_weekly_operation_bundle", self.stage4)
        self.assertIn('"stage_status": stage', self.stage4)
        self.assertIn("sys.stderr = sys.stdout", self.stage4)
        self.assertIn("$script:M67InvocationState = $OperationStage", self.stage4)
        self.assertIn("JSON=$M67Out Markdown=$OperationMarkdown", self.stage4)
        self.assertNotIn("$script:M67InvocationState = 'complete'", self.stage4)
        self.assertIn("weekly_operation_bundle_invalid", self.stage4)

    def test_noncomplete_operation_states_do_not_run_m67_dependent_regime_sidecars(self) -> None:
        self.assertIn(
            "$M67InvocationState -in @('degraded_no_new_entries', 'partial_holdings_only')",
            self.stage5,
        )
        self.assertIn("-SkipReason 'stage_not_complete'", self.stage5)
        self.assertIn("without M6.7-dependent action/effect binding", self.stage5)

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

    def test_failure_health_keeps_run_revision_and_receipt_identity_binding(self) -> None:
        self.assertIn("$Payload['run_revision_id'] = [string]$RunRevisionId", self.text)
        self.assertIn("$FailureHealthArgs += @('--run-revision-id', [string]$RunRevisionId)", self.text)
        self.assertIn(
            "-FailureDetailRef $FailureDetailRef -AnalysisInput $AnalysisInput -RunRevisionId $RunRevisionId",
            self.text,
        )
        self.assertIn("-RunRevisionId $RunRevisionId `", self.text)

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
