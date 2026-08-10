"""Regression tests for the structured #08 northbound market gate."""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jsonschema

import engine.a_short_northbound as northbound
from runners.a_short_weekly_pipeline import build_weekly_report
import runners.a_short_weekly_pipeline as weekly_pipeline
from runners.a_short_m67_render import render_weekly_markdown
from tests.test_a_short_weekly_pipeline import (
    AS_OF,
    GEN,
    _feed,
    _normalized,
    build_weekly_report as test_build_weekly_report,
)


def _control(*, flow, status, csi300, requested=5, observed=5,
             coverage_complete=True, production_effect_enabled=True,
             source_as_of=AS_OF, csi300_end_date=None):
    csi300_end_date = csi300_end_date or source_as_of
    return {
        "source_as_of": source_as_of,
        "source_paths": {
            "northbound": "analysis_input.market_context.northbound",
            "csi300": "analysis_input.market_context.breadth.csi300_pct_change_window",
        },
        "net_flow_5d": flow,
        "status": status,
        "csi300_pct_change_window": csi300,
        "csi300_window": {
            "start_date": "20260501",
            "end_date": csi300_end_date,
            "length": 20,
            "length_unit": "trading_sessions",
        },
        "requested_session_count": requested,
        "observed_session_count": observed,
        "coverage_complete": coverage_complete,
        "production_effect_enabled": production_effect_enabled,
    }


ROOT = Path(__file__).resolve().parents[1]


