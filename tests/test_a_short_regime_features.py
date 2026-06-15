"""Tests for the V14.3 regime daily-feature computation (slice 2b-impl ①, pure, comparison-only).

Layered contract pinned here: source-panel integrity raises (non-canonical trade_date, duplicate
daily/limit/index rows); as_of FAILS CLOSED on missing/unusable daily price OR stk_limit (non-null
count fields can't encode "unknown"); nullable / prior-window metrics degrade via flags
(stk_limit_history_incomplete, insufficient_sample, ma20_insufficient_window, csi*_unavailable,
iv_unavailable). Plus per-stock stk_limit caliber (ST ±5% vs ±10%), failed_limit_rate zero-denom null,
max consecutive limit-up streak, promotion thin-denom null, index ret_1d + csi1000_below_ma20 stale/
missing → null+flag, iv [0,100], PIT (rows>as_of ignored), and the produced row passes the daily
schema + ledger daily_row_semantic_errors. No data fetch.
"""
from __future__ import annotations

import sys
import json
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_regime_features import compute_regime_daily_features, MA_WINDOW  # noqa: E402
from engine.a_short_regime_ledger import daily_row_semantic_errors  # noqa: E402

DAILY_SCHEMA = ROOT / "schemas" / "a_short_market_regime_daily.schema.json"


def _daily(rows):   # rows: (trade_date, ts_code, high, close)
    return pd.DataFrame(rows, columns=["trade_date", "ts_code", "high", "close"])


def _limit(rows):   # rows: (trade_date, ts_code, up_limit, down_limit)
    return pd.DataFrame(rows, columns=["trade_date", "ts_code", "up_limit", "down_limit"])


def _idx(rows):     # rows: (trade_date, close)
    return pd.DataFrame(rows, columns=["trade_date", "close"])


def _dates(n, start=date(2024, 1, 2)):
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


# --- frozen pre-optimization reference (byte-exact copy of the engine at commit 5b20f09c) ----------
# The perf optimization (group-by-trade_date once instead of a per-window-day full-panel rescan) MUST
# be output-preserving; we load the ORIGINAL implementation here and assert the optimized engine emits
# byte-identical rows over the same panels across many as_of. Loaded by file path so it stays an
# independent frozen artifact, never re-resolving to the (mutated) production module.
import importlib.util  # noqa: E402

_REF_PATH = ROOT / "tests" / "_regime_features_reference_frozen.py"
_ref_spec = importlib.util.spec_from_file_location("_regime_features_reference_frozen", _REF_PATH)
_ref_mod = importlib.util.module_from_spec(_ref_spec)
_ref_spec.loader.exec_module(_ref_mod)
reference_compute = _ref_mod.compute_regime_daily_features


def _lim(p, caliber):
    return round(p * (1 + caliber), 2), round(p * (1 - caliber), 2)


