from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator

from engine.us_short_market_diagnostic_attribution import (
    AttributionError,
    build_attribution_input,
    build_attribution_report,
    calculate_target_exposure,
    validate_attribution_input,
    validate_attribution_report,
)
from tests.test_us_short_market_diagnostic import _weekly_rows


class UsShortMarketDiagnosticAttributionTest(unittest.TestCase):
    def _cash(self, rows: list[dict], *, unavailable_week: int | None = None) -> dict[int, dict]:
        result: dict[int, dict] = {}
        for row in rows:
            week = row["calendar_week_index"]
            if week == unavailable_week:
                continue
            valuation = datetime.strptime(row["valuation_date"], "%Y%m%d").date()
            source = f"{500 + week:064x}"
            result[week] = {
                "status": "evaluable",
                "instrument": "pit_3m_tbill",
                "weekly_return": 0.0001,
                "effective_start_date": (valuation - timedelta(days=7)).strftime("%Y%m%d"),
                "effective_end_date": valuation.strftime("%Y%m%d"),
                "as_of_date": valuation.strftime("%Y%m%d"),
                "available_at": f"{row['decision_date'][0:4]}-{row['decision_date'][4:6]}-{row['decision_date'][6:8]}T08:00:00Z",
                "source_sha256": source,
                "source_refs": [source],
                "data_quality_reasons": [],
            }
        return result

    def _target(self, rows: list[dict], *, cash_capacity: float = 0.5) -> dict[int, dict]:
        result: dict[int, dict] = {}
        for row in rows:
            week = row["calendar_week_index"]
            source = f"{600 + week:064x}"
            result[week] = {
                "status": "evaluable",
                "carried_holdings_exposure": 0.2,
                "new_order_exposure": 0.4,
                "cash_capacity_exposure": cash_capacity,
                "environment_position_cap": 0.8,
                "long_only_cap": 1.0,
                "source_refs": [source],
                "data_quality_reasons": [],
            }
        return result

    def _packet(self, *, price_only: bool = False, cash: dict[int, dict] | None = None) -> dict:
        rows = _weekly_rows(price_only=price_only)[:2]
        return build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash(rows) if cash is None else cash,
        )

    def test_complete_packet_splits_excess_and_preserves_identity(self) -> None:
        packet = self._packet()
        report = build_attribution_report(packet)

        self.assertEqual(report["status"], "evaluable")
        self.assertEqual(report["summary"]["evaluable_weeks"], 2)
        self.assertEqual(report["summary"]["unavailable_weeks"], 0)
        for row in report["weeks"]:
            self.assertEqual(row["g_star"], 0.5)
            self.assertAlmostEqual(
                row["raw_excess"], row["exposure_effect"] + row["active_system_effect"], places=12
            )
            self.assertAlmostEqual(row["identity_residual"], 0.0, places=12)
        self.assertAlmostEqual(
            report["summary"]["raw_excess"],
            report["summary"]["exposure_effect"] + report["summary"]["active_system_effect"],
            places=12,
        )
        validate_attribution_report(report)
        schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "schemas"
                / "us_short_market_diagnostic_attribution_report.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            [],
            list(Draft7Validator(schema).iter_errors(report)),
        )

    def test_missing_cash_is_unavailable_and_never_zero_filled(self) -> None:
        rows = _weekly_rows()[:2]
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week={},
        )
        report = build_attribution_report(packet)

        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["summary"]["evaluable_weeks"], 0)
        self.assertEqual(report["summary"]["unavailable_weeks"], 2)
        self.assertIsNone(report["summary"]["active_system_effect"])
        self.assertIn("pit_3m_tbill_not_available", report["weeks"][0]["unavailable_reasons"])
        self.assertTrue(all(row["matched_target_return"] is None for row in report["weeks"]))
        validate_attribution_report(report)

    def test_price_only_vti_cannot_enter_attribution(self) -> None:
        report = build_attribution_report(self._packet(price_only=True))

        self.assertEqual(report["status"], "unavailable")
        self.assertTrue(all(row["vti_total_return"] is None for row in report["weeks"]))
        self.assertIn("vti_total_return_not_available", report["weeks"][0]["unavailable_reasons"])

    def test_target_exposure_uses_rule_constraints_not_actual_nav(self) -> None:
        target = {
            "status": "evaluable",
            "carried_holdings_exposure": 0.7,
            "new_order_exposure": 0.6,
            "cash_capacity_exposure": 0.9,
            "environment_position_cap": 0.8,
            "long_only_cap": 1.0,
            "source_refs": ["a" * 64],
            "data_quality_reasons": [],
        }

        result = calculate_target_exposure(target)

        self.assertAlmostEqual(result["requested_exposure"], 1.3)
        self.assertAlmostEqual(result["g_star"], 0.8)
        self.assertEqual(result["binding_constraints"], ["environment_position_cap"])

    def test_cash_observation_after_decision_date_is_rejected(self) -> None:
        rows = _weekly_rows()[:2]
        cash = self._cash(rows)
        cash[1]["available_at"] = "2026-01-03T08:00:00Z"

        with self.assertRaises(AttributionError):
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=cash,
            )

    def test_historical_backfill_boundary_is_fail_closed(self) -> None:
        packet = self._packet()
        packet["boundary"]["historical_backfill_performed"] = True

        with self.assertRaises(AttributionError):
            build_attribution_report(packet)

    def test_report_source_binding_and_status_counts_are_fail_closed(self) -> None:
        report = build_attribution_report(self._packet())
        report["source_refs"] = report["source_refs"][1:]
        with self.assertRaises(AttributionError):
            validate_attribution_report(report)

        report = build_attribution_report(self._packet())
        report["summary"]["unavailable_weeks"] = 1
        with self.assertRaises(AttributionError):
            validate_attribution_report(report)

    def test_report_validator_rederives_g_star_and_binding_constraints(self) -> None:
        report = build_attribution_report(self._packet())
        week = report["weeks"][0]
        week["g_star"] = 0.9
        week["requested_exposure"] = 0.1
        week["constraint_exposures"]["requested_exposure"] = 0.1
        week["binding_constraints"] = ["requested_exposure"]
        week["matched_target_return"] = (
            week["g_star"] * week["vti_total_return"]
            + (1.0 - week["g_star"]) * week["cash_weekly_return"]
        )
        week["raw_excess"] = week["strategy_weekly_return"] - week["vti_total_return"]
        week["exposure_effect"] = week["matched_target_return"] - week["vti_total_return"]
        week["active_system_effect"] = week["strategy_weekly_return"] - week["matched_target_return"]
        week["identity_residual"] = 0.0

        with self.assertRaises(AttributionError):
            validate_attribution_report(report)

    def test_as_of_date_blocks_future_input_report_and_cash_availability(self) -> None:
        rows = _weekly_rows()[:2]
        cash = self._cash(rows)
        with self.assertRaises(AttributionError):
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=cash,
                as_of_date="20260101",
            )

        packet = self._packet()
        with self.assertRaises(AttributionError):
            validate_attribution_input(packet, as_of_date="20260101")

        report = build_attribution_report(packet)
        with self.assertRaises(AttributionError):
            validate_attribution_report(report, as_of_date="20260101")

    def test_public_apis_normalize_untyped_input_failures(self) -> None:
        target = self._target(_weekly_rows()[:1])[1]
        target["cash_capacity_exposure"] = 10**10000
        with self.assertRaises(AttributionError):
            calculate_target_exposure(target)

        rows = _weekly_rows()[:2]
        cash = self._cash(rows)
        cash[1]["available_at"] = None
        with self.assertRaises(AttributionError):
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=cash,
            )

        with self.assertRaises(AttributionError):
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=[],
                cash_return_by_week=self._cash(rows),
            )

        malformed = _weekly_rows()[:2]
        malformed[0]["calendar_week_index"] = "1"
        with self.assertRaises(AttributionError):
            build_attribution_input(
                malformed,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
            )

        packet = self._packet()
        for week in packet["weeks"]:
            week["strategy"]["weekly_return"] = 1e308
        with self.assertRaises(AttributionError):
            build_attribution_report(packet)

    def test_report_summary_and_evaluable_reason_invariants_are_fail_closed(self) -> None:
        report = build_attribution_report(self._packet())
        report["summary"]["calendar_weeks"] = 1
        with self.assertRaises(AttributionError):
            validate_attribution_report(report)

        report = build_attribution_report(self._packet())
        report["weeks"][0]["unavailable_reasons"] = ["should_be_empty"]
        with self.assertRaises(AttributionError):
            validate_attribution_report(report)


if __name__ == "__main__":
    unittest.main()
