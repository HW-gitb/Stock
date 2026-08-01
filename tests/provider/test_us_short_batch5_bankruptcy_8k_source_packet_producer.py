from __future__ import annotations

import json
import os
import sys
import unittest
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
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_bankruptcy_8k_source_packet_producer_20260705"
PRODUCER_MODULE = "runners.us_short_batch5_bankruptcy_8k_source_packet_producer"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sec_submissions(*, forms, filing_dates, accessions, items):
    return {
        "filings": {
            "recent": {
                "form": list(forms),
                "filingDate": list(filing_dates),
                "accessionNumber": list(accessions),
                "items": list(items),
            }
        }
    }


class FakeSecClient:
    def __init__(self, *, error_symbol: str | None = None):
        self.urls: list[str] = []
        self.error_symbol = error_symbol

    def get_json(self, url: str, *, headers=None, timeout_seconds=30):
        del headers, timeout_seconds
        self.urls.append(url)
        if url.endswith("/files/company_tickers_exchange.json"):
            return (
                {
                    "fields": ["ticker", "exchange", "cik"],
                    "data": [
                        ["AAPL", "Nasdaq", 320193],
                        ["MSFT", "Nasdaq", 789019],
                        ["JPM", "NYSE", 19617],
                    ],
                },
                200,
                True,
                None,
            )
        if url.endswith("CIK0000320193.json"):
            return (
                _sec_submissions(
                    forms=["8-K", "10-Q"],
                    filing_dates=["2026-06-10", "2026-06-11"],
                    accessions=["0000320193-26-000111", "0000320193-26-000112"],
                    items=["9.01", "2.02"],
                ),
                200,
                True,
                None,
            )
        if url.endswith("CIK0000789019.json"):
            if self.error_symbol == "MSFT":
                return {"error": "unit test"}, 503, False, "http_error"
            return (
                _sec_submissions(
                    forms=["8-K"],
                    filing_dates=["2026-06-10"],
                    accessions=["0000789019-26-000001"],
                    items=["1.03,9.01"],
                ),
                200,
                True,
                None,
            )
        if url.endswith("CIK0000019617.json"):
            return (
                _sec_submissions(
                    forms=["8-K"],
                    filing_dates=["2026-06-10"],
                    accessions=["0000019617-26-000001"],
                    items=["2.02"],
                ),
                200,
                True,
                None,
            )
        return {"unexpected": url}, 404, False, "unexpected_url"