def build_regime_equivalence_panel():
    """A deterministic panel rich enough to traverse EVERY regime branch (limit up/down/net, multi-day
    streak, promotion computed / thin-denom-null / prior-incomplete-null, failed-limit, ma20 null +
    computed, index present / missing / short-window, IV valid / none / out-of-range, ST caliber,
    stk_limit_history_incomplete, PIT) so the optimized==frozen equality below is not vacuous.

    Invariant respected: every chosen as_of day is fully usable for all its traded stocks (else the
    fail-closed gate would raise); the lone incomplete observation (``GHOST``: price, no usable limit)
    sits on a PRIOR day so it degrades history without being an as_of."""
    ds = _dates(36)
    drows = []
    lrows = []

    def add(day, code, high, close, up=None, down=None, with_limit=True):
        drows.append((day, code, high, close))
        if with_limit:
            lrows.append((day, code, up, down))

    for i, day in enumerate(ds):
        # 6 normal never-limit stocks (N0..N2 rising, N3..N5 falling) → MA20 eligibility + spread
        for k in range(6):
            base = max(10.0 + (i * 0.1 if k < 3 else -i * 0.05), 1.0)
            up, down = _lim(base, 0.10)
            add(day, f"N{k}", round(base * 1.02, 2), round(base, 2), up, down)
        # 6 promo stocks: all limit-up on ds[34]; only 4 again on ds[35] → promotion 5/7 incl streak
        for k in range(6):
            up, down = _lim(12.0, 0.10)
            if i == 34 or (i == 35 and k < 4):
                add(day, f"PROMO{k}", up, up, up, down)               # limit-up
            else:
                add(day, f"PROMO{k}", round(12.0 * 1.01, 2), 12.0, up, down)
        # STREAK: limit-up on the last 5 days → max_limit_streak 5
        up, down = _lim(15.0, 0.10)
        if i >= 31:
            add(day, "STREAK", up, up, up, down)
        else:
            add(day, "STREAK", round(15.0 * 1.01, 2), 15.0, up, down)
        # DOWN: limit-down only on the final day
        up, down = _lim(20.0, 0.10)
        if i == 35:
            add(day, "DOWN", 20.0, down, up, down)
        else:
            add(day, "DOWN", round(20.0 * 1.01, 2), 20.0, up, down)
        # FAILED: touched the up-limit but closed below it on the final day
        up, down = _lim(25.0, 0.10)
        if i == 35:
            add(day, "FAILED", up, round(up * 0.98, 2), up, down)
        else:
            add(day, "FAILED", round(25.0 * 1.01, 2), 25.0, up, down)
        # ST01: ±5% caliber (caliber smoke; stays mid)
        up, down = _lim(8.0, 0.05)
        add(day, "ST01", round(8.0 * 1.01, 2), 8.0, up, down)
        # GHOST: a prior-day incomplete observation (price present, NO usable limit) → history flag
        if i == 5:
            up, down = _lim(30.0, 0.10)
            add(day, "GHOST", 30.3, 30.0, up, down, with_limit=False)

    daily = _daily(drows)
    stk_limit = _limit(lrows)
    csi300 = _idx([(ds[i], 1000.0 + i * (2.0 if i % 2 else -1.0)) for i in range(36)])
    csi1000 = _idx([(ds[i], 2000.0 + i * 1.5) for i in range(36) if i != 30])   # missing at ds[30]
    iv_map = {ds[35]: 62.5, ds[25]: 10.0, ds[22]: 250.0}    # valid / valid / out-of-range
    as_ofs = [ds[3], ds[6], ds[10], ds[22], ds[25], ds[30], ds[35]]
    return daily, stk_limit, csi300, csi1000, iv_map, as_ofs


def build_regime_perf_panel(n_stocks=24, n_days=140, n_as_of=10):
    """A uniform fully-usable panel with MANY trade days; as_of sits at the tail so each call's window
    is deep. The frozen reference re-scans the full panel once per window-day (O(window) per call); the
    optimized engine groups once (O(panel) per call), so it must be dramatically faster here."""
    ds = _dates(n_days)
    drows = []
    lrows = []
    for i, day in enumerate(ds):
        for k in range(n_stocks):
            base = 10.0 + (k % 7) + (i % 13) * 0.1
            up, down = _lim(base, 0.10)
            drows.append((day, f"S{k}", round(base * 1.02, 2), round(base, 2)))
            lrows.append((day, f"S{k}", up, down))
    daily = _daily(drows)
    stk_limit = _limit(lrows)
    csi300 = _idx([(ds[i], 1000.0 + i) for i in range(n_days)])
    csi1000 = _idx([(ds[i], 2000.0 + i) for i in range(n_days)])
    return daily, stk_limit, csi300, csi1000, {}, ds[-n_as_of:]


