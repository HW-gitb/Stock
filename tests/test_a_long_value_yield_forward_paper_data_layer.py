"""A-long value-yield forward-PAPER 数据层(段3 universe + 段4 store/context/scored-items/prices)mock 测。

合成 raw records(不抓真数据)验:top-500 主板排名/分桶、scored_items 的因子值 + list/delist/ST-veto 过滤
(全走冻结 cap_audit/bf/base 函数)、数据层→brain→write_accumulator 端到端、gated fetch 接线(fake pro)。
真 provider 形状在第一笔真捕获(as_of≥20260630)现写现验。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import a_long_large_cap_value_yield_forward_paper_data_layer as dl  # noqa: E402
from runners import a_long_large_cap_value_yield_forward_paper_capture as cap  # noqa: E402


def _annual(symbol, *, cf=None, rev=None, ni=1.0):
    """单条 20251231 年报行(suffix 1231 → ttm_rollover 直接取年值);ann/f_ann 20260120 ≤ 20260630 as_of。"""
    cash = [{"ts_code": symbol, "end_date": "20251231", "ann_date": "20260120",
             "f_ann_date": "20260120", "n_cashflow_act": cf}]
    income = [{"ts_code": symbol, "end_date": "20251231", "ann_date": "20260120",
               "f_ann_date": "20260120", "revenue": rev, "n_income_attr_p": ni}]
    return cash, income


class RankUniverseTests(unittest.TestCase):
    def test_main_board_filter_rank_bucket(self):
        recs = [
            {"ts_code": "600000.SH", "circ_mv": 500.0},
            {"ts_code": "000001.SZ", "circ_mv": 300.0},
            {"ts_code": "002001.SZ", "circ_mv": 400.0},
            {"ts_code": "300750.SZ", "circ_mv": 9999.0},   # 创业板 → 排除
            {"ts_code": "688111.SH", "circ_mv": 9999.0},   # 科创板 → 排除
            {"ts_code": "920001.BJ", "circ_mv": 9999.0},   # 北交所 → 排除
            {"ts_code": "600002.SH", "circ_mv": 0.0},      # circ_mv 0 → 排除
        ]
        members = dl.rank_forward_universe(recs)
        self.assertEqual([m["symbol"] for m in members], ["600000.SH", "002001.SZ", "000001.SZ"])  # 主板+circ_mv>0,降序
        self.assertTrue(all(m["size_bucket"] == "q1" for m in members))    # <100 → q1
        self.assertEqual(members[0]["raw_rank"], 1)


class AssembleScoredItemsTests(unittest.TestCase):
    def test_factor_values_and_selection_filters(self):
        as_of = "20260630"
        mcap = [{"ts_code": s, "circ_mv": mv} for s, mv in
                [("600003.SH", 4000.0), ("600002.SH", 3000.0), ("000001.SZ", 2000.0), ("600000.SH", 1000.0)]]
        cf_by, inc_by = {}, {}
        for s, (c, r) in {"600003.SH": (400.0, 2000.0), "600002.SH": (300.0, 1500.0),
                          "000001.SZ": (200.0, 1000.0), "600000.SH": (100.0, 500.0)}.items():
            cash, income = _annual(s, cf=c, rev=r)
            cf_by[s], inc_by[s] = cash, income
        ind = [{"ts_code": s, "in_date": "20100101", "out_date": None, "l2_code": "L2", "l1_code": "L1"} for s in cf_by]
        list_date = {s: "20100101" for s in cf_by}
        list_date["600002.SH"] = "20990101"                      # 未上市 → 排除
        delist = {s: None for s in cf_by}
        namechg = {"600003.SH": [{"name": "*ST测试", "start_date": "20200101", "end_date": None}]}  # ST → veto 排除
        out = dl.assemble_forward_inputs(
            as_of=as_of, market_cap_records=mcap, cashflow_by_symbol=cf_by, income_by_symbol=inc_by,
            daily_by_symbol={s: [] for s in cf_by}, adj_by_symbol={s: [] for s in cf_by}, csi300_records=[],
            index_member_records=ind, list_date_by_symbol=list_date, delist_date_by_symbol=delist,
            selection_status_by_symbol=namechg, trade_dates=["20260701", "20260702"])
        items = {it["symbol"]: it for it in out["scored_items"]}
        self.assertEqual(set(items), {"600000.SH", "000001.SZ"})  # 600002 未上市 + 600003 ST 被排除
        self.assertAlmostEqual(items["600000.SH"]["cash_flow_to_circ_mv"], 100.0 / 1000.0)   # ttm cfo / circ_mv
        self.assertAlmostEqual(items["000001.SZ"]["sales_to_circ_mv"], 1000.0 / 2000.0)      # ttm revenue / circ_mv
        self.assertEqual(items["600000.SH"]["industry_l2"], "L2")
        self.assertEqual(items["600000.SH"]["size_bucket"], "q1")


class MissingMembershipAndClassificationTests(unittest.TestCase):
    def test_missing_sw_membership_excluded_not_aborted(self):
        # F1:活跃 top-500 票无 SW 成员行 → 优雅排除(assemble 放进 exception_symbols → industry_excluded=True、退出行业中性),**不 abort**。
        cash, inc = _annual("600000.SH", cf=100.0, rev=500.0)
        out = dl.assemble_forward_inputs(as_of="20260630", market_cap_records=[{"ts_code": "600000.SH", "circ_mv": 1000.0}],
            cashflow_by_symbol={"600000.SH": cash}, income_by_symbol={"600000.SH": inc},
            daily_by_symbol={"600000.SH": []}, adj_by_symbol={"600000.SH": []}, csi300_records=[],
            index_member_records=[],   # 无任何 SW 成员行
            list_date_by_symbol={"600000.SH": "20100101"}, delist_date_by_symbol={"600000.SH": None},
            selection_status_by_symbol={}, trade_dates=["20260701", "20260702"])
        items = {it["symbol"]: it for it in out["scored_items"]}
        self.assertIn("600000.SH", items)                          # 不 abort、仍在 scored
        self.assertTrue(items["600000.SH"]["industry_excluded"])   # 标 excluded(退出行业中性)
        self.assertIsNone(items["600000.SH"]["industry_l2"])

    def test_future_delist_active_past_delist_delisted(self):
        # F2:未来退市(delist_date>as_of)→ as_of 时仍 active;已退市(<=as_of)→ delisted(PIT 分类,非 `delist_date is None`)。
        ctx = dl.build_forward_context(symbols=["600000.SH", "600001.SH"], trade_dates=["20240628"],
            list_date_by_symbol={"600000.SH": "20100101", "600001.SH": "20100101"},
            delist_date_by_symbol={"600000.SH": "20251231", "600001.SH": "20230101"},
            selection_status_by_symbol={}, as_of="20240628")
        self.assertEqual(ctx.active_symbols, ["600000.SH"])     # 未来退市:as_of 时仍活跃
        self.assertEqual(ctx.delisted_symbols, ["600001.SH"])  # 已退市

    def test_delisted_by_list_status_origin_even_when_delist_date_blank(self):
        # F2(Codex re-审查):provider 给 list_status=D 但 delist_date 字段为空时,**按 origin 判已退市**——纯 delist_date
        # 判法会把这种已退市票误判成 active;L-origin 即使无 delist_date 也是 active。
        ctx = dl.build_forward_context(symbols=["600000.SH", "600001.SH"], trade_dates=["20240628"],
            list_date_by_symbol={"600000.SH": "20100101", "600001.SH": "20100101"},
            delist_date_by_symbol={"600000.SH": None, "600001.SH": None},   # 两票 delist_date 字段都空
            list_status_by_symbol={"600000.SH": "L", "600001.SH": "D"},
            selection_status_by_symbol={}, as_of="20240628")
        self.assertEqual(ctx.active_symbols, ["600000.SH"])     # L-origin → active
        self.assertEqual(ctx.delisted_symbols, ["600001.SH"])  # D-origin(delist_date 空)→ 仍 delisted

    def test_d_origin_blank_delist_fail_closed_in_assemble(self):
        # round 3(Codex re-审查):D-origin(list_status=D)但 delist_date 空 → assemble fail-closed(不得 delist_by_symbol=None 让 backfill 当未退市)。
        cash, inc = _annual("600001.SH", cf=100.0, rev=500.0)
        with self.assertRaises(ValueError):
            dl.assemble_forward_inputs(as_of="20260630", market_cap_records=[{"ts_code": "600001.SH", "circ_mv": 1000.0}],
                cashflow_by_symbol={"600001.SH": cash}, income_by_symbol={"600001.SH": inc},
                daily_by_symbol={"600001.SH": []}, adj_by_symbol={"600001.SH": []}, csi300_records=[],
                index_member_records=[{"ts_code": "600001.SH", "in_date": "20100101", "out_date": None, "l2_code": "L2", "l1_code": "L1"}],
                list_date_by_symbol={"600001.SH": "20100101"}, delist_date_by_symbol={"600001.SH": None},
                list_status_by_symbol={"600001.SH": "D"}, selection_status_by_symbol={}, trade_dates=["20260701", "20260702"])

    def test_d_origin_past_delist_excluded_from_scoring_not_aborted(self):
        # round 3:D-origin 有过去 delist_date → 不 abort,但已退市票不入新篮子(scored 不含),delist_by_symbol 保留真日期供 backfill terminal return。
        cash, inc = _annual("600001.SH", cf=100.0, rev=500.0)
        out = dl.assemble_forward_inputs(as_of="20260630", market_cap_records=[{"ts_code": "600001.SH", "circ_mv": 1000.0}],
            cashflow_by_symbol={"600001.SH": cash}, income_by_symbol={"600001.SH": inc},
            daily_by_symbol={"600001.SH": []}, adj_by_symbol={"600001.SH": []}, csi300_records=[],
            index_member_records=[{"ts_code": "600001.SH", "in_date": "20100101", "out_date": None, "l2_code": "L2", "l1_code": "L1"}],
            list_date_by_symbol={"600001.SH": "20100101"}, delist_date_by_symbol={"600001.SH": "20240101"},
            list_status_by_symbol={"600001.SH": "D"}, selection_status_by_symbol={}, trade_dates=["20260701", "20260702"])
        self.assertNotIn("600001.SH", {it["symbol"] for it in out["scored_items"]})   # 已退市不入新篮子
        self.assertEqual(out["delist_by_symbol"]["600001.SH"], "20240101")            # delist_date 保留供 backfill terminal return


def _panel_n(n, as_of="20260630", trade_dates=("20260701", "20260702", "20260703", "20260704", "20260705")):
    """n 个主板票(600000..)的完整 raw records(circ_mv 降序、cf/sales 随 k 变、同一 L2、老 list、无 veto、极简价格)。"""
    syms = [f"6{k:05d}.SH" for k in range(n)]
    mcap = [{"ts_code": s, "circ_mv": float(10_000_000 - k)} for k, s in enumerate(syms)]
    cf_by, inc_by, daily_by, adj_by = {}, {}, {}, {}
    for k, s in enumerate(syms):
        cash, income = _annual(s, cf=100.0 + k, rev=500.0 + k)
        cf_by[s], inc_by[s] = cash, income
        daily_by[s] = [{"ts_code": s, "trade_date": d, "close": 10.0 + i} for i, d in enumerate(trade_dates)]
        adj_by[s] = [{"ts_code": s, "trade_date": d, "adj_factor": 1.0} for d in trade_dates]
    ind = [{"ts_code": s, "in_date": "20100101", "out_date": None, "l2_code": "L2X", "l1_code": "L1X"} for s in syms]
    csi = [{"ts_code": dl.CSI300_CODE, "trade_date": d, "close": 3000.0} for d in trade_dates]
    return dict(as_of=as_of, market_cap_records=mcap, cashflow_by_symbol=cf_by, income_by_symbol=inc_by,
                daily_by_symbol=daily_by, adj_by_symbol=adj_by, csi300_records=csi, index_member_records=ind,
                list_date_by_symbol={s: "20100101" for s in syms}, delist_date_by_symbol={s: None for s in syms},
                selection_status_by_symbol={}, trade_dates=list(trade_dates))


class DataLayerToBrainEndToEndTests(unittest.TestCase):
    def test_assemble_then_build_accumulator_passes_write(self):
        panel = _panel_n(250)                       # 250 主板票 → 过 size≥50/industry≥20 中性化门
        out = dl.assemble_forward_inputs(**panel)
        self.assertGreaterEqual(len(out["scored_items"]), 250)
        acc = cap.build_forward_accumulator(
            prior_accumulator=None, as_of="20260630", captured_at="t", universe_size=out["universe_size"],
            scored_items=out["scored_items"], stock_price_cache=out["stock_price_cache"],
            csi300_prices=out["csi300_prices"], trade_dates=out["trade_dates"],
            delist_by_symbol=out["delist_by_symbol"], generated_at="t")
        cap.write_accumulator(acc, _tmp_out())      # schema + 一致性 双校验通过
        self.assertEqual(len(acc["cohorts"]), 1)
        self.assertEqual(acc["paper_read"]["routing"], "insufficient_cohorts")   # 短 trade_dates → 全 pending
        for con in acc["cohorts"][0]["constructions"]:
            self.assertEqual(con["basket_size"], 50)   # max(10, int(250*0.2)=50)


class _FakePro:
    """mock tushare pro:每方法返回小份 canned records(2 主板票)。"""
    def daily_basic(self, **kw):
        return [{"ts_code": "600000.SH", "trade_date": "20260630", "circ_mv": 2000.0},
                {"ts_code": "600001.SH", "trade_date": "20260630", "circ_mv": 1000.0}]
    def cashflow(self, ts_code, **kw):
        return [{"ts_code": ts_code, "end_date": "20251231", "ann_date": "20260120", "f_ann_date": "20260120", "n_cashflow_act": 100.0}]
    def income(self, ts_code, **kw):
        return [{"ts_code": ts_code, "end_date": "20251231", "ann_date": "20260120", "f_ann_date": "20260120", "revenue": 500.0, "n_income_attr_p": 1.0}]
    def daily(self, ts_code, **kw):
        return [{"ts_code": ts_code, "trade_date": "20260701", "close": 10.0}]
    def adj_factor(self, ts_code, **kw):
        return [{"ts_code": ts_code, "trade_date": "20260701", "adj_factor": 1.0}]
    def index_daily(self, **kw):
        return [{"ts_code": dl.CSI300_CODE, "trade_date": "20260701", "close": 3000.0}]
    def index_member_all(self, **kw):
        ts_code = kw.get("ts_code")
        if ts_code:
            return [{"ts_code": ts_code, "in_date": "20100101", "out_date": None, "l2_code": "L2", "l1_code": "L1"}]
        return [{"ts_code": "600000.SH", "in_date": "20100101", "out_date": None, "l2_code": "L2", "l1_code": "L1"},
                {"ts_code": "600001.SH", "in_date": "20100101", "out_date": None, "l2_code": "L2", "l1_code": "L1"}]
    def stock_basic(self, list_status, **kw):
        if list_status == "L":
            return [{"ts_code": "600000.SH", "list_date": "20100101", "delist_date": None},
                    {"ts_code": "600001.SH", "list_date": "20100101", "delist_date": None}]
        return []
    def namechange(self, **kw):
        ts_code = kw.get("ts_code", "600000.SH")
        return [{"ts_code": ts_code, "name": "测试一", "start_date": "20100101", "end_date": None}]
    def trade_cal(self, **kw):
        return [{"cal_date": "20260629", "is_open": "1"}, {"cal_date": "20260630", "is_open": "1"},
                {"cal_date": "20260701", "is_open": "1"}, {"cal_date": "20260702", "is_open": "1"},
                {"cal_date": "20260630", "is_open": "0"}]


class FetchWiringTests(unittest.TestCase):
    def test_fetch_panel_then_assemble(self):
        panel = dl.fetch_forward_panel(as_of="20260630", pro=_FakePro())
        # fetch 产出的 kwargs 直接喂 assemble(键对齐)
        self.assertEqual(set(panel["cashflow_by_symbol"]), {"600000.SH", "600001.SH"})
        self.assertEqual(panel["list_date_by_symbol"]["600000.SH"], "20100101")
        self.assertEqual(panel["trade_dates"], ["20260629", "20260630", "20260701", "20260702"])   # 只收 is_open=1
        out = dl.assemble_forward_inputs(**panel)
        self.assertEqual({it["symbol"] for it in out["scored_items"]}, {"600000.SH", "600001.SH"})


def _tmp_out():
    import os
    import tempfile
    return os.path.join(tempfile.mkdtemp(), "acc.json")


class _RecordingPro(_FakePro):
    """记录每个 endpoint 收到的 kwargs(验 Finding 3 explicit window 接线)。"""
    def __init__(self):
        self.calls = {}

    def cashflow(self, **kw):
        self.calls["cashflow"] = kw
        return super().cashflow(**kw)

    def daily(self, **kw):
        self.calls["daily"] = kw
        return super().daily(**kw)

    def trade_cal(self, **kw):
        self.calls["trade_cal"] = kw
        return super().trade_cal(**kw)

    def index_member_all(self, **kw):
        self.calls.setdefault("index_member_all", []).append(kw)
        return super().index_member_all(**kw)

    def namechange(self, **kw):
        self.calls.setdefault("namechange", []).append(kw)
        return super().namechange(**kw)


class FetchContractTests(unittest.TestCase):
    def test_explicit_windows_passed_to_provider(self):
        pro = _RecordingPro()
        dl.fetch_forward_panel(as_of="20260630", pro=pro, data_through="20260930")
        self.assertEqual(pro.calls["cashflow"]["start_date"], "20230101")   # as_of 年 -3(FORWARD_FUND_HISTORY_YEARS)
        self.assertEqual(pro.calls["cashflow"]["end_date"], "20260630")     # = as_of(PIT)
        self.assertEqual(pro.calls["daily"]["start_date"], "20230101")
        self.assertEqual(pro.calls["daily"]["end_date"], "20260930")        # = data_through(供 backfill)
        self.assertEqual(pro.calls["trade_cal"]["end_date"], "20260930")

    def test_missing_required_field_fails_before_assembly(self):
        class _BadPro(_FakePro):
            def cashflow(self, **kw):   # 缺 n_cashflow_act
                return [{"ts_code": "600000.SH", "end_date": "20251231", "ann_date": "20260120", "f_ann_date": "20260120"}]
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260630", pro=_BadPro())

    def test_daily_basic_missing_required_field_fails_before_assembly(self):
        class _BadPro(_FakePro):
            def daily_basic(self, **kw):   # 缺 circ_mv,否则会静默形成空 universe
                return [{"ts_code": "600000.SH", "trade_date": "20260630"}]
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260630", pro=_BadPro())

    def test_daily_basic_wrong_trade_date_fails_before_assembly(self):
        class _BadPro(_FakePro):
            def daily_basic(self, **kw):
                return [{"ts_code": "600000.SH", "trade_date": "20260629", "circ_mv": 2000.0}]
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260630", pro=_BadPro())

    def test_per_symbol_endpoint_wrong_ts_code_fails_before_assembly(self):
        class _BadPro(_FakePro):
            def cashflow(self, ts_code, **kw):
                return [{"ts_code": "000001.SZ", "end_date": "20251231", "ann_date": "20260120",
                         "f_ann_date": "20260120", "n_cashflow_act": 100.0}]
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260630", pro=_BadPro())

    def test_index_daily_wrong_benchmark_code_fails_before_assembly(self):
        class _BadPro(_FakePro):
            def index_daily(self, **kw):
                return [{"ts_code": "000300.SH", "trade_date": "20260701", "close": 3000.0}]
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260630", pro=_BadPro())

    def test_index_member_all_missing_interval_field_fails_before_assembly(self):
        # min-field 仍守 interval 字段(O3 放宽后 index_member_all required={ts_code,in_date,out_date}):缺 in_date → fail-closed。
        class _BadPro(_FakePro):
            def index_member_all(self, **kw):
                return [{"ts_code": kw.get("ts_code", "600000.SH"), "l1_code": "L1", "l2_code": "L2", "out_date": None}]  # 缺 in_date
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260630", pro=_BadPro())

    def test_index_member_all_name_only_industry_is_legal(self):
        # O3:行业身份只给 l1_name/l2_name(无 _code)仍合法——冻结 industry_values 取 code-or-name(name 是 fallback),不该被 min-field 拒。
        class _NameOnlyPro(_FakePro):
            def index_member_all(self, **kw):
                return [{"ts_code": kw.get("ts_code", "600000.SH"), "l1_name": "金融", "l2_name": "银行",
                         "in_date": "20100101", "out_date": None}]
        panel = dl.fetch_forward_panel(as_of="20260630", pro=_NameOnlyPro())   # 不 raise
        dl.assemble_forward_inputs(**panel)                                    # 装配也不 raise(行业用 name fallback)

    def test_namechange_missing_end_date_fails_before_assembly(self):
        class _BadPro(_FakePro):
            def namechange(self, **kw):   # 缺 end_date 键会让当前 ST/name veto 区间不可审计
                return [{"ts_code": kw.get("ts_code", "600000.SH"), "name": "测试", "start_date": "20100101"}]
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260630", pro=_BadPro())

    def test_stock_basic_missing_delist_date_fails_before_assembly(self):
        class _BadPro(_FakePro):
            def stock_basic(self, list_status, **kw):   # 缺 delist_date 键会让 active/delisted 语义不可审计
                return [{"ts_code": "600000.SH", "list_date": "20100101"}] if list_status == "L" else []
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260630", pro=_BadPro())

    def test_stock_basic_missing_symbol_master_row_fails_before_assembly(self):
        class _BadPro(_FakePro):
            def stock_basic(self, list_status, **kw):
                return []   # daily_basic/price 有票,security master 无行时不能默认为 active/no-delist
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260630", pro=_BadPro())

    def test_default_data_through_fetches_beyond_as_of_for_entry_anchor(self):
        pro = _RecordingPro()
        dl.fetch_forward_panel(as_of="20260630", pro=pro)
        self.assertGreater(pro.calls["trade_cal"]["end_date"], "20260630")
        self.assertLess(pro.calls["trade_cal"]["end_date"], "20260722")   # 不默认跨到 21 个交易日 horizon

    def test_symbol_scoped_industry_and_namechange_calls(self):
        pro = _RecordingPro()
        dl.fetch_forward_panel(as_of="20260630", pro=pro)
        self.assertEqual([c.get("ts_code") for c in pro.calls["index_member_all"]],
                         ["600000.SH", "600001.SH"])
        self.assertEqual([c.get("ts_code") for c in pro.calls["namechange"]],
                         ["600000.SH", "600001.SH"])

    def test_calendar_guard_runs_before_broad_fetch(self):
        # pre-broad(Codex re-审查):非月末 as_of 在拉 top-500 broad 数据前即被日历守门拒,daily_basic 不该被调到。
        class _CountPro(_FakePro):
            def __init__(self):
                self.daily_basic_calls = 0

            def daily_basic(self, **kw):
                self.daily_basic_calls += 1
                return super().daily_basic(**kw)
        pro = _CountPro()
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260615", pro=pro)   # 非月末(_FakePro 6月最后开市=30)
        self.assertEqual(pro.daily_basic_calls, 0)              # broad fetch 未发生(守门在 trade_cal 后、daily_basic 前)

    def test_list_status_origin_threaded_into_panel(self):
        # F2(Codex re-审查):stock_basic L/D origin 真透传进 panel(供 build_forward_context 按 origin 分 active/delisted)。
        panel = dl.fetch_forward_panel(as_of="20260630", pro=_FakePro())
        self.assertEqual(panel["list_status_by_symbol"], {"600000.SH": "L", "600001.SH": "L"})

    def test_empty_daily_basic_fails_closed(self):
        # round 3(Codex re-审查):daily_basic 空返回 → 组不出 universe → live fetch fail-closed(不写 universe_size=0 假 insufficient 月)。
        class _EmptyDailyPro(_FakePro):
            def daily_basic(self, **kw):
                return []
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260630", pro=_EmptyDailyPro())

    def test_all_nonpositive_circ_mv_fails_closed(self):
        # round 3:daily_basic 全 circ_mv<=0 → rank 过滤后空 universe → fail-closed。
        class _ZeroMvPro(_FakePro):
            def daily_basic(self, **kw):
                return [{"ts_code": "600000.SH", "trade_date": "20260630", "circ_mv": 0.0}]
        with self.assertRaises(ValueError):
            dl.fetch_forward_panel(as_of="20260630", pro=_ZeroMvPro())

    def test_ld_duplicate_source_d_origin_wins(self):
        # round 3:同票在 stock_basic L 和 D 都返回 → list_status D(已退市)覆盖 L,避免把已退市票当在市。
        class _DupLDPro(_FakePro):
            def stock_basic(self, list_status, **kw):
                if list_status == "L":
                    return [{"ts_code": "600000.SH", "list_date": "20100101", "delist_date": None},
                            {"ts_code": "600001.SH", "list_date": "20100101", "delist_date": None}]
                return [{"ts_code": "600000.SH", "list_date": "20100101", "delist_date": "20250101"}]
        panel = dl.fetch_forward_panel(as_of="20260630", pro=_DupLDPro())
        self.assertEqual(panel["list_status_by_symbol"]["600000.SH"], "D")   # D 覆盖 L

    def test_noncanonical_data_through_rejected(self):
        # round 3(Codex re-审查):strptime 容忍非标准串;_resolve_data_through 须拒非恰好-8-digit、返 canonical。
        for bad in ("2026071", "202607 1", "2026-07-01", "20260700"):       # 7位/含空格/含分隔/非法日
            with self.assertRaises(ValueError):
                dl._resolve_data_through("20260630", bad)
        self.assertEqual(dl._resolve_data_through("20260630", "20260930"), "20260930")  # canonical 正例


class CalendarValidatorTests(unittest.TestCase):
    """月末 + entry-anchor pre-broad 校验(逻辑从 capture 迁来,单一来源在数据层;raise ValueError)。"""
    def test_month_end_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            dl.validate_as_of_month_end("20260615", ["20260601", "20260615", "20260630"])  # 6月最后开市=30

    def test_month_end_ok_and_month_absent_rejected(self):
        dl.validate_as_of_month_end("20260630", ["20260601", "20260615", "20260630"])      # 月末→不抛
        with self.assertRaises(ValueError):
            dl.validate_as_of_month_end("20260630", ["20260701", "20260702"])              # 缺当月开市日

    def test_entry_anchor_missing_rejected(self):
        dl.validate_entry_anchor("20260630", ["20260630", "20260701"])                     # 有 next-open→不抛
        with self.assertRaises(ValueError):
            dl.validate_entry_anchor("20260630", ["20260601", "20260630"])                 # 无 as_of 之后开市日


if __name__ == "__main__":
    unittest.main()
