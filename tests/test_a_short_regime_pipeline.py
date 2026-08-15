"""Tests for V14.3 regime weekly orchestration (slice 2b-impl ②b-1, pure, comparison-only).

Pins: extend_ledger runs the fail-closed cadence workflow (bootstrap when empty, increment otherwise,
idempotent rerun), requires provider rows dated exactly the planned day, and rejects a gappy existing
ledger; weekly_regime_step composes extend + comparison record + audited evidence/panel, PIT-capped at
the run date. Data side is injected (fake feature_provider + synthetic csi1000) — no Tushare, no file
write, no EGS wiring.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_regime_pipeline import extend_ledger, weekly_regime_step  # noqa: E402
from engine.a_short_regime_ledger import build_ledger, validate_ledger  # noqa: E402
from engine.a_short_regime_classifier import build_comparison_record  # noqa: E402


def _dates(n, start=date(2024, 1, 2)):
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def _row(as_of):
    return {
        "schema_name": "a_short_market_regime_daily", "schema_version": "1.0.0",
        "as_of": as_of, "limit_up_count": 20, "limit_down_count": 5, "net_limit": 15,
        "max_limit_streak": 3, "promotion_rate": 0.30, "failed_limit_rate": 0.20,
        "iv_percentile_252d": 50.0, "csi300_ret_1d": 0.2, "csi1000_ret_1d": 0.3,
        "pct_above_ma20": 55.0, "csi1000_below_ma20": False, "data_quality_flags": [],
        "boundary": {"production": False, "comparison_only": True, "drives_phase5_risk_posture": False},
    }


def _idx(dates):
    return pd.DataFrame([(d, 100.0 + i) for i, d in enumerate(dates)], columns=["trade_date", "close"])


class _Provider:
    """Fake feature provider: returns the benign row for the requested date, counting calls."""
    def __init__(self):
        self.calls = []

    def __call__(self, d):
        self.calls.append(d)
        return _row(d)


class ExtendLedgerTests(unittest.TestCase):
    def test_bootstrap_from_empty(self):
        cal = _dates(5)
        p = _Provider()
        led = extend_ledger(build_ledger([]), cal[-1], cal, p)
        self.assertEqual([r["as_of"] for r in led["rows"]], cal)
        self.assertEqual(p.calls, cal)                      # provider called once per bootstrap day
        validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_steady_increment(self):
        cal = _dates(5)
        existing = build_ledger([_row(d) for d in cal[:3]])
        p = _Provider()
        led = extend_ledger(existing, cal[4], cal, p)
        self.assertEqual([r["as_of"] for r in led["rows"]], cal)
        self.assertEqual(p.calls, cal[3:5])                 # only the 2 new days fetched

    def test_idempotent_rerun(self):
        cal = _dates(5)
        existing = build_ledger([_row(d) for d in cal])
        p = _Provider()
        led = extend_ledger(existing, cal[-1], cal, p)
        self.assertEqual(p.calls, [])                        # nothing to add
        self.assertEqual([r["as_of"] for r in led["rows"]], cal)

    def test_provider_wrong_date_raises(self):
        cal = _dates(5)
        with self.assertRaises(ValueError):
            extend_ledger(build_ledger([]), cal[-1], cal, lambda d: _row("19990101"))

    def test_rejects_gappy_existing(self):
        cal = _dates(6)
        gappy = build_ledger([_row(d) for d in cal if d != cal[3]])   # internal gap
        with self.assertRaises(ValueError):
            extend_ledger(gappy, cal[-1], cal, _Provider())

    def test_generator_calendar_not_consumed(self):
        # R-V143-SLICE2B-PIPELINE-CALENDAR-ITERATOR-CONSUMED: calendar reused across 3 helpers.
        cal = _dates(5)
        p = _Provider()
        led = extend_ledger(build_ledger([]), cal[-1], (d for d in cal), p)
        self.assertEqual([r["as_of"] for r in led["rows"]], cal)

    def test_empty_calendar_bootstrap_raises(self):
        # R-V143-SLICE2B-PIPELINE-EMPTY-BOOTSTRAP-CALENDAR-ACCEPTED
        with self.assertRaises(ValueError):
            extend_ledger(build_ledger([]), "20240105", [], _Provider())

    def test_all_future_calendar_bootstrap_raises(self):
        with self.assertRaises(ValueError):
            extend_ledger(build_ledger([]), "20240105", ["20240110", "20240111"], _Provider())


class WeeklyStepTests(unittest.TestCase):
    def test_step_from_empty(self):
        cal = _dates(5)
        out = weekly_regime_step(build_ledger([]), cal[-1], cal, "unknown", _idx(cal), _Provider())
        self.assertEqual([r["as_of"] for r in out["ledger"]["rows"]], cal)
        rec = out["comparison_record"]
        self.assertEqual(rec["v14_3_raw_regime"], "shock")         # benign rows → shock
        self.assertTrue(rec["divergence"])                          # vs v14_2 'unknown'
        self.assertEqual(out["evidence"]["total_weeks"], 1)
        # as_of_now == run date → this week's forward horizons not yet elapsed
        self.assertEqual(rec["forward_returns_pending"], ["h1", "h3", "h5", "h10"])
        self.assertIn("comparison-only", out["panel_markdown"])
        self.assertIn("非生产", out["panel_markdown"])

    def test_step_accumulates_prior_records(self):
        cal = _dates(8)
        prior = build_comparison_record([_row(cal[0])], "unknown", as_of=cal[0])
        out = weekly_regime_step(build_ledger([_row(d) for d in cal[:7]]), cal[7], cal, "unknown",
                                 _idx(cal), _Provider(), prior_comparison_records=[prior])
        self.assertEqual(out["evidence"]["total_weeks"], 2)         # prior + current
        self.assertEqual(out["comparison_record"]["as_of"], cal[7])

    def test_identical_same_week_legacy_identity_rerun_dedups(self):
        # Legacy real evidence rows omit run_revision_id. A same-week rerun must still replace, not double.
        cal = _dates(5)
        ledger = build_ledger([_row(d) for d in cal])
        prior = build_comparison_record(ledger["rows"], "unknown", as_of=cal[-1])
        self.assertNotIn("run_revision_id", prior)
        out = weekly_regime_step(ledger, cal[-1], cal, "unknown", _idx(cal), _Provider(),
                                 prior_comparison_records=[prior])
        self.assertEqual(len(out["comparison_records"]), 1)
        self.assertEqual(out["evidence"]["total_weeks"], 1)        # deduped, not 2

    def test_divergent_same_week_legacy_identity_rerun_raises(self):
        cal = _dates(5)
        ledger = build_ledger([_row(d) for d in cal])
        conflict = build_comparison_record(ledger["rows"], "unknown", as_of=cal[-1])
        self.assertNotIn("run_revision_id", conflict)
        conflict["v14_3_raw_regime"] = "attack"                    # classification differs from rerun
        conflict["v14_3_fired_rule"] = "attack_all_of"
        with self.assertRaises(ValueError):
            weekly_regime_step(ledger, cal[-1], cal, "unknown", _idx(cal), _Provider(),
                               prior_comparison_records=[conflict])

    def test_output_records_sorted(self):
        cal = _dates(9)
        # unsorted prior history
        p1 = build_comparison_record([_row(cal[2])], "unknown", as_of=cal[2])
        p0 = build_comparison_record([_row(cal[0])], "unknown", as_of=cal[0])
        out = weekly_regime_step(build_ledger([_row(d) for d in cal[:8]]), cal[8], cal, "unknown",
                                 _idx(cal), _Provider(), prior_comparison_records=[p1, p0])
        dates = [r["as_of"] for r in out["comparison_records"]]
        self.assertEqual(dates, sorted(dates))


if __name__ == "__main__":
    unittest.main()
