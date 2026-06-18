"""tushare_health_probe no-network 测试(R-TUSHARE-HEALTH-PROBE-PLAINTEXT-TOKEN-AND-FALSE-OK-GAP)。
全程 no-network、不需真 token: ① 绝不向非 HTTPS 发 token ② 有列但 0 行不判健康(防 false-OK)
③ A 段复用 weekly pinned init_tushare_pro(注入 fake pro,不碰真网络)。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.tushare_health_probe import (  # noqa: E402
    _pkg_health, _verdict, _require_https, _http_known_good, main,
)


class _DF:
    def __init__(self, columns, n):
        self.columns = columns
        self._n = n

    def __len__(self):
        return self._n


class _Resp:
    status_code = 200

    def json(self):
        return {"code": 0, "data": {"fields": ["cal_date", "is_open"], "items": [["20260102", 1]]}}


class _Pro:
    """fake weekly-pinned pro: 各接口返回构造 df(便于注入 main,no-network)。"""
    def __init__(self, td, sf, dd):
        self._td, self._sf, self._dd = td, sf, dd

    def trade_cal(self, **kw):
        return self._td

    def share_float(self, **kw):
        return self._sf

    def disclosure_date(self, **kw):
        return self._dd


class RequireHttpsTests(unittest.TestCase):
    def test_rejects_http(self):
        with self.assertRaises(ValueError):
            _require_https("http://api.tushare.pro/dataapi")

    def test_accepts_https(self):
        _require_https("https://api.tushare.pro/dataapi")   # 不抛即通过

    def test_http_known_good_refuses_plaintext_before_send(self):
        # 绝不向 http 发 token: _require_https 在发请求前拦,注入的 post 一次都不应被调用
        sent = []

        def _post(*a, **k):
            sent.append(a)
            raise AssertionError("不该发出任何请求")

        with self.assertRaises(ValueError):
            _http_known_good("TKN", "http://api.tushare.pro/dataapi", post=_post)
        self.assertEqual(sent, [])

    def test_http_known_good_uses_https_and_parses(self):
        captured = {}

        def _post(url, json=None, timeout=None):
            captured["url"] = url
            captured["has_token"] = "token" in (json or {})
            return _Resp()

        ok = _http_known_good("TKN", "https://api.tushare.pro/dataapi", post=_post)
        self.assertTrue(ok)
        self.assertTrue(captured["url"].startswith("https://"))
        self.assertTrue(captured["has_token"])


class PkgHealthTests(unittest.TestCase):
    def test_known_good_zero_rows_not_healthy(self):
        # false-OK 防御:trade_cal 有列但 0 行 → 不健康(正是要抓"包静默返回空")
        ok, rows = _pkg_health(_DF(["cal_date", "is_open"], 0), "trade_cal")
        self.assertFalse(ok)
        self.assertEqual(rows, 0)

    def test_broken_no_columns_not_healthy(self):
        # broken 包: 无列空表 → 不健康
        self.assertFalse(_pkg_health(_DF([], 0), "trade_cal")[0])

    def test_known_good_with_rows_healthy(self):
        self.assertTrue(_pkg_health(_DF(["cal_date", "is_open"], 5), "trade_cal")[0])

    def test_data_api_columns_ok_even_zero_rows(self):
        # 数据接口(share_float)列齐即端点通,rows 可能真 0(该票无记录)
        self.assertTrue(_pkg_health(_DF(["ann_date", "float_date"], 0), "share_float")[0])

    def test_data_api_missing_column_not_healthy(self):
        self.assertFalse(_pkg_health(_DF(["ann_date"], 1), "share_float")[0])

    def test_real_pandas_columns_index(self):
        # 真 pandas df.columns 是 Index(bool ambiguous);_pkg_health 不能 `columns or []`(否则真跑 ValueError)
        import pandas as pd
        ok, rows = _pkg_health(pd.DataFrame({"cal_date": ["20260102"], "is_open": [1]}), "trade_cal")
        self.assertTrue(ok)
        self.assertEqual(rows, 1)
        self.assertFalse(_pkg_health(pd.DataFrame(), "trade_cal")[0])   # 空 df(无列)→ 不健康(broken 包形态)


class VerdictTests(unittest.TestCase):
    def test_all_apis_healthy_ok(self):
        self.assertEqual(_verdict({"trade_cal": (True, 5), "share_float": (True, 3), "disclosure_date": (True, 1)}, None),
                         ("OK", 0))

    def test_data_api_broken_critical_label(self):
        # residual: trade_cal 健康但 share_float 坏(无列)→ CRITICAL-API-BROKEN(非 OK;known-good 通故非 pin/网络问题)
        label, code = _verdict({"trade_cal": (True, 5), "share_float": (False, 0), "disclosure_date": (True, 1)}, True)
        self.assertEqual(label, "CRITICAL-API-BROKEN")
        self.assertEqual(code, 1)

    def test_zero_rows_not_ok_nonzero_exit(self):
        # known-good 0 行 → 非 OK + 非零退出码(不打印 healthy verdict)
        label, code = _verdict({"trade_cal": (False, 0)}, None)
        self.assertNotEqual(label, "OK")
        self.assertNotEqual(code, 0)

    def test_pinned_empty_http_ok(self):
        self.assertEqual(_verdict({"trade_cal": (False, 0)}, True), ("PINNED-PATH-EMPTY", 1))

    def test_http_fail(self):
        self.assertEqual(_verdict({"trade_cal": (False, 0)}, False), ("CHECK-TOKEN-NET", 1))


class MainNoNetworkTests(unittest.TestCase):
    def test_pinned_ok_no_network_no_real_token(self):
        # 注入 fake pinned pro(known-good 有行)+ fake token → OK exit 0,不发任何网络
        pro = _Pro(_DF(["cal_date", "is_open"], 5), _DF(["ann_date", "float_date"], 3), _DF(["ann_date", "pre_date"], 1))
        self.assertEqual(main(token="FAKE", pro=pro, http_kg=None), 0)

    def test_zero_row_known_good_nonzero_exit(self):
        # known-good 有列但 0 行 → 非零退出(false-OK regression);注入 http_kg 避免真网络
        pro = _Pro(_DF(["cal_date", "is_open"], 0), _DF(["ann_date", "float_date"], 0), _DF(["ann_date", "pre_date"], 0))
        self.assertEqual(main(token="FAKE", pro=pro, http_kg=True), 1)

    def test_data_api_broken_nonzero_exit(self):
        # residual: trade_cal 有行但 share_float 无列空表(broken)→ 非零、不 [OK];注入 http_kg 避免真网络
        pro = _Pro(_DF(["cal_date", "is_open"], 5), _DF([], 0), _DF(["ann_date", "pre_date"], 1))
        self.assertEqual(main(token="FAKE", pro=pro, http_kg=True), 1)

    def test_no_token_returns_2(self):
        self.assertEqual(main(token="", pro=None, http_kg=None), 2)


if __name__ == "__main__":
    unittest.main()
