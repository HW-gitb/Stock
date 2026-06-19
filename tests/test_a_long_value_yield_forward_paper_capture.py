"""A-long value-yield forward-PAPER capture core tests.

Covers the parity-pinned forward rolling-relative-NAV (must equal the frozen batch runner's
`rolling_relative_nav_drawdown` when checkpoints == the frozen MONTHLY_AS_OF_DATES), the paper-read
routing, the value-yield composite definition, and the accumulator assembly/schema/boundary.
The live-fetch data layer + cohort-from-data orchestration are the deferred next slice (not tested here).
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


if __name__ == "__main__":
    unittest.main()
