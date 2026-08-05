"""US-short 26-week market diagnostic — the operator entry that goes through the gate.

Until this runner existed the Knife 7 start gate was real but unreachable: nothing
in ``runners/`` ever called the store, so the door stood in a field. This is the
one path an operator uses, and it can only do what the gate allows.

Two subcommands, deliberately separate because they are different kinds of act:

``open-clock`` records a design-completion decision. It is not a routine step and
it happens once: it needs the notification text on disk, an explicit confirmation
flag, and the calendar week being frozen as week 1. Re-running it with the same
inputs is a no-op; re-running it with different ones is refused rather than
allowed to re-anchor a clock other artifacts have already been counted against.

``record-week`` persists one already-settled weekly record. It reads, it never
computes a week: the record comes from the local adapter, and this runner only
carries it through the gate and reports what the lifecycle now says.

Neither subcommand calls a provider, seeds or writes the model-paper account, or
changes selection, action, sizing or NAV. Everything written lands under the
private, git-ignored diagnostic root; nothing here publishes.
"""
from __future__ import annotations

import argparse
import json
from datetime import date as _date
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if _PYTHON_LIBS.exists() and str(_PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(_PYTHON_LIBS))

from engine.us_short_market_diagnostic_lifecycle import (  # noqa: E402
    DEFAULT_ROOT,
    MarketDiagnosticLifecycleError,
    load_lifecycle_register,
    persist_settled_weekly_record,
    render_weekly_report_reminder,
)
from engine.us_short_market_diagnostic_start_receipt import (  # noqa: E402
    DiagnosticStartReceiptError,
    _private_root,
    build_start_receipt,
    issue_start_receipt,
    load_start_receipt,
)


class MarketDiagnosticWeeklyRunnerError(RuntimeError):
    """The diagnostic weekly step cannot run safely."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MarketDiagnosticWeeklyRunnerError(f"cannot read {label}: {path}") from exc
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MarketDiagnosticWeeklyRunnerError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MarketDiagnosticWeeklyRunnerError(f"{label} must be a JSON object: {path}")
    return value


def _read_notification(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MarketDiagnosticWeeklyRunnerError(f"cannot read the notification: {path}") from exc
    if len(text.strip()) < 16:
        raise MarketDiagnosticWeeklyRunnerError(
            "the completion notification is too short to be a notification"
        )
    return text


def open_clock(
    *,
    confirm_design_complete: bool,
    notification_path: Path,
    issued_at: str,
    diagnostic_epoch: str,
    first_decision_date: str,
    root: Path = DEFAULT_ROOT,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Record the design-completion decision that opens the 26-week clock.

    ``dry_run`` runs every check the real thing runs and then writes nothing,
    because the write is exclusive and irreversible: one mistyped date otherwise
    anchors the clock on the wrong week forever. A dry run that only echoed its
    inputs back would accept the exact typo it exists to catch.
    """

    if dry_run:
        text = _read_notification(notification_path)
        try:
            _private_root(root)
            receipt = build_start_receipt(
                diagnostic_epoch=diagnostic_epoch,
                completion_notification={
                    "issued_at": issued_at,
                    "issuer": "codex",
                    "notification_text": text,
                },
                first_decision_date=first_decision_date,
            )
        except DiagnosticStartReceiptError as exc:
            raise MarketDiagnosticWeeklyRunnerError(str(exc)) from exc
        return {
            "status": "dry_run",
            "diagnostic_epoch": receipt["diagnostic_epoch"],
            "first_decision_date": receipt["first_calendar_week"]["decision_date"],
            "issued_at": receipt["completion_notification"]["issued_at"],
            "notification_first_line": text.strip().splitlines()[0][:120],
        }
    if not confirm_design_complete:
        raise MarketDiagnosticWeeklyRunnerError(
            "opening the diagnostic clock requires --confirm-design-complete; a date, a "
            "component completion, an account seeding, or a commit is not a decision"
        )
    text = _read_notification(notification_path)
    try:
        return issue_start_receipt(
            diagnostic_epoch=diagnostic_epoch,
            completion_notification={
                "issued_at": issued_at,
                "issuer": "codex",
                "notification_text": text,
            },
            first_decision_date=first_decision_date,
            root=root,
        )
    except DiagnosticStartReceiptError as exc:
        raise MarketDiagnosticWeeklyRunnerError(str(exc)) from exc


