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

``settle-week`` is the ordinary weekly act: it computes the next week from the
already-local model-paper artifacts and a local benchmark price packet, stores it
through the gate, and — because a closing week must not depend on somebody
remembering a second command — attempts publication every time, which is a no-op
except on a 26/52/78-week boundary.

``record-week`` carries a weekly record somebody already produced. It is the
repair and replay path, not the weekly one.

``publish`` emits the scorecard on its own, for the case where a week was stored
with ``--no-publish`` or publication failed and is being retried.

No subcommand calls a provider, seeds or writes the model-paper account, or
changes selection, action, sizing or NAV. Weekly evidence lands under the
private, git-ignored diagnostic root; the only thing published is the
de-identified 26-week scorecard the design asks for.
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

from engine.us_short_market_diagnostic_aggregator import (  # noqa: E402
    DEFAULT_PUBLIC_ROOT,
    MarketDiagnosticAggregationError,
    publish_completed_market_diagnostic_window,
)
from engine.us_short_market_diagnostic_lifecycle import (  # noqa: E402
    DEFAULT_ROOT,
    MarketDiagnosticLifecycleError,
    load_lifecycle_register,
    persist_settled_weekly_record,
    render_weekly_report_reminder,
)
from engine.us_short_market_diagnostic_weekly_producer import (  # noqa: E402
    MarketDiagnosticWeeklyProducerError,
    diagnostic_store_state,
    settle_next_week,
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
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Record the design-completion decision that opens the 26-week clock.

    ``dry_run`` runs every check the real thing runs and then writes nothing,
    because the write is exclusive and irreversible: one mistyped date otherwise
    anchors the clock on the wrong week forever. A dry run that only echoed its
    inputs back would accept the exact typo it exists to catch.

    Resolving today's date is the runner's job; the engine below takes it as a
    required argument so the check cannot be switched off by omission.
    """

    if as_of_date is None:
        as_of_date = _date.today().strftime("%Y%m%d")
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
                as_of_date=as_of_date,
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
            as_of_date=as_of_date,
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


def settle_week(
    *,
    model_paper_root: Path,
    benchmark_packet_path: Path,
    root: Path = DEFAULT_ROOT,
    total_return_sidecar_path: Path | None = None,
    as_of_date: str | None = None,
    publish: bool = True,
    output_root: Path = DEFAULT_PUBLIC_ROOT,
) -> dict[str, Any]:
    """Compute this week from local inputs, store it, and publish if a window closed.

    This is the subcommand the track was missing. ``record-week`` carries a record
    somebody else produced; nobody produced one, so the clock could be opened and
    then immediately fail to advance. Here the week is computed from the local
    model-paper artifacts and the local benchmark packet, at the index the store
    itself says is next.

    The benchmark packet is a file the caller names because nothing in the repo
    produces one yet. That is a real remaining gap, recorded as such, and it is
    still better than the alternative: a producer that invents prices when its
    upstream is absent is exactly the failure this whole track exists to detect.
    """

    if as_of_date is None:
        as_of_date = _date.today().strftime("%Y%m%d")
    packet = _read_json(benchmark_packet_path, "benchmark price packet")
    sidecar = (
        _read_json(total_return_sidecar_path, "total-return sidecar")
        if total_return_sidecar_path is not None
        else None
    )
    try:
        result = settle_next_week(
            model_paper_root=model_paper_root,
            benchmark_packet=packet,
            root=root,
            total_return_sidecar=sidecar,
            as_of_date=as_of_date,
        )
        register = load_lifecycle_register(root, as_of_date=as_of_date)
    except (MarketDiagnosticWeeklyProducerError, MarketDiagnosticLifecycleError) as exc:
        raise MarketDiagnosticWeeklyRunnerError(str(exc)) from exc

    settled = {
        "status": result["status"],
        "calendar_week_index": result["calendar_week_index"],
        "calendar_week_count": result["calendar_week_count"],
        "evaluable_week_count": result["evaluable_week_count"],
        "v1_1_reminder": result["v1_1_reminder"],
        "weekly_report_reminder_text": render_weekly_report_reminder(register),
    }
    # Publishing is attempted every week and is a no-op except on a boundary, so a
    # closing week cannot be missed by nobody remembering to run a second command.
    settled["publication"] = (
        publish_window(root=root, output_root=output_root, as_of_date=as_of_date)
        if publish
        else {"status": "skipped"}
    )
    return settled


def publish_window(
    *,
    root: Path = DEFAULT_ROOT,
    output_root: Path = DEFAULT_PUBLIC_ROOT,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Emit the 26/52/78-week scorecard when a window has closed; otherwise say so.

    The engine has been able to do this since Knife 4; nothing ever called it, so
    the one artifact this track exists to produce had no way of being produced.
    """

    if as_of_date is None:
        as_of_date = _date.today().strftime("%Y%m%d")
    try:
        return publish_completed_market_diagnostic_window(
            lifecycle_root=root, output_root=output_root, as_of_date=as_of_date
        )
    except MarketDiagnosticAggregationError as exc:
        raise MarketDiagnosticWeeklyRunnerError(str(exc)) from exc


def clock_status(*, root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    """Say plainly which of four things this clock is, without opening anything.

    ``not_started`` / ``fresh`` / ``running`` / ``broken`` come from the single
    store-state decider, so this cannot disagree with what the weekly task or the
    producer sees. Three readers used to answer this separately and each got a
    different case wrong: a clock opened this week read as broken, and a store
    whose receipt had been deleted under counted weeks read as never started.
    """

    state = diagnostic_store_state(root)
    if state["state"] == "not_started":
        return {"clock_status": "not_started", "diagnostic_epoch": None, "calendar_week_count": 0}
    if state["state"] == "fresh":
        return {
            "clock_status": "fresh",
            "diagnostic_epoch": state["receipt"]["diagnostic_epoch"],
            "first_decision_date": state["receipt"]["first_calendar_week"]["decision_date"],
            "calendar_week_count": 0,
        }
    if state["state"] == "broken":
        receipt = state["receipt"]
        return {
            "clock_status": "broken",
            "diagnostic_epoch": None if receipt is None else receipt["diagnostic_epoch"],
            "calendar_week_count": None,
            "problem": state["problem"],
        }
    register = state["register"]
    return {
        "clock_status": "started",
        "diagnostic_epoch": register["diagnostic_epoch"],
        "first_decision_date": state["receipt"]["first_calendar_week"]["decision_date"],
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

    settle = sub.add_parser("settle-week", help="compute this week from local inputs and store it")
    settle.add_argument("--model-paper-root", type=Path, required=True)
    settle.add_argument("--benchmark-packet-path", type=Path, required=True)
    settle.add_argument("--total-return-sidecar-path", type=Path)
    settle.add_argument("--output-root", type=Path, default=DEFAULT_PUBLIC_ROOT)
    settle.add_argument(
        "--no-publish",
        action="store_true",
        help="store the week but do not emit a scorecard even if this week closes a window",
    )
    settle.add_argument("--as-of-date", help="YYYYMMDD; defaults to today so future data fails closed")

    weekly = sub.add_parser("record-week", help="carry one already-settled weekly record (repair/replay)")
    weekly.add_argument("--weekly-record-path", type=Path, required=True)
    weekly.add_argument("--as-of-date", help="YYYYMMDD; defaults to today so future data fails closed")

    emit = sub.add_parser("publish", help="emit the scorecard if a 26-week window has closed")
    emit.add_argument("--output-root", type=Path, default=DEFAULT_PUBLIC_ROOT)
    emit.add_argument("--as-of-date", help="YYYYMMDD; defaults to today so future data fails closed")

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
        elif args.command == "settle-week":
            result = settle_week(
                model_paper_root=args.model_paper_root,
                benchmark_packet_path=args.benchmark_packet_path,
                root=args.root,
                total_return_sidecar_path=args.total_return_sidecar_path,
                as_of_date=args.as_of_date,
                publish=not args.no_publish,
                output_root=args.output_root,
            )
            print(
                f"week {result['calendar_week_index']} {result['status']}: "
                f"{result['calendar_week_count']} calendar / {result['evaluable_week_count']} evaluable"
            )
            print(result["weekly_report_reminder_text"])
            publication = result["publication"]
            if publication["status"] in {"published", "idempotent"}:
                print(f"scorecard {publication['status']}: {publication['window_id']}")
            else:
                print(f"scorecard: {publication['status']}")
        elif args.command == "publish":
            result = publish_window(
                root=args.root, output_root=args.output_root, as_of_date=args.as_of_date
            )
            if result["status"] in {"published", "idempotent"}:
                print(f"scorecard {result['status']}: {result['window_id']}")
            else:
                print(f"scorecard: {result['status']}")
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