class NorthboundMarketGateTests(unittest.TestCase):
    def _build(self, rows=None, **control):
        return test_build_weekly_report(
            rows or [_normalized()],
            AS_OF,
            GEN,
            northbound_control=_control(**control),
        )

    def test_dual_condition_demotes_every_new_entry_and_lands_structured_impact(self):
        weekly = self._build(
            rows=[_normalized("600000.SH"), _normalized("000001.SZ")],
            flow=-123.0,
            status="outflow",
            csi300=-12.0,
        )

        self.assertTrue(weekly["northbound_control"]["new_entry_blocked"])
        self.assertEqual(weekly["northbound_control"]["reason"], "dual_condition")
        for report in weekly["reports"]:
            self.assertEqual(report["m67"]["table"]["操作"], "观察")
            self.assertIsNone(report["m67"]["table"]["股数"])
            impacts = [
                item for item in report["machine"]["operation_impact"]
                if item["source_field"] == "northbound_market_silence_gate"
            ]
            self.assertEqual(len(impacts), 1)
            self.assertEqual(impacts[0]["new_entry_effect"], "observe_required")
            self.assertEqual(impacts[0]["holding_effect"], "none")
            self.assertFalse(impacts[0]["blocked_add_required"])
            self.assertTrue(impacts[0]["production_effect_enabled"])
            self.assertEqual(impacts[0]["evidence_ref"]["value"],
                             "analysis_input.market_context.northbound")

    def test_production_effect_disabled_records_predicate_without_demoting(self):
        weekly = test_build_weekly_report(
            [_normalized()], AS_OF, GEN,
            northbound_control=_control(
                flow=-123.0, status="outflow", csi300=-12.0,
                production_effect_enabled=False,
            ),
        )
        self.assertTrue(weekly["northbound_control"]["predicate_triggered"])
        self.assertFalse(weekly["northbound_control"]["new_entry_blocked"])
        self.assertEqual(weekly["northbound_control"]["reason"], "production_effect_disabled")
        self.assertEqual(weekly["reports"][0]["m67"]["table"]["操作"], "建仓")
        self.assertIn("仅记录未生效", render_weekly_markdown(weekly))

    def test_analysis_default_uses_shared_production_switch(self):
        analysis_input = {
            "decision_as_of": AS_OF,
            "market_context": {
                "northbound": {
                    "net_flow_5d": -123.0,
                    "status": "outflow",
                    "requested_session_count": 5,
                    "observed_session_count": 5,
                    "coverage_complete": True,
                },
                "breadth": {
                    "csi300_pct_change_window": -12.0,
                    "csi300_window": {
                        "start_date": "20260501",
                        "end_date": AS_OF,
                        "length": 20,
                        "length_unit": "trading_sessions",
                    },
                },
            },
        }
        control = weekly_pipeline._northbound_control_from_analysis(analysis_input, AS_OF)
        self.assertEqual(
            control["production_effect_enabled"],
            northbound.NORTHBOUND_MARKET_GATE_PRODUCTION_EFFECT_ENABLED,
        )
        self.assertTrue(control["production_effect_enabled"])
        self.assertTrue(control["new_entry_blocked"])

    def test_analysis_binds_northbound_and_csi300_to_price_data_through(self):
        analysis_input = {
            "decision_as_of": AS_OF,
            "price_data_through": "20260608",
            "market_context": {
                "northbound": {
                    "net_flow_5d": -123.0,
                    "status": "outflow",
                    "requested_session_count": 5,
                    "observed_session_count": 5,
                    "coverage_complete": True,
                },
                "breadth": {
                    "csi300_pct_change_window": -12.0,
                    "csi300_window": {
                        "start_date": "20260501",
                        "end_date": "20260608",
                        "length": 20,
                        "length_unit": "trading_sessions",
                    },
                },
            },
        }
        control = weekly_pipeline._northbound_control_from_analysis(
            analysis_input, AS_OF
        )
        self.assertEqual(control["source_as_of"], "20260608")
        self.assertEqual(control["csi300_window"]["end_date"], "20260608")
        analysis_input["market_context"]["breadth"]["csi300_window"]["end_date"] = AS_OF
        with self.assertRaisesRegex(ValueError, "end_date is not bound"):
            weekly_pipeline._northbound_control_from_analysis(
                analysis_input, AS_OF
            )

    def test_single_condition_does_not_block(self):
        cases = (
            {"flow": -1.0, "status": "outflow", "csi300": -9.0},
            {"flow": 1.0, "status": "inflow", "csi300": -12.0},
            {"flow": 0.0, "status": "flat", "csi300": -12.0},
        )
        for case in cases:
            with self.subTest(case=case):
                weekly = self._build(**case)
                self.assertFalse(weekly["northbound_control"]["new_entry_blocked"])
                self.assertEqual(weekly["reports"][0]["m67"]["table"]["操作"], "建仓")
                self.assertNotIn(
                    "northbound_market_silence_gate",
                    {item["source_field"] for item in weekly["reports"][0]["machine"].get("operation_impact") or []},
                )

    def test_missing_data_is_unknown_or_unavailable_and_does_not_block(self):
        cases = (
            {"flow": None, "status": "unknown", "csi300": -12.0},
            {"flow": -1.0, "status": "outflow", "csi300": None},
        )
        for case in cases:
            with self.subTest(case=case):
                weekly = self._build(**case)
                control = weekly["northbound_control"]
                self.assertFalse(control["new_entry_blocked"])
                self.assertEqual(weekly["reports"][0]["m67"]["table"]["操作"], "建仓")

    def test_existing_holding_is_not_changed_by_new_entry_gate(self):
        row = _normalized()
        row["stateful_risk"] = {
            "position_state": "held",
            "position": {
                "ts_code": row["ts_code"],
                "shares": 1000,
                "avg_cost": 2.70,
                "entry_date": "20260601",
                "stop_loss": 2.55,
            },
        }
        weekly = self._build(rows=[row], flow=-1.0, status="outflow", csi300=-12.0)
        report = weekly["reports"][0]
        self.assertEqual(report["m67"]["table"]["操作"], "持有")
        self.assertEqual(
            report,
            self._build(
                rows=[row], flow=-1.0, status="outflow", csi300=-12.0,
            )["reports"][0],
        )
        self.assertNotIn(
            "northbound_market_silence_gate",
            {item["source_field"] for item in report["machine"].get("operation_impact") or []},
        )

    def test_incomplete_window_is_unknown_and_does_not_block(self):
        weekly = test_build_weekly_report(
            [_normalized()], AS_OF, GEN,
            northbound_control=_control(
                flow=None, status="unknown", csi300=-12.0,
                observed=1, coverage_complete=False,
            ),
        )
        self.assertFalse(weekly["northbound_control"]["predicate_triggered"])
        self.assertFalse(weekly["northbound_control"]["new_entry_blocked"])
        self.assertEqual(weekly["reports"][0]["m67"]["table"]["操作"], "建仓")

    def test_disabling_gate_makes_positive_control_red(self):
        rows = [_normalized()]
        with patch.object(weekly_pipeline, "_apply_northbound_market_gate", return_value=None):
            weekly = self._build(rows=rows, flow=-1.0, status="outflow", csi300=-12.0)
        self.assertEqual(weekly["reports"][0]["m67"]["table"]["操作"], "建仓")

    def test_weekly_validator_accepts_landed_control(self):
        weekly = self._build(flow=-1.0, status="outflow", csi300=-12.0)
        from runners.a_short_weekly_pipeline import validate_weekly_report

        expected = _control(flow=-1.0, status="outflow", csi300=-12.0)
        validate_weekly_report(weekly, _feed(), expected_northbound_control=expected)
        weekly["northbound_control"] = self._build(
            flow=1.0, status="inflow", csi300=-12.0,
        )["northbound_control"]
        with self.assertRaisesRegex(ValueError, "analysis_input 北向事实"):
            validate_weekly_report(weekly, _feed(), expected_northbound_control=expected)

    def test_market_banner_is_visible_when_gate_removes_all_builds(self):
        weekly = self._build(
            rows=[_normalized("600000.SH"), _normalized("000001.SZ")],
            flow=-123.0,
            status="outflow",
            csi300=-12.0,
        )
        markdown = render_weekly_markdown(weekly)
        self.assertIn("北向资金联合静默门已触发", markdown)
        self.assertIn("没有可被该门降级的新建仓候选", markdown)

    def test_lookback_summary_is_provider_bound_counts_only_and_never_production(self):
        schema = json.loads((ROOT / "schemas" / "a_short_northbound_market_silence_lookback_summary.schema.json").read_text(encoding="utf-8"))
        summary = json.loads((ROOT / "research" / "results" / "a_short" / "northbound_market_silence_lookback_summary.json").read_text(encoding="utf-8"))
        jsonschema.validate(summary, schema)
        self.assertIn(summary["status"], {"COMPLETE", "PARTIAL", "NOT_VERIFIED"})
        self.assertEqual(summary["lookback_week_count"], len(summary["weeks_considered"]))
        self.assertEqual(summary["lookback_week_count"], len(summary["weeks"]))
        self.assertEqual(
            summary["eligible_week_count"] + summary["unavailable_week_count"],
            summary["lookback_week_count"],
        )
        if summary["status"] == "NOT_VERIFIED":
            self.assertIsNone(summary["trigger_count"])
        else:
            self.assertIsInstance(summary["trigger_count"], int)
        self.assertEqual(summary["source_binding"]["predicate"], "engine.a_short_northbound.should_block_new_entries")
        self.assertTrue(summary["comparison_only"])
        self.assertFalse(summary["production_effect_enabled"])
        self.assertTrue(summary["storage"]["raw_payload_root_gitignored"])
        self.assertFalse(summary["storage"]["tracked_summary_contains_raw_rows"])
        self.assertFalse(summary["storage"]["tracked_summary_contains_request_urls"])
        self.assertFalse(summary["storage"]["tracked_summary_contains_secret"])


