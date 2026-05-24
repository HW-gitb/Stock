import unittest

from engine.analyzer.rule6_hard_veto import run_veto


def codes(result):
    return {reason["code"] for reason in result["reasons"]}


class Rule6HardVetoTests(unittest.TestCase):
    def test_chasing_high_positive_nested_entry_flag(self):
        result = run_veto({"selection": {"entry_flag": "追高风险，周一确认"}})
        self.assertTrue(result["vetoed"])
        self.assertIn("chasing_high", codes(result))

    def test_chasing_high_negative(self):
        result = run_veto({"derived_flags": {"chasing_high": False}, "selection": {"entry_flag": "可直接观察"}})
        self.assertFalse(result["vetoed"])

    def test_overheat_positive_flat_l4_flag(self):
        result = run_veto({"l4_flag": "OVERHEAT"})
        self.assertTrue(result["vetoed"])
        self.assertIn("overheat", codes(result))

    def test_overheat_negative(self):
        result = run_veto({"derived_flags": {"overheat_flag": False}, "scores": {"l4_flag": "突破型"}})
        self.assertFalse(result["vetoed"])

    def test_l2_unknown_positive_nested_industry(self):
        result = run_veto({"industry": {"sw_l2_name": "未知"}})
        self.assertTrue(result["vetoed"])
        self.assertIn("l2_unknown", codes(result))

    def test_l2_unknown_negative_known_industry(self):
        result = run_veto({"industry": {"sw_l2_name": "专用设备"}})
        self.assertFalse(result["vetoed"])

    def test_esp_non_positive_positive_zero(self):
        result = run_veto({"fundamental": {"expectation": {"esp_raw": 0}}})
        self.assertTrue(result["vetoed"])
        self.assertIn("esp_non_positive", codes(result))

    def test_esp_non_positive_negative_positive_value(self):
        result = run_veto({"esp_raw": 18.5})
        self.assertFalse(result["vetoed"])

    def test_missing_fields_are_diagnostics_not_vetoes(self):
        result = run_veto({}, enabled_rules=["l2_unknown", "esp_non_positive"])
        self.assertFalse(result["vetoed"])
        statuses = {item["status"] for item in result["diagnostics"]}
        self.assertEqual(statuses, {"data_missing"})

    def test_unknown_rule_is_rejected(self):
        with self.assertRaises(ValueError):
            run_veto({}, enabled_rules=["overheat", "lock"])


if __name__ == "__main__":
    unittest.main()

