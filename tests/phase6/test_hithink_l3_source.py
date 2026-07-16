import unittest

from engine.a_short_hithink_l3 import (
    API_BASE_URL,
    CONCEPT_CATALOG_PATH,
    CONSTITUENTS_PATH,
    HiThinkL3SourceError,
    _require_api_key,
    fetch_complete_concept_graph,
)


def _envelope(items):
    return {"code": 0, "data": {"item": items}}


class HiThinkL3SourceTest(unittest.TestCase):
    def test_user_environment_fallback_accepts_just_configured_key_without_logging_it(self):
        self.assertEqual(
            _require_api_key(
                None,
                environment={},
                user_env_reader=lambda name: "test-user-key" if name == "HITHINK_FINANCE_API_KEY" else "",
            ),
            "test-user-key",
        )

    def _requester(self, catalog, boards):
        def request(url, _headers):
            if url == API_BASE_URL + CONCEPT_CATALOG_PATH:
                return catalog
            board_code = url.removeprefix(API_BASE_URL + CONSTITUENTS_PATH)
            return boards[board_code]

        return request

    def _fetch(self, catalog, boards, **kwargs):
        return fetch_complete_concept_graph(
            api_key="test-key",
            requester=self._requester(catalog, boards),
            max_workers=1,
            max_attempts=1,
            min_catalog_board_count=1,
            sleep=lambda _seconds: None,
            **kwargs,
        )

    def test_complete_catalog_builds_deterministic_graph_and_records_external_member(self):
        graph = self._fetch(
            _envelope([
                {"thscode": "885002.TI", "name": "概念二"},
                {"thscode": "885001.TI", "name": "概念一"},
                {"thscode": "885003.TI", "name": "空概念"},
            ]),
            {
                "885002.TI": _envelope([
                    {"thscode": "000001.SZ"},
                    {"thscode": "834683.NQ"},
                ]),
                "885001.TI": _envelope([
                    {"thscode": "000001.SZ"},
                    {"thscode": "600000.SH"},
                    {"thscode": "000001.SZ"},
                ]),
                "885003.TI": _envelope([]),
            },
        )

        self.assertEqual(list(graph.concepts_df["code"]), ["885002.TI", "885001.TI", "885003.TI"])
        self.assertEqual(graph.concept_members["885003.TI"], [])
        self.assertEqual(graph.stock_concepts["000001.SZ"], ["885001.TI", "885002.TI"])
        self.assertNotIn("834683.NQ", graph.stock_concepts)
        self.assertEqual(graph.coverage["catalog_board_count"], 3)
        self.assertEqual(graph.coverage["received_board_count"], 3)
        self.assertEqual(graph.coverage["verified_empty_board_count"], 1)
        self.assertEqual(graph.coverage["scope_filtered_empty_board_count"], 0)
        self.assertEqual(graph.coverage["raw_member_row_count"], 5)
        self.assertEqual(graph.coverage["unique_member_pair_count"], 4)
        self.assertEqual(graph.coverage["main_board_member_pair_count"], 3)
        self.assertEqual(graph.coverage["excluded_non_main_board_member_count"], 1)
        self.assertEqual(graph.coverage["out_of_a_share_member_count"], 1)
        self.assertEqual(graph.coverage["market_suffix_counts"], {"NQ": 1, "SH": 1, "SZ": 2})
        self.assertEqual(graph.coverage["scoring_universe"], "a_share_main_board")
        self.assertRegex(graph.coverage["catalog_digest"], r"^[0-9a-f]{64}$")
        self.assertTrue(graph.coverage["complete"])

    def test_one_failed_catalog_board_rejects_the_entire_graph(self):
        with self.assertRaisesRegex(HiThinkL3SourceError, "non-success envelope"):
            self._fetch(
                _envelope([
                    {"thscode": "885001.TI", "name": "概念一"},
                    {"thscode": "885002.TI", "name": "概念二"},
                ]),
                {
                    "885001.TI": _envelope([{ "thscode": "000001.SZ"}]),
                    "885002.TI": {"code": 1, "data": {"item": []}},
                },
            )

    def test_scoring_membership_is_complete_and_never_code_order_truncated(self):
        graph = self._fetch(
            _envelope([
                {"thscode": "885003.TI", "name": "概念三"},
                {"thscode": "885001.TI", "name": "概念一"},
                {"thscode": "885002.TI", "name": "概念二"},
            ]),
            {
                code: _envelope([{ "thscode": "000001.SZ"}])
                for code in ("885001.TI", "885002.TI", "885003.TI")
            },
        )
        self.assertEqual(
            graph.stock_concepts["000001.SZ"],
            ["885001.TI", "885002.TI", "885003.TI"],
        )
        self.assertEqual(len(graph.concept_members), 3)

    def test_non_main_board_members_are_counted_but_excluded_from_graph(self):
        graph = self._fetch(
            _envelope([{ "thscode": "885001.TI", "name": "概念一"}]),
            {"885001.TI": _envelope([
                {"thscode": "600000.SH"},
                {"thscode": "300001.SZ"},
                {"thscode": "688001.SH"},
                {"thscode": "920001.BJ"},
                {"thscode": "900901.SH"},
                {"thscode": "834683.NQ"},
            ])},
        )
        self.assertEqual(graph.concept_members["885001.TI"], ["600000.SH"])
        self.assertEqual(set(graph.stock_concepts), {"600000.SH"})
        self.assertEqual(graph.coverage["main_board_member_pair_count"], 1)
        self.assertEqual(graph.coverage["excluded_non_main_board_member_count"], 5)
        self.assertEqual(graph.coverage["out_of_a_share_member_count"], 1)

    def test_catalog_floor_and_previous_board_set_fail_closed(self):
        catalog = _envelope([{ "thscode": "885001.TI", "name": "概念一"}])
        boards = {"885001.TI": _envelope([])}
        with self.assertRaisesRegex(HiThinkL3SourceError, "completeness floor"):
            fetch_complete_concept_graph(
                api_key="test-key",
                requester=self._requester(catalog, boards),
                max_workers=1,
                max_attempts=1,
                min_catalog_board_count=2,
                sleep=lambda _seconds: None,
            )
        with self.assertRaisesRegex(HiThinkL3SourceError, "dropped previously accepted boards"):
            fetch_complete_concept_graph(
                api_key="test-key",
                requester=self._requester(catalog, boards),
                max_workers=1,
                max_attempts=1,
                min_catalog_board_count=1,
                expected_catalog_codes={"885001.TI", "885002.TI"},
                sleep=lambda _seconds: None,
            )

    def test_missing_member_list_is_not_treated_as_an_empty_board(self):
        with self.assertRaisesRegex(HiThinkL3SourceError, "missing its item list"):
            self._fetch(
                _envelope([{ "thscode": "885001.TI", "name": "概念一"}]),
                {"885001.TI": {"code": 0, "data": {}}},
            )

    def test_duplicate_catalog_and_malformed_member_are_fail_closed(self):
        with self.assertRaisesRegex(HiThinkL3SourceError, "duplicate board"):
            self._fetch(
                _envelope([
                    {"thscode": "885001.TI", "name": "概念一"},
                    {"thscode": "885001.TI", "name": "概念一重复"},
                ]),
                {"885001.TI": _envelope([])},
            )

        with self.assertRaisesRegex(HiThinkL3SourceError, "invalid stock code"):
            self._fetch(
                _envelope([{ "thscode": "885001.TI", "name": "概念一"}]),
                {"885001.TI": _envelope([{ "thscode": "BAD"}])},
            )

    def test_transport_failure_is_bounded_and_never_returns_partial_data(self):
        calls = []

        def failing_requester(url, _headers):
            calls.append(url)
            raise TimeoutError("network unavailable")

        with self.assertRaisesRegex(HiThinkL3SourceError, "request failed after 2 attempts"):
            fetch_complete_concept_graph(
                api_key="test-key",
                requester=failing_requester,
                max_workers=1,
                max_attempts=2,
                min_catalog_board_count=1,
                sleep=lambda _seconds: None,
            )
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
