from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from runners import us_short_paper_one_click as one_click
from runners.us_short_paper_one_click import (
    DEFAULT_STATE_DIR,
    PaperOneClickError,
    _canonical_source_state_dir,
    _prepare_paper_inputs,
    run_one_click,
)


class USShortPaperOneClickTest(unittest.TestCase):
    def test_prepares_only_a_pending_adapter_slot_without_reinitializing_capital(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            template_path, account_path = _prepare_paper_inputs(
                private_root=Path(td), decision_date="20260720"
            )
            account = json.loads(account_path.read_text(encoding="utf-8"))
            self.assertEqual({"pending_model_paper_adapter": True, "decision_date": "20260720"}, account)
            persisted = {"already": "an adapter from an earlier week"}
            account_path.write_text(json.dumps(persisted), encoding="utf-8")
            _template_again, account_again = _prepare_paper_inputs(private_root=Path(td), decision_date="20260727")
            self.assertEqual(account_path, account_again)
            self.assertEqual(persisted, json.loads(account_again.read_text(encoding="utf-8")))
            self.assertTrue(template_path.is_file())
            self.assertIn("basket_context", json.loads(template_path.read_text(encoding="utf-8")))

    def test_invalid_launcher_option_fails_before_any_provider_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(PaperOneClickError, "provider-pace-seconds"):
                run_one_click(
                    now_et=datetime(2026, 7, 20, 1, 0, 0),
                    private_root=Path(td),
                    state_dir=Path(td) / "state",
                    provider_pace_seconds=-1.0,
                )

    def test_rejects_private_root_as_shared_source_state_before_provider_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(PaperOneClickError, "canonical state/us_short"):
                _canonical_source_state_dir(Path(td) / "private" / "us_short")

    def test_accepts_the_active_checkout_canonical_source_state(self) -> None:
        self.assertEqual(DEFAULT_STATE_DIR.resolve(), _canonical_source_state_dir(DEFAULT_STATE_DIR))

    @mock.patch("runners.us_short_paper_one_click.run_weekly_capstone", return_value={})
    @mock.patch(
        "runners.us_short_paper_one_click.resolve_capstone_context",
        return_value=SimpleNamespace(decision_date="20260723", price_basis_date="20260722"),
    )
    def test_private_root_never_repoints_shared_source_state(self, _context, run_capstone) -> None:
        with tempfile.TemporaryDirectory() as td:
            private_root = Path(td)
            run_one_click(now_et=datetime(2026, 7, 23, 8, 0, 0), private_root=private_root)

        kwargs = run_capstone.call_args.kwargs
        self.assertEqual(private_root.resolve(), kwargs["private_root"])
        self.assertEqual(DEFAULT_STATE_DIR.resolve(), kwargs["state_dir"])

    @mock.patch(
        "runners.us_short_paper_one_click.resolve_capstone_context",
        return_value=SimpleNamespace(decision_date="20260723", price_basis_date="20260722"),
    )
    @mock.patch("runners.us_short_paper_one_click.run_weekly_capstone")
    def test_unexpected_failure_writes_redacted_private_diagnostics(self, run_capstone, _context) -> None:
        secret = "LEAK_DIAGNOSTICS_SENTINEL"
        run_capstone.side_effect = RuntimeError(f"provider process stopped: {secret}")
        old = os.environ.get("US_SHORT_DIAGNOSTICS_TEST_TOKEN")
        os.environ["US_SHORT_DIAGNOSTICS_TEST_TOKEN"] = secret
        try:
            with tempfile.TemporaryDirectory() as td:
                private_root = Path(td) / "private"
                rc = one_click.main([
                    "--now-et", "2026-07-23T08:00:00",
                    "--private-root", str(private_root),
                ])
                diagnostics_root = private_root / "weekly_private" / "_run_diagnostics"
                sessions = list(diagnostics_root.iterdir())
                self.assertEqual(rc, 1)
                self.assertEqual(len(sessions), 1)
                session = sessions[0]
                failure = json.loads((session / "failure.json").read_text(encoding="utf-8"))
                heartbeat = json.loads((session / "heartbeat.json").read_text(encoding="utf-8"))
                events = [json.loads(line) for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(failure["error_type"], "RuntimeError")
                self.assertNotIn(secret, json.dumps(failure, ensure_ascii=False))
                self.assertNotIn(secret, (session / "stderr.log").read_text(encoding="utf-8"))
                self.assertTrue((session / "stdout.log").is_file())
                self.assertEqual(events[-1]["event"], "runner_failed")
                self.assertEqual(heartbeat["event"], "runner_failed")
                self.assertIn("capstone_started", [event["event"] for event in events])
        finally:
            if old is None:
                os.environ.pop("US_SHORT_DIAGNOSTICS_TEST_TOKEN", None)
            else:
                os.environ["US_SHORT_DIAGNOSTICS_TEST_TOKEN"] = old

    def test_cmd_entrypoint_handles_execution_policy_in_process(self) -> None:
        text = (Path(__file__).parents[1] / "runners" / "us_short_paper_one_click.cmd").read_text(
            encoding="utf-8"
        )
        self.assertIn("-ExecutionPolicy Bypass", text)

    @unittest.skipUnless(os.name == "nt", "PowerShell native-stderr behavior is a Windows contract")
    def test_powershell_launcher_routes_stderr_without_changing_python_exit_code(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell executable not available")
        source = Path(__file__).parents[1] / "runners" / "us_short_paper_one_click.ps1"
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            runners = repo / "runners"
            tools = repo / ".tools"
            runners.mkdir(parents=True)
            tools.mkdir()
            (runners / "us_short_paper_one_click.ps1").write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8"
            )
            python_path = str(Path(sys.executable)).replace("'", "''")
            (tools / "Resolve-AshortPython.ps1").write_text(
                "function Resolve-AshortPython { param([string]$Requested); return '"
                + python_path
                + "' }\n",
                encoding="utf-8",
            )
            for expected_exit in (0, 17):
                with self.subTest(expected_exit=expected_exit):
                    (runners / "us_short_paper_one_click.py").write_text(
                        "import sys\n"
                        "expected = ['--now-et', '2026-07-23T08:00:00', '--momentum-top-k', '200', "
                        "'--provider-pace-seconds', '1']\n"
                        "if sys.argv[1:] != expected: raise SystemExit(91)\n"
                        "print('normal stdout summary')\n"
                        "print('normal stderr status', file=sys.stderr)\n"
                        f"raise SystemExit({expected_exit})\n",
                        encoding="utf-8",
                    )
                    result = subprocess.run(
                        [
                            powershell,
                            "-NoProfile",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-File",
                            str(runners / "us_short_paper_one_click.ps1"),
                            "-NowEt",
                            "2026-07-23T08:00:00",
                        ],
                        cwd=repo,
                        text=True,
                        capture_output=True,
                        errors="replace",
                    )

                    combined = result.stdout + result.stderr
                    self.assertEqual(result.returncode, expected_exit, combined)
                    self.assertIn("normal stdout summary", combined)
                    self.assertIn("normal stderr status", combined)
                    self.assertNotIn("RemoteException", combined)
                    self.assertNotIn("NativeCommandError", combined)


if __name__ == "__main__":
    unittest.main()
