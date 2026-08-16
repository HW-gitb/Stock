from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import _DECISION_DATE, _candidate_artifact  # noqa: E402
from tests.provider.us_short_private_test_root_light import (  # noqa: E402
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)


STATE_DIR = ROOT / "state" / "us_short"
PRODUCER_SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_theme_source_packet_20260705"
CONSUMER_SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_theme_source_20260705"
RUNNER_MODULE = "runners.us_short_batch5_theme_source_packet"

_PRICE_BASIS_YMD = "2026-06-12"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _runner():
    return importlib.import_module(RUNNER_MODULE)


def _dates(n: int) -> list[str]:
    end = datetime.strptime(_PRICE_BASIS_YMD, "%Y-%m-%d").date()
    return [(end - timedelta(days=(n - 1 - idx))).isoformat() for idx in range(n)]


def _massive_payload(*, start: float, step: float, volume_start: float = 1_000_000.0) -> dict:
    results = []
    for idx, date_text in enumerate(_dates(72)):
        dt = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        results.append(
            {
                "t": int(dt.timestamp() * 1000),
                "c": start + (idx * step),
                "v": volume_start + (idx * 1000.0),
            }
        )
    return {"results": results}


def _plan(*, selected=("AAPL", "JPM")) -> dict:
    return {
        "schema_name": "us_short_batch5_theme_source_packet_plan",
        "schema_version": "1.0.0",
        "authorization_ref": "user_chat_20260705_us_short_theme_source_packet",
        "generated_at": "2026-06-15T12:00:00+00:00",
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "purpose": "bounded_full_theme_source_packet_plan",
            "network_access_authorized": True,
            "full_market_download_allowed": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {"expected_decision_date": _DECISION_DATE},
        "selected_symbols": list(selected),
        "industry_peer_symbols_by_selected": {
            "AAPL": ["MSFT", "NVDA"],
            "JPM": ["BAC", "WFC"],
        },
        "provisional_themes_by_id": {
            "AI": ["AAPL", "MSFT", "NVDA"],
            "BANKS": ["JPM", "BAC", "WFC"],
        },
        "source_contract": {
            "symbol_source": "reviewed_local_peer_theme_plan",
            "profile_provider_id": "financial_modeling_prep",
            "price_provider_id": "massive",
            "benchmark_symbols": ["SPY", "QQQ"],
            "session": "RTH",
            "adjustment_mode": "split_adjusted",
            "min_points_per_series": 64,
            "lookback_calendar_days": 140,
            "max_selected_symbols": 3,
            "max_industry_symbols": 8,
            "max_total_endpoint_calls": 18,
            "full_gics_peer_pool": True,
            "provisional_theme_membership_frozen": True,
        },
        "prohibited_claims": {
            "provider_selection_complete": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "live_normalized_evidence": False,
            "ship_gate_evidence": False,
            "production_ready": False,
            "datahub_consumed": False,
        },
    }


