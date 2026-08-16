"""Offline tests for the bounded US-short yfinance analyst-grade feasibility probe.

No network: the fake client exposes in-memory tables only. The probe must stay source-bound to the 20260710
Pass2 cohort, remain dry-run by default, treat yfinance as a low-trust feasibility experiment, and never write
raw rows, tickers, secrets, or URLs to its tracked summary.
"""
from __future__ import annotations

import json
import shutil
import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_yfinance_grades_feasibility_probe as probe  # noqa: E402
from tests.provider.us_short_private_test_root_light import temporary_us_short_directory  # noqa: E402


def _artifacts():
    symbols = ["ABCL", "YEXT", "ZBIO", "ZURA", "HOOD", "MRNA"] + [f"T{i:03d}" for i in range(194)]
    rows = [{"ticker": symbol, "market_cap_usd": 1_000_000 + index * 10_000}
            for index, symbol in enumerate(symbols)]
    return (
        {"rows": rows, "row_count": 200},
        {"momentum_by_ticker": {symbol: float(index) for index, symbol in enumerate(symbols)}},
        {"records": {"HOOD": [{"date": "2026-07-02"}], "MRNA": [{"date": "2026-07-07"}]}},
    )


class FakeTicker:
    def __init__(self, symbol, *, recent=True, error=None):
        self.symbol = symbol
        self.recent = recent
        self.error = error

    @property
    def upgrades_downgrades(self):
        if self.error:
            raise RuntimeError(self.error)
        row_date = "2026-07-05" if self.recent else "2025-01-01"
        return [{"Date": row_date, "Action": "up", "Firm": "Example Research", "ToGrade": "Buy"}]

    @property
    def recommendations(self):
        if self.error:
            raise RuntimeError(self.error)
        return [{"period": "0m", "strongBuy": 3, "buy": 2}]


class FakeClient:
    def __init__(self, *, stale_symbols=(), error_symbol=None, error_text="429 Too Many Requests"):
        self.stale_symbols = set(stale_symbols)
        self.error_symbol = error_symbol
        self.error_text = error_text
        self.calls = []

    def ticker(self, symbol):
        self.calls.append(symbol)
        return FakeTicker(symbol, recent=symbol not in self.stale_symbols,
                          error=self.error_text if symbol == self.error_symbol else None)


class ProbeTestBase(unittest.TestCase):
    def setUp(self):
        self._sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_yfinance_grades_feasibility_20260710"
        )
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        original_raw_rel_root = probe.RAW_REL_ROOT
        probe.RAW_REL_ROOT = self.sample_root.relative_to(ROOT)
        self.addCleanup(setattr, probe, "RAW_REL_ROOT", original_raw_rel_root)
        self.candidate, self.momentum, self.actions = _artifacts()
        self.plan = probe.build_probe_plan(self.candidate, self.momentum, self.actions)
        self.raw_root = self.sample_root / "yfinance_grades_feasibility" / "_unit_tests" / self.id().split(".")[-1] / "raw"
        self.summary_path = self.raw_root.parent / "summary.json"

    def _run(self, client=None, **kwargs):
        return probe.run_probe(
            self.plan,
            client=FakeClient() if client is None else client,
            confirm_user_authorization=True,
            raw_root=self.raw_root,
            summary_path=self.summary_path,
            as_of=date(2026, 7, 10),
            pace_seconds=0.0,
            **kwargs,
        )


class SamplePlanTests(ProbeTestBase):
    def test_plan_binds_402_cohort_momentum_sample_and_controls(self):
        groups = {item["group"]: [] for item in self.plan["items"]}
        for item in self.plan["items"]:
            groups[item["group"]].append(item["ticker"])
        self.assertEqual(len(groups["fmp_402_small_cap"]), probe.FMP_402_SMALL_CAP_SAMPLE_COUNT)
        self.assertEqual(len(groups["momentum_top200"]), probe.MOMENTUM_TOP200_SAMPLE_COUNT)
        self.assertEqual(groups["fmp_200_control"], ["HOOD", "MRNA"])
        self.assertTrue(set(probe.FMP_402_EXEMPLARS).issubset(groups["fmp_402_small_cap"]))
        self.assertEqual(len({item["ticker"] for item in self.plan["items"]}), probe.TOTAL_PLANNED_SYMBOLS)

    def test_plan_rejects_unexpected_fmp_success_set(self):
        bad = {"records": {"HOOD": [], "MRNA": [], "ABCL": []}}
        with self.assertRaises(probe.YFinanceGradesProbeError):
            probe.build_probe_plan(self.candidate, self.momentum, bad)

    def test_default_dry_run_neither_imports_yfinance_nor_writes(self):
        called = []
        # The tracked live-run summary may legitimately exist as committed evidence; a dry-run must not CREATE or
        # MODIFY it. Capture its pre-state and assert the dry-run leaves it byte-for-byte untouched.
        summary_before = probe.SUMMARY_PATH.stat().st_mtime_ns if probe.SUMMARY_PATH.exists() else None
        out = probe.run_default(dry_run=True, importer=lambda _: called.append("import"),
                                plan_loader=lambda: self.plan)
        self.assertEqual(called, [])
        self.assertEqual(out["scope"]["status"], "dry_run_only")
        self.assertEqual(out["sample"]["planned_total"], probe.TOTAL_PLANNED_SYMBOLS)
        summary_after = probe.SUMMARY_PATH.stat().st_mtime_ns if probe.SUMMARY_PATH.exists() else None
        self.assertEqual(summary_before, summary_after)


