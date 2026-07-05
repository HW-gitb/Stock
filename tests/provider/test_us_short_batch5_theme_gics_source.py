from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import unittest
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
from engine.us_short_seam_theme import DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import _DECISION_DATE, _candidate_artifact  # noqa: E402
from tests.provider.test_us_short_batch5_momentum_price_source import _source_packet  # noqa: E402


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_theme_gics_source_20260705"
RUNNER_MODULE = "runners.us_short_batch5_theme_gics_source"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _runner():
    return importlib.import_module(RUNNER_MODULE)


class FakeFmpProfileClient:
    def __init__(self, *, missing_sector_symbol: str | None = None):
        self.urls: list[str] = []
        self.missing_sector_symbol = missing_sector_symbol

    def get_json(self, url: str, *, headers=None, timeout_seconds=30):
        self.urls.append(url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.netloc != "financialmodelingprep.com" or parsed.path != "/stable/profile":
            raise AssertionError(f"unexpected URL: {url}")
        symbol = query["symbol"][0]
        sectors = {"AAPL": "Technology", "MSFT": "Technology", "JPM": "Financial Services"}
        industries = {
            "AAPL": "Consumer Electronics",
            "MSFT": "Software - Infrastructure",
            "JPM": "Banks - Diversified",
        }
        row = {
            "symbol": symbol,
            "companyName": f"{symbol} Inc.",
            "sector": "" if symbol == self.missing_sector_symbol else sectors[symbol],
            "industry": industries[symbol],
            "marketCap": 123456789,
        }
        return [row], 200, True, None


class ThemeGicsSourceTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_theme_gics_source_{os.getpid()}_{self._testMethodName}"
        self.raw_root = SAMPLE_ROOT / self.slug / "raw"
        self.paths = {
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "price_packet": STATE_DIR / f"{self.slug}_price_packet.json",
            "source_packet": STATE_DIR / f"{self.slug}_theme_gics_packet.json",
            "theme_projection": STATE_DIR / f"{self.slug}_theme_projection.json",
            "summary": SAMPLE_ROOT / self.slug / "summary.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))
        _write_json(self.paths["price_packet"], _source_packet(symbols=("AAPL", "MSFT")))

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        root = SAMPLE_ROOT / self.slug
        if root.exists():
            for item in sorted(root.rglob("*"), reverse=True):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            root.rmdir()

    def _env(self):
        runner = _runner()
        return mock.patch.dict(
            runner.sample_validation.os.environ,
            {"FMP_API_KEY": "UNIT_TEST_FMP_SECRET"},
            clear=False,
        )

    def test_runner_and_schemas_are_routed_artifacts(self):
        self.assertIsNotNone(importlib.util.find_spec(RUNNER_MODULE))
        runner = _runner()
        self.assertTrue(runner.PACKET_SCHEMA_PATH.exists())
        self.assertTrue(runner.SUMMARY_SCHEMA_PATH.exists())

    def test_authorized_profile_packet_writes_neutral_projection_without_self_certifying_gics_heat(self):
        runner = _runner()
        client = FakeFmpProfileClient()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_theme_gics_source(
                candidate_artifact_path=self.paths["candidate"],
                price_source_packet_path=self.paths["price_packet"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["aapl", "MSFT"],
                output_source_packet_path=self.paths["source_packet"],
                output_theme_projection_path=self.paths["theme_projection"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                generated_at="2026-06-15T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
            )

        self.assertEqual(len(client.urls), 2)
        self.assertEqual(summary["scope"]["status"], "theme_gics_membership_packet_written")
        self.assertTrue(summary["scope"]["provider_calls_performed"])
        self.assertTrue(summary["scope"]["theme_projection_written"])
        self.assertFalse(summary["scope"]["full_market_call_performed"])
        self.assertEqual(summary["gics_source"]["membership_pool_basis"], "selected_symbols_only_not_full_gics_peer_pool")
        self.assertEqual(summary["projection_contract"]["theme_scored_count"], 0)
        self.assertTrue(summary["projection_contract"]["real_gics_membership_source_consumed"])
        self.assertFalse(summary["projection_contract"]["full_gics_peer_pool_consumed"])

        packet = _read_json(self.paths["source_packet"])
        self.assertEqual(packet["schema_name"], "us_short_batch5_theme_gics_source_packet")
        self.assertEqual(packet["membership_pool"]["selected_symbols"], ["AAPL", "MSFT"])
        self.assertFalse(packet["membership_pool"]["full_gics_peer_pool"])
        self.assertEqual(packet["gics_membership_by_ticker"]["AAPL"]["sector"], "Technology")
        self.assertEqual(packet["gics_membership_by_ticker"]["MSFT"]["industry"], "Software - Infrastructure")

        projection = _read_json(self.paths["theme_projection"])
        self.assertEqual(projection["theme_block_by_ticker"], {})
        self.assertEqual(projection["neutral_fill_tickers"], ["AAPL", "MSFT"])
        self.assertEqual(
            set(projection["coverage"].values()),
            {DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE},
        )
        self.assertEqual(len(list(self.raw_root.rglob("*.json"))), 2)

        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn("UNIT_TEST_FMP_SECRET", text)
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com", text.lower())
        self.assertNotIn('"payload"', text)
        self.assertNotIn('"request_url"', text)

    def test_missing_authorization_aborts_before_fetch_or_write(self):
        runner = _runner()
        client = FakeFmpProfileClient()

        with self.assertRaises(runner.ThemeGicsSourceError):
            runner.run_theme_gics_source(
                candidate_artifact_path=self.paths["candidate"],
                price_source_packet_path=self.paths["price_packet"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL"],
                output_source_packet_path=self.paths["source_packet"],
                output_theme_projection_path=self.paths["theme_projection"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=False,
                generated_at="2026-06-15T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["theme_projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_missing_sector_fails_closed_before_packet_projection_and_summary_write(self):
        runner = _runner()
        client = FakeFmpProfileClient(missing_sector_symbol="AAPL")

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            with self.assertRaises(runner.ThemeGicsSourceError):
                runner.run_theme_gics_source(
                    candidate_artifact_path=self.paths["candidate"],
                    price_source_packet_path=self.paths["price_packet"],
                    expected_decision_date=_DECISION_DATE,
                    selected_symbols=["AAPL", "MSFT"],
                    output_source_packet_path=self.paths["source_packet"],
                    output_theme_projection_path=self.paths["theme_projection"],
                    summary_path=self.paths["summary"],
                    raw_root=self.raw_root,
                    client=client,
                    confirm_user_authorization=True,
                    generated_at="2026-06-15T12:00:00+00:00",
                    observed_at="2026-06-15T12:00:00+00:00",
                )

        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["theme_projection"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_summary_schema_rejects_scope_creep_claims(self):
        runner = _runner()
        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_theme_gics_source(
                candidate_artifact_path=self.paths["candidate"],
                price_source_packet_path=self.paths["price_packet"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL"],
                output_source_packet_path=self.paths["source_packet"],
                output_theme_projection_path=self.paths["theme_projection"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=FakeFmpProfileClient(),
                confirm_user_authorization=True,
                generated_at="2026-06-15T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
            )
        schema = _read_json(runner.SUMMARY_SCHEMA_PATH)
        validator = Draft7Validator(schema)

        for path, value in (
            (("scope", "full_market_call_performed"), True),
            (("scope", "datahub_consumption_performed"), True),
            (("projection_contract", "full_gics_peer_pool_consumed"), True),
            (("prohibited_claims", "ship_gate_evidence_claimed"), True),
            (("prohibited_claims", "production_readiness_claimed"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)

    def test_summary_write_rejects_exact_sensitive_env_value_before_file_write(self):
        runner = _runner()
        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_theme_gics_source(
                candidate_artifact_path=self.paths["candidate"],
                price_source_packet_path=self.paths["price_packet"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL"],
                output_source_packet_path=self.paths["source_packet"],
                output_theme_projection_path=self.paths["theme_projection"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=FakeFmpProfileClient(),
                confirm_user_authorization=True,
                generated_at="2026-06-15T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
            )

        leaking_summary = json.loads(json.dumps(summary))
        leaking_summary["limitations"] = ["UNIT_TEST_FMP_SECRET"]
        leak_path = SAMPLE_ROOT / self.slug / "leaking_summary.json"

        with self.assertRaises(runner.ThemeGicsSourceError):
            runner._write_summary_validated(leaking_summary, leak_path, ["UNIT_TEST_FMP_SECRET"])

        self.assertFalse(leak_path.exists())

    def test_run_rejects_exact_sensitive_summary_value_before_any_output_write(self):
        runner = _runner()
        original_build_summary = runner._build_summary

        def leaking_summary(**kwargs):
            summary = original_build_summary(**kwargs)
            summary["limitations"] = ["UNIT_TEST_FMP_SECRET"]
            return summary

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ), mock.patch.object(runner, "_build_summary", side_effect=leaking_summary):
            with self.assertRaises(runner.ThemeGicsSourceError):
                runner.run_theme_gics_source(
                    candidate_artifact_path=self.paths["candidate"],
                    price_source_packet_path=self.paths["price_packet"],
                    expected_decision_date=_DECISION_DATE,
                    selected_symbols=["AAPL"],
                    output_source_packet_path=self.paths["source_packet"],
                    output_theme_projection_path=self.paths["theme_projection"],
                    summary_path=self.paths["summary"],
                    raw_root=self.raw_root,
                    client=FakeFmpProfileClient(),
                    confirm_user_authorization=True,
                    generated_at="2026-06-15T12:00:00+00:00",
                    observed_at="2026-06-15T12:00:00+00:00",
                )

        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["theme_projection"].exists())
        self.assertFalse(self.paths["summary"].exists())


if __name__ == "__main__":
    unittest.main()
