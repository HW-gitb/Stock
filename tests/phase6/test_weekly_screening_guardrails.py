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


if __name__ == "__main__":
    unittest.main()
