"""Behavior tests proving the reviewed JSON policies drive A-short decisions."""
from __future__ import annotations

import copy
import ast
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_runtime_config import RuntimeConfigError, load_runtime_configuration  # noqa: E402
from engine import a_short_portfolio_risk as baseline_portfolio  # noqa: E402
from runners import a_short_phase5_engine as baseline_phase5  # noqa: E402
from runners import a_short_weekly_pipeline as baseline_weekly  # noqa: E402
from runners.a_short_m67_render import render_weekly_markdown  # noqa: E402
from tests.test_a_short_phase5_engine import AS_OF, _good_input  # noqa: E402
from tests.test_a_short_portfolio_risk import _facts, _normal  # noqa: E402
from tests.test_a_short_weekly_pipeline import GEN, _analysis_input, _feed, _normalized  # noqa: E402


def _load_with_policy(relative_path: str, configuration: dict):
    """Execute a fresh consumer module with an explicit in-memory test policy."""
    name = "_runtime_policy_test_" + Path(relative_path).stem + "_" + str(id(configuration))
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch("engine.a_short_runtime_config.load_runtime_configuration", return_value=configuration):
        spec.loader.exec_module(module)
    return module


def _load_egs_with_policy(configuration: dict):
    old_argv = sys.argv[:]
    sys.argv = [str(ROOT / "A-EGS" / "egs_main.py"), "--help"]
    try:
        return _load_with_policy("A-EGS/egs_main.py", configuration)
    finally:
        sys.argv = old_argv


def _constant_string_subscript_path(node: ast.AST) -> tuple[str, tuple[str, ...]] | None:
    """Return a literal subscript chain such as ``root[\"a\"][\"b\"]``."""
    parts: list[str] = []
    while isinstance(node, ast.Subscript):
        if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, str):
            return None
        parts.append(node.slice.value)
        node = node.value
    if isinstance(node, ast.Name):
        return node.id, tuple(reversed(parts))
    return None


