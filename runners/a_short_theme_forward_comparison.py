"""Generate the A-short industry/theme forward comparison packet from the local tracker."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import pandas as pd

from engine.a_short_theme_forward_comparison import evaluate_theme_forward_comparison


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACKER = ROOT / "logs" / "forward_tracker.csv"
DEFAULT_OUTPUT = ROOT / "research" / "results" / "a_short_theme_forward_comparison.json"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate local A-short theme comparison evidence; no data fetch or promotion.")
    parser.add_argument("--tracker", default=str(DEFAULT_TRACKER))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    tracker_path = Path(args.tracker)
    if not tracker_path.exists():
        raise SystemExit(f"[FATAL] forward tracker not found: {tracker_path}")
    packet = evaluate_theme_forward_comparison(pd.read_csv(tracker_path, dtype={"as_of": str, "ts_code": str}))
    _write_json_atomic(Path(args.out), packet)
    print(f"[OK] wrote comparison packet: {args.out}; review_status={packet['review_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
