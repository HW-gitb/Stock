from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator

from engine.us_short_market_diagnostic_total_return import (
    TotalReturnSidecarError,
    build_total_return_benchmark_observation,
    sidecar_observation_sha256,
    validate_etf_total_return_sidecar,
)


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ("VTI", "IWB", "SPY", "QQQ")


def _sha(seed: int) -> str:
    return f"{seed:064x}"


def _sidecar(
    *,
    complete: bool = True,
    price_date: str = "20260724",
    prior_price_date: str = "20260723",
) -> dict:
    source_refs = {_sha(900)}
    benchmark_rows: dict[str, dict] = {}
    for index, symbol in enumerate(BENCHMARKS):
        if complete:
            binding = {
                "adjusted_price_sha256": _sha(100 + index),
                "unadjusted_price_sha256": _sha(110 + index),
                "dividend_sha256": _sha(120 + index),
                "split_sha256": _sha(130 + index),
                "raw_capture_sha256": _sha(140 + index),
                "source_date": price_date,
                "observed_at": "2026-07-25T01:00:00Z",
            }
            dividend_events = [
                {
                    "ex_date": price_date,
                    "cash_amount": "1.000000",
                    "split_adjustment_factor": 1.0,
                    "split_adjusted_cash_amount": "1.000000",
                    "source_sha256": _sha(150 + index),
                }
            ]
            split_events: list[dict] = []
            coverage = {
                "pagination_complete": True,
                "dividend_complete": True,
                "split_complete": True,
                "adjusted_unadjusted_reconciled": True,
            }
            reasons: list[str] = []
        else:
            binding = {
                "adjusted_price_sha256": None,
                "unadjusted_price_sha256": None,
                "dividend_sha256": None,
                "split_sha256": None,
                "raw_capture_sha256": None,
                "source_date": None,
                "observed_at": None,
            }
            dividend_events = []
            split_events = []
            coverage = {
                "pagination_complete": False,
                "dividend_complete": False,
                "split_complete": False,
                "adjusted_unadjusted_reconciled": False,
            }
            reasons = ["dividend_endpoint_incomplete"]
        source_refs.update(value for value in binding.values() if isinstance(value, str) and len(value) == 64)
        source_refs.update(event["source_sha256"] for event in [*dividend_events, *split_events])
        benchmark_rows[symbol] = {
            "prior_price_date": prior_price_date,
            "price_date": price_date,
            "dividend_events": dividend_events,
            "split_events": split_events,
            "coverage": coverage,
            "source_binding": binding,
            "data_quality_reasons": reasons,
        }
    return {
        "schema_name": "us_short_market_diagnostic_etf_total_return_sidecar",
        "schema_version": "1.0.0",
        "window_id": "26w-1-26",
        "diagnostic_epoch": "us_short_market_diagnostic_26w_v1",
        "price_basis": "split_adjusted_close",
        "benchmark_symbols": list(BENCHMARKS),
        "weeks": [
            {
                "calendar_week_index": 1,
                "valuation_date": price_date,
                "benchmarks": benchmark_rows,
            }
        ],
        "source_refs": sorted(source_refs),
        "boundary": {
            "sidecar_only": True,
            "provider_selection_performed": False,
            "provider_call_performed_by_reconciler": False,
            "account_write_performed": False,
            "paper_gate_upgrade_performed": False,
            "ship_gate_or_production_authorized": False,
        },
    }


def _price_observation() -> dict:
    return {
        "price_date": "20260724",
        "prior_price_date": "20260723",
        "prior_close": "100.000000",
        "close": "101.000000",
        "source_kind": "local_etf_price_packet",
        "source_sha256": _sha(800),
        "dividend_sidecar_sha256": None,
    }