class LimitCountTests(unittest.TestCase):
    def test_up_down_net_counts(self):
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0), (d, "B", 10.0, 9.0), (d, "C", 10.5, 10.0)])
        limit = _limit([(d, "A", 11.0, 9.0), (d, "B", 11.0, 9.0), (d, "C", 11.0, 9.0)])
        out = compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))
        self.assertEqual(out["limit_up_count"], 1)     # A only
        self.assertEqual(out["limit_down_count"], 1)   # B only
        self.assertEqual(out["net_limit"], 0)

    def test_st_caliber_respected(self):
        # both close at +5%; ST (up_limit=+5%) is limit-up, normal (up_limit=+10%) is not.
        d = "20240105"
        daily = _daily([(d, "ST", 10.5, 10.5), (d, "NORM", 10.5, 10.5)])
        limit = _limit([(d, "ST", 10.5, 9.5), (d, "NORM", 11.0, 9.0)])
        out = compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))
        self.assertEqual(out["limit_up_count"], 1)

    def test_missing_asof_limit_fails_closed(self):
        # R-V143-SLICE2B-FEATURES-ASOF-LIMIT-MISSING-METRIC-FABRICATION: no fabricated zero row.
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0)])
        with self.assertRaises(ValueError):
            compute_regime_daily_features(d, daily, _limit([]), _idx([]), _idx([]))

    def test_partial_asof_limit_fails_closed(self):
        # R-V143-SLICE2B-FEATURES-PARTIAL-STK-LIMIT-SILENT: 2 daily stocks, only 1 usable limit.
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 10.5), (d, "B", 11.0, 11.0)])
        limit = _limit([(d, "A", 11.0, 9.0)])   # B uncovered → fail closed
        with self.assertRaises(ValueError):
            compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))

    def test_unusable_asof_limit_values_fail_closed(self):
        # R-V143-SLICE2B-FEATURES-UNUSABLE-LIMIT-VALUES-SILENT: NaN/zero/negative up/down.
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0), (d, "B", 11.0, 11.0)])
        for bad_up, bad_down in ((float("nan"), 9.0), (0.0, 9.0), (11.0, 0.0), (11.0, -1.0)):
            limit = _limit([(d, "A", 11.0, 9.0), (d, "B", bad_up, bad_down)])
            with self.assertRaises(ValueError):
                compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))

    def test_partial_stk_limit_prior_day_nulls_promotion(self):
        ds = _dates(2)
        prev, today = ds
        # prev day has 5 up but one daily stock uncovered → promotion nulled
        rows_d = [(prev, f"P{i}", 11.0, 11.0) for i in range(5)] + [(prev, "X", 11.0, 11.0)]
        rows_l = [(prev, f"P{i}", 11.0, 9.0) for i in range(5)]   # X uncovered on prev
        rows_d += [(today, f"P{i}", 11.0, 11.0) for i in range(3)]
        rows_l += [(today, f"P{i}", 11.0, 9.0) for i in range(3)]
        out = compute_regime_daily_features(today, _daily(rows_d), _limit(rows_l), _idx([]), _idx([]))
        self.assertIsNone(out["promotion_rate"])                       # prior-day denom subset → null
        self.assertIn("stk_limit_history_incomplete", out["data_quality_flags"])


