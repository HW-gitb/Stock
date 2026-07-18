#!/usr/bin/env python3
"""Cache-only settlement utility for the A-short D1/D3 private comparison track.

Capture is called directly by the weekly pipeline while it still holds the
PIT-normalized candidate inputs.  This runner deliberately performs no provider
call: it only settles frozen selections from the already-approved shared forward
price cache, then refreshes factor verdicts and persistent reminders.
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_factor_comparison import DEFAULT_PRIVATE_ROOT, settle_from_daily_payload
from runners.backtest_rank import FORWARD_DAILY_CACHE


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
