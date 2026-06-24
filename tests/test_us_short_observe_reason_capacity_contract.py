# -*- coding: utf-8 -*-
"""US-short observe_reason_type capacity/budget closure guard (batch4).

After `capacity_or_budget_deferred` was added to the frozen observe_reason_type vocab, this guard pins
that (1) the frozen enum carries the new value, and (2) active US-short route / docstring / design
surfaces no longer hardcode the obsolete "7 observe_reason" count (they delegate to the frozen set or
state the current count) — preventing the enum-ripple / class-not-instance drift Codex flagged.
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_CONTRACT = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
# Active surfaces that previously taught the "7 observe_reason_type" contract (must not regress).
_ACTIVE_SURFACES = (
    "docs/README.md",
    "docs/us_short_system_design.md",
    "engine/us_short_observe_split.py",
    "engine/us_short_weekend_decision.py",
)
# obsolete claims: "7 observe_reason", "7 个 observe_reason", "the 7 observe_reason", "frozen 7 ... observe_reason"
_STALE = re.compile(r"7\s*(个\s*)?observe_reason|the\s+7\s+observe_reason|frozen\s+7\b")


class ObserveReasonCapacityContract(unittest.TestCase):
    def test_frozen_enum_includes_capacity_or_budget_deferred(self):
        enum = json.loads(_CONTRACT.read_text(encoding="utf-8"))["design_locked_enums"]["observe_reason_type"]
        self.assertIn("capacity_or_budget_deferred", enum)
        self.assertEqual(len(enum), len(set(enum)), "duplicate observe_reason_type value")

    def test_no_active_surface_claims_seven_observe_reasons(self):
        for rel in _ACTIVE_SURFACES:
            text = (ROOT / rel).read_text(encoding="utf-8")
            m = _STALE.search(text)
            self.assertIsNone(m, f"{rel} still hardcodes an obsolete observe_reason count: {m.group(0) if m else ''!r}")

    def test_sizing_below_min_reason_split_co_described(self):
        # Stale-reason guard: wherever the §8 sizing below-min / cap-zero observe reason is described, the
        # cap-0 → capacity_or_budget_deferred split must be co-present — so a regression back to the old
        # "cap-0 → cost_inefficient_min_size only" wording (the same class as the 7→8 count drift) is caught.
        # (a) the sizing engine + its test: if cost_inefficient_min_size is named, capacity must be too.
        for rel in ("engine/us_short_weekend_sizing.py", "tests/test_us_short_weekend_sizing.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            if "cost_inefficient_min_size" in text:
                self.assertIn("capacity_or_budget_deferred", text,
                              f"{rel} describes the sizing below-min reason without the cap-0 capacity split")
        # (b) README / CURRENT route rows citing the sizing slice: a line that names the sizing module and
        # cost_inefficient_min_size must also name capacity_or_budget_deferred.
        for rel in ("docs/README.md", "docs/CURRENT.md"):
            for line in (ROOT / rel).read_text(encoding="utf-8").splitlines():
                if "us_short_weekend_sizing" in line and "cost_inefficient_min_size" in line:
                    self.assertIn("capacity_or_budget_deferred", line,
                                  f"{rel} sizing route row is still cost-only for the cap-0 case")


if __name__ == "__main__":
    unittest.main()