class SourcePanelIntegrityTests(unittest.TestCase):
    def test_bad_asof_daily_price_fails_closed(self):
        # R-V143-SLICE2B-FEATURES-ASOF-DAILY-PRICE-QUALITY
        d = "20240105"
        limit = _limit([(d, "A", 11.0, 9.0), (d, "B", 11.0, 9.0)])
        for bad_high, bad_close in ((float("nan"), 11.0), (11.0, 0.0), (5.0, 10.0)):   # NaN, zero, high<close
            daily = _daily([(d, "A", 11.0, 11.0), (d, "B", bad_high, bad_close)])
            with self.assertRaises(ValueError):
                compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))

    def test_duplicate_daily_rows_rejected(self):
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0), (d, "A", 10.0, 9.0)])   # conflicting dup
        limit = _limit([(d, "A", 11.0, 9.0)])
        with self.assertRaises(ValueError):
            compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))

    def test_duplicate_stk_limit_rows_rejected(self):
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0)])
        limit = _limit([(d, "A", 11.0, 9.0), (d, "A", 12.0, 9.0)])    # conflicting dup
        with self.assertRaises(ValueError):
            compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))

    def test_duplicate_index_rows_rejected(self):
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0)])
        limit = _limit([(d, "A", 11.0, 9.0)])
        dup_idx = _idx([(d, 100.0), (d, 50.0)])   # two same-date rows → would fabricate -50% ret
        with self.assertRaises(ValueError):
            compute_regime_daily_features(d, daily, limit, dup_idx, _idx([]))

    def test_noncanonical_panel_date_rejected(self):
        d = "20240105"
        daily = _daily([("2026-01-01", "A", 11.0, 11.0), (d, "A", 11.0, 11.0)])   # malformed prior date
        limit = _limit([(d, "A", 11.0, 9.0)])
        with self.assertRaises(ValueError):
            compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))

    def test_infinite_asof_price_fails_closed(self):
        # R-V143-SLICE2B-FEATURES-NONFINITE-NUMERIC-INPUTS: +Inf must not pass the >0 usable check.
        d = "20240105"
        limit = _limit([(d, "A", 11.0, 9.0)])
        daily = _daily([(d, "A", float("inf"), float("inf"))])
        with self.assertRaises(ValueError):
            compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))

    def test_infinite_asof_limit_fails_closed(self):
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0)])
        limit = _limit([(d, "A", float("inf"), float("inf"))])
        with self.assertRaises(ValueError):
            compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))

    def test_infinite_index_close_becomes_unavailable(self):
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0)])
        limit = _limit([(d, "A", 11.0, 9.0)])
        inf_idx = _idx([("20240104", 100.0), (d, float("inf"))])   # as_of close +Inf
        out = compute_regime_daily_features(d, daily, limit, inf_idx, inf_idx)
        self.assertIsNone(out["csi300_ret_1d"])                    # not an inf return
        self.assertIn("csi300_unavailable", out["data_quality_flags"])


class FailedLimitTests(unittest.TestCase):
    def test_failed_limit_rate(self):
        d = "20240105"
        # X touched up_limit (high>=up) but closed below → failed; Y touched and held → not failed.
        daily = _daily([(d, "X", 11.0, 10.5), (d, "Y", 11.0, 11.0)])
        limit = _limit([(d, "X", 11.0, 9.0), (d, "Y", 11.0, 9.0)])
        out = compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))
        self.assertAlmostEqual(out["failed_limit_rate"], 0.5)   # 1 failed / 2 touched

    def test_failed_limit_rate_none_when_no_touch(self):
        d = "20240105"
        daily = _daily([(d, "A", 10.0, 10.0)])
        limit = _limit([(d, "A", 11.0, 9.0)])
        out = compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))
        self.assertIsNone(out["failed_limit_rate"])


class StreakPromotionTests(unittest.TestCase):
    def test_max_limit_streak(self):
        ds = _dates(3)
        daily = _daily([(ds[i], "Z", 11.0, 11.0) for i in range(3)]      # Z up all 3 days
                       + [(ds[2], "W", 11.0, 11.0)])                      # W up only last day
        limit = _limit([(ds[i], "Z", 11.0, 9.0) for i in range(3)]
                       + [(ds[2], "W", 11.0, 9.0)])
        out = compute_regime_daily_features(ds[2], daily, limit, _idx([]), _idx([]))
        self.assertEqual(out["max_limit_streak"], 3)

    def test_promotion_rate(self):
        ds = _dates(2)
        prev, today = ds
        # 5 stocks limit-up on prev; 3 of them limit-up again today → 0.6
        rows_d, rows_l = [], []
        for i in range(5):
            c = f"P{i}"
            rows_d.append((prev, c, 11.0, 11.0)); rows_l.append((prev, c, 11.0, 9.0))
        for i in range(3):
            c = f"P{i}"
            rows_d.append((today, c, 11.0, 11.0)); rows_l.append((today, c, 11.0, 9.0))
        out = compute_regime_daily_features(today, _daily(rows_d), _limit(rows_l), _idx([]), _idx([]))
        self.assertAlmostEqual(out["promotion_rate"], 0.6)

    def test_promotion_thin_denom_null(self):
        ds = _dates(2)
        prev, today = ds
        daily = _daily([(prev, "A", 11.0, 11.0), (today, "A", 11.0, 11.0)])   # denom 1 < 5
        limit = _limit([(prev, "A", 11.0, 9.0), (today, "A", 11.0, 9.0)])
        out = compute_regime_daily_features(today, daily, limit, _idx([]), _idx([]))
        self.assertIsNone(out["promotion_rate"])
        self.assertIn("insufficient_sample", out["data_quality_flags"])


