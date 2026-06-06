import tempfile
import unittest
from pathlib import Path

from runners import a_long_total_return_benchmark_access_probe as runner


class FakeTushareClient:
    def index_daily(self, *, ts_code: str, start_date: str, end_date: str, fields: str) -> list[dict]:
        if ts_code in {"000300.SH", "000852.SH"}:
            return [
                {"ts_code": ts_code, "trade_date": "20200103", "open": 100.0, "close": 101.0},
                {"ts_code": ts_code, "trade_date": "20200102", "open": 99.0, "close": 100.0},
            ]
        if ts_code in {"H00300.CSI", "H00852.CSI"}:
            return [
                {"ts_code": ts_code, "trade_date": "20200103", "open": None, "close": 101.0},
                {"ts_code": ts_code, "trade_date": "20200102", "open": None, "close": 100.0},
            ]
        return []


class ALongTotalReturnBenchmarkAccessProbeTest(unittest.TestCase):
    def test_requires_user_approved_route_a_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                runner.run(
                    summary_path=Path(tmp) / "summary.json",
                    generated_at="2026-06-06T00:00:00+00:00",
                    confirm_user_approved_route_a=False,
                    pro_factory=FakeTushareClient,
                )

    def test_close_only_total_return_candidates_block_signal_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = runner.run(
                summary_path=Path(tmp) / "summary.json",
                generated_at="2026-06-06T00:00:00+00:00",
                confirm_user_approved_route_a=True,
                pro_factory=FakeTushareClient,
            )

        self.assertEqual(
            summary["decision"]["benchmark_access_status"],
            "blocked_total_return_same_anchor_open_unavailable",
        )
        self.assertTrue(summary["decision"]["control_price_index_probe_passed"])
        self.assertFalse(summary["decision"]["signal_search_may_execute"])
        self.assertFalse(summary["decision"]["price_index_fallback_allowed"])
        self.assertFalse(summary["decision"]["derived_total_return_open_allowed"])
        tr_rows = [item for item in summary["direct_probes"] if item["candidate_role"] == "total_return_candidate"]
        close_only = [item for item in tr_rows if item["close_only_total_return_candidate"]]
        self.assertEqual({item["ts_code"] for item in close_only}, {"H00300.CSI", "H00852.CSI"})


if __name__ == "__main__":
    unittest.main()
