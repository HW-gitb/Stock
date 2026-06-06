import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/a_long_total_return_benchmark_access_probe_summary.schema.json")
SUMMARY_PATH = Path("docs/a_long_total_return_benchmark_access_probe_summary_20260606.json")


class ALongTotalReturnBenchmarkAccessProbeSummarySchemaTest(unittest.TestCase):
    def _schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        return sorted(Draft7Validator(self._schema()).iter_errors(payload), key=lambda error: list(error.path))

    def _valid_summary(self) -> dict:
        probes = []
        for label, control_code, tr_codes in [
            ("CSI300", "000300.SH", ["H00300.CSI", "H000300.CSI", "000300.CSI"]),
            ("CSI1000", "000852.SH", ["H00852.CSI", "H000852.CSI", "000852.CSI"]),
        ]:
            probes.append(
                {
                    "benchmark_label": label,
                    "candidate_role": "price_index_control",
                    "ts_code": control_code,
                    "call_status": "success",
                    "row_count": 7,
                    "columns": ["ts_code", "trade_date", "open", "close"],
                    "open_non_null_count": 7,
                    "close_non_null_count": 7,
                    "same_anchor_open_close_available": True,
                    "close_only_total_return_candidate": False,
                    "tracked_summary_contains_raw_rows": False,
                    "error_class": None,
                    "error_message_redacted": None,
                }
            )
            for code in tr_codes:
                probes.append(
                    {
                        "benchmark_label": label,
                        "candidate_role": "total_return_candidate",
                        "ts_code": code,
                        "call_status": "empty" if not code.startswith("H00") else "success",
                        "row_count": 0 if not code.startswith("H00") else 7,
                        "columns": ["ts_code", "trade_date", "open", "close"],
                        "open_non_null_count": 0,
                        "close_non_null_count": 0 if not code.startswith("H00") else 7,
                        "same_anchor_open_close_available": False,
                        "close_only_total_return_candidate": code in {"H00300.CSI", "H00852.CSI"},
                        "tracked_summary_contains_raw_rows": False,
                        "error_class": None,
                        "error_message_redacted": None,
                    }
                )
        return {
            "schema_name": "a_long_total_return_benchmark_access_probe_summary",
            "schema_version": "1.0.0",
            "generated_at": "2026-06-06T00:00:00+00:00",
            "artifact_id": "a_long_total_return_benchmark_access_probe_summary_20260606",
            "scope": {
                "phase": "7a_alpha_validation",
                "purpose": "a_long_total_return_benchmark_access_probe",
                "lane_id": "a_long",
                "market": "A-share",
                "research_only": True,
                "provider_family": "tushare_existing_account",
                "existing_account_only": True,
                "tushare_calls_executed": True,
                "provider_expansion_allowed": False,
                "paid_tier_change_allowed": False,
                "raw_payloads_written": False,
                "tracked_summary_contains_raw_rows": False,
                "tracked_summary_contains_secret": False,
                "signal_search_executed": False,
                "alpha_backtest_executed": False,
                "production_use_allowed": False,
                "ship_gate_claim_allowed": False,
                "full_size_manual_use_allowed": False,
                "broker_or_order_automation_allowed": False,
            },
            "probe_design": {
                "start_date": "20200102",
                "end_date": "20200110",
                "required_basis": "benchmark_total_return_index_next_trading_day_open_to_same_exit_close",
                "required_fields": ["ts_code", "trade_date", "open", "close"],
                "control_price_indices": {"CSI300": "000300.SH", "CSI1000": "000852.SH"},
                "total_return_candidates": {
                    "CSI300": ["H00300.CSI", "H000300.CSI", "000300.CSI"],
                    "CSI1000": ["H00852.CSI", "H000852.CSI", "000852.CSI"],
                },
                "max_total_calls": 8,
            },
            "direct_probes": probes,
            "decision": {
                "benchmark_access_status": "blocked_total_return_same_anchor_open_unavailable",
                "control_price_index_probe_passed": True,
                "selected_total_return_codes": {"CSI300": None, "CSI1000": None},
                "signal_search_may_execute": False,
                "runner_benchmark_switch_allowed": False,
                "price_index_fallback_allowed": False,
                "derived_total_return_open_allowed": False,
                "plain_result": "Total-return close data exists, but open is missing.",
                "next_action": "Stop A-long signal search.",
            },
            "prohibited_claims": {
                "a_long_alpha_found": False,
                "signal_search_authorized": False,
                "benchmark_total_return_route_ready": False,
                "price_index_benchmark_allowed": False,
                "derived_total_return_open_allowed": False,
                "production_ready": False,
                "ship_gate_evidence": False,
                "full_size_allowed": False,
                "datahub_authorized": False,
                "broker_or_order_automation_authorized": False,
            },
            "limitations": ["No raw rows, no signal search."],
        }

    def test_schema_meta_validates(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        Draft7Validator.check_schema(self._schema())
        self.assertFalse(self._schema()["additionalProperties"])

    def test_valid_summary_validates(self) -> None:
        self.assertEqual(self._validate(self._valid_summary()), [])

    def test_access_pass_still_does_not_authorize_signal_search(self) -> None:
        valid = self._valid_summary()
        valid["decision"]["benchmark_access_status"] = "passed_total_return_same_anchor_open_available"
        valid["decision"]["selected_total_return_codes"] = {
            "CSI300": "H00300.CSI",
            "CSI1000": "H00852.CSI",
        }
        valid["decision"]["plain_result"] = "Total-return benchmark access can prepare materialization."
        valid["decision"]["next_action"] = "Prepare reviewed benchmark materialization packet."

        self.assertEqual(self._validate(valid), [])
        self.assertFalse(valid["decision"]["signal_search_may_execute"])
        self.assertFalse(valid["decision"]["runner_benchmark_switch_allowed"])

    def test_generated_summary_validates_when_present(self) -> None:
        if not SUMMARY_PATH.exists():
            raise unittest.SkipTest("probe summary has not been generated yet")
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self._validate(summary), [])
        text = SUMMARY_PATH.read_text(encoding="utf-8")
        self.assertNotIn('"records"', text)
        self.assertNotIn("TUSHARE_TOKEN", text)

    def test_scope_creep_is_rejected(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["scope"]["signal_search_executed"] = True
        invalid["decision"]["signal_search_may_execute"] = True
        invalid["decision"]["price_index_fallback_allowed"] = True
        invalid["prohibited_claims"]["benchmark_total_return_route_ready"] = True

        self.assertGreaterEqual(len(self._validate(invalid)), 4)


if __name__ == "__main__":
    unittest.main()