if __name__ == "__main__":
    unittest.main()


class GateStateTriangleTests(unittest.TestCase):
    """The schema const and the engine constant must be flipped together.

    The schema const-pins the gate's active state, which is what stops it being
    switched off silently.  The cost is that the kill path is two files: flipping
    only the constant leaves every weekly report failing schema validation with
    no hint why.  This assertion turns that mystery red into an instruction.
    """

    def test_schema_const_matches_the_engine_switch(self):
        from engine.a_short_northbound import NORTHBOUND_MARKET_GATE_PRODUCTION_EFFECT_ENABLED as live

        schema = json.loads(
            (ROOT / "schemas" / "analysis_input.schema.json").read_text(encoding="utf-8")
        )

        def _find(node):
            if isinstance(node, dict):
                props = node.get("properties") or {}
                nb = props.get("northbound")
                if isinstance(nb, dict) and "net_flow_5d" in (nb.get("properties") or {}):
                    return (nb["properties"].get("production_effect_enabled") or {})
                for value in node.values():
                    found = _find(value)
                    if found is not None:
                        return found
            elif isinstance(node, list):
                for value in node:
                    found = _find(value)
                    if found is not None:
                        return found
            return None

        pinned = _find(schema)
        self.assertIsNotNone(pinned, "analysis_input schema lost the northbound switch pin")
        self.assertIn("const", pinned, "the switch must stay const-pinned in the schema")
        self.assertEqual(
            pinned["const"], live,
            "engine/a_short_northbound.py and schemas/analysis_input.schema.json disagree about "
            "the gate state -- the kill path is BOTH files, flip them together",
        )
