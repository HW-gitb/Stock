"""Runner and write-boundary controls for sequence 22b."""
from __future__ import annotations

from datetime import date, timedelta
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import jsonschema

from runners import a_short_northbound_market_silence_lookback as runner


def _sessions(end: str, count: int) -> list[str]:
    current = date.fromisoformat(f"{end[:4]}-{end[4:6]}-{end[6:]}")
    dates: list[str] = []
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current -= timedelta(days=1)
    return list(reversed(dates))


class _FakeProvider:
    def __init__(self) -> None:
        dates = _sessions("20260804", 65)
        self.flow = [
            {"trade_date": trade_date, "north_money": -1.0}
            for trade_date in dates
        ]
        self.index = [
            {
                "ts_code": "000300.SH",
                "trade_date": trade_date,
                "close": 200.0 - position,
            }
            for position, trade_date in enumerate(dates)
        ]
        self.calls: list[tuple[str, dict[str, str]]] = []

    def moneyflow_hsgt(self, **kwargs):
        self.calls.append(("moneyflow_hsgt", kwargs))
        start_date = kwargs.get("start_date")
        end_date = kwargs.get("end_date")
        return [
            row for row in self.flow
            if start_date <= row["trade_date"] <= end_date
        ]

    def index_daily(self, **kwargs):
        self.calls.append(("index_daily", kwargs))
        return self.index


class _LargeFakeProvider(_FakeProvider):
    def __init__(self) -> None:
        dates = _sessions("20260804", 726)
        self.flow = [
            {"trade_date": trade_date, "north_money": -1.0}
            for trade_date in dates
        ]
        self.index = [
            {
                "ts_code": "000300.SH",
                "trade_date": trade_date,
                "close": 200.0 - position,
            }
            for position, trade_date in enumerate(dates)
        ]
        self.calls: list[tuple[str, dict[str, str]]] = []


class _TruncatingFakeProvider(_LargeFakeProvider):
    def moneyflow_hsgt(self, **kwargs):
        self.calls.append(("moneyflow_hsgt", kwargs))
        return self.flow[:300]


@contextmanager
def _raw_temp():
    provider_root = runner.PROJECT_ROOT / "provider_samples"
    created_root = not provider_root.exists()
    provider_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=provider_root) as temp:
            yield Path(temp)
    finally:
        if created_root and provider_root.exists() and not any(provider_root.iterdir()):
            provider_root.rmdir()


class NorthboundLookbackRunnerTests(unittest.TestCase):
    def test_runner_segments_flow_under_provider_row_cap_and_keeps_safe_summary(self):
        fake = _FakeProvider()
        with _raw_temp() as raw_root:
            summary = runner.run_probe(fake, as_of="20260804", raw_root=raw_root)
            schema = json.loads(
                (runner.PROJECT_ROOT / "schemas" / "a_short_northbound_market_silence_lookback_summary.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            jsonschema.validate(summary, schema)
            self.assertEqual(
                [name for name, _ in fake.calls],
                ["index_daily", "moneyflow_hsgt"],
            )
            self.assertEqual(summary["execution"]["calls_made"], 2)
            self.assertEqual(summary["execution"]["successful_calls"], 2)
            self.assertEqual(summary["northbound_fetch"]["segment_count"], 1)
            self.assertFalse(summary["northbound_fetch"]["truncated"])
            self.assertFalse(summary["storage"]["tracked_summary_contains_raw_rows"])
            self.assertNotIn("rows", summary)
            self.assertTrue((raw_root / "northbound_moneyflow_hsgt.json").is_file())
            self.assertTrue((raw_root / "csi300_index_daily.json").is_file())
            self.assertTrue((raw_root / "northbound_moneyflow_hsgt_fetch_manifest.json").is_file())

    def test_large_calendar_uses_multiple_flow_calls_within_budget(self):
        fake = _LargeFakeProvider()
        with _raw_temp() as raw_root:
            summary = runner.run_probe(fake, as_of="20260804", raw_root=raw_root)
        self.assertEqual(summary["execution"]["calls_made"], 4)
        self.assertEqual(summary["northbound_fetch"]["segment_count"], 3)
        self.assertEqual(summary["northbound_fetch"]["requested_session_count"], 726)
        self.assertEqual(summary["northbound_fetch"]["observed_session_count"], 726)
        self.assertFalse(summary["northbound_fetch"]["truncated"])

    def test_row_cap_is_recorded_and_classified_as_fetch_truncation(self):
        fake = _TruncatingFakeProvider()
        with _raw_temp() as raw_root:
            summary = runner.run_probe(fake, as_of="20260804", raw_root=raw_root)
        self.assertEqual(summary["northbound_fetch"]["truncated_segment_count"], 3)
        self.assertTrue(summary["northbound_fetch"]["truncated"])
        self.assertGreater(summary["unavailable_breakdown"]["fetch_truncated"], 0)

    def test_raw_and_production_output_boundaries_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            outside = Path(temp)
            with self.assertRaisesRegex(ValueError, "provider_samples"):
                runner._assert_raw_root(outside)
            with self.assertRaisesRegex(ValueError, "result/a_short"):
                runner._assert_not_production_output(
                    runner.PROJECT_ROOT / "result" / "a_short" / "20260804" / "weekly.json"
                )

    def test_provider_failure_keeps_frequency_unverified(self):
        class FailingProvider:
            def moneyflow_hsgt(self, **kwargs):
                raise RuntimeError("provider failure with secret-like details")

            def index_daily(self, **kwargs):
                return []

        with _raw_temp() as raw_root:
            summary = runner.run_probe(FailingProvider(), raw_root=raw_root)
        self.assertEqual(summary["status"], "NOT_VERIFIED")
        self.assertIsNone(summary["trigger_count"])
        self.assertIn("did not return a usable payload", " ".join(summary["not_verified"]))
        self.assertNotIn("secret-like", json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
