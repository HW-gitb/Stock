"""The limit-up index probe must not report a clean negative over a cut-short universe.

The probe's whole value is the word "no".  A single ``index_basic`` call is
capped at 8000 rows and the CSI universe exceeds it, so a probe that took the
first page as the whole universe would report "no such index exists" after
searching 92% of it -- the same truncation that made row 22b's first northbound
lookback wrong.  These tests pin the pagination and, more importantly, pin that
an unexhausted universe downgrades the verdict instead of passing silently.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from runners import a_short_limit_up_index_source_probe as probe


PAGE = probe.INDEX_BASIC_PAGE_SIZE


def _frame(names: list[str], start: int = 0) -> pd.DataFrame:
    return pd.DataFrame({
        "ts_code": [f"{start + i:06d}.SH" for i in range(len(names))],
        "name": names,
        "market": ["CSI"] * len(names),
    })


class _FakeClient:
    """Serves fixed pages per market and records what was asked for."""

    def __init__(self, pages_by_market: dict[str, list[pd.DataFrame]],
                 ths_error: Exception | None = None) -> None:
        self._pages = pages_by_market
        self._ths_error = ths_error
        self.calls: list[dict] = []

    def index_basic(self, *, market: str, offset: int = 0, limit: int = PAGE):
        self.calls.append({"endpoint": "index_basic", "market": market, "offset": offset})
        pages = self._pages.get(market, [_frame([])])
        index = offset // PAGE
        return pages[index] if index < len(pages) else _frame([])

    def ths_index(self):
        self.calls.append({"endpoint": "ths_index"})
        if self._ths_error is not None:
            raise self._ths_error
        return _frame([])

    def index_daily(self, *, ts_code: str, start_date: str, end_date: str):
        self.calls.append({"endpoint": "index_daily", "ts_code": ts_code})
        return pd.DataFrame({"ts_code": [ts_code], "trade_date": [start_date], "close": [1.0]})


def _all_markets(**overrides) -> dict[str, list[pd.DataFrame]]:
    pages = {market: [_frame([])] for market in probe.INDEX_BASIC_MARKETS}
    pages.update(overrides)
    return pages


class LimitUpIndexSourceProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.raw_root = Path(self._tmp.name) / "raw"
        self.addCleanup(self._tmp.cleanup)

    def _run(self, client) -> dict:
        return probe.run_probe(client, raw_root=self.raw_root)

    def test_a_universe_larger_than_one_page_is_paged_until_a_short_page_proves_it_is_done(self):
        full = _frame([f"index {i}" for i in range(PAGE)])
        tail = _frame(["tail a", "tail b"], start=PAGE)
        client = _FakeClient(_all_markets(CSI=[full, tail]))

        summary = self._run(client)

        self.assertEqual(summary["universe_coverage"]["CSI"]["pages"], 2)
        self.assertEqual(summary["universe_coverage"]["CSI"]["rows"], PAGE + 2)
        self.assertTrue(summary["universe_coverage"]["CSI"]["exhausted"])
        offsets = [c["offset"] for c in client.calls
                   if c["endpoint"] == "index_basic" and c["market"] == "CSI"]
        self.assertEqual(offsets, [0, PAGE])

    def test_a_clean_negative_requires_every_universe_to_be_exhausted(self):
        full = _frame([f"index {i}" for i in range(PAGE)])
        tail = _frame(["tail"], start=PAGE)
        summary = self._run(_FakeClient(_all_markets(CSI=[full, tail])))

        self.assertEqual(summary["verdict"], "no_matching_published_index_reachable")
        self.assertEqual(summary["candidate_count"], 0)
        self.assertEqual(summary["universes_left_incomplete"], [])
        self.assertEqual(summary["indices_searched"], PAGE + 1)

    def test_an_unexhausted_universe_downgrades_the_verdict_instead_of_reading_as_no(self):
        """The row-22b class: a truncated fetch must never read as a finished search."""
        # Every page is exactly full, so a short page never arrives and the
        # budget runs out first -- precisely what a silent row cap looks like.
        client = _FakeClient(_all_markets(
            CSI=[_frame([f"index {i}" for i in range(PAGE)]) for _ in range(50)]
        ))

        summary = self._run(client)

        self.assertEqual(summary["verdict"], "negative_but_universe_coverage_incomplete")
        self.assertIn("CSI", summary["universes_left_incomplete"])
        self.assertFalse(summary["universe_coverage"]["CSI"]["exhausted"])
        self.assertLessEqual(summary["call_budget"]["used"], probe.CALL_BUDGET)

    def test_a_named_match_is_reported_with_its_code_and_the_marker_that_matched(self):
        client = _FakeClient(_all_markets(
            SSE=[_frame(["沪深300", "昨日涨停指数", "上证50"])]
        ))

        summary = self._run(client)

        self.assertEqual(summary["verdict"], "candidates_found")
        self.assertEqual(summary["candidate_count"], 1)
        candidate = summary["candidates"][0]
        self.assertEqual(candidate["name"], "昨日涨停指数")
        self.assertEqual(candidate["source"], "index_basic:SSE")
        self.assertIn("涨停", candidate["matched_markers"])
        self.assertTrue(candidate["code"])

    def test_history_depth_is_only_spent_when_there_is_a_candidate_to_spend_it_on(self):
        without = self._run(_FakeClient(_all_markets()))
        self.assertEqual(without["history_reach"], {})

        client = _FakeClient(_all_markets(SSE=[_frame(["昨日涨停指数"])]))
        with_candidate = self._run(client)
        self.assertEqual(set(with_candidate["history_reach"]),
                         {w["label"] for w in probe.HISTORY_PROBE_WINDOWS})
        self.assertTrue(any(c["endpoint"] == "index_daily" for c in client.calls))

    def test_a_permission_error_is_classified_rather_than_swallowed_or_raised(self):
        client = _FakeClient(_all_markets(), ths_error=Exception("抱歉，您没有访问该接口的权限，积分不足"))

        summary = self._run(client)

        self.assertIn("permission_or_entitlement", summary["error_categories"])
        ths = next(c for c in summary["calls"] if c["endpoint"] == "ths_index")
        self.assertEqual(ths["status"], "error")
        self.assertEqual(ths["error_category"], "permission_or_entitlement")

    def test_the_summary_declares_it_changed_no_production_behaviour(self):
        summary = self._run(_FakeClient(_all_markets()))
        scope = summary["scope"]
        for claim in ("regime_classified", "consumer_wired", "egs_or_weekly_behavior_changed",
                      "frozen_spec_modified", "production_or_ship_gate_claimed",
                      "broker_or_order_action"):
            self.assertFalse(scope[claim], claim)

    def test_vendor_nan_becomes_null_in_raw_without_letting_the_writer_accept_nan(self):
        frame = pd.DataFrame({"ts_code": ["000001.SH"], "name": ["x"], "base_point": [float("nan")]})
        self.assertIsNone(probe._raw_json_value(frame)["rows"][0]["base_point"])
        with self.assertRaises(ValueError):
            probe._write_json(self.raw_root / "guard.json", {"v": float("nan")})


if __name__ == "__main__":
    unittest.main()
