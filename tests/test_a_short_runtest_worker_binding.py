import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
PINNED_STOCK_PYTHON = r"C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe"


class AShortRuntestWorkerBindingTests(unittest.TestCase):
    """Exercise the real A-short wrapper without a provider or full runtest."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.source_root = self.base / "source"
        self.runners = self.source_root / "runners"
        self.runners.mkdir(parents=True)
        (self.source_root / ".tools").mkdir()
        (self.source_root / ".tools" / "Resolve-AshortPython.ps1").write_text(
            "throw 'Foreign SourceRoot resolver must never be loaded.'\n",
            encoding="utf-8",
        )
        (self.runners / "runtest_capsule.py").write_text(
            """import json
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
command = args[args.index("create")] if "create" in args else args[args.index("activate")] if "activate" in args else args[args.index("finish")]

def value(name):
    return args[args.index(name) + 1]

if command == "create":
    capsule = Path(value("--capsule-root")) / "a_short" / value("--run-id")
    repo = capsule / "repo"
    (repo / "runners").mkdir(parents=True)
    shutil.copy2(Path(value("--source-root")) / "runners" / "weekly_screening.ps1", repo / "runners" / "weekly_screening.ps1")
    print(json.dumps({"capsule": str(capsule), "repo": str(repo)}))
""",
            encoding="utf-8",
        )
        (self.runners / "weekly_screening.ps1").write_text(
            """param(
    [string]$AsOf = '',
    [string]$CanarySource = '',
    [string]$L3Mode = '',
    [string]$CachePolicy = '',
    [string]$PythonExe = '',
    [string]$Account = ''
)

[ordered]@{
    as_of = $AsOf
    canary_source = $CanarySource
    l3_mode = $L3Mode
    cache_policy = $CachePolicy
    python_exe = $PythonExe
    account = $Account
} | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:RUNTEST_TEST_CAPTURE_PATH -Encoding utf8
""",
            encoding="utf-8",
        )
        self.account = self.base / "account.json"
        self.account.write_text("{}\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_worker_parameters_are_bound_by_name_for_default_and_account_runs(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell executable not available")

        script = ROOT / "runners" / "a_short_runtest.ps1"
        escaped = lambda path: str(path).replace("'", "''")
        cases = (
            ("default", (), "", ""),
            ("account", ("-AsOf", "20260721", "-Account", self.account), "20260721", "a_short_account"),
        )
        for name, extra_args, expected_as_of, expected_account_leaf in cases:
            with self.subTest(name=name):
                capsule_root = self.base / f"capsules_{name}"
                capture = self.base / f"worker_capture_{name}.json"
                command_parts = [
                    f"& '{escaped(script)}'",
                    "-ConfirmRuntest",
                    f"-SourceRoot '{escaped(self.source_root)}'",
                    f"-CapsuleRoot '{escaped(capsule_root)}'",
                    f"-RunId 'worker-binding-{name}'",
                ]
                for value in extra_args:
                    command_parts.append(str(value) if str(value).startswith("-") else f"'{escaped(value)}'")
                environment = os.environ.copy()
                environment["RUNTEST_TEST_CAPTURE_PATH"] = str(capture)
                environment["PATH"] = r"C:\not-a-python-path"
                result = subprocess.run(
                    [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", " ".join(command_parts)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    errors="replace",
                    env=environment,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                captured = json.loads(capture.read_text(encoding="utf-8-sig"))
                capsule = capsule_root / "a_short" / f"worker-binding-{name}"
                self.assertEqual(captured["as_of"], expected_as_of)
                self.assertEqual(captured["canary_source"], "")
                self.assertEqual(captured["l3_mode"], "today")
                self.assertEqual(captured["cache_policy"], "disabled")
                self.assertEqual(captured["python_exe"].casefold(), PINNED_STOCK_PYTHON.casefold())
                expected_account = str(capsule / "private_inputs" / expected_account_leaf) if expected_account_leaf else ""
                self.assertEqual(captured["account"], expected_account)

    def test_raw_extra_args_are_rejected_before_a_capsule_is_created(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell executable not available")

        script = str(ROOT / "runners" / "a_short_runtest.ps1").replace("'", "''")
        source_root = str(self.source_root).replace("'", "''")
        capsule_root = self.base / "rejected_extra_args"
        escaped_capsule_root = str(capsule_root).replace("'", "''")
        command = (
            f"& '{script}' -ConfirmRuntest -SourceRoot '{source_root}' "
            f"-CapsuleRoot '{escaped_capsule_root}' "
            "-ExtraArgs @('--cache-policy', 'enabled')"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT,
            text=True,
            capture_output=True,
            errors="replace",
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(capsule_root.exists())


if __name__ == "__main__":
    unittest.main()
