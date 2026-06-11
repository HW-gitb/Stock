"""Tests for V14.3 comparison-record forward-return backfill + panel render (slice 2b-impl ②a, pure).

Pins: backfill fills only elapsed horizons (no look-ahead); an existing non-null value is audited
against the deterministic CSI1000 return and raises on mismatch / not-yet-elapsed (only a matching
value is preserved); horizons stay null when the target close is missing / non-finite / non-positive
or the anchor is absent; rejects non-canonical / duplicate index dates. summarize/render are the
AUDITED evidence path (require csi1000 + as_of_now, run backfill internally) so a fabricated record
cannot advance the evidence count. No data fetch.
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

from engine.a_short_regime_comparison import (  # noqa: E402
    backfill_forward_returns, summarize_comparison_records, render_regime_comparison_block,
)
from engine.a_short_regime_classifier import (  # noqa: E402
    validate_comparison_record, FORWARD_RETURN_BASIS,
)


def _dates(n, start=date(2024, 1, 2)):
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def _idx(rows):
    return pd.DataFrame(rows, columns=["trade_date", "close"])


_FIRED = {"shock": "residual", "defense": "broad_index_crash",
          "attack": "attack_all_of", "contraction": "slow_bleed"}


def _rec(as_of, v2="shock", v3="shock", fired=None, fr=None):
    fired = fired or _FIRED[v3]
    fwd = {h: (fr or {}).get(h) for h in ("h1", "h3", "h5", "h10")}
    pending = [h for h in ("h1", "h3", "h5", "h10") if fwd[h] is None]
    rec = {
        "schema_name": "a_short_regime_comparison_weekly", "schema_version": "1.0.0",
        "as_of": as_of, "generated_at": None,
        "v14_2_regime": v2, "v14_3_raw_regime": v3, "divergence": v2 != v3,
        "v14_3_fired_rule": fired, "v14_3_window_n": 252, "v14_3_insufficient_window": False,
        "data_quality_flags": [],
        "forward_returns": fwd, "forward_returns_pending": pending, "backfill_complete": not pending,
        "forward_return_basis": dict(FORWARD_RETURN_BASIS),
        "boundary": {"production": False, "comparison_only": True,
                     "drives_phase5_risk_posture": False, "mixes_with_overlay_star_or_m67_action": False},
    }
    validate_comparison_record(rec)
    return rec


class BackfillTests(unittest.TestCase):
    def _rising_idx(self, n):
        ds = _dates(n)
        return ds, _idx([(ds[i], 100.0 + i) for i in range(n)])

    def test_fills_all_elapsed_horizons(self):
        ds, idx = self._rising_idx(11)
        rec = _rec(ds[0])
        out = backfill_forward_returns([rec], idx)[0]
        self.assertAlmostEqual(out["forward_returns"]["h1"], 1.0)     # 101/100-1
        self.assertAlmostEqual(out["forward_returns"]["h3"], 3.0)
        self.assertAlmostEqual(out["forward_returns"]["h5"], 5.0)
        self.assertAlmostEqual(out["forward_returns"]["h10"], 10.0)
        self.assertTrue(out["backfill_complete"])
        self.assertEqual(out["forward_returns_pending"], [])

    def test_pit_caps_unelapsed_horizons(self):
        ds, idx = self._rising_idx(11)
        out = backfill_forward_returns([_rec(ds[0])], idx, as_of_now=ds[4])[0]
        self.assertAlmostEqual(out["forward_returns"]["h1"], 1.0)
        self.assertAlmostEqual(out["forward_returns"]["h3"], 3.0)
        self.assertIsNone(out["forward_returns"]["h5"])              # ds[5] > as_of_now
        self.assertIsNone(out["forward_returns"]["h10"])
        self.assertEqual(set(out["forward_returns_pending"]), {"h5", "h10"})

    def test_anchor_missing_leaves_all_null(self):
        ds, idx = self._rising_idx(11)
        out = backfill_forward_returns([_rec("20991231")], idx)[0]
        self.assertEqual(out["forward_returns_pending"], ["h1", "h3", "h5", "h10"])

    def test_nonfinite_target_close_leaves_horizon_null(self):
        ds = _dates(11)
        rows = [(ds[i], 100.0 + i) for i in range(11)]
        rows[5] = (ds[5], float("nan"))      # h5 target close NaN
        out = backfill_forward_returns([_rec(ds[0])], _idx(rows))[0]
        self.assertAlmostEqual(out["forward_returns"]["h3"], 3.0)
        self.assertIsNone(out["forward_returns"]["h5"])
        self.assertAlmostEqual(out["forward_returns"]["h10"], 10.0)

    def test_matching_existing_preserved_without_overwrite(self):
        # (c) an existing value that matches the deterministic return is kept (no raise, no change).
        ds, idx = self._rising_idx(11)
        out = backfill_forward_returns([_rec(ds[0], fr={"h1": 1.0})], idx)[0]
        self.assertAlmostEqual(out["forward_returns"]["h1"], 1.0)

    def test_existing_mismatch_raises(self):
        # (a) R-V143-SLICE2B-COMPARISON-EXISTING-FWD-RETURN-PIT-CONFLICT-BYPASS: stored != recomputed.
        ds, idx = self._rising_idx(11)
        with self.assertRaises(ValueError):
            backfill_forward_returns([_rec(ds[0], fr={"h1": 999.0})], idx)

    def test_existing_not_elapsed_raises(self):
        # (b) prefilled horizon whose target has not elapsed under as_of_now → look-ahead → raise.
        ds, idx = self._rising_idx(11)
        with self.assertRaises(ValueError):
            backfill_forward_returns([_rec(ds[0], fr={"h1": 1.0})], idx, as_of_now=ds[0])

    def test_rejects_duplicate_index_date(self):
        ds = _dates(11)
        rows = [(ds[i], 100.0 + i) for i in range(11)] + [(ds[0], 50.0)]
        with self.assertRaises(ValueError):
            backfill_forward_returns([_rec(ds[0])], _idx(rows))

    def test_rejects_noncanonical_index_date(self):
        ds = _dates(11)
        rows = [("2024-01-02", 100.0)] + [(ds[i], 100.0 + i) for i in range(1, 11)]
        with self.assertRaises(ValueError):
            backfill_forward_returns([_rec(ds[0])], _idx(rows))

    def test_updated_record_stays_valid(self):
        ds, idx = self._rising_idx(11)
        out = backfill_forward_returns([_rec(ds[0])], idx)[0]
        self.assertTrue(validate_comparison_record(out))

    def test_nonpositive_target_close_leaves_horizon_null(self):
        # R-V143-SLICE2B-COMPARISON-NONPOSITIVE-INDEX-CLOSE: 0/negative close must not fill -100%.
        ds = _dates(11)
        for bad in (0.0, -1.0):
            rows = [(ds[i], 100.0 + i) for i in range(11)]
            rows[1] = (ds[1], bad)   # h1 target
            out = backfill_forward_returns([_rec(ds[0])], _idx(rows))[0]
            self.assertIsNone(out["forward_returns"]["h1"])
            self.assertAlmostEqual(out["forward_returns"]["h3"], 3.0)


class EvidenceIntegrityTests(unittest.TestCase):
    """R-V143-SLICE2B-COMPARISON-UNVALIDATED-EVIDENCE-COUNT + RENDER-SUMMARY-BACKFILL-AUDIT-BYPASS:
    the summarize/render evidence path audits via backfill, so bad/fabricated/duplicate can't count."""

    def test_summarize_rejects_fabricated_forward(self):
        # a shape-valid but numerically fabricated h1 must NOT advance evidence (backfill audit raises).
        ds = _dates(11)
        idx = _idx([(ds[i], 100.0 + i) for i in range(11)])
        with self.assertRaises(ValueError):
            summarize_comparison_records([_rec(ds[0], fr={"h1": 999.0})], idx, ds[-1])

    def test_summarize_rejects_invalid_record(self):
        bad = _rec("20240102")
        bad["divergence"] = True                  # v14_2==v14_3==shock → must be False (validate raises)
        with self.assertRaises(ValueError):
            summarize_comparison_records([bad], _idx([]), "20240102")

    def test_summarize_rejects_duplicate_as_of(self):
        with self.assertRaises(ValueError):
            summarize_comparison_records([_rec("20240102"), _rec("20240102")], _idx([]), "20240102")

    def test_render_rejects_fabricated_current_record(self):
        ds = _dates(11)
        idx = _idx([(ds[i], 100.0 + i) for i in range(11)])
        with self.assertRaises(ValueError):
            render_regime_comparison_block(_rec(ds[0], fr={"h1": 999.0}), idx, ds[-1])

    def test_render_rejects_invalid_current_record(self):
        bad = _rec("20240102")
        bad["divergence"] = True                  # v14_2==v14_3==shock → must be False
        with self.assertRaises(ValueError):
            render_regime_comparison_block(bad, _idx([]), "20240102")

    def test_summarize_render_require_as_of_now(self):
        # R-V143-SLICE2B-COMPARISON-AUDITED-PATH-ASOF-NOW-OPTIONAL: no unaudited/uncapped path.
        rec = _rec("20240102")
        with self.assertRaises(TypeError):
            summarize_comparison_records([rec], _idx([]))          # omitted → no default
        with self.assertRaises(ValueError):
            summarize_comparison_records([rec], _idx([]), None)    # explicit None
        with self.assertRaises(ValueError):
            summarize_comparison_records([rec], _idx([]), "2024")  # non-canonical
        with self.assertRaises(TypeError):
            render_regime_comparison_block(rec, _idx([]))
        with self.assertRaises(ValueError):
            render_regime_comparison_block(rec, _idx([]), None)

    def test_summarize_rejects_future_record(self):
        # R-V143-SLICE2B-COMPARISON-FUTURE-ASOF-COUNTS: a record dated after the cap can't count.
        with self.assertRaises(ValueError):
            summarize_comparison_records([_rec("20991231")], _idx([]), "20240112")

    def test_render_rejects_future_current_record(self):
        with self.assertRaises(ValueError):
            render_regime_comparison_block(_rec("20991231"), _idx([]), "20240112")

    def test_render_requires_current_present_in_history(self):
        # R-V143-SLICE2B-COMPARISON-RENDER-HISTORY-CURRENT-MISMATCH: current must be in records.
        cur = _rec("20240103", v3="attack")
        with self.assertRaises(ValueError):
            render_regime_comparison_block(cur, _idx([]), "20240103", records=[_rec("20240102")])

    def test_render_rejects_current_payload_mismatch(self):
        cur = _rec("20240103", v3="attack")
        other_payload = _rec("20240103", v3="shock")   # same as_of, different regime/divergence
        with self.assertRaises(ValueError):
            render_regime_comparison_block(cur, _idx([]), "20240103", records=[other_payload])

    def test_asof_cap_leaves_future_horizons_pending(self):
        # an as-of cap at the anchor must leave all horizons pending even if csi1000 has future rows.
        ds = _dates(11)
        idx = _idx([(ds[i], 100.0 + i) for i in range(11)])       # full future series
        s = summarize_comparison_records([_rec(ds[0])], idx, ds[0])   # cap at anchor day
        self.assertEqual(s["backfill_complete_weeks"], 0)
        block = render_regime_comparison_block(_rec(ds[0]), idx, ds[0])
        self.assertIn("pending", block)