class BreadthIndexTests(unittest.TestCase):
    def test_pct_above_ma20_short_window_null(self):
        d = "20240105"
        daily = _daily([(d, "A", 10.0, 10.0)])
        out = compute_regime_daily_features(d, daily, _limit([(d, "A", 11.0, 9.0)]), _idx([]), _idx([]))
        self.assertIsNone(out["pct_above_ma20"])
        self.assertIn("ma20_insufficient_window", out["data_quality_flags"])

    def test_pct_above_ma20_computed(self):
        ds = _dates(MA_WINDOW)
        # one stock rising 10..29 → last close > 20d mean → above
        daily = _daily([(ds[i], "A", 10.0 + i, 10.0 + i) for i in range(MA_WINDOW)])
        limit = _limit([(ds[i], "A", 9999.0, 1.0) for i in range(MA_WINDOW)])
        out = compute_regime_daily_features(ds[-1], daily, limit, _idx([]), _idx([]))
        self.assertAlmostEqual(out["pct_above_ma20"], 100.0)

    def test_index_ret_and_below_ma20(self):
        ds = _dates(MA_WINDOW)
        rising = _idx([(ds[i], 100.0 + i) for i in range(MA_WINDOW)])     # last > mean → not below
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0)])
        limit = _limit([(d, "A", 11.0, 9.0)])
        # use as_of = ds[-1] so index window aligns
        daily2 = _daily([(ds[-1], "A", 11.0, 11.0)])
        limit2 = _limit([(ds[-1], "A", 11.0, 9.0)])
        out = compute_regime_daily_features(ds[-1], daily2, limit2, rising, rising)
        self.assertGreater(out["csi300_ret_1d"], 0)
        self.assertIs(out["csi1000_below_ma20"], False)

    def test_stale_index_flagged_unavailable(self):
        # R-V143-SLICE2B-FEATURES-STALE-INDEX-ASOF: index only through the day before as_of.
        ds = _dates(MA_WINDOW + 1)
        as_of = ds[-1]
        daily = _daily([(as_of, "A", 11.0, 11.0)])
        limit = _limit([(as_of, "A", 11.0, 9.0)])
        stale = _idx([(ds[i], 100.0 + i) for i in range(MA_WINDOW)])   # ends at ds[-2], not as_of
        out = compute_regime_daily_features(as_of, daily, limit, stale, stale)
        self.assertIsNone(out["csi300_ret_1d"])
        self.assertIsNone(out["csi1000_ret_1d"])
        self.assertIsNone(out["csi1000_below_ma20"])
        self.assertIn("csi300_unavailable", out["data_quality_flags"])
        self.assertIn("csi1000_unavailable", out["data_quality_flags"])

    def test_index_missing_flags(self):
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0)])
        out = compute_regime_daily_features(d, daily, _limit([(d, "A", 11.0, 9.0)]), _idx([]), _idx([]))
        self.assertIsNone(out["csi300_ret_1d"])
        self.assertIsNone(out["csi1000_ret_1d"])
        self.assertIsNone(out["csi1000_below_ma20"])
        self.assertIn("csi300_unavailable", out["data_quality_flags"])
        self.assertIn("csi1000_unavailable", out["data_quality_flags"])


