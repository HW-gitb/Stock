import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "runners" / "weekly_screening.ps1"


def _powershell_exe() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


class WeeklyScreeningGuardrailTest(unittest.TestCase):
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
        self.assertIn("-Account path not found", text)                   # bad supplied path -> labelled
        self.assertIn("$RunM67 = $false", text)                          # bad supplied path -> SKIP (no silent sizing-less run)
        self.assertIn("no -Account: observation-only", text)             # omitted account -> observation-only, labelled
        self.assertIn("sizing_mode=observation_only_no_account", text)   # points at the durable artifact marker
        self.assertIn("a_short_weekly_pipeline.py", text)                # the one-click stage IS the M6.7 pipeline
        self.assertNotIn("a_short_semantic_risk_summary.py", text)       # standalone summary CLI no longer invoked

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
