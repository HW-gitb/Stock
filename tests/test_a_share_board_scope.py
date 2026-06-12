from __future__ import annotations

import unittest

from engine.data.a_share_board_scope import (
    board_bucket_from_ts_code, non_main_board_symbols, is_a_share_main_board,
)


class AShareBoardScopeTest(unittest.TestCase):
    def test_main_board_includes_shanghai_and_shenzhen_main_prefixes(self) -> None:
        for symbol in ["000001.SZ", "001979.SZ", "002415.SZ", "003816.SZ", "600519.SH", "601318.SH", "603288.SH", "605499.SH"]:
            self.assertEqual(board_bucket_from_ts_code(symbol), "main", symbol)

    def test_non_main_board_prefixes_are_rejected(self) -> None:
        symbols = ["300750.SZ", "301001.SZ", "688981.SH", "689009.SH", "920118.BJ", "830799.BJ", "430047.BJ"]

        self.assertEqual(non_main_board_symbols(symbols), symbols)

    def test_is_a_share_main_board_inclusion_only(self) -> None:
        # exact governance prefixes accepted
        for s in ["600519.SH", "601318.SH", "603288.SH", "605499.SH",
                  "000001.SZ", "001979.SZ", "002415.SZ", "003816.SZ"]:
            self.assertTrue(is_a_share_main_board(s), s)
        # everything else rejected — B-shares, other boards, AND malformed-under-accepted-prefix
        for s in ["200001.SZ", "900901.SH", "300750.SZ", "301001.SZ", "688981.SH", "689009.SH",
                  "920083.BJ", "830799.BJ", "garbage", "600000", "", None,
                  "600ABC.SH", "60000.SH", "6000000.SH", "00000A.SZ", "002.SZ", "600000.BJ"]:
            self.assertFalse(is_a_share_main_board(s), s)


if __name__ == "__main__":
    unittest.main()