class FakeThemeSourceClient:
    def __init__(self):
        self.urls: list[str] = []

    def get_json(self, url: str, *, headers=None, timeout_seconds=30):
        self.urls.append(url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.netloc == "financialmodelingprep.com" and parsed.path == "/stable/profile":
            symbol = query["symbol"][0]
            sectors = {
                "AAPL": "Technology",
                "MSFT": "Technology",
                "NVDA": "Technology",
                "JPM": "Financial Services",
                "BAC": "Financial Services",
                "WFC": "Financial Services",
            }
            industries = {
                "AAPL": "Consumer Electronics",
                "MSFT": "Software - Infrastructure",
                "NVDA": "Semiconductors",
                "JPM": "Banks - Diversified",
                "BAC": "Banks - Diversified",
                "WFC": "Banks - Diversified",
            }
            return [{"symbol": symbol, "sector": sectors[symbol], "industry": industries[symbol], "marketCap": 1}], 200, True, None
        if parsed.netloc == "api.massive.com" and "/v2/aggs/ticker/" in parsed.path:
            parts = parsed.path.split("/")
            symbol = parts[4]
            if symbol in {"AAPL", "MSFT", "NVDA"}:
                return _massive_payload(start=100.0, step=2.0), 200, True, None
            if symbol in {"JPM", "BAC", "WFC"}:
                return _massive_payload(start=200.0, step=-0.75, volume_start=2_000_000.0), 200, True, None
            return _massive_payload(start=100.0, step=0.5, volume_start=5_000_000.0), 200, True, None
        raise AssertionError(f"unexpected URL: {url}")


class ThemeSourcePacketProducerTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_theme_source_packet_20260705"
        )
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        self._consumer_sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_theme_source_20260705"
        )
        self.consumer_sample_root = Path(self._consumer_sample_root_context.__enter__())
        self.addCleanup(self._consumer_sample_root_context.__exit__, None, None, None)
        self.slug = f"test_theme_source_packet_{os.getpid()}_{self._testMethodName}"
        self.raw_root = self.sample_root / "theme_source_packet_20260705" / self.slug / "raw"
        self.paths = {
            "candidate": self.state_root / f"{self.slug}_candidate.json",
            "plan": self.state_root / f"{self.slug}_plan.json",
            "source_packet": self.state_root / f"{self.slug}_theme_source_packet.json",
            "projection": self.state_root / f"{self.slug}_theme_projection.json",
            "producer_summary": self.sample_root / "theme_source_packet_20260705" / self.slug / "summary.json",
            "consumer_summary": self.consumer_sample_root / self.slug / "consumer_summary.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))
        _write_json(self.paths["plan"], _plan())

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)

    def _env(self):
        runner = _runner()
        return mock.patch.dict(
            runner.sample_validation.os.environ,
            {"FMP_API_KEY": "UNIT_TEST_FMP_SECRET", "MASSIVE_API_KEY": "UNIT_TEST_MASSIVE_SECRET"},
            clear=False,
        )

    def test_runner_and_schemas_are_routed_artifacts(self):
        self.assertIsNotNone(importlib.util.find_spec(RUNNER_MODULE))
        runner = _runner()
        self.assertTrue(runner.PLAN_SCHEMA_PATH.exists())
        self.assertTrue(runner.PACKET_SCHEMA_PATH.exists())
        self.assertTrue(runner.SUMMARY_SCHEMA_PATH.exists())

    def test_massive_bad_timestamp_fails_closed_as_domain_error(self):
        runner = _runner()

        for bad_timestamp in (10**30, 1e18, True):
            with self.subTest(bad_timestamp=bad_timestamp):
                record = runner.sample_validation.FetchRecord(
                    provider_id="massive",
                    endpoint_family=runner.PRICE_ENDPOINT_FAMILY,
                    symbol="AAPL",
                    raw_sample_ref="provider_samples/us_short_batch5_theme_source_packet_20260705/raw/aapl.json",
                    ok=True,
                    http_status=200,
                    error_type=None,
                    payload={"results": [{"t": bad_timestamp, "c": 100.0, "v": 1_000_000.0}]},
                )

                with self.assertRaises(runner.ThemeSourcePacketError):
                    runner._series_from_record(record, min_points_per_series=1)

    def test_authorized_full_source_packet_writes_packet_projection_and_no_secret_summary(self):
        runner = _runner()
        client = FakeThemeSourceClient()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_theme_source_packet(
                plan_path=self.paths["plan"],
                candidate_artifact_path=self.paths["candidate"],
                output_source_packet_path=self.paths["source_packet"],
                output_projection_path=self.paths["projection"],
                producer_summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                generated_at="2026-06-15T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                massive_sleep_seconds=0.0,
            )

        self.assertEqual(len(client.urls), 14)
        self.assertEqual(summary["scope"]["status"], "theme_source_packet_written_and_projection_written")
        self.assertTrue(summary["scope"]["provider_calls_performed"])
        self.assertTrue(summary["theme_source_packet"]["full_gics_peer_pool"])
        self.assertEqual(summary["theme_source_packet"]["industry_member_count"], 6)
        self.assertEqual(summary["theme_source_packet"]["theme_count"], 2)
        self.assertEqual(summary["consumer_projection"]["theme_scored_count"], 2)
        self.assertEqual(summary["endpoint_call_budget"]["actual_profile_endpoint_calls"], 6)
        self.assertEqual(summary["endpoint_call_budget"]["actual_price_endpoint_calls"], 8)

        packet = _read_json(self.paths["source_packet"])
        self.assertEqual(packet["schema_name"], "us_short_batch5_theme_source_packet")
        self.assertTrue(packet["scope"]["full_gics_peer_pool"])
        self.assertEqual(set(packet["industry_members_by_ticker"]), {"AAPL", "MSFT", "NVDA", "JPM", "BAC", "WFC"})
        self.assertEqual(set(packet["provisional_themes_by_id"]), {"AI", "BANKS"})
        self.assertEqual(set(packet["benchmark_series_by_ticker"]), {"SPY", "QQQ"})

        projection = _read_json(self.paths["projection"])
        self.assertEqual(projection["target_count"], 2)
        self.assertEqual(projection["scored_count"], 2)
        self.assertGreater(projection["theme_block_by_ticker"]["AAPL"], projection["theme_block_by_ticker"]["JPM"])

        text = self.paths["producer_summary"].read_text(encoding="utf-8")
        self.assertNotIn("UNIT_TEST_FMP_SECRET", text)
        self.assertNotIn("UNIT_TEST_MASSIVE_SECRET", text)
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com", text.lower())
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn('"payload"', text)
        self.assertNotIn('"points"', text)
        self.assertNotIn("Technology", text)
        self.assertNotIn("Financial Services", text)

    def test_missing_authorization_aborts_before_fetch_or_write(self):
        runner = _runner()
        client = FakeThemeSourceClient()

        with self.assertRaises(runner.ThemeSourcePacketError):
            runner.run_theme_source_packet(
                plan_path=self.paths["plan"],
                candidate_artifact_path=self.paths["candidate"],
                output_source_packet_path=self.paths["source_packet"],
                output_projection_path=self.paths["projection"],
                producer_summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=False,
                generated_at="2026-06-15T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                massive_sleep_seconds=0.0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["producer_summary"].exists())

    def test_plan_requires_nonselected_peer_for_every_selected_symbol_before_fetch(self):
        bad = _plan()
        bad["industry_peer_symbols_by_selected"]["AAPL"] = ["AAPL"]
        _write_json(self.paths["plan"], bad)
        runner = _runner()
        client = FakeThemeSourceClient()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            with self.assertRaises(runner.ThemeSourcePacketError):
                runner.run_theme_source_packet(
                    plan_path=self.paths["plan"],
                    candidate_artifact_path=self.paths["candidate"],
                    output_source_packet_path=self.paths["source_packet"],
                    output_projection_path=self.paths["projection"],
                    producer_summary_path=self.paths["producer_summary"],
                    consumer_summary_path=self.paths["consumer_summary"],
                    raw_root=self.raw_root,
                    client=client,
                    confirm_user_authorization=True,
                    generated_at="2026-06-15T12:00:00+00:00",
                    observed_at="2026-06-15T12:00:00+00:00",
                    massive_sleep_seconds=0.0,
                )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["producer_summary"].exists())

    def test_summary_schema_rejects_scope_creep_claims(self):
        runner = _runner()
        client = FakeThemeSourceClient()
        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_theme_source_packet(
                plan_path=self.paths["plan"],
                candidate_artifact_path=self.paths["candidate"],
                output_source_packet_path=self.paths["source_packet"],
                output_projection_path=self.paths["projection"],
                producer_summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                generated_at="2026-06-15T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                massive_sleep_seconds=0.0,
            )
        schema = _read_json(runner.SUMMARY_SCHEMA_PATH)
        validator = Draft7Validator(schema)

        for path, value in (
            (("scope", "full_market_call_performed"), True),
            (("scope", "datahub_consumption_performed"), True),
            (("prohibited_claims", "ship_gate_evidence_claimed"), True),
            (("theme_source_packet", "full_gics_peer_pool"), False),
            (("consumer_projection", "selected_symbol_only_membership_rejected"), False),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)

    def test_run_rejects_exact_sensitive_summary_value_before_state_writes(self):
        runner = _runner()
        original_build_summary = runner._build_summary

        def leaking_summary(**kwargs):
            summary = original_build_summary(**kwargs)
            summary["limitations"] = ["UNIT_TEST_FMP_SECRET"]
            return summary

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ), mock.patch.object(runner, "_build_summary", side_effect=leaking_summary):
            with self.assertRaises(runner.ThemeSourcePacketError):
                runner.run_theme_source_packet(
                    plan_path=self.paths["plan"],
                    candidate_artifact_path=self.paths["candidate"],
                    output_source_packet_path=self.paths["source_packet"],
                    output_projection_path=self.paths["projection"],
                    producer_summary_path=self.paths["producer_summary"],
                    consumer_summary_path=self.paths["consumer_summary"],
                    raw_root=self.raw_root,
                    client=FakeThemeSourceClient(),
                    confirm_user_authorization=True,
                    generated_at="2026-06-15T12:00:00+00:00",
                    observed_at="2026-06-15T12:00:00+00:00",
                    massive_sleep_seconds=0.0,
                )

        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["projection"].exists())
        self.assertFalse(self.paths["producer_summary"].exists())


if __name__ == "__main__":
    unittest.main()
