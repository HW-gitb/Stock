from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path
from runners import us_short_paper_one_click as one_click
from runners.us_short_paper_one_click import (
    DEFAULT_STATE_DIR,
    PaperOneClickError,
    _canonical_source_state_dir,
    _prepare_paper_inputs,
    run_one_click,
)
from runners.us_short_weekly_capstone import _decision_lock_path, resolve_capstone_context


def _production_state_dir_literal_children() -> list[tuple[Path, str]]:
    """Enumerate production ``ctx.state_dir / "child"`` paths without a runtime registry."""
    children: list[tuple[Path, str]] = []
    for source_root in (one_click.ROOT / "runners", one_click.ROOT / "engine"):
        for source_path in sorted(source_root.glob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.BinOp)
                    and isinstance(node.op, ast.Div)
                    and isinstance(node.left, ast.Attribute)
                    and isinstance(node.left.value, ast.Name)
                    and node.left.value.id == "ctx"
                    and node.left.attr == "state_dir"
                    and isinstance(node.right, ast.Constant)
                    and type(node.right.value) is str
                ):
                    continue
                children.append((source_path, node.right.value))
    return sorted(set(children), key=lambda item: (str(item[0]), item[1]))


def _assert_state_dir_literal_children_are_gitignored(
    children: list[tuple[Path, str]],
) -> None:
    for source_path, child in children:
        probe = one_click.ROOT / "state" / "us_short" / child / "private_probe.json"
        result = subprocess.run(
            ["git", "check-ignore", "-v", "--no-index", "--", str(probe)],
            cwd=str(one_click.ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        source = result.stdout.strip().split("\t", 1)[0].split(":", 2)[0].replace("\\", "/").lower()
        if result.returncode != 0 or not (source == ".gitignore" or source.endswith("/.gitignore")):
            raise AssertionError(
                f"{source_path}:{child} is not covered by tracked .gitignore: "
                f"rc={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}"
            )


class USShortPaperOneClickTest(unittest.TestCase):
    def setUp(self):
        self._actual_clock = mock.patch(
            "engine.us_short_live_provider_preflight._now_et_wall_clock",
            return_value=datetime(2026, 7, 23, 8, 0, 0),
        )
        self._actual_clock.start()
        self.addCleanup(self._actual_clock.stop)

    def test_no_receipt_is_typed_dormant_stop_before_context_inputs_provider_or_store(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            private_root = root / "private"
            activation_root = private_root / "market_diagnostic_private"
            with (
                mock.patch(
                    "engine.us_short_model_paper_activation.MODEL_PAPER_ACTIVATION_ROOT",
                    activation_root,
                ),
                mock.patch.object(one_click, "resolve_capstone_context", side_effect=AssertionError("context reached")),
                mock.patch.object(one_click, "_prepare_paper_inputs", side_effect=AssertionError("inputs reached")),
                mock.patch.object(one_click, "run_weekly_capstone", side_effect=AssertionError("capstone reached")),
            ):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    result = run_one_click(
                        now_et=datetime(2026, 7, 20, 8, 0, 0),
                        private_root=private_root,
                        state_dir=DEFAULT_STATE_DIR,
                        provider_pace_seconds=0.0,
                    )
            self.assertEqual(result["activation_status"], "dormant")
            self.assertFalse(result["model_paper_started"])
            self.assertIn("[US-SHORT PAPER] DORMANT", stderr.getvalue())
            self.assertFalse((private_root / "weekly_private" / "_run_inputs").exists())
            self.assertFalse((private_root / "model_paper_private").exists())

    def test_broken_activation_is_not_downgraded_to_dormant(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(
                one_click,
                "resolve_model_paper_activation",
                side_effect=ValueError("C:\\private\\diagnostic_start_receipt.json"),
            ), mock.patch.object(one_click, "resolve_capstone_context") as resolve_context:
                with self.assertRaises(PaperOneClickError) as raised:
                    run_one_click(
                        now_et=datetime(2026, 7, 20, 8, 0, 0),
                        private_root=Path(td) / "private",
                        state_dir=DEFAULT_STATE_DIR,
                        provider_pace_seconds=0.0,
                    )
                self.assertIn("activation_gate_broken", str(raised.exception))
                self.assertNotIn("diagnostic_start_receipt.json", str(raised.exception))
                resolve_context.assert_not_called()

    def test_broken_activation_does_not_write_private_path_to_failure_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            private_root = Path(td) / "private"
            with mock.patch.object(
                one_click,
                "resolve_model_paper_activation",
                side_effect=ValueError(str(private_root / "diagnostic_start_receipt.json")),
            ):
                rc = one_click.main([
                    "--now-et", "2026-07-20T08:00:00",
                    "--private-root", str(private_root),
                ])
            self.assertEqual(rc, 2)
            sessions = list((private_root / "weekly_private" / "_run_diagnostics").iterdir())
            self.assertEqual(len(sessions), 1)
            failure = (sessions[0] / "failure.json").read_text(encoding="utf-8")
            self.assertNotIn("diagnostic_start_receipt.json", failure)

    @mock.patch(
        "runners.us_short_paper_one_click.resolve_model_paper_activation",
        return_value={"status": "authorized", "receipt": {}},
    )
    @mock.patch(
        "runners.us_short_paper_one_click.resolve_capstone_context",
        return_value=SimpleNamespace(decision_date="20260723", price_basis_date="20260722"),
    )
    @mock.patch(
        "runners.us_short_paper_one_click.run_weekly_capstone",
        return_value={
            "mode": "live",
            "execution_mode": "injected_pipeline",
            "report_mode": "offline_test",
            "operational_use": "not_authorized",
            "decision_date": "20260723",
            "price_basis_date": "20260722",
            "emitted": True,
            "stages": [],
            "stage_outcomes": [
                {
                    "stage": "soft_discovery",
                    "execution_mode": "executed",
                    "outcome_class": "no_work_expected",
                    "reason_code": "SOFT_DISCOVERY_DISABLED",
                },
                {
                    "stage": "serenity_quality_forward",
                    "execution_mode": "reused",
                    "outcome_class": "waiting_dependency",
                    "reason_code": "SERENITY_REVIEW_PENDING",
                },
                {
                    "stage": "weekly_bridge",
                    "execution_mode": "refreshed_equivalent",
                    "outcome_class": "completed_work",
                    "reason_code": "STAGE_COMPLETED",
                },
            ],
            "stage_outcome_counts": {
                "completed_work": 1,
                "no_work_expected": 1,
                "waiting_dependency": 1,
                "failed_nonblocking": 0,
            },
        },
    )
    def test_main_prints_stage_outcome_counts_and_rows_from_same_stdout_summary(
        self, _run_capstone, _context, _activation,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = one_click.main([
                    "--now-et", "2026-07-23T08:00:00",
                    "--private-root", str(Path(td) / "private"),
                ])
            self.assertEqual(rc, 0, stderr.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["stage_outcome_counts"], {
                "completed_work": 1,
                "no_work_expected": 1,
                "waiting_dependency": 1,
                "failed_nonblocking": 0,
            })
            rendered = stderr.getvalue()
            self.assertIn("completed_work=1 no_work_expected=1 waiting_dependency=1 failed_nonblocking=0", rendered)
            self.assertIn("stage=soft_discovery outcome=no_work_expected reason=SOFT_DISCOVERY_DISABLED", rendered)
            self.assertIn("stage=serenity_quality_forward outcome=waiting_dependency reason=SERENITY_REVIEW_PENDING", rendered)
            self.assertNotIn("all success", rendered.lower())

            diagnostics_root = Path(td) / "private" / "weekly_private" / "_run_diagnostics"
            session = next(diagnostics_root.iterdir())
            events = [json.loads(line) for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            capstone_completed = [event for event in events if event["event"] == "capstone_completed"]
            runner_completed = [event for event in events if event["event"] == "runner_completed"]
            self.assertEqual(len(capstone_completed), 1)
            self.assertNotIn("stage_outcome_counts", capstone_completed[0])
            self.assertEqual(len(runner_completed), 1)
            self.assertEqual(runner_completed[0]["stage_outcome_counts"], payload["stage_outcome_counts"])

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
            with mock.patch.object(
                one_click,
                "resolve_model_paper_activation",
                return_value={"status": "authorized", "receipt": {}},
            ), self.assertRaisesRegex(PaperOneClickError, "provider_pace_seconds"):
                run_one_click(
                    now_et=datetime(2026, 7, 20, 1, 0, 0),
                    private_root=Path(td),
                    state_dir=DEFAULT_STATE_DIR,
                    provider_pace_seconds=-1.0,
                )

    def test_rejects_private_root_as_shared_source_state_before_provider_stage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(PaperOneClickError, "canonical state/us_short"):
                _canonical_source_state_dir(Path(td) / "private" / "us_short")

    def test_accepts_the_active_checkout_canonical_source_state(self) -> None:
        self.assertEqual(DEFAULT_STATE_DIR.resolve(), _canonical_source_state_dir(DEFAULT_STATE_DIR))

    def test_canonical_decision_lock_is_ignored_by_tracked_gitignore(self) -> None:
        ctx = resolve_capstone_context(
            now_et=datetime(2026, 7, 23, 8, 0, 0),
            private_root=Path(tempfile.gettempdir()) / "us_short_problem1_private",
            batch4_template_path=Path("template.json"),
            account_state_path=Path("account.json"),
            state_dir=DEFAULT_STATE_DIR,
        )
        lock_path = _decision_lock_path(ctx)
        self.assertEqual(lock_path.parent, (DEFAULT_STATE_DIR / "_transaction_locks").resolve())

        # This is the exact consumer used immediately before the production lock is created.
        reject_nonprivate_output_path(lock_path)

        result = subprocess.run(
            ["git", "check-ignore", "-v", "--no-index", "--", str(lock_path)],
            cwd=str(one_click.ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        source = result.stdout.strip().split("\t", 1)[0].split(":", 2)[0].replace("\\", "/").lower()
        self.assertTrue(source == ".gitignore" or source.endswith("/.gitignore"), result.stdout)
        self.assertNotIn(".git/info/exclude", source)

    def test_unregistered_deep_state_path_remains_nonprivate(self) -> None:
        path = one_click.ROOT / "state" / "us_short" / "anything" / "deep" / "x.json"
        with self.assertRaises(PrivatePathError):
            reject_nonprivate_output_path(path)

        result = subprocess.run(
            ["git", "check-ignore", "-v", "--no-index", "--", str(path)],
            cwd=str(one_click.ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_every_production_state_dir_literal_child_is_gitignored_with_planted_failure(self) -> None:
        children = _production_state_dir_literal_children()
        self.assertTrue(children)
        _assert_state_dir_literal_children_are_gitignored(children)

        planted = ast.parse(
            'def planted(ctx):\n    return ctx.state_dir / "_unregistered_state_child"\n'
        )
        planted_children = [
            (Path("planted_production.py"), node.right.value)
            for node in ast.walk(planted)
            if (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Div)
                and isinstance(node.left, ast.Attribute)
                and isinstance(node.left.value, ast.Name)
                and node.left.value.id == "ctx"
                and node.left.attr == "state_dir"
                and isinstance(node.right, ast.Constant)
                and type(node.right.value) is str
            )
        ]
        with self.assertRaises(AssertionError):
            _assert_state_dir_literal_children_are_gitignored(planted_children)

    @mock.patch(
        "runners.us_short_paper_one_click.resolve_model_paper_activation",
        return_value={"status": "authorized", "receipt": {}},
    )
    @mock.patch("runners.us_short_paper_one_click.run_weekly_capstone", return_value={})
    @mock.patch(
        "runners.us_short_paper_one_click.resolve_capstone_context",
        return_value=SimpleNamespace(decision_date="20260723", price_basis_date="20260722"),
    )
    def test_private_root_never_repoints_shared_source_state(self, _context, run_capstone, _activation) -> None:
        with tempfile.TemporaryDirectory() as td:
            private_root = Path(td)
            run_one_click(now_et=datetime(2026, 7, 23, 8, 0, 0), private_root=private_root)

        kwargs = run_capstone.call_args.kwargs
        self.assertEqual(private_root.resolve(), kwargs["private_root"])
        self.assertEqual(DEFAULT_STATE_DIR.resolve(), kwargs["state_dir"])
        self.assertIsNone(kwargs["max_retries_per_call"])
        self.assertIsNone(kwargs["retry_backoff_seconds"])
        self.assertIsNone(kwargs["max_total_http_attempts"])
        self.assertIs(kwargs["soft_discovery_enabled"], True)
        self.assertIs(kwargs["theme_soft_boost_enabled"], True)

    @mock.patch(
        "runners.us_short_paper_one_click.resolve_model_paper_activation",
        return_value={"status": "authorized", "receipt": {}},
    )
    @mock.patch("runners.us_short_paper_one_click.run_weekly_capstone", return_value={})
    @mock.patch(
        "runners.us_short_paper_one_click.resolve_capstone_context",
        return_value=SimpleNamespace(decision_date="20260723", price_basis_date="20260722"),
    )
    def test_explicit_problem12_controls_reach_the_existing_capstone_owners(self, _context, run_capstone, _activation) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_one_click(
                now_et=datetime(2026, 7, 23, 8, 0, 0),
                private_root=Path(td),
                max_retries_per_call=1,
                retry_backoff_seconds=65.0,
                max_total_http_attempts=123,
                soft_discovery_enabled=False,
                theme_soft_boost_enabled=False,
            )

        kwargs = run_capstone.call_args.kwargs
        self.assertEqual(1, kwargs["max_retries_per_call"])
        self.assertEqual(65.0, kwargs["retry_backoff_seconds"])
        self.assertEqual(123, kwargs["max_total_http_attempts"])
        self.assertIs(kwargs["soft_discovery_enabled"], False)
        self.assertIs(kwargs["theme_soft_boost_enabled"], False)

    @mock.patch(
        "runners.us_short_paper_one_click.resolve_model_paper_activation",
        return_value={"status": "authorized", "receipt": {}},
    )
    @mock.patch(
        "runners.us_short_paper_one_click.resolve_capstone_context",
        return_value=SimpleNamespace(decision_date="20260723", price_basis_date="20260722"),
    )
    @mock.patch("runners.us_short_paper_one_click.run_weekly_capstone")
    def test_unexpected_failure_writes_redacted_private_diagnostics(self, run_capstone, _context, _activation) -> None:
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
            log_path = repo / "argv.jsonl"
            (runners / "us_short_paper_one_click.py").write_text(
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "with Path(os.environ['US_SHORT_ONE_CLICK_ARG_LOG']).open('a', encoding='utf-8') as handle:\n"
                "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                "print('normal stdout summary')\n"
                "print('normal stderr status', file=sys.stderr)\n"
                "raise SystemExit(int(os.environ['US_SHORT_ONE_CLICK_EXIT']))\n",
                encoding="utf-8",
            )
            base = [
                "--momentum-top-k", "200",
                "--provider-pace-seconds", "1",
            ]
            calls = (
                (17, base + [
                    "--max-retries-per-call", "1",
                    "--retry-backoff-seconds", "65",
                    "--max-total-http-attempts", "123",
                    "--disable-soft-discovery",
                    "--disable-theme-soft-boost",
                ]),
                (0, base),
            )
            for expected_exit, expected_argv in calls:
                with self.subTest(expected_exit=expected_exit):
                    env = os.environ.copy()
                    env["US_SHORT_ONE_CLICK_ARG_LOG"] = str(log_path)
                    env["US_SHORT_ONE_CLICK_EXIT"] = str(expected_exit)
                    result = subprocess.run(
                        [
                            powershell,
                            "-NoProfile",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-File",
                            str(runners / "us_short_paper_one_click.ps1"),
                            *(["-MaxRetriesPerCall", "1", "-RetryBackoffSeconds", "65",
                               "-MaxTotalHttpAttempts", "123", "-DisableSoftDiscovery",
                               "-DisableThemeSoftBoost"] if expected_exit == 17 else []),
                        ],
                        cwd=repo,
                        env=env,
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

            recorded = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(recorded), len(calls))
            for actual, (_exit, expected) in zip(recorded, calls):
                self.assertGreaterEqual(len(actual), 2)
                self.assertEqual(actual[0], "--now-et")
                self.assertRegex(actual[1], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
                self.assertEqual(actual[2:], expected)


if __name__ == "__main__":
    unittest.main()
