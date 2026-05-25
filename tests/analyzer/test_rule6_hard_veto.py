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

    def test_esp_non_positive_positive_negative_value(self):
        result = run_veto({"fundamental": {"expectation": {"esp_raw": -1.5}}}, enabled_rules=["esp_non_positive"])
        self.assertTrue(result["vetoed"])
        self.assertIn("esp_non_positive", codes(result))

    def test_esp_zero_is_diagnostic_not_veto(self):
        result = run_veto({"fundamental": {"expectation": {"esp_raw": 0}}}, enabled_rules=["esp_non_positive"])
        self.assertFalse(result["vetoed"])
        self.assertEqual(result["diagnostics"][0]["status"], "neutral_zero_not_vetoed")

    def test_esp_non_positive_negative_positive_value(self):
        result = run_veto({"esp_raw": 18.5}, enabled_rules=["esp_non_positive"])
        self.assertFalse(result["vetoed"])

    def test_missing_fields_are_diagnostics_not_vetoes(self):
        result = run_veto({}, enabled_rules=["l2_unknown", "esp_non_positive"])
        self.assertFalse(result["vetoed"])
        statuses = {item["status"] for item in result["diagnostics"]}
        self.assertEqual(statuses, {"data_missing"})

    def test_unknown_rule_is_rejected(self):
        with self.assertRaises(ValueError):
            run_veto({}, enabled_rules=["overheat", "lock"])

    def test_diagnostic_field_records_path_that_was_checked(self):
        # Phase 3 audit (2026-05-24): previously _first_present stashed the
        # last-resolved path on a function attribute, so a diagnostic written
        # for a missing field could silently inherit the path from a prior
        # call. Now each check pulls its own (value, path) tuple.
        result = run_veto(
            {"selection": {"entry_flag": "可直接观察"}},
            enabled_rules=["overheat"],
        )
        self.assertFalse(result["vetoed"])
        self.assertEqual(len(result["diagnostics"]), 1)
        diag = result["diagnostics"][0]
        self.assertEqual(diag["code"], "overheat")
        self.assertEqual(diag["status"], "data_missing")
        # Field should list overheat's own probe paths, not entry_flag.
        self.assertIn("overheat_flag", diag["field"])
        self.assertNotIn("entry_flag", diag["field"])

    def test_esp_nan_string_is_diagnostic_not_silent_pass(self):
        # float("nan") parses but every comparison is False; without the
        # parsed!=parsed guard the rule would silently fall through with no
        # diagnostic and no veto, hiding bad input.
        result = run_veto({"esp_raw": "nan"}, enabled_rules=["esp_non_positive"])
        self.assertFalse(result["vetoed"])
        self.assertEqual(result["diagnostics"][0]["status"], "data_unparseable")

    def test_l2_empty_string_is_missing_not_unknown(self):
        # Backtest's build_group_columns flags "" as unknown for stats
        # coverage, but the analyzer must treat "" as data_missing, not as
        # an explicit "未知" label (Phase 3 spec: missing != negative).
        result = run_veto({"l2_name": ""}, enabled_rules=["l2_unknown"])
        self.assertFalse(result["vetoed"])
        self.assertEqual(result["diagnostics"][0]["status"], "data_missing")

    def test_overheat_no_false_positive_on_substring_label(self):
        # Phase 3 audit (2026-05-25): "OVERHEAT" in str(flag).upper() would
        # match "NO_OVERHEAT" or "OVERHEAT_CLEARED" if EGS ever extends the
        # vocabulary. Token-based matching is the safer contract.
        for label in ["NO_OVERHEAT", "OVERHEAT_CLEARED", "NOT-OVERHEAT"]:
            result = run_veto({"l4_flag": label}, enabled_rules=["overheat"])
            self.assertFalse(result["vetoed"], f"false positive on label: {label}")
        # Plain OVERHEAT still fires.
        result = run_veto({"l4_flag": "OVERHEAT"}, enabled_rules=["overheat"])
        self.assertTrue(result["vetoed"])
        # Composite labels with OVERHEAT as a token still fire.
        result = run_veto({"l4_flag": "BREAKOUT|OVERHEAT"}, enabled_rules=["overheat"])
        self.assertTrue(result["vetoed"])

    def test_parse_bool_numeric_zero_one(self):
        # Phase 3 audit (2026-05-25): pandas-loaded bool columns sometimes
        # become int/float 0/1. _parse_bool must accept these, not return
        # None (which would emit a misleading 'data_unparseable' diagnostic).
        self.assertTrue(run_veto({"chasing_high": 1}, enabled_rules=["chasing_high"])["vetoed"])
        self.assertFalse(run_veto({"chasing_high": 0}, enabled_rules=["chasing_high"])["vetoed"])
        self.assertTrue(run_veto({"chasing_high": 1.0}, enabled_rules=["chasing_high"])["vetoed"])

    def test_pd_na_treated_as_missing_not_present(self):
        # Phase 3 audit (2026-05-25): _is_missing_value previously caught
        # TypeError from bool(pd.NA) and returned False (a present value),
        # which would let pd.NA flow into downstream checks. Now NA-like
        # sentinels are treated as missing.
        try:
            import pandas as pd
        except ModuleNotFoundError:
            self.skipTest("pandas not available")
        result = run_veto({"esp_raw": pd.NA}, enabled_rules=["esp_non_positive"])
        self.assertFalse(result["vetoed"])
        # Must surface as data_missing, not data_unparseable.
        statuses = {d["status"] for d in result["diagnostics"]}
        self.assertEqual(statuses, {"data_missing"})


if __name__ == "__main__":
    unittest.main()