def record_week(
    *,
    weekly_record_path: Path,
    root: Path = DEFAULT_ROOT,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Carry one already-settled weekly record through the gate.

    ``as_of_date`` defaults to today rather than to ``None``: the look-ahead guard
    exists in the store, and leaving it unset here is what let a whole clock be
    recorded on dates years in the future.
    """

    if as_of_date is None:
        as_of_date = _date.today().strftime("%Y%m%d")
    record = _read_json(weekly_record_path, "weekly record")
    try:
        result = persist_settled_weekly_record(record, root=root, as_of_date=as_of_date)
        register = load_lifecycle_register(root, as_of_date=as_of_date)
    except MarketDiagnosticLifecycleError as exc:
        raise MarketDiagnosticWeeklyRunnerError(str(exc)) from exc
    return {
        "status": result["status"],
        "calendar_week_index": result["calendar_week_index"],
        "calendar_week_count": result["calendar_week_count"],
        "evaluable_week_count": result["evaluable_week_count"],
        "v1_1_reminder": result["v1_1_reminder"],
        "weekly_report_reminder_text": render_weekly_report_reminder(register),
    }


def clock_status(*, root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    """Say plainly whether the clock is running, without opening anything.

    A store that cannot be read is reported as broken, never as a clock with zero
    weeks. Those two look identical to an operator and mean opposite things: one
    says "nothing has happened yet", the other says "eighteen weeks of evidence
    are unreadable". Reading is not an AUTHORIZE moment, so the contract digest is
    not re-checked here.
    """

    try:
        receipt = load_start_receipt(root, verify_design_against_disk=False)
    except DiagnosticStartReceiptError as exc:
        return {
            "clock_status": "broken",
            "diagnostic_epoch": None,
            "calendar_week_count": None,
            "problem": str(exc),
        }
    if receipt is None:
        return {"clock_status": "not_started", "diagnostic_epoch": None, "calendar_week_count": 0}
    try:
        register = load_lifecycle_register(root)
    except MarketDiagnosticLifecycleError as exc:
        return {
            "clock_status": "broken",
            "diagnostic_epoch": receipt["diagnostic_epoch"],
            "first_decision_date": receipt["first_calendar_week"]["decision_date"],
            "calendar_week_count": None,
            "problem": str(exc),
        }
    return {
        "clock_status": "started",
        "diagnostic_epoch": receipt["diagnostic_epoch"],
        "first_decision_date": receipt["first_calendar_week"]["decision_date"],
        "calendar_week_count": register["calendar_week_count"],
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="US-short 26-week market diagnostic weekly entry")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    opener = sub.add_parser("open-clock", help="record the design-completion decision (once)")
    opener.add_argument("--confirm-design-complete", action="store_true")
    opener.add_argument("--dry-run", action="store_true", help="resolve and echo; write nothing")
    opener.add_argument("--notification-path", type=Path, required=True)
    opener.add_argument("--issued-at", required=True, help="timezone-aware ISO-8601 instant")
    opener.add_argument("--diagnostic-epoch", required=True)
    opener.add_argument("--first-decision-date", required=True, help="YYYYMMDD of week 1")

    weekly = sub.add_parser("record-week", help="persist one already-settled weekly record")
    weekly.add_argument("--weekly-record-path", type=Path, required=True)
    weekly.add_argument("--as-of-date", help="YYYYMMDD; defaults to today so future data fails closed")

    sub.add_parser("status", help="report whether the clock is running")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "open-clock":
            result = open_clock(
                confirm_design_complete=args.confirm_design_complete,
                notification_path=args.notification_path,
                issued_at=args.issued_at,
                diagnostic_epoch=args.diagnostic_epoch,
                first_decision_date=args.first_decision_date,
                root=args.root,
                dry_run=args.dry_run,
            )
            if result["status"] == "dry_run":
                print(
                    f"dry run: epoch={result['diagnostic_epoch']} "
                    f"week1={result['first_decision_date']} issued_at={result['issued_at']}"
                )
                print(f"  notification: {result['notification_first_line']}")
            else:
                print(f"clock {result['status']}: epoch={result['receipt']['diagnostic_epoch']}")
        elif args.command == "record-week":
            result = record_week(
                weekly_record_path=args.weekly_record_path,
                root=args.root,
                as_of_date=args.as_of_date,
            )
            print(
                f"week {result['calendar_week_index']} {result['status']}: "
                f"{result['calendar_week_count']} calendar / {result['evaluable_week_count']} evaluable"
            )
            print(result["weekly_report_reminder_text"])
        else:
            result = clock_status(root=args.root)
            if result["clock_status"] == "broken":
                print(f"clock: broken - {result['problem']}")
                return 2
            print(f"clock: {result['clock_status']} weeks={result['calendar_week_count']}")
    except MarketDiagnosticWeeklyRunnerError as exc:
        print(f"ERROR: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
