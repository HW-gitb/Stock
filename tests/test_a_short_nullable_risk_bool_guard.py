"""Prevent nullable A-short risk facts from returning to truthiness-based gates."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pandas as pd

from engine.a_short_nullable_bool import fail_closed_risk_bool


ROOT = Path(__file__).resolve().parents[1]
RISK_NAMES = {
    "overheat",
    "overheat_flag",
    "chasing_high",
    "chase_flag",
    "high_pos_shrink",
    "is_suspended",
    "has_crash_veto",
    "hard_veto",
    "is_lock",
    "has_l4_overheat",
    "has_l4_lock",
}


def _unsafe_bool_calls(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    unsafe = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "bool"
            and node.args
        ):
            continue
        argument = ast.unparse(node.args[0])
        identifiers = {
            child.id for child in ast.walk(node.args[0])
            if isinstance(child, ast.Name)
        }
        string_literals = {
            child.value for child in ast.walk(node.args[0])
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        }
        if RISK_NAMES & (identifiers | string_literals):
            unsafe.append((node.lineno, argument))
    return unsafe


class AShortNullableRiskBoolGuardTest(unittest.TestCase):
    def test_fail_closed_parser_preserves_canonical_false_and_rejects_unknown(self) -> None:
        for value in (False, 0, 0.0, "false", "FALSE", "0"):
            with self.subTest(value=value):
                self.assertFalse(fail_closed_risk_bool(value))
        for value in (None, pd.NA, float("nan"), "", "unknown", 2):
            with self.subTest(value=value):
                self.assertTrue(fail_closed_risk_bool(value))

    def test_reverse_control_finds_truthiness_and_accepts_fail_closed_helper(self) -> None:
        bad = "def f(row):\n    return bool(row.get('overheat_flag'))\n"
        good = (
            "def f(row):\n"
            "    return fail_closed_risk_bool(row.get('overheat_flag'))\n"
        )
        self.assertEqual(len(_unsafe_bool_calls(bad)), 1)
        self.assertEqual(_unsafe_bool_calls(good), [])

    def test_a_short_production_surfaces_have_no_direct_nullable_risk_truthiness(self) -> None:
        paths = [
            ROOT / "A-EGS" / "egs_main.py",
            ROOT / "engine" / "egs_industry_heat.py",
            *sorted((ROOT / "engine").glob("a_short_*.py")),
            ROOT / "runners" / "backtest_rank.py",
            *sorted((ROOT / "runners").glob("a_short_*.py")),
        ]
        failures = []
        for path in paths:
            if path.name == "a_short_nullable_bool.py":
                continue
            for line, argument in _unsafe_bool_calls(path.read_text(encoding="utf-8")):
                failures.append(f"{path.relative_to(ROOT)}:{line}: bool({argument})")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
