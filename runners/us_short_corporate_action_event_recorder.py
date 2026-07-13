"""Print one sanitized, offline manual corporate-action event record; never fetch or write files."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_corporate_action_event_recorder as recorder  # noqa: E402


class ManualEventRecorderRunnerError(RuntimeError):
    """The explicitly supplied local manual-input file cannot be used safely."""


def _read_manual_input(path: Path) -> Any:
    if path.suffix != ".json":
        raise ManualEventRecorderRunnerError("manual input must be a JSON file")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManualEventRecorderRunnerError("manual input is missing or unreadable") from exc


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual-input", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true", help="confirm the human-reviewed SEC transcription")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = recorder.record_manual_corporate_action(_read_manual_input(args.manual_input), confirm=args.confirm)
    except (ManualEventRecorderRunnerError, recorder.CorporateActionEventRecorderError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
