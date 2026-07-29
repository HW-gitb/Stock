"""Every registered A-short JSON file writer must reject NaN and Infinity."""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
WRITER_ROOTS = (ROOT / "engine", ROOT / "runners")

# This registry is intentionally a reviewable policy surface, not the discovery
# mechanism.  The AST traversal below makes an unregistered JSON file writer fail
# the test as soon as it is added anywhere in an A-short module.
PUBLIC_WRITER_FUNCTIONS = frozenset({
    "engine/a_short_factor_comparison.py:_atomic_write",
    "engine/a_short_factor_comparison_v2.py:_atomic_write",
    "engine/a_short_industry_weight_comparison.py:_atomic_write",
    "engine/a_short_overlay_adjudication.py:_write",
    "runners/a_short_final_action_validation_runner.py:_atomic_write",
    "runners/a_short_account_state_from_manual_tables.py:_write_json_atomic",
    "runners/a_short_crash_veto_tracker.py:_atomic_json",
    "runners/a_short_d4_policy_ablation.py:_atomic_write_json",
    "runners/a_short_em_news_probe.py:write_em_probe_summary",
    "runners/a_short_entry_funnel_calibration.py:write_report",
    "runners/a_short_factor_comparison_v2_cache_build.py:_atomic_write",
    "runners/a_short_iv_feed_build.py:write_feed",
    "runners/a_short_iv_feed_probe.py:write_fetch_failure_summary",
    "runners/a_short_iv_feed_probe.py:write_probe_summary",
    "runners/a_short_official_operation_evidence.py:_atomic_write",
    "runners/a_short_phase5_engine.py:write_m67_report",
    "runners/a_short_regime_comparison_runner.py:_write_json",
    "runners/a_short_rule6_report_rc_coverage_audit.py:_write_json",
    "runners/a_short_rule6_tushare_d_tier_probe.py:_write_json",
    "runners/a_short_rule6_yfinance_probe.py:_write_json",
    "runners/a_short_semantic_risk_probe.py:write_probe_summary",
    "runners/a_short_steady_alpha_reaudit.py:update_ledger",
    "runners/a_short_steady_alpha_reaudit.py:write_outputs",
    "runners/a_short_target_policy_comparison_runner.py:_atomic_write",
    "runners/a_short_theme_forward_comparison.py:_write_json_atomic",
    "runners/a_short_theme_forward_comparison.py:_write_json_exclusive",
    "runners/a_short_theme_overlay_comparison.py:write_overlay_summary",
    "runners/a_short_weekly_pipeline.py:_write_pipeline_sidecar_outcomes",
    "runners/a_short_weekly_pipeline.py:publish_weekly_bundle",
    "runners/a_short_weekly_pipeline.py:save_holding_ratchet",
    "runners/a_short_weekly_pipeline.py:write_weekly_report",
    "runners/a_short_weekly_sidecar_health.py:write_health_bundle",
})


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _is_json_serializer(node: ast.Call) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
        and node.func.attr in {"dump", "dumps"}
    )


