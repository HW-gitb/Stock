"""Every registered A-short public JSON writer must reject NaN and Infinity."""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_WRITER_FUNCTIONS = {
    "engine/a_short_overlay_adjudication.py": "_write",
    "engine/a_short_industry_weight_comparison.py": "_atomic_write",
    "engine/a_short_factor_comparison.py": "_atomic_write",
    "engine/a_short_factor_comparison_v2.py": "_atomic_write",
    "runners/a_short_final_action_validation_runner.py": "_atomic_write",
    "runners/a_short_regime_comparison_runner.py": "_write_json",
    "runners/a_short_target_policy_comparison_runner.py": "_atomic_write",
}


def _json_writer_violations(source: str, expected_function: str) -> list[str]:
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == expected_function]
    if len(functions) != 1:
        return [f"missing-or-duplicate:{expected_function}"]
    violations = []
    for node in ast.walk(functions[0]):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "json" and node.func.attr in {"dump", "dumps"}):
            continue
        allow_nan = next((keyword.value for keyword in node.keywords if keyword.arg == "allow_nan"), None)
        if not (isinstance(allow_nan, ast.Constant) and allow_nan.value is False):
            violations.append(f"{expected_function}:{node.lineno}:allow_nan_false_required")
    return violations


class PublicJsonWriterNonfiniteGuardTests(unittest.TestCase):
    def test_repaired_writer_helpers_reject_nonfinite_payloads_without_writing_targets(self):
        from engine.a_short_factor_comparison import _atomic_write as write_factor
        from engine.a_short_factor_comparison_v2 import _atomic_write as write_factor_v2
        from engine.a_short_overlay_adjudication import _write as write_overlay
        with tempfile.TemporaryDirectory() as tmp:
            for name, writer in (("overlay", write_overlay), ("factor", write_factor), ("factor_v2", write_factor_v2)):
                target = Path(tmp) / f"{name}.json"
                with self.assertRaises(ValueError):
                    writer(target, {"value": float("nan")})
                self.assertFalse(target.exists())

    def test_registered_public_writers_reject_nonfinite_json(self):
        violations = []
        for relative, function in PUBLIC_WRITER_FUNCTIONS.items():
            violations.extend(f"{relative}:{item}" for item in _json_writer_violations(
                (ROOT / relative).read_text(encoding="utf-8"), function))
        self.assertEqual(violations, [])

    def test_guard_rejects_a_writer_missing_allow_nan_false(self):
        source = "import json\ndef _write(value):\n    return json.dumps(value, ensure_ascii=False, indent=2)\n"
        self.assertEqual(_json_writer_violations(source, "_write"), ["_write:3:allow_nan_false_required"])