class ProbeExecutionTests(ProbeTestBase):
    def test_canonical_tracked_summary_path_is_allowed_for_confirmed_execution(self):
        # The live output is deliberately tracked under docs/, while only raw belongs in provider_samples.
        probe._validate_write_paths(self.raw_root, probe.SUMMARY_PATH)

    def test_noncanonical_summary_outside_probe_root_is_rejected(self):
        with self.assertRaises(probe.YFinanceGradesProbeError):
            probe._validate_write_paths(self.raw_root, ROOT / "state" / "unrelated_summary.json")

    def test_live_fetch_refuses_without_confirm_before_touching_client(self):
        client = FakeClient()
        with self.assertRaisesRegex(probe.YFinanceGradesProbeError, "confirm-user-authorization"):
            probe.run_probe(
                self.plan,
                client=client,
                confirm_user_authorization=False,
                raw_root=self.raw_root,
                summary_path=self.summary_path,
                as_of=date(2026, 7, 10),
                pace_seconds=0.0,
            )
        self.assertEqual(client.calls, [])

    def test_all_recent_small_caps_passes_threshold_and_summary_is_hygienic(self):
        summary = self._run()
        self.assertEqual(summary["decision"]["verdict"], "worth_building")
        self.assertEqual(summary["coverage"]["fmp_402_small_cap"]["recent90_coverage_pct"], 100.0)
        self.assertTrue(self.summary_path.exists())
        self.assertEqual(len(list(self.raw_root.glob("*.json"))), probe.TOTAL_PLANNED_SYMBOLS)
        text = self.summary_path.read_text(encoding="utf-8")
        self.assertNotIn("ABCL", text)
        self.assertNotIn("Example Research", text)
        self.assertNotIn("http", text.lower())

    def test_stale_small_cap_grades_fail_the_50_percent_criterion(self):
        small_caps = [item["ticker"] for item in self.plan["items"] if item["group"] == "fmp_402_small_cap"]
        summary = self._run(FakeClient(stale_symbols=small_caps))
        self.assertEqual(summary["decision"]["verdict"], "not_worth_building")
        self.assertIn("small_cap_coverage_below_50_percent", summary["decision"]["reason_codes"])

    def test_small_cap_coverage_exactly_50_percent_passes_the_inclusive_boundary(self):
        small_caps = [item["ticker"] for item in self.plan["items"] if item["group"] == "fmp_402_small_cap"]
        summary = self._run(FakeClient(stale_symbols=small_caps[:6]))
        self.assertEqual(summary["coverage"]["fmp_402_small_cap"]["recent90_coverage_pct"], 50.0)
        self.assertEqual(summary["decision"]["verdict"], "worth_building")

    def test_rate_limit_or_crumb_stops_the_probe_and_cannot_pass(self):
        second = self.plan["items"][1]["ticker"]
        client = FakeClient(error_symbol=second, error_text="invalid crumb 429")
        summary = self._run(client)
        self.assertEqual(summary["scope"]["status"], "halted_rate_limit_or_crumb_failure")
        self.assertEqual(summary["rate_limit"]["first_failure_symbol_index"], 2)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(summary["decision"]["verdict"], "not_worth_building")

    def test_missing_yfinance_fails_only_after_confirmed_execution(self):
        def missing(_):
            raise ModuleNotFoundError("No module named yfinance")
        with self.assertRaisesRegex(probe.YFinanceGradesProbeError, "not installed"):
            probe.run_probe(
                self.plan,
                client=None,
                importer=missing,
                confirm_user_authorization=True,
                raw_root=self.raw_root,
                summary_path=self.summary_path,
                as_of=date(2026, 7, 10),
                pace_seconds=0.0,
            )


class SchemaTests(ProbeTestBase):
    def test_schema_rejects_provider_or_production_claim_drift(self):
        summary = self._run()
        probe.validate_summary(summary)
        summary["scope"]["provider_selected"] = True
        with self.assertRaises(probe.YFinanceGradesProbeError):
            probe.validate_summary(summary)


if __name__ == "__main__":
    unittest.main()
