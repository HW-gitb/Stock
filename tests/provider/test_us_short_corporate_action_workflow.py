from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_corporate_action_workflow as runner  # noqa: E402
from tests.test_us_short_corporate_action_workflow import (  # noqa: E402
    account_state,
    lifecycle,
    manual_input,
    massive_assessment,
    sec_candidate,
    security,
    yfinance_alarm,
)


class CorporateActionWorkflowRunnerTest(unittest.TestCase):
    def _write(self, root: Path, name: str, value: dict) -> Path:
        path = root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def _sources(self, root: Path) -> dict[str, Path]:
        record = security()
        return {
            "identity": self._write(root, "identity.json", record),
            "lifecycle": self._write(root, "lifecycle.json", lifecycle()),
            "sec": self._write(root, "sec.json", sec_candidate(record)),
            "yfinance": self._write(root, "yfinance.json", yfinance_alarm(record)),
            "massive": self._write(root, "massive.json", massive_assessment()),
            "manual": self._write(root, "manual.json", manual_input(record)),
            "account": self._write(root, "account.json", account_state()),
        }

    def _base_args(self, paths: dict[str, Path], workflow_out: Path, ticket_out: Path) -> list[str]:
        return [
            "--identity", str(paths["identity"]),
            "--lifecycle-observation", str(paths["lifecycle"]),
            "--sec-candidate", str(paths["sec"]),
            "--yfinance-alarm", str(paths["yfinance"]),
            "--massive-assessment", str(paths["massive"]),
            "--workflow-out", str(workflow_out),
            "--private-disposition-out", str(ticket_out),
        ]

    def test_one_command_stops_at_review_until_manual_and_account_confirmations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._sources(root)
            workflow_out = root / "workflow.json"
            ticket_out = root / "ticket.json"
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(runner.main(self._base_args(paths, workflow_out, ticket_out)), 0)
            result = json.loads(workflow_out.read_text(encoding="utf-8"))
            self.assertEqual(result["workflow_status"], "manual_review_required")
            self.assertFalse(ticket_out.exists())
            self.assertEqual(json.loads(captured.getvalue())["workflow_status"], "manual_review_required")

    def test_one_command_writes_private_workflow_and_ticket_after_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._sources(root)
            workflow_out = root / "workflow.json"
            ticket_out = root / "ticket.json"
            args = self._base_args(paths, workflow_out, ticket_out) + [
                "--manual-input", str(paths["manual"]),
                "--account-state", str(paths["account"]),
                "--confirm", "--confirm-account-read",
            ]
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(runner.main(args), 0)
            result = json.loads(workflow_out.read_text(encoding="utf-8"))
            ticket = json.loads(ticket_out.read_text(encoding="utf-8"))
            self.assertEqual(result["workflow_status"], "private_disposition_prepared")
            self.assertEqual(ticket["manual_disposition"]["cash_entitlement_cents"], 27100)
            self.assertNotIn("27100", captured.getvalue())
            self.assertNotIn("shares", captured.getvalue())
            self.assertTrue(result["boundary"]["account_state_read"])
            self.assertFalse(result["boundary"]["account_state_mutated"])
            self.assertEqual(
                result["disposition"]["ticket_ref_sha256"],
                hashlib.sha256(ticket_out.read_bytes()).hexdigest(),
            )

    def test_tracked_output_or_confirmation_without_manual_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._sources(root)
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(runner.main(
                    self._base_args(paths, ROOT / "docs" / "forbidden_workflow.json", root / "ticket.json")
                ), 2)
            self.assertIn("private output path is unsafe", captured.getvalue())

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                self.assertEqual(runner.main(
                    self._base_args(paths, root / "workflow.json", root / "ticket.json")
                    + ["--confirm", "--confirm-account-read"]
                ), 2)
            self.assertIn("manual input", captured.getvalue())

    def test_partial_output_commit_failure_removes_ticket_and_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._sources(root)
            workflow_out = root / "workflow.json"
            ticket_out = root / "ticket.json"
            args = self._base_args(paths, workflow_out, ticket_out) + [
                "--manual-input", str(paths["manual"]),
                "--account-state", str(paths["account"]),
                "--confirm", "--confirm-account-read",
            ]
            real_link = runner.os.link
            link_count = 0

            def fail_after_ticket(source, target):
                nonlocal link_count
                link_count += 1
                if link_count == 2:
                    raise OSError("simulated workflow commit failure")
                return real_link(source, target)

            captured = io.StringIO()
            with mock.patch.object(runner.os, "link", side_effect=fail_after_ticket):
                with contextlib.redirect_stdout(captured):
                    self.assertEqual(runner.main(args), 2)
            self.assertIn("could not be committed", captured.getvalue())
            self.assertFalse(workflow_out.exists())
            self.assertFalse(ticket_out.exists())

    def test_output_created_after_precheck_is_preserved_without_partial_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._sources(root)
            workflow_out = root / "workflow.json"
            ticket_out = root / "ticket.json"
            args = self._base_args(paths, workflow_out, ticket_out) + [
                "--manual-input", str(paths["manual"]),
                "--account-state", str(paths["account"]),
                "--confirm", "--confirm-account-read",
            ]
            real_link = runner.os.link
            link_count = 0

            def create_racing_workflow(source, target):
                nonlocal link_count
                link_count += 1
                if link_count == 2:
                    workflow_out.write_text("foreign workflow", encoding="utf-8")
                    raise FileExistsError("simulated no-clobber race")
                return real_link(source, target)

            captured = io.StringIO()
            with mock.patch.object(runner.os, "link", side_effect=create_racing_workflow):
                with contextlib.redirect_stdout(captured):
                    self.assertEqual(runner.main(args), 2)
            self.assertEqual(workflow_out.read_text(encoding="utf-8"), "foreign workflow")
            self.assertFalse(ticket_out.exists())
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_ticket_staging_failure_removes_staged_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._sources(root)
            workflow_out = root / "workflow.json"
            ticket_out = root / "ticket.json"
            args = self._base_args(paths, workflow_out, ticket_out) + [
                "--manual-input", str(paths["manual"]),
                "--account-state", str(paths["account"]),
                "--confirm", "--confirm-account-read",
            ]
            real_stage = runner._stage_json
            stage_count = 0

            def fail_ticket_stage(path, value):
                nonlocal stage_count
                stage_count += 1
                if stage_count == 2:
                    raise runner.CorporateActionWorkflowRunnerError("simulated ticket staging failure")
                return real_stage(path, value)

            captured = io.StringIO()
            with mock.patch.object(runner, "_stage_json", side_effect=fail_ticket_stage):
                with contextlib.redirect_stdout(captured):
                    self.assertEqual(runner.main(args), 2)
            self.assertIn("ticket staging failure", captured.getvalue())
            self.assertFalse(workflow_out.exists())
            self.assertFalse(ticket_out.exists())
            self.assertEqual(list(root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