def _has_literal_allow_nan_false(node: ast.Call) -> bool:
    return any(
        keyword.arg == "allow_nan"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is False
        for keyword in node.keywords
    )


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _has_ancestor_file_write(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Any enclosing ``*write*`` call counts, not just ``write`` / ``write_text``.

    Matching the exact two names let a serializer handed straight to a local
    helper escape discovery — ``_atomic_write_text(json.dumps(...), path)``, the
    form `runners/a_short_regime_comparison_runner.py::_write_json` is written in
    (the one real in-repo function whose classification this widening changes).
    A planted inline ``path.write_bytes(json.dumps(...).encode())`` escaped too;
    no A-short module uses that form today.  Substring matching covers both
    without pulling in the digest helpers, whose names contain no ``write``.
    """
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.Call) and "write" in (_call_name(current) or ""):
            return True
    return False


def _is_bundle_payload(serializer: ast.Call, function: ast.FunctionDef, parents: dict[ast.AST, ast.AST]) -> bool:
    """Recognise encoded JSON staged for an atomic multi-file replacement."""
    current: ast.AST = serializer
    in_mapping = False
    while current in parents:
        current = parents[current]
        in_mapping = in_mapping or isinstance(current, ast.Dict)
    return in_mapping and any(
        isinstance(node, ast.Call) and _call_name(node) == "_replace_many_with_rollback"
        for node in ast.walk(function)
    )


def _names_in(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _serializer_flows_to_named_write(
    serializer: ast.Call,
    serialized_names: set[str],
    parents: dict[ast.AST, ast.AST],
) -> bool:
    current: ast.AST = serializer
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.Assign):
            return any(isinstance(target, ast.Name) and target.id in serialized_names for target in current.targets)
    return False


def _function_json_file_writers(source: str) -> dict[str, list[ast.Call]]:
    """Derive every function that sends a ``json.dump(s)`` result to a file."""
    tree = ast.parse(source)
    parents = _parents(tree)
    writers: dict[str, list[ast.Call]] = {}
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        serialized_names: set[str] = set()
        assignments = [node for node in ast.walk(function) if isinstance(node, ast.Assign)]
        while True:
            derived_names = {
                target.id
                for node in assignments
                if any(_is_json_serializer(child) for child in ast.walk(node.value))
                or bool(_names_in(node.value) & serialized_names)
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if derived_names <= serialized_names:
                break
            serialized_names.update(derived_names)
        writes_serialized_name = any(
            isinstance(node, ast.Call)
            and "write" in (_call_name(node) or "")
            and bool(_names_in(node) & serialized_names)
            for node in ast.walk(function)
        )
        serializations = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and _is_json_serializer(node)
            and (
                node.func.attr == "dump"
                or _has_ancestor_file_write(node, parents)
                or _is_bundle_payload(node, function, parents)
                or (writes_serialized_name and _serializer_flows_to_named_write(node, serialized_names, parents))
            )
        ]
        if serializations:
            writers[function.name] = serializations
    return writers


def _discovered_writer_calls() -> dict[str, list[ast.Call]]:
    discovered: dict[str, list[ast.Call]] = {}
    for writer_root in WRITER_ROOTS:
        for path in sorted(writer_root.glob("a_short_*.py")):
            relative = path.relative_to(ROOT).as_posix()
            for function, calls in _function_json_file_writers(path.read_text(encoding="utf-8")).items():
                discovered[f"{relative}:{function}"] = calls
    return discovered


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

    def test_every_json_file_writer_is_registered_and_finite_only(self):
        discovered = _discovered_writer_calls()
        self.assertSetEqual(set(discovered) - PUBLIC_WRITER_FUNCTIONS, set())
        violations = [
            f"{writer}:{call.lineno}:allow_nan_false_required"
            for writer, calls in discovered.items()
            for call in calls
            if not _has_literal_allow_nan_false(call)
        ]
        self.assertEqual(violations, [])

    def test_registered_writers_keep_literal_finite_only_serializers(self):
        violations = []
        for qualified_name in PUBLIC_WRITER_FUNCTIONS:
            relative, function_name = qualified_name.rsplit(":", 1)
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            functions = [
                node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == function_name
            ]
            if len(functions) != 1:
                violations.append(f"{qualified_name}:missing-or-duplicate")
                continue
            for node in ast.walk(functions[0]):
                if isinstance(node, ast.Call) and _is_json_serializer(node) and not _has_literal_allow_nan_false(node):
                    violations.append(f"{qualified_name}:{node.lineno}:allow_nan_false_required")
        self.assertEqual(violations, [])

    def test_guard_rejects_an_unregistered_json_file_writer(self):
        source = (
            "import json\n\n"
            "def write_new_output(path, value):\n"
            "    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')\n"
        )
        injected = set(_function_json_file_writers(source))
        self.assertEqual(injected, {"write_new_output"})
        self.assertSetEqual(injected - PUBLIC_WRITER_FUNCTIONS, {"write_new_output"})

    def test_guard_discovers_write_bytes_and_local_write_helper_forms(self):
        """Both forms escaped the earlier exact-name match; neither may escape now."""
        inline_bytes = (
            "import json\n\n"
            "def dump_bytes(path, value):\n"
            "    path.write_bytes(json.dumps(value).encode('utf-8'))\n"
        )
        local_helper = (
            "import json\n\n"
            "def dump_via_helper(path, value):\n"
            "    _atomic_write_text(json.dumps(value) + '\\n', path)\n"
        )
        two_line_helper = (
            "import json\n\n"
            "def dump_via_named_helper(path, value):\n"
            "    payload = json.dumps(value)\n"
            "    _atomic_write_text(payload, path)\n"
        )
        for source, name in ((inline_bytes, "dump_bytes"), (local_helper, "dump_via_helper"),
                             (two_line_helper, "dump_via_named_helper")):
            with self.subTest(form=name):
                discovered = _function_json_file_writers(source)
                self.assertEqual(set(discovered), {name})
                self.assertFalse(_has_literal_allow_nan_false(discovered[name][0]))

    def test_guard_does_not_treat_a_digest_helper_as_a_file_writer(self):
        """Substring matching must not drag hash/digest serializers into the registry."""
        source = (
            "import hashlib\nimport json\n\n"
            "def _digest(value):\n"
            "    return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()\n"
        )
        self.assertEqual(_function_json_file_writers(source), {})

    def test_reviewer_named_weekly_and_ledger_writers_reject_nonfinite_without_publishing(self):
        import runners.a_short_steady_alpha_reaudit as reaudit
        import runners.a_short_weekly_pipeline as weekly_pipeline

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_target = root / "weekly.json"
            with (
                mock.patch.object(weekly_pipeline.jsonschema, "validate"),
                mock.patch.object(weekly_pipeline, "validate_weekly_report"),
            ):
                with self.assertRaises(ValueError):
                    weekly_pipeline.write_weekly_report({"reports": [], "value": float("nan")}, {}, str(weekly_target))
            self.assertFalse(weekly_target.exists())
            self.assertFalse(Path(str(weekly_target) + ".tmp").exists())

            sidecar_target = root / "sidecar.json"
            with mock.patch.object(weekly_pipeline.jsonschema, "validate"):
                with self.assertRaises(ValueError):
                    weekly_pipeline._write_pipeline_sidecar_outcomes(
                        sidecar_target, as_of="20260729", run_id=None, candidate_digest=None,
                        expected=[], outcomes=[{"value": float("nan")}],
                    )
            self.assertFalse(sidecar_target.exists())
            self.assertFalse((root / ".sidecar.json.tmp").exists())

            ratchet_target = root / "ratchet.json"
            with mock.patch.object(weekly_pipeline, "_holding_ratchet_doc", return_value={"value": float("nan")}):
                with self.assertRaises(ValueError):
                    weekly_pipeline.save_holding_ratchet(ratchet_target, {}, "20260729", "2026-07-29T00:00:00Z")
            self.assertFalse(ratchet_target.exists())
            self.assertFalse(Path(str(ratchet_target) + ".tmp").exists())

            ledger_path = root / "ledger.json"
            original = '{"budget_policy": {}, "test_spend_log": [], "planned_tests": [], "nan": NaN}'
            ledger_path.write_text(original, encoding="utf-8")
            with mock.patch.object(reaudit, "validate_json"):
                with self.assertRaises(ValueError):
                    reaudit.update_ledger(ledger_path, root / "result.json", "summary", "not_passed")
            self.assertEqual(ledger_path.read_text(encoding="utf-8"), original)
