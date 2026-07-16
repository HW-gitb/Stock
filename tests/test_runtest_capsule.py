import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "runners" / "runtest_capsule.py"


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
        self.assertIn("'-CachePolicy', 'disabled'", a_short)
        self.assertIn("'TEMP', 'TMP', 'XDG_CACHE_HOME', 'PYTHONPYCACHEPREFIX'", a_short)
        self.assertIn("[switch]$ConfirmRuntest", us_short)
        self.assertIn("'runners\\us_short_weekly_capstone.ps1'", us_short)
        self.assertIn("Runtest does not forward -ExtraArgs", us_short)
        self.assertIn("if ($ExtraArgs.Count -gt 0)", us_short)
        self.assertNotIn("$WorkerArgs += '-ExtraArgs'", us_short)
        self.assertIn("'-PrivateRoot', $PrivateRoot", us_short)
        self.assertIn("[string]$CachePolicy = 'enabled'", weekly)
        self.assertIn("'--cache-policy', $CachePolicy", weekly)

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