def _runtime_policy_literal_reads(configuration: dict) -> list[tuple[str, int, tuple[str, ...]]]:
    """Find every production literal read rooted in ``_RUNTIME_CONFIGURATION``.

    This lane-local closure guard intentionally scans the production consumers instead
    of relying on a manually curated key list.  A deleted preset key therefore turns
    red even when a consumer was omitted from an ordinary repair grep.
    """
    reads: list[tuple[str, int, tuple[str, ...]]] = []
    for directory in ("A-EGS", "engine", "runners"):
        for path in sorted((ROOT / directory).glob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            aliases: dict[str, tuple[str, ...]] = {}
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if len(targets) != 1 or not isinstance(targets[0], ast.Name):
                    continue
                chain = _constant_string_subscript_path(node.value)
                if chain and chain[0] == "_RUNTIME_CONFIGURATION":
                    aliases[targets[0].id] = chain[1]
            for node in ast.walk(tree):
                if not isinstance(node, ast.Subscript):
                    continue
                chain = _constant_string_subscript_path(node)
                if not chain:
                    continue
                root, parts = chain
                if root == "_RUNTIME_CONFIGURATION":
                    full_path = parts
                elif root in aliases:
                    full_path = aliases[root] + parts
                else:
                    if (root == "CONF" and len(parts) == 1
                            and parts[0] in (configuration.get("screening") or {})):
                        reads.append((path.relative_to(ROOT).as_posix(), node.lineno,
                                      ("screening", parts[0])))
                    continue
                if full_path:
                    reads.append((path.relative_to(ROOT).as_posix(), node.lineno, full_path))
    return sorted(set(reads))


def _missing_runtime_policy_literal_reads(configuration: dict) -> list[str]:
    missing: list[str] = []
    for relative_path, line, policy_path in _runtime_policy_literal_reads(configuration):
        value = configuration
        for key in policy_path:
            if not isinstance(value, dict) or key not in value:
                missing.append(f"{relative_path}:{line}:{'.'.join(policy_path)}")
                break
            value = value[key]
    return missing


class RuntimeConfigurationBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.configuration = load_runtime_configuration()

    def _temporary_root(self, mutate=None):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        preset_dir = root / "presets"
        preset_dir.mkdir()
        screening_path = ROOT / "presets" / "a_short_screening_threshold_governance_20260602.json"
        m67_path = ROOT / "presets" / "a_short_m67_runtime_policy_20260715.json"
        screening = json.loads(screening_path.read_text(encoding="utf-8"))
        m67 = json.loads(m67_path.read_text(encoding="utf-8"))
        if mutate:
            mutate(screening, m67)
        (preset_dir / screening_path.name).write_text(
            json.dumps(screening, ensure_ascii=False), encoding="utf-8"
        )
        (preset_dir / m67_path.name).write_text(
            json.dumps(m67, ensure_ascii=False), encoding="utf-8"
        )
        (preset_dir / "a_short.yaml").write_text(
            "screening_threshold_governance:\n"
            "  schema_ref: schemas/a_short_screening_threshold_governance.schema.json\n"
            f"  artifact_ref: presets/{screening_path.name}\n"
            "  status: runtime_json_authority\n\n"
            "m67_runtime_policy:\n"
            "  schema_ref: schemas/a_short_m67_runtime_policy.schema.json\n"
            f"  artifact_ref: presets/{m67_path.name}\n"
            "  status: runtime_json_authority\n",
            encoding="utf-8",
        )
        return temp, root

    def test_iv_nobuild_json_change_changes_m67_action(self) -> None:
        baseline = baseline_phase5.build_m67_report(_good_input(), AS_OF, "t")
        changed = copy.deepcopy(self.configuration)
        changed["m67"]["phase5"]["iv_nobuild_pct"] = 50.0
        configured = _load_with_policy("runners/a_short_phase5_engine.py", changed)
        inp = _good_input()
        inp["iv"]["iv_percentile_252d"] = 55.0
        result = configured.build_m67_report(inp, AS_OF, "t")
        self.assertEqual(baseline["m67"]["table"]["操作"], "建仓")
        self.assertEqual(result["m67"]["table"]["操作"], "否决")

    def test_single_cap_json_change_changes_m67_share_count(self) -> None:
        baseline = baseline_phase5.build_m67_report(_good_input(), AS_OF, "t")
        changed = copy.deepcopy(self.configuration)
        changed["m67"]["phase5"]["single_cap_pct"]["震荡期"] = 0.1
        configured = _load_with_policy("runners/a_short_phase5_engine.py", changed)
        result = configured.build_m67_report(_good_input(), AS_OF, "t")
        self.assertEqual(result["m67"]["table"]["操作"], "建仓")
        self.assertLess(result["m67"]["table"]["股数"], baseline["m67"]["table"]["股数"])

    def test_portfolio_threshold_json_change_changes_concentration_action(self) -> None:
        held = _normal("000001.SZ", "bank", held_shares=20_000)
        candidate = _normal("600000.SH", "bank")
        facts = {"000001.SZ": _facts("000001.SZ", "bank"), "600000.SH": _facts("600000.SH", "bank")}
        baseline_context = baseline_portfolio.build_context([held, candidate], AS_OF, fact_overrides=facts)
        self.assertEqual(baseline_portfolio.evaluate_candidate(baseline_context, "600000.SH", 100_000)["action"], "replace")

        changed = copy.deepcopy(self.configuration)
        changed["m67"]["portfolio_risk"]["same_sw_l2_threshold_pct"] = 100.0
        configured = _load_with_policy("engine/a_short_portfolio_risk.py", changed)
        context = configured.build_context([held, candidate], AS_OF, fact_overrides=facts)
        self.assertEqual(configured.evaluate_candidate(context, "600000.SH", 100_000)["action"], "allow")

    def test_future_event_window_json_change_changes_weekly_event_inclusion(self) -> None:
        provider = lambda _code: [{"ann_date": AS_OF, "float_date": "20260619"}]
        baseline = baseline_weekly._upcoming_events([("600000.SH", "测试")], AS_OF, provider)
        self.assertEqual(len(baseline["events"]), 1)

        changed = copy.deepcopy(self.configuration)
        changed["m67"]["weekly_windows"]["forward_event_window_days"] = 5
        configured = _load_with_policy("runners/a_short_weekly_pipeline.py", changed)
        result = configured._upcoming_events([("600000.SH", "测试")], AS_OF, provider)
        self.assertEqual(result["events"], [])

    def test_ocf_policy_json_change_changes_score_l2(self) -> None:
        baseline = _load_egs_with_policy(self.configuration)
        changed_configuration = copy.deepcopy(self.configuration)
        changed_configuration["screening"]["ocf_quality_min_pct"] = 40.0
        changed = _load_egs_with_policy(changed_configuration)
        row = {
            "ts_code": "600000.SH", "l2_name": "test", "q0_dt_yoy": 10.0,
            "q1_dt_yoy": 10.0, "pe": 10.0, "pb": 1.0, "roe": 10.0,
            "q0_dt_profit_ratio": 100.0, "ttm_ocf_ratio": 50.0,
            "ttm_profit_dedt": None, "pct_20d_n": 0.0,
            "reduce_deduct": 0.0, "avg_amount_5d": 1.0, "avg_amount_20d": 1.0,
        }

        def flags(module):
            output = module.score_l2(
                pd.DataFrame([row]), pd.DataFrame(), [], {"test": 5.0},
                margin_observation=None,
            )
            return output.iloc[0]["l2_flags"]

        self.assertIn("ESP-Q", flags(baseline))
        self.assertNotIn("ESP-Q", flags(changed))

    def test_weekly_json_and_markdown_carry_and_validate_the_same_fingerprint(self) -> None:
        weekly = baseline_weekly.build_weekly_report([_normalized()], AS_OF, GEN)
        lineage = weekly["run_lineage"]["runtime_configuration"]
        self.assertEqual(lineage, self.configuration["lineage"])
        self.assertIn(lineage["configuration_fingerprint"], render_weekly_markdown(weekly))
        baseline_weekly.validate_weekly_report(weekly, _feed())

        weekly["run_lineage"]["runtime_configuration"]["configuration_fingerprint"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "runtime_configuration"):
            baseline_weekly.validate_weekly_report(weekly, _feed())

    def test_stale_analysis_input_configuration_stops_before_price_provider_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            analysis_input = _analysis_input()
            analysis_input["source"]["runtime_configuration"]["configuration_fingerprint"] = "0" * 64
            ai_path, feed_path, out_path = root / "analysis_input.json", root / "feed.json", root / "weekly.json"
            ai_path.write_text(json.dumps(analysis_input, ensure_ascii=False), encoding="utf-8")
            feed_path.write_text(json.dumps(_feed(), ensure_ascii=False), encoding="utf-8")
            calls: list[str] = []

            def price_provider(code: str):
                calls.append(code)
                raise AssertionError("stale configuration must stop before a price provider call")

            with self.assertRaisesRegex(SystemExit, "runtime configuration"):
                baseline_weekly.main([
                    "--as-of", AS_OF, "--analysis-input", str(ai_path),
                    "--iv-feed", str(feed_path), "--out", str(out_path),
                ], price_provider=price_provider)
            self.assertEqual(calls, [])
            self.assertFalse(out_path.exists())

    def test_every_runtime_policy_literal_read_resolves_in_the_preset(self) -> None:
        self.assertEqual(_missing_runtime_policy_literal_reads(self.configuration), [])

    def test_deleted_preset_key_turns_the_runtime_policy_read_guard_red(self) -> None:
        changed = copy.deepcopy(self.configuration)
        del changed["m67"]["portfolio_risk"]["margin_threshold_pct"]
        missing = _missing_runtime_policy_literal_reads(changed)
        self.assertTrue(any(item.endswith(":m67.portfolio_risk.margin_threshold_pct") for item in missing),
                        missing)

        temp, root = self._temporary_root(
            lambda screening, _m67: screening["thresholds"].pop("ocf_quality_min_pct")
        )
        with temp:
            with self.assertRaises(RuntimeConfigError):
                load_runtime_configuration(root=root)

    def test_ocf_policy_value_changes_runtime_configuration_fingerprint(self) -> None:
        temp, root = self._temporary_root(
            lambda screening, _m67: screening["thresholds"].__setitem__("ocf_quality_min_pct", 75.0)
        )
        with temp:
            changed = load_runtime_configuration(root=root)
        self.assertEqual(changed["screening"]["ocf_quality_min_pct"], 75.0)
        self.assertNotEqual(
            changed["lineage"]["configuration_fingerprint"],
            self.configuration["lineage"]["configuration_fingerprint"],
        )

    def test_historical_weekly_artifact_uses_legacy_contract_compat_but_new_builder_requires_fact_fetch(self) -> None:
        historic = json.loads((ROOT / "research" / "results" / "a_short" / "20260727" / "weekly_m67.json").read_text(encoding="utf-8"))
        from engine.a_short_effect_contract import load_legacy_effect_contract, validate_effect_contract_ledger
        fingerprint = (historic.get("effect_contract_ledger") or {}).get("contract_fingerprint")
        self.assertIsNotNone(load_legacy_effect_contract(fingerprint))
        validate_effect_contract_ledger(historic)
        self.assertNotIn("data_quality_shadow", historic)

        new_weekly = baseline_weekly.build_weekly_report([_normalized()], AS_OF, GEN)
        del new_weekly["portfolio_risk"]["fact_fetch"]
        with self.assertRaisesRegex(ValueError, "fact_fetch status/clock"):
            baseline_weekly.validate_weekly_report(new_weekly, _feed())


if __name__ == "__main__":
    unittest.main()