class SummaryRenderTests(unittest.TestCase):
    def test_summarize_counts(self):
        recs = [_rec("20240102", v3="defense"), _rec("20240103"), _rec("20240104", v3="attack")]
        s = summarize_comparison_records(recs, _idx([]), "20240104")   # all-null, no anchor → clean
        self.assertEqual(s["total_weeks"], 3)
        self.assertEqual(s["divergence_weeks"], 2)        # two differ from v14_2 'shock'

    def test_render_contains_panel_fields(self):
        ds, idx = _dates(11), _idx([(d, 100.0 + i) for i, d in enumerate(_dates(11))])
        rec = backfill_forward_returns([_rec(ds[0], v3="defense")], idx, as_of_now=ds[2])[0]
        block = render_regime_comparison_block(rec, idx, as_of_now=ds[2], records=[rec])
        self.assertIn("comparison-only", block)
        self.assertIn("非生产", block)
        self.assertIn("defense", block)
        self.assertIn("pending", block)                  # h5/h10 not elapsed at as_of_now=ds[2]
        self.assertIn("/", block)                        # evidence n/gate
        self.assertIn("overlay", block)                  # the explicit do-not-mix disclaimer

    def test_render_without_records_shows_gate_only(self):
        block = render_regime_comparison_block(_rec("20240102"), _idx([]), "20240102")
        self.assertIn("周", block)


if __name__ == "__main__":
    unittest.main()
