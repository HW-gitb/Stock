import importlib.util
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from engine.a_short_hithink_l3 import (
    API_BASE_URL,
    CONCEPT_CATALOG_PATH,
    CONSTITUENTS_PATH,
    HiThinkL3Graph,
    HiThinkL3SourceError,
    catalog_digest,
    fetch_complete_concept_graph,
)

ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_main_l3_guard_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class EgsMainL3GuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def test_historical_asof_rejects_default_today_l3(self) -> None:
        with self.assertRaisesRegex(SystemExit, "cannot run with --l3-mode=today"):
            self.egs_main._guard_historical_asof_l3_mode(
                "20260522",
                "today",
                run_date="20260601",
            )

    def test_empty_candidates_do_not_bypass_unavailable_market_data_guard(self) -> None:
        original_conf = dict(self.egs_main.CONF)
        try:
            self.egs_main.CONF["l3_mode"] = "today"
            messages = []
            for candidates in (
                pd.DataFrame(columns=["ts_code", "pct_20d_n"]),
                pd.DataFrame([{"ts_code": "600000.SH", "pct_20d_n": 0.0}]),
            ):
                with self.assertRaises(SystemExit) as raised:
                    self.egs_main.score_l3(candidates, [], pd.DataFrame())
                messages.append(str(raised.exception))
            self.assertEqual(messages[0], messages[1])
            self.assertIn("requires usable market daily data", messages[0])
        finally:
            self.egs_main.CONF.clear()
            self.egs_main.CONF.update(original_conf)

    def test_empty_neutralized_l3_records_explicit_provider_binding(self) -> None:
        original_conf = dict(self.egs_main.CONF)
        try:
            self.egs_main.CONF["l3_mode"] = "neutralize"
            scored = self.egs_main.score_l3(
                pd.DataFrame(columns=["ts_code", "pct_20d_n"]),
                [],
                pd.DataFrame(),
            )
            self.assertTrue(scored.empty)
            self.assertEqual(self.egs_main.CONF["l3_provider"], "neutralized")
            self.assertIsNone(self.egs_main.CONF["l3_coverage"])
        finally:
            self.egs_main.CONF.clear()
            self.egs_main.CONF.update(original_conf)

    def test_historical_asof_allows_pit_or_neutralize(self) -> None:
        self.egs_main._guard_historical_asof_l3_mode("20260522", "pit", run_date="20260601")
        self.egs_main._guard_historical_asof_l3_mode("20260522", "neutralize", run_date="20260601")

    def test_today_l3_requires_explicit_live_l3_declaration_for_historical_replay(self) -> None:
        self.egs_main._guard_historical_asof_l3_mode(
            "20260522",
            "today",
            allow_historical_live_l3=True,
            run_date="20260601",
        )

    def test_current_asof_keeps_default_today_l3_allowed(self) -> None:
        self.egs_main._guard_historical_asof_l3_mode("20260601", "today", run_date="20260601")

    def test_prospective_asof_allows_default_today_l3(self) -> None:
        # canonical 解析器把周末/周一盘前运行解析成「即将到来的周一」as_of(> run_date 的前瞻交易日);
        # 这类前瞻 live 运行用 l3=today 正确,不应被当历史回放拦死(判据已从 != 放宽为 <)。
        self.egs_main._guard_historical_asof_l3_mode("20260622", "today", run_date="20260620")

    def test_disabled_egs_cache_neither_reads_nor_writes(self) -> None:
        original_conf = dict(self.egs_main.CONF)
        try:
            with TemporaryDirectory(dir=str(ROOT)) as tmp:
                self.egs_main.CONF["result_dir"] = tmp
                self.egs_main.CONF["cache_dir"] = str(Path(tmp) / "cache")
                self.egs_main.CONF["cache_policy"] = "disabled"
                self.egs_main.save_cache("fresh", {"must": "not write"})
                self.assertFalse(Path(self.egs_main.CONF["cache_dir"]).exists())

                cache_path = Path(self.egs_main.CONF["cache_dir"]) / "existing.pkl"
                cache_path.parent.mkdir(parents=True)
                cache_path.write_bytes(b"not-a-valid-pickle")
                self.assertIsNone(self.egs_main.load_cache("existing"))
        finally:
            self.egs_main.CONF.clear()
            self.egs_main.CONF.update(original_conf)

    def test_disabled_cache_explicit_asof_logs_ttl_as_ignored(self) -> None:
        original_conf = dict(self.egs_main.CONF)
        original_today = self.egs_main.TODAY
        original_today_dt = self.egs_main.TODAY_DT
        try:
            self.egs_main.CONF["cache_policy"] = "disabled"
            self.egs_main.CONF["cache_ttl"] = 123
            calendar = pd.DataFrame([{"cal_date": "20260723", "is_open": 1}])
            with patch.object(self.egs_main, "safe_api", return_value=calendar), \
                    patch.object(self.egs_main.log, "info") as info:
                self.egs_main.set_asof("20260723")

            self.assertEqual(self.egs_main.CONF["cache_ttl"], 123)
            info.assert_called_once_with(
                "[ASOF] running EGS as of 20260723; cache_policy=disabled; cache_ttl=ignored"
            )
        finally:
            self.egs_main.CONF.clear()
            self.egs_main.CONF.update(original_conf)
            self.egs_main.TODAY = original_today
            self.egs_main.TODAY_DT = original_today_dt

    def test_today_l3_uses_complete_hithink_graph_and_persists_coverage_receipt(self) -> None:
        graph = HiThinkL3Graph(
            concepts_df=pd.DataFrame([
                {"code": "885001.TI", "name": "概念一"},
                {"code": "885002.TI", "name": "概念二"},
            ]),
            stock_concepts={"000001.SZ": ["885001.TI"], "000002.SZ": ["885002.TI"]},
            concept_members={"885001.TI": ["000001.SZ"], "885002.TI": ["000002.SZ"]},
            coverage={
                "source": "hithink_finance", "catalog_tag": "cn_concept",
                "catalog_digest": "a" * 64,
                "catalog_board_count": 2, "received_board_count": 2,
                "verified_empty_board_count": 0, "raw_member_row_count": 2,
                "scope_filtered_empty_board_count": 0,
                "unique_member_pair_count": 2, "out_of_a_share_member_count": 0,
                "main_board_member_pair_count": 2,
                "excluded_non_main_board_member_count": 0,
                "market_suffix_counts": {"SZ": 2},
                "scoring_universe": "a_share_main_board", "complete": True,
            },
        )
        candidates = pd.DataFrame([
            {"ts_code": "000001.SZ", "pct_20d_n": 0.0},
            {"ts_code": "000002.SZ", "pct_20d_n": 0.0},
        ])
        daily = pd.DataFrame([
            {"ts_code": "000001.SZ", "trade_date": "20260716", "pct_chg": 3.0, "amount": 100.0},
            {"ts_code": "000002.SZ", "trade_date": "20260716", "pct_chg": 1.0, "amount": 100.0},
        ])
        original_today = self.egs_main.TODAY
        original_today_dt = self.egs_main.TODAY_DT
        original_snapshot_dir = self.egs_main.L3_SNAPSHOT_DIR
        original_conf = dict(self.egs_main.CONF)
        try:
            self.egs_main.TODAY = "20260716"
            self.egs_main.TODAY_DT = pd.Timestamp("2026-07-16").to_pydatetime()
            self.egs_main.CONF["l3_mode"] = "today"
            self.egs_main.CONF["l3_cache_mode"] = "refresh"
            with TemporaryDirectory(dir=str(ROOT)) as tmp:
                self.egs_main.L3_SNAPSHOT_DIR = tmp
                with patch.object(self.egs_main, "fetch_complete_concept_graph", return_value=graph) as fetch:
                    scored = self.egs_main.score_l3(candidates, ["20260716"], daily)
                fetch.assert_called_once_with(expected_catalog_codes=None)
                self.assertEqual(self.egs_main.CONF["l3_provider"], "hithink_finance")
                self.assertEqual(self.egs_main.CONF["l3_coverage"], graph.coverage)
                self.assertGreater(scored.loc[0, "cat_score"], scored.loc[1, "cat_score"])
                snapshot = self.egs_main._load_l3_snapshot(
                    self.egs_main.CONF["l3_snapshot_date"], include_metadata=True)
                self.assertIsNotNone(snapshot)
                self.assertEqual(snapshot[4], "hithink_finance")
                self.assertEqual(snapshot[5], graph.coverage)
        finally:
            self.egs_main.TODAY = original_today
            self.egs_main.TODAY_DT = original_today_dt
            self.egs_main.L3_SNAPSHOT_DIR = original_snapshot_dir
            self.egs_main.CONF.clear()
            self.egs_main.CONF.update(original_conf)

    def test_today_reuse_uses_complete_hithink_snapshot_without_provider_call(self) -> None:
        # The reuse gate compares the snapshot against the real wall clock, so a
        # pinned date silently rots into a >14d failure.  Anchor on today instead:
        # this case is about reusing a FRESH snapshot without a provider call, and
        # the staleness gate itself is covered by its own case below.
        fresh_day = datetime.now().strftime("%Y%m%d")
        catalog_codes = {f"{885000 + i}.TI" for i in range(1, 390)}
        concepts = pd.DataFrame([
            {"code": code, "name": f"概念{code}"} for code in sorted(catalog_codes)
        ])
        concept_members = {code: [] for code in catalog_codes}
        concept_members["885001.TI"] = ["600000.SH"]
        coverage = {
            "source": "hithink_finance", "catalog_tag": "cn_concept",
            "catalog_digest": catalog_digest(catalog_codes),
            "catalog_board_count": 389, "received_board_count": 389,
            "verified_empty_board_count": 388, "scope_filtered_empty_board_count": 0,
            "raw_member_row_count": 1, "unique_member_pair_count": 1,
            "main_board_member_pair_count": 1,
            "excluded_non_main_board_member_count": 0,
            "out_of_a_share_member_count": 0,
            "market_suffix_counts": {"SH": 1},
            "scoring_universe": "a_share_main_board", "complete": True,
        }
        candidates = pd.DataFrame([{"ts_code": "600000.SH", "pct_20d_n": 0.0}])
        daily = pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": fresh_day, "pct_chg": 2.0, "amount": 100.0}
        ])
        original_today = self.egs_main.TODAY
        original_snapshot_dir = self.egs_main.L3_SNAPSHOT_DIR
        original_conf = dict(self.egs_main.CONF)
        try:
            self.egs_main.TODAY = fresh_day
            self.egs_main.CONF["l3_mode"] = "today"
            self.egs_main.CONF["l3_cache_mode"] = "reuse"
            with TemporaryDirectory(dir=str(ROOT)) as tmp:
                self.egs_main.L3_SNAPSHOT_DIR = tmp
                self.egs_main._write_l3_snapshot(
                    fresh_day, concepts,
                    {"600000.SH": ["885001.TI"]},
                    concept_members,
                    l3_source="hithink_finance", coverage=coverage,
                )
                with patch.object(
                    self.egs_main, "fetch_complete_concept_graph",
                    side_effect=AssertionError("provider must not be called"),
                ) as fetch:
                    scored = self.egs_main.score_l3(candidates, [fresh_day], daily)
                    empty_scored = self.egs_main.score_l3(
                        pd.DataFrame(columns=["ts_code", "pct_20d_n"]),
                        [fresh_day],
                        daily,
                    )
                fetch.assert_not_called()
                self.assertEqual(scored.loc[0, "cat_score"], 100.0)
                self.assertTrue(empty_scored.empty)
                self.assertEqual(self.egs_main.CONF["l3_provider"], "hithink_finance")
                self.assertEqual(self.egs_main.CONF["l3_snapshot_date"], fresh_day)
        finally:
            self.egs_main.TODAY = original_today
            self.egs_main.L3_SNAPSHOT_DIR = original_snapshot_dir
            self.egs_main.CONF.clear()
            self.egs_main.CONF.update(original_conf)

    def test_today_reuse_rejects_stale_snapshot_without_provider_call(self) -> None:
        real_today = datetime.now().strftime("%Y%m%d")
        stale_date = (datetime.now() - timedelta(days=15)).strftime("%Y%m%d")
        catalog_codes = {f"{885000 + i}.TI" for i in range(1, 390)}
        concepts = pd.DataFrame([
            {"code": code, "name": f"概念{code}"} for code in sorted(catalog_codes)
        ])
        concept_members = {code: [] for code in catalog_codes}
        concept_members["885001.TI"] = ["600000.SH"]
        coverage = {
            "source": "hithink_finance", "catalog_tag": "cn_concept",
            "catalog_digest": catalog_digest(catalog_codes),
            "catalog_board_count": 389, "received_board_count": 389,
            "verified_empty_board_count": 388, "scope_filtered_empty_board_count": 0,
            "raw_member_row_count": 1, "unique_member_pair_count": 1,
            "main_board_member_pair_count": 1, "excluded_non_main_board_member_count": 0,
            "out_of_a_share_member_count": 0, "market_suffix_counts": {"SH": 1},
            "scoring_universe": "a_share_main_board", "complete": True,
        }
        candidates = pd.DataFrame([{"ts_code": "600000.SH", "pct_20d_n": 0.0}])
        daily = pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": real_today, "pct_chg": 2.0, "amount": 100.0}
        ])
        original_today = self.egs_main.TODAY
        original_snapshot_dir = self.egs_main.L3_SNAPSHOT_DIR
        original_conf = dict(self.egs_main.CONF)
        try:
            self.egs_main.TODAY = real_today
            self.egs_main.CONF["l3_mode"] = "today"
            self.egs_main.CONF["l3_cache_mode"] = "reuse"
            self.egs_main.CONF["l3_allow_stale_cache"] = False
            with TemporaryDirectory(dir=str(ROOT)) as tmp:
                self.egs_main.L3_SNAPSHOT_DIR = tmp
                self.egs_main._write_l3_snapshot(
                    stale_date, concepts, {"600000.SH": ["885001.TI"]}, concept_members,
                    l3_source="hithink_finance", coverage=coverage,
                )
                with patch.object(
                    self.egs_main, "fetch_complete_concept_graph",
                    side_effect=AssertionError("provider must not be called"),
                ) as fetch:
                    with self.assertRaisesRegex(SystemExit, r">14d"):
                        self.egs_main.score_l3(candidates, [real_today], daily)
                fetch.assert_not_called()
                self.egs_main.CONF["l3_allow_stale_cache"] = True
                with patch.object(
                    self.egs_main, "fetch_complete_concept_graph",
                    side_effect=AssertionError("provider must not be called"),
                ) as fetch:
                    scored = self.egs_main.score_l3(candidates, [real_today], daily)
                fetch.assert_not_called()
                self.assertEqual(scored.loc[0, "cat_score"], 100.0)
                self.assertEqual(self.egs_main.CONF["l3_snapshot_date"], stale_date)
        finally:
            self.egs_main.TODAY = original_today
            self.egs_main.L3_SNAPSHOT_DIR = original_snapshot_dir
            self.egs_main.CONF.clear()
            self.egs_main.CONF.update(original_conf)

    def test_snapshot_loader_rebuilds_complete_main_board_membership(self) -> None:
        concepts = pd.DataFrame([
            {"code": f"88500{i}.TI", "name": f"概念{i}"} for i in range(1, 7)
        ])
        concept_members = {
            f"88500{i}.TI": ["600000.SH", "300001.SZ"] for i in range(1, 7)
        }
        coverage = {
            "source": "hithink_finance", "catalog_tag": "cn_concept",
            "catalog_digest": "c" * 64,
            "catalog_board_count": 6, "received_board_count": 6,
            "verified_empty_board_count": 0, "scope_filtered_empty_board_count": 0,
            "raw_member_row_count": 12, "unique_member_pair_count": 12,
            "main_board_member_pair_count": 6,
            "excluded_non_main_board_member_count": 6,
            "out_of_a_share_member_count": 0,
            "market_suffix_counts": {"SH": 6, "SZ": 6},
            "scoring_universe": "a_share_main_board", "complete": True,
        }
        original_snapshot_dir = self.egs_main.L3_SNAPSHOT_DIR
        try:
            with TemporaryDirectory(dir=str(ROOT)) as tmp:
                self.egs_main.L3_SNAPSHOT_DIR = tmp
                self.egs_main._write_l3_snapshot(
                    "20260716", concepts,
                    {"600000.SH": [f"88500{i}.TI" for i in range(1, 6)]},
                    concept_members,
                    l3_source="hithink_finance", coverage=coverage,
                )
                loaded = self.egs_main._load_l3_snapshot("20260716", include_metadata=True)
            self.assertEqual(
                loaded[1]["600000.SH"],
                [f"88500{i}.TI" for i in range(1, 7)],
            )
            self.assertNotIn("300001.SZ", loaded[1])
            self.assertTrue(all("300001.SZ" not in members for members in loaded[2].values()))
        finally:
            self.egs_main.L3_SNAPSHOT_DIR = original_snapshot_dir

    def test_non_main_board_daily_move_cannot_change_main_board_cat_score(self) -> None:
        def envelope(items):
            return {"code": 0, "data": {"item": items}}

        catalog = envelope([
            {"thscode": "885001.TI", "name": "概念一"},
            {"thscode": "885002.TI", "name": "概念二"},
        ])
        boards = {
            "885001.TI": envelope([
                {"thscode": "600000.SH"},
                {"thscode": "300001.SZ"},
            ]),
            "885002.TI": envelope([{"thscode": "600001.SH"}]),
        }

        def requester(url, _headers):
            if url == API_BASE_URL + CONCEPT_CATALOG_PATH:
                return catalog
            return boards[url.removeprefix(API_BASE_URL + CONSTITUENTS_PATH)]

        graph = fetch_complete_concept_graph(
            api_key="test-key",
            requester=requester,
            max_workers=1,
            max_attempts=1,
            min_catalog_board_count=1,
            sleep=lambda _seconds: None,
        )
        self.assertNotIn("300001.SZ", graph.stock_concepts)

        candidates = pd.DataFrame([
            {"ts_code": "600000.SH", "pct_20d_n": 0.0},
            {"ts_code": "600001.SH", "pct_20d_n": 0.0},
        ])
        original_today = self.egs_main.TODAY
        original_snapshot_dir = self.egs_main.L3_SNAPSHOT_DIR
        original_conf = dict(self.egs_main.CONF)
        try:
            self.egs_main.TODAY = "20260716"
            self.egs_main.CONF["l3_mode"] = "today"
            self.egs_main.CONF["l3_cache_mode"] = "refresh"
            with TemporaryDirectory(dir=str(ROOT)) as tmp:
                self.egs_main.L3_SNAPSHOT_DIR = tmp
                scores = []
                for non_main_move in (-10.0, 10.0):
                    daily = pd.DataFrame([
                        {"ts_code": "600000.SH", "trade_date": "20260716", "pct_chg": -1.0, "amount": 100.0},
                        {"ts_code": "600001.SH", "trade_date": "20260716", "pct_chg": 0.0, "amount": 100.0},
                        {"ts_code": "300001.SZ", "trade_date": "20260716", "pct_chg": non_main_move, "amount": 100.0},
                    ])
                    with patch.object(
                        self.egs_main, "fetch_complete_concept_graph", return_value=graph
                    ):
                        scored = self.egs_main.score_l3(candidates, ["20260716"], daily)
                    scores.append(scored.set_index("ts_code")["cat_score"].to_dict())
            self.assertEqual(scores[0], scores[1])
            self.assertEqual(scores[0]["600000.SH"], 50.0)
        finally:
            self.egs_main.TODAY = original_today
            self.egs_main.L3_SNAPSHOT_DIR = original_snapshot_dir
            self.egs_main.CONF.clear()
            self.egs_main.CONF.update(original_conf)

    def test_today_l3_refuses_partial_provider(self) -> None:
        candidates = pd.DataFrame([{ "ts_code": "000001.SZ", "pct_20d_n": 0.0}])
        daily = pd.DataFrame([
            {"ts_code": "000001.SZ", "trade_date": self.egs_main.TODAY, "pct_chg": 1.0, "amount": 100.0}
        ])
        original_conf = dict(self.egs_main.CONF)
        try:
            self.egs_main.CONF["l3_mode"] = "today"
            with patch.object(
                self.egs_main,
                "fetch_complete_concept_graph",
                side_effect=HiThinkL3SourceError("concept board 885001.TI request failed"),
            ):
                with self.assertRaisesRegex(SystemExit, "no selection will be published"):
                    self.egs_main.score_l3(candidates, [self.egs_main.TODAY], daily)
        finally:
            self.egs_main.CONF.clear()
            self.egs_main.CONF.update(original_conf)


if __name__ == "__main__":
    unittest.main()
