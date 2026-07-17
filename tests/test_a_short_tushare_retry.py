"""Retry classification must be shared by every A-short Tushare caller."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from runners.backtest_rank import _ts_call
from runners.materialize_execution_price_data_tushare import ts_call


class TushareRetryTests(unittest.TestCase):
    def _assert_rate_limit_retries(self, call, sleep_path: str) -> None:
        attempts = 0

        def flaky():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("每分钟最多访问该接口")
            return "ok"

        with patch(sleep_path) as sleep:
            self.assertEqual(call(flaky, retries=3, base_delay=0.1), "ok")
        self.assertEqual(attempts, 3)
        self.assertEqual(sleep.call_count, 2)

    def _assert_permission_does_not_retry(self, call, sleep_path: str) -> None:
        attempts = 0

        def denied():
            nonlocal attempts
            attempts += 1
            raise RuntimeError("没有访问该接口的权限")

        with patch(sleep_path) as sleep:
            with self.assertRaisesRegex(RuntimeError, "without retry"):
                call(denied, retries=3, base_delay=0.1)
        self.assertEqual(attempts, 1)
        sleep.assert_not_called()

    def test_backtest_rank_retries_only_transient_errors(self):
        self._assert_rate_limit_retries(_ts_call, "runners.backtest_rank.time.sleep")
        self._assert_permission_does_not_retry(_ts_call, "runners.backtest_rank.time.sleep")

    def test_execution_price_materializer_retries_only_transient_errors(self):
        self._assert_rate_limit_retries(ts_call, "runners.materialize_execution_price_data_tushare.time.sleep")
        self._assert_permission_does_not_retry(ts_call, "runners.materialize_execution_price_data_tushare.time.sleep")


if __name__ == "__main__":
    unittest.main()
