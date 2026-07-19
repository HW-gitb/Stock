#!/usr/bin/env python3
"""Cache-only settlement utility for the A-short D1/D3 private comparison track.

Capture is called directly by the weekly pipeline while it still holds the
PIT-normalized candidate inputs.  This runner deliberately performs no provider
call: it only settles frozen selections from the already-approved shared forward
price cache, then refreshes factor verdicts and persistent reminders.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_factor_comparison import DEFAULT_PRIVATE_ROOT, settle_from_daily_payload
from runners.backtest_rank import FORWARD_DAILY_CACHE


def _settlement_cache_required(root: Path, today: str) -> tuple[bool, str]:
    """Avoid treating a future-only forward cohort as a missing-price incident.

    The sidecar can only settle after its decision date. A fresh Friday or
    weekend run commonly freezes the next Monday's cohort, so no shared price
    cache is needed yet. Any malformed, current, or past pending snapshot
    remains cache-required and therefore keeps the existing loud cache warning.
    """
    if not root.exists():
        return False, "no frozen comparison snapshots"
    snapshots = [path for path in root.iterdir() if path.is_dir() and path.name.isdigit()]
    if not snapshots:
        return False, "no frozen comparison snapshots"
    for day in snapshots:
        try:
            manifest = json.loads((day / "manifest.json").read_text(encoding="utf-8"))
            baseline = json.loads((day / "baseline_result.json").read_text(encoding="utf-8"))
            pending = baseline["outcome"]["status"] != "settled_h10"
            decision_date = str(manifest["decision_date"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            return True, "comparison snapshot is malformed"
        if bool(manifest.get("forward_eligible")) and pending and decision_date <= today:
            return True, "a forward comparison snapshot may need settlement"
    return False, "all pending forward comparison snapshots are future-dated"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="A-short D1/D3 factor comparison cache-only settler")
    parser.add_argument("settle", nargs="?", default="settle")
    parser.add_argument("--root", default=str(DEFAULT_PRIVATE_ROOT),
                        help="must end state/a_short/factor_comparison_private")
    parser.add_argument("--cache", default=str(FORWARD_DAILY_CACHE),
                        help="existing forward_daily.pkl; this runner never fetches")
    args = parser.parse_args(argv)
    if args.settle != "settle":
        raise SystemExit("only the cache-only settle command is supported")
    root = Path(args.root)
    cache_required, cache_reason = _settlement_cache_required(
        root, datetime.now().astimezone().strftime("%Y%m%d")
    )
    if not cache_required:
        print(f"[factor-comparison] {cache_reason}; no cache read or forward outcome settlement needed")
        return 0
    cache_path = Path(args.cache)
    if not cache_path.exists():
        print(f"[factor-comparison] cache unavailable: {cache_path}; no forward outcomes settled")
        return 0
    with cache_path.open("rb") as handle:
        payload = pickle.load(handle)
    result = settle_from_daily_payload(root=args.root, daily_payload=payload)
    reminders = (result.get("reminder") or {}).get("reminders") or []
    reminder_count = len(reminders)
    print(f"[factor-comparison] cache settlement updated={len(result.get('updated_dates') or [])}; "
          f"pending user reminders={reminder_count}; production unchanged")
    for reminder in reminders:
        print(f"[factor-comparison reminder] {reminder['factor_id']}: {reminder['status']}; "
              "user decision required, production unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
