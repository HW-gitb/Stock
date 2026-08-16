from __future__ import annotations

from datetime import datetime, timezone
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from engine.us_short_market_diagnostic_local_adapter import (
    adapt_benchmark_week,
    validate_local_price_packet,
)
from engine.us_short_market_diagnostic_total_return import validate_etf_total_return_sidecar
from runners import us_short_market_diagnostic_etf_sidecar_fetch as fetch
from tests.test_us_short_market_diagnostic_local_adapter import _packet
from tests.provider.us_short_private_test_root_light import temporary_provider_directory


ROOT = Path(__file__).resolve().parents[1]
OBSERVED_AT = "2026-07-25T01:00:00Z"
SECOND_OBSERVED_AT = "2026-07-25T01:00:01Z"
AS_OF = "20260806"


def _timestamp(day: str) -> int:
    return int(
        datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp() * 1000
    )


class _MassiveFixture:
    def __init__(
        self,
        *,
        pagination_gap: bool = False,
        unreadable_dividends: bool = False,
        unreadable_family: str | None = None,
        dividend_dates: tuple[str, ...] | None = None,
        dividend_fault: str | None = None,
        split_dates: tuple[str, ...] | None = None,
        split_fault: str | None = None,
        price_fault: str | None = None,
        interrupt_after: int | None = None,
        massive_429_attempts: int = 0,
    ) -> None:
        self.pagination_gap = pagination_gap
        self.unreadable_dividends = unreadable_dividends
        self.unreadable_family = unreadable_family
        self.dividend_dates = dividend_dates
        self.dividend_fault = dividend_fault
        self.split_dates = split_dates
        self.split_fault = split_fault
        self.price_fault = price_fault
        self.interrupt_after = interrupt_after
        self.massive_429_attempts = massive_429_attempts
        self.calls: list[str] = []

    def get_json(self, url: str, *, headers: dict[str, str]):
        del headers
        self.calls.append(url)
        if self.interrupt_after is not None and len(self.calls) > self.interrupt_after:
            raise KeyboardInterrupt("fixture interruption")
        if self.massive_429_attempts:
            self.massive_429_attempts -= 1
            return {}, 429, False, "http_error"
        parsed = urlsplit(url)
        if "/v2/aggs/ticker/" in parsed.path:
            symbol = parsed.path.split("/v2/aggs/ticker/", 1)[1].split("/", 1)[0]
            family = "daily_adjusted" if parse_qs(parsed.query)["adjusted"][0] == "true" else "daily_unadjusted"
            rows = [
                {"t": _timestamp("20260723"), "c": 100.0},
                {"t": _timestamp("20260724"), "c": 101.0},
            ]
        else:
            query = parse_qs(parsed.query)
            symbol = query["ticker"][0]
            family = "dividends" if parsed.path.endswith("/dividends") else "splits"
            if family == "dividends":
                rows = [
                    {
                        "ticker": symbol,
                        "ex_dividend_date": day,
                        "cash_amount": 1.0,
                        "split_adjusted_cash_amount": 1.0,
                        "historical_adjustment_factor": 1.0,
                    }
                    for day in (self.dividend_dates or ("20260724",))
                ]
            else:
                rows = [
                    {
                        "ticker": symbol,
                        "execution_date": day,
                        "split_from": 1.0,
                        "split_to": 2.0,
                    }
                    for day in (self.split_dates or (("20260724",) if self.split_fault else ()))
                ]
            if symbol == "VTI" and family == "dividends" and rows:
                if self.dividend_fault == "changed_payload":
                    rows[0]["cash_amount"] = 2.0
                    rows[0]["split_adjusted_cash_amount"] = 2.0
                elif self.dividend_fault == "huge_factor":
                    rows[0]["historical_adjustment_factor"] = "1e30"
                elif self.dividend_fault == "extreme_ratio":
                    rows[0].pop("historical_adjustment_factor")
                    rows[0]["cash_amount"] = "0.000001"
                    rows[0]["split_adjusted_cash_amount"] = "1000000000000000000000.000000"
            if symbol == "VTI" and family == "splits" and rows:
                if self.split_fault == "huge_ratio":
                    rows[0]["split_from"] = "1e400"
                elif self.split_fault == "tiny_ratio":
                    rows[0]["split_from"] = "1e-400"
        if symbol == "VTI" and family == "daily_unadjusted" and self.price_fault == "mismatch":
            rows[1]["c"] = 55.0
        unreadable = (
            self.unreadable_dividends and family == "dividends"
        ) or (
            self.unreadable_family == family and symbol == "VTI"
        )
        payload = (
            {}
            if unreadable
            else {"results": rows}
        )
        if self.pagination_gap and symbol == "VTI" and family == "dividends":
            payload["next_url"] = "https://evil.invalid/stocks/v1/dividends?ticker=VTI"
        return payload, 200, True, None


class EtfSidecarProducerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs_root = Path(tempfile.mkdtemp())
        self.decision_date = f"20991231-{id(self)}"
        self.provider_temp = temporary_provider_directory(ROOT)
        self.raw_root = Path(self.provider_temp.__enter__())
        self.raw_parent = self.raw_root / "provider_samples" / (
            f"us_short_market_diagnostic_etf_sidecar_{self.decision_date}"
        )
        self.addCleanup(self.inputs_root_cleanup)
        self.addCleanup(self.provider_temp.__exit__, None, None, None)

    def inputs_root_cleanup(self) -> None:
        shutil.rmtree(self.inputs_root, ignore_errors=True)

    def _capture(
        self,
        *,
        pagination_gap: bool = False,
        api_key: str | None = "fixture-key",
        client: _MassiveFixture | None = None,
        benchmark_packet: dict | None = None,
        decision_date: str | None = None,
        now: str = OBSERVED_AT,
        sleep_func=None,
    ):
        client = client or _MassiveFixture(pagination_gap=pagination_gap)
        with (
            mock.patch.object(fetch, "ROOT", self.raw_root),
            mock.patch.object(fetch.capture, "ROOT", self.raw_root),
        ):
            result = fetch.capture_sidecar_week(
                confirm_user_authorization=True,
                benchmark_packet=benchmark_packet or _packet(),
                decision_date=decision_date or self.decision_date,
                as_of_date=AS_OF,
                inputs_root=self.inputs_root,
                client=client,
                api_key=api_key,
                now=lambda: now,
                sleep_func=sleep_func,
            )
        return result, client

    def test_gated_fetch_builds_four_etf_sidecar_and_is_idempotent(self) -> None:
        first, client = self._capture()
        self.assertEqual("captured", first["status"])
        self.assertEqual(16, first["provider_calls"])
        self.assertEqual(["VTI", "IWB", "SPY", "QQQ"], first["evaluable_symbols"])
        sidecar_path = Path(first["sidecar_path"])
        before = sidecar_path.read_bytes()
        sidecar = validate_etf_total_return_sidecar(
            json.loads(before.decode("utf-8")),
            expected_price_intervals={
                (1, symbol): ("20260723", "20260724")
                for symbol in ("VTI", "IWB", "SPY", "QQQ")
            },
            as_of_date=AS_OF,
        )
        validate_local_price_packet(_packet(), as_of_date=AS_OF)
        self.assertEqual(["VTI", "IWB", "SPY", "QQQ"], list(sidecar["benchmark_symbols"]))

        second, _ = self._capture()
        self.assertEqual("idempotent", second["status"])
        self.assertEqual(16, len(client.calls))
        self.assertEqual(before, sidecar_path.read_bytes())

    def test_pagination_gap_degrades_only_the_affected_etf(self) -> None:
        result, client = self._capture(pagination_gap=True)
        self.assertEqual(16, result["provider_calls"])
        self.assertEqual(["IWB", "SPY", "QQQ"], result["evaluable_symbols"])
        sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
        vti = sidecar["weeks"][0]["benchmarks"]["VTI"]
        self.assertIn("pagination_incomplete", vti["data_quality_reasons"])
        self.assertNotIn("VTI", result["evaluable_symbols"])

    def test_429_retries_same_page_with_fixed_wait_and_keeps_attempt_raw(self) -> None:
        sleeps = []
        decision_date = f"{self.decision_date}-429-recover"
        result, client = self._capture(
            client=_MassiveFixture(massive_429_attempts=1),
            decision_date=decision_date,
            sleep_func=sleeps.append,
        )
        self.assertEqual(result["status"], "captured")
        self.assertEqual(result["logical_requests"], 16)
        self.assertEqual(result["http_attempts"], 17)
        self.assertEqual(result["retry_count_used"], 1)
        self.assertEqual(result["massive_429_retry_wait_seconds"], 65.0)
        self.assertEqual(sleeps, [65.0])
        self.assertEqual(client.calls[0], client.calls[1])
        raw_root = (
            self.raw_root / "provider_samples"
            / f"us_short_market_diagnostic_etf_sidecar_{decision_date}"
            / "raw" / "massive" / "VTI" / "dividends"
        )
        self.assertEqual(json.loads((raw_root / "page-001-attempt-001.json").read_text())["http_status"], 429)
        self.assertEqual(json.loads((raw_root / "page-001-attempt-002.json").read_text())["http_status"], 200)

    def test_persistent_429_degrades_only_one_family_and_other_families_continue_under_cap(self) -> None:
        sleeps = []
        result, client = self._capture(
            client=_MassiveFixture(massive_429_attempts=3),
            decision_date=f"{self.decision_date}-429-persistent",
            sleep_func=sleeps.append,
        )
        self.assertEqual(result["status"], "captured")
        self.assertEqual(result["logical_requests"], 16)
        self.assertEqual(result["retry_count_used"], 2)
        self.assertEqual(result["http_attempts"], 18)
        self.assertLessEqual(result["http_attempts"], fetch.MAX_TOTAL_HTTP_ATTEMPTS)
        self.assertEqual(sleeps, [65.0, 65.0])
        self.assertEqual(["IWB", "SPY", "QQQ"], result["evaluable_symbols"])
        self.assertGreater(len(client.calls), 3)
        self.assertEqual(result["logical_requests"] + result["retry_count_used"], result["http_attempts"])

    def test_all_family_429_is_incomplete_and_exact_rerun_recovers(self) -> None:
        decision_date = f"{self.decision_date}-429-all"
        sleeps = []
        first, first_client = self._capture(
            client=_MassiveFixture(massive_429_attempts=1000),
            decision_date=decision_date,
            sleep_func=sleeps.append,
        )
        self.assertEqual(first["status"], "incomplete_no_count")
        self.assertIsNone(first["sidecar_path"])
        self.assertEqual([], first["evaluable_symbols"])
        self.assertEqual(first["logical_requests"] + first["retry_count_used"], first["http_attempts"])
        self.assertLessEqual(first["http_attempts"], fetch.MAX_TOTAL_HTTP_ATTEMPTS)
        self.assertEqual(first["http_attempts"], len(first_client.calls))
        self.assertEqual([65.0] * first["retry_count_used"], sleeps)
        self.assertFalse(fetch.sidecar_path(decision_date, inputs_root=self.inputs_root).exists())

        recovered, recovered_client = self._capture(
            client=_MassiveFixture(),
            decision_date=decision_date,
            now=SECOND_OBSERVED_AT,
        )
        self.assertEqual(recovered["status"], "captured")
        self.assertEqual(["VTI", "IWB", "SPY", "QQQ"], recovered["evaluable_symbols"])
        self.assertEqual(16, len(recovered_client.calls))

    def test_unreadable_dividend_body_never_upgrades_to_total_return(self) -> None:
        result, _ = self._capture(
            client=_MassiveFixture(unreadable_dividends=True),
            decision_date=f"{self.decision_date}-unreadable",
        )
        self.assertEqual("captured", result["status"])
        self.assertEqual([], result["evaluable_symbols"])
        sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
        benchmarks = adapt_benchmark_week(
            _packet(),
            1,
            strategy_evaluable=True,
            strategy_weekly_return=0.03,
            total_return_sidecar=sidecar,
            windows_aligned=True,
        )
        for symbol in ("VTI", "IWB", "SPY", "QQQ"):
            with self.subTest(symbol=symbol):
                row = sidecar["weeks"][0]["benchmarks"][symbol]
                self.assertFalse(row["coverage"]["dividend_complete"])
                self.assertIn("dividend_history_empty_or_unreadable", row["data_quality_reasons"])
                self.assertEqual("price_return_diagnostic", benchmarks[symbol]["return_quality"])

    def test_unreadable_body_in_each_family_degrades_only_the_affected_etf(self) -> None:
        expected_reasons = {
            "dividends": "dividend_body_unreadable",
            "splits": "split_body_unreadable",
            "daily_adjusted": "adjusted_price_body_unreadable",
            "daily_unadjusted": "unadjusted_price_body_unreadable",
        }
        for family, expected_reason in expected_reasons.items():
            with self.subTest(family=family):
                result, _ = self._capture(
                    client=_MassiveFixture(unreadable_family=family),
                    decision_date=f"{self.decision_date}-unreadable-{family}",
                )
                self.assertEqual(["IWB", "SPY", "QQQ"], result["evaluable_symbols"])
                sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
                vti = sidecar["weeks"][0]["benchmarks"]["VTI"]
                self.assertIn(expected_reason, vti["data_quality_reasons"])
                self.assertNotIn("VTI", result["evaluable_symbols"])

    def test_interrupted_raw_capture_retries_with_a_new_observed_at(self) -> None:
        decision_date = f"{self.decision_date}-retry"
        with self.assertRaises(KeyboardInterrupt):
            self._capture(
                client=_MassiveFixture(interrupt_after=3),
                decision_date=decision_date,
            )
        result, client = self._capture(
            client=_MassiveFixture(),
            decision_date=decision_date,
            now=SECOND_OBSERVED_AT,
        )
        self.assertEqual("captured", result["status"])
        self.assertEqual(["VTI", "IWB", "SPY", "QQQ"], result["evaluable_symbols"])
        self.assertEqual(16, len(client.calls))

    def test_raw_conflict_degrades_only_one_etf_and_does_not_abort(self) -> None:
        decision_date = f"{self.decision_date}-conflict"
        with self.assertRaises(KeyboardInterrupt):
            self._capture(
                client=_MassiveFixture(interrupt_after=1),
                decision_date=decision_date,
            )
        result, _ = self._capture(
            client=_MassiveFixture(dividend_fault="changed_payload"),
            decision_date=decision_date,
            now=SECOND_OBSERVED_AT,
        )
        self.assertEqual("captured", result["status"])
        self.assertEqual(["IWB", "SPY", "QQQ"], result["evaluable_symbols"])
        sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
        self.assertIn("raw_conflict", sidecar["weeks"][0]["benchmarks"]["VTI"]["data_quality_reasons"])

    def test_decimal_faults_degrade_only_their_etf(self) -> None:
        for fault in ("huge_factor", "extreme_ratio"):
            with self.subTest(fault=fault):
                result, _ = self._capture(
                    client=_MassiveFixture(dividend_fault=fault),
                    decision_date=f"{self.decision_date}-{fault}",
                )
                self.assertEqual("captured", result["status"])
                self.assertEqual(["IWB", "SPY", "QQQ"], result["evaluable_symbols"])
                sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
                self.assertIn(
                    "dividend_event_reconciliation_failed",
                    sidecar["weeks"][0]["benchmarks"]["VTI"]["data_quality_reasons"],
                )

    def test_duplicate_dividend_rows_are_counted_once(self) -> None:
        result, _ = self._capture(
            client=_MassiveFixture(dividend_dates=("20260724", "20260724")),
            decision_date=f"{self.decision_date}-duplicate-dividend",
        )
        self.assertEqual(["VTI", "IWB", "SPY", "QQQ"], result["evaluable_symbols"])
        sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
        for symbol in ("VTI", "IWB", "SPY", "QQQ"):
            self.assertEqual(
                ["20260724"],
                [
                    event["ex_date"]
                    for event in sidecar["weeks"][0]["benchmarks"][symbol]["dividend_events"]
                ],
            )

    def test_non_finite_split_ratios_degrade_only_their_etf(self) -> None:
        for fault in ("huge_ratio", "tiny_ratio"):
            with self.subTest(fault=fault):
                result, _ = self._capture(
                    client=_MassiveFixture(split_fault=fault),
                    decision_date=f"{self.decision_date}-split-{fault}",
                )
                self.assertEqual(["IWB", "SPY", "QQQ"], result["evaluable_symbols"])
                sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
                self.assertIn(
                    "split_event_reconciliation_failed",
                    sidecar["weeks"][0]["benchmarks"]["VTI"]["data_quality_reasons"],
                )

    def test_adjusted_unadjusted_price_mismatch_degrades_only_the_etf(self) -> None:
        result, _ = self._capture(
            client=_MassiveFixture(price_fault="mismatch"),
            decision_date=f"{self.decision_date}-price-mismatch",
        )
        self.assertEqual(["IWB", "SPY", "QQQ"], result["evaluable_symbols"])
        sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
        vti = sidecar["weeks"][0]["benchmarks"]["VTI"]
        self.assertFalse(vti["coverage"]["adjusted_unadjusted_reconciled"])
        self.assertIn("adjusted_unadjusted_not_reconciled", vti["data_quality_reasons"])

    def test_historical_as_of_rejects_before_sidecar_calls(self) -> None:
        client = _MassiveFixture()
        with self.assertRaisesRegex(fetch.EtfSidecarFetchError, "after the requested as_of_date"):
            self._capture(
                client=client,
                decision_date=f"{self.decision_date}-asof",
                now="2026-08-07T00:00:00Z",
            )
        self.assertEqual([], client.calls)

    def test_partial_price_interval_degrades_only_that_etf(self) -> None:
        packet = _packet()
        vti = packet["weeks"][0]["benchmarks"]["VTI"]
        vti["prior_price_date"] = None
        vti["prior_close"] = None
        result, _ = self._capture(
            benchmark_packet=packet,
            decision_date=f"{self.decision_date}-partial-price",
        )
        self.assertEqual("captured", result["status"])
        self.assertEqual(["IWB", "SPY", "QQQ"], result["evaluable_symbols"])
        sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
        vti_sidecar = sidecar["weeks"][0]["benchmarks"]["VTI"]
        self.assertIsNone(vti_sidecar["prior_price_date"])
        self.assertIsNone(vti_sidecar["price_date"])
        self.assertIn("price_interval_partial", vti_sidecar["data_quality_reasons"])
        benchmarks = adapt_benchmark_week(
            packet,
            1,
            strategy_evaluable=True,
            strategy_weekly_return=0.03,
            total_return_sidecar=sidecar,
            windows_aligned=True,
        )
        self.assertEqual("unavailable", benchmarks["VTI"]["return_quality"])
        for symbol in ("IWB", "SPY", "QQQ"):
            self.assertEqual("total_return_evaluable", benchmarks[symbol]["return_quality"])

    def test_dividend_events_stay_inside_the_price_interval(self) -> None:
        result, _ = self._capture(
            client=_MassiveFixture(
                dividend_dates=("20260722", "20260723", "20260724", "20260725")
            ),
            decision_date=f"{self.decision_date}-dividend-window",
        )
        sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
        for symbol in ("VTI", "IWB", "SPY", "QQQ"):
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    ["20260724"],
                    [event["ex_date"] for event in sidecar["weeks"][0]["benchmarks"][symbol]["dividend_events"]],
                )

    def test_missing_provider_key_writes_a_degraded_sidecar_without_network(self) -> None:
        result, client = self._capture(api_key="")
        self.assertEqual("captured", result["status"])
        self.assertEqual([], result["evaluable_symbols"])
        self.assertEqual([], client.calls)
        sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
        for symbol in ("VTI", "IWB", "SPY", "QQQ"):
            self.assertIn(
                "provider_key_missing",
                sidecar["weeks"][0]["benchmarks"][symbol]["data_quality_reasons"],
            )
        self.assertFalse(self.raw_parent.exists())

    def test_request_budget_is_rejected_before_first_request(self) -> None:
        client = _MassiveFixture()
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(fetch, "ROOT", self.raw_root),
                mock.patch.object(fetch.capture, "ROOT", self.raw_root),
                mock.patch.object(fetch, "MAX_LOGICAL_REQUESTS", 0),
            ):
                with self.assertRaises(fetch.EtfSidecarFetchError):
                    fetch.capture_sidecar_week(
                        confirm_user_authorization=True,
                        benchmark_packet=_packet(),
                        decision_date=self.decision_date,
                        as_of_date=AS_OF,
                        inputs_root=Path(tmp) / "inputs",
                        client=client,
                        api_key="fixture-key",
                        now=lambda: OBSERVED_AT,
                    )
            self.assertEqual([], client.calls)


if __name__ == "__main__":
    unittest.main()