class IvAndPitTests(unittest.TestCase):
    def test_iv_passthrough(self):
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0)])
        limit = _limit([(d, "A", 11.0, 9.0)])
        out = compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]), iv_percentile_252d=67.5)
        self.assertEqual(out["iv_percentile_252d"], 67.5)

    def test_iv_nan_none_and_out_of_range_flagged(self):
        # R-V143-SLICE2B-FEATURES-SCHEMA-INVALID-OUTPUT-GUARDS: IV outside [0,100] is invalid.
        d = "20240105"
        daily = _daily([(d, "A", 11.0, 11.0)])
        limit = _limit([(d, "A", 11.0, 9.0)])
        for bad in (None, float("nan"), float("inf"), 150.0, -5.0):
            out = compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]), iv_percentile_252d=bad)
            self.assertIsNone(out["iv_percentile_252d"])
            self.assertIn("iv_unavailable", out["data_quality_flags"])

    def test_rejects_noncanonical_as_of(self):
        # R-V143-SLICE2B-FEATURES-SCHEMA-INVALID-OUTPUT-GUARDS: malformed/impossible as_of.
        daily = _daily([("2024011", "A", 11.0, 11.0)])
        for bad in ("2024011", "20240231", "202401 1"):
            with self.assertRaises(ValueError):
                compute_regime_daily_features(bad, daily, _limit([]), _idx([]), _idx([]))

    def test_pit_ignores_future_rows(self):
        d = "20240105"
        future = "20240108"
        daily = _daily([(d, "A", 11.0, 11.0), (future, "A", 12.0, 12.0)])   # future row present
        limit = _limit([(d, "A", 11.0, 9.0), (future, "A", 12.0, 10.0)])
        out = compute_regime_daily_features(d, daily, limit, _idx([]), _idx([]))
        self.assertEqual(out["as_of"], d)
        self.assertEqual(out["limit_up_count"], 1)   # only the as_of day counted

    def test_raises_when_as_of_absent(self):
        daily = _daily([("20240104", "A", 11.0, 11.0)])
        with self.assertRaises(ValueError):
            compute_regime_daily_features("20240105", daily, _limit([]), _idx([]), _idx([]))


class IntegrationTests(unittest.TestCase):
    def _full_day(self):
        ds = _dates(MA_WINDOW)
        as_of = ds[-1]
        daily = _daily([(ds[i], "A", 10.0 + i, 10.0 + i) for i in range(MA_WINDOW)]
                       + [(ds[i], "B", 10.0, 10.0) for i in range(MA_WINDOW)])
        limit = _limit([(ds[i], "A", 9999.0, 1.0) for i in range(MA_WINDOW)]
                       + [(ds[i], "B", 9999.0, 1.0) for i in range(MA_WINDOW)])
        idx = _idx([(ds[i], 100.0 + i) for i in range(MA_WINDOW)])
        return compute_regime_daily_features(as_of, daily, limit, idx, idx, iv_percentile_252d=55.0)

    def test_row_passes_daily_schema(self):
        row = self._full_day()
        jsonschema.validate(row, json.loads(DAILY_SCHEMA.read_text(encoding="utf-8")))

    def test_row_passes_ledger_semantic_validator(self):
        row = self._full_day()
        self.assertEqual(daily_row_semantic_errors(row), [])   # finite floats, net_limit, real date

    def test_net_limit_identity(self):
        row = self._full_day()
        self.assertEqual(row["net_limit"], row["limit_up_count"] - row["limit_down_count"])


