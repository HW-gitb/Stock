import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "runners" / "runtest_capsule.py"
PINNED_STOCK_PYTHON = r"C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe"


def _load_module():
    spec = importlib.util.spec_from_file_location("runtest_capsule_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


capsule = _load_module()


class RuntestCapsuleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.source = self.base / "source"
        self.root = self.base / "capsules"
        self.key = self.base / "external" / "capsule.key"
        self.source.mkdir()
        self._git("init")
        self._git("config", "user.email", "runtest@example.invalid")
        self._git("config", "user.name", "runtest")
        (self.source / ".gitignore").write_text(
            "A-EGS/Result/\nlogs/\nstate/a_short/\nprovider_samples/\nresult/a_short/\nresearch/results/a_short/\n",
            encoding="utf-8",
        )
        (self.source / "runners").mkdir()
        (self.source / "runners" / "entry.py").write_text("print('tracked source')\n", encoding="utf-8")
        # These simulate a prior formal run.  A normal clone must not bring
        # ignored caches/checkpoints/private output into a runtest capsule.
        (self.source / "A-EGS" / "Result").mkdir(parents=True)
        (self.source / "A-EGS" / "Result" / "old_cache.pkl").write_bytes(b"old-cache")
        (self.source / "state" / "a_short").mkdir(parents=True)
        (self.source / "state" / "a_short" / "old_checkpoint.json").write_text("{}", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "-m", "fixture")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=self.source,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _create(self, run_id: str = "run-001", *, inputs=None):
        return capsule.create_capsule(
            source_root=self.source,
            capsule_root=self.root,
            market="a_short",
            run_id=run_id,
            copy_inputs=inputs,
            key_path=self.key,
        )

    def _manifest(self, created):
        return json.loads(Path(created["manifest"]).read_text(encoding="utf-8"))

    def test_create_is_fresh_detached_and_records_nonproduction_contract(self) -> None:
        before = capsule.source_guard_snapshot(self.source)
        created = self._create()
        repo = Path(created["repo"])
        manifest = self._manifest(created)

        self.assertTrue((repo / ".git").exists())
        self.assertFalse((repo / "A-EGS" / "Result" / "old_cache.pkl").exists())
        self.assertFalse((repo / "state" / "a_short" / "old_checkpoint.json").exists())
        self.assertEqual(manifest["run_mode"], "runtest")
        self.assertFalse(manifest["production_eligible"])
        self.assertFalse(manifest["ship_gate_evidence_allowed"])
        self.assertEqual(manifest["cache_policy"], "disabled")
        self.assertEqual(
            manifest["forbidden_runtime_reuse"],
            ["cache", "checkpoint", "resume", "provider_raw", "source_packet"],
        )
        self.assertEqual(manifest["source_guard_before"], before)
        self.assertTrue(self.key.is_file())
        self.assertFalse(str(self.key).startswith(str(self.root)))

    def test_windows_path_preflight_stops_before_clone_creates_a_partial_capsule(self) -> None:
        calls: list[list[str]] = []

        def fake_git(args: list[str], *, cwd=None) -> str:
            del cwd
            calls.append(args)
            if "rev-parse" in args:
                return "a" * 40
            if "ls-tree" in args:
                return "x" * (capsule.WINDOWS_CHECKOUT_PATH_LIMIT + 1)
            self.fail(f"checkout path preflight must reject before git {' '.join(args)}")

        with mock.patch.object(capsule.os, "name", "nt"):
            with mock.patch.object(capsule, "_run_git", side_effect=fake_git):
                with self.assertRaisesRegex(capsule.CapsuleError, "capsule root is too long"):
                    self._create("path-budget")

        target = self.root / "a_short" / "path-budget"
        self.assertFalse(target.exists())
        self.assertFalse(any(args and args[0] == "clone" for args in calls))

    def test_failed_create_reuses_readonly_safe_capsule_cleanup(self) -> None:
        target = self.root / "a_short" / "clone-failure"
        repo = target / "repo"

        def fake_git(args: list[str], *, cwd=None) -> str:
            del cwd
            if "rev-parse" in args:
                return "a" * 40
            if "ls-tree" in args:
                return "runners/entry.py"
            if args and args[0] == "clone":
                repo.mkdir(parents=True)
                read_only = repo / "read_only_git_file"
                read_only.write_text("partial clone", encoding="utf-8")
                os.chmod(read_only, 0o444)
                raise capsule.CapsuleError("git clone failed")
            self.fail(f"unexpected git call: {' '.join(args)}")

        with mock.patch.object(capsule, "_run_git", side_effect=fake_git):
            with self.assertRaisesRegex(capsule.CapsuleError, "git clone failed"):
                self._create("clone-failure")

        self.assertFalse(target.exists())

    def test_private_input_is_copied_only_under_capsule_and_not_written_to_manifest(self) -> None:
        private_input = self.base / "manual_account.json"
        private_input.write_text('{"secret":"must-not-appear"}', encoding="utf-8")
        created = self._create(inputs={"a_short_account": private_input})

        copied = Path(created["capsule"]) / "private_inputs" / "a_short_account"
        manifest_text = Path(created["manifest"]).read_text(encoding="utf-8")
        self.assertEqual(copied.read_text(encoding="utf-8"), private_input.read_text(encoding="utf-8"))
        self.assertIn("a_short_account", manifest_text)
        self.assertNotIn("must-not-appear", manifest_text)
        self.assertNotIn(str(private_input), manifest_text)

    def test_active_capsule_cannot_be_deleted_then_completed_capsule_deletes_only_itself(self) -> None:
        created = self._create()
        target = Path(created["capsule"])
        capsule.activate_capsule(target, capsule_root=self.root, key_path=self.key)
        with self.assertRaisesRegex(capsule.CapsuleError, "active"):
            capsule.delete_capsule(target, capsule_root=self.root, key_path=self.key)
        self.assertTrue(target.exists())

        outcome = capsule.finish_capsule(target, exit_code=0, capsule_root=self.root, key_path=self.key)
        self.assertEqual(outcome["status"], "completed")
        capsule.delete_capsule(target, capsule_root=self.root, key_path=self.key)
        self.assertFalse(target.exists())
        self.assertTrue(self.source.exists())
        self.assertTrue((self.source / ".git").exists())

    def test_source_output_change_during_run_fails_closed_and_retains_capsule(self) -> None:
        created = self._create()
        target = Path(created["capsule"])
        capsule.activate_capsule(target, capsule_root=self.root, key_path=self.key)
        (self.source / "logs").mkdir(exist_ok=True)
        (self.source / "logs" / "unexpected_main_tree_write.log").write_text("changed", encoding="utf-8")

        with self.assertRaisesRegex(capsule.CapsuleError, "source output guard changed"):
            capsule.finish_capsule(target, exit_code=0, capsule_root=self.root, key_path=self.key)
        manifest = self._manifest(created)
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse(manifest["source_guard_unchanged"])
        self.assertTrue(target.exists())

    def test_source_toplevel_aegs_xlsx_change_during_run_fails_closed(self) -> None:
        # EGS writes egs_tier1_*.xlsx to the A-EGS/ top level (CONF["xlsx_dir"]
        # default SCRIPT_DIR), not A-EGS/Result/, so the guard must cover
        # A-EGS/*.xlsx directly or a source-side workbook mutation goes unseen.
        xlsx = self.source / "A-EGS" / "egs_tier1_20260101.xlsx"
        xlsx.write_bytes(b"baseline-workbook")
        created = self._create()
        target = Path(created["capsule"])
        capsule.activate_capsule(target, capsule_root=self.root, key_path=self.key)
        xlsx.write_bytes(b"mutated-workbook-with-a-different-size")

        with self.assertRaisesRegex(capsule.CapsuleError, "source output guard changed"):
            capsule.finish_capsule(target, exit_code=0, capsule_root=self.root, key_path=self.key)
        manifest = self._manifest(created)
        self.assertEqual(manifest["status"], "failed")
        self.assertFalse(manifest["source_guard_unchanged"])
        self.assertTrue(target.exists())

    def test_tampered_manifest_and_traversal_path_cannot_delete_anything(self) -> None:
        created = self._create()
        target = Path(created["capsule"])
        manifest_path = Path(created["manifest"])
        manifest_path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(capsule.CapsuleError, "signature"):
            capsule.delete_capsule(target, capsule_root=self.root, key_path=self.key)
        self.assertTrue(target.exists())
        with self.assertRaises(capsule.CapsuleError):
            capsule.delete_capsule(self.base, capsule_root=self.root, key_path=self.key)
        self.assertTrue(self.source.exists())

    def test_launchers_keep_full_entry_in_capsule_and_forbid_reuse(self) -> None:
        a_short = (ROOT / "runners" / "a_short_runtest.ps1").read_text(encoding="utf-8")
        us_short = (ROOT / "runners" / "us_short_runtest.ps1").read_text(encoding="utf-8")
        weekly = (ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$ConfirmRuntest", a_short)
        self.assertIn("'runners\\weekly_screening.ps1'", a_short)
        self.assertIn("'TEMP', 'TMP', 'XDG_CACHE_HOME', 'PYTHONPYCACHEPREFIX'", a_short)
        self.assertNotIn("$WorkerArgs", a_short)
        self.assertIn("$WorkerParams = @{", a_short)
        # The splat must still name the mode itself (never leave it to the worker
        # default) and must still fall back to today when the caller asks for nothing;
        # a historical replay is the only reason it may carry anything else.
        self.assertIn(
            "L3Mode = if ([string]::IsNullOrWhiteSpace($L3Mode)) { 'today' } else { $L3Mode }",
            a_short,
        )
        self.assertIn("[ValidateSet('', 'today', 'pit', 'neutralize')]", a_short)
        self.assertIn("CachePolicy = 'disabled'", a_short)
        self.assertIn("PythonExe = $PythonExe", a_short)
        self.assertIn("PYTHONIOENCODING", a_short)
        self.assertIn("PYTHONUTF8", a_short)
        self.assertIn("[Console]::OutputEncoding", a_short)
        self.assertIn("if (-not [string]::IsNullOrWhiteSpace($AsOf))", a_short)
        self.assertIn("$WorkerParams.AsOf = $AsOf", a_short)
        self.assertIn("if (-not [string]::IsNullOrWhiteSpace($Account))", a_short)
        self.assertIn("$WorkerParams.Account = Join-Path $Capsule 'private_inputs\\a_short_account'", a_short)
        self.assertIn("& $Worker @WorkerParams", a_short)
        self.assertIn("[switch]$ConfirmRuntest", us_short)
        self.assertIn("'runners\\us_short_weekly_capstone.ps1'", us_short)
        self.assertIn("Runtest does not forward -ExtraArgs", us_short)
        self.assertIn("if ($ExtraArgs.Count -gt 0)", us_short)
        self.assertNotIn("$WorkerArgs += '-ExtraArgs'", us_short)
        self.assertNotIn("$WorkerArgs", us_short)
        self.assertIn("$WorkerParams = @{", us_short)
        self.assertIn("PrivateRoot = $PrivateRoot", us_short)
        self.assertIn("PythonExe = $PythonExe", us_short)
        self.assertNotIn("[switch]$PrepareBudget", us_short)
        self.assertNotIn("[int]$Pass2Budget", us_short)
        self.assertIn("& $Worker @WorkerParams", us_short)
        self.assertIn("[string]$CachePolicy = 'enabled'", weekly)
        self.assertIn("'--cache-policy', $CachePolicy", weekly)
        self.assertIn("PYTHONIOENCODING", weekly)
        self.assertIn("PYTHONUTF8", weekly)
        self.assertIn("[Console]::OutputEncoding", weekly)

    def test_file_mode_launchers_reach_confirmation_gate_without_source_root(self) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("Windows PowerShell executable not available")

        for market in ("a_short", "us_short"):
            with self.subTest(market=market):
                script = ROOT / "runners" / f"{market}_runtest.ps1"
                capsule_root = self.base / f"{market}_file_mode_capsule"
                result = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(script),
                        "-CapsuleRoot",
                        str(capsule_root),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    errors="replace",
                )
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn("Runtest is intentionally explicit", output)
                self.assertNotIn("Split-Path", output)
                self.assertFalse(capsule_root.exists())

    def test_us_weekly_launcher_auto_derives_budget_and_rejects_manual_budget_flags(self) -> None:
        weekly_capstone = (ROOT / "runners" / "us_short_weekly_capstone.ps1").read_text(encoding="utf-8")
        self.assertIn('@("--live", "--confirm-user-authorization", "--auto-pass2-budget")', weekly_capstone)
        self.assertIn("if ($ExtraArgs.Count -gt 0)", weekly_capstone)
        self.assertIn("Weekly capstone does not forward -ExtraArgs", weekly_capstone)
        self.assertNotIn("$cliArgs += $ExtraArgs", weekly_capstone)

    def test_us_weekly_launcher_rejects_raw_clock_override(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell executable not available")
        script = ROOT / "runners" / "us_short_weekly_capstone.ps1"
        escaped_script = str(script).replace("'", "''")
        command = (
            f"& '{escaped_script}' -Live "
            "-ExtraArgs @('--now-et','2026-01-01T08:00:00')"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT,
            text=True,
            capture_output=True,
            errors="replace",
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Weekly capstone does not forward -ExtraArgs", result.stdout + result.stderr)

    def test_us_launcher_rejects_raw_private_root_override_before_creating_capsule(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell executable not available")
        script = ROOT / "runners" / "us_short_runtest.ps1"
        escaped_script = str(script).replace("'", "''")
        attempted_root = self.base / "outside_private_root"
        command = (
            f"& '{escaped_script}' -ConfirmRuntest "
            f"-ExtraArgs @('--private-root','{attempted_root}')"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT,
            text=True,
            capture_output=True,
            errors="replace",
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Runtest does not forward -ExtraArgs", result.stdout + result.stderr)
        self.assertFalse(attempted_root.exists())
        self.assertFalse(self.root.exists())

    def test_us_launcher_binds_all_worker_parameters_by_name(self) -> None:
        """The wrapper must splat named parameters, never a positional token array."""
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell executable not available")

        source_root = self.base / "worker_binding_source"
        runners = source_root / "runners"
        runners.mkdir(parents=True)
        (runners / "runtest_capsule.py").write_text(
            """import json
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
command = args[args.index(\"create\")] if \"create\" in args else args[args.index(\"activate\")] if \"activate\" in args else args[args.index(\"finish\")]

def value(name):
    return args[args.index(name) + 1]

if command == \"create\":
    capsule = Path(value(\"--capsule-root\")) / \"us_short\" / value(\"--run-id\")
    repo = capsule / \"repo\"
    (repo / \"runners\").mkdir(parents=True)
    shutil.copy2(Path(value(\"--source-root\")) / \"runners\" / \"us_short_weekly_capstone.ps1\", repo / \"runners\" / \"us_short_weekly_capstone.ps1\")
    print(json.dumps({\"capsule\": str(capsule), \"repo\": str(repo)}))
""",
            encoding="utf-8",
        )
        (runners / "us_short_weekly_capstone.ps1").write_text(
            """param(
    [string]$NowEt = '',
    [string]$PrivateRoot = '',
    [string]$BatchTemplate = '',
    [string]$AccountState = '',
    [switch]$Live,
    [int]$MomentumTopK = 0,
    [string]$PythonExe = ''
)

[ordered]@{
    now_et = $NowEt
    private_root = $PrivateRoot
    batch_template = $BatchTemplate
    account_state = $AccountState
    live = [bool]$Live
    momentum_top_k = $MomentumTopK
    python_exe = $PythonExe
} | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:RUNTEST_TEST_CAPTURE_PATH -Encoding utf8
""",
            encoding="utf-8",
        )
        batch_template = self.base / "batch_template.json"
        account_state = self.base / "account_state.json"
        batch_template.write_text("{}\n", encoding="utf-8")
        account_state.write_text("{}\n", encoding="utf-8")

        script = ROOT / "runners" / "us_short_runtest.ps1"
        escaped = lambda path: str(path).replace("'", "''")
        cases = (
            ("dry_run", (), {"live": False, "momentum_top_k": 0}),
            (
                "live",
                ("-BatchTemplate", batch_template, "-AccountState", account_state, "-Live", "-MomentumTopK", "200"),
                {"live": True, "momentum_top_k": 200},
            ),
        )
        for name, extra_args, expected in cases:
            with self.subTest(name=name):
                capsule_root = self.base / f"capsules_{name}"
                capture = self.base / f"worker_capture_{name}.json"
                command_parts = [
                    f"& '{escaped(script)}'",
                    "-ConfirmRuntest",
                    f"-SourceRoot '{escaped(source_root)}'",
                    f"-CapsuleRoot '{escaped(capsule_root)}'",
                    f"-RunId 'worker-binding-{name}'",
                ]
                if name != "live":
                    command_parts.append("-NowEt '2026-07-21T08:00:00'")
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
                capsule = capsule_root / "us_short" / f"worker-binding-{name}"
                if name == "dry_run":
                    self.assertEqual(captured["now_et"], "2026-07-21T08:00:00")
                else:
                    self.assertEqual(captured["now_et"], "")
                self.assertEqual(captured["private_root"], str(capsule / "private" / "us_short"))
                self.assertEqual(captured["python_exe"].casefold(), PINNED_STOCK_PYTHON.casefold())
                self.assertEqual(captured["batch_template"], str(capsule / "private_inputs" / "us_batch_template") if expected["live"] else "")
                self.assertEqual(captured["account_state"], str(capsule / "private_inputs" / "us_account_state") if expected["live"] else "")
                for key, value in expected.items():
                    self.assertEqual(captured[key], value)

    def test_live_explicit_clock_override_rejects_before_capsule_creation(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell executable not available")
        script = ROOT / "runners" / "us_short_runtest.ps1"
        capsule_root = self.base / "problem7_capsule_rejected"
        escaped = str(script).replace("'", "''")
        command = (
            f"& '{escaped}' -ConfirmRuntest -CapsuleRoot '{str(capsule_root).replace(chr(39), chr(39) + chr(39))}' "
            "-Live -NowEt '2026-07-21T08:00:00'"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT,
            text=True,
            capture_output=True,
            errors="replace",
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("actual current ET clock", result.stdout + result.stderr)
        self.assertFalse(capsule_root.exists())
