from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_NAMES = [
    "us_short_market_diagnostic_26w_policy.schema.json",
    "us_short_market_diagnostic_weekly_record.schema.json",
    "us_short_market_diagnostic_summary.schema.json",
]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _design_contract() -> dict:
    text = (ROOT / "docs" / "us_short_market_diagnostic_26w_design.md").read_text(encoding="utf-8")
    match = re.search(
        r"```json\s*(\{\s*\"v1_summary_strategy_metric_fields\".*?\})\s*```",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("machine-bound v1 summary contract is missing from the design")
    return json.loads(match.group(1))


def _boundary() -> dict:
    return {
        "diagnostic_only": True,
        "comparison_only": True,
        "counts_ship_gate": False,
        "changes_selection_or_action": False,
        "automatic_policy_switch": False,
        "broker_or_order_automation": False,
    }


def _benchmark() -> dict:
    return {
        "return_quality": "price_return_diagnostic",
        "benchmark_evaluable": True,
        "joint_evaluable": True,
        "weekly_return": 0.01,
        "cumulative_return": 0.01,
        "raw_excess": 0.0,
        "relative_wealth": 0.0,
        "price_packet_sha256": "a" * 64,
        "dividend_sidecar_sha256": None,
        "data_quality_reasons": ["dividend_sidecar_not_complete"],
    }


def _weekly() -> dict:
    return {
        "schema_name": "us_short_market_diagnostic_weekly_record",
        "schema_version": "1.0.0",
        "decision_date": "20260804",
        "valuation_date": "20260803",
        "calendar_week_index": 1,
        "window_id": "26w-1-26",
        "diagnostic_epoch": "us_short_market_diagnostic_26w_v1",
        "diagnostic_policy_sha256": "b" * 64,
        "strategy_ruleset_fingerprint": "c" * 64,
        "strategy": {
            "paper_evaluable": True,
            "performance_status": "evaluable",
            "strategy_evaluable": True,
            "initial_capital": "100000.000000",
            "prior_nav": None,
            "nav": "101000.000000",
            "weekly_return": 0.01,
            "cumulative_return": 0.01,
            "cash": "50000.000000",
            "market_value": "51000.000000",
            "cumulative_cost_paid": "10.000000",
            "no_count": False,
            "no_count_reason": None,
            "source_sha256": "d" * 64,
            "degradation_reasons": [],
        },
        "benchmarks": {symbol: _benchmark() for symbol in ("VTI", "IWB", "SPY", "QQQ")},
        "v1_1_reminder": {
            "status": "pending",
            "evaluable_week_count": 1,
            "text": "v1.1 reminder is pending.",
        },
        "source_refs": ["e" * 64],
        "boundary": _boundary(),
    }


def _summary() -> dict:
    benchmark = {
        "role": "ship_gate_economic_continuity",
        "cumulative_return": 0.01,
        "relative_wealth": 0.0,
        "raw_excess": 0.0,
        "information_ratio": 0.0,
        "hac_t": 0.0,
        "joint_evaluable_weeks": 1,
        "total_return_evaluable_weeks": 0,
        "price_only_weeks": 1,
        "unavailable_weeks": 0,
        "max_drawdown": 0.0,
        "data_coverage": 0.5,
        "status": "data_degraded",
    }
    return {
        "schema_name": "us_short_market_diagnostic_summary",
        "schema_version": "1.0.0",
        "window_id": "26w-1-26",
        "diagnostic_epoch": "us_short_market_diagnostic_26w_v1",
        "window_start_week": 1,
        "window_end_week": 26,
        "calendar_weeks": 26,
        "mixed_ruleset_window": False,
        "strategy": {
            "status": "evaluable",
            "final_nav": "101000.000000",
            "cumulative_return": 0.01,
            "since_inception_return": 0.01,
            "strategy_evaluable_weeks": 1,
            "no_count_weeks": 0,
            "paper_degraded_weeks": 0,
            "max_drawdown": 0.0,
            "cumulative_cost_paid": "10.000000",
            "cash_ratio": 0.5,
            "equity_ratio": 0.5,
            "turnover": 0.1,
            "unfilled_order_count": 0,
            "data_coverage": 1.0,
        },
        "benchmarks": {
            "VTI": benchmark,
            "IWB": dict(benchmark, role="russell_1000_investable_proxy"),
            "SPY": dict(benchmark, role="broad_large_cap_sensitivity"),
            "QQQ": dict(benchmark, role="growth_technology_sensitivity"),
        },
        "overall_status": "data_degraded",
        "status_reason": "benchmark dividends are not complete",
        "ruleset_fingerprints": ["c" * 64],
        "v1_1_reminder": {
            "status": "pending",
            "evaluable_week_count": 1,
            "text": "v1.1 reminder is pending.",
        },
        "source_week_record_sha256": ["e" * 64],
        "boundary": _boundary(),
    }


class UsShortMarketDiagnosticSchemaTest(unittest.TestCase):
    def test_all_schemas_are_valid_draft7_and_closed_world_at_root(self) -> None:
        for name in SCHEMA_NAMES:
            with self.subTest(schema=name):
                schema = _schema(name)
                Draft7Validator.check_schema(schema)
                self.assertFalse(schema["additionalProperties"])

    def test_policy_and_runtime_contract_examples_validate(self) -> None:
        policy = json.loads(
            (ROOT / "presets" / "us_short_market_diagnostic_26w_policy_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual([], list(Draft7Validator(_schema(SCHEMA_NAMES[0])).iter_errors(policy)))
        self.assertEqual([], list(Draft7Validator(_schema(SCHEMA_NAMES[1])).iter_errors(_weekly())))
        self.assertEqual([], list(Draft7Validator(_schema(SCHEMA_NAMES[2])).iter_errors(_summary())))

    def test_design_metrics_statuses_and_priority_are_bound_to_schema(self) -> None:
        policy = json.loads(
            (ROOT / "presets" / "us_short_market_diagnostic_26w_policy_v1.json").read_text(
                encoding="utf-8"
            )
        )
        summary_schema = _schema(SCHEMA_NAMES[2])
        strategy_summary = summary_schema["definitions"]["strategy_summary"]
        benchmark_summary = summary_schema["definitions"]["benchmark_summary"]
        contract = _design_contract()

        for field in contract["v1_summary_strategy_metric_fields"]:
            self.assertIn(field, strategy_summary["properties"])
            self.assertIn(field, strategy_summary["required"])
        for field in contract["v1_summary_benchmark_metric_fields"]:
            self.assertIn(field, benchmark_summary["properties"])
            self.assertIn(field, benchmark_summary["required"])

        expected_statuses = policy["strategy_quality"]["allowed_statuses"]
        weekly_statuses = _schema(SCHEMA_NAMES[1])["definitions"]["strategy"]["properties"][
            "performance_status"
        ]["enum"]
        summary_statuses = strategy_summary["properties"]["status"]["enum"]
        self.assertEqual(expected_statuses, weekly_statuses)
        self.assertEqual(expected_statuses, summary_statuses)
        self.assertEqual(policy["status_resolution"]["priority"], contract["status_priority"])
        self.assertIn("mixed_ruleset_window", summary_schema["required"])

    def test_policy_priority_and_summary_window_flag_are_fail_closed(self) -> None:
        policy_schema = _schema(SCHEMA_NAMES[0])
        policy = json.loads(
            (ROOT / "presets" / "us_short_market_diagnostic_26w_policy_v1.json").read_text(
                encoding="utf-8"
            )
        )
        drifted_policy = copy.deepcopy(policy)
        drifted_policy["status_resolution"]["priority"][0] = "data_degraded"
        self.assertTrue(list(Draft7Validator(policy_schema).iter_errors(drifted_policy)))

        summary = copy.deepcopy(_summary())
        del summary["mixed_ruleset_window"]
        self.assertTrue(list(Draft7Validator(_schema(SCHEMA_NAMES[2])).iter_errors(summary)))

        summary = copy.deepcopy(_summary())
        summary["strategy"]["status"] = "data_degraded"
        self.assertTrue(list(Draft7Validator(_schema(SCHEMA_NAMES[2])).iter_errors(summary)))

    def test_weekly_record_is_closed_world_and_paper_gate_is_separate(self) -> None:
        schema = _schema(SCHEMA_NAMES[1])
        forged = copy.deepcopy(_weekly())
        forged["unexpected"] = True
        self.assertTrue(list(Draft7Validator(schema).iter_errors(forged)))

        not_evaluable = copy.deepcopy(_weekly())
        not_evaluable["strategy"]["paper_evaluable"] = False
        not_evaluable["strategy"]["performance_status"] = "not_evaluable"
        not_evaluable["strategy"]["strategy_evaluable"] = False
        not_evaluable["strategy"]["degradation_reasons"] = ["corporate_action_unconfirmed"]
        self.assertEqual([], list(Draft7Validator(schema).iter_errors(not_evaluable)))

        bad_no_count = copy.deepcopy(_weekly())
        bad_no_count["strategy"]["no_count"] = True
        bad_no_count["strategy"]["no_count_reason"] = None
        self.assertTrue(list(Draft7Validator(schema).iter_errors(bad_no_count)))

        execution_metrics = copy.deepcopy(_weekly())
        execution_metrics["strategy"]["turnover"] = 0.1
        execution_metrics["strategy"]["unfilled_order_count"] = None
        self.assertEqual([], list(Draft7Validator(schema).iter_errors(execution_metrics)))

        bad_execution_metrics = copy.deepcopy(execution_metrics)
        bad_execution_metrics["strategy"]["turnover"] = -0.1
        self.assertTrue(list(Draft7Validator(schema).iter_errors(bad_execution_metrics)))

    def test_summary_requires_all_four_benchmarks_and_closed_world(self) -> None:
        schema = _schema(SCHEMA_NAMES[2])
        missing = copy.deepcopy(_summary())
        del missing["benchmarks"]["VTI"]
        self.assertTrue(list(Draft7Validator(schema).iter_errors(missing)))

        forged = copy.deepcopy(_summary())
        forged["extra"] = True
        self.assertTrue(list(Draft7Validator(schema).iter_errors(forged)))


if __name__ == "__main__":
    unittest.main()
