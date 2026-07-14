import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"
DATA_HEALTH_SCHEMA = ROOT / "schemas" / "data_health.schema.json"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location(
            "egs_main_rank_reconciliation_under_test",
            EGS_SCRIPT,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _frame(*codes):
    return pd.DataFrame({"ts_code": list(codes)})


class RankUniverseReconciliationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def test_expected_l1_l2_exclusions_are_accounted_per_symbol(self) -> None:
        summary, detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B", "C", "D"),
            stages=[
                ("master_join", _frame("A", "B", "C", "D"), False, "master_join_loss"),
                ("l1_industry_leader", _frame("A", "C", "D"), True, "l1_industry_leader_elim"),
                ("l2_quality_risk", _frame("A", "D"), True, "l2_quality_or_risk_elim"),
                ("l5_rank", _frame("A", "D"), False, "l5_unexpected_row_loss"),
            ],
            sources={
                "financial_l0": (_frame("A", "B", "C", "D"), _frame("A", "B", "C", "D"), 1.0),
            },
        )

        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["l0_count"], 4)
        self.assertEqual(summary["ranked_count"], 2)
        self.assertEqual(summary["expected_excluded_count"], 2)
        self.assertEqual(summary["unaccounted_count"], 0)
        self.assertEqual(len(detail), 4)
        by_code = detail.set_index("ts_code").to_dict("index")
        self.assertEqual(by_code["B"]["reason"], "l1_industry_leader_elim")
        self.assertEqual(by_code["C"]["reason"], "l2_quality_or_risk_elim")
        self.assertEqual(by_code["A"]["outcome"], "ranked")

    def test_score_l1_records_the_exact_terminal_reason(self) -> None:
        frame = pd.DataFrame({
            "ts_code": ["A", "B"],
            "l2_name": ["行业A", "未知"],
            "pct_20d": [0.0, 0.0],
            "total_mv": [100.0, 100.0],
            "avg_amount_5d": [2e8, 2e8],
            "pe": [20.0, 20.0],
        })
        reasons = {}

        out = self.egs_main.score_l1(frame, csi300_ret=100.0, exclusion_reasons=reasons)

        self.assertTrue(out.empty)
        self.assertEqual(reasons["A"], "l1_industry_leader_elim")
        self.assertEqual(reasons["B"], "l1_unknown_industry_elim")

    def test_truncated_critical_source_fails_reconciliation(self) -> None:
        summary, _detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B", "C"),
            stages=[
                ("master_join", _frame("A", "B", "C"), False, "master_join_loss"),
                ("l5_rank", _frame("A", "B", "C"), False, "l5_unexpected_row_loss"),
            ],
            sources={
                "financial_l0": (_frame("A", "B", "C"), _frame("A", "B"), 1.0),
            },
        )

        self.assertEqual(summary["status"], "fail")
        self.assertEqual(summary["source_coverage_failure_count"], 1)
        self.assertEqual(summary["source_coverage"]["financial_l0"]["missing_count"], 1)

    def test_unexpected_loss_in_scoring_only_stage_fails_reconciliation(self) -> None:
        summary, detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B"),
            stages=[
                ("master_join", _frame("A", "B"), False, "master_join_loss"),
                ("l3_scoring", _frame("A"), False, "l3_unexpected_row_loss"),
            ],
            sources={},
        )

        self.assertEqual(summary["status"], "fail")
        self.assertEqual(summary["unexpected_stage_change_count"], 1)
        by_code = detail.set_index("ts_code").to_dict("index")
        self.assertEqual(by_code["B"]["reason"], "l3_unexpected_row_loss")

    def _build_health(self, rank_reconciliation):
        ranked = pd.DataFrame({
            "ts_code": ["A", "B"],
            "tier": ["Tier1", "Tier1"],
            "close": [10.0, 11.0],
            "pe": [20.0, 21.0],
            "pb": [2.0, 2.1],
            "l1_name": ["行业A", "行业A"],
            "l2_name": ["行业B", "行业B"],
        })
        analysis_input = {
            "schema_name": "analysis_input",
            "schema_version": "1.1.0",
            "source": {
                "screening_engine_version": self.egs_main.EGS_VERSION,
                "data_provider": "tushare",
            },
            "candidates": [
                {"data_quality": {"completeness_score": 100}},
                {"data_quality": {"completeness_score": 100}},
            ],
        }
        return self.egs_main.build_data_health(
            df_full=ranked,
            watch_df=ranked,
            tier1_final=ranked,
            analysis_input=analysis_input,
            latest_td="20260714",
            analysis_path=str(EGS_SCRIPT),
            snapshot_path=str(EGS_SCRIPT),
            candidates_path=str(EGS_SCRIPT),
            tier1_csv_path=str(EGS_SCRIPT),
            full_csv_path=str(EGS_SCRIPT),
            rank_reconciliation=rank_reconciliation,
        )

    def test_small_but_reconciled_rank_pool_does_not_trigger_legacy_1000_warning(self) -> None:
        summary, _detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B", "C"),
            stages=[
                ("l1_industry_leader", _frame("A", "B"), True, "l1_industry_leader_elim"),
                ("l5_rank", _frame("A", "B"), False, "l5_unexpected_row_loss"),
            ],
            sources={"financial_l0": (_frame("A", "B", "C"), _frame("A", "B", "C"), 1.0)},
        )

        health = self._build_health(summary)

        self.egs_main.validate_json_schema(
            health,
            schema_path=str(DATA_HEALTH_SCHEMA),
            label="rank reconciliation health test",
        )
        self.assertNotIn("full_universe", {item["check"] for item in health["warnings"]})
        self.assertNotIn("rank_universe_reconciliation", {item["check"] for item in health["errors"]})

    def test_source_coverage_failure_is_a_data_health_error(self) -> None:
        summary, _detail = self.egs_main.build_rank_universe_reconciliation(
            df_l0=_frame("A", "B"),
            stages=[("l5_rank", _frame("A", "B"), False, "l5_unexpected_row_loss")],
            sources={"financial_l0": (_frame("A", "B"), _frame("A"), 1.0)},
        )

        health = self._build_health(summary)

        self.assertEqual(health["overall_status"], "error")
        self.assertIn("rank_source_coverage", {item["check"] for item in health["errors"]})


if __name__ == "__main__":
    unittest.main()