class OptimizationEquivalenceTests(unittest.TestCase):
    """The perf rewrite (group panels by trade_date once vs per-window-day full scans) must be
    output-preserving. Pin every emitted row byte-for-byte against the frozen pre-optimization
    reference across a branch-covering panel + as_of sequence, and pin the speedup."""

    def test_optimized_row_is_byte_identical_to_frozen_reference(self):
        daily, stk_limit, csi300, csi1000, iv_map, as_ofs = build_regime_equivalence_panel()
        seen_flags = set()
        saw_streak = saw_promo = saw_pct = saw_failed = False
        for a in as_ofs:
            iv = iv_map.get(a)
            opt = compute_regime_daily_features(a, daily, stk_limit, csi300, csi1000,
                                                iv_percentile_252d=iv)
            ref = reference_compute(a, daily, stk_limit, csi300, csi1000, iv_percentile_252d=iv)
            self.assertEqual(opt, ref, f"optimized output diverged from frozen reference at as_of {a}")
            seen_flags.update(opt["data_quality_flags"])
            saw_streak = saw_streak or opt["max_limit_streak"] > 1
            saw_promo = saw_promo or opt["promotion_rate"] is not None
            saw_pct = saw_pct or opt["pct_above_ma20"] is not None
            saw_failed = saw_failed or opt["failed_limit_rate"] is not None
        # guard against a vacuous equality: the panel must actually exercise the interesting branches
        for f in ("stk_limit_history_incomplete", "insufficient_sample", "ma20_insufficient_window",
                  "csi1000_unavailable", "iv_unavailable"):
            self.assertIn(f, seen_flags, f"equivalence panel never produced flag {f!r}")
        self.assertTrue(saw_streak and saw_promo and saw_pct and saw_failed,
                        "equivalence panel did not traverse streak/promotion/ma20/failed-limit metrics")

    def test_future_dated_duplicate_stk_limit_is_ignored_pit(self):
        # R-V143-REGIME-PIT-FUTURE-DUP-STKLIMIT-REGRESSION: a DUPLICATE stk_limit row at a date AFTER
        # as_of is not seen by the (<= as_of) uniqueness check; under the "rows > as_of ignored"
        # contract it must be dropped, exactly as the frozen reference does — never inflating merge
        # cardinality into a raise, nor altering the current row. (Reverse guard: a duplicate AT/<= as_of
        # must still raise — covered by SourcePanelIntegrityTests.test_duplicate_stk_limit_rows_rejected.)
        as_of = "20240120"
        daily = _daily([(as_of, "A", 11.0, 11.0), ("20240121", "A", 12.0, 12.0)])   # + a future row
        stk = _limit([(as_of, "A", 11.0, 9.0),
                      ("20240121", "A", 12.0, 10.0), ("20240121", "A", 12.0, 10.0)])  # future duplicate
        empty = _idx([])
        opt = compute_regime_daily_features(as_of, daily, stk, empty, empty)
        ref = reference_compute(as_of, daily, stk, empty, empty)
        self.assertEqual(opt, ref, "future-dated duplicate stk_limit must be ignored like the reference")
        self.assertEqual(opt["limit_up_count"], 1)     # as_of row counted; future dup neither counts nor raises

    def test_optimized_matches_reference_on_deep_panel(self):
        # identity must also hold when there are MANY trade-day groups (group-once path), not just the
        # 36-day equivalence panel — this is the 252-day-bootstrap recompute shape (same panel, tail as_of).
        daily, stk_limit, csi300, csi1000, _iv, as_ofs = build_regime_perf_panel(
            n_stocks=12, n_days=120, n_as_of=4)
        for a in as_ofs:
            self.assertEqual(compute_regime_daily_features(a, daily, stk_limit, csi300, csi1000),
                             reference_compute(a, daily, stk_limit, csi300, csi1000),
                             f"optimized != frozen reference on deep panel at as_of {a}")

    def test_runtime_is_linear_in_trade_day_depth_not_quadratic(self):
        # The win is asymptotic: per call the optimization replaces an O(window) per-window-day
        # full-panel rescan with ONE group-by, so cost is ~linear in trade-day depth. Quadrupling the
        # depth (same stocks / as_of count) must grow wall time far below the ~16x a reintroduced
        # quadratic rescan would cost. We time only the (fast) optimized engine, best-of-2 to damp noise.
        def timed(n_days):
            daily, sl, c3, c1, _iv, as_ofs = build_regime_perf_panel(
                n_stocks=16, n_days=n_days, n_as_of=3)
            best = float("inf")
            for _ in range(2):
                compute_regime_daily_features(as_ofs[-1], daily, sl, c3, c1)   # warmup
                t0 = time.perf_counter()
                for a in as_ofs:
                    compute_regime_daily_features(a, daily, sl, c3, c1)
                best = min(best, time.perf_counter() - t0)
            return best

        base = max(timed(70), 1e-3)
        deep = timed(280)        # 4x the trade-day depth
        self.assertLess(deep, base * 8.0,
                        f"runtime grew {deep / base:.1f}x for 4x trade-day depth (expected ~4x linear) "
                        f"— near-quadratic; the per-window-day full-panel rescan may have regressed")


if __name__ == "__main__":
    unittest.main()
