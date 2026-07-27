from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfoNotFoundError

from runners import a_short_preflight
from runners import backtest_rank
from runners import materialize_execution_price_data_tushare as execution_materializer

ROOT = Path(__file__).resolve().parents[1]
PINNED_STOCK_PYTHON = r"C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe"


class PinnedStockPythonSmoke(unittest.TestCase):
    """Nested by the .cmd launcher to prove its selected interpreter."""

    def test_interpreter_is_the_pinned_stock_python(self) -> None:
        if os.name != "nt":
            self.skipTest("The strict Stock Python pin is a Windows checkout contract.")
        self.assertEqual(
            str(Path(sys.executable).resolve()).casefold(),
            str(Path(PINNED_STOCK_PYTHON).resolve()).casefold(),
        )


class AShortPreflightTests(unittest.TestCase):
    def _powershell(self) -> Path:
        if os.name != "nt":
            self.skipTest("The strict Stock Python pin is a Windows checkout contract.")
        system_root = Path(os.environ["SystemRoot"])
        executable = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        self.assertTrue(executable.is_file(), f"Missing Windows PowerShell: {executable}")
        return executable

    def _run_powershell(self, command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self._powershell()), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_preflight_lists_every_missing_dependency_in_one_result(self) -> None:
        present = {"jsonschema", "numpy"}
        result = a_short_preflight.build_result(
            find_spec=lambda name: object() if name in present else None,
            timezone_loader=lambda _name: object(),
        )
        self.assertEqual(result["status"], "fail")
        self.assertEqual(
            [item["module"] for item in result["missing"]],
            ["akshare", "openpyxl", "pandas", "requests", "tqdm", "tushare", "tzdata"],
        )
        self.assertEqual(result["dependencies"]["status"], "fail")
        self.assertEqual(result["timezone_capability"]["status"], "pass")

    def test_preflight_fails_when_tzdata_is_missing(self) -> None:
        result = a_short_preflight.build_result(
            find_spec=lambda name: None if name == "tzdata" else object(),
            timezone_loader=lambda _name: object(),
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["dependencies"]["status"], "fail")
        self.assertEqual(result["dependencies"]["missing"], [
            {"module": "tzdata", "package": "tzdata"},
        ])
        self.assertEqual(result["timezone_capability"]["status"], "pass")

    def test_preflight_fails_when_asia_shanghai_zoneinfo_is_unavailable(self) -> None:
        def unavailable(_name: str) -> object:
            raise ZoneInfoNotFoundError("timezone database unavailable")

        result = a_short_preflight.build_result(
            find_spec=lambda _name: object(),
            timezone_loader=unavailable,
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["dependencies"]["status"], "pass")
        self.assertEqual(result["timezone_capability"], {
            "timezone": "Asia/Shanghai",
            "status": "fail",
            "error_type": "ZoneInfoNotFoundError",
        })

    def test_preflight_records_normal_timezone_capability(self) -> None:
        result = a_short_preflight.build_result(
            find_spec=lambda _name: object(),
            timezone_loader=lambda name: object() if name == "Asia/Shanghai" else None,
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["dependencies"]["status"], "pass")
        self.assertEqual(result["timezone_capability"], {
            "timezone": "Asia/Shanghai",
            "status": "pass",
        })

    def test_a_short_provider_initializers_pass_token_without_set_token(self) -> None:
        class _FakeDataApi:
            pass
        setattr(_FakeDataApi, "_DataApi__http_url", "old")
        fake_tushare = types.SimpleNamespace(
            __version__="1.4.29",
            pro=types.SimpleNamespace(client=types.SimpleNamespace(DataApi=_FakeDataApi)),
            pro_api=mock.Mock(),
        )
        fake_tushare.pro_api.return_value = object()
        with mock.patch.dict(sys.modules, {"tushare": fake_tushare}), mock.patch.dict(
            os.environ, {"TUSHARE_TOKEN": "masked-test-token"}
        ):
            backtest_rank._tushare_pro()
            execution_materializer.tushare_pro()
        self.assertEqual(fake_tushare.pro_api.call_args_list, [
            mock.call("masked-test-token"),
            mock.call("masked-test-token"),
        ])

    def test_no_a_short_python_callsite_invokes_set_token(self) -> None:
        paths = [ROOT / "A-EGS" / "egs_main.py", ROOT / "runners" / "backtest_rank.py"]
        paths.extend(sorted((ROOT / "runners").glob("a_short_*.py")))
        paths.append(ROOT / "runners" / "materialize_execution_price_data_tushare.py")
        offenders: list[str] = []
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "set_token"
                for node in ast.walk(tree)
            ):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_tracked_python_resolver_does_not_pin_agent_private_runtime(self) -> None:
        text = (ROOT / ".tools" / "Resolve-AshortPython.ps1").read_text(encoding="utf-8")
        self.assertNotIn("codex-runtimes", text.lower())
        self.assertNotIn("claude", text.lower())

    def test_tracked_python_resolver_is_strictly_pinned(self) -> None:
        text = (ROOT / ".tools" / "Resolve-AshortPython.ps1").read_text(encoding="utf-8")
        self.assertIn("$PinnedPython", text)
        self.assertIn("must equal the pinned Stock Python", text)
        self.assertNotIn("Get-Command", text)
        self.assertNotIn("Get-ChildItem", text)

    def test_resolver_rejects_every_legacy_interpreter_override_at_runtime(self) -> None:
        resolver = str(ROOT / ".tools" / "Resolve-AshortPython.ps1").replace("'", "''")
        pin = PINNED_STOCK_PYTHON.replace("'", "''")
        non_pinned = str(self._powershell())
        self.assertNotEqual(non_pinned.casefold(), PINNED_STOCK_PYTHON.casefold())
        escaped_non_pinned = non_pinned.replace("'", "''")
        default = self._run_powershell(
            f". '{resolver}'; $actual = Resolve-AshortPython; "
            f"if ([string]::Equals($actual, '{pin}', [StringComparison]::OrdinalIgnoreCase)) {{ exit 0 }}; exit 11"
        )
        self.assertEqual(default.returncode, 0, default.stdout)
        attacks = (
            f"Resolve-AshortPython -Requested '{escaped_non_pinned}' | Out-Null",
            f"$env:STOCK_PYTHON = '{escaped_non_pinned}'; Resolve-AshortPython | Out-Null",
            f"$env:STOCK_TEST_PYTHON = '{escaped_non_pinned}'; Resolve-AshortPython | Out-Null",
        )
        for attack in attacks:
            result = self._run_powershell(
                f". '{resolver}'; try {{ {attack}; exit 12 }} catch {{ exit 0 }}"
            )
            self.assertEqual(result.returncode, 0, f"override was accepted: {attack}\n{result.stdout}")

    def test_test_launcher_ignores_poisoned_legacy_interpreter_environment(self) -> None:
        if os.name != "nt":
            self.skipTest("The strict Stock Python pin is a Windows checkout contract.")
        cmd = Path(os.environ["ComSpec"])
        launcher = ROOT / ".tools" / "run_unittest_with_repo_pythonpath.cmd"
        non_pinned = str(self._powershell())
        environment = os.environ.copy()
        environment.update({
            "STOCK_PYTHON": non_pinned,
            "STOCK_TEST_PYTHON": non_pinned,
            "PYTHON_EXE": non_pinned,
            "PATH": r"C:\not-a-python-path",
            "PYTHONPATH": r"C:\not-a-python-path",
        })
        result = subprocess.run(
            [str(cmd), "/d", "/c", "call", str(launcher),
             "tests.test_a_short_preflight.PinnedStockPythonSmoke"],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_test_launcher_uses_pinned_python_under_path_pollution(self) -> None:
        if os.name != "nt":
            self.skipTest("The strict Stock Python pin is a Windows checkout contract.")
        cmd = Path(os.environ["ComSpec"])
        launcher = ROOT / ".tools" / "run_unittest_with_repo_pythonpath.cmd"
        environment = os.environ.copy()
        for name in ("STOCK_PYTHON", "STOCK_TEST_PYTHON", "PYTHON_EXE"):
            environment.pop(name, None)
        environment.update({
            "PATH": r"C:\not-a-python-path",
            "PYTHONPATH": r"C:\not-a-python-path",
        })
        result = subprocess.run(
            [str(cmd), "/d", "/c", "call", str(launcher),
             "tests.test_a_short_preflight.PinnedStockPythonSmoke"],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_all_resolver_entrypoints_bind_once_without_reassignment(self) -> None:
        entrypoints = (
            ROOT / "runners" / "a_short_offline_check.ps1",
            ROOT / "runners" / "a_short_runtest.ps1",
            ROOT / "runners" / "weekly_screening.ps1",
            ROOT / "runners" / "us_short_paper_one_click.ps1",
            ROOT / "runners" / "us_short_weekly_capstone.ps1",
            ROOT / "runners" / "us_short_runtest.ps1",
        )
        binding = re.compile(
            r"(?m)^\s*\$PythonExe\s*=\s*Resolve-AshortPython\s+-Requested\s+\$PythonExe\s*$"
        )
        reassignment = re.compile(r"(?m)^\s*\$PythonExe\s*=")
        for path in entrypoints:
            source = path.read_text(encoding="utf-8-sig")
            match = binding.search(source)
            self.assertIsNotNone(match, f"resolver binding missing: {path.relative_to(ROOT)}")
            assert match is not None
            self.assertIsNone(
                reassignment.search(source, match.end()),
                f"resolver output is reassigned later: {path.relative_to(ROOT)}",
            )

    def test_codex_entry_and_offline_check_fail_closed_on_missing_exit_code(self) -> None:
        entry = (ROOT / ".tools" / "codex_main_python.ps1").read_text(encoding="utf-8")
        offline_path = ROOT / "runners" / "a_short_offline_check.ps1"
        offline = offline_path.read_text(encoding="utf-8")
        self.assertIn("$ErrorActionPreference = 'Stop'", entry)
        self.assertIn("if ($null -eq $PythonExit)", entry)
        self.assertNotIn("$env:STOCK_TEST_PYTHON", offline)
        self.assertGreaterEqual(offline.count("$null -eq $LASTEXITCODE"), 2)

        source_line = ". (Join-Path $ProjectRoot '.tools\\Resolve-AshortPython.ps1')"
        altered = offline.replace(
            source_line,
            "function Resolve-AshortPython { param([string]$Requested); return 'C:\\not-the-pinned-python.exe' }",
        )
        self.assertNotEqual(altered, offline, "test setup failed to replace the resolver import")
        with tempfile.TemporaryDirectory() as temporary_directory:
            altered_offline = Path(temporary_directory) / "a_short_offline_check_missing_binary.ps1"
            altered_offline.write_text(altered, encoding="utf-8")
            missing = subprocess.run(
                [str(self._powershell()), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(altered_offline)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertNotEqual(missing.returncode, 0, missing.stdout)

    def test_codex_main_python_entry_propagates_failure_and_missing_binary_fails_closed(self) -> None:
        entry = ROOT / ".tools" / "codex_main_python.ps1"
        failure = subprocess.run(
            [str(self._powershell()), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(entry),
             "-c", "raise SystemExit(37)"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(failure.returncode, 37, failure.stdout)

        source = entry.read_text(encoding="utf-8")
        replacement = r"$MainPython = 'C:\\not-the-pinned-python.exe'"
        altered = source.replace(f"$MainPython = '{PINNED_STOCK_PYTHON}'", replacement)
        self.assertNotEqual(altered, source, "test setup failed to replace the pinned interpreter")
        with tempfile.TemporaryDirectory() as temporary_directory:
            altered_entry = Path(temporary_directory) / "codex_main_python_missing_binary.ps1"
            altered_entry.write_text(altered, encoding="utf-8")
            missing = subprocess.run(
                [str(self._powershell()), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(altered_entry),
                 "-c", "print('must-not-run')"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertNotEqual(missing.returncode, 0, missing.stdout)

    def test_pre_commit_ignores_a_path_python_and_uses_the_pinned_host(self) -> None:
        if os.name != "nt":
            self.skipTest("The strict Stock Python pin is a Windows checkout contract.")
        git_sh = Path(os.environ["ProgramFiles"]) / "Git" / "bin" / "sh.exe"
        self.assertTrue(git_sh.is_file(), f"Missing Git shell: {git_sh}")
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_python = Path(temporary_directory) / "python"
            fake_python.write_text("#!/bin/sh\nexit 86\n", encoding="utf-8")
            fake_python.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = os.pathsep.join((
                temporary_directory,
                str(Path(os.environ["ProgramFiles"]) / "Git" / "cmd"),
                str(Path(os.environ["ProgramFiles"]) / "Git" / "bin"),
            ))
            result = subprocess.run(
                [str(git_sh), ".githooks/pre-commit"],
                cwd=ROOT,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("exit 86", result.stdout)

    def test_active_codex_commands_do_not_advertise_bare_python(self) -> None:
        active_commands = {
            ROOT / "AGENTS.md": "python .tools/full_pack_ledger.py",
            ROOT / "docs" / "CURRENT.md": "\npython ",
            ROOT / "docs" / "README.md": "`python runners/us_short_weekend_batch4.py",
            ROOT / ".tools" / "full_pack_ledger.py": "\n   python .tools/full_pack_ledger.py",
            ROOT / ".githooks" / "pre-commit": 'echo "  python .tools/full_pack_ledger.py',
        }
        for path, stale_command in active_commands.items():
            self.assertNotIn(stale_command, path.read_text(encoding="utf-8"), path)

    def test_precommit_reminder_points_at_the_atomic_ledger_run(self) -> None:
        # The reminder is the only place an executor meets rule 3/4 at commit time;
        # it must not hand out a subcommand the ledger now refuses.
        hook = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
        for retired in ("full_pack_ledger.py record", "full_pack_ledger.py prepare"):
            self.assertNotIn(retired, hook)
        self.assertIn("full_pack_ledger.py run a_short", hook)


if __name__ == "__main__":
    unittest.main()
