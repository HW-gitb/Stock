#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-share business dates must be derived from the Shanghai market clock."""
from __future__ import annotations

import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_share_market_clock import (  # noqa: E402
    A_SHARE_MARKET_TZ,
    a_share_market_wall_time,
)
from runners.resolve_canonical_asof import resolve_canonical_asof  # noqa: E402


class AShareMarketClockTests(unittest.TestCase):
    def test_windows_market_clock_dependency_is_directly_declared(self):
        requirements = (ROOT / "requirements-a-short.txt").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any(re.match(r"^tzdata(?:[<>=!~]|$)", line.strip()) for line in requirements))

    def test_same_utc_instant_uses_shanghai_close_boundary(self):
        # 2026-06-26 07:30 UTC = 15:30 Shanghai, even though a west-coast
        # host would still show 00:30 on 2026-06-26.
        market_now = a_share_market_wall_time(
            datetime(2026, 6, 26, 7, 30, tzinfo=timezone.utc))
        self.assertEqual(market_now, datetime(2026, 6, 26, 15, 30))
        self.assertEqual(A_SHARE_MARKET_TZ.key, "Asia/Shanghai")
        result = resolve_canonical_asof(
            market_now, ["20260624", "20260625", "20260626", "20260629", "20260630"])
        self.assertEqual(result["as_of"], "20260629")
        self.assertEqual(
            resolve_canonical_asof(
                datetime(2026, 6, 26, 7, 30, tzinfo=timezone.utc),
                ["20260624", "20260625", "20260626", "20260629", "20260630"],
            )["as_of"],
            "20260629",
        )

    def test_naive_instant_is_rejected_at_market_clock_boundary(self):
        with self.assertRaises(ValueError):
            a_share_market_wall_time(datetime(2026, 6, 26, 15, 30))

    def test_business_date_callers_use_shared_market_clock(self):
        resolver = (ROOT / "runners" / "resolve_canonical_asof.py").read_text(encoding="utf-8")
        egs = (ROOT / "A-EGS" / "egs_main.py").read_text(encoding="utf-8")
        tracker = (ROOT / "runners" / "forward_tracker.py").read_text(encoding="utf-8")
        weekly = (ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")

        self.assertIn("a_share_market_wall_time()", resolver)
        self.assertIn("TODAY = a_share_market_date()", egs)
        self.assertIn("effective_run_date = run_date or a_share_market_date()", egs)
        self.assertIn("wall_date = a_share_market_date()", egs)
        self.assertIn("return a_share_market_date()", tracker)
        self.assertIn("China Standard Time", weekly)
        self.assertNotIn("$RunDate = Get-Date -Format 'yyyyMMdd'", weekly)


if __name__ == "__main__":
    unittest.main()
