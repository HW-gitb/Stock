"""P0 proofs for the bounded, provenance-preserving v2 cache builder."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import a_short_factor_comparison as v1  # noqa: E402
from engine.a_short_factor_comparison_v2 import ComparisonV2Error, capture_v2_week  # noqa: E402
from runners.a_short_factor_comparison_v2_cache_build import materialize_incremental_cache  # noqa: E402


DECISION_DATE = "20260202"
RUN_DATE = "20260227"


def _root(tmp: str) -> Path:
    return Path(tmp) / "state" / "a_short" / "factor_comparison_private" / "v2"


def _trading_dates(start: date, count: int) -> list[str]:
    result = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return result


def _candidate(index: int) -> dict:
    history = _trading_dates(date(2025, 12, 23), 30)
    series = []
    for day_index, day in enumerate(history):
        close = 10.5 if day_index >= 20 else 10.2
        series.append({"trade_date": day, "high": 15.0 if day_index in (22, 27) else close + 0.2,
                       "low": 9.7 if day_index in (21, 26) else close - 0.2, "close": close})
    assert history[-1] == DECISION_DATE
    return {
        "ts_code": f"60000{index}.SH", "name": f"name-{index}", "close": 10.5,
        "price_series": series,
        "egs_score": 100.0 - index, "derived": {}, "event": {},
        "liquidity": {"avg_amount_5d": 1e9},
        "iv": {"iv_percentile_252d": 50.0, "iv_value": 0.20, "hv_value": 0.18},
        "market_regime": "attack", "regime_fallback": {}, "stateful_risk": {},
    }


def _capture(root: Path) -> dict:
    candidates = [_candidate(index) for index in range(5)]
    identity = {
        "run_id": "p0-cache-test", "run_date": DECISION_DATE, "source_as_of": DECISION_DATE,
        "price_data_through": DECISION_DATE,
        "candidate_digest": v1._digest([v1._safe_candidate(row) for row in candidates]),
        "official_m67_digest": "a" * 64,
    }
    return capture_v2_week(root=root, decision_date=DECISION_DATE, candidates=candidates,
                           run_identity=identity, forward_eligible=False)


class FakeTushare:
    def __init__(self, *, missing_adj: bool = False):
        self.missing_adj = missing_adj
        self.calls: list[tuple[str, dict]] = []

    @staticmethod
    def _days(start: str, end: str) -> list[str]:
        current = datetime_from(start)
        finish = datetime_from(end)
        result = []
        while current <= finish:
            if current.weekday() < 5:
                result.append(current.strftime("%Y%m%d"))
            current += timedelta(days=1)
        return result

    def trade_cal(self, **kwargs):
        self.calls.append(("trade_cal", kwargs))
        return pd.DataFrame({"cal_date": self._days(kwargs["start_date"], kwargs["end_date"])})

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        return pd.DataFrame([{ "ts_code": kwargs["ts_code"], "trade_date": day, "open": 10.0,
                               "close": 10.5 } for day in self._days(kwargs["start_date"], kwargs["end_date"])])

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", kwargs))
        dates = self._days(kwargs["start_date"], kwargs["end_date"])
        if self.missing_adj:
            dates = dates[1:]
        return pd.DataFrame([{ "ts_code": kwargs["ts_code"], "trade_date": day, "adj_factor": 2.0 }
                             for day in dates])

    def stk_limit(self, **kwargs):
        self.calls.append(("stk_limit", kwargs))
        return pd.DataFrame([{ "ts_code": kwargs["ts_code"], "trade_date": day, "up_limit": 11.0 }
                             for day in self._days(kwargs["start_date"], kwargs["end_date"])])


def datetime_from(value: str) -> date:
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


class ComparisonV2CacheBuildTests(unittest.TestCase):
    def test_no_frozen_capture_makes_no_provider_call_or_empty_success_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            root.mkdir(parents=True)
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                result = materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=provider)
            self.assertEqual(result["status"], "no_frozen_v2_captures")
            self.assertEqual(provider.calls, [])
            self.assertFalse((root / "daily_cache.json").exists())

    def test_terminal_capture_is_not_refetched_when_its_cache_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            capture = _capture(root)["capture"]
            terminal = {
                "schema_name": "a_short_factor_comparison_v2_weekly", "schema_version": "2.0.0",
                "record_type": "outcome", "program_id": "a_short_factor_comparison_v2",
                "decision_date": DECISION_DATE, "epoch_id": capture["epoch_id"],
                "payload": {"questions": [{"status": "settled"}]}, "boundary": capture["boundary"],
            }
            (root / "weeks" / DECISION_DATE / "outcome.json").write_text(json.dumps(terminal), encoding="utf-8")
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                result = materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=provider)
            self.assertEqual(result["status"], "no_frozen_v2_captures")
            self.assertEqual(provider.calls, [])

    def test_fetches_only_frozen_selected_union_and_marks_direct_adjustment_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            capture = _capture(root)["capture"]
            selected = sorted({code for question in capture["payload"]["questions"] for arm in question["arms"]
                               for code in arm["selected_symbols"]})
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                result = materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=provider)
            self.assertEqual(result["status"], "cache_updated")
            self.assertEqual(result["provider_calls"], 1 + 3 * len(selected))
            self.assertEqual(sorted({call[1].get("ts_code") for call in provider.calls if call[0] == "daily"}), selected)
            cache = json.loads((root / "daily_cache.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted({row["ts_code"] for row in cache["stocks"]}), selected)
            self.assertTrue(all(row["adj_factor_observed"] is True for row in cache["stocks"]))
            self.assertTrue(all(row["adj_factor_source"] == "provider_observed" for row in cache["stocks"]))
            self.assertTrue(all(row["corporate_action_verified"] is False for row in cache["stocks"]))
            self.assertEqual(cache["stocks"][0]["open"], 10.0, "raw daily price must not be double-adjusted")

    def test_missing_adjustment_is_recorded_as_missing_not_forward_filled_or_defaulted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            provider = FakeTushare(missing_adj=True)
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=provider)
            cache = json.loads((root / "daily_cache.json").read_text(encoding="utf-8"))
            first_by_symbol = {}
            for row in cache["stocks"]:
                first_by_symbol.setdefault(row["ts_code"], row)
            self.assertTrue(all(row["adj_factor"] is None for row in first_by_symbol.values()))
            self.assertTrue(all(row["adj_factor_observed"] is False for row in first_by_symbol.values()))
            self.assertTrue(all(row["adj_factor_source"] == "provider_missing" for row in first_by_symbol.values()))

    def test_budget_failure_happens_before_any_provider_call_or_cache_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                with self.assertRaisesRegex(ComparisonV2Error, "budget exceeded"):
                    materialize_incremental_cache(root=root, run_date=RUN_DATE, max_provider_calls=1, pro=provider)
            self.assertEqual(provider.calls, [])
            self.assertFalse((root / "daily_cache.json").exists())

    def test_conflicting_provider_row_preserves_the_existing_cache_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            root.mkdir(parents=True, exist_ok=True)
            original = {
                "schema_name": "a_short_factor_comparison_v2_daily_cache", "schema_version": "1.0.0",
                "stocks": [{"ts_code": "600000.SH", "trade_date": DECISION_DATE, "open": 99.0, "close": 10.5,
                            "adj_factor": 2.0, "adj_factor_observed": True,
                            "adj_factor_source": "provider_observed", "corporate_action_verified": False}],
                "limits": [],
                "meta": {"cache_kind": "a_short_factor_comparison_v2_incremental", "source": "tushare:daily+adj_factor+stk_limit"},
            }
            path = root / "daily_cache.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                with self.assertRaisesRegex(ComparisonV2Error, "conflicting duplicate"):
                    materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=provider)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)


if __name__ == "__main__":
    unittest.main()
