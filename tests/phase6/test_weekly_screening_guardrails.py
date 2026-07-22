import shutil
import subprocess
import sys
import unittest
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "runners" / "weekly_screening.ps1"
CMD_LAUNCHER = ROOT / "runners" / "weekly_screening.cmd"


def _powershell_exe() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


class WeeklyScreeningGuardrailTest(unittest.TestCase):
    def test_cmd_launcher_runs_under_restricted_default_policy(self) -> None:
        cmd = os.environ.get("ComSpec") or shutil.which("cmd")
        if cmd is None:
            self.skipTest("cmd.exe not available")
        command = subprocess.list2cmdline([
            str(CMD_LAUNCHER),
            "-AsOf", "19000101",
            "-L3Mode", "neutralize",
            "-SkipCanary",
            "-SkipTracker",
            "-SkipSemanticRisk",
            "-PythonExe", sys.executable,
        ])
        result = subprocess.run(
            [cmd, "/d", "/s", "/c", command],
            cwd=ROOT,
            text=True,
            capture_output=True,
            errors="replace",
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("[OK] A-short preflight passed", output)
        self.assertIn("=== Weekly screening pipeline ===", output)
        self.assertIn("--as-of 19000101 is not an A-share trading day", output)
        self.assertNotIn("禁止运行脚本", output)

    def test_cmd_launcher_uses_process_scoped_bypass_only(self) -> None:
        text = CMD_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("-NoProfile -ExecutionPolicy Bypass -File", text)
        self.assertIn('"%~dp0weekly_screening.ps1" %*', text)
        self.assertNotIn("Set-ExecutionPolicy", text)

    def test_overlay_is_built_from_post_stage3_weekly_candidates(self) -> None:
        """M6.7 overlay must be the exact same batch as analysis_input candidates."""
        source = (ROOT / "A-EGS" / "egs_main.py").read_text(encoding="utf-8")
        stage3_pos = source.index("tier1_final, cninfo_checked = stage3_ai_clearing")
        watch_pos = source.index("watch_df  = top50.head(watch_n).copy()")
        self.assertIn("_ov_pool = watch_df[[", source)
        overlay_pos = source.index("_ov_pool = watch_df[[")

        self.assertLess(stage3_pos, watch_pos)
        self.assertLess(watch_pos, overlay_pos)
        self.assertNotIn("_ov_pool = top50[[", source)

    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        powershell = _powershell_exe()
        if powershell is None:
            self.skipTest("PowerShell executable not available")
        return subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPT),
                *args,
                "-SkipCanary",
                "-SkipTracker",
                "-SkipSemanticRisk",
                "-PythonExe",
                sys.executable,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            errors="replace",
        )

    def test_historical_asof_requires_explicit_l3_mode(self) -> None:
        result = self.run_script("-AsOf", "19000101")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("Historical -AsOf 19000101", output)
        self.assertIn("-L3Mode pit or -L3Mode neutralize", output)

    def test_historical_asof_rejects_today_l3_mode(self) -> None:
        result = self.run_script("-AsOf", "19000101", "-L3Mode", "today")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("cannot run with -L3Mode today", output)
        self.assertIn("-L3Mode pit", output)
        self.assertIn("-L3Mode neutralize", output)

    def test_historical_asof_refuses_existing_official_output(self) -> None:
        as_of = "19000103"
        target = ROOT / "result" / "a_short" / as_of
        if target.exists():
            self.skipTest(f"guardrail fixture path already exists: {target}")
        target.mkdir(parents=True)
        try:
            result = self.run_script("-AsOf", as_of, "-L3Mode", "neutralize")
        finally:
            target.rmdir()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("would overwrite existing official output", output)
        self.assertIn(str(target), output)

    def test_historical_asof_refuses_existing_default_xlsx_output(self) -> None:
        as_of = "19000104"
        target = ROOT / "A-EGS" / f"egs_tier1_{as_of}.xlsx"
        if target.exists():
            self.skipTest(f"guardrail fixture path already exists: {target}")
        target.write_text("guardrail fixture", encoding="utf-8")
        try:
            result = self.run_script("-AsOf", as_of, "-L3Mode", "neutralize")
        finally:
            target.unlink()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("would overwrite existing official output", output)
        self.assertIn(str(target), output)

    def test_pit_mode_uses_strict_snapshot_guard(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("$EgsArgs += '--l3-pit-strict'", text)
        self.assertIn("default --l3-mode=today is blocked", text)

    def test_canary_output_marks_sidecar_advisory(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("ConvertFrom-Json", text)
        self.assertIn(
            "sidecar only, not a data-pass and not a ship-gate signal",
            text,
        )

    def test_m67_stage_passes_account_and_labels_missing(self) -> None:
        # R-ASHORT-WEEKLYSCREENING-M67-MISSING-ACCOUNT: the one-click M6.7 stage must pass --account when a
        # reviewed account is provided, and the missing-account path must be LOUDLY labelled (not silently
        # emit a sizing-less 观察 that reads like a real avoid signal).
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("[string]$Account", text)                          # -Account param exists
        self.assertIn("$M67Args += @('--account', $Account)", text)      # valid account -> passed to the M6.7 pipeline
        self.assertIn("-Account path was not found", text)               # bad supplied path -> labelled
        self.assertIn("exit 23", text)                                  # bad supplied path -> fail requested M6.7 (no silent sizing-less run)
        self.assertIn("no -Account: observation-only", text)             # omitted account -> observation-only, labelled
        self.assertIn("sizing_mode=observation_only_no_account", text)   # points at the durable artifact marker
        self.assertIn("a_short_weekly_pipeline.py", text)                # the one-click stage IS the M6.7 pipeline
        self.assertNotIn("a_short_semantic_risk_summary.py", text)       # standalone summary CLI no longer invoked

    def test_m67_stage_exactly_forwards_optional_confirmation_files(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("[string]$RegulatoryConfirmations", text)
        self.assertIn("[string]$HoldingRegulatoryConfirmations", text)
        self.assertIn("@('--regulatory-confirmations', $RegulatoryConfirmations)", text)
        self.assertIn("@('--holding-regulatory-confirmations', $HoldingRegulatoryConfirmations)", text)
        self.assertNotIn("Test-Path $RegulatoryConfirmations", text)
        self.assertNotIn("Test-Path $HoldingRegulatoryConfirmations", text)

    def test_requested_m67_failures_are_receipted_and_nonzero(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Write-M67FailureReceipt", text)
        for reason in (
            "analysis_input_missing",
            "iv_feed_failed",
            "account_path_missing",
            "weekly_pipeline_failed",
        ):
            self.assertIn(reason, text)
        for exit_code in ("exit 21", "exit 22", "exit 23", "exit $M67ExitCode"):
            self.assertIn(exit_code, text)

    def test_preflight_runs_before_canonical_resolver_and_provider(self) -> None:
        # 刀3: dependency preflight must run BEFORE the canonical resolver (provider/network),
        # egs_main, and any private-state access.
        text = SCRIPT.read_text(encoding="utf-8")
        preflight = text.index("& $PythonExe $PreflightScript")
        resolver = text.index("& $PythonExe $ResolveScript")
        egs = text.index("& $PythonExe @EgsArgs")
        self.assertLess(preflight, resolver)
        self.assertLess(preflight, egs)
        self.assertIn("$null -eq $PreflightExit", text)

    def test_failure_receipt_invalidates_stale_and_records_identity(self) -> None:
        # 刀2: a failed known-date run removes the stale weekly_m67.json/.md (the old complete receipt
        # is unlinked FIRST, ErrorAction Stop) and records the real run identity, never fabricated;
        # every known-date failure stage writes a receipt.
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Remove-Item -LiteralPath $Stale -Force -ErrorAction Stop", text)
        self.assertLess(
            text.index("Remove-Item -LiteralPath $Receipt -Force -ErrorAction Stop"),
            text.index("Remove-Item -LiteralPath $Stale -Force -ErrorAction Stop"),
        )
        self.assertIn("$Payload['run_id']", text)
        self.assertIn("$Payload['candidate_digest']", text)
        for reason in ("preflight_failed", "entrypoint_missing", "egs_failed"):
            self.assertIn(reason, text)
        self.assertEqual(text.count("-AnalysisInput $SemAnalysisInput"), 3)

    def test_iv_feed_failure_receipt_is_wired_without_copying_error_text(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("$IvFailureReceipt", text)
        self.assertIn('"iv_feed_failure_$PID.json"', text)
        self.assertIn("Remove-Item -LiteralPath $IvFailureReceipt", text)
        self.assertIn("--failure-receipt-out $IvFailureReceipt", text)
        self.assertIn("-FailureDetailRef $IvFailureDetailRef", text)
        self.assertIn("failure_detail_ref", text)
        self.assertNotIn("Get-Content -Raw $IvFailureReceipt", text)

    def test_regime_stage_wired_live_only_nonblocking(self):
        # V14.3 regime comparison sidecar wired into the one-click weekly: runs only on a live run
        # (skipped for historical replay), non-blocking, bootstrap-or-increment by ledger existence.
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("a_short_regime_comparison_runner.py", text)        # the regime runner IS invoked
        self.assertIn("[switch]$SkipRegime", text)                       # opt-out switch exists
        self.assertIn("regime_daily_ledger.json", text)                  # ledger-existence check
        self.assertIn("$RegimeArgs += '--bootstrap'", text)              # absent ledger -> one-time backfill
        self.assertIn("only live runs advance the forward regime evidence", text)  # historical replay skipped
        self.assertIn("does NOT block the weekly", text)                 # non-blocking comparison-only sidecar
        self.assertIn("forward_tracker.py backfill --windows 5,10,20", text)
        self.assertIn("cache-only backfill", text)

    def test_factor_comparison_v2_cache_is_live_only_and_never_reuses_retired_v1_wiring(self):
        text = SCRIPT.read_text(encoding="utf-8")
        live_block = text[text.index("if (-not $IsHistoricalAsOf) {"):text.index("if (Test-Path $OverlayPath)")]
        self.assertIn("a_short_factor_comparison_v2_cache_build.py", live_block)
        self.assertIn("--factor-comparison-v2-root", live_block)
        self.assertIn("--factor-comparison-v2-daily-cache", live_block)
        self.assertIn("--factor-comparison-v2-forward", live_block)
        self.assertIn("M6.7/V14.3/overlay continue unchanged", live_block)
        pipeline = (ROOT / "runners" / "a_short_weekly_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("evidence is already frozen", pipeline)
        self.assertNotIn("--factor-comparison-root", text)
        self.assertNotIn("--factor-comparison-forward", text)
        self.assertNotIn("a_short_factor_comparison.py settle", text)

    def test_runner_readme_documents_regime_stage(self):
        # route-doc/entrypoint sync (R-V143-WEEKLYSCREENING-ROUTEDOC-STAGE5-DRIFT): the one-click operator
        # README must list the V14.3 regime sidecar while weekly_screening.ps1 invokes it + exposes -SkipRegime,
        # so an operator/LLM reading the active runner README cannot miss that the weekly does real regime work.
        ps1 = SCRIPT.read_text(encoding="utf-8")
        if "a_short_regime_comparison_runner.py" in ps1 and "$SkipRegime" in ps1:
            readme = (ROOT / "runners" / "README.md").read_text(encoding="utf-8")
            for token in ("a_short_regime_comparison_runner.py", "-SkipRegime", "--bootstrap",
                          "comparison-only", "非阻断"):
                self.assertIn(token, readme,
                              f"runners/README.md omits regime-stage token {token!r} while ps1 wires it (route-doc drift)")

    # R-ASHORT-WEEKLY-CANONICAL-ASOF-LIVE-HISTORICAL-CONTRACT-DRIFT anti-recurrence (BROADENED after Codex
    # re-审查 FAIL): after the 2026-06-22 canonical resolver, a valid LIVE run can have as_of > run_date
    # (a prospective Monday resolved from a weekend run); the live/historical boundary is `as_of < run_date`
    # everywhere (wrapper, egs guard, pipeline price-freshness, regime/M6.7/overlay gating). Active
    # cadence/price-freshness surfaces must NOT teach the same-day-only contract in ANY synonym. Patterns
    # are PRECISE to the same-day-ONLY framing so the correct today-OR-prospective wording (实盘当天/前瞻,
    # `run_date==as_of` named as a sub-case) and historical §0 prose (只实盘当天跑, no 在) are NOT false-flagged.
    SAME_DAY_ONLY_PATTERNS = ("as_of==运行日", "as_of == 运行日", "只在实盘当天跑",
                              "--run-date == --as-of", "--run-date==--as-of")
    CADENCE_SURFACES = ("runners/weekly_screening.ps1", "runners/README.md",
                        "docs/CURRENT.md", "runners/a_short_weekly_pipeline.py")

    @classmethod
    def _same_day_only_hits(cls, text):
        return [p for p in cls.SAME_DAY_ONLY_PATTERNS if p in text]

    def test_active_cadence_surfaces_no_same_day_only_wording(self):
        offenders = []
        for rel in self.CADENCE_SURFACES:
            text = (ROOT / rel).read_text(encoding="utf-8")
            for p in self._same_day_only_hits(text):
                offenders.append((rel, p))
        self.assertEqual(offenders, [],
                         f"active cadence/price-freshness surface still teaches same-day-only: {offenders}")
        # positive: the live model (canonical resolver + as_of>=run_date predicate) must be documented in ps1.
        ps1 = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("canonical", ps1, "ps1 must document the canonical-resolver cadence model")
        self.assertIn("as_of>=运行日", ps1.replace(" ", ""),
                      "ps1 must document the live predicate as_of>=run_date (incl. prospective canonical)")

    def test_same_day_only_guard_planted(self):
        # guard ↔ proof can't drift: each synonym is caught; the correct today-OR-prospective wording and
        # the historical §0 prose are NOT flagged (false-positive controls).
        self.assertTrue(self._same_day_only_hits("regime sidecar **只在实盘当天跑**(历史回放跳过)"),
                        "synonym 只在实盘当天跑 must be caught")
        self.assertTrue(self._same_day_only_hits("accept_prior_settled 仅由 main 在 `--run-date == --as-of` 传入"),
                        "synonym --run-date == --as-of must be caught")
        self.assertTrue(self._same_day_only_hits("M6.7 intraday/live 行为是 as_of==运行日"),
                        "synonym as_of==运行日 must be caught")
        self.assertEqual(self._same_day_only_hits("intraday(实盘当天/前瞻 canonical、要求 --as-of >= --run-date)"), [],
                         "correct today-OR-prospective wording must not be flagged")
        self.assertEqual(self._same_day_only_hits("as_of is today (run_date==as_of) OR a prospective session"), [],
                         "the today sub-case run_date==as_of (no dashes) must not be flagged")
        self.assertEqual(self._same_day_only_hits("③ regime 接进 weekly Stage 5 … 只实盘当天跑、非阻断"), [],
                         "historical §0 prose 只实盘当天跑 (no 在) must not be flagged")


if __name__ == "__main__":
    unittest.main()