class UsShortMarketDiagnosticTotalReturnTest(unittest.TestCase):
    def test_complete_sidecar_produces_source_bound_total_return(self) -> None:
        sidecar = _sidecar()
        self.assertEqual([], list(Draft7Validator(json.loads(
            (ROOT / "schemas" / "us_short_market_diagnostic_etf_total_return_sidecar.schema.json").read_text(
                encoding="utf-8"
            )
        )).iter_errors(sidecar)))
        validate_etf_total_return_sidecar(sidecar)
        observation = sidecar["weeks"][0]["benchmarks"]["VTI"]
        benchmark = build_total_return_benchmark_observation(
            sidecar_observation=observation,
            price_observation=_price_observation(),
            strategy_evaluable=True,
            strategy_weekly_return=0.03,
            windows_aligned=True,
        )
        self.assertEqual("total_return_evaluable", benchmark["return_quality"])
        self.assertAlmostEqual(0.02, benchmark["weekly_return"])
        self.assertAlmostEqual(0.01, benchmark["raw_excess"])
        self.assertEqual(sidecar_observation_sha256(observation), benchmark["dividend_sidecar_sha256"])
        self.assertEqual([], benchmark["data_quality_reasons"])

    def test_incomplete_sidecar_keeps_price_return_and_reason(self) -> None:
        sidecar = _sidecar(complete=False)
        validate_etf_total_return_sidecar(sidecar)
        benchmark = build_total_return_benchmark_observation(
            sidecar_observation=sidecar["weeks"][0]["benchmarks"]["VTI"],
            price_observation=_price_observation(),
            strategy_evaluable=True,
            strategy_weekly_return=0.03,
            windows_aligned=True,
        )
        self.assertEqual("price_return_diagnostic", benchmark["return_quality"])
        self.assertAlmostEqual(0.01, benchmark["weekly_return"])
        self.assertIn("dividend_endpoint_incomplete", benchmark["data_quality_reasons"])
        self.assertIn("dividend_sidecar_not_reconciled", benchmark["data_quality_reasons"])
        self.assertIsNotNone(benchmark["dividend_sidecar_sha256"])

    def test_adjusted_cash_must_match_cash_and_factor(self) -> None:
        sidecar = _sidecar()
        sidecar["weeks"][0]["benchmarks"]["VTI"]["dividend_events"][0]["split_adjusted_cash_amount"] = "1.100000"
        with self.assertRaises(TotalReturnSidecarError):
            validate_etf_total_return_sidecar(sidecar)

    def test_events_must_stay_inside_the_price_interval(self) -> None:
        sidecar = _sidecar()
        sidecar["weeks"][0]["benchmarks"]["VTI"]["dividend_events"][0]["ex_date"] = "20260722"
        with self.assertRaises(TotalReturnSidecarError):
            validate_etf_total_return_sidecar(sidecar)

    def test_all_source_digests_must_be_bound_at_root(self) -> None:
        sidecar = _sidecar()
        missing = sidecar["weeks"][0]["benchmarks"]["VTI"]["dividend_events"][0]["source_sha256"]
        sidecar["source_refs"] = [value for value in sidecar["source_refs"] if value != missing]
        with self.assertRaises(TotalReturnSidecarError):
            validate_etf_total_return_sidecar(sidecar)

    def test_direct_builder_rejects_malformed_sidecar_observation(self) -> None:
        observation = dict(_sidecar()["weeks"][0]["benchmarks"]["VTI"])
        del observation["coverage"]
        with self.assertRaises(TotalReturnSidecarError):
            build_total_return_benchmark_observation(
                sidecar_observation=observation,
                price_observation=_price_observation(),
                strategy_evaluable=True,
                strategy_weekly_return=0.03,
                windows_aligned=True,
            )

    def test_complete_sidecar_with_wrong_price_date_downgrades_only_this_week(self) -> None:
        sidecar = _sidecar(price_date="20260723", prior_price_date="20260722")
        benchmark = build_total_return_benchmark_observation(
            sidecar_observation=sidecar["weeks"][0]["benchmarks"]["VTI"],
            price_observation=_price_observation(),
            strategy_evaluable=True,
            strategy_weekly_return=0.03,
            windows_aligned=True,
        )
        self.assertEqual("price_return_diagnostic", benchmark["return_quality"])
        self.assertAlmostEqual(0.01, benchmark["weekly_return"])
        self.assertIn("sidecar_price_date_mismatch", benchmark["data_quality_reasons"])

    def test_unavailable_price_does_not_publish_sidecar_digest(self) -> None:
        sidecar = _sidecar()
        missing_price = _price_observation()
        missing_price.update({"prior_price_date": None, "price_date": None, "prior_close": None, "close": None})
        benchmark = build_total_return_benchmark_observation(
            sidecar_observation=sidecar["weeks"][0]["benchmarks"]["VTI"],
            price_observation=missing_price,
            strategy_evaluable=True,
            strategy_weekly_return=0.03,
            windows_aligned=True,
        )
        self.assertEqual("unavailable", benchmark["return_quality"])
        self.assertIsNone(benchmark["dividend_sidecar_sha256"])

    def test_as_of_date_rejects_future_sidecar_observation(self) -> None:
        with self.assertRaises(TotalReturnSidecarError):
            validate_etf_total_return_sidecar(_sidecar(), as_of_date="20260724")

    def test_huge_price_number_is_a_typed_rejection(self) -> None:
        price = _price_observation()
        price["prior_close"] = "1" + ("0" * 400) + ".000000"
        with self.assertRaises(TotalReturnSidecarError):
            build_total_return_benchmark_observation(
                sidecar_observation=_sidecar()["weeks"][0]["benchmarks"]["VTI"],
                price_observation=price,
                strategy_evaluable=True,
                strategy_weekly_return=0.03,
                windows_aligned=True,
            )

    def test_public_builder_requires_a_real_windows_aligned_value(self) -> None:
        kwargs = {
            "sidecar_observation": _sidecar()["weeks"][0]["benchmarks"]["VTI"],
            "price_observation": _price_observation(),
            "strategy_evaluable": True,
            "strategy_weekly_return": 0.03,
        }
        with self.assertRaises(TypeError):
            build_total_return_benchmark_observation(**kwargs)
        with self.assertRaises(TotalReturnSidecarError):
            build_total_return_benchmark_observation(**kwargs, windows_aligned="false")


if __name__ == "__main__":
    unittest.main()
