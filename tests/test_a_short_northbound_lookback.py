"""Pure acceptance and negative controls for sequence 22b."""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import jsonschema

from engine.a_short_northbound_lookback import (
    build_lookback_summary,
    three_year_lookback_start,
)
from engine.a_short_csi300_window import CSI300_LIVE_WINDOW_SESSIONS


def _sessions(end: str, count: int) -> list[str]:
    current = date.fromisoformat(f"{end[:4]}-{end[4:6]}-{end[6:]}")
    dates: list[str] = []
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current -= timedelta(days=1)
    return list(reversed(dates))


def _payloads(*, flow_value: float = -1.0, rising: bool = False):
    dates = _sessions("20260804", 65)
    flow = [
        {"trade_date": trade_date, "north_money": flow_value}
        for trade_date in dates
    ]
    index = []
    for position, trade_date in enumerate(dates):
        close = 100.0 + position if rising else 200.0 - position
        index.append({"ts_code": "000300.SH", "trade_date": trade_date, "close": close})
    return flow, index


class NorthboundLookbackTests(unittest.TestCase):
    def test_three_year_start_is_calendar_bound(self):
        self.assertEqual(three_year_lookback_start("20260804"), "20230804")
        self.assertEqual(three_year_lookback_start("20240229"), "20210228")

    def test_positive_dual_condition_counts_trigger(self):
        flow, index = _payloads()
        summary = build_lookback_summary(flow, index, as_of="20260804")
        self.assertGreater(summary["eligible_week_count"], 0)
        self.assertGreater(summary["trigger_count"], 0)
        self.assertIn("triggered", {week["verdict"] for week in summary["weeks"]})
        self.assertTrue(all(week["predicate_consistent"] for week in summary["weeks"]))

    def test_single_condition_does_not_count_as_trigger(self):
        flow, index = _payloads(rising=True)
        summary = build_lookback_summary(flow, index, as_of="20260804")
        self.assertGreater(summary["eligible_week_count"], 0)
        self.assertEqual(summary["trigger_count"], 0)
        self.assertNotIn("triggered", {week["verdict"] for week in summary["weeks"]})

    def test_csi300_lookback_uses_the_live_trade_date_span(self):
        dates = _sessions("20260804", CSI300_LIVE_WINDOW_SESSIONS)
        flow = [{"trade_date": trade_date, "north_money": -1.0} for trade_date in dates]
        index = []
        for position, trade_date in enumerate(dates):
            if position < 45:
                close = 200.0
            else:
                close = 180.0 - (position - 45) * 0.5
            index.append({"ts_code": "000300.SH", "trade_date": trade_date, "close": close})
        summary = build_lookback_summary(flow, index, as_of="20260804")
        self.assertEqual(
            summary["source_binding"]["csi300_window_sessions"],
            CSI300_LIVE_WINDOW_SESSIONS,
        )
        self.assertGreater(summary["trigger_count"], 0)

    def test_finite_provider_numeric_strings_are_normalized_before_22a(self):
        flow, index = _payloads()
        for row in flow:
            row["north_money"] = str(row["north_money"])
        for row in index:
            row["close"] = str(row["close"])
        summary = build_lookback_summary(flow, index, as_of="20260804")
        self.assertGreater(summary["eligible_week_count"], 0)
        self.assertGreater(summary["trigger_count"], 0)

    def test_missing_latest_northbound_session_is_unavailable_not_shifted(self):
        flow, index = _payloads()
        latest = index[-1]["trade_date"]
        flow = [row for row in flow if row["trade_date"] != latest]
        summary = build_lookback_summary(flow, index, as_of="20260804")
        latest_week = summary["weeks"][-1]
        self.assertEqual(latest_week["verdict"], "unavailable")
        self.assertEqual(latest_week["unavailable_reason"], "source_gap")
        self.assertGreater(summary["unavailable_week_count"], 0)
        self.assertLess(summary["eligible_week_count"], summary["lookback_week_count"])

    def test_fetch_truncation_and_warmup_are_separate_unavailable_reasons(self):
        flow, index = _payloads()
        latest = index[-1]["trade_date"]
        flow = [row for row in flow if row["trade_date"] != latest]
        summary = build_lookback_summary(
            flow,
            index,
            as_of="20260804",
            northbound_fetch_truncated_dates={latest},
        )
        self.assertGreater(summary["unavailable_breakdown"]["warm_up"], 0)
        self.assertGreater(summary["unavailable_breakdown"]["fetch_truncated"], 0)
        self.assertEqual(summary["unavailable_breakdown"]["source_gap"], 0)
        self.assertEqual(summary["weeks"][-1]["unavailable_reason"], "fetch_truncated")

    def test_wrong_benchmark_source_binding_is_unavailable(self):
        flow, index = _payloads()
        index[0]["ts_code"] = "000852.SH"
        summary = build_lookback_summary(flow, index, as_of="20260804")
        self.assertEqual(summary["status"], "NOT_VERIFIED")
        self.assertIsNone(summary["trigger_count"])
        self.assertIn("index_daily CSI300 source", " ".join(summary["not_verified"]))

    def test_injected_lookback_predicate_turns_consistency_control_red(self):
        flow, index = _payloads()
        with patch(
            "engine.a_short_northbound_lookback._lookback_predicate",
            return_value=False,
        ) as injected:
            with self.assertRaisesRegex(AssertionError, "diverges from live predicate"):
                build_lookback_summary(flow, index, as_of="20260804")
        injected.assert_called()

    def test_schema_rejects_numeric_input_leak_in_week_verdict(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads(
            (root / "schemas" / "a_short_northbound_market_silence_lookback_summary.schema.json").read_text(
                encoding="utf-8"
            )
        )
        flow, index = _payloads()
        summary = build_lookback_summary(flow, index, as_of="20260804")
        summary["weeks"][0]["net_flow_yuan"] = -100.0
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(summary, schema)


if __name__ == "__main__":
    unittest.main()
