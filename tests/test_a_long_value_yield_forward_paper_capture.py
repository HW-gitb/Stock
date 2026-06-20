"""A-long value-yield forward-PAPER capture core tests.

Covers the parity-pinned forward rolling-relative-NAV (must equal the frozen batch runner's
`rolling_relative_nav_drawdown` when checkpoints == the frozen MONTHLY_AS_OF_DATES), the paper-read
routing, the value-yield composite definition, and the accumulator assembly/schema/boundary.
Also covers the gated live-fetch data-layer wiring with mock providers; real provider calls remain out of scope.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import a_long_large_cap_batch_factor_search_signal_search as bf  # noqa: E402
from runners import a_long_large_cap_value_yield_forward_paper_capture as cap  # noqa: E402

SCHEMA = json.loads((ROOT / "schemas" / "a_long_large_cap_value_yield_forward_paper_accumulator.schema.json").read_text(encoding="utf-8"))


def _tmp_out():
    import os
    return os.path.join(tempfile.mkdtemp(), "acc.json")


class ForwardRollingNavParityTests(unittest.TestCase):
    """forward_rolling_relative_nav_drawdown 与冻结 bf.rolling_relative_nav_drawdown 在 checkpoints==
    sorted(bf.MONTHLY_AS_OF_DATES) 时逐字段相等(差别仅 checkpoints 参数化;短 horizon 下用小 fixture 验非空 NAV)。"""

    def _fixture(self):
        # 26 个合成有序交易日(只做字符串比较/bisect/index,无需真历法语义)。
        trade_dates = [f"202601{d:02d}" for d in range(2, 28)]
        # 每符号/基准的合成收盘(随 index 单调,基本面无关,只验 NAV 一致)。
        def closes(base_, step):
            return {d: {"close": base_ + i * step} for i, d in enumerate(trade_dates)}
        stock_price_cache = {"AAA.SZ": closes(10.0, 0.10), "BBB.SZ": closes(20.0, 0.05)}
        csi300_prices = closes(3000.0, 1.0)
        primary_selections = {"20260102": ["AAA.SZ", "BBB.SZ"]}
        return trade_dates, stock_price_cache, csi300_prices, primary_selections

    def test_forward_rolling_nav_parity(self):
        trade_dates, spc, csi, sel = self._fixture()
        orig_h, orig_dates = bf.PRIMARY_HORIZON, bf.MONTHLY_AS_OF_DATES
        try:
            bf.PRIMARY_HORIZON = 5        # 短 horizon → 小 fixture 即可成熟出非空 NAV(entry+5)
            bf.MONTHLY_AS_OF_DATES = ["20260103", "20260105", "20260106", "20260108", "20260110"]
            frozen = bf.rolling_relative_nav_drawdown(
                primary_selections=sel, stock_price_cache=spc, csi300_prices=csi, trade_dates=trade_dates)
            forward = cap.forward_rolling_relative_nav_drawdown(
                primary_selections=sel, stock_price_cache=spc, csi300_prices=csi, trade_dates=trade_dates,
                checkpoints=sorted(bf.MONTHLY_AS_OF_DATES))
            self.assertEqual(forward, frozen)                         # 逐字段相等
            self.assertGreater(frozen["relative_nav_checkpoint_count"], 0)   # 且非空(真验到逻辑,非空对空)
        finally:
            bf.PRIMARY_HORIZON, bf.MONTHLY_AS_OF_DATES = orig_h, orig_dates

    def test_forward_rolling_nav_checkpoints_param_used(self):
        # 反向:换 checkpoints(空)→ 无 NAV(证明用的是参数而非全局)。
        trade_dates, spc, csi, sel = self._fixture()
        out = cap.forward_rolling_relative_nav_drawdown(
            primary_selections=sel, stock_price_cache=spc, csi300_prices=csi, trade_dates=trade_dates, checkpoints=[])
        self.assertEqual(out["relative_nav_checkpoint_count"], 0)


class ValueYieldCompositeTests(unittest.TestCase):
    def test_both_present_equal_weight_mean(self):
        item = {"cash_flow_to_circ_mv__industry_size_neutral": 0.8, "sales_to_circ_mv__industry_size_neutral": 0.6}
        self.assertAlmostEqual(cap.value_yield_composite_score(item), 0.7)

    def test_one_missing_unknown(self):
        self.assertIsNone(cap.value_yield_composite_score({"cash_flow_to_circ_mv__industry_size_neutral": 0.8}))
        self.assertIsNone(cap.value_yield_composite_score({}))


class PaperReadTests(unittest.TestCase):
    def test_insufficient_cohorts(self):
        r = cap.compute_paper_read({"persistence_positive": True, "rolling_relative_nav_max_drawdown": -0.10}, 11)
        self.assertEqual(r["routing"], "insufficient_cohorts")
        self.assertFalse(r["read_available"])

    def test_promote_eligible(self):
        r = cap.compute_paper_read({"persistence_positive": True, "rolling_relative_nav_max_drawdown": -0.12}, 12)
        self.assertEqual(r["routing"], "promote_eligible_pending_new_reviewed_real_money_prereg")
        self.assertTrue(r["decision_is_advisory_not_authorization"])   # 不授权真钱

    def test_stay_research_drawdown_breach(self):
        r = cap.compute_paper_read({"persistence_positive": True, "rolling_relative_nav_max_drawdown": -0.20}, 12)
        self.assertEqual(r["routing"], "stay_research_only_or_drop")

    def test_stay_research_no_persistence(self):
        r = cap.compute_paper_read({"persistence_positive": False, "rolling_relative_nav_max_drawdown": -0.05}, 12)
        self.assertEqual(r["routing"], "stay_research_only_or_drop")

    def test_primary_construction_is_composite_only(self):
        r = cap.compute_paper_read({}, 0)
        self.assertEqual(r["primary_construction_id"], "value_yield_composite_cf_sales")


# ── legal accumulator fixtures(共享:Assembly + Consistency 两类用;basket_size==selected_symbols 数、3 构造、role↔id 一致)──
_MATURED_ASOFS = ["20260630", "20260731", "20260831", "20260930", "20261031", "20261130",
                  "20261231", "20270131", "20270227", "20270331", "20270430", "20270531"]   # 12 个 ≥ start_floor


def _legal_construction(cid, role, *, matured=False, basket=2):
    syms = [f"{cid[:4]}{i}.SZ" for i in range(basket)]
    hz = {"504": {"status": "matured" if matured else "pending",
                  "relative_excess_net": 0.05 if matured else None,
                  "exit_date": "20280701" if matured else None,
                  "exit_policy": "scheduled_exit" if matured else None}}
    return {"construction_id": cid, "promotion_role": role, "basket_size": basket,
            "selected_symbols": syms, "entry_date": "20260701", "entry_status": "ok", "horizons": hz}


def _legal_cohort(as_of="20260630", *, matured=False):
    return {"as_of": as_of, "captured_at": "t", "universe_size": 480,
            "pit_source": "forward_live_frozen_at_as_of",
            "constructions": [
                _legal_construction("cash_flow_to_circ_mv", "diagnostic_supporting_only", matured=matured),
                _legal_construction("sales_to_circ_mv", "diagnostic_supporting_only", matured=matured),
                _legal_construction("value_yield_composite_cf_sales", "primary_promotion_construction", matured=matured),
            ]}


def _legal_metrics(*, matured_count=0, persistence=None, dd=None):
    def m(cid, role, primary):
        return {"construction_id": cid, "promotion_role": role, "matured_cohort_count": matured_count,
                "mean_relative_excess": (0.05 if (primary and matured_count) else None),
                "hac_t": None, "hac_p": None,
                "rolling_relative_nav_max_drawdown": (dd if primary else None),
                "persistence_positive": (persistence if primary else None)}
    return [m("cash_flow_to_circ_mv", "diagnostic_supporting_only", False),
            m("sales_to_circ_mv", "diagnostic_supporting_only", False),
            m("value_yield_composite_cf_sales", "primary_promotion_construction", True)]


def _legal_pending_acc():
    return cap.build_accumulator(cohorts=[_legal_cohort()], construction_metrics=_legal_metrics(matured_count=0),
                                 paper_read=cap.compute_paper_read({}, 0),
                                 as_of_latest_capture="20260630", generated_at="t")


def _legal_matured_promote_acc():
    pm = {"persistence_positive": True, "rolling_relative_nav_max_drawdown": -0.10}
    return cap.build_accumulator(
        cohorts=[_legal_cohort(d, matured=True) for d in _MATURED_ASOFS],
        construction_metrics=_legal_metrics(matured_count=12, persistence=True, dd=-0.10),
        paper_read=cap.compute_paper_read(pm, 12), as_of_latest_capture="20270531", generated_at="t")


class AccumulatorAssemblyTests(unittest.TestCase):
    def test_legal_pending_schema_and_consistency(self):
        acc = _legal_pending_acc()
        jsonschema.validate(acc, SCHEMA)
        cap.validate_accumulator_consistency(acc)                     # 双校验都过

    def test_boundary_and_prohibited_all_false(self):
        acc = _legal_pending_acc()
        self.assertTrue(all(v is False for v in acc["boundary"].values()))
        self.assertTrue(all(v is False for v in acc["prohibited_claims"].values()))
        self.assertEqual(acc["scope"]["evidence_level"], "paper")
        self.assertEqual(acc["frozen_construction_ref"]["prereg_artifact_id"], cap.PREREG_ID)

    def test_write_accumulator_roundtrip(self):
        import os
        acc = _legal_pending_acc()
        path = os.path.join(tempfile.mkdtemp(), "acc.json")
        cap.write_accumulator(acc, path)                              # schema + 一致性 双校验 + 原子写
        self.assertEqual(json.loads(Path(path).read_text(encoding="utf-8")), acc)


class AccumulatorConsistencyTests(unittest.TestCase):
    """R-ALONG-VY-FP-ACCUMULATOR-SCHEMA-PROMOTION-GATE-GAP:每个 Codex 坏 probe → 被 schema 或 validator 拒;legal 不误拒。"""

    def test_legal_matured_promote_passes_both(self):
        acc = _legal_matured_promote_acc()
        jsonschema.validate(acc, SCHEMA)
        cap.validate_accumulator_consistency(acc)
        self.assertEqual(acc["paper_read"]["routing"], "promote_eligible_pending_new_reviewed_real_money_prereg")

    # ── validator 跨字段拒 ──
    def test_promote_with_zero_cohorts_rejected(self):
        acc = _legal_pending_acc()
        acc["paper_read"]["routing"] = "promote_eligible_pending_new_reviewed_real_money_prereg"
        with self.assertRaises(ValueError):
            cap.validate_accumulator_consistency(acc)

    def test_insufficient_with_enough_cohorts_rejected(self):
        acc = _legal_matured_promote_acc()
        acc["paper_read"]["routing"] = "insufficient_cohorts"
        with self.assertRaises(ValueError):
            cap.validate_accumulator_consistency(acc)

    def test_pre_start_cohort_rejected(self):
        acc = _legal_pending_acc()
        acc["cohorts"][0]["as_of"] = "20260529"                       # < start_floor 20260630
        with self.assertRaises(ValueError):
            cap.validate_accumulator_consistency(acc)

    def test_basket_size_mismatch_rejected(self):
        acc = _legal_pending_acc()
        acc["cohorts"][0]["constructions"][0]["basket_size"] = 20     # selected_symbols 仍 2 个
        with self.assertRaises(ValueError):
            cap.validate_accumulator_consistency(acc)

    def test_single_factor_as_primary_rejected_validator(self):
        acc = _legal_pending_acc()
        for m in acc["construction_metrics"]:
            if m["construction_id"] == "cash_flow_to_circ_mv":
                m["promotion_role"] = "primary_promotion_construction"
        with self.assertRaises(ValueError):
            cap.validate_accumulator_consistency(acc)

    def test_matured_count_overclaim_rejected(self):
        acc = _legal_pending_acc()                                    # 实际 0 个 matured cohort
        acc["paper_read"]["matured_cohort_count"] = 12
        acc["paper_read"]["read_available"] = True
        acc["paper_read"]["routing"] = "stay_research_only_or_drop"   # read↔routing 自洽,单测 count 不变式
        for m in acc["construction_metrics"]:
            if m["construction_id"] == "value_yield_composite_cf_sales":
                m["matured_cohort_count"] = 12
        with self.assertRaises(ValueError):                           # n=12 但 actual 504-matured=0
            cap.validate_accumulator_consistency(acc)

    def test_missing_source_ref_rejected(self):
        acc = _legal_pending_acc()
        acc["source_refs"] = [r for r in acc["source_refs"] if "execution_summary.json" not in r["path"]]
        with self.assertRaises(ValueError):
            cap.validate_accumulator_consistency(acc)

    # ── residual contract gaps(Codex re-审查 FAIL):construction 身份唯一/全覆盖 + 精确 source ref + cohort as_of 唯一 ──
    def test_duplicate_construction_metrics_rejected(self):
        # residual #1:重复 construction_metrics(primary 行重复 → 4 行)→ schema(maxItems:3)或 validator 拒。
        acc = _legal_pending_acc()
        acc["construction_metrics"].append(dict(acc["construction_metrics"][-1]))
        with self.assertRaises((ValueError, jsonschema.ValidationError)):
            cap.write_accumulator(acc, _tmp_out())

    def test_duplicate_construction_in_cohort_rejected(self):
        # residual #2:一个 cohort 内重复 composite 构造行 → schema 或 validator 拒。
        acc = _legal_pending_acc()
        cons = acc["cohorts"][0]["constructions"]
        cons.append(dict(cons[-1]))
        with self.assertRaises((ValueError, jsonschema.ValidationError)):
            cap.write_accumulator(acc, _tmp_out())

    def test_missing_primary_construction_in_cohort_rejected(self):
        # residual #3:cohort 缺 primary(只剩 2 单因子)→ schema(minItems:3)或 validator 拒。
        acc = _legal_pending_acc()
        acc["cohorts"][0]["constructions"] = [
            c for c in acc["cohorts"][0]["constructions"]
            if c["construction_id"] != "value_yield_composite_cf_sales"]
        with self.assertRaises((ValueError, jsonschema.ValidationError)):
            cap.write_accumulator(acc, _tmp_out())

    def test_wrong_source_ref_substring_rejected(self):
        # residual #4:伪造 ledger 路径(仍含旧子串)→ 精确匹配拒(旧子串检查会漏)。
        acc = _legal_pending_acc()
        evil = "research/ledgers/evil/not_the_right_program_test_budget_ledger_20260609.json"
        self.assertIn("_program_test_budget_ledger_20260609.json", evil)   # 证明旧子串检查会放行
        acc["source_refs"] = [({"path": evil, "role": r["role"]} if r["path"] == cap.LEDGER_PATH else r)
                              for r in acc["source_refs"]]
        with self.assertRaises((ValueError, jsonschema.ValidationError)):
            cap.write_accumulator(acc, _tmp_out())

    def test_construction_metrics_identity_dup_caught_by_validator(self):
        # 3 行但 primary 重复、缺 sales(count==3 过 schema)→ validator multiset 身份拒(非仅靠 schema 计数)。
        acc = _legal_pending_acc()
        for m in acc["construction_metrics"]:
            if m["construction_id"] == "sales_to_circ_mv":
                m["construction_id"] = "value_yield_composite_cf_sales"
                m["promotion_role"] = "primary_promotion_construction"
        jsonschema.validate(acc, SCHEMA)                                # schema(count==3)放行
        with self.assertRaises(ValueError):
            cap.validate_accumulator_consistency(acc)                   # validator multiset 拒

    def test_duplicate_cohort_as_of_rejected(self):
        # 同 as_of 重复 cohort(可双计 matured 越 12 门)→ validator 拒。
        acc = _legal_pending_acc()
        acc["cohorts"].append(_legal_cohort("20260630"))
        with self.assertRaises(ValueError):
            cap.validate_accumulator_consistency(acc)

    def test_as_of_latest_capture_mismatch_rejected(self):
        # as_of_latest_capture 与最新 cohort as_of 漂移 → validator 拒(metadata↔data 一致)。
        acc = _legal_pending_acc()
        acc["as_of_latest_capture"] = "20270101"
        with self.assertRaises(ValueError):
            cap.validate_accumulator_consistency(acc)

    # ── frozen-horizon 元数据(Codex re-审查 FAIL round3):interim 集 const + 每 construction 必含主 504 horizon ──
    def test_interim_horizons_empty_rejected(self):
        acc = _legal_pending_acc()
        acc["forward_window"]["interim_horizons_trading_days"] = []
        with self.assertRaises((ValueError, jsonschema.ValidationError)):
            cap.write_accumulator(acc, _tmp_out())

    def test_interim_horizons_duplicate_rejected(self):
        acc = _legal_pending_acc()
        acc["forward_window"]["interim_horizons_trading_days"] = [21, 21]
        with self.assertRaises((ValueError, jsonschema.ValidationError)):
            cap.write_accumulator(acc, _tmp_out())

    def test_construction_missing_primary_504_horizon_rejected(self):
        acc = _legal_pending_acc()
        for con in acc["cohorts"][0]["constructions"]:
            if con["construction_id"] == "value_yield_composite_cf_sales":
                con["horizons"] = {}                                   # 缺 504
        with self.assertRaises((ValueError, jsonschema.ValidationError)):
            cap.write_accumulator(acc, _tmp_out())

    def test_construction_only_interim_horizon_no_504_rejected(self):
        acc = _legal_pending_acc()
        for con in acc["cohorts"][0]["constructions"]:
            if con["construction_id"] == "value_yield_composite_cf_sales":
                con["horizons"] = {"21": {"status": "pending", "relative_excess_net": None,
                                          "exit_date": None, "exit_policy": None}}   # 只 21,无 504
        with self.assertRaises((ValueError, jsonschema.ValidationError)):
            cap.write_accumulator(acc, _tmp_out())

    def test_construction_with_interim_horizons_also_legal(self):
        # 决策另一侧:interim horizon 可选但**允许**存在(非禁止);只要含主 504 即合法。
        acc = _legal_pending_acc()
        for con in acc["cohorts"][0]["constructions"]:
            con["horizons"]["21"] = {"status": "pending", "relative_excess_net": None, "exit_date": None, "exit_policy": None}
            con["horizons"]["63"] = {"status": "pending", "relative_excess_net": None, "exit_date": None, "exit_policy": None}
        jsonschema.validate(acc, SCHEMA)
        cap.validate_accumulator_consistency(acc)

    # ── schema(enum/propertyNames/uniqueItems/if-then)拒 ──
    def test_unknown_horizon_key_rejected_by_schema(self):
        acc = _legal_pending_acc()
        acc["cohorts"][0]["constructions"][0]["horizons"]["999"] = {
            "status": "pending", "relative_excess_net": None, "exit_date": None, "exit_policy": None}
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(acc, SCHEMA)

    def test_matured_null_excess_rejected_by_schema(self):
        acc = _legal_pending_acc()
        acc["cohorts"][0]["constructions"][0]["horizons"]["504"]["status"] = "matured"   # excess 仍 null
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(acc, SCHEMA)

    def test_dup_symbols_rejected_by_schema(self):
        acc = _legal_pending_acc()
        acc["cohorts"][0]["constructions"][0]["selected_symbols"] = ["X.SZ", "X.SZ"]
        acc["cohorts"][0]["constructions"][0]["basket_size"] = 2
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(acc, SCHEMA)

    def test_single_factor_as_primary_rejected_by_schema(self):
        acc = _legal_pending_acc()
        for m in acc["construction_metrics"]:
            if m["construction_id"] == "sales_to_circ_mv":
                m["promotion_role"] = "primary_promotion_construction"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(acc, SCHEMA)

    def test_interim_horizon_unknown_rejected_by_schema(self):
        acc = _legal_pending_acc()
        acc["forward_window"]["interim_horizons_trading_days"] = [999]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(acc, SCHEMA)


# ── 编排核心(brain)fixtures:合成 items + 价格世界(无需 PayloadStore;字符串交易日只做比较/index/bisect)──
def _td(n):
    return [f"T{i:05d}" for i in range(n)]          # 排序字符串交易日,均 > 任何 2026MMDD as_of("T">"2")


def _flat_idx(trade_dates, level=3000.0):
    return {d: {"close": level} for d in trade_dates}


def _rising(trade_dates, base_close, step):
    return {d: {"close": base_close + i * step} for i, d in enumerate(trade_dates)}


class NeutralizeTests(unittest.TestCase):
    def _items(self):
        items = []
        for b in range(5):
            for j in range(50):                     # 50/bucket × 5 = 250(满足 size-neutral ≥50 + industry ≥20)
                k = b * 50 + j
                items.append({"symbol": f"{k:06d}.SZ", "as_of": "20260630",
                              "industry_l2": "L2X", "industry_l1": "L1X", "size_bucket": f"q{b + 1}",
                              "market_cap": 1e9 + k,
                              "cash_flow_to_circ_mv": 0.01 + k * 0.0001, "sales_to_circ_mv": 0.5 + k * 0.001})
        return items

    def test_sets_three_score_fields_composite_is_mean(self):
        items = self._items()
        cap.neutralize_value_yield_scores(items)
        it = items[123]
        cf = it["cash_flow_to_circ_mv__industry_size_neutral"]
        sa = it["sales_to_circ_mv__industry_size_neutral"]
        comp = it["value_yield_composite_cf_sales__industry_size_neutral"]
        self.assertIsNotNone(cf)
        self.assertIsNotNone(sa)
        self.assertAlmostEqual(comp, (cf + sa) / 2.0)   # 合成 = 2 个 isn 等权均值(非全 family COMPOSITE_ID)


class SelectBasketTests(unittest.TestCase):
    def test_top_fraction_floor_and_members(self):
        items = [{"symbol": f"{k:04d}.SZ", "sc": float(k)} for k in range(50)]
        basket = cap.select_basket(items, "sc")
        self.assertEqual(len(basket), 10)                          # max(10, int(50*0.2)=10)
        self.assertEqual(set(basket), {f"{k:04d}.SZ" for k in range(40, 50)})  # 最高分 10 个

    def test_floor_fraction_above_min(self):
        items = [{"symbol": f"{k:04d}.SZ", "sc": float(k)} for k in range(60)]
        self.assertEqual(len(cap.select_basket(items, "sc")), 12)  # int(60*0.2)=12 > 10

    def test_below_min_top_count_empty(self):
        items = [{"symbol": f"{k}.SZ", "sc": float(k)} for k in range(9)]
        self.assertEqual(cap.select_basket(items, "sc"), [])

    def test_score_only_not_excess_filtered(self):
        # forward 分歧:仅按 score 选,不按未来收益过滤(in-sample 的 excess-present 过滤是 look-ahead)。
        items = [{"symbol": f"{k:04d}.SZ", "sc": float(k)} for k in range(12)]
        self.assertIn("0011.SZ", cap.select_basket(items, "sc"))   # 最高分必入选,无论将来有无收益


class CohortSnapshotTests(unittest.TestCase):
    def _scored(self, n):
        return [{"symbol": f"{k:04d}.SZ", "as_of": "20260630", "market_cap": 1e9 + k,
                 "cash_flow_to_circ_mv__industry_size_neutral": float(k),
                 "sales_to_circ_mv__industry_size_neutral": float(k),
                 "value_yield_composite_cf_sales__industry_size_neutral": float(k)} for k in range(n)]

    def test_three_constructions_all_pending(self):
        td = _td(600)
        cohort = cap.build_cohort_snapshot("20260630", self._scored(12), captured_at="t", universe_size=480, trade_dates=td)
        self.assertEqual(len(cohort["constructions"]), 3)
        for con in cohort["constructions"]:
            self.assertEqual(con["basket_size"], 10)
            self.assertEqual(con["entry_date"], td[0])
            self.assertEqual(set(con["horizons"]), {"21", "63", "126", "252", "504"})
            self.assertTrue(all(h["status"] == "pending" for h in con["horizons"].values()))

    def test_insufficient_basket(self):
        td = _td(600)
        cohort = cap.build_cohort_snapshot("20260630", self._scored(5), captured_at="t", universe_size=480, trade_dates=td)
        for con in cohort["constructions"]:
            self.assertEqual(con["basket_size"], 0)
            self.assertEqual(con["entry_status"], "insufficient_basket")
            self.assertIsNone(con["entry_date"])

    def test_missing_entry_date_branch(self):
        # 篮子非空但 as_of 之后无交易日(as_of 晚于所有 trade_dates)→ entry None / missing_entry_close。
        td = _td(600)
        cohort = cap.build_cohort_snapshot("T99999", self._scored(12), captured_at="t", universe_size=480, trade_dates=td)
        con = cohort["constructions"][0]
        self.assertEqual(con["basket_size"], 10)
        self.assertIsNone(con["entry_date"])
        self.assertEqual(con["entry_status"], "missing_entry_date")
        self.assertTrue(all(h["status"] == "missing_entry_close" for h in con["horizons"].values()))


class BackfillTests(unittest.TestCase):
    def _cohort(self, as_of, symbols, trade_dates):
        hz = {str(h): {"status": "pending", "relative_excess_net": None, "exit_date": None, "exit_policy": None}
              for h in cap.ALL_HORIZONS}
        con = {"construction_id": "value_yield_composite_cf_sales", "promotion_role": "primary_promotion_construction",
               "basket_size": len(symbols), "selected_symbols": list(symbols),
               "entry_date": cap._first_trade_day_after(as_of, trade_dates),   # 冻结 PIT 锚
               "entry_status": "ok", "horizons": hz}
        return {"as_of": as_of, "captured_at": "t", "universe_size": 480,
                "pit_source": "forward_live_frozen_at_as_of", "constructions": [con]}

    def test_matured_excess_value_idempotent_scheduled_policy(self):
        td = _td(600)
        spc = {"A.SZ": _rising(td, 10.0, 0.1), "B.SZ": _rising(td, 20.0, 0.05)}
        csi = _flat_idx(td)
        cohort = self._cohort("20260630", ["A.SZ", "B.SZ"], td)
        cap.backfill_cohort(cohort, stock_price_cache=spc, csi300_prices=csi, trade_dates=td, delist_by_symbol={})
        rec = cohort["constructions"][0]["horizons"]["21"]
        self.assertEqual(rec["status"], "matured")
        self.assertEqual(rec["exit_policy"], "scheduled_exit_basket_equal_weight")   # 全 scheduled
        cost = cap.base.ROUND_TRIP_COST                       # 等权篮子;csi 平→bench 0
        ex_a = (10.0 + 21 * 0.1) / 10.0 - 1 - cost
        ex_b = (20.0 + 21 * 0.05) / 20.0 - 1 - cost
        self.assertAlmostEqual(rec["relative_excess_net"], round((ex_a + ex_b) / 2.0, 10), places=8)
        before = json.dumps(cohort, sort_keys=True)
        cap.backfill_cohort(cohort, stock_price_cache=spc, csi300_prices=csi, trade_dates=td, delist_by_symbol={})
        self.assertEqual(json.dumps(cohort, sort_keys=True), before)   # 幂等

    def test_pending_when_horizon_not_reached(self):
        td = _td(30)                                          # 21 可到期,63/504 未到
        spc = {"A.SZ": _rising(td, 10.0, 0.1)}
        cohort = self._cohort("20260630", ["A.SZ"], td)
        cap.backfill_cohort(cohort, stock_price_cache=spc, csi300_prices=_flat_idx(td), trade_dates=td, delist_by_symbol={})
        self.assertEqual(cohort["constructions"][0]["horizons"]["21"]["status"], "matured")
        self.assertEqual(cohort["constructions"][0]["horizons"]["504"]["status"], "pending")

    def test_missing_exit_close_when_no_member_resolves(self):
        td = _td(600)
        cohort = self._cohort("20260630", ["X.SZ"], td)       # 篮子成员无价格
        cap.backfill_cohort(cohort, stock_price_cache={}, csi300_prices=_flat_idx(td), trade_dates=td, delist_by_symbol={})
        self.assertEqual(cohort["constructions"][0]["horizons"]["21"]["status"], "missing_exit_close")
        self.assertIsNone(cohort["constructions"][0]["horizons"]["21"]["relative_excess_net"])

    def test_backfill_uses_frozen_entry_drift_rejected(self):
        # Finding 1:冻结 entry 与当前 first-open-after-as_of 不符 → fail-closed(拒静默重锚,防 OOS 证据污染)。
        td = _td(600)
        cohort = self._cohort("20260630", ["A.SZ"], td)
        cohort["constructions"][0]["entry_date"] = td[5]      # 篡改成非 first-open(模拟历史日历被改/错锚)
        with self.assertRaises(ValueError):
            cap.backfill_cohort(cohort, stock_price_cache={"A.SZ": _rising(td, 10.0, 0.1)},
                                csi300_prices=_flat_idx(td), trade_dates=td, delist_by_symbol={})

    def test_backfill_missing_frozen_entry_on_ok_rejected(self):
        # Finding 1:entry_status=ok 但缺冻结 entry → fail-closed。
        td = _td(600)
        cohort = self._cohort("20260630", ["A.SZ"], td)
        cohort["constructions"][0]["entry_date"] = None
        with self.assertRaises(ValueError):
            cap.backfill_cohort(cohort, stock_price_cache={"A.SZ": _rising(td, 10.0, 0.1)},
                                csi300_prices=_flat_idx(td), trade_dates=td, delist_by_symbol={})

    def test_matured_mixed_exit_policy_on_delist(self):
        # Finding 2:成员在 504 scheduled exit 前退市 → 篮子 exit_policy 标 mixed_member_exits(不伪装 scheduled,保 survivorship)。
        td = _td(600)
        a = _rising(td, 10.0, 0.1)
        b = {d: {"close": 20.0 + i * 0.05} for i, d in enumerate(td[:301])}   # B 价格只到 td[300]
        cohort = self._cohort("20260630", ["A.SZ", "B.SZ"], td)
        cap.backfill_cohort(cohort, stock_price_cache={"A.SZ": a, "B.SZ": b}, csi300_prices=_flat_idx(td),
                            trade_dates=td, delist_by_symbol={"B.SZ": td[305]})
        rec504 = cohort["constructions"][0]["horizons"]["504"]
        self.assertEqual(rec504["status"], "matured")
        self.assertTrue(rec504["exit_policy"].startswith("mixed_member_exits:"))
        self.assertIn("terminal_last_trade_before_delist", rec504["exit_policy"])
        self.assertEqual(cohort["constructions"][0]["horizons"]["21"]["exit_policy"],  # 短 horizon B 仍有价 → 全 scheduled
                         "scheduled_exit_basket_equal_weight")


class ForwardAccumulatorTests(unittest.TestCase):
    def _raw_items(self, as_of, n=250):
        items = []
        per = n // 5
        for b in range(5):
            for j in range(per):
                k = b * per + j
                items.append({"symbol": f"{k:06d}.SZ", "as_of": as_of, "industry_l2": "L2X", "industry_l1": "L1X",
                              "size_bucket": f"q{b + 1}", "market_cap": 1e9 + k,
                              "cash_flow_to_circ_mv": 0.01 + k * 0.0001, "sales_to_circ_mv": 0.5 + k * 0.001})
        return items

    def _prices(self, td, items):
        return {it["symbol"]: _rising(td, 10.0, 0.05) for it in items}

    def test_end_to_end_pending_passes_write(self):
        td = _td(520)                                         # 504 < 520 → 504 matured
        items = self._raw_items("20260630")
        acc = cap.build_forward_accumulator(
            prior_accumulator=None, as_of="20260630", captured_at="t", universe_size=480,
            scored_items=items, stock_price_cache=self._prices(td, items), csi300_prices=_flat_idx(td),
            trade_dates=td, delist_by_symbol={}, generated_at="t")
        cap.write_accumulator(acc, _tmp_out())               # schema + 一致性 双校验通过
        self.assertEqual(len(acc["cohorts"]), 1)
        self.assertEqual(acc["paper_read"]["routing"], "insufficient_cohorts")
        primary = next(m for m in acc["construction_metrics"] if m["construction_id"] == "value_yield_composite_cf_sales")
        self.assertEqual(primary["matured_cohort_count"], 1)

    def test_second_capture_accumulates_and_updates_latest(self):
        td = _td(520)
        i1 = self._raw_items("20260630")
        acc1 = cap.build_forward_accumulator(
            prior_accumulator=None, as_of="20260630", captured_at="t", universe_size=480,
            scored_items=i1, stock_price_cache=self._prices(td, i1), csi300_prices=_flat_idx(td),
            trade_dates=td, delist_by_symbol={}, generated_at="t")
        i2 = self._raw_items("20260731")
        acc2 = cap.build_forward_accumulator(
            prior_accumulator=acc1, as_of="20260731", captured_at="t", universe_size=480,
            scored_items=i2, stock_price_cache=self._prices(td, i2), csi300_prices=_flat_idx(td),
            trade_dates=td, delist_by_symbol={}, generated_at="t")
        self.assertEqual(len(acc2["cohorts"]), 2)
        self.assertEqual(acc2["as_of_latest_capture"], "20260731")
        cap.write_accumulator(acc2, _tmp_out())

    def test_duplicate_as_of_capture_rejected(self):
        td = _td(520)
        items = self._raw_items("20260630")
        acc1 = cap.build_forward_accumulator(
            prior_accumulator=None, as_of="20260630", captured_at="t", universe_size=480,
            scored_items=items, stock_price_cache=self._prices(td, items), csi300_prices=_flat_idx(td),
            trade_dates=td, delist_by_symbol={}, generated_at="t")
        with self.assertRaises(ValueError):
            cap.build_forward_accumulator(
                prior_accumulator=acc1, as_of="20260630", captured_at="t2", universe_size=480,
                scored_items=self._raw_items("20260630"), stock_price_cache=self._prices(td, items),
                csi300_prices=_flat_idx(td), trade_dates=td, delist_by_symbol={}, generated_at="t2")

    def test_out_of_order_capture_rejected(self):
        td = _td(520)
        i1 = self._raw_items("20260731")
        acc1 = cap.build_forward_accumulator(
            prior_accumulator=None, as_of="20260731", captured_at="t", universe_size=480,
            scored_items=i1, stock_price_cache=self._prices(td, i1), csi300_prices=_flat_idx(td),
            trade_dates=td, delist_by_symbol={}, generated_at="t")
        old_items = self._raw_items("20260630")
        with self.assertRaises(ValueError):
            cap.build_forward_accumulator(
                prior_accumulator=acc1, as_of="20260630", captured_at="t2", universe_size=480,
                scored_items=old_items, stock_price_cache=self._prices(td, old_items),
                csi300_prices=_flat_idx(td), trade_dates=td, delist_by_symbol={}, generated_at="t2")

    def test_assemble_metrics_rolling_drawdown_wired(self):
        # realistic-sortable 8 位日期(as_of 是交易日,checkpoint 能落进 tranche 区间)→ 真跑 assemble→forward_rolling
        # 回撤接线(非 None);synthetic 的 "T#####" 日期会让 checkpoint 早于 entry、回撤恒 None,故此处单独验。
        td = [f"3{i:07d}" for i in range(560)]   # "30000000".. ≥ start_floor、8 位、可排序;宽到 3 cohort 504 都到期
        spc = {"A.SZ": _rising(td, 10.0, 0.1), "B.SZ": _rising(td, 20.0, 0.05)}
        csi = _flat_idx(td)

        def cohort(as_of):
            hz = {str(h): {"status": "pending", "relative_excess_net": None, "exit_date": None, "exit_policy": None}
                  for h in cap.ALL_HORIZONS}
            con = {"construction_id": "value_yield_composite_cf_sales", "promotion_role": "primary_promotion_construction",
                   "basket_size": 2, "selected_symbols": ["A.SZ", "B.SZ"],
                   "entry_date": cap._first_trade_day_after(as_of, td),   # 冻结 PIT 锚(backfill 用快照 entry)
                   "entry_status": "ok", "horizons": hz}
            return {"as_of": as_of, "captured_at": "t", "universe_size": 480,
                    "pit_source": "forward_live_frozen_at_as_of", "constructions": [con]}

        cohorts = [cohort(td[0]), cohort(td[10]), cohort(td[20])]   # entries idx1/11/21,504-exit 505/515/525<560 都到期;后 checkpoint 落进早 tranche → ≥2 NAV 点
        for c in cohorts:
            cap.backfill_cohort(c, stock_price_cache=spc, csi300_prices=csi, trade_dates=td, delist_by_symbol={})
        metrics = cap.assemble_construction_metrics(cohorts, stock_price_cache=spc, csi300_prices=csi, trade_dates=td)
        primary = next(m for m in metrics if m["construction_id"] == "value_yield_composite_cf_sales")
        self.assertEqual(primary["matured_cohort_count"], 3)         # 三 cohort 504 都到期
        self.assertIsNotNone(primary["rolling_relative_nav_max_drawdown"])  # 回撤接线真跑出值

    def test_brain_promote_eligible_end_to_end(self):
        # O5:12 个 matured cohort 经真 build_forward_accumulator → promote_eligible(覆盖决策边界,非仅 hand-built fixture)。
        td = [f"3{i:07d}" for i in range(800)]   # 8 位可排序 ≥ start_floor;宽到 504 都到期
        syms = [f"6{k:05d}.SH" for k in range(50)]
        spc = {s: _rising(td, 10.0, 0.05) for s in syms}     # 篮子涨 → 正超额 + 小回撤(≥ -0.15)
        csi = _flat_idx(td)

        def scored(as_of):
            return [{"symbol": s, "as_of": as_of, "industry_l2": "L2X", "industry_l1": "L1X",
                     "size_bucket": "q1", "market_cap": 1e9 + k,
                     "cash_flow_to_circ_mv": 0.01 + k * 0.001, "sales_to_circ_mv": 0.5 + k * 0.01}
                    for k, s in enumerate(syms)]

        acc = None
        for i in range(12):
            acc = cap.build_forward_accumulator(prior_accumulator=acc, as_of=td[5 * i], captured_at="t",
                universe_size=50, scored_items=scored(td[5 * i]), stock_price_cache=spc, csi300_prices=csi,
                trade_dates=td, delist_by_symbol={}, generated_at="t")
        cap.write_accumulator(acc, _tmp_out())                        # schema + 一致性 双校验过
        self.assertEqual(len(acc["cohorts"]), 12)
        primary = next(m for m in acc["construction_metrics"] if m["construction_id"] == "value_yield_composite_cf_sales")
        self.assertEqual(primary["matured_cohort_count"], 12)
        self.assertTrue(primary["persistence_positive"])
        self.assertEqual(acc["paper_read"]["routing"], "promote_eligible_pending_new_reviewed_real_money_prereg")


class _CapFakePro:
    """mock tushare pro(2 主板票)→ 测 run_forward_capture 全接线(fetch→assemble→brain→write)。"""
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
        return [{"ts_code": "H00300.CSI", "trade_date": "20260701", "close": 3000.0}]
    def index_member_all(self, **kw):
        ts_code = kw.get("ts_code")
        if ts_code:
            return [{"ts_code": ts_code, "in_date": "20100101", "out_date": None, "l2_code": "L2", "l1_code": "L1"}]
        return [{"ts_code": "600000.SH", "in_date": "20100101", "out_date": None, "l2_code": "L2", "l1_code": "L1"},
                {"ts_code": "600001.SH", "in_date": "20100101", "out_date": None, "l2_code": "L2", "l1_code": "L1"}]
    def stock_basic(self, list_status, **kw):
        return ([{"ts_code": "600000.SH", "list_date": "20100101", "delist_date": None},
                 {"ts_code": "600001.SH", "list_date": "20100101", "delist_date": None}] if list_status == "L" else [])
    def namechange(self, **kw):
        return [{"ts_code": kw.get("ts_code", "600000.SH"), "name": "测试", "start_date": "20100101", "end_date": None}]
    def trade_cal(self, **kw):
        return [{"cal_date": "20260629", "is_open": "1"}, {"cal_date": "20260630", "is_open": "1"},
                {"cal_date": "20260701", "is_open": "1"}, {"cal_date": "20260702", "is_open": "1"}]


class ForwardCaptureWiringTests(unittest.TestCase):
    def test_run_forward_capture_writes_valid_accumulator(self):
        import os
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "research", "results", "a_long_vy", "acc.json")  # research-only(过 Finding 4 守门)
        acc = cap.run_forward_capture(as_of="20260630", out=out, prior_accumulator=None,
                                      pro=_CapFakePro(), generated_at="t", captured_at="t")
        self.assertEqual(json.loads(Path(out).read_text(encoding="utf-8")), acc)   # 落盘 == 返回(write_accumulator 双校验过)
        self.assertEqual(len(acc["cohorts"]), 1)
        self.assertEqual(acc["paper_read"]["routing"], "insufficient_cohorts")
        for con in acc["cohorts"][0]["constructions"]:
            self.assertEqual(con["basket_size"], 0)                                # 2 票过不了 size≥50 中性化门 → 空篮子

    def test_prior_basket_symbols_union(self):
        prior = {"cohorts": [
            {"constructions": [{"selected_symbols": ["A.SZ", "B.SZ"]}, {"selected_symbols": ["B.SZ", "C.SZ"]}]},
            {"constructions": [{"selected_symbols": ["C.SZ", "D.SZ"]}]}]}
        self.assertEqual(cap._prior_basket_symbols(prior), ("A.SZ", "B.SZ", "C.SZ", "D.SZ"))
        self.assertEqual(cap._prior_basket_symbols(None), ())

    def test_run_forward_capture_rejects_bad_prior_before_fetch(self):
        class _ExplodingPro:
            def daily_basic(self, **kw):
                raise AssertionError("provider should not be called before prior accumulator validation")

        import os
        import tempfile
        bad = _legal_pending_acc()
        bad["source_refs"] = []
        out = os.path.join(tempfile.mkdtemp(), "research", "results", "a_long_vy", "acc.json")
        with self.assertRaises((ValueError, jsonschema.ValidationError)):
            cap.run_forward_capture(as_of="20260630", out=out, prior_accumulator=bad,
                                    pro=_ExplodingPro(), generated_at="t", captured_at="t")

    def test_run_forward_capture_requires_post_as_of_entry_anchor(self):
        class _NoFutureTradePro(_CapFakePro):
            def trade_cal(self, **kw):
                return [{"cal_date": "20260629", "is_open": "1"}, {"cal_date": "20260630", "is_open": "1"}]

        import os
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "research", "results", "a_long_vy", "acc.json")
        with self.assertRaises(ValueError):   # entry-anchor 守门已前移进 dl.fetch_forward_panel(pre-broad),抛 ValueError
            cap.run_forward_capture(as_of="20260630", out=out, prior_accumulator=None,
                                    pro=_NoFutureTradePro(), generated_at="t", captured_at="t",
                                    data_through="20260630")


class CaptureArgGuardTests(unittest.TestCase):
    """Finding 4:as_of floor/格式 + research-only out fail-closed 守门(月末/entry-anchor 守门已前移至数据层 pre-broad,测试见 data-layer)。"""
    def test_as_of_below_floor_rejected(self):
        with self.assertRaises(SystemExit):
            cap._validate_capture_args("20260101", "research/results/a_long_vy/x.json")

    def test_as_of_bad_format_rejected(self):
        with self.assertRaises(SystemExit):
            cap._validate_capture_args("2026-06-30", "research/results/a_long_vy/x.json")

    def test_out_production_path_rejected(self):
        with self.assertRaises(SystemExit):
            cap._validate_capture_args("20260630", "result/a_long/x.json")     # 生产 result/ 顶层

    def test_out_nested_result_path_rejected(self):
        with self.assertRaises(SystemExit):
            cap._validate_capture_args("20260630", "D:/cnhea/Stock/result/research/a_long_vy/x.json")

    def test_out_non_research_rejected(self):
        with self.assertRaises(SystemExit):
            cap._validate_capture_args("20260630", "tmp/x.json")               # 不含 research/

    def test_legal_args_ok(self):
        cap._validate_capture_args("20260630", "research/results/a_long_vy/acc.json")   # 不抛

    def test_out_traversal_to_result_rejected(self):
        # round 3(Codex re-审查):normpath 解析 `..` 后落到生产 result(case-insensitive)应被拒,即使原串含 research segment。
        with self.assertRaises(SystemExit):
            cap._validate_capture_args("20260630", "research/../RESULT/a_long/x.json")


if __name__ == "__main__":
    unittest.main()
