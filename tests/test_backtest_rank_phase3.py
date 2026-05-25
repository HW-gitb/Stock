import unittest

import pandas as pd

from runners.backtest_rank import _is_l2_unknown_value, build_analyzer_ablation_variants


class BacktestRankPhase3Tests(unittest.TestCase):
    def test_l2_unknown_normalization_matches_analyzer(self):
        self.assertTrue(_is_l2_unknown_value("未知"))
        self.assertTrue(_is_l2_unknown_value(" unknown "))
        self.assertTrue(_is_l2_unknown_value("UNK"))
        self.assertFalse(_is_l2_unknown_value(""))
        self.assertFalse(_is_l2_unknown_value(None))
        self.assertFalse(_is_l2_unknown_value("专用设备"))

    def test_analyzer_ablation_variant_names_state_scope(self):
        samples = pd.DataFrame([
            {
                "tier": "Tier1",
                "entry_flag": "可直接观察",
                "l4_flag": "",
                "l2_name": "专用设备",
                "esp_raw": 10,
            },
            {
                "tier": "Tier1",
                "entry_flag": "可直接观察",
                "l4_flag": "",
                "l2_name": "专用设备",
                "esp_raw": -1,
            },
            {
                "tier": "Tier2",
                "entry_flag": "追高风险，周一确认",
                "l4_flag": "OVERHEAT",
                "l2_name": "专用设备",
                "esp_raw": 10,
            },
        ])

        variants = build_analyzer_ablation_variants(samples, analyzer_enabled=True)

        self.assertIn("all_analyzer_veto_all_rules", variants)
        self.assertIn("tier1_analyzer_veto_all_rules", variants)
        self.assertIn("all_analyzer_veto_chase_overheat", variants)
        self.assertIn("tier1_analyzer_veto_chase_overheat", variants)
        self.assertNotIn("analyzer_veto_all_rules", variants)
        self.assertEqual(len(variants["all_analyzer_veto_all_rules"]), 1)
        self.assertEqual(len(variants["tier1_analyzer_veto_all_rules"]), 1)
        self.assertEqual(len(variants["all_analyzer_veto_chase_overheat"]), 2)
        self.assertEqual(len(variants["tier1_analyzer_veto_chase_overheat"]), 2)


if __name__ == "__main__":
    unittest.main()
