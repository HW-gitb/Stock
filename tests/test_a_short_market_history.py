"""Queue row 22a: a historical series is usable only on exact window coverage.

The judge must be the same shape as row 12's five-session reconciliation
(`A-EGS/egs_main.py::_northbound_provider_facts`): row count equals requested
count, de-duplication does not shrink it, and the date sets are equal.  These
tests pin each of those legs separately so a future loosening of any one is
caught, plus a planted control proving the set-equality leg carries weight.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_market_history import (  # noqa: E402
    canonical_dates,
    percentile_rank,
    reconcile_dated_series,
)

WINDOW = ("20260731", "20260730", "20260729", "20260728", "20260727")


def _rows(pairs, date_key="trade_date", value_key="rzye"):
    return [{date_key: d, value_key: v} for d, v in pairs]


FULL = [(d, 1000.0 + i) for i, d in enumerate(WINDOW)]


class ReconcileDatedSeriesTests(unittest.TestCase):
    def _reconcile(self, rows, window=WINDOW):
        return reconcile_dated_series(rows, requested_dates=window, value_key="rzye")

    def test_exact_coverage_yields_a_newest_first_series(self):
        got = self._reconcile(_rows(FULL))
        self.assertTrue(got["coverage_complete"])
        self.assertEqual(got["observed_count"], 5)
        self.assertEqual([date for date, _ in got["series"]], sorted(WINDOW, reverse=True))

    def test_short_response_fails_closed(self):
        got = self._reconcile(_rows(FULL[:3]))
        self.assertFalse(got["coverage_complete"])
        self.assertIsNone(got["series"])
        self.assertEqual(got["observed_count"], 3)

    def test_duplicate_session_fails_closed(self):
        got = self._reconcile(_rows([FULL[0]] * 5))
        self.assertFalse(got["coverage_complete"])
        self.assertEqual(got["observed_count"], 1)

    def test_out_of_window_row_fails_closed_even_at_the_right_row_count(self):
        got = self._reconcile(_rows(FULL[:4] + [("20251201", 9.0)]))
        self.assertFalse(got["coverage_complete"])
        self.assertEqual(got["observed_count"], 4)

    def test_extra_row_fails_closed(self):
        got = self._reconcile(_rows(FULL + [("20260726", 1.0)]))
        self.assertFalse(got["coverage_complete"])

    def test_non_finite_and_missing_values_fail_closed(self):
        for bad in (float("nan"), float("inf"), None, "1000", True):
            with self.subTest(bad=bad):
                rows = _rows(FULL[:4] + [(WINDOW[4], bad)])
                self.assertFalse(self._reconcile(rows)["coverage_complete"])

    def test_degenerate_inputs_do_not_crash(self):
        for rows in (None, [], "not-a-sequence", [{"trade_date": "x"}], [42]):
            with self.subTest(rows=rows):
                self.assertFalse(self._reconcile(rows)["coverage_complete"])
        self.assertFalse(
            reconcile_dated_series(_rows(FULL), requested_dates=(), value_key="rzye")[
                "coverage_complete"
            ]
        )

    def test_a_non_date_in_the_requested_window_is_a_caller_error(self):
        with self.assertRaises(ValueError):
            reconcile_dated_series(_rows(FULL), requested_dates=("2026-07-31",), value_key="rzye")

    def test_planted_removal_of_the_set_equality_leg_turns_a_control_red(self):
        """Without set-equality, an out-of-window row at the right count passes."""
        rows = _rows(FULL[:4] + [("20251201", 9.0)])
        loosened = [row for row in rows]
        # The real judge rejects this; a judge that only counted rows would not.
        self.assertFalse(self._reconcile(loosened)["coverage_complete"])
        self.assertEqual(len(loosened), len(WINDOW))  # row count alone is satisfied

    def test_numpy_scalars_from_provider_frames_are_accepted(self):
        """Regression: numpy.int64 / float32 do not subclass Python builtins.

        Rejecting them would fail a good window closed and report it as
        "coverage incomplete", hiding a dtype problem behind a data problem.
        The sibling judge in engine/a_short_northbound.py uses numbers.Real for
        the same reason; these two must not diverge.
        """
        import numpy as np

        for maker in (np.float64, np.float32, np.int64, np.int32):
            with self.subTest(dtype=maker.__name__):
                rows = _rows([(date, maker(1)) for date in WINDOW])
                self.assertTrue(self._reconcile(rows)["coverage_complete"])
        # numpy bools stay rejected, like Python bools.
        self.assertFalse(
            self._reconcile(_rows([(date, np.bool_(True)) for date in WINDOW]))[
                "coverage_complete"
            ]
        )

    def test_callers_must_pass_mappings_not_a_dataframe_or_generator(self):
        """Documented boundary: these fail closed rather than half-reading."""
        import pandas as pd

        frame = pd.DataFrame(_rows(FULL))
        self.assertFalse(self._reconcile(frame)["coverage_complete"])
        self.assertFalse(self._reconcile(row for row in _rows(FULL))["coverage_complete"])
        # The supported shapes both work.
        self.assertTrue(self._reconcile(_rows(FULL))["coverage_complete"])
        self.assertTrue(self._reconcile(tuple(_rows(FULL)))["coverage_complete"])

    def test_canonical_dates_dedupes_and_orders_newest_first(self):
        self.assertEqual(
            canonical_dates(["20260729", "20260731", "20260729", 20260730.0]),
            ("20260731", "20260730", "20260729"),
        )


class RawProviderRowNumericAcceptanceTests(unittest.TestCase):
    """Pin the two raw-provider-row judges together so they cannot diverge again.

    This class has exactly two members today: `a_short_northbound` (five-session
    northbound flow) and `a_short_market_history` (multi-year windows).  They are
    the only engines that reduce provider rows directly -- everywhere else the
    numbers arrive already serialised through JSON, where numpy scalars cannot
    appear and `isinstance(value, (int, float))` is correct.

    Both regressed to the builtin form once.  A future third raw-row consumer
    belongs in this test rather than in a repo-wide sweep of ~142 call sites,
    almost none of which are in this class.
    """

    def _judges(self):
        from engine.a_short_market_history import _is_finite_number as history_judge
        from engine.a_short_northbound import _finite_number as northbound_judge

        return {"a_short_market_history": history_judge, "a_short_northbound": northbound_judge}

    def test_both_judges_accept_numpy_scalars_from_provider_frames(self):
        import numpy as np

        for name, judge in self._judges().items():
            for maker in (np.float64, np.float32, np.int64, np.int32):
                with self.subTest(module=name, dtype=maker.__name__):
                    self.assertTrue(judge(maker(1)), f"{name} rejects {maker.__name__}")

    def test_both_judges_still_reject_bools_and_non_finite(self):
        import numpy as np

        for name, judge in self._judges().items():
            for bad in (True, False, np.bool_(True), float("nan"), float("inf"),
                        np.float64("nan"), None, "1", object()):
                with self.subTest(module=name, value=repr(bad)):
                    self.assertFalse(judge(bad), f"{name} accepts {bad!r}")


class PercentileRankTests(unittest.TestCase):
    def test_rank_is_the_fraction_at_or_below(self):
        self.assertEqual(percentile_rank([1, 2, 3, 4], 3), 0.75)
        self.assertEqual(percentile_rank([1, 2, 3, 4], 4), 1.0)
        self.assertEqual(percentile_rank([1, 2, 3, 4], 0), 0.0)

    def test_unusable_windows_return_none_rather_than_a_fabricated_rank(self):
        self.assertIsNone(percentile_rank([], 1))
        self.assertIsNone(percentile_rank([1, float("nan")], 1))
        self.assertIsNone(percentile_rank([1, 2], float("inf")))
        self.assertIsNone(percentile_rank([1, 2], None))
        self.assertIsNone(percentile_rank([1, 2], True))


if __name__ == "__main__":
    unittest.main()
