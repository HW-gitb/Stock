"""Knife-3 tests for the v2 weekly adapter; all data is synthetic and cache-only."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import a_short_factor_comparison as v1  # noqa: E402
from engine.a_short_factor_comparison_v2 import capture_v2_week  # noqa: E402
from engine.a_short_factor_comparison_v2_weekly import (  # noqa: E402
    DAILY_CACHE_NAME,
    PUBLIC_STATUS_CURRENT,
    PUBLIC_STATUS_UNAVAILABLE,
    capture_v2_after_published_weekly,
    load_v2_daily_cache,
    settle_and_summarize_v2_weekly,
)


def _root(tmp: str) -> Path:
    return Path(tmp) / "state" / "a_short" / "factor_comparison_private" / "v2"


def _trading_dates(start: date, count: int) -> list[str]:
    dates = []
    current = start
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


DECISION_DATE = "20260202"


def _candidate(index: int) -> dict:
    history = _trading_dates(date(2025, 12, 22), 31)
    assert history[-1] == DECISION_DATE
    return {
        "ts_code": f"60000{index}.SH", "name": f"name-{index}", "close": 10.5,
        "price_series": [{"trade_date": day, "high": 10.7, "low": 9.9, "close": 10.5}
                         for day in history],
        "egs_score": 100.0 - index, "derived": {}, "event": {},
        "liquidity": {"avg_amount_5d": 1e9},
        "iv": {"iv_percentile_252d": 50.0, "iv_value": 0.20, "hv_value": 0.18},
        "market_regime": "attack", "regime_fallback": {}, "stateful_risk": {},
    }


def _candidates() -> list[dict]:
    return [_candidate(index) for index in range(5)]


def _identity(candidates: list[dict]) -> dict:
    return {
        "run_id": "knife3-test", "run_date": DECISION_DATE, "source_as_of": DECISION_DATE,
        "candidate_digest": v1._digest([v1._safe_candidate(row) for row in candidates]),
        "official_m67_digest": "b" * 64,
    }


def _daily_cache() -> dict:
    rows = []
    for code_index in range(5):
        for day in _trading_dates(date(2026, 2, 2), 25):
            rows.append({
                "ts_code": f"60000{code_index}.SH", "trade_date": day,
                "open": 10.0, "close": 10.5 if day == DECISION_DATE else 10.0,
                "adj_factor": 1.0, "adj_factor_observed": True,
                "adj_factor_source": "provider_observed", "corporate_action_verified": False,
            })
    return {
        "schema_name": "a_short_factor_comparison_v2_daily_cache", "schema_version": "1.0.0",
        "stocks": rows, "limits": [], "meta": {"cache_kind": "synthetic", "source": "test"},
    }


class ComparisonV2WeeklyAdapterTests(unittest.TestCase):
    def _capture(self, root: Path) -> list[dict]:
        candidates = _candidates()
        with mock.patch("engine.a_short_factor_comparison_v2._today", return_value=DECISION_DATE):
            capture_v2_week(root=root, decision_date=DECISION_DATE, candidates=candidates,
                            run_identity=_identity(candidates), forward_eligible=True)
        return candidates

    def test_existing_private_cache_settles_and_uses_the_freshly_written_reminder_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            self._capture(root)
            (root / DAILY_CACHE_NAME).write_text(json.dumps(_daily_cache()), encoding="utf-8")
            summary = settle_and_summarize_v2_weekly(root=root)
            self.assertEqual(summary["status"], PUBLIC_STATUS_CURRENT)
            self.assertEqual(summary["reminder_count"], 0)
            self.assertTrue((root / "reminder.json").is_file())

    def test_missing_cache_never_relays_a_stale_reminder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            self._capture(root)
            (root / "reminder.json").write_text(json.dumps({
                "schema_name": "a_short_factor_comparison_v2_reminder", "schema_version": "2.0.0",
                "program_id": "a_short_factor_comparison_v2", "reminders": [{"private": "stale"}],
                "production_unchanged": True,
            }), encoding="utf-8")
            summary = settle_and_summarize_v2_weekly(root=root)
            self.assertEqual(summary["status"], PUBLIC_STATUS_UNAVAILABLE)
            self.assertEqual(summary["reminder_count"], 0)
            self.assertNotIn("stale", summary["message"])

    def test_daily_cache_must_stay_under_the_private_v2_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            root.mkdir(parents=True)
            outside = Path(tmp) / "outside.json"
            outside.write_text(json.dumps(_daily_cache()), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_v2_daily_cache(root=root, daily_cache_path=outside)

    def test_capture_requires_the_matching_published_bundle_before_freezing_current_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            out = Path(tmp) / "weekly_m67.json"
            md = out.with_suffix(".md")
            receipt_path = out.with_suffix("").with_suffix(".receipt.json")
            candidates = _candidates()
            source_identity = {"run_id": "official-run", "candidate_digest": "a" * 64}
            weekly = {
                "as_of": DECISION_DATE,
                "run_lineage": {"run_id": "official-run", "candidate_digest": "a" * 64},
                "factor_comparison_v2": {
                    "summary_id": "a_short_factor_comparison_v2", "status": "not_configured",
                    "reminder_count": 0,
                    "message": "对比轨 v2：未配置；未读取或写入对比证据，生产结论不变。",
                    "production_unchanged": True,
                },
            }
            out.write_text(json.dumps(weekly), encoding="utf-8")
            md.write_text("weekly", encoding="utf-8")
            receipt_path.write_text(json.dumps({
                "stage_status": "complete", "as_of": DECISION_DATE, "run_id": "official-run",
                "candidate_digest": "a" * 64, "outputs": [out.name, md.name],
            }), encoding="utf-8")
            result = capture_v2_after_published_weekly(
                root=root, decision_date=DECISION_DATE, candidates=candidates,
                source_identity=source_identity, out_path=out, receipt_path=receipt_path,
                forward_eligible=False)
            self.assertEqual(result["status"], "captured")
            receipt_path.unlink()
            with self.assertRaises(ValueError):
                capture_v2_after_published_weekly(
                    root=root, decision_date=DECISION_DATE, candidates=candidates,
                    source_identity=source_identity, out_path=out, receipt_path=receipt_path,
                    forward_eligible=False)


if __name__ == "__main__":
    unittest.main()
