from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_momentum import compute_momentum_features  # noqa: E402
from engine.us_short_momentum_grouped_reconstruct import (  # noqa: E402
    MomentumGroupedReconstructError,
    reconstruct_series_from_grouped,
)


def _session(date: str, rows: list[dict]) -> dict:
    return {"date": date, "rows": rows}


class ReconstructSeriesFromGroupedTest(unittest.TestCase):
    def _base_kwargs(self):
        return {
            "tickers": ["AAPL", "MSFT", "SPY"],
            "as_of": "2026-07-02",
            "session": "regular",
            "adjustment_mode": "split_dividend_adjusted",
        }

    def test_groups_rows_into_ascending_per_ticker_series(self):
        grouped = [
            _session("2026-06-30", [{"ticker": "AAPL", "close": 10.0, "volume": 100},
                                    {"ticker": "MSFT", "close": 20.0, "volume": 200}]),
            _session("2026-07-01", [{"ticker": "AAPL", "close": 11.0, "volume": 110},
                                    {"ticker": "MSFT", "close": 21.0, "volume": 210}]),
            _session("2026-07-02", [{"ticker": "AAPL", "close": 12.0, "volume": 120}]),
        ]
        out = reconstruct_series_from_grouped(grouped, **self._base_kwargs())
        self.assertEqual(set(out), {"AAPL", "MSFT"})  # SPY requested but absent from every session -> omitted
        self.assertEqual(out["AAPL"]["as_of"], "2026-07-02")
        self.assertEqual(out["AAPL"]["session"], "regular")
        self.assertEqual(out["AAPL"]["adjustment_mode"], "split_dividend_adjusted")
        self.assertEqual(
            out["AAPL"]["points"],
            [
                {"date": "2026-06-30", "close": 10.0, "volume": 100},
                {"date": "2026-07-01", "close": 11.0, "volume": 110},
                {"date": "2026-07-02", "close": 12.0, "volume": 120},
            ],
        )
        # MSFT is missing from the last session -> that date is a GAP, omitted (never zero-filled).
        self.assertEqual([p["date"] for p in out["MSFT"]["points"]], ["2026-06-30", "2026-07-01"])

    def test_raw_close_volume_pass_through_unvalidated_engine_owns_cleaning(self):
        # A non-positive close is NOT rejected here (the engine's _clean_series owns that); it passes through.
        grouped = [_session("2026-07-01", [{"ticker": "AAPL", "close": -1.0}])]
        out = reconstruct_series_from_grouped(grouped, **self._base_kwargs())
        self.assertEqual(out["AAPL"]["points"], [{"date": "2026-07-01", "close": -1.0}])

    def test_missing_close_is_omitted_as_a_gap(self):
        grouped = [
            _session("2026-07-01", [{"ticker": "AAPL", "close": 10.0}]),
            _session("2026-07-02", [{"ticker": "AAPL", "volume": 5}]),  # no close -> gap
            _session("2026-07-03", [{"ticker": "AAPL", "close": 12.0}]),
        ]
        out = reconstruct_series_from_grouped(grouped, **self._base_kwargs())
        self.assertEqual([p["date"] for p in out["AAPL"]["points"]], ["2026-07-01", "2026-07-03"])
        self.assertNotIn("volume", out["AAPL"]["points"][0])  # volume omitted when absent

    def test_non_ascending_or_duplicate_session_dates_fail_closed(self):
        for dates in (["2026-07-02", "2026-07-01"], ["2026-07-01", "2026-07-01"]):
            grouped = [_session(d, [{"ticker": "AAPL", "close": 1.0}]) for d in dates]
            with self.assertRaises(MomentumGroupedReconstructError):
                reconstruct_series_from_grouped(grouped, **self._base_kwargs())

    def test_duplicate_ticker_within_a_session_fails_closed(self):
        grouped = [_session("2026-07-01", [{"ticker": "AAPL", "close": 1.0},
                                           {"ticker": "AAPL", "close": 2.0}])]
        with self.assertRaises(MomentumGroupedReconstructError):
            reconstruct_series_from_grouped(grouped, **self._base_kwargs())

    def test_malformed_shapes_fail_closed(self):
        good = self._base_kwargs()
        bad_inputs = [
            ("not-a-list", good),
            ([{"date": "2026-07-01", "rows": "not-a-list"}], good),
            ([{"date": "20260701", "rows": []}], good),  # wrong date format
            ([{"rows": []}], good),  # missing date
            (["not-a-dict"], good),
            ([_session("2026-07-01", ["not-a-dict"])], good),
        ]
        for grouped, kwargs in bad_inputs:
            with self.assertRaises(MomentumGroupedReconstructError):
                reconstruct_series_from_grouped(grouped, **kwargs)
        # bad clock / ticker inputs
        with self.assertRaises(MomentumGroupedReconstructError):
            reconstruct_series_from_grouped([], tickers=["AAPL"], as_of="2026/07/02",
                                            session="regular", adjustment_mode="split_dividend_adjusted")
        with self.assertRaises(MomentumGroupedReconstructError):
            reconstruct_series_from_grouped([], tickers=[""], as_of="2026-07-02",
                                            session="regular", adjustment_mode="split_dividend_adjusted")

    def test_reconstructed_series_is_engine_compatible(self):
        # 64 ascending sessions (> LOOKBACK_3M=63) with strictly rising closes -> the engine parses the
        # reconstructed shape and computes the core return features (proves shape compatibility end-to-end).
        grouped = [
            _session(f"2026-0{1 + (i // 28)}-{(i % 28) + 1:02d}", [{"ticker": "AAPL", "close": 100.0 + i, "volume": 1000 + i}])
            for i in range(64)
        ]
        out = reconstruct_series_from_grouped(
            grouped, tickers=["AAPL"], as_of="2026-03-08", session="regular", adjustment_mode="split_dividend_adjusted"
        )
        computed = compute_momentum_features(out["AAPL"])
        self.assertIn("ret_1m", computed["features"])
        self.assertIn("ret_3m", computed["features"])
        self.assertGreater(computed["n_features"], 0)


if __name__ == "__main__":
    unittest.main()
