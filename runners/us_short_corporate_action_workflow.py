"""Run the private offline US-short corporate-action manual workflow in one command."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_corporate_action_event_recorder as recorder  # noqa: E402
from engine import us_short_corporate_action_workflow as workflow  # noqa: E402
from engine import us_short_private_paths as private_paths  # noqa: E402


class CorporateActionWorkflowRunnerError(RuntimeError):
    """The private workflow command cannot proceed without weakening its safety boundary."""


def _read_json(path: Path | None, *, label: str, required: bool = False) -> Any | None:
    if path is None:
        if required:
            raise CorporateActionWorkflowRunnerError(f"{label} is required")
        return None
    if path.suffix.lower() != ".json":
        raise CorporateActionWorkflowRunnerError(f"{label} must be a JSON file")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorporateActionWorkflowRunnerError(f"{label} is missing or unreadable") from exc


def _json_bytes(value: Any) -> bytes:
    try:
        return workflow.private_artifact_bytes(value)
    except workflow.CorporateActionWorkflowError as exc:
        raise CorporateActionWorkflowRunnerError("private workflow output is not canonical JSON") from exc


def _check_output(path: Path, *, label: str) -> Path:
    if path.suffix.lower() != ".json":
        raise CorporateActionWorkflowRunnerError(f"{label} must be a JSON file")
    try:
        private_paths.reject_nonprivate_output_path(str(path))
    except private_paths.PrivatePathError as exc:
        raise CorporateActionWorkflowRunnerError("private output path is unsafe") from exc
    if path.exists():
        raise CorporateActionWorkflowRunnerError(f"{label} already exists; refusing to overwrite it")
    return path


def _stage_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, CorporateActionWorkflowRunnerError) as exc:
        try:
            os.close(fd)
        except OSError:
            pass
        temp.unlink(missing_ok=True)
        raise CorporateActionWorkflowRunnerError("private workflow output could not be staged") from exc
    return temp


def _write_outputs(
    *, workflow_path: Path, workflow_value: dict[str, Any], ticket_path: Path, ticket_value: dict[str, Any] | None
) -> None:
    workflow_temp = _stage_json(workflow_path, workflow_value)
    try:
        ticket_temp = _stage_json(ticket_path, ticket_value) if ticket_value is not None else None
    except CorporateActionWorkflowRunnerError:
        workflow_temp.unlink(missing_ok=True)
        raise
    ticket_written = False
    workflow_written = False
    try:
        if ticket_temp is not None:
            os.link(ticket_temp, ticket_path)
            ticket_written = True
            ticket_temp.unlink()
        os.link(workflow_temp, workflow_path)
        workflow_written = True
        workflow_temp.unlink()
    except OSError as exc:
        workflow_temp.unlink(missing_ok=True)
        if ticket_temp is not None:
            ticket_temp.unlink(missing_ok=True)
        if ticket_written:
            ticket_path.unlink(missing_ok=True)
        if workflow_written:
            workflow_path.unlink(missing_ok=True)
        raise CorporateActionWorkflowRunnerError("private workflow outputs could not be committed") from exc


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--lifecycle-observation", type=Path)
    parser.add_argument("--sec-candidate", type=Path)
    parser.add_argument("--yfinance-alarm", type=Path)
    parser.add_argument("--massive-assessment", type=Path)
    parser.add_argument("--manual-input", type=Path)
    parser.add_argument("--account-state", type=Path)
    parser.add_argument("--confirm", action="store_true", help="confirm the human-reviewed SEC transcription")
    parser.add_argument("--confirm-account-read", action="store_true", help="allow this one private local account read")
    parser.add_argument("--workflow-out", type=Path, required=True)
    parser.add_argument("--private-disposition-out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        workflow_path = _check_output(args.workflow_out, label="workflow output")
        ticket_path = _check_output(args.private_disposition_out, label="private disposition output")
        if workflow_path.resolve() == ticket_path.resolve():
            raise CorporateActionWorkflowRunnerError("workflow and disposition outputs must be different files")
        if (args.confirm or args.confirm_account_read) and args.manual_input is None:
            raise CorporateActionWorkflowRunnerError("confirmation flags require a manual input")
        if args.confirm_account_read and not args.confirm:
            raise CorporateActionWorkflowRunnerError("account-read confirmation requires manual confirmation")
        if args.confirm and args.confirm_account_read and args.account_state is None:
            raise CorporateActionWorkflowRunnerError("account state is required for a confirmed private ticket")

        identity_record = _read_json(args.identity, label="identity", required=True)
        lifecycle_observation = _read_json(args.lifecycle_observation, label="lifecycle observation")
        sec_candidate = _read_json(args.sec_candidate, label="SEC candidate")
        yfinance_alarm = _read_json(args.yfinance_alarm, label="yfinance alarm")
        massive_assessment = _read_json(args.massive_assessment, label="Massive assessment")

        manual_record = None
        account_state = None
        if args.manual_input is not None:
            manual = _read_json(args.manual_input, label="manual input", required=True)
            account_state_read = bool(args.confirm and args.confirm_account_read)
            if account_state_read:
                account_state = _read_json(args.account_state, label="account state", required=True)
            manual_record = recorder.record_manual_corporate_action(
                manual,
                account_state=account_state,
                confirm=args.confirm,
                account_state_read=account_state_read,
            )

        preliminary = workflow.build_corporate_action_workflow(
            identity_record=identity_record,
            lifecycle_observation=lifecycle_observation,
            sec_parse_candidate=sec_candidate,
            yfinance_daily_alarm=yfinance_alarm,
            massive_assessment=massive_assessment,
            manual_event_record=manual_record,
            disposition_ticket=None,
        )
        ticket = None
        result = preliminary
        if preliminary["workflow_status"] == "private_disposition_ready":
            ticket = recorder.build_private_disposition(account_state, manual_record)
            result = workflow.build_corporate_action_workflow(
                identity_record=identity_record,
                lifecycle_observation=lifecycle_observation,
                sec_parse_candidate=sec_candidate,
                yfinance_daily_alarm=yfinance_alarm,
                massive_assessment=massive_assessment,
                manual_event_record=manual_record,
                disposition_ticket=ticket,
            )
        _write_outputs(
            workflow_path=workflow_path,
            workflow_value=result,
            ticket_path=ticket_path,
            ticket_value=ticket,
        )
    except (
        CorporateActionWorkflowRunnerError,
        workflow.CorporateActionWorkflowError,
        recorder.CorporateActionEventRecorderError,
    ) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(
        {
            "schema_name": result["schema_name"],
            "current_ticker": result["security_binding"]["current_ticker"],
            "workflow_status": result["workflow_status"],
            "private_ticket_written": ticket is not None,
        },
        ensure_ascii=True,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
