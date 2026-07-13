"""Record one offline corporate action and write its actual ticket only to a private path."""
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
from engine import us_short_private_paths as private_paths  # noqa: E402


class ManualEventRecorderRunnerError(RuntimeError):
    """The explicitly supplied local manual-input file cannot be used safely."""


def _read_json(path: Path, *, label: str) -> Any:
    if path.suffix != ".json":
        raise ManualEventRecorderRunnerError(f"{label} must be a JSON file")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManualEventRecorderRunnerError(f"{label} is missing or unreadable") from exc


def _write_private_disposition(path: Path, ticket: dict[str, Any]) -> None:
    try:
        private_paths.reject_nonprivate_output_path(str(path))
    except private_paths.PrivatePathError as exc:
        raise ManualEventRecorderRunnerError("private disposition output path is unsafe") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(ticket, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    except OSError as exc:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass
        raise ManualEventRecorderRunnerError("private disposition artifact could not be written") from exc


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual-input", type=Path, required=True)
    parser.add_argument("--account-state", type=Path, required=True, help="private local us_short_account_state JSON")
    parser.add_argument("--confirm-account-read", action="store_true", help="explicitly allow this one private local account read")
    parser.add_argument("--private-disposition-out", type=Path, required=True, help="absolute gitignored or external private ticket path")
    parser.add_argument("--confirm", action="store_true", help="confirm the human-reviewed SEC transcription")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        manual = _read_json(args.manual_input, label="manual input")
        account_state = None
        account_state_read = False
        if args.confirm and args.confirm_account_read:
            account_state_read = True
            try:
                account_state = _read_json(args.account_state, label="account state")
            except ManualEventRecorderRunnerError:
                account_state = None
        result = recorder.record_manual_corporate_action(
            manual,
            account_state=account_state,
            confirm=args.confirm,
            account_state_read=account_state_read,
        )
        if result["record_status"] == "confirmed_event":
            _write_private_disposition(
                args.private_disposition_out,
                recorder.build_private_disposition(account_state, result),
            )
    except (ManualEventRecorderRunnerError, recorder.CorporateActionEventRecorderError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