class Bankruptcy8kSourcePacketProducerTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_dir = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_bankruptcy_8k_source_packet_producer_20260705"
        )
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        self.slug = f"test_b8kprod_{os.getpid()}_{self._testMethodName[:24]}"
        self.paths = {
            "candidate": self.state_dir / f"{self.slug}_candidate.json",
            "source_packet": self.state_dir / f"{self.slug}_packet.json",
            "screen": self.state_dir / f"{self.slug}_screen.json",
            "producer_summary": ROOT / "docs" / f"{self.slug}_producer_summary.json",
            "consumer_summary": ROOT / "docs" / f"{self.slug}_consumer_summary.json",
        }
        self.raw_root = self.sample_root / self.slug / "raw"
        for path in self.paths.values():
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM", "LOWADV")))

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)

    def _env(self, producer):
        return mock.patch.dict(
            producer.sample_validation.os.environ,
            {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
            clear=False,
        )

    def _run_happy(self, *, client=None, selected_symbols=None):
        import importlib

        producer = importlib.import_module(PRODUCER_MODULE)
        client = client or FakeSecClient()
        with self._env(producer), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ), mock.patch.object(producer.time, "sleep"):
            summary = producer.run_source_packet_producer(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=selected_symbols or ["AAPL", "MSFT"],
                output_source_packet_path=self.paths["source_packet"],
                output_screen_path=self.paths["screen"],
                summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                generated_at="2026-07-05T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                sec_sleep_seconds=0,
            )
        return summary, client

    def test_authorized_candidate_fetch_writes_source_packet_and_existing_consumer_screen(self):
        summary, client = self._run_happy()

        self.assertEqual(len(client.urls), 3)  # SEC ticker map + 2 company-submissions calls
        self.assertTrue(summary["scope"]["provider_calls_performed"])
        self.assertTrue(summary["scope"]["source_packet_written"])
        self.assertTrue(summary["scope"]["bankruptcy_screen_written_by_consumer"])
        self.assertFalse(summary["scope"]["run_fetch_invoked"])
        self.assertFalse(summary["scope"]["status_records_written"])
        self.assertFalse(summary["scope"]["datahub_consumption_performed"])
        self.assertFalse(summary["scope"]["ship_gate_or_live_normalized_evidence_claimed"])
        self.assertEqual(summary["candidate_scope"]["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 3)
        self.assertEqual(summary["endpoint_call_budget"]["sec_company_submissions_calls"], 2)
        self.assertEqual(summary["source_packet"]["input_symbol_count"], 2)
        self.assertEqual(summary["consumer_screen"]["bankruptcy_8k_positive_count"], 1)

        packet = _read_json(self.paths["source_packet"])
        self.assertEqual(packet["schema_name"], "us_short_batch5_bankruptcy_8k_source_packet")
        self.assertEqual(packet["source_contract"]["input_source"], "provider_fetched_candidate_sec_submissions_source_packet")
        self.assertEqual(set(packet["sec_submissions_by_ticker"]), {"AAPL", "MSFT"})
        screen = _read_json(self.paths["screen"])
        self.assertEqual(screen["by_ticker"]["AAPL"], {"screen_status": "screened_no_filing"})
        self.assertEqual(screen["by_ticker"]["MSFT"]["screen_status"], "bankrupt_8k_found")
        self.assertTrue(self.paths["consumer_summary"].exists())
        consumer_summary = _read_json(self.paths["consumer_summary"])
        self.assertEqual(
            consumer_summary["source_contract"]["input_source"],
            "provider_fetched_candidate_sec_submissions_source_packet",
        )
        self.assertIn("consumer summary covers only", " ".join(consumer_summary["limitations"]))
        self.assertNotIn(
            "No SEC/FMP/Massive provider call",
            " ".join(consumer_summary["limitations"]),
        )
        self.assertEqual(len(list(self.raw_root.rglob("*.json"))), 3)

        text = self.paths["producer_summary"].read_text(encoding="utf-8")
        self.assertNotIn("UnitTest/0.1 contact:test@example.com", text)
        self.assertNotIn("https://", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn("www.sec.gov", text.lower())
        self.assertNotIn("submissions/CIK", text)
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn('"filings"', text)
        self.assertNotIn('"accessionNumber"', text)

    def test_summary_safe_guard_rejects_sec_recent_raw_keys_case_aware(self):
        import importlib

        producer = importlib.import_module(PRODUCER_MODULE)
        for raw_key in ('"accessionNumber"', '"form"', '"filingDate"'):
            with self.subTest(raw_key=raw_key):
                with self.assertRaises(producer.Bankruptcy8kSourcePacketProducerError):
                    producer._assert_summary_safe_text(f"{{{raw_key}: []}}", [])

    def test_summary_safe_guard_allows_form_ticker_but_rejects_raw_form_key(self):
        import importlib

        producer = importlib.import_module(PRODUCER_MODULE)
        producer._assert_summary_safe_text('{"symbol": "FORM"}', [])
        with self.assertRaises(producer.Bankruptcy8kSourcePacketProducerError):
            producer._assert_summary_safe_text('{"form": []}', [])

    def test_requires_authorization_before_fetch_or_write(self):
        import importlib

        producer = importlib.import_module(PRODUCER_MODULE)
        client = FakeSecClient()
        with self.assertRaises(producer.Bankruptcy8kSourcePacketProducerError):
            producer.run_source_packet_producer(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL", "MSFT"],
                output_source_packet_path=self.paths["source_packet"],
                output_screen_path=self.paths["screen"],
                summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=False,
                generated_at="2026-07-05T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["producer_summary"].exists())
        self.assertFalse(self.paths["screen"].exists())

    def test_rejects_ineligible_or_missing_candidate_symbols_before_fetch(self):
        import importlib

        producer = importlib.import_module(PRODUCER_MODULE)
        client = FakeSecClient()
        with self._env(producer), self.assertRaises(producer.Bankruptcy8kSourcePacketProducerError):
            producer.run_source_packet_producer(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["LOWADV"],
                output_source_packet_path=self.paths["source_packet"],
                output_screen_path=self.paths["screen"],
                summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                generated_at="2026-07-05T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                sec_sleep_seconds=0,
            )
        self.assertEqual(client.urls, [])

    def test_endpoint_error_fails_closed_before_packet_summary_or_screen_write(self):
        summary_path = self.paths["producer_summary"]
        client = FakeSecClient(error_symbol="MSFT")
        import importlib

        producer = importlib.import_module(PRODUCER_MODULE)
        with self._env(producer), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ), mock.patch.object(producer.time, "sleep"):
            with self.assertRaises(producer.Bankruptcy8kSourcePacketProducerError):
                producer.run_source_packet_producer(
                    candidate_artifact_path=self.paths["candidate"],
                    expected_decision_date=_DECISION_DATE,
                    selected_symbols=["AAPL", "MSFT"],
                    output_source_packet_path=self.paths["source_packet"],
                    output_screen_path=self.paths["screen"],
                    summary_path=summary_path,
                    consumer_summary_path=self.paths["consumer_summary"],
                    raw_root=self.raw_root,
                    client=client,
                    confirm_user_authorization=True,
                    generated_at="2026-07-05T12:00:00+00:00",
                    observed_at="2026-06-15T12:00:00+00:00",
                    sec_sleep_seconds=0,
                )

        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(summary_path.exists())
        self.assertFalse(self.paths["screen"].exists())
        self.assertFalse(self.paths["consumer_summary"].exists())

    def test_output_source_packet_and_screen_must_be_gitignored_state_json(self):
        import importlib

        producer = importlib.import_module(PRODUCER_MODULE)
        client = FakeSecClient()
        with self._env(producer), self.assertRaises(producer.Bankruptcy8kSourcePacketProducerError):
            producer.run_source_packet_producer(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL", "MSFT"],
                output_source_packet_path=ROOT / "docs" / f"{self.slug}_packet.json",
                output_screen_path=self.paths["screen"],
                summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                generated_at="2026-07-05T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                sec_sleep_seconds=0,
            )
        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["screen"].exists())

    def test_summary_schema_rejects_scope_creep_claims(self):
        import importlib

        producer = importlib.import_module(PRODUCER_MODULE)
        summary, _ = self._run_happy()
        schema = _read_json(producer.SUMMARY_SCHEMA_PATH)
        validator = Draft7Validator(schema)

        for path, value in (
            (("scope", "full_market_scan_performed"), True),
            (("scope", "status_records_written"), True),
            (("scope", "datahub_consumption_performed"), True),
            (("scope", "ship_gate_or_live_normalized_evidence_claimed"), True),
            (("prohibited_claims", "production_ready_claimed"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)


if __name__ == "__main__":
    unittest.main()
