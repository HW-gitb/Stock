# -*- coding: utf-8 -*-
"""Decision-time source capture and H20 maturity tests for US-short A1."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from engine import us_short_forward_policy_source_capture as source  # noqa: E402
import test_us_short_forward_policy_order_snapshot as fixture  # noqa: E402
import test_us_short_forward_policy_private_week as private_fixture  # noqa: E402


def _packet(*, decision_date: str, price_basis_date: str, tickers: list[str], start: date, days: int) -> dict:
    series = {}
    for ticker in tickers:
        points = []
        for offset in range(days):
            current = start + timedelta(days=offset)
            # The first bars print a prior swing high so the window carries a REAL overhead
            # structural target. A perfectly flat series has resistance == close, and the price
            # engine (since "stop measuring a momentum trade with a mean-reversion ruler") refuses
            # to invent a target from the RR floor, so every candidate would be non-executable and
            # the whole week would degrade to no_count — a fixture artefact, not the behaviour
            # under test.
            shelf = offset < days - 10
            if shelf:
                # Prior range whose top is BACKED by a near-tied second high, so `effective_resistance`
                # keeps it (a lone spike would be de-spiked away and the candidate would have no target).
                bar = {"open": 109.5, "high": 110.0 if offset % 2 == 0 else 109.5,
                       "low": 109.0, "close": 109.5}
            else:
                # Pullback to the support shelf, likewise backed by a near-tied second low.
                bar = {"open": 100.0, "high": 100.0,
                       "low": 98.0 if offset % 2 == 0 else 98.5, "close": 100.0}
            points.append({"date": current.isoformat(), "volume": 1000.0, **bar})
        series[ticker] = {
            "as_of": price_basis_date[:4] + "-" + price_basis_date[4:6] + "-" + price_basis_date[6:],
            "session": "regular", "adjustment_mode": "split_dividend_adjusted", "points": points,
        }
    return {
        "schema_name": "us_short_batch5_full_universe_ohlcv_series_packet",
        "schema_version": "1.0.0",
        "generated_at": "2026-07-13T08:00:00-04:00",
        "scope": {
            "market": "US", "lane": "us_short", "batch": "batch5_provider_live",
            "packet_status": "full_universe_per_ticker_ohlcv_series_ready_for_local_overextension_projection",
            "full_market_reconstruction": True, "network_access_performed_by_packet_producer": True,
            "provider_calls_performed_by_packet_producer": True, "raw_payload_refs_gitignored": True,
            "datahub_consumption_allowed": False, "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False, "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": decision_date,
            "candidate_price_basis_date": price_basis_date,
            "price_basis_date": price_basis_date[:4] + "-" + price_basis_date[4:6] + "-" + price_basis_date[6:],
            "source_as_of": price_basis_date[:4] + "-" + price_basis_date[4:6] + "-" + price_basis_date[6:],
        },
        "series_contract": {
            "session": "regular", "adjustment_mode": "split_dividend_adjusted",
            "as_of": price_basis_date[:4] + "-" + price_basis_date[4:6] + "-" + price_basis_date[6:],
            "grouped_session_count": days,
        },
        "provenance": {
            "provider_id": "massive", "endpoint_or_family": "grouped_daily",
            "source_as_of": price_basis_date[:4] + "-" + price_basis_date[4:6] + "-" + price_basis_date[6:],
            "observed_at": "2026-07-13T08:00:00-04:00", "coverage_status": "full", "parser_status": "ok",
        },
        "series_by_ticker": series,
    }


class ForwardPolicySourceCaptureTests(unittest.TestCase):
    def _capture(self):
        return fixture._capture()

    def _source_capture(self, *, market_axis_regimes=None):
        capture = self._capture()
        packet = _packet(
            decision_date="20260713", price_basis_date="20260710",
            tickers=list(fixture.COMMON_POOL), start=date(2026, 6, 16), days=25,
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "forward_policy_source_capture_20260713.json"
            result = source.materialize_forward_policy_source_capture(
                capture=capture,
                ohlcv_packet=packet,
                ohlcv_packet_sha256="a" * 64,
                source_context_sha256=capture["source_context_sha256"],
                overextension_by_ticker={ticker: None for ticker in fixture.COMMON_POOL},
                market_axis_regimes=dict(
                    fixture._AGGRESSIVE if market_axis_regimes is None else market_axis_regimes
                ),
                prior_regime=None,
                prior_upgrade_count=0,
                private_output_path=output,
            )
            expected_status = "ready_for_outcome" if market_axis_regimes is None else "data_degraded_whole_week_no_count"
            self.assertEqual(result["order_snapshot_status"], expected_status)
            return json.loads(output.read_text(encoding="utf-8"))

    def test_freezes_complete_common_pool_under_one_pullback_execution_basis(self):
        record = self._source_capture()
        source.validate_forward_policy_source_capture(record)
        self.assertEqual(set(record["candidate_price_inputs_by_ticker"]), set(fixture.COMMON_POOL))
        self.assertTrue(all(
            row["sub_mode"] == "pullback" and row["defensive_breakout_probe_allowed"] is False
            for row in record["candidate_price_inputs_by_ticker"].values()
        ))
        self.assertEqual(record["order_snapshot"]["order_snapshot_status"], "ready_for_outcome")

    def test_missing_common_candidate_or_tampered_execution_contract_fails_closed(self):
        capture = self._capture()
        packet = _packet(
            decision_date="20260713", price_basis_date="20260710",
            tickers=["ALFA"], start=date(2026, 6, 16), days=25,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(source.ForwardPolicySourceCaptureError):
                source.materialize_forward_policy_source_capture(
                    capture=capture, ohlcv_packet=packet, ohlcv_packet_sha256="a" * 64,
                    source_context_sha256=capture["source_context_sha256"],
                    overextension_by_ticker={ticker: None for ticker in fixture.COMMON_POOL},
                    market_axis_regimes=dict(fixture._AGGRESSIVE), prior_regime=None, prior_upgrade_count=0,
                    private_output_path=Path(tmp) / "forward_policy_source_capture_20260713.json",
                )
        tampered = self._source_capture()
        tampered["cost_prior"]["commission_fee"] = 0.0
        with self.assertRaises(source.ForwardPolicySourceCaptureError):
            source.validate_forward_policy_source_capture(tampered)

    def test_duplicate_or_unordered_source_dates_fail_closed(self):
        capture = self._capture()
        packet = _packet(
            decision_date="20260713", price_basis_date="20260710",
            tickers=list(fixture.COMMON_POOL), start=date(2026, 6, 16), days=25,
        )
        first = packet["series_by_ticker"][fixture.COMMON_POOL[0]]["points"]
        first[1]["date"] = first[0]["date"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(source.ForwardPolicySourceCaptureError):
                source.materialize_forward_policy_source_capture(
                    capture=capture, ohlcv_packet=packet, ohlcv_packet_sha256="a" * 64,
                    source_context_sha256=capture["source_context_sha256"],
                    overextension_by_ticker={ticker: None for ticker in fixture.COMMON_POOL},
                    market_axis_regimes=dict(fixture._AGGRESSIVE), prior_regime=None, prior_upgrade_count=0,
                    private_output_path=Path(tmp) / "forward_policy_source_capture_20260713.json",
                )

    def test_maturity_writes_explicit_no_count_without_adjustment_evidence_then_ready_receipt_when_injected(self):
        record = self._source_capture()
        maturity = _packet(
            decision_date="20260810", price_basis_date="20260807",
            tickers=list(fixture.COMMON_POOL), start=date(2026, 7, 13), days=20,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "forward_policy_outcome_20260713.json"
            no_count = source.materialize_forward_policy_source_maturity(
                source_capture=record,
                current_ohlcv_packet=maturity,
                current_ohlcv_packet_sha256="b" * 64,
                maturity_as_of="20260810",
                source_run_id="maturity-20260810",
                adjustment_evidence=None,
                private_outcome_path=path,
            )
            self.assertEqual(no_count["materialization_status"], "data_degraded_whole_week_no_count")
            self.assertFalse(no_count["counted_week_eligible"])
            self.assertIsNone(no_count["source_receipt"])
            persisted_no_count = json.loads(path.read_text(encoding="utf-8"))
            adjustment_evidence = private_fixture._adjustment_evidence()
            adjustment_evidence["source_refs"] = [{
                "id": "maturity_ohlcv_packet",
                "path": "state/us_short/shadow_compare_private/forward_policy_maturity_source.json",
                "sha256": "b" * 64,
            }]
            for section_name in (
                "adjustment_mode", "split_handling", "dividend_handling", "ex_date_price_consistency",
            ):
                adjustment_evidence[section_name]["source_ref_ids"] = ["maturity_ohlcv_packet"]

            ready = source.materialize_forward_policy_source_maturity(
                source_capture=record,
                current_ohlcv_packet=maturity,
                current_ohlcv_packet_sha256="c" * 64,
                maturity_as_of="20260810",
                source_run_id="maturity-20260817",
                adjustment_evidence=adjustment_evidence,
                private_outcome_path=path,
                prior_private_week_record=persisted_no_count,
            )
            self.assertEqual(ready["materialization_status"], "ready_for_accumulation")
            self.assertTrue(ready["counted_week_eligible"])
            self.assertEqual(ready["source_receipt"]["source_packet_sha256"], "b" * 64)

    def test_maturity_as_of_blocks_a_future_h20_window_and_makes_the_no_count_observable(self):
        record = self._source_capture()
        maturity = _packet(
            decision_date="20260731", price_basis_date="20260730",
            tickers=list(fixture.COMMON_POOL), start=date(2026, 7, 13), days=20,
        )
        adjustment_evidence = private_fixture._adjustment_evidence()
        adjustment_evidence["source_refs"] = [{
            "id": "maturity_ohlcv_packet",
            "path": "state/us_short/shadow_compare_private/forward_policy_maturity_source.json",
            "sha256": "d" * 64,
        }]
        for section_name in (
            "adjustment_mode", "split_handling", "dividend_handling", "ex_date_price_consistency",
        ):
            adjustment_evidence[section_name]["source_ref_ids"] = ["maturity_ohlcv_packet"]
        with tempfile.TemporaryDirectory() as tmp:
            result = source.materialize_forward_policy_source_maturity(
                source_capture=record,
                current_ohlcv_packet=maturity,
                current_ohlcv_packet_sha256="d" * 64,
                maturity_as_of="20260731",
                source_run_id="maturity-20260731",
                adjustment_evidence=adjustment_evidence,
                private_outcome_path=Path(tmp) / "forward_policy_outcome_20260713.json",
            )
        self.assertFalse(result["counted_week_eligible"])
        self.assertEqual(result["materialization_status"], "data_degraded_whole_week_no_count")
        self.assertEqual(result["maturity_observability"]["maturity_as_of"], "20260731")
        self.assertEqual(result["maturity_observability"]["degradation_reason"], "outcome:incomplete_price_series")

    def test_order_snapshot_no_count_does_not_require_a_nonexistent_adjustment_sidecar(self):
        record = self._source_capture(market_axis_regimes={})
        maturity = _packet(
            decision_date="20260810", price_basis_date="20260807",
            tickers=list(fixture.COMMON_POOL), start=date(2026, 7, 13), days=20,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = source.materialize_forward_policy_source_maturity(
                source_capture=record,
                current_ohlcv_packet=maturity,
                current_ohlcv_packet_sha256="a" * 64,
                maturity_as_of="20260810",
                source_run_id="unit-test",
                adjustment_evidence=None,
                private_outcome_path=Path(temp_dir) / "forward_policy_outcome_20260713.json",
            )
        self.assertFalse(result["counted_week_eligible"])
        self.assertEqual(result["maturity_observability"]["degradation_reason"], "order_snapshot:new_entry_not_permitted")

    def test_maturity_rejects_an_evaluable_sidecar_that_is_not_bound_to_its_exact_price_packet(self):
        record = self._source_capture()
        maturity = _packet(
            decision_date="20260810", price_basis_date="20260807",
            tickers=list(fixture.COMMON_POOL), start=date(2026, 7, 13), days=20,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(source.ForwardPolicySourceCaptureError):
                source.materialize_forward_policy_source_maturity(
                    source_capture=record,
                    current_ohlcv_packet=maturity,
                    current_ohlcv_packet_sha256="e" * 64,
                    maturity_as_of="20260810",
                    source_run_id="maturity-20260810",
                    adjustment_evidence=private_fixture._adjustment_evidence(),
                    private_outcome_path=Path(tmp) / "forward_policy_outcome_20260713.json",
                )


if __name__ == "__main__":
    unittest.main()
