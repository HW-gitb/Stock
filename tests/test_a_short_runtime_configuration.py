"""Behavior tests proving the reviewed JSON policies drive A-short decisions."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_runtime_config import load_runtime_configuration  # noqa: E402
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


class RuntimeConfigurationBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.configuration = load_runtime_configuration()

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


if __name__ == "__main__":
    unittest.main()

