from __future__ import annotations

import importlib
import importlib.util
import json
import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import _DECISION_DATE, _candidate_artifact  # noqa: E402
from tests.provider.us_short_private_test_root import (  # noqa: E402
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_momentum_price_source_packet_20260705"
CONSUMER_SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_momentum_price_source_20260705"
PRODUCER_MODULE = "runners.us_short_batch5_momentum_price_source_packet"
CONSUMER_MODULE = "runners.us_short_batch5_momentum_price_source"
_PRICE_BASIS_YMD = "2026-06-12"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dates(n: int, *, as_of: str = _PRICE_BASIS_YMD) -> list[str]:
    end = datetime.strptime(as_of, "%Y-%m-%d").date()
    return [(end - timedelta(days=(n - 1 - idx))).isoformat() for idx in range(n)]


def _millis(date_value: str) -> int:
    dt = datetime.strptime(date_value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class FakeMassivePriceClient:
    def __init__(
        self,
        *,
        error_symbol: str | None = None,
        bad_close_symbol: str | None = None,
        row_override: dict | None = None,
    ):
        self.urls: list[str] = []
        self.error_symbol = error_symbol
        self.bad_close_symbol = bad_close_symbol
        self.row_override = row_override or {}

    def get_json(self, url: str, *, headers=None, timeout_seconds=30):
        self.urls.append(url)
        symbol = url.split("/ticker/", 1)[1].split("/range/", 1)[0]
        if symbol == self.error_symbol:
            return {"status": "ERROR", "message": "unit test endpoint error"}, 429, False, "http_error"

        bases = {"AAPL": 100.0, "MSFT": 90.0, "JPM": 80.0, "SPY": 95.0, "QQQ": 98.0}
        step = {"AAPL": 2.0, "MSFT": 0.25, "JPM": 0.1, "SPY": 0.9, "QQQ": 1.0}[symbol]
        rows = []
        for idx, date_value in enumerate(_dates(72)):
            close = bases[symbol] + (idx * step)
            if symbol == self.bad_close_symbol and idx == 10:
                close = 0.0
            row = {"t": _millis(date_value), "c": close, "v": 1_000_000 + idx}
            if symbol in self.row_override and idx == 10:
                row.update(self.row_override[symbol])
            rows.append(row)
        return {"status": "OK", "resultsCount": len(rows), "results": rows}, 200, True, None


class MomentumPriceSourcePacketProducerTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_momentum_price_source_packet_20260705"
        )
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        self._consumer_sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_momentum_price_source_20260705"
        )
        self.consumer_sample_root = Path(self._consumer_sample_root_context.__enter__())
        self.addCleanup(self._consumer_sample_root_context.__exit__, None, None, None)
        self.slug = f"test_momentum_price_packet_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "candidate": self.state_root / f"{self.slug}_candidate.json",
            "source_packet": self.state_root / f"{self.slug}_source_packet.json",
            "projection": self.state_root / f"{self.slug}_momentum_projection.json",
            "summary": self.sample_root / "momentum_price_source_packet_20260705" / self.slug / "summary.json",
            "consumer_summary": self.consumer_sample_root / self.slug / "consumer_summary.json",
        }
        self.raw_root = self.sample_root / "momentum_price_source_packet_20260705" / self.slug / "raw"
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        if self.raw_root.exists():
            for item in sorted(self.raw_root.rglob("*"), reverse=True):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            self.raw_root.rmdir()
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)

    def _env(self):
        producer = importlib.import_module(PRODUCER_MODULE)
        return mock.patch.dict(
            producer.sample_validation.os.environ,
            {"MASSIVE_API_KEY": "UNIT_TEST_MASSIVE_SECRET"},
            clear=False,
        )

    def _run_happy(self, *, client=None):
        producer = importlib.import_module(PRODUCER_MODULE)
        client = client or FakeMassivePriceClient()
        with self._env(), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = producer.run_price_source_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL", "MSFT"],
                output_source_packet_path=self.paths["source_packet"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                generated_at="2026-06-15T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                massive_sleep_seconds=0,
            )
        return summary, client

    def test_runner_and_summary_schema_are_routed_artifacts(self):
        self.assertIsNotNone(importlib.util.find_spec(PRODUCER_MODULE))
        producer = importlib.import_module(PRODUCER_MODULE)
        self.assertTrue(producer.SUMMARY_SCHEMA_PATH.exists())
        self.assertTrue(producer.PACKET_SCHEMA_PATH.exists())

    def test_authorized_fetch_builds_price_packet_consumed_by_existing_runner(self):
        summary, client = self._run_happy()

        self.assertEqual(len(client.urls), 4)
        self.assertTrue(summary["scope"]["provider_calls_performed"])
        self.assertTrue(summary["scope"]["source_packet_written"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 4)
        self.assertEqual(summary["sample_universe"]["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(summary["sample_universe"]["benchmark_symbols"], ["SPY", "QQQ"])
        self.assertTrue(self.paths["source_packet"].exists())
        self.assertEqual(len(list(self.raw_root.rglob("*.json"))), 4)

        packet = _read_json(self.paths["source_packet"])
        self.assertEqual(packet["schema_name"], "us_short_batch5_momentum_price_source_packet")
        self.assertTrue(packet["scope"]["network_access_performed_by_packet_producer"])
        self.assertEqual(set(packet["series_by_ticker"]), {"AAPL", "MSFT", "SPY", "QQQ"})
        self.assertEqual(packet["series_contract"]["adjustment_mode"], "split_adjusted")
        self.assertEqual(packet["provenance_by_ticker"]["AAPL"]["provider_id"], "massive")
        self.assertEqual(len(packet["series_by_ticker"]["AAPL"]["points"]), 72)

        consumer = importlib.import_module(CONSUMER_MODULE)
        consumer_summary = consumer.run_packet(
            candidate_artifact_path=self.paths["candidate"],
            source_packet_path=self.paths["source_packet"],
            output_projection_path=self.paths["projection"],
            summary_path=self.paths["consumer_summary"],
            generated_at="2026-06-15T12:05:00+00:00",
        )
        self.assertEqual(consumer_summary["scope"]["status"], "momentum_projection_written")
        projection = _read_json(self.paths["projection"])
        self.assertEqual(projection["target_count"], 2)
        self.assertEqual(projection["scored_count"], 2)
        self.assertEqual(set(projection["momentum_by_ticker"]), {"AAPL", "MSFT"})

        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn("UNIT_TEST_MASSIVE_SECRET", text)
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn('"payload"', text)
        self.assertNotIn('"request_url"', text)
        self.assertNotIn('"results"', text)

    def test_requires_authorization_before_fetch_or_write(self):
        producer = importlib.import_module(PRODUCER_MODULE)
        client = FakeMassivePriceClient()

        with self.assertRaises(producer.MomentumPriceSourcePacketError):
            producer.run_price_source_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL", "MSFT"],
                output_source_packet_path=self.paths["source_packet"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=False,
                generated_at="2026-06-15T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                massive_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_endpoint_error_fails_closed_before_packet_and_summary_write(self):
        producer = importlib.import_module(PRODUCER_MODULE)
        client = FakeMassivePriceClient(error_symbol="QQQ")

        with self._env(), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            with self.assertRaises(producer.MomentumPriceSourcePacketError):
                producer.run_price_source_packet(
                    candidate_artifact_path=self.paths["candidate"],
                    expected_decision_date=_DECISION_DATE,
                    selected_symbols=["AAPL", "MSFT"],
                    output_source_packet_path=self.paths["source_packet"],
                    summary_path=self.paths["summary"],
                    raw_root=self.raw_root,
                    client=client,
                    confirm_user_authorization=True,
                    generated_at="2026-06-15T12:00:00+00:00",
                    observed_at="2026-06-15T12:00:00+00:00",
                    massive_sleep_seconds=0,
                )

        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_nonpositive_price_fails_closed_before_packet_and_summary_write(self):
        producer = importlib.import_module(PRODUCER_MODULE)
        client = FakeMassivePriceClient(bad_close_symbol="SPY")

        with self._env(), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            with self.assertRaises(producer.MomentumPriceSourcePacketError):
                producer.run_price_source_packet(
                    candidate_artifact_path=self.paths["candidate"],
                    expected_decision_date=_DECISION_DATE,
                    selected_symbols=["AAPL", "MSFT"],
                    output_source_packet_path=self.paths["source_packet"],
                    summary_path=self.paths["summary"],
                    raw_root=self.raw_root,
                    client=client,
                    confirm_user_authorization=True,
                    generated_at="2026-06-15T12:00:00+00:00",
                    observed_at="2026-06-15T12:00:00+00:00",
                    massive_sleep_seconds=0,
                )

        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_huge_price_numbers_fail_closed_without_bare_overflow(self):
        producer = importlib.import_module(PRODUCER_MODULE)
        client = FakeMassivePriceClient(row_override={"AAPL": {"c": 10**400}})

        with self._env(), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            with self.assertRaises(producer.MomentumPriceSourcePacketError):
                producer.run_price_source_packet(
                    candidate_artifact_path=self.paths["candidate"],
                    expected_decision_date=_DECISION_DATE,
                    selected_symbols=["AAPL", "MSFT"],
                    output_source_packet_path=self.paths["source_packet"],
                    summary_path=self.paths["summary"],
                    raw_root=self.raw_root,
                    client=client,
                    confirm_user_authorization=True,
                    generated_at="2026-06-15T12:00:00+00:00",
                    observed_at="2026-06-15T12:00:00+00:00",
                    massive_sleep_seconds=0,
                )

        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_out_of_range_timestamps_fail_closed_without_bare_oserror(self):
        producer = importlib.import_module(PRODUCER_MODULE)

        for value in (10**400, 1e18, -1e18):
            source_packet_path = self.state_root / f"{self.slug}_ts_{type(value).__name__}_{abs(hash(value))}.json"
            summary_path = self.sample_root / "momentum_price_source_packet_20260705" / self.slug / f"ts_{abs(hash(value))}_summary.json"
            client = FakeMassivePriceClient(row_override={"AAPL": {"t": value}})
            try:
                with self.subTest(timestamp=value), self._env(), mock.patch.object(
                    producer.sample_validation, "_read_windows_environment_value", return_value=None
                ):
                    with self.assertRaises(producer.MomentumPriceSourcePacketError):
                        producer.run_price_source_packet(
                            candidate_artifact_path=self.paths["candidate"],
                            expected_decision_date=_DECISION_DATE,
                            selected_symbols=["AAPL", "MSFT"],
                            output_source_packet_path=source_packet_path,
                            summary_path=summary_path,
                            raw_root=self.raw_root,
                            client=client,
                            confirm_user_authorization=True,
                            generated_at="2026-06-15T12:00:00+00:00",
                            observed_at="2026-06-15T12:00:00+00:00",
                            massive_sleep_seconds=0,
                        )
                    self.assertFalse(source_packet_path.exists())
                    self.assertFalse(summary_path.exists())
            finally:
                source_packet_path.unlink(missing_ok=True)
                summary_path.unlink(missing_ok=True)

    def test_present_invalid_volume_is_rejected_not_silently_dropped(self):
        producer = importlib.import_module(PRODUCER_MODULE)

        for value in (10**400, math.nan, math.inf, {}, "123", True):
            source_packet_path = self.state_root / f"{self.slug}_vol_{abs(hash(str(value)))}.json"
            summary_path = self.sample_root / "momentum_price_source_packet_20260705" / self.slug / f"vol_{abs(hash(str(value)))}_summary.json"
            client = FakeMassivePriceClient(row_override={"AAPL": {"v": value}})
            try:
                with self.subTest(volume=repr(value)), self._env(), mock.patch.object(
                    producer.sample_validation, "_read_windows_environment_value", return_value=None
                ):
                    with self.assertRaises(producer.MomentumPriceSourcePacketError):
                        producer.run_price_source_packet(
                            candidate_artifact_path=self.paths["candidate"],
                            expected_decision_date=_DECISION_DATE,
                            selected_symbols=["AAPL", "MSFT"],
                            output_source_packet_path=source_packet_path,
                            summary_path=summary_path,
                            raw_root=self.raw_root,
                            client=client,
                            confirm_user_authorization=True,
                            generated_at="2026-06-15T12:00:00+00:00",
                            observed_at="2026-06-15T12:00:00+00:00",
                            massive_sleep_seconds=0,
                        )
                    self.assertFalse(source_packet_path.exists())
                    self.assertFalse(summary_path.exists())
            finally:
                source_packet_path.unlink(missing_ok=True)
                summary_path.unlink(missing_ok=True)

    def test_rejects_benchmark_symbols_as_selected_candidates(self):
        producer = importlib.import_module(PRODUCER_MODULE)
        client = FakeMassivePriceClient()

        with self.assertRaises(producer.MomentumPriceSourcePacketError):
            producer.run_price_source_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["SPY"],
                output_source_packet_path=self.paths["source_packet"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                generated_at="2026-06-15T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                massive_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_summary_schema_rejects_scope_creep_claims(self):
        producer = importlib.import_module(PRODUCER_MODULE)
        summary, _ = self._run_happy()
        schema = _read_json(producer.SUMMARY_SCHEMA_PATH)
        validator = Draft7Validator(schema)

        for path, value in (
            (("scope", "full_market_call_performed"), True),
            (("scope", "datahub_consumption_performed"), True),
            (("price_packet", "corporate_action_reconciliation_performed"), True),
            (("prohibited_claims", "ship_gate_evidence_claimed"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)


if __name__ == "__main__":
    unittest.main()
